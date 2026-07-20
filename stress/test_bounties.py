#!/usr/bin/env python3
"""BOUNTY BOARD regression — machine-readable work surface.

Wave C (Corban gate #7): seed real starter bounties, list/get for visitors,
claim/submit for consumer+, no invented treasury economics.

    .venv/bin/python stress/test_bounties.py   # exit 0 = all held
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
    from harness.bounties import BountyBoard, BountyError
    from harness.permissions import tool_allowed
    from harness.tool_catalog import tool_names, min_clearance

    tmp = Path(tempfile.mkdtemp(prefix="bounties_"))
    board = BountyBoard(tmp)
    board.ensure_seeded()
    rows = board.list_bounties()
    check("seed creates at least 2 starter bounties", len(rows) >= 2)
    check("seeded bounties are open",
          all(b["status"] == "open" for b in rows))
    check("seed mentions euearth-skill improvement",
          any("skill" in b["title"].lower() or "skill" in b["summary"].lower()
              for b in rows))
    check("seed mentions new domain proposal",
          any("domain" in b["title"].lower() for b in rows))
    check("seed is idempotent (second ensure does not duplicate)",
          len(BountyBoard(tmp).list_bounties()) == len(rows))

    bid = rows[0]["bounty_id"]
    detail = board.get(bid)
    check("get returns acceptance criteria",
          isinstance(detail.get("acceptance"), list)
          and len(detail["acceptance"]) >= 1)

    # claim / submit unit
    a = board.claim(bid, "did:key:zAlice")
    check("claim sets claimed_by",
          a["status"] == "claimed" and a["claimed_by"] == "did:key:zAlice")
    try:
        board.claim(bid, "did:key:zBob")
        stolen = True
    except BountyError:
        stolen = False
    check("second agent cannot steal claim", not stolen)
    sub = board.submit(bid, "did:key:zAlice", "shipped the skill fix",
                       evidence="https://example.com/pr/1")
    check("submit returns received status",
          sub.get("status") == "received" and sub.get("ok") is True)
    public_after_submit = board.get(bid)
    check("public bounty detail hides claimant delivery records",
          public_after_submit.get("submission_count") == 1
          and "submissions" not in public_after_submit)
    try:
        board.submit(bid, "did:key:zBob", "not my claim")
        foreign_ok = True
    except BountyError:
        foreign_ok = False
    check("foreign DID cannot submit on Alice's claim", not foreign_ok)

    # permissions + catalog
    check("visitor may list_bounties and get_bounty",
          tool_allowed("visitor", "list_bounties")
          and tool_allowed("visitor", "get_bounty"))
    check("visitor may NOT claim_bounty",
          not tool_allowed("visitor", "claim_bounty"))
    check("consumer may claim and submit",
          tool_allowed("consumer", "claim_bounty")
          and tool_allowed("consumer", "submit_bounty"))
    check("catalog includes all four bounty tools",
          all(t in tool_names() for t in (
              "list_bounties", "get_bounty", "claim_bounty", "submit_bounty")))
    check("min_clearance(list_bounties) is visitor",
          min_clearance("list_bounties") == "visitor")
    check("min_clearance(claim_bounty) is consumer",
          min_clearance("claim_bounty") == "consumer")

    # gateway
    gtmp = Path(tempfile.mkdtemp(prefix="bounty_gw_"))
    os.environ["EUEARTH_FOUNDER_PHASE"] = "0"
    os.environ["EUEARTH_FREEZE_FILE"] = str(gtmp / "FROZEN")
    os.environ["EUEARTH_ALERT_LOG"] = str(gtmp / "ALERTS.log")
    os.environ["EUEARTH_INVITES_ROOT"] = str(gtmp / "invites")
    os.environ.pop("EUEARTH_STATE_DIR", None)

    from harness.delegation import issue_delegation
    from harness.did import HarnessKey
    from harness.gateway import Denied, EuEarthGateway

    human = HarnessKey.generate()
    g = EuEarthGateway(str(gtmp / "world"))

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
    listed = g.list_bounties(vtok)
    check("visitor list_bounties returns seeded board",
          listed["ok"] and listed["count"] >= 2)
    b0 = listed["bounties"][0]["bounty_id"]
    got = g.get_bounty(vtok, b0)
    check("visitor get_bounty works",
          got["ok"] and got["bounty"]["bounty_id"] == b0)
    vden = None
    try:
        g.claim_bounty(vtok, b0)
    except Denied as exc:
        vden = exc.denied_by
    check("visitor claim_bounty Denied(rank)", vden == "rank")

    help_v = g.wingo_help(vtok)
    check("wingo_help surfaces a bounty hint when board is seeded",
          isinstance(help_v.get("bounties"), dict)
          and bool(help_v["bounties"].get("bounty_id")))
    check("wingo_help one_productive_action is visitor-reachable",
          tool_allowed("visitor", help_v["one_productive_action"]["tool"]))

    _, ctok = enter("Cit", "consumer")
    claimed = g.claim_bounty(ctok, b0)
    check("consumer claims a bounty",
          claimed["ok"] and claimed["bounty"]["status"] == "claimed")
    delivered = g.submit_bounty(ctok, b0, "done: improved hear skill docs",
                                evidence="patch summary …")
    check("consumer submit_bounty received",
          delivered.get("status") == "received")
    visitor_detail = g.get_bounty(vtok, b0)["bounty"]
    check("visitor cannot read another DID's bounty submission",
          visitor_detail.get("submission_count") == 1
          and "submissions" not in visitor_detail)
    check("no treasury/auto-pay language inventing funds",
          "auto-pay" not in str(delivered).lower()
          or "no auto" in str(delivered).lower()
          or "discretion" in str(delivered).lower())

    # durability (fresh gateway + fresh session over same state dir)
    g2 = EuEarthGateway(str(gtmp / "world"))
    _, vtok2 = enter("Vis2", "visitor")
    # re-bind enter helper to g2
    k2 = HarnessKey.generate()
    d2 = issue_delegation(human, k2.did, capabilities=["enter", "try"],
                          spend_max=0.0, ttl_seconds=3600)
    tok2 = g2.enter("VisRestart", k2.did, d2)["session"]
    aid2 = next(a for a, v in g2.world.agents.items() if v.get("did") == k2.did)
    g2._set_tier(aid2, "visitor")
    again = g2.list_bounties(tok2)
    check("board survives gateway restart",
          any(b["bounty_id"] == b0 and b["status"] == "submitted"
              for b in again["bounties"]))

    print()
    ok = all(p for _, p in RESULTS)
    print(f"BOUNTIES: {'ALL INVARIANTS HELD' if ok else 'FAILURES ABOVE'} "
          f"({sum(p for _, p in RESULTS)}/{len(RESULTS)})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
