#!/usr/bin/env python3
"""INVITE SINGLE-USE ATOMICITY (issue #8 — TOCTOU) regression test.

Fires N concurrent redemptions of ONE single-use invite code and asserts
EXACTLY ONE commits. Runs the race two ways:

  * REAL PROCESSES (multiprocessing, fork) — the deployment-relevant case:
    uvicorn workers are separate processes, so the file lock must hold
    across process boundaries, not just the GIL.
  * THREADS — a tighter interleave of the read-modify-write.

Before the fix (non-atomic load-check-save) 4-16 of the racers would each
get a founder record back. After the fcntl lock in InviteBook.redeem, the
loser threads/processes re-read a store whose code is already `redeemed`
and are refused.

    .venv/bin/python stress/test_invite_race.py     # exit 0 = invariant held
"""
from __future__ import annotations

import multiprocessing as mp
import os
import sys
import tempfile
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def _redeem_worker(code: str, root: str, i: int) -> str:
    from harness.invites import InviteBook, InviteError
    book = InviteBook(root)
    try:
        book.redeem(code, f"did:key:zRacer{i}")
        return "WIN"
    except InviteError:
        return "lose"
    except Exception as exc:  # pragma: no cover - unexpected
        return f"err:{type(exc).__name__}"


def _proc_entry(args):
    return _redeem_worker(*args)


def race_processes(n: int = 16) -> int:
    root = tempfile.mkdtemp(prefix="invite_race_proc_")
    from harness.invites import InviteBook
    code = InviteBook(root).mint(1, quota=0)[0]
    ctx = mp.get_context("fork")
    with ctx.Pool(n) as pool:
        outs = pool.map(_proc_entry, [(code, root, i) for i in range(n)])
    wins = sum(1 for o in outs if o == "WIN")
    print(f"  processes: {n} racers -> {wins} winner(s)  {outs}")
    return wins


def race_threads(n: int = 24) -> int:
    root = tempfile.mkdtemp(prefix="invite_race_thr_")
    from harness.invites import InviteBook
    code = InviteBook(root).mint(1, quota=0)[0]
    results: list[str | None] = [None] * n
    barrier = threading.Barrier(n)

    def worker(i: int) -> None:
        barrier.wait()  # release all threads at once for a tight race
        results[i] = _redeem_worker(code, root, i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wins = sum(1 for r in results if r == "WIN")
    print(f"  threads:   {n} racers -> {wins} winner(s)")
    return wins


def main() -> int:
    print("INVITE SINGLE-USE ATOMICITY under concurrency (issue #8)")
    ok = True
    for _ in range(3):  # repeat to shake out scheduling nondeterminism
        pw = race_processes()
        tw = race_threads()
        if pw != 1 or tw != 1:
            ok = False
    verdict = "PASS" if ok else "FAIL — SINGLE-USE HOLE"
    print(f"[{verdict}] exactly one redemption commits across processes AND threads")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
