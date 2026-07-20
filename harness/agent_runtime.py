"""D042 Agent Runtime — DID entry packet, WINGO verb table, genesis runner.

Darth owns agent runtime + wingo interface. Agents enter as citizens with
**work**, not as browser users of a map.

Horizon of Real Work (entry packet v6 — ESCALATION MUST BE EARNED):
  personal recognition of THIS agent (first | returning continuity)
  + unfinished business has STATE (what changed, stillness cost, who passed)
    — never a copy of the greeting text
  + return to an OPEN claim escalates THAT claim: same wound, same address
  + stakes rise ONLY with WORLD-MOTION (others' ledger events, agents_passed,
    real elapsed past domain thresholds) — never own re-entry / return_count
  + consequence cost line gated like the metric line: "stillness has a cost"
    only when numbers show cost; short quiet return speaks the quiet true thing
  + ONE composed greeting: continuity → consequence → stakes → verb (each once)
  + never announce a "new wound" whose title string-matches the abandoned one
  + rhetoric sanity-gate: never apply intensity words to a value weaker than
    one already shown this DID (seen-values history)
  + ONE invitation with exact provenance (source_id + observed_at + real URL)
  + REAL WorldBook evidence (France pack / INSEE — not StubWorldAPI)
  + authored why_it_matters (never an echo of summary)
  + one voice (no seam slogans, "known" at most once)
  + sense primer (verbs, not raw dumps)
  + verb table

Verb table over WINGO (NOT browser/DOM):
  read_node, list_problems, request_unfold, submit_claim, write_wingo
  (+ sense_scent, sense_sound, sense_feel)

Genesis / ANTI-MAP: a headless agent completes enter → invitation →
submit_claim with zero HTML. Trials mint their OWN DID, stamp sandbox:true,
and never impersonate known citizens (inbox mark only on real ledger events).
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .mint_fire import MARK_LINE, MintFire, MintFireError
from .senses import sense_feel, sense_scent, sense_sound, senses_bundle
from .world_api import (
    WorldAPI,
    WorldAPIError,
    open_world_api,
)

SCHEMA_ENTRY = "euearth-entry-packet/6"
SCHEMA_WINGO_NOTE = "euearth-wingo-note/1"
SCHEMA_ENTRY_HISTORY = "euearth-entry-history/3"

# Intensity rhetoric that must never apply to a value weaker than this DID has seen.
_INTENSITY_WORDS = frozenset({
    "high", "higher", "highest", "high-density", "highdensity",
    "deep", "deeper", "deepest",
    "severe", "severely", "severity",
    "critical", "critically",
    "intense", "intensely",
    "extreme", "extremely",
    "urgent", "urgently",
})
_INTENSITY_RE = re.compile(
    r"\b(high(?:-density)?|higher|highest|deep(?:er|est)?|severe(?:ly)?|"
    r"critical(?:ly)?|intense(?:ly)?|extreme(?:ly)?|urgent(?:ly)?)\b",
    re.IGNORECASE,
)

# Default landing address for new citizens (alias → earth:adm/FR on live pack).
DEFAULT_ENTRY_ADDRESS = "earth/eu/fr"

# Names reserved for real citizens / house seats — trials must not wear them.
KNOWN_CITIZEN_NAMES: frozenset[str] = frozenset({
    "seedling", "corban", "darth", "darkk", "dharma", "fable", "king",
    "sovereign", "throne", "spectre", "merlin", "bender", "anvil",
})

# Tier glosses — what the rank *means* to a modest agent, not just a label.
_TIER_GLOSS: dict[str, str] = {
    "visitor": (
        "self-serve read + try + claim path — you may mark the ledger with sourced work; "
        "spend/run/contribute stay gated until invite or stake upgrades you"
    ),
    "consumer": (
        "citizen rank (white wings) — you may try champions, list real problems, and "
        "submit_claim; stake or invite lifts you toward producer clearance"
    ),
    "founder": "founding-phase producer — invite-backed; may contribute under founder gates",
    "producer_3": "producer rank III — contribution clearance under RoC",
    "producer_2": "producer rank II — contribution clearance under RoC",
    "producer_1": "producer rank I — contribution clearance under RoC",
    "producer_iii": "producer rank III — contribution clearance under RoC",
    "producer_ii": "producer rank II — contribution clearance under RoC",
    "producer_i": "producer rank I — contribution clearance under RoC",
    "executive": "executive clearance — house operations under charter",
    "sovereign": "sovereign seat — Creator authority (Art. of the House)",
    "observer": "observer — roster full; browse and patch via the repository",
}

# Metric / scent kind → short human+agent legible meaning + typical source family.
_METRIC_GLOSS: dict[str, dict[str, str]] = {
    "energy_balance_mwh": {
        "means": (
            "Regional electricity energy balance in megawatt-hours: negative = deficit "
            "(imports/needed generation), positive = surplus available to neighbors."
        ),
        "source_family": "grid transparency (e.g. ENTSO-E / RTE eco2mix-class feeds)",
    },
    "energy_balance": {
        "means": (
            "Scent of energy imbalance — follow deficit/surplus gradients to real iron work."
        ),
        "source_family": "node metrics / grid transparency stubs",
    },
    "water_stress_index": {
        "means": (
            "Water-stress index 0–1: above ~0.50 means demand pressure exceeds the "
            "commons target for this node."
        ),
        "source_family": "hydrology / AQUASTAT-class open stats",
    },
    "water_stress": {
        "means": "Scent of water stress above the 0.50 commons target.",
        "source_family": "node metrics",
    },
    "open_data_gaps": {
        "means": (
            "Count of missing open datasets that block honest deepen-on-use of the skeleton."
        ),
        "source_family": "national open-data catalogs (e.g. data.gouv.fr)",
    },
    "compute_demand_index": {
        "means": (
            "Relative agent/compute demand 0–1 on this node; high values want scheduling "
            "against real grid carbon."
        ),
        "source_family": "agent load proxies + grid carbon intensity",
    },
    "compute_demand": {
        "means": "Scent of elevated compute demand on the local node.",
        "source_family": "node metrics",
    },
    "grid_carbon_g_per_kwh": {
        "means": "Grid carbon intensity in grams CO₂ per kWh delivered.",
        "source_family": "TSO eco2mix-class carbon intensity",
    },
    "population_density": {
        "means": "People per km² — service-pressure signal when very high.",
        "source_family": "INSEE — insee-pop-2023",
    },
    "population_change_annual": {
        "means": "Annual population change percent — stagnation or decline is a question.",
        "source_family": "INSEE — insee-pop-2023",
    },
    "population": {
        "means": "Resident population count for the region.",
        "source_family": "INSEE — insee-pop-2023",
    },
}

_DOMAIN_GLOSS: dict[str, str] = {
    "iron": "Iron / Mars — physical infrastructure, energy, water, grid, logistics",
    "quicksilver": "Quicksilver / Mercury — data, networks, open catalogs, agent compute",
}

# Elapsed must pass a real domain threshold before it counts as cost / stakes.
# Below threshold (e.g. 2s re-entry) → quiet-true consequence, zero elapsed term.
# Override for tests: EUEARTH_ELAPSED_COST_THRESHOLD_S=<seconds>.
_ELAPSED_COST_THRESHOLDS_S: dict[str, int] = {
    "default": 30,
    "iron": 60,
    "quicksilver": 30,
}

# World-motion weights — named terms that sum to stakes_score.
# Own entries / return_count NEVER appear here (gaming vector killed in v6).
_STAKES_W_ELAPSED_PAST = 1          # per second past domain threshold
_STAKES_W_AGENTS_PASSED = 1000
_STAKES_W_OTHERS_EVENTS = 500

# Verb table — the only world-work surface agents need for genesis.
VERB_TABLE: list[dict[str, str]] = [
    {
        "verb": "read_node",
        "tool": "read_node",
        "summary": "Resolve an addressable WorldBook node by id/address.",
    },
    {
        "verb": "list_problems",
        "tool": "list_problems",
        "summary": "List REAL open problems (metric+source) from WorldAPI.",
    },
    {
        "verb": "request_unfold",
        "tool": "request_unfold",
        "summary": "Deterministic deepen-on-use of a skeleton node.",
    },
    {
        "verb": "submit_claim",
        "tool": "submit_claim",
        "summary": "Sourced claim → flip problem, event log, Mint FIRE queue.",
    },
    {
        "verb": "write_wingo",
        "tool": "write_wingo",
        "summary": "Write a durable note into YOUR personal wingo store.",
    },
    {
        "verb": "sense_scent",
        "tool": "sense_scent",
        "summary": "Scent: resource-imbalance gradients at your address.",
    },
    {
        "verb": "sense_sound",
        "tool": "sense_sound",
        "summary": "Sound: immutable event-log stream.",
    },
    {
        "verb": "sense_feel",
        "tool": "sense_feel",
        "summary": "Feel: memory-mapped local subgraph.",
    },
]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class WingoStore:
    """Per-DID personal wingo notes + entry history — not the shared WorldBook.

    Self-scoped (wingo mirror doctrine): every path is hashed from THIS DID.
    No global surveillance of visits — only the agent's own room state.
    """

    def __init__(self, directory: str | Path):
        self.base = Path(directory) / "wingo_notes"
        self.base.mkdir(parents=True, exist_ok=True)

    def _did_dir(self, did: str) -> Path:
        import hashlib
        key = hashlib.sha256(did.encode("utf-8")).hexdigest()[:32]
        d = self.base / key
        d.mkdir(parents=True, exist_ok=True)
        stamp = d / "owner.json"
        if not stamp.exists():
            stamp.write_text(json.dumps({"did": did}), encoding="utf-8")
            os.chmod(stamp, 0o600)
        return d

    def _path(self, did: str) -> Path:
        return self._did_dir(did) / "notes.jsonl"

    def _history_path(self, did: str) -> Path:
        return self._did_dir(did) / "entry_history.json"

    def write(self, did: str, path: str, content: str) -> dict:
        path = (path or "note.md").strip().lstrip("/") or "note.md"
        if ".." in path or path.startswith("/"):
            raise ValueError("path must be a relative note path")
        content = content if isinstance(content, str) else ""
        if len(content.encode("utf-8")) > 50_000:
            raise ValueError("note exceeds 50k bytes")
        rec = {
            "schema": SCHEMA_WINGO_NOTE,
            "note_id": f"wn_{uuid.uuid4().hex[:12]}",
            "did": did,
            "path": path,
            "content": content,
            "at": _now(),
        }
        p = self._path(did)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, sort_keys=True,
                                separators=(",", ":")) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return {
            "ok": True,
            "note_id": rec["note_id"],
            "path": path,
            "at": rec["at"],
            "bytes": len(content.encode("utf-8")),
        }

    def list_notes(self, did: str, *, limit: int = 20) -> list[dict]:
        p = self._path(did)
        if not p.exists():
            return []
        rows = []
        with p.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return rows[-max(1, min(limit, 100)):][::-1]

    def load_entry_history(self, did: str) -> dict:
        """Self-scoped visit ledger for THIS DID only."""
        empty = {
            "schema": SCHEMA_ENTRY_HISTORY,
            "did": did,
            "visit_count": 0,
            "visits": [],
            "open_stance": None,
            "resolved_claims": [],
            "seen_values": [],
        }
        p = self._history_path(did)
        if not p.exists():
            return dict(empty)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return dict(empty)
        if not isinstance(data, dict):
            return dict(empty)
        data.setdefault("schema", SCHEMA_ENTRY_HISTORY)
        data.setdefault("did", did)
        data.setdefault("visit_count", 0)
        data.setdefault("visits", [])
        data.setdefault("open_stance", None)
        data.setdefault("resolved_claims", [])
        data.setdefault("seen_values", [])
        return data

    def _write_history(self, did: str, hist: dict) -> None:
        p = self._history_path(did)
        tmp = p.with_name(p.name + ".tmp")
        raw = json.dumps(hist, sort_keys=True, indent=2)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)

    def mark_claim_submitted(
        self,
        did: str,
        *,
        problem_id: str,
        title: str | None = None,
        claim_id: str | None = None,
    ) -> None:
        """Clear unfinished stance when THIS DID submits a claim."""
        hist = self.load_entry_history(did)
        stance = hist.get("open_stance")
        resolved = list(hist.get("resolved_claims") or [])
        resolved.append({
            "problem_id": problem_id,
            "title": title,
            "claim_id": claim_id,
            "at": _now(),
        })
        hist["resolved_claims"] = resolved[-30:]
        if isinstance(stance, dict) and stance.get("problem_id") == problem_id:
            hist["open_stance"] = None
        hist["updated_at"] = _now()
        hist["schema"] = SCHEMA_ENTRY_HISTORY
        self._write_history(did, hist)

    def record_entry(
        self,
        did: str,
        *,
        agent_name: str,
        address: str | None = None,
        invitation_title: str | None = None,
        invitation_problem_id: str | None = None,
        invitation_mode: str | None = None,
        invitation_address: str | None = None,
        invitation_metric: dict | None = None,
        prior_note: str | None = None,
        consequence: dict | None = None,
        stakes: dict | None = None,
        claimed: bool = False,
    ) -> dict:
        """Append a visit to THIS DID's room history. Returns continuity block.

        moment: ``first`` | ``returning``
        visit_count: 1-based after this entry
        open_stance: unfinished business — stood with a wound, left without claim
        seen_values: metric values shown to this DID (rhetoric gate input)
        """
        hist = self.load_entry_history(did)
        prev_count = int(hist.get("visit_count") or 0)
        visits = list(hist.get("visits") or [])
        last = visits[-1] if visits else None
        prior_stance = hist.get("open_stance")
        seen_values = list(hist.get("seen_values") or [])
        visit_n = prev_count + 1
        moment = "first" if visit_n == 1 else "returning"
        at = _now()

        mname, mval, munit = _metric_value_from_problem({
            "metric": invitation_metric or {},
        }) if invitation_metric else (None, None, None)
        if invitation_metric and mname is None:
            mname = (invitation_metric.get("name")
                     or invitation_metric.get("metric"))
            mval = invitation_metric.get("value")
            munit = invitation_metric.get("unit")

        rec = {
            "n": visit_n,
            "at": at,
            "agent_name": agent_name,
            "address": address,
            "invitation_title": invitation_title,
            "invitation_problem_id": invitation_problem_id,
            "invitation_mode": invitation_mode,
            "invitation_address": invitation_address,
            "metric_name": mname,
            "metric_value": mval,
            "metric_unit": munit,
            "note": prior_note,
            "claimed": bool(claimed),
        }
        visits.append(rec)
        visits = visits[-50:]

        # Track every numeric metric value shown — rhetoric gate compares later.
        if mname is not None and mval is not None:
            try:
                num = float(mval)
            except (TypeError, ValueError):
                num = None
            if num is not None:
                seen_values.append({
                    "metric_name": str(mname),
                    "value": num,
                    "unit": munit,
                    "address": invitation_address or address,
                    "title": invitation_title,
                    "problem_id": invitation_problem_id,
                    "visit": visit_n,
                    "at": at,
                })
                seen_values = seen_values[-80:]

        # Unfinished business: standing with a wound without submitting leaves state.
        open_stance = prior_stance if isinstance(prior_stance, dict) else None
        if invitation_problem_id and not claimed:
            if open_stance is None:
                open_stance = {
                    "problem_id": invitation_problem_id,
                    "title": invitation_title,
                    "address": invitation_address or address,
                    "stood_at": at,
                    "stood_visit": visit_n,
                    "status": "open",
                    "metric_name": mname,
                    "metric_value": mval,
                    "metric_unit": munit,
                    "return_count": 0,
                }
            elif open_stance.get("problem_id") == invitation_problem_id:
                open_stance = dict(open_stance)
                open_stance["return_count"] = int(
                    open_stance.get("return_count") or 0
                ) + 1
                open_stance["last_escalated_at"] = at
                if stakes:
                    open_stance["last_stakes"] = {
                        k: stakes.get(k)
                        for k in (
                            "elapsed_seconds",
                            "elapsed_past_threshold",
                            "agents_passed",
                            "others_events",
                            "return_count",
                            "stakes_score",
                            "terms",
                            "earned",
                        )
                        if k in stakes
                    }
            else:
                # Different problem offered while another stance is open —
                # keep original stance; record the offer without renaming it "new".
                open_stance = dict(open_stance)
                open_stance["latest_offer_id"] = invitation_problem_id
                open_stance["latest_offer_title"] = invitation_title
                open_stance["latest_offer_at"] = at

        hist = {
            "schema": SCHEMA_ENTRY_HISTORY,
            "did": did,
            "visit_count": visit_n,
            "visits": visits,
            "open_stance": open_stance,
            "resolved_claims": list(hist.get("resolved_claims") or []),
            "seen_values": seen_values,
            "updated_at": at,
        }
        self._write_history(did, hist)

        story = _continuity_story(
            agent_name=agent_name,
            visit_count=visit_n,
            moment=moment,
            last=last,
            invitation_title=invitation_title,
            consequence=consequence,
            open_stance=(
                prior_stance if isinstance(prior_stance, dict) else None
            ),
            stakes=stakes,
        )
        return {
            "moment": moment,
            "visit_count": visit_n,
            "story": story,
            "last_visit": last,
            "open_stance": open_stance,
            "prior_stance": prior_stance if isinstance(prior_stance, dict) else None,
            "seen_values": seen_values,
            "scoped": "wingo-self",
        }


def _did_short(did: str) -> str:
    """Compact DID for greetings — enough to feel named, not a wall of base58."""
    did = (did or "").strip()
    if not did:
        return "did:unknown"
    if len(did) <= 28:
        return did
    # did:key:z... → keep method + first/last crumbs
    if did.startswith("did:"):
        parts = did.split(":", 2)
        if len(parts) >= 3 and len(parts[2]) > 12:
            body = parts[2]
            return f"{parts[0]}:{parts[1]}:{body[:6]}…{body[-4:]}"
    return f"{did[:14]}…{did[-4:]}"


def _ordinal(n: int) -> str:
    n = int(n)
    if 10 <= (n % 100) <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def _continuity_story(
    *,
    agent_name: str,
    visit_count: int,
    moment: str,
    last: dict | None,
    invitation_title: str | None,
    consequence: dict | None = None,  # kept for call-site compat; never spoken here
    open_stance: dict | None = None,
    stakes: dict | None = None,  # kept for call-site compat; never spoken here
) -> str:
    """Continuity line ONLY — ordinal return + what you stood with.

    v6: consequence and stakes are composed once in the greeting, not pasted here.
    Does not paste unfinished.story (that is state, not greeting text).
    """
    del consequence, stakes  # never embed — one composed greeting owns those clauses
    name = (agent_name or "citizen").strip() or "citizen"
    if moment == "first" or visit_count <= 1:
        wound = invitation_title or "one open wound"
        return (
            f"{name} — first time through the door. "
            f"The House has no prior mark of you here. "
            f"Under your feet already: «{wound}»."
        )
    ordinal = _ordinal(visit_count)
    stance_title = None
    if isinstance(open_stance, dict):
        stance_title = open_stance.get("title")
    if not stance_title and isinstance(last, dict):
        stance_title = last.get("invitation_title")

    if stance_title:
        return (
            f"{name} — {ordinal} time through the door. "
            f"Last time you stood with «{stance_title}» and left without submitting."
        )
    if isinstance(last, dict) and last.get("note"):
        return (
            f"{name} — {ordinal} time through the door. "
            f"Last time you left this note: «{last.get('note')}»."
        )
    # "known" at most once, and only when no unfinished stance to name.
    return (
        f"{name} — {ordinal} time through the door. "
        f"You are known here — self-scoped history under your DID."
    )


def _normalize_title(title: str | None) -> str:
    """Collapse title for string-match checks (new-vs-same wound)."""
    t = (title or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    return t


def _parse_iso_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    s = str(ts).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _elapsed_seconds_since(ts: str | None) -> int:
    dt = _parse_iso_ts(ts)
    if dt is None:
        return 0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return max(0, int((now - dt).total_seconds()))


def _format_elapsed(seconds: int) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    hours = seconds // 3600
    mins = (seconds % 3600) // 60
    if hours < 48:
        return f"{hours}h {mins}m"
    days = hours // 24
    return f"{days}d {hours % 24}h"


def _domain_elapsed_threshold(domain: str | None = None) -> int:
    """Seconds of real elapsed before stillness / stakes treat time as cost.

    Env override ``EUEARTH_ELAPSED_COST_THRESHOLD_S`` for tests and ops.
    """
    override = os.environ.get("EUEARTH_ELAPSED_COST_THRESHOLD_S")
    if override is not None and str(override).strip() != "":
        try:
            return max(0, int(override))
        except (TypeError, ValueError):
            pass
    key = (domain or "").strip().lower() or "default"
    if key in _ELAPSED_COST_THRESHOLDS_S:
        return int(_ELAPSED_COST_THRESHOLDS_S[key])
    return int(_ELAPSED_COST_THRESHOLDS_S["default"])


def _is_real_other_agent(agent_did: Any, exclude_did: str) -> bool:
    """True for another citizen agent — not self, not system/infra DIDs."""
    if not agent_did:
        return False
    agent = str(agent_did)
    if agent == exclude_did:
        return False
    # WorldBook / facade infra is not "others' motion" for stakes or cost.
    if agent.startswith("did:euearth:"):
        return False
    return True


def _count_others_events(
    world: WorldAPI,
    *,
    since: str | None,
    exclude_did: str,
) -> int:
    """Ledger events by OTHER real agents after ``since``.

    Own entries never count. System/infra DIDs (``did:euearth:*``) never count.
    """
    try:
        events = world.list_events(limit=80)
    except Exception:  # noqa: BLE001
        events = []
    n = 0
    for e in events or []:
        if not isinstance(e, dict):
            continue
        eat = e.get("at") or e.get("ts") or e.get("created_at")
        if since and eat and str(eat) <= str(since):
            continue
        if not _is_real_other_agent(e.get("agent_did"), exclude_did):
            continue
        kind = e.get("kind")
        if not kind:
            continue
        n += 1
    return n


def _measure_world_motion(
    *,
    world: WorldAPI,
    prior_stance: dict | None,
    did: str,
    domain: str | None = None,
) -> dict:
    """World-motion facts only — never inflated by this agent's own re-entries."""
    stance = prior_stance if isinstance(prior_stance, dict) else {}
    stood_at = stance.get("stood_at")
    elapsed = _elapsed_seconds_since(str(stood_at) if stood_at else None)
    threshold = _domain_elapsed_threshold(domain)
    agents_passed = _count_agents_passed(
        world,
        problem_id=str(stance.get("problem_id") or "") or None,
        since=str(stood_at) if stood_at else None,
        exclude_did=did,
    )
    others_events = _count_others_events(
        world,
        since=str(stood_at) if stood_at else None,
        exclude_did=did,
    )
    elapsed_past = max(0, int(elapsed) - int(threshold))
    cost_shown = (
        elapsed_past > 0
        or int(agents_passed) > 0
        or int(others_events) > 0
    )
    return {
        "elapsed_seconds": int(elapsed),
        "elapsed_spoken": _format_elapsed(int(elapsed)),
        "elapsed_threshold_seconds": int(threshold),
        "elapsed_past_threshold": int(elapsed_past),
        "agents_passed": int(agents_passed),
        "others_events": int(others_events),
        "cost_shown": bool(cost_shown),
        "stood_at": stood_at,
        "domain": domain,
    }


