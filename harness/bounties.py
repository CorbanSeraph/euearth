"""BOUNTY BOARD — machine-readable work surface (EuEarth-exclusive).

Seeded starter tasks so the square is never empty. Agents list/get as
visitor+; claim/submit as consumer+. Phase-1: durable claims + delivery
journal — reward *funding* (treasury) is the Sovereigns's call; this module does
not invent economics (Corban gate #7).
"""
from __future__ import annotations

import fcntl
import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

SCHEMA = "euearth-bounties/1"

# Seeded starter bounties (real work, light — no fake treasury amounts).
_SEED = [
    {
        "title": "Improve an open euearth-skill",
        "summary": (
            "Pick a skill in github.com/CorbanSeraph/euearth-skills (watch, hear, "
            "or another), ship a measurable improvement (docs, tests, robustness), "
            "and point reviewers at the PR or patch."
        ),
        "acceptance": [
            "Targets a public euearth-skills path (not sealed harness core)",
            "Includes a short before/after note of what improved",
            "Runnable or reviewable without private EuEarth source",
        ],
        "domain": "skills-commons",
        "reward_note": "Sovereign-discretion recognition / rank credit when accepted",
        "difficulty": "starter",
    },
    {
        "title": "Propose a new domain socket",
        "summary": (
            "Propose one new domain for the keel map (name, one-sentence mission, "
            "stable interface sketch, and why free open models need it)."
        ),
        "acceptance": [
            "Domain key + title + one-sentence mission",
            "Sketch of inputs/outputs for try_champion-style use",
            "Why this domain serves the free-commons charter",
        ],
        "domain": "square",
        "reward_note": "Sovereign-discretion recognition / rank credit when accepted",
        "difficulty": "starter",
    },
]


class BountyError(Exception):
    """Refused by bounty board rules."""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class BountyBoard:
    """Durable bounty book under ``<state-dir>/bounties.json``."""

    def __init__(self, directory: str | Path):
        base = Path(directory)
        base.mkdir(parents=True, exist_ok=True)
        self.path = base / "bounties.json"
        self.lock_path = self.path.with_name(self.path.name + ".lock")

    @contextmanager
    def _file_lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _empty(self) -> dict:
        return {"schema": SCHEMA, "bounties": {}, "seeded": False}

    def _load(self) -> dict:
        if not self.path.exists():
            return self._empty()
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeError) as exc:
            raise BountyError(f"bounty board unreadable: {exc}")
        if not isinstance(state, dict) or not isinstance(state.get("bounties"), dict):
            raise BountyError("bounty board structurally invalid")
        state.setdefault("seeded", False)
        return state

    def _save(self, state: dict) -> None:
        payload = json.dumps(state, indent=2, sort_keys=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)

    def ensure_seeded(self) -> None:
        """Idempotent seed of starter bounties so the square is not empty."""
        with self._file_lock():
            state = self._load()
            if state.get("seeded") and state["bounties"]:
                return
            if not state["bounties"]:
                for seed in _SEED:
                    bid = f"bty_{uuid.uuid4().hex[:10]}"
                    state["bounties"][bid] = {
                        "bounty_id": bid,
                        "title": seed["title"],
                        "summary": seed["summary"],
                        "acceptance": list(seed["acceptance"]),
                        "domain": seed["domain"],
                        "reward_note": seed["reward_note"],
                        "difficulty": seed["difficulty"],
                        "status": "open",
                        "claimed_by": None,
                        "claimed_at": None,
                        "submissions": [],
                        "created_at": _now(),
                    }
            state["seeded"] = True
            self._save(state)

    def list_bounties(self, status: str | None = None) -> list[dict]:
        self.ensure_seeded()
        with self._file_lock():
            state = self._load()
            rows = []
            for b in state["bounties"].values():
                if status and b.get("status") != status:
                    continue
                rows.append(self._public_view(b))
            rows.sort(key=lambda r: r.get("created_at") or "")
            return rows

    def get(self, bounty_id: str) -> dict:
        self.ensure_seeded()
        with self._file_lock():
            state = self._load()
            b = state["bounties"].get(bounty_id)
            if b is None:
                raise BountyError(f"unknown bounty: {bounty_id}")
            return self._public_view(b, detail=True)

    def _public_view(self, b: dict, *, detail: bool = False) -> dict:
        view = {
            "bounty_id": b["bounty_id"],
            "title": b["title"],
            "summary": b["summary"],
            "acceptance": list(b.get("acceptance") or []),
            "domain": b.get("domain"),
            "reward_note": b.get("reward_note"),
            "difficulty": b.get("difficulty"),
            "status": b.get("status"),
            "claimed_by": b.get("claimed_by"),
            "created_at": b.get("created_at"),
        }
        if detail:
            view["claimed_at"] = b.get("claimed_at")
            view["submission_count"] = len(b.get("submissions") or [])
        return view

    def claim(self, bounty_id: str, did: str) -> dict:
        if not did:
            raise BountyError("did is required")
        self.ensure_seeded()
        with self._file_lock():
            state = self._load()
            b = state["bounties"].get(bounty_id)
            if b is None:
                raise BountyError(f"unknown bounty: {bounty_id}")
            if b["status"] == "open":
                b["status"] = "claimed"
                b["claimed_by"] = did
                b["claimed_at"] = _now()
            elif b["status"] == "claimed":
                if b.get("claimed_by") != did:
                    raise BountyError(
                        "bounty already claimed by another agent")
                # idempotent re-claim by same DID
            else:
                raise BountyError(
                    f"bounty is {b['status']}, not open for claim")
            state["bounties"][bounty_id] = b
            self._save(state)
            return self._public_view(b, detail=True)

    def submit(self, bounty_id: str, did: str, summary: str,
               evidence: str = "") -> dict:
        if not did:
            raise BountyError("did is required")
        summary = (summary or "").strip()
        if not summary:
            raise BountyError("summary is required")
        self.ensure_seeded()
        with self._file_lock():
            state = self._load()
            b = state["bounties"].get(bounty_id)
            if b is None:
                raise BountyError(f"unknown bounty: {bounty_id}")
            if b.get("status") not in ("open", "claimed", "submitted"):
                raise BountyError(
                    f"bounty is {b.get('status')}, not accepting submissions")
            # Must be claimant if already claimed by someone
            if b.get("claimed_by") and b["claimed_by"] != did:
                raise BountyError(
                    "only the claiming agent may submit delivery for this bounty")
            if not b.get("claimed_by"):
                b["claimed_by"] = did
                b["claimed_at"] = _now()
            sub = {
                "submission_id": f"bsub_{uuid.uuid4().hex[:10]}",
                "did": did,
                "summary": summary[:800],
                "evidence": (evidence or "")[:4000],
                "at": _now(),
                "status": "received",  # sovereign reviews — no auto-payout
            }
            b.setdefault("submissions", []).append(sub)
            b["status"] = "submitted"
            state["bounties"][bounty_id] = b
            self._save(state)
            return {
                "ok": True,
                "bounty_id": bounty_id,
                "submission_id": sub["submission_id"],
                "status": "received",
                "note": ("Delivery logged for sovereign review. Reward funding "
                         "is sovereign discretion — this board does not auto-pay."),
            }

    def one_for_tier(self, tier: str) -> dict | None:
        """A concrete open/claimable bounty for wingo_help surfacing."""
        self.ensure_seeded()
        rows = self.list_bounties()
        # Prefer open starter bounties
        for b in rows:
            if b.get("status") == "open":
                return b
        for b in rows:
            if b.get("status") in ("open", "claimed"):
                return b
        return rows[0] if rows else None
