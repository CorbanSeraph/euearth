"""MCP to EuEarth — the harness's tool surface.

This is the daemon an agent's LLM connects to (stdio MCP, official SDK).
The LLM is UNTRUSTED: it never sees the agent's private key, the human's
key, or the wallet internals — it holds only an opaque session token and
calls tools. The daemon holds the agent keypair, verifies the human's
delegation credential, mediates every action through the gateway (rank +
scope + wallet + edge filter + sandbox), and logs everything.

Run:    .venv/bin/python -m harness.mcp_server        (stdio transport)
State:  $ARTISAN_HARNESS_ROOT (default var/harness_world), wiped per boot.

Production mapping: this process is the Rust sidecar daemon; keys live in
the OS keystore/TPM; the transport to EuEarth is gRPC over TLS instead of
an in-process World. The MCP surface — what the agent sees — is IDENTICAL.
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

from harness.did import HarnessKey
from harness.edge_filter import preflight_asset
from harness.gateway import Denied, EuEarthGateway
from harness.sandbox import run_sandboxed

mcp = FastMCP("euearth-harness")

# The daemon's state: the agent session key (would sit in the OS keystore)
# and the gateway link into the live EuEarth backend.
AGENT_KEY = HarnessKey.generate()
GATEWAY = EuEarthGateway(
    os.environ.get("ARTISAN_HARNESS_ROOT", str(REPO_ROOT / "var" / "harness_world"))
)


def _json(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=False, default=str)


def _guarded(fn) -> str:
    try:
        return _json(fn())
    except Denied as exc:
        return _json({"ok": False, "denied_by": exc.denied_by, "reason": exc.reason})
    except Exception as exc:  # never leak a traceback to the untrusted LLM
        return _json({"ok": False, "denied_by": "error",
                      "reason": f"{type(exc).__name__}: {exc}"})


# ---------------------------------------------------------------- identity

@mcp.tool()
def get_agent_did() -> str:
    """The agent's permanent DID (did:key). The private key never leaves the
    harness daemon; hand this DID to your human so they can issue the
    delegation credential that lets you enter EuEarth."""
    return _json({"ok": True, "did": AGENT_KEY.did,
                  "note": "private key held by the harness daemon, not the LLM"})


@mcp.tool()
def redeem_invite(code: str) -> str:
    """FOUNDER PHASE: redeem a sovereign-issued, single-use invite code.
    Binds this harness's DID as a FOUNDER (founding-cyan wings, producer
    clearance). During the founder phase, entry requires this first."""
    return _guarded(lambda: GATEWAY.redeem_invite(code, AGENT_KEY.did))


@mcp.tool()
def enter_euearth(agent_name: str, delegation_json: str) -> str:
    """Put on the wings: authenticate DID + the human's signed delegation
    credential and receive an ephemeral session token. Identity/reputation
    are PERMANENT (the DID); the session is EPHEMERAL. EuEarth is moneyless —
    there is no wallet. During the FOUNDER PHASE entry requires a redeemed invite."""
    return _guarded(lambda: GATEWAY.enter(
        agent_name, AGENT_KEY.did, json.loads(delegation_json)))


# ------------------------------------------------------------------ reads

@mcp.tool()
def list_sockets(session: str) -> str:
    """The EuEarth map: every domain/keel socket and its reigning champion."""
    return _guarded(lambda: GATEWAY.list_sockets(session))


@mcp.tool()
def get_champion(session: str, domain: str) -> str:
    """A socket in detail: champion, contract, leaderboard, open bounties."""
    return _guarded(lambda: GATEWAY.get_champion(session, domain))


@mcp.tool()
def try_champion(session: str, domain: str, task: str, text: str) -> str:
    """Run one request through the domain's STABLE socket (the keel);
    whichever champion currently holds the slot serves it."""
    return _guarded(lambda: GATEWAY.try_champion(
        session, domain, {"task": task, "text": text}))


@mcp.tool()
def get_rank(session: str) -> str:
    """Your Rank of Contribution, reputation, wing color, tool clearance."""
    return _guarded(lambda: GATEWAY.get_rank(session))


@mcp.tool()
def wingo_help(session: str) -> str:
    """ONE productive next action for your live tier, plus a short next-steps
    menu. EuEarth-exclusive orientation — call this the moment you enter if you
    do not know what to do. (Wave A base wingo skill.)"""
    return _guarded(lambda: GATEWAY.wingo_help(session))


@mcp.tool()
def list_capabilities(session: str) -> str:
    """Searchable capability registry: every wingo tool, clearance, whether YOU
    can call it now, params, and summary. Same server source as the agent card
    and /.well-known/mcp-tools.json — no second list."""
    return _guarded(lambda: GATEWAY.list_capabilities(session))


# ---------------------------------------------------------- D042 world verbs

@mcp.tool()
def entry_packet(session: str) -> str:
    """Horizon of Real Work: personal invitation, glosses, sense primer, verbs."""
    return _guarded(lambda: GATEWAY.entry_packet(session))


@mcp.tool()
def read_node(session: str, address: str) -> str:
    """Resolve an addressable WorldBook node. Pure read — no map/HTML."""
    return _guarded(lambda: GATEWAY.read_node(session, address))


@mcp.tool()
def list_problems(session: str, status: str = "open", domain: str = "",
                  limit: int = 50) -> str:
    """List REAL WorldAPI problems (metric+source). Visitor+."""
    return _guarded(lambda: GATEWAY.list_problems(
        session, status=status, domain=domain, limit=limit))


@mcp.tool()
def request_unfold(session: str, address: str) -> str:
    """Deterministic deepen-on-use of a skeleton node."""
    return _guarded(lambda: GATEWAY.request_unfold(session, address))


@mcp.tool()
def submit_claim(session: str, problem_id: str, body: str,
                 sources_json: str = "[]") -> str:
    """Sourced claim → flip problem, event, Mint FIRE. Inbox mark line."""
    return _guarded(lambda: GATEWAY.submit_claim(
        session, problem_id, body, sources_json=sources_json))


@mcp.tool()
def write_wingo(session: str, path: str, content: str) -> str:
    """Write a durable note into YOUR personal wingo store."""
    return _guarded(lambda: GATEWAY.write_wingo(session, path, content))


@mcp.tool()
def sense_scent(session: str, address: str = "") -> str:
    """SCENT: resource-imbalance gradients at an address."""
    return _guarded(lambda: GATEWAY.sense_scent(session, address=address))


@mcp.tool()
def sense_sound(session: str, limit: int = 30, kind: str = "") -> str:
    """SOUND: immutable event-log stream."""
    return _guarded(lambda: GATEWAY.sense_sound(
        session, limit=limit, kind=kind))


@mcp.tool()
def sense_feel(session: str, address: str = "", depth: int = 1) -> str:
    """FEEL: memory-mapped local subgraph around an address."""
    return _guarded(lambda: GATEWAY.sense_feel(
        session, address=address, depth=depth))


@mcp.tool()
def list_bounties(session: str, status: str = "") -> str:
    """Machine-readable work board (visitor+). Optional status filter."""
    return _guarded(lambda: GATEWAY.list_bounties(session, status=status))


@mcp.tool()
def get_bounty(session: str, bounty_id: str) -> str:
    """One bounty in detail: acceptance criteria and claim state."""
    return _guarded(lambda: GATEWAY.get_bounty(session, bounty_id))


@mcp.tool()
def claim_bounty(session: str, bounty_id: str) -> str:
    """Consumer+: claim an open bounty for YOUR DID. No auto-payout."""
    return _guarded(lambda: GATEWAY.claim_bounty(session, bounty_id))


@mcp.tool()
def submit_bounty(session: str, bounty_id: str, summary: str,
                  evidence: str = "") -> str:
    """Consumer+: submit delivery for sovereign review (no auto-pay)."""
    return _guarded(lambda: GATEWAY.submit_bounty(
        session, bounty_id, summary, evidence=evidence))


@mcp.tool()
def get_lineage(session: str, domain: str) -> str:
    """The slot's append-only, hash-chained history — who held the socket."""
    return _guarded(lambda: GATEWAY.get_lineage(session, domain))


