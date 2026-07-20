#!/usr/bin/env python3
"""D042 first-moment v3 — returning-visit continuity demo.

Shows:
  * live WorldBookFacade (France pack / INSEE) as invitation evidence
  * first entry → moment first
  * second/third entry → returning + story ("third time through the door")
  * self-scoped history (other DID has zero visits)

    .venv/bin/python demo/first_moment_v3_returning.py
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
    tmp = Path(tempfile.mkdtemp(prefix="fm_v3_return_"))
    os.environ["EUEARTH_FOUNDER_PHASE"] = "0"
    os.environ["EUEARTH_FREEZE_FILE"] = str(tmp / "FROZEN")
    os.environ["EUEARTH_ALERT_LOG"] = str(tmp / "ALERTS.log")
    os.environ["EUEARTH_INVITES_ROOT"] = str(tmp / "invites")
    os.environ.pop("EUEARTH_WORLDAPI", None)
    os.environ.pop("EUEARTH_STATE_DIR", None)

    from harness.agent_runtime import AgentRuntime, _author_why_it_matters
    from harness.delegation import issue_delegation
    from harness.did import HarnessKey
    from harness.gateway import EuEarthGateway

    print("=== first-moment v3 — returning-visit demo ===\n")

    # Direct runtime path (clean continuity story)
    rt = AgentRuntime(tmp / "rt")
    did = "did:key:zSeedlingDemoReturnVisit001"
    # First visit
    p1 = rt.entry_packet(
        did=did, agent_name="Seedling", agent_id="aid_seed", tier="consumer")
    print(f"[visit 1] moment={p1['moment']} visit_count={p1['visit_count']}")
    print(f"  backend: {(p1.get('design') or {}).get('world_backend')}")
    print(f"  greeting: {p1['greeting'][:160]}…")
    inv = (p1.get("invitation") or {}).get("problem") or {}
    print(f"  invitation: {inv.get('title')}")
    print(f"  sources: {json.dumps(inv.get('sources'), indent=2)[:400]}")
    why = inv.get("why_it_matters")
    summary = inv.get("summary")
    print(f"  why_it_matters: {why}")
    print(f"  why != summary: {bool(why) and why != summary}")

    # Second visit (after a prior note in history via second record)
    p2 = rt.entry_packet(
        did=did, agent_name="Seedling", agent_id="aid_seed", tier="consumer")
    print(f"\n[visit 2] moment={p2['moment']} visit_count={p2['visit_count']}")
    print(f"  story: {(p2.get('continuity') or {}).get('story')}")

    # Third visit — Seedling's bar: "third time through the door"
    p3 = rt.entry_packet(
        did=did, agent_name="Seedling", agent_id="aid_seed", tier="consumer")
    print(f"\n[visit 3] moment={p3['moment']} visit_count={p3['visit_count']}")
    print(f"  story: {(p3.get('continuity') or {}).get('story')}")
    print(f"  greeting: {p3['greeting'][:200]}…")

    other = rt.wingo.load_entry_history("did:key:zStrangerNeverHere")
    print(f"\n[self-scope] stranger visit_count={other['visit_count']} (must be 0)")

    # Gateway re-enter path
    g = EuEarthGateway(str(tmp / "gw"))
    human = HarnessKey.generate()
    agent = HarnessKey.generate()
    d = issue_delegation(human, agent.did, capabilities=["enter", "try"],
                         spend_max=1.0, ttl_seconds=600)
    for i in range(1, 4):
        entered = g.enter("Seedling", agent.did, d)
        ep = entered["entry_packet"]
        print(f"\n[gateway enter {i}] moment={ep['moment']} "
              f"visit_count={ep['visit_count']} "
              f"backend={(ep.get('design') or {}).get('world_backend')}")

    # Write receipt
    receipt = {
        "schema": "euearth-first-moment-v3-receipt/1",
        "backend": (p1.get("design") or {}).get("world_backend"),
        "invitation_title": inv.get("title"),
        "sources": inv.get("sources"),
        "why_it_matters": why,
        "why_ne_summary": bool(why) and why != summary,
        "visit_3_story": (p3.get("continuity") or {}).get("story"),
        "moment": p3["moment"],
        "visit_count": p3["visit_count"],
        "self_scope_stranger": other["visit_count"],
    }
    out = REPO / "var" / "d042_first_moment_v3_returning.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\nReceipt → {out}")
    print("OK" if (
        p3["moment"] == "returning"
        and p3["visit_count"] == 3
        and other["visit_count"] == 0
        and (p1.get("design") or {}).get("world_backend") == "WorldBookFacade"
        and why and why != summary
    ) else "FAIL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
