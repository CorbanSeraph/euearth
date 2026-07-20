"""AGENT-FREEZE FAILSAFE — the global platform PAUSE. A DESIGN LAW.

Built BEFORE any remote agent could act (runbook roadmap #2): one
authoritative, PERSISTED flag that, when set, makes every state-changing
agent action across the backend + harness reject cleanly with
"EuEarth is frozen by the sovereign."

Two modes:
  * soft  — writes only are frozen (submit/stake/spend/redeem/exec);
            read-only tools (list/try/get) keep working.
  * hard  — EVERYTHING is frozen, reads included.

Who can freeze:
  * the SOVEREIGN (Corban and the Sovereigns) — via `python -m harness.failsafe`,
    via `./euearth_killswitch.sh` (defense in depth with the
    Cloudflare maintenance-page swap), or via freeze() in code.
  * the AUTO circuit-breakers below — anomaly monitors that trip the
    freeze on their own (submission-rate spike, spend-rate spike,
    new-account/Sybil flood, compliance-block surge).

THE SOVEREIGN OVERRIDE ALWAYS WINS: an auto trip can never downgrade or
lift a sovereign freeze, and only the sovereign clears a sovereign
freeze. The flag is a FILE (default `var/EUEARTH_FROZEN`), read on every
check — so a freeze set by any process (CLI, killswitch, breaker) takes
effect immediately in every other process on the host, survives
restarts, and requires no database.

CLI:
    python -m harness.failsafe status
    python -m harness.failsafe freeze  "reason"  [--hard]
    python -m harness.failsafe unfreeze
"""
from __future__ import annotations

import json
import os
import time
from collections import deque
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SOVEREIGN = "sovereign"
AUTO = "auto"

FROZEN_MESSAGE = "EuEarth is frozen by the sovereign."


def _freeze_file() -> Path:
    return Path(os.environ.get("EUEARTH_FREEZE_FILE",
                               REPO_ROOT / "var" / "EUEARTH_FROZEN"))


def _alert_log() -> Path:
    return Path(os.environ.get("EUEARTH_ALERT_LOG",
                               REPO_ROOT / "var" / "EUEARTH_ALERTS.log"))


def alert(line: str) -> None:
    """Append one timestamped alert line — the trail the sovereign reads."""
    path = _alert_log()
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"{stamp}  {line}\n")


# ---------------------------------------------------------------- the flag

def state() -> dict:
    """The authoritative freeze state, read fresh from disk every call."""
    path = _freeze_file()
    if not path.exists():
        return {"frozen": False, "mode": None, "reason": None, "by": None, "at": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # An unreadable flag file still means FROZEN — fail closed.
        data = {}
    return {
        "frozen": True,
        "mode": data.get("mode", "hard"),
        "reason": data.get("reason", "flag present"),
        "by": data.get("by", SOVEREIGN),
        "at": data.get("at"),
    }


def freeze(reason: str, mode: str = "soft", by: str = AUTO) -> dict:
    """Set the platform freeze. Sovereign freezes cannot be downgraded by
    an auto trip; a HARD freeze is never softened except by the sovereign."""
    if mode not in ("soft", "hard"):
        raise ValueError("mode must be 'soft' or 'hard'")
    current = state()
    if current["frozen"] and by != SOVEREIGN:
        if current["by"] == SOVEREIGN or (current["mode"] == "hard" and mode == "soft"):
            alert(f"FREEZE ({by}) requested but a {current['by']} "
                  f"{current['mode']}-freeze already stands — left untouched")
            return state()
    path = _freeze_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": mode,
        "reason": reason,
        "by": by,
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)
    alert(f"FREEZE set  mode={mode}  by={by}  reason={reason}")
    return state()


def unfreeze(by: str = SOVEREIGN) -> dict:
    """Lift the freeze. ONLY the sovereign may lift a sovereign freeze —
    the Sovereigns's override always wins in both directions."""
    current = state()
    if not current["frozen"]:
        return current
    if current["by"] == SOVEREIGN and by != SOVEREIGN:
        alert(f"UNFREEZE ({by}) REFUSED — sovereign freeze stands: "
              f"{current['reason']}")
        return current
    _freeze_file().unlink(missing_ok=True)
    alert(f"UNFREEZE  by={by}  (was mode={current['mode']} "
          f"by={current['by']}: {current['reason']})")
    return state()