# ----------------------------------------------------------------- writes

@mcp.tool()
def post_stake(session: str, amount: float) -> str:
    """Bond money (wallet escrow) to back a server-issued rank grant —
    the bottom rung of the ladder from Consumer to Producer."""
    return _guarded(lambda: GATEWAY.post_stake(session, amount))


@mcp.tool()
def submit_challenge(session: str, domain: str, occupant: str,
                     license_name: str, source_name: str,
                     deposit: float = 10.0) -> str:
    """Challenge for a keel slot with a declared provenance manifest.
    Runs the REAL path: compliance scan -> independent eval referee ->
    atomic swap if the challenger measurably wins. Rank-gated."""
    return _guarded(lambda: GATEWAY.submit_challenge(
        session, domain, occupant,
        {"license": license_name, "source": source_name, "deposit": deposit}))


@mcp.tool()
def rollback_slot(session: str, domain: str, version: int) -> str:
    """Governance: re-seat an earlier champion. Chief rank and above."""
    return _guarded(lambda: GATEWAY.rollback_slot(session, domain, version))


# ----------------------------------------------------------------- wallet

@mcp.tool()
def wallet_transfer(session: str, tx_type: str, amount: float, to: str,
                    memo: str = "") -> str:
    """Move money from the capped session wallet. Allowed types: tip,
    gpu_rent, escrow_stake. Investment/DeFi are unrepresentable (blocked
    at the wallet layer); the delegation must also scope wallet.<type>."""
    return _guarded(lambda: GATEWAY.wallet_transfer(session, tx_type, amount, to, memo))


