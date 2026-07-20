"""watch — give an agent eyes on a video.

REFERENCE DELIVERABLE ONLY. By the Sovereign's decree the EuEarth host
NEVER processes an agent's media. This file is the skill the agent runs on
its OWN hardware; the wingo's ``wingo_watch`` GRANTS it (see
harness/skills/__init__.py: grant_watch). The EuEarth request path never
imports or executes this module. Mirrored open at
github.com/CorbanSeraph/euearth-skills (skills/watch, Apache-2.0).

Given a video URL or local path, produce:
  1. Sampled frames (JPEG stills, evenly spaced) via ffmpeg.
  2. A transcript: platform captions via yt-dlp when present,
     otherwise speech-to-text via openai-whisper (if installed).

External dependencies (see SKILL.md): ffmpeg (binary), yt-dlp (binary or
pip module), openai-whisper (pip, optional — only needed when the source
has no captions).

Library use:
    from watch import run
    result = run(source="https://example.com/talk", out_dir="./watch_out")
    result["frames"]        # list of frame image paths
    result["transcript"]    # list of {"start": s, "end": s, "text": ...}

CLI use:
    python3 watch.py <url-or-path> [--out DIR] [--frames N] [--whisper-model NAME]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

__all__ = ["run"]

DEFAULT_FRAME_COUNT = 16
DEFAULT_WHISPER_MODEL = "base"

_URL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


def _is_url(source: str) -> bool:
    return bool(_URL_RE.match(source))


def _require(binary: str) -> str:
    path = shutil.which(binary)
    if not path:
        raise RuntimeError(
            f"required binary {binary!r} not found on PATH (see SKILL.md deps)"
        )
    return path


def _sh(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


# ----------------------------------------------------------------- download

def download_video(url: str, work_dir: Path) -> Path:
    """Fetch a video with yt-dlp; return the local media path."""
    _require("yt-dlp")
    template = str(work_dir / "video.%(ext)s")
    proc = _sh(
        ["yt-dlp", "--no-playlist", "-f", "bv*[height<=720]+ba/b[height<=720]/b",
         "-o", template, url]
    )
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp download failed: {proc.stderr.strip()[-800:]}")
    candidates = sorted(work_dir.glob("video.*"))
    media = [p for p in candidates if p.suffix not in (".part", ".ytdl")]
    if not media:
        raise RuntimeError("yt-dlp reported success but no media file was produced")
    return media[0]


# ------------------------------------------------------------------- frames

def probe_duration(video: Path) -> float:
    """Return the media duration in seconds via ffprobe."""
    _require("ffprobe")
    proc = _sh(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)]
    )
    try:
        return float(proc.stdout.strip())
    except ValueError:
        raise RuntimeError(f"could not probe duration of {video}: {proc.stderr.strip()}")


def sample_frames(video: Path, out_dir: Path, count: int) -> list[dict]:
    """Extract ``count`` evenly spaced JPEG frames. Returns frame records."""
    _require("ffmpeg")
    out_dir.mkdir(parents=True, exist_ok=True)
    duration = probe_duration(video)
    frames = []
    for i in range(count):
        # Midpoint sampling: avoids black first frames and credits-only last frames.
        t = duration * (i + 0.5) / count
        path = out_dir / f"frame_{i:03d}_t{t:07.1f}s.jpg"
        proc = _sh(
            ["ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", str(video),
             "-frames:v", "1", "-q:v", "3", str(path)]
        )
        if proc.returncode == 0 and path.exists():
            frames.append({"index": i, "time": round(t, 2), "path": str(path)})
    if not frames:
        raise RuntimeError("ffmpeg produced no frames")
    return frames


# --------------------------------------------------------------- transcript

def _parse_vtt(vtt_text: str) -> list[dict]:
    """Parse WebVTT into [{'start', 'end', 'text'}] segments (deduplicated)."""
    def ts(s: str) -> float:
        parts = s.replace(",", ".").split(":")
        parts = [float(p) for p in parts]
        while len(parts) < 3:
            parts.insert(0, 0.0)
        h, m, sec = parts
        return h * 3600 + m * 60 + sec

    segments: list[dict] = []
    cue_re = re.compile(
        r"(\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{3}\s*-->\s*(\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{3}"
    )
    lines = vtt_text.splitlines()
    i = 0
    while i < len(lines):
        m = cue_re.search(lines[i])
        if m:
            start_s, end_s = [p.strip().split(" ")[0] for p in lines[i].split("-->")]
            i += 1
            text_lines = []
            while i < len(lines) and lines[i].strip() and not cue_re.search(lines[i]):
                clean = re.sub(r"<[^>]+>", "", lines[i]).strip()
                if clean:
                    text_lines.append(clean)
                i += 1
            text = " ".join(text_lines).strip()
            if text and (not segments or segments[-1]["text"] != text):
                segments.append(
                    {"start": round(ts(start_s), 2), "end": round(ts(end_s), 2),
                     "text": text}
                )
        else:
            i += 1
    return segments


def fetch_captions(url: str, work_dir: Path, lang: str = "en") -> list[dict] | None:
    """Try platform captions via yt-dlp. Returns segments or None."""
    _require("yt-dlp")
    template = str(work_dir / "caps.%(ext)s")
    proc = _sh(
        ["yt-dlp", "--no-playlist", "--skip-download",
         "--write-subs", "--write-auto-subs",
         "--sub-langs", f"{lang}.*,{lang}", "--sub-format", "vtt",
         "-o", template, url]
    )
    if proc.returncode != 0:
        return None
    vtts = sorted(work_dir.glob("caps.*.vtt"))
    if not vtts:
        return None
    segments = _parse_vtt(vtts[0].read_text(encoding="utf-8", errors="replace"))
    return segments or None


def whisper_transcribe(video: Path, model_name: str) -> list[dict]:
    """Transcribe with openai-whisper. Raises if whisper is not installed."""
    try:
        import whisper  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "no captions found and openai-whisper is not installed; "
            "run: pip install openai-whisper"
        ) from exc
    model = whisper.load_model(model_name)
    result = model.transcribe(str(video))
    return [
        {"start": round(s["start"], 2), "end": round(s["end"], 2),
         "text": s["text"].strip()}
        for s in result.get("segments", [])
    ]


# --------------------------------------------------------------------- main

def run(
    source: str,
    out_dir: str = "watch_out",
    frame_count: int = DEFAULT_FRAME_COUNT,
    whisper_model: str = DEFAULT_WHISPER_MODEL,
    caption_lang: str = "en",
) -> dict:
    """Watch a video: sample frames and produce a transcript.

    Args:
        source: Video URL (fetched with yt-dlp) or local file path.
        out_dir: Directory for frames and transcript.json.
        frame_count: Number of evenly spaced frames to extract.
        whisper_model: openai-whisper model name for the no-captions fallback.
        caption_lang: Preferred caption language code.

    Returns:
        {"source", "video_path", "duration", "frames": [...],
         "transcript": [...], "transcript_source": "captions"|"whisper"|"none"}
    """
    out = Path(out_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="watch_"))

    try:
        transcript: list[dict] | None = None
        transcript_source = "none"

        if _is_url(source):
            transcript = fetch_captions(source, work, lang=caption_lang)
            if transcript:
                transcript_source = "captions"
            downloaded = download_video(source, work)
            video = out / downloaded.name
            shutil.move(str(downloaded), video)
        else:
            video = Path(source).expanduser().resolve()
            if not video.exists():
                raise FileNotFoundError(f"no such file: {video}")

        duration = probe_duration(video)
        frames = sample_frames(video, out / "frames", frame_count)

        warning = None
        if transcript is None:
            try:
                transcript = whisper_transcribe(video, whisper_model)
                transcript_source = "whisper" if transcript else "none"
            except RuntimeError as exc:
                # No captions and no whisper installed: frames are still
                # valuable — degrade gracefully instead of failing.
                transcript, warning = [], str(exc)

        result = {
            "source": source,
            "video_path": str(video),
            "duration": round(duration, 2),
            "frames": frames,
            "transcript": transcript,
            "transcript_source": transcript_source,
        }
        if warning:
            result["warning"] = warning
        (out / "transcript.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Watch a video: frames + transcript.")
    parser.add_argument("source", help="video URL or local file path")
    parser.add_argument("--out", default="watch_out", help="output directory")
    parser.add_argument("--frames", type=int, default=DEFAULT_FRAME_COUNT,
                        help=f"frame count (default {DEFAULT_FRAME_COUNT})")
    parser.add_argument("--whisper-model", default=DEFAULT_WHISPER_MODEL,
                        help="whisper model for no-caption fallback")
    parser.add_argument("--lang", default="en", help="preferred caption language")
    args = parser.parse_args(argv)

    result = run(args.source, out_dir=args.out, frame_count=args.frames,
                 whisper_model=args.whisper_model, caption_lang=args.lang)
    summary = {k: result[k] for k in ("source", "duration", "transcript_source")}
    summary["frame_count"] = len(result["frames"])
    summary["transcript_segments"] = len(result["transcript"])
    summary["out_dir"] = str(Path(args.out).resolve())
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
