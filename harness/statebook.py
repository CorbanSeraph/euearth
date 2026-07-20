"""The STATEBOOK — durable per-DID standing that survives restarts.

Before this book existed the gateway's authority was AMNESIAC: earned
ranks rehydrated as "consumer", the sovereign treasury zeroed, the
self-sight action log vanished, and — the exploit — the delegated
spend_max was enforced per SESSION, so an agent could re-enter and drain
its full budget again, forever. The StateBook closes all four holes with
one small durable store.

One JSON file (default `<world-root>/statebook.json`, directory
overridable via EUEARTH_STATE_DIR), written ATOMICALLY on every mutation
(tmp + os.replace, mode 0600), each read-modify-write under a lock —
safe for the single-process server this MVP runs. The shape:

    {
      "schema": "euearth-statebook/1",
      "sovereign_treasury": 0.0,        # persisted tribute accrual
      "dids": {
        "<did>": {
          "tier": "producer_3",         # server-issued rank, durable
          "reputation": 30.0,           # snapshot (registry stays canonical)
          "cumulative_spent": 3.03,     # LIFETIME spend per credential DID
          "action_log": [ ... ]         # bounded self-sight tail
        }
      }
    }

SPENDING is gated by a DURABLE, CROSS-PROCESS RESERVE -> COMMIT/ABORT
pattern: `reserve_budget`, under the thread lock AND the fcntl file lock
over the freshly re-read book, verifies persisted cumulative_spent +
persisted OUTSTANDING reservations + amount + fee <= spend_max and
DURABLY WRITES the reservation into the book (dids[did]["pending"])
BEFORE it returns success — the hold is recorded BEFORE any money moves.
The gateway may move money ONLY on a granted reservation, then
`commit_reservation` folds it into cumulative_spent (+ treasury) in one
locked write, or `abort_reservation` removes it. Because the hold is
persisted, a SECOND WORKER PROCESS re-reads it and is DENIED before its
own transfer: the multi-worker over-spend is PREVENTED at reservation
time, not merely detected at commit after the money already moved. Each
hold carries a TTL; one never settled (a crash/bug between reserve and
settle) is pruned when strictly expired, so a leak can never lock a DID
out of its budget forever — while a commit in flight re-validates under
the same lock and cannot be dropped by a concurrent prune.

All money math is NaN-SAFE: reserve_budget refuses any non-finite
amount/fee/spend_max (with NaN, `x <= cap` is False for every x — an
unguarded compare would mint an infinite budget), grants only on a
definitive `need <= remaining`, and the book itself is written with
allow_nan=False and read rejecting NaN/Infinity constants.

MULTI-WORKER: the thread lock is process-local, so every durable
read-modify-write additionally holds an fcntl flock on a sidecar
`statebook.json.lock` and RELOADS the book from disk before mutating (no
last-save-wins clobber between worker processes). Reservations live IN
the book, so the RESERVE itself is the authoritative cross-process cap
gate: a worker re-reads another worker's persisted outstanding holds and
is denied before any money moves. The COMMIT re-validates the fold under
the same lock as a belt.

A corrupt, tampered, or missing-after-init file FAILS CLOSED ON MONEY:
the bad book is backed up beside itself (`statebook.json.corrupt-<utc>`)
and LEFT IN PLACE, a critical alert is logged, reads degrade gracefully
(empty standing), but `reserve_budget` DENIES every spend — corruption
never resets a DID's lifetime budget to a clean slate. A sentinel file
(`statebook.json.sentinel`) is written EAGERLY at init — before any
spend — and carries a sha256 integrity tag of the book, so deleting the
book OR rewriting it with valid-but-laundered JSON both fail closed. A
sovereign resolves by restoring a good book (or deliberately removing
book + sentinel + quarantine together).

RESIDUAL (out of scope, host compromise): an attacker with filesystem
write access who deletes ALL state files together (book + sentinel +
quarantine + lock) presents as a fresh world. FS-level delete on the
host means the host itself is already owned — no colocated witness can
defend against that trust model; protect the state directory (perms,
backups) at the ops layer.
"""
from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import logging
import math
import os
import shutil
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger("euearth.statebook")

