from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

SCHEMA = "euearth-worldbook/0"
FORBIDDEN_ECONOMY_KEYS = frozenset(
    {
        "balance", "balances", "currency", "fiat", "gift", "gifts", "gold",
        "kabad", "mint", "money", "sovereign_treasury", "standing", "wallet",
    }
)
NODE_TYPES = frozenset({"planet", "admin_country", "admin_region", "place", "feature"})


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({str(k): _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_thaw(v) for v in value]
    return copy.deepcopy(value)


def validate_node(node: Mapping[str, Any]) -> None:
    required = {"id", "address", "type", "properties", "relations"}
    missing = required - set(node)
    if missing:
        raise ValueError(f"node missing fields: {sorted(missing)}")
    if node["id"] != node["address"] or not str(node["address"]).startswith("earth:"):
        raise ValueError("node id must equal its canonical earth: address")
    if node["type"] not in NODE_TYPES:
        raise ValueError(f"unsupported node type: {node['type']!r}")
    if not isinstance(node["properties"], Mapping) or not isinstance(node["relations"], Mapping):
        raise ValueError("properties and relations must be objects")
    forbidden = FORBIDDEN_ECONOMY_KEYS.intersection(str(k).lower() for k in node["properties"])
    if forbidden:
        raise ValueError(f"economy state belongs in StateBook, not WorldBook: {sorted(forbidden)}")
    for relation, targets in node["relations"].items():
        if not isinstance(relation, str) or not isinstance(targets, (list, tuple)):
            raise ValueError("each relation must map to an address list")
        if any(not isinstance(target, str) or not target.startswith("earth:") for target in targets):
            raise ValueError("relation targets must be earth: addresses")


@dataclass(frozen=True)
class WorldBook:
    """Immutable graph snapshot consumed by the pure WorldAPI functions."""

    nodes: Mapping[str, Mapping[str, Any]]
    skeletons: Mapping[str, tuple[Mapping[str, Any], ...]]
    sources: Mapping[str, Mapping[str, Any]]
    events: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    schema: str = SCHEMA

    def __post_init__(self) -> None:
        if self.schema != SCHEMA:
            raise ValueError(f"unsupported WorldBook schema {self.schema!r}")
        mutable_nodes = {address: _thaw(node) for address, node in self.nodes.items()}
        for address, node in mutable_nodes.items():
            validate_node(node)
            if address != node["address"]:
                raise ValueError("node index key must equal node address")
        object.__setattr__(self, "nodes", _freeze(mutable_nodes))
        object.__setattr__(self, "skeletons", _freeze(_thaw(self.skeletons)))
        object.__setattr__(self, "sources", _freeze(_thaw(self.sources)))
        object.__setattr__(self, "events", tuple(_freeze(_thaw(e)) for e in self.events))

    def replace(
        self,
        *,
        nodes: Mapping[str, Mapping[str, Any]] | None = None,
        events: tuple[Mapping[str, Any], ...] | None = None,
    ) -> "WorldBook":
        return WorldBook(
            nodes=_thaw(self.nodes) if nodes is None else nodes,
            skeletons=_thaw(self.skeletons),
            sources=_thaw(self.sources),
            events=self.events if events is None else events,
        )


def load_country_pack(path: str | Path | None = None) -> WorldBook:
    pack_path = Path(path) if path else Path(__file__).with_name("data") / "france.json"
    payload = json.loads(pack_path.read_text(encoding="utf-8"))
    from .sources import SourceRegistry

    registry = SourceRegistry.from_mapping(payload["sources"])
    registry.gate_pack(payload, use="redistribution")
    return WorldBook(
        nodes={node["address"]: node for node in payload["nodes"]},
        skeletons=payload.get("skeletons", {}),
        sources=payload["sources"],
    )


def mutable(value: Any) -> Any:
    """Return a detached JSON-compatible copy of an immutable book value."""

    return _thaw(value)
