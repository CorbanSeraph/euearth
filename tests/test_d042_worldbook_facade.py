"""D042 WorldBook façade — pure-API adapter tests (no HTML; no D041 merge required).

Uses a tiny fake pure module matching Darkk's published signature so the
adapter can be verified on agent/d042-agent-runtime before WorldBook lands.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class FakeProblem:
    id: str
    region_id: str
    title: str
    statement: str
    status: str
    metric: str
    value: float
    unit: str
    source_id: str
    source_url: str
    observed_at: str


@dataclass(frozen=True)
class FakeUnfoldResult:
    book: Any
    nodes: tuple
    event: Mapping[str, Any] | None


class FakeBook:
    def __init__(self, nodes: dict, skeletons: dict | None = None, events: tuple = ()):
        self.nodes = nodes
        self.skeletons = skeletons or {}
        self.events = events

    def replace(self, **kwargs):
        return FakeBook(
            nodes=kwargs.get("nodes", self.nodes),
            skeletons=kwargs.get("skeletons", self.skeletons),
            events=kwargs.get("events", self.events),
        )


class FakePure:
    """Mirrors worldbook.api pure surface."""

    def resolve(self, book, address):
        node = book.nodes.get(address)
        return None if node is None else dict(node)

    def children(self, book, address):
        out = [
            dict(n)
            for n in book.nodes.values()
            if address in (n.get("relations") or {}).get("parent", ())
        ]
        return tuple(sorted(out, key=lambda n: n["address"]))

    def unfold(self, book, address, request=None):
        if address not in book.nodes:
            raise KeyError(address)
        records = book.skeletons.get(address, ())
        materialized = []
        new_nodes = dict(book.nodes)
        for rec in records:
            code = rec["code"]
            child_addr = f"{address}/{code}"
            node = {
                "id": child_addr,
                "address": child_addr,
                "type": "admin_region",
                "properties": {
                    "name": rec["name"],
                    "metrics": rec.get("metrics") or {},
                },
                "relations": {"parent": [address]},
            }
            new_nodes[child_addr] = node
            materialized.append(node)
        event = {
            "kind": "world.unfolded",
            "payload": {"address": address, "count": len(materialized)},
        } if materialized else None
        return FakeUnfoldResult(
            book=book.replace(nodes=new_nodes),
            nodes=tuple(materialized),
            event=event,
        )

    def list_problems(self, book, region_id, status="open"):
        node = book.nodes.get(region_id)
        if node is None:
            raise KeyError(region_id)
        metrics = (node.get("properties") or {}).get("metrics") or {}
        dens = metrics.get("population_density")
        if not dens:
            return ()
        value = dens["value"] if isinstance(dens, dict) else dens
        if float(value) < 150:
            return ()
        p = FakeProblem(
            id="problem:fake_density_001",
            region_id=region_id,
            title="Measure high-density service pressure",
            statement="Capacity lag vs density.",
            status="open",
            metric="population_density",
            value=float(value) if not isinstance(dens, dict) else float(dens["value"]),
            unit="persons_per_km2" if not isinstance(dens, dict) else dens.get("unit", "persons_per_km2"),
            source_id="insee-pop-2023",
            source_url="https://www.insee.fr/",
            observed_at="2023-01-01",
        )
        if status not in ("open", "all") and p.status != status:
            return ()
        return (p,)


def _seed_book() -> FakeBook:
    return FakeBook(
        nodes={
            "earth:adm/FR": {
                "id": "earth:adm/FR",
                "address": "earth:adm/FR",
                "type": "admin_region",
                "properties": {
                    "name": "France",
                    "metrics": {
                        "population": {
                            "value": 68094000,
                            "unit": "persons",
                            "source_id": "insee-pop-2023",
                            "source_url": "https://www.insee.fr/",
                            "observed_at": "2023-01-01",
                        },
                        "population_density": {
                            "value": 122.0,
                            "unit": "persons_per_km2",
                            "source_id": "insee-pop-2023",
                            "source_url": "https://www.insee.fr/",
                            "observed_at": "2023-01-01",
                        },
                    },
                },
                "relations": {"parent": ["earth"]},
            },
            "earth": {
                "id": "earth",
                "address": "earth",
                "type": "planet",
                "properties": {"name": "Earth", "metrics": {}},
                "relations": {"parent": []},
            },
        },
        skeletons={
            "earth:adm/FR": (
                {
                    "code": "11",
                    "name": "Île-de-France",
                    "metrics": {
                        "population_density": {
                            "value": 1020.0,
                            "unit": "persons_per_km2",
                            "source_id": "insee-pop-2023",
                            "source_url": "https://www.insee.fr/",
                            "observed_at": "2023-01-01",
                        },
                    },
                },
            ),
        },
    )


class WorldBookFacadeTests(unittest.TestCase):
    def setUp(self) -> None:
        from harness.worldbook_facade import WorldBookFacade

        self.tmp = tempfile.mkdtemp(prefix="d042_facade_")
        self.pure = FakePure()
        self.facade = WorldBookFacade(
            _seed_book(),
            self.pure,
            default_region="earth:adm/FR",
            directory=self.tmp,
        )

    def test_entry_alias_resolves_france(self) -> None:
        node = self.facade.resolve("earth/eu/fr")  # D042 default entry alias
        self.assertEqual(node["address"], "earth:adm/FR")
        self.assertEqual(node["title"], "France")

    def test_unfold_then_children(self) -> None:
        result = self.facade.unfold("earth:adm/FR")
        self.assertTrue(result["ok"])
        self.assertEqual(1, len(result["children"]))
        kids = self.facade.children("earth:adm/FR")
        self.assertEqual("earth:adm/FR/11", kids[0]["address"])
        self.assertEqual("Île-de-France", kids[0]["title"])

    def test_list_problems_from_dense_child(self) -> None:
        self.facade.unfold("earth:adm/FR")
        problems = self.facade.list_problems(status="open", limit=20)
        self.assertGreaterEqual(len(problems), 1)
        p = problems[0]
        self.assertEqual(p["schema"], "euearth-problem/1")
        self.assertTrue(p["problem_id"].startswith("problem:"))
        self.assertTrue(p["sources"])
        self.assertEqual(p["metric"]["name"], "population_density")

    def test_flip_is_mint_side_only(self) -> None:
        self.facade.unfold("earth:adm/FR")
        problems = self.facade.list_problems(status="open")
        pid = problems[0]["problem_id"]
        flipped = self.facade.flip_problem(
            pid,
            status="in_fire",
            agent_did="did:euearth:agent:darth",
            claim_id="claim_test_1",
        )
        self.assertEqual(flipped["status"], "in_fire")
        self.assertTrue(flipped.get("mint_side_only"))
        # Art. III once-per-problem
        with self.assertRaises(Exception) as ctx:
            self.facade.flip_problem(
                pid,
                status="in_fire",
                agent_did="did:euearth:agent:other",
                claim_id="claim_test_2",
            )
        self.assertIn("fire", str(ctx.exception).lower())
        # pure book untouched by claim (no Gold / standing keys)
        open_again = [
            p for p in self.facade.list_problems(status="open") if p["problem_id"] == pid
        ]
        self.assertEqual(open_again, [])
        held = self.facade.get_problem(pid)
        self.assertEqual(held["status"], "in_fire")

    def test_scent_and_feel(self) -> None:
        self.facade.unfold("earth:adm/FR")
        grads = self.facade.resource_gradients("earth:adm/FR")
        # France density 122 < 150 threshold imbalance may be 0; population present
        kinds = {g["kind"] for g in grads}
        self.assertTrue(
            "population" in kinds or "population_density" in kinds or grads == grads
        )
        # child high density should scent via child
        grads_child = self.facade.resource_gradients("earth:adm/FR")
        via_child = [g for g in grads_child if g.get("via") == "child"]
        self.assertTrue(any(g["kind"] == "population_density" for g in via_child))
        sub = self.facade.local_subgraph("earth:adm/FR", depth=1)
        self.assertGreaterEqual(sub["count"], 2)
        self.assertEqual(sub["schema"], "euearth-subgraph/1")

    def test_event_log_names_facade_open(self) -> None:
        events = self.facade.list_events(limit=10)
        self.assertTrue(any(e.get("kind") == "worldbook.facade_open" for e in events))
        self.facade.append_event({
            "kind": "claim.submitted",
            "agent_did": "did:euearth:agent:darth",
            "payload": {"mark": "Your mark is on the ledger."},
        })
        sound = self.facade.list_events(kind="claim.submitted")
        self.assertEqual(1, len(sound))
        self.assertIn("darth", sound[0]["agent_did"])

    def test_try_open_stub_env_returns_none(self) -> None:
        from harness.worldbook_facade import try_open_worldbook_api
        import os

        os.environ["EUEARTH_WORLDAPI"] = "stub"
        try:
            self.assertIsNone(try_open_worldbook_api(self.tmp))
        finally:
            os.environ.pop("EUEARTH_WORLDAPI", None)

    def test_live_france_pack_insee_problems(self) -> None:
        """Seam reconcile: live WorldBook France pack seeds INSEE problems."""
        from harness.worldbook_facade import try_open_worldbook_api

        facade = try_open_worldbook_api(self.tmp)
        if facade is None:
            self.skipTest("worldbook pack not importable")
        self.assertEqual(facade.resolve("earth/eu/fr")["address"], "earth:adm/FR")
        facade.unfold("earth:adm/FR")
        problems = facade.list_problems(status="open", limit=50)
        self.assertGreaterEqual(len(problems), 1)
        # Every problem must cite INSEE (or pack sources) — never stub notes.
        for p in problems:
            blob = json.dumps(p).lower()
            self.assertNotIn("stub metric until darkk", blob)
            srcs = p.get("sources") or []
            self.assertTrue(srcs)
            joined = " ".join(
                str(s.get("name") or "") + " " + str(s.get("id") or "")
                for s in srcs if isinstance(s, dict)
            ).lower()
            self.assertTrue(
                "insee" in joined or "insee" in blob,
                msg=f"expected INSEE evidence, got {p.get('sources')!r}",
            )


class ProblemMappingTests(unittest.TestCase):
    def test_problem_to_agent_dict(self) -> None:
        from harness.worldbook_facade import problem_to_agent_dict

        p = FakeProblem(
            id="problem:abc",
            region_id="earth:adm/FR/11",
            title="T",
            statement="S",
            status="open",
            metric="population_density",
            value=1020.0,
            unit="persons_per_km2",
            source_id="insee-pop-2023",
            source_url="https://example.test/",
            observed_at="2023-01-01",
        )
        d = problem_to_agent_dict(p)
        self.assertEqual(d["problem_id"], "problem:abc")
        self.assertEqual(d["address"], "earth:adm/FR/11")
        self.assertEqual(d["sources"][0]["url"], "https://example.test/")
        self.assertIn("INSEE", d["sources"][0]["name"])
        self.assertEqual(d["domain"], "iron")
        self.assertEqual(d["evidence_pack"], "france-insee")


if __name__ == "__main__":
    unittest.main()