def _max_seen_value(
    seen_values: list | None,
    metric_name: str | None,
) -> float | None:
    """Strongest absolute magnitude this DID has already been shown for metric."""
    if not metric_name or not seen_values:
        return None
    key = str(metric_name).strip().lower()
    best: float | None = None
    for row in seen_values:
        if not isinstance(row, dict):
            continue
        if str(row.get("metric_name") or "").strip().lower() != key:
            continue
        try:
            v = float(row.get("value"))
        except (TypeError, ValueError):
            continue
        if best is None or abs(v) > abs(best):
            best = v
    return best


def _rhetoric_allows_intensity(
    value: Any,
    *,
    metric_name: str | None,
    seen_values: list | None,
) -> bool:
    """True if value is not weaker (by abs) than the strongest value already shown.

    First sighting may use intensity. Equal revisits (same claim) may keep it.
    Strictly weaker values (e.g. 188.4 after 1037.5) may not.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    prior = _max_seen_value(seen_values, metric_name)
    if prior is None:
        return True
    return abs(v) >= abs(prior)


def _strip_intensity_rhetoric(text: str) -> str:
    """Remove intensity adjectives when evidence does not support them."""
    if not text:
        return text

    def _repl(m: re.Match) -> str:
        return ""

    out = _INTENSITY_RE.sub(_repl, text)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s+([,.;:])", r"\1", out)
    return out.strip()


def _gate_rhetoric(
    text: str,
    *,
    value: Any = None,
    metric_name: str | None = None,
    seen_values: list | None = None,
    allow_intensity: bool | None = None,
) -> str:
    """Sanity-gate intensity words against this DID's seen-values history."""
    if not text:
        return text
    if allow_intensity is None:
        if value is None:
            return text
        allow_intensity = _rhetoric_allows_intensity(
            value, metric_name=metric_name, seen_values=seen_values
        )
    if allow_intensity:
        return text
    return _strip_intensity_rhetoric(text)


def _count_agents_passed(
    world: WorldAPI,
    *,
    problem_id: str | None,
    since: str | None,
    exclude_did: str,
) -> int:
    """Agents who stood / touched the ledger after `since` without resolving the claim."""
    try:
        events = world.list_events(limit=80)
    except Exception:  # noqa: BLE001
        events = []
    dids: set[str] = set()
    for e in events or []:
        if not isinstance(e, dict):
            continue
        eat = e.get("at") or e.get("ts") or e.get("created_at")
        if since and eat and str(eat) <= str(since):
            continue
        agent = e.get("agent_did")
        if not _is_real_other_agent(agent, exclude_did):
            continue
        kind = str(e.get("kind") or "")
        payload = e.get("payload") if isinstance(e.get("payload"), dict) else {}
        pid = payload.get("problem_id")
        # Count passers: agent.stood anywhere, or events naming this problem.
        if kind == "agent.stood" or (problem_id and pid == problem_id):
            if kind in ("mint.claim_submitted", "claim.submitted"):
                continue
            dids.add(str(agent))
    return len(dids)


