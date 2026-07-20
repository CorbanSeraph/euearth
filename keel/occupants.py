"""Occupant adapters — what plugs INTO the keel socket.

An occupant is a whole engine competing to hold a domain's slot. The
adapter is deliberately thin: `infer(request) -> response` in the
socket's stable shape, plus a self-describing manifest for the registry
and the compliance scanner. The keel does not care what is behind the
adapter — a hand-rolled monolith and the ARTISAN router+expert composite
are interchangeable occupants of the SAME socket.

Two concrete adapters live here (the demo cast):

  * AnvilOne            — champion A: a single monolithic model.
  * ArtisanHeadOccupant — challenger B: a canonical ARTISAN head
    (router + expert library) wrapped as ONE contender. It reuses
    eval.harness.assemble_candidate / run_candidate verbatim — the
    composite grown by the inner contribution loop competes for the
    user-facing slot as a single occupant.
"""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod

from eval.harness import assemble_candidate, run_candidate
from store import BlobStore

from .contract import InterfaceContract


class Occupant(ABC):
    """Adapter every slot occupant implements. Stable calls in, engine-
    specific behavior behind."""

    name: str = "occupant"
    kind: str = "occupant"

    def __init__(self, contract: InterfaceContract):
        self.contract = contract

    @property
    def contract_fingerprint(self) -> str:
        """The socket this occupant declares conformance to."""
        return self.contract.fingerprint

    @abstractmethod
    def infer(self, request: dict) -> dict:
        """Serve one validated socket request; return a socket response."""

    @abstractmethod
    def engine(self) -> dict:
        """Engine-specific internals, recorded in the occupant descriptor."""

    def dataset_manifest(self) -> dict:
        """Provenance declaration, scanned by compliance/ on challenge."""
        fingerprint = hashlib.sha256(f"{self.kind}:{self.name}".encode()).hexdigest()
        return {
            "sources": [
                {"name": f"{self.name}-own-corpus", "license": "CC0-1.0",
                 "sha256": fingerprint}
            ]
        }

    def artifact_refs(self) -> list[str]:
        """Internal content-addressed artifacts (recorded on the head row)."""
        return []

    def describe(self) -> dict:
        """The occupant descriptor: stored content-addressed in the blob
        store; its digest is 'who holds the slot' in the registry."""
        return {
            "kind": self.kind,
            "name": self.name,
            "contract": self.contract_fingerprint,
            "engine": self.engine(),
            "dataset_manifest": self.dataset_manifest(),
        }


class AnvilOne(Occupant):
    """Champion A — a MONOLITHIC single model.

    Anvil-1 has two skills baked into its own inline implementation (its
    'weights'): the guild cipher and whitespace normalization. Word order
    and vowel work are beyond it — it echoes the input. Held-out score:
    0.5. A perfectly honest early champion, waiting to be dethroned.
    """

    name = "Anvil-1"
    kind = "single-model"

    _SHIFT = 7  # the guild cipher, learned into the monolith

    def infer(self, request: dict) -> dict:
        instruction = request["instruction"].lower()
        text = request["text"]
        if "cipher" in instruction:
            out = "".join(self._shift_char(c) for c in text)
        elif "whitespace" in instruction or "spacing" in instruction:
            out = " ".join(text.split())
        else:
            out = text  # not in the monolith's repertoire
        return {"text": out}

    @classmethod
    def _shift_char(cls, ch: str) -> str:
        # Anvil-1's own cipher path — intentionally NOT eval.transforms:
        # a different engine behind the same socket.
        if "a" <= ch <= "z":
            return chr((ord(ch) - 97 + cls._SHIFT) % 26 + 97)
        if "A" <= ch <= "Z":
            return chr((ord(ch) - 65 + cls._SHIFT) % 26 + 65)
        return ch

    def engine(self) -> dict:
        return {
            "architecture": "hand-rolled monolith",
            "skills": ["caesar(shift=7)", "dedup_spaces"],
            "weights": "inline",
        }


class ArtisanHeadOccupant(Occupant):
    """Challenger B — the ARTISAN router+expert composite as ONE occupant.

    Wraps a canonical head from the registry (base + router + expert
    library, all content-addressed) behind the stable socket. Inference
    is eval.harness.run_candidate — the exact code the inner loop already
    trusts. Router + experts = one contender for the slot.
    """

    kind = "artisan-composite"

    def __init__(
        self,
        contract: InterfaceContract,
        store: BlobStore,
        head: dict,
        source_domain: str,
        name: str | None = None,
    ):
        super().__init__(contract)
        self.name = name or f"ARTISAN head v{head['version']} ({source_domain})"
        self._head = head
        self._source_domain = source_domain
        self._candidate = assemble_candidate(
            store, head["base_ref"], head["router_ref"], head["expert_refs"]
        )

    def infer(self, request: dict) -> dict:
        out = run_candidate(self._candidate, request["instruction"], request["text"])
        return {"text": request["text"] if out is None else out}

    def engine(self) -> dict:
        return {
            "architecture": "router + expert library",
            "source_domain": self._source_domain,
            "head_version": self._head["version"],
            "base_ref": self._head["base_ref"],
            "router_ref": self._head["router_ref"],
            "n_experts": len(self._head["expert_refs"]),
        }

    def dataset_manifest(self) -> dict:
        return {
            "sources": [
                {
                    "name": f"{self._source_domain}-canonical-head-v{self._head['version']}",
                    "license": "CC0-1.0",
                    "sha256": self._head["router_ref"],
                }
            ]
        }

    def artifact_refs(self) -> list[str]:
        return list(self._head["expert_refs"])
