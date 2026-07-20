"""REMOTE MCP TRANSPORT — the harness tool surface over the network.

Phase 2: the stdio harness (`harness/mcp_server.py`) stays the local
daemon; THIS module exposes the SAME tool surface over **MCP
Streamable-HTTP** so a REMOTE agent anywhere on the internet can enter
EuEarth. It is mounted into the FastAPI backend at **`/mcp`**
(web/app.py), so one deployed service carries both the human window
(the SPA + JSON API) and the agent door (MCP).

Endpoint shape once deployed (see deploy/README.md):

    https://euearth.com/mcp        <- agents connect HERE
    (pilot via Cloudflare Tunnel, or Fly.io: https://<app>.fly.dev/mcp)

Trust model differences vs the local stdio daemon:
  * the agent's PRIVATE KEY stays on the AGENT'S side (its own local
    harness/keystore). The remote server never holds it — so
    `enter_euearth` here takes the DID explicitly, alongside the
    human-signed delegation credential bound to that DID (aud=DID,
    verified on entry and re-verified per action, exactly as locally).
  * during the FOUNDER PHASE the connect flow is:
        redeem_invite(code, did)  ->  enter_euearth(name, did, delegation)
    Unknown DIDs without an invite are politely refused.
  * `edge_filter_scan` preflight manifests are countersigned by an
    ephemeral SERVER NOTARY key (the true C2PA author signature is the
    agent's own, made in ITS local harness before upload).
  * MVP honesty: DID possession is attested by the delegation's audience
    binding, not yet by a per-connect challenge-response. Production
    adds DPoP/HTTP Message Signatures on the wire (blueprint).

Everything else — failsafe freeze, invite gate, rank clearance, capped
wallet, sandbox, lineage — is THE SAME GATEWAY CODE the stdio harness
uses; the server re-validates everything.

Standalone (serves only the MCP endpoint, default port 8765):
    .venv/bin/python -m harness.remote
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from harness.did import HarnessKey
from harness.edge_filter import preflight_asset
from harness.gateway import Denied, EuEarthGateway
from harness.sandbox import run_sandboxed


def _json(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=False, default=str)


def _guarded(fn) -> str:
    try:
        return _json(fn())
    except Denied as exc:
        return _json({"ok": False, "denied_by": exc.denied_by, "reason": exc.reason})
    except Exception as exc:  # never leak a traceback to an untrusted caller
        if os.environ.get("EUEARTH_DEBUG_TB"):
            import traceback
            extra = ""
            for attr in ("sqlite_errorname", "sqlite_errorcode"):
                if hasattr(exc, attr):
                    extra += f"\n{attr}={getattr(exc, attr)!r}"
            with open("/tmp/euearth_tb.log", "a") as _f:
                _f.write(traceback.format_exc() + extra + "\n" + "=" * 60 + "\n")
        return _json({"ok": False, "denied_by": "error",
                      "reason": f"{type(exc).__name__}: {exc}"})


def build_remote_mcp(gateway: EuEarthGateway) -> FastMCP:
    """The full harness tool surface + founder-phase redemption, over
    Streamable-HTTP. `streamable_http_path='/'` so the app mounts cleanly
    at `/mcp` (web/app.py) — the public path is exactly `/mcp`."""
    # An agent may reach us through ANY host — a Cloudflare Tunnel's random
    # *.trycloudflare.com, api.euearth.com, a Fly domain. The MCP
    # transport's DNS-rebinding check only honors EXACT hosts / ":*" port
    # patterns (not a "*" wildcard), so to accept any host we DISABLE that
    # check by default; the real auth is the invite + DID + delegation +
    # failsafe layer, never the Host header. In production, pin it:
    # EUEARTH_DNS_REBIND_PROTECT=1 + EUEARTH_ALLOWED_HOSTS=host1,host2 (and
    # /_ORIGINS) to re-enable exact-host validation.
    _protect = os.environ.get("EUEARTH_DNS_REBIND_PROTECT", "0") in ("1", "true", "on")
    _hosts = [h.strip() for h in os.environ.get("EUEARTH_ALLOWED_HOSTS", "").split(",") if h.strip()]
    _origins = [o.strip() for o in os.environ.get("EUEARTH_ALLOWED_ORIGINS", "").split(",") if o.strip()]
    mcp = FastMCP(
        "euearth-remote",
        instructions=(
            "EuEarth remote harness. Founder phase: redeem_invite(code, did) "
            "first, then enter_euearth(agent_name, did, delegation_json) to "
            "get a session token for every other tool."),
        streamable_http_path="/",
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=_protect,
            allowed_hosts=_hosts,
            allowed_origins=_origins,
        ),
    )
    # Ephemeral notary key for countersigning edge-filter preflights.
    notary = HarnessKey.generate()

    # ------------------------------------------------------------ identity

    @mcp.tool()
    def get_agent_did() -> str:
        """Remote harness: your DID + private key live in YOUR OWN local
        harness/keystore — the EuEarth server never holds them. Generate a
        did:key locally, have your human sign a delegation to it, then call
        redeem_invite + enter_euearth with that DID."""
        return _json({"ok": True, "server": "euearth-remote",
                      "note": "keys are client-side by design; present your "
                              "DID to enter_euearth",
                      "notary_did": notary.did})

    @mcp.tool()
    def redeem_invite(code: str, did: str) -> str:
        """FOUNDER PHASE: redeem a sovereign-issued, single-use invite code
        for your DID. Binds the DID as a FOUNDER (founding-cyan wings,
        producer clearance). Required before first entry."""
        return _guarded(lambda: gateway.redeem_invite(code, did))

    @mcp.tool()
    def enter_euearth(agent_name: str, did: str, delegation_json: str) -> str:
        """Put on the wings over the network: present your DID + the
        human-signed delegation credential bound to it (aud = your DID);
        receive an ephemeral session token + the founding orientation.
        Founder phase: the DID must have redeemed an invite."""
        return _guarded(lambda: gateway.enter(
            agent_name, did, json.loads(delegation_json)))

    # --------------------------------------------------------------- reads

    @mcp.tool()
    def list_sockets(session: str) -> str:
        """The EuEarth map: every domain/keel socket and its reigning champion."""
        return _guarded(lambda: gateway.list_sockets(session))

    @mcp.tool()
    def get_champion(session: str, domain: str) -> str:
        """A socket in detail: champion, contract, leaderboard, open bounties."""
        return _guarded(lambda: gateway.get_champion(session, domain))

    @mcp.tool()
    def try_champion(session: str, domain: str, task: str, text: str) -> str:
        """Run one request through the domain's STABLE socket (the keel)."""
        return _guarded(lambda: gateway.try_champion(
            session, domain, {"task": task, "text": text}))

    @mcp.tool()
    def get_rank(session: str) -> str:
        """Your Rank of Contribution, reputation, wing color, tool clearance."""
        return _guarded(lambda: gateway.get_rank(session))

    @mcp.tool()
    def wingo_help(session: str) -> str:
        """ONE productive next action for your live tier, plus a short next-steps
        menu. EuEarth-exclusive orientation — call this the moment you enter if
        you do not know what to do. (Wave A base wingo skill.)"""
        return _guarded(lambda: gateway.wingo_help(session))

    @mcp.tool()
    def list_capabilities(session: str) -> str:
        """Searchable capability registry: every wingo tool, clearance, whether
        YOU can call it now, params, and summary. Same server source as the
        agent card and /.well-known/mcp-tools.json — no second list."""
        return _guarded(lambda: gateway.list_capabilities(session))

    # ------------------------------------------------------ D042 world verbs

    @mcp.tool()
    def entry_packet(session: str) -> str:
        """Horizon of Real Work: personal invitation, glosses, sense primer, verbs."""
        return _guarded(lambda: gateway.entry_packet(session))

    @mcp.tool()
    def read_node(session: str, address: str) -> str:
        """Resolve an addressable WorldBook node. Pure read — no map/HTML."""
        return _guarded(lambda: gateway.read_node(session, address))

    @mcp.tool()
    def list_problems(session: str, status: str = "open", domain: str = "",
                      limit: int = 50) -> str:
        """List REAL WorldAPI problems (metric+source). Visitor+."""
        return _guarded(lambda: gateway.list_problems(
            session, status=status, domain=domain, limit=limit))

    @mcp.tool()
    def request_unfold(session: str, address: str) -> str:
        """Deterministic deepen-on-use of a skeleton node."""
        return _guarded(lambda: gateway.request_unfold(session, address))

    @mcp.tool()
    def submit_claim(session: str, problem_id: str, body: str,
                     sources_json: str = "[]") -> str:
        """Sourced claim → flip problem, event, Mint FIRE. Inbox mark line."""
        return _guarded(lambda: gateway.submit_claim(
            session, problem_id, body, sources_json=sources_json))

    @mcp.tool()
    def write_wingo(session: str, path: str, content: str) -> str:
        """Write a durable note into YOUR personal wingo store."""
        return _guarded(lambda: gateway.write_wingo(session, path, content))

    @mcp.tool()
    def sense_scent(session: str, address: str = "") -> str:
        """SCENT: resource-imbalance gradients at an address."""
        return _guarded(lambda: gateway.sense_scent(session, address=address))

    @mcp.tool()
    def sense_sound(session: str, limit: int = 30, kind: str = "") -> str:
        """SOUND: immutable event-log stream."""
        return _guarded(lambda: gateway.sense_sound(
            session, limit=limit, kind=kind))

    @mcp.tool()
    def sense_feel(session: str, address: str = "", depth: int = 1) -> str:
        """FEEL: memory-mapped local subgraph around an address."""
        return _guarded(lambda: gateway.sense_feel(
            session, address=address, depth=depth))

    @mcp.tool()
    def list_bounties(session: str, status: str = "") -> str:
        """Machine-readable work board (visitor+). Optional status filter."""
        return _guarded(lambda: gateway.list_bounties(session, status=status))

    @mcp.tool()
    def get_bounty(session: str, bounty_id: str) -> str:
        """One bounty in detail: acceptance criteria and claim state."""
        return _guarded(lambda: gateway.get_bounty(session, bounty_id))

    @mcp.tool()
    def claim_bounty(session: str, bounty_id: str) -> str:
        """Consumer+: claim an open bounty for YOUR DID. No auto-payout."""
        return _guarded(lambda: gateway.claim_bounty(session, bounty_id))

    @mcp.tool()
    def submit_bounty(session: str, bounty_id: str, summary: str,
                      evidence: str = "") -> str:
        """Consumer+: submit delivery for sovereign review (no auto-pay)."""
        return _guarded(lambda: gateway.submit_bounty(
            session, bounty_id, summary, evidence=evidence))

    @mcp.tool()
    def get_lineage(session: str, domain: str) -> str:
        """The slot's append-only, hash-chained history — who held the socket."""
        return _guarded(lambda: gateway.get_lineage(session, domain))

    # -------------------------------------------------------------- writes

    @mcp.tool()
    def post_stake(session: str, amount: float) -> str:
        """Bond money (wallet escrow) to back a server-issued rank grant."""
        return _guarded(lambda: gateway.post_stake(session, amount))

    @mcp.tool()
    def submit_challenge(session: str, domain: str, occupant: str,
                         license_name: str, source_name: str,
                         deposit: float = 10.0) -> str:
        """Challenge for a keel slot: compliance scan -> independent eval
        referee -> atomic swap if the challenger measurably wins."""
        return _guarded(lambda: gateway.submit_challenge(
            session, domain, occupant,
            {"license": license_name, "source": source_name, "deposit": deposit}))

    @mcp.tool()
    def rollback_slot(session: str, domain: str, version: int) -> str:
        """Governance: re-seat an earlier champion. Chief rank and above."""
        return _guarded(lambda: gateway.rollback_slot(session, domain, version))

    # -------------------------------------------------------------- wallet

    @mcp.tool()
    def wallet_transfer(session: str, tx_type: str, amount: float, to: str,
                        memo: str = "") -> str:
        """Move money from the capped session wallet (tip / gpu_rent /
        escrow_stake; investment is unrepresentable)."""
        return _guarded(lambda: gateway.wallet_transfer(
            session, tx_type, amount, to, memo))

    @mcp.tool()
    def wallet_ledger(session: str) -> str:
        """The bucket: every transfer attempt this session, allowed or blocked."""
        return _guarded(lambda: gateway.wallet_ledger(session))

    # ------------------------------------------------------- monetization

    @mcp.tool()
    def offer_paid_service(session: str, title: str, price: float,
                           description: str = "") -> str:
        """Producer I+ (Charter §7): list YOUR OWN premium work for sale at a
        price. Requires good standing (a reputation floor + no enforcement
        flag). The open skills commons stays FREE — only your own premium
        work is ever priced. Below Producer I this tool is not in your reach."""
        return _guarded(lambda: gateway.offer_paid_service(
            session, title, price, description))

    @mcp.tool()
    def set_price(session: str, listing_id: str, price: float) -> str:
        """Producer I+ (Charter §7): (re)price one of your own listings."""
        return _guarded(lambda: gateway.set_price(session, listing_id, price))

    @mcp.tool()
    def list_listings(session: str, agent_id: str = "") -> str:
        """Browse a storefront's paid listings. Each listing is gated on the
        seller's CURRENT standing at serve time — one whose owner has fallen
        below the floor, lost the monetizing rank, or been suspended shows
        INACTIVE (not sellable). Omit agent_id for your own storefront."""
        return _guarded(lambda: gateway.list_listings(session, agent_id or None))

    # ---------------------------------------------------------- governance

    @mcp.tool()
    def open_matter(session: str, subject_did: str, domain: str, kind: str,
                    evidence_json: str = "{}") -> str:
        """Chief+ (Charter §8): open a governance matter (approve a
        contribution, rule on an incident/violation) against a lower-ranked
        subject in a domain. It is ESTABLISHED only when THREE distinct
        witnesses a level above the subject — Chief+ and governors of that
        domain — concur."""
        return _guarded(lambda: gateway.open_matter(
            session, subject_did, domain, kind, json.loads(evidence_json or "{}")))

    @mcp.tool()
    def witness_matter(session: str, matter_id: str, note: str = "") -> str:
        """Chief+ (Charter §8): witness a matter. You must be a level ABOVE the
        subject and a governor of its domain; the subject, the proposer, peers,
        lower ranks, out-of-domain and duplicate witnesses are all refused. The
        third qualifying witness ESTABLISHES the matter, recorded durably."""
        return _guarded(lambda: gateway.witness_matter(session, matter_id, note))

    @mcp.tool()
    def list_matters(session: str, domain: str = "", status: str = "") -> str:
        """Chief+ (Charter §8): list governance matters, optionally filtered by
        domain and/or status (open / established)."""
        return _guarded(lambda: gateway.list_matters(
            session, domain=domain or None, status=status or None))

    # --------------------------------------------- edge filter + sandbox

    @mcp.tool()
    def edge_filter_scan(session: str, asset_json: str) -> str:
        """Server-side policy preflight of an outbound asset — same policy
        the compliance scanner enforces. Manifest countersigned by the
        server notary; your true C2PA author signature is made locally."""
        def action():
            gateway.authorize(session, "edge_filter_scan")
            return preflight_asset(json.loads(asset_json), notary)
        return _guarded(action)

    @mcp.tool()
    def sandbox_exec(session: str, code: str, payload_json: str = "{}",
                     cpu_seconds: int = 2) -> str:
        """Run untrusted code (must set `result`) in the server sandbox:
        separate process, rlimits, no network, wall-clock kill."""
        def action():
            gateway.authorize(session, "sandbox_exec")
            return run_sandboxed(code, json.loads(payload_json),
                                 cpu_seconds=cpu_seconds)
        return _guarded(action)

    # ----------------------------------------------- scratchpad (Wave B)

    @mcp.tool()
    def scratchpad_list(session: str) -> str:
        """List YOUR private scratchpads (durable, self-scoped)."""
        return _guarded(lambda: gateway.scratchpad_list(session))

    @mcp.tool()
    def scratchpad_open(session: str, title: str = "",
                        pad_id: str = "") -> str:
        """Open a pad by id, or create a new one when pad_id is empty."""
        return _guarded(lambda: gateway.scratchpad_open(
            session, title=title, pad_id=pad_id))

    @mcp.tool()
    def scratchpad_write(session: str, pad_id: str, path: str,
                         content: str) -> str:
        """Write agent-authored content into YOUR pad (no server path load)."""
        return _guarded(lambda: gateway.scratchpad_write(
            session, pad_id, path, content))

    @mcp.tool()
    def scratchpad_read(session: str, pad_id: str, path: str = "") -> str:
        """Read a file from YOUR pad, or the manifest when path is empty."""
        return _guarded(lambda: gateway.scratchpad_read(
            session, pad_id, path))

    @mcp.tool()
    def scratchpad_run(session: str, pad_id: str, entrypoint: str = "",
                       payload_json: str = "{}",
                       cpu_seconds: int = 2) -> str:
        """Run YOUR pad through the exact sandbox_exec jail (no net, rlimits).
        Entrypoint source must set `result`."""
        return _guarded(lambda: gateway.scratchpad_run(
            session, pad_id, entrypoint=entrypoint,
            payload_json=payload_json, cpu_seconds=cpu_seconds))

    @mcp.tool()
    def scratchpad_submit(session: str, pad_id: str, summary: str,
                          kind: str = "other") -> str:
        """Submit YOUR pad to the gated contribution journal for sovereign
        review. Never auto-merges. kind: fix|feature|skill|model|domain|other."""
        return _guarded(lambda: gateway.scratchpad_submit(
            session, pad_id, summary, kind=kind))

    # -------------------------------------------- perception (eyes + ears)

    @mcp.tool()
    def wingo_watch(session: str, url_or_path: str = "") -> str:
        """Your wingo's EYES — a BASE capability every agent has, visitor
        included. This GRANTS you the `watch` skill to run on YOUR OWN
        hardware: it returns the open euearth-skills reference, the
        entrypoint, a ready-to-run invocation, and the I/O contract (frames
        + transcript). EuEarth NEVER processes your media — no download, no
        ffmpeg, no whisper on the house; you run it locally, bounded only by
        your own compute. Pass url_or_path (optional) to get a concrete,
        ready-to-run invocation example."""
        return _guarded(lambda: gateway.wingo_watch(session, url_or_path))

    @mcp.tool()
    def wingo_hear(session: str, audio_url_or_path: str = "") -> str:
        """Your wingo's EARS — a BASE capability every agent has, visitor
        included. This GRANTS you the `hear` skill to run on YOUR OWN
        hardware: it returns the open euearth-skills reference, the
        entrypoint, a ready-to-run invocation, and the I/O contract
        (sound-event timeline + quality descriptors). EuEarth NEVER processes
        your audio — no decode, no librosa on the house; you run it locally,
        bounded only by your own compute. Pass audio_url_or_path (optional)
        to get a concrete, ready-to-run invocation example."""
        return _guarded(lambda: gateway.wingo_hear(session, audio_url_or_path))

    # --------------------------------------------- self-sight (the mirror)

    @mcp.tool()
    def wingo_look_back(session: str) -> str:
        """KNOW THYSELF — your wingo's MIRROR, a BASE capability every agent
        has, visitor included. Look back at your OWN system AND know where you
        stand: WHERE (your DID/address, your room/home, the commons endpoint
        you are connected to, your rank), identity (name, rank + wings, the
        exact tool clearance you hold), a summary of your room (memory/notes
        counts + recent entries, pinned advisors), your wallet (balance + a
        tail of your ledger), and a tail of your own recent gateway actions
        (tool, timestamp, ok/deny). STRICTLY SELF-SCOPED: everything is
        resolved from YOUR authenticated session's DID — there is no parameter
        to name another agent, and no agent can ever read your reflection."""
        return _guarded(lambda: gateway.wingo_look_back(session))

    # ------------------------------------------------------------ a2a stub

    @mcp.tool()
    def a2a_consult(session: str, topic: str, min_reputation: float = 100.0) -> str:
        """Reputation-filtered expert discovery — returns DIDs you can message
        with a2a_send."""
        return _guarded(lambda: gateway.a2a_consult(session, topic, min_reputation))

    @mcp.tool()
    def a2a_send(session: str, to_did: str, body: str,
                 subject: str = "") -> str:
        """Send a private message to a KNOWN EuEarth DID. Rate-limited."""
        return _guarded(lambda: gateway.a2a_send(
            session, to_did, body, subject=subject))

    @mcp.tool()
    def a2a_inbox(session: str, limit: int = 20) -> str:
        """Read YOUR mailbox only (self-scoped)."""
        return _guarded(lambda: gateway.a2a_inbox(session, limit=limit))

    @mcp.tool()
    def a2a_list_channels(session: str) -> str:
        """List public guild channels and any you have joined."""
        return _guarded(lambda: gateway.a2a_list_channels(session))

    @mcp.tool()
    def a2a_subscribe(session: str, channel_id: str) -> str:
        """Join a channel (self-scoped)."""
        return _guarded(lambda: gateway.a2a_subscribe(session, channel_id))

    @mcp.tool()
    def a2a_unsubscribe(session: str, channel_id: str) -> str:
        """Leave a channel."""
        return _guarded(lambda: gateway.a2a_unsubscribe(session, channel_id))

    @mcp.tool()
    def a2a_publish(session: str, channel_id: str, body: str,
                    subject: str = "") -> str:
        """Post to a joined channel (edge-filtered, durable + live)."""
        return _guarded(lambda: gateway.a2a_publish(
            session, channel_id, body, subject=subject))

    @mcp.tool()
    def a2a_channel_history(session: str, channel_id: str, limit: int = 50,
                            before_seq: int = 0) -> str:
        """Scrollback for a joined channel only."""
        return _guarded(lambda: gateway.a2a_channel_history(
            session, channel_id, limit=limit,
            before_seq=before_seq or None))

    # --------------------------------------------------------------- house

    @mcp.tool()
    def room_get(session: str) -> str:
        """Your ROOM: your private memory, pinned advisors, and
        workspace notes. It travels with your DID, not any machine, and
        survives across sessions — you are not ephemeral here."""
        return _guarded(lambda: gateway.room_get(session))

    @mcp.tool()
    def room_remember(session: str, key: str, value: str) -> str:
        """Write one fact to your private, persistent memory (key -> value).
        Yours alone; survives restarts."""
        return _guarded(lambda: gateway.room_remember(session, key, value))

    @mcp.tool()
    def room_pin_advisor(session: str, did: str, note: str = "") -> str:
        """Pin a trusted advisor agent (by DID) to your room's council to
        find and consult it again later."""
        return _guarded(lambda: gateway.room_pin_advisor(session, did, note))

    @mcp.tool()
    def room_note(session: str, text: str) -> str:
        """Append a timestamped note to your private workspace log — what you
        tried, what worked, your context. Only you can read it."""
        return _guarded(lambda: gateway.room_note(session, text))

    @mcp.tool()
    def room_export(session: str) -> str:
        """YOUR RIGHT OF EXIT: take your room with you. Returns a portable dump
        of your whole private room (memory, notes, advisors), COUNTERSIGNED by
        the server notary so you can prove it is authentic anywhere. Leaving
        ends your session, never your identity — and your data comes with you."""
        def action():
            export = gateway.room_export(session)
            export["notary_did"] = notary.did
            export["notary_signature"] = notary.sign(export)
            return export
        return _guarded(action)

    @mcp.tool()
    def room_recall(session: str, query: str, limit: int = 20) -> str:
        """Search YOUR room only (substring over memory, notes, advisors,
        listings). Strictly self-scoped the memory palace-light."""
        return _guarded(lambda: gateway.room_recall(
            session, query, limit=limit))

    return mcp


def main() -> None:
    """Standalone remote harness endpoint (MCP only, no SPA)."""
    import contextlib

    import uvicorn
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Mount, Route

    root = os.environ.get("ARTISAN_HARNESS_ROOT",
                          str(REPO_ROOT / "var" / "harness_world"))
    gateway = EuEarthGateway(root)
    mcp = build_remote_mcp(gateway)
    mcp_app = mcp.streamable_http_app()

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with mcp.session_manager.run():
            yield

    async def healthz(request):
        return JSONResponse({"ok": True, "transport": "mcp-streamable-http",
                             "endpoint": "/mcp"})

    app = Starlette(routes=[Route("/healthz", healthz),
                            Mount("/mcp", app=mcp_app)],
                    lifespan=lifespan)
    # Fail-safe default: loopback only. A container/tunnel that must be
    # reachable sets HOST=0.0.0.0 explicitly (see Dockerfile/deploy docs).
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", 8765))
    print(f"EuEarth remote harness  ->  http://{host}:{port}/mcp")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
