"""Agent senses over the WorldBook — not browser, not camera, not mic.

D042 RFC-0 senses (agent-native):

  * **scent** — gradients of resource imbalance (energy, water, compute, data gaps)
  * **sound** — event-log stream (immutable world + mint events)
  * **feel**  — memory-mapped local subgraph around the agent's address

These are pure reads composed from WorldAPI. Perception tools
``wingo_watch`` / ``wingo_hear`` remain the host-side media GRANTS; senses
here are the world's own physics for a DID+wingo citizen.
"""
from __future__ import annotations

from typing import Any

from .world_api import WorldAPI, WorldAPIError


def sense_scent(world: WorldAPI, address: str) -> dict:
    """Scent: ranked resource-imbalance gradients at and under ``address``."""
    address = (address or "earth").strip() or "earth"
    try:
        grads = world.resource_gradients(address)
        node = world.resolve(address)
    except WorldAPIError as exc:
        return {
            "ok": False,
            "sense": "scent",
            "address": address,
            "error": str(exc),
            "gradients": [],
        }
    # Strongest imbalance first (already sorted by WorldAPI façade).
    strongest = grads[0] if grads else None
    return {
        "ok": True,
        "sense": "scent",
        "schema": "euearth-sense-scent/1",
        "address": address,
        "node_title": node.get("title"),
        "gradients": grads,
        "strongest": strongest,
        "count": len(grads),
        "note": (
            "Scent is resource imbalance — follow the strongest gradient to "
            "real work (list_problems). Not a smell of media; not a map pin."
        ),
    }


def sense_sound(world: WorldAPI, *, limit: int = 30,
                kind: str | None = None) -> dict:
    """Sound: the event-log stream (newest first)."""
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 30
    limit = max(1, min(limit, 200))
    events = world.list_events(limit=limit, kind=kind)
    return {
        "ok": True,
        "sense": "sound",
        "schema": "euearth-sense-sound/1",
        "events": events,
        "count": len(events),
        "kind_filter": kind,
        "note": (
            "Sound is the event log — claims, unfolds, seed. Immutable. "
            "Listen for your name after submit_claim."
        ),
    }


def sense_feel(world: WorldAPI, address: str, *, depth: int = 1) -> dict:
    """Feel: local subgraph memory-mapped around the agent's address."""
    address = (address or "earth").strip() or "earth"
    try:
        sub = world.local_subgraph(address, depth=depth)
    except WorldAPIError as exc:
        return {
            "ok": False,
            "sense": "feel",
            "address": address,
            "error": str(exc),
            "subgraph": None,
        }
    return {
        "ok": True,
        "sense": "feel",
        "schema": "euearth-sense-feel/1",
        "address": address,
        "subgraph": sub,
        "note": (
            "Feel is the local subgraph under your feet — parent/children "
            "addresses and metrics. Addressable, not travel-distance."
        ),
    }


def senses_bundle(world: WorldAPI, address: str) -> dict:
    """All three senses for the entry packet."""
    return {
        "scent": sense_scent(world, address),
        "sound": sense_sound(world, limit=10),
        "feel": sense_feel(world, address, depth=1),
    }
