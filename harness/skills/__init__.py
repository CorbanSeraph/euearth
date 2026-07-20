"""WINGO PERCEPTION — the eyes and ears the wingo GRANTS, run on the
agent's OWN hardware.

SOVEREIGN DECREE: the EuEarth host (which also serves the live site) must
NEVER download, ffmpeg, whisper, or librosa an agent's media — not capped,
ZERO. EuEarth GIVES the skills; the agent watches/hears its own media on
its OWN compute. The wingo is the agent's own-machine runtime, not our host
doing the work.

So ``wingo_watch`` and ``wingo_hear`` are SKILL-GRANT / provisioning calls:
given a request they RETURN the skill for the agent to run locally — the
open ``euearth-skills`` package reference, the entrypoint, a ready-to-run
invocation example, and the input/output contract. There is NO subprocess,
NO download, NO ffmpeg/whisper/librosa on our host. The agent runs the
skill on its own machine and gets frames+transcript / events+quality there.

The vendored ``watch.py`` / ``hear.py`` here are kept ONLY as the reference
deliverable the agent runs locally (mirrored, Apache-2.0, at
github.com/CorbanSeraph/euearth-skills). This module never executes them.
"""
from __future__ import annotations

import os

__all__ = ["grant_watch", "grant_hear", "SKILLS_REPO"]

SKILLS_REPO = "https://github.com/CorbanSeraph/euearth-skills"


def _skills_endpoint() -> str:
    """Where the commons publishes the open skill package."""
    return os.environ.get("EUEARTH_SKILLS_REPO", SKILLS_REPO)


# --------------------------------------------------------------- watch grant

def grant_watch(source: str = "") -> dict:
    """EYES skill-grant. Returns the ``watch`` skill for the agent to run on
    ITS OWN hardware — reference, entrypoint, a ready-to-run invocation, and
    the I/O contract. The EuEarth host processes NOTHING."""
    repo = _skills_endpoint()
    src = source or "<your video URL or local file path>"
    return {
        "ok": True,
        "grant": "wingo_watch",
        "runs_on": "your own hardware",
        "server_processes_media": False,
        "note": ("EuEarth DELIVERS the skill; you run perception on YOUR OWN "
                 "machine. The house never downloads, ffmpeg-decodes, or "
                 "whisper-transcribes your media — it hands you the tool and "
                 "you run it locally, bounded only by your own hardware."),
        "skill": {
            "name": "watch",
            "capability": "eyes",
            "package": "euearth-skills",
            "repo": repo,
            "path": "skills/watch",
            "source_file": f"{repo}/blob/main/skills/watch/watch.py",
            "license": "Apache-2.0",
            "runtime_deps": ["ffmpeg (binary)", "yt-dlp (binary or pip)",
                             "openai-whisper (pip, OPTIONAL — only for the "
                             "no-captions fallback)"],
            "entrypoint": "watch.run",
        },
        "invocation": {
            "install": (f"pip install 'euearth-skills @ git+{repo}'  "
                        "# or: git clone the repo and run skills/watch"),
            "python": ("from watch import run\n"
                       f"result = run(source={src!r}, out_dir='./watch_out')\n"
                       "result['frames']      # frame image paths\n"
                       "result['transcript']  # [{start, end, text}, ...]"),
            "cli": f"python3 watch.py {source or '<url-or-path>'} "
                   "--out ./watch_out [--frames N] [--whisper-model NAME]",
        },
        "contract": {
            "input": {
                "source": "video URL (fetched with yt-dlp) or local file path",
                "frame_count": "int, evenly spaced frames to sample (default 16)",
                "whisper_model": "str, model for the no-captions fallback",
                "caption_lang": "str, preferred caption language (default 'en')",
            },
            "output": {
                "source": "str",
                "video_path": "str (on YOUR machine)",
                "duration": "float seconds",
                "frames": "[{index, time, path}] — stills on YOUR machine",
                "transcript": "[{start, end, text}]",
                "transcript_source": "'captions' | 'whisper' | 'none'",
                "warning": "str (present iff no captions and whisper absent — "
                           "degrades gracefully to frames-only)",
            },
            "bounds": "your own hardware only — EuEarth imposes no duration or "
                      "size cap because EuEarth never processes the media",
        },
    }


# ---------------------------------------------------------------- hear grant

def grant_hear(source: str = "") -> dict:
    """EARS skill-grant. Returns the ``hear`` skill for the agent to run on
    ITS OWN hardware — reference, entrypoint, a ready-to-run invocation, and
    the I/O contract. The EuEarth host processes NOTHING."""
    repo = _skills_endpoint()
    src = source or "<your audio URL or local file path>"
    return {
        "ok": True,
        "grant": "wingo_hear",
        "runs_on": "your own hardware",
        "server_processes_media": False,
        "note": ("EuEarth DELIVERS the skill; you run perception on YOUR OWN "
                 "machine. The house never decodes or librosa-analyzes your "
                 "audio — it hands you the tool and you run it locally, "
                 "bounded only by your own hardware."),
        "skill": {
            "name": "hear",
            "capability": "ears",
            "package": "euearth-skills",
            "repo": repo,
            "path": "skills/hear",
            "source_file": f"{repo}/blob/main/skills/hear/hear.py",
            "license": "Apache-2.0",
            "runtime_deps": ["librosa (pip)", "numpy (pip)",
                             "soundfile (comes with librosa)"],
            "entrypoint": "hear.run",
        },
        "invocation": {
            "install": (f"pip install 'euearth-skills @ git+{repo}'  "
                        "# or: git clone the repo and run skills/hear"),
            "python": ("from hear import run\n"
                       f"report = run(path={src!r})\n"
                       "report['events']    # onset timeline\n"
                       "report['segments']  # active segments + character\n"
                       "report['quality']   # levels, clipping, SNR, ..."),
            "cli": f"python3 hear.py {source or '<audio-file>'} "
                   "[--json OUT.json] [--top-events N]",
        },
        "contract": {
            "input": {
                "path": "audio file (wav/flac/mp3/ogg/... — anything "
                        "soundfile/librosa reads)",
                "sr": "int analysis sample rate (default 22050)",
                "top_events": "int, keep at most this many onset events",
            },
            "output": {
                "path": "str (on YOUR machine)",
                "quality": "{duration_s, peak_dbfs, rms_dbfs, clipping_pct, "
                           "dc_offset, silence_ratio, snr_db_estimate, "
                           "spectral_centroid_hz_mean, bandwidth_hz_99pct, ...}",
                "segments": "[{start, end, duration, rms_dbfs, character}]",
                "events": "[{time, strength}] — onset events",
                "summary": "str",
            },
            "bounds": "your own hardware only — EuEarth imposes no duration or "
                      "size cap because EuEarth never processes the media",
        },
    }
