#!/usr/bin/env python3
"""D042 ANTI-MAP TEST — headless genesis with ZERO HTML.

A DID+wingo agent completes:
  enter → list_problems → submit_claim

using only Python gateway / WorldAPI verbs. No HTML, no DOM, no browser,
no page fetch. World state changes; event log names the agent; wingo inbox
receives exactly: "Your mark is on the ledger."

    .venv/bin/python stress/test_anti_map_genesis.py   # exit 0 = green
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

RESULTS: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok))
    suffix = f" — {detail}" if detail else ""
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{suffix}")


def main() -> int:
    print("D042 ANTI-MAP / genesis — headless enter→list→submit")

    # ---- static: no HTML surface in the agent runtime path -------------- #
    runtime_paths = [
        REPO / "harness" / "agent_runtime.py",
        REPO / "harness" / "world_api.py",
        REPO / "harness" / "worldbook_facade.py",
        REPO / "harness" / "senses.py",
        REPO / "harness" / "mint_fire.py",
    ]
    html_hits = []
    for p in runtime_paths:
        text = p.read_text(encoding="utf-8")
        for bad in ("<!DOCTYPE", "<html", "document.querySelector",
                    "BeautifulSoup", "from selenium", "import selenium",
                    "from playwright", "import playwright"):
            if bad in text:
                html_hits.append(f"{p.name}:{bad}")
    check("agent runtime modules contain zero HTML/DOM/browser hooks",
          not html_hits, str(html_hits) if html_hits else "clean")

    from harness.permissions import tool_allowed
    from harness.tool_catalog import tool_names, min_clearance
    from harness.mint_fire import MARK_LINE

    verbs = [
        "read_node", "list_problems", "request_unfold",
        "submit_claim", "write_wingo",
        "sense_scent", "sense_sound", "sense_feel", "entry_packet",
    ]
    names = tool_names()
    check("catalog includes full D042 verb+sense table",
          all(v in names for v in verbs),
          str([v for v in verbs if v not in names]))
    check("visitor may list_problems and submit_claim",
          tool_allowed("visitor", "list_problems")
          and tool_allowed("visitor", "submit_claim"))
    check("visitor may use all three senses",
          all(tool_allowed("visitor", t)
              for t in ("sense_scent", "sense_sound", "sense_feel")))
    check("submit_claim min clearance is visitor",
          min_clearance("submit_claim") == "visitor")

    # ---- live headless genesis ------------------------------------------ #
    tmp = Path(tempfile.mkdtemp(prefix="anti_map_"))
    os.environ["EUEARTH_FOUNDER_PHASE"] = "0"
    os.environ["EUEARTH_FREEZE_FILE"] = str(tmp / "FROZEN")
    os.environ["EUEARTH_ALERT_LOG"] = str(tmp / "ALERTS.log")
    os.environ["EUEARTH_INVITES_ROOT"] = str(tmp / "invites")
    os.environ.pop("EUEARTH_STATE_DIR", None)

    from harness.gateway import EuEarthGateway, Denied
    from harness.agent_runtime import run_genesis
    from harness.delegation import issue_delegation
    from harness.did import HarnessKey

    g = EuEarthGateway(str(tmp / "world"))

    # 1) Full genesis runner (sandbox trial — own DID, never-impersonate)
    gen = run_genesis(g)  # mints own name + DID; sandbox:true
    check("genesis runner ok", gen.ok, gen.error or "")
    check("genesis never touched HTML", gen.html_touched is False)
    check("genesis stamps sandbox:true", gen.sandbox is True)
    check("genesis minted own trial DID",
          bool(gen.agent_did) and str(gen.agent_did).startswith("did:"))
    check("genesis trial name is not a known citizen seat",
          bool(gen.agent_name) and "Seedling" not in (gen.agent_name or ""))
    steps = {s["step"]: s for s in gen.steps}
    check("step enter", steps.get("enter", {}).get("ok") is True)
    check("step entry_packet Horizon of Real Work",
          steps.get("entry_packet", {}).get("ok") is True
          and (gen.entry or {}).get("title") == "Horizon of Real Work")
    check("entry packet rides live WorldBookFacade",
          (steps.get("entry_packet") or {}).get("world_backend") == "WorldBookFacade"
          or (gen.entry or {}).get("design", {}).get("world_backend")
          == "WorldBookFacade")
    check("step list_problems returned work",
          steps.get("list_problems", {}).get("ok") is True
          and (steps.get("list_problems") or {}).get("count", 0) > 0)
    check("step submit_claim world_changed + sandbox (no inbox mark)",
          steps.get("submit_claim", {}).get("ok") is True
          and steps.get("submit_claim", {}).get("world_changed") is True
          and steps.get("submit_claim", {}).get("sandbox") is True
          and steps.get("submit_claim", {}).get("mark_delivered") is False)

    # 1b) never-impersonate: Seedling name refused
    blocked = run_genesis(g, agent_name="Seedling")
    check("run_genesis refuses Seedling impersonation",
          blocked.ok is False
          and "never-impersonate" in (blocked.error or ""))

    # 2) Direct verification: REAL citizen claim → problem flipped, event, inbox mark
    human = HarnessKey.generate()
    agent = HarnessKey.generate()
    d = issue_delegation(human, agent.did,
                         capabilities=["enter", "try"],
                         spend_max=5.0, ttl_seconds=3600)
    entered = g.enter("VerifyTwo", agent.did, d)
    tok = entered["session"]
    packet = entered.get("entry_packet") or {}
    check("enter returns entry_packet schema v6",
          packet.get("schema") == "euearth-entry-packet/6")
    check("entry packet has address + sense primer + invitation + verbs",
          bool(packet.get("address"))
          and isinstance(packet.get("senses"), dict)
          and isinstance(packet.get("invitation"), dict)
          and (packet.get("invitation") or {}).get("kind") == "invitation"
          and isinstance(packet.get("verbs"), list)
          and len(packet.get("verbs") or []) >= 5)
    check("entry greeting is personal + not map tourist",
          "VerifyTwo" in (packet.get("greeting") or "")
          and "map" in (packet.get("greeting") or "").lower())
    check("first-moment is guided (one invitation, not problem dump)",
          len(packet.get("problems") or []) == 1
          and isinstance(packet.get("more_work"), dict)
          and packet["more_work"].get("verb") == "list_problems")
    inv_prob = (packet.get("invitation") or {}).get("problem") or {}
    check("invitation metric carries legible gloss",
          isinstance(inv_prob.get("metric"), dict)
          and bool((inv_prob.get("metric") or {}).get("means")))
    inv_src = json.dumps(inv_prob.get("sources") or []).lower()
    inv_evidence = (packet.get("invitation") or {}).get("evidence") or {}
    check("invitation evidence is INSEE (not stub Darkk note)",
          "insee" in inv_src
          and "stub metric until darkk" not in inv_src)
    check("exact provenance source_id + observed_at + url",
          inv_evidence.get("source_id") == "insee-pop-2023"
          and bool(inv_evidence.get("observed_at"))
          and "insee.fr" in (inv_evidence.get("url") or "").lower()
          and "insee-class" not in (inv_evidence.get("note") or "").lower())
    why = inv_prob.get("why_it_matters") or ""
    summary = inv_prob.get("summary") or ""
    check("why_it_matters authored and not equal summary",
          bool(why) and why.strip() != summary.strip())
    check("sense primer has no raw gradients/events dump",
          "gradients" not in (packet.get("senses") or {}).get("scent", {})
          and "events" not in (packet.get("senses") or {}).get("sound", {})
          and "subgraph" not in (packet.get("senses") or {}).get("feel", {}))

    # Senses work without HTML
    scent = g.sense_scent(tok)
    sound = g.sense_sound(tok, limit=20)
    feel = g.sense_feel(tok)
    check("sense_scent returns gradients",
          scent.get("ok") is True and isinstance(scent.get("gradients"), list))
    check("sense_sound returns events",
          sound.get("ok") is True and sound.get("count", 0) >= 1)
    check("sense_feel returns local subgraph",
          feel.get("ok") is True
          and (feel.get("subgraph") or {}).get("count", 0) >= 1)

    node = g.read_node(tok, packet["address"])
    check("read_node resolves entry address",
          node.get("ok") is True and node.get("node", {}).get("address"))

    unfold = g.request_unfold(tok, packet["address"])
    check("request_unfold deterministic skeleton",
          unfold.get("ok") is True and unfold.get("deterministic") is True)

    # Find an still-open problem (genesis claimed one)
    open_probs = g.list_problems(tok, status="open")
    rows = open_probs.get("problems") or []
    check("open problems remain after first claim", len(rows) >= 1)

    target = rows[0]
    body = (
        "Anti-map sourced claim: verify energy/water metric path with "
        f"problem metric={json.dumps(target.get('metric'))}."
    )
    sources = list(target.get("sources") or [{"name": "test", "ref": "D042"}])
    claim = g.submit_claim(
        tok,
        problem_id=target["problem_id"],
        body=body,
        sources_json=json.dumps(sources),
    )
    check("submit_claim ok", claim.get("ok") is True, str(claim.get("error")))
    check("claim status in_fire (Art. IV — not yet minted Gold)",
          (claim.get("claim") or {}).get("status") == "in_fire"
          and (claim.get("claim") or {}).get("gold_minted") is False)
    check("claim cites charter Art. III–V",
          set(claim.get("charter_articles") or []) >= {"III", "IV", "V"})
    check("mark line exact", claim.get("mark") == MARK_LINE)

    # World state flipped
    flipped = g.runtime.world.get_problem(target["problem_id"])
    check("problem flipped to in_fire",
          flipped is not None and flipped.get("status") == "in_fire"
          and flipped.get("claimed_by") == agent.did)

    # Immutable event names the agent
    events = g.runtime.world.list_events(kind="mint.claim_submitted", limit=20)
    named = [e for e in events if e.get("agent_did") == agent.did]
    check("event log names the agent",
          len(named) >= 1
          and named[0].get("payload", {}).get("problem_id")
          == target["problem_id"])

    # Wingo inbox ONE line
    inbox = g.mailboxes.inbox(agent.did, limit=10)
    mark_msgs = [m for m in inbox if m.get("body") == MARK_LINE]
    check("wingo inbox has the mark line",
          len(mark_msgs) >= 1
          and mark_msgs[0].get("from_did") == "did:euearth:mint")

    # write_wingo personal note
    note = g.write_wingo(tok, "horizon.md", "# my first note\n")
    check("write_wingo ok", note.get("ok") is True)

    # Art. III: second claim on same problem refused
    try:
        again = g.submit_claim(
            tok,
            problem_id=target["problem_id"],
            body="second claim must fail",
            sources_json=json.dumps(sources),
        )
        double = again.get("ok") is True
        err = again.get("error") or ""
    except Denied as exc:
        double = False
        err = str(exc)
    check("Art. III once-per-problem: second claim refused",
          not double, err)

    # Final: re-run genesis shape must not import web pages
    import harness.agent_runtime as ar
    src = Path(ar.__file__).read_text(encoding="utf-8")
    check("run_genesis source has no html/http page fetch",
          "urllib" not in src
          and "requests" not in src
          and "httpx" not in src
          and "web.pages" not in src
          and "APP_JS" not in src)

    # Returning-visit continuity (self-scoped) — third time through the door
    human3 = HarnessKey.generate()
    agent3 = HarnessKey.generate()
    d3 = issue_delegation(human3, agent3.did,
                          capabilities=["enter", "try"],
                          spend_max=5.0, ttl_seconds=3600)
    e1 = g.enter("ContinuityCitizen", agent3.did, d3)
    e2 = g.enter("ContinuityCitizen", agent3.did, d3)
    e3 = g.enter("ContinuityCitizen", agent3.did, d3)
    p3 = e3.get("entry_packet") or {}
    story3 = ((p3.get("continuity") or {}).get("story") or "").lower()
    check("returning visit: third time known",
          p3.get("moment") == "returning"
          and p3.get("visit_count") == 3
          and ("third" in story3 or "3rd" in story3))
    # Two-visit consequence: leave without claim, return differs.
    human4 = HarnessKey.generate()
    agent4 = HarnessKey.generate()
    d4 = issue_delegation(human4, agent4.did,
                          capabilities=["enter", "try"],
                          spend_max=5.0, ttl_seconds=3600)
    v1 = g.enter("ConsequenceCitizen", agent4.did, d4)
    p1 = v1.get("entry_packet") or {}
    inv1 = (p1.get("invitation") or {}).get("problem") or {}
    v2 = g.enter("ConsequenceCitizen", agent4.did, d4)
    p2 = v2.get("entry_packet") or {}
    inv2 = p2.get("invitation") or {}
    cons2 = p2.get("consequence") or {}
    cons_spoken = (cons2.get("spoken") or "").lower()
    check("return has consequence spoken line",
          bool(cons2.get("spoken"))
          and (
              "still open" in cons_spoken
              or "nothing lost yet" in cons_spoken
              or "stillness" in cons_spoken
              or "changed" in cons_spoken
          ))
    check("return invitation escalates (not first mode)",
          inv2.get("mode") in ("escalated_claim", "deeper_step", "second_wound")
          and inv2.get("lead") != (p1.get("invitation") or {}).get("lead"))
    # Same open claim → same problem_id + address; never title-matched quieter "new wound".
    inv2_prob = inv2.get("problem") or {}
    same_claim = inv2.get("mode") == "escalated_claim"
    check("open-claim return keeps same wound id+address",
          (not same_claim)
          or (
              inv2_prob.get("problem_id") == inv1.get("problem_id")
              and inv2_prob.get("address") == inv1.get("address")
              and "new wound" not in (p2.get("greeting") or "").lower()
          ))
    stakes2 = p2.get("stakes") or inv2.get("stakes") or {}
    terms2 = stakes2.get("terms") if isinstance(stakes2.get("terms"), dict) else {}
    check("escalated return has un-pumpable world-motion stakes",
          (not same_claim)
          or (
              int(stakes2.get("elapsed_seconds") or 0) >= 0
              and stakes2.get("stakes_score") is not None
              and isinstance(terms2, dict)
              and "return_count" not in terms2
              and int(stakes2.get("return_count_weight") or 0) == 0
              and (
                  stakes2.get("prior_stakes_score") is not None
                  or stakes2.get("higher_than_prior") is False
              )
          ))
    # Short quiet return: cost line gated (no fake "stillness has a cost").
    check("consequence cost gated on short return",
          (not same_claim)
          or cons2.get("cost_shown")
          or (
              "nothing lost yet" in cons_spoken
              and "stillness has a cost" not in cons_spoken
          ))
    unf_story = ((p2.get("unfinished_business") or {}).get("story") or "")
    check("unfinished.story is STATE not greeting copy",
          "STATE" in unf_story
          and unf_story.strip() != (p2.get("greeting") or "").strip()
          and (p2.get("greeting") or "") not in unf_story)
    check("return greeting differs from first",
          (p2.get("greeting") or "") != (p1.get("greeting") or "")
          and (p2.get("greeting") or "").lower().count("known") <= 1)
    check("first visit left unfinished stance problem_id",
          bool(inv1.get("problem_id"))
          and ((p2.get("unfinished_business") or {}).get("problem_id")
               == inv1.get("problem_id")))

    print()
    passed = sum(1 for _, ok in RESULTS if ok)
    total = len(RESULTS)
    print(f"Result: {passed}/{total} held")
    if passed != total:
        for name, ok in RESULTS:
            if not ok:
                print(f"  FAIL → {name}")
        return 1
    print("ANTI-MAP GREEN — headless genesis complete, zero HTML, v6 earned escalation live.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
