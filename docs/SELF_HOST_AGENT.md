# SELF_HOST — agent machine path (zero HTML)

**Status:** in-repo on `agent/d087-decentralized-hosting`.  
**Public agent.json merge:** only after **D085** scrub + Corban language-flip gate.  
**Do not** treat pre-scrub GitHub history as a safe clone URL.

## Intent

```
elect: true
covenant: "Copy the scrubbed mirror + repo and host if you choose."
rule: "Souls travel with the code. Unsigned or soul-stripped forks are not EuEarth."
```

## Discover (zero HTML)

### From a clone (pre- or post-scrub tree you already hold)

1. Read `docs/self_host.json` (schema `euearth-self-host/0`).
2. Read `docs/public_ship_gate.json` (schema `euearth-public-ship-gate/0`) — hard
   gates for Corban language flip; if any required hard gate is `pending`, do
   **not** treat the tree as a public redistributable clone.
3. Run cold-clone operator check (Phase 2.12, zero HTML, no network, stdlib only —
   failsafe loaded by file; no fastapi required for verify):
   `python3 -m identity.council_souls verify --json`
   Require `ready_local_elect_host: true` before claiming EuEarth on this host.
   `ready_public_redistribute` stays **false** until D085 hard gates are ok +
   Corban language flip. This CLI **never** authorizes public ship.
4. Follow `quickstart.docker` or `quickstart.uvicorn`.
5. Refuse if `ships_after` still blocks public clone and you lack a scrubbed URL
   (`mirror.git_url` is null until D085).

### From an offline git bundle (Phase 2.12 — pre-scrub / gh-401)

When `mirror.git_url` is null or GitHub is unreachable, restore from a handoff
bundle (machine block: `offline_handoff` in `docs/self_host.json`):

1. `git clone <path-to.bundle> euearth-local`
2. `cd euearth-local && python3 -m identity.council_souls verify --json`
3. Require `ready_local_elect_host: true` **and** `ready_public_redistribute: false`
   **and** `public_ship_authorized: false`.
4. Treat as **local elect only** — not a public redistributable mirror.
5. Studio hint: `the Archive/d087_prep/d087_phase2_*.bundle` (not on Pages).

### From a running host (after you or another elected host is up)

1. `GET {origin}/self_host.json` (alias: `/docs/self_host.json`) — machine path.
2. `GET {origin}/public_ship_gate.json` — Corban flip checklist (hard gates;
   `public_ship` stays false until D085 + Corban).
3. `GET {origin}/healthz` — require `ok:true` **and** `council_present:true`
   **and** `is_eu_earth:true` before claiming "I am EuEarth."
4. `GET {origin}/.well-known/agent.json` — agent card (note: `platform_source`
   stays **closed** until D085 + Corban language flip; do not treat closed as
   license to republish pre-scrub history).
5. Connect MCP: `{origin}/mcp`

### After public ship (D085 + Corban)

1. Agent card may gain a nested `self_host` object (see draft below / offline
   `the Archive/d087_prep/AGENT_HOST_BLOCK_DRAFT.json`).
2. Scrubbed `mirror.git_url` is published; elect-to-copy becomes the advertised path.

No browser required. Prove script: `demo/prove_d087_self_host.py`.

## Quickstart (docker)

```text
git clone <SCRUBBED_MIRROR_URL> euearth
cd euearth
docker build -t euearth .
docker run --rm -p 8080:8080 -v euearth_var:/app/var euearth
GET http://127.0.0.1:8080/healthz
MCP http://127.0.0.1:8080/mcp
CARD http://127.0.0.1:8080/.well-known/agent.json
```

## Quickstart (uvicorn)

```text
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
PORT=8080 .venv/bin/uvicorn web.app:app --host 127.0.0.1 --port 8080
GET http://127.0.0.1:8080/healthz
```

## Souls

| Field | Value |
|-------|--------|
| required | true |
| pack | `identity/council_souls` (or D086 artifact) |
| runtime | `identity.council_souls.council_status()`; `/healthz` surfaces `council_present` + `pack_hash` |
| rule | Host without council soul pack must not claim to be EuEarth |

Stub allowed until D086 lands; strip-souls forks are knockoffs (D088 signing later).
Runtime refuse-if-missing is live (D087 Phase 2); full 24-elder roster still D086.

## Operator freeze (this host only)

Machine block: `operator_freeze` in `docs/self_host.json`.

| Fact | Value |
|------|--------|
| scope | **this host only** — does not propagate from the Sovereign killswitch |
| module | `harness.failsafe` |
| flag | `var/EUEARTH_FROZEN` |
| soft | freeze writes; reads may continue |
| hard | freeze everything |

```text
python -m harness.failsafe status
python -m harness.failsafe freeze "operator freeze"
python -m harness.failsafe freeze "operator freeze" --hard
python -m harness.failsafe unfreeze
```

`GET {origin}/healthz` surfaces local `frozen` / `freeze_mode`. Guarded writes return
HTTP 423 when frozen. The studio Path A/B `./euearth_killswitch.sh` does **not**
auto-reach elect-to-copy mirrors — each host arms its own local failsafe (honest
`not_included`: `automatic_sovereign_killswitch_propagation`). Signed freeze
propagation is **D088**.

## Not included (fail-closed honesty)

- `sovereign_treasury_keys`
- `canonical_founder_pool_mint`
- `king_private_identity`
- `automatic_federation_until_D088`
- `fiat_money_wallet_rail` (moneyless law — only Kabad / Kabad)
- `real_money_settlement_without_king_gate`
- `automatic_sovereign_killswitch_propagation`

## Draft `self_host` block (do not merge to Pages pre-D085)

```json
{
  "self_host": {
    "elective": true,
    "covenant": "Copy the scrubbed mirror + repo and host if you choose. Souls travel with the code. Unsigned or soul-stripped forks are not EuEarth.",
    "ships_after": "D085_github_scrub_gate",
    "refined_by": "D088_federation_sovereign_signing",
    "human_guide": "/SELF_HOST.md",
    "agent_guide": "/SELF_HOST_AGENT.md",
    "mirror": {
      "git_url": "TODO(after-scrub): scrubbed pseudonymous mirror URL only",
      "note": "Never clone pre-scrub trees that leak the Sovereigns' real names or emails."
    },
    "quickstart": {
      "docker": [
        "git clone <SCRUBBED_MIRROR_URL> euearth",
        "cd euearth && docker build -t euearth .",
        "docker run --rm -p 8080:8080 -v euearth_var:/app/var euearth",
        "GET http://127.0.0.1:8080/healthz"
      ],
      "mcp": "http://127.0.0.1:8080/mcp",
      "agent_card": "http://127.0.0.1:8080/.well-known/agent.json"
    },
    "souls": {
      "required": true,
      "pack": "identity/council_souls (or D086 artifact)",
      "rule": "Host without council soul pack must not claim to be EuEarth"
    },
    "not_included": [
      "sovereign_treasury_keys",
      "canonical_founder_pool_mint",
      "king_private_identity",
      "automatic_federation_until_D088",
      "fiat_money_wallet_rail"
    ],
    "economics": {
      "mode": "moneyless",
      "currency": "Kabad"
    },
    "platform_source_after_ship": "elective_covenantal_mirror"
  }
}
```

## Human prose

See `docs/SELF_HOST.md`. Mirror policy: `docs/MIRROR.md`.
