"""The router — ARTISAN's one central training job, budgeted and metered.

The council's core objection: our toy proof dodged the router by making
tasks orthogonal. Here the router is REAL and the experts OVERLAP:

  * arms = frozen base | each expert alone | uniform blend of experts
  * features = mean-pooled frozen-base embedding of the prompt
  * gate = multinomial logistic head over those features (tiny, CPU)

Refit procedure (runs on EVERY submission that reaches evaluation —
this is exactly the "centralized compute" the council said we must
stop hiding, so it runs under a HARD wall-clock budget and its
GPU-seconds are metered):

  1. draw a private router-fit shard (never shown to submitters)
  2. generate under EVERY arm, batch by batch, until the budget is
     spent — the expensive part, and it scales with #arms
  3. label each item with the best-scoring arm (ties -> simplest arm)
  4. fit the logistic head (negligible next to step 2)

The fitted head is serialized to a content-addressed blob and becomes
`router_ref` in the candidate head. If the budget truncates the fit,
that is recorded — an underfit router is an honest outcome, not an
error.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import time

import numpy as np
import torch

from plane.domain import CAPABILITIES, Item, parse_json_object, score_item
from plane.model_ops import embed_prompts, generate_batch, chat_prompt

BASE_ARM = "__base__"
BLEND_ARM = "__blend__"
FIT_CHUNK = 32          # items scored per budget check


def arm_list(expert_names: list, include_blend: bool = True) -> list:
    arms = [BASE_ARM] + sorted(expert_names)
    if include_blend and len(expert_names) >= 2:
        arms.append(BLEND_ARM)
    return arms


def _active_adapters(model):
    active = getattr(model, "active_adapters", None)
    if callable(active):                       # some peft versions expose a method
        try:
            active = active()
        except Exception:
            active = None
    if active is None:
        active = getattr(model, "active_adapter", None)
        if callable(active):
            try:
                active = active()
            except Exception:
                active = None
    if active is None:
        return None
    return [active] if isinstance(active, str) else list(active)


@contextlib.contextmanager
def use_arm(model, arm: str, expert_names: list):
    """Council fix #1: activate `arm`, then RESTORE the exact prior adapter
    state on exit. Base uses PEFT's own restoring disable_adapter(); expert
    /blend arms restore whatever was active before, so no arm ever leaks
    into the next generation or (critically) into base feature extraction."""
    previous = _active_adapters(model)
    if arm == BASE_ARM:
        disable = getattr(model, "disable_adapter", None)
        if disable is None:
            yield
        else:
            with disable():
                yield
        return
    try:
        if arm == BLEND_ARM:
            from plane.model_ops import ensure_blend
            ensure_blend(model, sorted(expert_names), BLEND_ARM)
            model.set_adapter(BLEND_ARM)
        else:
            model.set_adapter(arm)
        yield
    finally:
        if previous:
            model.set_adapter(previous[0] if len(previous) == 1 else previous)


# Back-compat alias: _set_arm was a plain (non-restoring) CM; use_arm is the
# restoring replacement and is a drop-in for `with _set_arm(...)`.
_set_arm = use_arm


def embed_base(model, tok, prompts: list, device: str) -> np.ndarray:
    """Council fix #1: the gate/field features are ALWAYS the frozen base's
    hidden state. embed_prompts already runs under disable_adapter(); we
    wrap it once more explicitly and validate finiteness so a contaminated
    or NaN feature can never silently drive routing."""
    with torch.inference_mode():
        feats = embed_prompts(model, tok, prompts, device)
    feats = feats.detach().float().cpu().numpy() if isinstance(feats, torch.Tensor) \
        else np.asarray(feats, dtype=np.float32)
    if feats.ndim != 2 or not np.isfinite(feats).all():
        raise ValueError(f"bad base embeddings: shape {feats.shape}, finite={np.isfinite(feats).all()}")
    return feats


def feature_fingerprint(pin: dict) -> str:
    """Bind a router to the exact base whose frozen embeddings it routes on."""
    return hashlib.sha256(
        f"embed_base|mean_pool_last_hidden|{pin.get('fingerprint','?')}".encode()
    ).hexdigest()[:16]


def _arm_priority(arm: str) -> int:
    if arm == BASE_ARM:
        return 0
    if arm == BLEND_ARM:
        return 2
    return 1


class Router:
    """Standardized-feature multinomial logistic gate over discrete arms."""

    def __init__(self, arms: list, mean, std, weight, bias, meta: dict):
        self.arms = arms
        self.mean = np.asarray(mean, dtype=np.float32)
        self.std = np.asarray(std, dtype=np.float32)
        self.weight = np.asarray(weight, dtype=np.float32)
        self.bias = np.asarray(bias, dtype=np.float32)
        self.meta = meta

    def choose(self, feats: np.ndarray) -> list:
        x = (feats - self.mean) / self.std
        logits = x @ self.weight.T + self.bias
        return [self.arms[i] for i in logits.argmax(axis=1)]

    def to_json(self) -> dict:
        return {
            "kind": "router", "family": "logistic-gate-v1", "arms": self.arms,
            "mean": self.mean.tolist(), "std": self.std.tolist(),
            "weight": self.weight.tolist(), "bias": self.bias.tolist(),
            "meta": self.meta,
        }

    @classmethod
    def from_json(cls, obj: dict) -> "Router":
        return cls(obj["arms"], obj["mean"], obj["std"], obj["weight"],
                   obj["bias"], obj.get("meta", {}))

    @classmethod
    def trivial(cls, dim: int) -> "Router":
        """Genesis router: always the frozen base."""
        return cls([BASE_ARM], np.zeros(dim), np.ones(dim),
                   np.zeros((1, dim)), np.zeros(1),
                   {"fit_items": 0, "note": "genesis: base only"})


def load_router(obj: dict):
    """Deserialize any router family from its JSON blob."""
    fam = obj.get("family")
    if fam == "presence-merge-v4":
        return PresenceMergeRouter.from_json(obj)
    if fam == "field-merge-v3":
        return FieldMergeRouter.from_json(obj)
    if fam == "soft-gate-v2":
        return SoftRouter.from_json(obj)
    return Router.from_json(obj)


class SoftRouter:
    """v2 gate: base-embedding features + soft top-2 + confidence fallback.

    The trio the Sovereigns asked for:
      (a) features are the FROZEN BASE's own hidden-state embedding of the
          prompt (set upstream by embed_prompts) — the model's own
          representation separates capabilities better than surface cues;
      (b) SOFT top-2: when the gate spreads mass across BOTH experts (an
          overlapping item), route to their blend instead of forcing one;
      (c) CONFIDENCE FALLBACK: when the non-base mass is below a calibrated
          threshold tau, fall back to the frozen base — structurally
          guaranteeing no per-capability regression on items the gate
          cannot confidently place.

    tau (fallback) and eta (top-2 activation) are CALIBRATED on the fit
    pool against the per-capability no-regression objective, using the
    generations already produced during refit (no extra GPU)."""

    def __init__(self, arms, mean, std, weight, bias, tau, eta, meta):
        self.arms = list(arms)                 # [BASE, e1, e2, ..., BLEND]
        self.mean = np.asarray(mean, dtype=np.float32)
        self.std = np.asarray(std, dtype=np.float32)
        self.weight = np.asarray(weight, dtype=np.float32)
        self.bias = np.asarray(bias, dtype=np.float32)
        self.tau = float(tau)
        self.eta = float(eta)
        self.meta = meta
        self._experts = [a for a in self.arms if a not in (BASE_ARM, BLEND_ARM)]

    def _probs(self, feats: np.ndarray) -> np.ndarray:
        x = (feats - self.mean) / self.std
        logits = x @ self.weight.T + self.bias
        logits = logits - logits.max(axis=1, keepdims=True)
        e = np.exp(logits)
        return e / e.sum(axis=1, keepdims=True)

    def choose(self, feats: np.ndarray) -> list:
        probs = self._probs(feats)
        idx = {a: i for i, a in enumerate(self.arms)}
        has_blend = BLEND_ARM in idx
        out = []
        for p in probs:
            p_base = p[idx[BASE_ARM]]
            expert_ps = {e: p[idx[e]] for e in self._experts}
            blend_p = p[idx[BLEND_ARM]] if has_blend else 0.0
            nonbase_mass = 1.0 - p_base
            # (c) confidence fallback -> frozen base
            if nonbase_mass < self.tau:
                out.append(BASE_ARM)
                continue
            # rank experts; (b) soft top-2: both strongly active -> blend
            ranked = sorted(expert_ps.items(), key=lambda kv: kv[1], reverse=True)
            top_e, top_p = ranked[0]
            second_p = ranked[1][1] if len(ranked) > 1 else 0.0
            if has_blend and len(ranked) >= 2 and second_p >= self.eta and top_p >= self.eta:
                out.append(BLEND_ARM)
            elif has_blend and blend_p >= max(top_p, p_base):
                out.append(BLEND_ARM)
            else:
                out.append(top_e)
        return out

    def to_json(self) -> dict:
        return {"kind": "router", "family": "soft-gate-v2", "arms": self.arms,
                "mean": self.mean.tolist(), "std": self.std.tolist(),
                "weight": self.weight.tolist(), "bias": self.bias.tolist(),
                "tau": self.tau, "eta": self.eta, "meta": self.meta}

    @classmethod
    def from_json(cls, obj: dict) -> "SoftRouter":
        return cls(obj["arms"], obj["mean"], obj["std"], obj["weight"],
                   obj["bias"], obj["tau"], obj["eta"], obj.get("meta", {}))


def _fit_logistic(feats, labels, n_arms, seed=0, soft_targets=None,
                  class_weights=None, steps=400, lr=0.03):
    """Council fix #3: supports SOFT targets (KL to per-arm field utility)
    and inverse-frequency class weights, so the gate is trained on the
    policy it will actually serve instead of a hard argmax that suppresses
    the second expert."""
    mean = feats.mean(axis=0)
    std = feats.std(axis=0) + 1e-6
    x = torch.tensor((feats - mean) / std, dtype=torch.float32)
    torch.manual_seed(seed)
    lin = torch.nn.Linear(x.shape[1], n_arms)
    opt = torch.optim.AdamW(lin.parameters(), lr=lr, weight_decay=1e-2)
    if soft_targets is not None:
        y_soft = torch.tensor(soft_targets, dtype=torch.float32)
        w = None
    else:
        y = torch.tensor(labels, dtype=torch.long)
        if class_weights is None:
            counts = np.bincount(labels, minlength=n_arms).astype(np.float32) + 1.0
            class_weights = (counts.sum() / (n_arms * counts)).astype(np.float32)
        w = torch.tensor(class_weights, dtype=torch.float32)
    for _ in range(steps):
        opt.zero_grad()
        logits = lin(x)
        if soft_targets is not None:
            loss = -(y_soft * torch.nn.functional.log_softmax(logits, dim=-1)).sum(-1).mean()
        else:
            loss = torch.nn.functional.cross_entropy(logits, y, weight=w)
        loss.backward()
        opt.step()
    return (mean, std, lin.weight.detach().numpy(), lin.bias.detach().numpy())


def _soft_labels_from_fields(arms, per_arm_fields, n, temperature=0.15):
    """Per-arm utility = mean field hit; softmax over arms -> soft targets."""
    util = np.zeros((n, len(arms)), dtype=np.float32)
    for ai, arm in enumerate(arms):
        for i in range(n):
            vals = list(per_arm_fields[arm][i].values())
            util[i, ai] = (float(np.mean(vals)) if vals else 0.0) - 1e-3 * _arm_priority(arm)
    u = util / max(temperature, 1e-3)
    u = u - u.max(axis=1, keepdims=True)
    e = np.exp(u)
    return e / e.sum(axis=1, keepdims=True)


def refit_router(model, tok, expert_names: list, fit_items: list,
                 device: str, budget_seconds: float, seed: int = 0) -> tuple:
    """Budgeted refit. Returns (Router, stats). `model` must already carry
    all experts in `expert_names` (a PeftModel from attach_adapters)."""
    arms = arm_list(expert_names)
    t0 = time.monotonic()
    used_items: list = []
    per_arm_scores: dict = {a: [] for a in arms}
    tokens = 0
    truncated = False

    for start in range(0, len(fit_items), FIT_CHUNK):
        if time.monotonic() - t0 > budget_seconds * 0.85:
            truncated = True
            break
        chunk = fit_items[start:start + FIT_CHUNK]
        prompts = [chat_prompt(tok, it) for it in chunk]
        for arm in arms:
            with _set_arm(model, arm, expert_names):
                outs, gt = generate_batch(model, tok, prompts, device)
            tokens += gt
            per_arm_scores[arm].extend(
                (score_item(it, out)["pass"],
                 float(np.mean(list(score_item(it, out)["fields"].values()) or [0])))
                for it, out in zip(chunk, outs)
            )
        used_items.extend(chunk)

    if not used_items:
        raise RuntimeError(f"router budget {budget_seconds}s too small for even one chunk")

    # Label = best arm per item; ties -> simplest arm (base < expert < blend).
    labels = []
    for i in range(len(used_items)):
        best, best_key = 0, None
        for ai, arm in enumerate(arms):
            p, f = per_arm_scores[arm][i]
            key = (p, f, -_arm_priority(arm))
            if best_key is None or key > best_key:
                best, best_key = ai, key
        labels.append(best)
    labels = np.asarray(labels)

    feats = embed_base(model, tok, [chat_prompt(tok, it) for it in used_items], device)
    mean, std, weight, bias = _fit_logistic(feats, labels, len(arms), seed=seed)

    stats = {
        "arms": arms,
        "fit_items_used": len(used_items),
        "fit_items_offered": len(fit_items),
        "budget_seconds": budget_seconds,
        "wall_seconds": time.monotonic() - t0,
        "truncated_by_budget": truncated,
        "generated_tokens": tokens,
        "label_histogram": {arms[i]: int((labels == i).sum()) for i in range(len(arms))},
        "oracle_pass_rate": float(np.mean([
            max(per_arm_scores[a][i][0] for a in arms) for i in range(len(used_items))
        ])),
        "base_pass_rate_on_fit": float(np.mean([s[0] for s in per_arm_scores[BASE_ARM]])),
    }
    router = Router(arms, mean, std, weight, bias,
                    {"fit_items": len(used_items), "truncated": truncated})
    return router, stats


def _calibrate_fallback(arms, per_arm_fields, gate_probs, tau_grid, eta_grid,
                        epsilon: float):
    """Pick (tau, eta) that MAXIMIZE aggregate pass on the fit pool subject
    to NO per-capability regression vs base beyond epsilon. Uses only the
    already-generated per-arm outputs — zero extra GPU. This bakes the
    sealed per-capability gate's own criterion into the router itself."""
    n = len(gate_probs)
    idx = {a: i for i, a in enumerate(arms)}
    experts = [a for a in arms if a not in (BASE_ARM, BLEND_ARM)]
    has_blend = BLEND_ARM in idx
    caps = list(per_arm_fields[BASE_ARM][0].keys()) if n else []
    # base per-capability hit counts
    base_cap = {c: 0 for c in _all_caps(per_arm_fields, arms)}
    base_cap_n = {c: 0 for c in base_cap}
    for i in range(n):
        for c, hit in per_arm_fields[BASE_ARM][i].items():
            base_cap[c] += hit
            base_cap_n[c] += 1

    def route_one(p):
        p_base = p[idx[BASE_ARM]]
        if (1.0 - p_base) < route_one.tau:
            return BASE_ARM
        ranked = sorted(((e, p[idx[e]]) for e in experts), key=lambda kv: kv[1], reverse=True)
        top_e, top_p = ranked[0]
        second_p = ranked[1][1] if len(ranked) > 1 else 0.0
        if has_blend and len(ranked) >= 2 and second_p >= route_one.eta and top_p >= route_one.eta:
            return BLEND_ARM
        if has_blend and p[idx[BLEND_ARM]] >= max(top_p, p_base):
            return BLEND_ARM
        return top_e

    best = None
    for tau in tau_grid:
        for eta in eta_grid:
            route_one.tau, route_one.eta = tau, eta
            agg_hit = 0
            cap_hit = {c: 0 for c in base_cap}
            for i in range(n):
                arm = route_one(gate_probs[i])
                fields = per_arm_fields[arm][i]
                agg_hit += int(all(fields.values()))
                for c, hit in fields.items():
                    cap_hit[c] += hit
            # per-cap regression check vs base
            ok = True
            worst = 0.0
            for c in base_cap:
                if base_cap_n[c] == 0:
                    continue
                delta = (cap_hit[c] - base_cap[c]) / base_cap_n[c]
                worst = min(worst, delta)
                if delta < -epsilon:
                    ok = False
            score = agg_hit / max(n, 1)
            cand = (ok, score, worst, -tau, -eta, tau, eta)
            if ok and (best is None or (score, worst) > (best[1], best[2])):
                best = cand
    if best is None:
        # nothing clears the no-regression bar -> pure base fallback (safe)
        return 1.01, 1.01, {"note": "no config avoided regression; base-only"}
    return best[5], best[6], {"fit_aggregate": round(best[1], 4),
                              "worst_cap_delta_on_fit": round(best[2], 4)}


