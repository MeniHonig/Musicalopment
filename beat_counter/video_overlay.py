"""Overlay beat-count numbers and BPM onto video frames using OpenCV."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def _draw_text_with_bg(
    frame: np.ndarray,
    text: str,
    origin: tuple[int, int],
    font_scale: float,
    thickness: int,
    fg_color: tuple[int, int, int],
    bg_color: tuple[int, int, int],
    bg_opacity: float,
) -> np.ndarray:
    """Draw *text* on *frame* with a semi-transparent background rectangle."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    (tw, th), baseline = cv2.getTextSize(text, font, font_scale, thickness)
    x, y = origin
    pad = 10

    overlay = frame.copy()
    cv2.rectangle(
        overlay,
        (x - pad, y - th - pad),
        (x + tw + pad, y + baseline + pad),
        bg_color,
        cv2.FILLED,
    )
    frame = cv2.addWeighted(overlay, bg_opacity, frame, 1 - bg_opacity, 0)
    cv2.putText(frame, text, (x, y), font, font_scale, fg_color, thickness, cv2.LINE_AA)
    return frame


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
) -> Path:
    """
    Read *video_path* frame-by-frame, overlay beat counter + BPM,
    write to *output_path*.

    When *measure_positions* is provided, the overlay shows musical counting
    (e.g. "1  2  3  4") instead of (or alongside) a running total.
    """
    video_path = Path(video_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fourcc = cv2.VideoWriter_fourcc(*codec)
    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))

    # Overlay settings
    counter_font_scale = cfg_overlay.get("counter_font_scale", 2.0)
    measure_font_scale = cfg_overlay.get("measure_font_scale", 1.6)
    bpm_font_scale = cfg_overlay.get("bpm_font_scale", 1.2)
    font_thickness = cfg_overlay.get("font_thickness", 3)
    font_color = tuple(cfg_overlay.get("font_color", [0, 255, 255]))
    bg_color = tuple(cfg_overlay.get("text_bg_color", [0, 0, 0]))
    bg_opacity = cfg_overlay.get("text_bg_opacity", 0.55)
    counter_pos = (cfg_overlay.get("counter_x", 30), cfg_overlay.get("counter_y", 70))
    measure_pos = (cfg_overlay.get("measure_x", 30), cfg_overlay.get("measure_y", 140))
    bpm_pos = (cfg_overlay.get("bpm_x", 30), cfg_overlay.get("bpm_y", 200))
    flash_frames = cfg_overlay.get("flash_frames", 3)
    flash_color = tuple(cfg_overlay.get("flash_color", [0, 255, 0]))
    downbeat_color = tuple(cfg_overlay.get("downbeat_color", [0, 0, 255]))
    show_continuous = cfg_overlay.get("show_continuous_count", True)
    show_measure = cfg_overlay.get("show_measure_count", True)
    show_bar_number = cfg_overlay.get("show_bar_number", False)
    bar_pos = (cfg_overlay.get("bar_x", 30), cfg_overlay.get("bar_y", 260))

    has_measures = measure_positions is not None and len(measure_positions) > 0

    beat_idx = 0
    beat_count = 0
    current_measure_pos = 0
    bar_number = 0
    frames_since_beat = flash_frames + 1
    is_downbeat = False

    frame_num = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        current_time = frame_num / fps

        while beat_idx < len(beat_times) and current_time >= beat_times[beat_idx]:
            beat_count += 1
            if has_measures and beat_idx < len(measure_positions):
                current_measure_pos = int(measure_positions[beat_idx])
                is_downbeat = current_measure_pos == 1
                if is_downbeat:
                    bar_number += 1
            beat_idx += 1
            frames_since_beat = 0

        if frames_since_beat < flash_frames:
            use_color = downbeat_color if is_downbeat else flash_color
        else:
            use_color = font_color

        # --- Draw continuous counter ---
        if show_continuous:
            frame = _draw_text_with_bg(
                frame,
                text=str(beat_count),
                origin=counter_pos,
                font_scale=counter_font_scale,
                thickness=font_thickness,
                fg_color=use_color,
                bg_color=bg_color,
                bg_opacity=bg_opacity,
            )

        # --- Draw measure position (e.g. "1 / 4") ---
        if show_measure and has_measures and beat_count > 0:
            measure_text = f"{current_measure_pos} / {beats_per_measure}"
            frame = _draw_text_with_bg(
                frame,
                text=measure_text,
                origin=measure_pos,
                font_scale=measure_font_scale,
                thickness=font_thickness,
                fg_color=use_color,
                bg_color=bg_color,
                bg_opacity=bg_opacity,
            )

        # --- Draw bar number (optional) ---
        if show_bar_number and has_measures and bar_number > 0:
            bar_text = f"Bar {bar_number}"
            frame = _draw_text_with_bg(
                frame,
                text=bar_text,
                origin=bar_pos,
                font_scale=bpm_font_scale,
                thickness=font_thickness,
                fg_color=font_color,
                bg_color=bg_color,
                bg_opacity=bg_opacity,
            )

        # --- Draw BPM + time signature ---
        ts_label = f"BPM: {bpm:.1f}   {beats_per_measure}/4" if has_measures else f"BPM: {bpm:.1f}"
        frame = _draw_text_with_bg(
            frame,
            text=ts_label,
            origin=bpm_pos,
            font_scale=bpm_font_scale,
            thickness=font_thickness,
            fg_color=font_color,
            bg_color=bg_color,
            bg_opacity=bg_opacity,
        )

        writer.write(frame)
        frame_num += 1
        frames_since_beat += 1

    cap.release()
    writer.release()
    return output_path
