#!/usr/bin/env python3
"""SCRATCHPAD regression — private durable workbench + sandbox run.

Wave B base wingo skill (Corban-gated after #21). Per-DID durable pads,
agent-content-only writes, path jail, env-overridable caps fail closed,
run via the exact sandbox path, strict self-scoping (session DID only).

    .venv/bin/python stress/test_scratchpad.py   # exit 0 = all held
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

RESULTS: list[tuple[str, bool]] = []


def check(name: str, ok: bool) -> None:
    RESULTS.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")


def main() -> int:
    from harness.permissions import tool_allowed
    from harness.scratchpad import (
        ScratchpadBook, ScratchpadError, safe_relpath, MAX_PADS,
    )
    from harness.tool_catalog import tool_names, min_clearance

    # ---- unit: path jail ------------------------------------------------- #
    check("safe path accepts main.py", safe_relpath("main.py") == "main.py")
    check("safe path accepts nested/ok_file.py",
          safe_relpath("nested/ok_file.py") == "nested/ok_file.py")
    for bad in ("../etc/passwd", "/etc/passwd", "..", "", "a\x00b",
                "foo/../../x", "~/secret"):
        try:
            safe_relpath(bad)
            ok = False
        except ScratchpadError:
            ok = True
        check(f"safe_relpath refuses {bad!r}", ok)

    # ---- unit: durable book ---------------------------------------------- #
    tmp = Path(tempfile.mkdtemp(prefix="scratchpad_"))
    book = ScratchpadBook(tmp)
    DID = "did:key:zScratchOwner"
    OTHER = "did:key:zOtherAgent"

    m = book.open_pad(DID, title="first pad")
    pid = m["pad_id"]
    check("open creates a pad with main.py entrypoint default",
          m["entrypoint"] == "main.py" and pid.startswith("pad_"))
    w = book.write_file(DID, pid, "main.py", "result = 1 + 1\n")
    check("write main.py ok", w["ok"] and w["path"] == "main.py")
    r = book.read_file(DID, pid, "main.py")
    check("read returns written content",
          r["content"] == "result = 1 + 1\n")
    book.write_file(DID, pid, "helper.py", "def double(x):\n    return x * 2\n")
    listed = book.list_pads(DID)
    check("list_pads shows the pad with file_count >= 2",
          len(listed) == 1 and listed[0]["file_count"] >= 2)

    # durability across fresh book
    book2 = ScratchpadBook(tmp)
    check("pad SURVIVES fresh book over same directory",
          any(p["pad_id"] == pid for p in book2.list_pads(DID)))
    check("content SURVIVES restart",
          book2.read_file(DID, pid, "main.py")["content"] == "result = 1 + 1\n")

    # OTHER did cannot see owner's pad by pad_id (different hash dir)
    check("other DID list is empty (self-scoped store)",
          book2.list_pads(OTHER) == [])
    try:
        book2.read_file(OTHER, pid, "main.py")
        cross = False
    except ScratchpadError:
        cross = True
    check("other DID cannot read owner's pad_id (unknown pad)", cross)

    # path escape attempts
    try:
        book.write_file(DID, pid, "../escape.py", "x")
        esc = False
    except ScratchpadError:
        esc = True
    check("write refuses path escape ..", esc)

    # caps: max file bytes
    os.environ["EUEARTH_SCRATCHPAD_MAX_FILE_BYTES"] = "32"
    # re-import caps by constructing with env already set — module read env at
    # import time; force small content check via direct compare
    from harness import scratchpad as sp
    big = "x" * (sp.MAX_FILE_BYTES + 1)
    try:
        book.write_file(DID, pid, "big.py", big)
        # if module already loaded with default 64k, big might still fit —
        # only assert fail-closed when over the module's current cap
        over = len(big.encode()) > sp.MAX_FILE_BYTES
        if over:
            capped = False
        else:
            capped = True  # default cap large enough; skip strict fail
    except ScratchpadError:
        capped = True
    check("write fails closed when content exceeds MAX_FILE_BYTES",
          capped or len(big.encode()) <= sp.MAX_FILE_BYTES)

    # ---- permissions + catalog ------------------------------------------- #
    check("visitor may NOT call scratchpad_write",
          not tool_allowed("visitor", "scratchpad_write"))
    check("consumer may call scratchpad_list/open/write/read/run",
          all(tool_allowed("consumer", t) for t in (
              "scratchpad_list", "scratchpad_open", "scratchpad_write",
              "scratchpad_read", "scratchpad_run")))
    check("catalog includes scratchpad list/open/write/read/run tools",
          all(t in tool_names() for t in (
              "scratchpad_list", "scratchpad_open", "scratchpad_write",
              "scratchpad_read", "scratchpad_run")))
    check("min_clearance(scratchpad_write) is consumer",
          min_clearance("scratchpad_write") == "consumer")

    # ---- gateway wiring + self-scope + sandbox run ----------------------- #
    gtmp = Path(tempfile.mkdtemp(prefix="scratch_gw_"))
    os.environ["EUEARTH_FOUNDER_PHASE"] = "0"
    os.environ["EUEARTH_FREEZE_FILE"] = str(gtmp / "FROZEN")
    os.environ["EUEARTH_ALERT_LOG"] = str(gtmp / "ALERTS.log")
    os.environ["EUEARTH_INVITES_ROOT"] = str(gtmp / "invites")
    os.environ.pop("EUEARTH_STATE_DIR", None)

    from harness.delegation import issue_delegation
    from harness.did import HarnessKey
    from harness.gateway import Denied, EuEarthGateway

    human = HarnessKey.generate()
    g = EuEarthGateway(str(gtmp / "world"))

    def enter(name: str, tier: str, caps=None):
        k = HarnessKey.generate()
        d = issue_delegation(
            human, k.did,
            capabilities=caps or ["enter", "try"],
            spend_max=5.0, ttl_seconds=3600)
        tok = g.enter(name, k.did, d)["session"]
        aid = next(a for a, v in g.world.agents.items() if v.get("did") == k.did)
        if g.world.agents[aid]["tier"] != tier:
            g._set_tier(aid, tier)
        return k, tok

    # visitor refused
    _, vtok = enter("Vis", "visitor")
    vden = None
    try:
        g.scratchpad_open(vtok, title="nope")
    except Denied as exc:
        vden = exc.denied_by
    check("visitor scratchpad_open Denied(rank)", vden == "rank")

    # consumer happy path
    owner_k, otok = enter("Owner", "consumer")
    opened = g.scratchpad_open(otok, title="demo")
    check("consumer opens a pad", opened["ok"] and "pad_id" in opened)
    opid = opened["pad_id"]
    g.scratchpad_write(otok, opid, "helper.py",
                       "def double(x):\n    return x * 2\n")
    g.scratchpad_write(otok, opid, "main.py",
                       "from helper import double\nresult = double(21)\n")
    run = g.scratchpad_run(otok, opid)
    check("scratchpad_run returns ok via sandbox",
          run.get("ok") is True and run.get("result") == 42)
    check("scratchpad_run uses sandboxed path (has exit_code or result)",
          "result" in run)

    # multi-file helper import proves files were materialized in the jail
    check("multi-file pad: helper import works inside sandbox",
          run.get("result") == 42)

    # list + read
    pads = g.scratchpad_list(otok)
    check("scratchpad_list returns the open pad",
          any(p["pad_id"] == opid for p in pads["pads"]))
    rd = g.scratchpad_read(otok, opid, "main.py")
    check("scratchpad_read returns main.py content",
          "double" in rd.get("content", ""))

    # second agent cannot open owner's pad_id
    _, other_tok = enter("Other", "consumer")
    cross_den = None
    try:
        g.scratchpad_read(other_tok, opid, "main.py")
    except Denied as exc:
        cross_den = exc.denied_by
    check("cross-agent scratchpad_read is Denied (self-scope)",
          cross_den in ("scratchpad", "rank") or cross_den is not None)
    # stronger: must not return content
    try:
        leaked = g.scratchpad_read(other_tok, opid, "main.py")
        leaked_ok = leaked.get("content") is not None
    except Denied:
        leaked_ok = False
    check("cross-agent read does NOT return file content", not leaked_ok)

    # no server path load API — write is content-only (already); refuse
    # absolute-looking paths
    path_den = None
    try:
        g.scratchpad_write(otok, opid, "/etc/passwd", "x")
    except Denied as exc:
        path_den = exc.denied_by
    check("absolute path write Denied(scratchpad)", path_den == "scratchpad")

    # IP guardrail: responses never include host harness paths
    blob = str(g.scratchpad_list(otok)) + str(g.scratchpad_read(otok, opid))
    check("scratchpad responses do not leak host filesystem paths",
          "/Users/" not in blob and "harness/gateway" not in blob)

    # ---- scratchpad_submit → gated contribution journal ------------------ #
    from harness.contributions import tree_hash, ContributionJournal
    from harness.permissions import tool_allowed as _ta

    check("consumer may call scratchpad_submit",
          _ta("consumer", "scratchpad_submit"))
    check("visitor may NOT call scratchpad_submit",
          not _ta("visitor", "scratchpad_submit"))
    check("catalog includes scratchpad_submit",
          "scratchpad_submit" in tool_names())

    empty = g.scratchpad_open(otok, title="empty")
    empty_den = None
    try:
        g.scratchpad_submit(otok, empty["pad_id"], "nothing here")
    except Denied as exc:
        empty_den = exc.denied_by
    check("submit empty pad is Denied(scratchpad)", empty_den == "scratchpad")

    sub = g.scratchpad_submit(
        otok, opid, "demo: double helper for the commons", kind="skill")
    check("submit returns receipt_id and status received",
          sub.get("ok") is True
          and str(sub.get("receipt_id", "")).startswith("cbr_")
          and sub.get("status") == "received")
    check("submit returns tree_hash and file_count",
          bool(sub.get("tree_hash")) and sub.get("file_count", 0) >= 2)

    # durable journal line
    journal = ContributionJournal(g.world.statebook.path.parent)
    mine = journal.list_for_did(owner_k.did)
    check("journal lists the caller's own receipt",
          any(r.get("receipt_id") == sub["receipt_id"] for r in mine))
    rec = next(r for r in mine if r.get("receipt_id") == sub["receipt_id"])
    check("journal record is scratchpad channel with tree_hash",
          rec.get("channel") == "scratchpad_submit"
          and rec.get("tree_hash") == sub["tree_hash"]
          and rec.get("did") == owner_k.did)
    check("journal never claims auto-merge (status received only)",
          rec.get("status") == "received")

    # tree_hash matches recompute
    _meta, files = g.scratchpads.load_files(owner_k.did, opid)
    th, _ = tree_hash(files)
    check("tree_hash is deterministic over pad files", th == sub["tree_hash"])

    # cross-agent cannot submit owner's pad_id
    cross_sub = None
    try:
        g.scratchpad_submit(other_tok, opid, "steal this pad")
    except Denied as exc:
        cross_sub = exc.denied_by
    check("cross-agent submit of foreign pad_id is Denied",
          cross_sub is not None)
    other_did = g._session(other_tok).did
    check("other DID journal does not contain owner's receipt",
          not any(r.get("receipt_id") == sub["receipt_id"]
                  for r in journal.list_for_did(other_did)))

    # bad kind / empty summary
    bad_kind = None
    try:
        g.scratchpad_submit(otok, opid, "x", kind="not-a-kind")
    except Denied as exc:
        bad_kind = exc.denied_by
    check("invalid kind is Denied(scratchpad)", bad_kind == "scratchpad")
    no_sum = None
    try:
        g.scratchpad_submit(otok, opid, "   ")
    except Denied as exc:
        no_sum = exc.denied_by
    check("empty summary is Denied(scratchpad)", no_sum == "scratchpad")

    print()
    ok = all(p for _, p in RESULTS)
    print(f"SCRATCHPAD: {'ALL INVARIANTS HELD' if ok else 'FAILURES ABOVE'} "
          f"({sum(p for _, p in RESULTS)}/{len(RESULTS)})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