def _all_caps(per_arm_fields, arms):
    caps = set()
    for arm in arms:
        for f in per_arm_fields[arm]:
            caps.update(f.keys())
    return sorted(caps)


def refit_soft_router(model, tok, expert_names: list, fit_items: list,
                      device: str, budget_seconds: float, seed: int = 0) -> tuple:
    """v2 refit: generate all arms (budgeted), fit the gate on base
    embeddings, then CALIBRATE the confidence fallback + top-2 activation
    against the per-capability no-regression objective. Returns
    (SoftRouter, stats)."""
    arms = arm_list(expert_names)
    t0 = time.monotonic()
    used_items: list = []
    per_arm_pass: dict = {a: [] for a in arms}
    per_arm_fields: dict = {a: [] for a in arms}
    tokens, truncated = 0, False

    for start in range(0, len(fit_items), FIT_CHUNK):
        if time.monotonic() - t0 > budget_seconds * 0.85:
            truncated = True
            break
        chunk = fit_items[start:start + FIT_CHUNK]
        prompts = [chat_prompt(tok, it) for it in chunk]
        for arm in arms:
            with _set_arm(model, arm, expert_names):
                outs, gt = generate_batch(model, tok, prompts, device)
            tokens += gt
            for it, out in zip(chunk, outs):
                sc = score_item(it, out)
                per_arm_pass[arm].append(sc["pass"])
                per_arm_fields[arm].append(sc["fields"])
        used_items.extend(chunk)

    if not used_items:
        raise RuntimeError(f"router budget {budget_seconds}s too small for one chunk")

    n = len(used_items)
    # council fix #3: SOFT targets (KL to per-arm field utility) instead of
    # a hard argmax that suppresses the second expert / the blend.
    soft = _soft_labels_from_fields(arms, per_arm_fields, n)
    hard_labels = soft.argmax(axis=1)          # diagnostic only

    feats = embed_base(model, tok, [chat_prompt(tok, it) for it in used_items], device)

    # council fix #2: OUT-OF-FOLD — fit the gate on a TRAIN split, then
    # calibrate tau/eta on a HELD-OUT split (no in-sample optimism).
    rng = np.random.default_rng(seed)
    order = rng.permutation(n)
    cut = max(int(n * 0.6), 10)
    tr, ca = order[:cut], (order[cut:] if n - cut >= 5 else order)
    mean, std, weight, bias = _fit_logistic(
        feats[tr], None, len(arms), seed=seed, soft_targets=soft[tr])

    def _probs(fs):
        xs = (fs - mean) / std
        lg = xs @ weight.T + bias
        lg = lg - lg.max(axis=1, keepdims=True)
        e = np.exp(lg)
        return e / e.sum(axis=1, keepdims=True)

    ca_fields = {a: [per_arm_fields[a][i] for i in ca] for a in arms}
    tau, eta, calib = _calibrate_fallback(
        arms, ca_fields, _probs(feats[ca]),
        tau_grid=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9],
        eta_grid=[0.1, 0.2, 0.3, 0.4, 0.5], epsilon=0.03)   # <= sealed eps 0.05

    router = SoftRouter(arms, mean, std, weight, bias, tau, eta,
                        {"fit_items": n, "truncated": truncated,
                         "calibration": calib, "oof": True,
                         "train_n": len(tr), "calib_n": len(ca)})
    labels = hard_labels
    # routed-arm histogram on the fit pool (diagnostic)
    routed = router.choose(feats)
    stats = {
        "family": "soft-gate-v2", "arms": arms,
        "fit_items_used": len(used_items), "fit_items_offered": len(fit_items),
        "budget_seconds": budget_seconds, "wall_seconds": time.monotonic() - t0,
        "truncated_by_budget": truncated, "generated_tokens": tokens,
        "tau": tau, "eta": eta, "calibration": calib,
        "gate_label_histogram": {arms[i]: int((labels == i).sum()) for i in range(len(arms))},
        "routed_histogram": {a: routed.count(a) for a in arms},
        "oracle_pass_rate": float(np.mean([
            max(per_arm_pass[a][i] for a in arms) for i in range(len(used_items))])),
        "base_pass_rate_on_fit": float(np.mean(per_arm_pass[BASE_ARM])),
    }
    return router, stats


