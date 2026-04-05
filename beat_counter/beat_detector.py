"""Detect beats, estimate BPM, and infer time signature from audio using librosa."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import librosa
import numpy as np


@dataclass
class BeatInfo:
    """Result of beat detection on one audio track."""
    bpm: float
    beat_times: np.ndarray        # seconds of every detected beat
    duration: float               # total audio duration in seconds
    beats_per_measure: int = 4    # 4 → 4/4 time, 3 → 3/4 waltz, etc.
    downbeat_indices: np.ndarray = field(default_factory=lambda: np.array([], dtype=int))
    measure_positions: np.ndarray = field(default_factory=lambda: np.array([], dtype=int))
    meter_confidence: float = 0.0
    beat_strengths: np.ndarray = field(default_factory=lambda: np.array([], dtype=float))


def detect_beats(
    audio_path: str | Path,
    sr: int = 22050,
    hop_length: int = 512,
    calibration_seconds: float = 5.0,
    bpm_min: float = 60,
    bpm_max: float = 200,
    time_signature: str = "auto",
) -> BeatInfo:
    """
    Three-phase beat detection:

    1. **Calibration** – estimate a stable tempo from the first N seconds.
    2. **Full-track beat tracking** – use calibrated BPM as a prior.
    3. **Meter detection** – analyse accent pattern to determine if the
       music groups into 3s (waltz) or 4s (common time).

    Parameters
    ----------
    time_signature : "auto", "3/4", "4/4", "3", "4", etc.
        If "auto", the detector picks the best meter.
        Otherwise forces the given beats-per-measure.
    """
    import gc
    audio_path = Path(audio_path)

    # --- Phase 1: calibration window ---
    y_cal, _ = librosa.load(audio_path, sr=sr, duration=calibration_seconds)
    onset_env_cal = librosa.onset.onset_strength(y=y_cal, sr=sr, hop_length=hop_length)
    cal_tempo = librosa.feature.tempo(
        onset_envelope=onset_env_cal,
        sr=sr,
        hop_length=hop_length,
    )
    cal_bpm = float(np.atleast_1d(cal_tempo)[0])
    cal_bpm = np.clip(cal_bpm, bpm_min, bpm_max)
    del y_cal, onset_env_cal
    gc.collect()

    # --- Phase 2: full track with calibrated prior ---
    y_full, _ = librosa.load(audio_path, sr=sr)
    duration = float(len(y_full)) / sr

    onset_env = librosa.onset.onset_strength(y=y_full, sr=sr, hop_length=hop_length)
    del y_full
    gc.collect()
    full_tempo, beat_frames = librosa.beat.beat_track(
        onset_envelope=onset_env,
        sr=sr,
        hop_length=hop_length,
        start_bpm=cal_bpm,
        units="frames",
    )
    final_bpm = float(np.atleast_1d(full_tempo)[0])
    final_bpm = np.clip(final_bpm, bpm_min, bpm_max)

    beat_times = librosa.frames_to_time(beat_frames, sr=sr, hop_length=hop_length)

    # --- Phase 3: meter / time-signature detection ---
    forced_meter = _parse_time_signature(time_signature)

    beat_strengths = onset_env[beat_frames[beat_frames < len(onset_env)]]

    if forced_meter is not None:
        best_meter = forced_meter
        confidence = 1.0
    else:
        best_meter, confidence = _detect_meter(beat_strengths, candidates=[3, 4])

    measure_positions, downbeat_indices = _assign_measure_positions(
        beat_strengths, best_meter
    )

    del onset_env
    gc.collect()

    return BeatInfo(
        bpm=final_bpm,
        beat_times=beat_times,
        duration=duration,
        beats_per_measure=best_meter,
        downbeat_indices=downbeat_indices,
        measure_positions=measure_positions,
        meter_confidence=confidence,
        beat_strengths=beat_strengths,
    )


def _parse_time_signature(ts: str) -> int | None:
    """Return beats-per-measure int, or None for auto."""
    if ts.lower() in ("auto", ""):
        return None
    ts = ts.strip().split("/")[0]
    val = int(ts)
    if val < 2 or val > 12:
        raise ValueError(f"Unsupported beats_per_measure: {val}")
    return val


def _detect_meter(
    beat_strengths: np.ndarray,
    candidates: list[int] | None = None,
) -> tuple[int, float]:
    """
    Score each candidate meter by trying every possible phase offset and
    checking how clearly one position stands out as the accent (the "1").

    For each candidate m and each offset o (0..m-1), we treat beat[o] as
    the first downbeat and measure the ratio of downbeat strength to other
    beat strengths.  The (m, o) combination with the highest ratio wins.

    Returns (best_meter, confidence).
    """
    if candidates is None:
        candidates = [3, 4]

    if len(beat_strengths) < max(candidates) * 2:
        return 4, 0.0

    best_meter = 4
    best_score = -1.0

    for m in candidates:
        for offset in range(m):
            shifted = beat_strengths[offset:]
            usable = (len(shifted) // m) * m
            if usable < m * 2:
                continue
            groups = shifted[:usable].reshape(-1, m)
            pos_means = groups.mean(axis=0)

            downbeat_mean = pos_means[0]
            other_mean = pos_means[1:].mean()

            score = (downbeat_mean / other_mean) if other_mean > 0 else 1.0

            if score > best_score:
                best_score = score
                best_meter = m

    confidence = max(0.0, min(best_score, 5.0))
    return best_meter, confidence


def _assign_measure_positions(
    beat_strengths: np.ndarray,
    beats_per_measure: int,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Assign each beat a position within its measure (1-based: 1,2,3,4,...).

    Tries every possible phase offset (0..m-1), picks the one where the
    "position 1" beats have the highest average onset strength — that
    alignment places the downbeats on the actual accents.

    Returns (measure_positions, downbeat_indices).
    """
    n = len(beat_strengths)
    m = beats_per_measure

    if n == 0:
        return np.array([], dtype=int), np.array([], dtype=int)

    best_offset = 0
    best_score = -1.0
    for offset in range(min(m, n)):
        shifted = beat_strengths[offset:]
        usable = (len(shifted) // m) * m
        if usable < m:
            continue
        groups = shifted[:usable].reshape(-1, m)
        downbeat_mean = groups[:, 0].mean()
        if downbeat_mean > best_score:
            best_score = downbeat_mean
            best_offset = offset

    measure_positions = np.zeros(n, dtype=int)
    for i in range(n):
        measure_positions[i] = ((i - best_offset) % m) + 1

    downbeat_indices = np.where(measure_positions == 1)[0]

    return measure_positions, downbeat_indices


# ------------------------------------------------------------------
#  Tap-anchored meter detection (used by the web UI)
# ------------------------------------------------------------------

def detect_meter_from_tap(
    beat_times: np.ndarray,
    beat_strengths: np.ndarray,
    tap_time: float,
    analysis_window: float = 10.0,
    candidates: list[int] | None = None,
) -> tuple[int, int, float]:
    """
    Given a user tap that marks where "1" approximately falls, snap to the
    nearest detected beat, then analyse the accent pattern with that phase
    locked to determine the meter.

    Parameters
    ----------
    beat_times : array of beat timestamps (seconds).
    beat_strengths : onset strength at each beat.
    tap_time : the timestamp (seconds) the user tapped as the "one".
    analysis_window : how many seconds of beats around the tap to analyse.
    candidates : meters to try, default [3, 4, 5].

    Returns (beats_per_measure, anchor_beat_index, confidence).
    """
    if candidates is None:
        candidates = [3, 4, 5]

    if len(beat_times) == 0:
        return 4, 0, 0.0

    anchor_idx = int(np.argmin(np.abs(beat_times - tap_time)))

    window_start = max(0, anchor_idx - int(analysis_window * 4))
    window_end = min(len(beat_strengths), anchor_idx + int(analysis_window * 4))
    window_strengths = beat_strengths[window_start:window_end]
    anchor_in_window = anchor_idx - window_start

    best_meter = 4
    best_score = -1.0

    for m in candidates:
        if len(window_strengths) < m * 2:
            continue

        offset = anchor_in_window % m
        shifted = window_strengths[offset:]
        usable = (len(shifted) // m) * m
        if usable < m * 2:
            continue

        groups = shifted[:usable].reshape(-1, m)
        pos_means = groups.mean(axis=0)
        downbeat_mean = pos_means[0]
        other_mean = pos_means[1:].mean()
        score = (downbeat_mean / other_mean) if other_mean > 0 else 1.0

        if score > best_score:
            best_score = score
            best_meter = m

    confidence = max(0.0, min(best_score, 5.0))
    return best_meter, anchor_idx, confidence


def assign_positions_from_anchor(
    n_beats: int,
    anchor_idx: int,
    beats_per_measure: int,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Assign measure positions (1-based) to all beats, with beat[anchor_idx]
    locked as position 1.
    """
    m = beats_per_measure
    positions = np.zeros(n_beats, dtype=int)
    for i in range(n_beats):
        positions[i] = ((i - anchor_idx) % m) + 1
    downbeat_indices = np.where(positions == 1)[0]
    return positions, downbeat_indices
