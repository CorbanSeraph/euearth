from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

GENESIS_HASH = "0" * 64


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(_json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def event_hash(event_without_hash: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(event_without_hash).encode("utf-8")).hexdigest()


def make_event(kind: str, payload: Mapping[str, Any], previous_hash: str) -> dict[str, Any]:
    body = {"schema": "euearth-world-event/0", "kind": kind, "previous_hash": previous_hash, "payload": dict(payload)}
    return {**body, "hash": event_hash(body)}


def verify_chain(events: Iterable[Mapping[str, Any]]) -> bool:
    previous = GENESIS_HASH
    for event in events:
        body = {k: v for k, v in event.items() if k != "hash"}
        if event.get("previous_hash") != previous or event.get("hash") != event_hash(body):
            return False
        previous = str(event["hash"])
    return True


class AppendOnlyEventLog:
    """Durable JSONL sink. Existing bytes are never rewritten or truncated."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def read(self) -> tuple[dict[str, Any], ...]:
        if not self.path.exists():
            return ()
        events = tuple(json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line)
        if not verify_chain(events):
            raise ValueError("WorldBook event log hash chain is invalid")
        return events

    def append(self, event: Mapping[str, Any]) -> None:
        current = self.read()
        expected = current[-1]["hash"] if current else GENESIS_HASH
        if event.get("previous_hash") != expected:
            raise ValueError("event does not extend the immutable log")
        if not verify_chain((*current, event)):
            raise ValueError("invalid event hash")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, (canonical_json(event) + "\n").encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
