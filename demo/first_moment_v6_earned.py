#!/usr/bin/env python3
"""D042 first-moment v6 — ESCALATION MUST BE EARNED demo.

Shows:
  * visit 1: first invitation with exact INSEE provenance + density number
  * leave WITHOUT submit_claim (unfinished business has STATE)
  * visit 2 @ ~2s / 0 passers / 0 others:
      consequence = quiet-true ("nothing lost yet — you came back fast")
      stakes_score unchanged / unearned (world-motion terms all zero)
      NO "stillness has a cost" without numbers
  * 5 rapid re-entries: stakes_score flat (return_count cannot pump)
  * threshold-passed path (EUEARTH_ELAPSED_COST_THRESHOLD_S=0): cost line + earned terms
  * one composed greeting: continuity → consequence → stakes → verb
  * never higher_than_prior:true against prior:null

    .venv/bin/python demo/first_moment_v6_earned.py
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
    tmp = Path(tempfile.mkdtemp(prefix="fm_v6_earned_"))
    os.environ["EUEARTH_FOUNDER_PHASE"] = "0"
    os.environ["EUEARTH_FREEZE_FILE"] = str(tmp / "FROZEN")
    os.environ["EUEARTH_ALERT_LOG"] = str(tmp / "ALERTS.log")
    os.environ["EUEARTH_INVITES_ROOT"] = str(tmp / "invites")
    os.environ.pop("EUEARTH_WORLDAPI", None)
    os.environ.pop("EUEARTH_STATE_DIR", None)
    os.environ.pop("EUEARTH_ELAPSED_COST_THRESHOLD_S", None)

    from harness.agent_runtime import AgentRuntime

    print("=== first-moment v6 — ESCALATION MUST BE EARNED ===\n")

    rt = AgentRuntime(tmp / "rt")
    did = "did:key:zSeedlingDemoEarnedV6"

    p1 = rt.entry_packet(
        did=did, agent_name="Seedling", agent_id="aid_seed", tier="consumer")
    inv1 = (p1.get("invitation") or {})
    prob1 = inv1.get("problem") or {}
    ev1 = inv1.get("evidence") or {}
    v1 = _metric_value(prob1)
    print(f"[visit 1] moment={p1['moment']} visit_count={p1['visit_count']}")
    print(f"  schema: {p1.get('schema')}")
    print(f"  invitation: {prob1.get('title')}")
    print(f"  metric_value: {v1}")
    print(f"  greeting: {(p1.get('greeting') or '')[:200]}…")
    print("  → leaves WITHOUT submit_claim\n")

    time.sleep(1.1)

    p2 = rt.entry_packet(
        did=did, agent_name="Seedling", agent_id="aid_seed", tier="consumer")
    inv2 = (p2.get("invitation") or {})
    prob2 = inv2.get("problem") or {}
    cons = p2.get("consequence") or {}
    unf = p2.get("unfinished_business") or {}
    stakes = p2.get("stakes") or inv2.get("stakes") or {}
    g2 = p2.get("greeting") or ""
    print(f"[visit 2 ~1s] moment={p2['moment']} visit_count={p2['visit_count']}")
    print(f"  consequence.kind: {cons.get('kind')}")
    print(f"  consequence.spoken: {cons.get('spoken')}")
    print(f"  cost_shown: {cons.get('cost_shown')}")
    print(f"  stakes: {json.dumps({k: stakes.get(k) for k in ('elapsed_seconds','elapsed_past_threshold','agents_passed','others_events','return_count','terms','stakes_score','higher_than_prior','prior_stakes_score','earned')}, sort_keys=True)}")
    print(f"  unfinished.story: {unf.get('story')}")
    print(f"  greeting: {g2[:360]}…\n")

    # Five rapid re-entries — stakes must stay flat.
    pump_scores: list[int] = []
    for i in range(5):
        pi = rt.entry_packet(
            did=did, agent_name="Seedling", agent_id="aid_seed", tier="consumer")
        si = pi.get("stakes") or {}
        pump_scores.append(int(si.get("stakes_score") or 0))
    print(f"[pump 5x] stakes_scores={pump_scores}")

    # Threshold-passed path.
    os.environ["EUEARTH_ELAPSED_COST_THRESHOLD_S"] = "0"
    did_c = "did:key:zSeedlingDemoCostV6"
    rt.entry_packet(
        did=did_c, agent_name="Costly", agent_id="aid_cost", tier="consumer")
    time.sleep(1.1)
    pc = rt.entry_packet(
        did=did_c, agent_name="Costly", agent_id="aid_cost", tier="consumer")
    cons_c = pc.get("consequence") or {}
    stakes_c = pc.get("stakes") or {}
    print(f"\n[threshold=0 cost path] kind={cons_c.get('kind')} cost_shown={cons_c.get('cost_shown')}")
    print(f"  spoken: {cons_c.get('spoken')}")
    print(f"  stakes_score={stakes_c.get('stakes_score')} terms={stakes_c.get('terms')}")
    os.environ.pop("EUEARTH_ELAPSED_COST_THRESHOLD_S", None)

    same_claim = (
        inv2.get("mode") == "escalated_claim"
        and prob2.get("problem_id") == prob1.get("problem_id")
        and prob2.get("address") == prob1.get("address")
        and prob2.get("title") == prob1.get("title")
    )
    quiet_true = (
        cons.get("kind") == "quiet_return"
        and cons.get("cost_shown") is False
        and "nothing lost yet" in (cons.get("spoken") or "").lower()
        and "you came back fast" in (cons.get("spoken") or "").lower()
        and "stillness has a cost" not in (cons.get("spoken") or "").lower()
    )
    terms = stakes.get("terms") if isinstance(stakes.get("terms"), dict) else {}
    unpumpable = (
        stakes.get("stakes_score") is not None
        and "return_count" not in terms
        and int(stakes.get("return_count_weight") or 0) == 0
        and stakes.get("higher_than_prior") is False
        and stakes.get("prior_stakes_score") is None
        and int(stakes.get("stakes_score") or 0) == sum(int(v) for v in terms.values())
    )
    pump_flat = len(pump_scores) == 5 and all(s == pump_scores[0] for s in pump_scores)
    cost_path = (
        cons_c.get("kind") == "stillness_cost"
        and cons_c.get("cost_shown") is True
        and "stillness has a cost" in (cons_c.get("spoken") or "").lower()
        and int((stakes_c.get("terms") or {}).get("elapsed_past_threshold") or 0) > 0
    )
    # One composed greeting: continuity ordinal once; consequence once; no double stakes numbers.
    g2l = g2.lower()
    composed = (
        ("2nd" in g2l or "second" in g2l)
        and "nothing lost yet" in g2l
        and g2l.count("nothing lost yet") == 1
        and g2l.count("sense harder") <= 1
        and "return #" not in g2l  # old pump rhetoric dead
    )
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
        "schema_v6": p1.get("schema") == "euearth-entry-packet/6",
        "backend_live": (p1.get("design") or {}).get("world_backend") == "WorldBookFacade",
        "provenance_exact": provenance_ok,
        "same_claim_escalated": same_claim,
        "quiet_true_at_short_return": quiet_true,
        "stakes_unpumpable_terms": unpumpable,
        "stakes_pump_5x_flat": pump_flat,
        "threshold_passed_cost_line": cost_path,
        "one_composed_greeting": composed,
        "unfinished_state_not_greeting": unfinished_state,
        "no_fake_new_wound": "new wound" not in g2l,
    }
    for k, v in checks.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}")

    receipt = {
        "schema": "euearth-first-moment-v6-receipt/1",
        "visit_1": {
            "moment": p1["moment"],
            "title": prob1.get("title"),
            "problem_id": prob1.get("problem_id"),
            "metric_value": v1,
            "greeting": p1.get("greeting"),
        },
        "visit_2_quiet": {
            "moment": p2["moment"],
            "mode": inv2.get("mode"),
            "consequence": cons,
            "stakes": stakes,
            "unfinished_business": unf,
            "greeting": g2,
        },
        "pump_5x_scores": pump_scores,
        "threshold_cost_path": {
            "consequence": cons_c,
            "stakes": {
                "stakes_score": stakes_c.get("stakes_score"),
                "terms": stakes_c.get("terms"),
                "elapsed_past_threshold": stakes_c.get("elapsed_past_threshold"),
            },
        },
        "checks": checks,
        "ok": all(checks.values()),
    }
    out = REPO / "var" / "d042_first_moment_v6_earned.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\nReceipt → {out}")
    print("OK" if receipt["ok"] else "FAIL")
    return 0 if receipt["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
