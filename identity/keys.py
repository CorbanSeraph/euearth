"""Ed25519 agent identity.

An agent's identity IS its public key: agent_id = sha256(raw public key).
Submissions are manifests signed over their canonical JSON bytes, so any
mirror or third party can verify authorship without trusting ARTISAN.

Production mapping: the same Ed25519 signatures, plus Sigstore/in-toto
attestations binding the agent key to an OIDC principal (the human/org
the agent acts for). Agents are delegates, not legal identities.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.exceptions import InvalidSignature


def canonical_json(obj) -> bytes:
    """Deterministic JSON bytes: sorted keys, tight separators, UTF-8.

    Sign/verify ALWAYS goes through this so a manifest has exactly one
    valid byte representation."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def agent_id_for_public_key(public_key_hex: str) -> str:
    return hashlib.sha256(bytes.fromhex(public_key_hex)).hexdigest()


class AgentIdentity:
    """Holds an Ed25519 keypair; signs manifests."""

    def __init__(self, private_key: Ed25519PrivateKey):
        self._private = private_key

    # --- lifecycle -------------------------------------------------------

    @classmethod
    def generate(cls) -> "AgentIdentity":
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def load(cls, path: str | Path) -> "AgentIdentity":
        pem = Path(path).read_bytes()
        key = serialization.load_pem_private_key(pem, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("not an Ed25519 private key")
        return cls(key)

    def save(self, path: str | Path) -> None:
        pem = self._private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(pem)
        p.chmod(0o600)

    # --- identity --------------------------------------------------------

    @property
    def public_key_hex(self) -> str:
        raw = self._private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return raw.hex()

    @property
    def agent_id(self) -> str:
        return agent_id_for_public_key(self.public_key_hex)

    # --- signing ---------------------------------------------------------

    def sign_manifest(self, manifest: dict) -> str:
        """Sign the canonical JSON of a manifest; returns hex signature."""
        return self._private.sign(canonical_json(manifest)).hex()


def verify_manifest(public_key_hex: str, manifest: dict, signature_hex: str) -> bool:
    """Verify a manifest signature against a registered public key."""
    try:
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        pub.verify(bytes.fromhex(signature_hex), canonical_json(manifest))
        return True
    except (InvalidSignature, ValueError):
        return False
