"""Base-model pinning by content hash (council fix #1).

The whole expert library is only meaningful against ONE exact frozen
base. We pin: HF repo + resolved revision + sha256 of every model file
(weights, config, tokenizer) + an architecture descriptor giving the
in/out dimensions of every LoRA-targetable module. The descriptor is
what lets the sandbox verify adapter tensor shapes WITHOUT loading the
adapter into a live model.

The pin is stored as a content-addressed blob; every adapter manifest
must cite `base_fingerprint` and is rejected on mismatch. Base drift
(new revision, changed tokenizer, different dtype) changes the
fingerprint and invalidates nothing silently.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

# Files that define the model identity. (Weights + config + tokenizer.)
_PIN_GLOBS = ("*.safetensors", "config.json", "generation_config.json",
              "tokenizer.json", "tokenizer_config.json", "vocab.json",
              "merges.txt", "special_tokens_map.json")

# The LoRA target set for this plane (fixed by the adapter ABI).
TARGET_MODULES = ("q_proj", "k_proj", "v_proj", "o_proj",
                  "gate_proj", "up_proj", "down_proj")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _module_dims(cfg: dict) -> dict:
    """in/out features of each targetable module, from the HF config alone.
    Supports the Llama/Qwen2 decoder family (what this plane pins)."""
    hidden = cfg["hidden_size"]
    heads = cfg["num_attention_heads"]
    kv_heads = cfg.get("num_key_value_heads", heads)
    head_dim = cfg.get("head_dim") or hidden // heads
    inter = cfg["intermediate_size"]
    return {
        "q_proj": (hidden, heads * head_dim),
        "k_proj": (hidden, kv_heads * head_dim),
        "v_proj": (hidden, kv_heads * head_dim),
        "o_proj": (heads * head_dim, hidden),
        "gate_proj": (hidden, inter),
        "up_proj": (hidden, inter),
        "down_proj": (inter, hidden),
    }


def build_base_pin(model_dir: str | Path, repo: str, revision: str) -> dict:
    """Hash a downloaded model directory into a pin spec (a plain dict;
    caller stores it as a blob and uses its digest as `base_ref`)."""
    model_dir = Path(model_dir)
    files = {}
    for pattern in _PIN_GLOBS:
        for p in sorted(model_dir.glob(pattern)):
            files[p.name] = _sha256_file(p)
    if not any(name.endswith(".safetensors") for name in files):
        raise ValueError(f"no safetensors weights found in {model_dir}")
    cfg = json.loads((model_dir / "config.json").read_text())
    fingerprint = hashlib.sha256(
        json.dumps(files, sort_keys=True).encode()
    ).hexdigest()
    return {
        "kind": "base_pin",
        "repo": repo,
        "revision": revision,
        "architecture": cfg.get("architectures", ["?"])[0],
        "dtype": cfg.get("torch_dtype", "float32"),
        "num_hidden_layers": cfg["num_hidden_layers"],
        "hidden_size": cfg["hidden_size"],
        "module_dims": {k: list(v) for k, v in _module_dims(cfg).items()},
        "target_modules": list(TARGET_MODULES),
        "files": files,
        "fingerprint": fingerprint,
    }


def expected_adapter_keys(pin: dict, rank: int) -> dict:
    """The EXACT tensor key -> shape map a conforming adapter must have.
    Keys use the peft `save_pretrained` layout (adapter-name-free)."""
    dims = pin["module_dims"]
    layers = pin["num_hidden_layers"]
    expected = {}
    for layer in range(layers):
        for mod in pin["target_modules"]:
            in_f, out_f = dims[mod]
            group = "self_attn" if mod.endswith(("q_proj", "k_proj", "v_proj", "o_proj")) else "mlp"
            stem = f"base_model.model.model.layers.{layer}.{group}.{mod}"
            expected[f"{stem}.lora_A.weight"] = (rank, in_f)
            expected[f"{stem}.lora_B.weight"] = (out_f, rank)
    return expected
