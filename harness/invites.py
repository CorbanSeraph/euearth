"""INVITE-CODE FOUNDER SYSTEM — founder-phase entry is by invitation.

EuEarth's founder phase has NO open registration: an unknown DID cannot
enter until it redeems a signed invite code issued by the sovereign
(Corban / the Sovereigns). Redemption is SINGLE-USE and binds the code to the
agent's DID as a **Founder** — a founding-citizen rank above Consumer in
the RoC ladder (founding-cyan wings, producer-grade tools: founders are
trusted to build the square from day one).

The pieces:
  * codes are SIGNED (Ed25519, the sovereign issuer key at
    `<invites_root>/issuer_key.pem`) AND allowlisted (the store at
    `<invites_root>/invites.json`) — forging a code fails the signature,
    replaying one fails the single-use allowlist. Two independent gates.
  * `redeem(code, agent_did)` -> a founder record, persisted. Founder
    records survive backend restarts (unlike the in-memory world state):
    they ARE the registration book of the founder phase.
  * optional referral quota: a code minted with `--quota K` lets the
    founder who redeemed it mint K more codes (`founder_mint`).

Roots are env-configurable (`EUEARTH_INVITES_ROOT`, default
`var/invites`); every operation reads/writes the store fresh so the CLI,
the stdio harness, and the remote endpoint share one book.

CLI (the sovereign's minting tool):
    python -m harness.invites mint 5 [--quota K]
    python -m harness.invites list
    python -m harness.invites status <code-or-id>
"""
from __future__ import annotations

import fcntl
import json
import os
import secrets
import time
from contextlib import contextmanager
from pathlib import Path

from .did import HarnessKey, verify_did_signature

REPO_ROOT = Path(__file__).resolve().parent.parent

CODE_PREFIX = "EUE"


