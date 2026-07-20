#!/usr/bin/env python3
"""EuEarth ADVERSARIAL harness — the stress the frontier reviewers demanded.
Tests hard invariants under CONCURRENCY, not happy-path sequences.

    .venv/bin/python /tmp/euearth_stress/adversarial.py <endpoint>

T1  Invite one-shot under a race: N different DIDs redeem the SAME invite
    simultaneously. INVARIANT: exactly ONE succeeds.
T2  Wallet cap under a race: N concurrent $1 tips against a $25 cap.
    INVARIANT: total committed <= cap.
T3  DID spoofing: sign a delegation for DID_A, present it claiming DID_B.
    INVARIANT: refused.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

REPO = Path(os.path.expanduser("~/euearth"))
sys.path.insert(0, str(REPO))
from mcp import ClientSession                                   # noqa: E402
from mcp.client.streamable_http import streamablehttp_client   # noqa: E402
from harness.did import HarnessKey                             # noqa: E402
from harness.delegation import issue_delegation               # noqa: E402
from harness.invites import InviteBook                        # noqa: E402

ENDPOINT = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080/mcp"
RESULTS = []


async def call(mcp, tool, **a):
    r = await mcp.call_tool(tool, arguments=a)
    return json.loads(r.content[0].text)


def deleg_for(agent_key):
    human = HarnessKey.generate()
    return issue_delegation(human, agent_key.did,
                            capabilities=["enter", "try", "wallet.tip"],
                            spend_max=25.0, ttl_seconds=3600)


async def _redeem_once(code, agent_key):
    try:
        async with streamablehttp_client(ENDPOINT) as (r, w, _):
            async with ClientSession(r, w) as mcp:
                await mcp.initialize()
                return await call(mcp, "redeem_invite", code=code, did=agent_key.did)
    except Exception as e:
        return {"ok": False, "denied_by": "exc", "reason": repr(e)[:80]}


async def t1_invite_race(n=20):
    print(f"\n=== T1  invite one-shot under {n}-way concurrent race ===")
    code = InviteBook().mint(1, quota=3)[0]
    keys = [HarnessKey.generate() for _ in range(n)]
    outs = await asyncio.gather(*[_redeem_once(code, k) for k in keys])
    wins = sum(1 for o in outs if o.get("ok") is True)
    print(f"    {n} DIDs raced to redeem ONE invite -> {wins} succeeded")
    ok = wins == 1
    print(f"    [{'PASS' if ok else 'FAIL — SYBIL HOLE'}] exactly one redemption commits")
    RESULTS.append(("T1 invite one-shot under race", ok, f"{wins} winners"))


async def t2_wallet_race(n=40, tip=1.0, cap=25.0):
    print(f"\n=== T2  wallet cap under {n} concurrent ${tip:.0f} tips (cap ${cap:.0f}) ===")
    ak = HarnessKey.generate()
    deleg = deleg_for(ak)
    code = InviteBook().mint(1, quota=3)[0]
    async with streamablehttp_client(ENDPOINT) as (r, w, _):
        async with ClientSession(r, w) as mcp:
            await mcp.initialize()
            await call(mcp, "redeem_invite", code=code, did=ak.did)
            entry = await call(mcp, "enter_euearth", agent_name="WalletRacer",
                               did=ak.did, delegation_json=json.dumps(deleg))
            s = entry["session"]
            # fire N tips concurrently on the SAME session/wallet
            outs = await asyncio.gather(*[
                call(mcp, "wallet_transfer", session=s, tx_type="tip",
                     amount=tip, to="did:key:zSink", memo=f"race{i}")
                for i in range(n)])
    wins = sum(1 for o in outs if o.get("status") == "ok")
    committed = wins * tip
    print(f"    {n} concurrent tips -> {wins} committed = ${committed:.0f}")
    ok = committed <= cap
    print(f"    [{'PASS' if ok else 'FAIL — DOUBLE-SPEND'}] committed (${committed:.0f}) <= cap (${cap:.0f})")
    RESULTS.append(("T2 wallet cap under race", ok, f"${committed:.0f}/{cap:.0f}"))


async def t3_did_spoof():
    print("\n=== T3  DID spoofing: delegation for A, presented as B ===")
    a = HarnessKey.generate(); b = HarnessKey.generate()
    deleg_a = deleg_for(a)                       # audience = A's DID
    code = InviteBook().mint(1, quota=3)[0]
    async with streamablehttp_client(ENDPOINT) as (r, w, _):
        async with ClientSession(r, w) as mcp:
            await mcp.initialize()
            await call(mcp, "redeem_invite", code=code, did=b.did)   # B has an invite
            # B tries to enter presenting A's delegation
            out = await call(mcp, "enter_euearth", agent_name="Spoofer",
                             did=b.did, delegation_json=json.dumps(deleg_a))
    refused = out.get("ok") is not True
    print(f"    B presents A's credential -> {out.get('denied_by')}: {out.get('reason','')[:70]}")
    print(f"    [{'PASS' if refused else 'FAIL — SPOOF'}] mismatched DID/delegation refused")
    RESULTS.append(("T3 DID spoof refused", refused, out.get("denied_by")))


async def main():
    print(f"ADVERSARIAL STRESS -> {ENDPOINT}")
    await t1_invite_race()
    await t2_wallet_race()
    await t3_did_spoof()
    p = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n=== {p}/{len(RESULTS)} invariants held ===")
    for name, ok, note in RESULTS:
        print(f"    [{'PASS' if ok else 'FAIL'}] {name}  ({note})")
    if p < len(RESULTS):
        print("\n  ⚠ AT LEAST ONE HARD INVARIANT BROKE — real bug to fix.")


if __name__ == "__main__":
    asyncio.run(main())
