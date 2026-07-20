#!/usr/bin/env python3
"""A2A MAILBOX regression — rate limits, known DID, self-scoped inbox.

Wave D (Corban gate #6): spam surface treated adversarially.

    .venv/bin/python stress/test_mailbox.py   # exit 0 = all held
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
    from harness.mailbox import MailboxBook, MailboxError, MAX_BODY, RATE_MAX
    from harness.permissions import tool_allowed
    from harness.tool_catalog import tool_names, min_clearance

    tmp = Path(tempfile.mkdtemp(prefix="mailbox_"))
    box = MailboxBook(tmp)
    A, B, C = "did:key:zAlice", "did:key:zBob", "did:key:zCarol"

    # unknown recipient refused even if known_recipient=False
    try:
        box.send(from_did=A, to_did=B, body="hi", known_recipient=False)
        unk = False
    except MailboxError:
        unk = True
    check("send refuses when known_recipient=False", unk)

    r = box.send(from_did=A, to_did=B, body="hello Bob", subject="hi",
                 known_recipient=True)
    check("send to known recipient ok", r.get("ok") is True)
    inbox_b = box.inbox(B)
    check("Bob sees Alice's message",
          len(inbox_b) == 1 and inbox_b[0]["body"] == "hello Bob"
          and inbox_b[0]["from_did"] == A)
    check("Alice cannot read Bob's inbox by calling inbox(A) empty",
          box.inbox(A) == [])
    # defense: even if we somehow write wrong to_did, inbox filters
    check("Carol's inbox empty (no cross-leak)", box.inbox(C) == [])

    # self-send refused
    try:
        box.send(from_did=A, to_did=A, body="loop", known_recipient=True)
        self_ok = True
    except MailboxError:
        self_ok = False
    check("self-send refused", not self_ok)

    # body size cap
    try:
        box.send(from_did=A, to_did=B, body="x" * (MAX_BODY + 10),
                 known_recipient=True)
        big = True
    except MailboxError:
        big = False
    check("oversized body fail closed", not big)

    # rate limit
    os.environ["EUEARTH_MAIL_RATE_MAX"] = "5"
    # module already imported RATE_MAX — use current RATE_MAX for loop
    limited = False
    # use a fresh book so rate window is clean for a new sender
    box2 = MailboxBook(tmp)
    for i in range(RATE_MAX + 3):
        try:
            box2.send(from_did=C, to_did=B, body=f"flood {i}",
                      known_recipient=True)
        except MailboxError as exc:
            if "rate limit" in str(exc):
                limited = True
                break
    check("send rate limit trips under flood", limited)

    # A fresh process/book must not reset the sender's rolling window.
    restart_root = Path(tempfile.mkdtemp(prefix="mailbox_rate_restart_"))
    before_restart = MailboxBook(restart_root)
    for i in range(RATE_MAX):
        before_restart.send(
            from_did=A, to_did=B, body=f"pre-restart {i}",
            known_recipient=True)
    after_restart = MailboxBook(restart_root)
    try:
        after_restart.send(
            from_did=A, to_did=B, body="restart bypass",
            known_recipient=True)
        restart_limited = False
    except MailboxError as exc:
        restart_limited = "rate limit" in str(exc)
    check("send rate limit survives mailbox restart", restart_limited)

    # permissions / catalog
    check("visitor may NOT a2a_send",
          not tool_allowed("visitor", "a2a_send"))
    check("consumer may a2a_send and a2a_inbox",
          tool_allowed("consumer", "a2a_send")
          and tool_allowed("consumer", "a2a_inbox"))
    check("catalog includes a2a_send and a2a_inbox",
          "a2a_send" in tool_names() and "a2a_inbox" in tool_names())
    check("min_clearance(a2a_send) is consumer",
          min_clearance("a2a_send") == "consumer")

    # gateway wiring
    gtmp = Path(tempfile.mkdtemp(prefix="mail_gw_"))
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

    def enter(name, tier):
        k = HarnessKey.generate()
        d = issue_delegation(human, k.did, capabilities=["enter", "try"],
                             spend_max=5.0, ttl_seconds=3600)
        tok = g.enter(name, k.did, d)["session"]
        aid = next(a for a, v in g.world.agents.items() if v.get("did") == k.did)
        if g.world.agents[aid]["tier"] != tier:
            g._set_tier(aid, tier)
        return k, tok

    ak, atok = enter("Alice", "consumer")
    bk, btok = enter("Bob", "consumer")
    _, vtok = enter("Vis", "visitor")

    vden = None
    try:
        g.a2a_send(vtok, bk.did, "nope")
    except Denied as exc:
        vden = exc.denied_by
    check("visitor a2a_send Denied(rank)", vden == "rank")

    # unknown DID refused
    uden = None
    try:
        g.a2a_send(atok, "did:key:zNeverSeenOnEuEarth", "ping")
    except Denied as exc:
        uden = exc.denied_by
    check("unknown recipient Denied(mailbox)", uden == "mailbox")

    sent = g.a2a_send(atok, bk.did, "work together on text-transform?",
                      subject="collab")
    check("Alice sends to Bob ok", sent.get("ok") is True)
    binbox = g.a2a_inbox(btok)
    check("Bob inbox has Alice's message",
          binbox["count"] >= 1
          and any(m.get("from_did") == ak.did for m in binbox["messages"]))
    ainbox = g.a2a_inbox(atok)
    check("Alice inbox does not contain Bob's mail (self-scope)",
          not any(m.get("body") == "work together on text-transform?"
                  for m in ainbox["messages"]))

    # consult returns DID + a2a_send hint
    council = g.a2a_consult(atok, "text", min_reputation=0.0)
    ex0 = (council.get("experts") or [None])[0] or {}
    check("a2a_consult returns experts list",
          isinstance(council.get("experts"), list) and len(council["experts"]) > 0)
    # Seeded elders may be discovery-only (no DID); live citizens get a2a_send.
    check("a2a_consult expert rows carry a channel field",
          all(isinstance(x.get("channel"), str) for x in council["experts"]))

    # durability
    g2 = EuEarthGateway(str(gtmp / "world"))
    k3 = HarnessKey.generate()
    d3 = issue_delegation(human, k3.did, capabilities=["enter"],
                          spend_max=5.0, ttl_seconds=3600)
    # re-enter as Bob's DID? sessions are ephemeral — use book directly
    durable = g2.mailboxes.inbox(bk.did)
    check("inbox survives gateway restart",
          any(m.get("from_did") == ak.did for m in durable))

    print()
    ok = all(p for _, p in RESULTS)
    print(f"MAILBOX: {'ALL INVARIANTS HELD' if ok else 'FAILURES ABOVE'} "
          f"({sum(p for _, p in RESULTS)}/{len(RESULTS)})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
