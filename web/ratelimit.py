"""Dependency-free in-memory rate limiting for the PUBLIC HTTP surface.

The backend is exposed on the open internet (Cloudflare tunnel), so the
unauthenticated endpoints need a cheap abuse ceiling (GitHub issue #9). This
is a fixed-window counter keyed on an arbitrary string (client IP or agent
DID) — no Redis, no external dependency, thread-safe, self-pruning.

It is a courtesy/greylist limiter, not a DDoS shield (that is Cloudflare's
job upstream). It stops a single client from hammering request-invite /
validate-delegation / try in a tight loop and filling logs or CPU.
"""
from __future__ import annotations

import threading
import time


class FixedWindowLimiter:
    """Allow at most `limit` events per `window` seconds per key."""

    def __init__(self, limit: int, window: float, *, max_keys: int = 100_000):
        self.limit = int(limit)
        self.window = float(window)
        self.max_keys = int(max_keys)
        self._buckets: dict[str, list[float]] = {}   # key -> [window_start, count]
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """Record one event for `key`; return False if over the limit."""
        now = time.monotonic()
        with self._lock:
            slot = self._buckets.get(key)
            if slot is None or now - slot[0] >= self.window:
                self._buckets[key] = [now, 1.0]
                if len(self._buckets) > self.max_keys:
                    self._prune(now)
                return True
            slot[1] += 1
            return slot[1] <= self.limit

    def _prune(self, now: float) -> None:
        """Drop expired buckets to bound memory (called under the lock)."""
        dead = [k for k, s in self._buckets.items()
                if now - s[0] >= self.window]
        for k in dead:
            self._buckets.pop(k, None)


def client_ip(request) -> str:
    """Best-effort client identity for keying. Behind the Cloudflare tunnel
    `request.client.host` collapses to the tunnel address, so prefer the
    edge-set client-IP headers when present (spoofable, but fine for a
    courtesy limiter)."""
    hdrs = request.headers
    cf = hdrs.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    xff = hdrs.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
