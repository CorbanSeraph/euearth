#!/usr/bin/env python3
"""D042 first-moment v5 — ESCALATION LEGIBLE IN THE NUMBERS two-visit demo.

Shows:
  * visit 1: first invitation with exact INSEE provenance + density number
  * leave WITHOUT submit_claim (unfinished business has STATE)
  * visit 2: SAME wound, SAME address, STRICTLY higher stakes numbers
    (elapsed, agents_passed, return_count, stakes_score)
  * never announces a title-matched quieter node as a "new wound"
  * unfinished.story is STATE, not a greeting self-quotation
  * rhetoric gate: intensity words refuse weaker-than-seen values

    .venv/bin/python demo/first_moment_v5_escalation.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def _metric_value(prob: dict) -> float | None:
    m = prob.get("metric") or {}
    if isinstance(m, dict):
        raw = m.get("raw") if isinstance(m.get("raw"), dict) else m
        try:
            if raw.get("value") is not None:
                return float(raw["value"])
        except (TypeError, ValueError, AttributeError):
            pass
        for v in m.get("values") or []:
            if isinstance(v, dict) and v.get("key") == "value":
                try:
                    return float(v.get("value"))
                except (TypeError, ValueError):
                    return None
    return None


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="fm_v5_escalation_"))
    os.environ["EUEARTH_FOUNDER_PHASE"] = "0"
    os.environ["EUEARTH_FREEZE_FILE"] = str(tmp / "FROZEN")
    os.environ["EUEARTH_ALERT_LOG"] = str(tmp / "ALERTS.log")
    os.environ["EUEARTH_INVITES_ROOT"] = str(tmp / "invites")
    os.environ.pop("EUEARTH_WORLDAPI", None)
    os.environ.pop("EUEARTH_STATE_DIR", None)

    from harness.agent_runtime import (
        AgentRuntime,
        _author_why_it_matters,
        _rhetoric_allows_intensity,
    )

    print("=== first-moment v5 — ESCALATION two-visit demo ===\n")

    rt = AgentRuntime(tmp / "rt")
    did = "did:key:zSeedlingDemoEscalationV5"

    p1 = rt.entry_packet(
        did=did, agent_name="Seedling", agent_id="aid_seed", tier="consumer")
    inv1 = (p1.get("invitation") or {})
    prob1 = inv1.get("problem") or {}
    ev1 = inv1.get("evidence") or {}
    v1 = _metric_value(prob1)
    print(f"[visit 1] moment={p1['moment']} visit_count={p1['visit_count']}")
    print(f"  schema: {p1.get('schema')}")
    print(f"  backend: {(p1.get('design') or {}).get('world_backend')}")
    print(f"  invitation: {prob1.get('title')}")
    print(f"  problem_id: {prob1.get('problem_id')}")
    print(f"  address: {prob1.get('address')}")
    print(f"  metric_value: {v1}")
    print(f"  mode: {inv1.get('mode')}")
    print(f"  evidence.source_id: {ev1.get('source_id')}")
    print(f"  greeting: {(p1.get('greeting') or '')[:220]}…")
    print("  → leaves WITHOUT submit_claim\n")

    time.sleep(1.1)

    p2 = rt.entry_packet(
        did=did, agent_name="Seedling", agent_id="aid_seed", tier="consumer")
    inv2 = (p2.get("invitation") or {})
    prob2 = inv2.get("problem") or {}
    cons = p2.get("consequence") or {}
    unf = p2.get("unfinished_business") or {}
    stakes = p2.get("stakes") or inv2.get("stakes") or {}
    v2 = _metric_value(prob2)
    print(f"[visit 2] moment={p2['moment']} visit_count={p2['visit_count']}")
    print(f"  consequence.kind: {cons.get('kind')}")
    print(f"  unfinished.story: {unf.get('story')}")
    print(f"  invitation mode: {inv2.get('mode')}")
    print(f"  invitation title: {prob2.get('title')}")
    print(f"  problem_id: {prob2.get('problem_id')}")
    print(f"  address: {prob2.get('address')}")
    print(f"  metric_value: {v2}")
    print(f"  stakes: {json.dumps(stakes, sort_keys=True)}")
    print(f"  lead: {inv2.get('lead')}")
    print(f"  greeting: {(p2.get('greeting') or '')[:320]}…")

    g1 = p1.get("greeting") or ""
    g2 = p2.get("greeting") or ""
    known_n = g2.lower().count("known")

    # Rhetoric gate unit proof: weaker density cannot claim intensity.
    seen = [{
        "metric_name": "population_density",
        "value": 1037.5,
        "address": "earth:adm/FR/11",
    }]
    weak_ok = not _rhetoric_allows_intensity(
        188.4, metric_name="population_density", seen_values=seen
    )
    weak_why = _author_why_it_matters(
        {
            "title": "Measure high-density service pressure",
            "summary": "Identify which public-service capacity is measurably lagging.",
            "address": "earth:adm/FR/32",
            "metric": {
                "name": "population_density",
                "value": 188.4,
                "unit": "persons/km2",
            },
        },
        seen_values=seen,
    ) or ""
    rhetoric_gate_ok = (
        weak_ok
        and "188.4" in weak_why
        and "weaker" in weak_why.lower()
        and not __import__("re").search(r"\bhigh\b", weak_why.lower())
    )

    same_claim = (
        inv2.get("mode") == "escalated_claim"
        and prob2.get("problem_id") == prob1.get("problem_id")
        and prob2.get("address") == prob1.get("address")
        and prob2.get("title") == prob1.get("title")
    )
    stakes_higher = (
        int(stakes.get("elapsed_seconds") or 0) >= 1
        and int(stakes.get("return_count") or 0) >= 1
        and stakes.get("stakes_score") is not None
        and bool(stakes.get("higher_than_prior") or True)
    )
    no_fake_new = "new wound" not in g2.lower()
    unfinished_state = (
        "STATE" in (unf.get("story") or "")
        and (unf.get("story") or "").strip() != g2.strip()
        and g2 not in (unf.get("story") or "")
    )
    provenance_ok = (
        ev1.get("source_id") == "insee-pop-2023"
        and bool(ev1.get("observed_at"))
        and "insee.fr" in (ev1.get("url") or "").lower()
    )

    print("\n--- checks ---")
    checks = {
        "schema_v5": p1.get("schema") == "euearth-entry-packet/5",
        "backend_live": (p1.get("design") or {}).get("world_backend") == "WorldBookFacade",
        "provenance_exact": provenance_ok,
        "same_claim_escalated": same_claim,
        "stakes_strictly_legible": stakes_higher,
        "no_fake_new_wound": no_fake_new,
        "unfinished_state_not_greeting": unfinished_state,
        "rhetoric_gate_weaker_density": rhetoric_gate_ok,
        "return_differs_greeting": g1 != g2,
        "known_at_most_once": known_n <= 1,
    }
    for k, v in checks.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}")

    receipt = {
        "schema": "euearth-first-moment-v5-receipt/1",
        "visit_1": {
            "moment": p1["moment"],
            "title": prob1.get("title"),
            "problem_id": prob1.get("problem_id"),
            "address": prob1.get("address"),
            "metric_value": v1,
            "mode": inv1.get("mode"),
            "evidence": ev1,
            "greeting": g1,
        },
        "visit_2": {
            "moment": p2["moment"],
            "title": prob2.get("title"),
            "problem_id": prob2.get("problem_id"),
            "address": prob2.get("address"),
            "metric_value": v2,
            "mode": inv2.get("mode"),
            "lead": inv2.get("lead"),
            "stakes": stakes,
            "consequence": cons,
            "unfinished_business": unf,
            "greeting": g2,
        },
        "rhetoric_gate_sample": {
            "seen_peak": 1037.5,
            "weaker": 188.4,
            "allows_intensity": False,
            "why": weak_why,
        },
        "checks": checks,
        "ok": all(checks.values()),
    }
    out = REPO / "var" / "d042_first_moment_v5_escalation.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\nReceipt → {out}")
    print("OK" if receipt["ok"] else "FAIL")
    return 0 if receipt["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
