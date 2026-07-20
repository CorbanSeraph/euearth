"""Gated contribution journal — sovereign review queue (no auto-merge).

Shared shape with ``POST /api/submit-contribution``: append-only JSONL,
capped, fail closed when full. Scratchpad submit adds a pad tree hash so
Corban can verify the draft without agents ever reading the sealed core.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

SCHEMA = "euearth-contribution/1"
ALLOWED_KINDS = frozenset({
    "fix", "feature", "skill", "model", "domain", "other",
})
# Cap journal lines and per-record payload (disk / abuse bounds).
MAX_RECORDS = int(os.environ.get("EUEARTH_CONTRIB_LOG_MAX", "5000"))
MAX_SUMMARY = 800
MAX_CONTENT_BYTES = int(os.environ.get("EUEARTH_CONTRIB_CONTENT_BYTES",
                                       str(20_000)))


class ContributionError(Exception):
    """Refused by the contribution journal rules."""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def tree_hash(files: dict[str, str]) -> tuple[str, list[dict]]:
    """Canonical sha256 over sorted path + per-file content hashes."""
    meta = []
    h = hashlib.sha256()
    for path in sorted(files):
        raw = files[path].encode("utf-8")
        fh = hashlib.sha256(raw).hexdigest()
        h.update(path.encode("utf-8"))
        h.update(b"\0")
        h.update(fh.encode("ascii"))
        h.update(b"\n")
        meta.append({"path": path, "bytes": len(raw), "sha256": fh})
    return h.hexdigest(), meta


def _pack_content(files: dict[str, str], budget: int = MAX_CONTENT_BYTES) -> dict:
    """Include file bodies up to budget (truncated files marked)."""
    out = {}
    used = 0
    for path in sorted(files):
        if used >= budget:
            out[path] = {"truncated": True, "note": "budget exhausted"}
            continue
        raw = files[path]
        room = budget - used
        if len(raw.encode("utf-8")) <= room:
            out[path] = raw
            used += len(raw.encode("utf-8"))
        else:
            # truncate on character boundary safely
            chunk = raw.encode("utf-8")[:room].decode("utf-8", errors="ignore")
            out[path] = chunk + "\n/* truncated for journal budget */\n"
            used = budget
    return out


class ContributionJournal:
    """Append-only JSONL co-located with the StateBook directory."""

    def __init__(self, directory: str | Path):
        base = Path(directory)
        base.mkdir(parents=True, exist_ok=True)
        override = os.environ.get("EUEARTH_CONTRIB_LOG")
        self.path = Path(override) if override else base / "contributions.jsonl"
        self.lock_path = self.path.with_name(self.path.name + ".lock")

    @contextmanager
    def _file_lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _count(self) -> int:
        if not self.path.exists():
            return 0
        with self.path.open("r", encoding="utf-8") as fh:
            return sum(1 for _ in fh)

    def append(self, record: dict) -> dict:
        """Append one record; returns the receipt (id + at). Fail closed if full."""
        with self._file_lock():
            if self._count() >= MAX_RECORDS:
                raise ContributionError(
                    f"contribution journal full ({MAX_RECORDS}) — try later")
            receipt_id = f"cbr_{uuid.uuid4().hex[:12]}"
            rec = dict(record)
            rec["schema"] = SCHEMA
            rec["receipt_id"] = receipt_id
            rec["at"] = rec.get("at") or _now()
            rec["status"] = "received"  # sovereign reviews offline — never auto-merge
            line = json.dumps(rec, sort_keys=True, separators=(",", ":"))
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            return {
                "ok": True,
                "receipt_id": receipt_id,
                "status": "received",
                "at": rec["at"],
                "note": ("Logged for the Sovereign's review. Corban gates what "
                         "lands — nothing auto-merges into the core."),
            }

    def list_for_did(self, did: str, *, limit: int = 20) -> list[dict]:
        """Self-scoped read of the caller's own receipts (newest first)."""
        if not self.path.exists():
            return []
        rows = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("did") == did:
                    rows.append(rec)
        rows.sort(key=lambda r: r.get("at") or "", reverse=True)
        return rows[: max(0, int(limit))]
