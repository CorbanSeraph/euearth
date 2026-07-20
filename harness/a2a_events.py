"""A2A event envelope + frozen realtime caps (Wave E, Corban-gated).

Shared by durable stores and the live SSE path so history and push never
drift. Caps are env-overridable; defaults are frozen for v1.
"""
from __future__ import annotations

import os
import time
import uuid
from typing import Any

SCHEMA = "euearth-a2a-event/1"

# Frozen v1 defaults (Corban gate #27) — all env-overridable.
SSE_BUFFER = int(os.environ.get("EUEARTH_A2A_SSE_BUFFER", "64"))
HEARTBEAT_S = float(os.environ.get("EUEARTH_A2A_HEARTBEAT_S", "20"))
# Presence: miss this many heartbeats → offline
HEARTBEAT_MISS = int(os.environ.get("EUEARTH_A2A_HEARTBEAT_MISS", "2"))

# Re-export mail/channel caps for a single docs surface (owned by mailbox/
# future channels modules for enforcement; listed here as the gated table).
MAIL_RATE_MAX = int(os.environ.get("EUEARTH_MAIL_RATE_MAX", "20"))
MAIL_RATE_WINDOW = float(os.environ.get("EUEARTH_MAIL_RATE_WINDOW", "60"))
MAIL_MAX_BODY = int(os.environ.get("EUEARTH_MAIL_MAX_BODY", "2000"))
MULTICAST_FANOUT = int(os.environ.get("EUEARTH_A2A_MULTICAST_FANOUT", "16"))
CHANNEL_PUB_RATE = int(os.environ.get("EUEARTH_A2A_CHAN_PUB_RATE", "10"))
CHANNEL_GLOBAL_RATE = int(os.environ.get("EUEARTH_A2A_CHAN_GLOBAL_RATE", "60"))
CHANNEL_SCROLLBACK = int(os.environ.get("EUEARTH_A2A_CHAN_SCROLLBACK", "500"))
CHANNEL_MEMBER_CAP = int(os.environ.get("EUEARTH_A2A_CHAN_MEMBER_CAP", "500"))

KIND_DM = "dm"
KIND_CHANNEL = "channel"
KIND_SYSTEM = "system"

TOPIC_DM_PREFIX = "dm:"
TOPIC_CHAN_PREFIX = "chan:"
TOPIC_SYSTEM_HOUSE = "system:house"


def dm_topic(did: str) -> str:
    return f"{TOPIC_DM_PREFIX}{did}"


def chan_topic(channel_id: str) -> str:
    """Bus/SSE topic for a channel. channel_id is already ``chan:…``."""
    if not channel_id:
        return TOPIC_CHAN_PREFIX
    if channel_id.startswith(TOPIC_CHAN_PREFIX):
        return channel_id
    return f"{TOPIC_CHAN_PREFIX}{channel_id}"


def new_message_id() -> str:
    return f"msg_{uuid.uuid4().hex[:16]}"


def make_event(
    *,
    kind: str,
    body: str,
    from_did: str | None = None,
    to_did: str | None = None,
    channel_id: str | None = None,
    subject: str = "",
    seq: int | None = None,
    edge: str = "clean",
    attrs: dict | None = None,
    message_id: str | None = None,
) -> dict[str, Any]:
    """Canonical envelope (proposal §4)."""
    if kind not in (KIND_DM, KIND_CHANNEL, KIND_SYSTEM):
        raise ValueError(f"unknown a2a event kind: {kind!r}")
    if edge not in ("clean", "flagged"):
        edge = "clean"
    return {
        "schema": SCHEMA,
        "message_id": message_id or new_message_id(),
        "kind": kind,
        "from_did": from_did,
        "to_did": to_did,
        "channel_id": channel_id,
        "seq": seq,
        "subject": (subject or "")[:200],
        "body": body if isinstance(body, str) else str(body),
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "edge": edge,
        "attrs": dict(attrs or {}),
    }


def format_sse(event_name: str, data: dict, *, event_id: str | None = None) -> str:
    """One SSE event block (text/event-stream)."""
    import json
    lines = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event_name}")
    payload = json.dumps(data, separators=(",", ":"), sort_keys=True)
    # SSE data lines must not contain raw newlines unescaped
    for part in payload.split("\n"):
        lines.append(f"data: {part}")
    lines.append("")
    return "\n".join(lines) + "\n"
