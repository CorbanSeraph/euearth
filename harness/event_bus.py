"""EventBus — in-process pub/sub for realtime A2A (Wave E PR1).

LocalBus is the founder-scale implementation. A future RedisBus implements
the same surface so tools never rewrite (proposal §2.6).

Topics (v1):
  dm:<did>           — direct messages to a DID
  chan:<channel_id>  — channel fan-out (PR3+)
  system:house       — house nervous system (champion swap, freeze, …)
"""
from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Callable
from typing import Any, Protocol


class EventBus(Protocol):
    def publish(self, topic: str, event: dict) -> None: ...
    def subscribe(self, topic: str, handler: Callable[[str, dict], None]) -> None: ...
    def unsubscribe(self, topic: str, handler: Callable[[str, dict], None]) -> None: ...


class LocalBus:
    """Thread-safe in-process fan-out. Handlers must not block long."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subs: dict[str, list[Callable[[str, dict], None]]] = defaultdict(list)

    def subscribe(self, topic: str, handler: Callable[[str, dict], None]) -> None:
        if not topic or not callable(handler):
            return
        with self._lock:
            handlers = self._subs[topic]
            if handler not in handlers:
                handlers.append(handler)

    def unsubscribe(self, topic: str, handler: Callable[[str, dict], None]) -> None:
        with self._lock:
            handlers = self._subs.get(topic) or []
            try:
                handlers.remove(handler)
            except ValueError:
                pass
            if not handlers and topic in self._subs:
                del self._subs[topic]

    def publish(self, topic: str, event: dict) -> None:
        """Deliver to current subscribers. Best-effort: handler errors are
        swallowed so one bad SSE connection cannot break the bus."""
        if not topic or not isinstance(event, dict):
            return
        with self._lock:
            handlers = list(self._subs.get(topic) or [])
        for h in handlers:
            try:
                h(topic, event)
            except Exception:
                pass

    def topics(self) -> list[str]:
        with self._lock:
            return sorted(self._subs.keys())

    def subscriber_count(self, topic: str) -> int:
        with self._lock:
            return len(self._subs.get(topic) or [])
