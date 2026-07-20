"""The KEEL interface contract — the definition of the stable socket.

A keel contract fixes, per domain, exactly three things:

  * input spec       — the fields a request through the socket carries
  * output spec      — the fields every response carries
  * control surface  — the controls the stable UI exposes: the thing a
                       user learns ONCE and never relearns

Occupants (whole models, or the ARTISAN router+expert composite) plug in
BEHIND this contract and compete to hold the slot. The contract is
content-addressed: the sha256 of its canonical JSON is the fingerprint an
occupant must declare conformance to, and the digest the registry pins on
EVERY head version of the slot — so "the interface did not change across
the swap" is machine-checkable from lineage, not a promise.

Interface versioning (the honest decision the keel forces): a champion
that can do MORE than the socket surfaces either holds to the common
shape (extras unexposed) or a NEW contract version is cut — a new
fingerprint, a new slot, some user relearning. Never a silent mutation.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from identity.keys import canonical_json


class ContractViolation(ValueError):
    """A request or response does not match the socket's contract."""


@dataclass(frozen=True)
class InterfaceContract:
    domain: str
    version: int
    description: str
    input_spec: dict    # field -> {"type": "string", "required": bool}
    output_spec: dict   # field -> {"type": "string", "required": bool}
    controls: tuple     # ordered control descriptors (see below)

    # Control descriptor shapes:
    #   {"name","label","kind":"select","options":[{"value","label","request":{...}}]}
    #   {"name","label","kind":"text","maps_to": <input field>, "placeholder": str}

    def to_dict(self) -> dict:
        return {
            "kind": "keel_contract",
            "domain": self.domain,
            "version": self.version,
            "description": self.description,
            "input_spec": self.input_spec,
            "output_spec": self.output_spec,
            "controls": list(self.controls),
        }

    @property
    def fingerprint(self) -> str:
        """Content address of the socket. Occupants declare it; the
        registry pins it on every head version of the slot."""
        return hashlib.sha256(canonical_json(self.to_dict())).hexdigest()

    # -- socket validation --------------------------------------------------

    def _validate(self, payload: dict, spec: dict, side: str) -> dict:
        if not isinstance(payload, dict):
            raise ContractViolation(f"{side} must be an object, got {type(payload).__name__}")
        extra = set(payload) - set(spec)
        if extra:
            raise ContractViolation(f"unknown {side} fields: {sorted(extra)}")
        out = {}
        for name, field_spec in spec.items():
            value = payload.get(name)
            if value is None:
                if field_spec.get("required", True):
                    raise ContractViolation(f"missing required {side} field: {name}")
                continue
            if field_spec.get("type", "string") == "string" and not isinstance(value, str):
                raise ContractViolation(f"{side} field {name} must be a string")
            out[name] = value
        return out

    def validate_request(self, request: dict) -> dict:
        return self._validate(request, self.input_spec, "request")

    def validate_response(self, response: dict) -> dict:
        return self._validate(response, self.output_spec, "response")

    # -- the stable UI ------------------------------------------------------

    def request_from_controls(self, values: dict) -> dict:
        """Translate stable-UI control values into a socket request.
        This mapping is part of the contract, so the UI is GENERATED from
        the socket definition — it cannot drift from it."""
        request: dict = {}
        for control in self.controls:
            value = values.get(control["name"])
            if value is None:
                raise ContractViolation(f"missing control value: {control['name']}")
            if control["kind"] == "select":
                options = {o["value"]: o for o in control["options"]}
                if value not in options:
                    raise ContractViolation(
                        f"control {control['name']}: unknown option {value!r}"
                    )
                request.update(options[value].get("request", {}))
            elif control["kind"] == "text":
                request[control["maps_to"]] = str(value)
            else:  # pragma: no cover - contract author error
                raise ContractViolation(f"unknown control kind: {control['kind']!r}")
        return request


def text_transform_contract() -> InterfaceContract:
    """The keel contract for the existing toy domain (text-transform).

    The socket accepts (instruction, text) and returns (text). The stable
    control surface is a task selector — whose options carry the domain's
    canonical instruction phrasings — plus a free text field. Occupants
    are scored by the EXISTING eval benchmark through this same socket.
    """
    return InterfaceContract(
        domain="text-transform",
        version=1,
        description="Transform a line of text according to one of the "
                    "domain's canonical tasks.",
        input_spec={
            "instruction": {"type": "string", "required": True},
            "text": {"type": "string", "required": True},
        },
        output_spec={
            "text": {"type": "string", "required": True},
        },
        controls=(
            {
                "name": "task",
                "label": "Task",
                "kind": "select",
                "options": [
                    {
                        "value": "cipher",
                        "label": "Guild cipher",
                        "request": {"instruction": "encrypt the text with the guild cipher"},
                    },
                    {
                        "value": "reverse",
                        "label": "Reverse word order",
                        "request": {"instruction": "reverse the word order of the line"},
                    },
                    {
                        "value": "vowels",
                        "label": "Capitalize vowels",
                        "request": {"instruction": "capitalize every vowel in the text"},
                    },
                    {
                        "value": "spacing",
                        "label": "Normalize spacing",
                        "request": {"instruction": "collapse repeated whitespace in the text"},
                    },
                ],
            },
            {
                "name": "text",
                "label": "Text",
                "kind": "text",
                "maps_to": "text",
                "placeholder": "raven a character throne ember",
            },
        ),
    )