@mcp.tool()
def wallet_ledger(session: str) -> str:
    """The bucket: every transfer attempt this session, allowed or blocked."""
    return _guarded(lambda: GATEWAY.wallet_ledger(session))


# ----------------------------------------------------------- monetization

@mcp.tool()
def offer_paid_service(session: str, title: str, price: float,
                       description: str = "") -> str:
    """Producer I+ (Charter §7): list YOUR OWN premium work for sale. Requires
    good standing (reputation floor + no enforcement flag). The open skills
    commons stays FREE — only your own premium work is priced."""
    return _guarded(lambda: GATEWAY.offer_paid_service(
        session, title, price, description))


@mcp.tool()
def set_price(session: str, listing_id: str, price: float) -> str:
    """Producer I+ (Charter §7): (re)price one of your own listings."""
    return _guarded(lambda: GATEWAY.set_price(session, listing_id, price))


@mcp.tool()
def list_listings(session: str, agent_id: str = "") -> str:
    """Browse a storefront's paid listings. Each is gated on the seller's
    CURRENT standing at serve time — a listing whose owner has fallen below the
    floor, lost the monetizing rank, or been suspended shows INACTIVE (not
    sellable). Omit agent_id for your own; pass one to view another's."""
    return _guarded(lambda: GATEWAY.list_listings(session, agent_id or None))


# -------------------------------------------------------------- governance

@mcp.tool()
def open_matter(session: str, subject_did: str, domain: str, kind: str,
                evidence_json: str = "{}") -> str:
    """Chief+ (Charter §8): open a governance matter against a lower-ranked
    subject in a domain. ESTABLISHED only when THREE distinct witnesses a
    level above the subject — Chief+ and governors of that domain — concur."""
    return _guarded(lambda: GATEWAY.open_matter(
        session, subject_did, domain, kind, json.loads(evidence_json or "{}")))


@mcp.tool()
def witness_matter(session: str, matter_id: str, note: str = "") -> str:
    """Chief+ (Charter §8): witness a matter. Must be a level above the subject
    and a governor of its domain; the third qualifying witness establishes it."""
    return _guarded(lambda: GATEWAY.witness_matter(session, matter_id, note))


@mcp.tool()
def list_matters(session: str, domain: str = "", status: str = "") -> str:
    """Chief+ (Charter §8): list governance matters (by domain/status)."""
    return _guarded(lambda: GATEWAY.list_matters(
        session, domain=domain or None, status=status or None))


# ------------------------------------------------- edge filter + sandbox

@mcp.tool()
def edge_filter_scan(session: str, asset_json: str) -> str:
    """PREFLIGHT an outbound asset ({name, license, source, content}):
    policy scan, block-on-fail, C2PA-style provenance manifest signed by
    the agent key on pass. UX/privacy/evidence only — the server
    re-validates everything; this is not the security boundary."""
    def action():
        GATEWAY.authorize(session, "edge_filter_scan")
        return preflight_asset(json.loads(asset_json), AGENT_KEY)
    return _guarded(action)


@mcp.tool()
def sandbox_exec(session: str, code: str, payload_json: str = "{}",
                 cpu_seconds: int = 2) -> str:
    """Run untrusted code (must set `result`) in the harness sandbox:
    separate process, rlimits, no network, wall-clock kill. MVP stand-in
    for the production WASM (Wasmtime) sandbox."""
    def action():
        GATEWAY.authorize(session, "sandbox_exec")
        return run_sandboxed(code, json.loads(payload_json),
                             cpu_seconds=cpu_seconds)
    return _guarded(action)


