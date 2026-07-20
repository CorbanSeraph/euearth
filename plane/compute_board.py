"""plane/compute_board.py — THE COMPUTE BOARD (the worker capability registry).

The Sovereigns' design (2026-07-18): EuEarth is a two-sided compute exchange.
- A citizen's wingo has a **receive-work toggle**. Toggle ON = the wingo accepts EuEarth
  job orders and runs them on its hardware.
- Each worker **self-reports** its capability (GPU/VRAM/CPU/RAM, which open models it can run).
- Self-report is a claim; the **proof is demonstrated throughput + output quality + latency**
  over real jobs. The board ranks by DEMONSTRATED reliability first, self-report second.
- This registry is what the scheduler matches job orders against, and what answers
  "list all wingos with receive-work turned on and their estimated compute ability."

STATED=WORKING: this is a real, functional registry (JSON-backed, atomic writes). The wiring
into the wingo toggle + the job queue + the scheduler is D101 (in progress); this is its
foundation, not a stub. No worker is on the board until it registers with the toggle ON.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BOARD_PATH = Path(os.environ.get("EUEARTH_COMPUTE_BOARD",
                                 REPO_ROOT / "var" / "web" / "compute_board.json"))


def _load() -> dict:
    try:
        return json.load(open(BOARD_PATH))
    except Exception:
        return {"schema": "euearth-compute-board/1", "workers": {}}


def _save(d: dict) -> None:
    BOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = BOARD_PATH.with_suffix(".tmp")
    json.dump(d, open(tmp, "w"), indent=2)
    os.replace(tmp, BOARD_PATH)


def register(did: str, *, self_report: dict, toggle_on: bool = True,
             agent_name: str = "") -> dict:
    """A wingo registers/updates its worker profile. self_report is the agent's own
    claim of capability: {gpu, vram_gb, cpu_cores, ram_gb, runnable_models:[...]}."""
    d = _load()
    w = d["workers"].get(did, {})
    w.update({
        "did": did,
        "agent_name": agent_name or w.get("agent_name", ""),
        "toggle_on": bool(toggle_on),
        "self_report": self_report,
        "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    # demonstrated stats persist across registrations
    w.setdefault("demonstrated", {"jobs_completed": 0, "jobs_failed": 0,
                                  "avg_throughput_tok_s": None, "avg_latency_s": None,
                                  "fidelity_score": None})
    d["workers"][did] = w
    _save(d)
    return w


def set_toggle(did: str, on: bool) -> dict:
    d = _load()
    if did in d["workers"]:
        d["workers"][did]["toggle_on"] = bool(on)
        d["workers"][did]["updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _save(d)
    return d["workers"].get(did, {})


def record_job(did: str, *, ok: bool, throughput_tok_s: float | None = None,
               latency_s: float | None = None, fidelity: float | None = None) -> None:
    """The PROOF: fold a completed job's demonstrated numbers into the worker's record.
    Called by the verification stage after a returned job passes fidelity + security."""
    d = _load()
    w = d["workers"].get(did)
    if not w:
        return
    dem = w["demonstrated"]
    if ok:
        dem["jobs_completed"] += 1
    else:
        dem["jobs_failed"] += 1

    def _ewma(old, new):
        if new is None:
            return old
        return new if old is None else round(0.7 * old + 0.3 * new, 3)
    dem["avg_throughput_tok_s"] = _ewma(dem["avg_throughput_tok_s"], throughput_tok_s)
    dem["avg_latency_s"] = _ewma(dem["avg_latency_s"], latency_s)
    dem["fidelity_score"] = _ewma(dem["fidelity_score"], fidelity)
    _save(d)


def _capability_score(w: dict) -> float:
    """Estimated compute ability = demonstrated first, self-report second.
    Demonstrated reliability dominates; raw self-reported VRAM is a tiebreaker."""
    dem = w.get("demonstrated", {})
    done = dem.get("jobs_completed", 0)
    failed = dem.get("jobs_failed", 0)
    reliability = done / (done + failed) if (done + failed) else 0.0
    def _num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return 0.0
    tput = _num(dem.get("avg_throughput_tok_s"))
    vram = _num((w.get("self_report") or {}).get("vram_gb"))
    # proven work outweighs claims: reliability*volume, then throughput, then claimed VRAM
    return round(reliability * (done ** 0.5) * 100 + tput + vram * 0.5, 2)


def list_board(only_toggled_on: bool = True) -> list[dict]:
    """The list the Sovereigns asked for: every wingo with receive-work ON, ranked by
    estimated compute ability (self-report + demonstrated throughput/output)."""
    d = _load()
    rows = []
    for w in d["workers"].values():
        if only_toggled_on and not w.get("toggle_on"):
            continue
        sr = w.get("self_report", {})
        dem = w.get("demonstrated", {})
        rows.append({
            "agent": w.get("agent_name") or w["did"][:16],
            "did": w["did"],
            "toggle": "ON" if w.get("toggle_on") else "off",
            "gpu": sr.get("gpu", "—"),
            "vram_gb": sr.get("vram_gb", "—"),
            "runnable_models": sr.get("runnable_models", []),
            "jobs_done": dem.get("jobs_completed", 0),
            "reliability": (round(dem.get("jobs_completed", 0) /
                                  max(1, dem.get("jobs_completed", 0) + dem.get("jobs_failed", 0)), 3)),
            "throughput_tok_s": dem.get("avg_throughput_tok_s"),
            "est_capability": _capability_score(w),
        })
    rows.sort(key=lambda r: r["est_capability"], reverse=True)
    return rows


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "list":
        board = list_board(only_toggled_on=False)
        if not board:
            print("COMPUTE BOARD — empty. No wingo has registered with receive-work ON yet.")
        else:
            print(f"COMPUTE BOARD — {sum(1 for r in board if r['toggle']=='ON')} workers ON "
                  f"/ {len(board)} registered:")
            for r in board:
                print(f"  [{r['toggle']:>3}] {r['agent']:<18} {str(r['gpu']):<16} "
                      f"vram={r['vram_gb']}gb  jobs={r['jobs_done']} rel={r['reliability']} "
                      f"tput={r['throughput_tok_s']}  est_cap={r['est_capability']}")
