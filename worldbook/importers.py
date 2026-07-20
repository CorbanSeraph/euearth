"""Normalized import pipeline for GADM, OSM, and open metrics.

Network retrieval is intentionally outside this module. Callers pin downloads,
record checksums in the source registry, then pass decoded records here. This
keeps builds reproducible and makes the license gate unavoidable.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from .sources import SourceRegistry


def import_gadm_admin(records: Iterable[Mapping[str, Any]], registry: SourceRegistry, *, use: str) -> tuple[dict[str, Any], ...]:
    registry.require("gadm-4.1", use=use)
    result = []
    for row in records:
        if not row.get("GID_1") or not row.get("NAME_1"):
            raise ValueError("GADM admin-1 record requires GID_1 and NAME_1")
        geometry = row.get("geometry")
        if not isinstance(geometry, Mapping) or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            raise ValueError("GADM boundary requires GeoJSON Polygon or MultiPolygon geometry")
        result.append({"code": str(row["GID_1"]), "name": str(row["NAME_1"]), "geometry": row.get("geometry"), "source_ids": ["gadm-4.1"]})
    return tuple(sorted(result, key=lambda item: item["code"]))


def import_osm_features(records: Iterable[Mapping[str, Any]], registry: SourceRegistry) -> tuple[dict[str, Any], ...]:
    registry.require("osm", use="redistribution")
    result = []
    for row in records:
        if row.get("type") not in {"node", "way", "relation"} or not isinstance(row.get("id"), int):
            raise ValueError("OSM record requires integer id and node/way/relation type")
        result.append({"external_id": f"osm:{row['type']}/{row['id']}", "tags": dict(row.get("tags", {})), "source_ids": ["osm"]})
    return tuple(sorted(result, key=lambda item: item["external_id"]))


def join_open_metrics(
    admin: Iterable[Mapping[str, Any]],
    metrics: Iterable[Mapping[str, Any]],
    registry: SourceRegistry,
    *, source_id: str,
) -> tuple[dict[str, Any], ...]:
    source = registry.require(source_id, use="redistribution")
    by_code = {str(row["code"]): row for row in metrics}
    result = []
    for record in admin:
        item = dict(record)
        row = by_code.get(str(record["code"]))
        if row:
            item["metrics"] = {
                key: {**dict(value), "source_id": source_id, "source_url": source["url"]}
                for key, value in row["metrics"].items()
            }
            item["source_ids"] = sorted(set(item.get("source_ids", ())) | {source_id})
        result.append(item)
    return tuple(result)
