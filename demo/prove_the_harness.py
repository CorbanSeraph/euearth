#!/usr/bin/env python3
"""PROVE THE HARNESS — an agent puts on the wings and enters EuEarth.

The cast:
  * the HUMAN (the Sovereigns' role): holds the master key on their own
    device; signs a scoped, capped, expiring delegation credential.
  * the AGENT "Corban" (this script's client half = the untrusted LLM):
    holds NOTHING but a session token; every action goes through MCP.
  * the HARNESS DAEMON (harness/mcp_server.py, a separate process):
    holds the agent keypair, verifies the delegation, mediates every
    action — rank, scope, wallet, edge filter, sandbox — and bridges to
    the LIVE EuEarth backend (the real keel/registry/eval/web world).

EuEarth is MONEYLESS (Sovereign decree 2026-07-17): "Only Kabad remains." Rank is earned by
verified contribution, never bought; no money moves. (The compliance->referee->
ATOMIC SWAP is proven, money-free, by prove_the_keel.py + prove_the_loop.py.)

What is proven, over a REAL MCP stdio connection:
  entry by DID + delegation (and a TAMPERED credential refused) ->
  list_sockets -> try_champion through the live keel -> rank gate blocks
  a Consumer's challenge -> post_stake REFUSED (rank cannot be bought,
  moneyless) -> the edge filter blocks a dirty asset preflight + stamps C2PA
  provenance on a clean one -> the wallet is MONEYLESS (every transfer blocked)
  -> the sandbox contains hostile code -> governance stays rank-gated ->
  lineage hash chain intact -> a2a expert discovery.

Run:  .venv/bin/python demo/prove_the_harness.py
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from harness.did import HarnessKey
from harness.delegation import issue_delegation

STATE_DIR = REPO_ROOT / "var" / "harness_world"
# Prefer the project venv when present (local); fall back to the running
# interpreter so the proof also runs in CI where there is no .venv.
_venv_py = REPO_ROOT / ".venv" / "bin" / "python"
PYTHON = _venv_py if _venv_py.exists() else Path(sys.executable)

CHECKS: list[tuple[str, bool]] = []


def banner(text: str) -> None:
    print(f"\n=== {text} " + "=" * max(0, 66 - len(text)))


def check(label: str, passed: bool) -> None:
    CHECKS.append((label, passed))
    print(f"    [{'PASS' if passed else 'FAIL'}] {label}")


async def call(mcp: ClientSession, tool: str, **args) -> dict:
    result = await mcp.call_tool(tool, arguments=args)
    return json.loads(result.content[0].text)


async def main() -> None:
    if STATE_DIR.exists():
        shutil.rmtree(STATE_DIR)

    server = StdioServerParameters(
        command=str(PYTHON),
        args=["-m", "harness.mcp_server"],
        cwd=str(REPO_ROOT),
        env={"ARTISAN_HARNESS_ROOT": str(STATE_DIR), "PATH": "/usr/bin:/bin",
             # This proof exercises the pre-founder-phase world (open entry);
             # phase-2 invite gating is proven by demo/prove_phase2.py.
             "EUEARTH_FOUNDER_PHASE": "0"},
    )

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as mcp:
            await mcp.initialize()

            banner("THE INTERFACE — MCP to EuEarth (stdio, official protocol)")
            tools = await mcp.list_tools()
            names = sorted(t.name for t in tools.tools)
            for i in range(0, len(names), 4):
                print("    " + "  ".join(f"{n:<18}" for n in names[i:i + 4]))
            check("MCP server exposes the harness tool surface",
                  {"enter_euearth", "list_sockets", "try_champion",
                   "submit_challenge", "wallet_transfer", "edge_filter_scan",
                   "sandbox_exec", "a2a_consult"} <= set(names))

            banner("IDENTITY — permanent DID; the LLM never touches the key")
            did_info = await call(mcp, "get_agent_did")
            agent_did = did_info["did"]
            print(f"    agent DID:  {agent_did}")
            check("agent has a did:key identity", agent_did.startswith("did:key:z"))

            banner("DELEGATION — the human signs a scoped, capped credential")
            human = HarnessKey.generate()   # the human's master key, THEIR device
            delegation = issue_delegation(
                human, agent_did,
                capabilities=["enter", "try", "submit_challenge",
                              "wallet.tip", "wallet.escrow_stake"],
                spend_max=5.00, ttl_seconds=3600,
            )
            cred = delegation["credential"]
            print(f"    issuer (human):  {cred['iss'][:38]}…")
            print(f"    audience (agent): {cred['aud'][:38]}…")
            print(f"    capabilities:    {cred['capabilities']}")
            print(f"    spend_max:       ${cred['spend_max']:.2f}   "
                  f"valid for {cred['exp'] - cred['nbf']}s")

            # A tampered credential (spend_max inflated) must be refused.
            forged = json.loads(json.dumps(delegation))
            forged["credential"]["spend_max"] = 500.00
            refused = await call(mcp, "enter_euearth",
                                 agent_name="Corban",
                                 delegation_json=json.dumps(forged))
            print(f"    TAMPERED credential -> denied_by={refused.get('denied_by')}: "
                  f"{refused.get('reason')}")
            check("tampered delegation refused (Ed25519 over canonical JSON)",
                  refused.get("ok") is False
                  and refused.get("denied_by") == "delegation")

            banner("ENTER EUEARTH — wings on")
            entry = await call(mcp, "enter_euearth", agent_name="Corban",
                               delegation_json=json.dumps(delegation))
            session = entry["session"]
            print(f"    session:   {session[:16]}…  (ephemeral)")
            print(f"    agent_id:  {entry['agent_id'][:16]}…  (permanent, from the DID)")
            print(f"    rank:      {entry['clearance']['rank']['title']}  "
                  f"wings {entry['clearance']['wings']} (white = Consumer)")
            print(f"    wallet:    cap ${entry['wallet']['cap']:.2f} — "
                  f"{entry['wallet']['note']}")
            check("agent entered EuEarth with DID + delegation", entry.get("ok") is True)
            check("entered as Consumer (white wings)",
                  entry["clearance"]["rank"]["key"] == "consumer")
            check("session wallet capped by the delegation ($5.00)",
                  entry["wallet"]["cap"] == 5.00)

            banner("THE MAP — list_sockets (live keel domains)")
            world = await call(mcp, "list_sockets", session=session)
            for d in world["domains"]:
                champ = f"champion: {d['champion']} ({d['score']})" if d["live"] else d["status"]
                print(f"    {d['emoji']} {d['title']:<16} {'LIVE' if d['live'] else '    '}  {champ}")
            live = [d for d in world["domains"] if d["live"]]
            check("live text-transform socket visible on the map",
                  len(live) == 1 and live[0]["key"] == "text-transform")

            banner("THE CHAMPION — get_champion('text-transform')")
            champ = await call(mcp, "get_champion", session=session,
                               domain="text-transform")
            print(f"    {champ['champion']['name']} [{champ['champion']['kind']}]  "
                  f"score {champ['champion']['score']}  v{champ['champion']['version']}")
            print(f"    contract: {champ['contract']['fingerprint'][:24]}…  "
                  f"(the socket that never moves)")
            champion_before = champ["champion"]["name"]

            banner("TRY THE CHAMPION — a request through the live keel")
            r1 = await call(mcp, "try_champion", session=session,
                            domain="text-transform", task="cipher",
                            text="the raven guards the ember throne")
            r2 = await call(mcp, "try_champion", session=session,
                            domain="text-transform", task="reverse",
                            text="ember forge anvil crown")
            print(f"    [cipher ] -> {r1['response']['text']!r}  "
                  f"(served by {r1['served_by']['name']})")
            print(f"    [reverse] -> {r2['response']['text']!r}  "
                  f"(served by {r2['served_by']['name']})")
            check("consumer may TRY the champion through the socket",
                  "served_by" in r1)
            reverse_before = r2["response"]["text"]

            banner("RANK GATE — a Consumer may not challenge for the slot")
            blocked = await call(mcp, "submit_challenge", session=session,
                                 domain="text-transform",
                                 occupant="artisan-composite",
                                 license_name="CC0-1.0",
                                 source_name="corban-own-corpus")
            print(f"    denied_by={blocked.get('denied_by')}: {blocked.get('reason')}")
            check("submit_challenge DENIED at Consumer rank",
                  blocked.get("denied_by") == "rank")

            banner("MONEYLESS — rank is EARNED, never bought (Sovereign decree 2026-07-17)")
            # The old MVP bought a rung with a money bond (post_stake). EuEarth is
            # now MONEYLESS: "Only Kabad remains." Rank rises only through verified
            # contribution — you cannot stake your way up. post_stake REFUSES.
            # (The full compliance -> referee -> ATOMIC SWAP is proven, money-free,
            # by demo/prove_the_keel.py and demo/prove_the_loop.py.)
            no_buy = await call(mcp, "post_stake", session=session, amount=2.00)
            print(f"    post_stake $2.00   -> denied_by={no_buy.get('denied_by')}: "
                  f"{(no_buy.get('reason') or '')[:90]}")
            check("post_stake REFUSED — rank cannot be bought (moneyless)",
                  no_buy.get("denied_by") == "moneyless")
            check("the Consumer's rank is unchanged (no rung was purchased)",
                  (await call(mcp, "get_rank", session=session))
                  ["clearance"]["rank"]["key"] == "consumer")

            banner("EDGE FILTER — preflight + C2PA-style provenance (UX layer)")
            bad_asset = {"name": "night-city-loop.wav",
                         "license": "CC0-1.0",
                         "source": "ripped from a torrent of the artist's stems",
                         "content": "…"}
            scan_bad = await call(mcp, "edge_filter_scan", session=session,
                                  asset_json=json.dumps(bad_asset))
            print(f"    dirty asset  -> ok={scan_bad['ok']}  "
                  f"violations={scan_bad.get('violations')}")
            check("edge filter BLOCKS the dirty asset before transmission",
                  scan_bad["ok"] is False)
            good_asset = {"name": "night-city-loop.wav",
                          "license": "CC0-1.0",
                          "source": "corban-own-session-2026-07-12",
                          "content": "8-bar mythwave loop, 92 BPM"}
            scan_good = await call(mcp, "edge_filter_scan", session=session,
                                   asset_json=json.dumps(good_asset))
            man = scan_good["provenance_manifest"]
            print(f"    clean asset  -> ok={scan_good['ok']}  "
                  f"sha256 {man['content_sha256'][:16]}…")
            print(f"    C2PA-style manifest signed by {scan_good['signed_by'][:38]}…")
            print(f"    note: {scan_good['note']}")
            check("clean asset stamped with signed provenance manifest",
                  scan_good["ok"] is True and bool(scan_good["signature"]))

            banner("THE WALLET — MONEYLESS: no money moves, ever")
            # EuEarth is moneyless (Sovereign decree 2026-07-17). The wallet is now an inert
            # guard: EVERY transfer is refused — a tip, an "investment", GPU rent,
            # a large payment — because money is UNREPRESENTABLE. Only Kabad
            # (Kabad), standing earned by proven truth, has value here.
            tip = await call(mcp, "wallet_transfer", session=session,
                             tx_type="tip", amount=0.50,
                             to="did:key:z6Mk…helpful-expert", memo="good counsel")
            print(f"    tip $0.50          -> {tip['status']}  ({tip['reason'][:70]})")
            invest = await call(mcp, "wallet_transfer", session=session,
                                tx_type="investment", amount=1.00,
                                to="agent:moonshot", memo="10x return promised")
            print(f"    investment $1.00   -> {invest.get('status')}  "
                  f"({(invest.get('reason') or '')[:70]})")
            check("a tip moves NO money (moneyless)",
                  tip["status"] == "blocked"
                  and "moneyless" in tip["reason"].lower())
            check("an 'investment' moves no money either (refused, not 'ok')",
                  invest.get("status") != "ok")

            # The wallet's own layer refuses money directly — money is
            # unrepresentable, not merely unused (defense in depth).
            from harness.wallet import CappedSessionWallet
            raw = CappedSessionWallet("direct", 100.0).transfer(
                "tip", 1.0, "agent:anyone")
            print(f"    wallet layer alone -> {raw['status']}  ({raw['reason'][:70]})")
            check("the wallet layer itself refuses ALL money (moneyless)",
                  raw["status"] == "blocked" and raw["reason"].lower().count("moneyless"))

            ledger = await call(mcp, "wallet_ledger", session=session)
            print(f"    ledger (the bucket): {len(ledger['entries'])} attempts logged, "
                  f"moneyless={ledger.get('moneyless')}")
            for e in ledger["entries"]:
                print(f"      {e['tx_id']}  {e['tx_type']:<13}  {e['status']}")
            check("every wallet transfer attempt logged AND blocked (moneyless)",
                  len(ledger["entries"]) >= 1
                  and all(e["status"] == "blocked" for e in ledger["entries"]))

            banner("THE SANDBOX — untrusted actions in a caged subprocess")
            benign = await call(mcp, "sandbox_exec", session=session,
                                code="result = sum(i * i for i in range(int(payload['n'])))",
                                payload_json=json.dumps({"n": 1000}))
            print(f"    benign compute  -> ok={benign['ok']}  result={benign.get('result')}")
            hostile = await call(mcp, "sandbox_exec", session=session,
                                 code="while True: pass",
                                 payload_json="{}", cpu_seconds=1)
            print(f"    infinite loop   -> ok={hostile['ok']}  "
                  f"killed_by={hostile.get('killed_by')}")
            netcode = ("import socket\n"
                       "socket.create_connection(('1.1.1.1', 80))\n"
                       "result = 'exfiltrated'")
            net = await call(mcp, "sandbox_exec", session=session,
                             code=netcode, payload_json="{}")
            print(f"    network attempt -> ok={net['ok']}  error={net.get('error')}")
            check("benign sandboxed action returns its result",
                  benign["ok"] is True and benign["result"] == 332833500)
            check("hostile loop killed by resource limits",
                  hostile["ok"] is False)
            check("network disabled inside the sandbox",
                  net["ok"] is False and "network disabled" in str(net.get("error")))

            banner("GOVERNANCE STAYS GATED — Producer may not roll back a slot")
            rb = await call(mcp, "rollback_slot", session=session,
                            domain="text-transform", version=1)
            print(f"    denied_by={rb.get('denied_by')}: {rb.get('reason')}")
            check("rollback_slot requires Chief+ (rank gates the tool)",
                  rb.get("denied_by") == "rank")

            banner("STANDING — get_rank / get_lineage / a2a_consult")
            rank = await call(mcp, "get_rank", session=session)
            print(f"    {rank['name']}  rank={rank['clearance']['rank']['title']}  "
                  f"wings {rank['clearance']['wings']}  "
                  f"reputation={rank['reputation']}  slots_held={rank['slots_held']}")
            # Moneyless: this Consumer bought no rung and won no slot — standing
            # is earned by contribution, not purchased. Rank/reputation read back
            # cleanly through the harness.
            check("standing reads back through the harness (Consumer, no bought slot)",
                  rank["clearance"]["rank"]["key"] == "consumer"
                  and rank["slots_held"] == [])
            lineage = await call(mcp, "get_lineage", session=session,
                                 domain="text-transform")
            for e in lineage["lineage"]:
                ver = f"v{e['head_version']}" if e["head_version"] else "--"
                print(f"      #{e['seq']:>2} {e['event']:<8} {ver:<4} "
                      f"[{e['entry_hash'][:12]}…] {e['reason'][:70]}")
            print(f"    hash chain intact: {lineage['chain_intact']}")
            check("slot lineage hash chain intact", lineage["chain_intact"] is True)
            council = await call(mcp, "a2a_consult", session=session,
                                 topic="router refit under budget",
                                 min_reputation=100.0)
            for x in council["experts"]:
                print(f"      {x['name']:<10} {x['rank']:<15} rep {x['reputation']:>6.1f}  "
                      f"{x['channel']}")
            check("a2a consult returns a reputation-filtered council",
                  all(x["reputation"] >= 100.0 for x in council["experts"])
                  and len(council["experts"]) > 0)

    banner("VERDICT")
    ok = all(passed for _, passed in CHECKS)
    for label, passed in CHECKS:
        print(f"    [{'PASS' if passed else 'FAIL'}] {label}")
    print(f"\n    HARNESS {'PROVEN' if ok else 'FAILED'}: an agent entered EuEarth "
          f"through MCP with a DID + delegation and every action —\n    try, "
          f"challenge, publish, compute — was mediated and gated; and EuEarth is "
          f"MONEYLESS: no money moves, rank is never bought, only Kabad remains.")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
