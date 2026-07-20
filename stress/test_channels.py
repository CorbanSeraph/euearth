#!/usr/bin/env python3
"""Wave E PR3 — ChannelBook + subscribe/publish/history + live fan-out.

    .venv/bin/python stress/test_channels.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

RESULTS: list[tuple[str, bool]] = []


def check(name: str, ok: bool) -> None:
    RESULTS.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")


def main() -> int:
    from harness.channels import ChannelBook, ChannelError
    from harness.permissions import tool_allowed
    from harness.tool_catalog import tool_names, min_clearance

    tmp = Path(tempfile.mkdtemp(prefix="channels_"))
    book = ChannelBook(tmp)
    book.ensure_seeded()
    rows = book.list_channels()
    check("seed creates at least 2 public channels", len(rows) >= 2)
    check("seed includes text-transform domain guild",
          any(r["channel_id"] == "chan:domain:text-transform" for r in rows))
    check("seed is idempotent",
          len(ChannelBook(tmp).list_channels()) == len(rows))

    cid = "chan:domain:text-transform"
    A, B, C = "did:key:zA", "did:key:zB", "did:key:zC"
    book.subscribe(cid, A)
    book.subscribe(cid, B)
    check("A and B are members",
          book.is_member(cid, A) and book.is_member(cid, B))
    check("C is not a member", not book.is_member(cid, C))

    # non-member cannot publish
    try:
        book.publish(cid, C, "intruder")
        pub_c = True
    except ChannelError:
        pub_c = False
    check("non-member publish refused", not pub_c)

    msg = book.publish(cid, A, "hello guild", subject="hi")
    check("member publish returns seq and message_id",
          msg.get("seq") == 1 and str(msg.get("message_id", "")).startswith("msg_"))
    hist_b = book.history(cid, B, limit=10)
    check("member B can read history",
          len(hist_b) == 1 and hist_b[0]["body"] == "hello guild")
    try:
        book.history(cid, C)
        hist_c = True
    except ChannelError:
        hist_c = False
    check("non-member C cannot read history (self-scope)", not hist_c)

    # permissions / catalog
    for t in ("a2a_list_channels", "a2a_subscribe", "a2a_unsubscribe",
              "a2a_publish", "a2a_channel_history"):
        check(f"catalog includes {t}", t in tool_names())
        check(f"consumer may {t}", tool_allowed("consumer", t))
        check(f"visitor may NOT {t}", not tool_allowed("visitor", t))
    check("min_clearance(a2a_publish) is consumer",
          min_clearance("a2a_publish") == "consumer")

    # ---- gateway live fan-out -------------------------------------------- #
    gtmp = Path(tempfile.mkdtemp(prefix="chan_gw_"))
    os.environ["EUEARTH_FOUNDER_PHASE"] = "0"
    os.environ["EUEARTH_FREEZE_FILE"] = str(gtmp / "FROZEN")
    os.environ["EUEARTH_ALERT_LOG"] = str(gtmp / "ALERTS.log")
    os.environ["EUEARTH_INVITES_ROOT"] = str(gtmp / "invites")
    os.environ.pop("EUEARTH_STATE_DIR", None)
    if Path(os.environ["EUEARTH_FREEZE_FILE"]).exists():
        Path(os.environ["EUEARTH_FREEZE_FILE"]).unlink()

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
    ck, ctok = enter("Carol", "consumer")
    _, vtok = enter("Vis", "visitor")

    listed = g.a2a_list_channels(atok)
    check("list_channels returns seeded guilds",
          listed["ok"] and listed["count"] >= 2)
    cid = "chan:guild:builders"

    vden = None
    try:
        g.a2a_subscribe(vtok, cid)
    except Denied as exc:
        vden = exc.denied_by
    check("visitor subscribe Denied(rank)", vden == "rank")

    g.a2a_subscribe(atok, cid)
    g.a2a_subscribe(btok, cid)
    # Carol does NOT join

    # Bob online on SSE
    conn_b = g.open_a2a_stream(btok)
    check("Bob stream topics include joined channel after open",
          f"chan:{cid}" in conn_b.topics or any(
              cid in t for t in conn_b.topics))

    # Alice joins then publishes (Bob already streaming with membership attach)
    # Re-subscribe Bob stream topics if join was after stream open
    g.a2a_subscribe(btok, cid)  # idempotent
    # ensure Bob's live conn has the topic (subscribe attaches to live conns)
    check("subscribe attaches chan topic to live SSE",
          any(cid in t for t in conn_b.topics))

    pub = g.a2a_publish(atok, cid, "builders: ship the channel PR",
                        subject="work")
    check("publish ok with seq",
          pub.get("ok") and pub.get("message", {}).get("seq") >= 1)
    time.sleep(0.05)
    found = False
    while not conn_b.queue.empty():
        item = conn_b.queue.get_nowait()
        if (item.get("_control") == "event"
                and item.get("event", {}).get("body")
                == "builders: ship the channel PR"):
            found = True
            check("live channel event has kind=channel",
                  item["event"].get("kind") == "channel")
            check("live channel event channel_id matches",
                  item["event"].get("channel_id") == cid)
    check("online member Bob receives channel publish on SSE", found)

    # Carol not member — no history, no publish
    hden = None
    try:
        g.a2a_channel_history(ctok, cid)
    except Denied as exc:
        hden = exc.denied_by
    check("non-member history Denied(channel)", hden == "channel")
    pden = None
    try:
        g.a2a_publish(ctok, cid, "not a member")
    except Denied as exc:
        pden = exc.denied_by
    check("non-member publish Denied(channel)", pden == "channel")

    # History for member
    hist = g.a2a_channel_history(atok, cid, limit=20)
    check("member history includes the post",
          any(m.get("body") == "builders: ship the channel PR"
              for m in hist["messages"]))

    # Edge filter on publish
    eden = None
    try:
        g.a2a_publish(atok, cid, "leaked pirate scrape dump")
    except Denied as exc:
        eden = exc.denied_by
    check("edge filter blocks banned channel body", eden == "edge")

    # Unsubscribe
    g.a2a_unsubscribe(btok, cid)
    check("after unsubscribe Bob not a member",
          not g.channels.is_member(cid, bk.did))
    check("unsubscribe drops topic from live SSE",
          not any(cid in t for t in conn_b.topics))

    g.close_a2a_stream(conn_b)

    # Durability across gateway restart
    g4 = EuEarthGateway(str(gtmp / "world"))
    hist2 = g4.channels.history(cid, ak.did, limit=20)
    check("channel scrollback survives restart",
          any(m.get("body") == "builders: ship the channel PR" for m in hist2))

    print()
    ok = all(p for _, p in RESULTS)
    print(f"CHANNELS: {'ALL INVARIANTS HELD' if ok else 'FAILURES ABOVE'} "
          f"({sum(p for _, p in RESULTS)}/{len(RESULTS)})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
