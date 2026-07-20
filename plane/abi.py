"""Adapter ABI + sandboxed validation (council fixes #2/#3).

An expert submission is TENSORS ONLY: one `.safetensors` blob. The ABI
a conforming adapter must satisfy (all enforced, all rejectable):

    base_fingerprint  == the pinned base's fingerprint
    target_modules    == the pin's fixed target set
    rank              == ABI_RANK (uniform rank keeps experts blendable)
    lora_alpha        == ABI_ALPHA
    dtype             == float32 tensors
    keys              == exactly `expected_adapter_keys(pin, rank)`
    shapes            == exactly as derived from the pinned architecture
    values            all finite (no NaN/Inf), max-abs sanity cap
    size              <= policy max_artifact_bytes

Validation happens in a THROWAWAY SUBPROCESS with an address-space
rlimit and no torch — `safetensors` + numpy only, so a hostile blob is
parsed by a memory-safe format parser, never unpickled, never executed,
and never touches the serving process or the GPU until it has passed.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ABI_RANK = 16
ABI_ALPHA = 32
ABI_DTYPE = "float32"
MAX_ABS_VALUE = 100.0          # honest LoRA weights are tiny; 100 is generous
SANDBOX_TIMEOUT_S = 120
SANDBOX_AS_LIMIT_BYTES = 4 << 30

_SANDBOX_SCRIPT = Path(__file__).parent / "abi_sandbox.py"


@dataclass
class AbiVerdict:
    ok: bool
    reason: str
    num_tensors: int = 0
    total_bytes: int = 0


def adapter_abi_manifest_fields(pin: dict) -> dict:
    """The ABI block a submitter must embed (and sign) in their manifest."""
    return {
        "base_fingerprint": pin["fingerprint"],
        "target_modules": list(pin["target_modules"]),
        "rank": ABI_RANK,
        "lora_alpha": ABI_ALPHA,
        "dtype": ABI_DTYPE,
    }


def check_manifest_abi(manifest_abi: dict, pin: dict) -> str | None:
    """Static manifest-vs-pin check (no tensor IO). None = ok."""
    want = adapter_abi_manifest_fields(pin)
    for key, expect in want.items():
        got = manifest_abi.get(key)
        if got != expect:
            return f"ABI mismatch on {key!r}: submitted {got!r} != required {expect!r}"
    return None


def sandbox_validate(adapter_bytes: bytes, pin: dict, max_bytes: int,
                     python_exe: str | None = None) -> AbiVerdict:
    """Validate adapter tensors in a resource-limited subprocess."""
    if len(adapter_bytes) > max_bytes:
        return AbiVerdict(False, f"artifact too large: {len(adapter_bytes)} > {max_bytes}")
    with tempfile.TemporaryDirectory(prefix="artisan_abi_") as td:
        blob = Path(td) / "adapter.safetensors"
        blob.write_bytes(adapter_bytes)
        spec = Path(td) / "spec.json"
        spec.write_text(json.dumps({
            "pin": pin,
            "rank": ABI_RANK,
            "max_abs": MAX_ABS_VALUE,
            "as_limit": SANDBOX_AS_LIMIT_BYTES,
        }))
        try:
            proc = subprocess.run(
                [python_exe or sys.executable, str(_SANDBOX_SCRIPT), str(blob), str(spec)],
                capture_output=True, text=True, timeout=SANDBOX_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            return AbiVerdict(False, "sandbox validation timed out")
    if proc.returncode != 0 and not proc.stdout.strip():
        return AbiVerdict(False, f"sandbox crashed: {proc.stderr.strip()[-300:]}")
    try:
        verdict = json.loads(proc.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return AbiVerdict(False, f"sandbox produced no verdict: {proc.stderr.strip()[-300:]}")
    return AbiVerdict(verdict["ok"], verdict["reason"],
                      verdict.get("num_tensors", 0), verdict.get("total_bytes", 0))
