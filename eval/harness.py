"""Independent evaluation harness.

Input: a CANDIDATE — (base spec + router config + expert library), all
resolved from the content-addressed store — and the domain's held-out
benchmark. Output: an objective, reproducible score.

Hard rule (council, unanimous): this module has NO access to a
submitter's claimed score. The benchmark decides what is BETTER.

Production mapping: this becomes a pinned, sandboxed eval container run
per-submission on Modal / RunPod spot GPU, against versioned hidden test
sets, funded by the submitter's eval deposit.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from store import BlobStore
from .benchmark import held_out_benchmark, benchmark_fingerprint
from .transforms import apply_transform, UnknownFamilyError


@dataclass
class Candidate:
    """A fully resolved head candidate: base + router + expert library."""

    base: dict                       # e.g. {"family": "identity", "params": {}}
    router: dict                     # {"version": 1, "routes": [{"keywords": [...], "expert": digest}]}
    experts: dict = field(default_factory=dict)  # digest -> expert param blob


@dataclass
class EvalReport:
    score: float                     # exact-match accuracy in [0, 1]
    n_examples: int
    per_family: dict                 # family -> accuracy
    benchmark_fingerprint: str


def assemble_candidate(
    store: BlobStore, base_ref: str, router_ref: str, expert_refs: list[str]
) -> Candidate:
    """Resolve a candidate from content-addressed refs. Integrity is
    checked by the store (digest == sha256(bytes))."""
    return Candidate(
        base=store.get_json(base_ref),
        router=store.get_json(router_ref),
        experts={ref: store.get_json(ref) for ref in expert_refs},
    )


def route(candidate: Candidate, instruction: str) -> dict:
    """Pick the expert for a prompt; fall back to the base.

    First-match-wins over ordered routes; a route fires when any of its
    keywords appears in the instruction. This is the toy stand-in for the
    learned lightweight router — the ONE thing ARTISAN trains centrally."""
    instr = instruction.lower()
    for r in candidate.router.get("routes", []):
        if any(kw in instr for kw in r.get("keywords", [])):
            expert = candidate.experts.get(r.get("expert"))
            if expert is not None:
                return expert
    return candidate.base


def run_candidate(candidate: Candidate, instruction: str, text: str) -> str | None:
    spec = route(candidate, instruction)
    try:
        return apply_transform(spec, text)
    except (UnknownFamilyError, TypeError, ValueError):
        return None  # a broken expert scores zero; it never crashes the harness


def evaluate(candidate: Candidate, examples: list[dict] | None = None) -> EvalReport:
    """Score a candidate on the held-out benchmark. Deterministic."""
    if examples is None:
        examples = held_out_benchmark()
    correct = 0
    fam_total: dict[str, int] = {}
    fam_correct: dict[str, int] = {}
    for ex in examples:
        fam = ex["family"]
        fam_total[fam] = fam_total.get(fam, 0) + 1
        out = run_candidate(candidate, ex["instruction"], ex["input"])
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
