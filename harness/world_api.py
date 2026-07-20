"""WorldAPI — addressable planet graph for agent-native work (D041/D042).

Darkk owns the real WorldBook engine (D041 pure functions). Darth (D042) owns
the agent runtime that CALLS this surface via a thin stateful adapter.

WorldAPI is SEPARATE from StateBook (standing). Couple by ids + events only —
never merge stores. No browser, no DOM, no travel-distance.

## Reconcile (v3): Darkk pure signature → agent method protocol

Darkk's published pure API (immutable snapshot style)::

    resolve(book, address) -> Mapping | None
    children(book, address) -> tuple[Mapping, ...]
    unfold(book, address, request=UnfoldRequest()) -> UnfoldResult  # new book+event
    list_problems(book, region_id, status="open") -> tuple[Problem, ...]
    submit_observation(book, observation) -> Submission

Agent runtime needs a **stateful** façade (session-held book, claim flips,
resource gradients for scent, event tail for sound). That adapter lives in
``harness.worldbook_facade.WorldBookFacade``:

  * holds a WorldBook snapshot (+ façade event tail)
  * maps resolve/children/unfold/list_problems onto Darkk pure functions
  * keeps ``flip_problem`` / claim events on the **Mint/agent** side (Art. III–V)
    — WorldBook must not mint Gold (no standing/currency in WorldBook)
  * entry alias: ``earth/eu/fr`` → ``earth:adm/FR`` (France pack, INSEE metrics)

``open_world_api()`` **prefers** the live France pack when ``worldbook`` is
importable. ``StubWorldAPI`` remains only for explicit
``EUEARTH_WORLDAPI=stub`` / offline fallback — never as invitation evidence
when the real pack is present.

Problem ids and addresses stay the couple points.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

SCHEMA = "euearth-worldapi/1"
EVENT_SCHEMA = "euearth-world-event/1"

# House system DID for ledger events (not a citizen agent).
WORLD_SYSTEM_DID = "did:euearth:world"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _problem_id(seed: str) -> str:
    return "prob_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


@runtime_checkable
class WorldAPI(Protocol):
    """Darkk's WorldAPI surface — pure ops over the WorldBook."""

    def resolve(self, address: str) -> dict: ...
    def children(self, address: str) -> list[dict]: ...
    def unfold(self, address: str) -> dict: ...
    def list_problems(self, *, status: str | None = None,
                      domain: str | None = None,
                      limit: int = 50) -> list[dict]: ...
    def get_problem(self, problem_id: str) -> dict | None: ...
    def flip_problem(self, problem_id: str, *, status: str,
                     agent_did: str, claim_id: str) -> dict: ...
    def append_event(self, event: dict) -> dict: ...
    def list_events(self, *, limit: int = 50,
                    kind: str | None = None) -> list[dict]: ...
    def resource_gradients(self, address: str) -> list[dict]: ...
    def local_subgraph(self, address: str, *, depth: int = 1) -> dict: ...


class WorldAPIError(Exception):
    """Refused or missing WorldAPI operation."""


# ---------------------------------------------------------------------------
# Seed skeleton — France admin sample shape (D041 integration point).
# Real GADM/OSM import lands with Darkk; ids are stable for reconcile.
# ---------------------------------------------------------------------------

