"""WorldBook → stateful WorldAPI façade (D042 adapter for Darkk D041 pure API).

Darkk owns pure functions over immutable WorldBook snapshots::

    resolve(book, address) -> Mapping | None
    children(book, address) -> tuple[Mapping, ...]
    unfold(book, address, request=...) -> UnfoldResult  # new book + event
    list_problems(book, region_id, status="open") -> tuple[Problem, ...]
    submit_observation(book, observation) -> Submission

Agent runtime needs a **stateful** façade (session-held book, claim flips,
resource gradients for scent, event tail for sound). This module is that
adapter.

Guards (charter + RFC-0):
  * WorldBook never mints Gold / holds standing / currency
  * ``flip_problem`` lives on the Mint/agent side of this façade only
  * couple points = problem ids + addresses + events

v3 reconcile: ``open_world_api()`` prefers this façade whenever the
``worldbook`` pack is importable (France / INSEE). Stub remains offline
fallback only. Factory helper: ``try_open_worldbook_api()``.
"""
from __future__ import annotations

import hashlib
import os
import threading
import time
import uuid
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from .world_api import (
    EVENT_SCHEMA,
    SCHEMA,
    WORLD_SYSTEM_DID,
    WorldAPIError,
)

# Entry aliases — D042 stub used path slashes; D041 France pack uses earth:adm/FR.
ENTRY_ALIASES: dict[str, str] = {
    "earth/eu/fr": "earth:adm/FR",
    "earth/eu/fr/": "earth:adm/FR",
    "france": "earth:adm/FR",
    "fr": "earth:adm/FR",
}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _as_mapping(obj: Any) -> dict:
    if obj is None:
        return {}
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    if isinstance(obj, Mapping):
        return dict(obj)
    # duck Problem / simple namespace
    out = {}
    for key in (
        "id", "problem_id", "region_id", "title", "statement", "status",
        "metric", "value", "unit", "source_id", "source_url", "observed_at",
        "summary", "domain", "address", "sources",
    ):
        if hasattr(obj, key):
            out[key] = getattr(obj, key)
    return out


def _normalize_node(node: Mapping[str, Any] | None) -> dict | None:
    if node is None:
        return None
    n = dict(node)
    address = n.get("address") or n.get("id")
    if address:
        n.setdefault("id", address)
        n.setdefault("address", address)
    # title: D041 France nodes use properties.name
    if "title" not in n:
        props = n.get("properties") or {}
        if isinstance(props, Mapping) and props.get("name"):
            n["title"] = props["name"]
        else:
            n["title"] = address or "node"
    # relations: D041 parent is a list; children may be absent (use pure children())
    rel = dict(n.get("relations") or {})
    parent = rel.get("parent")
    if isinstance(parent, (list, tuple)):
        rel["parent"] = parent[0] if parent else None
        rel["parents"] = list(parent)
    n["relations"] = rel
    # flatten metrics for scent when nested {value, unit, ...}
    props = dict(n.get("properties") or {})
    metrics = props.get("metrics")
    if isinstance(metrics, Mapping):
        flat: dict[str, Any] = {}
        for k, v in metrics.items():
            if isinstance(v, Mapping) and "value" in v:
                flat[k] = v["value"]
                # keep unit hints on side channel for gradients
                if "unit" in v:
                    flat[f"{k}__unit"] = v["unit"]
            else:
                flat[k] = v
        props["metrics"] = flat
        props["metrics_raw"] = dict(metrics)
    n["properties"] = props
    return n


