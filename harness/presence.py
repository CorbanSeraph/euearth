"""PresenceRegistry — who is connected for live A2A push (Wave E PR1).

NOT a global "who's online" board (Corban gate). Presence is only used to
route push to a DID's own SSE connections. Peer visibility stays deferred.

Each connection owns a bounded queue (SSE_BUFFER). On overflow the
connection is marked closed (backpressure) — durable store remains truth.
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field

from harness.a2a_events import HEARTBEAT_MISS, HEARTBEAT_S, SSE_BUFFER, dm_topic


@dataclass
class StreamConnection:
    """One SSE (or future MCP-notif) connection for a DID."""
    did: str
    session_token: str
    queue: queue.Queue
    topics: set[str] = field(default_factory=set)
    connected_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    closed: bool = False
    close_reason: str | None = None

    def touch(self) -> None:
        self.last_seen = time.time()

    def put(self, item: dict) -> bool:
        """Enqueue an event. False → buffer full / closed (caller should drop push)."""
        if self.closed:
            return False
        try:
            self.queue.put_nowait(item)
            return True
        except queue.Full:
            self.closed = True
            self.close_reason = "sse_buffer_overflow"
            return False

    def close(self, reason: str = "closed") -> None:
        self.closed = True
        self.close_reason = reason
        try:
            self.queue.put_nowait({"_control": "close", "reason": reason})
        except queue.Full:
            pass


class PresenceRegistry:
    """DID → set of live StreamConnections. Thread-safe."""

    def __init__(self, *, buffer: int = SSE_BUFFER) -> None:
        self._lock = threading.RLock()
        self._by_did: dict[str, list[StreamConnection]] = {}
        self._buffer = max(1, int(buffer))
        self._closed_all = False

    def connect(self, did: str, session_token: str,
                extra_topics: set[str] | None = None) -> StreamConnection:
        """Register a new live connection. Auto-subscribes to dm:<did>."""
        if not did or not session_token:
            raise ValueError("did and session_token are required")
        if self._closed_all:
            raise RuntimeError("presence registry closed (hard freeze)")
        conn = StreamConnection(
            did=did,
            session_token=session_token,
            queue=queue.Queue(maxsize=self._buffer),
            topics={dm_topic(did)},
        )
        if extra_topics:
            conn.topics |= set(extra_topics)
        with self._lock:
            self._by_did.setdefault(did, []).append(conn)
        return conn

    def disconnect(self, conn: StreamConnection, reason: str = "disconnect") -> None:
        conn.close(reason)
        with self._lock:
            lst = self._by_did.get(conn.did) or []
            self._by_did[conn.did] = [c for c in lst if c is not conn]
            if not self._by_did[conn.did]:
                self._by_did.pop(conn.did, None)

    def heartbeat(self, conn: StreamConnection) -> None:
        if not conn.closed:
            conn.touch()

    def is_online(self, did: str) -> bool:
        """True if at least one non-closed, non-stale connection exists.
        NOT for public export — routing only."""
        now = time.time()
        stale_after = HEARTBEAT_S * HEARTBEAT_MISS
        with self._lock:
            for c in self._by_did.get(did) or []:
                if not c.closed and (now - c.last_seen) <= stale_after:
                    return True
        return False

    def connections_for(self, did: str) -> list[StreamConnection]:
        with self._lock:
            return [c for c in (self._by_did.get(did) or []) if not c.closed]

    def push_to_did(self, did: str, event: dict) -> int:
        """Best-effort push to all live connections of ``did``. Returns delivered count."""
        n = 0
        for c in self.connections_for(did):
            # Self-scope: only deliver if the event targets this DID's topics
            if not self._event_in_scope(c, event):
                continue
            if c.put({"_control": "event", "event": event}):
                n += 1
        return n

    def _event_in_scope(self, conn: StreamConnection, event: dict) -> bool:
        """Law: a connection only receives its DMs + joined channel topics.
        Cross-scope delivery is an automatic FAIL (drop)."""
        kind = event.get("kind")
        if kind == "dm":
            return event.get("to_did") == conn.did
        if kind == "system":
            # House system events only on system:house subscription
            return "system:house" in conn.topics
        if kind == "channel":
            cid = event.get("channel_id")
            if not cid:
                return False
            # Topics are stored as the full channel_id (chan:…)
            return cid in conn.topics or f"chan:{cid}" in conn.topics
        return False

    def subscribe_topic(self, conn: StreamConnection, topic: str) -> None:
        if topic:
            conn.topics.add(topic)

    def unsubscribe_topic(self, conn: StreamConnection, topic: str) -> None:
        conn.topics.discard(topic)

    def close_all(self, reason: str = "hard_freeze") -> int:
        """Hard freeze: close every SSE connection. Returns count closed."""
        self._closed_all = True
        n = 0
        with self._lock:
            all_conns = [c for lst in self._by_did.values() for c in lst]
            self._by_did.clear()
        for c in all_conns:
            if not c.closed:
                c.close(reason)
                n += 1
        return n

    def reopen(self) -> None:
        """Allow new connections after unfreeze."""
        self._closed_all = False

    def online_count(self) -> int:
        """Count of DIDs with a live connection — for health only, not a roster."""
        with self._lock:
            return sum(1 for did in self._by_did if self.is_online(did))