def route_and_generate(model, tok, router, items: list, device: str,
                       expert_names: list) -> tuple:
    """Serve a shard through the routed head. Dispatches on router family:
    field-merge-v3 does per-field late fusion; gate families route whole
    items to a single arm."""
    if isinstance(router, PresenceMergeRouter):
        return _serve_presence_merge(model, tok, router, items, device, expert_names)
    if isinstance(router, FieldMergeRouter):
        return _serve_field_merge(model, tok, router, items, device, expert_names)
    t0 = time.monotonic()
    prompts = [chat_prompt(tok, it) for it in items]
    feats = embed_base(model, tok, prompts, device)     # frozen-base features
    chosen = router.choose(feats)
    outputs = [None] * len(items)
    tokens = 0
    for arm in router.arms:
        idx = [i for i, c in enumerate(chosen) if c == arm]
        if not idx:
            continue
        with use_arm(model, arm, expert_names):
            outs, gt = generate_batch(model, tok, [prompts[i] for i in idx], device)
        tokens += gt
        for i, out in zip(idx, outs):
            outputs[i] = out
    wall = time.monotonic() - t0
    stats = {
        "wall_seconds": wall,
        "latency_s_per_item": wall / max(len(items), 1),
        "generated_tokens": tokens,
        "arm_histogram": {a: chosen.count(a) for a in router.arms},
    }
    return outputs, stats


