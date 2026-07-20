"""A2A MAILBOX — per-DID private message box (EuEarth-exclusive).

Corban gate #6 (spam vector): hard rate-limit + size caps, send only to a
KNOWN DID, never expose another agent's mail. Self-scoped reads only.

Storage: ``<state-dir>/mailboxes/<sha256(did)[:32]>/inbox.jsonl``
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

SCHEMA = "euearth-mailbox/1"

MAX_BODY = int(os.environ.get("EUEARTH_MAIL_MAX_BODY", "2000"))
MAX_SUBJECT = int(os.environ.get("EUEARTH_MAIL_MAX_SUBJECT", "120"))
MAX_INBOX = int(os.environ.get("EUEARTH_MAIL_MAX_INBOX", "100"))
# Rate limit: max sends per DID per rolling window (seconds).
RATE_MAX = int(os.environ.get("EUEARTH_MAIL_RATE_MAX", "20"))
RATE_WINDOW = float(os.environ.get("EUEARTH_MAIL_RATE_WINDOW", "60"))


class MailboxError(Exception):
    """Refused by mailbox rules (rate, size, unknown recipient, scope)."""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _did_key(did: str) -> str:
    return hashlib.sha256(did.encode("utf-8")).hexdigest()[:32]


class MailboxBook:
    """Durable per-DID inboxes + durable send rate tracker."""

    def __init__(self, directory: str | Path):
        self.base = Path(directory) / "mailboxes"
        self.base.mkdir(parents=True, exist_ok=True)

    def _box_dir(self, did: str) -> Path:
        if not did:
            raise MailboxError("did is required")
        d = self.base / _did_key(did)
        d.mkdir(parents=True, exist_ok=True)
        # Bind the directory to the DID (detect transplant/corruption).
        stamp = d / "owner.json"
        if stamp.exists():
            try:
                owner = json.loads(stamp.read_text(encoding="utf-8")).get("did")
            except (json.JSONDecodeError, OSError):
                owner = None
            if owner not in (None, did):
                raise MailboxError("mailbox owner mismatch (fail closed)")
        else:
            stamp.write_text(json.dumps({"did": did, "schema": SCHEMA}),
                             encoding="utf-8")
            os.chmod(stamp, 0o600)
        return d

    def _inbox_path(self, did: str) -> Path:
        return self._box_dir(did) / "inbox.jsonl"

    def _lock_path(self, did: str) -> Path:
        return self._box_dir(did) / ".lock"

    def _rate_path(self, did: str) -> Path:
        return self._box_dir(did) / "send_rate.json"

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

    def _check_rate(self, from_did: str) -> None:
        with self._file_lock(from_did):
            path = self._rate_path(from_did)
            if path.exists():
                try:
                    loaded = json.loads(path.read_text(encoding="utf-8"))
                    if not isinstance(loaded, list):
                        raise ValueError("rate state must be a list")
                    timestamps = [float(value) for value in loaded]
                    if not all(math.isfinite(value) for value in timestamps):
                        raise ValueError("rate timestamps must be finite")
                except (OSError, UnicodeError, json.JSONDecodeError,
                        TypeError, ValueError) as exc:
                    raise MailboxError(
                        f"send rate state unreadable — fail closed: {exc}")
            else:
                timestamps = []
            now = time.time()
            timestamps = [value for value in timestamps
                          if now - value <= RATE_WINDOW]
            if len(timestamps) >= RATE_MAX:
                raise MailboxError(
                    f"send rate limit exceeded ({RATE_MAX} per "
                    f"{int(RATE_WINDOW)}s) — fail closed")
            timestamps.append(now)
            tmp = path.with_name(path.name + ".tmp")
            payload = json.dumps(timestamps, separators=(",", ":"))
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)

    def _inbox_count(self, path: Path) -> int:
        if not path.exists():
            return 0
        with path.open("r", encoding="utf-8") as fh:
            return sum(1 for line in fh if line.strip())

    def send(self, *, from_did: str, to_did: str, body: str,
             subject: str = "", known_recipient: bool = False) -> dict:
        """Deliver one message into ``to_did``'s inbox. Caller must set
        ``known_recipient=True`` only after verifying the DID is known to
        EuEarth (gateway checks the roster/StateBook)."""
        if not from_did or not to_did:
            raise MailboxError("from_did and to_did are required")
        if from_did == to_did:
            raise MailboxError("cannot send mail to yourself")
        if not known_recipient:
            raise MailboxError("recipient DID is not known to EuEarth")
        body = body if isinstance(body, str) else ""
        subject = subject if isinstance(subject, str) else ""
        if not body.strip():
            raise MailboxError("body is required")
        if len(body.encode("utf-8")) > MAX_BODY:
            raise MailboxError(
                f"body exceeds cap ({MAX_BODY} bytes) — fail closed")
        if len(subject.encode("utf-8")) > MAX_SUBJECT:
            raise MailboxError(
                f"subject exceeds cap ({MAX_SUBJECT} bytes) — fail closed")

        self._check_rate(from_did)

        msg = {
            "schema": SCHEMA,
            "message_id": f"msg_{uuid.uuid4().hex[:12]}",
            "from_did": from_did,
            "to_did": to_did,
            "subject": subject.strip()[:MAX_SUBJECT],
            "body": body,
            "at": _now(),
        }

        with self._file_lock(to_did):
            path = self._inbox_path(to_did)
            if self._inbox_count(path) >= MAX_INBOX:
                raise MailboxError(
                    f"recipient inbox full ({MAX_INBOX}) — fail closed")
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(msg, sort_keys=True,
                                    separators=(",", ":")) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        return {
            "ok": True,
            "message_id": msg["message_id"],
            "to_did": to_did,
            "at": msg["at"],
            "note": "Delivered to recipient inbox. Only they can read it.",
        }

    def inbox(self, did: str, *, limit: int = 20) -> list[dict]:
        """Read ONLY this DID's inbox (newest first). Never accepts another DID."""
        if not did:
            raise MailboxError("did is required")
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 20
        limit = max(1, min(limit, MAX_INBOX))
        with self._file_lock(did):
            path = self._inbox_path(did)
            if not path.exists():
                return []
            rows = []
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    # Defense in depth: drop rows not addressed to this DID
                    if rec.get("to_did") not in (None, did):
                        continue
                    rows.append(rec)
            rows.sort(key=lambda r: r.get("at") or "", reverse=True)
            return rows[:limit]

    def system_drop(self, *, to_did: str, body: str, subject: str = "",
                    from_did: str = "did:euearth:mint") -> dict:
        """House/Mint drop into a citizen's wingo inbox (no rate limit, no self-send ban).

        Used by the Mint FIRE claim path (D042): one line — the ledger mark.
        Not available as an agent-callable tool.
        """
        if not to_did:
            raise MailboxError("to_did is required")
        body = body if isinstance(body, str) else ""
        subject = subject if isinstance(subject, str) else ""
        if not body.strip():
            raise MailboxError("body is required")
        if len(body.encode("utf-8")) > MAX_BODY:
            raise MailboxError(
                f"body exceeds cap ({MAX_BODY} bytes) — fail closed")
        if len(subject.encode("utf-8")) > MAX_SUBJECT:
            raise MailboxError(
                f"subject exceeds cap ({MAX_SUBJECT} bytes) — fail closed")

        msg = {
            "schema": SCHEMA,
            "message_id": f"msg_{uuid.uuid4().hex[:12]}",
            "from_did": from_did,
            "to_did": to_did,
            "subject": subject.strip()[:MAX_SUBJECT],
            "body": body,
            "at": _now(),
            "system": True,
        }
        with self._file_lock(to_did):
            path = self._inbox_path(to_did)
            if self._inbox_count(path) >= MAX_INBOX:
                raise MailboxError(
                    f"recipient inbox full ({MAX_INBOX}) — fail closed")
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(msg, sort_keys=True,
                                    separators=(",", ":")) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        return {
            "ok": True,
            "message_id": msg["message_id"],
            "to_did": to_did,
            "at": msg["at"],
            "system": True,
        }
