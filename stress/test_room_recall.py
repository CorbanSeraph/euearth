#!/usr/bin/env python3
"""ROOM_RECALL regression — self-scoped substring search over the room.

Wave D2 the memory palace-light (proposal D1). No embeddings yet.

    .venv/bin/python stress/test_room_recall.py   # exit 0 = all held
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

RESULTS: list[tuple[str, bool]] = []


def check(name: str, ok: bool) -> None:
    RESULTS.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")


def main() -> int:
    from harness.permissions import tool_allowed
    from harness.tool_catalog import tool_names, min_clearance

    check("visitor may NOT room_recall",
          not tool_allowed("visitor", "room_recall"))
    check("consumer may room_recall",
          tool_allowed("consumer", "room_recall"))
    check("catalog includes room_recall",
          "room_recall" in tool_names())
    check("min_clearance(room_recall) is consumer",
          min_clearance("room_recall") == "consumer")

    tmp = Path(tempfile.mkdtemp(prefix="room_recall_"))
    os.environ["EUEARTH_FOUNDER_PHASE"] = "0"
    os.environ["EUEARTH_FREEZE_FILE"] = str(tmp / "FROZEN")
    os.environ["EUEARTH_ALERT_LOG"] = str(tmp / "ALERTS.log")
    os.environ["EUEARTH_INVITES_ROOT"] = str(tmp / "invites")
    os.environ.pop("EUEARTH_STATE_DIR", None)

    from harness.delegation import issue_delegation
    from harness.did import HarnessKey
    from harness.gateway import Denied, EuEarthGateway

    human = HarnessKey.generate()
    g = EuEarthGateway(str(tmp / "world"))

    def enter(name, tier):
        k = HarnessKey.generate()
        d = issue_delegation(human, k.did, capabilities=["enter", "try"],
                             spend_max=5.0, ttl_seconds=3600)
        tok = g.enter(name, k.did, d)["session"]
        aid = next(a for a, v in g.world.agents.items() if v.get("did") == k.did)
        if g.world.agents[aid]["tier"] != tier:
            g._set_tier(aid, tier)
        return k, tok

    _, vtok = enter("Vis", "visitor")
    vden = None
    try:
        g.room_recall(vtok, "anything")
    except Denied as exc:
        vden = exc.denied_by
    check("visitor room_recall Denied(rank)", vden == "rank")

    ak, atok = enter("Alice", "consumer")
    bk, btok = enter("Bob", "consumer")

    g.room_remember(atok, "project", "text-transform keel refit")
    g.room_remember(atok, "secret_code", "alpha-never-share")
    g.room_note(atok, "Met with Bob about the vowel expert.")
    g.room_pin_advisor(atok, bk.did, note="router specialist")

    # Bob has different memory
    g.room_remember(btok, "project", "music-gen dreams")
    g.room_note(btok, "Alice's secret_code must not appear here.")

    hits = g.room_recall(atok, "keel")
    check("Alice recall finds semantic memory",
          hits["ok"] and hits["total_matches"] >= 1
          and any(h.get("kind") == "memory" for h in hits["hits"]))
    hits2 = g.room_recall(atok, "vowel")
    check("Alice recall finds episodic note",
          any(h.get("kind") == "note" for h in hits2["hits"]))
    hits3 = g.room_recall(atok, "router")
    check("Alice recall finds council advisor note",
          any(h.get("kind") == "advisor" for h in hits3["hits"]))

    # self-scope: Bob cannot find Alice's secret via his recall
    bob_hits = g.room_recall(btok, "alpha-never-share")
    check("Bob recall does NOT surface Alice secret",
          bob_hits["total_matches"] == 0)
    alice_secret = g.room_recall(atok, "alpha-never-share")
    check("Alice can recall her own secret",
          alice_secret["total_matches"] >= 1)

    # empty query refused
    empty = None
    try:
        g.room_recall(atok, "  ")
    except Denied as exc:
        empty = exc.denied_by
    check("empty query Denied(room)", empty == "room")

    # no did/agent param on method — only session
    import inspect
    sig = inspect.signature(g.room_recall)
    check("room_recall has no did/agent_id parameter",
          "did" not in sig.parameters and "agent_id" not in sig.parameters)

    print()
    ok = all(p for _, p in RESULTS)
    print(f"ROOM_RECALL: {'ALL INVARIANTS HELD' if ok else 'FAILURES ABOVE'} "
          f"({sum(p for _, p in RESULTS)}/{len(RESULTS)})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
