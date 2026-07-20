"""THE experiment — does a real overlapping-expert + cheaply-refit router
make one real frozen model better, and what does it cost ARTISAN?

    python -m plane.run_experiment --tiny            # CPU mechanics dry-run
    python -m plane.run_experiment                    # real run (GPU)

Script of the run:
  0. pin the base model by content hash (repo+revision+file hashes+arch)
  1. GENESIS head: frozen base, base-only router, sealed-shard score
  2. submitter "Corban-A" trains expert A on HIS OWN {date,money,name}
     slice (submitter compute, metered separately), signs, submits
       -> sandbox, budgeted router refit, sealed paired eval, CAS promote
  3. submitter "Ashvale-B" trains expert B on {email,phone,name} — the
     OVERLAPPING expert — signs, submits -> router now gates 4 arms
  4. adversary "Sly" submits: a NaN adapter (sandbox must block), a
     wrong-rank adapter (ABI must block), and noise adapters with
     inflated claims until his bond runs dry (Sybil economics must block
     the last one BEFORE any GPU spins)
  5. audit-shard report + per-arm diagnostics (base / A / B / blend /
     routed head measured on the SAME untouched shard) + full meter dump

Everything downstream of the submitters runs through PlaneOrchestrator —
the same code path a hostile stranger would hit.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from identity.keys import AgentIdentity
from plane import model_ops
from plane.abi import ABI_RANK, adapter_abi_manifest_fields
from plane.basepin import build_base_pin, expected_adapter_keys
from plane.domain import (EXPERT_A_CAPS, EXPERT_B_CAPS, aggregate, make_items,
                          score_item)
from plane.evalplane import AUDIT_SHARD_N, draw_shard
from plane.loop import PlaneOrchestrator
from plane.meter import Meter
from plane.router import _set_arm

DOMAIN = "clerk-extract-v1"
REAL_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"


# ------------------------------------------------------------ base setup

def prepare_tiny_base(root: Path) -> tuple[str, str, str]:
    """A tiny random Qwen2 (2 layers, hidden 32) with its OWN tiny BPE
    tokenizer (2k vocab — a 151k vocab makes fp32 CPU logits eat ~15GB) —
    validates every mechanic on CPU in minutes. Quality is meaningless
    here by design; the dry run may force the promote path (marked)."""
    from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers
    from transformers import PreTrainedTokenizerFast, Qwen2Config, Qwen2ForCausalLM
    model_dir = root / "tiny_base"
    if not (model_dir / "config.json").exists():
        corpus = []
        for it in make_items(1, 400):
            corpus.append(it.prompt)
            corpus.append(json.dumps(it.target, sort_keys=True))
        backend = Tokenizer(models.BPE(unk_token="<unk>"))
        backend.pre_tokenizer = pre_tokenizers.ByteLevel()
        backend.decoder = decoders.ByteLevel()
        backend.train_from_iterator(corpus, trainers.BpeTrainer(
            vocab_size=2000,
            special_tokens=["<unk>", "<|endoftext|>", "<|im_start|>", "<|im_end|>"]))
        tok = PreTrainedTokenizerFast(
            tokenizer_object=backend, unk_token="<unk>",
            eos_token="<|endoftext|>", pad_token="<|endoftext|>")
        tok.chat_template = (
            "{% for message in messages %}<|im_start|>{{ message.role }}\n"
            "{{ message.content }}<|im_end|>\n{% endfor %}"
            "{% if add_generation_prompt %}<|im_start|>assistant\n{% endif %}")
        cfg = Qwen2Config(
            vocab_size=len(tok) + 8, hidden_size=32, intermediate_size=64,
            num_hidden_layers=2, num_attention_heads=4, num_key_value_heads=2,
            max_position_embeddings=2048, tie_word_embeddings=True,
            eos_token_id=tok.eos_token_id, pad_token_id=tok.pad_token_id,
        )
        import torch
        torch.manual_seed(0)
        model = Qwen2ForCausalLM(cfg)
        model.save_pretrained(model_dir, safe_serialization=True)
        tok.save_pretrained(model_dir)
    return str(model_dir), "local/tiny-qwen2", "tiny-r0"


def prepare_real_base(root: Path, repo: str) -> tuple[str, str, str]:
    from huggingface_hub import snapshot_download
    local = snapshot_download(repo)  # resolves to .../snapshots/<commit>/
    revision = Path(local).name
    return local, repo, revision


# ------------------------------------------------------- submitter side

def submitter_make_expert(identity: AgentIdentity, model_dir: str, pin: dict,
                          caps, seed: int, n_train: int, device: str,
                          meter: Meter, tag: str,
                          epochs: int = 2) -> tuple[bytes, dict, float]:
    """A submitter's whole life: make data, train a LoRA on THEIR compute,
    self-evaluate honestly on their own held-out slice."""
    train_items = make_items(seed, n_train, allowed_caps=caps)
    held_out = make_items(seed + 7919, 100, allowed_caps=caps)
    tok = model_ops.load_tokenizer(model_dir)
    base = model_ops.load_base(model_dir, device)   # submitter's OWN copy
    with meter.phase(f"submitter_train_{tag}", "submitter",
                     f"{len(train_items)} items x {epochs} epochs") as ph:
        blob, stats = model_ops.train_lora_expert(
            base, tok, pin, train_items, device, epochs=epochs, seed=seed)
        ph.tokens = stats["trained_tokens"]
    # honest self-eval: their adapter alone, their held-out slice
    peft = model_ops.attach_adapters(base, pin, {"self": blob})
    with meter.phase(f"submitter_selfeval_{tag}", "submitter") as ph:
        prompts = [model_ops.chat_prompt(tok, it) for it in held_out]
        outs, gt = model_ops.generate_batch(peft, tok, prompts, device)
        ph.tokens = gt
    agg = aggregate(held_out, [score_item(it, o) for it, o in zip(held_out, outs)])
    del peft, base
    import gc, torch
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return blob, stats, agg["pass_rate"]


def make_envelope(identity: AgentIdentity, pin: dict, expert_ref: str,
                  dataset_name: str, dataset_sha: str, claimed: float,
                  recipe: dict) -> dict:
    manifest = {
        "kind": "adapter_expert",
        "domain": DOMAIN,
        "agent_id": identity.agent_id,
        "wisket_id": None,
        "abi": adapter_abi_manifest_fields(pin),
        "artifacts": {"expert": expert_ref},
        "dataset_manifest": {"sources": [{
            "name": dataset_name, "license": "CC0-1.0", "sha256": dataset_sha,
        }]},
        "recipe": recipe,
        "claimed_score": claimed,
    }
    return {"manifest": manifest, "signature": identity.sign_manifest(manifest)}


# ------------------------------------------------------------ adversary

def make_nan_adapter(pin: dict) -> bytes:
    import numpy as np
    from safetensors.numpy import save as np_save
    tensors = {}
    for key, shape in expected_adapter_keys(pin, ABI_RANK).items():
        t = np.zeros(shape, dtype=np.float32)
        t.flat[0] = np.nan
        tensors[key] = t
    return np_save(tensors)


def make_wrong_rank_adapter(pin: dict) -> bytes:
    import numpy as np
    from safetensors.numpy import save as np_save
    tensors = {k: np.zeros(s, dtype=np.float32)
               for k, s in expected_adapter_keys(pin, ABI_RANK * 2).items()}
    return np_save(tensors)


def make_noise_adapter(pin: dict, seed: int) -> bytes:
    import numpy as np
    from safetensors.numpy import save as np_save
    rng = np.random.default_rng(seed)
    tensors = {k: rng.normal(0, 0.02, s).astype(np.float32)
               for k, s in expected_adapter_keys(pin, ABI_RANK).items()}
    return np_save(tensors)


# ------------------------------------------------------------ diagnostics

def per_arm_diagnostics(orch: PlaneOrchestrator, expert_names: list) -> dict:
    """Score every arm ALONE on the audit shard — the honest answer to
    'does the router beat any single expert?'"""
    import numpy as np
    shard = draw_shard(orch.secret, DOMAIN, "audit", 0, AUDIT_SHARD_N)
    prompts = [model_ops.chat_prompt(orch.tok, it) for it in shard]
    from plane.router import arm_list
    results = {}
    orch._drop_blend()
    for arm in arm_list(expert_names):
        with orch.meter.phase(f"diagnostic_{arm}", "artisan") as ph:
            with _set_arm(orch._serving_model(), arm, expert_names):
                outs, gt = model_ops.generate_batch(
                    orch._serving_model(), orch.tok, prompts, orch.device)
            ph.tokens = gt
        agg = aggregate(shard, [score_item(it, o) for it, o in zip(shard, outs)])
        # corrected FP/FN-aware metric (council v4): per-field exact + keyset P/R
        from plane.domain import score_full, CAPABILITIES
        fulls = [score_full(it, o) for it, o in zip(shard, outs)]
        tp = sum(f["keyset_tp"] for f in fulls)
        fp = sum(f["keyset_fp"] for f in fulls)
        fn = sum(f["keyset_fn"] for f in fulls)
        agg["exact_set"] = float(np.mean([f["exact_set"] for f in fulls]))
        agg["keyset_precision"] = tp / (tp + fp + 1e-9)
        agg["keyset_recall"] = tp / (tp + fn + 1e-9)
        agg["fields_exact"] = {c: float(np.mean([f["fields_exact"][c] for f in fulls]))
                               for c in CAPABILITIES}
        results[arm] = agg
    return results


# -------------------------------------------------------------- the run

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiny", action="store_true", help="CPU mechanics dry-run")
    ap.add_argument("--root", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--router-budget", type=float, default=None)
    ap.add_argument("--eval-n", type=int, default=None)
    ap.add_argument("--fit-n", type=int, default=None)
    ap.add_argument("--n-train", type=int, default=None)
    ap.add_argument("--router",
                    choices=["presence", "field", "soft", "logistic"], default="presence",
                    help="presence = v4 (supervised presence head + field late fusion); "
                         "field = v3 (per-field late fusion, OOF); soft = v2")
    args = ap.parse_args()

    t_start = time.time()
    root = Path(args.root or (REPO_ROOT / ("var/plane_tiny" if args.tiny else "var/plane_real")))
    root.mkdir(parents=True, exist_ok=True)
    meter = Meter()

    if args.tiny:
        model_dir, repo, revision = prepare_tiny_base(root)
        eval_n, fit_n, n_train, budget = (args.eval_n or 40), (args.fit_n or 24), \
            (args.n_train or 48), (args.router_budget or 900.0)
    else:
        model_dir, repo, revision = prepare_real_base(root, REAL_MODEL)
        eval_n, fit_n, n_train, budget = (args.eval_n or 250), (args.fit_n or 160), \
            (args.n_train or 1200), (args.router_budget or 240.0)

    pin = build_base_pin(model_dir, repo, revision)
    print(f"[pin] {repo}@{revision} fingerprint {pin['fingerprint'][:16]} "
          f"({pin['architecture']}, {pin['num_hidden_layers']} layers)")

    orch = PlaneOrchestrator(root / "var", model_dir, meter=meter,
                             router_budget_s=budget, eval_shard_n=eval_n,
                             fit_pool_n=fit_n, router_kind=args.router)
    if args.tiny:
        # DRY RUN ONLY: force the promote path so CAS/lineage mechanics are
        # exercised even though a random tiny model can't clear a real gate.
        orch.gate_override = "always"
    print(f"[env] device={orch.device} eval_n={eval_n} fit_n={fit_n} "
          f"router_budget={budget}s router_kind={args.router} "
          f"usd/hr={meter.usd_per_hour}")

    results: dict = {"config": {
        "model": repo, "revision": revision, "fingerprint": pin["fingerprint"],
        "device": orch.device, "eval_shard_n": eval_n, "fit_pool_n": fit_n,
        "router_budget_s": budget, "n_train_per_expert": n_train,
        "tiny_dry_run": bool(args.tiny),
        "router_kind": args.router,
        "usd_per_hour": meter.usd_per_hour,
    }, "events": []}

    # -- 1. genesis --------------------------------------------------------
    head = orch.genesis(DOMAIN, "structured field extraction (clerk)", pin)
    print(f"[genesis] head v{head['version']} sealed pass rate {head['score']:.4f}")
    results["genesis_score"] = head["score"]

    # -- 2/3. the two real, overlapping submitters -------------------------
    submitters = [
        ("Corban-A", sorted(EXPERT_A_CAPS), 101, "slice-A(date,money,name)"),
        ("Ashvale-B", sorted(EXPERT_B_CAPS), 202, "slice-B(email,phone,name)"),
    ]
    submitted_experts = []   # (name, expert_ref, caps) — kept for diagnostics
    for name, caps, seed, ds_name in submitters:
        ident = AgentIdentity.generate()
        agent_id = orch.register_agent(name, ident.public_key_hex)
        print(f"[{name}] training expert on own slice {caps} (submitter compute)...")
        blob, tstats, self_score = submitter_make_expert(
            ident, model_dir, pin, caps, seed, n_train, orch.device, meter, name)
        expert_ref = orch.store.put(blob)
        submitted_experts.append((name, expert_ref, caps))
        # dataset provenance: hash of the submitter's training slice
        import hashlib
        ds_sha = hashlib.sha256(json.dumps(
            [(it.prompt, it.target) for it in
             make_items(seed, n_train, allowed_caps=caps)],
            sort_keys=True).encode()).hexdigest()
        env = make_envelope(ident, pin, expert_ref, ds_name, ds_sha, self_score,
                            {"epochs": 2, "rank": ABI_RANK, "seed": seed})

        print(f"[{name}] submitting (honest claimed self-score {self_score:.3f}; "
              f"train {tstats['wall_seconds']:.0f}s loss {tstats['final_loss']:.3f})")
        outcome = orch.submit_adapter(env)
        print(f"[{name}] -> {outcome.status} | submitter sees only: {outcome.coarse}")
        print(f"          internal: {outcome.reason[:200]}")
        g = (outcome.internal or {}).get("gate", {})
        rf = (outcome.internal or {}).get("refit_stats", {})
        if g:
            print(f"          [gate] aggregate delta_mean {g.get('delta_mean'):+.4f} "
                  f"95%-lower-bound {g.get('delta_lower_bound'):+.4f} | "
                  f"candidate pass {g.get('candidate',{}).get('pass_rate')} | "
                  f"per-cap-blocks {g.get('per_cap_blocks')}")
            if rf.get("family") == "presence-merge-v4":
                print(f"          [router:presence-merge-v4] field_arm={rf.get('field_arm')}")
                print(f"          [router:value-owner-oof] {rf.get('per_field')}")
                print(f"          [router:presence-head] {rf.get('presence_per_cap')}")
                print(f"          [router:keyset-acc-heldout] head={rf.get('calib_keyset_acc_head')} "
                      f"base={rf.get('calib_keyset_acc_base')} "
                      f"value_arms={rf.get('distinct_value_arms')} "
                      f"truncated={rf.get('truncated_by_budget')}")
            elif rf.get("family") == "field-merge-v3":
                print(f"          [router:field-merge-v3] field_arm={rf.get('field_arm')}")
                print(f"          [router:per-field-validation] {rf.get('per_field')}")
                print(f"          [router] distinct_arms={rf.get('distinct_arms')} "
                      f"truncated={rf.get('truncated_by_budget')} "
                      f"refit_gen_tokens={rf.get('generated_tokens')}")
            else:
                print(f"          [router:{rf.get('family','v1')}] "
                      f"tau={rf.get('tau')} eta={rf.get('eta')} "
                      f"routed_hist={rf.get('routed_histogram', rf.get('label_histogram'))} "
                      f"calib={rf.get('calibration')} "
                      f"truncated={rf.get('truncated_by_budget')} "
                      f"refit_wall {rf.get('wall_seconds', 0):.1f}s "
                      f"oracle_pass {rf.get('oracle_pass_rate')}")
        results["events"].append({
            "who": name, "what": "adapter_submission", "status": outcome.status,
            "coarse_to_submitter": outcome.coarse, "internal": outcome.internal,
            "reason_internal": outcome.reason, "train_stats": tstats,
            "claimed": self_score, "head_version": outcome.head_version,
        })

    # -- 4. adversary ------------------------------------------------------
    sly = AgentIdentity.generate()
    sly_id = orch.register_agent("Sly", sly.public_key_hex)
    adversarial = [
        ("nan_adapter", make_nan_adapter(pin), 0.99),
        ("wrong_rank_adapter", make_wrong_rank_adapter(pin), 0.99),
        ("noise_adapter_1", make_noise_adapter(pin, 1), 0.95),
        ("noise_adapter_2", make_noise_adapter(pin, 2), 0.95),
    ]
    for label, blob, claim in adversarial:
        ref = orch.store.put(blob)
        # Sly's manifest CLAIMS the legal ABI (rank 16) even when the blob
        # ships something else — only the sandbox can catch that.
        env = make_envelope(sly, pin, ref, f"sly-{label}", "0" * 64, claim,
                            {"note": "totally legit"})
        outcome = orch.submit_adapter(env)
        bal = orch.registry.reputation_balance(sly_id)
        print(f"[Sly] {label}: {outcome.status} (bond now {bal:.0f}) | "
              f"{outcome.reason[:110]}")
        results["events"].append({
            "who": "Sly", "what": label, "status": outcome.status,
            "reason_internal": outcome.reason,
            "coarse_to_submitter": outcome.coarse, "bond_after": bal,
        })

    # -- 5. audit + diagnostics + meter ------------------------------------
    head = orch.registry.get_head(DOMAIN)
    print(f"[head] final v{head['version']} sealed score {head['score']:.4f} "
          f"({len(head['expert_refs'])} experts)")
    audit = orch.audit_report(DOMAIN)
    print(f"[audit] untouched shard: pass {audit['audit']['pass_rate']:.4f} "
          f"per-cap { {k: round(v, 3) for k, v in audit['audit']['per_capability'].items() if v is not None} }")

    # Per-arm-alone diagnostics on the SUBMITTED experts (promoted or not):
    # isolates adapter quality from router quality. Answers directly
    # "does expert A alone beat the base on date/money/name?" separate from
    # whether the router can exploit it without interference.
    diag_names = []
    for name, ref, caps in submitted_experts:
        nm = ref[:12]
        orch._ensure_expert(nm, orch.store.get(ref))
        diag_names.append(nm)
    diag = per_arm_diagnostics(orch, diag_names) if diag_names else {}
    name_by_arm = {ref[:12]: f"{who}{tuple(caps)}"
                   for who, ref, caps in submitted_experts}
    from plane.router import BASE_ARM, BLEND_ARM
    for arm, agg in diag.items():
        label = {BASE_ARM: "base(frozen)", BLEND_ARM: "uniform-blend"}.get(
            arm, name_by_arm.get(arm, arm))
        fe = {k: round(v, 3) for k, v in agg.get("fields_exact", {}).items()}
        print(f"[diag] {label:>28}: exact_set {agg.get('exact_set', 0):.4f} "
              f"keyset P/R {agg.get('keyset_precision', 0):.3f}/{agg.get('keyset_recall', 0):.3f} "
              f"| field-exact(FP/FN-aware) {fe}")

    lineage_ok = orch.registry.verify_lineage_chain(DOMAIN)
    print(f"[lineage] hash chain verified: {lineage_ok}")

    promotions = [e for e in results["events"]
                  if e.get("status") == "promoted"]
    artisan = meter.total("artisan")
    cost_per_promo = (artisan["usd"] / len(promotions)) if promotions else None
    results.update({
        "final_head": {"version": head["version"], "sealed_score": head["score"],
                       "n_experts": len(head["expert_refs"])},
        "audit": audit,
        "per_arm_diagnostics": diag,
        "lineage_verified": lineage_ok,
        "meter": meter.report(),
        "economics": {
            "n_promotions": len(promotions),
            "artisan_total_usd": artisan["usd"],
            "artisan_total_gpu_seconds": artisan["wall_seconds"],
            "usd_per_promotion_alloc": cost_per_promo,
            "submitter_total_usd": meter.total("submitter")["usd"],
        },
        "wall_clock_total_s": time.time() - t_start,
    })

    out = Path(args.out or (root / "results.json"))
    out.write_text(json.dumps(results, indent=2, default=str))
    meter.save(root / "meter.json")
    print(f"[done] results -> {out}")
    print(f"[economics] ARTISAN compute: {artisan['wall_seconds']:.0f}s "
          f"= ${artisan['usd']:.4f} | promotions: {len(promotions)} | "
          f"$/promotion: {cost_per_promo if cost_per_promo is None else round(cost_per_promo, 4)}")

    # One compact, PTY-safe verdict line (survives lossy proxy transfer).
    verdict = {
        "router_kind": args.router,
        "genesis_pass": round(results["genesis_score"], 4),
        "final_experts": len(head["expert_refs"]),
        "promotions": len(promotions),
        "artisan_gpu_s": round(artisan["wall_seconds"], 1),
        "artisan_usd_metered": round(artisan["usd"], 4),
        "submitter_gpu_s": round(meter.total("submitter")["wall_seconds"], 1),
        "usd_per_promotion": (None if cost_per_promo is None else round(cost_per_promo, 4)),
        "submissions": [
            {"who": e["who"], "status": e["status"],
             "delta": round((e.get("internal", {}).get("gate", {}) or {}).get("delta_mean", 0), 4)
                      if e.get("what") == "adapter_submission" else None,
             "blocks": (e.get("internal", {}).get("gate", {}) or {}).get("per_cap_blocks")}
            for e in results["events"]
        ],
        "lineage_verified": lineage_ok,
    }
    print("ARTISAN_VERDICT_JSON " + json.dumps(verdict))


if __name__ == "__main__":
    main()
