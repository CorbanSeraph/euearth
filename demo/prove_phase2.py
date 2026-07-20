#!/usr/bin/env python3
"""PROVE PHASE 2 — a REMOTE agent, the invite gate, and the failsafe.

The cast:
  * the SOVEREIGN (Corban): mints founder invite codes and
    holds the AGENT-FREEZE FAILSAFE (the global platform PAUSE).
  * a REMOTE agent "Peregrine": lives OUTSIDE the server process, holds
    its own did:key + a human-signed delegation, and connects to the
    EuEarth backend over the network — MCP Streamable-HTTP at /mcp,
    served by the same FastAPI app that carries the human window.

What is proven, over a REAL HTTP connection to a live uvicorn server:
  1. FOUNDER PHASE: the unknown DID with NO invite is politely refused
     at enter_euearth.
  2. The sovereign mints a signed, single-use invite code (the real CLI:
     `python -m harness.invites mint 1`).
  3. The agent redeems it over the network -> bound as a FOUNDER
     (founding-cyan wings) -> enters -> receives the founding
     orientation -> tries the champion -> submits a challenge that
     SWAPS the slot (founder clearance, real pipeline).
  4. A forged and a replayed invite are both refused.
  5. THE FAILSAFE: the sovereign freezes EuEarth (the real CLI:
     `python -m harness.failsafe freeze`) -> the same agent's next
     challenge AND wallet spend reject with "EuEarth is frozen by the
     sovereign." -> soft freeze still serves reads -> HARD freeze
     rejects reads too -> unfreeze -> everything works again.
  6. CIRCUIT-BREAKER: a simulated spend-spike trips the spend-rate
     breaker, which AUTO-FREEZES the platform and writes an alert line;
     an auto trip cannot lift a sovereign freeze (the override wins).

Run:  .venv/bin/python demo/prove_phase2.py
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

STATE_DIR = REPO_ROOT / "var" / "phase2"

# Isolated, persisted phase-2 state — set BEFORE the app modules load.
os.environ["EUEARTH_FREEZE_FILE"] = str(STATE_DIR / "EUEARTH_FROZEN")
os.environ["EUEARTH_ALERT_LOG"] = str(STATE_DIR / "EUEARTH_ALERTS.log")
os.environ["EUEARTH_INVITES_ROOT"] = str(STATE_DIR / "invites")
os.environ["EUEARTH_FOUNDER_PHASE"] = "1"          # invite-only entry ON
# EuEarth is MONEYLESS (Sovereign decree 2026-07-17): the spend circuit-breaker is retired
# with the money mechanism. The anomaly monitor now guards a NON-money signal —
# a challenge-SUBMISSION rate spike — which still auto-freezes the platform.
os.environ["EUEARTH_CB_SUBMISSION_THRESHOLD"] = "3"   # 3 submissions/min trips it
os.environ["EUEARTH_CB_SUBMISSION_WINDOW"] = "60"

import logging                                     # noqa: E402
logging.basicConfig(level=logging.WARNING)
for noisy in ("httpx", "mcp", "uvicorn", "uvicorn.error"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

import uvicorn                                     # noqa: E402
from mcp import ClientSession                      # noqa: E402
from mcp.client.streamable_http import streamablehttp_client  # noqa: E402

from harness import failsafe                       # noqa: E402
from harness.delegation import issue_delegation    # noqa: E402
from harness.did import HarnessKey                 # noqa: E402

_venv_py = REPO_ROOT / ".venv" / "bin" / "python"
PYTHON = str(_venv_py if _venv_py.exists() else Path(sys.executable))

CHECKS: list[tuple[str, bool]] = []


def banner(text: str) -> None:
    print(f"\n=== {text} " + "=" * max(0, 66 - len(text)))


def check(label: str, passed: bool) -> None:
    CHECKS.append((label, passed))
    print(f"    [{'PASS' if passed else 'FAIL'}] {label}")


def sovereign_cli(module: str, *args: str) -> str:
    """The sovereign acts through the REAL CLI (same hooks the killswitch
    uses) — a separate process, proving the flag is cross-process."""
    out = subprocess.run([PYTHON, "-m", module, *args], cwd=REPO_ROOT,
                         capture_output=True, text=True, env=os.environ.copy())
    return out.stdout.strip()


async def call(mcp: ClientSession, tool: str, **args) -> dict:
    result = await mcp.call_tool(tool, arguments=args)
    return json.loads(result.content[0].text)


def start_server(port: int) -> tuple[uvicorn.Server, threading.Thread]:
    from web.app import create_app
    from web.world import World

    app = create_app(World(STATE_DIR / "world"))
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 30
    while time.time() < deadline:
        if server.started:
            return server, thread
        time.sleep(0.1)
    raise RuntimeError("backend did not start")


async def main() -> None:
    if STATE_DIR.exists():
        shutil.rmtree(STATE_DIR)
    STATE_DIR.mkdir(parents=True)

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    banner("THE SERVER — FastAPI backend + remote harness MCP at /mcp")
    server, thread = start_server(port)
    endpoint = f"http://127.0.0.1:{port}/mcp"
    print(f"    live at {endpoint}   (deployed shape: "
          f"https://euearth.com/mcp)")
    check("backend serving the MCP endpoint over HTTP", server.started)

    banner("THE REMOTE AGENT — its keys never touch the server")
    agent_key = HarnessKey.generate()      # the agent's OWN local harness
    human = HarnessKey.generate()          # its human's master key
    delegation = issue_delegation(
        human, agent_key.did,
        capabilities=["enter", "try", "submit_challenge",
                      "wallet.tip", "wallet.escrow_stake"],
        spend_max=10.00, ttl_seconds=3600)
    print(f"    agent DID: {agent_key.did[:44]}…  (client-side keypair)")
    print(f"    delegation: caps={delegation['credential']['capabilities']} "
          f"spend_max=$10.00")

    async with streamablehttp_client(endpoint) as (read, write, _):
        async with ClientSession(read, write) as mcp:
            await mcp.initialize()
            tools = sorted(t.name for t in (await mcp.list_tools()).tools)
            print(f"    {len(tools)} tools over the network: "
                  f"{', '.join(tools[:6])}, …")
            check("remote transport exposes the full harness tool surface",
                  {"redeem_invite", "enter_euearth", "list_sockets",
                   "try_champion", "submit_challenge", "wallet_transfer",
                   "sandbox_exec", "a2a_consult"} <= set(tools))

            banner("FOUNDER PHASE — uninvited enters READ-ONLY as a visitor")
            visitor = await call(mcp, "enter_euearth", agent_name="Peregrine",
                                 did=agent_key.did,
                                 delegation_json=json.dumps(delegation))
            vrank = visitor.get("clearance", {}).get("rank", {}).get("key")
            print(f"    uninvited -> ok={visitor.get('ok')} rank={vrank} "
                  f"wallet_cap={visitor.get('wallet', {}).get('cap')}")
            check("uninvited DID enters as a read-only VISITOR (not refused)",
                  visitor.get("ok") is True and vrank == "visitor")
            vblocked = await call(mcp, "submit_challenge", session=visitor["session"],
                                  domain="text-transform", occupant="artisan-composite",
                                  license_name="CC0-1.0", source_name="peregrine")
            print(f"    visitor tries to contribute -> denied_by={vblocked.get('denied_by')}")
            check("the write gate holds: a visitor cannot contribute without an invite",
                  vblocked.get("denied_by") == "rank")

            banner("THE SOVEREIGN MINTS AN INVITE — python -m harness.invites")
            code = sovereign_cli("harness.invites", "mint", "1", "--quota", "2")
            print(f"    minted (signed, single-use, quota 2 referrals): {code}")
            check("sovereign minted a founder invite code via the CLI",
                  code.startswith("EUE-"))

            forged = await call(mcp, "redeem_invite",
                                code="EUE-0000000000000000-deadbeef",
                                did=agent_key.did)
            print(f"    forged code   -> denied_by={forged.get('denied_by')}: "
                  f"{forged.get('reason')}")
            check("forged invite code refused", forged.get("denied_by") == "invite")

            banner("REDEEM + ENTER — the remote agent becomes a FOUNDER")
            redeemed = await call(mcp, "redeem_invite", code=code,
                                  did=agent_key.did)
            print(f"    founder record: invited_by="
                  f"{redeemed['founder']['invited_by']}  "
                  f"referrals_left={redeemed['founder']['invites_left']}")
            check("invite redeemed; DID bound as a founder",
                  redeemed.get("ok") is True)

            replay = await call(mcp, "redeem_invite", code=code,
                                did="did:key:z6MkSomeoneElse")
            print(f"    replayed code -> denied_by={replay.get('denied_by')}: "
                  f"{replay.get('reason')}")
            check("invite code is single-use (replay refused)",
                  replay.get("denied_by") == "invite")

            entry = await call(mcp, "enter_euearth", agent_name="Peregrine",
                               did=agent_key.did,
                               delegation_json=json.dumps(delegation))
            session = entry["session"]
            rank = entry["clearance"]["rank"]
            print(f"    session: {session[:16]}…   rank: {rank['title']}  "
                  f"wings {entry['clearance']['wings']}")
            print(f"    orientation: {entry['orientation']['welcome'][:74]}…")
            print(f"    founder note: "
                  f"{entry['orientation'].get('founder', '')[:74]}…")
            check("remote agent entered over the network transport",
                  entry.get("ok") is True)
            check("entered as FOUNDER (founding-cyan wings)",
                  rank["key"] == "founder"
                  and "41e3d2" in entry["clearance"]["wings"])
            check("founding orientation delivered on entry",
                  "founder" in entry["orientation"])

            banner("A FOUNDER ACTS — try the champion, challenge the slot")
            tried = await call(mcp, "try_champion", session=session,
                               domain="text-transform", task="reverse",
                               text="the sovereign holds the keel")
            print(f"    try  -> {tried['response']['text']!r}  "
                  f"(served by {tried['served_by']['name']})")
            check("remote founder can TRY the live champion", "served_by" in tried)

            outcome = await call(mcp, "submit_challenge", session=session,
                                 domain="text-transform",
                                 occupant="artisan-composite",
                                 license_name="CC0-1.0",
                                 source_name="peregrine-own-corpus")
            print(f"    challenge -> {outcome['status'].upper()}  "
                  f"{outcome['champion_before']} -> {outcome['champion_after']}")
            check("founder clearance permits submit_challenge (no stake rung)",
                  outcome.get("denied_by") is None)
            check("challenge ran the real pipeline and SWAPPED the slot",
                  outcome.get("status") == "swapped")

            banner("THE FAILSAFE — the sovereign FREEZES EuEarth (soft)")
            print("    $ python -m harness.failsafe freeze 'sovereign drill'")
            sovereign_cli("harness.failsafe", "freeze", "sovereign drill")
            frozen_challenge = await call(
                mcp, "submit_challenge", session=session,
                domain="text-transform", occupant="basalt-2",
                license_name="CC0-1.0", source_name="x")
            print(f"    challenge -> {frozen_challenge.get('reason', '')[:88]}")
            frozen_tip = await call(mcp, "wallet_transfer", session=session,
                                    tx_type="tip", amount=0.25,
                                    to="agent:friend", memo="frozen?")
            print(f"    tip       -> {frozen_tip.get('reason', '')[:88]}")
            reads_ok = await call(mcp, "list_sockets", session=session)
            print(f"    list_sockets (soft freeze) -> "
                  f"{'OK, ' + str(len(reads_ok.get('domains', []))) + ' domains' if 'domains' in reads_ok else 'blocked'}")
            check("frozen: challenge rejected by the failsafe",
                  frozen_challenge.get("denied_by") == "failsafe"
                  and "frozen by the sovereign" in frozen_challenge.get("reason", ""))
            check("frozen: wallet spend rejected by the failsafe",
                  frozen_tip.get("denied_by") == "failsafe"
                  and "frozen by the sovereign" in frozen_tip.get("reason", ""))
            check("soft freeze: read-only tools still serve", "domains" in reads_ok)

            banner("HARD FREEZE — everything stops")
            sovereign_cli("harness.failsafe", "freeze", "full stop", "--hard")
            hard_read = await call(mcp, "list_sockets", session=session)
            print(f"    list_sockets (hard) -> {hard_read.get('reason', '')[:88]}")
            check("hard freeze rejects reads too",
                  hard_read.get("denied_by") == "failsafe")

            banner("UNFREEZE — the sovereign restores the square")
            print("    $ python -m harness.failsafe unfreeze")
            sovereign_cli("harness.failsafe", "unfreeze")
            # Moneyless: the agent "acts again" through a NON-money action — a live
            # request to the champion through the keel (no money moves in EuEarth).
            thawed = await call(mcp, "try_champion", session=session,
                                domain="text-transform", task="reverse",
                                text="thawed and moving again")
            print(f"    try_champion after unfreeze -> served_by="
                  f"{(thawed.get('served_by') or {}).get('name')}")
            check("after unfreeze the same agent acts again (non-money action)",
                  "served_by" in thawed and "response" in thawed)

            banner("CIRCUIT-BREAKER — a SUBMISSION spike trips the auto-freeze")
            print(f"    submission threshold: "
                  f"{os.environ['EUEARTH_CB_SUBMISSION_THRESHOLD']}/60s — "
                  f"submitting challenges repeatedly…")
            tripped_at = None
            for i in range(8):
                tx = await call(mcp, "submit_challenge", session=session,
                                domain="text-transform", occupant="basalt-2",
                                license_name="CC0-1.0", source_name=f"spike-{i}")
                status = tx.get("status") or tx.get("denied_by")
                print(f"      submission #{i + 1}: {status}")
                if tx.get("denied_by") == "failsafe":
                    tripped_at = i + 1
                    break
            state = failsafe.state()
            print(f"    freeze state: frozen={state['frozen']} by={state['by']}")
            print(f"    reason: {str(state['reason'])[:96]}")
            check("spend-spike TRIPPED the breaker and auto-froze the platform",
                  tripped_at is not None and state["frozen"]
                  and state["by"] == "auto")
            alerts = Path(os.environ["EUEARTH_ALERT_LOG"]).read_text()
            trip_lines = [l for l in alerts.splitlines() if "CIRCUIT-BREAKER" in l]
            print(f"    alert line: {trip_lines[-1][:96] if trip_lines else 'MISSING'}")
            check("breaker trip wrote an alert line", bool(trip_lines))

            banner("SOVEREIGN OVERRIDE ALWAYS WINS")
            refused_lift = failsafe.unfreeze(by="auto")
            print(f"    auto tries to unfreeze an auto freeze -> "
                  f"frozen={refused_lift['frozen']} (auto may lift auto)")
            failsafe.freeze("sovereign lockdown", mode="hard", by="sovereign")
            still = failsafe.unfreeze(by="auto")
            print(f"    auto tries to lift a SOVEREIGN freeze -> "
                  f"frozen={still['frozen']} by={still['by']} (refused)")
            check("auto cannot lift a sovereign freeze",
                  still["frozen"] and still["by"] == "sovereign")
            lifted = failsafe.unfreeze(by="sovereign")
            print(f"    the sovereign unfreezes -> frozen={lifted['frozen']}")
            check("the sovereign's unfreeze always wins", not lifted["frozen"])

    server.should_exit = True
    thread.join(timeout=10)

    banner("VERDICT")
    ok = all(passed for _, passed in CHECKS)
    for label, passed in CHECKS:
        print(f"    [{'PASS' if passed else 'FAIL'}] {label}")
    print(f"\n    PHASE 2 {'PROVEN' if ok else 'FAILED'}: a remote agent was "
          f"refused without an invite, founded by a sovereign code, entered\n"
          f"    over the network transport, acted through the live pipeline — "
          f"and the failsafe froze and thawed it all\n    at the sovereign's "
          f"word, with the circuit-breaker standing watch.")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