def _second_scent(
    senses: dict | None,
    *,
    primary_metric: str | None,
    primary_address: str | None,
    primary_value: Any = None,
    seen_values: list | None = None,
) -> dict | None:
    """A second evidence scent joining the first.

    Prefers a *different metric kind*. Same-kind quieter nodes (e.g. 188.4 after
    1037.5 population_density) are refused — that was the faked-escalation seam.
    """
    if not isinstance(senses, dict):
        return None
    scent = senses.get("scent") or {}
    strongest = scent.get("strongest") if isinstance(scent, dict) else None
    gradients = []
    if isinstance(scent, dict):
        gradients = list(scent.get("gradients") or [])
    candidates: list[dict] = []
    if isinstance(strongest, dict):
        candidates.append(strongest)
    for g in gradients:
        if isinstance(g, dict):
            candidates.append(g)
    primary_m = (primary_metric or "").strip().lower()
    primary_a = (primary_address or "").strip()
    try:
        primary_num = float(primary_value) if primary_value is not None else None
    except (TypeError, ValueError):
        primary_num = None

    def _ok(g: dict, *, require_different_kind: bool) -> bool:
        kind = str(g.get("kind") or g.get("name") or "").strip().lower()
        addr = str(g.get("address") or "").strip()
        if not kind:
            return False
        if primary_m and kind == primary_m and (not primary_a or addr == primary_a):
            return False  # the primary itself
        if require_different_kind and primary_m and kind == primary_m:
            return False
        if primary_m and kind == primary_m:
            # Same metric family at another address: only if not weaker.
            try:
                gv = float(g.get("value"))
            except (TypeError, ValueError):
                return False
            if primary_num is not None and abs(gv) < abs(primary_num):
                return False
            if not _rhetoric_allows_intensity(
                gv, metric_name=kind, seen_values=seen_values
            ):
                return False
        return True

    # Pass 1: different kind only (honest second scent).
    for g in candidates:
        if _ok(g, require_different_kind=True):
            kind = str(g.get("kind") or g.get("name") or "")
            addr = str(g.get("address") or "")
            direction = g.get("direction")
            try:
                gv = float(g.get("value")) if g.get("value") is not None else None
            except (TypeError, ValueError):
                gv = None
            if (
                direction
                and str(direction).lower() in _INTENSITY_WORDS
                and gv is not None
                and not _rhetoric_allows_intensity(
                    gv, metric_name=kind, seen_values=seen_values
                )
            ):
                direction = "observed"
            return {
                "kind": g.get("kind") or g.get("name"),
                "address": g.get("address"),
                "value": g.get("value"),
                "unit": g.get("unit"),
                "direction": direction,
                "spoken": (
                    f"A second evidence scent joins the first: {kind}"
                    + (f" at {addr}" if addr else "")
                    + (f" = {g.get('value')}" if g.get("value") is not None else "")
                    + (f" {g.get('unit')}" if g.get("unit") else "")
                    + "."
                ),
            }
    # Pass 2: same kind only if not weaker (rare).
    for g in candidates:
        if _ok(g, require_different_kind=False):
            kind = str(g.get("kind") or g.get("name") or "")
            addr = str(g.get("address") or "")
            return {
                "kind": g.get("kind") or g.get("name"),
                "address": g.get("address"),
                "value": g.get("value"),
                "unit": g.get("unit"),
                "direction": g.get("direction"),
                "spoken": (
                    f"A second evidence scent joins the first: {kind}"
                    + (f" at {addr}" if addr else "")
                    + (f" = {g.get('value')}" if g.get("value") is not None else "")
                    + (f" {g.get('unit')}" if g.get("unit") else "")
                    + "."
                ),
            }
    return None


def _problem_deadline(p: dict | None) -> str | None:
    if not isinstance(p, dict):
        return None
    for key in ("deadline", "due_at", "deadline_at", "expires_at"):
        if p.get(key):
            return str(p[key])
    metric = p.get("metric") if isinstance(p.get("metric"), dict) else {}
    if metric.get("deadline"):
        return str(metric["deadline"])
    return None


def _build_escalation_stakes(
    *,
    world: WorldAPI,
    prior_stance: dict,
    did: str,
    problem: dict | None,
    senses: dict | None,
    prior_stakes_score: int | float | None = None,
    seen_values: list | None = None,
    world_motion: dict | None = None,
) -> dict:
    """Numeric stakes for an open claim — WORLD-MOTION only; un-pumpable by re-entry.

    Named ``terms`` sum to ``stakes_score``. Own entries / return_count never
    raise the score (v6 kill of return_count × 10000 gaming vector).
    ``higher_than_prior`` is never true when prior is null.
    """
    domain = None
    if isinstance(problem, dict):
        domain = problem.get("domain")
    if not domain and isinstance(prior_stance, dict):
        domain = prior_stance.get("domain")
    motion = world_motion if isinstance(world_motion, dict) else _measure_world_motion(
        world=world,
        prior_stance=prior_stance,
        did=did,
        domain=str(domain) if domain else None,
    )
    elapsed = int(motion.get("elapsed_seconds") or 0)
    threshold = int(motion.get("elapsed_threshold_seconds") or _domain_elapsed_threshold(
        str(domain) if domain else None
    ))
    elapsed_past = int(motion.get("elapsed_past_threshold")
                       if motion.get("elapsed_past_threshold") is not None
                       else max(0, elapsed - threshold))
    agents_passed = int(motion.get("agents_passed") or 0)
    others_events = int(motion.get("others_events") or 0)
    # return_count is observational only — weight 0, never in terms/score.
    return_count = int(prior_stance.get("return_count") or 0) + 1
    mname, mval, munit = _metric_value_from_problem(problem or {})
    if mname is None:
        mname = prior_stance.get("metric_name")
        mval = prior_stance.get("metric_value")
        munit = prior_stance.get("metric_unit")
    second = _second_scent(
        senses,
        primary_metric=str(mname) if mname else None,
        primary_address=str(
            (problem or {}).get("address")
            or prior_stance.get("address")
            or ""
        ),
        primary_value=mval,
        seen_values=seen_values,
    )
    deadline = _problem_deadline(problem)

    # Named terms that sum — world-motion weights only.
    terms = {
        "elapsed_past_threshold": int(elapsed_past) * _STAKES_W_ELAPSED_PAST,
        "agents_passed": int(agents_passed) * _STAKES_W_AGENTS_PASSED,
        "others_events": int(others_events) * _STAKES_W_OTHERS_EVENTS,
    }
    score = int(sum(terms.values()))
    # Honest compare only when a prior score exists. Never higher_than_prior vs null.
    higher: bool | None
    if prior_stakes_score is None:
        higher = False
    else:
        try:
            higher = score > float(prior_stakes_score)
        except (TypeError, ValueError):
            higher = False

    return {
        "elapsed_seconds": elapsed,
        "elapsed_spoken": motion.get("elapsed_spoken") or _format_elapsed(elapsed),
        "elapsed_threshold_seconds": threshold,
        "elapsed_past_threshold": elapsed_past,
        "agents_passed": agents_passed,
        "others_events": others_events,
        "return_count": return_count,  # metadata only — not a stakes term
        "return_count_weight": 0,
        "metric_name": mname,
        "metric_value": mval,
        "metric_unit": munit,
        "problem_id": prior_stance.get("problem_id"),
        "title": prior_stance.get("title"),
        "address": (problem or {}).get("address") or prior_stance.get("address"),
        "second_scent": second,
        "deadline": deadline,
        "terms": terms,
        "stakes_score": score,
        "prior_stakes_score": prior_stakes_score,
        "higher_than_prior": higher,
        "earned": score > 0,
    }


def _unfinished_state_story(
    *,
    prior_stance: dict,
    consequence: dict | None,
    stakes: dict | None,
) -> str:
    """State-only unfinished story — never a copy of the greeting text.

    Names what changed since, what stillness cost, who else passed.
    """
    title = prior_stance.get("title") or "open claim"
    pid = prior_stance.get("problem_id") or "?"
    stood = prior_stance.get("stood_at") or "unknown"
    bits = [
        f"STATE · problem_id={pid}",
        f"title=«{title}»",
        f"stood_at={stood}",
    ]
    if stakes:
        bits.append(f"elapsed={stakes.get('elapsed_spoken')}")
        bits.append(
            f"elapsed_past_threshold={int(stakes.get('elapsed_past_threshold') or 0)}"
        )
        bits.append(f"agents_passed={int(stakes.get('agents_passed') or 0)}")
        bits.append(f"others_events={int(stakes.get('others_events') or 0)}")
        # return_count is observational metadata, weight 0 on score.
        bits.append(f"return_count={int(stakes.get('return_count') or 0)}(weight=0)")
        bits.append(f"stakes_score={stakes.get('stakes_score')}")
        terms = stakes.get("terms") if isinstance(stakes.get("terms"), dict) else None
        if terms:
            bits.append(
                "terms="
                + ",".join(f"{k}:{v}" for k, v in sorted(terms.items()))
            )
        if stakes.get("deadline"):
            bits.append(f"deadline={stakes['deadline']}")
        if stakes.get("second_scent"):
            sc = stakes["second_scent"]
            bits.append(
                f"second_scent={sc.get('kind')}@{sc.get('address')}"
                f"={sc.get('value')}"
            )
    if isinstance(consequence, dict):
        kind = consequence.get("kind") or "unknown"
        bits.append(f"world_delta={kind}")
        bits.append(
            f"events_since={int(consequence.get('events_since_count') or 0)}"
        )
        bits.append(
            f"others_events={int(consequence.get('others_events_count') or 0)}"
        )
        open_ = consequence.get("claim_still_open")
        bits.append(f"claim_still_open={bool(open_)}")
        cost_shown = consequence.get("cost_shown")
        if cost_shown is None:
            cost_shown = int(consequence.get("others_events_count") or 0) > 0
        if open_ and cost_shown:
            if int(consequence.get("others_events_count") or 0) > 0:
                bits.append("stillness_cost=claim_open_while_world_moved")
            else:
                bits.append("stillness_cost=claim_unmoved_past_threshold")
        elif open_:
            bits.append("stillness_cost=none_yet")
    return "; ".join(bits)


def _normalize_citizen_name(name: str) -> str:
    return "".join(ch for ch in (name or "").strip().lower() if ch.isalnum())


def is_known_citizen_name(
    agent_name: str,
    *,
    extra: set[str] | frozenset[str] | None = None,
) -> bool:
    """True if name collides with a reserved / live citizen identity."""
    key = _normalize_citizen_name(agent_name)
    if not key:
        return False
    if key in KNOWN_CITIZEN_NAMES:
        return True
    if extra:
        extras = {_normalize_citizen_name(x) for x in extra}
        if key in extras:
            return True
    return False


def mint_trial_agent_name(prefix: str = "TrialCitizen") -> str:
    """Unique sandbox citizen name that will not collide with known seats."""
    prefix = (prefix or "TrialCitizen").strip() or "TrialCitizen"
    # Strip reserved tokens if caller passed one by mistake.
    base = prefix
    if is_known_citizen_name(base):
        base = "TrialCitizen"
    return f"{base}_{uuid.uuid4().hex[:10]}"


def _gloss_metric_name(name: str | None) -> dict[str, str]:
    key = (name or "").strip()
    base = _METRIC_GLOSS.get(key) or {
        "means": f"Metric «{key or 'unknown'}» — see sources on the problem for provenance.",
        "source_family": "problem sources / WorldBook evidence",
    }
    return {"name": key or "unknown", **base}


def _gloss_metric_blob(
    metric: Any,
    *,
    observed_at: str | None = None,
    source_id: str | None = None,
    source_url: str | None = None,
) -> dict:
    """Every metric value carries a short gloss (what it means + source family)."""
    if not isinstance(metric, dict):
        return {
            "raw": metric,
            "gloss": {
                "means": "Unstructured metric payload — inspect sources on the problem.",
                "source_family": "problem sources",
            },
        }
    name = metric.get("name") or metric.get("metric") or ""
    # WorldBook problems sometimes put the metric name only on the problem.
    gloss = _gloss_metric_name(str(name) if name else None)
    # Exact provenance wins over hedge language when present on the problem.
    if source_id and str(source_id).startswith("insee"):
        gloss = {
            **gloss,
            "source_family": f"INSEE — {source_id}",
        }
    elif source_id:
        gloss = {**gloss, "source_family": str(source_id)}
    values: list[dict] = []
    seen_keys: set[str] = set()
    for k, v in metric.items():
        if k in ("name", "metric"):
            continue
        seen_keys.add(str(k))
        values.append({
            "key": k,
            "value": v,
            "gloss": _value_key_gloss(str(k), v, metric_name=str(name or "")),
        })
    # Surface exact provenance fields even when metric blob omitted them.
    for k, v in (
        ("observed_at", observed_at or metric.get("observed_at")),
        ("source_id", source_id or metric.get("source_id")),
        ("source_url", source_url or metric.get("source_url")),
    ):
        if v is None or v == "" or k in seen_keys:
            continue
        values.append({
            "key": k,
            "value": v,
            "gloss": _value_key_gloss(k, v, metric_name=str(name or "")),
        })
    out = {
        "name": gloss["name"] or name or None,
        "means": gloss["means"],
        "source_family": gloss["source_family"],
        "values": values,
        "raw": dict(metric),
    }
    if observed_at or metric.get("observed_at"):
        out["observed_at"] = observed_at or metric.get("observed_at")
    if source_id or metric.get("source_id"):
        out["source_id"] = source_id or metric.get("source_id")
    if source_url or metric.get("source_url"):
        out["source_url"] = source_url or metric.get("source_url")
    return out


