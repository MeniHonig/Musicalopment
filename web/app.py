"""
Musicalopment – Flask Web Backend
=================================
Mobile-friendly API for beat-counting dance videos.

Endpoints
---------
GET  /                  → serves the single-page mobile UI
POST /api/upload        → upload video, run step-1 (beat detection + continuous count)
POST /api/tap-rerender  → receive tap anchor, detect meter, re-render with 1-2-3-4
GET  /api/video/<name>  → serve processed videos
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory, render_template

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import yaml

from beat_counter.audio_extractor import extract_audio
from beat_counter.beat_detector import (
    detect_beats,
    detect_meter_from_tap,
    assign_positions_from_anchor,
)
from beat_counter.video_overlay import render_video_with_beats

app = Flask(
    __name__,
    template_folder=str(Path(__file__).parent / "templates"),
    static_folder=str(Path(__file__).parent / "static"),
)

UPLOAD_DIR = ROOT / "web" / "uploads"
OUTPUT_DIR = ROOT / "web" / "processed"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 MB

CONFIG_PATH = ROOT / "config.yaml"


def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


# In-memory store for job results (keyed by job_id)
_jobs: dict[str, dict] = {}


# ------------------------------------------------------------------
#  Routes
# ------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/upload", methods=["POST"])
def upload_and_process():
    """
    Step 1: Upload video → extract audio → detect beats → render video
    with continuous counting + BPM.  Returns job metadata + beat_times
    so the frontend can do the tap interaction.
    """
    if "video" not in request.files:
        return jsonify(error="No video file in request"), 400

    f = request.files["video"]
    if not f.filename:
        return jsonify(error="Empty filename"), 400

    job_id = uuid.uuid4().hex[:12]
    ext = Path(f.filename).suffix or ".mp4"
    input_path = UPLOAD_DIR / f"{job_id}{ext}"
    f.save(str(input_path))

    cfg = _load_config()
    bd = cfg["beat_detection"]
    ov = cfg["overlay"]
    codec = cfg["output_video"].get("codec", "mp4v")

    try:
        # Extract audio
        wav_path = extract_audio(input_path, sample_rate=bd["audio_sample_rate"])

        # Detect beats (continuous, no meter yet)
        info = detect_beats(
            wav_path,
            sr=bd["audio_sample_rate"],
            hop_length=bd["hop_length"],
            calibration_seconds=bd["calibration_seconds"],
            bpm_min=bd["bpm_min"],
            bpm_max=bd["bpm_max"],
            time_signature="auto",
        )

        # Render step-1 video (continuous count + BPM only)
        step1_name = f"{job_id}_step1.mp4"
        step1_path = OUTPUT_DIR / step1_name
        ov_step1 = {**ov, "show_measure_count": False, "show_continuous_count": True}

        render_video_with_beats(
            input_path, step1_path, info.beat_times, info.bpm,
            ov_step1, codec,
            measure_positions=info.measure_positions,
            beats_per_measure=info.beats_per_measure,
        )

        # Mux audio back into step-1 video
        _mux_audio(input_path, step1_path)

        # Clean up wav
        try:
            os.unlink(wav_path)
        except OSError:
            pass

        _jobs[job_id] = {
            "input_path": str(input_path),
            "beat_times": [float(t) for t in info.beat_times],
            "beat_strengths": [float(s) for s in info.beat_strengths],
            "bpm": float(info.bpm),
            "duration": float(info.duration),
            "auto_meter": int(info.beats_per_measure),
            "auto_confidence": float(info.meter_confidence),
            "step1_video": step1_name,
        }

        return jsonify(
            job_id=job_id,
            bpm=round(float(info.bpm), 1),
            total_beats=len(info.beat_times),
            duration=round(float(info.duration), 1),
            beat_times=[float(t) for t in info.beat_times],
            auto_meter=int(info.beats_per_measure),
            auto_confidence=round(float(info.meter_confidence), 2),
            step1_video=f"/api/video/{step1_name}",
        )

    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route("/api/tap-rerender", methods=["POST"])
def tap_rerender():
    """
    Step 2: User tapped the "one" at a given timestamp.
    Detect meter from that anchor point, then re-render the full video
    with proper 1-2-3-4 counting.
    """
    data = request.get_json()
    if not data:
        return jsonify(error="No JSON body"), 400

    job_id = data.get("job_id")
    tap_time = data.get("tap_time")
    analysis_window = data.get("analysis_window", 10.0)

    if not job_id or tap_time is None:
        return jsonify(error="Missing job_id or tap_time"), 400

    job = _jobs.get(job_id)
    if not job:
        return jsonify(error="Job not found — upload a video first"), 404

    beat_times = np.array(job["beat_times"])
    beat_strengths = np.array(job["beat_strengths"])
    bpm = job["bpm"]
    input_path = Path(job["input_path"])

    cfg = _load_config()
    ov = cfg["overlay"]
    codec = cfg["output_video"].get("codec", "mp4v")

    # Detect meter using the tap anchor
    meter, anchor_idx, confidence = detect_meter_from_tap(
        beat_times, beat_strengths, float(tap_time),
        analysis_window=float(analysis_window),
        candidates=[3, 4, 5],
    )

    # Assign measure positions locked to the anchor
    positions, downbeat_indices = assign_positions_from_anchor(
        len(beat_times), anchor_idx, meter
    )

    # Render final video with full measure counting
    final_name = f"{job_id}_final.mp4"
    final_path = OUTPUT_DIR / final_name

    render_video_with_beats(
        input_path, final_path, beat_times, bpm, ov, codec,
        measure_positions=positions,
        beats_per_measure=meter,
    )

    _mux_audio(input_path, final_path)

    return jsonify(
        job_id=job_id,
        detected_meter=meter,
        anchor_beat_index=int(anchor_idx),
        anchor_beat_time=round(float(beat_times[anchor_idx]), 3),
        confidence=round(confidence, 2),
        total_measures=int(len(downbeat_indices)),
        final_video=f"/api/video/{final_name}",
    )


@app.route("/api/video/<filename>")
def serve_video(filename):
    return send_from_directory(str(OUTPUT_DIR), filename)


# ------------------------------------------------------------------
#  Audio mux helper
# ------------------------------------------------------------------

def _mux_audio(original: Path, overlay: Path) -> None:
    import subprocess
    tmp = overlay.with_suffix(".tmp" + overlay.suffix)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(overlay), "-i", str(original),
        "-c:v", "copy", "-c:a", "aac",
        "-map", "0:v:0", "-map", "1:a:0",
        "-shortest", str(tmp),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        overlay.unlink()
        tmp.rename(overlay)
    elif tmp.exists():
        tmp.unlink()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
