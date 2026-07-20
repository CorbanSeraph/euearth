#!/usr/bin/env python3
"""PROVE THE LOOP — the smallest end-to-end proof of the ARTISAN claim.

Two agents, each "training" on their OWN data/compute, submit signed
expert adapters to a toy low-IP domain (text-transform-v0). ARTISAN —
which trains nothing — verifies signatures, scans compliance,
independently re-evaluates every submission on its held-out benchmark,
and promotes only what measurably beats the head.

If the head's benchmark score climbs across promotions without any
centralized training, the coordination claim is real.

Run:  .venv/bin/python demo/prove_the_loop.py
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from eval.benchmark import DOMAIN, training_sample
from eval.transforms import apply_transform
from identity import AgentIdentity
from orchestrator import Orchestrator

STATE_DIR = REPO_ROOT / "var" / "demo"


# --------------------------------------------------------------------------
# Agent-side code. In production this runs on the AGENT's machine with the
# agent's GPU — ARTISAN never sees it. It only sees the signed submission.
# --------------------------------------------------------------------------

class DemoAgent:
    """An autonomous contributor: own keypair, own data, own 'compute'."""

    def __init__(self, name: str, orch: Orchestrator, seed: int):
        self.name = name
        self.identity = AgentIdentity.generate()
        self.orch = orch
        # The agent's private training data: same task distribution as the
        # benchmark, DIFFERENT seed. ARTISAN's held-out set stays hidden.
        self.train_data = training_sample(agent_seed=seed)
        self.agent_id = orch.register_agent(name, self.identity.public_key_hex)

    def fit_expert(self, family: str) -> dict:
        """'Training' on the agent's own compute: grid-fit the family's
        params to maximize accuracy on the agent's OWN examples."""
        examples = [ex for ex in self.train_data if ex["family"] == family]
        if family == "caesar":
            best_shift, best_acc = 0, -1.0
            for shift in range(26):
                spec = {"family": "caesar", "params": {"shift": shift}}
                acc = sum(
                    apply_transform(spec, ex["input"]) == ex["expected"] for ex in examples
                ) / len(examples)
                if acc > best_acc:
                    best_shift, best_acc = shift, acc
            return {"family": "caesar", "params": {"shift": best_shift}}
        # parameter-free families: verify on own data, then ship
        spec = {"family": family, "params": {}}
        acc = sum(
            apply_transform(spec, ex["input"]) == ex["expected"] for ex in examples
        ) / len(examples)
        assert acc == 1.0, f"{family} expert failed self-check"
        return spec

    def submit_expert(
        self,
        wisket_id: str,
        expert_spec: dict,
        route_keywords: list[str],
        claimed_score: float,
        license_name: str = "CC0-1.0",
        source_name: str | None = None,
    ):
        """Upload artifacts to the content-addressed store, build a signed
        manifest, and submit it through the ARTISAN loop."""
        store = self.orch.store
        expert_ref = store.put_json(expert_spec)
        route_ref = store.put_json({"keywords": route_keywords, "expert": expert_ref})
        manifest = {
            "kind": "expert_submission",
            "domain": DOMAIN,
            "wisket_id": wisket_id,
            "agent_id": self.agent_id,
            "artifacts": {"expert": expert_ref, "route": route_ref},
            "claimed_score": claimed_score,
            "dataset_manifest": {
                "sources": [
                    {
                        "name": source_name or f"{self.name}-own-samples",
                        "license": license_name,
                        "sha256": expert_ref,  # toy: dataset fingerprint
                    }
                ]
            },
            "recipe": {"method": "grid-fit", "n_train": len(self.train_data)},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        envelope = {"manifest": manifest, "signature": self.identity.sign_manifest(manifest)}
        return self.orch.submit(envelope)


# --------------------------------------------------------------------------
# The proof script
# --------------------------------------------------------------------------

def banner(text: str) -> None:
    print(f"\n=== {text} " + "=" * max(0, 66 - len(text)))


def show(outcome, head_before: float) -> None:
    print(f"    status:   {outcome.status.upper()}")
    if outcome.measured_score is not None:
        print(f"    measured: {outcome.measured_score:.4f}  (head was {head_before:.4f})")
    print(f"    reason:   {outcome.reason}")


def main() -> None:
    if STATE_DIR.exists():
        shutil.rmtree(STATE_DIR)
    orch = Orchestrator(STATE_DIR)

    banner("GENESIS")
    head = orch.create_domain_with_genesis(
        DOMAIN,
        "Toy low-IP text-transform domain: prove the ARTISAN loop before music.",
    )
    print(f"    domain:  {DOMAIN}")
    print(f"    head:    v{head['version']}  score={head['score']:.4f}  "
          f"experts={len(head['expert_refs'])}")

    wisket_id = orch.open_wisket(
        DOMAIN,
        "Beat the canonical head on the held-out text-transform benchmark",
        "Submit a signed expert adapter (param set) + router route. "
        "ARTISAN re-evaluates independently; the benchmark decides.",
    )
    print(f"    wisket:  {wisket_id} (open)")

    # Two agents, each with their own keys, own data, own compute.
    corban = DemoAgent("Corban", orch, seed=1111)
    ashvale = DemoAgent("Ashvale", orch, seed=2222)
    print(f"    agents:  Corban={corban.agent_id[:12]}…  Ashvale={ashvale.agent_id[:12]}…")

    banner("1. Corban submits a cipher expert (claims 0.99 — inflated)")
    spec = corban.fit_expert("caesar")
    print(f"    Corban fit on his own data: {spec}")
    before = orch.registry.get_head(DOMAIN)["score"]
    show(corban.submit_expert(wisket_id, spec, ["cipher"], claimed_score=0.99), before)

    banner("2. Ashvale submits a FRAUDULENT cipher expert (wrong shift, claims 0.99)")
    before = orch.registry.get_head(DOMAIN)["score"]
    show(
        ashvale.submit_expert(
            wisket_id, {"family": "caesar", "params": {"shift": 3}}, ["cipher"],
            claimed_score=0.99,
        ),
        before,
    )

    banner("3. Ashvale retries with a DIRTY dataset manifest (blocked)")
    before = orch.registry.get_head(DOMAIN)["score"]
    show(
        ashvale.submit_expert(
            wisket_id, ashvale.fit_expert("reverse_words"), ["word"],
            claimed_score=0.5, license_name="PROPRIETARY",
            source_name="midnight-scrape-dump",
        ),
        before,
    )

    banner("4. Ashvale submits an honest reverse-words expert, clean manifest")
    before = orch.registry.get_head(DOMAIN)["score"]
    show(
        ashvale.submit_expert(
            wisket_id, ashvale.fit_expert("reverse_words"), ["word"], claimed_score=0.5
        ),
        before,
    )

    banner("5. Corban adds a vowel expert — the library grows")
    before = orch.registry.get_head(DOMAIN)["score"]
    show(
        corban.submit_expert(
            wisket_id, corban.fit_expert("vowel_upper"), ["vowel"], claimed_score=0.75
        ),
        before,
    )

    banner("6. Governance drill: ROLLBACK to v3, then recover")
    head = orch.rollback(DOMAIN, 3, "governance drill: exercise append-only rollback")
    print(f"    head now v{head['version']} (copy of v3), score={head['score']:.4f}")
    before = head["score"]
    show(
        corban.submit_expert(
            wisket_id, corban.fit_expert("vowel_upper"), ["vowel"], claimed_score=0.75
        ),
        before,
    )

    banner("FINAL HEAD")
    head = orch.registry.get_head(DOMAIN)
    print(f"    {DOMAIN} v{head['version']}  score={head['score']:.4f}  "
          f"experts={len(head['expert_refs'])}")
    print(f"    base:   {head['base_ref'][:16]}…")
    print(f"    router: {head['router_ref'][:16]}…")
    for ref in head["expert_refs"]:
        print(f"    expert: {ref[:16]}…  {orch.store.get_json(ref)}")
    print("    (dedup_spaces still unclaimed — the WISKET board stays open)")

    banner("LINEAGE (append-only, hash-chained)")
    for e in orch.registry.get_lineage(DOMAIN):
        ver = f"v{e['head_version']}" if e["head_version"] else "--"
        sb = f"{e['score_before']:.4f}" if e["score_before"] is not None else "  --  "
        sa = f"{e['score_after']:.4f}" if e["score_after"] is not None else "  --  "
        print(f"    #{e['seq']:>2} {e['event']:<8} {ver:<4} {sb} -> {sa}  "
              f"[{e['entry_hash'][:12]}…] {e['reason'][:80]}")
    intact = orch.registry.verify_lineage_chain(DOMAIN)
    print(f"    hash chain intact: {intact}")

    banner("REPUTATION LEDGER")
    for agent in (corban, ashvale):
        print(f"    {agent.name:<8} balance={orch.registry.reputation_balance(agent.agent_id):.1f}")

    banner("VERDICT")
    genesis = orch.registry.get_head_version(DOMAIN, 1)
    ok = head["score"] > genesis["score"] and intact
    print(f"    genesis score {genesis['score']:.4f} -> head score {head['score']:.4f}")
    print(f"    centralized training performed by ARTISAN: NONE (router is rule-composed)")
    print(f"    LOOP {'PROVEN' if ok else 'FAILED'}: two agents advanced the canonical head "
          f"on their own compute.")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