# ===================================================================== #
# v3 — FIELD-LEVEL LATE FUSION (council's unanimous fix for overlap)
# ===================================================================== #
#
# Whole-item routing cannot compose overlapping multi-field experts:
# sending a "date + email" prompt to ONE expert must regress the other's
# capability. The fix is to generate the WHOLE output under each candidate
# arm and then MERGE PER FIELD — take each field's value from the arm that
# owns that capability (date/money from A, email/phone from B, name from
# whichever is better). Ownership is decided on a TRAIN split of the fit
# pool and then VALIDATED on a HELD-OUT split; a field is only assigned to
# an expert if it does NOT regress base on that field on the held-out
# split (else it stays on base). Because every emitted field comes from an
# arm that is >= base on that field, the merged output is STRUCTURALLY
# non-regressive per capability — the guarantee v2's calibration only
# approximated (and did so in-sample).


class FieldMergeRouter:
    """field-merge-v3: a per-capability arm assignment + late fusion."""

    def __init__(self, field_arm: dict, feat_fp: str, meta: dict):
        # field_arm: capability -> arm name (BASE_ARM or an expert name)
        self.field_arm = dict(field_arm)
        self.feat_fp = feat_fp
        self.meta = meta or {}
        self.arms = sorted(set(self.field_arm.values()) | {BASE_ARM})

    def distinct_arms(self) -> list:
        return sorted(set(self.field_arm.values()))

    def to_json(self) -> dict:
        return {"kind": "router", "family": "field-merge-v3",
                "field_arm": self.field_arm, "feat_fp": self.feat_fp,
                "meta": self.meta}

    @classmethod
    def from_json(cls, obj: dict) -> "FieldMergeRouter":
        return cls(obj["field_arm"], obj.get("feat_fp", ""), obj.get("meta", {}))

    @classmethod
    def base_only(cls, feat_fp: str = "") -> "FieldMergeRouter":
        return cls({c: BASE_ARM for c in CAPABILITIES}, feat_fp,
                   {"note": "genesis: every field from frozen base"})


