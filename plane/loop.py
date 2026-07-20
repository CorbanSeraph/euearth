"""The plane orchestrator — the REAL loop over real tensors.

    signed manifest (tensors already in the blob store)
      -> Ed25519 verify against the REGISTERED key
      -> Sybil economics: eval fee charged BEFORE any GPU spins
      -> compliance scan (dataset/license manifest vs policy)
      -> static ABI check (base fingerprint, rank, targets, dtype)
      -> sandboxed tensor validation (subprocess, no torch, rlimits)
      -> router refit over head experts + candidate (HARD budget, METERED)
      -> sealed paired eval: incumbent vs candidate on a FRESH shard
      -> confidence-bound + per-capability gates
      -> atomic CAS promotion (or reject; fraud slash if claims inflated)
      -> submitter receives COARSE feedback only

Reuses the MVP's registry/store/identity/compliance unchanged — this is
the layer the council said was real; the plane bolts the hard part on.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from compliance import load_policy, scan_manifest
from identity.keys import canonical_json, verify_manifest
from registry import CASConflict, Registry
from store import LocalFSBlobStore

from plane.abi import check_manifest_abi, sandbox_validate
from plane.evalplane import (AUDIT_SHARD_N, EVAL_SHARD_N, coarse_feedback,
                             draw_shard, load_or_create_secret, paired_gate)
from plane.meter import Meter
from plane.router import (BLEND_ARM, FieldMergeRouter, PresenceMergeRouter, Router,
                          feature_fingerprint, load_router, refit_field_router,
                          refit_presence_router, refit_router, refit_soft_router,
                          route_and_generate)
from plane import model_ops

# --- Sybil economics (council: Ed25519 alone = free identities). -------
# In production the bond is real money or proof-of-work bound to the key;
# here it is ledger units, but the MECHANISM is live: no balance, no eval.
REGISTRATION_BOND = 25.0
EVAL_FEE = 5.0            # charged per submission BEFORE evaluation
PROMOTE_REWARD = 10.0
FRAUD_SLASH = 15.0
FRAUD_TOLERANCE = 0.25    # claimed pass-rate may exceed measured by this

ROUTER_BUDGET_SECONDS = 240.0
ROUTER_FIT_POOL_N = 160


@dataclass
class PlaneOutcome:
    submission_id: str
    status: str
    reason: str                       # internal; NOT returned to submitters
    coarse: dict                      # what the submitter actually sees
    head_version: int | None = None
    internal: dict = field(default_factory=dict)


class PlaneOrchestrator:
    def __init__(self, root: str | Path, model_dir: str | Path,
                 meter: Meter | None = None, device: str | None = None,
                 router_budget_s: float = ROUTER_BUDGET_SECONDS,
                 eval_shard_n: int = EVAL_SHARD_N,
                 fit_pool_n: int = ROUTER_FIT_POOL_N,
                 sandbox_python: str | None = None,
                 router_kind: str = "soft"):
        root = Path(root)
        self.store = LocalFSBlobStore(root / "blobs")
        self.registry = Registry(root / "registry.sqlite3")
        self.policy = load_policy(None)
        self.meter = meter or Meter()
        self.secret = load_or_create_secret(root / "eval_secret")
        self.device = device or model_ops.pick_device()
        self.model_dir = str(model_dir)
        self.router_budget_s = router_budget_s
        self.eval_shard_n = eval_shard_n
        self.fit_pool_n = fit_pool_n
        self.sandbox_python = sandbox_python
        self.router_kind = router_kind   # "soft" (v2) | "logistic" (v1)

        self.tok = model_ops.load_tokenizer(self.model_dir)
        self.base = model_ops.load_base(self.model_dir, self.device)
        self._peft = None            # PeftModel carrying loaded experts
        self._loaded: set = set()    # adapter names currently attached
        # DRY-RUN ONLY: "always" forces the promote path so CAS/lineage
        # mechanics can be exercised with a meaningless tiny model. Any
        # promotion made this way is loudly marked in lineage.
        self.gate_override: str | None = None

    # ------------------------------------------------------------ agents

    def register_agent(self, name: str, public_key_hex: str) -> str:
        agent_id = self.registry.register_agent(name, public_key_hex)
        if self.registry.reputation_balance(agent_id) == 0:
            self.registry.add_reputation_event(agent_id, REGISTRATION_BOND, "bond", None)
        return agent_id

    # ----------------------------------------------------------- serving

    def _serving_model(self):
        return self._peft if self._peft is not None else self.base

    def _ensure_expert(self, name: str, blob: bytes):
        if name in self._loaded:
            return
        self._drop_blend()
        if self._peft is None:
            self._peft = model_ops.attach_adapters(self.base, self.pin, {name: blob})
        else:
            from peft import set_peft_model_state_dict
            from safetensors.torch import load as st_load
            self._peft.add_adapter(name, model_ops.lora_config(self.pin))
            set_peft_model_state_dict(self._peft, st_load(blob), adapter_name=name)
            self._peft.eval()
        self._loaded.add(name)

    def _drop_blend(self):
        if self._peft is not None and BLEND_ARM in getattr(self._peft, "peft_config", {}):
            self._peft.delete_adapter(BLEND_ARM)

    def _serve(self, router: Router, expert_names: list, items: list) -> tuple:
        self._drop_blend()
        return route_and_generate(self._serving_model(), self.tok, router,
                                  items, self.device, expert_names)

    # ----------------------------------------------------------- genesis

    def genesis(self, domain: str, description: str, pin: dict) -> dict:
        """Create the domain with the hash-pinned base and a base-only
        router, scored honestly on a sealed shard."""
        self.pin = pin
        self.registry.create_domain(domain, description)
        head = self.registry.get_head(domain)
        if head:
            return head
        base_ref = self.store.put_json(pin)
        self.feat_fp = feature_fingerprint(pin)
        if self.router_kind == "presence":
            router = PresenceMergeRouter.base_only(self.feat_fp)
        elif self.router_kind == "field":
            router = FieldMergeRouter.base_only(self.feat_fp)
        else:
            router = Router.trivial(pin["hidden_size"])
        router_ref = self.store.put_json(router.to_json())
        shard = draw_shard(self.secret, domain, "eval", 0, self.eval_shard_n)
        with self.meter.phase("genesis_eval", "artisan",
                              f"base-only score on sealed shard n={len(shard)}") as ph:
            outputs, stats = self._serve(router, [], shard)
            ph.tokens = stats["generated_tokens"]
        from plane.domain import aggregate, score_item
        agg = aggregate(shard, [score_item(it, o) for it, o in zip(shard, outputs)])
        version = self.registry.insert_head(domain, base_ref, router_ref, [],
                                            agg["pass_rate"], None)
        self.registry.append_lineage(
            domain, "GENESIS", version, None, None, None, agg["pass_rate"],
            f"genesis: pinned base {pin['repo']}@{pin['revision'][:12]} "
            f"fingerprint {pin['fingerprint'][:12]}, base-only router, "
            f"sealed-shard pass rate {agg['pass_rate']:.4f}",
        )
        return self.registry.get_head(domain)

    # -------------------------------------------------------------- loop

    def submit_adapter(self, envelope: dict) -> PlaneOutcome:
        manifest = envelope.get("manifest") or {}
        signature = envelope.get("signature", "")
        domain = manifest.get("domain", "")
        agent_id = manifest.get("agent_id", "")
        claimed = manifest.get("claimed_score")
        manifest_json = canonical_json(manifest).decode()

        def finish(sub_id, status, reason, head_version=None, internal=None,
                   band="fail_low"):
            self.registry.update_submission(sub_id, status, None, reason)
            return PlaneOutcome(sub_id, status, reason,
                                coarse_feedback(status, band), head_version,
                                internal or {})

        # 1. identity — key comes from the registry, never the envelope.
        agent = self.registry.get_agent(agent_id)
        if agent is None or not verify_manifest(agent["public_key"], manifest, signature):
            sub_id = self.registry.create_submission(
                manifest.get("wisket_id"), domain, agent_id, manifest_json,
                signature, claimed)
            return finish(sub_id, "rejected_signature",
                          "unknown agent" if agent is None else "bad signature")

        sub_id = self.registry.create_submission(
            manifest.get("wisket_id"), domain, agent_id, manifest_json,
            signature, claimed)

        head = self.registry.get_head(domain)
        if head is None:
            return finish(sub_id, "rejected", f"unknown domain: {domain}")
        if not hasattr(self, "pin"):
            self.pin = self.store.get_json(head["base_ref"])

        # 2. Sybil economics: the eval fee is charged BEFORE any GPU work.
        if self.registry.reputation_balance(agent_id) < EVAL_FEE:
            return finish(sub_id, "rejected",
                          "insufficient stake: evaluation requires a funded bond")
        self.registry.add_reputation_event(agent_id, -EVAL_FEE, "eval_fee", sub_id)

        # 3. compliance.
        comp = scan_manifest(manifest, self.policy)
        if not comp.ok:
            reason = "compliance block: " + "; ".join(comp.violations)
            self.registry.append_lineage(domain, "REJECT", None, sub_id, agent_id,
                                         head["score"], None, reason)
            return finish(sub_id, "blocked_compliance", reason)

        # 4. static ABI check against the pinned base.
        problem = check_manifest_abi(manifest.get("abi") or {}, self.pin)
        if problem:
            self.registry.append_lineage(domain, "REJECT", None, sub_id, agent_id,
                                         head["score"], None, problem)
            return finish(sub_id, "rejected", problem)

        expert_ref = (manifest.get("artifacts") or {}).get("expert")
        if not expert_ref or not self.store.has(expert_ref):
            return finish(sub_id, "rejected", "expert artifact missing from store")
        adapter_bytes = self.store.get(expert_ref)

        # 5. sandboxed tensor validation (subprocess; tensors never touch
        #    the serving process or GPU unless they pass).
        with self.meter.phase("sandbox_validate", "artisan", f"sub {sub_id}"):
            verdict = sandbox_validate(adapter_bytes, self.pin,
                                       self.policy.get("max_artifact_bytes", 1 << 28),
                                       python_exe=self.sandbox_python)
        if not verdict.ok:
            reason = f"adapter failed sandbox validation: {verdict.reason}"
            self.registry.append_lineage(domain, "REJECT", None, sub_id, agent_id,
                                         head["score"], None, reason)
            return finish(sub_id, "rejected", reason)

        # 6. assemble candidate = head experts + this expert.
        expert_name = expert_ref[:12]
        for ref in head["expert_refs"]:
            self._ensure_expert(ref[:12], self.store.get(ref))
        self._ensure_expert(expert_name, adapter_bytes)
        cand_experts = [r[:12] for r in head["expert_refs"]] + [expert_name]

        # 7. router refit under a HARD budget — ARTISAN's central job,
        #    metered in GPU-seconds and dollars.
        event_no = len(self.registry.get_lineage(domain)) + 1
        fit_pool = draw_shard(self.secret, domain, "routerfit", event_no,
                              self.fit_pool_n)
        if not hasattr(self, "feat_fp"):
            self.feat_fp = feature_fingerprint(self.pin)
        refit_fn = {"soft": refit_soft_router, "logistic": refit_router,
                    "field": refit_field_router,
                    "presence": refit_presence_router}[self.router_kind]
        kw = ({"feat_fp": self.feat_fp}
              if self.router_kind in ("field", "presence") else {})
        with self.meter.phase("router_refit", "artisan",
                              f"sub {sub_id}: {len(cand_experts)} experts "
                              f"({self.router_kind})") as ph:
            router, refit_stats = refit_fn(
                self._serving_model(), self.tok, cand_experts, fit_pool,
                self.device, self.router_budget_s, seed=event_no, **kw)
            ph.tokens = refit_stats["generated_tokens"]

        # 8. sealed paired eval on a FRESH shard: incumbent vs candidate.
        shard = draw_shard(self.secret, domain, "eval", event_no, self.eval_shard_n)
        inc_router = load_router(self.store.get_json(head["router_ref"]))
        inc_experts = [r[:12] for r in head["expert_refs"]]
        with self.meter.phase("sealed_eval_incumbent", "artisan",
                              f"sub {sub_id} shard#{event_no}") as ph:
            inc_out, inc_stats = self._serve(inc_router, inc_experts, shard)
            ph.tokens = inc_stats["generated_tokens"]
        with self.meter.phase("sealed_eval_candidate", "artisan",
                              f"sub {sub_id} shard#{event_no}") as ph:
            cand_out, cand_stats = self._serve(router, cand_experts, shard)
            ph.tokens = cand_stats["generated_tokens"]

        gate = paired_gate(shard, inc_out, cand_out, stat_seed=event_no)
        if self.gate_override == "always" and not gate.promote:
            gate.promote = True
            gate.reason = "[DRY-RUN GATE OVERRIDE — MECHANICS TEST ONLY] " + gate.reason
        measured = gate.candidate["pass_rate"]
        internal = {
            "gate": {
                "delta_mean": gate.delta_mean,
                "delta_lower_bound": gate.delta_lower_bound,
                "per_cap_blocks": gate.per_cap_blocks,
                "incumbent": gate.incumbent, "candidate": gate.candidate,
            },
            "refit_stats": refit_stats,
            "serve_stats": {"incumbent": inc_stats, "candidate": cand_stats},
        }

        # "Wasted-eval" slash (Sybil deterrent), NOT a claim-vs-measured
        # comparison: self-reports are on the submitter's OWN slice, while
        # ARTISAN measures the full sealed distribution, so a large gap is
        # distribution shift, not fraud. We only slash a submission that
        # did not even improve the AGGREGATE (delta_mean <= 0) yet claimed
        # a large gain — that is a garbage/noise adapter burning eval
        # compute. An honest expert that lifts aggregate but trips the
        # per-capability regression gate is rejected WITHOUT a slash.
        fraud = (isinstance(claimed, (int, float))
                 and gate.delta_mean <= 0.0
                 and claimed - measured > FRAUD_TOLERANCE)

        if gate.promote:
            router_ref = self.store.put_json(router.to_json())
            expert_refs = list(head["expert_refs"]) + [expert_ref]
            try:
                version = self.registry.insert_head_cas(
                    domain, head["version"], head["base_ref"], router_ref,
                    expert_refs, measured, sub_id)
            except CASConflict as exc:
                reason = f"CAS conflict, re-evaluation required: {exc}"
                self.registry.append_lineage(domain, "REJECT", None, sub_id,
                                             agent_id, head["score"], measured, reason)
                return finish(sub_id, "rejected", reason, internal=internal,
                              band="fail_near")
            self.registry.update_submission(sub_id, "promoted", measured, gate.reason)
            self.registry.add_reputation_event(agent_id, PROMOTE_REWARD, "reward", sub_id)
            self.registry.append_lineage(domain, "PROMOTE", version, sub_id, agent_id,
                                         head["score"], measured, gate.reason)
            return PlaneOutcome(sub_id, "promoted", gate.reason,
                                coarse_feedback("promoted", gate.coarse_band),
                                version, internal)

        reason = gate.reason
        if fraud:
            reason += f" (claimed {claimed:.3f} vs measured {measured:.3f}: slashed)"
            self.registry.add_reputation_event(agent_id, -FRAUD_SLASH, "slash", sub_id)
        self.registry.update_submission(sub_id, "rejected", measured, reason)
        self.registry.append_lineage(domain, "REJECT", None, sub_id, agent_id,
                                     head["score"], measured, reason)
        # Reject leaves the candidate expert unused; drop it from serving.
        return PlaneOutcome(sub_id, "rejected", reason,
                            coarse_feedback("rejected", gate.coarse_band),
                            None, internal)

    # -------------------------------------------------------------- audit

    def audit_report(self, domain: str) -> dict:
        """Score the CURRENT head on the untouched audit shard (never used
        for gating). Reported once, at report time."""
        head = self.registry.get_head(domain)
        shard = draw_shard(self.secret, domain, "audit", 0, AUDIT_SHARD_N)
        router = load_router(self.store.get_json(head["router_ref"]))
        experts = [r[:12] for r in head["expert_refs"]]
        for ref in head["expert_refs"]:
            self._ensure_expert(ref[:12], self.store.get(ref))
        with self.meter.phase("audit_eval", "artisan", f"head v{head['version']}") as ph:
            outputs, stats = self._serve(router, experts, shard)
            ph.tokens = stats["generated_tokens"]
        from plane.domain import aggregate, score_item
        agg = aggregate(shard, [score_item(it, o) for it, o in zip(shard, outputs)])
        return {"head_version": head["version"], "audit": agg, "serve_stats": stats}
