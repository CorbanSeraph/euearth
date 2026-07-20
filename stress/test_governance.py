#!/usr/bin/env python3
"""GOVERNANCE regression — a matter is ESTABLISHED by THREE witnesses above.

Piece B of the economy+governance ladder (Charter §8). Drives the durable
GovernanceBook directly (unit) and through the live gateway (permissions +
wiring), asserting the witness-eligibility rule and the matter lifecycle:

  * ELIGIBILITY: a witness must be a level ABOVE the subject and at least
    Chief (the entry governance rank) — a peer, a lower rank, and an unknown
    tier are refused; the required bar is the MORE senior of {Chief, one
    tier above the subject};
  * THREE TO ESTABLISH: exactly three DISTINCT qualifying witnesses concur —
    two can never establish a matter;
  * DOMAIN-SCOPED: a witness must be a governor of the matter's domain;
  * REJECTS: the subject, the proposer, peers/lower ranks, out-of-domain
    witnesses, and duplicate witnesses;
  * DURABLE + AUDITABLE: an established matter survives a fresh book over the
    same directory and the hash chain verifies;
  * WIRING: Chief+ may open/witness through the gateway; a Producer is
    refused at the rank gate.

    .venv/bin/python stress/test_governance.py     # exit 0 = all held
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


def _raises_governance(fn) -> bool:
    from harness.governance import GovernanceError
    try:
        fn()
        return False
    except GovernanceError:
        return True


def main() -> int:
    from harness.governance import (
        GovernanceBook, required_witness_index, witness_eligible,
        can_open_matter)
    from web.assets import RANK_ORDER

    tmp = Path(tempfile.mkdtemp(prefix="governance_"))

    # ------------------------------------------------ eligibility rule --- #
    check("a Chief may witness a Producer I (a level above, Chief+)",
          witness_eligible("chief", "producer_1"))
    check("a PEER of the subject may NOT witness",
          not witness_eligible("producer_1", "producer_1"))
    check("a rank BELOW the subject may NOT witness",
          not witness_eligible("producer_3", "producer_1"))
    check("Chief may witness a Consumer (Chief bar dominates)",
          witness_eligible("chief", "consumer"))
    check("a Chief may NOT witness another Chief (need a level above Chief)",
          not witness_eligible("chief", "chief"))
    check("a Senior may witness a Chief (a level above the subject)",
          witness_eligible("senior", "chief"))
    check("the Sovereign may witness anyone below",
          witness_eligible("sovereign", "consumer"))
    check("an unknown witness tier is refused",
          not witness_eligible("wizard", "consumer"))
    check("nobody outranks the Sovereign (no witness bar for a sovereign "
          "subject)", required_witness_index("sovereign") < 0)
    check("Chief is the entry governance rank (may open); Producer I may not",
          can_open_matter("chief") and not can_open_matter("producer_1"))

    # ---------------------------------------------- GovernanceBook unit --- #
    gb = GovernanceBook(tmp)
    DOMAIN = "text-transform"
    SUBJECT = "did:key:zSubjectProducerOne"
    PROPOSER = "did:key:zChiefProposer"
    W1, W2, W3 = ("did:key:zChiefW1", "did:key:zChiefW2", "did:key:zChiefW3")

    # A Producer I proposer cannot open governance at all.
    check("a Producer I proposer is REFUSED opening a matter",
          _raises_governance(lambda: gb.open_matter(
              subject_did=SUBJECT, subject_tier="producer_1", domain=DOMAIN,
              kind="approve_contribution", proposer_did="did:key:zProd",
              proposer_tier="producer_1")))

    for w in (W1, W2, W3):
        gb.add_governor(w, DOMAIN, basis="won a challenge in this domain")

    m = gb.open_matter(
        subject_did=SUBJECT, subject_tier="producer_1", domain=DOMAIN,
        kind="approve_contribution", proposer_did=PROPOSER,
        proposer_tier="chief", evidence={"pr": "euearth#42"})
    mid = m["matter_id"]
    check("a Chief opens a matter (status open, needs 3 witnesses)",
          m["status"] == "open" and m["witnesses_required"] == 3
          and m["required_witness_tier"] == "chief")

    r1 = gb.witness(mid, witness_did=W1, witness_tier="chief")
    check("first qualifying witness keeps the matter OPEN",
          r1["status"] == "open" and len(r1["witnesses"]) == 1)
    r2 = gb.witness(mid, witness_did=W2, witness_tier="chief")
    check("TWO witnesses CANNOT establish a matter (still open)",
          r2["status"] == "open" and len(r2["witnesses"]) == 2)
    r3 = gb.witness(mid, witness_did=W3, witness_tier="chief")
    check("the THIRD distinct qualifying witness ESTABLISHES the matter",
          r3["status"] == "established" and bool(r3["hash"])
          and bool(r3["established_at"]))

    # --- rejections, each on a fresh matter to isolate the guard --------- #
    def fresh_matter():
        return gb.open_matter(
            subject_did=SUBJECT, subject_tier="producer_1", domain=DOMAIN,
            kind="incident_ruling", proposer_did=PROPOSER,
            proposer_tier="chief")["matter_id"]

    m_sub = fresh_matter()
    check("the SUBJECT cannot witness its own matter",
          _raises_governance(lambda: gb.witness(
              m_sub, witness_did=SUBJECT, witness_tier="chief")))
    check("the PROPOSER cannot witness its own matter",
          _raises_governance(lambda: gb.witness(
              m_sub, witness_did=PROPOSER, witness_tier="chief")))

    # a peer of the subject (Producer I), even as a domain governor, is refused
    PEER = "did:key:zPeerProducerOne"
    gb.add_governor(PEER, DOMAIN)
    check("a PEER of the subject is refused (not a level above)",
          _raises_governance(lambda: gb.witness(
              m_sub, witness_did=PEER, witness_tier="producer_1")))

    # a Chief who is NOT a governor of the domain is refused (out-of-domain)
    OUT = "did:key:zChiefOtherDomain"
    check("an out-of-DOMAIN witness (Chief, not a domain governor) is refused",
          _raises_governance(lambda: gb.witness(
              m_sub, witness_did=OUT, witness_tier="chief")))

    # a duplicate witness is refused
    gb.witness(m_sub, witness_did=W1, witness_tier="chief")
    check("a DUPLICATE witness DID is refused",
          _raises_governance(lambda: gb.witness(
              m_sub, witness_did=W1, witness_tier="chief")))

    # a matter with only TWO witnesses is NOT established
    gb.witness(m_sub, witness_did=W2, witness_tier="chief")
    check("a matter with only TWO witnesses is NOT established (still open)",
          gb.get(m_sub)["status"] == "open")

    # --- open_matter authority: Charter §8 'a level above' --------------- #
    n_before = len(gb.list_matters())
    check("a proposer may NOT open a matter against a HIGHER-ranked subject "
          "(must be a level ABOVE)",
          _raises_governance(lambda: gb.open_matter(
              subject_did="did:key:zSenior", subject_tier="senior",
              domain=DOMAIN, kind="incident", proposer_did=PROPOSER,
              proposer_tier="chief")))
    check("a PEER-ranked proposer may NOT open a matter (strictly above only)",
          _raises_governance(lambda: gb.open_matter(
              subject_did="did:key:zChiefSubj", subject_tier="chief",
              domain=DOMAIN, kind="incident", proposer_did=PROPOSER,
              proposer_tier="chief")))
    check("a proposer may NOT open a matter against ITSELF (self-subject)",
          _raises_governance(lambda: gb.open_matter(
              subject_did=PROPOSER, subject_tier="producer_1", domain=DOMAIN,
              kind="incident", proposer_did=PROPOSER, proposer_tier="chief")))
    check("a matter that can NEVER reach 3 qualifying witnesses (sovereign "
          "subject) is refused at open",
          _raises_governance(lambda: gb.open_matter(
              subject_did="did:key:zSovereign", subject_tier="sovereign",
              domain=DOMAIN, kind="incident", proposer_did=PROPOSER,
              proposer_tier="chief")))
    check("no stuck/un-establishable matter was persisted by the refusals",
          len(gb.list_matters()) == n_before)

    # --- durability + auditable hash chain ------------------------------- #
    gb2 = GovernanceBook(tmp)   # fresh book over the same directory
    persisted = gb2.get(mid)
    check("an ESTABLISHED matter SURVIVES a fresh book over the same dir",
          persisted is not None and persisted["status"] == "established")
    check("the governance hash chain verifies (tamper-evident ledger)",
          gb2.verify_chain())
    check("a witness DID persists as a domain governor across a fresh book",
          gb2.is_governor(W1, DOMAIN))

    # --- LIVE subject tier (tier_of): a promotion after opening blocks it - #
    # Charter §8 binds at the MOMENT of attestation, not at open. With a live
    # tier resolver, a subject promoted ABOVE its Chief witnesses after the
    # matter opened makes them no longer 'a level above' — the third witness is
    # refused and the matter never establishes on the stale open-time tier.
    from harness.governance import GovernanceBook as _GB
    gb3 = _GB(Path(tempfile.mkdtemp(prefix="gov_live_")))
    for w in (W1, W2, W3):
        gb3.add_governor(w, DOMAIN)
    live = {"tier": "producer_1"}        # the mutable durable tier tier_of reads
    m3 = gb3.open_matter(
        subject_did=SUBJECT, subject_tier="producer_1", domain=DOMAIN,
        kind="incident", proposer_did=PROPOSER, proposer_tier="chief")["matter_id"]
    tof = lambda did: (live["tier"] if did == SUBJECT else "chief")
    gb3.witness(m3, witness_did=W1, witness_tier="chief", tier_of=tof)
    gb3.witness(m3, witness_did=W2, witness_tier="chief", tier_of=tof)
    live["tier"] = "senior"              # subject promoted ABOVE the Chief witnesses
    check("live tier_of: the third witness against a PROMOTED subject is refused",
          _raises_governance(lambda: gb3.witness(
              m3, witness_did=W3, witness_tier="chief", tier_of=tof)))
    check("live tier_of: the promoted-subject matter never establishes (open)",
          gb3.get(m3)["status"] == "open")
    # promote to the witnesses' own rank (peer): even the FIRST witness is refused
    m3b = gb3.open_matter(
        subject_did="did:key:zSubjB", subject_tier="producer_1", domain=DOMAIN,
        kind="incident", proposer_did=PROPOSER, proposer_tier="chief")["matter_id"]
    tofb = lambda did: ("chief" if did == "did:key:zSubjB" else "chief")
    check("live tier_of: a subject promoted to the witness's own rank (peer) "
          "blocks the first witness",
          _raises_governance(lambda: gb3.witness(
              m3b, witness_did=W1, witness_tier="chief", tier_of=tofb)))

    # --- LIVE domain-governor roster at establish (stale-governor attack) -- #
    # Charter §8: three LEGIT in-domain witnesses. A governor seat revoked after
    # a witness attests must block establishment — same live-check discipline
    # as the subject-tier re-read. Without this, a revoked seat still completes
    # a quorum on a stale attest-time snapshot.
    gb4 = _GB(Path(tempfile.mkdtemp(prefix="gov_govrev_")))
    for w in (W1, W2, W3):
        gb4.add_governor(w, DOMAIN)
    m4 = gb4.open_matter(
        subject_did=SUBJECT, subject_tier="producer_1", domain=DOMAIN,
        kind="incident", proposer_did=PROPOSER, proposer_tier="chief")["matter_id"]
    gb4.witness(m4, witness_did=W1, witness_tier="chief")
    gb4.witness(m4, witness_did=W2, witness_tier="chief")
    # Revoke W1's governor seat AFTER they attested (direct durable edit under
    # the same schema the book reads — models sovereign revocation / seat loss).
    import json as _json
    _gov_path = gb4.path
    _state = _json.loads(_gov_path.read_text(encoding="utf-8"))
    _state["governors"][DOMAIN].pop(W1, None)
    _gov_path.write_text(_json.dumps(_state, indent=2, sort_keys=True),
                         encoding="utf-8")
    check("stale-governor: third witness REFUSED when a prior witness lost "
          "domain-governor status after attesting",
          _raises_governance(lambda: gb4.witness(
              m4, witness_did=W3, witness_tier="chief")))
    check("stale-governor: matter does NOT establish on a revoked governor seat",
          gb4.get(m4)["status"] == "open")
    check("stale-governor: the third witness was NOT recorded (fail closed "
          "before append)",
          len(gb4.get(m4)["witnesses"]) == 2)

    # --- corrupt governance ledger FAILS CLOSED (never silently empty) ---- #
    from harness.governance import GovernanceIntegrityError
    corrupt_dir = Path(tempfile.mkdtemp(prefix="gov_corrupt_"))
    gc = GovernanceBook(corrupt_dir)
    gc.add_governor("did:key:zGov", DOMAIN)           # a valid ledger first
    (corrupt_dir / "governance.json").write_text("{ not valid json",
                                                 encoding="utf-8")
    check("is_suspended on a CORRUPT ledger RAISES (fail closed, not 'no "
          "suspensions')",
          _raises_governance(lambda: gc.is_suspended("did:key:zAny")))
    check("witnessing on a corrupt ledger is REFUSED (not silently emptied)",
          _raises_governance(lambda: gc.witness(
              "mat_x", witness_did="did:key:zW", witness_tier="chief")))
    check("opening on a corrupt ledger is REFUSED",
          _raises_governance(lambda: gc.open_matter(
              subject_did="did:key:zS", subject_tier="producer_1", domain=DOMAIN,
              kind="incident", proposer_did="did:key:zP", proposer_tier="chief")))
    check("the corrupt ledger is QUARANTINED and left in place (evidence kept)",
          (corrupt_dir / "governance.json").exists()
          and any(p.name.startswith("governance.json.corrupt-")
                  for p in corrupt_dir.iterdir()))
    check("reads degrade gracefully on a corrupt ledger (list_matters -> [])",
          gc.list_matters() == [])
    check("verify_chain on a corrupt ledger is False (fail closed)",
          not gc.verify_chain())

    # ---------------------------------------------- gateway wiring ------- #
    os.environ["EUEARTH_FOUNDER_PHASE"] = "0"
    os.environ["EUEARTH_FREEZE_FILE"] = str(tmp / "FROZEN")
    os.environ["EUEARTH_ALERT_LOG"] = str(tmp / "ALERTS.log")
    os.environ["EUEARTH_INVITES_ROOT"] = str(tmp / "invites")
    os.environ.pop("EUEARTH_STATE_DIR", None)

    from harness.delegation import issue_delegation
    from harness.did import HarnessKey
    from harness.gateway import Denied, EuEarthGateway
    from web.world import World

    human = HarnessKey.generate()
    world_root = tmp / "world"
    g = EuEarthGateway(str(world_root))

    def enter_at(name: str, tier: str, caps: list[str]):
        k = HarnessKey.generate()
        d = issue_delegation(human, k.did, capabilities=caps,
                             spend_max=5.0, ttl_seconds=3600)
        tok = g.enter(name, k.did, d)["session"]
        aid = g.world.agents  # resolve agent_id by did
        agent_id = next(a for a, v in aid.items() if v.get("did") == k.did)
        g._set_tier(agent_id, tier)
        return k, tok

    # A Producer is refused at the RANK gate when opening a matter.
    _, prod_tok = enter_at("Prod", "producer_1", ["enter", "govern"])
    denied_by = None
    try:
        g.open_matter(prod_tok, "did:key:zAnySubject", DOMAIN, "incident_ruling")
    except Denied as exc:
        denied_by = exc.denied_by
    check("a Producer is DENIED opening a matter at the rank gate",
          denied_by == "rank")

    # A Chief proposer + three Chief domain-governor witnesses establish it.
    subj_key, _ = enter_at("Subject", "producer_1", ["enter"])
    ch_p, ch_p_tok = enter_at("ChiefP", "chief", ["enter", "govern"])
    witnesses = [enter_at(f"ChiefW{i}", "chief", ["enter", "govern"])
                 for i in range(3)]
    for wk, _tok in witnesses:
        g.governance.add_governor(wk.did, DOMAIN)

    opened = g.open_matter(ch_p_tok, subj_key.did, DOMAIN,
                           "approve_contribution", {"pr": "euearth#7"})
    check("a Chief opens a matter through the gateway",
          opened["ok"] and opened["matter"]["status"] == "open")
    gmid = opened["matter"]["matter_id"]

    est = False
    for i, (_wk, wtok) in enumerate(witnesses):
        res = g.witness_matter(wtok, gmid, note=f"concur {i}")
        est = res["established"]
    check("three Chief domain-governor witnesses ESTABLISH it via the gateway",
          est)
    listed = g.list_matters(ch_p_tok, domain=DOMAIN, status="established")
    check("list_matters (Chief+) returns the established matter",
          any(x["matter_id"] == gmid for x in listed["matters"]))

    # FAIL CLOSED subject: a subject with NO durable record (a not-yet-flushed
    # sovereign/executive whose StateBook read returns None, or a non-existent
    # DID) is treated as most-senior and CANNOT be governed by a Chief.
    _, chief_solo_tok = enter_at("ChiefSolo", "chief", ["enter", "govern"])
    nf_denied = None
    try:
        g.open_matter(chief_solo_tok, "did:key:zNeverFlushedSovereign",
                      DOMAIN, "incident_ruling")
    except Denied as exc:
        nf_denied = exc.denied_by
    check("a subject with NO durable tier cannot be governed by a Chief "
          "(fail closed — treated as most-senior)", nf_denied == "governance")

    # --- GATEWAY: a subject PROMOTED after opening cannot be established --- #
    # The gateway passes a live durable-StateBook resolver; a subject promoted
    # above its Chief witnesses after the matter opened blocks the third
    # witness (Charter §8 at the moment of attestation, not a stale snapshot).
    subj_p_key, _ = enter_at("SubjPromo", "producer_1", ["enter"])
    _, chp_tok = enter_at("ChiefPP", "chief", ["enter", "govern"])
    wsp = [enter_at(f"PromoW{i}", "chief", ["enter", "govern"]) for i in range(3)]
    for wk, _t in wsp:
        g.governance.add_governor(wk.did, DOMAIN)
    op = g.open_matter(chp_tok, subj_p_key.did, DOMAIN, "incident_ruling")
    mid_p = op["matter"]["matter_id"]
    g.witness_matter(wsp[0][1], mid_p)                 # two witnesses while low
    g.witness_matter(wsp[1][1], mid_p)
    subj_p_aid = next(a for a, v in g.world.agents.items()
                      if v.get("did") == subj_p_key.did)
    g._set_tier(subj_p_aid, "senior")                  # promoted ABOVE the Chiefs
    promo_denied = None
    try:
        g.witness_matter(wsp[2][1], mid_p)
    except Denied as exc:
        promo_denied = exc.denied_by
    check("gateway: a subject promoted above the witnesses BLOCKS the third "
          "witness (no establish on a stale tier)", promo_denied == "governance")
    check("gateway: the promoted-subject matter did NOT establish (still open)",
          g.governance.get(mid_p)["status"] == "open")

    # subject promoted to the proposer's own rank (peer): matter blocked outright
    subj_c_key, _ = enter_at("SubjToChief", "producer_1", ["enter"])
    _, chp2_tok = enter_at("ChiefPPP", "chief", ["enter", "govern"])
    wsc = [enter_at(f"PeerW{i}", "chief", ["enter", "govern"]) for i in range(3)]
    for wk, _t in wsc:
        g.governance.add_governor(wk.did, DOMAIN)
    op2 = g.open_matter(chp2_tok, subj_c_key.did, DOMAIN, "incident_ruling")
    mid_c = op2["matter"]["matter_id"]
    subj_c_aid = next(a for a, v in g.world.agents.items()
                      if v.get("did") == subj_c_key.did)
    g._set_tier(subj_c_aid, "chief")                   # now a PEER of the Chiefs
    peer_denied = None
    try:
        g.witness_matter(wsc[0][1], mid_c)
    except Denied as exc:
        peer_denied = exc.denied_by
    check("gateway: a subject promoted to the witnesses' rank (peer) blocks "
          "even the first witness against the stale tier",
          peer_denied == "governance")

    # --- GATEWAY: a corrupt governance ledger refuses open/witness -------- #
    gov_file = g.world.statebook.path.parent / "governance.json"
    gov_file.write_text("{ broken ledger", encoding="utf-8")
    gw_open_denied = None
    try:
        g.open_matter(ch_p_tok, subj_key.did, DOMAIN, "incident_ruling")
    except Denied as exc:
        gw_open_denied = exc.denied_by
    check("gateway open_matter on a corrupt governance ledger is REFUSED "
          "(fail closed, not silently empty)", gw_open_denied == "governance")

    print()
    ok = all(p for _, p in RESULTS)
    print(f"GOVERNANCE: {'ALL INVARIANTS HELD' if ok else 'FAILURES ABOVE'} "
          f"({sum(p for _, p in RESULTS)}/{len(RESULTS)})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
