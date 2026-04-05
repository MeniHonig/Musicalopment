"""Overlay beat-count numbers and BPM using FFmpeg drawtext filters.

Single-pass native FFmpeg processing — vastly faster than frame-by-frame
Python/OpenCV.  Audio is copied in the same pass (no separate mux step).
"""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

import numpy as np


def render_video_with_beats(
    video_path: str | Path,
    output_path: str | Path,
    beat_times: np.ndarray,
    bpm: float,
    cfg_overlay: dict,
    codec: str = "mp4v",
    measure_positions: np.ndarray | None = None,
    beats_per_measure: int = 4,
    bar_start_idx: int | None = None,
    progress_callback=None,
) -> Path:
    """Render beat overlay onto *video_path* via FFmpeg drawtext (one pass).

    Audio is copied directly — no separate mux step.
    *progress_callback(pct)* receives 0-100.
    """
    video_path = Path(video_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    duration = _probe_duration(video_path)
    fontfile = _find_font()

    font_color = _bgr_to_hex(cfg_overlay.get("font_color", [0, 255, 255]))
    downbeat_clr = _bgr_to_hex(cfg_overlay.get("downbeat_color", [0, 0, 255]))
    bg = cfg_overlay.get("text_bg_color", [0, 0, 0])
    bg_op = cfg_overlay.get("text_bg_opacity", 0.55)
    boxcolor = f"0x{bg[2]:02x}{bg[1]:02x}{bg[0]:02x}@{bg_op}"

    counter_fs = max(20, int(cfg_overlay.get("counter_font_scale", 2.0) * 30))
    measure_fs = max(16, int(cfg_overlay.get("measure_font_scale", 1.6) * 30))
    bpm_fs = max(14, int(cfg_overlay.get("bpm_font_scale", 1.2) * 30))

    cx, cy = cfg_overlay.get("counter_x", 30), cfg_overlay.get("counter_y", 70)
    mx, my = cfg_overlay.get("measure_x", 30), cfg_overlay.get("measure_y", 140)
    bpx, bpy = cfg_overlay.get("bpm_x", 30), cfg_overlay.get("bpm_y", 200)
    brx, bry = cfg_overlay.get("bar_x", 30), cfg_overlay.get("bar_y", 260)

    show_cont = cfg_overlay.get("show_continuous_count", True)
    show_meas = cfg_overlay.get("show_measure_count", True)
    show_bars = cfg_overlay.get("show_bar_number", False)
    has_meas = measure_positions is not None and len(measure_positions) > 0

    # ---- build drawtext filter chain ----
    parts: list[str] = []

    bpm_label = f"BPM: {bpm:.1f}   {beats_per_measure}/4" if has_meas else f"BPM: {bpm:.1f}"
    parts.append(_dt(bpm_label, bpx, bpy, bpm_fs, font_color, boxcolor,
                     0, duration, fontfile))

    bar_num = 0
    for i, bt in enumerate(beat_times):
        t0 = float(bt)
        t1 = float(beat_times[i + 1]) if i + 1 < len(beat_times) else duration

        is_down = has_meas and int(measure_positions[i]) == 1
        if is_down:
            bar_num += 1
        clr = downbeat_clr if is_down else font_color

        if show_cont:
            parts.append(_dt(str(i + 1), cx, cy, counter_fs, clr, boxcolor,
                             t0, t1, fontfile))
        if show_meas and has_meas:
            parts.append(_dt(f"{int(measure_positions[i])} / {beats_per_measure}",
                             mx, my, measure_fs, clr, boxcolor, t0, t1, fontfile))
        if show_bars and has_meas and bar_num > 0:
            parts.append(_dt(f"Bar {bar_num}", brx, bry, bpm_fs,
                             font_color, boxcolor, t0, t1, fontfile))

    vf = ",\n".join(parts)
    script = output_path.with_suffix(".filtscript")
    script.write_text(vf)

    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-filter_script:v", str(script),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "copy", "-movflags", "+faststart",
        "-progress", "pipe:1",
        str(output_path),
    ]

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )

    stderr_buf: list[str] = []
    drain = threading.Thread(
        target=lambda: stderr_buf.extend(proc.stderr), daemon=True,
    )
    drain.start()

    for line in proc.stdout:
        if progress_callback and line.startswith("out_time="):
            try:
                secs = _parse_ffmpeg_time(line.split("=", 1)[1].strip())
                if secs >= 0:
                    progress_callback(min(99, int(100 * secs / duration)))
            except Exception:
                pass

    proc.wait()
    drain.join(timeout=3)
    script.unlink(missing_ok=True)

    if proc.returncode != 0:
        tail = "".join(stderr_buf[-30:]) if stderr_buf else "unknown error"
        raise RuntimeError(f"FFmpeg render failed:\n{tail}")

    if progress_callback:
        progress_callback(100)
    return output_path


# ---- helpers --------------------------------------------------------

def _dt(text, x, y, fontsize, fontcolor, boxcolor, t_start, t_end, fontfile):
    """Build one ``drawtext`` filter entry.

    Uses unquoted text values with escaped colons and backslashes,
    and quoted ``enable`` expressions so commas in ``between()`` are
    treated as literals.
    """
    esc = (
        text
        .replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
    )
    ff = f":fontfile={fontfile}" if fontfile else ""
    return (
        f"drawtext=text='{esc}':x={x}:y={y}:fontsize={fontsize}"
        f":fontcolor={fontcolor}{ff}"
        f":box=1:boxcolor={boxcolor}:boxborderw=8"
        f":enable='between(t,{t_start:.3f},{t_end:.3f})'"
    )


def _bgr_to_hex(bgr: list[int]) -> str:
    """[B,G,R] (OpenCV / config order) → FFmpeg ``0xRRGGBB``."""
    return f"0x{bgr[2]:02x}{bgr[1]:02x}{bgr[0]:02x}"


def _find_font() -> str | None:
    """Return path to a usable TTF font, or *None*."""
    for p in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ):
        if Path(p).exists():
            return p
    return None


def _probe_duration(path: Path) -> float:
    """Video duration in seconds via ``ffprobe``."""
    r = subprocess.run(
        ["ffprobe", "-v", "quiet",
         "-show_entries", "format=duration", "-of", "json",
         str(path)],
        capture_output=True, text=True,
    )
    return float(json.loads(r.stdout)["format"]["duration"])


def _parse_ffmpeg_time(s: str) -> float:
    """Parse ``HH:MM:SS.micro`` → seconds."""
    parts = s.split(":")
    if len(parts) != 3:
        return -1
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