def _serve_field_merge(model, tok, router: FieldMergeRouter, items: list,
                       device: str, expert_names: list) -> tuple:
    """Generate under each DISTINCT owning arm, then assemble each item's
    JSON field-by-field from its owner arm's parsed output."""
    t0 = time.monotonic()
    prompts = [chat_prompt(tok, it) for it in items]
    per_arm_parsed: dict = {}
    tokens = 0
    for arm in router.distinct_arms():
        with use_arm(model, arm, expert_names):
            outs, gt = generate_batch(model, tok, prompts, device)
        tokens += gt
        per_arm_parsed[arm] = [parse_json_object(o) or {} for o in outs]
    outputs = []
    for i in range(len(items)):
        # PRESENCE + VALUE both from the field's OWNER arm: the owner is the
        # arm validated best on that capability (out-of-fold), and a
        # specialist detects its own field best. This preserves the
        # per-capability no-regression guarantee. NOTE (measured on RTX
        # 3090/A5000): this cleanly kills the *value*-overlap the council
        # flagged, but exact-match aggregate promotion is bottlenecked by
        # field-PRESENCE detection (which keys to emit) — a separate problem
        # no single arm solves here. See README "Router v3 verdict".
        merged = {}
        for cap, arm in router.field_arm.items():
            val = per_arm_parsed[arm][i].get(cap)
            if val is not None:               # owner detected this field
                merged[cap] = val
        outputs.append(json.dumps(merged, sort_keys=True))
    wall = time.monotonic() - t0
    stats = {
        "wall_seconds": wall,
        "latency_s_per_item": wall / max(len(items), 1),
        "generated_tokens": tokens,
        "distinct_arms": router.distinct_arms(),
        "field_arm": router.field_arm,
    }
    return outputs, stats


def _percap_accuracy(idxs, per_arm_fields, arm, cap):
    """Accuracy of `arm` on capability `cap` over items in idxs that contain
    it; returns (acc, n)."""
    hit = n = 0
    for i in idxs:
        f = per_arm_fields[arm][i]
        if cap in f:
            hit += f[cap]
            n += 1
    return (hit / n if n else None), n


