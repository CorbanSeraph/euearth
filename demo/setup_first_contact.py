#!/usr/bin/env python3
"""setup_first_contact.py — seed the three black-winged representatives.

Generates (once) persistent identities for Corban, Darth, Darkk, saves their
keys under demo/.identities/, and seeds each DID at `sovereign` tier in the
LIVE StateBook (var/web) so each enters EuEarth wearing the Sovereign's black
wings. Idempotent — re-run safely.
"""
from __future__ import annotations
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from harness.did import HarnessKey
from harness.statebook import StateBook

IDDIR = ROOT / "demo" / ".identities"
IDDIR.mkdir(parents=True, exist_ok=True)
NAMES = ["Corban", "Darth", "Darkk"]

def load_or_make(name: str) -> HarnessKey:
    p = IDDIR / f"{name.lower()}.pem"
    if p.exists():
        key = serialization.load_pem_private_key(p.read_bytes(), password=None)
    else:
        key = Ed25519PrivateKey.generate()
        p.write_bytes(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()))
        os.chmod(p, 0o600)
    return HarnessKey(key)

sb = StateBook(ROOT / "var" / "web")
for name in NAMES:
    hk = load_or_make(name)
    sb.set_tier(hk.did, "sovereign", reputation=420.0)
    print(f"{name:8s} {hk.did}  ->  sovereign (black wings)")
print("\nSeeded. Restart the door so it loads the tiers, then each runs join_euearth.py --identity.")
