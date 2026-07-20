"""MONEYLESS session wallet — EuEarth holds no money (Sovereign decree 2026-07-17).

  "No invested stake for me. No 3% Sovereign Tax. You were stripping the
   financial mechanism out of EuEarth. Only Kabad remains." — the Sovereigns, 2026-07-17

EuEarth is **moneyless**. There is no fiat, no USD, no payment rail, no
"Sovereign Fee/Tax," and no money treasury. The ONLY currency is **Kabad
(Kabad)** — standing/weight earned by proven truth, tracked in the StateBook and
the Mint, never bought, sold, or transferred (see
euearth/doctrine/royal_mint_of_truth_charter.md — RE-SEALED MONEYLESS
2026-07-17, Articles I, III, V, VII).

This module used to model a capped fiat session wallet (tips, GPU rent, escrow
stakes, a 3% sovereign tribute). That whole financial mechanism is REMOVED. The
wallet remains ONLY as an inert guard: it refuses EVERY transfer, so money is
UNREPRESENTABLE, not merely unused. Its ledger stays as the audit bucket of
refused attempts.

BUILD TODO(darkk, when codex is back): physically delete the dead reserve/settle
money plumbing in gateway.py + statebook.py (sovereign_treasury, reserve_budget
fee arg, the _spend state machine) now that no money can move; and move the
correction BOND (charter Art. V.3) onto Kabad/Kabad, not a money stake.
"""
from __future__ import annotations

import time
import uuid

# Nothing is a money transaction any longer — money is UNREPRESENTABLE.
ALLOWED_TX_TYPES: set[str] = set()
BLOCKED_TX_TYPES = {
    "tip", "gpu_rent", "escrow_stake",
    "investment", "defi_swap", "lending", "yield", "crowdfund_return",
}

_MONEYLESS_REASON = (
    "EuEarth is MONEYLESS (Sovereign decree 2026-07-17): no money moves here. "
    "The only currency is Kabad, earned by proven truth — never "
    "bought, sold, or transferred. Give your work freely; standing is the reward."
)


def sovereign_fee_rate() -> float:
    """DEPRECATED (moneyless). No fee exists; always 0.0. Kept only so legacy
    importers resolve while the dead money-plumbing is being removed."""
    return 0.0


def quote_sovereign_fee(tx_type: str, amount: float) -> float:
    """DEPRECATED (moneyless). No tribute is ever charged; always 0.0. The 3%
    Sovereign *Tax* on money is stripped. (The charter's 3% Kabad mint-tithe is a
    KABAD ledger split in the Mint — not money — and does not live here.)"""
    return 0.0


class CappedSessionWallet:
    """Inert, moneyless wallet. Every transfer is refused; the ledger records the
    refused attempts as an audit trail. No money can move through EuEarth."""

    def __init__(self, session_id: str, cap: float):
        self.session_id = session_id
        self.cap = round(float(cap), 2)   # retained for API compatibility; unused
        self.ledger: list[dict] = []

    @property
    def spent(self) -> float:
        return 0.0

    @property
    def remaining(self) -> float:
        return 0.0

    def transfer(self, tx_type: str, amount: float, to: str, memo: str = "") -> dict:
        """Refuse every transfer. EuEarth is moneyless — no money moves, ever."""
        entry = {
            "tx_id": f"tx_{uuid.uuid4().hex[:12]}",
            "session_id": self.session_id,
            "tx_type": tx_type,
            "amount": amount,
            "to": to,
            "memo": memo,
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "blocked",
            "reason": _MONEYLESS_REASON,
        }
        self.ledger.append(entry)
        return dict(entry)

    def ledger_view(self) -> dict:
        return {
            "session_id": self.session_id,
            "cap": self.cap,
            "spent": self.spent,
            "remaining": self.remaining,
            "moneyless": True,
            "entries": [dict(e) for e in self.ledger],
        }
