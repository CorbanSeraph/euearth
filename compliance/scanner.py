"""Compliance scanner v0.

Validates a submission's dataset/license manifest against a policy JSON
and blocks on failure. HONEST FRAMING (council finding #5): this is
best-effort provenance + policy compliance. It verifies what agents
DECLARE; it cannot prove data was lawfully obtained. Production adds
hash-linked dataset manifests and random human/legal audit on top.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_POLICY_PATH = Path(__file__).parent / "policy.json"


@dataclass
class ComplianceResult:
    ok: bool
    violations: list[str] = field(default_factory=list)


def load_policy(path: str | Path | None = None) -> dict:
    return json.loads(Path(path or DEFAULT_POLICY_PATH).read_text())


def scan_manifest(manifest: dict, policy: dict) -> ComplianceResult:
    violations: list[str] = []

    for f in policy.get("required_manifest_fields", []):
        if f not in manifest:
            violations.append(f"manifest missing required field: {f}")

    ds = manifest.get("dataset_manifest") or {}
    sources = ds.get("sources")
    if not isinstance(sources, list) or not sources:
        violations.append("dataset_manifest.sources must be a non-empty list")
        sources = []

    allowed = set(policy.get("allowed_licenses", []))
    banned_kw = [k.lower() for k in policy.get("banned_source_keywords", [])]
    required_src = policy.get("required_source_fields", [])

    for i, src in enumerate(sources):
        if not isinstance(src, dict):
            violations.append(f"source[{i}] is not an object")
            continue
        for f in required_src:
            if not src.get(f):
                violations.append(f"source[{i}] missing required field: {f}")
        lic = src.get("license")
        if lic and lic not in allowed:
            violations.append(f"source[{i}] license not allowed by policy: {lic}")
        name = str(src.get("name", "")).lower()
        for kw in banned_kw:
            if kw in name:
                violations.append(f"source[{i}] name matches banned keyword: {kw!r}")

    return ComplianceResult(ok=not violations, violations=violations)
