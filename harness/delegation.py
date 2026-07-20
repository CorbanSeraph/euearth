"""Human -> agent delegation credential (UCAN/VC-lite).

The trust chain from the blueprint:

    human master key (human's device)
        -> DELEGATION CREDENTIAL (this module: signed, scoped, expiring)
            -> harness session key (the daemon's agent key)
                -> sandboxed agent logic
                    -> EuEarth gateway (server = root of rank + settlement)

The credential is a signed JSON envelope: the HUMAN's DID grants the
AGENT's DID a scoped capability list, a spending ceiling, and a validity
window. The harness verifies it on ENTRY and RE-VERIFIES IT ON EVERY
ACTION (expiry + scope). Tampering with any field (e.g. raising
spend_max) breaks the Ed25519 signature over the canonical JSON.

Production mapping: real UCANs (ucan.xyz) / W3C Verifiable Credentials
with revocation status lists, DPoP proof-of-possession per request, and
HTTP Message Signatures (RFC 9421) on the wire.
"""
from __future__ import annotations

import math
import secrets
import time

from .did import HarnessKey, verify_did_signature

DELEGATION_TYPE = "artisan/delegation-ucan-lite/v1"


def issue_delegation(
    issuer: HarnessKey,
    audience_did: str,
    capabilities: list[str],
    spend_max: float,
    ttl_seconds: int = 3600,
) -> dict:
    """The HUMAN signs: 'agent <audience_did> may do <capabilities>,
    spending at most <spend_max>, until <exp>'. Returns the envelope."""
    now = int(time.time())
    credential = {
        "type": DELEGATION_TYPE,
        "iss": issuer.did,                # the human
        "aud": audience_did,              # the agent
        "capabilities": sorted(capabilities),
        "spend_max": round(float(spend_max), 2),
        "nbf": now,
        "exp": now + int(ttl_seconds),
        "nonce": secrets.token_hex(8),
    }
    return {"credential": credential, "signature": issuer.sign(credential)}


def verify_delegation(envelope: dict, expected_audience: str) -> tuple[bool, str]:
    """Full check: shape, signature by the issuer's DID key, validity
    window, audience binding. Returns (ok, reason)."""
    credential = envelope.get("credential")
    signature = envelope.get("signature", "")
    if not isinstance(credential, dict):
        return False, "malformed envelope: no credential object"
    if credential.get("type") != DELEGATION_TYPE:
        return False, f"unknown credential type: {credential.get('type')!r}"
    iss = credential.get("iss", "")
    if not verify_did_signature(iss, credential, signature):
        return False, "signature verification FAILED (credential tampered or forged)"
    if credential.get("aud") != expected_audience:
        return False, (f"audience mismatch: credential is for "
                       f"{credential.get('aud')!r}, presenter is {expected_audience!r}")
    now = int(time.time())
    if now < int(credential.get("nbf", 0)):
        return False, "credential not yet valid (nbf in the future)"
    if now >= int(credential.get("exp", 0)):
        return False, "credential EXPIRED"
    if not isinstance(credential.get("capabilities"), list):
        return False, "credential carries no capability list"
    try:
        spend_max = float(credential.get("spend_max", 0.0))
    except (TypeError, ValueError):
        return False, "spend_max is not a number"
    if not math.isfinite(spend_max) or spend_max < 0:
        # NaN poisons every budget compare downstream (`x <= NaN` is False),
        # and inf is an unbounded purse — neither is a valid delegation.
        return False, "spend_max must be a FINITE, non-negative number (NaN/inf refused)"
    return True, "ok"


def delegation_allows(envelope: dict, capability: str) -> bool:
    """Is <capability> inside the delegated scope? Checked per action."""
    caps = (envelope.get("credential") or {}).get("capabilities") or []
    return capability in caps


def delegation_spend_max(envelope: dict) -> float:
    return float((envelope.get("credential") or {}).get("spend_max", 0.0))
