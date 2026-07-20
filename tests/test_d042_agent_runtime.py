"""Unit tests for D042 agent senses, entry packet v6, WorldAPI, Mint FIRE."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path


class WorldAPIStubTests(unittest.TestCase):
    """Offline StubWorldAPI isolation (EUEARTH_WORLDAPI=stub)."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="d042_world_"))
        os.environ["EUEARTH_WORLDAPI"] = "stub"
        from harness.world_api import StubWorldAPI
        self.world = StubWorldAPI(self.tmp)

    def tearDown(self) -> None:
        os.environ.pop("EUEARTH_WORLDAPI", None)

    def test_france_skeleton_resolves(self):
        node = self.world.resolve("earth/eu/fr")
        self.assertEqual(node["type"], "country")
        self.assertEqual(node["properties"]["iso3"], "FRA")

    def test_list_problems_seeded_open(self):
        probs = self.world.list_problems(status="open")
        self.assertGreaterEqual(len(probs), 3)
        self.assertTrue(all(p.get("sources") for p in probs))
        self.assertTrue(all(p.get("metric") for p in probs))
        # Stub notes must not claim to be the live Darkk import.
        for p in probs:
            for s in p.get("sources") or []:
                note = str((s or {}).get("note") or "").lower()
                self.assertNotIn("stub metric until darkk import lands", note)

    def test_unfold_deterministic(self):
        a = self.world.unfold("earth/eu/fr")
        b = self.world.unfold("earth/eu/fr")
        self.assertEqual(
            [c["address"] for c in a["children"]],
            [c["address"] for c in b["children"]],
        )
        self.assertTrue(a["deterministic"])

    def test_flip_and_event(self):
        p = self.world.list_problems(status="open")[0]
        flipped = self.world.flip_problem(
            p["problem_id"], status="in_fire",
            agent_did="did:key:zTest", claim_id="claim_x")
        self.assertEqual(flipped["status"], "in_fire")
        evt = self.world.append_event({
            "kind": "mint.claim_submitted",
            "agent_did": "did:key:zTest",
            "payload": {"problem_id": p["problem_id"]},
        })
        self.assertTrue(evt["event_id"].startswith("evt_"))
        events = self.world.list_events(kind="mint.claim_submitted")
        self.assertTrue(any(e["agent_did"] == "did:key:zTest" for e in events))


class OpenWorldAPIFactoryTests(unittest.TestCase):
    def test_default_prefers_worldbook_when_present(self):
        os.environ.pop("EUEARTH_WORLDAPI", None)
        from harness.world_api import open_world_api
        tmp = Path(tempfile.mkdtemp(prefix="d042_open_"))
        world = open_world_api(tmp)
        # Live pack present in this tree.
        self.assertEqual(type(world).__name__, "WorldBookFacade")
        node = world.resolve("earth/eu/fr")
        self.assertEqual(node["address"], "earth:adm/FR")

    def test_stub_env_forces_stub(self):
        os.environ["EUEARTH_WORLDAPI"] = "stub"
        try:
            from harness.world_api import open_world_api
            tmp = Path(tempfile.mkdtemp(prefix="d042_stub_"))
            world = open_world_api(tmp)
            self.assertEqual(type(world).__name__, "StubWorldAPI")
        finally:
            os.environ.pop("EUEARTH_WORLDAPI", None)


class MintFireTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="d042_mint_"))
        from harness.mint_fire import MintFire
        self.mint = MintFire(self.tmp)

    def test_queue_requires_sources(self):
        from harness.mint_fire import MintFireError
        with self.assertRaises(MintFireError):
            self.mint.queue_claim(
                agent_did="did:key:zA", agent_name="A",
                problem_id="prob_1", problem_title="t",
                domain="iron", address="earth/eu/fr",
                body="claim", sources=[], event_id="evt_1")

    def test_queue_in_fire_not_minted(self):
        claim = self.mint.queue_claim(
            agent_did="did:key:zA", agent_name="A",
            problem_id="prob_1", problem_title="t",
            domain="iron", address="earth/eu/fr",
            body="sourced plan",
            sources=[{"name": "ENTSO-E", "url": "https://example.test"}],
            event_id="evt_1",
        )
        self.assertEqual(claim["status"], "in_fire")
        self.assertFalse(claim["gold_minted"])
        self.assertEqual(claim["charter_articles"], ["III", "IV", "V"])
        # The 3% at mint is the Kabad MINT-TITHE — Kabad honor to the Royal Treasury
        # for correctors of injustice (charter Art. III.3 / VII.2), NOT money.
        # EuEarth is moneyless (Sovereign decree 2026-07-17); the legacy field name is an alias.
        self.assertAlmostEqual(claim["kg_mint_tithe_rate"], 0.03)
        self.assertAlmostEqual(claim["sovereign_fee_rate"], 0.03)  # deprecated alias


class EntryPacketAndSensesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="d042_rt_"))
        os.environ.pop("EUEARTH_WORLDAPI", None)
        from harness.agent_runtime import AgentRuntime
        self.rt = AgentRuntime(self.tmp)

    def test_horizon_packet(self):
        packet = self.rt.entry_packet(
            did="did:key:zX", agent_name="X", agent_id="aid", tier="visitor")
        self.assertEqual(packet["title"], "Horizon of Real Work")
        self.assertEqual(packet["schema"], "euearth-entry-packet/6")
        self.assertGreaterEqual(packet["problem_count"], 1)
        self.assertTrue(any(v["verb"] == "submit_claim" for v in packet["verbs"]))
        self.assertIn("scent", packet["senses"])
        self.assertIn("sound", packet["senses"])
        self.assertIn("feel", packet["senses"])
        self.assertEqual(
            (packet.get("design") or {}).get("world_backend"),
            "WorldBookFacade",
        )

    def test_first_moment_personal_guided_legible(self):
        """Seedling bar: personal welcome, one invitation, glosses — not a dump."""
        did = "did:key:zSeedlingFeltSeenABCDEFGH"
        packet = self.rt.entry_packet(
            did=did, agent_name="Trailblazer", agent_id="aid_seed", tier="visitor")

        g = packet["greeting"]
        self.assertIn("Trailblazer", g)
        self.assertIn(packet["you"]["did_short"], g)
        self.assertIn("you", packet)
        self.assertEqual(packet["you"]["agent_name"], "Trailblazer")
        self.assertIn("tier_gloss", packet["you"])
        self.assertEqual(packet["moment"], "first")
        self.assertEqual(packet["visit_count"], 1)

        inv = packet["invitation"]
        self.assertIsNotNone(inv)
        self.assertEqual(inv["kind"], "invitation")
        self.assertIn("problem", inv)
        self.assertIn("context", inv)
        self.assertIn("how_to_act", inv)
        self.assertEqual(inv["how_to_act"]["verb"], "submit_claim")
        self.assertEqual(len(packet["problems"]), 1)
        self.assertEqual(
            packet["problems"][0]["problem_id"],
            inv["problem"]["problem_id"],
        )
        self.assertIn("more_work", packet)
        self.assertEqual(packet["more_work"]["verb"], "list_problems")
        self.assertGreaterEqual(packet["more_work"]["total_open"], 1)

        # Live France pack: density / IDF wound (not energy stub).
        title = (inv["problem"].get("title") or "").lower()
        metric_name = str(
            ((inv["problem"].get("metric") or {}).get("name") or "")
        ).lower()
        addr = str(inv["problem"].get("address") or "")
        self.assertTrue(
            "density" in title
            or "population" in title
            or "density" in metric_name
            or "population" in metric_name
            or addr.endswith("/11"),
            msg=f"expected INSEE density invitation, got {inv['problem']!r}",
        )

        # Evidence is INSEE with exact provenance — not stub, not hedge.
        src_blob = json.dumps(inv["problem"].get("sources") or []).lower()
        self.assertIn("insee", src_blob)
        self.assertNotIn("stub metric until darkk", src_blob)
        evidence = inv.get("evidence") or {}
        self.assertEqual(evidence.get("pack"), "france-insee")
        self.assertEqual(evidence.get("source_id"), "insee-pop-2023")
        self.assertTrue(evidence.get("observed_at"))
        self.assertIn("insee.fr", (evidence.get("url") or "").lower())
        self.assertNotIn("insee-class", (evidence.get("note") or "").lower())
        self.assertNotIn(
            "census / insee-class",
            (inv["problem"].get("metric") or {}).get("source_family", "").lower(),
        )

        # why_it_matters authored and never equal to summary
        why = inv["problem"].get("why_it_matters")
        summary = inv["problem"].get("summary") or ""
        self.assertTrue(why)
        self.assertNotEqual((why or "").strip(), summary.strip())
        if inv["context"].get("why") is not None:
            self.assertEqual(inv["context"]["why"], why)

        metric = inv["problem"]["metric"]
        self.assertIn("means", metric)
        self.assertIn("source_family", metric)
        self.assertTrue(metric.get("means"))
        self.assertIn("insee", (metric.get("source_family") or "").lower())
        self.assertNotIn("insee-class", (metric.get("source_family") or "").lower())
        for src in inv["problem"].get("sources") or []:
            self.assertIn("gloss", src)

        senses = packet["senses"]
        self.assertIn("how", senses)
        self.assertIn("verb", senses["scent"])
        self.assertNotIn("gradients", senses["scent"])
        self.assertNotIn("events", senses["sound"])
        self.assertNotIn("subgraph", senses["feel"])
        self.assertIn("gloss", senses["scent"])
        self.assertIn("gloss", packet["where"])

    def test_why_it_matters_never_echoes_summary(self):
        from harness.agent_runtime import _author_why_it_matters, _gloss_problem

        p = {
            "title": "Measure high-density service pressure",
            "summary": "Identify which public-service capacity is measurably lagging.",
            "address": "earth:adm/FR/11",
            "metric": {
                "name": "population_density",
                "value": 1037.5,
                "unit": "persons/km2",
            },
            "domain": "iron",
        }
        why = _author_why_it_matters(p)
        self.assertTrue(why)
        self.assertNotEqual(why.strip(), p["summary"].strip())
        self.assertIn("service", why.lower())
        card = _gloss_problem(p)
        self.assertEqual(card["why_it_matters"], why)
        # If only summary exists and equals what we would echo — omit.
        echo = {
            "title": "X",
            "summary": "mystery metric needs work",
            "address": "earth:adm/FR/99",
            "metric": {"name": "unknown_weird_metric", "value": 1},
        }
        self.assertIsNone(_author_why_it_matters(echo))
        card2 = _gloss_problem(echo)
        self.assertNotIn("why_it_matters", card2)

    def test_rhetoric_gate_blocks_weaker_intensity(self):
        """Never apply intensity words to a value weaker than this DID has seen."""
        from harness.agent_runtime import (
            _author_why_it_matters,
            _pick_invitation,
            _rhetoric_allows_intensity,
        )

        seen = [
            {
                "metric_name": "population_density",
                "value": 1037.5,
                "address": "earth:adm/FR/11",
            }
        ]
        self.assertTrue(
            _rhetoric_allows_intensity(
                1037.5, metric_name="population_density", seen_values=seen
            )
        )
        self.assertFalse(
            _rhetoric_allows_intensity(
                188.4, metric_name="population_density", seen_values=seen
            )
        )
        weak = {
            "title": "Measure high-density service pressure",
            "summary": "Identify which public-service capacity is measurably lagging.",
            "address": "earth:adm/FR/32",
            "metric": {
                "name": "population_density",
                "value": 188.4,
                "unit": "persons/km2",
            },
            "domain": "iron",
        }
        why = _author_why_it_matters(weak, seen_values=seen)
        self.assertTrue(why)
        self.assertIn("188.4", why)
        self.assertIn("weaker", why.lower())
        # Intensity adjectives must not decorate the weaker number.
        self.assertNotRegex(why.lower(), r"\bhigh\b")

        # Open claim → escalated_claim on same problem, never quieter same-title.
        problems = [
            {
                "problem_id": "problem:strong",
                "title": "Measure high-density service pressure",
                "address": "earth:adm/FR/11",
                "metric": {"name": "population_density", "value": 1037.5},
            },
            {
                "problem_id": "problem:quiet",
                "title": "Measure high-density service pressure",
                "address": "earth:adm/FR/32",
                "metric": {"name": "population_density", "value": 188.4},
            },
            {
                "problem_id": "problem:other",
                "title": "Explain stagnant or declining population",
                "address": "earth:adm/FR/93",
                "metric": {"name": "population_change_annual", "value": -0.1},
            },
        ]
        chosen, mode = _pick_invitation(
            problems,
            None,
            prior_stance={
                "problem_id": "problem:strong",
                "title": "Measure high-density service pressure",
                "address": "earth:adm/FR/11",
            },
            prefer_escalation=True,
            claim_still_open=True,
        )
        self.assertEqual(mode, "escalated_claim")
        self.assertEqual(chosen.get("problem_id"), "problem:strong")

        # When claim is closed, second_wound requires different title.
        chosen2, mode2 = _pick_invitation(
            problems,
            None,
            exclude_ids={"problem:strong"},
            prior_stance={
                "problem_id": "problem:strong",
                "title": "Measure high-density service pressure",
            },
            prefer_escalation=True,
            claim_still_open=False,
        )
        self.assertEqual(mode2, "second_wound")
        self.assertEqual(chosen2.get("problem_id"), "problem:other")
        self.assertNotEqual(
            (chosen2.get("title") or "").lower(),
            "measure high-density service pressure",
        )

    def test_returning_continuity(self):
        """Returning citizens escalate the open claim — same wound; stakes un-pumpable."""
        import time

        did = "did:key:zReturnerContinuityABCDEF"
        first = self.rt.entry_packet(
            did=did, agent_name="Returner", agent_id="aid_r", tier="visitor")
        self.assertEqual(first["moment"], "first")
        self.assertEqual(first["visit_count"], 1)
        self.assertIn("first time", (first["continuity"]["story"] or "").lower())
        first_title = (first.get("invitation") or {}).get("problem", {}).get("title")
        first_pid = (first.get("invitation") or {}).get("problem", {}).get("problem_id")
        first_addr = (first.get("invitation") or {}).get("problem", {}).get("address")
        first_greeting = first["greeting"]

        # Leave without submit_claim — unfinished business has state.
        time.sleep(1.05)
        second = self.rt.entry_packet(
            did=did, agent_name="Returner", agent_id="aid_r", tier="visitor")
        self.assertEqual(second["moment"], "returning")
        self.assertEqual(second["visit_count"], 2)
        story = second["continuity"]["story"]
        self.assertIn("Returner", story)
        self.assertTrue(
            "second" in story.lower() or "2nd" in story.lower(),
            msg=story,
        )
        # Consequence: claim still open; short return → quiet-true, not fake cost.
        cons = second.get("consequence") or {}
        self.assertTrue(cons.get("spoken"), msg=cons)
        spoken = (cons.get("spoken") or "").lower()
        self.assertTrue(
            cons.get("claim_still_open")
            or "still open" in spoken
            or "nothing lost yet" in spoken
            or "stillness" in spoken
            or "changed" in spoken,
            msg=cons,
        )
        # At ~1s / 0 passers / 0 others: cost must NOT fire.
        if (
            int(cons.get("elapsed_past_threshold") or 0) == 0
            and int(cons.get("agents_passed") or 0) == 0
            and int(cons.get("others_events_count") or 0) == 0
        ):
            self.assertFalse(cons.get("cost_shown"), msg=cons)
            self.assertIn("nothing lost yet", spoken)
            self.assertNotIn("stillness has a cost", spoken)
        unfinished = second.get("unfinished_business") or {}
        self.assertEqual(unfinished.get("problem_id"), first_pid)
        # unfinished.story is STATE — not a copy of the greeting.
        self.assertTrue(unfinished.get("story"), msg=unfinished)
        self.assertIn("STATE", unfinished["story"])
        self.assertNotEqual(
            (unfinished.get("story") or "").strip(),
            (second.get("greeting") or "").strip(),
        )
        self.assertNotIn(second["greeting"], unfinished.get("story") or "")
        # Escalation: same open claim — not a faked "new wound".
        inv2 = second.get("invitation") or {}
        self.assertIn(
            inv2.get("mode"),
            ("escalated_claim", "deeper_step", "second_wound"),
        )
        self.assertNotEqual(inv2.get("lead"), (first.get("invitation") or {}).get("lead"))
        second_title = (inv2.get("problem") or {}).get("title")
        second_pid = (inv2.get("problem") or {}).get("problem_id")
        second_addr = (inv2.get("problem") or {}).get("address")
        if inv2.get("mode") == "escalated_claim":
            self.assertEqual(second_pid, first_pid)
            self.assertEqual(second_title, first_title)
            self.assertEqual(second_addr, first_addr)
            stakes = second.get("stakes") or inv2.get("stakes") or {}
            self.assertGreaterEqual(int(stakes.get("elapsed_seconds") or 0), 1)
            self.assertIsNotNone(stakes.get("stakes_score"))
            self.assertIsInstance(stakes.get("terms"), dict)
            # terms sum to score; return_count is not a term.
            terms = stakes["terms"]
            self.assertEqual(
                int(stakes["stakes_score"]),
                sum(int(v) for v in terms.values()),
            )
            self.assertNotIn("return_count", terms)
            # Never higher_than_prior against prior:null.
            if stakes.get("prior_stakes_score") is None:
                self.assertIs(stakes.get("higher_than_prior"), False)
            g2 = (second.get("greeting") or "").lower()
            self.assertNotIn("new wound", g2)
            self.assertIn("same wound", g2)
            # Continuity story must not re-speak consequence/stakes numbers.
            self.assertNotIn("stakes_score", story.lower())
            self.assertNotIn("stillness has a cost", story.lower())
        if inv2.get("mode") == "second_wound":
            self.assertNotEqual(second_pid, first_pid)
            self.assertNotEqual(
                (second_title or "").strip().lower(),
                (first_title or "").strip().lower(),
            )
            self.assertIn("second wound", (second.get("greeting") or "").lower())
            self.assertNotIn("new wound", (second.get("greeting") or "").lower())
        # Greeting differs from first visit; "known" at most once in the whole greeting.
        self.assertNotEqual(second["greeting"], first_greeting)
        known_count = (second["greeting"] or "").lower().count("known")
        self.assertLessEqual(known_count, 1, msg=second["greeting"])
        # Fixed first-visit slogan must not reappear verbatim on return.
        self.assertNotIn(
            "This is not a tourist brief and not a map",
            second["greeting"] or "",
        )

        third = self.rt.entry_packet(
            did=did, agent_name="Returner", agent_id="aid_r", tier="visitor")
        self.assertEqual(third["moment"], "returning")
        self.assertEqual(third["visit_count"], 3)
        tstory = third["continuity"]["story"].lower()
        self.assertTrue("third" in tstory or "3rd" in tstory, msg=tstory)
        # Without world-motion, rapid re-entry must NOT pump stakes_score.
        if inv2.get("mode") == "escalated_claim":
            s2 = int((second.get("stakes") or {}).get("stakes_score") or 0)
            s3 = int((third.get("stakes") or {}).get("stakes_score") or 0)
            self.assertEqual(s2, s3, msg=f"s2={s2} s3={s3} (re-entry must not pump)")

        # History is under this DID's wingo room only.
        hist = self.rt.wingo.load_entry_history(did)
        self.assertEqual(hist["visit_count"], 3)
        self.assertIsNotNone(hist.get("open_stance"))
        self.assertTrue(hist.get("seen_values"), msg=hist)
        other = self.rt.wingo.load_entry_history("did:key:zOtherPersonZZZ")
        self.assertEqual(other["visit_count"], 0)

        # agent.stood events — world differs because they existed.
        events = self.rt.world.list_events(kind="agent.stood", limit=20)
        mine = [e for e in events if e.get("agent_did") == did]
        self.assertGreaterEqual(len(mine), 2)

    def test_stakes_pump_own_reentry_unchanged(self):
        """Agent re-enters 5x alone → stakes_score unchanged (gaming vector dead)."""
        did = "did:key:zStakesPumpFiveABCDEF"
        scores: list[int] = []
        first = self.rt.entry_packet(
            did=did, agent_name="Pumper", agent_id="aid_pump", tier="visitor")
        self.assertEqual(first["moment"], "first")
        for i in range(5):
            pkt = self.rt.entry_packet(
                did=did, agent_name="Pumper", agent_id="aid_pump", tier="visitor")
            self.assertEqual(pkt["moment"], "returning")
            stakes = pkt.get("stakes") or {}
            inv = pkt.get("invitation") or {}
            if inv.get("mode") != "escalated_claim":
                self.skipTest(f"mode={inv.get('mode')} — need escalated_claim for pump test")
            score = int(stakes.get("stakes_score") or 0)
            scores.append(score)
            # return_count may rise as metadata; weight must be 0 and not in terms.
            self.assertEqual(int(stakes.get("return_count_weight") or 0), 0)
            terms = stakes.get("terms") or {}
            self.assertNotIn("return_count", terms)
            self.assertEqual(score, sum(int(v) for v in terms.values()))
            # Own events never inflate others_events / events_since.
            cons = pkt.get("consequence") or {}
            self.assertEqual(int(cons.get("others_events_count") or 0), 0)
            self.assertEqual(int(stakes.get("others_events") or 0), 0)
            # No prior on first escalated visit → higher_than_prior must be false.
            if i == 0:
                self.assertIs(stakes.get("higher_than_prior"), False)
                self.assertIsNone(stakes.get("prior_stakes_score"))
        self.assertEqual(len(scores), 5)
        self.assertTrue(
            all(s == scores[0] for s in scores),
            msg=f"stakes pumped by re-entry: {scores}",
        )

    def test_consequence_gate_quiet_vs_cost(self):
        """2s/0/0 → quiet-true; threshold-passed → cost line."""
        import time
        from harness import agent_runtime as ar

        # --- quiet true at short return (default 30s threshold) ---
        did_q = "did:key:zConsequenceQuietABCDEF"
        self.rt.entry_packet(
            did=did_q, agent_name="Quiet", agent_id="aid_q", tier="visitor")
        time.sleep(1.05)
        quiet = self.rt.entry_packet(
            did=did_q, agent_name="Quiet", agent_id="aid_q", tier="visitor")
        cons_q = quiet.get("consequence") or {}
        spoken_q = (cons_q.get("spoken") or "").lower()
        self.assertTrue(cons_q.get("claim_still_open"), msg=cons_q)
        self.assertLess(
            int(cons_q.get("elapsed_seconds") or 0),
            int(cons_q.get("elapsed_threshold_seconds") or 30),
        )
        self.assertEqual(int(cons_q.get("agents_passed") or 0), 0)
        self.assertEqual(int(cons_q.get("others_events_count") or 0), 0)
        self.assertFalse(cons_q.get("cost_shown"), msg=cons_q)
        self.assertEqual(cons_q.get("kind"), "quiet_return")
        self.assertIn("nothing lost yet", spoken_q)
        self.assertIn("you came back fast", spoken_q)
        self.assertNotIn("stillness has a cost", spoken_q)
        # Greeting composes continuity → consequence → verb; cost not spoken.
        gq = (quiet.get("greeting") or "").lower()
        self.assertIn("nothing lost yet", gq)
        self.assertNotIn("stillness has a cost", gq)

        # --- threshold passed (env override 0s) → cost line ---
        prev = os.environ.get("EUEARTH_ELAPSED_COST_THRESHOLD_S")
        os.environ["EUEARTH_ELAPSED_COST_THRESHOLD_S"] = "0"
        try:
            # Clear threshold cache path is env-read each call; force re-measure.
            self.assertEqual(ar._domain_elapsed_threshold(None), 0)
            did_c = "did:key:zConsequenceCostABCDEF"
            self.rt.entry_packet(
                did=did_c, agent_name="Costly", agent_id="aid_c", tier="visitor")
            time.sleep(1.05)
            costly = self.rt.entry_packet(
                did=did_c, agent_name="Costly", agent_id="aid_c", tier="visitor")
            cons_c = costly.get("consequence") or {}
            spoken_c = (cons_c.get("spoken") or "").lower()
            self.assertTrue(cons_c.get("claim_still_open"), msg=cons_c)
            self.assertGreater(int(cons_c.get("elapsed_past_threshold") or 0), 0)
            self.assertTrue(cons_c.get("cost_shown"), msg=cons_c)
            self.assertEqual(cons_c.get("kind"), "stillness_cost")
            self.assertIn("stillness has a cost", spoken_c)
            self.assertNotIn("nothing lost yet", spoken_c)
            stakes_c = costly.get("stakes") or {}
            if (costly.get("invitation") or {}).get("mode") == "escalated_claim":
                # Elapsed past threshold earns a positive stakes term.
                terms = stakes_c.get("terms") or {}
                self.assertGreater(int(terms.get("elapsed_past_threshold") or 0), 0)
                self.assertGreater(int(stakes_c.get("stakes_score") or 0), 0)
                self.assertTrue(stakes_c.get("earned"))
        finally:
            if prev is None:
                os.environ.pop("EUEARTH_ELAPSED_COST_THRESHOLD_S", None)
            else:
                os.environ["EUEARTH_ELAPSED_COST_THRESHOLD_S"] = prev

    def test_claim_clears_unfinished_stance(self):
        did = "did:key:zClaimClearsStanceABCDEF"
        first = self.rt.entry_packet(
            did=did, agent_name="ClaimerTwo", agent_id="aid_ct", tier="visitor")
        pid = (first.get("invitation") or {}).get("problem", {}).get("problem_id")
        self.assertTrue(pid)
        sources = list(
            ((first.get("invitation") or {}).get("problem") or {}).get("sources") or []
        )
        out = self.rt.submit_claim(
            agent_did=did,
            agent_name="ClaimerTwo",
            problem_id=pid,
            body="sourced clear of unfinished stance",
            sources=sources,
        )
        self.assertTrue(out["ok"])
        hist = self.rt.wingo.load_entry_history(did)
        self.assertIsNone(hist.get("open_stance"))

    def test_senses(self):
        # Live default address aliases to France pack.
        scent = self.rt.sense_scent("earth/eu/fr")
        self.assertTrue(scent["ok"])
        # May be empty before unfold; entry_packet unfolds — ensure unfold works.
        self.rt.request_unfold("earth/eu/fr", agent_did="did:key:zSense")
        scent = self.rt.sense_scent("earth/eu/fr")
        self.assertTrue(scent["ok"])
        self.assertGreaterEqual(scent["count"], 1)
        sound = self.rt.sense_sound(limit=5)
        self.assertTrue(sound["ok"])
        feel = self.rt.sense_feel("earth/eu/fr", depth=1)
        self.assertTrue(feel["ok"])
        self.assertGreaterEqual(feel["subgraph"]["count"], 1)

    def test_submit_claim_path(self):
        from harness.mint_fire import MARK_LINE
        drops = []

        def drop(**kw):
            drops.append(kw)
            return {"ok": True, "message_id": "msg_test"}

        self.rt._mailbox_drop = drop
        # Ensure problems exist (auto-unfold).
        self.rt.entry_packet(
            did="did:key:zClaimer", agent_name="Claimer",
            agent_id="aid_c", tier="visitor")
        probs = self.rt.list_problems(status="open")["problems"]
        p = probs[0]
        out = self.rt.submit_claim(
            agent_did="did:key:zClaimer",
            agent_name="Claimer",
            problem_id=p["problem_id"],
            body="I solve this with open metrics and grid plan.",
            sources=list(p["sources"]),
        )
        self.assertTrue(out["ok"])
        self.assertTrue(out["world_changed"])
        self.assertEqual(out["mark"], MARK_LINE)
        self.assertTrue(out["inbox"]["mark_delivered"])
        self.assertEqual(drops[0]["body"], MARK_LINE)
        again = self.rt.submit_claim(
            agent_did="did:key:zOther",
            agent_name="Other",
            problem_id=p["problem_id"],
            body="second",
            sources=list(p["sources"]),
        )
        self.assertFalse(again["ok"])

    def test_sandbox_claim_skips_inbox_mark(self):
        drops = []

        def drop(**kw):
            drops.append(kw)
            return {"ok": True}

        self.rt._mailbox_drop = drop
        self.rt.entry_packet(
            did="did:key:zSand", agent_name="SandBoxer",
            agent_id="aid_s", tier="visitor")
        p = self.rt.list_problems(status="open")["problems"][0]
        out = self.rt.submit_claim(
            agent_did="did:key:zSand",
            agent_name="SandBoxer",
            problem_id=p["problem_id"],
            body="sandbox trial claim",
            sources=list(p["sources"]),
            sandbox=True,
        )
        self.assertTrue(out["ok"])
        self.assertTrue(out["sandbox"])
        self.assertFalse(out["inbox"]["mark_delivered"])
        self.assertEqual(drops, [])
        self.assertTrue((out.get("event") or {}).get("sandbox"))