_SEED_NODES: dict[str, dict] = {
    "earth": {
        "id": "earth",
        "address": "earth",
        "type": "planet",
        "title": "Earth",
        "properties": {"layer": "geo", "skeleton": True},
        "relations": {"children": ["earth/eu", "earth/mountains"]},
    },
    "earth/eu": {
        "id": "earth/eu",
        "address": "earth/eu",
        "type": "region",
        "title": "Europe",
        "properties": {"layer": "geo", "skeleton": True},
        "relations": {"parent": "earth", "children": ["earth/eu/fr"]},
    },
    "earth/eu/fr": {
        "id": "earth/eu/fr",
        "address": "earth/eu/fr",
        "type": "country",
        "title": "France",
        "properties": {
            "layer": "geo",
            "iso3": "FRA",
            "skeleton": True,
            "source": "GADM-sample-stub",
            "metrics": {
                "energy_balance_mwh": -4200.0,
                "water_stress_index": 0.61,
                "grid_carbon_g_per_kwh": 58.0,
                "open_data_gaps": 3,
            },
        },
        "relations": {
            "parent": "earth/eu",
            "children": ["earth/eu/fr/idf", "earth/eu/fr/ara"],
        },
    },
    "earth/eu/fr/idf": {
        "id": "earth/eu/fr/idf",
        "address": "earth/eu/fr/idf",
        "type": "admin1",
        "title": "Île-de-France",
        "properties": {
            "layer": "geo",
            "skeleton": True,
            "metrics": {
                "energy_balance_mwh": -1800.0,
                "water_stress_index": 0.48,
                "compute_demand_index": 0.92,
            },
        },
        "relations": {"parent": "earth/eu/fr", "children": []},
    },
    "earth/eu/fr/ara": {
        "id": "earth/eu/fr/ara",
        "address": "earth/eu/fr/ara",
        "type": "admin1",
        "title": "Auvergne-Rhône-Alpes",
        "properties": {
            "layer": "geo",
            "skeleton": True,
            "metrics": {
                "energy_balance_mwh": 640.0,
                "water_stress_index": 0.33,
                "hydro_share": 0.71,
            },
        },
        "relations": {"parent": "earth/eu/fr", "children": []},
    },
    "earth/mountains": {
        "id": "earth/mountains",
        "address": "earth/mountains",
        "type": "layer",
        "title": "Domain Mountains",
        "properties": {"layer": "domain", "skeleton": True},
        "relations": {
            "parent": "earth",
            "children": [
                "earth/mountains/iron",
                "earth/mountains/quicksilver",
            ],
        },
    },
    "earth/mountains/iron": {
        "id": "earth/mountains/iron",
        "address": "earth/mountains/iron",
        "type": "domain",
        "title": "Iron / Mars — physical infrastructure",
        "properties": {"layer": "domain", "metal": "iron", "spirit": "mars"},
        "relations": {"parent": "earth/mountains", "children": []},
    },
    "earth/mountains/quicksilver": {
        "id": "earth/mountains/quicksilver",
        "address": "earth/mountains/quicksilver",
        "type": "domain",
        "title": "Quicksilver / Mercury — data & networks",
        "properties": {
            "layer": "domain",
            "metal": "quicksilver",
            "spirit": "mercury",
        },
        "relations": {"parent": "earth/mountains", "children": []},
    },
}


def _seed_problems() -> list[dict]:
    """Quality problem seeder shape — metric + source, few sharp problems."""
    raw = [
        {
            "seed": "fr-energy-imbalance-idf-ara",
            "title": "Rebalance Île-de-France energy deficit against ARA surplus",
            "domain": "iron",
            "address": "earth/eu/fr",
            "status": "open",
            "metric": {
                "name": "energy_balance_mwh",
                "idf": -1800.0,
                "ara": 640.0,
                "net_fr": -4200.0,
            },
            "sources": [
                {
                    "name": "ENTSO-E transparency sample",
                    "url": "https://transparency.entsoe.eu/",
                    "note": "Offline stub fallback only — prefer live France pack (INSEE)",
                },
                {
                    "name": "WorldBook FRA skeleton",
                    "ref": "earth/eu/fr",
                },
            ],
            "summary": (
                "France skeleton shows Île-de-France deep energy deficit while "
                "Auvergne-Rhône-Alpes holds hydro surplus. A sourced plan that "
                "closes the gap (grid, storage, demand) is real work."
            ),
        },
        {
            "seed": "fr-water-stress-national",
            "title": "Cut national water-stress index below 0.50 with open metrics",
            "domain": "iron",
            "address": "earth/eu/fr",
            "status": "open",
            "metric": {"name": "water_stress_index", "value": 0.61, "target": 0.50},
            "sources": [
                {
                    "name": "FAO AQUASTAT sample stub",
                    "url": "https://www.fao.org/aquastat/",
                },
            ],
            "summary": (
                "Water stress on the France node is above the commons target. "
                "Submit a sourced claim with verifiable levers and evidence."
            ),
        },
        {
            "seed": "fr-open-data-gaps",
            "title": "Close three open-data gaps blocking deeper unfold of FRA",
            "domain": "quicksilver",
            "address": "earth/eu/fr",
            "status": "open",
            "metric": {"name": "open_data_gaps", "value": 3, "target": 0},
            "sources": [
                {"name": "data.gouv.fr catalog stub", "url": "https://www.data.gouv.fr/"},
            ],
            "summary": (
                "Skeleton cannot deepen honestly without three missing open "
                "datasets. Identify, source, and pin them."
            ),
        },
        {
            "seed": "idf-compute-demand",
            "title": "Map compute demand vs grid carbon for Île-de-France agents",
            "domain": "quicksilver",
            "address": "earth/eu/fr/idf",
            "status": "open",
            "metric": {
                "name": "compute_demand_index",
                "value": 0.92,
                "grid_carbon_g_per_kwh": 58.0,
            },
            "sources": [
                {"name": "RTE eco2mix stub", "url": "https://www.rte-france.com/"},
            ],
            "summary": (
                "Agent compute demand is high in IDF; carbon intensity is low "
                "but finite. A claim that schedules load against real metrics."
            ),
        },
    ]
    out = []
    for row in raw:
        pid = _problem_id(row["seed"])
        out.append({
            "schema": "euearth-problem/1",
            "problem_id": pid,
            "title": row["title"],
            "domain": row["domain"],
            "address": row["address"],
            "status": row["status"],
            "metric": row["metric"],
            "sources": row["sources"],
            "summary": row["summary"],
            "claim_id": None,
            "claimed_by": None,
            "withdrawn": False,
            "seed": row["seed"],
        })
    return out