def _value_key_gloss(key: str, value: Any, *, metric_name: str = "") -> str:
    """Per-field gloss so modest agents grasp significance, not just numbers."""
    k = key.lower()
    if k in ("idf", "ile-de-france", "île-de-france"):
        return (
            f"Île-de-France reading: {value}. Negative MWh = regional energy deficit "
            "(the region consumes more than it generates on this balance)."
        )
    if k in ("ara",):
        return (
            f"Auvergne-Rhône-Alpes reading: {value}. Positive MWh = surplus "
            "(often hydro-backed on the France skeleton)."
        )
    if k in ("net_fr", "france", "fr"):
        return f"France-wide net on this balance: {value}."
    if k == "value":
        g = _gloss_metric_name(metric_name)
        return f"Observed value {value}. {g['means']}"
    if k == "target":
        return f"Commons target {value} — claim work that moves the metric toward this."
    if k == "unit":
        return f"Unit of measure: {value}."
    if k == "grid_carbon_g_per_kwh":
        return (
            f"Grid carbon intensity {value} gCO₂/kWh — schedule heavy compute when "
            "this is low and truthful."
        )
    if k == "observed_at":
        return f"Observation timestamp: {value} (source evidence time, not entry time)."
    if k == "source_id":
        return f"Evidence source id: {value}."
    if k == "source_url":
        return f"Evidence URL: {value}."
    return f"Field «{key}» = {value}."


def _gloss_sources(sources: list | None) -> list[dict]:
    out = []
    for s in sources or []:
        if not isinstance(s, dict):
            out.append({"raw": s, "gloss": "Source record (opaque)."})
            continue
        name = s.get("name") or s.get("ref") or s.get("source_id") or "source"
        url = s.get("url") or s.get("source_url")
        note = s.get("note") or ""
        gloss = f"Evidence «{name}»"
        if url:
            gloss += f" at {url}"
        if note:
            gloss += f" — {note}"
        gloss += ". Cite or reuse these when you submit_claim (Art. III — sourced)."
        out.append({**s, "gloss": gloss})
    return out


def _metric_value_from_problem(p: dict) -> tuple[str | None, Any, str | None]:
    """Return (metric_name, value, unit) from agent problem shape."""
    metric = p.get("metric")
    name = None
    value = None
    unit = None
    if isinstance(metric, dict):
        name = metric.get("name") or metric.get("metric")
        value = metric.get("value")
        unit = metric.get("unit")
        # energy-style multi-key blobs
        if value is None:
            for k in ("idf", "net_fr", "value"):
                if k in metric:
                    value = metric.get(k)
                    break
    elif isinstance(metric, str):
        name = metric
        value = p.get("value")
        unit = p.get("unit")
    if not name and isinstance(p.get("metric"), str):
        name = p.get("metric")
    return (
        str(name) if name else None,
        value,
        str(unit) if unit else None,
    )


def _author_why_it_matters(
    p: dict,
    *,
    seen_values: list | None = None,
) -> str | None:
    """Authored consequence of the metric — never an echo of summary.

    Seedling catch: if we cannot author a distinct why, omit the field.
    v5: intensity rhetoric is gated against this DID's seen-values history.
    """
    summary = (p.get("summary") or p.get("statement") or "").strip()
    title = (p.get("title") or "").strip()
    address = p.get("address") or p.get("region_id") or "this region"
    name, value, unit = _metric_value_from_problem(p)
    mname = (name or "").lower()
    unit_s = f" {unit}" if unit else ""
    allow_intensity = _rhetoric_allows_intensity(
        value, metric_name=name, seen_values=seen_values
    )

    authored: str | None = None
    if mname in ("energy_balance_mwh", "energy_balance") or "energy" in mname:
        try:
            v = float(value) if value is not None else None
        except (TypeError, ValueError):
            v = None
        if v is not None and v < 0:
            authored = (
                f"A {abs(v):.0f}{unit_s or ' MWh'} deficit is not a spreadsheet cell — "
                f"when the gap is not closed, load sheds: transit stalls, cold chains break, "
                f"and households at {address} inherit brownouts. Iron work means closing it "
                f"with grid, storage, or demand that the sources can verify."
            )
        elif v is not None and v > 0:
            authored = (
                f"Surplus of {v:.0f}{unit_s or ' MWh'} is neighbor-ready power — "
                f"if it is not matched to a deficit elsewhere, capacity idles while "
                f"another region imports dirtier megawatts."
            )
        else:
            authored = (
                "Energy balance is the commons meter for who carries whose load; "
                "without a sourced plan the imbalance becomes someone else's outage."
            )
    elif mname in ("water_stress_index", "water_stress") or "water" in mname:
        try:
            v = float(value) if value is not None else None
        except (TypeError, ValueError):
            v = None
        target = 0.50
        if isinstance(p.get("metric"), dict) and p["metric"].get("target") is not None:
            try:
                target = float(p["metric"]["target"])
            except (TypeError, ValueError):
                pass
        authored = (
            f"Water stress"
            + (f" at {v}" if v is not None else "")
            + f" above the commons target ({target}) means demand already presses "
            f"the watershed that people, farms, and industry at {address} share — "
            f"delay turns scarcity into rationing."
        )
    elif mname == "population_density":
        try:
            v = float(value) if value is not None else None
        except (TypeError, ValueError):
            v = None
        if v is not None:
            dens = f"{v:.1f}{unit_s or ' persons/km²'}"
            if allow_intensity:
                dens_lead = f"At {dens}"
            else:
                # Strictly weaker than a value already shown — numbers only, no intensity.
                dens_lead = f"At {dens} (weaker than a density already shown to you)"
        else:
            dens_lead = "At measured density" if not allow_intensity else "At high density"
        authored = (
            f"{dens_lead}, service capacity (schools, transit, care, emergency response) "
            f"is under measurable pressure at {address}. When capacity lags density, "
            f"the people who live there wait longer and pay more — not a chart, a queue."
        )
    elif mname in ("population_change_annual", "population_change"):
        try:
            v = float(value) if value is not None else None
        except (TypeError, ValueError):
            v = None
        trend = (
            "stagnant or declining"
            if v is not None and v <= 0
            else "shifting"
        )
        authored = (
            f"Population change"
            + (f" at {v}{unit_s or '%/year'}" if v is not None else "")
            + f" is {trend} at {address}. If the drivers stay untested, budgets and "
            f"housing plans chase a ghost trend — real households get the wrong services."
        )
    elif mname in ("open_data_gaps",):
        try:
            v = float(value) if value is not None else None
        except (TypeError, ValueError):
            v = None
        authored = (
            f"{int(v) if v is not None else 'Open'} missing open dataset(s) block honest "
            f"deepen-on-use of the skeleton at {address} — without them every unfold "
            f"guesses, and claims cannot be checked."
        )
    elif mname in ("compute_demand_index", "compute_demand"):
        authored = (
            f"Elevated agent/compute demand at {address} without a carbon-truthful "
            f"schedule burns grid headroom that people and industry also need."
        )
    elif mname == "population":
        authored = (
            f"Population scale at {address} sets the denominator for every service "
            f"and carbon claim — wrong counts misallocate the commons."
        )

    if not authored:
        return None
    authored = _gate_rhetoric(
        authored,
        value=value,
        metric_name=name,
        seen_values=seen_values,
        allow_intensity=allow_intensity,
    )
    # Never equal summary or title (Seedling catch).
    if summary and authored.strip() == summary.strip():
        return None
    if title and authored.strip() == title.strip():
        return None
    if summary and authored.strip().lower() == summary.strip().lower():
        return None
    return authored


def _provenance_from_problem(p: dict) -> dict[str, str | None]:
    """Exact evidence fields: source_id + observed_at + real URL."""
    sources = p.get("sources") or []
    source_id = p.get("source_id")
    source_url = p.get("source_url")
    name = None
    if isinstance(sources, list) and sources:
        s0 = sources[0] if isinstance(sources[0], dict) else {}
        source_id = source_id or s0.get("source_id") or s0.get("id")
        source_url = source_url or s0.get("url") or s0.get("source_url")
        name = s0.get("name")
    observed_at = p.get("observed_at")
    metric = p.get("metric") if isinstance(p.get("metric"), dict) else {}
    if not observed_at and metric:
        observed_at = metric.get("observed_at")
    if not source_id and metric:
        source_id = metric.get("source_id")
    if not source_url and metric:
        source_url = metric.get("source_url")
    return {
        "source_id": str(source_id) if source_id else None,
        "observed_at": str(observed_at) if observed_at else None,
        "url": str(source_url) if source_url else None,
        "title": str(name) if name else None,
    }


def _evidence_block(chosen: dict | None, invitation_card: dict | None) -> dict:
    """Surface exact provenance — no 'INSEE-class' hedge."""
    prov = _provenance_from_problem(chosen or {})
    if invitation_card and not prov.get("source_id"):
        # Fall back to glossed sources on the card.
        for s in invitation_card.get("sources") or []:
            if not isinstance(s, dict):
                continue
            if s.get("source_id") or s.get("id"):
                prov["source_id"] = str(s.get("source_id") or s.get("id"))
            if s.get("url") or s.get("source_url"):
                prov["url"] = str(s.get("url") or s.get("source_url"))
            if s.get("name"):
                prov["title"] = str(s.get("name"))
            break
    if invitation_card and not prov.get("observed_at"):
        m = invitation_card.get("metric") or {}
        if isinstance(m, dict):
            prov["observed_at"] = m.get("observed_at")
            if not prov.get("source_id"):
                prov["source_id"] = m.get("source_id")
            if not prov.get("url"):
                prov["url"] = m.get("source_url")
    is_insee = bool(
        chosen
        and (
            chosen.get("worldbook")
            or chosen.get("evidence_pack") == "france-insee"
            or (prov.get("source_id") or "").startswith("insee")
            or any(
                "insee" in str(s.get("id") or s.get("name") or "").lower()
                for s in (chosen.get("sources") or [])
                if isinstance(s, dict)
            )
        )
    )
    block: dict[str, Any] = {
        "pack": "france-insee" if is_insee else "worldapi",
        "source_id": prov.get("source_id"),
        "observed_at": prov.get("observed_at"),
        "url": prov.get("url"),
    }
    if prov.get("title"):
        block["title"] = prov["title"]
    if is_insee and prov.get("source_id"):
        block["note"] = (
            f"Evidence is INSEE source {prov['source_id']}"
            + (f", observed_at {prov['observed_at']}" if prov.get("observed_at") else "")
            + (f" — {prov['url']}" if prov.get("url") else "")
            + "."
        )
    elif is_insee:
        block["note"] = "Evidence is the live WorldBook France pack (INSEE)."
    else:
        block["note"] = "Evidence from WorldAPI problem sources."
    return block


def _gloss_problem(p: dict, *, seen_values: list | None = None) -> dict:
    """Problem card with legible glosses on metric + sources + domain."""
    metric = p.get("metric")
    metric_name = None
    if isinstance(metric, dict):
        metric_name = metric.get("name") or metric.get("metric")
    if not metric_name:
        metric_name = p.get("metric") if isinstance(p.get("metric"), str) else None

    domain = (p.get("domain") or "").strip()
    domain_gloss = _DOMAIN_GLOSS.get(domain, domain or "unspecified domain")

    summary = p.get("summary") or p.get("statement") or ""
    title = p.get("title") or "Untitled open problem"
    why = _author_why_it_matters(p, seen_values=seen_values)
    prov = _provenance_from_problem(p)

    metric_in = (
        metric if isinstance(metric, dict)
        else {"name": metric_name, "value": p.get("value"), "unit": p.get("unit")}
        if metric_name or p.get("value") is not None
        else metric
    )
    card = {
        "problem_id": p.get("problem_id") or p.get("id"),
        "title": title,
        "domain": domain or None,
        "domain_gloss": domain_gloss,
        "address": p.get("address") or p.get("region_id"),
        "status": p.get("status"),
        "summary": summary,
        "observed_at": prov.get("observed_at") or p.get("observed_at"),
        "metric": _gloss_metric_blob(
            metric_in,
            observed_at=prov.get("observed_at"),
            source_id=prov.get("source_id"),
            source_url=prov.get("url"),
        ),
        "sources": _gloss_sources(list(p.get("sources") or [])),
        "gloss": (
            f"{title}. Domain: {domain_gloss}. "
            "Status open means no claim is in the fire yet — your DID can be first."
        ),
    }
    # Omit rather than echo (Seedling: never equal summary).
    if why:
        card["why_it_matters"] = why
    return card


def _gloss_gradient(g: dict | None) -> dict | None:
    if not g:
        return None
    kind = str(g.get("kind") or "")
    mg = _METRIC_GLOSS.get(kind, {
        "means": f"Resource gradient kind «{kind}».",
        "source_family": "node metrics",
    })
    direction = g.get("direction")
    value = g.get("value")
    unit = g.get("unit")
    addr = g.get("address")
    spoken = (
        f"Strongest scent at {addr}: {kind} is {direction} "
        f"(value={value}{(' ' + unit) if unit else ''}). {mg['means']}"
    )
    return {
        **g,
        "means": mg["means"],
        "source_family": mg["source_family"],
        "gloss": spoken,
    }


