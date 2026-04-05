# Musicalopment – Beat Counter

Analyse a dance video, detect the musical beats, and render a new video with a **running beat counter** and **BPM display** overlaid on screen.

## Quick start

```bash
# 1. Clone & enter the repo
cd Musicalopment

# 2. Create / activate the virtual environment
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Make sure ffmpeg is on your PATH
ffmpeg -version

# 5. Drop a video into input/ and run
cp /path/to/dance_video.mp4 input/
python run.py
# — or pass the path directly —
python run.py /path/to/dance_video.mp4
```

The output video will appear in `output/`.

## Configuration

All tuneable settings live in **`config.yaml`**:

| Setting | Default | Description |
|---------|---------|-------------|
| `calibration_seconds` | 5.0 | Seconds used at start to estimate BPM |
| `audio_sample_rate` | 22050 | Sample rate for audio analysis |
| `hop_length` | 512 | Librosa onset-strength hop length |
| `bpm_min` / `bpm_max` | 60 / 200 | Plausible BPM range filter |
| `counter_font_scale` | 2.0 | Size of the beat number |
| `bpm_font_scale` | 1.2 | Size of the BPM label |
| `font_color` | yellow | BGR colour of text |
| `flash_color` | green | Colour flash on each beat |
| `flash_frames` | 3 | How many frames the flash lasts |

See the file for the full list.

## System requirements

* Python 3.10+
* **ffmpeg** must be installed and on `PATH`
  * Ubuntu/Debian: `sudo apt install ffmpeg`
  * macOS: `brew install ffmpeg`

## Open-source dependency audit

| Package | Version | License | Source |
|---------|---------|---------|--------|
| librosa | 0.11.0 | ISC | https://github.com/librosa/librosa |
| opencv-python-headless | 4.13.0 | Apache-2.0 | https://github.com/opencv/opencv-python |
| ffmpeg-python | 0.2.0 | Apache-2.0 | https://github.com/kkroening/ffmpeg-python |
| PyYAML | 6.0.3 | MIT | https://github.com/yaml/pyyaml |
| numpy | 2.2.6 | BSD-3-Clause | https://github.com/numpy/numpy |
| soundfile | 0.13.1 | BSD-3-Clause | https://github.com/bastibe/python-soundfile |
| scipy | 1.15.3 | BSD-3-Clause | https://github.com/scipy/scipy |
| scikit-learn | 1.7.2 | BSD-3-Clause | https://github.com/scikit-learn/scikit-learn |
| numba | 0.65.0 | BSD-2-Clause | https://github.com/numba/numba |

All packages are sourced from PyPI, maintained by reputable open-source organisations, and carry permissive licenses (MIT / BSD / Apache / ISC).

## Roadmap

- [ ] Musical counting (4/4, 3/4 time signatures)
- [ ] Mobile-friendly UI
- [ ] Adaptive BPM (handle tempo changes mid-song)
- [ ] Pose-detection sync (match moves to beats)