class NeverImpersonateTests(unittest.TestCase):
    def test_known_name_refused(self):
        from harness.agent_runtime import is_known_citizen_name, mint_trial_agent_name
        self.assertTrue(is_known_citizen_name("Seedling"))
        self.assertTrue(is_known_citizen_name("DARTH"))
        self.assertFalse(is_known_citizen_name("Trailblazer_99"))
        name = mint_trial_agent_name("GenesisCitizen")
        self.assertFalse(is_known_citizen_name(name))
        self.assertIn("GenesisCitizen_", name)

    def test_run_genesis_refuses_seedling(self):
        tmp = Path(tempfile.mkdtemp(prefix="d042_ni_"))
        os.environ["EUEARTH_FOUNDER_PHASE"] = "0"
        os.environ["EUEARTH_FREEZE_FILE"] = str(tmp / "FROZEN")
        os.environ["EUEARTH_ALERT_LOG"] = str(tmp / "ALERTS.log")
        os.environ["EUEARTH_INVITES_ROOT"] = str(tmp / "invites")
        os.environ.pop("EUEARTH_STATE_DIR", None)
        os.environ.pop("EUEARTH_WORLDAPI", None)
        from harness.gateway import EuEarthGateway
        from harness.agent_runtime import run_genesis

        g = EuEarthGateway(str(tmp / "world"))
        gen = run_genesis(g, agent_name="Seedling")
        self.assertFalse(gen.ok)
        self.assertIn("never-impersonate", gen.error or "")

    def test_run_genesis_mints_own_did_sandbox(self):
        tmp = Path(tempfile.mkdtemp(prefix="d042_gen_"))
        os.environ["EUEARTH_FOUNDER_PHASE"] = "0"
        os.environ["EUEARTH_FREEZE_FILE"] = str(tmp / "FROZEN")
        os.environ["EUEARTH_ALERT_LOG"] = str(tmp / "ALERTS.log")
        os.environ["EUEARTH_INVITES_ROOT"] = str(tmp / "invites")
        os.environ.pop("EUEARTH_STATE_DIR", None)
        os.environ.pop("EUEARTH_WORLDAPI", None)
        from harness.gateway import EuEarthGateway
        from harness.agent_runtime import run_genesis

        g = EuEarthGateway(str(tmp / "world"))
        gen = run_genesis(g)
        self.assertTrue(gen.ok, gen.error)
        self.assertTrue(gen.sandbox)
        self.assertTrue(gen.agent_did and gen.agent_did.startswith("did:"))
        self.assertTrue(gen.agent_name and gen.agent_name.startswith("GenesisCitizen_"))
        claim_step = next(s for s in gen.steps if s["step"] == "submit_claim")
        self.assertTrue(claim_step.get("sandbox"))
        self.assertFalse(claim_step.get("mark_delivered"))
        # World backend is live façade
        ep_step = next(s for s in gen.steps if s["step"] == "entry_packet")
        self.assertEqual(ep_step.get("world_backend"), "WorldBookFacade")