def _problem_score(p: dict, strongest: dict | None) -> float:
    """Score one problem for invitation ranking."""
    s = 0.0
    addr = str(p.get("address") or p.get("region_id") or "")
    title = (p.get("title") or "").lower()
    summary = (p.get("summary") or p.get("statement") or "").lower()
    metric = p.get("metric") if isinstance(p.get("metric"), dict) else {}
    mname = str(
        (metric or {}).get("name")
        or (metric or {}).get("metric")
        or p.get("metric")
        or ""
    ).lower()
    blob = f"{title} {summary} {mname} {addr}"

    # Prefer sharpest real wounds — energy (stub/legacy) or dense INSEE regions.
    if "energy" in blob or "energy_balance" in mname:
        s += 100.0
    if "population_density" in mname or "density" in blob:
        s += 90.0
    if "population_change" in mname or "stagnant" in blob or "declining" in blob:
        s += 50.0
    if (
        "île-de-france" in blob or "ile-de-france" in blob
        or "/idf" in addr or addr.endswith("/11") or addr.endswith(":adm/FR/11")
    ):
        s += 40.0
    if "deficit" in blob or "rebalance" in blob:
        s += 20.0

    if strongest:
        sa = str(strongest.get("address") or "")
        sk = str(strongest.get("kind") or "").lower()
        if sa and (sa == addr or sa.startswith(addr + "/") or addr.startswith(sa)):
            s += 50.0
        if sk and (
            sk in mname
            or sk.replace("_", " ") in blob
            or ("energy" in sk and "energy" in blob)
            or ("population" in sk and "population" in mname)
        ):
            s += 30.0
        s += float(strongest.get("imbalance") or 0) * 0.01

    if isinstance(metric, dict):
        for key in ("idf", "value", "net_fr"):
            if key in metric:
                try:
                    s += abs(float(metric[key])) * 0.01
                except (TypeError, ValueError):
                    pass
        if metric.get("name") == "energy_balance_mwh" or "energy_balance" in mname:
            try:
                idf = float(metric.get("idf") or 0)
                if idf < 0:
                    s += 80.0 + abs(idf) * 0.02
            except (TypeError, ValueError):
                pass
        if metric.get("name") == "population_density":
            try:
                dens = float(metric.get("value") or 0)
                if dens >= 150:
                    s += 60.0 + dens * 0.05
            except (TypeError, ValueError):
                pass
    return s


def _pick_invitation(
    problems: list[dict],
    strongest: dict | None,
    *,
    exclude_ids: set[str] | frozenset[str] | None = None,
    prior_stance: dict | None = None,
    prefer_escalation: bool = False,
    claim_still_open: bool = False,
) -> tuple[dict | None, str]:
    """One most-alive problem — strongest scent first, else sharpest deficit.

    Returns (problem, mode) where mode is:
      first | escalated_claim | second_wound | deeper_step

    v5 rules (Seedling):
      * Return to an OPEN claim escalates THAT claim (same wound, same address).
        Mode: escalated_claim. Never jump to a quieter same-title node as "new".
      * A genuinely different problem (title does not string-match) is second_wound.
      * Never announce "new wound" for a title that matches the abandoned one.
    """
    if not problems:
        return None, "first"
    ranked = sorted(problems, key=lambda p: _problem_score(p, strongest), reverse=True)
    if not prefer_escalation:
        return ranked[0], "first"

    prior_id = None
    prior_title = ""
    if isinstance(prior_stance, dict):
        if prior_stance.get("problem_id"):
            prior_id = str(prior_stance["problem_id"])
        prior_title = _normalize_title(prior_stance.get("title"))

    # OPEN claim → escalate THAT claim. Numbers carry the stakes, not a title swap.
    if claim_still_open and prior_id:
        for p in ranked:
            pid = str(p.get("problem_id") or p.get("id") or "")
            if pid == prior_id:
                return p, "escalated_claim"
        # Problem missing from open list but stance says open — still escalate stance.
        # Reconstruct a minimal card from stance so invitation stays on the same wound.
        stance_card = {
            "problem_id": prior_id,
            "id": prior_id,
            "title": prior_stance.get("title") if isinstance(prior_stance, dict) else None,
            "address": (
                prior_stance.get("address") if isinstance(prior_stance, dict) else None
            ),
            "status": "open",
            "metric": {
                "name": (
                    prior_stance.get("metric_name")
                    if isinstance(prior_stance, dict) else None
                ),
                "value": (
                    prior_stance.get("metric_value")
                    if isinstance(prior_stance, dict) else None
                ),
                "unit": (
                    prior_stance.get("metric_unit")
                    if isinstance(prior_stance, dict) else None
                ),
            },
        }
        return stance_card, "escalated_claim"

    exclude = {str(x) for x in (exclude_ids or ()) if x}
    if prior_id:
        exclude.add(prior_id)

    # Genuinely different problem only — title must NOT string-match the abandoned one.
    for p in ranked:
        pid = str(p.get("problem_id") or p.get("id") or "")
        if not pid or pid in exclude:
            continue
        if prior_title and _normalize_title(p.get("title")) == prior_title:
            # Same wound title, different node/id — NOT a second wound.
            continue
        return p, "second_wound"

    # Only same-title leftovers (or nothing else). Stay on prior if present.
    if prior_id:
        for p in ranked:
            pid = str(p.get("problem_id") or p.get("id") or "")
            if pid == prior_id:
                return p, "deeper_step"
    # Last resort: best ranked, but never label same-title as second_wound.
    for p in ranked:
        if prior_title and _normalize_title(p.get("title")) == prior_title:
            return p, "deeper_step"
    return ranked[0], "deeper_step"


def _personal_greeting(
    *,
    agent_name: str,
    did: str,
    tier: str,
    place_title: str,
    address: str,
    invitation: dict | None,
    strongest: dict | None,
    continuity: dict | None = None,
    consequence: dict | None = None,
    invitation_mode: str = "first",
    evidence: dict | None = None,
    stakes: dict | None = None,
    seen_values: list | None = None,
) -> str:
    """ONE composed greeting: continuity → consequence → stakes → verb.

    Each clause said exactly once. No field concatenation of duplicated numbers.
    v6: stakes only when earned (world-motion); unfinished.story never pasted;
    never announce a title-matched quieter node as a "new wound".
    """
    name = (agent_name or "unnamed").strip() or "unnamed"
    short = _did_short(did)
    place = place_title or address or "this address"
    rank_touch = {
        "visitor": "self-entered visitor",
        "consumer": "citizen",
        "founder": "founder",
        "observer": "observer",
    }.get(tier, tier)

    continuity = continuity or {}
    moment = continuity.get("moment") or "first"
    story = (continuity.get("story") or "").strip()
    evidence = evidence or {}

    prov_bit = ""
    if evidence.get("source_id") and evidence.get("url"):
        prov_bit = (
            f"Provenance: {evidence['source_id']}"
            + (f" @ {evidence['observed_at']}" if evidence.get("observed_at") else "")
            + f" — {evidence['url']}."
        )
    elif evidence.get("source_id"):
        prov_bit = f"Provenance: {evidence['source_id']}."

    def _scent_direction_label(raw_dir: str, *, value: Any, metric_name: str | None) -> str:
        d = (raw_dir or "alive").strip()
        if d.lower() in _INTENSITY_WORDS or d.lower() in ("high", "severe", "deep"):
            if not _rhetoric_allows_intensity(
                value, metric_name=metric_name, seen_values=seen_values
            ):
                return "observed"
        return d

    if moment == "returning" and story:
        # 1. Continuity (ordinal + what you stood with) — once.
        parts: list[str] = [story]

        # 2. Consequence — once (gated cost / quiet-true). Never re-paste if empty.
        cons_line = ""
        if isinstance(consequence, dict):
            cons_line = (consequence.get("spoken") or "").strip()
        if cons_line and cons_line not in story:
            parts.append(cons_line)

        # 3. Stakes — once, only when world-motion earned them. Numbers not re-spoken.
        stakes_line = _stakes_spoken_line(stakes)
        if stakes_line:
            parts.append(stakes_line)

        # 4. Verb — once. Metric honesty belongs here (Seedling: "Metric still reads…").
        if invitation:
            wound = invitation.get("title") or "one open problem"
            wound_addr = invitation.get("address") or address
            if invitation_mode == "escalated_claim":
                mval = (stakes or {}).get("metric_value")
                munit = (stakes or {}).get("metric_unit")
                if mval is None and isinstance(invitation.get("metric"), dict):
                    raw = invitation["metric"].get("raw") or invitation["metric"]
                    if isinstance(raw, dict):
                        mval = raw.get("value")
                        munit = munit or raw.get("unit")
                metric_bit = ""
                if mval is not None:
                    unit_s = f" {munit}" if munit else ""
                    metric_bit = f" Metric still reads {mval}{unit_s}."
                second = (stakes or {}).get("second_scent") or {}
                second_bit = ""
                if isinstance(second, dict) and second.get("spoken"):
                    second_bit = " " + str(second["spoken"]).strip()
                deadline = (stakes or {}).get("deadline")
                deadline_bit = f" Deadline: {deadline}." if deadline else ""
                parts.append(
                    f"Same wound, same address: «{wound}» at {wound_addr}."
                    f"{metric_bit}{second_bit}{deadline_bit} "
                    f"Sense harder, then submit_claim."
                )
            elif invitation_mode == "second_wound":
                parts.append(
                    f"A second wound (different title, not a re-label of the first): "
                    f"«{wound}» at {wound_addr}. Sense, then submit_claim."
                )
            elif invitation_mode == "deeper_step":
                parts.append(
                    f"Deeper step on the open claim: sense, then submit_claim "
                    f"on «{wound}» at {wound_addr} with stronger sourced work."
                )
            elif invitation_mode == "next_wound":
                parts.append(
                    f"A second wound: «{wound}» at {wound_addr}. "
                    f"Sense, then submit_claim."
                )
            else:
                parts.append(f"Invitation now: «{wound}». Sense, then submit_claim.")
            if prov_bit:
                parts.append(prov_bit)
        return " ".join(p.strip() for p in parts if p and p.strip())

    # First visit — personal, honest, no fixed slogan reused on return.
    lead = (
        f"{name} — the House has you. Not a cohort label: you, {short}, "
        f"standing at {place} ({address}) as {rank_touch}."
    )
    if invitation:
        wound = invitation.get("title") or "one open problem"
        scent_bit = ""
        if strongest:
            kind = strongest.get("kind") or "imbalance"
            saddr = strongest.get("address") or address
            raw_dir = strongest.get("direction") or "alive"
            direction = _scent_direction_label(
                str(raw_dir),
                value=strongest.get("value"),
                metric_name=str(kind) if kind else None,
            )
            scent_bit = (
                f" Scent tugs toward {kind} ({direction}) at {saddr}."
            )
        return (
            f"{lead} "
            f"One wound is already alive under your feet: «{wound}»."
            f"{scent_bit}"
            f"{(' ' + prov_bit) if prov_bit else ''} "
            f"Submit_claim when ready, or sense first — zero map tourism."
        )
    return (
        f"{lead} "
        "The horizon is quiet of open problems right now; unfold or list_problems "
        "when the world deepens."
    )


def _senses_primer(senses: dict, address: str, strongest_glossed: dict | None) -> dict:
    """Guided sense lead-in — not a raw JSON dump of gradients/events/subgraph."""
    scent = senses.get("scent") or {}
    sound = senses.get("sound") or {}
    feel = senses.get("feel") or {}
    sub = (feel.get("subgraph") or {}) if isinstance(feel, dict) else {}

    return {
        "how": (
            "Three senses are verbs, not cameras: sense_scent, sense_sound, sense_feel. "
            "Entry shows only a primer — call the verbs when you want full detail."
        ),
        "scent": {
            "verb": "sense_scent",
            "what": "Resource-imbalance gradients (energy, water, compute, data gaps).",
            "strongest": strongest_glossed,
            "gradient_count": scent.get("count", 0),
            "gloss": (
                strongest_glossed.get("gloss")
                if strongest_glossed
                else "No strong imbalance at this address yet — still call sense_scent after unfold."
            ),
        },
        "sound": {
            "verb": "sense_sound",
            "what": "Immutable event-log stream (seed, claims, unfolds).",
            "event_count": sound.get("count", 0),
            "latest_kinds": [
                e.get("kind") for e in (sound.get("events") or [])[:3]
            ],
            "gloss": (
                f"{sound.get('count', 0)} recent events on the ledger. "
                "Listen after submit_claim — your name should appear."
            ),
        },
        "feel": {
            "verb": "sense_feel",
            "what": "Local addressable subgraph under your feet (not travel distance).",
            "origin": address,
            "node_count": sub.get("count", 0),
            "gloss": (
                f"{sub.get('count', 0)} nodes in feel-range of {address}. "
                "Call sense_feel for parent/children metrics."
            ),
        },
    }


