"""artisan.eval — the independent evaluation harness.

ARTISAN never trusts an agent's self-reported score. Every submission is
re-evaluated here, on ARTISAN's own harness, against the domain's
held-out benchmark. Deterministic and reproducible for the toy domain.
"""
from .harness import Candidate, assemble_candidate, evaluate, EvalReport
from .benchmark import held_out_benchmark, training_sample, HELD_OUT_SEED

__all__ = [
    "Candidate",
    "assemble_candidate",
    "evaluate",
    "EvalReport",
    "held_out_benchmark",
    "training_sample",
    "HELD_OUT_SEED",
]
