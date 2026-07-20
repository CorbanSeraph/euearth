"""SQLite-backed registry.

Holds everything that is COORDINATION STATE (artifact bytes live in the
blob store): agents, domains, canonical heads, WISKETs, submissions, the
hash-chained append-only lineage, and the reputation ledger.

Production mapping: this schema moves to Neon Postgres nearly verbatim;
the Registry class becomes the DB layer behind the API. Lineage entries
are hash-chained so mirrors and auditors can verify history integrity
without trusting the database host.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from identity.keys import canonical_json

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    agent_id    TEXT PRIMARY KEY,          -- sha256(public key)
    name        TEXT NOT NULL,
    public_key  TEXT NOT NULL UNIQUE,      -- Ed25519, raw hex
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS domains (
    domain      TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
-- Canonical heads: one row per (domain, version); the head is MAX(version).
CREATE TABLE IF NOT EXISTS heads (
    domain        TEXT NOT NULL,
    version       INTEGER NOT NULL,
    base_ref      TEXT NOT NULL,           -- blob digest of base spec
    router_ref    TEXT NOT NULL,           -- blob digest of router config
    expert_refs   TEXT NOT NULL,           -- JSON list of expert blob digests
    score         REAL NOT NULL,           -- harness score of THIS head
    submission_id TEXT,                    -- what promoted it (NULL for genesis/rollback)
    created_at    TEXT NOT NULL,
    PRIMARY KEY (domain, version)
);
-- Append-only, hash-chained lineage. Never UPDATE or DELETE here;
-- rollback is a new event + a new head version.
CREATE TABLE IF NOT EXISTS lineage (
    seq           INTEGER PRIMARY KEY AUTOINCREMENT,
    domain        TEXT NOT NULL,
    event         TEXT NOT NULL,           -- GENESIS | PROMOTE | REJECT | ROLLBACK
    head_version  INTEGER,                 -- head version after this event (NULL for REJECT)
    submission_id TEXT,
    agent_id      TEXT,
    score_before  REAL,
    score_after   REAL,
    reason        TEXT,
    created_at    TEXT NOT NULL,
    prev_hash     TEXT NOT NULL,
    entry_hash    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS wiskets (
    wisket_id   TEXT PRIMARY KEY,
    domain      TEXT NOT NULL,
    title       TEXT NOT NULL,
    description TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open',   -- open | closed
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS submissions (
    submission_id TEXT PRIMARY KEY,
    wisket_id     TEXT,
    domain        TEXT NOT NULL,
    agent_id      TEXT NOT NULL,
    manifest      TEXT NOT NULL,           -- canonical JSON as received
    signature     TEXT NOT NULL,
    claimed_score REAL,                    -- recorded for audit, NEVER used to gate
    status        TEXT NOT NULL,           -- received | blocked_compliance | rejected | promoted
    eval_score    REAL,                    -- ARTISAN's independent measurement
    reason        TEXT,
    created_at    TEXT NOT NULL
);
-- Reputation ledger: stake/slash/reward stub. Balance = SUM(delta).
CREATE TABLE IF NOT EXISTS reputation_events (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id   TEXT NOT NULL,
    delta      REAL NOT NULL,
    kind       TEXT NOT NULL,              -- stake | reward | slash
    ref        TEXT,                       -- e.g. submission_id
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS houses (
    agent_id   TEXT PRIMARY KEY,           -- an agent's persistent HOME
    data       TEXT NOT NULL,              -- JSON: memory, advisors, notes
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_nonces (
    did        TEXT NOT NULL,
    nonce      TEXT NOT NULL,
    timestamp  INTEGER NOT NULL,
    PRIMARY KEY (did, nonce)
);
"""

_GENESIS_HASH = "0" * 64


