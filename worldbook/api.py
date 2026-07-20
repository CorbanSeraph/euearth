"""Published WorldAPI RFC-0 — pure functions over immutable WorldBook snapshots."""
from __future__ import annotations

import hashlib
import math
from dataclasses import asdict
from typing import Any, Mapping

from .book import WorldBook, mutable, validate_node
from .events import GENESIS_HASH, make_event
from .models import Observation, Problem, Submission, UnfoldRequest, UnfoldResult
from .seeder import seed_problems
from .sources import SourceRegistry


def resolve(book: WorldBook, address: str) -> Mapping[str, Any] | None:
    node = book.nodes.get(address)
    return None if node is None else mutable(node)


def children(book: WorldBook, address: str) -> tuple[Mapping[str, Any], ...]:
    result = [mutable(node) for node in book.nodes.values() if address in node["relations"].get("parent", ())]
    return tuple(sorted(result, key=lambda node: node["address"]))


def _node_from_skeleton(parent: str, record: Mapping[str, Any]) -> dict[str, Any]:
    code = str(record["code"])
    address = f"{parent}/{code}"
    source_ids = sorted(str(s) for s in record["source_ids"])
    properties = {k: mutable(v) for k, v in record.items() if k not in {"code", "source_ids"}}
    properties["source_ids"] = source_ids
    properties["unfold_fingerprint"] = hashlib.sha256(
        (address + "|" + "|".join(source_ids)).encode("utf-8")
    ).hexdigest()
    node = {
        "id": address,
        "address": address,
        "type": "admin_region",
        "properties": properties,
        "relations": {"parent": [parent]},
    }
    validate_node(node)
    return node


def unfold(book: WorldBook, address: str, request: UnfoldRequest = UnfoldRequest()) -> UnfoldResult:
    if request.depth != 1:
        raise ValueError("RFC-0 unfolds exactly one imported administrative level per call")
    if request.limit < 1 or request.limit > 1000:
        raise ValueError("unfold limit must be between 1 and 1000")
    if address not in book.nodes:
        raise KeyError(address)
    records = book.skeletons.get(address, ())
    materialized = tuple(_node_from_skeleton(address, record) for record in records[: request.limit])
    new_nodes = mutable(book.nodes)
    changed = False
    for node in materialized:
        existing = new_nodes.get(node["address"])
        if existing is not None and existing != node:
            raise ValueError(f"determinism violation at {node['address']}")
        if existing is None:
            changed = True
            new_nodes[node["address"]] = node
    event = None
    events = book.events
    if changed:
        previous = events[-1]["hash"] if events else GENESIS_HASH
        event = make_event("world.unfolded", {
            "address": address,
            "depth": request.depth,
            "limit": request.limit,
            "node_ids": [node["id"] for node in materialized],
        }, previous)
        events = (*events, event)
    return UnfoldResult(book=book.replace(nodes=new_nodes, events=events), nodes=materialized, event=event)


def list_problems(book: WorldBook, region_id: str, status: str = "open") -> tuple[Problem, ...]:
    if status not in {"open", "withdrawn", "all"}:
        raise ValueError("status must be open, withdrawn, or all")
    node = book.nodes.get(region_id)
    if node is None:
        raise KeyError(region_id)
    seeded = seed_problems(node)
    state = {problem.id: problem for problem in seeded}
    for event in book.events:
        if event.get("kind") == "world.problem_withdrawn":
            problem_id = event["payload"].get("problem_id")
            if problem_id in state:
                state[problem_id] = Problem(**{**asdict(state[problem_id]), "status": "withdrawn"})
    return tuple(p for p in state.values() if status == "all" or p.status == status)


def submit_observation(book: WorldBook, observation: Observation) -> Submission:
    if observation.node_id not in book.nodes:
        raise KeyError(observation.node_id)
    if not observation.metric or not observation.unit or not observation.observer_id:
        raise ValueError("metric, unit, and observer_id are required")
    if isinstance(observation.value, bool) or not math.isfinite(float(observation.value)):
        raise ValueError("observation value must be finite")
    SourceRegistry.from_mapping(book.sources).require(observation.source_id, use="internal")
    payload = asdict(observation)
    previous = book.events[-1]["hash"] if book.events else GENESIS_HASH
    event = make_event("world.observation.submitted", payload, previous)
    return Submission(book=book.replace(events=(*book.events, event)), event=event)
