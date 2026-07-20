"""Sandboxed adapter validator — run as a THROWAWAY SUBPROCESS only.

Usage: python abi_sandbox.py <adapter.safetensors> <spec.json>

Prints exactly one JSON verdict line on stdout:
    {"ok": bool, "reason": str, "num_tensors": int, "total_bytes": int}

Design constraints (why this file looks paranoid):
  * no torch, no pickle — safetensors' memory-safe parser + numpy only
  * RLIMIT_AS so a hostile header can't balloon the process
  * validates keys, shapes, dtype, finiteness, magnitude against the
    base pin's architecture descriptor — the blob never gets near a
    model or a GPU unless every check passes
"""
import json
import resource
import sys


def main() -> None:
    adapter_path, spec_path = sys.argv[1], sys.argv[2]
    spec = json.load(open(spec_path))
    limit = int(spec.get("as_limit", 4 << 30))
    try:
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except (ValueError, OSError):
        pass  # some platforms refuse; the parent's timeout still bounds us

    import numpy as np
    from safetensors import safe_open

    # Recompute expected keys from the pin (duplicated from basepin so this
    # script imports NOTHING from the repo — it must stay standalone).
    pin, rank = spec["pin"], int(spec["rank"])
    dims, layers = pin["module_dims"], int(pin["num_hidden_layers"])
    expected = {}
    for layer in range(layers):
        for mod in pin["target_modules"]:
            in_f, out_f = dims[mod]
            group = "self_attn" if mod in ("q_proj", "k_proj", "v_proj", "o_proj") else "mlp"
            stem = f"base_model.model.model.layers.{layer}.{group}.{mod}"
            expected[f"{stem}.lora_A.weight"] = (rank, in_f)
            expected[f"{stem}.lora_B.weight"] = (out_f, rank)

    def verdict(ok, reason, n=0, total=0):
        print(json.dumps({"ok": ok, "reason": reason,
                          "num_tensors": n, "total_bytes": total}))
        sys.exit(0)

    max_abs = float(spec.get("max_abs", 100.0))
    total_bytes = 0
    try:
        with safe_open(adapter_path, framework="numpy") as f:
            keys = list(f.keys())
            if set(keys) != set(expected):
                missing = sorted(set(expected) - set(keys))[:3]
                extra = sorted(set(keys) - set(expected))[:3]
                verdict(False, f"key set mismatch (missing {missing}, extra {extra})")
            for key in keys:
                t = f.get_tensor(key)
                if t.dtype != np.float32:
                    verdict(False, f"{key}: dtype {t.dtype} != float32")
                if tuple(t.shape) != tuple(expected[key]):
                    verdict(False, f"{key}: shape {tuple(t.shape)} != {tuple(expected[key])}")
                if not np.isfinite(t).all():
                    verdict(False, f"{key}: non-finite values (NaN/Inf)")
                if np.abs(t).max(initial=0.0) > max_abs:
                    verdict(False, f"{key}: |value| exceeds sanity cap {max_abs}")
                total_bytes += t.nbytes
    except Exception as exc:  # malformed container, truncated file, etc.
        verdict(False, f"unparseable safetensors: {type(exc).__name__}: {exc}")

    verdict(True, "conforms to ABI", len(expected), total_bytes)


if __name__ == "__main__":
    main()
