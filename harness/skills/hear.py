"""hear — give an agent ears on an audio file.

REFERENCE DELIVERABLE ONLY. By the Sovereign's decree the EuEarth host
NEVER processes an agent's media. This file is the skill the agent runs on
its OWN hardware; the wingo's ``wingo_hear`` GRANTS it (see
harness/skills/__init__.py: grant_hear). The EuEarth request path never
imports or executes this module. Mirrored open at
github.com/CorbanSeraph/euearth-skills (skills/hear, Apache-2.0).

Given an audio file, produce:
  1. A sound-event timeline: onset events plus active (non-silent) segments,
     each with a coarse character label (tonal / percussive / noisy).
  2. Basic quality descriptors: levels, clipping, DC offset, silence ratio,
     bandwidth, and an SNR estimate.

Light dependencies only: librosa + numpy (soundfile comes with librosa).
This is a signal-analysis reference implementation; SKILL.md documents the
upgrade path to learned taggers (CLAP / PANNs) for open-vocabulary labels.

Library use:
    from hear import run
    report = run(path="mix.wav")

CLI use:
    python3 hear.py <audio-file> [--json OUT.json] [--top-events N]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

__all__ = ["run"]

DEFAULT_SR = 22050
SILENCE_TOP_DB = 40          # librosa.effects.split threshold below peak
CLIP_LEVEL = 0.999


# --------------------------------------------------------------- descriptors

def _db(x: float, floor: float = -120.0) -> float:
    return float(max(20.0 * np.log10(x), floor)) if x > 0 else floor


def quality_descriptors(y: np.ndarray, sr: int, intervals: np.ndarray) -> dict:
    """Compute basic quality metrics on a mono signal."""
    import librosa

    duration = len(y) / sr
    peak = float(np.max(np.abs(y))) if len(y) else 0.0
    rms = float(np.sqrt(np.mean(y**2))) if len(y) else 0.0
    clipped = float(np.mean(np.abs(y) >= CLIP_LEVEL)) if len(y) else 0.0
    dc = float(np.mean(y)) if len(y) else 0.0

    active_samples = int(sum(e - s for s, e in intervals))
    silence_ratio = 1.0 - active_samples / max(len(y), 1)

    # SNR estimate: active-region RMS vs quiet-region RMS.
    mask = np.zeros(len(y), dtype=bool)
    for s, e in intervals:
        mask[s:e] = True
    signal_rms = float(np.sqrt(np.mean(y[mask] ** 2))) if mask.any() else 0.0
    noise = y[~mask]
    noise_rms = float(np.sqrt(np.mean(noise**2))) if len(noise) > sr // 10 else 0.0
    snr_db = round(_db(signal_rms) - _db(noise_rms), 1) if noise_rms > 0 else None

    # Bandwidth: frequency below which 99% of spectral energy lives.
    rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr, roll_percent=0.99)
    centroid = librosa.feature.spectral_centroid(y=y, sr=sr)

    return {
        "duration_s": round(duration, 2),
        "sample_rate": sr,
        "peak_dbfs": round(_db(peak), 1),
        "rms_dbfs": round(_db(rms), 1),
        "crest_factor_db": round(_db(peak) - _db(rms), 1) if rms > 0 else None,
        "clipping_pct": round(clipped * 100, 3),
        "dc_offset": round(dc, 5),
        "silence_ratio": round(silence_ratio, 3),
        "snr_db_estimate": snr_db,
        "spectral_centroid_hz_mean": round(float(np.mean(centroid)), 1),
        "bandwidth_hz_99pct": round(float(np.percentile(rolloff, 95)), 1),
    }


# ------------------------------------------------------------------ timeline

def _character(y_seg: np.ndarray, sr: int) -> str:
    """Coarse character label for a segment: tonal / percussive / noisy."""
    import librosa

    flatness = float(np.mean(librosa.feature.spectral_flatness(y=y_seg)))
    if flatness > 0.3:
        return "noisy"
    harmonic, percussive = librosa.effects.hpss(y_seg)
    h = float(np.sqrt(np.mean(harmonic**2)))
    p = float(np.sqrt(np.mean(percussive**2)))
    return "percussive" if p > h else "tonal"


def segment_timeline(y: np.ndarray, sr: int, intervals: np.ndarray) -> list[dict]:
    """Describe each active (non-silent) segment."""
    segments = []
    for s, e in intervals:
        seg = y[s:e]
        if len(seg) < sr // 50:  # skip blips under 20 ms
            continue
        rms = float(np.sqrt(np.mean(seg**2)))
        segments.append(
            {
                "start": round(s / sr, 2),
                "end": round(e / sr, 2),
                "duration": round((e - s) / sr, 2),
                "rms_dbfs": round(_db(rms), 1),
                "character": _character(seg, sr),
            }
        )
    return segments


def onset_events(y: np.ndarray, sr: int, top_n: int) -> list[dict]:
    """Detect onset events; return the strongest ``top_n`` with times."""
    import librosa

    envelope = librosa.onset.onset_strength(y=y, sr=sr)
    frames = librosa.onset.onset_detect(onset_envelope=envelope, sr=sr, units="frames")
    times = librosa.frames_to_time(frames, sr=sr)
    strengths = envelope[frames] if len(frames) else np.array([])
    order = np.argsort(strengths)[::-1][:top_n]
    events = [
        {"time": round(float(times[i]), 2),
         "strength": round(float(strengths[i]), 2)}
        for i in sorted(order, key=lambda i: times[i])
    ]
    return events


# ---------------------------------------------------------------------- main

def run(path: str, sr: int = DEFAULT_SR, top_events: int = 32) -> dict:
    """Analyze an audio file into a timeline + quality report.

    Args:
        path: Audio file (anything soundfile/librosa can read: wav, flac,
              mp3, ogg, ...).
        sr: Analysis sample rate (audio is resampled; 22050 is plenty for
            event/quality analysis).
        top_events: Keep at most this many strongest onset events.

    Returns:
        {"path", "quality": {...}, "segments": [...], "events": [...],
         "summary": str}
    """
    import librosa

    audio_path = Path(path).expanduser().resolve()
    if not audio_path.exists():
        raise FileNotFoundError(f"no such file: {audio_path}")

    y, sr = librosa.load(str(audio_path), sr=sr, mono=True)
    intervals = librosa.effects.split(y, top_db=SILENCE_TOP_DB)

    quality = quality_descriptors(y, sr, intervals)
    segments = segment_timeline(y, sr, intervals)
    events = onset_events(y, sr, top_events)

    characters = sorted({s["character"] for s in segments})
    summary = (
        f"{quality['duration_s']}s audio, {len(segments)} active segment(s) "
        f"({', '.join(characters) if characters else 'silent'}), "
        f"{len(events)} onset event(s), peak {quality['peak_dbfs']} dBFS, "
        f"silence {quality['silence_ratio']:.0%}"
    )

    return {
        "path": str(audio_path),
        "quality": quality,
        "segments": segments,
        "events": events,
        "summary": summary,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Hear: audio timeline + quality.")
    parser.add_argument("path", help="audio file to analyze")
    parser.add_argument("--json", dest="json_out", help="also write report to file")
    parser.add_argument("--top-events", type=int, default=32)
    args = parser.parse_args(argv)

    report = run(args.path, top_events=args.top_events)
    text = json.dumps(report, indent=2)
    if args.json_out:
        Path(args.json_out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
