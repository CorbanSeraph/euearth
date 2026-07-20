"""Expert adapters for the toy domain are PARAMETER SETS, not code.

An "expert" is a JSON blob like {"family": "caesar", "params": {"shift": 7}}.
This module is the fixed, ARTISAN-controlled interpreter for those param
sets. Submissions never ship executable code, so the eval harness never
executes untrusted code — the toy-scale analogue of "a LoRA is tensors,
not a program", and the security stance production keeps.
"""
from __future__ import annotations

import re


class UnknownFamilyError(ValueError):
    pass


def _identity(text: str) -> str:
    return text


def _caesar(text: str, shift: int = 0) -> str:
    shift = int(shift) % 26
    out = []
    for ch in text:
        if "a" <= ch <= "z":
            out.append(chr((ord(ch) - 97 + shift) % 26 + 97))
        elif "A" <= ch <= "Z":
            out.append(chr((ord(ch) - 65 + shift) % 26 + 65))
        else:
            out.append(ch)
    return "".join(out)


def _reverse_words(text: str) -> str:
    return " ".join(text.split()[::-1])


def _vowel_upper(text: str) -> str:
    return "".join(c.upper() if c in "aeiou" else c for c in text)


def _dedup_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def apply_transform(spec: dict, text: str) -> str:
    """Interpret an expert/base param blob against an input string."""
    family = spec.get("family")
    params = spec.get("params") or {}
    if family == "identity":
        return _identity(text)
    if family == "caesar":
        return _caesar(text, shift=params.get("shift", 0))
    if family == "reverse_words":
        return _reverse_words(text)
    if family == "vowel_upper":
        return _vowel_upper(text)
    if family == "dedup_spaces":
        return _dedup_spaces(text)
    raise UnknownFamilyError(f"unknown transform family: {family!r}")