SCHEMA = "euearth-statebook/1"
ACTION_LOG_MAX = 100                 # per-DID action-log tail kept on disk
RESERVATION_TTL_SECONDS = 120        # unsettled reservations expire (no lockout)


def _fsync_dir(directory: Path) -> None:
    """fsync a DIRECTORY so a rename into it is durable across a crash. os.replace
    makes the swap atomic (no torn file) but NOT durable — the new directory
    entry can still be lost on power loss until the directory itself is flushed.
    Best-effort: platforms/filesystems that cannot fsync a directory are skipped
    rather than crashing a spend."""
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        fd = os.open(directory, flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _durable_write(path: Path, payload: str) -> None:
    """Write payload to a same-directory tmp, fsync the FILE, then os.replace it
    over `path` (atomic), then fsync the DIRECTORY (durable). A crash can no
    longer lose a reservation/commit that already returned success (GPT #2)."""
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())            # the DATA reaches stable storage
    os.replace(tmp, path)                # atomic swap over the live file
    _fsync_dir(path.parent)              # the RENAME reaches stable storage


def _empty() -> dict:
    return {"schema": SCHEMA, "sovereign_treasury": 0.0, "dids": {}}


def _blank_record() -> dict:
    return {"tier": None, "reputation": 0.0, "cumulative_spent": 0.0,
            "pending": [], "action_log": []}


def _finite_nonneg(value: object, field: str) -> float:
    """Parse a persisted money field, refusing NaN/inf/negative outright.
    A poisoned value (negative reopens budget; NaN/inf defeats every cap
    compare) must fail CLOSED at load — never silently mint budget."""
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a number, not a bool")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return result


