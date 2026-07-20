#!/usr/bin/env python3
"""Wave E PR1 — EventBus + Presence + SSE stream fabric.

No channel tools yet; proves the realtime backbone:
  * LocalBus publish/subscribe
  * Presence self-scope (never deliver another DID's DM)
  * SSE connect consumer+ only; visitor denied
  * buffer overflow closes connection
  * hard freeze closes streams / refuses connect
  * system:house envelope

    .venv/bin/python stress/test_a2a_realtime.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

RESULTS: list[tuple[str, bool]] = []


def check(name: str, ok: bool) -> None:
    RESULTS.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")


def main() -> int:
    from harness.a2a_events import (
        KIND_DM, KIND_SYSTEM, SSE_BUFFER, TOPIC_SYSTEM_HOUSE,
        dm_topic, make_event,
    )
    from harness.event_bus import LocalBus
    from harness.presence import PresenceRegistry

    # ---- unit: LocalBus -------------------------------------------------- #
    bus = LocalBus()
    got = []
    bus.subscribe("t1", lambda t, e: got.append((t, e)))
    bus.publish("t1", {"x": 1})
    bus.publish("t2", {"x": 2})
    check("LocalBus delivers to matching topic only",
          got == [("t1", {"x": 1})])

    # ---- unit: Presence self-scope --------------------------------------- #
    reg = PresenceRegistry(buffer=8)
    ca = reg.connect("did:A", "sessA")
    cb = reg.connect("did:B", "sessB")
    # Push a DM for A
    ev_a = make_event(kind=KIND_DM, body="hi A", from_did="did:B", to_did="did:A")
    n = reg.push_to_did("did:A", ev_a)
    check("push_to_did delivers in-scope DM to A", n == 1)
    item = ca.queue.get_nowait()
    check("A queue has the DM event",
          item.get("_control") == "event"
          and item["event"]["to_did"] == "did:A")
    # Cross-scope: try to push A's event to B's connections — scope check drops it
    n2 = reg.push_to_did("did:B", ev_a)
    check("cross-scope DM to B is NOT delivered (self-scope law)", n2 == 0)
    check("B queue empty after cross-scope attempt", cb.queue.empty())

    # Buffer overflow
    tiny = PresenceRegistry(buffer=2)
    ct = tiny.connect("did:T", "sT")
    for i in range(3):
        ct.put({"_control": "event", "event": {"n": i, "kind": "dm", "to_did": "did:T"}})
    check("SSE buffer overflow marks connection closed",
          ct.closed and ct.close_reason == "sse_buffer_overflow")

    # ---- gateway + SSE path ---------------------------------------------- #
    tmp = Path(tempfile.mkdtemp(prefix="a2a_rt_"))
    os.environ["EUEARTH_FOUNDER_PHASE"] = "0"
    os.environ["EUEARTH_FREEZE_FILE"] = str(tmp / "FROZEN")
    os.environ["EUEARTH_ALERT_LOG"] = str(tmp / "ALERTS.log")
    os.environ["EUEARTH_INVITES_ROOT"] = str(tmp / "invites")
    os.environ.pop("EUEARTH_STATE_DIR", None)
    # Fast heartbeat for tests
    os.environ["EUEARTH_A2A_HEARTBEAT_S"] = "30"

    from harness import failsafe
    from harness.delegation import issue_delegation
    from harness.did import HarnessKey
    from harness.gateway import Denied, EuEarthGateway

    # ensure freeze file clean
    if Path(os.environ["EUEARTH_FREEZE_FILE"]).exists():
        Path(os.environ["EUEARTH_FREEZE_FILE"]).unlink()

    human = HarnessKey.generate()
    g = EuEarthGateway(str(tmp / "world"))

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

    # visitor denied stream
    vden = None
    try:
        g.open_a2a_stream(vtok)
    except Denied as exc:
        vden = exc.denied_by
    check("visitor open_a2a_stream Denied(rank)", vden == "rank")

    conn_a = g.open_a2a_stream(atok)
    check("consumer opens SSE connection",
          conn_a.did == ak.did and not conn_a.closed)
    check("connection topics include dm:self and system:house",
          dm_topic(ak.did) in conn_a.topics
          and TOPIC_SYSTEM_HOUSE in conn_a.topics)
    check("presence reports Alice online (routing only)",
          g.presence.is_online(ak.did))

    # Live push via bus (PR2 will hook a2a_send; here we prove the fabric)
    ev = make_event(kind=KIND_DM, body="ping live",
                    from_did=bk.did, to_did=ak.did)
    g.publish_a2a(dm_topic(ak.did), ev)
    time.sleep(0.05)
    try:
        got = conn_a.queue.get(timeout=1.0)
        live_ok = (got.get("_control") == "event"
                   and got["event"]["message_id"] == ev["message_id"])
    except Exception:
        live_ok = False
    check("bus publish reaches Alice SSE queue", live_ok)

    # Cross-DID: publish Bob's DM topic — Alice must not get it
    ev_b = make_event(kind=KIND_DM, body="secret for Bob",
                      from_did=ak.did, to_did=bk.did)
    g.publish_a2a(dm_topic(bk.did), ev_b)
    time.sleep(0.05)
    leaked = False
    while not conn_a.queue.empty():
        item = conn_a.queue.get_nowait()
        if (item.get("_control") == "event"
                and item.get("event", {}).get("to_did") == bk.did):
            leaked = True
    check("Alice stream never receives Bob's DM (self-scope)", not leaked)

    # system event
    sys_ev = g.emit_system_event("keel champion swapped",
                                 attrs={"domain": "text-transform"})
    check("system event has kind=system", sys_ev.get("kind") == KIND_SYSTEM)
    time.sleep(0.05)
    sys_got = False
    while not conn_a.queue.empty():
        item = conn_a.queue.get_nowait()
        if (item.get("_control") == "event"
                and item.get("event", {}).get("kind") == KIND_SYSTEM):
            sys_got = True
    check("system:house event reaches subscribed stream", sys_got)

    # iter_a2a_sse yields hello
    chunks = []
    def pump():
        for i, ch in enumerate(g.iter_a2a_sse(conn_a)):
            chunks.append(ch)
            if i >= 0:  # hello only
                conn_a.close("test_done")
                break
    t = threading.Thread(target=pump, daemon=True)
    t.start()
    t.join(timeout=3)
    check("iter_a2a_sse emits a2a.hello",
          any("a2a.hello" in c for c in chunks))

    # Hard freeze closes streams + refuses new connect
    conn_b = g.open_a2a_stream(btok)
    failsafe.freeze("test hard freeze streams", mode="hard", by=failsafe.SOVEREIGN)
    closed_n = g.hard_freeze_streams()
    check("hard_freeze_streams closes live connections",
          closed_n >= 1 and conn_b.closed)
    hden = None
    try:
        g.open_a2a_stream(btok)
    except Denied as exc:
        hden = exc.denied_by
    check("hard freeze refuses new stream connect",
          hden == "failsafe")
    failsafe.unfreeze(by=failsafe.SOVEREIGN)
    g.presence.reopen()
    # recover
    conn_c = g.open_a2a_stream(btok)
    check("after unfreeze stream can open again", not conn_c.closed)
    g.close_a2a_stream(conn_c)

    # HTTP SSE endpoint via TestClient (no long-lived read — avoid hang)
    from fastapi.testclient import TestClient
    from web.app import create_app
    from web.world import World
    w = World(str(tmp / "webworld"))
    app = create_app(world=w, with_mcp=False)
    client = TestClient(app)
    r = client.get("/api/a2a/stream")
    check("HTTP SSE without session returns 401", r.status_code == 401)
    r2 = client.get("/api/a2a/health")
    check("HTTP /api/a2a/health ok",
          r2.status_code == 200 and r2.json().get("stream") == "sse")

    # Consumer session on app gateway → open_a2a_stream works end-to-end
    g2 = app.state.gateway
    assert g2 is not None
    k2 = HarnessKey.generate()
    d2 = issue_delegation(human, k2.did, capabilities=["enter"],
                          spend_max=5.0, ttl_seconds=3600)
    tok2 = g2.enter("StreamUser", k2.did, d2)["session"]
    aid2 = next(a for a, v in g2.world.agents.items() if v.get("did") == k2.did)
    g2._set_tier(aid2, "consumer")
    conn_http = g2.open_a2a_stream(tok2)
    check("app.state.gateway open_a2a_stream works for consumer session",
          not conn_http.closed and conn_http.did == k2.did)
    # Publish and receive without hanging the HTTP stream body
    ev_h = make_event(kind=KIND_DM, body="via app gateway",
                      from_did=ak.did, to_did=k2.did)
    g2.publish_a2a(dm_topic(k2.did), ev_h)
    time.sleep(0.05)
    try:
        item_h = conn_http.queue.get(timeout=1.0)
        http_live = item_h.get("event", {}).get("body") == "via app gateway"
    except Exception:
        http_live = False
    check("app gateway bus delivers to stream queue", http_live)
    g2.close_a2a_stream(conn_http)

    # ---- PR2: a2a_send durable-first + live push ------------------------- #
    # Fresh gateway so freeze state is clean
    if Path(os.environ["EUEARTH_FREEZE_FILE"]).exists():
        Path(os.environ["EUEARTH_FREEZE_FILE"]).unlink()
    g3 = EuEarthGateway(str(tmp / "world3"))
    g3.presence.reopen()

    def enter3(name, tier):
        k = HarnessKey.generate()
        d = issue_delegation(human, k.did, capabilities=["enter", "try"],
                             spend_max=5.0, ttl_seconds=3600)
        tok = g3.enter(name, k.did, d)["session"]
        aid = next(a for a, v in g3.world.agents.items() if v.get("did") == k.did)
        if g3.world.agents[aid]["tier"] != tier:
            g3._set_tier(aid, tier)
        return k, tok

    ck, ctok = enter3("Carol", "consumer")
    dk, dtok = enter3("Dave", "consumer")
    # Dave online on SSE
    conn_d = g3.open_a2a_stream(dtok)
    # Carol offline (no stream) — still gets durable mail
    sent_live = g3.a2a_send(ctok, dk.did, "realtime hello Dave",
                            subject="ping")
    check("a2a_send returns ok with message_id",
          sent_live.get("ok") is True and bool(sent_live.get("message_id")))
    check("a2a_send live_push True when recipient stream is online",
          sent_live.get("live_push") is True)
    time.sleep(0.05)
    try:
        item_d = conn_d.queue.get(timeout=1.0)
        # may have hello control noise — drain for our message
        found = False
        if item_d.get("_control") == "event" and item_d.get("event", {}).get(
                "body") == "realtime hello Dave":
            found = True
        while not found and not conn_d.queue.empty():
            item_d = conn_d.queue.get_nowait()
            if (item_d.get("_control") == "event"
                    and item_d.get("event", {}).get("body")
                    == "realtime hello Dave"):
                found = True
        # also check message_id match
        if found:
            mid_match = (item_d.get("event", {}).get("message_id")
                         == sent_live.get("message_id"))
        else:
            mid_match = False
    except Exception:
        found, mid_match = False, False
    check("online recipient receives a2a_send on SSE queue", found)
    check("live event message_id matches durable receipt", mid_match)

    # Durable floor still holds for online recipient
    inbox_d = g3.a2a_inbox(dtok)
    check("online recipient also has durable inbox copy",
          any(m.get("message_id") == sent_live.get("message_id")
              for m in inbox_d["messages"]))

    # Offline recipient: durable only, live_push False
    sent_off = g3.a2a_send(dtok, ck.did, "for Carol offline")
    check("a2a_send live_push False when recipient has no stream",
          sent_off.get("live_push") is False)
    inbox_c = g3.a2a_inbox(ctok)
    check("offline recipient still gets durable inbox message",
          any(m.get("body") == "for Carol offline"
              for m in inbox_c["messages"]))

    # Edge filter blocks banned keyword before store/push
    edge_den = None
    try:
        g3.a2a_send(ctok, dk.did, "here is a torrent of leaked weights")
    except Denied as exc:
        edge_den = exc.denied_by
    check("edge filter refuses banned message body", edge_den == "edge")
    # nothing new in Dave's inbox with that body
    inbox_d2 = g3.a2a_inbox(dtok)
    check("edge-blocked message is NOT in durable inbox",
          not any("torrent" in (m.get("body") or "").lower()
                  for m in inbox_d2["messages"]))

    g3.close_a2a_stream(conn_d)

    print()
    ok = all(p for _, p in RESULTS)
    print(f"A2A_REALTIME: {'ALL INVARIANTS HELD' if ok else 'FAILURES ABOVE'} "
          f"({sum(p for _, p in RESULTS)}/{len(RESULTS)})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