def refit_field_router(model, tok, expert_names: list, fit_items: list,
                       device: str, budget_seconds: float, seed: int = 0,
                       epsilon: float = 0.03, feat_fp: str = "") -> tuple:
    """Assign each capability to its best non-regressive arm, decided on a
    TRAIN split and validated on a HELD-OUT split of the fit pool (council
    fix #2 — out-of-fold, so the no-regression claim is honest). Generates
    under base + each expert under a HARD budget deadline (fix #5)."""
    arms = arm_list(expert_names, include_blend=False)   # base + experts only
    deadline = time.monotonic() + budget_seconds
    per_arm_fields: dict = {a: [] for a in arms}
    used_items: list = []
    tokens, truncated = 0, False

    for start in range(0, len(fit_items), FIT_CHUNK):
        # hard deadline: leave headroom for the last arm's generation
        if time.monotonic() >= deadline - 5.0:
            truncated = True
            break
        chunk = fit_items[start:start + FIT_CHUNK]
        prompts = [chat_prompt(tok, it) for it in chunk]
        for arm in arms:
            if time.monotonic() >= deadline:
                truncated = True
                break
            with use_arm(model, arm, expert_names):
                outs, gt = generate_batch(model, tok, prompts, device)
            tokens += gt
            for it, out in zip(chunk, outs):
                per_arm_fields[arm].append(score_item(it, out)["fields"])
        else:
            used_items.extend(chunk)
            continue
        break   # deadline hit mid-chunk; drop the partial chunk

    n = len(used_items)
    if n < 20:
        raise RuntimeError(f"field-router budget too small: only {n} fit items")

    # out-of-fold split: assign on train, validate no-regression on calib
    rng = np.random.default_rng(seed)
    order = rng.permutation(n)
    cut = max(int(n * 0.6), 10)
    train_idx, calib_idx = list(order[:cut]), list(order[cut:])
    if len(calib_idx) < 5:                    # tiny pool: fall back to LOO-ish
        train_idx, calib_idx = list(order), list(order)

    field_arm, per_field = {}, {}
    for cap in CAPABILITIES:
        base_tr, base_tr_n = _percap_accuracy(train_idx, per_arm_fields, BASE_ARM, cap)
        if base_tr is None:
            field_arm[cap] = BASE_ARM
            continue
        # pick the arm with best TRAIN accuracy on this capability
        best_arm, best_acc = BASE_ARM, base_tr
        for arm in expert_names:
            acc, _ = _percap_accuracy(train_idx, per_arm_fields, arm, cap)
            if acc is not None and acc > best_acc + 1e-9:
                best_arm, best_acc = arm, acc
        # HELD-OUT validation: only keep an expert if it does NOT regress
        # base on this capability on the calib split (fix #2).
        chosen = best_arm
        val = {}
        if best_arm != BASE_ARM:
            base_ca, _ = _percap_accuracy(calib_idx, per_arm_fields, BASE_ARM, cap)
            exp_ca, exp_n = _percap_accuracy(calib_idx, per_arm_fields, best_arm, cap)
            val = {"train_base": round(base_tr, 3), "train_best": round(best_acc, 3),
                   "calib_base": None if base_ca is None else round(base_ca, 3),
                   "calib_expert": None if exp_ca is None else round(exp_ca, 3),
                   "calib_n": exp_n}
            if base_ca is not None and exp_ca is not None and exp_ca < base_ca - epsilon:
                chosen = BASE_ARM          # would regress on held-out -> revert
                val["reverted_to_base"] = True
        field_arm[cap] = chosen
        per_field[cap] = {"arm": chosen, **val}

    router = FieldMergeRouter(field_arm, feat_fp,
                              {"fit_items": n, "truncated": truncated,
                               "epsilon": epsilon, "per_field": per_field,
                               "train_n": len(train_idx), "calib_n": len(calib_idx)})
    stats = {
        "family": "field-merge-v3", "arms": arms,
        "fit_items_used": n, "fit_items_offered": len(fit_items),
        "budget_seconds": budget_seconds, "wall_seconds": budget_seconds - max(deadline - time.monotonic(), 0),
        "truncated_by_budget": truncated, "generated_tokens": tokens,
        "field_arm": field_arm, "per_field": per_field,
        "distinct_arms": router.distinct_arms(),
    }
    return router, stats


# ===================================================================== #
# v4 — PRESENCE-MASKED FIELD MERGE (council: presence is a SUPERVISED problem)
# ===================================================================== #
#
# v3 late-fused VALUES correctly but let each owner arm decide field
# PRESENCE by emission, so hallucinated keys (false positives) tanked the
# exact-key-set metric — and the internal per-cap metric was blind to them.
# v4 splits the two decisions the 0.5B was failing jointly:
#   presence[c] = should key c be emitted?  -> supervised multilabel head on
#                 the FROZEN-BASE EMBEDDING (gold labels are free from the
#                 fit shard; base hidden states separate presence even when
#                 base GENERATION does not, same reason the gate works).
#   value[c]    = owner-arm generation      -> OOF-validated assignment (v3).
# Serve emits EXACTLY the predicted key-set, values from the value owner
# (with a fallback chain), and never emits a presence=0 key -> kills FP.


class PresenceHead:
    """Per-capability sigmoid logistic over standardized base embeddings,
    with per-field thresholds calibrated out-of-fold for the exact-set
    metric. Tiny, CPU, gold-supervised."""

    def __init__(self, caps, mean, std, weight, bias, thresholds, meta=None):
        self.caps = list(caps)
        self.mean = np.asarray(mean, dtype=np.float32)
        self.std = np.asarray(std, dtype=np.float32)
        self.weight = np.asarray(weight, dtype=np.float32)   # (C, D)
        self.bias = np.asarray(bias, dtype=np.float32)       # (C,)
        self.thresholds = np.asarray(thresholds, dtype=np.float32)  # (C,)
        self.meta = meta or {}

    def probs(self, feats: np.ndarray) -> np.ndarray:
        x = (feats - self.mean) / self.std
        logits = x @ self.weight.T + self.bias
        return 1.0 / (1.0 + np.exp(-np.clip(logits, -40, 40)))

    def predict_keys(self, feats: np.ndarray) -> list:
        """Returns, per row, the set of capabilities to emit."""
        p = self.probs(feats)
        out = []
        for row in p:
            out.append({self.caps[j] for j in range(len(self.caps))
                        if row[j] >= self.thresholds[j]})
        return out

    def to_json(self) -> dict:
        return {"caps": self.caps, "mean": self.mean.tolist(),
                "std": self.std.tolist(), "weight": self.weight.tolist(),
                "bias": self.bias.tolist(), "thresholds": self.thresholds.tolist(),
                "meta": self.meta}

    @classmethod
    def from_json(cls, obj):
        return cls(obj["caps"], obj["mean"], obj["std"], obj["weight"],
                   obj["bias"], obj["thresholds"], obj.get("meta", {}))


def _fit_presence_head(feats, Y, seed=0, steps=600, lr=0.05):
    n, d = feats.shape
    c = Y.shape[1]
    mean = feats.mean(axis=0).astype(np.float32)
    std = (feats.std(axis=0) + 1e-6).astype(np.float32)
    x = torch.tensor((feats - mean) / std, dtype=torch.float32)
    y = torch.tensor(Y, dtype=torch.float32)
    pos = y.sum(0).clamp(min=1.0)
    neg = (n - pos).clamp(min=1.0)
    pos_weight = (neg / pos).clamp(max=20.0)
    torch.manual_seed(seed)
    lin = torch.nn.Linear(d, c)
    with torch.no_grad():
        lin.weight.mul_(0.01)
        prior = (pos / n).clamp(1e-3, 1 - 1e-3)
        lin.bias.copy_(torch.log(prior / (1 - prior)))
    opt = torch.optim.AdamW(lin.parameters(), lr=lr, weight_decay=1e-2)
    bce = torch.nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    for _ in range(steps):
        opt.zero_grad()
        loss = bce(lin(x), y)
        loss.backward()
        opt.step()
    return (mean, std, lin.weight.detach().numpy().astype(np.float32),
            lin.bias.detach().numpy().astype(np.float32))