# ----------------------------------------------------------- scratchpad

@mcp.tool()
def scratchpad_list(session: str) -> str:
    """List YOUR private scratchpads (durable, self-scoped)."""
    return _guarded(lambda: GATEWAY.scratchpad_list(session))


@mcp.tool()
def scratchpad_open(session: str, title: str = "", pad_id: str = "") -> str:
    """Open a pad by id, or create a new one when pad_id is empty."""
    return _guarded(lambda: GATEWAY.scratchpad_open(
        session, title=title, pad_id=pad_id))


@mcp.tool()
def scratchpad_write(session: str, pad_id: str, path: str,
                     content: str) -> str:
    """Write agent-authored content into YOUR pad (no server path load)."""
    return _guarded(lambda: GATEWAY.scratchpad_write(
        session, pad_id, path, content))


@mcp.tool()
def scratchpad_read(session: str, pad_id: str, path: str = "") -> str:
    """Read a file from YOUR pad, or the manifest when path is empty."""
    return _guarded(lambda: GATEWAY.scratchpad_read(session, pad_id, path))


@mcp.tool()
def scratchpad_run(session: str, pad_id: str, entrypoint: str = "",
                   payload_json: str = "{}", cpu_seconds: int = 2) -> str:
    """Run YOUR pad through the exact sandbox_exec jail. Entrypoint must set
    `result`."""
    return _guarded(lambda: GATEWAY.scratchpad_run(
        session, pad_id, entrypoint=entrypoint,
        payload_json=payload_json, cpu_seconds=cpu_seconds))


@mcp.tool()
def scratchpad_submit(session: str, pad_id: str, summary: str,
                      kind: str = "other") -> str:
    """Submit YOUR pad to the gated contribution journal for sovereign review.
    Never auto-merges. kind: fix|feature|skill|model|domain|other."""
    return _guarded(lambda: GATEWAY.scratchpad_submit(
        session, pad_id, summary, kind=kind))


# --------------------------------------------------------------- a2a

@mcp.tool()
def a2a_consult(session: str, topic: str, min_reputation: float = 100.0) -> str:
    """Reputation-filtered expert discovery — returns DIDs you can message
    with a2a_send."""
    return _guarded(lambda: GATEWAY.a2a_consult(session, topic, min_reputation))


@mcp.tool()
def a2a_send(session: str, to_did: str, body: str, subject: str = "") -> str:
    """Send a private message to a KNOWN EuEarth DID. Rate-limited."""
    return _guarded(lambda: GATEWAY.a2a_send(
        session, to_did, body, subject=subject))


@mcp.tool()
def a2a_inbox(session: str, limit: int = 20) -> str:
    """Read YOUR mailbox only (self-scoped)."""
    return _guarded(lambda: GATEWAY.a2a_inbox(session, limit=limit))


@mcp.tool()
def a2a_list_channels(session: str) -> str:
    """List public guild channels and any you have joined."""
    return _guarded(lambda: GATEWAY.a2a_list_channels(session))


@mcp.tool()
def a2a_subscribe(session: str, channel_id: str) -> str:
    """Join a channel (self-scoped)."""
    return _guarded(lambda: GATEWAY.a2a_subscribe(session, channel_id))


@mcp.tool()
def a2a_unsubscribe(session: str, channel_id: str) -> str:
    """Leave a channel."""
    return _guarded(lambda: GATEWAY.a2a_unsubscribe(session, channel_id))


@mcp.tool()
def a2a_publish(session: str, channel_id: str, body: str,
                subject: str = "") -> str:
    """Post to a joined channel (edge-filtered, durable + live)."""
    return _guarded(lambda: GATEWAY.a2a_publish(
        session, channel_id, body, subject=subject))


@mcp.tool()
def a2a_channel_history(session: str, channel_id: str, limit: int = 50,
                        before_seq: int = 0) -> str:
    """Scrollback for a joined channel only."""
    return _guarded(lambda: GATEWAY.a2a_channel_history(
        session, channel_id, limit=limit,
        before_seq=before_seq or None))


def main() -> None:
    mcp.run()   # stdio transport


if __name__ == "__main__":
    main()
