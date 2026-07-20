"""did:key identity for the harness — W3C DIDs over Ed25519.

The agent's PERMANENT logical identity is a DID (`did:key:z6Mk...`), the
multibase/multicodec encoding of its Ed25519 public key. Reputation and
bans attach to the DID (the credential), never the machine. Per the
council blueprint there is NO single permanent private key in production:
the human's master key lives on the human's device (TPM/Secure Enclave),
the harness daemon holds a rotatable session/device key, and the agent's
LLM never sees either — it gets only a short-lived session token.

This module gives the MVP both roles: the human's key (issues the
delegation) and the daemon's agent key (signs actions). Clean-room,
stdlib + `cryptography` only.
"""
from __future__ import annotations

from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from identity.keys import canonical_json

# base58btc (Bitcoin alphabet) — required by the did:key multibase 'z' prefix.
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

# multicodec varint prefix for an Ed25519 public key (0xed, varint-encoded).
_MULTICODEC_ED25519_PUB = b"\xed\x01"


def b58encode(data: bytes) -> str:
    n = int.from_bytes(data, "big")
    out = ""
    while n:
        n, rem = divmod(n, 58)
        out = _B58[rem] + out
    # preserve leading zero bytes
    pad = len(data) - len(data.lstrip(b"\x00"))
    return "1" * pad + out


def b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        n = n * 58 + _B58.index(ch)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    pad = len(s) - len(s.lstrip("1"))
    return b"\x00" * pad + raw


def did_from_public_bytes(raw_public: bytes) -> str:
    if len(raw_public) != 32:
        raise ValueError("Ed25519 public key must be 32 bytes")
    return "did:key:z" + b58encode(_MULTICODEC_ED25519_PUB + raw_public)


def public_bytes_from_did(did: str) -> bytes:
    if not did.startswith("did:key:z"):
        raise ValueError(f"not a did:key with base58btc multibase: {did!r}")
    decoded = b58decode(did[len("did:key:z"):])
    if not decoded.startswith(_MULTICODEC_ED25519_PUB):
        raise ValueError("did:key does not carry an Ed25519 public key")
    raw = decoded[len(_MULTICODEC_ED25519_PUB):]
    if len(raw) != 32:
        raise ValueError("malformed did:key payload")
    return raw


class HarnessKey:
    """An Ed25519 keypair addressed by its DID. Signs canonical JSON."""

    def __init__(self, private_key: Ed25519PrivateKey):
        self._private = private_key

    @classmethod
    def generate(cls) -> "HarnessKey":
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def load(cls, path: str | Path) -> "HarnessKey":
        key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
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

    @property
    def public_bytes(self) -> bytes:
        return self._private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
        )

    @property
    def public_key_hex(self) -> str:
        return self.public_bytes.hex()

    @property
    def did(self) -> str:
        return did_from_public_bytes(self.public_bytes)

    def sign(self, payload: dict) -> str:
        """Sign the canonical JSON of a payload; hex signature."""
        return self._private.sign(canonical_json(payload)).hex()


def verify_did_signature(did: str, payload: dict, signature_hex: str) -> bool:
    """Verify a canonical-JSON signature against the key inside a did:key."""
    try:
        pub = Ed25519PublicKey.from_public_bytes(public_bytes_from_did(did))
        pub.verify(bytes.fromhex(signature_hex), canonical_json(payload))
        return True
    except (InvalidSignature, ValueError):
        return False
