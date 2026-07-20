"""The keel runtime — holds the slot, routes requests, runs challenges.

One Keel per (domain, contract version). It generalizes the inner loop's
swap from "promote an expert adapter into the composite" to "swap the
WHOLE OCCUPANT behind the socket" — using the same machinery:

Registry mapping (REUSE — no new tables, no schema change). A keel slot
is a registry domain named `keel/<domain>/v<contract version>`, and each
head row reads:

    base_ref    -> occupant descriptor blob    (WHO holds the slot)
    router_ref  -> the contract blob           (the socket itself)
    expert_refs -> occupant's internal artifact refs

Because router_ref must carry the SAME contract digest on every version
of the slot, "the interface never changed across the swap" is verifiable
straight from registry history — content addressing does the proving.

Challenge path:  conformance (declared contract fingerprint + live probe)
    -> compliance scan of the occupant manifest (existing scanner)
    -> referee on the existing held-out benchmark (existing eval)
    -> if the challenger wins by the existing promotion margin:
       ATOMIC swap via Registry.insert_head_cas + hash-chained lineage.
Rollback is the same append-only governance event the orchestrator uses.

In-process note: the registry persists WHO holds the slot; the live
Python occupant instances are seated in this process. A real domain adds
an occupant LOADER spec to the descriptor so a fresh runtime can re-seat
the champion from the record alone.
"""
from __future__ import annotations

from dataclasses import dataclass

from compliance import scan_manifest
from orchestrator import Orchestrator

from .contract import ContractViolation, InterfaceContract
from .occupants import Occupant
from .referee import evaluate_occupant, referee


@dataclass
class ChallengeOutcome:
    status: str                     # swapped | rejected | blocked_compliance | rejected_nonconformant
    reason: str
    challenger: str
    champion_before: str
    champion_after: str
    champion_score: float | None = None
    challenger_score: float | None = None
    head_version: int | None = None
    contract_ref_before: str | None = None
    contract_ref_after: str | None = None