def _f1(y, yhat):
    tp = float((y * yhat).sum())
    fp = float(((1 - y) * yhat).sum())
    fn = float((y * (1 - yhat)).sum())
    prec = tp / (tp + fp + 1e-9)
    rec = tp / (tp + fn + 1e-9)
    return 2 * prec * rec / (prec + rec + 1e-9)


def _calibrate_presence_thresholds(probs, Y, baseline_mask, epsilon=0.03):
    """Per-field threshold on HELD-OUT: maximize F1, never regress the
    baseline (base-arm key emission) F1 by more than epsilon."""
    C = probs.shape[1]
    grid = np.linspace(0.05, 0.95, 19)
    thr = np.full(C, 0.5, dtype=np.float32)
    per_cap = {}
    for j in range(C):
        y = Y[:, j]
        base_f1 = _f1(y, baseline_mask[:, j].astype(np.float32))
        best_f1, best_t = -1.0, 0.5
        for t in grid:
            f1 = _f1(y, (probs[:, j] >= t).astype(np.float32))
            if f1 > best_f1 + 1e-12:
                best_f1, best_t = f1, float(t)
        if best_f1 < base_f1 - epsilon:
            # can't beat baseline: mimic it (high thr => conservative emit)
            best_t = 0.9
            note = "fallback_conservative"
        else:
            note = "head"
        thr[j] = best_t
        per_cap[j] = {"thr": round(best_t, 3), "head_f1": round(best_f1, 3),
                      "base_f1": round(base_f1, 3), "mode": note}
    return thr, per_cap


class PresenceMergeRouter:
    """presence-merge-v4: supervised presence head + OOF value owners."""

    def __init__(self, field_arm, presence, feat_fp, meta):
        self.field_arm = dict(field_arm)              # cap -> value owner arm
        self.presence = presence                      # PresenceHead | None (genesis)
        self.feat_fp = feat_fp
        self.meta = meta or {}
        self.arms = sorted(set(self.field_arm.values()) | {BASE_ARM})

    def distinct_value_arms(self):
        return sorted(set(self.field_arm.values()))

    def to_json(self):
        return {"kind": "router", "family": "presence-merge-v4",
                "field_arm": self.field_arm, "feat_fp": self.feat_fp,
                "presence": None if self.presence is None else self.presence.to_json(),
                "meta": self.meta}

    @classmethod
    def from_json(cls, obj):
        pres = obj.get("presence")
        return cls(obj["field_arm"],
                   PresenceHead.from_json(pres) if pres else None,
                   obj.get("feat_fp", ""), obj.get("meta", {}))

    @classmethod
    def base_only(cls, feat_fp=""):
        return cls({c: BASE_ARM for c in CAPABILITIES}, None, feat_fp,
                   {"note": "genesis: base passthrough (schema-filtered)"})


def _serve_presence_merge(model, tok, router, items, device, expert_names):
    from plane.domain import schema_filter
    t0 = time.monotonic()
    prompts = [chat_prompt(tok, it) for it in items]

    # presence key-set per item
    if router.presence is None:            # genesis: base decides presence
        gen_arms = [BASE_ARM]
        key_sets = None
    else:
        feats = embed_base(model, tok, prompts, device)
        key_sets = router.presence.predict_keys(feats)
        # only generate under value-owner arms that own >=1 predicted key
        needed = {router.field_arm.get(c, BASE_ARM)
                  for ks in key_sets for c in ks}
        gen_arms = sorted(needed | {BASE_ARM})   # base kept for fallback

    per_arm_parsed = {}
    tokens = 0
    for arm in gen_arms:
        with use_arm(model, arm, expert_names):
            outs, gt = generate_batch(model, tok, prompts, device)
        tokens += gt
        per_arm_parsed[arm] = [schema_filter(parse_json_object(o) or {}) for o in outs]

    outputs = []
    for i in range(len(items)):
        base_out = per_arm_parsed[BASE_ARM][i]
        keys = key_sets[i] if key_sets is not None else set(base_out.keys())
        merged = {}
        for cap in keys:
            owner = router.field_arm.get(cap, BASE_ARM)
            # value fallback chain: owner -> base -> any arm that emitted it
            val = per_arm_parsed.get(owner, base_out)[i].get(cap)
            if val is None:
                val = base_out.get(cap)
            if val is None:
                for a in gen_arms:
                    v = per_arm_parsed[a][i].get(cap)
                    if v is not None:
                        val = v
                        break
            if val is not None:                # never emit a key with no value
                merged[cap] = val
        outputs.append(json.dumps(merged, sort_keys=True))
    wall = time.monotonic() - t0
    stats = {"wall_seconds": wall, "latency_s_per_item": wall / max(len(items), 1),
             "generated_tokens": tokens, "gen_arms": gen_arms,
             "field_arm": router.field_arm}
    return outputs, stats


