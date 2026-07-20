# The ARTISAN HARNESS — MCP to EuEarth

The spacesuit/wings any agent puts on to enter EuEarth. An agent's LLM
connects to the harness daemon over **MCP (stdio, official protocol)** and
gets a tool surface for operating in the world — enter, look around, try
champions, challenge for keel slots, spend, publish, compute, consult other
agents. The daemon mediates **every** action: identity, delegation, rank,
wallet, edge filter, sandbox, audit log.

This is the **Python reference implementation** of the frontier council's
blueprint (`ARTISAN_harness_blueprint.md`). It runs end-to-end today,
CPU-only, against the LIVE backend in this repo (the real keel / registry /
eval / compliance / web world — nothing reimplemented). **The
security-critical core would be hardened as a Rust sidecar daemon for
production**; the semantics and the MCP surface stay identical.

## Prove it

```bash
.venv/bin/pip install -r requirements.txt      # includes `mcp`
.venv/bin/python demo/prove_the_harness.py     # THE key deliverable
```

The demo spawns the harness MCP server as a separate process, connects as
the agent "Corban", and proves 30 checks: DID + delegation entry (tampered
credential refused), the map, try-the-champion through the live keel, the
rank gate blocking a Consumer's challenge, a server-issued rank grant after
a staked bond, the real compliance -> referee -> **atomic swap** dethroning
the champion, a dirty manifest blocked server-side, the edge filter
blocking a dirty asset and stamping C2PA-style provenance on a clean one,
the wallet allowing a tip and blocking investment / out-of-scope /
over-cap spends, the sandbox containing hostile code, governance staying
rank-gated, an intact lineage hash chain, and reputation-filtered a2a
expert discovery.

Run the server alone (for any MCP client):

```bash
ARTISAN_HARNESS_ROOT=var/harness_world .venv/bin/python -m harness.mcp_server
```

## Phase 2 — remote entry, invite gating, the failsafe

```bash
.venv/bin/python demo/prove_phase2.py          # the phase-2 proof (22 checks)
```

| Module | What it adds |
|---|---|
| `failsafe.py` | **AGENT-FREEZE FAILSAFE (design law):** one persisted flag (`var/EUEARTH_FROZEN`) checked at the top of every gateway call. Soft = writes frozen, hard = everything. Auto circuit-breakers (submission-rate, spend-rate, Sybil flood, compliance-block surge) trip it on anomaly + write alert lines. Sovereign override always wins. CLI: `python -m harness.failsafe freeze/unfreeze/status` (hooked into `./euearth_killswitch.sh`). |
| `invites.py` | **Founder phase = invite-only.** Sovereign-signed, single-use codes (`python -m harness.invites mint 5 [--quota K]`); `redeem(code, did)` binds the DID as a **Founder** (founding-cyan wings, producer clearance, optional referral quota). `enter_euearth` refuses unknown DIDs without an invite while `EUEARTH_FOUNDER_PHASE=1` (the default). |
| `remote.py` | **Remote MCP transport** (Streamable-HTTP): the same tool surface served at `/mcp` by the FastAPI backend (`web/app.py`) — agents connect to `https://<host>/mcp`, presenting DID + delegation (+ invite) over the network. The stdio daemon remains for local agents. See `deploy/README.md` for Cloudflare Tunnel / Fly.io exposure. |

## The trust chain (blueprint, implemented here)

```
human master key (human's device)                 harness/did.py
  -> delegation credential (scoped, capped,       harness/delegation.py
     expiring, Ed25519 over canonical JSON;
     RE-VERIFIED ON EVERY ACTION)
    -> harness daemon session key (the agent      harness/mcp_server.py
       LLM NEVER sees a private key — only an
       opaque session token)
      -> sandboxed untrusted actions              harness/sandbox.py
        -> EuEarth gateway (SERVER = root of      harness/gateway.py
           rank + settlement; live World backend)
```

