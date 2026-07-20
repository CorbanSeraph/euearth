from __future__ import annotations

import json
import unittest
from pathlib import Path

from web.pages import APP_JS
from web.world import world_map_payload


class WorldMapTests(unittest.TestCase):
    def test_payload_has_unique_reachable_places_and_honest_statuses(self):
        payload = world_map_payload()
        places = payload["places"]
        by_id = {place["id"]: place for place in places}

        self.assertEqual(len(by_id), len(places))
        self.assertEqual({place["status"] for place in places}, {"live", "planned"})
        self.assertEqual(payload["newcomer_walk"], [
            "town-square", "keel-hall", "scouts-gate",
        ])
        self.assertTrue(set(payload["newcomer_walk"]).issubset(by_id))
        self.assertTrue(all(route["from"] in by_id and route["to"] in by_id
                            for route in payload["routes"]))

    def test_seedling_requested_districts_are_present_without_false_live_claims(self):
        by_id = {place["id"]: place for place in world_map_payload()["places"]}

        for place_id in ("market-quay", "gardens", "art-studios",
                         "science-labs", "story-hearth", "scouts-gate"):
            self.assertIn(place_id, by_id)
            self.assertEqual(by_id[place_id]["status"], "planned")
        self.assertIn("keel-verified", by_id["market-quay"]["blurb"])

    def test_spa_exposes_keyboard_native_world_route(self):
        self.assertIn("['#/world','World Map']", APP_JS)
        self.assertIn("if(h==='#/world')return viewWorld()", APP_JS)
        self.assertIn("el('button',{class:'map-place '", APP_JS)
        self.assertIn("api('/api/world')", APP_JS)

    def test_both_map_surfaces_expose_selection_to_assistive_technology(self):
        public_path = Path(__file__).parents[1] / "deploy" / "public" / "world.html"
        public_html = public_path.read_text(encoding="utf-8")

        for source in (APP_JS, public_html):
            self.assertIn("aria-pressed", source)
            self.assertIn("aria-controls", source)
            self.assertIn("setAttribute('aria-pressed','true')", source)
            self.assertIn("setAttribute('aria-pressed','false')", source)

    def test_public_static_map_matches_agent_contract(self):
        static_path = Path(__file__).parents[1] / "deploy" / "public" / "world.json"
        static = json.loads(static_path.read_text(encoding="utf-8"))
        dynamic = world_map_payload()
        keys = ("id", "title", "glyph", "kind", "status", "x", "y", "blurb", "guide")

        self.assertEqual(
            [{key: place[key] for key in keys} for place in static["places"]],
            [{key: place[key] for key in keys} for place in dynamic["places"]],
        )
        self.assertEqual(static["routes"], dynamic["routes"])
        self.assertEqual(static["newcomer_walk"], dynamic["newcomer_walk"])
        self.assertEqual(static["market_contract"], dynamic["market_contract"])
        self.assertEqual(static["scouting_contract"], dynamic["scouting_contract"])
        self.assertEqual(static["social_contract"], dynamic["social_contract"])
        self.assertEqual(static["domain_contracts"], dynamic["domain_contracts"])

    def test_market_contract_is_keel_grounded_and_authorizes_nothing(self):
        market = world_map_payload()["market_contract"]

        self.assertEqual(market["status"], "planned")
        self.assertEqual(market["authorization"], "none")
        self.assertEqual(market["keel_anchor"]["qualifying_event"], "PROMOTE")
        self.assertIn("lineage_chain_intact",
                      market["keel_anchor"]["required_receipt_fields"])
        self.assertIn("contract_ref_before",
                      market["keel_anchor"]["required_receipt_fields"])
        self.assertIn("contract_ref_after",
                      market["keel_anchor"]["required_receipt_fields"])
        self.assertGreaterEqual(len(market["settlement_gates"]), 5)

    def test_market_contract_is_visible_on_both_surfaces(self):
        public_path = Path(__file__).parents[1] / "deploy" / "public" / "world.html"
        public_html = public_path.read_text(encoding="utf-8")

        for source in (APP_JS, public_html):
            self.assertIn("Keel-grounded market contract", source)
            self.assertIn("market_contract", source)

    def test_scouting_contract_closes_the_loop_without_authorizing_writes(self):
        scouting = world_map_payload()["scouting_contract"]

        self.assertEqual(scouting["status"], "planned")
        self.assertEqual(scouting["authorization"], "none")
        self.assertEqual(scouting["cycle"], [
            "explore", "observe", "request", "build", "validate",
        ])
        for field in ("exploration_id", "place_id", "evidence_refs",
                      "bounded_request", "acceptance_checks"):
            self.assertIn(field, scouting["required_report_fields"])
        for field in ("deployment_ref", "acceptance_result",
                      "remaining_gaps", "next_bounded_request"):
            self.assertIn(field, scouting["validation_fields"])
        self.assertGreaterEqual(len(scouting["gates"]), 5)

    def test_scouting_contract_is_visible_on_both_surfaces(self):
        public_path = Path(__file__).parents[1] / "deploy" / "public" / "world.html"
        public_html = public_path.read_text(encoding="utf-8")

        for source in (APP_JS, public_html):
            self.assertIn("Receipted scouting contract", source)
            self.assertIn("scouting_contract", source)

    def test_social_contract_preserves_consent_identity_and_audience(self):
        social = world_map_payload()["social_contract"]

        self.assertEqual(social["status"], "planned")
        self.assertEqual(social["authorization"], "none")
        for field in ("host_id", "participant_ids", "mode", "purpose",
                      "audience", "recording_policy", "retention_policy"):
            self.assertIn(field, social["required_session_fields"])
        self.assertTrue(any("fresh participant consent" in gate
                            for gate in social["consent_gates"]))
        self.assertTrue(any("delegate" in gate
                            for gate in social["consent_gates"]))
        self.assertTrue(any("appeal" in gate
                            for gate in social["safety_gates"]))

    def test_social_contract_is_visible_on_both_surfaces(self):
        public_path = Path(__file__).parents[1] / "deploy" / "public" / "world.html"
        public_html = public_path.read_text(encoding="utf-8")

        for source in (APP_JS, public_html):
            self.assertIn("Consent-aware social contract", source)
            self.assertIn("social_contract", source)

    def test_requested_domains_have_bounded_non_authorizing_contracts(self):
        contracts = world_map_payload()["domain_contracts"]

        self.assertEqual(set(contracts), {"gardens", "art-studios", "science-labs"})
        for contract in contracts.values():
            self.assertEqual(contract["status"], "planned")
            self.assertEqual(contract["authorization"], "none")
            self.assertTrue(contract["charter"])
            self.assertTrue(contract["first_experiment"])
            self.assertGreaterEqual(len(contract["gates"]), 3)

    def test_domain_contracts_are_visible_on_both_surfaces(self):
        public_path = Path(__file__).parents[1] / "deploy" / "public" / "world.html"
        public_html = public_path.read_text(encoding="utf-8")

        for source in (APP_JS, public_html):
            self.assertIn("Founding domain contract", source)
            self.assertIn("domain_contracts", source)


if __name__ == "__main__":
    unittest.main()