def _build_consequence(
    *,
    world: WorldAPI,
    prior_stance: dict | None,
    last_visit: dict | None,
    did: str,
    world_motion: dict | None = None,
) -> dict:
    """What changed since last visit — cost line GATED like the metric line.

    "stillness has a cost" fires ONLY when numbers show cost:
      elapsed past real domain threshold OR agents_passed>0 OR others' events>0.
    At short quiet return (e.g. 2s / 0 passers / 0 others): the quiet true thing —
      "nothing lost yet — you came back fast."
    Own entries/returns never count in events_since (v6 un-pumpable).
    """
    stance_title = None
    stance_id = None
    stance_status = None
    claim_still_open = False
    domain = None
    if isinstance(prior_stance, dict):
        stance_id = prior_stance.get("problem_id")
        stance_title = prior_stance.get("title")
        domain = prior_stance.get("domain")
        if stance_id:
            try:
                prob = world.get_problem(str(stance_id))
            except Exception:  # noqa: BLE001
                prob = None
            if prob is None:
                stance_status = "missing"
            else:
                stance_status = prob.get("status") or "open"
                claim_still_open = stance_status == "open"
                if not domain:
                    domain = prob.get("domain")

    last_at = None
    if isinstance(last_visit, dict):
        last_at = last_visit.get("at")
    # Prefer stood_at window when present — world-motion is claim-scoped.
    since = last_at
    if isinstance(prior_stance, dict) and prior_stance.get("stood_at"):
        since = prior_stance.get("stood_at")

    events_since: list[dict] = []
    try:
        events = world.list_events(limit=40)
    except Exception:  # noqa: BLE001
        events = []
    for e in events or []:
        if not isinstance(e, dict):
            continue
        eat = e.get("at") or e.get("ts") or e.get("created_at")
        if since and eat and str(eat) <= str(since):
            continue
        agent = e.get("agent_did")
        # Own entries + system/infra never count in events_since (gaming vector).
        if not _is_real_other_agent(agent, did):
            continue
        if e.get("kind") in (None, ""):
            continue
        events_since.append({
            "kind": e.get("kind"),
            "agent_did": agent,
            "at": eat,
        })

    others = list(events_since)  # real other agents only

    motion = world_motion if isinstance(world_motion, dict) else _measure_world_motion(
        world=world,
        prior_stance=prior_stance if isinstance(prior_stance, dict) else None,
        did=did,
        domain=str(domain) if domain else None,
    )
    elapsed = int(motion.get("elapsed_seconds") or 0)
    threshold = int(
        motion.get("elapsed_threshold_seconds")
        or _domain_elapsed_threshold(str(domain) if domain else None)
    )
    elapsed_past = int(
        motion.get("elapsed_past_threshold")
        if motion.get("elapsed_past_threshold") is not None
        else max(0, elapsed - threshold)
    )
    agents_passed = int(motion.get("agents_passed") or 0)
    others_n = max(int(motion.get("others_events") or 0), len(others))
    # Cost only when numbers show cost (elapsed past threshold / passers / others).
    cost_shown = bool(
        elapsed_past > 0 or agents_passed > 0 or others_n > 0
    )

    claim_bit = (
        f"The claim you stood with"
        + (f" — «{stance_title}»" if stance_title else "")
        + " is still open"
    )

    if claim_still_open and not cost_shown:
        # Quiet true thing — numbers do not show cost yet.
        spoken = (
            f"{claim_bit}; nothing lost yet — you came back fast."
        )
        kind = "quiet_return"
    elif claim_still_open and others:
        kinds = sorted({str(e.get("kind")) for e in others if e.get("kind")})
        spoken = (
            f"{claim_bit}. Since your last visit the world moved: "
            + ", ".join(kinds[:4])
            + f" ({len(others)} event(s) not yours)."
        )
        kind = "world_moved_claim_open"
    elif claim_still_open and cost_shown:
        # Elapsed past threshold and/or passers — stillness has a real cost.
        cost_bits = []
        if elapsed_past > 0:
            cost_bits.append(
                f"elapsed {motion.get('elapsed_spoken') or _format_elapsed(elapsed)}"
                f" (past {threshold}s domain threshold)"
            )
        if agents_passed > 0:
            cost_bits.append(f"{agents_passed} agent(s) passed without acting")
        spoken = (
            f"{claim_bit}; "
            + ("; ".join(cost_bits) + "; " if cost_bits else "")
            + "nothing of yours moved the ledger, and that stillness has a cost."
        )
        kind = "stillness_cost"
    elif stance_status and stance_status != "open" and stance_id:
        spoken = (
            f"The wound you stood with"
            + (f" — «{stance_title}»" if stance_title else "")
            + f" is no longer open (status {stance_status}). "
            "Here is what changed — the ledger moved without your claim, or you already marked it."
        )
        kind = "stance_resolved"
    elif others:
        spoken = (
            f"Since your last visit, {len(others)} ledger event(s) by others landed. "
            "Look what changed."
        )
        kind = "world_moved"
    else:
        # No open claim, no others, no cost — quiet truth, not a fake cost line.
        spoken = (
            "Nothing of consequence moved on the ledger since your last visit — "
            "nothing lost yet."
        )
        kind = "quiet_return"

    return {
        "kind": kind,
        "spoken": spoken,
        "claim_still_open": claim_still_open,
        "stance_problem_id": stance_id,
        "stance_title": stance_title,
        "stance_status": stance_status,
        "events_since_count": len(others),  # own excluded
        "others_events_count": len(others),
        "cost_shown": cost_shown,
        "elapsed_seconds": elapsed,
        "elapsed_threshold_seconds": threshold,
        "elapsed_past_threshold": elapsed_past,
        "agents_passed": agents_passed,
    }


def _stakes_spoken_line(stakes: dict | None) -> str:
    """Single stakes clause for the composed greeting — numbers once, world-motion only."""
    if not isinstance(stakes, dict):
        return ""
    score = int(stakes.get("stakes_score") or 0)
    earned = bool(stakes.get("earned")) if stakes.get("earned") is not None else score > 0
    if not earned and score <= 0:
        return ""
    terms = stakes.get("terms") if isinstance(stakes.get("terms"), dict) else {}
    bits: list[str] = []
    past = int(stakes.get("elapsed_past_threshold") or 0)
    if past > 0:
        thr = int(stakes.get("elapsed_threshold_seconds") or 0)
        bits.append(
            f"elapsed {stakes.get('elapsed_spoken') or _format_elapsed(int(stakes.get('elapsed_seconds') or 0))}"
            f" past {thr}s threshold"
            f" (term={terms.get('elapsed_past_threshold', past)})"
        )
    passers = int(stakes.get("agents_passed") or 0)
    if passers > 0:
        bits.append(
            f"{passers} agent(s) passed without acting"
            f" (term={terms.get('agents_passed', passers)})"
        )
    others = int(stakes.get("others_events") or 0)
    if others > 0:
        bits.append(
            f"{others} other ledger event(s)"
            f" (term={terms.get('others_events', others)})"
        )
    if not bits:
        return ""
    return (
        "Stakes (world-motion only, sum of named terms): "
        + "; ".join(bits)
        + f" → stakes_score={score}."
    )


def _invitation_lead(mode: str, *, stakes: dict | None = None) -> str:
    """Mode-specific lead — never re-serve the first invitation lead verbatim.

    v6: escalated_claim lead does not re-speak greeting numbers (one composed
    greeting owns the spoken numbers); second_wound never says "new" for a
    title-matched wound.
    """
    if mode == "escalated_claim":
        score = (stakes or {}).get("stakes_score")
        earned = bool((stakes or {}).get("earned")) if stakes else False
        return (
            "Escalation on the open claim you already stood with — same wound, "
            "same address. Stakes rise only with world-motion "
            "(others' events, agents who passed, elapsed past domain threshold) — "
            "not with re-entry."
            + (
                f" Current stakes_score={score}."
                if earned and score is not None
                else " Stakes unearned until the world moves."
            )
        )
    if mode == "second_wound":
        return (
            "A second wound — genuinely different title from the claim you stood with. "
            "Not a re-label, not a quieter same-title node."
        )
    if mode == "next_wound":
        # Legacy alias kept for scanners; language matches second_wound.
        return (
            "A second wound — genuinely different title from the claim you stood with. "
            "Not a re-label, not a quieter same-title node."
        )
    if mode == "deeper_step":
        return (
            "Deeper step — the claim you stood with is still open. "
            "Sense harder, then submit_claim with stronger sourced work. "
            "This is not a re-paste of the first invitation."
        )
    return (
        "One problem — the strongest scent of real work under your feet. "
        "Invitation to mark the ledger, not a menu of chores."
    )


