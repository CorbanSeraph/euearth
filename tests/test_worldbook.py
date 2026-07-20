from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from worldbook import (
    AppendOnlyEventLog,
    Observation,
    UnfoldRequest,
    children,
    list_problems,
    load_country_pack,
    resolve,
    submit_observation,
    unfold,
)
from worldbook.book import WorldBook, validate_node
from worldbook.events import verify_chain
from worldbook.importers import import_gadm_admin
from worldbook.sources import SourceRegistry


class WorldBookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.book = load_country_pack()

    def test_schema_and_statebook_separation(self) -> None:
        france = resolve(self.book, "earth:adm/FR")
        self.assertEqual(france["id"], france["address"])
        validate_node(france)
        poisoned = {**france, "properties": {**france["properties"], "kabad": 9}}
        with self.assertRaisesRegex(ValueError, "StateBook"):
            validate_node(poisoned)

    def test_json_schema_accepts_real_node(self) -> None:
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema is optional in the lean CI image")
        schema_path = Path(__file__).parents[1] / "worldbook" / "schemas" / "node.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(resolve(self.book, "earth:adm/FR"), schema)

    def test_deterministic_deepen_on_use(self) -> None:
        request = UnfoldRequest(depth=1, limit=13)
        first = unfold(self.book, "earth:adm/FR", request)
        second = unfold(self.book, "earth:adm/FR", request)
        self.assertEqual(first.nodes, second.nodes)
        self.assertEqual(first.event, second.event)
        repeated = unfold(first.book, "earth:adm/FR", request)
        self.assertEqual(first.nodes, repeated.nodes)
        self.assertIsNone(repeated.event)
        self.assertEqual(13, len(children(first.book, "earth:adm/FR")))
        self.assertEqual("Île-de-France", resolve(first.book, "earth:adm/FR/11")["properties"]["name"])

    def test_unfold_is_limited_to_imported_skeleton(self) -> None:
        result = unfold(self.book, "earth:adm/FR", UnfoldRequest(limit=2))
        self.assertEqual(["earth:adm/FR/11", "earth:adm/FR/24"], [n["id"] for n in result.nodes])
        self.assertIsNone(resolve(result.book, "earth:adm/FR/fictionville"))

    def test_problem_seeder_is_sparse_evidenced_and_withdrawable(self) -> None:
        unfolded = unfold(self.book, "earth:adm/FR").book
        problems = list_problems(unfolded, "earth:adm/FR/32")
        self.assertGreaterEqual(len(problems), 1)
        self.assertLessEqual(len(problems), 10)
        self.assertTrue(all(p.source_id and p.source_url and p.metric for p in problems))
        event = {
            "schema": "euearth-world-event/0",
            "kind": "world.problem_withdrawn",
            "previous_hash": unfolded.events[-1]["hash"],
            "payload": {"problem_id": problems[0].id, "reason": "metric revised"},
        }
        from worldbook.events import event_hash
        event["hash"] = event_hash(event)
        withdrawn_book = unfolded.replace(events=(*unfolded.events, event))
        self.assertEqual("withdrawn", list_problems(withdrawn_book, "earth:adm/FR/32", "all")[0].status)

    def test_observation_returns_new_snapshot_and_hash_chained_event(self) -> None:
        observation = Observation(
            node_id="earth:adm/FR",
            metric="population", value=68094000, unit="persons",
            source_id="insee-pop-2023", observed_at="2023-01-01",
            observer_id="did:key:darkk", note="France excluding Mayotte",
        )
        submission = submit_observation(self.book, observation)
        self.assertEqual(0, len(self.book.events))
        self.assertEqual(1, len(submission.book.events))
        self.assertTrue(verify_chain(submission.book.events))
        with tempfile.TemporaryDirectory() as directory:
            log = AppendOnlyEventLog(Path(directory) / "world-events.jsonl")
            log.append(submission.event)
            self.assertEqual((submission.event,), log.read())

    def test_source_gate_blocks_gadm_redistribution_without_permission(self) -> None:
        registry = SourceRegistry.from_mapping(self.book.sources)
        fixture = [{
            "GID_1": "FRA.1_1", "NAME_1": "Fixture",
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
        }]
        with self.assertRaises(PermissionError):
            import_gadm_admin(fixture, registry, use="redistribution")
        imported = import_gadm_admin(fixture, registry, use="noncommercial-internal")
        self.assertEqual("FRA.1_1", imported[0]["code"])


if __name__ == "__main__":
    unittest.main()
