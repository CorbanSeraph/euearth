"""Run Bender's demo mutation as a registered, signed code-layer agent."""
from __future__ import annotations

import json
import os
import secrets
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from bender.demo import DEMO_MUTATION_PAYLOAD
from identity.keys import AgentIdentity
from registry.db import Registry


def main() -> None:
    root = Path(os.environ.get("ARTISAN_ROOT", "var/api"))
    key_path = Path(os.environ.get("BENDER_DEMO_KEY", root / "bender-demo-agent.pem"))
    identity = AgentIdentity.load(key_path) if key_path.exists() else AgentIdentity.generate()
    if not key_path.exists():
        identity.save(key_path)

    registry = Registry(root / "registry.sqlite3")
    agent_id = registry.register_agent("Bender signed demo agent", identity.public_key_hex)
    registry.close()

    manifest = {
        "did": f"did:artisan:{agent_id}",
        "payload": DEMO_MUTATION_PAYLOAD,
        "nonce": secrets.token_hex(16),
        "timestamp": int(time.time()),
    }
    body = {**manifest, "signature": identity.sign_manifest(manifest)}
    base_url = os.environ.get("BENDER_URL", "http://localhost:8000")
    request = urllib.request.Request(
        f"{base_url}/api/demo_tick",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        print(response.read().decode("utf-8"))


if __name__ == "__main__":
    main()
