"""The ARTISAN loop.

    signed submission
        -> verify Ed25519 signature against the REGISTERED key
        -> compliance scan (manifest vs policy; block on fail)
        -> independent re-evaluation on ARTISAN's harness
           (the submitter's claimed score is recorded for audit and
            otherwise IGNORED)
        -> if measured score beats the current head by the promotion
           margin: PROMOTE (new head version + lineage entry + reward)
           else: REJECT (lineage entry + slash if fraud)

Rollback is supported as a first-class governance event: a new head
version pointing at an earlier head's artifacts, appended to lineage —
history is never rewritten.

Production mapping: each `submit()` becomes a Temporal workflow; the
re-eval step dispatches to an ephemeral Modal/RunPod eval job funded by
the submitter's deposit; promotion margins become statistical confidence
thresholds over multi-gate evals (objective metrics + contamination
checks + regression budget + blinded human A/B).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from compliance import load_policy, scan_manifest
from eval.harness import Candidate, assemble_candidate, evaluate
from identity.keys import agent_id_for_public_key, canonical_json, verify_manifest
from registry import Registry
from store import LocalFSBlobStore

# Promotion margin: measured score must exceed head score by this much.
# Toy stand-in for a statistical confidence threshold.
PROMOTION_MARGIN = 0.02

# Reputation economics (stub): registration grant, promotion reward,
# slash for submissions whose claims don't survive re-eval, smaller
# slash for compliance blocks.
REGISTRATION_STAKE = 100.0
PROMOTE_REWARD = 10.0
FRAUD_SLASH = 15.0
COMPLIANCE_SLASH = 5.0
# Claimed score may exceed measured by this much before it counts as fraud.
FRAUD_TOLERANCE = 0.05


@dataclass
class SubmissionOutcome:
    submission_id: str
    status: str            # promoted | rejected | blocked_compliance | rejected_signature
    measured_score: float | None
    head_score_before: float | None
    head_score_after: float | None
    head_version: int | None
    reason: str


class Orchestrator:
    def __init__(self, root: str | Path, policy_path: str | Path | None = None):
        root = Path(root)
        self.store = LocalFSBlobStore(root / "blobs")
        self.registry = Registry(root / "registry.sqlite3")
        self.policy = load_policy(policy_path)

    # ------------------------------------------------------------------ #
    # setup
    # ------------------------------------------------------------------ #

    def register_agent(self, name: str, public_key_hex: str) -> str:
        already = self.registry.get_agent(agent_id_for_public_key(public_key_hex))
        agent_id = self.registry.register_agent(name, public_key_hex)
        if already is None:
            self.registry.add_reputation_event(agent_id, REGISTRATION_STAKE, "stake", None)
        return agent_id

    def create_domain_with_genesis(self, domain: str, description: str) -> dict:
        """Create a domain and its genesis head: identity base, empty
        router, empty expert library — scored honestly by the harness."""
        self.registry.create_domain(domain, description)
        if self.registry.get_head(domain):
            return self.registry.get_head(domain)
        base_ref = self.store.put_json({"family": "identity", "params": {}})
        router_ref = self.store.put_json({"version": 1, "routes": []})
        report = evaluate(assemble_candidate(self.store, base_ref, router_ref, []))
        version = self.registry.insert_head(domain, base_ref, router_ref, [], report.score, None)
        self.registry.append_lineage(
            domain, "GENESIS", version, None, None, None, report.score,
            f"genesis head: identity base, empty expert library "
            f"(benchmark {report.benchmark_fingerprint[:12]})",
        )
        return self.registry.get_head(domain)

    def open_wisket(self, domain: str, title: str, description: str) -> str:
        return self.registry.create_wisket(domain, title, description)

    # ------------------------------------------------------------------ #
    # the loop
    # ------------------------------------------------------------------ #

    def submit(self, envelope: dict) -> SubmissionOutcome:
        """Process a signed submission envelope:
        {"manifest": {...}, "signature": "<hex over canonical JSON of manifest>"}
        """
        manifest = envelope.get("manifest") or {}
        signature = envelope.get("signature", "")
        domain = manifest.get("domain", "")
        agent_id = manifest.get("agent_id", "")
        claimed = manifest.get("claimed_score")
        manifest_json = canonical_json(manifest).decode()

        # -- 1. identity: agent must be registered; key comes from the
        #       registry, never from the envelope.
        agent = self.registry.get_agent(agent_id)
        if agent is None or not verify_manifest(agent["public_key"], manifest, signature):
            sub_id = self.registry.create_submission(
                manifest.get("wisket_id"), domain, agent_id, manifest_json, signature, claimed
            )
            reason = "unknown agent" if agent is None else "signature verification failed"
            self.registry.update_submission(sub_id, "rejected_signature", None, reason)
            return SubmissionOutcome(sub_id, "rejected_signature", None, None, None, None, reason)

        sub_id = self.registry.create_submission(
            manifest.get("wisket_id"), domain, agent_id, manifest_json, signature, claimed
        )

        head = self.registry.get_head(domain)
        if head is None:
            reason = f"unknown domain: {domain}"
            self.registry.update_submission(sub_id, "rejected", None, reason)
            return SubmissionOutcome(sub_id, "rejected", None, None, None, None, reason)

        # -- 2. compliance: manifest vs policy, block on fail.
        comp = scan_manifest(manifest, self.policy)
        if not comp.ok:
            reason = "compliance block: " + "; ".join(comp.violations)
            self.registry.update_submission(sub_id, "blocked_compliance", None, reason)
            self.registry.add_reputation_event(agent_id, -COMPLIANCE_SLASH, "slash", sub_id)
            self.registry.append_lineage(
                domain, "REJECT", None, sub_id, agent_id, head["score"], None, reason
            )
            return SubmissionOutcome(
                sub_id, "blocked_compliance", None, head["score"], None, None, reason
            )

        # -- 3. resolve artifacts from the content-addressed store.
        artifacts = manifest.get("artifacts") or {}
        expert_ref, route_ref = artifacts.get("expert"), artifacts.get("route")
        problem = self._validate_artifacts(expert_ref, route_ref)
        if problem:
            self.registry.update_submission(sub_id, "rejected", None, problem)
            self.registry.append_lineage(
                domain, "REJECT", None, sub_id, agent_id, head["score"], None, problem
            )
            return SubmissionOutcome(sub_id, "rejected", None, head["score"], None, None, problem)

        # -- 4. independent re-eval. Candidate = current head + this expert
        #       + this route appended to the router. claimed_score is NOT
        #       an input to anything below.
        route_entry = self.store.get_json(route_ref)
        candidate_router = self.store.get_json(head["router_ref"])
        candidate_router = {
            "version": candidate_router.get("version", 1),
            "routes": list(candidate_router.get("routes", []))
            + [{"keywords": route_entry["keywords"], "expert": expert_ref}],
        }
        candidate_router_ref = self.store.put_json(candidate_router)
        candidate_expert_refs = list(head["expert_refs"])
        if expert_ref not in candidate_expert_refs:
            candidate_expert_refs.append(expert_ref)

        candidate = assemble_candidate(
            self.store, head["base_ref"], candidate_router_ref, candidate_expert_refs
        )
        report = evaluate(candidate)
        measured = report.score

        # -- 5. the benchmark decides.
        if measured >= head["score"] + PROMOTION_MARGIN:
            version = self.registry.insert_head(
                domain, head["base_ref"], candidate_router_ref,
                candidate_expert_refs, measured, sub_id,
            )
            reason = (
                f"promoted: measured {measured:.4f} beats head {head['score']:.4f} "
                f"by >= {PROMOTION_MARGIN} (claimed {claimed}, ignored; "
                f"per-family {json.dumps(report.per_family)})"
            )
            self.registry.update_submission(sub_id, "promoted", measured, reason)
            self.registry.add_reputation_event(agent_id, PROMOTE_REWARD, "reward", sub_id)
            self.registry.append_lineage(
                domain, "PROMOTE", version, sub_id, agent_id, head["score"], measured, reason
            )
            return SubmissionOutcome(
                sub_id, "promoted", measured, head["score"], measured, version, reason
            )

        reason = (
            f"rejected: measured {measured:.4f} does not beat head "
            f"{head['score']:.4f} by margin {PROMOTION_MARGIN}"
        )
        if isinstance(claimed, (int, float)) and claimed - measured > FRAUD_TOLERANCE:
            reason += f" (claimed {claimed:.4f} — inflated claim, stake slashed)"
            self.registry.add_reputation_event(agent_id, -FRAUD_SLASH, "slash", sub_id)
        self.registry.update_submission(sub_id, "rejected", measured, reason)
        self.registry.append_lineage(
            domain, "REJECT", None, sub_id, agent_id, head["score"], measured, reason
        )
        return SubmissionOutcome(
            sub_id, "rejected", measured, head["score"], None, None, reason
        )

    def _validate_artifacts(self, expert_ref: str | None, route_ref: str | None) -> str | None:
        if not expert_ref or not self.store.has(expert_ref):
            return "artifact missing from store: expert"
        if not route_ref or not self.store.has(route_ref):
            return "artifact missing from store: route"
        route_entry = self.store.get_json(route_ref)
        if route_entry.get("expert") not in (None, expert_ref):
            return "route artifact references a different expert digest"
        if not isinstance(route_entry.get("keywords"), list) or not route_entry["keywords"]:
            return "route artifact must declare a non-empty keywords list"
        return None

    # ------------------------------------------------------------------ #
    # rollback
    # ------------------------------------------------------------------ #

    def rollback(self, domain: str, to_version: int, reason: str) -> dict:
        """Advance the head to a COPY of an earlier version. Lineage is
        append-only: the rollback is a new event, not a rewrite."""
        head = self.registry.get_head(domain)
        target = self.registry.get_head_version(domain, to_version)
        if head is None or target is None:
            raise ValueError(f"no such head version: {domain} v{to_version}")
        version = self.registry.insert_head(
            domain, target["base_ref"], target["router_ref"],
            target["expert_refs"], target["score"], None,
        )
        self.registry.append_lineage(
            domain, "ROLLBACK", version, None, None, head["score"], target["score"],
            f"rollback to v{to_version}: {reason}",
        )
        return self.registry.get_head(domain)