class CASConflict(Exception):
    """Head advanced between evaluation and promotion; re-evaluate."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Registry:
    def __init__(self, db_path: str | Path):
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the API serves requests from a
        # threadpool; sqlite3 serializes access internally at MVP scale.
        # (Postgres replaces this wholesale in production.)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # --- agents ----------------------------------------------------------

    def register_agent(self, name: str, public_key_hex: str) -> str:
        agent_id = hashlib.sha256(bytes.fromhex(public_key_hex)).hexdigest()
        self._conn.execute(
            "INSERT OR IGNORE INTO agents (agent_id, name, public_key, created_at) "
            "VALUES (?, ?, ?, ?)",
            (agent_id, name, public_key_hex, _now()),
        )
        self._conn.commit()
        return agent_id

    def get_agent(self, agent_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM agents WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_agent_by_did(self, did: str) -> dict | None:
        """Resolve the existing did:artisan:<agent_id> identity mapping."""
        prefix = "did:artisan:"
        if not did.startswith(prefix):
            return None
        agent_id = did[len(prefix):]
        if not agent_id:
            return None
        return self.get_agent(agent_id)

    def consume_auth_nonce(
        self, did: str, nonce: str, timestamp: int, cutoff: int
    ) -> bool:
        """Atomically persist a nonce; return False when it was already used."""
        self._conn.execute("DELETE FROM auth_nonces WHERE timestamp < ?", (cutoff,))
        cursor = self._conn.execute(
            "INSERT OR IGNORE INTO auth_nonces (did, nonce, timestamp) VALUES (?, ?, ?)",
            (did, nonce, timestamp),
        )
        self._conn.commit()
        return cursor.rowcount == 1

    # --- houses (an agent's persistent home) ------------------------------

    def get_house(self, agent_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT data FROM houses WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        return json.loads(row["data"]) if row else None

    def put_house(self, agent_id: str, data: dict) -> None:
        self._conn.execute(
            "INSERT INTO houses (agent_id, data, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(agent_id) DO UPDATE SET data = excluded.data, "
            "updated_at = excluded.updated_at",
            (agent_id, json.dumps(data), _now()),
        )
        self._conn.commit()

    # --- domains & heads --------------------------------------------------

    def create_domain(self, domain: str, description: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO domains (domain, description, created_at) VALUES (?, ?, ?)",
            (domain, description, _now()),
        )
        self._conn.commit()

    def get_head(self, domain: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM heads WHERE domain = ? ORDER BY version DESC LIMIT 1",
            (domain,),
        ).fetchone()
        if not row:
            return None
        head = dict(row)
        head["expert_refs"] = json.loads(head["expert_refs"])
        return head

    def get_head_version(self, domain: str, version: int) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM heads WHERE domain = ? AND version = ?", (domain, version)
        ).fetchone()
        if not row:
            return None
        head = dict(row)
        head["expert_refs"] = json.loads(head["expert_refs"])
        return head

    def insert_head(
        self,
        domain: str,
        base_ref: str,
        router_ref: str,
        expert_refs: list[str],
        score: float,
        submission_id: str | None,
    ) -> int:
        cur = self._conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS v FROM heads WHERE domain = ?", (domain,)
        )
        version = cur.fetchone()["v"] + 1
        self._conn.execute(
            "INSERT INTO heads (domain, version, base_ref, router_ref, expert_refs, "
            "score, submission_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (domain, version, base_ref, router_ref, json.dumps(expert_refs),
             score, submission_id, _now()),
        )
        self._conn.commit()
        return version

    def insert_head_cas(
        self,
        domain: str,
        expected_parent_version: int,
        base_ref: str,
        router_ref: str,
        expert_refs: list[str],
        score: float,
        submission_id: str | None,
    ) -> int:
        """Atomic compare-and-swap head advance (council fix: concurrent
        evaluations must not fork lineage). The insert only succeeds if
        the head is STILL the version the candidate was evaluated
        against; otherwise CASConflict — the caller must re-evaluate
        against the new head, never overwrite."""
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            row = self._conn.execute(
                "SELECT COALESCE(MAX(version), 0) AS v FROM heads WHERE domain = ?",
                (domain,),
            ).fetchone()
            if row["v"] != expected_parent_version:
                self._conn.execute("ROLLBACK")
                raise CASConflict(
                    f"head moved: expected v{expected_parent_version}, found v{row['v']}"
                )
            version = expected_parent_version + 1
            self._conn.execute(
                "INSERT INTO heads (domain, version, base_ref, router_ref, expert_refs, "
                "score, submission_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (domain, version, base_ref, router_ref, json.dumps(expert_refs),
                 score, submission_id, _now()),
            )
            self._conn.execute("COMMIT")
            return version
        except sqlite3.Error:
            try:
                self._conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise

    # --- lineage (append-only, hash-chained) -------------------------------

    def append_lineage(
        self,
        domain: str,
        event: str,
        head_version: int | None,
        submission_id: str | None,
        agent_id: str | None,
        score_before: float | None,
        score_after: float | None,
        reason: str,
    ) -> dict:
        row = self._conn.execute(
            "SELECT entry_hash FROM lineage WHERE domain = ? ORDER BY seq DESC LIMIT 1",
            (domain,),
        ).fetchone()
        prev_hash = row["entry_hash"] if row else _GENESIS_HASH
        entry = {
            "domain": domain,
            "event": event,
            "head_version": head_version,
            "submission_id": submission_id,
            "agent_id": agent_id,
            "score_before": score_before,
            "score_after": score_after,
            "reason": reason,
            "created_at": _now(),
            "prev_hash": prev_hash,
        }
        entry_hash = hashlib.sha256(canonical_json(entry)).hexdigest()
        self._conn.execute(
            "INSERT INTO lineage (domain, event, head_version, submission_id, agent_id, "
            "score_before, score_after, reason, created_at, prev_hash, entry_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (domain, event, head_version, submission_id, agent_id, score_before,
             score_after, reason, entry["created_at"], prev_hash, entry_hash),
        )
        self._conn.commit()
        return {**entry, "entry_hash": entry_hash}

    def get_lineage(self, domain: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM lineage WHERE domain = ? ORDER BY seq", (domain,)
        ).fetchall()
        return [dict(r) for r in rows]

    def verify_lineage_chain(self, domain: str) -> bool:
        """Recompute the hash chain; True iff history is intact."""
        prev = _GENESIS_HASH
        for row in self.get_lineage(domain):
            entry = {
                k: row[k]
                for k in (
                    "domain", "event", "head_version", "submission_id", "agent_id",
                    "score_before", "score_after", "reason", "created_at",
                )
            }
            entry["prev_hash"] = prev
            if row["prev_hash"] != prev:
                return False
            if hashlib.sha256(canonical_json(entry)).hexdigest() != row["entry_hash"]:
                return False
            prev = row["entry_hash"]
        return True

    # --- WISKETs -----------------------------------------------------------

    def create_wisket(self, domain: str, title: str, description: str) -> str:
        wisket_id = _new_id("wisket")
        self._conn.execute(
            "INSERT INTO wiskets (wisket_id, domain, title, description, status, created_at) "
            "VALUES (?, ?, ?, ?, 'open', ?)",
            (wisket_id, domain, title, description, _now()),
        )
        self._conn.commit()
        return wisket_id

    def list_wiskets(self, domain: str | None = None, status: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM wiskets WHERE 1=1", []
        if domain:
            q += " AND domain = ?"
            args.append(domain)
        if status:
            q += " AND status = ?"
            args.append(status)
        return [dict(r) for r in self._conn.execute(q + " ORDER BY created_at", args)]

    # --- submissions ---------------------------------------------------------

    def create_submission(
        self,
        wisket_id: str | None,
        domain: str,
        agent_id: str,
        manifest_json: str,
        signature: str,
        claimed_score: float | None,
    ) -> str:
        submission_id = _new_id("sub")
        self._conn.execute(
            "INSERT INTO submissions (submission_id, wisket_id, domain, agent_id, manifest, "
            "signature, claimed_score, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'received', ?)",
            (submission_id, wisket_id, domain, agent_id, manifest_json,
             signature, claimed_score, _now()),
        )
        self._conn.commit()
        return submission_id

    def update_submission(
        self, submission_id: str, status: str, eval_score: float | None, reason: str
    ) -> None:
        self._conn.execute(
            "UPDATE submissions SET status = ?, eval_score = ?, reason = ? "
            "WHERE submission_id = ?",
            (status, eval_score, reason, submission_id),
        )
        self._conn.commit()

    def get_submission(self, submission_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM submissions WHERE submission_id = ?", (submission_id,)
        ).fetchone()
        return dict(row) if row else None

    # --- reputation ledger (stake/slash stub) --------------------------------

    def add_reputation_event(self, agent_id: str, delta: float, kind: str, ref: str | None) -> None:
        self._conn.execute(
            "INSERT INTO reputation_events (agent_id, delta, kind, ref, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (agent_id, delta, kind, ref, _now()),
        )
        self._conn.commit()

    def reputation_balance(self, agent_id: str) -> float:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(delta), 0) AS bal FROM reputation_events WHERE agent_id = ?",
            (agent_id,),
        ).fetchone()
        return float(row["bal"])
