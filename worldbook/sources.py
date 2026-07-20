from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

ALLOWED_LICENSES = frozenset({"ODbL-1.0", "etalab-2.0", "CC-BY-4.0", "CC0-1.0", "PDDL-1.0"})


@dataclass(frozen=True)
class SourceRegistry:
    sources: Mapping[str, Mapping[str, Any]]

    @classmethod
    def from_mapping(cls, sources: Mapping[str, Mapping[str, Any]]) -> "SourceRegistry":
        return cls(sources=sources)

    def require(self, source_id: str, *, use: str = "internal") -> Mapping[str, Any]:
        try:
            source = self.sources[source_id]
        except KeyError as exc:
            raise ValueError(f"unregistered source: {source_id}") from exc
        required = {"title", "url", "license", "retrieved_at", "attribution", "redistributable"}
        missing = required - set(source)
        if missing:
            raise ValueError(f"source {source_id} missing registry fields: {sorted(missing)}")
        if use == "redistribution" and not source["redistributable"]:
            raise PermissionError(f"source {source_id} is not cleared for redistribution")
        if source["redistributable"] and source["license"] not in ALLOWED_LICENSES:
            raise PermissionError(f"source {source_id} has an unapproved redistribution license")
        return source

    def gate_pack(self, pack: Mapping[str, Any], *, use: str) -> None:
        declared = set(pack.get("included_sources", ()))
        for source_id in declared:
            self.require(source_id, use=use)
        for node in pack.get("nodes", ()):
            for source_id in node.get("properties", {}).get("source_ids", ()):
                if source_id not in declared:
                    raise ValueError(f"node cites undeclared pack source {source_id}")
                self.require(source_id, use=use)
        for records in pack.get("skeletons", {}).values():
            for record in records:
                for source_id in record.get("source_ids", ()):
                    if source_id not in declared:
                        raise ValueError(f"skeleton cites undeclared pack source {source_id}")
                    self.require(source_id, use=use)