class Keel:
    def __init__(self, orch: Orchestrator, contract: InterfaceContract):
        self.orch = orch
        self.contract = contract
        self.slot_domain = f"keel/{contract.domain}/v{contract.version}"
        # The socket is itself a content-addressed artifact.
        self.contract_ref = orch.store.put_json(contract.to_dict())
        orch.registry.create_domain(
            self.slot_domain,
            f"KEEL slot for {contract.domain}: stable socket "
            f"{contract.fingerprint[:12]}… — occupants compete to hold it",
        )
        self._live: dict[str, Occupant] = {}   # occupant_ref -> seated instance
        self._current_ref: str | None = None

    # ------------------------------------------------------------------ #
    # state
    # ------------------------------------------------------------------ #

    def head(self) -> dict | None:
        return self.orch.registry.get_head(self.slot_domain)

    @property
    def occupant(self) -> Occupant:
        if self._current_ref is None:
            raise RuntimeError(f"slot {self.slot_domain} is not seated")
        return self._live[self._current_ref]

    def current(self) -> dict | None:
        head = self.head()
        if head is None:
            return None
        descriptor = self.orch.store.get_json(head["base_ref"])
        return {
            "slot_domain": self.slot_domain,
            "version": head["version"],
            "score": head["score"],
            "name": descriptor["name"],
            "kind": descriptor["kind"],
            "occupant_ref": head["base_ref"],
            "contract_ref": head["router_ref"],
            "seated_at": head["created_at"],
        }

    def leaderboard(self) -> list[dict]:
        """Every occupant that ever held the slot, in seating order."""
        head = self.head()
        if head is None:
            return []
        rows = []
        for version in range(1, head["version"] + 1):
            row = self.orch.registry.get_head_version(self.slot_domain, version)
            descriptor = self.orch.store.get_json(row["base_ref"])
            rows.append(
                {
                    "version": version,
                    "name": descriptor["name"],
                    "kind": descriptor["kind"],
                    "score": row["score"],
                    "contract_ref": row["router_ref"],
                    "seated_at": row["created_at"],
                    "reigning": version == head["version"],
                }
            )
        return rows

    def lineage(self) -> list[dict]:
        return self.orch.registry.get_lineage(self.slot_domain)

    # ------------------------------------------------------------------ #
    # seating + serving
    # ------------------------------------------------------------------ #

    def seat_genesis(self, occupant: Occupant) -> dict:
        """Seat the first champion. Scored honestly by the referee before
        it touches the slot — even the genesis occupant earns its number."""
        if self.head() is not None:
            raise RuntimeError(f"slot {self.slot_domain} already seated")
        problem = self._conformance_problem(occupant)
        if problem:
            raise ContractViolation(f"genesis occupant nonconformant: {problem}")
        report = evaluate_occupant(occupant, self.contract)
        ref = self.orch.store.put_json(occupant.describe())
        version = self.orch.registry.insert_head(
            self.slot_domain, ref, self.contract_ref,
            occupant.artifact_refs(), report.score, None,
        )
        self.orch.registry.append_lineage(
            self.slot_domain, "GENESIS", version, None, None, None, report.score,
            f"slot seated: {occupant.name} [{occupant.kind}] measured "
            f"{report.score:.4f} behind contract {self.contract.fingerprint[:12]}",
        )
        self._live[ref] = occupant
        self._current_ref = ref
        return self.current()

    def run(self, request: dict | None = None, *, controls: dict | None = None) -> dict:
        """Serve one user request through the stable socket. The caller
        never addresses the occupant — only the contract."""
        if controls is not None:
            request = self.contract.request_from_controls(controls)
        validated = self.contract.validate_request(request or {})
        response = self.occupant.infer(validated)
        return self.contract.validate_response(response)

    # ------------------------------------------------------------------ #
    # the challenge — whole-occupant swap
    # ------------------------------------------------------------------ #

    def challenge(self, challenger: Occupant) -> ChallengeOutcome:
        head = self.head()
        if head is None:
            raise RuntimeError(f"slot {self.slot_domain} is not seated")
        champion = self.occupant

        def rejected(status: str, reason: str, decision=None) -> ChallengeOutcome:
            self.orch.registry.append_lineage(
                self.slot_domain, "REJECT", None, None, None,
                head["score"],
                decision.challenger_report.score if decision else None,
                f"challenge by {challenger.name} [{challenger.kind}]: {reason}",
            )
            return ChallengeOutcome(
                status=status, reason=reason, challenger=challenger.name,
                champion_before=champion.name, champion_after=champion.name,
                champion_score=decision.champion_report.score if decision else head["score"],
                challenger_score=decision.challenger_report.score if decision else None,
                head_version=head["version"],
                contract_ref_before=head["router_ref"],
                contract_ref_after=head["router_ref"],
            )

        # 1. conformance: the challenger must implement THIS socket.
        problem = self._conformance_problem(challenger)
        if problem:
            return rejected("rejected_nonconformant", f"nonconformant — {problem}")

        # 2. compliance: occupant manifest vs policy (existing scanner).
        comp = scan_manifest(challenger.describe(), self._keel_policy())
        if not comp.ok:
            return rejected(
                "blocked_compliance", "compliance block: " + "; ".join(comp.violations)
            )

        # 3. the referee (existing eval) measures both on the same gate set.
        decision = referee(champion, challenger, self.contract)
        if not decision.challenger_wins:
            return rejected("rejected", decision.reason, decision)

        # 4. atomic whole-occupant swap. CAS guarantees we only advance
        #    the exact head the challenger was measured against.
        ref = self.orch.store.put_json(challenger.describe())
        version = self.orch.registry.insert_head_cas(
            self.slot_domain, head["version"], ref, self.contract_ref,
            challenger.artifact_refs(), decision.challenger_report.score, None,
        )
        self.orch.registry.append_lineage(
            self.slot_domain, "PROMOTE", version, None, None,
            decision.champion_report.score, decision.challenger_report.score,
            f"SWAP: {challenger.name} [{challenger.kind}] dethrones "
            f"{champion.name} — {decision.reason}; contract "
            f"{self.contract.fingerprint[:12]} unchanged",
        )
        self._live[ref] = challenger
        self._current_ref = ref
        new_head = self.head()
        return ChallengeOutcome(
            status="swapped", reason=decision.reason, challenger=challenger.name,
            champion_before=champion.name, champion_after=challenger.name,
            champion_score=decision.champion_report.score,
            challenger_score=decision.challenger_report.score,
            head_version=version,
            contract_ref_before=head["router_ref"],
            contract_ref_after=new_head["router_ref"],
        )

    def rollback(self, to_version: int, reason: str) -> dict:
        """Re-seat an earlier champion. Append-only, same governance shape
        as the orchestrator's rollback: a new head version, never a rewrite."""
        head = self.head()
        target = self.orch.registry.get_head_version(self.slot_domain, to_version)
        if head is None or target is None:
            raise ValueError(f"no such head version: {self.slot_domain} v{to_version}")
        if target["base_ref"] not in self._live:
            raise RuntimeError(
                "target occupant is not seated in this process; a real domain "
                "re-seats from the descriptor's loader spec"
            )
        version = self.orch.registry.insert_head(
            self.slot_domain, target["base_ref"], target["router_ref"],
            target["expert_refs"], target["score"], None,
        )
        self.orch.registry.append_lineage(
            self.slot_domain, "ROLLBACK", version, None, None,
            head["score"], target["score"],
            f"rollback to v{to_version}: {reason}",
        )
        self._current_ref = target["base_ref"]
        return self.current()

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #

    def _conformance_problem(self, occupant: Occupant) -> str | None:
        """Eligibility for the slot: declare THIS contract, survive a live
        probe through it."""
        if occupant.contract_fingerprint != self.contract.fingerprint:
            return (
                f"declares contract {occupant.contract_fingerprint[:12]}, "
                f"slot requires {self.contract.fingerprint[:12]}"
            )
        descriptor = occupant.describe()
        if descriptor.get("contract") != self.contract.fingerprint:
            return "descriptor contract field does not match the slot contract"
        probe = {name: "probe" for name in self.contract.input_spec}
        try:
            self.contract.validate_response(
                occupant.infer(self.contract.validate_request(probe))
            )
        except Exception as exc:
            return f"live probe through the socket failed: {exc}"
        return None

    def _keel_policy(self) -> dict:
        """The existing compliance policy, with required top-level fields
        adapted to occupant descriptors (sources/licenses rules unchanged)."""
        policy = dict(self.orch.policy)
        policy["required_manifest_fields"] = [
            "kind", "name", "contract", "engine", "dataset_manifest",
        ]
        return policy
