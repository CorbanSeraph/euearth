"""ChannelBook — durable guild channels for A2A 1-to-many (Wave E PR3).

Membership + capped scrollback. Live fan-out goes through EventBus
(chan:<id>); SSE connections must subscribe the topic for self-scoped
delivery. Town square create/rank gates land in PR4 — this module seeds
public guild channels and supports join/publish/history.

Caps (Corban-frozen): scrollback 500, members 500, pub rate 10/60s/DID,
global channel rate 60/60s.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import time
import uuid
from collections import deque
from contextlib import contextmanager
from pathlib import Path

from harness.a2a_events import (
    CHANNEL_GLOBAL_RATE,
    CHANNEL_MEMBER_CAP,
    CHANNEL_PUB_RATE,
    CHANNEL_SCROLLBACK,
    MAIL_MAX_BODY,
    MAIL_RATE_WINDOW,
    new_message_id,
)

SCHEMA = "euearth-channels/1"
_SAFE_ID = re.compile(r"^chan:[a-z0-9][a-z0-9:._-]{1,80}$")

# Seeded public guilds (idempotent). Town is PR4.
_SEED = [
    {
        "channel_id": "chan:domain:text-transform",
        "title": "Text-Transform guild",
        "summary": "Coordinate on the live text-transform keel: challenges, "
                   "adapters, eval notes.",
        "kind": "domain",
        "public": True,
    },
    {
        "channel_id": "chan:guild:builders",
        "title": "Builders",
        "summary": "General builder collaboration — skills, square, patches.",
        "kind": "guild",
        "public": True,
    },
]


class ChannelError(Exception):
    """Refused by channel rules (membership, caps, rate)."""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class ChannelBook:
    """Durable channels under ``<state-dir>/channels.json``."""

    def __init__(self, directory: str | Path):
        base = Path(directory)
        base.mkdir(parents=True, exist_ok=True)
        self.path = base / "channels.json"
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        # rate: (did, channel_id) -> deque[timestamps]; channel_id -> deque
        self._pub_did: dict[tuple[str, str], deque[float]] = {}
        self._pub_global: dict[str, deque[float]] = {}

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

    def _empty(self) -> dict:
        return {"schema": SCHEMA, "channels": {}, "seeded": False}

    def _load(self) -> dict:
        if not self.path.exists():
            return self._empty()
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeError) as exc:
            raise ChannelError(f"channels ledger unreadable: {exc}")
        if not isinstance(state, dict) or not isinstance(state.get("channels"), dict):
            raise ChannelError("channels ledger structurally invalid")
        state.setdefault("seeded", False)
        return state

    def _save(self, state: dict) -> None:
        payload = json.dumps(state, indent=2, sort_keys=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)

    def ensure_seeded(self) -> None:
        with self._file_lock():
            state = self._load()
            if state.get("seeded") and state["channels"]:
                return
            for seed in _SEED:
                cid = seed["channel_id"]
                if cid in state["channels"]:
                    continue
                state["channels"][cid] = {
                    "channel_id": cid,
                    "title": seed["title"],
                    "summary": seed["summary"],
                    "kind": seed["kind"],
                    "public": bool(seed.get("public", True)),
                    "created_at": _now(),
                    "created_by": "system:seed",
                    "members": {},          # did -> {joined_at}
                    "messages": [],         # scrollback
                    "next_seq": 1,
                }
            state["seeded"] = True
            self._save(state)

    def list_channels(self, *, did: str | None = None,
                      public_only: bool = False) -> list[dict]:
        """Public catalog + channels ``did`` has joined (if provided)."""
        self.ensure_seeded()
        with self._file_lock():
            state = self._load()
            rows = []
            for ch in state["channels"].values():
                is_member = bool(did and did in (ch.get("members") or {}))
                if public_only and not ch.get("public") and not is_member:
                    continue
                if not ch.get("public") and not is_member:
                    continue
                rows.append(self._public_meta(ch, is_member=is_member))
            rows.sort(key=lambda r: r.get("channel_id") or "")
            return rows

    def _public_meta(self, ch: dict, *, is_member: bool) -> dict:
        return {
            "channel_id": ch["channel_id"],
            "title": ch.get("title"),
            "summary": ch.get("summary"),
            "kind": ch.get("kind"),
            "public": bool(ch.get("public")),
            "member_count": len(ch.get("members") or {}),
            "joined": is_member,
            "created_at": ch.get("created_at"),
        }

    def get(self, channel_id: str) -> dict:
        self.ensure_seeded()
        with self._file_lock():
            state = self._load()
            ch = state["channels"].get(channel_id)
            if ch is None:
                raise ChannelError(f"unknown channel: {channel_id}")
            return dict(ch)

    def is_member(self, channel_id: str, did: str) -> bool:
        self.ensure_seeded()
        with self._file_lock():
            state = self._load()
            ch = state["channels"].get(channel_id)
            if ch is None:
                return False
            return did in (ch.get("members") or {})

    def members(self, channel_id: str) -> list[str]:
        self.ensure_seeded()
        with self._file_lock():
            state = self._load()
            ch = state["channels"].get(channel_id)
            if ch is None:
                raise ChannelError(f"unknown channel: {channel_id}")
            return sorted((ch.get("members") or {}).keys())

    def memberships_for(self, did: str) -> list[str]:
        """Channel ids this DID has joined (for SSE topic attach)."""
        self.ensure_seeded()
        with self._file_lock():
            state = self._load()
            out = []
            for cid, ch in state["channels"].items():
                if did in (ch.get("members") or {}):
                    out.append(cid)
            return out

    def subscribe(self, channel_id: str, did: str) -> dict:
        if not did:
            raise ChannelError("did is required")
        self.ensure_seeded()
        with self._file_lock():
            state = self._load()
            ch = state["channels"].get(channel_id)
            if ch is None:
                raise ChannelError(f"unknown channel: {channel_id}")
            members = ch.setdefault("members", {})
            if did not in members:
                if len(members) >= CHANNEL_MEMBER_CAP:
                    raise ChannelError(
                        f"channel membership full ({CHANNEL_MEMBER_CAP}) "
                        "— fail closed")
                members[did] = {"joined_at": _now()}
                state["channels"][channel_id] = ch
                self._save(state)
            return self._public_meta(ch, is_member=True)

    def unsubscribe(self, channel_id: str, did: str) -> dict:
        if not did:
            raise ChannelError("did is required")
        self.ensure_seeded()
        with self._file_lock():
            state = self._load()
            ch = state["channels"].get(channel_id)
            if ch is None:
                raise ChannelError(f"unknown channel: {channel_id}")
            members = ch.setdefault("members", {})
            members.pop(did, None)
            state["channels"][channel_id] = ch
            self._save(state)
            return self._public_meta(ch, is_member=False)

    def _check_rates(self, did: str, channel_id: str) -> None:
        now = time.time()
        key = (did, channel_id)
        q = self._pub_did.setdefault(key, deque())
        while q and now - q[0] > MAIL_RATE_WINDOW:
            q.popleft()
        if len(q) >= CHANNEL_PUB_RATE:
            raise ChannelError(
                f"channel publish rate exceeded ({CHANNEL_PUB_RATE}/"
                f"{int(MAIL_RATE_WINDOW)}s per DID) — fail closed")
        gq = self._pub_global.setdefault(channel_id, deque())
        while gq and now - gq[0] > MAIL_RATE_WINDOW:
            gq.popleft()
        if len(gq) >= CHANNEL_GLOBAL_RATE:
            raise ChannelError(
                f"channel global rate exceeded ({CHANNEL_GLOBAL_RATE}/"
                f"{int(MAIL_RATE_WINDOW)}s) — fail closed")
        q.append(now)
        gq.append(now)

    def publish(self, channel_id: str, did: str, body: str,
                subject: str = "") -> dict:
        """Append a message (member only). Returns the event dict with seq."""
        if not did:
            raise ChannelError("did is required")
        body = body if isinstance(body, str) else ""
        subject = subject if isinstance(subject, str) else ""
        if not body.strip():
            raise ChannelError("body is required")
        if len(body.encode("utf-8")) > MAIL_MAX_BODY:
            raise ChannelError(
                f"body exceeds cap ({MAIL_MAX_BODY} bytes) — fail closed")
        self._check_rates(did, channel_id)
        self.ensure_seeded()
        with self._file_lock():
            state = self._load()
            ch = state["channels"].get(channel_id)
            if ch is None:
                raise ChannelError(f"unknown channel: {channel_id}")
            if did not in (ch.get("members") or {}):
                raise ChannelError(
                    "not a member — a2a_subscribe first (self-scope)")
            seq = int(ch.get("next_seq") or 1)
            msg = {
                "message_id": new_message_id(),
                "kind": "channel",
                "channel_id": channel_id,
                "from_did": did,
                "to_did": None,
                "seq": seq,
                "subject": subject.strip()[:200],
                "body": body,
                "at": _now(),
                "edge": "clean",
                "schema": "euearth-a2a-event/1",
                "attrs": {},
            }
            msgs = ch.setdefault("messages", [])
            msgs.append(msg)
            # scrollback cap (drop oldest)
            if len(msgs) > CHANNEL_SCROLLBACK:
                ch["messages"] = msgs[-CHANNEL_SCROLLBACK:]
            ch["next_seq"] = seq + 1
            state["channels"][channel_id] = ch
            self._save(state)
            return dict(msg)

    def history(self, channel_id: str, did: str, *,
                limit: int = 50, before_seq: int | None = None) -> list[dict]:
        """Scrollback for members only (self-scope)."""
        if not did:
            raise ChannelError("did is required")
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 50
        limit = max(1, min(limit, CHANNEL_SCROLLBACK))
        self.ensure_seeded()
        with self._file_lock():
            state = self._load()
            ch = state["channels"].get(channel_id)
            if ch is None:
                raise ChannelError(f"unknown channel: {channel_id}")
            if did not in (ch.get("members") or {}):
                raise ChannelError(
                    "not a member — history is self-scoped to joiners")
            msgs = list(ch.get("messages") or [])
            if before_seq is not None:
                try:
                    bs = int(before_seq)
                    msgs = [m for m in msgs if int(m.get("seq") or 0) < bs]
                except (TypeError, ValueError):
                    pass
            return msgs[-limit:]