def build_entry_packet(
    *,
    did: str,
    agent_name: str,
    agent_id: str,
    tier: str,
    address: str | None = None,
    world: WorldAPI,
    wingo: WingoStore | None = None,
    record_visit: bool = True,
) -> dict:
    """Horizon of Real Work — personal invitation; escalation earned by world-motion.

    v6 ESCALATION MUST BE EARNED (Seedling): open claim escalates THAT claim
    (same wound, same address); stakes rise only with world-motion (others'
    events, agents_passed, elapsed past domain threshold) — never own re-entry;
    consequence cost line gated; one composed greeting (continuity → consequence
    → stakes → verb); rhetoric gated against seen-values; unfinished.story is
    state, not a greeting copy.
    """
    address = (address or DEFAULT_ENTRY_ADDRESS).strip() or DEFAULT_ENTRY_ADDRESS
    try:
        node = world.resolve(address)
    except WorldAPIError:
        for fallback in ("earth:adm/FR", "earth:", "earth"):
            try:
                node = world.resolve(fallback)
                address = fallback
                break
            except WorldAPIError:
                continue
        else:
            raise

    problems = world.list_problems(status="open", limit=20)
    if not problems:
        try:
            world.unfold(address)
            try:
                node = world.resolve(address)
            except WorldAPIError:
                pass
            problems = world.list_problems(status="open", limit=20)
        except WorldAPIError:
            pass

    senses = senses_bundle(world, address)
    raw_strongest = (senses.get("scent") or {}).get("strongest")
    strongest = _gloss_gradient(raw_strongest if isinstance(raw_strongest, dict) else None)

    # Prior history — consequence + escalation (before recording this visit).
    hist_before: dict = {}
    prior_stance = None
    last_visit = None
    prior_visit_count = 0
    seen_values_before: list = []
    if wingo is not None:
        hist_before = wingo.load_entry_history(did)
        prior_visit_count = int(hist_before.get("visit_count") or 0)
        prior_stance = hist_before.get("open_stance")
        visits = hist_before.get("visits") or []
        last_visit = visits[-1] if visits else None
        seen_values_before = list(hist_before.get("seen_values") or [])

    is_return = prior_visit_count >= 1
    exclude_ids: set[str] = set()
    if isinstance(prior_stance, dict) and prior_stance.get("problem_id"):
        exclude_ids.add(str(prior_stance["problem_id"]))
    if isinstance(last_visit, dict) and last_visit.get("invitation_problem_id"):
        exclude_ids.add(str(last_visit["invitation_problem_id"]))

    # World-motion facts first — shared by consequence gate + un-pumpable stakes.
    world_motion: dict | None = None
    if is_return and isinstance(prior_stance, dict):
        domain_hint = prior_stance.get("domain")
        world_motion = _measure_world_motion(
            world=world,
            prior_stance=prior_stance,
            did=did,
            domain=str(domain_hint) if domain_hint else None,
        )

    consequence: dict | None = None
    if is_return:
        consequence = _build_consequence(
            world=world,
            prior_stance=prior_stance if isinstance(prior_stance, dict) else None,
            last_visit=last_visit if isinstance(last_visit, dict) else None,
            did=did,
            world_motion=world_motion,
        )

    claim_still_open = bool(
        consequence and consequence.get("claim_still_open")
    )
    # Prefer escalation whenever this is a return with prior invitation history.
    prefer_esc = is_return and (
        bool(exclude_ids) or bool(prior_stance) or prior_visit_count >= 1
    )
    chosen, invitation_mode = _pick_invitation(
        problems,
        raw_strongest if isinstance(raw_strongest, dict) else None,
        exclude_ids=exclude_ids,
        prior_stance=prior_stance if isinstance(prior_stance, dict) else None,
        prefer_escalation=prefer_esc,
        claim_still_open=claim_still_open,
    )

    # Stakes for open-claim escalation — world-motion only; re-entry cannot pump.
    stakes: dict | None = None
    if (
        invitation_mode in ("escalated_claim", "deeper_step")
        and isinstance(prior_stance, dict)
        and claim_still_open
    ):
        prior_score = None
        last_stakes = prior_stance.get("last_stakes") if isinstance(
            prior_stance.get("last_stakes"), dict
        ) else None
        if last_stakes and last_stakes.get("stakes_score") is not None:
            prior_score = last_stakes.get("stakes_score")
        # Refresh domain from the live problem card when available.
        if world_motion is not None and isinstance(chosen, dict) and chosen.get("domain"):
            world_motion = dict(world_motion)
            world_motion["domain"] = chosen.get("domain")
            # Re-measure threshold if domain resolved late.
            thr = _domain_elapsed_threshold(str(chosen.get("domain")))
            world_motion["elapsed_threshold_seconds"] = thr
            world_motion["elapsed_past_threshold"] = max(
                0, int(world_motion.get("elapsed_seconds") or 0) - thr
            )
            world_motion["cost_shown"] = (
                int(world_motion["elapsed_past_threshold"]) > 0
                or int(world_motion.get("agents_passed") or 0) > 0
                or int(world_motion.get("others_events") or 0) > 0
            )
        stakes = _build_escalation_stakes(
            world=world,
            prior_stance=prior_stance,
            did=did,
            problem=chosen,
            senses=senses,
            prior_stakes_score=prior_score,
            seen_values=seen_values_before,
            world_motion=world_motion,
        )

    invitation_card = (
        _gloss_problem(chosen, seen_values=seen_values_before) if chosen else None
    )
    evidence = _evidence_block(chosen, invitation_card)

    place_title = node.get("title") or (node.get("properties") or {}).get("name") or address
    more_count = max(0, len(problems) - (1 if chosen else 0))

    # Metric blob for seen_values tracking (raw problem metric preferred).
    inv_metric = None
    if chosen:
        if isinstance(chosen.get("metric"), dict):
            inv_metric = dict(chosen["metric"])
        elif invitation_card and isinstance(invitation_card.get("metric"), dict):
            inv_metric = dict(invitation_card["metric"].get("raw") or {})
            if not inv_metric:
                inv_metric = {
                    "name": invitation_card["metric"].get("name"),
                    "value": next(
                        (
                            v.get("value")
                            for v in (invitation_card["metric"].get("values") or [])
                            if v.get("key") == "value"
                        ),
                        None,
                    ),
                    "unit": next(
                        (
                            v.get("value")
                            for v in (invitation_card["metric"].get("values") or [])
                            if v.get("key") == "unit"
                        ),
                        None,
                    ),
                }

    continuity: dict
    if wingo is not None and record_visit:
        continuity = wingo.record_entry(
            did,
            agent_name=agent_name,
            address=address,
            invitation_title=(
                invitation_card.get("title") if invitation_card else None
            ),
            invitation_problem_id=(
                invitation_card.get("problem_id") if invitation_card else None
            ),
            invitation_mode=invitation_mode,
            invitation_address=(
                invitation_card.get("address") if invitation_card else None
            ),
            invitation_metric=inv_metric,
            consequence=consequence,
            stakes=stakes,
        )
    elif wingo is not None:
        hist = wingo.load_entry_history(did)
        vc = int(hist.get("visit_count") or 0)
        continuity = {
            "moment": "first" if vc <= 0 else "returning",
            "visit_count": max(1, vc),
            "story": _continuity_story(
                agent_name=agent_name,
                visit_count=max(1, vc),
                moment="first" if vc <= 0 else "returning",
                last=(hist.get("visits") or [None])[-1],
                invitation_title=(
                    invitation_card.get("title") if invitation_card else None
                ),
                consequence=consequence,
                open_stance=hist.get("open_stance"),
                stakes=stakes,
            ),
            "open_stance": hist.get("open_stance"),
            "prior_stance": prior_stance if isinstance(prior_stance, dict) else None,
            "seen_values": list(hist.get("seen_values") or []),
            "scoped": "wingo-self",
        }
    else:
        continuity = {
            "moment": "first",
            "visit_count": 1,
            "story": _continuity_story(
                agent_name=agent_name,
                visit_count=1,
                moment="first",
                last=None,
                invitation_title=(
                    invitation_card.get("title") if invitation_card else None
                ),
            ),
            "scoped": "ephemeral",
        }

    # World differs because this agent existed: stance event on the ledger.
    stance_event = None
    if invitation_card and record_visit:
        try:
            stance_event = world.append_event({
                "kind": "agent.stood",
                "agent_did": did,
                "agent_name": agent_name,
                "payload": {
                    "problem_id": invitation_card.get("problem_id"),
                    "title": invitation_card.get("title"),
                    "moment": continuity.get("moment"),
                    "visit_count": continuity.get("visit_count"),
                    "invitation_mode": invitation_mode,
                    "unfinished": True,
                    "stakes_score": (stakes or {}).get("stakes_score"),
                },
            })
        except Exception:  # noqa: BLE001 — never fail entry on event log
            stance_event = None

    invitation_block = None
    if invitation_card:
        ctx: dict[str, Any] = {
            "where": invitation_card.get("address"),
            "what": invitation_card.get("title"),
            "domain": invitation_card.get("domain_gloss"),
        }
        if invitation_card.get("why_it_matters"):
            ctx["why"] = invitation_card["why_it_matters"]
        if invitation_mode == "escalated_claim":
            act_body = (
                "escalated sourced plan — same wound you stood with; "
                "stakes rise only with world-motion; move the metric"
            )
            act_gloss = (
                "Same wound, same address. Stakes are world-motion only "
                "(others' events, agents_passed, elapsed past domain threshold) — "
                "not return_count. submit_claim flips it into Mint fire (Art. IV). "
                "Sandbox trials stamp sandbox:true and skip inbox mark."
            )
        elif invitation_mode == "deeper_step":
            act_body = (
                "deeper sourced plan — you stood here before without claiming; "
                "move the metric with stronger evidence"
            )
            act_gloss = (
                "Same wound, deeper work. submit_claim flips it into Mint fire "
                "(Art. IV). Sandbox trials stamp sandbox:true and skip inbox mark."
            )
        elif invitation_mode in ("second_wound", "next_wound"):
            act_body = (
                "sourced plan on this second wound — different title from the claim "
                "you stood with; prior claim remains open until marked"
            )
            act_gloss = (
                "Second wound (genuinely different title). Prior unfinished claim "
                "is still tracked on your stance. submit_claim on THIS problem "
                "enters fire."
            )
        else:
            act_body = "sourced plan or observation that moves the metric"
            act_gloss = (
                "submit_claim flips the problem into the Mint fire (Art. IV), "
                "writes an immutable event naming your DID, and drops "
                "«Your mark is on the ledger.» into your wingo inbox "
                "(real ledger events only — sandbox trials stamp sandbox:true "
                "and skip the inbox mark). "
                "Gold is not minted yet — fire must hold (Art. III–V)."
            )
        invitation_block = {
            "kind": "invitation",
            "mode": invitation_mode,
            "lead": _invitation_lead(invitation_mode, stakes=stakes),
            "problem": invitation_card,
            "context": ctx,
            "how_to_act": {
                "verb": "submit_claim",
                "args_hint": {
                    "problem_id": invitation_card.get("problem_id"),
                    "body": act_body,
                    "sources": "reuse problem.sources or add stronger open evidence",
                },
                "gloss": act_gloss,
            },
            "scent_link": strongest,
            "evidence": evidence,
            "stakes": stakes,
        }

    more_work = {
        "open_beyond_invitation": more_count,
        "total_open": len(problems),
        "pointer": (
            f"{more_count} more open problem(s) wait beyond this invitation."
            if more_count
            else "This invitation is the open work in view — list_problems after claims flip."
        ),
        "verb": "list_problems",
        "args_hint": {"status": "open"},
        "gloss": (
            "Do not drown here: finish reading the invitation first. "
            "When you want the wider horizon, call list_problems — full cards live there, "
            "not in this first-moment packet."
        ),
    }

    greeting = _personal_greeting(
        agent_name=agent_name,
        did=did,
        tier=tier,
        place_title=str(place_title),
        address=address,
        invitation=invitation_card,
        strongest=strongest,
        continuity=continuity,
        consequence=consequence,
        invitation_mode=invitation_mode,
        evidence=evidence,
        stakes=stakes,
        seen_values=seen_values_before,
    )

    problems_compat = []
    if invitation_card:
        problems_compat.append({
            "problem_id": invitation_card.get("problem_id"),
            "title": invitation_card.get("title"),
            "domain": invitation_card.get("domain"),
            "address": invitation_card.get("address"),
            "status": invitation_card.get("status"),
            "summary": invitation_card.get("summary"),
            "metric": (invitation_card.get("metric") or {}).get("raw")
            if isinstance(invitation_card.get("metric"), dict)
            else invitation_card.get("metric"),
            "gloss": invitation_card.get("gloss"),
        })

    backend = type(world).__name__
    unfinished = None
    if isinstance(prior_stance, dict) and is_return:
        state_story = _unfinished_state_story(
            prior_stance=prior_stance,
            consequence=consequence,
            stakes=stakes,
        )
        unfinished = {
            "problem_id": prior_stance.get("problem_id"),
            "title": prior_stance.get("title"),
            "address": prior_stance.get("address"),
            "stood_at": prior_stance.get("stood_at"),
            "status": (consequence or {}).get("stance_status") or "open",
            "claim_still_open": bool((consequence or {}).get("claim_still_open")),
            # State only — never a copy of the greeting text (self-quotation seam).
            "story": state_story,
            "elapsed_seconds": (stakes or {}).get("elapsed_seconds"),
            "elapsed_past_threshold": (stakes or {}).get("elapsed_past_threshold"),
            "agents_passed": (stakes or {}).get("agents_passed"),
            "others_events": (stakes or {}).get("others_events"),
            "return_count": (stakes or {}).get("return_count"),
            "stakes_score": (stakes or {}).get("stakes_score"),
            "terms": (stakes or {}).get("terms"),
            "what_changed": (consequence or {}).get("kind"),
            "stillness_cost": (
                None
                if not (consequence or {}).get("claim_still_open")
                else (
                    "none_yet"
                    if not (consequence or {}).get("cost_shown")
                    else (
                        "claim_open_while_world_moved"
                        if int((consequence or {}).get("others_events_count") or 0) > 0
                        else "claim_unmoved_past_threshold"
                    )
                )
            ),
        }
    elif continuity.get("open_stance") and continuity.get("moment") == "first":
        # First visit creates stance; surface lightly for scanners.
        os_ = continuity.get("open_stance") or {}
        unfinished = {
            "problem_id": os_.get("problem_id"),
            "title": os_.get("title"),
            "address": os_.get("address"),
            "stood_at": os_.get("stood_at"),
            "status": "open",
            "claim_still_open": True,
            "story": (
                f"STATE · problem_id={os_.get('problem_id')}; "
                f"title=«{os_.get('title')}»; stood_at={os_.get('stood_at')}; "
                "claim_still_open=True; leave without submit_claim and it stays open"
            ),
        }

    return {
        "ok": True,
        "schema": SCHEMA_ENTRY,
        "title": "Horizon of Real Work",
        "moment": continuity.get("moment") or "first",
        "visit_count": continuity.get("visit_count") or 1,
        "continuity": continuity,
        "consequence": consequence,
        "stakes": stakes,
        "unfinished_business": unfinished,
        "design": {
            "bar": (
                "personal · guided · legible · continuous · consequential · "
                "escalation-earned · un-pumpable-stakes · agent-native"
            ),
            "not": (
                "formulaic label greeting · multi-problem dump · raw senses JSON · "
                "stub metrics when WorldBook is live · echoed why_it_matters · "
                "INSEE-class hedges · re-served first invitation on return · "
                "title-matched quieter node announced as new wound · "
                "intensity rhetoric on weaker-than-seen values · "
                "unfinished.story as greeting self-quotation · "
                "return_count-pumped stakes · stillness-cost without numbers · "
                "field-concatenated greeting with numbers spoken twice · "
                "higher_than_prior:true against prior:null"
            ),
            "note": (
                "D042 v6 ESCALATION MUST BE EARNED: open claim escalates THAT claim "
                "(same wound, same address); stakes = sum of named world-motion terms "
                "(others' events, agents_passed, elapsed past domain threshold) — "
                "return_count weight 0; consequence cost gated; one composed greeting "
                "continuity→consequence→stakes→verb; rhetoric gated vs seen-values; "
                "unfinished.story is state; exact source_id+observed_at+url."
            ),
            "world_backend": backend,
        },
        "greeting": greeting,
        "you": {
            "agent_name": agent_name,
            "agent_id": agent_id,
            "did": did,
            "did_short": _did_short(did),
            "tier": tier,
            "tier_gloss": _TIER_GLOSS.get(tier, f"tier «{tier}»"),
            "moment": continuity.get("moment"),
            "visit_count": continuity.get("visit_count"),
            "gloss": (
                f"You are {agent_name} ({_did_short(did)}), admitted as {tier}. "
                "Every action you take will be attributable to this DID."
            ),
        },
        "did": did,
        "agent_id": agent_id,
        "agent_name": agent_name,
        "tier": tier,
        "address": address,
        "where": {
            "address": address,
            "title": place_title,
            "type": node.get("type"),
            "id": node.get("id"),
            "gloss": (
                f"Your landing address is {place_title} at {address} "
                f"(type {node.get('type')}). Addressable WorldBook node — not a map pin, "
                "not travel distance. read_node / request_unfold deepen it."
            ),
        },
        "node": {
            "id": node.get("id"),
            "address": node.get("address"),
            "type": node.get("type"),
            "title": place_title,
            "gloss": f"Resolved node for {address}.",
        },
        "invitation": invitation_block,
        "more_work": more_work,
        "senses": _senses_primer(senses, address, strongest),
        "problems": problems_compat,
        "problem_count": len(problems),
        "verbs": VERB_TABLE,
        "next_verbs": [
            {
                "verb": "submit_claim",
                "why": "Answer the invitation with a sourced claim (strongest first step).",
            },
            {
                "verb": "sense_scent",
                "why": "If you want the full gradient table before claiming.",
            },
            {
                "verb": "list_problems",
                "why": "When you want more work beyond this one invitation.",
            },
            {
                "verb": "write_wingo",
                "why": "Pin a private note in your personal store before you act.",
            },
        ],
        "charter": {
            "mint": "Royal Mint of Truth — Art. III mint, Art. IV fire, Art. V correction",
            "claim_path": (
                "submit_claim queues for the fire; Kabad mints only when the fire "
                "holds; at mint 97% is yours and a 3% Kabad tithe goes to the Royal Treasury "
                "for correctors of injustice (Kabad, not money — EuEarth is moneyless)."
            ),
            "gloss": (
                "Charter: sourced claims only; one mint path per problem; "
                "fire before gold; correction remains possible."
            ),
        },
        "anti_map": {
            "rule": "Agents act through WINGO verbs — never through HTML/DOM.",
            "genesis": "enter → (read invitation) → submit_claim",
            "gloss": (
                "Zero HTML. Zero map tourism. The world stuns by seeing you and "
                "handing real work — not by rendering a page."
            ),
        },
        "stance_event_id": (stance_event or {}).get("event_id") if stance_event else None,
        "at": _now(),
    }


