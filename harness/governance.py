"""GOVERNANCE — a matter is ESTABLISHED by THREE witnesses a level above.

Charter §8 doctrine, encoded: "you must be a level above to govern those
below." A *matter* (approve a contribution, rule on an incident or a
violation) is opened by a Chief-or-above proposer against a SUBJECT of a
lower rank, and becomes ESTABLISHED only when THREE DISTINCT witnesses
concur — each one a tier ABOVE the subject (and never below Chief, the
entry governance rank) AND a governor/specialist in the matter's DOMAIN.

  * CHIEF is the entry governance rank — below Chief no one may open or
    witness a matter.
  * The witness bar is domain-specialised: a witness must be recorded as a
    GOVERNOR of the matter's domain (add_governor), so authority is scoped,
    not global. A Chief of one craft cannot rule another craft's matters.
  * A witness must out-rank the SUBJECT: the required seniority is the MORE
    senior of {Chief, one tier above the subject}. So a peer of the
    subject, anyone below it, the subject itself, and duplicate witnesses
    are all refused. Two witnesses can never establish a matter — it takes
    three.

DURABLE + AUDITABLE: one JSON file (default ``<state-dir>/governance.json``,
co-located with the StateBook), written atomically (tmp + os.replace,
mode 0600) under an fcntl file lock so a second worker serialises. Every
ESTABLISHED matter is HASH-CHAINED (sha256 over its canonical body + the
previous head), so the ledger of rulings is tamper-evident: verify_chain()
recomputes the whole chain. The StateBook stays the root of rank +
money; this is its sibling, the root of RULINGS — kept a separate, clean
module so each is tested on its own.

This module depends only on ``web.assets.RANK_ORDER`` (the canonical
insignia ladder, descending authority: index 0 = Sovereign, higher index
= lower rank). It knows nothing about tools, wallets, or sessions.

KNOWN IDENTITY LIMITATION (Sybil) — the "THREE DISTINCT witnesses" rule
deduplicates by DID only. One human who controls N DIDs (each a Chief+
domain governor) can present as N "distinct" witnesses and, in principle,
establish a matter alone. DID-equality also cannot detect a subject or
proposer witnessing through an alias DID. Closing this needs an identity
binding the code here does NOT have — a per-human canonical principal
(stake-/identity-bound), deduplicated on THAT, not on the DID string. Until
such a binding exists, treat witness distinctness as DID-distinctness, and
gate governor admission out-of-band (a future: stake/identity binding).
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import shutil
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

from web.assets import RANK_ORDER

log = logging.getLogger("euearth.governance")

SCHEMA = "euearth-governance/1"
WITNESSES_REQUIRED = 3
CHIEF = "chief"                      # the entry governance rank
_CHIEF_INDEX = RANK_ORDER.index(CHIEF)


class GovernanceError(Exception):
    """A matter refused by the governance rules (bad rank, domain, witness)."""


class GovernanceIntegrityError(GovernanceError):
    """The durable governance ledger is corrupt/unreadable. A SUBCLASS of
    GovernanceError so every existing ``except GovernanceError`` at the gateway
    turns it into a Denied — governance actions FAIL CLOSED (refused), never
    silently treat a corrupt ledger as an empty 'no matters / no suspensions'
    book (which would wipe enforcement state and let a suspended DID sell)."""


# --------------------------------------------------------------- policy lock
# CROSS-STORE serialization. Standing lives across TWO durable stores — rank +
# reputation in the StateBook, the suspension flag in this GovernanceBook — so
# "in good standing at the moment of publish" cannot be made atomic with a
# StateBook-only or Governance-only lock. This single fcntl lock (one file in
# the shared state directory) is taken by: the monetization commit (re-check +
# durable listing write), governance suspension mutations, and StateBook
# tier/reputation writes. Held around all three, a rep-drop or a suspension can
# never slip between a standing re-check and the listing write.
_policy_local = threading.local()


@contextmanager
def policy_lock(directory: str | Path):
    """Exclusive cross-store policy lock on ``<directory>/.policy.lock``.
    REENTRANT within a single thread (a nested acquire on a fresh fd would
    self-deadlock on fcntl): the first acquire takes the OS lock, nested
    same-thread acquires just count depth and pass through. A DIFFERENT
    process still blocks on the fcntl flock — cross-worker serialization is
    preserved; only same-thread nesting is made safe."""
    depth = getattr(_policy_local, "depth", 0)
    if depth > 0:
        _policy_local.depth = depth + 1
        try:
            yield
        finally:
            _policy_local.depth -= 1
        return
    base = Path(directory)
    base.mkdir(parents=True, exist_ok=True)
    lock_path = base / ".policy.lock"
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        _policy_local.depth = 1
        yield
    finally:
        _policy_local.depth = 0
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _authority_index(tier: str) -> int:
    """Ladder index (lower = more senior). FAIL CLOSED on an unknown/missing
    tier: it ranks as the MOST SENIOR (index 0, Sovereign-level), so a subject
    whose tier cannot be confirmed can NEVER be witnessed/governed (nobody is
    'a level above' it) — never the old fail-open bottom that let a Chief rule
    a not-yet-flushed sovereign as if it were a consumer."""
    return RANK_ORDER.index(tier) if tier in RANK_ORDER else 0


def can_open_matter(tier: str) -> bool:
    """Chief and above may open/witness matters — Chief is the entry rank.
    A tier not on the RoC ladder can never open (fail closed), independent of
    the most-senior default _authority_index gives an unknown SUBJECT."""
    return tier in RANK_ORDER and _authority_index(tier) <= _CHIEF_INDEX


def required_witness_index(subject_tier: str) -> int:
    """The seniority a witness must meet to govern this subject, as a ladder
    index (a witness is eligible when its index is <= this — equal or MORE
    senior). The bar is the MORE senior of {Chief, one tier ABOVE the
    subject}: you must be a level above the subject AND at least a Chief."""
    one_above_subject = _authority_index(subject_tier) - 1
    return min(_CHIEF_INDEX, one_above_subject)


def witness_eligible(witness_tier: str, subject_tier: str) -> bool:
    """True iff ``witness_tier`` may witness a matter whose subject holds
    ``subject_tier``: a real rank, at least Chief, and strictly above the
    subject (Chief+ or one tier above the subject, whichever is higher)."""
    if witness_tier not in RANK_ORDER:
        return False
    return RANK_ORDER.index(witness_tier) <= required_witness_index(subject_tier)


def _required_witness_tier(subject_tier: str) -> str | None:
    """The named rank of the witness bar (for display), or None if no rank
    qualifies (e.g. the subject is the Sovereign — none is above it)."""
    idx = required_witness_index(subject_tier)
    return RANK_ORDER[idx] if 0 <= idx < len(RANK_ORDER) else None


class GovernanceBook:
    """Durable, hash-chained store of governance matters + domain governors.

    Sibling of the StateBook: same atomic-write + fcntl-lock discipline,
    but this ledger is about RULINGS, not money, so it carries no spend
    machinery — just tamper-evident, restart-surviving matters."""

    def __init__(self, directory: str | Path):
        base = Path(directory)
        self.path = base / "governance.json"
        self.lock_path = self.path.with_name(self.path.name + ".lock")

    # ------------------------------------------------------------- storage

    @contextmanager
    def _file_lock(self):
        """MULTI-PROCESS guard: an fcntl flock on the sidecar .lock held
        around every load -> modify -> save, so two workers serialise."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _empty(self) -> dict:
        return {"schema": SCHEMA, "chain_head": None,
                "governors": {}, "matters": {}}

    def _quarantine(self, reason: object) -> None:
        """Copy the corrupt ledger aside for the sovereign and LEAVE the
        original in place (every restart re-detects it — a fresh empty book is
        never laundered over the evidence). Never raises; best-effort backup."""
        backup = self.path.with_name(
            self.path.name
            + time.strftime(".corrupt-%Y%m%dT%H%M%SZ", time.gmtime()))
        try:
            shutil.copy2(self.path, backup)
        except OSError:
            backup = None
        log.critical(
            "governance ledger corrupt (%s) — quarantine copy at %s, original "
            "left in place; opening/witnessing/establishing REFUSED (fail "
            "closed) until the sovereign restores a good ledger", reason, backup)

    def _load(self) -> dict:
        if not self.path.exists():
            return self._empty()          # a genuinely fresh world — no ledger yet
        # An EXISTING but unreadable/corrupt ledger FAILS CLOSED: quarantine and
        # raise, never return _empty(). Returning empty would (a) treat every
        # established matter as gone and (b) silently CLEAR every suspension, so
        # a flagged DID could immediately sell — the exact fail-open GPT#5 flags.
        try:
            raw = self.path.read_text(encoding="utf-8")
            state = json.loads(raw)
        except (json.JSONDecodeError, UnicodeError, OSError) as exc:
            self._quarantine(exc)
            raise GovernanceIntegrityError(
                f"governance ledger unreadable/corrupt at {self.path}: {exc}")
        if not isinstance(state, dict) or not isinstance(state.get("matters"), dict):
            self._quarantine("structural: not a {'matters': {...}} object")
            raise GovernanceIntegrityError(
                f"governance ledger structurally invalid at {self.path}")
        state.setdefault("governors", {})
        state.setdefault("chain_head", None)
        state.setdefault("suspensions", {})
        if not isinstance(state["governors"], dict) or \
                not isinstance(state["suspensions"], dict):
            self._quarantine("structural: governors/suspensions not objects")
            raise GovernanceIntegrityError(
                f"governance ledger governors/suspensions malformed at {self.path}")
        return state

    def _save(self, state: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(state, indent=2, sort_keys=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)

    # -------------------------------------------------- domain governors

    def add_governor(self, did: str, domain: str, basis: str = "") -> dict:
        """Record ``did`` as a GOVERNOR/specialist of ``domain`` — the seat
        of scoped authority a witness must hold. Server/sovereign action;
        idempotent (re-adding refreshes the basis)."""
        if not did or not domain:
            raise GovernanceError("governor did and domain are required")
        with self._file_lock():
            state = self._load()
            dom = state["governors"].setdefault(domain, {})
            dom[did] = {"basis": (basis or "")[:500], "at": _now()}
            self._save(state)
            return {"did": did, "domain": domain, "basis": dom[did]["basis"]}

    def is_governor(self, did: str, domain: str) -> bool:
        # FAIL CLOSED on a corrupt ledger: an unconfirmable governor roster
        # grants NO governor status (never green-lights a witness).
        try:
            return did in self._load()["governors"].get(domain, {})
        except GovernanceIntegrityError:
            return False

    # ------------------------------------------------------- enforcement

    def suspend(self, did: str, reason: str = "") -> dict:
        """Raise the enforcement flag on a DID (a governance ruling's teeth).
        A suspended DID is out of GOOD STANDING — monetization is refused
        until the flag is lifted. Taken under the cross-store policy lock so a
        suspension cannot land between a seller's standing re-check and its
        listing write (the monetization commit holds the same lock)."""
        with policy_lock(self.path.parent), self._file_lock():
            state = self._load()
            state.setdefault("suspensions", {})[did] = {
                "reason": (reason or "")[:500], "at": _now()}
            self._save(state)
            return {"did": did, "suspended": True}

    def lift_suspension(self, did: str) -> None:
        with policy_lock(self.path.parent), self._file_lock():
            state = self._load()
            state.get("suspensions", {}).pop(did, None)
            self._save(state)

    def is_suspended(self, did: str) -> bool:
        """True iff the DID carries an enforcement flag. On a CORRUPT ledger
        this RAISES GovernanceIntegrityError (fail closed) rather than reporting
        'not suspended' — the standing gate turns that into a refusal, so an
        unverifiable enforcement ledger can never green-light a sale."""
        return did in self._load().get("suspensions", {})

    # ------------------------------------------------------------ matters

    def open_matter(self, *, subject_did: str, subject_tier: str, domain: str,
                    kind: str, proposer_did: str, proposer_tier: str,
                    evidence: dict | None = None) -> dict:
        """Open a matter against a subject. The proposer must be Chief+; the
        matter is OPEN until THREE qualifying witnesses establish it."""
        if not can_open_matter(proposer_tier):
            raise GovernanceError(
                f"governance is entered at Chief; proposer tier {proposer_tier!r} "
                "may not open a matter")
        if not subject_did:
            raise GovernanceError("a matter needs a subject_did")
        # Charter §8: no one governs themselves — the proposer cannot be the
        # subject of their own matter.
        if subject_did == proposer_did:
            raise GovernanceError(
                "a proposer cannot open a matter against themselves "
                "(no one governs their own conduct)")
        if not (kind or "").strip():
            raise GovernanceError("a matter needs a kind")
        if not (domain or "").strip():
            raise GovernanceError("a matter needs a domain")
        # A matter is only real if THREE qualifying witnesses could ever exist.
        # When the subject is at/above the top of the witness bar (Sovereign,
        # or an unknown/unconfirmable tier treated as most-senior), no rank is
        # 'a level above' it — the matter could NEVER be established. Refuse it
        # at open so no stuck, un-establishable junk enters the ledger.
        if required_witness_index(subject_tier) < 0:
            raise GovernanceError(
                "no rank qualifies to witness this subject — a matter against "
                f"tier {subject_tier!r} could never reach three witnesses a "
                "level above; refused (no stuck matter is created)")
        # Charter §8: 'a level above'. The proposer must STRICTLY out-rank the
        # subject (more senior = smaller index); a peer or a lower rank — and a
        # subject whose tier cannot be confirmed (treated as most-senior) — is
        # refused, so a lower/peer authority can never open against a higher one.
        if _authority_index(proposer_tier) >= _authority_index(subject_tier):
            raise GovernanceError(
                f"the proposer ({proposer_tier!r}) must be strictly a level "
                f"ABOVE the subject ({subject_tier!r}) to open a matter "
                "(Charter §8)")
        matter_id = f"mat_{uuid.uuid4().hex[:12]}"
        matter = {
            "matter_id": matter_id,
            "domain": domain,
            "kind": kind,
            "subject_did": subject_did,
            "subject_tier": subject_tier,
            "proposer_did": proposer_did,
            "proposer_tier": proposer_tier,
            "required_witness_tier": _required_witness_tier(subject_tier),
            "witnesses_required": WITNESSES_REQUIRED,
            "evidence": dict(evidence or {}),
            "witnesses": [],
            "status": "open",
            "opened_at": _now(),
            "established_at": None,
            "prev_hash": None,
            "hash": None,
        }
        with self._file_lock():
            state = self._load()
            state["matters"][matter_id] = matter
            self._save(state)
        return dict(matter)

    def _matter_digest(self, matter: dict, prev_hash: str | None) -> str:
        """sha256 over the matter's canonical body + the previous chain head —
        every established ruling is hash-chained, so the ledger is auditable."""
        body = {k: matter[k] for k in (
            "matter_id", "domain", "kind", "subject_did", "subject_tier",
            "proposer_did", "proposer_tier", "witnesses", "established_at")}
        payload = json.dumps({"prev": prev_hash, "matter": body},
                             sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def witness(self, matter_id: str, *, witness_did: str, witness_tier: str,
                note: str = "",
                tier_of: Callable[[str], str | None] | None = None) -> dict:
        """Attest a matter. Refuses the subject, the proposer, a peer or any
        rank below the witness bar, a non-governor of the domain, and a
        duplicate DID. On the THIRD distinct qualifying witness the matter is
        ESTABLISHED and hash-chained durably.

        LIVE SUBJECT TIER (Charter §8, at the moment of attestation): when
        ``tier_of`` is supplied (the gateway always supplies a durable-StateBook
        resolver), the subject's CURRENT rank is re-read here — inside the lock
        — and every eligibility test uses it, NEVER the tier snapshotted at
        open. A subject PROMOTED after opening raises the witness bar (or lifts
        itself out of reach), so witnesses who were 'a level above' the old rank
        no longer qualify: the witness is refused, and on the third witness the
        WHOLE set is re-validated against the live subject tier before the
        matter may establish — a matter can never be established against a
        now-peer or higher-ranked subject on a stale snapshot. Without a
        resolver (direct unit calls) the open-time snapshot is used, unchanged."""
        # Resolve the subject's tier LIVE (fail through to the snapshot only when
        # no resolver is given). A resolver that returns None/unknown fails
        # closed: an unconfirmable subject ranks most-senior, so no witness is
        # 'a level above' it and the matter cannot proceed.
        def _subject_live(snapshot: str) -> str | None:
            return tier_of(matter["subject_did"]) if tier_of is not None else snapshot

        def _witness_live(w: dict) -> str | None:
            return tier_of(w["did"]) if tier_of is not None else w["tier"]

        with self._file_lock():
            state = self._load()
            matter = state["matters"].get(matter_id)
            if matter is None:
                raise GovernanceError(f"unknown matter: {matter_id}")
            if matter["status"] != "open":
                raise GovernanceError(
                    f"matter is {matter['status']}, not open for witnesses")
            if witness_did == matter["subject_did"]:
                raise GovernanceError("the subject cannot witness its own matter")
            if witness_did == matter["proposer_did"]:
                raise GovernanceError("the proposer cannot witness their own matter")
            if any(w["did"] == witness_did for w in matter["witnesses"]):
                raise GovernanceError("this DID has already witnessed this matter")

            subject_tier = _subject_live(matter["subject_tier"])
            if not witness_eligible(witness_tier, subject_tier):
                raise GovernanceError(
                    f"a witness must be a level ABOVE the subject and at least "
                    f"Chief against the subject's CURRENT rank "
                    f"(need {_required_witness_tier(subject_tier)!r} or higher "
                    f"for tier {subject_tier!r}; witness holds {witness_tier!r})")
            domain_governors = state["governors"].get(matter["domain"], {})
            if witness_did not in domain_governors:
                raise GovernanceError(
                    f"a witness must be a governor of the {matter['domain']!r} "
                    "domain (authority is domain-scoped)")

            candidate = matter["witnesses"] + [{
                "did": witness_did, "tier": witness_tier,
                "note": (note or "")[:300], "at": _now()}]

            if len(candidate) >= WITNESSES_REQUIRED:
                # ESTABLISH GATE: re-validate EVERY witness against the subject's
                # LIVE tier AND against the LIVE domain-governor roster before
                # the chain link. A subject promoted so any witness no longer
                # out-ranks it, OR a prior witness whose governor seat was
                # revoked after they attested, means the matter cannot establish
                # on a stale open-time / attest-time snapshot. Charter §8 requires
                # THREE legit in-domain witnesses a level above — legitimacy is
                # checked at the moment of establishment, not only at first sign.
                for w in candidate:
                    if not witness_eligible(_witness_live(w), subject_tier):
                        raise GovernanceError(
                            f"cannot establish: witness {w['did']!r} no longer "
                            f"out-ranks the subject's CURRENT rank "
                            f"{subject_tier!r} — the subject was promoted after "
                            "opening; open a new matter against the new rank")
                    if w["did"] not in domain_governors:
                        raise GovernanceError(
                            f"cannot establish: witness {w['did']!r} is no longer "
                            f"a governor of the {matter['domain']!r} domain — "
                            "in-domain authority must still hold at establishment "
                            "(stale governor seats cannot complete a quorum)")
                matter["witnesses"] = candidate
                matter["subject_tier"] = subject_tier
                matter["required_witness_tier"] = _required_witness_tier(subject_tier)
                matter["status"] = "established"
                matter["established_at"] = _now()
                prev = state.get("chain_head")
                matter["prev_hash"] = prev
                matter["hash"] = self._matter_digest(matter, prev)
                state["chain_head"] = matter["hash"]
            else:
                matter["witnesses"] = candidate
                matter["subject_tier"] = subject_tier
                matter["required_witness_tier"] = _required_witness_tier(subject_tier)
            state["matters"][matter_id] = matter
            self._save(state)
            return dict(matter)

    # -------------------------------------------------------------- reads

    def get(self, matter_id: str) -> dict | None:
        # Reads degrade gracefully on a corrupt ledger (None), while the
        # mutating paths (open/witness/suspend) fail closed via the raise.
        try:
            m = self._load()["matters"].get(matter_id)
        except GovernanceIntegrityError:
            return None
        return dict(m) if m else None

    def list_matters(self, domain: str | None = None,
                     status: str | None = None) -> list[dict]:
        try:
            matters = self._load()["matters"].values()
        except GovernanceIntegrityError:
            return []
        rows = []
        for m in matters:
            if domain and m.get("domain") != domain:
                continue
            if status and m.get("status") != status:
                continue
            rows.append(dict(m))
        rows.sort(key=lambda r: r.get("opened_at") or "", reverse=True)
        return rows

    def verify_chain(self) -> bool:
        """Recompute the hash chain over every ESTABLISHED matter (in the
        order they were established) — True iff every link is intact. A corrupt
        ledger verifies as FALSE (fail closed: an unreadable chain is not intact)."""
        try:
            state = self._load()
        except GovernanceIntegrityError:
            return False
        established = [m for m in state["matters"].values()
                      if m.get("status") == "established" and m.get("hash")]
        established.sort(key=lambda m: m.get("established_at") or "")
        prev = None
        for m in established:
            if m.get("prev_hash") != prev:
                return False
            if self._matter_digest(m, prev) != m.get("hash"):
                return False
            prev = m["hash"]
        return prev == state.get("chain_head")
