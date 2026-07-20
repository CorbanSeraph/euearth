from __future__ import annotations

import tempfile
import time
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from bender.demo import DEMO_MUTATION_PAYLOAD
from bender.server import SIGNATURE_WINDOW_SECONDS, create_app
from bender.tree import genesis
from identity.keys import AgentIdentity
from merlin.guard import MerlinGuard
from registry.db import Registry


def signed_request(identity: AgentIdentity, did: str, payload: dict, **overrides) -> dict:
    manifest = {
        "did": did,
        "payload": payload,
        "nonce": overrides.get("nonce", uuid.uuid4().hex),
        "timestamp": overrides.get("timestamp", int(time.time())),
    }
    signer = overrides.get("signer", identity)
    return {**manifest, "signature": signer.sign_manifest(manifest)}


def mutation_payload() -> dict:
    return {"target_asset_id": "keel_0", "transform": {"rotation": [0, 0.5, 0]}}


class BenderSignatureAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.identity = AgentIdentity.generate()
        registry = Registry(self.root / "registry.sqlite3")
        agent_id = registry.register_agent("test signer", self.identity.public_key_hex)
        registry.close()
        self.did = f"did:artisan:{agent_id}"
        self.client = TestClient(create_app(self.root))

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def test_unknown_did_and_bad_or_missing_signature_are_rejected(self):
        forged = signed_request(
            self.identity, "did:artisan:not-registered", mutation_payload()
        )
        self.assertEqual(self.client.post("/api/mutate", json=forged).status_code, 401)

        bad = signed_request(self.identity, self.did, mutation_payload())
        bad["signature"] = "00" * 64
        self.assertEqual(self.client.post("/api/mutate", json=bad).status_code, 401)

        missing = signed_request(self.identity, self.did, mutation_payload())
        del missing["signature"]
        self.assertEqual(self.client.post("/api/mutate", json=missing).status_code, 401)

    def test_wrong_registered_key_signature_is_rejected(self):
        request = signed_request(
            self.identity,
            self.did,
            mutation_payload(),
            signer=AgentIdentity.generate(),
        )
        self.assertEqual(self.client.post("/api/mutate", json=request).status_code, 401)

    def test_reused_nonce_survives_app_restart_and_stale_timestamp_is_rejected(self):
        request = signed_request(self.identity, self.did, mutation_payload())
        self.assertEqual(self.client.post("/api/mutate", json=request).status_code, 200)
        self.assertEqual(self.client.post("/api/mutate", json=request).status_code, 401)

        restarted_client = TestClient(create_app(self.root))
        self.assertEqual(restarted_client.post("/api/mutate", json=request).status_code, 401)
        restarted_client.close()

        stale = signed_request(
            self.identity,
            self.did,
            mutation_payload(),
            timestamp=int(time.time()) - SIGNATURE_WINDOW_SECONDS - 1,
        )
        self.assertEqual(self.client.post("/api/mutate", json=stale).status_code, 401)

    def test_valid_registered_did_can_mutate_and_demo_tick(self):
        mutate = signed_request(self.identity, self.did, mutation_payload())
        response = self.client.post("/api/mutate", json=mutate)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")

        tick = signed_request(self.identity, self.did, DEMO_MUTATION_PAYLOAD)
        response = self.client.post("/api/demo_tick", json=tick)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")

    def test_unlock_also_requires_a_valid_signature(self):
        request = signed_request(
            self.identity, self.did, {"target_asset_id": "keel_0"}
        )
        request["signature"] = "not-a-signature"
        self.assertEqual(self.client.post("/api/unlock", json=request).status_code, 401)

    def test_rotation_threshold_is_live_below_schema_maximum(self):
        tree = genesis(
            {
                "zone_id": "test_zone",
                "author_did": self.did,
                "class": "G0",
                "scene_root": "test-root",
                "privacy_level": 0,
            }
        )
        guard = MerlinGuard(tree)
        with self.assertRaisesRegex(Exception, "three-witness consensus"):
            guard.process_mutation(
                self.did,
                {"target_asset_id": "keel_0", "transform": {"rotation": [51, 0, 0]}},
            )
        self.assertEqual(tree.assets["keel_0"]["transform"]["rotation"], [0, 0, 0])


if __name__ == "__main__":
    unittest.main()