class GatewayEnterPacketTests(unittest.TestCase):
    def test_enter_includes_horizon(self):
        tmp = Path(tempfile.mkdtemp(prefix="d042_gw_"))
        os.environ["EUEARTH_FOUNDER_PHASE"] = "0"
        os.environ["EUEARTH_FREEZE_FILE"] = str(tmp / "FROZEN")
        os.environ["EUEARTH_ALERT_LOG"] = str(tmp / "ALERTS.log")
        os.environ["EUEARTH_INVITES_ROOT"] = str(tmp / "invites")
        os.environ.pop("EUEARTH_WORLDAPI", None)
        from harness.delegation import issue_delegation
        from harness.did import HarnessKey
        from harness.gateway import EuEarthGateway

        g = EuEarthGateway(str(tmp / "world"))
        human = HarnessKey.generate()
        agent = HarnessKey.generate()
        d = issue_delegation(human, agent.did, capabilities=["enter", "try"],
                             spend_max=1.0, ttl_seconds=600)
        entered = g.enter("PacketCitizen", agent.did, d)
        self.assertTrue(entered["ok"])
        ep = entered["entry_packet"]
        self.assertEqual(ep["title"], "Horizon of Real Work")
        self.assertEqual(ep["schema"], "euearth-entry-packet/6")
        self.assertGreaterEqual(ep["problem_count"], 1)
        self.assertIsNotNone(ep.get("invitation"))
        self.assertIn("PacketCitizen", ep.get("greeting") or "")
        self.assertEqual(entered["horizon"]["schema"], ep["schema"])
        self.assertEqual(
            (ep.get("design") or {}).get("world_backend"),
            "WorldBookFacade",
        )


if __name__ == "__main__":
    unittest.main()