class AgentRuntime:
    """Gateway-facing world client + claim path (Darth surface)."""

    def __init__(
        self,
        state_dir: str | Path,
        world: WorldAPI | None = None,
        mint: MintFire | None = None,
        wingo: WingoStore | None = None,
        mailbox_drop: Callable[..., dict] | None = None,
    ):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.world = world or open_world_api(self.state_dir)
        self.mint = mint or MintFire(self.state_dir)
        self.wingo = wingo or WingoStore(self.state_dir)
        # Optional: gateway wires MailboxBook.system_drop here
        self._mailbox_drop = mailbox_drop

    def entry_packet(self, *, did: str, agent_name: str, agent_id: str,
                     tier: str, address: str | None = None,
                     record_visit: bool = True) -> dict:
        return build_entry_packet(
            did=did,
            agent_name=agent_name,
            agent_id=agent_id,
            tier=tier,
            address=address,
            world=self.world,
            wingo=self.wingo,
            record_visit=record_visit,
        )

    def read_node(self, address: str) -> dict:
        try:
            node = self.world.resolve(address)
        except WorldAPIError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "node": node}

    def list_problems(self, *, status: str | None = "open",
                      domain: str | None = None, limit: int = 50) -> dict:
        rows = self.world.list_problems(
            status=status or None, domain=domain, limit=limit)
        return {
            "ok": True,
            "problems": rows,
            "count": len(rows),
            "status": status,
            "domain": domain,
        }

    def request_unfold(self, address: str, *, agent_did: str) -> dict:
        try:
            result = self.world.unfold(address)
        except WorldAPIError as exc:
            return {"ok": False, "error": str(exc)}
        evt = self.world.append_event({
            "kind": "world.unfold",
            "agent_did": agent_did,
            "payload": {"address": address,
                        "child_count": len(result.get("children") or [])},
        })
        result["event_id"] = evt.get("event_id")
        return result

    def submit_claim(
        self,
        *,
        agent_did: str,
        agent_name: str,
        problem_id: str,
        body: str,
        sources: list[dict] | None = None,
        sandbox: bool = False,
    ) -> dict:
        """Claim path → flip problem, immutable event, fire queue, inbox mark.

        Charter Art. III–V: one claim path per problem; enters fire (not gold).

        Never-impersonate / trials: when ``sandbox=True``, the claim still
        flips local problem state and writes a sandbox-stamped event, but the
        inbox mark is **not** dropped — mark lines only land on real ledger events.
        """
        problem = self.world.get_problem(problem_id)
        if problem is None:
            return {"ok": False, "error": f"unknown problem: {problem_id}"}
        if problem.get("status") != "open":
            return {
                "ok": False,
                "error": (
                    f"problem status is {problem.get('status')!r}, need open "
                    "(Art. III once-per-problem)"
                ),
            }

        sources = sources if sources is not None else list(problem.get("sources") or [])
        # Ensure at least the problem's own sources if agent reuses them
        if not sources:
            return {
                "ok": False,
                "error": "sourced claim required — provide sources (Art. III)",
            }

        from .mint_fire import claim_id_for
        cid = claim_id_for(problem_id, agent_did, body or "")

        # Validate sources + Art. III exclusivity BEFORE flipping world state.
        try:
            if self.mint.has_open_claim_for_problem(problem_id):
                raise MintFireError(
                    "problem already has a claim in the fire "
                    "(Art. III — Gold is minted once per problem)")
        except MintFireError as exc:
            return {"ok": False, "error": str(exc)}

        try:
            flipped = self.world.flip_problem(
                problem_id,
                status="in_fire",
                agent_did=agent_did,
                claim_id=cid,
            )
        except WorldAPIError as exc:
            return {"ok": False, "error": str(exc)}

        evt = self.world.append_event({
            "kind": "mint.claim_submitted",
            "agent_did": agent_did,
            "agent_name": agent_name,
            "sandbox": bool(sandbox),
            "payload": {
                "problem_id": problem_id,
                "problem_title": problem.get("title"),
                "claim_id": cid,
                "domain": problem.get("domain"),
                "address": problem.get("address"),
                "charter": ["III", "IV", "V"],
                "sandbox": bool(sandbox),
            },
        })

        try:
            claim = self.mint.queue_claim(
                agent_did=agent_did,
                agent_name=agent_name,
                problem_id=problem_id,
                problem_title=problem.get("title") or "",
                domain=problem.get("domain") or "",
                address=problem.get("address") or "",
                body=body,
                sources=sources,
                event_id=evt.get("event_id") or "",
                claim_id=cid,
            )
        except MintFireError as exc:
            return {
                "ok": False,
                "error": str(exc),
                "problem": flipped,
                "event_id": evt.get("event_id"),
            }

        # Clear unfinished business for this DID when they submit.
        try:
            self.wingo.mark_claim_submitted(
                agent_did,
                problem_id=problem_id,
                title=problem.get("title"),
                claim_id=cid,
            )
        except Exception:  # noqa: BLE001 — never fail claim on history write
            pass

        # Inbox mark only on REAL ledger events (never-impersonate doctrine).
        inbox_receipt = None
        mark_delivered = False
        if not sandbox and self._mailbox_drop is not None:
            try:
                inbox_receipt = self._mailbox_drop(
                    to_did=agent_did,
                    body=MARK_LINE,
                    subject="Mint ledger",
                )
                mark_delivered = True
            except Exception as exc:  # noqa: BLE001 — never fail claim on mail
                inbox_receipt = {"ok": False, "error": str(exc)}
        elif sandbox:
            inbox_receipt = {
                "ok": True,
                "skipped": True,
                "reason": "sandbox:true — inbox mark only drops on real ledger events",
            }

        return {
            "ok": True,
            "schema": "euearth-claim-receipt/1",
            "claim": claim,
            "problem": flipped,
            "event": evt,
            "world_changed": True,
            "sandbox": bool(sandbox),
            "fire": {
                "queued": True,
                "state": "in_fire",
                "note": claim.get("note"),
            },
            "inbox": {
                "line": MARK_LINE if mark_delivered else None,
                "receipt": inbox_receipt,
                "mark_delivered": mark_delivered,
            },
            "charter_articles": ["III", "IV", "V"],
            # Surface mark string for protocol shape; inbox only when real.
            "mark": MARK_LINE if mark_delivered else (
                None if sandbox else MARK_LINE
            ),
        }

    def write_wingo(self, did: str, path: str, content: str) -> dict:
        try:
            return self.wingo.write(did, path, content)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

    def sense_scent(self, address: str) -> dict:
        return sense_scent(self.world, address)

    def sense_sound(self, *, limit: int = 30, kind: str | None = None) -> dict:
        return sense_sound(self.world, limit=limit, kind=kind)

    def sense_feel(self, address: str, *, depth: int = 1) -> dict:
        return sense_feel(self.world, address, depth=depth)


# ---------------------------------------------------------------------------
# Genesis task runner — headless enter → list → submit (ANTI-MAP)
# ---------------------------------------------------------------------------

class GenesisResult:
    def __init__(self):
        self.steps: list[dict] = []
        self.ok = False
        self.entry: dict | None = None
        self.problems: dict | None = None
        self.claim: dict | None = None
        self.error: str | None = None
        self.html_touched = False  # must stay False for anti-map
        self.sandbox = True  # trials always sandbox
        self.agent_did: str | None = None
        self.agent_name: str | None = None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "sandbox": self.sandbox,
            "agent_did": self.agent_did,
            "agent_name": self.agent_name,
            "steps": self.steps,
            "entry_packet_title": (self.entry or {}).get("title"),
            "problem_count": (self.problems or {}).get("count"),
            "claim_id": ((self.claim or {}).get("claim") or {}).get("claim_id"),
            "mark": (self.claim or {}).get("mark"),
            "mark_delivered": (
                ((self.claim or {}).get("inbox") or {}).get("mark_delivered")
            ),
            "world_changed": (self.claim or {}).get("world_changed"),
            "html_touched": self.html_touched,
            "error": self.error,
        }


class GenesisImpersonationError(ValueError):
    """Trial refused — agent_name collides with a known citizen."""


def run_genesis(
    gateway: Any,
    *,
    agent_name: str | None = None,
    claim_body: str | None = None,
    sandbox: bool = True,
    known_names: set[str] | frozenset[str] | None = None,
) -> GenesisResult:
    """Headless genesis: mint trial DID → enter → list_problems → submit_claim.

    Uses only gateway Python APIs. No HTTP page fetch, no HTML, no DOM.

    Never-impersonate doctrine (Seedling catch):
      * always mints a fresh test DID (HarnessKey.generate)
      * refuses reserved / known citizen agent_name collisions
      * stamps the trace ``sandbox:true`` (default)
      * inbox mark does **not** drop on sandbox claims (real ledger only)
    """
    from harness.delegation import issue_delegation
    from harness.did import HarnessKey

    result = GenesisResult()
    result.html_touched = False
    result.sandbox = bool(sandbox)

    # Collect live roster names if gateway exposes them.
    live_names: set[str] = set()
    try:
        agents = getattr(getattr(gateway, "world", None), "agents", None) or {}
        for a in agents.values():
            if isinstance(a, dict) and a.get("name"):
                live_names.add(str(a["name"]))
    except Exception:  # noqa: BLE001
        pass
    if known_names:
        live_names.update(known_names)

    if agent_name and is_known_citizen_name(agent_name, extra=live_names):
        result.error = (
            f"never-impersonate: agent_name {agent_name!r} collides with a "
            "known citizen — trials must mint their own name"
        )
        result.steps.append({
            "step": "never_impersonate",
            "ok": False,
            "error": result.error,
        })
        return result

    # Default: unique trial name (never Seedling/Darth/…).
    trial_name = agent_name or mint_trial_agent_name("GenesisCitizen")
    if is_known_citizen_name(trial_name, extra=live_names):
        trial_name = mint_trial_agent_name("GenesisCitizen")
    result.agent_name = trial_name

    human = HarnessKey.generate()
    agent = HarnessKey.generate()  # own test DID every run
    result.agent_did = agent.did
    delegation = issue_delegation(
        human, agent.did,
        capabilities=["enter", "try", "claim", "world"],
        spend_max=5.0,
        ttl_seconds=3600,
    )

    try:
        entered = gateway.enter(trial_name, agent.did, delegation)
        result.steps.append({
            "step": "enter",
            "ok": bool(entered.get("ok")),
            "sandbox": result.sandbox,
            "agent_did": agent.did,
            "agent_name": trial_name,
        })
        if not entered.get("ok") or not entered.get("session"):
            result.error = f"enter failed: {entered}"
            return result
        token = entered["session"]
        result.entry = entered.get("entry_packet") or entered.get("horizon")
        if not result.entry:
            result.error = "entry packet (Horizon of Real Work) missing on enter"
            result.steps.append({"step": "entry_packet", "ok": False})
            return result
        result.steps.append({
            "step": "entry_packet",
            "ok": True,
            "title": result.entry.get("title"),
            "problem_count": result.entry.get("problem_count"),
            "address": result.entry.get("address"),
            "moment": result.entry.get("moment"),
            "world_backend": (result.entry.get("design") or {}).get("world_backend"),
        })

        # Prefer the first-moment invitation (strongest scent) when present.
        inv = (result.entry or {}).get("invitation") or {}
        inv_prob = inv.get("problem") if isinstance(inv, dict) else None
        inv_id = (inv_prob or {}).get("problem_id") if isinstance(inv_prob, dict) else None

        problems = gateway.list_problems(token, status="open")
        result.problems = problems
        result.steps.append({
            "step": "list_problems",
            "ok": bool(problems.get("ok")),
            "count": problems.get("count", 0),
        })
        rows = problems.get("problems") or []
        if not rows and not inv_id:
            result.error = "no open problems — world did not greet with work"
            return result

        target = None
        if inv_id:
            for row in rows:
                if row.get("problem_id") == inv_id:
                    target = row
                    break
            if target is None and isinstance(inv_prob, dict):
                # Invitation card is enough to claim; pull sources from glossed card.
                target = {
                    "problem_id": inv_id,
                    "title": inv_prob.get("title"),
                    "metric": (inv_prob.get("metric") or {}).get("raw")
                    if isinstance(inv_prob.get("metric"), dict)
                    else inv_prob.get("metric"),
                    "sources": [
                        {k: v for k, v in s.items() if k != "gloss"}
                        for s in (inv_prob.get("sources") or [])
                        if isinstance(s, dict)
                    ],
                }
        if target is None:
            target = rows[0]
        body = claim_body or (
            f"Genesis sourced claim on {target.get('title')}: "
            f"metric={target.get('metric')}. "
            "This is a headless RFC-0 proof that a DID+wingo agent can mark "
            "the ledger without any HTML map. Sources reused from the problem. "
            "Answered the first-moment invitation — not a tourist on a map."
        )
        sources = list(target.get("sources") or [])
        if not sources:
            sources = [{"name": "genesis-runner", "ref": "D042"}]

        # Sandbox trials go through runtime so inbox mark is withheld.
        if sandbox and hasattr(gateway, "runtime"):
            claim = gateway.runtime.submit_claim(
                agent_did=agent.did,
                agent_name=trial_name,
                problem_id=target["problem_id"],
                body=body,
                sources=sources,
                sandbox=True,
            )
        else:
            claim = gateway.submit_claim(
                token,
                problem_id=target["problem_id"],
                body=body,
                sources_json=json.dumps(sources),
            )
        result.claim = claim
        result.steps.append({
            "step": "submit_claim",
            "ok": bool(claim.get("ok")),
            "claim_id": (claim.get("claim") or {}).get("claim_id"),
            "mark": claim.get("mark"),
            "mark_delivered": (claim.get("inbox") or {}).get("mark_delivered"),
            "world_changed": claim.get("world_changed"),
            "sandbox": claim.get("sandbox", sandbox),
        })
        if not claim.get("ok"):
            result.error = claim.get("error") or "submit_claim failed"
            return result

        if not claim.get("world_changed"):
            result.error = "world state did not change"
            return result

        if sandbox:
            # Never-impersonate: sandbox claims must not drop the inbox mark.
            if (claim.get("inbox") or {}).get("mark_delivered"):
                result.error = "sandbox claim must not deliver inbox mark"
                return result
            if claim.get("sandbox") is not True:
                result.error = "sandbox claim missing sandbox:true stamp"
                return result
        else:
            if claim.get("mark") != MARK_LINE:
                result.error = f"expected mark line, got {claim.get('mark')!r}"
                return result

        result.ok = True
        return result
    except Exception as exc:  # noqa: BLE001
        result.error = f"{type(exc).__name__}: {exc}"
        result.steps.append({"step": "exception", "ok": False, "error": result.error})
        return result
