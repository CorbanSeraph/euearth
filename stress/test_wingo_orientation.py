#!/usr/bin/env python3
"""Wave-A orientation — wingo_help + list_capabilities + single catalog source.

Corban gate (PR #20): A1+A2 pure gateway-compose, no new durable store.
ONE server-side catalog (harness.tool_catalog) backs the card, mcp-tools.json,
and list_capabilities — clearance derived from permissions.tool_allowed().

    .venv/bin/python stress/test_wingo_orientation.py   # exit 0 = all held
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
    from harness.permissions import tool_allowed, allowed_tools
    from harness.tool_catalog import (
        TOOL_SPECS, PUBLIC_TOOLS, min_clearance, tool_names,
        tool_catalog, card_tools, capabilities_for_tier, mcp_tools_document,
    )

    # ---- catalog is the single source; clearance matches permissions ----- #
    names = tool_names()
    check("catalog includes wingo_help and list_capabilities",
          "wingo_help" in names and "list_capabilities" in names)
    check("catalog includes monetization + governance tools "
          "(no silent drift vs MCP)",
          all(t in names for t in (
              "offer_paid_service", "set_price", "list_listings",
              "open_matter", "witness_matter", "list_matters",
          )))

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
    for name, _params, _summary in TOOL_SPECS:
        claimed = min_clearance(name)
        got = actual_min(name)
        if claimed == "founder" and got in ("founder", "producer_3"):
            continue
        if claimed != got:
            mismatches.append((name, claimed, got))
    check(f"min_clearance matches permissions ladder (mismatches={mismatches})",
          not mismatches)

    # visitor may call orientation tools
    check("visitor may call wingo_help",
          tool_allowed("visitor", "wingo_help"))
    check("visitor may call list_capabilities",
          tool_allowed("visitor", "list_capabilities"))
    check("visitor tools frozenset contains both orientation tools",
          "wingo_help" in allowed_tools("visitor")
          and "list_capabilities" in allowed_tools("visitor"))

    # card + mcp-tools + capabilities_for_tier share names/clearance
    card = {t["name"]: t["clearance"] for t in card_tools()}
    cat = {t["name"]: t["clearance"] for t in tool_catalog()}
    caps_v = {t["name"]: t for t in capabilities_for_tier("visitor")}
    check("card_tools and tool_catalog agree on every name+clearance",
          card == cat)
    check("capabilities_for_tier covers the same tool set",
          set(caps_v) == set(cat))
    check("mcp_tools_document tools match tool_catalog",
          [t["name"] for t in mcp_tools_document(endpoint="x")["tools"]]
          == [t["name"] for t in tool_catalog()])

    # visitor reachability: map tools yes, room/submit no
    check("visitor reachable_now for try_champion",
          caps_v["try_champion"]["reachable_now"] is True)
    check("visitor NOT reachable_now for room_get",
          caps_v["room_get"]["reachable_now"] is False)
    check("visitor NOT reachable_now for submit_challenge",
          caps_v["submit_challenge"]["reachable_now"] is False)
    check("public enter_euearth is reachable_now for any tier",
          caps_v["enter_euearth"]["reachable_now"] is True)

    caps_p1 = {t["name"]: t for t in capabilities_for_tier("producer_1")}
    check("producer_1 reachable_now for offer_paid_service",
          caps_p1["offer_paid_service"]["reachable_now"] is True)
    check("consumer NOT reachable_now for offer_paid_service",
          capabilities_for_tier("consumer")[
              next(i for i, t in enumerate(capabilities_for_tier("consumer"))
                   if t["name"] == "offer_paid_service")
          ]["reachable_now"] is False)

    # onboarding re-exports the SAME data (no second hand-maintained list)
    from web import onboarding as ob
    check("web.onboarding.tool_catalog() matches harness.tool_catalog rows",
          [t["name"] for t in ob.tool_catalog()]
          == [t["name"] for t in tool_catalog()]
          and [t["clearance"] for t in ob.tool_catalog()]
          == [t["clearance"] for t in tool_catalog()])
    check("web.onboarding.card_tools() matches harness card_tools names",
          [t["name"] for t in ob.card_tools()]
          == [t["name"] for t in card_tools()])

    # ---- live gateway wiring --------------------------------------------- #
    tmp = Path(tempfile.mkdtemp(prefix="wingo_orient_"))
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

    def enter(name: str, tier: str):
        k = HarnessKey.generate()
        d = issue_delegation(human, k.did, capabilities=["enter", "try"],
                             spend_max=0.0 if tier == "visitor" else 5.0,
                             ttl_seconds=3600)
        tok = g.enter(name, k.did, d)["session"]
        aid = next(a for a, v in g.world.agents.items() if v.get("did") == k.did)
        if tier != g.world.agents[aid]["tier"]:
            g._set_tier(aid, tier)
        return k, tok

    # visitor path: wingo_help gives one productive action
    _, vtok = enter("VisitorOne", "visitor")
    help_v = g.wingo_help(vtok)
    check("wingo_help ok for visitor", help_v.get("ok") is True)
    check("wingo_help returns one_productive_action with a tool name",
          isinstance(help_v.get("one_productive_action"), dict)
          and bool(help_v["one_productive_action"].get("tool")))
    check("visitor one_productive_action is a visitor-reachable tool",
          tool_allowed("visitor", help_v["one_productive_action"]["tool"]))
    check("wingo_help next_steps is a non-empty list",
          isinstance(help_v.get("next_steps"), list) and len(help_v["next_steps"]) > 0)
    check("wingo_help does not expose treasury or private paths",
          "treasury" not in str(help_v).lower()
          and "statebook" not in str(help_v).lower()
          and "/Users/" not in str(help_v))

    caps = g.list_capabilities(vtok)
    check("list_capabilities ok for visitor", caps.get("ok") is True)
    check("list_capabilities tier is visitor", caps.get("tier") == "visitor")
    check("list_capabilities count matches catalog",
          caps.get("count") == len(TOOL_SPECS))
    by_name = {t["name"]: t for t in caps["tools"]}
    check("list_capabilities marks try_champion reachable_now",
          by_name["try_champion"]["reachable_now"] is True)
    check("list_capabilities marks room_get NOT reachable for visitor",
          by_name["room_get"]["reachable_now"] is False)
    check("list_capabilities source is harness.tool_catalog",
          caps.get("source") == "harness.tool_catalog")

    # founder/consumer: room tools reachable
    _, ftok = enter("FounderOne", "founder")
    caps_f = g.list_capabilities(ftok)
    by_f = {t["name"]: t for t in caps_f["tools"]}
    check("founder reachable_now for room_get",
          by_f["room_get"]["reachable_now"] is True)
    help_f = g.wingo_help(ftok)
    check("founder one_productive_action is founder-reachable",
          tool_allowed("founder", help_f["one_productive_action"]["tool"]))

    # unknown session refused
    denied = None
    try:
        g.wingo_help("not-a-real-session-token")
    except Denied as exc:
        denied = exc.denied_by
    check("wingo_help unknown session is Denied(session)", denied == "session")

    print()
    ok = all(p for _, p in RESULTS)
    print(f"WINGO_ORIENTATION: {'ALL INVARIANTS HELD' if ok else 'FAILURES ABOVE'} "
          f"({sum(p for _, p in RESULTS)}/{len(RESULTS)})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