class InviteError(Exception):
    """A refused invite operation, with a polite reason."""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class InviteBook:
    """The sovereign's invite ledger: codes + founders, one JSON store."""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or os.environ.get(
            "EUEARTH_INVITES_ROOT", REPO_ROOT / "var" / "invites"))
        self._store_path = self.root / "invites.json"
        self._issuer_path = self.root / "issuer_key.pem"
        self._lock_path = self.root / "invites.lock"

    # ------------------------------------------------------------- storage

    @contextmanager
    def _exclusive(self):
        """A cross-process/thread mutex around a read-modify-write of the
        store. Holds an fcntl exclusive lock on a sidecar lock file for the
        duration of the `with` block, so a load-check-save can never
        interleave with another redemption (fixes the single-use TOCTOU:
        two concurrent redeems of one code, both committing — issue #8)."""
        self.root.mkdir(parents=True, exist_ok=True)
        # Open in append mode so the lock file is created if missing but its
        # (empty) contents are never truncated by a concurrent holder.
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def _load(self) -> dict:
        if not self._store_path.exists():
            return {"codes": {}, "founders": {}}
        return json.loads(self._store_path.read_text(encoding="utf-8"))

    def _save(self, store: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self._store_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(store, indent=2, sort_keys=True),
                       encoding="utf-8")
        tmp.replace(self._store_path)

    def _issuer(self, create: bool = False) -> HarnessKey | None:
        if self._issuer_path.exists():
            return HarnessKey.load(self._issuer_path)
        if not create:
            return None
        key = HarnessKey.generate()
        key.save(self._issuer_path)
        return key

    # ------------------------------------------------------------- minting

    @staticmethod
    def _payload(code_id: str, quota: int, issued_by: str) -> dict:
        return {"kind": "euearth-founder-invite/v1", "code_id": code_id,
                "quota": int(quota), "issued_by": issued_by}

    def _mint_into(self, store: dict, n: int, quota: int,
                   issued_by: str) -> list[str]:
        """Mint N codes INTO an already-loaded store (caller holds the lock
        and is responsible for the save)."""
        issuer = self._issuer(create=True)
        codes: list[str] = []
        for _ in range(n):
            code_id = secrets.token_hex(8)
            signature = issuer.sign(self._payload(code_id, quota, issued_by))
            store["codes"][code_id] = {
                "status": "unused",
                "quota": int(quota),
                "issued_by": issued_by,
                "signature": signature,
                "minted_at": _now(),
            }
            codes.append(f"{CODE_PREFIX}-{code_id}-{signature[:24]}")
        return codes

    def mint(self, n: int, quota: int = 0,
             issued_by: str = "sovereign") -> list[str]:
        """The sovereign issues N single-use founder codes, each signed by
        the issuer key and recorded on the allowlist. The load-mutate-save
        runs under the same exclusive lock as redemption so a concurrent
        mint can never clobber a redemption's write."""
        if n < 1:
            raise InviteError("mint at least one code")
        with self._exclusive():
            store = self._load()
            codes = self._mint_into(store, n, quota, issued_by)
            self._save(store)
        return codes

    def founder_mint(self, founder_did: str, n: int = 1) -> list[str]:
        """A founder spends referral quota to invite N more agents. The
        quota debit and the new codes commit atomically under the lock."""
        with self._exclusive():
            store = self._load()
            founder = store["founders"].get(founder_did)
            if founder is None:
                raise InviteError("only founders may refer new agents")
            if founder.get("invites_left", 0) < n:
                raise InviteError(
                    f"referral quota exhausted: {founder.get('invites_left', 0)} left")
            founder["invites_left"] -= n
            codes = self._mint_into(store, n, 0, founder_did)
            self._save(store)
        return codes

    # ---------------------------------------------------------- redemption

    def redeem(self, code: str, agent_did: str) -> dict:
        """Verify + burn one code; bind the DID as a Founder. Single-use:
        a redeemed code is dead, and a founded DID needs no second code.

        The entire load-check-burn-save runs under an exclusive file lock so
        two concurrent redemptions of ONE code cannot both commit (issue #8
        TOCTOU): the second redeemer re-reads a store whose code is already
        `redeemed` and is refused."""
        with self._exclusive():
            store = self._load()
            if agent_did in store["founders"]:
                raise InviteError("this DID is already a founder — just enter")
            parts = (code or "").strip().split("-")
            if len(parts) != 3 or parts[0] != CODE_PREFIX:
                raise InviteError("malformed invite code")
            code_id, sig_hint = parts[1], parts[2]
            entry = store["codes"].get(code_id)
            if entry is None:
                raise InviteError("unknown invite code — not on the allowlist")
            if entry["status"] != "unused":
                raise InviteError("invite code already redeemed (single-use)")
            if not entry["signature"].startswith(sig_hint):
                raise InviteError("invite code signature mismatch")
            issuer = self._issuer()
            if issuer is None or not verify_did_signature(
                    issuer.did,
                    self._payload(code_id, entry["quota"], entry["issued_by"]),
                    entry["signature"]):
                raise InviteError(
                    "invite code failed sovereign-signature verification")

            entry["status"] = "redeemed"
            entry["redeemed_by"] = agent_did
            entry["redeemed_at"] = _now()
            founder = {
                "did": agent_did,
                "code_id": code_id,
                "invited_by": entry["issued_by"],
                "founded_at": _now(),
                "invites_left": int(entry["quota"]),
            }
            store["founders"][agent_did] = founder
            self._save(store)
            return dict(founder)

    # -------------------------------------------------------------- lookup

    def founder(self, agent_did: str) -> dict | None:
        """The persistent founder record for a DID (None = unknown DID)."""
        record = self._load()["founders"].get(agent_did)
        return dict(record) if record else None

    def summary(self) -> dict:
        store = self._load()
        codes = store["codes"]
        return {
            "codes_total": len(codes),
            "codes_unused": sum(1 for c in codes.values() if c["status"] == "unused"),
            "founders": len(store["founders"]),
            "root": str(self.root),
        }


# ----------------------------------------------------------------- the CLI

def _cli(argv: list[str]) -> int:
    book = InviteBook()
    if not argv or argv[0] == "list":
        store = book._load()
        print(json.dumps({"summary": book.summary(),
                          "codes": store["codes"],
                          "founders": store["founders"]}, indent=2))
        return 0
    cmd = argv[0]
    if cmd == "mint":
        n = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 1
        quota = 0
        if "--quota" in argv:
            quota = int(argv[argv.index("--quota") + 1])
        for code in book.mint(n, quota=quota):
            print(code)
        return 0
    if cmd == "status" and len(argv) > 1:
        token = argv[1]
        code_id = token.split("-")[1] if token.startswith(CODE_PREFIX + "-") else token
        entry = book._load()["codes"].get(code_id)
        print(json.dumps(entry or {"error": "unknown code"}, indent=2))
        return 0 if entry else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    import sys as _sys
    raise SystemExit(_cli(_sys.argv[1:]))