def problem_to_agent_dict(problem: Any, *, default_address: str = "") -> dict:
    """Map D041 Problem (dataclass or mapping) → euearth-problem/1 agent shape."""
    p = _as_mapping(problem)
    pid = p.get("id") or p.get("problem_id") or ""
    region = p.get("region_id") or p.get("address") or default_address
    metric_name = p.get("metric")
    metric_block: Any
    if isinstance(metric_name, Mapping):
        metric_block = metric_name
    else:
        metric_block = {
            "name": metric_name,
            "value": p.get("value"),
            "unit": p.get("unit"),
        }
    sources = p.get("sources")
    if not sources:
        sources = []
        if p.get("source_id") or p.get("source_url"):
            sid = str(p.get("source_id") or "source")
            # Prefer human titles for known France pack ids (never stub notes).
            pretty = {
                "insee-pop-2023": "INSEE Populations des régions en 2023",
                "gadm-4.1": "GADM 4.1 administrative boundaries",
                "osm": "OpenStreetMap",
            }.get(sid, sid)
            sources = [{
                "name": pretty,
                "url": p.get("source_url") or "",
                "id": sid,
                "source_id": sid,
            }]
    # Domain from metric family when pure Problem has none.
    domain = p.get("domain")
    if not domain:
        mname = metric_block.get("name") if isinstance(metric_block, dict) else metric_name
        mname = str(mname or "").lower()
        if any(k in mname for k in ("population", "density", "energy", "water", "grid")):
            domain = "iron"
        elif any(k in mname for k in ("data", "open_data", "compute")):
            domain = "quicksilver"
        else:
            domain = "iron"
    return {
        "schema": "euearth-problem/1",
        "problem_id": pid,
        "title": p.get("title") or pid,
        "domain": domain,
        "address": region,
        "status": p.get("status") or "open",
        "metric": metric_block,
        "sources": sources,
        "summary": p.get("statement") or p.get("summary") or "",
        "claim_id": p.get("claim_id"),
        "claimed_by": p.get("claimed_by"),
        "withdrawn": (p.get("status") == "withdrawn") or bool(p.get("withdrawn")),
        "observed_at": p.get("observed_at"),
        "worldbook": True,
        "evidence_pack": "france-insee",
    }


class PureWorldAPI(Protocol):
    """Minimal pure surface matching Darkk worldbook.api."""

    def resolve(self, book: Any, address: str) -> Mapping[str, Any] | None: ...
    def children(self, book: Any, address: str) -> tuple: ...
    def unfold(self, book: Any, address: str, request: Any = None) -> Any: ...
    def list_problems(self, book: Any, region_id: str, status: str = "open") -> tuple: ...


