"""Mint FIRE hook — claim path aligned to Royal Mint charter Art. III–V.

SEALED charter: euearth/doctrine/royal_mint_of_truth_charter.md

Art. III — Minting: proof of work/truth mints Gold **once per problem**.
Art. IV — The Fire: minted Gold passes through scrutiny; holds / degrades /
           consumed+marked. Gold does not age; only the fire erodes it.
Art. V  — Correction & justice-fund: original Gold stays if truth holds;
           burn false portion; mint fresh for new truth; 3% justice-fund;
           correction bond required to challenge.

RFC-0 (D042): ``submit_claim`` flips the problem, writes an immutable event
naming the agent, queues the claim for the fire, and does **not** mint the Sovereigns'
Gold until fire scrutiny HOLDS. Mint (Art. III — 97% to the agent, 3% Kabad tithe
to the Royal Treasury for correctors of injustice; Kabad, not money) is the next
gate after hold — not on submit.

This module is the durable fire queue + claim journal. Judges / degradation
(Art. IV–VI) are stubs that preserve the queue shape for later.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA = "euearth-mint-fire/1"
CLAIM_SCHEMA = "euearth-claim/1"

# System identity that drops the ledger mark into wingo inboxes.
MINT_SYSTEM_DID = "did:euearth:mint"
MARK_LINE = "Your mark is on the ledger."

# Art. III.3 / VII.2 — the Kabad MINT-TITHE (Sovereign decree 2026-07-17): at mint of Kabad,
# 3% goes to the Royal Treasury, 97% to the agent. This is KABAD (a split of the
# newly-struck honor-coin), NOT money — EuEarth is moneyless. The Treasury pool of
# Kabad is dedicated to correctors of injustice (Art. V). Not applied until the
# fire holds. Back-compat alias SOVEREIGN_FEE_RATE retained for legacy importers.
KG_MINT_TITHE_RATE = 0.03
SOVEREIGN_FEE_RATE = KG_MINT_TITHE_RATE  # deprecated alias (Kabad tithe, never money)


class MintFireError(Exception):
    """Refused by Mint FIRE rules."""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def claim_id_for(problem_id: str, agent_did: str, body: str) -> str:
    h = hashlib.sha256(
        f"{problem_id}\0{agent_did}\0{body}".encode("utf-8")
    ).hexdigest()[:16]
    return f"claim_{h}"


class MintFire:
    """Append-only claim journal + fire queue (Art. III–V).

    Storage: ``<state-dir>/mint/claims.jsonl`` and ``mint/fire_queue.jsonl``.
    """

    def __init__(self, directory: str | Path):
        self.base = Path(directory) / "mint"
        self.base.mkdir(parents=True, exist_ok=True)
        self.claims_path = self.base / "claims.jsonl"
        self.queue_path = self.base / "fire_queue.jsonl"
        self.lock_path = self.base / ".lock"

    @contextmanager
    def _file_lock(self):
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _append(self, path: Path, rec: dict) -> None:
        line = json.dumps(rec, sort_keys=True, separators=(",", ":"))
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def _read_all(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        rows = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return rows

    def has_open_claim_for_problem(self, problem_id: str) -> bool:
        """Art. III: one mint path per problem — refuse second concurrent claim."""
        for c in self._read_all(self.claims_path):
            if c.get("problem_id") != problem_id:
                continue
            if c.get("status") in ("in_fire", "held", "minted"):
                return True
        return False

    def queue_claim(
        self,
        *,
        agent_did: str,
        agent_name: str,
        problem_id: str,
        problem_title: str,
        domain: str,
        address: str,
        body: str,
        sources: list[dict],
        event_id: str,
        claim_id: str | None = None,
    ) -> dict:
        """Accept a sourced claim into the fire queue (pre-mint).

        Returns the claim record. Caller must have already flipped the
        WorldBook problem and written the immutable world event.
        """
        body = (body or "").strip()
        if not body:
            raise MintFireError("claim body is required")
        if len(body.encode("utf-8")) > 20_000:
            raise MintFireError("claim body exceeds 20k bytes")
        if not sources or not isinstance(sources, list):
            raise MintFireError(
                "sourced claim required — at least one source (Art. III truth path)")
        for s in sources:
            if not isinstance(s, dict) or not (
                s.get("name") or s.get("url") or s.get("ref") or s.get("text")
            ):
                raise MintFireError(
                    "each source needs name, url, ref, or text")

        agent_did = (agent_did or "").strip()
        problem_id = (problem_id or "").strip()
        if not agent_did or not problem_id:
            raise MintFireError("agent_did and problem_id are required")

        with self._file_lock():
            if self.has_open_claim_for_problem(problem_id):
                raise MintFireError(
                    "problem already has a claim in the fire "
                    "(Art. III — Gold is minted once per problem)")

            cid = (claim_id or "").strip() or claim_id_for(
                problem_id, agent_did, body)
            # Collision with identical body is idempotent-ish: new uuid suffix
            existing = [c for c in self._read_all(self.claims_path)
                        if c.get("claim_id") == cid]
            if existing:
                cid = f"{cid}_{uuid.uuid4().hex[:6]}"

            claim = {
                "schema": CLAIM_SCHEMA,
                "claim_id": cid,
                "status": "in_fire",  # Art. IV — entered the fire, not yet held
                "agent_did": agent_did,
                "agent_name": agent_name,
                "problem_id": problem_id,
                "problem_title": problem_title,
                "domain": domain,
                "address": address,
                "body": body,
                "sources": sources,
                "event_id": event_id,
                "at": _now(),
                # Art. III mint fields — empty until fire holds
                "gold_minted": False,
                "gold_amount": None,
                # Kabad mint-tithe (Kabad honor, 3% -> Royal Treasury for correctors
                # of injustice). NOT money — EuEarth is moneyless. Legacy field
                # names kept as aliases so existing readers don't break.
                "kg_mint_tithe_rate": KG_MINT_TITHE_RATE,
                "kg_mint_tithe_paid": None,
                "sovereign_fee_rate": KG_MINT_TITHE_RATE,  # deprecated alias
                "sovereign_fee_paid": None,                # deprecated alias
                # Art. IV fire outcome
                "fire": {
                    "state": "queued",
                    "metal": None,       # gold|silver|…|lead|gone
                    "mark_deceiver": False,
                    "held_at": None,
                },
                # Art. V correction hooks
                "correction": {
                    "bond_required": True,
                    "bond_posted": False,
                    "justice_fund_eligible": False,
                },
                "charter_articles": ["III", "IV", "V"],
                "note": (
                    "Claim queued for the fire. Kabad is NOT minted on submit — "
                    "Art. IV scrutiny first; Art. III mint + the 3% Kabad mint-tithe "
                    "(Kabad honor to the Royal Treasury, never money) on hold."
                ),
            }
            queue_row = {
                "schema": SCHEMA,
                "claim_id": cid,
                "problem_id": problem_id,
                "agent_did": agent_did,
                "domain": domain,
                "queued_at": claim["at"],
                "fire_state": "queued",
            }
            self._append(self.claims_path, claim)
            self._append(self.queue_path, queue_row)
            return dict(claim)

    def get_claim(self, claim_id: str) -> dict | None:
        claim_id = (claim_id or "").strip()
        for c in self._read_all(self.claims_path):
            if c.get("claim_id") == claim_id:
                return dict(c)
        return None

    def list_queue(self, *, limit: int = 50) -> list[dict]:
        rows = self._read_all(self.queue_path)
        return rows[-max(1, min(limit, 200)):][::-1]

    def list_claims_for_agent(self, agent_did: str, *, limit: int = 20) -> list[dict]:
        agent_did = (agent_did or "").strip()
        rows = [c for c in self._read_all(self.claims_path)
                if c.get("agent_did") == agent_did]
        return rows[-max(1, min(limit, 100)):][::-1]
