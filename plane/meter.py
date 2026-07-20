"""Compute metering — the honest ledger of what ARTISAN's central jobs cost.

Every GPU-touching phase runs inside `Meter.phase(...)`. We record wall
seconds, device, peak VRAM, generated/processed tokens, and dollars
(wall_hours x the ACTUAL hourly price of the machine, passed in via
ARTISAN_GPU_USD_PER_HOUR — set from the real RunPod pod price).

Phases are tagged with who pays in production:
  payer="submitter"  — expert training (BYO-compute; ARTISAN never pays)
  payer="artisan"    — sandbox validation, router refit, sealed eval
The report sums the artisan side into $/promotion. That number is the
correction the council demanded to "storage-only cost".
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from pathlib import Path


def _device_and_vram():
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda", torch.cuda.max_memory_allocated()
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            try:
                return "mps", torch.mps.current_allocated_memory()
            except Exception:
                return "mps", 0
    except Exception:
        pass
    return "cpu", 0


def _reset_vram_peak():
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
    except Exception:
        pass


@dataclass
class Phase:
    name: str
    payer: str                 # "artisan" | "submitter"
    wall_seconds: float = 0.0
    device: str = "cpu"
    peak_vram_bytes: int = 0
    tokens: int = 0            # generated + trained tokens attributed to phase
    est_flops: float = 0.0     # rough: 2*active_params*tokens (x3 if backward)
    usd: float = 0.0
    notes: str = ""


@dataclass
class Meter:
    usd_per_hour: float = float(os.environ.get("ARTISAN_GPU_USD_PER_HOUR", "0"))
    phases: list = field(default_factory=list)

    @contextmanager
    def phase(self, name: str, payer: str, notes: str = ""):
        _reset_vram_peak()
        p = Phase(name=name, payer=payer, notes=notes)
        t0 = time.monotonic()
        try:
            yield p
        finally:
            p.wall_seconds = time.monotonic() - t0
            p.device, p.peak_vram_bytes = _device_and_vram()
            p.usd = p.wall_seconds / 3600.0 * self.usd_per_hour
            self.phases.append(p)

    def total(self, payer: str | None = None) -> dict:
        sel = [p for p in self.phases if payer is None or p.payer == payer]
        return {
            "wall_seconds": round(sum(p.wall_seconds for p in sel), 2),
            "usd": round(sum(p.usd for p in sel), 6),
            "tokens": sum(p.tokens for p in sel),
            "est_flops": sum(p.est_flops for p in sel),
        }

    def report(self) -> dict:
        return {
            "usd_per_hour": self.usd_per_hour,
            "phases": [asdict(p) for p in self.phases],
            "artisan_total": self.total("artisan"),
            "submitter_total": self.total("submitter"),
            "grand_total": self.total(None),
        }

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.report(), indent=2))