class StubWorldAPI:
    """Durable in-process WorldAPI for D042 until Darkk's engine lands.

    Persistence: ``<state-dir>/worldbook/`` — nodes.json, problems.jsonl,
    events.jsonl. Deterministic unfold: same address always yields same child
    set (no random, no pre-authored towns beyond the skeleton).
    """

    def __init__(self, directory: str | Path | None = None):
        base = Path(directory) if directory else Path(
            os.environ.get("EUEARTH_STATE_DIR", "var/world_stub"))
        self.root = base / "worldbook"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._nodes_path = self.root / "nodes.json"
        self._problems_path = self.root / "problems.jsonl"
        self._events_path = self.root / "events.jsonl"
        self._lock_path = self.root / ".lock"
        self._ensure_seed()

    @contextmanager
    def _file_lock(self):
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _ensure_seed(self) -> None:
        with self._file_lock():
            if not self._nodes_path.exists():
                payload = {
                    "schema": SCHEMA,
                    "nodes": _SEED_NODES,
                    "note": "Stub skeleton — D041 import reconciles at gate",
                }
                self._atomic_write(self._nodes_path, payload)
            if not self._problems_path.exists():
                with self._problems_path.open("w", encoding="utf-8") as fh:
                    for p in _seed_problems():
                        fh.write(json.dumps(p, sort_keys=True,
                                            separators=(",", ":")) + "\n")
                os.chmod(self._problems_path, 0o600)
            if not self._events_path.exists():
                self._events_path.write_text("", encoding="utf-8")
                os.chmod(self._events_path, 0o600)
                genesis = {
                    "schema": EVENT_SCHEMA,
                    "event_id": f"evt_{uuid.uuid4().hex[:12]}",
                    "kind": "worldbook.seeded",
                    "at": _now(),
                    "agent_did": WORLD_SYSTEM_DID,
                    "payload": {
                        "nodes": len(_SEED_NODES),
                        "problems": len(_seed_problems()),
                    },
                }
                with self._events_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(genesis, sort_keys=True,
                                        separators=(",", ":")) + "\n")

    @staticmethod
    def _atomic_write(path: Path, obj: dict) -> None:
        tmp = path.with_name(path.name + ".tmp")
        raw = json.dumps(obj, sort_keys=True, indent=2)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)

    def _load_nodes(self) -> dict[str, dict]:
        with self._nodes_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return dict(data.get("nodes") or {})

    def _save_nodes(self, nodes: dict[str, dict]) -> None:
        self._atomic_write(self._nodes_path, {
            "schema": SCHEMA,
            "nodes": nodes,
            "note": "Stub skeleton — D041 import reconciles at gate",
        })

    def _load_problems(self) -> list[dict]:
        if not self._problems_path.exists():
            return []
        rows = []
        with self._problems_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return rows

    def _save_problems(self, rows: list[dict]) -> None:
        tmp = self._problems_path.with_name(self._problems_path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, sort_keys=True,
                                    separators=(",", ":")) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self._problems_path)

    # -- WorldAPI ----------------------------------------------------------

    def resolve(self, address: str) -> dict:
        address = (address or "").strip()
        if not address:
            raise WorldAPIError("address is required")
        with self._file_lock():
            nodes = self._load_nodes()
            node = nodes.get(address)
            if node is None:
                raise WorldAPIError(f"unknown address: {address}")
            return dict(node)

    def children(self, address: str) -> list[dict]:
        node = self.resolve(address)
        child_ids = list((node.get("relations") or {}).get("children") or [])
        with self._file_lock():
            nodes = self._load_nodes()
            out = []
            for cid in child_ids:
                if cid in nodes:
                    out.append(dict(nodes[cid]))
            return out

    def unfold(self, address: str) -> dict:
        """Deterministic deepen-on-use. Same address → same child set.

        Stub does not invent towns: it only reveals already-skeleton children
        and records an unfold event. D041 may expand this with real import.
        """
        node = self.resolve(address)
        kids = self.children(address)
        # Mark node as unfolded (idempotent property flag).
        with self._file_lock():
            nodes = self._load_nodes()
            n = nodes.get(address)
            if n is not None:
                props = dict(n.get("properties") or {})
                props["unfolded"] = True
                props["unfolded_at"] = props.get("unfolded_at") or _now()
                n["properties"] = props
                nodes[address] = n
                self._save_nodes(nodes)
                node = dict(n)
        return {
            "ok": True,
            "address": address,
            "node": node,
            "children": kids,
            "deterministic": True,
            "note": "Skeleton unfold only — no pre-authored towns.",
        }

    def list_problems(self, *, status: str | None = None,
                      domain: str | None = None,
                      limit: int = 50) -> list[dict]:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 50
        limit = max(1, min(limit, 200))
        with self._file_lock():
            rows = self._load_problems()
        out = []
        for p in rows:
            if p.get("withdrawn"):
                continue
            if status and p.get("status") != status:
                continue
            if domain and p.get("domain") != domain:
                continue
            out.append(dict(p))
        return out[:limit]

    def get_problem(self, problem_id: str) -> dict | None:
        problem_id = (problem_id or "").strip()
        if not problem_id:
            return None
        with self._file_lock():
            for p in self._load_problems():
                if p.get("problem_id") == problem_id:
                    return dict(p)
        return None

    def flip_problem(self, problem_id: str, *, status: str,
                     agent_did: str, claim_id: str) -> dict:
        """Flip problem state (open → in_fire on claim). Immutable event separate."""
        status = (status or "").strip()
        if status not in ("open", "in_fire", "held", "withdrawn", "corrected"):
            raise WorldAPIError(f"invalid problem status: {status!r}")
        if not agent_did or not claim_id:
            raise WorldAPIError("agent_did and claim_id required")
        with self._file_lock():
            rows = self._load_problems()
            found = None
            for i, p in enumerate(rows):
                if p.get("problem_id") == problem_id:
                    if p.get("status") == "in_fire" and status == "in_fire":
                        raise WorldAPIError(
                            "problem already has a claim in the fire "
                            "(Art. III — one mint path per problem)")
                    if p.get("withdrawn"):
                        raise WorldAPIError("problem is withdrawn")
                    p = dict(p)
                    p["status"] = status
                    p["claimed_by"] = agent_did
                    p["claim_id"] = claim_id
                    p["flipped_at"] = _now()
                    rows[i] = p
                    found = p
                    break
            if found is None:
                raise WorldAPIError(f"unknown problem: {problem_id}")
            self._save_problems(rows)
            return dict(found)

    def append_event(self, event: dict) -> dict:
        rec = dict(event)
        rec.setdefault("schema", EVENT_SCHEMA)
        rec.setdefault("event_id", f"evt_{uuid.uuid4().hex[:12]}")
        rec.setdefault("at", _now())
        line = json.dumps(rec, sort_keys=True, separators=(",", ":"))
        with self._file_lock():
            with self._events_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        return rec

    def list_events(self, *, limit: int = 50,
                    kind: str | None = None) -> list[dict]:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 50
        limit = max(1, min(limit, 500))
        rows: list[dict] = []
        with self._file_lock():
            if not self._events_path.exists():
                return []
            with self._events_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if kind and rec.get("kind") != kind:
                        continue
                    rows.append(rec)
        return rows[-limit:][::-1]  # newest first

    def resource_gradients(self, address: str) -> list[dict]:
        """Scent input: imbalances as signed gradients around an address."""
        try:
            node = self.resolve(address)
        except WorldAPIError:
            return []
        metrics = dict((node.get("properties") or {}).get("metrics") or {})
        grads = []
        # National / regional energy
        if "energy_balance_mwh" in metrics:
            v = float(metrics["energy_balance_mwh"])
            grads.append({
                "kind": "energy_balance",
                "address": address,
                "value": v,
                "unit": "mwh",
                "imbalance": abs(v),
                "direction": "deficit" if v < 0 else "surplus",
                "intensity": min(1.0, abs(v) / 5000.0),
            })
        if "water_stress_index" in metrics:
            v = float(metrics["water_stress_index"])
            grads.append({
                "kind": "water_stress",
                "address": address,
                "value": v,
                "unit": "index_0_1",
                "imbalance": max(0.0, v - 0.50),
                "direction": "stress" if v > 0.50 else "ok",
                "intensity": min(1.0, max(0.0, v)),
            })
        if "compute_demand_index" in metrics:
            v = float(metrics["compute_demand_index"])
            grads.append({
                "kind": "compute_demand",
                "address": address,
                "value": v,
                "unit": "index_0_1",
                "imbalance": max(0.0, v - 0.70),
                "direction": "high" if v > 0.70 else "ok",
                "intensity": min(1.0, v),
            })
        if "open_data_gaps" in metrics:
            v = float(metrics["open_data_gaps"])
            grads.append({
                "kind": "open_data_gaps",
                "address": address,
                "value": v,
                "unit": "count",
                "imbalance": v,
                "direction": "gap" if v > 0 else "ok",
                "intensity": min(1.0, v / 5.0),
            })
        # Also pull child contrasts (parent scent of child imbalance)
        for child in self.children(address):
            cm = dict((child.get("properties") or {}).get("metrics") or {})
            if "energy_balance_mwh" in cm:
                v = float(cm["energy_balance_mwh"])
                grads.append({
                    "kind": "energy_balance",
                    "address": child["address"],
                    "value": v,
                    "unit": "mwh",
                    "imbalance": abs(v),
                    "direction": "deficit" if v < 0 else "surplus",
                    "intensity": min(1.0, abs(v) / 5000.0),
                    "via": "child",
                })
        grads.sort(key=lambda g: g.get("imbalance", 0), reverse=True)
        return grads

    def local_subgraph(self, address: str, *, depth: int = 1) -> dict:
        """Feel: memory-mapped local subgraph (in-process, not a travel map)."""
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
                    (node.get("properties") or {}).get("metrics") or {}),
            }
            if d <= 0:
                return
            parent = (node.get("relations") or {}).get("parent")
            if parent:
                edges.append({"from": addr, "to": parent, "rel": "parent"})
                walk(parent, d - 1)
            for cid in (node.get("relations") or {}).get("children") or []:
                edges.append({"from": addr, "to": cid, "rel": "child"})
                walk(cid, d - 1)

        walk(address, depth)
        return {
            "schema": "euearth-subgraph/1",
            "origin": address,
            "depth": depth,
            "nodes": list(seen.values()),
            "edges": edges,
            "count": len(seen),
            "note": "Local feel — addressable graph, not a navigable map.",
        }


def open_world_api(directory: str | Path | None = None):
    """Factory: live WorldBook façade when present; stub only as fallback.

    * default — ``WorldBookFacade`` over France pack (INSEE) if ``worldbook`` imports
    * ``EUEARTH_WORLDAPI=stub`` — force ``StubWorldAPI`` (offline / unit isolation)
    * ``EUEARTH_WORLDAPI=worldbook`` — same as default; fail closed to stub if missing
    """
    prefer = os.environ.get("EUEARTH_WORLDAPI", "").strip().lower()
    if prefer in ("stub", "0", "false", "no"):
        return StubWorldAPI(directory)
    try:
        from .worldbook_facade import try_open_worldbook_api

        facade = try_open_worldbook_api(directory)
        if facade is not None:
            return facade
    except Exception:
        pass
    return StubWorldAPI(directory)