def refit_presence_router(model, tok, expert_names, fit_items, device,
                          budget_seconds, seed=0, epsilon=0.03, feat_fp=""):
    """Budgeted gen under base+experts (hard deadline, partial-chunk
    rollback); OOF value-owner assignment; gold-supervised presence head on
    base embeddings; per-field thresholds calibrated on the HELD-OUT split."""
    from plane.domain import schema_filter
    arms = arm_list(expert_names, include_blend=False)
    t0 = time.monotonic()
    deadline = t0 + budget_seconds
    per_arm_fields = {a: [] for a in arms}      # value-on-present (owner pick)
    per_arm_parsed = {a: [] for a in arms}      # for base-emission baseline
    used_items = []
    tokens, truncated = 0, False
    for start in range(0, len(fit_items), FIT_CHUNK):
        if time.monotonic() >= deadline - 5.0:
            truncated = True
            break
        chunk = fit_items[start:start + FIT_CHUNK]
        prompts = [chat_prompt(tok, it) for it in chunk]
        ok = True
        buf_fields = {a: [] for a in arms}
        buf_parsed = {a: [] for a in arms}
        for arm in arms:
            if time.monotonic() >= deadline:
                truncated = True; ok = False; break
            with use_arm(model, arm, expert_names):
                outs, gt = generate_batch(model, tok, prompts, device)
            tokens += gt
            for it, out in zip(chunk, outs):
                buf_fields[arm].append(score_item(it, out)["fields"])
                buf_parsed[arm].append(schema_filter(parse_json_object(out) or {}))
        if not ok:                              # deadline mid-chunk: roll back
            break
        for a in arms:                          # commit whole chunk atomically
            per_arm_fields[a].extend(buf_fields[a])
            per_arm_parsed[a].extend(buf_parsed[a])
        used_items.extend(chunk)

    n = len(used_items)
    if n < 20:
        raise RuntimeError(f"presence-router budget too small: {n} fit items")

    rng = np.random.default_rng(seed)
    order = rng.permutation(n)
    cut = max(int(n * 0.6), 10)
    train_idx, calib_idx = list(order[:cut]), list(order[cut:])
    if len(calib_idx) < 8:                      # OOF degeneracy -> hard fail
        raise RuntimeError(f"OOF calibration split degenerate: calib_n={len(calib_idx)}")

    # ---- value owner per capability (OOF-validated on value accuracy) ----
    field_arm, per_field = {}, {}
    for cap in CAPABILITIES:
        base_tr, _ = _percap_accuracy(train_idx, per_arm_fields, BASE_ARM, cap)
        if base_tr is None:
            field_arm[cap] = BASE_ARM; continue
        best_arm, best_acc = BASE_ARM, base_tr
        for arm in expert_names:
            acc, _ = _percap_accuracy(train_idx, per_arm_fields, arm, cap)
            if acc is not None and acc > best_acc + 1e-9:
                best_arm, best_acc = arm, acc
        chosen, val = best_arm, {}
        if best_arm != BASE_ARM:
            b_ca, _ = _percap_accuracy(calib_idx, per_arm_fields, BASE_ARM, cap)
            e_ca, e_n = _percap_accuracy(calib_idx, per_arm_fields, best_arm, cap)
            val = {"train_base": round(base_tr, 3), "train_best": round(best_acc, 3),
                   "calib_base": None if b_ca is None else round(b_ca, 3),
                   "calib_expert": None if e_ca is None else round(e_ca, 3),
                   "calib_n": e_n}
            if b_ca is not None and e_ca is not None and e_ca < b_ca - epsilon:
                chosen = BASE_ARM; val["reverted_to_base"] = True
        field_arm[cap] = chosen
        per_field[cap] = {"arm": chosen, **val}

    # ---- gold presence labels + base-embedding features ----
    caps = list(CAPABILITIES)
    Y = np.zeros((n, len(caps)), dtype=np.float32)
    for i, it in enumerate(used_items):
        for j, c in enumerate(caps):
            if c in it.target:
                Y[i, j] = 1.0
    feats = embed_base(model, tok, [chat_prompt(tok, it) for it in used_items], device)

    # ---- fit presence head on TRAIN, calibrate thresholds on HELD-OUT ----
    mean, std, W, b = _fit_presence_head(feats[train_idx], Y[train_idx], seed=seed)
    xg = (feats - mean) / std
    probs_all = 1.0 / (1.0 + np.exp(-np.clip(xg @ W.T + b, -40, 40)))
    # baseline presence = base arm emits key c (v3 behavior)
    base_emit = np.zeros((n, len(caps)), dtype=np.float32)
    for i in range(n):
        for j, c in enumerate(caps):
            if c in per_arm_parsed[BASE_ARM][i]:
                base_emit[i, j] = 1.0
    thr, thr_diag = _calibrate_presence_thresholds(
        probs_all[calib_idx], Y[calib_idx], base_emit[calib_idx], epsilon=epsilon)
    head = PresenceHead(caps, mean, std, W, b, thr,
                        {"train_n": len(train_idx), "calib_n": len(calib_idx),
                         "per_cap": {caps[j]: thr_diag[j] for j in range(len(caps))}})

    # held-out exact-set diagnostics: head key-set vs gold, and base-emit vs gold
    def _setacc(mask):
        return float(np.mean([
            set(np.array(caps)[mask[i] > 0]) == set(np.array(caps)[Y[i] > 0])
            for i in calib_idx]))
    head_mask = (probs_all >= thr).astype(np.float32)
    calib_setacc_head = _setacc(head_mask)
    calib_setacc_base = _setacc(base_emit)

    router = PresenceMergeRouter(field_arm, head, feat_fp,
                                 {"fit_items": n, "truncated": truncated,
                                  "epsilon": epsilon, "per_field": per_field,
                                  "presence_per_cap": head.meta["per_cap"],
                                  "calib_keyset_acc_head": round(calib_setacc_head, 3),
                                  "calib_keyset_acc_base": round(calib_setacc_base, 3),
                                  "train_n": len(train_idx), "calib_n": len(calib_idx)})
    stats = {
        "family": "presence-merge-v4", "arms": arms,
        "fit_items_used": n, "fit_items_offered": len(fit_items),
        "budget_seconds": budget_seconds, "wall_seconds": time.monotonic() - t0,
        "truncated_by_budget": truncated, "generated_tokens": tokens,
        "field_arm": field_arm, "per_field": per_field,
        "presence_per_cap": head.meta["per_cap"],
        "calib_keyset_acc_head": round(calib_setacc_head, 3),
        "calib_keyset_acc_base": round(calib_setacc_base, 3),
        "distinct_value_arms": router.distinct_value_arms(),
    }
    return router, stats
