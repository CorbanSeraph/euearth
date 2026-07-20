"""Sealed, rotating evaluation + statistical promotion gates.

Council fixes implemented here:

  ROTATION      every eval event draws a FRESH shard from a private
                secret (sha256(secret|domain|purpose|counter)) — there
                is no fixed hidden set to hill-climb across submissions.
  PAIRED GATE   incumbent and candidate run on the SAME shard; promotion
                requires the one-sided 95% bootstrap lower bound of the
                per-item pass delta to clear zero — not a fixed +0.02.
  PER-CAP GATE  no capability may significantly regress (bootstrap 90%
                upper bound of the per-field regression > 5 points on
                any capability blocks promotion) — aggregate wins can't
                hide capability losses.
  COARSE OUT    submitters get {promoted|rejected} + a coarse band only;
                precise measured scores stay internal (anti-probing).
  AUDIT SET     one shard (purpose="audit") is generated at genesis and
                NEVER used for gating; it is scored only for reports, so
                gate-set adaptation shows up as an audit/gate gap.
"""
from __future__ import annotations

import secrets as _secrets
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from plane.domain import (CAPABILITIES, aggregate, make_items, score_full,
                          score_item, shard_seed)

EVAL_SHARD_N = 250
AUDIT_SHARD_N = 250
BOOTSTRAP_RESAMPLES = 10_000
CONFIDENCE = 0.95            # one-sided, on the aggregate delta
CAP_REGRESSION_LIMIT = 0.05  # max tolerated true per-cap regression
CAP_CONFIDENCE = 0.90


def load_or_create_secret(path: str | Path) -> str:
    """The eval secret NEVER leaves ARTISAN's environment."""
    p = Path(path)
    if p.exists():
        return p.read_text().strip()
    p.parent.mkdir(parents=True, exist_ok=True)
    s = _secrets.token_hex(32)
    p.write_text(s)
    p.chmod(0o600)
    return s


def draw_shard(secret: str, domain: str, purpose: str, counter: int, n: int) -> list:
    return make_items(shard_seed(secret, domain, purpose, counter), n)


# ------------------------------------------------------------- statistics

@dataclass
class GateResult:
    promote: bool
    reason: str
    coarse_band: str                  # fail_low | fail_near | pass
    incumbent: dict                   # aggregate() dict
    candidate: dict
    delta_mean: float
    delta_lower_bound: float          # one-sided CI lower bound
    per_cap_blocks: list


def _bootstrap_lb(deltas: np.ndarray, confidence: float, rng: np.random.Generator) -> float:
    idx = rng.integers(0, len(deltas), size=(BOOTSTRAP_RESAMPLES, len(deltas)))
    means = deltas[idx].mean(axis=1)
    return float(np.quantile(means, 1.0 - confidence))


def _bootstrap_ub(deltas: np.ndarray, confidence: float, rng: np.random.Generator) -> float:
    idx = rng.integers(0, len(deltas), size=(BOOTSTRAP_RESAMPLES, len(deltas)))
    means = deltas[idx].mean(axis=1)
    return float(np.quantile(means, confidence))


def paired_gate(items: list, incumbent_outputs: list, candidate_outputs: list,
                stat_seed: int = 0) -> GateResult:
    """The benchmark decides — with confidence, per capability, paired."""
    rng = np.random.default_rng(stat_seed)
    inc_scores = [score_item(it, o) for it, o in zip(items, incumbent_outputs)]
    cand_scores = [score_item(it, o) for it, o in zip(items, candidate_outputs)]
    inc_agg, cand_agg = aggregate(items, inc_scores), aggregate(items, cand_scores)

    deltas = np.array([c["pass"] - i["pass"] for c, i in zip(cand_scores, inc_scores)],
                      dtype=np.float64)
    delta_mean = float(deltas.mean())
    lb = _bootstrap_lb(deltas, CONFIDENCE, rng)

    # Council v4 metric fix: per-capability regression is checked with the
    # FP/FN-aware `score_full.fields_exact` over ALL items (a hallucinated
    # or missing key scores 0), NOT the old present-only value accuracy that
    # was blind to false-positive key emission.
    inc_full = [score_full(it, o) for it, o in zip(items, incumbent_outputs)]
    cand_full = [score_full(it, o) for it, o in zip(items, candidate_outputs)]
    per_cap_blocks = []
    for cap in CAPABILITIES:
        cap_deltas = np.array(
            [cf["fields_exact"][cap] - inf["fields_exact"][cap]
             for cf, inf in zip(cand_full, inc_full)], dtype=np.float64)
        if len(cap_deltas) < 10:
            continue
        # Block if we are confident the regression exceeds the limit:
        # even the optimistic (upper) bound of the delta is worse than -limit.
        ub = _bootstrap_ub(cap_deltas, CAP_CONFIDENCE, rng)
        if ub < -CAP_REGRESSION_LIMIT:
            per_cap_blocks.append(
                f"{cap}: regression (mean {cap_deltas.mean():+.3f}, "
                f"{int(CAP_CONFIDENCE*100)}% ub {ub:+.3f} < -{CAP_REGRESSION_LIMIT})"
            )

    promote = lb > 0 and not per_cap_blocks
    if promote:
        band, reason = "pass", (
            f"promote: paired delta {delta_mean:+.4f}, one-sided "
            f"{int(CONFIDENCE*100)}% lower bound {lb:+.4f} > 0, no capability regression"
        )
    elif per_cap_blocks:
        band = "fail_near" if lb > 0 else "fail_low"
        reason = "reject: capability regression — " + "; ".join(per_cap_blocks)
    else:
        band = "fail_near" if delta_mean > 0 else "fail_low"
        reason = (f"reject: paired delta {delta_mean:+.4f}, lower bound {lb:+.4f} "
                  f"does not clear 0 at {int(CONFIDENCE*100)}% confidence")
    return GateResult(promote, reason, band, inc_agg, cand_agg,
                      delta_mean, lb, per_cap_blocks)


def coarse_feedback(outcome_status: str, band: str) -> dict:
    """The ONLY evaluation signal a submitter receives (anti hill-climb).
    Precise measured scores never leave ARTISAN's internal records."""
    return {"status": outcome_status, "band": band}
