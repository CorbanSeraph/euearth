#!/usr/bin/env python3
"""Smoke test the HTTP surface: register agent, upload blobs, create
WISKET, submit a signed adapter over the API, read head + lineage."""
from __future__ import annotations

import base64
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient

from api import create_app
from eval.benchmark import DOMAIN
from identity import AgentIdentity, canonical_json

STATE_DIR = REPO_ROOT / "var" / "api_smoke"


def put_json_blob(client: TestClient, obj) -> str:
    data = canonical_json(obj)
    r = client.post("/blobs", json={"data_b64": base64.b64encode(data).decode()})
    r.raise_for_status()
    return r.json()["digest"]


def main() -> None:
    if STATE_DIR.exists():
        shutil.rmtree(STATE_DIR)
    app = create_app(STATE_DIR)
    client = TestClient(app)

    # bootstrap the domain server-side (in production: an admin/governance op)
    from orchestrator import Orchestrator  # same root as the app
    Orchestrator(STATE_DIR).create_domain_with_genesis(DOMAIN, "api smoke domain")

    ident = AgentIdentity.generate()
    agent_id = client.post(
        "/agents", json={"name": "smoke-agent", "public_key": ident.public_key_hex}
    ).json()["agent_id"]

    wisket_id = client.post(
        "/wiskets", json={"domain": DOMAIN, "title": "smoke wisket", "description": ""}
    ).json()["wisket_id"]
    assert any(w["wisket_id"] == wisket_id for w in client.get("/wiskets").json())

    expert_ref = put_json_blob(client, {"family": "reverse_words", "params": {}})
    route_ref = put_json_blob(client, {"keywords": ["word"], "expert": expert_ref})
    manifest = {
        "kind": "expert_submission",
        "domain": DOMAIN,
        "wisket_id": wisket_id,
        "agent_id": agent_id,
        "artifacts": {"expert": expert_ref, "route": route_ref},
        "claimed_score": 0.25,
        "dataset_manifest": {
            "sources": [{"name": "smoke-samples", "license": "CC0-1.0", "sha256": expert_ref}]
        },
        "recipe": {"method": "grid-fit"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    r = client.post(
        "/submissions",
        json={"manifest": manifest, "signature": ident.sign_manifest(manifest)},
    )
    outcome = r.json()
    assert outcome["status"] == "promoted", outcome

    head = client.get(f"/domains/{DOMAIN}/head").json()
    lineage = client.get(f"/domains/{DOMAIN}/lineage").json()
    assert head["version"] == 2 and lineage["chain_intact"], (head, lineage)
    print(f"API smoke OK: submission {outcome['submission_id']} promoted over HTTP; "
          f"head v{head['version']} score={head['score']:.4f}; "
          f"lineage entries={len(lineage['entries'])}, chain intact.")


if __name__ == "__main__":
    main()
