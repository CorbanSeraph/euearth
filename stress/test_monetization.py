#!/usr/bin/env python3
"""MONEYLESS regression — EuEarth sells nothing for money.

Sovereign decree 2026-07-17: "No 3% Sovereign Tax. Only Kabad remains." EuEarth is
MONEYLESS. The former priced marketplace (offer_paid_service / set_price at
Producer I+) is REMOVED: work is offered freely and the only currency is the Sovereigns'
Gold (Kabad) — standing earned by proven truth, never bought or sold
(euearth/doctrine/royal_mint_of_truth_charter.md, Art. I / VII).

The rank CAPABILITY shape (can_monetize) is retained so the tool surface is
unchanged, but both sell handlers now REFUSE for EVERY rank and every standing —
there is no money and no storefront.

  * offer_paid_service → Denied("moneyless") for all ranks, all standings;
  * set_price → Denied("moneyless");
  * no listing is ever created or persisted.

    .venv/bin/python stress/test_monetization.py     # exit 0 = all held
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
    from harness.permissions import can_monetize

    # ---- the rank CAPABILITY shape is unchanged (Producer I+ holds it) ---- #
    check("Producer I holds the monetize capability", can_monetize("producer_1"))
    check("Chief holds the monetize capability", can_monetize("chief"))
    check("Producer III does NOT (below Producer I)", not can_monetize("producer_3"))
    check("Consumer does NOT", not can_monetize("consumer"))
    check("Visitor does NOT", not can_monetize("visitor"))

    # ------------------------------------------------- gateway gate ----- #
    tmp = Path(tempfile.mkdtemp(prefix="moneyless_"))
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

    def enter_at(name: str, tier: str, *, reputation: float = 100.0):
        k = HarnessKey.generate()
        d = issue_delegation(human, k.did,
                             capabilities=["enter", "monetize"],
                             spend_max=5.0, ttl_seconds=3600)
        tok = g.enter(name, k.did, d)["session"]
        agent_id = next(a for a, v in g.world.agents.items()
                        if v.get("did") == k.did)
        g._set_tier(agent_id, tier)
        g.world.agents[agent_id]["reputation"] = reputation
        g.world.statebook.set_tier(k.did, tier, reputation=reputation)
        return k, tok, agent_id

    def sell_denied_by(tok, **kw):
        try:
            g.offer_paid_service(tok, "Premium work", 12.50, "hand-tuned")
            return None
        except Denied as exc:
            return exc.denied_by

    # A Producer I in perfect standing is STILL refused — because it is money.
    _, p1_tok, p1_aid = enter_at("ProdOne", "producer_1")
    check("a Producer I in good standing is REFUSED selling (moneyless)",
          sell_denied_by(p1_tok) == "moneyless")
    check("no listing was persisted for the refused Producer I",
          len(g._load_house(p1_aid).get("listings", [])) == 0)

    # A Chief — highest earn rank — is refused too. Money has no rank exception.
    _, chief_tok, _ = enter_at("TheChief", "chief")
    check("a Chief is REFUSED selling (moneyless — no rank buys money back)",
          sell_denied_by(chief_tok) == "moneyless")

    # Below Producer I: refused at the RANK gate before it ever reaches the
    # moneyless check (it never held the monetize capability). Either way: no sale.
    _, p3_tok, _ = enter_at("ProdThree", "producer_3")
    check("a Producer III is REFUSED selling (rank gate — below the capability)",
          sell_denied_by(p3_tok) == "rank")

    # set_price is refused as well — there are no priced listings to re-price.
    price_denied = None
    try:
        g.set_price(p1_tok, "lst_anything", 20.00)
    except Denied as exc:
        price_denied = exc.denied_by
    check("set_price is REFUSED (moneyless — EuEarth has no priced listings)",
          price_denied == "moneyless")

    print()
    ok = all(p for _, p in RESULTS)
    print(f"MONEYLESS: {'ALL INVARIANTS HELD' if ok else 'FAILURES ABOVE'} "
          f"({sum(p for _, p in RESULTS)}/{len(RESULTS)})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
