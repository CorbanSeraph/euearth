"""Model machinery shared by the submitter side (LoRA training on the
submitter's OWN data) and the ARTISAN side (embeddings, routed batched
generation). Everything is float32 + greedy decoding for determinism.

Nothing here reads a submitter-provided config: LoRA configs are always
constructed from the ABI constants, and adapter weights are plain
tensors that already passed the sandbox.
"""
from __future__ import annotations

import io
import time

import torch
from peft import LoraConfig, get_peft_model, get_peft_model_state_dict, set_peft_model_state_dict
from safetensors.torch import load as st_load, save as st_save
from transformers import AutoModelForCausalLM, AutoTokenizer

from plane.abi import ABI_ALPHA, ABI_RANK
from plane.domain import SYSTEM_PROMPT, Item

MAX_NEW_TOKENS = 80
GEN_BATCH = 16


def pick_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def load_tokenizer(model_dir: str):
    tok = AutoTokenizer.from_pretrained(model_dir)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    tok.model_input_names = ["input_ids", "attention_mask"]  # no token_type_ids
    return tok


def load_base(model_dir: str, device: str):
    model = AutoModelForCausalLM.from_pretrained(model_dir, torch_dtype=torch.float32)
    model.to(device)
    model.eval()
    return model


def lora_config(pin: dict) -> LoraConfig:
    return LoraConfig(
        r=ABI_RANK, lora_alpha=ABI_ALPHA, lora_dropout=0.0, bias="none",
        target_modules=list(pin["target_modules"]), task_type="CAUSAL_LM",
    )


def chat_prompt(tok, item: Item) -> str:
    return tok.apply_chat_template(
        [{"role": "system", "content": SYSTEM_PROMPT},
         {"role": "user", "content": item.prompt}],
        tokenize=False, add_generation_prompt=True,
    )


def count_params(model) -> int:
    return sum(p.numel() for p in model.parameters())


# ------------------------------------------------------------- generation

@torch.no_grad()
def generate_batch(model, tok, prompts: list, device: str) -> tuple[list, int]:
    """Greedy generation. Returns (texts, generated_token_count)."""
    outs, gen_tokens = [], 0
    tok.padding_side = "left"
    for i in range(0, len(prompts), GEN_BATCH):
        chunk = prompts[i:i + GEN_BATCH]
        enc = tok(chunk, return_tensors="pt", padding=True).to(device)
        gen = model.generate(
            **enc, max_new_tokens=MAX_NEW_TOKENS, do_sample=False,
            pad_token_id=tok.pad_token_id,
        )
        new = gen[:, enc["input_ids"].shape[1]:]
        gen_tokens += int((new != tok.pad_token_id).sum())
        outs.extend(tok.batch_decode(new, skip_special_tokens=True))
    return outs, gen_tokens


# ------------------------------------------------------------- embeddings

@torch.no_grad()
def embed_prompts(model, tok, prompts: list, device: str) -> torch.Tensor:
    """Router features: mean-pooled last hidden state of the prompt under
    the FROZEN BASE (adapters disabled if `model` is a PeftModel)."""
    import contextlib
    ctx = model.disable_adapter() if hasattr(model, "disable_adapter") else contextlib.nullcontext()
    feats = []
    tok.padding_side = "left"
    with ctx:
        for i in range(0, len(prompts), GEN_BATCH):
            enc = tok(prompts[i:i + GEN_BATCH], return_tensors="pt", padding=True).to(device)
            hidden = model(**enc, output_hidden_states=True).hidden_states[-1]
            mask = enc["attention_mask"].unsqueeze(-1).to(hidden.dtype)
            pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1)
            feats.append(pooled.float().cpu())
    return torch.cat(feats, dim=0)


# ---------------------------------------------------------- LoRA training

def train_lora_expert(base_model, tok, pin: dict, items: list, device: str,
                      epochs: int = 3, batch_size: int = 8, lr: float = 2e-4,
                      seed: int = 0) -> tuple[bytes, dict]:
    """Submitter-side: fit ONE LoRA expert on the submitter's own items.
    Returns (safetensors bytes in ABI layout, training stats)."""
    import json as _json
    torch.manual_seed(seed)
    model = get_peft_model(base_model, lora_config(pin), adapter_name="default")
    model.train()

    # Build (input_ids, labels) with the prompt masked out of the loss.
    examples = []
    for it in items:
        prompt = chat_prompt(tok, it)
        answer = _json.dumps(it.target, sort_keys=True)
        p_ids = tok(prompt, add_special_tokens=False)["input_ids"]
        a_ids = tok(answer, add_special_tokens=False)["input_ids"] + [tok.eos_token_id]
        examples.append((p_ids + a_ids, [-100] * len(p_ids) + a_ids))
    examples.sort(key=lambda e: len(e[0]))

    params = [p for p in model.parameters() if p.requires_grad]
    optim = torch.optim.AdamW(params, lr=lr)
    n_trained_tokens, steps, t0 = 0, 0, time.monotonic()
    g = torch.Generator().manual_seed(seed)
    for _ in range(epochs):
        order = torch.randperm(len(examples) // batch_size + 1, generator=g)
        for bi in order:
            batch = examples[bi * batch_size:(bi + 1) * batch_size]
            if not batch:
                continue
            width = max(len(ids) for ids, _ in batch)
            input_ids = torch.full((len(batch), width), tok.pad_token_id)
            labels = torch.full((len(batch), width), -100)
            attn = torch.zeros((len(batch), width), dtype=torch.long)
            for row, (ids, labs) in enumerate(batch):
                input_ids[row, :len(ids)] = torch.tensor(ids)
                labels[row, :len(labs)] = torch.tensor(labs)
                attn[row, :len(ids)] = 1
            out = model(input_ids=input_ids.to(device),
                        attention_mask=attn.to(device),
                        labels=labels.to(device))
            out.loss.backward()
            optim.step()
            optim.zero_grad()
            n_trained_tokens += int(attn.sum())
            steps += 1

    model.eval()
    sd = get_peft_model_state_dict(model, adapter_name="default")
    sd = {k: v.detach().float().cpu().contiguous() for k, v in sd.items()}
    blob = st_save(sd)
    stats = {"steps": steps, "trained_tokens": n_trained_tokens,
             "wall_seconds": time.monotonic() - t0,
             "final_loss": float(out.loss.detach())}
    # Detach the LoRA so the caller gets its frozen base back untouched.
    model = model.unload()
    return blob, stats


# ------------------------------------------------------- adapter serving

def attach_adapters(base_model, pin: dict, adapters: dict):
    """ARTISAN-side: wrap the frozen base in a PeftModel carrying every
    promoted expert (name -> sandbox-validated safetensors bytes)."""
    peft_model = None
    for name, blob in adapters.items():
        cfg = lora_config(pin)
        if peft_model is None:
            peft_model = get_peft_model(base_model, cfg, adapter_name=name)
        else:
            peft_model.add_adapter(name, cfg)
        sd = st_load(blob)
        set_peft_model_state_dict(peft_model, sd, adapter_name=name)
    if peft_model is not None:
        peft_model.eval()
    return peft_model if peft_model is not None else base_model


def ensure_blend(peft_model, names: list, blend_name: str):
    """Uniform linear blend of same-rank experts as an extra arm."""
    if blend_name in getattr(peft_model, "peft_config", {}):
        return
    peft_model.add_weighted_adapter(
        adapters=list(names), weights=[1.0 / len(names)] * len(names),
        adapter_name=blend_name, combination_type="linear",
    )
