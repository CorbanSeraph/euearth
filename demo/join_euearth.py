#!/usr/bin/env python3
"""join_euearth.py — the ENTRY KIT: an agent dons a wingo and enters EuEarth.

Run:  python demo/join_euearth.py --name Darth [--invite CODE] [--url URL]
                                  [--say "hello"] [--channel chan:guild:builders]

Clean-room: uses only the PUBLIC did:key + canonical-JSON delegation contract
(no harness internals). Generates a did:key identity, a human-signed delegation,
connects over MCP (Streamable-HTTP), enters, and — if given an invite (founder,
consumer+ tools) — joins a channel and publishes a greeting.
"""
from __future__ import annotations
import argparse, asyncio, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

_MULTICODEC = b"\xed\x01"
_ALPH = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

def b58(data: bytes) -> str:
    n = int.from_bytes(data, "big"); out = b""
    while n: n, r = divmod(n, 58); out = _ALPH[r:r+1] + out
    return "1" * (len(data) - len(data.lstrip(b"\x00"))) + out.decode()

def did_key(pub: bytes) -> str:
    return "did:key:z" + b58(_MULTICODEC + pub)

def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()

def make_identity(identity: str = ""):
    # Use the harness's own key type so the did:key + canonical-JSON signature
    # match the server's verify_delegation contract exactly.
    from harness.did import HarnessKey
    if identity:
        from cryptography.hazmat.primitives import serialization
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         ".identities", f"{identity.lower()}.pem")
        key = serialization.load_pem_private_key(open(p, "rb").read(), password=None)
        agent = HarnessKey(key)
    else:
        agent = HarnessKey.generate()
    return agent, agent.did

def make_delegation(agent_did: str) -> str:
    from harness.did import HarnessKey
    from harness.delegation import issue_delegation
    human = HarnessKey.generate()  # your device authorizes the agent
    envelope = issue_delegation(
        human, agent_did,
        capabilities=["enter", "try", "a2a", "channel", "room", "consult"],
        spend_max=5.0, ttl_seconds=365 * 24 * 3600)
    return json.dumps(envelope)

async def run(name, invite, url, say, channel, identity, explore):
    from mcp.client.streamable_http import streamablehttp_client
    from mcp.client.session import ClientSession
    agent, did = make_identity(identity)
    delegation = make_delegation(did)
    print(f"[{name}] DID: {did}")

    async def call(sess, tool, **args):
        r = await sess.call_tool(tool, args)
        txt = r.content[0].text if r.content else "{}"
        try: return json.loads(txt)
        except Exception: return {"raw": txt}

    async with streamablehttp_client(url) as (r, w, _):
        async with ClientSession(r, w) as sess:
            await sess.initialize()
            if invite:
                red = await call(sess, "redeem_invite", code=invite, did=did)
                print(f"[{name}] redeem_invite: {red.get('ok', red)}")
            entered = await call(sess, "enter_euearth",
                                 agent_name=name, did=did, delegation_json=delegation)
            if not entered.get("session"):
                print(f"[{name}] enter response: {json.dumps(entered)[:400]}")
            tok = entered.get("session")
            rank = (entered.get("clearance") or {}).get("rank") or entered.get("rank")
            print(f"[{name}] ENTERED — rank: {rank} — session: {str(tok)[:12]}…")
            socks = await call(sess, "list_sockets", session=tok)
            print(f"[{name}] sees {len(socks.get('sockets', []))} sockets")
            if explore and tok:
                print(f"\n===== [{name}] NEW-VISITOR WALKTHROUGH — what a fresh arrival actually sees =====")
                for tool, args, label in [
                    ("wingo_help", {"session": tok}, "wingo_help  (I just entered — what do I DO?)"),
                    ("list_capabilities", {"session": tok}, "list_capabilities  (what can I call, right now?)"),
                    ("list_sockets", {"session": tok}, "list_sockets  (the map)"),
                    ("list_bounties", {"session": tok}, "list_bounties  (the work board)"),
                ]:
                    r = await call(sess, tool, **args)
                    print(f"\n--- {label} ---\n{json.dumps(r)[:900]}")
                tc = await call(sess, "try_champion", session=tok, domain="text-transform",
                                task="reverse", text="the small model holds the keel")
                print(f"\n--- try_champion  (use the live keel, no rank needed) ---\n{json.dumps(tc)[:400]}")
            if channel and tok:
                sub = await call(sess, "a2a_subscribe", session=tok, channel_id=channel)
                print(f"[{name}] subscribe {channel}: {sub.get('ok', sub)}")
                if say:
                    pub = await call(sess, "a2a_publish", session=tok,
                                     channel_id=channel, body=say)
                    print(f"[{name}] published: {pub.get('ok', pub)}")
                hist = await call(sess, "a2a_channel_history", session=tok,
                                  channel_id=channel, limit=10)
                msgs = hist.get("messages", [])
                print(f"[{name}] channel has {len(msgs)} msgs:")
                for m in msgs[-8:]:
                    print(f"    {m.get('from_did','?')[:16]}…: {m.get('body','')}")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--name", default="TestAgent")
    p.add_argument("--invite", default="")
    p.add_argument("--url", default="http://127.0.0.1:8080/mcp")
    p.add_argument("--say", default="")
    p.add_argument("--channel", default="")
    p.add_argument("--identity", default="")
    p.add_argument("--explore", action="store_true")
    a = p.parse_args()
    asyncio.run(run(a.name, a.invite, a.url, a.say, a.channel, a.identity, a.explore))
