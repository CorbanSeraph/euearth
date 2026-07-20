"""artisan.keel — THE KEEL: the stable socket at the top of ARTISAN.

Per domain, ARTISAN exposes a keel: a fixed interface contract
(inputs / outputs / controls) plus a stable UI users learn once. Whole
occupants — a single model, or the ARTISAN router+expert composite —
plug into the socket and COMPETE to hold the slot. The reigning champion
stays plugged in until a challenger beats it on the existing eval
referee, at which point the occupant is swapped atomically. The engine
changes; the user's controls never do.

Reused, not rebuilt:
  * eval/          — the swap referee (held-out benchmark + report)
  * registry/      — who holds the slot (heads, CAS swap, lineage)
  * orchestrator/  — promotion margin + the inner loop that grows
                     composite challengers
  * compliance/    — occupant manifests are scanned before a challenge
"""
from .contract import ContractViolation, InterfaceContract, text_transform_contract
from .occupants import AnvilOne, ArtisanHeadOccupant, Occupant
from .referee import RefereeDecision, evaluate_occupant, referee
from .runtime import ChallengeOutcome, Keel

__all__ = [
    "ContractViolation",
    "InterfaceContract",
    "text_transform_contract",
    "Occupant",
    "AnvilOne",
    "ArtisanHeadOccupant",
    "RefereeDecision",
    "evaluate_occupant",
    "referee",
    "Keel",
    "ChallengeOutcome",
]