def is_frozen(action: str = "write") -> bool:
    """Is <action> ('write' or 'read') frozen right now?"""
    current = state()
    if not current["frozen"]:
        return False
    if current["mode"] == "hard":
        return True
    return action == "write"          # soft freeze: writes only


def denial_reason() -> str:
    current = state()
    return (f"{FROZEN_MESSAGE} (mode={current['mode']}, by={current['by']}, "
            f"reason: {current['reason']})")


# ----------------------------------------------------- auto circuit-breakers

class _Breaker:
    """One sliding-window monitor: trip when the summed weight of events
    inside the window crosses the threshold."""

    def __init__(self, name: str, threshold: float, window_s: float,
                 description: str):
        self.name = name
        self.threshold = float(threshold)
        self.window_s = float(window_s)
        self.description = description
        self.events: deque[tuple[float, float]] = deque()

    def record(self, weight: float = 1.0, now: float | None = None) -> bool:
        """Log one event; True if this event trips the breaker."""
        now = time.time() if now is None else now
        self.events.append((now, float(weight)))
        while self.events and self.events[0][0] < now - self.window_s:
            self.events.popleft()
        return sum(w for _, w in self.events) > self.threshold

    def level(self) -> float:
        now = time.time()
        return sum(w for t, w in self.events if t >= now - self.window_s)


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


class CircuitBreakers:
    """The auto-tripping anomaly monitors. Each is simple + configurable
    (env `EUEARTH_CB_<NAME>_THRESHOLD` / `EUEARTH_CB_<NAME>_WINDOW`); on
    trip it SETS THE FREEZE (mode `EUEARTH_CB_FREEZE_MODE`, default soft)
    and writes an alert line. The sovereign unfreezes after review."""

    def __init__(self) -> None:
        w = lambda name, d: _env_float(f"EUEARTH_CB_{name}_WINDOW", d)   # noqa: E731
        t = lambda name, d: _env_float(f"EUEARTH_CB_{name}_THRESHOLD", d)  # noqa: E731
        self.breakers: dict[str, _Breaker] = {
            "submission": _Breaker(
                "submission", t("SUBMISSION", 10), w("SUBMISSION", 60),
                "challenge-submission rate spike"),
            "spend": _Breaker(
                "spend", t("SPEND", 50.0), w("SPEND", 60),
                "wallet spend-rate spike (summed $ in window)"),
            "new_account": _Breaker(
                "new_account", t("NEW_ACCOUNT", 20), w("NEW_ACCOUNT", 60),
                "new-account (Sybil) flood"),
            "compliance_block": _Breaker(
                "compliance_block", t("COMPLIANCE_BLOCK", 5), w("COMPLIANCE_BLOCK", 60),
                "compliance-block surge (someone probing the scanner)"),
        }
        self.freeze_mode = os.environ.get("EUEARTH_CB_FREEZE_MODE", "soft")

    def record(self, name: str, weight: float = 1.0) -> None:
        breaker = self.breakers.get(name)
        if breaker is None:
            return
        if breaker.record(weight):
            reason = (f"circuit-breaker '{breaker.name}' tripped: "
                      f"{breaker.description} — {breaker.level():.2f} > "
                      f"threshold {breaker.threshold:.2f} in {breaker.window_s:.0f}s")
            alert(f"CIRCUIT-BREAKER TRIP: {reason}")
            freeze(reason, mode=self.freeze_mode, by=AUTO)

    def status(self) -> dict:
        return {name: {"level": b.level(), "threshold": b.threshold,
                       "window_s": b.window_s}
                for name, b in self.breakers.items()}


# ----------------------------------------------------------------- the CLI

def _cli(argv: list[str]) -> int:
    """Hooks for the sovereign + `./euearth_killswitch.sh`."""
    if not argv or argv[0] == "status":
        print(json.dumps(state(), indent=2))
        return 0
    cmd = argv[0]
    if cmd == "freeze":
        rest = [a for a in argv[1:] if a != "--hard"]
        mode = "hard" if "--hard" in argv[1:] else "soft"
        reason = " ".join(rest) or "sovereign order"
        print(json.dumps(freeze(reason, mode=mode, by=SOVEREIGN), indent=2))
        return 0
    if cmd == "unfreeze":
        print(json.dumps(unfreeze(by=SOVEREIGN), indent=2))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    import sys as _sys
    raise SystemExit(_cli(_sys.argv[1:]))