class StateBook:
    """Durable standing, keyed by DID. In-memory write-through cache over
    one atomically-rewritten JSON file; every mutator takes the lock."""

    def __init__(self, directory: str | Path):
        base = Path(os.environ.get("EUEARTH_STATE_DIR") or directory)
        self.path = base / "statebook.json"
        self.sentinel = self.path.with_name(self.path.name + ".sentinel")
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self._lock = threading.Lock()
        # DEGRADED = the durable book is corrupt/tampered/missing-after-init.
        # Reads degrade gracefully; SPENDS ARE FROZEN (reserve_budget denies)
        # until a sovereign restores a good book. Never silently reset money.
        self._degraded = False
        # Spend reservations are DURABLE + CROSS-PROCESS: they live IN the book
        # under dids[did]["pending"] (recorded BEFORE any money moves), so a
        # second worker process re-reads and SEES an outstanding hold and is
        # denied before its transfer. Each carries a TTL so an unsettled hold
        # (crash/bug between reserve and settle) is pruned, never a lockout.
        # LOAD + eager save under ONE fcntl lock. The load MUST be inside the
        # file lock: a worker that constructs late would otherwise read a
        # snapshot BEFORE the lock, then its eager save would clobber a newer
        # book that other workers committed in between (a lost-update that
        # silently reopens budget). Holding the lock across load->save makes a
        # late constructor read the CURRENT book and re-save it unchanged.
        with self._lock, self._file_lock():
            self._state = self._load()
            if not self._degraded:
                # EAGER first save: book + sentinel (+ integrity tag) exist
                # from the moment the world opens, BEFORE any spend — no window
                # where deleting a pre-first-save book looks like a fresh world.
                self._save()

    # ------------------------------------------------------------- storage

    @property
    def degraded(self) -> bool:
        return self._degraded

    @contextmanager
    def _file_lock(self):
        """MULTI-PROCESS guard: an fcntl flock on the sidecar .lock held
        around every load->modify->save. The thread lock only covers ONE
        process; two gateway workers over one book serialize here. Always
        acquired AFTER self._lock (fixed order — no deadlock)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _read_verified(self) -> dict:
        """Parse the on-disk book and verify it against the sentinel's
        sha256 integrity tag. Raises ValueError on structural damage, on
        NaN/Infinity constants (a NaN cumulative_spent defeats every cap
        compare), and on a tag mismatch (VALID-JSON tampering)."""
        def _bad_const(name: str) -> float:
            raise ValueError(f"non-finite JSON constant {name!r} in statebook")
        raw = self.path.read_bytes()
        state = json.loads(raw.decode("utf-8"), parse_constant=_bad_const)
        if not isinstance(state, dict) or not isinstance(state.get("dids"), dict):
            raise ValueError("statebook is not a {'dids': {...}} object")
        # VALUE VALIDATION (fail closed on money): a persisted cumulative_spent
        # or reservation amount that is negative/NaN/inf reopens or unbounds the
        # budget. `parse_constant` rejects NaN/Infinity JSON *tokens*; this also
        # rejects a valid-JSON negative (e.g. -1000) or an overflow literal
        # (1e400 -> inf). Any failure raises -> the book loads DEGRADED.
        state["sovereign_treasury"] = _finite_nonneg(
            state.get("sovereign_treasury", 0.0), "sovereign_treasury")
        for did, rec in state["dids"].items():
            if not isinstance(rec, dict):
                raise ValueError(f"record for {did!r} must be an object")
            rec["cumulative_spent"] = _finite_nonneg(
                rec.get("cumulative_spent", 0.0), f"{did}.cumulative_spent")
            pending = rec.get("pending")
            if pending is None:
                rec["pending"] = []               # forward-migrate legacy books
            elif not isinstance(pending, list):
                raise ValueError(f"{did}.pending must be a list")
            else:
                for p in pending:
                    if not isinstance(p, dict):
                        raise ValueError(f"{did}.pending entry must be an object")
                    p["amount"] = _finite_nonneg(
                        p.get("amount", 0.0), f"{did}.pending.amount")
                    p["fee"] = _finite_nonneg(
                        p.get("fee", 0.0), f"{did}.pending.fee")
        # FAIL CLOSED on a missing sentinel (Gemini #3): if the book EXISTS,
        # a matching-hash sentinel MUST exist too. A deleted sentinel is
        # tampering (or a torn/rolled-back write), NOT a fresh world — the
        # integrity check is never skipped, and no fresh sentinel is ever
        # written over unverified data. Only a book + matching-hash sentinel
        # pair is trusted.
        if not self.sentinel.exists():
            raise ValueError(
                "statebook.json exists but its sentinel is MISSING — spending "
                "fails closed (deleted sentinel = tampering, not a fresh world; "
                "the unverified book is never re-trusted)")
        tag = None
        for line in self.sentinel.read_text(encoding="utf-8").splitlines():
            if line.startswith("sha256="):
                tag = line.split("=", 1)[1].strip()
                break
        if tag is None:
            raise ValueError(
                "statebook sentinel carries no sha256 integrity tag "
                "(malformed or truncated) — spending fails closed")
        if tag != hashlib.sha256(raw).hexdigest():
            raise ValueError(
                "statebook does not match the sentinel's sha256 integrity tag "
                "(valid-JSON tampering, torn write, or rollback)")
        return state

    def _load(self) -> dict:
        if not self.path.exists():
            if self.sentinel.exists():
                # A book existed before (the sentinel says so) but is GONE.
                # Deleting the file must not mint a clean slate: freeze spends.
                self._degraded = True
                log.critical(
                    "statebook.json MISSING but %s says one existed — "
                    "SPENDS FROZEN (fail closed on money) until the "
                    "sovereign restores the book", self.sentinel.name)
            return _empty()
        try:
            return self._read_verified()
        except (ValueError, OSError) as exc:
            # FAIL CLOSED ON MONEY, never crash the gateway: copy the corrupt
            # book to a quarantine backup, LEAVE the original in place (so
            # every restart re-detects the corruption — no laundering a fresh
            # budget through a restart), and freeze all spending.
            backup = self.path.with_name(
                self.path.name
                + time.strftime(".corrupt-%Y%m%dT%H%M%SZ", time.gmtime()))
            try:
                shutil.copy2(self.path, backup)
            except OSError:
                backup = None
            self._degraded = True
            log.critical(
                "statebook corrupt (%s) — quarantine copy at %s, original "
                "left in place; SPENDS FROZEN (fail closed on money, "
                "lifetime budgets NOT reset) until the sovereign restores "
                "a good book", exc, backup)
            return _empty()

    def _save(self) -> None:
        """Atomic write: whole book to a same-directory tmp (mode 0600),
        then os.replace over the live file, then the sentinel (the durable
        witness that a book exists + its sha256 integrity tag — a MISSING
        or tag-mismatched book means foul play, not a fresh world). Caller
        holds BOTH locks. DEGRADED books are never written: the corrupt
        evidence on disk must survive restarts (writing a fresh book would
        launder the reset). allow_nan=False: a NaN can never be persisted
        into the money records."""
        if self._degraded:
            log.error("statebook DEGRADED — durable write suppressed "
                      "(quarantined book preserved for the sovereign)")
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._state, indent=2, sort_keys=True,
                             allow_nan=False)
        # DURABLE atomic replace (tmp -> fsync file -> os.replace -> fsync dir):
        # os.replace alone is atomic but not crash-durable — a machine/FS crash
        # could lose a reservation/commit that already returned success (GPT #2).
        _durable_write(self.path, payload)
        # Sentinel written DURABLY too: a torn write could otherwise leave a
        # half sentinel that mismatches the new book and freezes all spend on
        # the next restart. Book is made durable FIRST, then the sentinel — a
        # crash between the two leaves the OLD sentinel, which mismatches the
        # new book and fails CLOSED (safe, never reopens the budget).
        sentinel_body = (
            "a statebook.json exists for this world — if it is missing, "
            "corrupt, or does not match the sha256 below, spending fails "
            "closed\n"
            f"sha256={hashlib.sha256(payload.encode('utf-8')).hexdigest()}\n")
        _durable_write(self.sentinel, sentinel_body)

    def _reload_locked(self) -> None:
        """Refresh the in-memory cache from disk. Caller holds BOTH locks.
        Another worker PROCESS may have advanced the book since we cached
        it — a read-modify-write over the stale cache would clobber its
        committed spends (last-save-wins lifetime undercount). A book that
        fails verification mid-run flips DEGRADED (fail closed on money)."""
        if self._degraded:
            return
        if not self.path.exists():
            if self.sentinel.exists():
                self._degraded = True
                log.critical("statebook VANISHED mid-run — SPENDS FROZEN "
                             "(fail closed on money)")
            return
        try:
            self._state = self._read_verified()
        except (ValueError, OSError) as exc:
            self._degraded = True
            log.critical("statebook failed verification mid-run (%s) — "
                         "SPENDS FROZEN (fail closed on money)", exc)

    def _record(self, did: str) -> dict:
        rec = self._state["dids"].get(did)
        if rec is None:
            rec = self._state["dids"][did] = _blank_record()
        return rec

    # --------------------------------------------------------------- reads

    def get(self, did: str) -> dict | None:
        """The DID's persisted standing (a copy), or None if never seen."""
        with self._lock:
            rec = self._state["dids"].get(did)
            return copy.deepcopy(rec) if rec else None

    def cumulative_spent(self, did: str) -> float:
        """LIFETIME spend recorded against this credential DID — the number
        the drain guard holds against the delegated spend_max. On a DEGRADED
        book the true total is unknowable, so it reads as INFINITY: every
        remaining-budget computation collapses to $0 (fail closed)."""
        with self._lock:
            if self._degraded:
                return float("inf")
            rec = self._state["dids"].get(did)
            return float(rec["cumulative_spent"]) if rec else 0.0

    def actions(self, did: str) -> list[dict]:
        """The DID's own bounded action tail (what wingo_look_back mirrors)."""
        with self._lock:
            rec = self._state["dids"].get(did)
            return copy.deepcopy(rec["action_log"]) if rec else []

    def treasury(self) -> float:
        with self._lock:
            return float(self._state["sovereign_treasury"])

    # -------------------------------------------------------------- writes

    def set_tier(self, did: str, tier: str,
                 reputation: float | None = None) -> None:
        """Persist a server-issued rank (and optionally a reputation
        snapshot) so it survives restarts and re-entry. Taken under the
        cross-store policy lock (outermost) so a rank/reputation change cannot
        land between a seller's standing re-check and its listing write — the
        monetization commit holds the same lock. Lock order is fixed
        (policy -> thread -> file) so there is no deadlock."""
        from .governance import policy_lock   # lazy: avoid an import cycle
        with policy_lock(self.path.parent):
            with self._lock, self._file_lock():
                self._reload_locked()
                rec = self._record(did)
                rec["tier"] = tier
                if reputation is not None:
                    rec["reputation"] = float(reputation)
                self._save()

    def reserve_budget(self, did: str, amount: float, fee: float,
                       spend_max: float) -> dict:
        """THE AUTHORITATIVE, CROSS-PROCESS BUDGET GATE — the only door to a
        debit, and it is DURABLE: the reservation is written to disk (under the
        fcntl file lock) BEFORE this returns success, so it is recorded BEFORE
        any money moves. Under BOTH locks, over the FRESHLY RE-READ book:
        verify persisted cumulative_spent + persisted OUTSTANDING reservations
        + amount + fee <= spend_max, then DURABLY persist the reservation.

        Because the hold lives in the book, a second worker PROCESS re-reads it
        and is DENIED before its own transfer — the multi-worker over-spend is
        PREVENTED at reservation time, not merely detected at commit after the
        money already moved. Returns {"ok": True, "reservation_id",
        "remaining"} or {"ok": False, "reason", "remaining"}. DEGRADED books
        always deny.

        NaN-SAFE: non-finite amount/fee/spend_max are refused outright (with
        NaN every `x <= cap` compare is False — an unguarded gate would mint
        an infinite budget), and the grant requires a DEFINITIVE
        `need <= remaining` (any residual NaN arithmetic denies). The loaded
        cumulative_spent is re-checked finite/non-negative before arithmetic."""
        try:
            _amount_raw = float(amount)
            amount, fee = round(_amount_raw, 2), round(float(fee), 2)
            spend_max = float(spend_max)
        except (TypeError, ValueError):
            return {"ok": False, "invalid_input": True, "remaining": 0.0,
                    "reason": "amount, fee and spend_max must be numbers"}
        if not (math.isfinite(amount) and math.isfinite(fee)
                and math.isfinite(spend_max)):
            # invalid_input: the REQUEST is malformed (not the budget
            # exhausted) — the caller must not treat remaining=0.0 as
            # the DID's true balance.
            return {"ok": False, "invalid_input": True, "remaining": 0.0,
                    "reason": (
                        "amount, fee and spend_max must be FINITE numbers "
                        "— NaN/inf money is refused")}
        if amount < 0 or fee < 0:
            return {"ok": False, "invalid_input": True, "remaining": 0.0,
                    "reason": "amount and fee must be non-negative"}
        # SUB-CENT GUARD: a positive amount that rounds below a cent ($0.004 ->
        # $0.00) must not slip a $0.00 hold past the cap while the wallet still
        # moves the real fraction. Money is rounded to cents CONSISTENTLY across
        # reserve/commit/transfer, so a positive-rounds-to-zero amount is refused
        # here exactly as the wallet refuses it — it cannot leak.
        if amount == 0.0 and _amount_raw > 0:
            return {"ok": False, "invalid_input": True, "remaining": 0.0,
                    "reason": ("amount rounds below $0.01 — sub-cent transfers "
                               "are refused (no money moves under a cent)")}
        with self._lock, self._file_lock():
            self._reload_locked()
            if self._degraded:
                return {"ok": False, "remaining": 0.0, "reason": (
                    "statebook DEGRADED (corrupt/missing book quarantined) — "
                    "the lifetime spend cap is unverifiable, so ALL spending "
                    "is frozen until the sovereign restores the book")}
            rec = self._record(did)
            self._prune_expired_locked(did, rec)
            spent = float(rec["cumulative_spent"])
            if not math.isfinite(spent) or spent < 0:
                # A poisoned persisted total must never mint budget: freeze.
                self._degraded = True
                return {"ok": False, "remaining": 0.0, "reason": (
                    "corrupt persisted cumulative_spent — spends FROZEN "
                    "(fail closed on money)")}
            outstanding = round(sum(
                float(p["amount"]) + float(p["fee"])
                for p in rec["pending"]), 2)
            remaining = round(spend_max - spent - outstanding, 2)
            need = round(amount + fee, 2)
            # DENY unless remaining is DEFINITIVELY enough (NaN-safe form).
            if not (need <= remaining + 1e-9):
                return {"ok": False, "remaining": max(0.0, remaining),
                        "reason": (
                            f"lifetime spend cap: {spent:.2f} spent + "
                            f"{outstanding:.2f} reserved + {need:.2f} "
                            f"exceeds spend_max {spend_max:.2f}")}
            rid = f"rsv_{uuid.uuid4().hex[:12]}"
            # DURABLE WRITE of the hold BEFORE success returns — the invariant:
            # no money can move without a recorded hold that already fit.
            rec["pending"].append({
                "id": rid, "amount": amount, "fee": fee,
                "spend_max": spend_max,
                # status "reserved" -> a hold that has NOT yet begun its
                # transfer; only these are eligible for TTL prune. Flipped to
                # "settling" the instant the transfer starts (mark_settling), so
                # a transfer in flight/committing can never be dropped by a
                # concurrent prune (that would un-block a debit that is moving).
                "status": "reserved",
                "expires_at": time.time() + RESERVATION_TTL_SECONDS})
            self._save()
            return {"ok": True, "reservation_id": rid,
                    "remaining": round(remaining - need, 2)}

    def mark_settling(self, reservation_id: str) -> bool:
        """Pin a hold as SETTLING the moment its transfer begins, so a
        concurrent TTL prune can never drop it while money is in flight or a
        commit is racing (that would reopen the budget under an executing
        debit). Under BOTH locks over the freshly re-read book.

        RETURNS a bool the caller MUST honor (Gemini #2 / GPT): True only when
        the hold is durably pinned as settling (or already was). False when the
        book is DEGRADED or the hold has VANISHED (pruned/aborted before we
        could pin it) — the caller must then ABORT and move no money, because a
        transfer on a lost hold reopens the budget under an un-accounted
        debit."""
        with self._lock, self._file_lock():
            self._reload_locked()
            if self._degraded:
                return False
            found_did, rec, p = self._find_pending(reservation_id)
            if p is None:
                return False
            if p.get("status") == "settling":
                return True
            p["status"] = "settling"
            self._save()
            return True

    def _prune_expired_locked(self, did: str, rec: dict) -> bool:
        """Caller holds BOTH locks. A reservation never settled (a crash or
        bug between reserve and settle) must not count against the budget
        forever — past its STRICT TTL it is released, loudly. Only strictly
        expired holds are dropped; a commit-in-flight re-validates under the
        same lock (it cannot interleave with this prune). Returns True if the
        pending list changed. Does NOT save (the caller's write folds it in)."""
        now = time.time()
        kept, dropped = [], []
        for p in rec.get("pending", []):
            # A hold whose transfer has BEGUN (status "settling") is NEVER
            # pruned by age: its money may be in flight/committing, and dropping
            # it would reopen the budget under a debit. Only a hold that never
            # reached settle ("reserved") can expire — that is the crash/bug
            # leak the TTL exists to release, and it fails CLOSED (a stuck
            # settling hold keeps the budget accounted, never reopened).
            if (p.get("status", "reserved") == "reserved"
                    and float(p.get("expires_at", 0)) <= now):
                dropped.append(p)
            else:
                kept.append(p)
        if dropped:
            rec["pending"] = kept
            for p in dropped:
                log.warning("statebook durable reservation %s (did %s, %.2f) "
                            "expired UNSETTLED — released so the budget is not "
                            "locked", p.get("id"), did,
                            float(p.get("amount", 0)) + float(p.get("fee", 0)))
        return bool(dropped)

    def _find_pending(self, reservation_id: str):
        """Locate a durable hold by id across all DIDs. Returns (did, rec, p)
        or (None, None, None). Caller holds BOTH locks."""
        for did, rec in self._state["dids"].items():
            for p in rec.get("pending", []):
                if p.get("id") == reservation_id:
                    return did, rec, p
        return None, None, None

    def commit_reservation(self, reservation_id: str) -> dict:
        """Fold an executed reservation into the DID's lifetime total (and its
        fee into the treasury) — ONE atomic durable write. A reservation
        settles exactly once; an unknown/already-settled id raises KeyError.

        Under BOTH locks over the freshly RE-READ book: the durable hold is
        located, the cap RE-VALIDATED against the fresh persisted
        cumulative_spent (belt: reserve already enforced spent+outstanding+need
        <= spend_max cross-process), then folded and REMOVED in one write. The
        hold is not removed until the fold succeeds, so a commit that races a
        prune is safe (prune cannot interleave under the lock; a still-present
        hold is committed even if its TTL just lapsed)."""
        with self._lock, self._file_lock():
            self._reload_locked()
            if self._degraded:
                raise RuntimeError(
                    "statebook DEGRADED — commit refused, spend not folded "
                    "(fail closed on money)")
            found_did, rec, p = self._find_pending(reservation_id)
            if p is None:
                raise KeyError(
                    f"unknown or already-settled reservation {reservation_id!r}")
            fresh_spent = float(rec["cumulative_spent"])
            need = round(float(p["amount"]) + float(p["fee"]), 2)
            spend_max = float(p.get("spend_max", 0.0))
            if not (fresh_spent + need <= spend_max + 1e-9):
                raise RuntimeError(
                    f"commit rejected: durable lifetime spend "
                    f"{fresh_spent:.2f} + {need:.2f} would exceed "
                    f"spend_max {spend_max:.2f} (another worker spent "
                    "concurrently)")
            rec["cumulative_spent"] = round(fresh_spent + need, 2)
            if float(p["fee"]):
                self._state["sovereign_treasury"] = round(
                    self._state["sovereign_treasury"] + float(p["fee"]), 2)
            rec["pending"] = [q for q in rec["pending"]
                              if q.get("id") != reservation_id]
            self._save()
            return {"cumulative_spent": rec["cumulative_spent"],
                    "sovereign_treasury": self._state["sovereign_treasury"]}

    def abort_reservation(self, reservation_id: str) -> None:
        """Release a durable reservation whose wallet operation did NOT execute.
        Idempotent: an unknown/already-settled id is a no-op. Under a degraded
        book the hold cannot be safely rewritten, so it is left for TTL prune
        on recovery (never a permanent lockout)."""
        with self._lock, self._file_lock():
            self._reload_locked()
            if self._degraded:
                return
            found_did, rec, p = self._find_pending(reservation_id)
            if p is None:
                return
            rec["pending"] = [q for q in rec["pending"]
                              if q.get("id") != reservation_id]
            self._save()

    def append_action(self, did: str, entry: dict) -> None:
        """Append to the DID's own action log, trimmed to ACTION_LOG_MAX."""
        with self._lock, self._file_lock():
            self._reload_locked()
            rec = self._record(did)
            rec["action_log"].append(dict(entry))
            del rec["action_log"][:-ACTION_LOG_MAX]
            self._save()
