"""
Musicalopment – Flask Web Backend (simplified)
===============================================
Step 1: Upload → detect BPM + beat positions → render continuous-count video
Step 2: User picks meter (3/4, 4/4, 5/4) + taps the "ONE" →
        pure math to assign measure positions → re-render with 1-2-3-4
"""

from __future__ import annotations

import gc
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory, render_template

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import yaml

from beat_counter.audio_extractor import extract_audio
from beat_counter.beat_detector import detect_beats
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

app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024

CONFIG_PATH = ROOT / "config.yaml"

_jobs: dict[str, dict] = {}


def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


# ------------------------------------------------------------------
#  Routes
# ------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/upload", methods=["POST"])
def upload_and_process():
    """
    Step 1: Upload video → detect beats + BPM → render video with
    continuous counting only.  Returns beat_times so step 2 is pure math.
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
        wav_path = extract_audio(input_path, sample_rate=bd["audio_sample_rate"])

        info = detect_beats(
            wav_path,
            sr=bd["audio_sample_rate"],
            hop_length=bd["hop_length"],
            calibration_seconds=bd["calibration_seconds"],
            bpm_min=bd["bpm_min"],
            bpm_max=bd["bpm_max"],
            time_signature="4",  # doesn't matter, we only use beat_times + bpm
        )

        # Render step-1 video: continuous count + BPM only
        step1_name = f"{job_id}_step1.mp4"
        step1_path = OUTPUT_DIR / step1_name
        ov_step1 = {**ov, "show_measure_count": False, "show_continuous_count": True}

        render_video_with_beats(
            input_path, step1_path, info.beat_times, info.bpm,
            ov_step1, codec,
        )
        _mux_audio(input_path, step1_path)

        try:
            os.unlink(wav_path)
        except OSError:
            pass
        gc.collect()

        _jobs[job_id] = {
            "input_path": str(input_path),
            "beat_times": [float(t) for t in info.beat_times],
            "bpm": float(info.bpm),
            "duration": float(info.duration),
            "step1_video": step1_name,
        }

        return jsonify(
            job_id=job_id,
            bpm=round(float(info.bpm), 1),
            total_beats=len(info.beat_times),
            duration=round(float(info.duration), 1),
            beat_times=[float(t) for t in info.beat_times],
            step1_video=f"/api/video/{step1_name}",
        )

    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route("/api/rerender", methods=["POST"])
def rerender():
    """
    Step 2: User chose meter + tapped the "ONE".
    Pure math: snap tap to nearest beat, assign 1-2-3-4 cyclically,
    then re-render the video overlay.
    """
    data = request.get_json()
    if not data:
        return jsonify(error="No JSON body"), 400

    job_id = data.get("job_id")
    tap_time = data.get("tap_time")
    meter = int(data.get("meter", 4))
    show_bars = bool(data.get("show_bars", False))

    if not job_id or tap_time is None:
        return jsonify(error="Missing job_id or tap_time"), 400

    job = _jobs.get(job_id)
    if not job:
        return jsonify(error="Job not found — upload a video first"), 404

    beat_times = np.array(job["beat_times"])
    bpm = job["bpm"]
    input_path = Path(job["input_path"])

    cfg = _load_config()
    ov = cfg["overlay"]
    codec = cfg["output_video"].get("codec", "mp4v")

    # Snap tap to nearest beat
    anchor_idx = int(np.argmin(np.abs(beat_times - float(tap_time))))

    # Pure math: assign 1-based positions cyclically from the anchor
    n = len(beat_times)
    positions = np.zeros(n, dtype=int)
    for i in range(n):
        positions[i] = ((i - anchor_idx) % meter) + 1

    # Render final video
    final_name = f"{job_id}_final.mp4"
    final_path = OUTPUT_DIR / final_name

    ov_final = {
        **ov,
        "show_continuous_count": True,
        "show_measure_count": True,
        "show_bar_number": show_bars,
    }

    render_video_with_beats(
        input_path, final_path, beat_times, bpm, ov_final, codec,
        measure_positions=positions,
        beats_per_measure=meter,
        bar_start_idx=anchor_idx if show_bars else None,
    )
    _mux_audio(input_path, final_path)
    gc.collect()

    total_bars = int(np.sum(positions == 1))

    return jsonify(
        job_id=job_id,
        meter=meter,
        anchor_beat_time=round(float(beat_times[anchor_idx]), 3),
        total_bars=total_bars,
        show_bars=show_bars,
        final_video=f"/api/video/{final_name}",
    )


@app.route("/api/video/<filename>")
def serve_video(filename):
    return send_from_directory(str(OUTPUT_DIR), filename)


def _mux_audio(original: Path, overlay: Path) -> None:
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
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
