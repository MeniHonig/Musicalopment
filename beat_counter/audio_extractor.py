"""Extract audio track from a video file using ffmpeg."""

from pathlib import Path
import subprocess
import tempfile


def extract_audio(video_path: str | Path, sample_rate: int = 22050) -> Path:
    """
    Extract audio from *video_path* into a temporary WAV file.

    Returns the Path to the WAV file (caller is responsible for cleanup).
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    out_path = Path(tmp.name)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", str(sample_rate),
        "-ac", "1",
        str(out_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg audio extraction failed (exit {result.returncode}):\n{result.stderr}"
        )

    return out_path
