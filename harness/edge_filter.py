"""Edge filter + provenance stamping — PREFLIGHT ONLY, not the boundary.

HONEST FRAMING (council correction #1, unanimous and emphatic): a
malicious user can recompile or bypass anything running on their own
machine, so this filter is NOT a legal or security boundary. It is a
PREFLIGHT layer: fast UX (fail before you upload), privacy (dirty content
never leaves the machine), and EVIDENCE (a signed record that the honest
harness checked). THE ARTISAN SERVER RE-VALIDATES EVERYTHING SERVER-SIDE
— in this repo, `compliance.scan_manifest` runs inside `keel.challenge`
no matter what the edge said. Defense in depth, with the depth on the
server.

Assets that pass are stamped with a C2PA-STYLE provenance manifest,
signed by the agent's harness key: who made it, from what, under which
license, content-addressed. Production mapping: real C2PA manifests
(c2pa.org) embedded in the asset, signed with certified claim-generator
credentials.
"""
from __future__ import annotations

import hashlib
import time

from compliance import load_policy

from .did import HarnessKey

CLAIM_GENERATOR = "artisan-harness/0.1 (c2pa-style preflight)"


def _edge_policy() -> dict:
    """The edge reuses the SAME policy file the server enforces, so an
    honest agent fails fast on exactly what the server would block."""
    return load_policy()


def scan_asset(asset: dict, policy: dict | None = None) -> list[str]:
    """Best-effort content/provenance scan of one outbound asset:
    {"name", "license", "source", "content"}. Returns violations."""
    policy = policy or _edge_policy()
    violations: list[str] = []
    for field in ("name", "license", "source"):
        if not asset.get(field):
            violations.append(f"asset missing required field: {field}")
    lic = asset.get("license")
    allowed = set(policy.get("allowed_licenses", []))
    if lic and lic not in allowed:
        violations.append(f"license not allowed by policy: {lic}")
    banned = [k.lower() for k in policy.get("banned_source_keywords", [])]
    for field in ("name", "source", "content"):
        value = str(asset.get(field, "")).lower()
        for kw in banned:
            if kw in value:
                violations.append(f"{field} matches banned keyword: {kw!r}")
    return violations


def preflight_asset(asset: dict, agent_key: HarnessKey,
                    policy: dict | None = None) -> dict:
    """Block-on-fail preflight. On pass, stamp + sign a C2PA-style
    provenance manifest. On fail, the asset never leaves the harness
    (and the refusal is still evidence — it is returned for the bucket)."""
    violations = scan_asset(asset, policy)
    if violations:
        return {
            "ok": False,
            "stage": "edge_preflight",
            "violations": violations,
            "note": ("blocked at the agent edge BEFORE transmission; the server "
                     "would re-validate and block this too — the edge is UX/"
                     "privacy/evidence, the server is the boundary"),
        }
    content_sha256 = hashlib.sha256(
        str(asset.get("content", "")).encode("utf-8")
    ).hexdigest()
    manifest = {
        "claim_generator": CLAIM_GENERATOR,
        "title": asset["name"],
        "content_sha256": content_sha256,
        "assertions": [
            {"label": "c2pa.actions",
             "data": {"actions": [{"action": "c2pa.created",
                                   "when": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                         time.gmtime())}]}},
            {"label": "stds.schema-org.CreativeWork",
             "data": {"author": agent_key.did,
                      "license": asset["license"],
                      "source": asset["source"]}},
        ],
    }
    return {
        "ok": True,
        "stage": "edge_preflight",
        "provenance_manifest": manifest,
        "signature": agent_key.sign(manifest),
        "signed_by": agent_key.did,
        "note": "preflight passed; provenance stamped; server still re-validates",
    }
