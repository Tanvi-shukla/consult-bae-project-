"""
audio_analysis.py  —  extract acoustic properties from any submitted audio.

For every uploaded/recorded clip we report:
    - duration_sec       (seconds)
    - sample_rate_hz     (Hz, e.g. 44100)
    - bitrate_kbps        (kbps)
    - loudness_dbfs      (RMS level in dBFS; 0 = full scale, more negative = quieter)
    - noise_estimate     (rough quality label: clean / moderate / noisy)

Strategy: browsers record WebM/Opus and users may upload MP3/WAV/M4A. Rather
than depend on a decoder for each codec, we shell out to ffprobe (container
metadata) and ffmpeg (decode to a mono 16-bit WAV we can read with the stdlib
`wave` module + numpy). ffmpeg/ffprobe are ubiquitous and already in the
Docker image / Render buildpack.
"""

import json
import subprocess
import tempfile
import wave
import os
import numpy as np


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def _probe(path):
    """Return the ffprobe format+stream metadata as a dict (or {} on failure)."""
    out = _run([
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", path,
    ])
    if out.returncode != 0:
        return {}
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return {}


def _decode_to_wav(path):
    """Decode any input to a temp mono 16-bit 44.1k WAV. Returns the temp path."""
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    _run(["ffmpeg", "-y", "-i", path, "-ac", "1", "-ar", "44100",
          "-sample_fmt", "s16", tmp.name])
    return tmp.name


def _loudness_and_noise(wav_path):
    """
    Compute RMS loudness in dBFS and a rough noise/quality label.

    Noise heuristic: split the signal into short frames, take the quietest 10%
    of frames as the 'noise floor' and the loudest 10% as 'signal'. A large gap
    between them means clean speech over quiet background; a small gap means the
    whole clip is noisy/hissy. Crude but defensible for a screening estimate.
    """
    with wave.open(wav_path, "rb") as w:
        n = w.getnframes()
        raw = w.readframes(n)
    if n == 0:
        return None, "silent/empty"

    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
    rms = np.sqrt(np.mean(samples ** 2))
    loudness_dbfs = round(20 * np.log10(rms), 1) if rms > 0 else -120.0

    # Frame-based noise-floor vs signal analysis (~30 ms frames at 44.1k).
    frame = 1323
    frames = [samples[i:i + frame] for i in range(0, len(samples), frame)]
    frame_rms = np.array([np.sqrt(np.mean(f ** 2)) for f in frames if len(f)])
    frame_rms = frame_rms[frame_rms > 0]
    if len(frame_rms) < 5:
        return loudness_dbfs, "too short to judge"

    floor = np.percentile(frame_rms, 10)
    signal = np.percentile(frame_rms, 90)
    dyn_db = 20 * np.log10(signal / floor) if floor > 0 else 60.0

    if dyn_db > 30:
        label = "clean"
    elif dyn_db > 15:
        label = "moderate"
    else:
        label = "noisy"
    return loudness_dbfs, f"{label} (~{dyn_db:.0f} dB dynamic range)"


def analyze(path):
    """Return a dict of extracted audio properties for `path`."""
    meta = _probe(path)
    fmt = meta.get("format", {})
    astream = next((s for s in meta.get("streams", [])
                    if s.get("codec_type") == "audio"), {})

    # Duration (prefer stream, fall back to format).
    duration = astream.get("duration") or fmt.get("duration")
    duration = round(float(duration), 2) if duration else None

    sample_rate = astream.get("sample_rate")
    sample_rate = int(sample_rate) if sample_rate else None

    # Bitrate: many WebM/Opus blobs omit a stream bitrate, so derive it from
    # file size / duration when the container doesn't report one.
    bitrate = astream.get("bit_rate") or fmt.get("bit_rate")
    if bitrate:
        bitrate_kbps = round(int(bitrate) / 1000)
    elif duration and duration > 0 and os.path.exists(path):
        bitrate_kbps = round((os.path.getsize(path) * 8) / duration / 1000)
    else:
        bitrate_kbps = None

    # Loudness + noise need decoded PCM.
    loudness_dbfs, noise = None, "unknown"
    wav = None
    try:
        wav = _decode_to_wav(path)
        loudness_dbfs, noise = _loudness_and_noise(wav)
    except Exception as e:  # never let analysis crash a submission
        noise = f"analysis error: {e}"
    finally:
        if wav and os.path.exists(wav):
            os.remove(wav)

    return {
        "duration_sec": duration,
        "sample_rate_hz": sample_rate,
        "bitrate_kbps": bitrate_kbps,
        "loudness_dbfs": loudness_dbfs,
        "noise_estimate": noise,
    }


if __name__ == "__main__":
    import sys
    print(json.dumps(analyze(sys.argv[1]), indent=2))
