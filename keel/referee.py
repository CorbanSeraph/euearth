"""The swap referee — the EXISTING eval module deciding who holds the slot.

Reused verbatim (nothing re-derived here):
  * eval.benchmark.held_out_benchmark  — the private gate set
  * eval.harness.EvalReport            — the report shape
  * orchestrator.loop.PROMOTION_MARGIN — the confidence margin the inner
                                         loop already gates on

The only new mechanic: probes are driven THROUGH the stable socket
(contract.validate_request / validate_response → occupant.infer), because
a keel occupant is an arbitrary engine behind the interface — not
necessarily the base+router+experts Candidate the inner harness scores.
Both contenders are measured on the SAME examples in the SAME run.
An occupant that crashes or violates the contract scores zero on that
example; it never crashes the referee (same stance as the inner harness).
"""
from __future__ import annotations

from dataclasses import dataclass

from eval.benchmark import benchmark_fingerprint, held_out_benchmark
from eval.harness import EvalReport
from orchestrator.loop import PROMOTION_MARGIN

from .contract import InterfaceContract
from .occupants import Occupant


def evaluate_occupant(
    occupant: Occupant,
    contract: InterfaceContract,
    examples: list[dict] | None = None,
) -> EvalReport:
    """Score an occupant on the domain's held-out benchmark, with every
    probe passing through the stable socket. Deterministic."""
    if examples is None:
        examples = held_out_benchmark()
    correct = 0
    fam_total: dict[str, int] = {}
    fam_correct: dict[str, int] = {}
    for ex in examples:
        fam = ex["family"]
        fam_total[fam] = fam_total.get(fam, 0) + 1
        try:
            request = contract.validate_request(
                {"instruction": ex["instruction"], "text": ex["input"]}
            )
            response = contract.validate_response(occupant.infer(request))
            out = response["text"]
        except Exception:
            out = None  # broken occupants score zero, never crash the referee
        if out == ex["expected"]:
            correct += 1
            fam_correct[fam] = fam_correct.get(fam, 0) + 1
    per_family = {
        fam: round(fam_correct.get(fam, 0) / n, 4) for fam, n in sorted(fam_total.items())
    }
    return EvalReport(
        score=round(correct / len(examples), 6),
        n_examples=len(examples),
        per_family=per_family,
        benchmark_fingerprint=benchmark_fingerprint(examples),
    )


@dataclass
class RefereeDecision:
    challenger_wins: bool
    margin: float
    champion_report: EvalReport
    challenger_report: EvalReport
    reason: str


def referee(
    champion: Occupant, challenger: Occupant, contract: InterfaceContract
) -> RefereeDecision:
    """Head-to-head on the same held-out set; the benchmark decides."""
    examples = held_out_benchmark()
    champ = evaluate_occupant(champion, contract, examples)
    chal = evaluate_occupant(challenger, contract, examples)
    wins = chal.score >= champ.score + PROMOTION_MARGIN
    verdict = "beats" if wins else "does not beat"
    reason = (
        f"challenger measured {chal.score:.4f} {verdict} champion "
        f"{champ.score:.4f} by margin {PROMOTION_MARGIN} "
        f"(benchmark {champ.benchmark_fingerprint[:12]})"
    )
    return RefereeDecision(
        challenger_wins=wins,
        margin=PROMOTION_MARGIN,
        champion_report=champ,
        challenger_report=chal,
        reason=reason,
    )
