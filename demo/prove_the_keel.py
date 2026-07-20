#!/usr/bin/env python3
"""PROVE THE KEEL — the socket stays, the engine swaps.

Champion A (Anvil-1, a monolithic single model) holds the text-transform
slot. A user runs requests through the STABLE interface. Challenger B —
the ARTISAN router+expert composite, grown by the EXISTING contribution
loop on an agent's own compute — challenges. The EXISTING eval referee
measures both on the held-out gate set; B wins; the occupant is swapped
ATOMICALLY. The same user request through the same controls now runs on
B. The contract is content-addressed and pinned on every head version,
so "the interface did not change" is verified from registry history —
identical digests, not a promise.

Run:  .venv/bin/python demo/prove_the_keel.py
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from demo.prove_the_loop import DemoAgent          # reuse the agent-side code
from eval.benchmark import DOMAIN
from keel import AnvilOne, ArtisanHeadOccupant, Keel, text_transform_contract
from orchestrator import Orchestrator

STATE_DIR = REPO_ROOT / "var" / "keel_demo"

# The user's fixed request set — expressed ONLY in stable-UI controls.
USER_REQUESTS = [
    {"task": "cipher", "text": "the raven guards the ember throne"},
    {"task": "reverse", "text": "ember forge anvil crown"},
    {"task": "vowels", "text": "granite echo willow"},
    {"task": "spacing", "text": "a character   oak    reed"},
]


def build_world(root: Path):
    """Champion A seated in the keel; challenger B grown by the existing
    inner loop, waiting to challenge. Shared with `python -m keel.ui`."""
    orch = Orchestrator(root)
    contract = text_transform_contract()
    keel = Keel(orch, contract)
    keel.seat_genesis(AnvilOne(contract))

    # Grow challenger B with the EXISTING contribution loop — zero new
    # machinery: genesis, WISKET, signed expert submissions, independent
    # re-eval, promotion. The resulting canonical head becomes ONE
    # contender for the keel slot.
    orch.create_domain_with_genesis(
        DOMAIN, "inner domain: grows the composite that challenges for the keel slot"
    )
    wisket_id = orch.open_wisket(
        DOMAIN, "Grow the composite challenger",
        "Expert adapters promoted here compose the occupant that will "
        "challenge for the keel slot.",
    )
    smith = DemoAgent("Forgesmith", orch, seed=4242)
    for family, keywords in [
        ("caesar", ["cipher"]),
        ("reverse_words", ["word", "flip"]),
        ("vowel_upper", ["vowel"]),
        ("dedup_spaces", ["whitespace", "spacing"]),
    ]:
        outcome = smith.submit_expert(
            wisket_id, smith.fit_expert(family), keywords, claimed_score=0.0
        )
        assert outcome.status == "promoted", f"{family}: {outcome.reason}"

    head = orch.registry.get_head(DOMAIN)
    challenger = ArtisanHeadOccupant(
        contract, orch.store, head, DOMAIN,
        name=f"ARTISAN composite (router + {len(head['expert_refs'])} experts)",
    )
    return keel, {"artisan-composite": challenger}


def banner(text: str) -> None:
    print(f"\n=== {text} " + "=" * max(0, 66 - len(text)))


def run_user_requests(keel: Keel) -> dict[str, str]:
    outputs = {}
    for controls in USER_REQUESTS:
        response = keel.run(controls=controls)
        outputs[controls["task"]] = response["text"]
        print(f"    [{controls['task']:>7}] {controls['text']!r}"
              f"  ->  {response['text']!r}")
    return outputs


def main() -> None:
    if STATE_DIR.exists():
        shutil.rmtree(STATE_DIR)
    keel, challengers = build_world(STATE_DIR)
    challenger = challengers["artisan-composite"]
    contract = keel.contract
    registry = keel.orch.registry
    checks: list[tuple[str, bool]] = []

    banner("THE SOCKET (keel interface contract)")
    print(f"    slot:        {keel.slot_domain}")
    print(f"    contract:    {contract.fingerprint}")
    print(f"    inputs:      {sorted(contract.input_spec)}   "
          f"outputs: {sorted(contract.output_spec)}")
    task_options = [o["value"] for o in contract.controls[0]["options"]]
    print(f"    controls:    task={task_options} + free text field")
    controls_before = json.dumps(contract.to_dict()["controls"], sort_keys=True)

    banner("CHAMPION A HOLDS THE SLOT")
    before = keel.current()
    print(f"    v{before['version']}  {before['name']} [{before['kind']}]  "
          f"measured {before['score']:.4f} on the held-out gate")

    banner("USER RUNS THROUGH THE STABLE INTERFACE (engine: Anvil-1)")
    outputs_a = run_user_requests(keel)

    banner("CHALLENGE — referee is the EXISTING eval harness")
    outcome = keel.challenge(challenger)
    print(f"    status:            {outcome.status.upper()}")
    print(f"    eval decision:     {outcome.reason}")
    print(f"    champion before:   {outcome.champion_before}")
    print(f"    champion after:    {outcome.champion_after}")
    print(f"    slot head:         v{outcome.head_version} (atomic CAS swap)")
    checks.append(("challenger swap happened", outcome.status == "swapped"))

    banner("SAME USER, SAME CONTROLS — engine is now the composite")
    outputs_b = run_user_requests(keel)

    banner("PROOF: the socket never moved")
    v1 = registry.get_head_version(keel.slot_domain, 1)
    v2 = registry.get_head_version(keel.slot_domain, 2)
    same_ref = v1["router_ref"] == v2["router_ref"] == keel.contract_ref
    same_dict = (keel.orch.store.get_json(v1["router_ref"])
                 == keel.orch.store.get_json(v2["router_ref"]))
    controls_after = json.dumps(contract.to_dict()["controls"], sort_keys=True)
    print(f"    contract ref @v1:  {v1['router_ref'][:16]}…")
    print(f"    contract ref @v2:  {v2['router_ref'][:16]}…")
    print(f"    identical digest across the swap:   {same_ref}")
    print(f"    identical contract JSON:            {same_dict}")
    print(f"    identical control surface:          {controls_before == controls_after}")
    checks.append(("contract digest identical across swap", same_ref))
    checks.append(("contract JSON identical across swap", same_dict))
    checks.append(("control surface identical", controls_before == controls_after))
    checks.append(("engine actually changed",
                   outcome.champion_before != outcome.champion_after))
    checks.append(("cipher output stable (both engines know it)",
                   outputs_a["cipher"] == outputs_b["cipher"]))
    checks.append(("reverse output IMPROVED behind the same controls",
                   outputs_a["reverse"] != outputs_b["reverse"]
                   and outputs_b["reverse"] == "crown anvil forge ember"))
    checks.append(("vowels output IMPROVED behind the same controls",
                   outputs_b["vowels"] == "grAnItE EchO wIllOw"))

    banner("THE DETHRONED CHAMPION TRIES TO RETAKE THE SLOT")
    retake = keel.challenge(AnvilOne(contract))
    print(f"    status:  {retake.status.upper()}")
    print(f"    reason:  {retake.reason}")
    checks.append(("referee gates both directions", retake.status == "rejected"))

    banner("SLOT LEADERBOARD (who held the socket)")
    for row in keel.leaderboard():
        crown = "  <- reigning" if row["reigning"] else ""
        print(f"    v{row['version']}  {row['name']:<42} [{row['kind']}]  "
              f"{row['score']:.4f}{crown}")

    banner("SLOT LINEAGE (append-only, hash-chained)")
    for e in keel.lineage():
        ver = f"v{e['head_version']}" if e["head_version"] else "--"
        print(f"    #{e['seq']:>2} {e['event']:<8} {ver:<4} "
              f"[{e['entry_hash'][:12]}…] {e['reason'][:88]}")
    intact = registry.verify_lineage_chain(keel.slot_domain)
    print(f"    hash chain intact: {intact}")
    checks.append(("lineage hash chain intact", intact))

    banner("VERDICT")
    ok = all(passed for _, passed in checks)
    for label, passed in checks:
        print(f"    [{'PASS' if passed else 'FAIL'}] {label}")
    print(f"    KEEL {'PROVEN' if ok else 'FAILED'}: the engine swapped "
          f"({outcome.champion_before} -> {outcome.champion_after}); the "
          f"interface and controls did not change.")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
