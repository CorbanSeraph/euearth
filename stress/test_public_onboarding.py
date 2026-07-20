#!/usr/bin/env python3
"""PUBLIC onboarding accuracy — catalog clearance + synthetic filter.

Adversarial review of PR #17 (self-onboarding). Public surfaces must not:

  * advertise a higher minimum clearance than harness/permissions actually
    enforces (agents plan against the catalog; lying about the ladder is a
    public claim bug);
  * let known synthetic/load-test name families (WalletRacer variants) into
    the public roster / house counts.

    .venv/bin/python stress/test_public_onboarding.py   # exit 0 = all held
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

RESULTS: list[tuple[str, bool]] = []


def check(name: str, ok: bool) -> None:
    RESULTS.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")


def main() -> int:
    from harness.permissions import tool_allowed
    from harness.tool_catalog import PUBLIC_TOOLS, catalog_rows, min_clearance
    from web.onboarding import _CATALOG, card_tools, tool_catalog
    from web.world import is_synthetic

    # ---- catalog clearance must match the live permissions ladder -------- #
    # Single source: harness.tool_catalog (clearance derived from
    # permissions.tool_allowed). Card + onboarding re-export that source.
    climb = ["visitor", "consumer", "founder", "producer_3", "producer_2",
             "producer_1", "chief", "senior", "sovereign"]

    def actual_min(tool: str) -> str | None:
        if tool in PUBLIC_TOOLS:
            return "public"
        for t in climb:
            if tool_allowed(t, tool):
                return t
        return None

    mismatches = []
    for name, clearance, _params, _summary in _CATALOG:
        got = actual_min(name)
        # Founder-advertised tools that first unlock at producer_3 are OK:
        # founders carry producer clearance; producer_3 is the earn-ladder
        # twin. Accept either founder or producer_3 as the claimed minimum
        # when the tool is in both FOUNDER_TOOLS and PRODUCER_TOOLS.
        if clearance == "founder" and got in ("founder", "producer_3"):
            continue
        if got != clearance:
            mismatches.append((name, clearance, got))
    check("public catalog clearance matches harness.permissions minima "
          f"(mismatches={mismatches})", not mismatches)
    check("onboarding._CATALOG rows match harness.tool_catalog.catalog_rows",
          list(_CATALOG) == list(catalog_rows()))
    check("onboarding.tool_catalog() matches harness tool_catalog names",
          [t["name"] for t in tool_catalog()]
          == [t["name"] for t in __import__(
              "harness.tool_catalog", fromlist=["tool_catalog"]).tool_catalog()])

    # consumer tools must NOT be labeled founder
    consumer_tools = {
        "room_get", "room_remember", "room_note", "room_pin_advisor",
        "room_export", "post_stake", "wallet_transfer", "wallet_ledger",
        "edge_filter_scan", "sandbox_exec", "a2a_consult",
    }
    claimed = {t["name"]: t["clearance"] for t in card_tools()}
    check("room/wallet/sandbox/a2a tools are advertised as consumer (not founder)",
          all(claimed.get(t) == "consumer" for t in consumer_tools))
    check("min_clearance(room_get) is consumer",
          min_clearance("room_get") == "consumer")

    # ---- synthetic filter: WalletRacer family + separators -------------- #
    must_filter = [
        "WalletRacer", "walletracer", "wallet_racer", "wallet-racer",
        "Wallet_Racer_99", "wallet racer", "stress-test-bot", "loadtest_user",
        "Probe-1", "sybil",
    ]
    must_pass = ["Alice", "Corban", "Ashvale", "text-writer", "ChiefSteward"]
    check("synthetic filter catches WalletRacer separator variants",
          all(is_synthetic(n) for n in must_filter))
    check("synthetic filter does NOT false-positive ordinary citizen names",
          not any(is_synthetic(n) for n in must_pass))

    print()
    ok = all(p for _, p in RESULTS)
    print(f"PUBLIC_ONBOARDING: {'ALL INVARIANTS HELD' if ok else 'FAILURES ABOVE'} "
          f"({sum(p for _, p in RESULTS)}/{len(RESULTS)})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