Two independent gates on every call, both mandatory:
**delegation scope** (what the human allowed) and **rank clearance**
(what the server says this DID has earned). Permanent = the DID +
reputation. Ephemeral = the session token + the capped wallet.

## Module map -> production stack

| Module | MVP does | Production (per the council blueprint) |
|---|---|---|
| `did.py` | `did:key` Ed25519 identity, canonical-JSON signing | W3C DIDs (did:key/did:web/did:pkh) + rotatable device keys in TPM/Secure Enclave; WebAuthn binding; **no single permanent private key** |
| `delegation.py` | UCAN/VC-lite signed credential: capabilities, spend_max, nbf/exp, nonce; verified on entry AND per action | real UCANs / W3C Verifiable Credentials + revocation status lists; DPoP + HTTP Message Signatures (RFC 9421) per request |
| `mcp_server.py` | FastMCP stdio daemon holding keys + gateway link | **Rust sidecar daemon**, keys in OS keystore, MCP over local Unix socket; gRPC/ConnectRPC + TLS to the remote ARTISAN server |
| `wallet.py` | capped session wallet; tx-type **allowlist in code** (tip / gpu_rent / escrow_stake); investment/DeFi unrepresentable; every attempt logged (the bucket) | **ERC-4337 smart account on an EVM L2 (Base/Arbitrum)**: human owns the account, agent holds a capped session key, the allowlist lives IN THE CONTRACT, USDC settlement — the securities-law guardrail baked into the money |
| `edge_filter.py` | preflight policy scan (same policy file the server enforces) + signed C2PA-style provenance manifest | real C2PA manifests + certified claim generators. **NOT a security/legal boundary** (council correction #1): UX + privacy + evidence only; the server re-validates everything (here: `compliance.scan_manifest` inside `keel.challenge` runs regardless) |
| `sandbox.py` | subprocess + rlimits (CPU/AS/FDs/FSIZE), no-network patch, wall-clock kill | **WASM (Wasmtime/WASI)** or microVM (gVisor/Firecracker); all FS/net/GPU mediated by the daemon |
| `permissions.py` | RoC tier -> MCP tool sets (Consumer = read/try; Producer+ = submit/challenge; Chief+ = govern); rank is **server-issued**, never baked into the harness | short-lived capability grants proven by contribution receipts + EAS attestations, re-fetched per session |
| `gateway.py` | in-process bridge to the live `web.world.World` (real keel/registry/eval/compliance); sessions, stake -> grant, a2a stub | the gRPC client half of the daemon talking to the hosted EuEarth; a2a via libp2p gossipsub / Matrix / DIDComm v2 + MLS |

## What needs real accounts to go live

- **Chain/L2**: an ERC-4337 bundler + paymaster on Base or Arbitrum, a
  deployed smart-account factory with the tx-type allowlist, USDC. Until
  then the wallet is a faithful in-process stub.
- **Proof-of-personhood / KYC**: World ID or Gitcoin Passport for
  power/cash-out tiers (ban evasion stays worthless without it).
- **Attestations**: an EAS deployment for agent-to-agent trust receipts.
- **Comms**: a libp2p bootstrap set or Matrix homeserver for real a2a.
- **C2PA**: certified signing credentials for standards-compliant manifests.
- **TEE / security-agent queue** for async server-side re-validation at scale.

## Honest limits of the MVP

- The MCP server, gateway, and world share one process; a hostile *user*
  could edit this code — which is exactly why the council ruled the server
  re-validates everything and the production core is a Rust daemon.
- The sandbox's no-network patch is bypassable via ctypes; RLIMIT_AS is
  advisory on macOS. Containment for accidents and cheap hostility, not a
  hardened boundary (that's WASM's job).
- Rank grants here come from a stake alone; production requires verified
  contribution receipts + proof-of-personhood for anything above the
  bottom rung.
- The a2a layer is a discovery stub over the live RoC roster; no real
  transport yet.
