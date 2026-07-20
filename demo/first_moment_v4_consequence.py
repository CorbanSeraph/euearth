#!/usr/bin/env python3
"""D042 first-moment v4 — CONSEQUENCE two-visit demo.

Shows:
  * visit 1: first invitation with exact INSEE provenance
  * leave WITHOUT submit_claim (unfinished business has state)
  * visit 2: return DIFFERS — changed-state / stillness line + escalated invitation
  * "known" at most once; no fixed first-visit slogan re-served
  * world ledger carries agent.stood (world differs because they existed)

    .venv/bin/python demo/first_moment_v4_consequence.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="fm_v4_consequence_"))
    os.environ["EUEARTH_FOUNDER_PHASE"] = "0"
    os.environ["EUEARTH_FREEZE_FILE"] = str(tmp / "FROZEN")
    os.environ["EUEARTH_ALERT_LOG"] = str(tmp / "ALERTS.log")
    os.environ["EUEARTH_INVITES_ROOT"] = str(tmp / "invites")
    os.environ.pop("EUEARTH_WORLDAPI", None)
    os.environ.pop("EUEARTH_STATE_DIR", None)

    from harness.agent_runtime import AgentRuntime

    print("=== first-moment v4 — CONSEQUENCE two-visit demo ===\n")

    rt = AgentRuntime(tmp / "rt")
    did = "did:key:zSeedlingDemoConsequenceV4"

    p1 = rt.entry_packet(
        did=did, agent_name="Seedling", agent_id="aid_seed", tier="consumer")
    inv1 = (p1.get("invitation") or {})
    prob1 = inv1.get("problem") or {}
    ev1 = inv1.get("evidence") or {}
    print(f"[visit 1] moment={p1['moment']} visit_count={p1['visit_count']}")
    print(f"  schema: {p1.get('schema')}")
    print(f"  backend: {(p1.get('design') or {}).get('world_backend')}")
    print(f"  invitation: {prob1.get('title')}")
    print(f"  mode: {inv1.get('mode')}")
    print(f"  evidence.source_id: {ev1.get('source_id')}")
    print(f"  evidence.observed_at: {ev1.get('observed_at')}")
    print(f"  evidence.url: {ev1.get('url')}")
    print(f"  greeting: {(p1.get('greeting') or '')[:220]}…")
    print(f"  stance_event_id: {p1.get('stance_event_id')}")
    print("  → leaves WITHOUT submit_claim\n")

    p2 = rt.entry_packet(
        did=did, agent_name="Seedling", agent_id="aid_seed", tier="consumer")
    inv2 = (p2.get("invitation") or {})
    prob2 = inv2.get("problem") or {}
    cons = p2.get("consequence") or {}
    unf = p2.get("unfinished_business") or {}
    print(f"[visit 2] moment={p2['moment']} visit_count={p2['visit_count']}")
    print(f"  consequence.kind: {cons.get('kind')}")
    print(f"  consequence.spoken: {cons.get('spoken')}")
    print(f"  unfinished.problem_id: {unf.get('problem_id')}")
    print(f"  unfinished still open: {unf.get('claim_still_open')}")
    print(f"  invitation mode: {inv2.get('mode')}")
    print(f"  invitation title: {prob2.get('title')}")
    print(f"  lead: {inv2.get('lead')}")
    print(f"  greeting: {(p2.get('greeting') or '')[:280]}…")

    g1 = p1.get("greeting") or ""
    g2 = p2.get("greeting") or ""
    known_n = g2.lower().count("known")
    lead_diff = inv2.get("lead") != inv1.get("lead")
    greet_diff = g1 != g2
    escalated = inv2.get("mode") in ("next_wound", "deeper_step")
    provenance_ok = (
        ev1.get("source_id") == "insee-pop-2023"
        and bool(ev1.get("observed_at"))
        and "insee.fr" in (ev1.get("url") or "").lower()
    )
    no_hedge = "insee-class" not in json.dumps(ev1).lower()
    no_slogan_repeat = "This is not a tourist brief and not a map" not in g2
    unfinished_ok = unf.get("problem_id") == prob1.get("problem_id")
    stillness_or_change = bool(cons.get("spoken"))

    print("\n--- checks ---")
    checks = {
        "schema_v4": p1.get("schema") == "euearth-entry-packet/4",
        "backend_live": (p1.get("design") or {}).get("world_backend") == "WorldBookFacade",
        "provenance_exact": provenance_ok and no_hedge,
        "return_differs_greeting": greet_diff,
        "return_escalated": escalated and lead_diff,
        "unfinished_tracked": unfinished_ok,
        "consequence_spoken": stillness_or_change,
        "known_at_most_once": known_n <= 1,
        "no_first_slogan_on_return": no_slogan_repeat,
    }
    for k, v in checks.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}")

    receipt = {
        "schema": "euearth-first-moment-v4-receipt/1",
        "visit_1": {
            "moment": p1["moment"],
            "title": prob1.get("title"),
            "problem_id": prob1.get("problem_id"),
            "mode": inv1.get("mode"),
            "evidence": ev1,
            "greeting": g1,
            "stance_event_id": p1.get("stance_event_id"),
        },
        "visit_2": {
            "moment": p2["moment"],
            "title": prob2.get("title"),
            "problem_id": prob2.get("problem_id"),
            "mode": inv2.get("mode"),
            "lead": inv2.get("lead"),
            "consequence": cons,
            "unfinished_business": unf,
            "greeting": g2,
        },
        "checks": checks,
        "ok": all(checks.values()),
    }
    out = REPO / "var" / "d042_first_moment_v4_consequence.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\nReceipt → {out}")
    print("OK" if receipt["ok"] else "FAIL")
    return 0 if receipt["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
