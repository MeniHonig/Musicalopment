#!/usr/bin/env python3
"""
Musicalopment – Beat Counter Pipeline
======================================
Reads a dance video, detects musical beats, and renders a new video with
a running beat count and BPM display overlaid on screen.

Usage (CLI)
-----------
    python run.py                          # process first video found in input/
    python run.py path/to/video.mp4        # process a specific file
    python run.py --config my_config.yaml  # use alternate config

Usage (Notebook / Python)
-------------------------
    from run import process_video, print_report, show_sample_frame

    result = process_video("input/dance.mp4")
    print_report(result)
    show_sample_frame(result)
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import yaml

from beat_counter.audio_extractor import extract_audio
from beat_counter.beat_detector import detect_beats, BeatInfo
from beat_counter.video_overlay import render_video_with_beats

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config.yaml"


# ------------------------------------------------------------------
#  Data returned by process_video()
# ------------------------------------------------------------------
@dataclass
class PipelineResult:
    video_path: Path
    output_path: Path
    beat_info: BeatInfo
    config: dict
    timings: dict = field(default_factory=dict)


# ------------------------------------------------------------------
#  Public API — used by the notebook and CLI
# ------------------------------------------------------------------

def load_config(config_path: str | Path = DEFAULT_CONFIG) -> dict:
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")
    with open(config_path) as f:
        return yaml.safe_load(f)


def process_video(
    video_path: str | Path,
    config_path: str | Path = DEFAULT_CONFIG,
) -> PipelineResult:
    """
    Run the full beat-counter pipeline on *video_path*.

    Returns a PipelineResult with all data needed for reporting.
    """
    video_path = Path(video_path).resolve()
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    cfg = load_config(config_path)
    bd = cfg["beat_detection"]
    ov = cfg["overlay"]
    codec = cfg["output_video"].get("codec", "mp4v")
    suffix = cfg["output_video"].get("suffix", "_beat_counted")

    out_dir = ROOT / cfg["paths"]["output_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / f"{video_path.stem}{suffix}{video_path.suffix}"

    timings: dict[str, float] = {}

    # Step 1 — extract audio
    print(f"[1/3] Extracting audio from {video_path.name} …")
    t0 = time.time()
    wav_path = extract_audio(video_path, sample_rate=bd["audio_sample_rate"])
    timings["audio_extract"] = time.time() - t0
    print(f"      Done ({timings['audio_extract']:.1f}s)")

    # Step 2 — detect beats + time signature
    ts_setting = bd.get("time_signature", "auto")
    print(f"[2/3] Detecting beats (calibration = {bd['calibration_seconds']}s, meter = {ts_setting}) …")
    t0 = time.time()
    info = detect_beats(
        wav_path,
        sr=bd["audio_sample_rate"],
        hop_length=bd["hop_length"],
        calibration_seconds=bd["calibration_seconds"],
        bpm_min=bd["bpm_min"],
        bpm_max=bd["bpm_max"],
        time_signature=ts_setting,
    )
    timings["beat_detect"] = time.time() - t0
    meter_label = f"{info.beats_per_measure}/4"
    conf_label = f"confidence={info.meter_confidence:.2f}" if ts_setting == "auto" else "forced"
    print(f"      BPM: {info.bpm:.1f}  |  Meter: {meter_label} ({conf_label})")
    print(f"      Beats: {len(info.beat_times)}  |  Measures: {len(info.downbeat_indices)}  |  Duration: {info.duration:.1f}s")
    print(f"      Done ({timings['beat_detect']:.1f}s)")

    # Step 3 — render overlay video
    print(f"[3/3] Rendering overlay → {output_path.name} …")
    t0 = time.time()
    render_video_with_beats(
        video_path, output_path, info.beat_times, info.bpm, ov, codec,
        measure_positions=info.measure_positions,
        beats_per_measure=info.beats_per_measure,
    )
    timings["video_render"] = time.time() - t0
    print(f"      Done ({timings['video_render']:.1f}s)")

    # Cleanup temp WAV
    try:
        os.unlink(wav_path)
    except OSError:
        pass

    print(f"\n✓ Output saved to: {output_path}")

    return PipelineResult(
        video_path=video_path,
        output_path=output_path,
        beat_info=info,
        config=cfg,
        timings=timings,
    )


def print_report(result: PipelineResult) -> None:
    """Print a formatted summary of the pipeline run."""
    info = result.beat_info
    t = result.timings
    bd = result.config["beat_detection"]

    avg_interval = float(np.mean(np.diff(info.beat_times))) if len(info.beat_times) > 1 else 0
    bpm_from_intervals = (1 / avg_interval) * 60 if avg_interval > 0 else 0
    file_size_mb = result.output_path.stat().st_size / (1024 * 1024)
    total_time = sum(t.values())
    ts_mode = bd.get("time_signature", "auto")

    print(f"""
{'='*50}
  BEAT COUNTER — REPORT
{'='*50}

  Input video      : {result.video_path.name}
  Output video     : {result.output_path}
  Output size      : {file_size_mb:.2f} MB

  Duration         : {info.duration:.1f} s
  Detected BPM     : {info.bpm:.1f}
  Time signature   : {info.beats_per_measure}/4  (mode: {ts_mode}, confidence: {info.meter_confidence:.2f})
  Total beats      : {len(info.beat_times)}
  Total measures   : {len(info.downbeat_indices)}
  Avg beat interval: {avg_interval:.3f} s  ({bpm_from_intervals:.1f} BPM)
  Calibration used : {bd['calibration_seconds']} s

  Processing time
    Audio extract  : {t.get('audio_extract', 0):.1f} s
    Beat detection : {t.get('beat_detect', 0):.1f} s
    Video render   : {t.get('video_render', 0):.1f} s
    Total          : {total_time:.1f} s

  First 10 beat timestamps (seconds):
    {np.array2string(info.beat_times[:10], precision=2, separator=', ')}

  First 10 measure positions:
    {info.measure_positions[:10]}
{'='*50}
""")


def show_sample_frame(result: PipelineResult, at_second: float = 3.0) -> None:
    """Display a frame from the output video (works in Jupyter / VS Code notebooks)."""
    from IPython.display import display, Image as IPImage

    cap = cv2.VideoCapture(str(result.output_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    target = min(int(fps * at_second), total_frames - 1)
    cap.set(cv2.CAP_PROP_POS_FRAMES, target)
    ret, frame = cap.read()
    cap.release()

    if not ret:
        print("Could not read sample frame.")
        return

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    cv2.imwrite(tmp.name, frame)
    print(f"Frame #{target} (~{target / fps:.1f}s into the video):")
    display(IPImage(filename=tmp.name))
    os.unlink(tmp.name)


# ------------------------------------------------------------------
#  CLI helpers
# ------------------------------------------------------------------

def _find_input_video(cfg: dict, explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit)
        if not p.exists():
            sys.exit(f"Error: video not found – {p}")
        return p

    input_dir = ROOT / cfg["paths"]["input_dir"]
    video_exts = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
    for f in sorted(input_dir.iterdir()):
        if f.suffix.lower() in video_exts:
            return f

    sys.exit(
        f"Error: no video files found in {input_dir}/\n"
        "Place a video there or pass one as an argument."
    )



def main() -> None:
    parser = argparse.ArgumentParser(description="Beat-count overlay for dance videos")
    parser.add_argument("video", nargs="?", help="Path to input video (optional)")
    parser.add_argument(
        "--config", "-c",
        default=str(DEFAULT_CONFIG),
        help="Path to YAML config file",
    )
    args = parser.parse_args()

    cfg = load_config(Path(args.config))
    video_path = _find_input_video(cfg, args.video)

    result = process_video(video_path, args.config)
    print_report(result)


if __name__ == "__main__":
    main()
