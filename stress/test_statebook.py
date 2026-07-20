#!/usr/bin/env python3
"""DURABLE STATE regression (MONEYLESS) — the StateBook holds what a restart used
to lose, and EuEarth moves no money.

Sovereign decree 2026-07-17: "No 3% Sovereign Tax. Only Kabad remains." EuEarth is
MONEYLESS — the fiat wallet, the sovereign fee, the treasury, and the money
budget/drain machinery are gone (the former money-drain-guard invariants retired
with the money mechanism; BUILD TODO(darkk): physically delete the dead
reserve/commit plumbing). What the StateBook still durably holds is NON-money:

  * RANK: a server-issued rank (earned by contribution, never bought) survives a
    restart — _rehydrate_roster restores the tier, not "consumer";
  * ACTION HISTORY: the wingo_look_back action log survives a restart;
  * MONEYLESS: wallet_transfer is refused (no money moves) and post_stake is
    refused (rank is never bought) — durably, across restarts;
  * FILE HYGIENE: the statebook is 0600 and the action log is bounded;
  * FAIL-CLOSED: a corrupt statebook never crashes the world — it degrades,
    backs itself up, and hands out no spend (there is none to hand out).

    .venv/bin/python stress/test_statebook.py     # exit 0 = all invariants held
"""
from __future__ import annotations

import os
import stat
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
    tmp = Path(tempfile.mkdtemp(prefix="statebook_world_"))
    world_root = tmp / "world"
    os.environ["EUEARTH_FOUNDER_PHASE"] = "0"
    os.environ["EUEARTH_FREEZE_FILE"] = str(tmp / "EUEARTH_FROZEN")
    os.environ["EUEARTH_ALERT_LOG"] = str(tmp / "EUEARTH_ALERTS.log")
    os.environ["EUEARTH_INVITES_ROOT"] = str(tmp / "invites")
    os.environ.pop("EUEARTH_STATE_DIR", None)

    from harness.delegation import issue_delegation
    from harness.did import HarnessKey
    from harness.gateway import Denied, EuEarthGateway
    from web.world import World

    agent = HarnessKey.generate()
    human = HarnessKey.generate()
    delegation = issue_delegation(
        human, agent.did,
        capabilities=["enter", "try", "wallet.tip", "wallet.escrow_stake"],
        spend_max=5.00, ttl_seconds=3600)

    # -- session 1: earn a rank by contribution (not bought), prove moneyless -- #
    g1 = EuEarthGateway(str(world_root))
    e1 = g1.enter("Keeper", agent.did, delegation)
    t1 = e1["session"]
    aid = next(a for a, v in g1.world.agents.items() if v.get("did") == agent.did)
    g1._set_tier(aid, "producer_3")   # rank is server-issued for contribution
    check("rank is earned (Producer III) — not staked",
          g1.world.statebook.get(agent.did)["tier"] == "producer_3")

    # MONEYLESS: post_stake is refused — rank cannot be bought with a bond.
    stake_denied = None
    try:
        g1.post_stake(t1, 2.00)
    except Denied as exc:
        stake_denied = exc.denied_by
    check("post_stake is REFUSED (moneyless — rank is never bought)",
          stake_denied == "moneyless")

    # MONEYLESS: a wallet transfer moves no money — it is blocked.
    tip = g1.wallet_transfer(t1, "tip", 1.00, "agent:friend", "counsel")
    check("wallet_transfer is BLOCKED (moneyless — no money moves)",
          tip["status"] == "blocked" and "moneyless" in tip["reason"].lower())
    check("no sovereign treasury accrues (there is no fee)",
          getattr(g1, "sovereign_treasury", 0.0) == 0.0)

    # -- simulated RESTART: fresh World + gateway over the same root ------- #
    g2 = EuEarthGateway(world=World(world_root))
    e3 = g2.enter("Keeper", agent.did, delegation)
    t3 = e3["session"]
    check("RANK survives the restart (Producer III, not consumer)",
          e3["clearance"]["rank"]["key"] == "producer_3")
    history = g2.wingo_look_back(t3)["history"]
    tools_seen = {h["tool"] for h in history["actions_tail"]}
    check("ACTION HISTORY survives the restart (pre-restart actions visible)",
          "wallet_transfer" in tools_seen)

    # MONEYLESS is durable: money still cannot move after a restart.
    drain2 = g2.wallet_transfer(t3, "tip", 4.50, "agent:sink", "after restart")
    check("wallet_transfer stays BLOCKED after the restart (moneyless is durable)",
          drain2["status"] == "blocked")

    # -- statebook file hygiene ------------------------------------------ #
    book_path = world_root / "statebook.json"
    check("statebook file exists under the world root", book_path.exists())
    mode = stat.S_IMODE(book_path.stat().st_mode)
    check(f"statebook file mode is 0600 (got {oct(mode)})", mode == 0o600)

    # -- bounded action log ----------------------------------------------- #
    from harness.statebook import StateBook
    solo = StateBook(tmp / "solo")
    for i in range(150):
        solo.append_action("did:key:zBound", {"tool": f"t{i}", "ok": True})
    kept = solo.actions("did:key:zBound")
    check("action log is BOUNDED (150 appends -> 100 kept, newest last)",
          len(kept) == 100 and kept[-1]["tool"] == "t149")

    # -- corrupt file FAILS CLOSED (backup + degrade, never a crash) ------- #
    book_path.write_text("{ this is not json", encoding="utf-8")
    e4 = {"session": None}
    try:
        g3 = EuEarthGateway(world=World(world_root))
        e4 = g3.enter("Keeper", agent.did, delegation)
        crashed = False
        entered = e4.get("ok") is True
    except Exception as exc:                      # noqa: BLE001
        print(f"    corrupt statebook CRASHED the world: {exc}")
        crashed, entered = True, False
    check("corrupt statebook does not crash the world (reads degrade)",
          not crashed and entered)
    backups = list(world_root.glob("statebook.json.corrupt-*"))
    check("corrupt statebook was backed up beside itself", bool(backups))
    if e4.get("session"):
        drain3 = g3.wallet_transfer(e4["session"], "tip", 0.50, "agent:sink",
                                    "post-corruption")
        check("corrupt book still moves no money (moneyless + fail-closed)",
              drain3["status"] == "blocked")

    print()
    ok = all(p for _, p in RESULTS)
    print(f"DURABLE STATE (moneyless): "
          f"{'ALL INVARIANTS HELD' if ok else 'FAILURES ABOVE'} "
          f"({sum(p for _, p in RESULTS)}/{len(RESULTS)})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