class WorldBookFacade:
    """Stateful WorldAPI over an injected pure WorldBook module + session book.

    Claim flips and agent events are local to this façade (Mint side).
    Unfold/observation snapshots advance ``self.book`` only.
    """

    def __init__(
        self,
        book: Any,
        pure: Any,
        *,
        default_region: str | None = None,
        directory: str | Path | None = None,
    ):
        self._pure = pure
        self._book = book
        self._lock = threading.RLock()
        self._flips: dict[str, dict] = {}  # problem_id → agent problem dict overrides
        self._events: list[dict] = []
        self._default_region = default_region or self._guess_default_region(book, pure)
        self.root = Path(directory) if directory else None
        # seed a façade-local genesis event
        self._events.append({
            "schema": EVENT_SCHEMA,
            "event_id": f"evt_{uuid.uuid4().hex[:12]}",
            "kind": "worldbook.facade_open",
            "at": _now(),
            "agent_did": WORLD_SYSTEM_DID,
            "payload": {
                "default_region": self._default_region,
                "schema": SCHEMA,
                "note": "WorldBookFacade — pure WorldAPI + Mint-side claim state",
            },
        })

    @staticmethod
    def _guess_default_region(book: Any, pure: Any) -> str:
        for candidate in ("earth:adm/FR", "earth/eu/fr", "earth"):
            try:
                if pure.resolve(book, candidate) is not None:
                    return candidate
            except Exception:
                continue
        # fall back to first node address if book exposes nodes
        nodes = getattr(book, "nodes", None)
        if isinstance(nodes, Mapping) and nodes:
            return next(iter(nodes.keys()))
        return "earth:adm/FR"

    def _canon(self, address: str) -> str:
        address = (address or "").strip()
        if not address:
            raise WorldAPIError("address is required")
        return ENTRY_ALIASES.get(address, address)

    @property
    def book(self) -> Any:
        return self._book

    @property
    def default_region(self) -> str:
        return self._default_region

    # -- WorldAPI ----------------------------------------------------------

    def resolve(self, address: str) -> dict:
        address = self._canon(address)
        with self._lock:
            node = self._pure.resolve(self._book, address)
        if node is None:
            raise WorldAPIError(f"unknown address: {address}")
        out = _normalize_node(node)
        assert out is not None
        return out

    def children(self, address: str) -> list[dict]:
        address = self._canon(address)
        with self._lock:
            kids = self._pure.children(self._book, address)
        return [_normalize_node(k) for k in kids]  # type: ignore[misc]

    def unfold(self, address: str) -> dict:
        address = self._canon(address)
        with self._lock:
            # D041 UnfoldRequest is optional with defaults
            try:
                result = self._pure.unfold(self._book, address)
            except TypeError:
                result = self._pure.unfold(self._book, address, None)
            except KeyError as exc:
                raise WorldAPIError(f"unknown address: {address}") from exc
            except ValueError as exc:
                raise WorldAPIError(str(exc)) from exc
            new_book = getattr(result, "book", None)
            if new_book is not None:
                self._book = new_book
            event = getattr(result, "event", None)
            if event is not None:
                self._events.append({
                    "schema": EVENT_SCHEMA,
                    "event_id": f"evt_{uuid.uuid4().hex[:12]}",
                    "kind": "world.unfolded",
                    "at": _now(),
                    "agent_did": WORLD_SYSTEM_DID,
                    "payload": dict(event) if isinstance(event, Mapping) else {
                        "raw": str(event),
                    },
                })
            nodes = getattr(result, "nodes", ()) or ()
            node = self._pure.resolve(self._book, address)
            kids = [_normalize_node(n) for n in nodes] or self.children(address)
        return {
            "ok": True,
            "address": address,
            "node": _normalize_node(node),
            "children": kids,
            "deterministic": True,
            "note": "WorldBook pure unfold — skeleton only, no pre-authored towns.",
        }

    def list_problems(
        self,
        *,
        status: str | None = None,
        domain: str | None = None,
        limit: int = 50,
        region_id: str | None = None,
    ) -> list[dict]:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 50
        limit = max(1, min(limit, 200))
        region = self._canon(region_id or self._default_region)
        want = status or "open"
        with self._lock:
            try:
                raw = self._pure.list_problems(self._book, region, want)
            except TypeError:
                raw = self._pure.list_problems(self._book, region)
            except KeyError:
                # region missing — try default; else empty
                if region != self._default_region:
                    try:
                        raw = self._pure.list_problems(
                            self._book, self._default_region, want
                        )
                    except Exception:
                        raw = ()
                else:
                    raw = ()
            # also surface problems from unfolded children when region has none
            problems = [problem_to_agent_dict(p, default_address=region) for p in raw]
            if not problems and want in ("open", "all", None):
                try:
                    for child in self._pure.children(self._book, region):
                        cid = (child.get("address") or child.get("id") or "")
                        if not cid:
                            continue
                        try:
                            child_probs = self._pure.list_problems(
                                self._book, cid, "open"
                            )
                        except Exception:
                            continue
                        for p in child_probs:
                            problems.append(
                                problem_to_agent_dict(p, default_address=cid)
                            )
                except Exception:
                    pass
            # apply Mint-side flips
            out: list[dict] = []
            for p in problems:
                pid = p.get("problem_id")
                if pid and pid in self._flips:
                    p = dict(self._flips[pid])
                if p.get("withdrawn") and want == "open":
                    continue
                if want not in (None, "all") and p.get("status") != want:
                    continue
                if domain and p.get("domain") != domain:
                    continue
                out.append(p)
            return out[:limit]

    def get_problem(self, problem_id: str) -> dict | None:
        problem_id = (problem_id or "").strip()
        if not problem_id:
            return None
        with self._lock:
            if problem_id in self._flips:
                return dict(self._flips[problem_id])
            # scan open + all via default region + children
            for p in self.list_problems(status="all", limit=200):
                if p.get("problem_id") == problem_id:
                    return p
        return None

    def flip_problem(
        self,
        problem_id: str,
        *,
        status: str,
        agent_did: str,
        claim_id: str,
    ) -> dict:
        """Mint-side flip only — never writes Gold into WorldBook."""
        status = (status or "").strip()
        if status not in ("open", "in_fire", "held", "withdrawn", "corrected"):
            raise WorldAPIError(f"invalid problem status: {status!r}")
        if not agent_did or not claim_id:
            raise WorldAPIError("agent_did and claim_id required")
        with self._lock:
            existing = self.get_problem(problem_id)
            if existing is None:
                raise WorldAPIError(f"unknown problem: {problem_id}")
            if existing.get("status") == "in_fire" and status == "in_fire":
                raise WorldAPIError(
                    "problem already has a claim in the fire "
                    "(Art. III — one mint path per problem)"
                )
            if existing.get("withdrawn") or existing.get("status") == "withdrawn":
                raise WorldAPIError("problem is withdrawn")
            flipped = dict(existing)
            flipped["status"] = status
            flipped["claimed_by"] = agent_did
            flipped["claim_id"] = claim_id
            flipped["flipped_at"] = _now()
            flipped["mint_side_only"] = True
            self._flips[problem_id] = flipped
            return dict(flipped)

    def append_event(self, event: dict) -> dict:
        rec = dict(event)
        rec.setdefault("schema", EVENT_SCHEMA)
        rec.setdefault("event_id", f"evt_{uuid.uuid4().hex[:12]}")
        rec.setdefault("at", _now())
        with self._lock:
            self._events.append(rec)
        return rec

    def list_events(self, *, limit: int = 50, kind: str | None = None) -> list[dict]:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 50
        limit = max(1, min(limit, 500))
        with self._lock:
            rows = list(self._events)
            # also surface pure book events if present
            book_events = getattr(self._book, "events", None) or ()
            for ev in book_events:
                if isinstance(ev, Mapping):
                    rows.append(dict(ev))
        if kind:
            rows = [r for r in rows if r.get("kind") == kind]
        return rows[-limit:][::-1]

    def resource_gradients(self, address: str) -> list[dict]:
        try:
            node = self.resolve(address)
        except WorldAPIError:
            return []
        metrics = dict((node.get("properties") or {}).get("metrics") or {})
        grads: list[dict] = []

        def add(kind: str, key: str, *, unit: str, imbalance_fn, direction_fn, intensity_fn):
            if key not in metrics:
                return
            try:
                v = float(metrics[key])
            except (TypeError, ValueError):
                return
            grads.append({
                "kind": kind,
                "address": address if address.startswith("earth") else node.get("address"),
                "value": v,
                "unit": metrics.get(f"{key}__unit") or unit,
                "imbalance": imbalance_fn(v),
                "direction": direction_fn(v),
                "intensity": intensity_fn(v),
            })

        # D042 stub metrics
        add(
            "energy_balance", "energy_balance_mwh", unit="mwh",
            imbalance_fn=lambda v: abs(v),
            direction_fn=lambda v: "deficit" if v < 0 else "surplus",
            intensity_fn=lambda v: min(1.0, abs(v) / 5000.0),
        )
        add(
            "water_stress", "water_stress_index", unit="index_0_1",
            imbalance_fn=lambda v: max(0.0, v - 0.50),
            direction_fn=lambda v: "stress" if v > 0.50 else "ok",
            intensity_fn=lambda v: min(1.0, max(0.0, v)),
        )
        add(
            "compute_demand", "compute_demand_index", unit="index_0_1",
            imbalance_fn=lambda v: max(0.0, v - 0.70),
            direction_fn=lambda v: "high" if v > 0.70 else "ok",
            intensity_fn=lambda v: min(1.0, v),
        )
        add(
            "open_data_gaps", "open_data_gaps", unit="count",
            imbalance_fn=lambda v: v,
            direction_fn=lambda v: "gap" if v > 0 else "ok",
            intensity_fn=lambda v: min(1.0, v / 5.0),
        )
        # D041 France metrics
        add(
            "population_density", "population_density", unit="persons_per_km2",
            imbalance_fn=lambda v: max(0.0, v - 150.0),
            direction_fn=lambda v: "high" if v >= 150 else "ok",
            intensity_fn=lambda v: min(1.0, v / 1000.0),
        )
        add(
            "population_change", "population_change_annual", unit="rate",
            imbalance_fn=lambda v: abs(min(0.0, v)),
            direction_fn=lambda v: "decline" if v <= 0 else "growth",
            intensity_fn=lambda v: min(1.0, abs(v) * 10.0),
        )
        add(
            "population", "population", unit="persons",
            imbalance_fn=lambda v: 0.0,
            direction_fn=lambda v: "present",
            intensity_fn=lambda v: min(1.0, v / 1e8) if v else 0.0,
        )

        for child in self.children(node.get("address") or address):
            cm = dict((child.get("properties") or {}).get("metrics") or {})
            for key, kind, unit, thr in (
                ("energy_balance_mwh", "energy_balance", "mwh", 5000.0),
                ("population_density", "population_density", "persons_per_km2", 1000.0),
            ):
                if key not in cm:
                    continue
                try:
                    v = float(cm[key])
                except (TypeError, ValueError):
                    continue
                grads.append({
                    "kind": kind,
                    "address": child.get("address"),
                    "value": v,
                    "unit": unit,
                    "imbalance": abs(v) if key.startswith("energy") else max(0.0, v - 150.0),
                    "direction": (
                        ("deficit" if v < 0 else "surplus")
                        if key.startswith("energy")
                        else ("high" if v >= 150 else "ok")
                    ),
                    "intensity": min(1.0, abs(v) / thr),
                    "via": "child",
                })
        grads.sort(key=lambda g: g.get("imbalance", 0), reverse=True)
        return grads

    def local_subgraph(self, address: str, *, depth: int = 1) -> dict:
        try:
            depth = int(depth)
        except (TypeError, ValueError):
            depth = 1
        depth = max(0, min(depth, 3))
        seen: dict[str, dict] = {}
        edges: list[dict] = []

        def walk(addr: str, d: int) -> None:
            if addr in seen:
                return
            try:
                node = self.resolve(addr)
            except WorldAPIError:
                return
            seen[addr] = {
                "id": node.get("id"),
                "address": node.get("address"),
                "type": node.get("type"),
                "title": node.get("title"),
                "metrics": dict(
                    (node.get("properties") or {}).get("metrics") or {}
                ),
            }
            if d <= 0:
                return
            parent = (node.get("relations") or {}).get("parent")
            if parent:
                edges.append({"from": addr, "to": parent, "rel": "parent"})
                walk(str(parent), d - 1)
            # D041: children via pure children(); also honor explicit list
            child_ids = list((node.get("relations") or {}).get("children") or [])
            if not child_ids:
                try:
                    child_ids = [
                        c.get("address") or c.get("id")
                        for c in self.children(addr)
                    ]
                except WorldAPIError:
                    child_ids = []
            for cid in child_ids:
                if not cid:
                    continue
                edges.append({"from": addr, "to": cid, "rel": "child"})
                walk(str(cid), d - 1)

        walk(self._canon(address), depth)
        return {
            "schema": "euearth-subgraph/1",
            "origin": self._canon(address),
            "depth": depth,
            "nodes": list(seen.values()),
            "edges": edges,
            "count": len(seen),
            "note": "Local feel — addressable graph, not a navigable map.",
        }


def try_open_worldbook_api(
    directory: str | Path | None = None,
) -> WorldBookFacade | None:
    """If ``worldbook`` pack is importable, open France pack under the façade.

    Returns None when D041 code is not on this tree — caller keeps StubWorldAPI.
    Respects ``EUEARTH_WORLDAPI=stub`` to force offline isolation.
    """
    force = os.environ.get("EUEARTH_WORLDAPI", "").strip().lower()
    if force in ("stub", "0", "false", "no"):
        return None
    try:
        from worldbook import load_country_pack  # type: ignore
        import worldbook as wb  # type: ignore
    except ImportError:
        return None
    book = load_country_pack()
    return WorldBookFacade(
        book,
        wb,
        default_region="earth:adm/FR",
        directory=directory,
    )


def open_world_api_preferring_worldbook(directory: str | Path | None = None):
    """Prefer live WorldBook when present; else stub (same as open_world_api)."""
    from .world_api import StubWorldAPI

    facade = try_open_worldbook_api(directory)
    if facade is not None:
        return facade
    return StubWorldAPI(directory)
