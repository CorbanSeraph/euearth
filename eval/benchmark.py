"""Deterministic benchmark for the toy domain `text-transform-v0`.

A deliberately LOW-IP domain (per the council: prove the machine on
something that isn't music). Each example is (instruction, input,
expected). The domain has four capability families; the HEAD starts as
the identity base and only improves as agents contribute experts.

Two data sources, same task distribution, DIFFERENT seeds:
  * held_out_benchmark()  — ARTISAN's private gate. Only the harness
    generates it. Production analogue: versioned hidden test sets,
    rotated over time.
  * training_sample(seed) — the public sampler agents use to train on
    their OWN compute. Never the held-out seed.

Everything is seeded and pure: the same candidate always scores the same.
"""
from __future__ import annotations

import hashlib
import random

from .transforms import apply_transform

DOMAIN = "text-transform-v0"
BENCHMARK_VERSION = 1

# Held-out seed derived from a fixed tag; agents get a different sampler.
HELD_OUT_SEED = int.from_bytes(
    hashlib.sha256(f"artisan/{DOMAIN}/held-out/v{BENCHMARK_VERSION}".encode()).digest()[:8],
    "big",
)

_WORDS = (
    "ember forge anvil raven a character oak throne crown scepter quill "
    "lantern harbor granite echo cinder marble sable onyx iron reed "
    "willow falcon summit hollow amber slate garnet birch fable stone"
).split()

# Instruction phrasings per family. The router matches keywords against
# these, so routing is learnable but not given away by the family name.
_TEMPLATES = {
    "caesar": [
        "encrypt the text with the guild cipher",
        "apply the workshop cipher to this line",
    ],
    "reverse_words": [
        "reverse the word order of the line",
        "flip the words back to front",
    ],
    "vowel_upper": [
        "capitalize every vowel in the text",
        "uppercase the vowels of this line",
    ],
    "dedup_spaces": [
        "collapse repeated whitespace in the text",
        "normalize the spacing of this line",
    ],
}

# The domain's canonical hidden parameters. Agents must FIT these from
# sampled data (their own compute); they are not published in any spec.
_TARGETS = {
    "caesar": {"shift": 7},
    "reverse_words": {},
    "vowel_upper": {},
    "dedup_spaces": {},
}

FAMILIES = tuple(sorted(_TEMPLATES))


def _make_input(rng: random.Random, family: str) -> str:
    words = [rng.choice(_WORDS) for _ in range(rng.randint(3, 8))]
    text = " ".join(words)
    if family == "dedup_spaces":
        # inject messy whitespace so identity != expected
        parts = text.split(" ")
        text = ""
        for i, w in enumerate(parts):
            text += w
            if i < len(parts) - 1:
                text += " " * rng.randint(2, 4)
    return text


def _generate(seed: int, n_per_family: int) -> list[dict]:
    rng = random.Random(seed)
    examples = []
    for family in FAMILIES:
        for _ in range(n_per_family):
            text = _make_input(rng, family)
            instruction = rng.choice(_TEMPLATES[family])
            expected = apply_transform({"family": family, "params": _TARGETS[family]}, text)
            examples.append(
                {
                    "family": family,
                    "instruction": instruction,
                    "input": text,
                    "expected": expected,
                }
            )
    return examples


def held_out_benchmark(n_per_family: int = 60) -> list[dict]:
    """ARTISAN's private gate set. Generated only inside the harness."""
    return _generate(HELD_OUT_SEED, n_per_family)


def training_sample(agent_seed: int, n_per_family: int = 40) -> list[dict]:
    """Public sampler for agents: same distribution, never the gate seed."""
    if agent_seed == HELD_OUT_SEED:
        raise ValueError("training seed may not equal the held-out seed")
    return _generate(agent_seed, n_per_family)


def benchmark_fingerprint(examples: list[dict]) -> str:
    """Stable id of the exact benchmark evaluated, recorded in eval reports."""
    h = hashlib.sha256()
    for ex in examples:
        h.update(ex["instruction"].encode())
        h.update(b"\x00")
        h.update(ex["input"].encode())
        h.update(b"\x00")
        h.update(ex["expected"].encode())
        h.update(b"\x01")
    return h.hexdigest()
