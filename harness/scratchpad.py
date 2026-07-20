"""SCRATCHPAD — private, durable, sandboxed code workbench (EuEarth-exclusive).

Per-DID pad store co-located with the StateBook. An agent drafts code and
notes here, runs them ONLY through ``harness.sandbox.run_sandboxed`` (same
jail as ``sandbox_exec``), and never receives a server-side "open repo path"
API (IP guardrail: agent content in, sealed core never out).

Caps are env-overridable and FAIL CLOSED on overflow.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

SCHEMA = "euearth-scratchpad/1"

# Env-overridable caps (Corban gate #5) — fail closed on overflow.
MAX_PADS = int(os.environ.get("EUEARTH_SCRATCHPAD_MAX_PADS", "8"))
MAX_FILES = int(os.environ.get("EUEARTH_SCRATCHPAD_MAX_FILES", "32"))
MAX_FILE_BYTES = int(os.environ.get("EUEARTH_SCRATCHPAD_MAX_FILE_BYTES", str(64 * 1024)))
MAX_TOTAL_BYTES = int(os.environ.get("EUEARTH_SCRATCHPAD_MAX_TOTAL_BYTES",
                                     str(512 * 1024)))

_SAFE_PATH = re.compile(r"^[A-Za-z0-9._-][A-Za-z0-9._/-]*$")


class ScratchpadError(Exception):
    """Refused by scratchpad rules (caps, path, ownership of the store)."""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _did_key(did: str) -> str:
    return hashlib.sha256(did.encode("utf-8")).hexdigest()[:32]


def safe_relpath(path: str) -> str:
    """Relative pad path: no absolute, no ``..``, no nulls, no empty."""
    if not path or not isinstance(path, str):
        raise ScratchpadError("path is required")
    if "\x00" in path:
        raise ScratchpadError("path must not contain null bytes")
    p = path.replace("\\", "/").strip()
    if p.startswith("/") or p.startswith("~"):
        raise ScratchpadError("path must be relative (no absolute paths)")
    parts = [x for x in p.split("/") if x not in ("", ".")]
    if not parts or any(x == ".." for x in parts):
        raise ScratchpadError("path must not contain '..' or be empty")
    joined = "/".join(parts)
    if not _SAFE_PATH.match(joined):
        raise ScratchpadError(
            "path may only use letters, digits, . _ - / "
            f"(got {path!r})")
    if len(joined) > 200:
        raise ScratchpadError("path too long (max 200)")
    return joined


class ScratchpadBook:
    """Durable per-DID scratchpads under ``<state-dir>/scratchpads/<did-hash>/``."""

    def __init__(self, directory: str | Path):
        self.base = Path(directory) / "scratchpads"
        self.base.mkdir(parents=True, exist_ok=True)

    def _agent_dir(self, did: str) -> Path:
        if not did:
            raise ScratchpadError("did is required")
        d = self.base / _did_key(did)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _index_path(self, did: str) -> Path:
        return self._agent_dir(did) / "index.json"

    def _lock_path(self, did: str) -> Path:
        return self._agent_dir(did) / ".lock"

    def _pad_dir(self, did: str, pad_id: str) -> Path:
        return self._agent_dir(did) / pad_id

    @contextmanager
    def _file_lock(self, did: str):
        lock_path = self._lock_path(did)
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _load_index(self, did: str) -> dict:
        path = self._index_path(did)
        if not path.exists():
            return {"schema": SCHEMA, "did": did, "pads": {}}
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeError) as exc:
            raise ScratchpadError(f"scratchpad index unreadable: {exc}")
        if not isinstance(state, dict) or not isinstance(state.get("pads"), dict):
            raise ScratchpadError("scratchpad index structurally invalid")
        # Identity bind: the index is under the hash of `did`; refuse a
        # mismatched did field (corruption / cross-agent transplant).
        if state.get("did") not in (None, did):
            raise ScratchpadError("scratchpad index DID mismatch (fail closed)")
        state["did"] = did
        state.setdefault("schema", SCHEMA)
        return state

    def _save_index(self, did: str, state: dict) -> None:
        path = self._index_path(did)
        state["did"] = did
        state["schema"] = SCHEMA
        payload = json.dumps(state, indent=2, sort_keys=True)
        tmp = path.with_name(path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)

    def _total_bytes(self, did: str) -> int:
        root = self._agent_dir(did)
        total = 0
        for p in root.rglob("*"):
            if p.is_file() and p.name not in (".lock",) and not p.name.endswith(".tmp"):
                if p.name == "index.json":
                    continue
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
        return total

    def list_pads(self, did: str) -> list[dict]:
        with self._file_lock(did):
            state = self._load_index(did)
            rows = []
            for pad_id, meta in state["pads"].items():
                rows.append(dict(meta))
            rows.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
            return rows

    def open_pad(self, did: str, *, title: str = "",
                 pad_id: str | None = None) -> dict:
        """Open an existing pad, or create one when ``pad_id`` is None."""
        with self._file_lock(did):
            state = self._load_index(did)
            if pad_id:
                meta = state["pads"].get(pad_id)
                if meta is None:
                    raise ScratchpadError(f"unknown pad: {pad_id}")
                return self._manifest(did, pad_id, meta)

            if len(state["pads"]) >= MAX_PADS:
                raise ScratchpadError(
                    f"pad limit reached ({MAX_PADS}) — delete is not yet "
                    "available; fail closed")
            pad_id = f"pad_{uuid.uuid4().hex[:12]}"
            now = _now()
            meta = {
                "pad_id": pad_id,
                "title": (title or "untitled")[:120],
                "entrypoint": "main.py",
                "created_at": now,
                "updated_at": now,
                "file_count": 0,
                "bytes": 0,
            }
            pdir = self._pad_dir(did, pad_id)
            (pdir / "files").mkdir(parents=True, exist_ok=True)
            meta_path = pdir / "meta.json"
            meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True),
                                 encoding="utf-8")
            os.chmod(meta_path, 0o600)
            state["pads"][pad_id] = meta
            self._save_index(did, state)
            return self._manifest(did, pad_id, meta)

    def _manifest(self, did: str, pad_id: str, meta: dict) -> dict:
        files_dir = self._pad_dir(did, pad_id) / "files"
        files = []
        total = 0
        if files_dir.is_dir():
            for p in sorted(files_dir.rglob("*")):
                if p.is_file():
                    rel = str(p.relative_to(files_dir)).replace("\\", "/")
                    size = p.stat().st_size
                    total += size
                    files.append({"path": rel, "bytes": size})
        out = dict(meta)
        out["files"] = files
        out["file_count"] = len(files)
        out["bytes"] = total
        out["caps"] = {
            "max_pads": MAX_PADS,
            "max_files": MAX_FILES,
            "max_file_bytes": MAX_FILE_BYTES,
            "max_total_bytes": MAX_TOTAL_BYTES,
        }
        return out

    def write_file(self, did: str, pad_id: str, path: str, content: str) -> dict:
        """Write agent-authored content only (no server path load)."""
        rel = safe_relpath(path)
        if not isinstance(content, str):
            raise ScratchpadError("content must be a string")
        # UTF-8 size gate
        raw = content.encode("utf-8")
        if len(raw) > MAX_FILE_BYTES:
            raise ScratchpadError(
                f"file exceeds cap ({MAX_FILE_BYTES} bytes) — fail closed")
        with self._file_lock(did):
            state = self._load_index(did)
            meta = state["pads"].get(pad_id)
            if meta is None:
                raise ScratchpadError(f"unknown pad: {pad_id}")
            files_dir = self._pad_dir(did, pad_id) / "files"
            files_dir.mkdir(parents=True, exist_ok=True)
            target = files_dir / rel
            # ensure target stays under files_dir
            try:
                target.resolve().relative_to(files_dir.resolve())
            except ValueError:
                raise ScratchpadError("path escapes pad files directory")
            existing = list(files_dir.rglob("*"))
            existing_files = [p for p in existing if p.is_file()]
            is_new = not target.exists()
            if is_new and len(existing_files) >= MAX_FILES:
                raise ScratchpadError(
                    f"file limit per pad reached ({MAX_FILES}) — fail closed")
            # total bytes after write
            other = 0
            for p in existing_files:
                if p.resolve() != target.resolve():
                    other += p.stat().st_size
            # index.json is outside files/; count pad files only for total
            # also count other pads under this DID for MAX_TOTAL_BYTES
            total_other_pads = 0
            for other_id in state["pads"]:
                if other_id == pad_id:
                    continue
                od = self._pad_dir(did, other_id) / "files"
                if od.is_dir():
                    for p in od.rglob("*"):
                        if p.is_file():
                            total_other_pads += p.stat().st_size
            if other + len(raw) + total_other_pads > MAX_TOTAL_BYTES:
                raise ScratchpadError(
                    f"total scratchpad bytes would exceed "
                    f"{MAX_TOTAL_BYTES} — fail closed")
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, target)
            # refresh meta stats
            manifest = self._manifest(did, pad_id, meta)
            meta["updated_at"] = _now()
            meta["file_count"] = manifest["file_count"]
            meta["bytes"] = manifest["bytes"]
            state["pads"][pad_id] = meta
            self._save_index(did, state)
            return {
                "ok": True,
                "pad_id": pad_id,
                "path": rel,
                "bytes": len(raw),
                "file_count": meta["file_count"],
                "pad_bytes": meta["bytes"],
            }

    def read_file(self, did: str, pad_id: str, path: str | None = None) -> dict:
        with self._file_lock(did):
            state = self._load_index(did)
            meta = state["pads"].get(pad_id)
            if meta is None:
                raise ScratchpadError(f"unknown pad: {pad_id}")
            if path is None or path == "":
                return {"ok": True, "pad_id": pad_id,
                        "manifest": self._manifest(did, pad_id, meta)}
            rel = safe_relpath(path)
            files_dir = self._pad_dir(did, pad_id) / "files"
            target = files_dir / rel
            try:
                target.resolve().relative_to(files_dir.resolve())
            except ValueError:
                raise ScratchpadError("path escapes pad files directory")
            if not target.is_file():
                raise ScratchpadError(f"unknown file: {rel}")
            content = target.read_text(encoding="utf-8")
            return {"ok": True, "pad_id": pad_id, "path": rel,
                    "content": content, "bytes": len(content.encode("utf-8"))}

    def load_files(self, did: str, pad_id: str) -> tuple[dict, dict[str, str]]:
        """Return (meta, {relpath: content}) for sandbox materialization."""
        with self._file_lock(did):
            state = self._load_index(did)
            meta = state["pads"].get(pad_id)
            if meta is None:
                raise ScratchpadError(f"unknown pad: {pad_id}")
            files_dir = self._pad_dir(did, pad_id) / "files"
            out: dict[str, str] = {}
            if files_dir.is_dir():
                for p in files_dir.rglob("*"):
                    if p.is_file():
                        rel = str(p.relative_to(files_dir)).replace("\\", "/")
                        out[rel] = p.read_text(encoding="utf-8")
            return dict(meta), out
