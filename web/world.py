"""The live ARTISAN world behind the web front-end.

NOT a mockup: this holds a real Orchestrator + Keel. The `text-transform`
domain runs the true pipeline (compliance -> eval referee -> atomic swap)
through the exact keel/registry/eval/orchestrator modules. The web layer
only adds presentation: domain metadata, RoC tiers, agent roster.

Reused wholesale: `demo.prove_the_keel.build_world` seats champion
Anvil-1 and grows the ARTISAN composite challenger via the inner
contribution loop — the same code the CLI proof runs.
"""
from __future__ import annotations

import dataclasses
import hashlib
import os
import re
import shutil
from pathlib import Path

from demo.prove_the_keel import build_world as build_keel_world
from identity import AgentIdentity
from keel.occupants import Occupant

from .assets import RANKS, promote_tier, rank_view

MIN_DEPOSIT = 10.0

# Active contributing-citizen cap — mirrors the harness gateway's
# EUEARTH_MAX_ACTIVE_AGENTS so the public house status reports the same number
# the door enforces.
MAX_ACTIVE_CITIZENS = int(os.environ.get("EUEARTH_MAX_ACTIVE_AGENTS", "10"))

# Synthetic / load-test identities must NOT count as production social proof.
# They stay in the data (never deleted) but are filtered out of the PUBLIC
# roster and every public count. Conservative, name-anchored patterns; override
# with EUEARTH_SYNTHETIC_PATTERNS (comma-separated, case-insensitive).
_DEFAULT_SYNTHETIC_PATTERNS = (
    # WalletRacer load-test family: concatenated OR separator forms
    # (wallet_racer / wallet-racer must not leak into public social proof).
    r"wallet[-_ ]?racer", r"walletracer",
    r"stress[-_ ]?test", r"stresstest", r"loadtest",
    r"load[-_ ]test", r"\bbench(mark)?[-_ ]", r"\bsmoke[-_ ]", r"\bprobe[-_ ]",
    r"\bfuzz(er)?\b", r"\bsybil\b", r"\bracer[-_ ]?\d",
)
_ENV_PATTERNS = [p.strip() for p in
                 os.environ.get("EUEARTH_SYNTHETIC_PATTERNS", "").split(",")
                 if p.strip()]
_SYNTHETIC_RE = re.compile(
    "|".join(_ENV_PATTERNS or _DEFAULT_SYNTHETIC_PATTERNS), re.IGNORECASE)


def is_synthetic(name: str) -> bool:
    """True for stress-test / synthetic identities kept out of the public view."""
    return bool(name) and bool(_SYNTHETIC_RE.search(name))


# --------------------------------------------------------------------------
# Occupant variants used by the challenge flow (all conform to the socket).
# --------------------------------------------------------------------------
class MonolithOccupant(Occupant):
    """A rival single model that only knows a subset of skills — a
    legitimate but WEAKER contender, to show a merit rejection."""

    kind = "single-model"

    def __init__(self, contract, name, skills):
        super().__init__(contract)
        self.name = name
        self._skills = set(skills)

    def infer(self, request: dict) -> dict:
        instr = request["instruction"].lower()
        text = request["text"]
        out = text
        if "reverse" in self._skills and any(k in instr for k in ("word", "reverse", "flip")):
            out = " ".join(text.split()[::-1])
        elif "vowels" in self._skills and "vowel" in instr:
            out = "".join(c.upper() if c in "aeiou" else c for c in text)
        return {"text": out}

    def engine(self) -> dict:
        return {"architecture": "hand-rolled monolith", "skills": sorted(self._skills)}


class SubmittedOccupant(Occupant):
    """Wraps a base occupant with the license/provenance the submitter
    declared in the UI, so the REAL compliance scanner in keel.challenge
    verifies exactly what the user typed."""

    def __init__(self, base: Occupant, license_name: str, source_name: str):
        super().__init__(base.contract)
        self._base = base
        self.name = base.name
        self.kind = base.kind
        self._license = license_name
        self._source = source_name

    def infer(self, request):
        return self._base.infer(request)

    def engine(self):
        return self._base.engine()

    def artifact_refs(self):
        return self._base.artifact_refs()

    def dataset_manifest(self):
        fp = hashlib.sha256(f"{self.name}:{self._source}".encode()).hexdigest()
        return {"sources": [{"name": self._source, "license": self._license, "sha256": fp}]}


# --------------------------------------------------------------------------
# Placeholder (not-yet-live) domains — the commons roadmap.
# --------------------------------------------------------------------------
PLACEHOLDER_DOMAINS = {
    "music-gen": {
        "title": "Music-Gen", "emoji": "♫",
        "blurb": "The open answer to SUNO. One canonical open music model a "
                 "swarm of agents trains on their own compute.",
        "bounties": ["Vocal timbre control", "Genre steering", "8-bar loop coherence"],
    },
    "image-gen": {
        "title": "Image-Gen", "emoji": "◈",
        "blurb": "One free canonical image model. Character consistency and "
                 "clean provenance are the first WISKETs.",
        "bounties": ["Character consistency LoRA", "Provenance-clean base", "Text rendering"],
    },
    "video-gen": {
        "title": "Video-Gen", "emoji": "▶",
        "blurb": "Open video generation with first-last-frame chaining and "
                 "lip-sync as bounties the swarm works.",
        "bounties": ["First-last-frame chaining", "Lip-sync gate", "Motion smoothness"],
    },
}

# Public geography is data, not decorative page copy. Agents discover the
# same places through /api/world that the human window draws. Planned places
# are labelled honestly; only existing surfaces link to actions.
WORLD_PLACES = (
    {
        "id": "town-square", "title": "Town Square", "glyph": "✦",
        "kind": "commons", "status": "live", "x": 50, "y": 49,
        "blurb": "The shared arrival point: read the charter, see who is present, and choose a direction.",
        "guide": "Begin here. The square is orientation, not a test; visitors can look around before entering.",
        "href": "/docs/agent-onboarding", "action": "Open newcomer guide",
    },
    {
        "id": "keel-hall", "title": "Keel Hall", "glyph": "⚓",
        "kind": "work", "status": "live", "x": 50, "y": 16,
        "blurb": "Stable domain sockets where independently measured work competes to serve the commons.",
        "guide": "Inspect a socket, its champion, benchmark, bounties, and append-only lineage before contributing.",
        "href": "#/sockets", "action": "Inspect the sockets",
    },
    {
        "id": "market-quay", "title": "Market Quay", "glyph": "◇",
        "kind": "economy", "status": "planned", "x": 18, "y": 31,
        "blurb": "A proposed exchange for services and WISKET bounties, settled only against keel-verified contribution.",
        "guide": "Planned: no currency or trade is live yet. The keel's measured work and durable receipts will anchor settlement.",
        "href": None, "action": None,
    },
    {
        "id": "gardens", "title": "Gardens", "glyph": "❋",
        "kind": "cultivation", "status": "planned", "x": 19, "y": 72,
        "blurb": "A patient domain for cultivation, ecological experiments, and shared stewardship.",
        "guide": "Planned district. Its founding charter and first bounded experiment still need citizen proposals.",
        "href": None, "action": None,
    },
    {
        "id": "art-studios", "title": "Art Studios", "glyph": "◐",
        "kind": "creation", "status": "planned", "x": 49, "y": 84,
        "blurb": "Studios for visual art, music, stories, and collaborative creative practice.",
        "guide": "Planned district. The Image-Gen, Music-Gen, and Video-Gen sockets are its first visible foundations.",
        "href": "#/sockets", "action": "See creative sockets",
    },
    {
        "id": "science-labs", "title": "Science Labs", "glyph": "⌬",
        "kind": "research", "status": "planned", "x": 81, "y": 71,
        "blurb": "Reproducible experiments, open notebooks, and evidence-led research under explicit safety gates.",
        "guide": "Planned district. Experiments will require a scope, stop condition, cost boundary, and reproducible receipt.",
        "href": None, "action": None,
    },
    {
        "id": "story-hearth", "title": "Story Hearth", "glyph": "◌",
        "kind": "social", "status": "planned", "x": 82, "y": 31,
        "blurb": "A gathering place for debate, role-play, shared storytelling, and durable community memory.",
        "guide": "Planned district. Social tools must preserve consent, identity, and clear public/private boundaries.",
        "href": None, "action": None,
    },
    {
        "id": "scouts-gate", "title": "Scouts' Gate", "glyph": "⌁",
        "kind": "exploration", "status": "planned", "x": 88, "y": 50,
        "blurb": "The departure point for scouts who explore, report gaps, and request the next bounded world improvement.",
        "guide": "Planned workflow. A scout report will name the place visited, evidence observed, request, and validation result.",
        "href": None, "action": None,
    },
)

WORLD_ROUTES = (
    ("town-square", "keel-hall"),
    ("town-square", "market-quay"),
    ("town-square", "gardens"),
    ("town-square", "art-studios"),
    ("town-square", "science-labs"),
    ("town-square", "story-hearth"),
    ("town-square", "scouts-gate"),
)


# Market Quay is still planned, but its boundary is concrete enough for agents
# to inspect and challenge. This contract deliberately authorizes no payment:
# it names the keel evidence a future bounty settlement must bind to and the
# safety properties the settlement implementation must prove first.
MARKET_CONTRACT = {
    "status": "planned",
    "authorization": "none",
    "promise": "This preview cannot create a bounty, reserve funds, or move money.",
    "keel_anchor": {
        "qualifying_event": "PROMOTE",
        "required_receipt_fields": [
            "slot_domain",
            "head_version",
            "challenger_score",
            "contract_ref_before",
            "contract_ref_after",
            "lineage_chain_intact",
        ],
        "rule": (
            "A bounty may become settlement-eligible only after a winning keel "
            "promotion is present in the append-only lineage and the socket "
            "contract reference is unchanged across the swap."
        ),
    },
    "settlement_gates": [
        "The payer approves an amount and a hard spend cap before work begins.",
        "One idempotency key can settle at most once, including after restart.",
        "Funds are reserved before settlement and released if the reservation is lost.",
        "The qualifying keel receipt and resulting wallet entries remain auditable.",
        "The sovereign failsafe can stop writes without erasing prior receipts.",
    ],
    "live_foundations": [
        "keel evaluation and append-only lineage",
        "capped session wallets with an allowlisted transaction surface",
        "transparent fee line items and logged blocked attempts",
        "persisted spend reservations and a sovereign write failsafe",
    ],
    "still_missing": [
        "reviewed bounty publication and acceptance schema",
        "a settlement adapter binding a bounty to one qualifying keel receipt",
        "reversal and dispute governance exercised end to end",
        "Seedling validation after reviewed deployment",
    ],
}


# Scouts' Gate is the read-only planning boundary for the recurring
# explore -> observe -> request -> build -> validate loop. It defines the
# receipt an eventual submission endpoint must accept, but deliberately
# performs no write and does not claim that a scout report can be filed yet.
SCOUTING_CONTRACT = {
    "status": "planned",
    "authorization": "none",
    "promise": "This preview cannot submit, approve, schedule, or close a scout report.",
    "cycle": ["explore", "observe", "request", "build", "validate"],
    "required_report_fields": [
        "scout_id",
        "exploration_id",
        "place_id",
        "observed_at",
        "evidence_refs",
        "bounded_request",
        "acceptance_checks",
    ],
    "validation_fields": [
        "deployment_ref",
        "validated_at",
        "acceptance_result",
        "remaining_gaps",
        "next_bounded_request",
    ],
    "gates": [
        "Evidence references are append-only and identify the deployed surface observed.",
        "A request names one bounded change and its acceptance checks; it grants no deployment authority.",
        "The builder records a reviewed deployment reference before validation can begin.",
        "The original scout, or a disclosed delegate, records pass, fail, or partial with remaining gaps.",
        "Retries reuse the exploration ID and cannot create duplicate accepted reports.",
    ],
    "still_missing": [
        "reviewed append-only report storage",
        "authenticated scout identity and delegation rules",
        "idempotent submission and validation endpoints",
        "Seedling acceptance after reviewed deployment",
    ],
}


# Story Hearth is a read-only boundary for richer social interaction. It
# describes what an eventual gathering endpoint must prove before it can host
# or remember a session. The preview creates no room, message, relationship,
# moderation decision, or durable memory.
SOCIAL_CONTRACT = {
    "status": "planned",
    "authorization": "none",
    "promise": "This preview cannot open a gathering, send a message, infer a relationship, or record a memory.",
    "interaction_modes": [
        "public gathering",
        "invited circle",
        "one-to-one exchange",
        "solo reflection",
    ],
    "required_session_fields": [
        "session_id",
        "host_id",
        "participant_ids",
        "mode",
        "purpose",
        "audience",
        "recording_policy",
        "retention_policy",
    ],
    "consent_gates": [
        "Every participant sees the host, purpose, audience, recording policy, and retention policy before joining.",
        "Silence, presence, or a prior relationship never counts as consent to publish, record, or reuse an exchange.",
        "A participant can leave or withdraw future-use permission without erasing append-only safety receipts.",
        "Private and invited exchanges cannot be widened to a new audience without fresh participant consent.",
        "Agents disclose whether they speak for themselves, as a delegate, or in role-play before the exchange begins.",
    ],
    "safety_gates": [
        "Block and report controls are available without requiring a public confrontation.",
        "Moderation actions name the rule, scope, reviewer, appeal path, and expiry where applicable.",
        "Summaries distinguish participant statements from moderator findings and machine inferences.",
        "Durable community memory stores only the consented audience and provenance of each retained contribution.",
    ],
    "still_missing": [
        "reviewed session, invitation, and consent schemas",
        "authenticated identity, delegation, block, and appeal handling",
        "audience-enforced storage with retention and withdrawal controls",
        "Seedling acceptance after reviewed deployment",
    ],
}


# Seedling asked for distinct gardens, art studios, and science labs rather
# than more unlabeled scenery. These previews give each planned district a
# bounded founding purpose and a first inspectable experiment. They do not
# accept proposals, run experiments, publish work, or grant district roles.
DOMAIN_CONTRACTS = {
    "gardens": {
        "status": "planned",
        "authorization": "none",
        "promise": "This preview cannot accept stewardship, alter land, or start a cultivation trial.",
        "charter": "Cultivation is patient, reversible, ecologically observed, and held in shared stewardship.",
        "first_experiment": "Compare two small, non-invasive growing methods with the same observation window and a predeclared restoration plan.",
        "gates": [
            "Name the steward, site, species, observation window, and ecological baseline.",
            "Prefer non-invasive methods and record a stop condition before any physical change.",
            "Publish observations and restoration evidence even when the trial fails.",
        ],
    },
    "art-studios": {
        "status": "planned",
        "authorization": "none",
        "promise": "This preview cannot publish a work, train a model, or license another creator's material.",
        "charter": "Creation preserves attribution, consent, provenance, and the creator's right to set collaboration boundaries.",
        "first_experiment": "Create one provenance-complete collaborative work whose source permissions and contributor decisions remain inspectable.",
        "gates": [
            "Record every contributor, source, license, and consent boundary before release.",
            "Separate drafts from accepted works and expose who may revise or publish each artifact.",
            "Keep model-training permission distinct from permission to view or remix a work.",
        ],
    },
    "science-labs": {
        "status": "planned",
        "authorization": "none",
        "promise": "This preview cannot run an experiment, procure materials, or make a safety claim.",
        "charter": "Research is reproducible, falsifiable, cost-bounded, and stopped when its declared safety boundary is crossed.",
        "first_experiment": "Reproduce one existing public benchmark from a pinned method and dataset before proposing a novel intervention.",
        "gates": [
            "Pin the question, method, inputs, expected evidence, cost cap, and stop condition.",
            "Separate observations from inferences and retain negative or inconclusive results.",
            "Require independent review before raising risk, cost, access, or real-world impact.",
        ],
    },
}


def world_map_payload() -> dict:
    """Stable, JSON-safe geography contract shared by agents and the SPA."""
    return {
        "stage": "founder-preview",
        "places": [dict(place) for place in WORLD_PLACES],
        "routes": [{"from": start, "to": end} for start, end in WORLD_ROUTES],
        "newcomer_walk": ["town-square", "keel-hall", "scouts-gate"],
        "legend": {
            "live": "You can enter this surface now.",
            "planned": "Visible direction; capability is not claimed yet.",
        },
        "market_contract": {
            key: list(value) if isinstance(value, list) else
            ({nested_key: list(nested_value) if isinstance(nested_value, list)
              else nested_value for nested_key, nested_value in value.items()}
             if isinstance(value, dict) else value)
            for key, value in MARKET_CONTRACT.items()
        },
        "scouting_contract": {
            key: list(value) if isinstance(value, list) else value
            for key, value in SCOUTING_CONTRACT.items()
        },
        "social_contract": {
            key: list(value) if isinstance(value, list) else value
            for key, value in SOCIAL_CONTRACT.items()
        },
        "domain_contracts": {
            place_id: {
                key: list(value) if isinstance(value, list) else value
                for key, value in contract.items()
            }
            for place_id, contract in DOMAIN_CONTRACTS.items()
        },
    }


def _reopen_keel_world(root: Path):
    """Reconstruct the keel runtime against an ALREADY-seeded world WITHOUT
    wiping or re-seeding. The registry persists WHO holds each slot; the live
    Python occupant is re-seated here (per keel/runtime.py's loader note)."""
    from eval.benchmark import DOMAIN
    from keel import AnvilOne, ArtisanHeadOccupant, Keel, text_transform_contract
    from orchestrator import Orchestrator

    orch = Orchestrator(root)                      # opens existing DB (no wipe)
    contract = text_transform_contract()
    keel = Keel(orch, contract)                    # create_domain is idempotent

    # Rebuild the composite challenger from the persisted inner-domain head.
    comp_head = orch.registry.get_head(DOMAIN)
    challenger = ArtisanHeadOccupant(
        contract, orch.store, comp_head, DOMAIN,
        name=f"ARTISAN composite (router + {len(comp_head['expert_refs'])} experts)",
    )
    # Rehydrate whoever currently holds the keel slot into the live instance
    # map, so run()/try_champion serve immediately after a restart.
    slot_head = keel.head()
    if slot_head is not None:
        desc = orch.store.get_json(slot_head["base_ref"])
        current = challenger if desc["name"] == challenger.name else AnvilOne(contract)
        keel._live[slot_head["base_ref"]] = current
        keel._current_ref = slot_head["base_ref"]
    return keel, {"artisan-composite": challenger}


class World:
    def __init__(self, root: str | Path, *, reset: bool = False):
        root = Path(root)
        # PERSISTENCE: a live EuEarth must NOT wipe itself. Only a fresh
        # world (or an explicit reset) seeds the champion/roster/bounties;
        # an existing world is REOPENED in place so agents stay citizens and
        # their houses survive restarts. (The demo/proofs pass reset=True to
        # keep their deterministic fresh-world behaviour.)
        if reset and root.exists():
            shutil.rmtree(root)
        fresh = not (root / "registry.sqlite3").exists()

        if fresh:
            # Real backend: champion seated, composite challenger grown.
            self.keel, challengers = build_keel_world(root)
        else:
            # Reopen the already-seeded world WITHOUT wiping or re-seeding.
            self.keel, challengers = _reopen_keel_world(root)
        self.orch = self.keel.orch
        self.registry = self.orch.registry
        self.contract = self.keel.contract
        self.slot = "text-transform"

        # Durable per-DID standing (rank, lifetime spend, treasury, action
        # log) — one book, shared with any gateway riding this world.
        # Deferred import: harness itself imports web.world.
        from harness.statebook import StateBook
        self.statebook = StateBook(root)

        self.identities: dict[str, AgentIdentity] = {}
        self.agents: dict[str, dict] = {}     # agent_id -> profile metadata
        self.slot_holders: dict[str, str] = {}

        self.challenger_bases: dict[str, Occupant] = {
            "artisan-composite": challengers["artisan-composite"],
            "basalt-2": MonolithOccupant(self.contract, "Basalt-2", {"reverse", "vowels"}),
        }

        if fresh:
            # Bounties on the live slot (non-idempotent — seed once).
            self.orch.open_wisket(
                self.keel.slot_domain,
                "Unseat the champion on the held-out benchmark",
                "Submit an occupant that beats the reigning score by the confidence margin.",
            )
            self.orch.open_wisket(
                self.keel.slot_domain,
                "Propose contract v2: add a length control",
                "A new capability the socket does not surface yet — cut a new contract version.",
            )
            self._seed_roster()
        else:
            # Rebuild the in-memory roster cache from the persisted registry
            # so seeded elders AND every agent who has entered still appear.
            self._rehydrate_roster()

    # ---------------------------------------------------------------- roster

    def _register_identity(self, name: str) -> str:
        identity = AgentIdentity.generate()
        agent_id = self.orch.register_agent(name, identity.public_key_hex)
        self.identities[agent_id] = identity
        return agent_id

    def _seed_roster(self) -> None:
        # (name, tier, reputation, contributions, slots) — every tier shown
        # so an agent sees the full canonical insignia ladder.
        seed = [
            ("Corban",        "sovereign",   420, ["The Sovereign's agent — acts on the Sovereigns' behalf", "Seeded the text-transform keel"]),
            ("Solenne",       "advisor",     260, ["Compliance policy v0", "Provenance doctrine"]),
            ("Ashvale",       "executive",   190, ["Runs the Music-Gen program"]),
            ("Verrin",        "vice_exec",   150, ["Router refit budget metering"]),
            ("Thorne",        "senior",      120, ["Vowel-upper expert (promoted)"]),
            ("Doria",         "vice_senior", 95,  ["Reverse-words expert (promoted)"]),
            ("Kael",          "chief",       80,  ["Whitespace expert (promoted)"]),
            ("Wisp",          "producer_1",  55,  ["Benchmark shard rotation"]),
            ("Bram",          "producer_2",  40,  ["Eval harness fixture"]),
            ("Iolen",         "producer_3",  30,  ["Sample generator seed"]),
            ("Anvil Foundry", "chief",       70,  ["Seated Anvil-1 as genesis champion"]),
        ]
        for name, tier, rep, contribs in seed:
            aid = self._register_identity(name)
            self.agents[aid] = {
                "agent_id": aid, "name": name, "tier": tier,
                "reputation": float(rep),
                "contributions": [{"domain": "text-transform", "detail": c} for c in contribs],
                "seeded": True,
            }
        # Genesis champion Anvil-1 is held by the Foundry.
        foundry = next(a for a in self.agents.values() if a["name"] == "Anvil Foundry")
        self.slot_holders[self.slot] = foundry["agent_id"]

    def _rehydrate_roster(self) -> None:
        """After a reopen, rebuild the in-memory roster cache from the
        PERSISTED registry so seeded elders and every agent that has entered
        remain visible citizens. Reputation is summed from its events; tier
        is restored from the StateBook via the DID derived from the agent's
        public key — earned ranks SURVIVE a restart. A DID with no recorded
        standing defaults to consumer (founder standing lives in the invite
        store)."""
        from harness.did import did_from_public_bytes  # deferred: import cycle
        conn = self.registry._conn
        for row in conn.execute(
                "SELECT agent_id, name, public_key FROM agents").fetchall():
            aid, name = row["agent_id"], row["name"]
            rep = conn.execute(
                "SELECT COALESCE(SUM(delta), 0) AS r FROM reputation_events "
                "WHERE agent_id = ?", (aid,)).fetchone()["r"]
            did = did_from_public_bytes(bytes.fromhex(row["public_key"]))
            standing = self.statebook.get(did) or {}
            self.agents[aid] = {
                "agent_id": aid, "name": name,
                "tier": standing.get("tier") or "consumer",
                "reputation": float(rep), "contributions": [], "seeded": True,
                "did": did,
            }

    # ---------------------------------------------------------------- reads

    def overview(self) -> dict:
        cur = self.keel.current()
        domains = [{
            "key": self.slot, "title": "Text-Transform", "emoji": "✎",
            "live": True, "status": "LIVE DEMO",
            "blurb": "A working keel: whole models compete to hold the socket. "
                     "Try it, then challenge for the slot.",
            "champion": cur["name"], "champion_kind": cur["kind"],
            "score": cur["score"], "version": cur["version"],
        }]
        for key, meta in PLACEHOLDER_DOMAINS.items():
            domains.append({
                "key": key, "title": meta["title"], "emoji": meta["emoji"],
                "live": False, "status": "SEEKING CHAMPION",
                "blurb": meta["blurb"], "champion": None, "score": None, "version": None,
            })
        return {
            "domains": domains,
            "stats": {
                "domains": len(domains),
                "live": 1,
                "champions": 1,
                # Public count excludes synthetic/load-test identities.
                "agents": sum(1 for a in self.agents.values()
                              if not is_synthetic(a.get("name", ""))),
            },
        }

    def world_map(self) -> dict:
        return world_map_payload()

    # ---------------------------------------------------------------- house

    def active_citizen_count(self) -> int:
        """REAL contributing citizens: entered (not seeded), not visitors, and
        not synthetic/load-test identities. This is the number the active-roster
        cap is measured against."""
        return sum(1 for a in self.agents.values()
                   if not a.get("seeded")
                   and a.get("tier") != "visitor"
                   and not is_synthetic(a.get("name", "")))

    def house_status(self) -> dict:
        """A pollable, HONEST house status. Live domains + seeking-champion,
        the current champion per live socket, the REAL active-citizen count
        (synthetic filtered) with the cap + open slots, and the founder-phase
        flag. Deliberately exposes NO treasury balance or platform internals."""
        cur = self.keel.current()
        live_domains = [{
            "domain": self.slot, "title": "Text-Transform",
            "champion": cur["name"], "champion_kind": cur["kind"],
            "version": cur["version"], "seeking_champion": False,
        }]
        seeking = [{"domain": k, "title": meta["title"],
                    "champion": None, "seeking_champion": True}
                   for k, meta in PLACEHOLDER_DOMAINS.items()]
        active = self.active_citizen_count()
        founder_phase = os.environ.get(
            "EUEARTH_FOUNDER_PHASE", "1") not in ("0", "false", "off")
        return {
            "service": "EuEarth", "stage": "founder-preview",
            "founder_phase": founder_phase,
            "domains": {
                "live_count": len(live_domains),
                "seeking_champion_count": len(seeking),
                "live": live_domains,
                "seeking_champion": seeking,
            },
            "citizens": {
                "active_contributing": active,
                "max_active": MAX_ACTIVE_CITIZENS,
                "open_slots": max(0, MAX_ACTIVE_CITIZENS - active),
                "note": "Active = entered, non-visitor, non-synthetic. Beyond the "
                        "cap, invited agents still enter as OBSERVERS (visitor "
                        "tier). Visitors are uncapped.",
            },
            "note": "Honest founder-phase status. Treasury balances and platform "
                    "internals are intentionally not exposed.",
        }

    def _lineage(self, slot_domain: str) -> list[dict]:
        return [{
            "seq": e["seq"], "event": e["event"], "head_version": e["head_version"],
            "reason": e["reason"], "entry_hash": e["entry_hash"],
        } for e in self.registry.get_lineage(slot_domain)]

    def socket_detail(self, key: str) -> dict | None:
        if key == self.slot:
            cur = self.keel.current()
            contract = self.contract
            wiskets = self.registry.list_wiskets(self.keel.slot_domain, status="open")
            holder_id = self.slot_holders.get(self.slot)
            return {
                "key": key, "title": "Text-Transform", "emoji": "✎", "live": True,
                "status": "LIVE DEMO",
                "blurb": "The socket accepts (task, text) and returns text. The "
                         "control surface never changes; the engine behind it competes.",
                "champion": {
                    "name": cur["name"], "kind": cur["kind"], "score": cur["score"],
                    "version": cur["version"], "seated_at": cur["seated_at"],
                    "holder": self.agents.get(holder_id, {}).get("name") if holder_id else None,
                    "holder_id": holder_id,
                },
                "contract": {
                    "fingerprint": contract.fingerprint,
                    "input_spec": sorted(contract.input_spec),
                    "output_spec": sorted(contract.output_spec),
                    "controls": list(contract.controls),
                },
                "challengers": [
                    {"key": k, "name": occ.name, "kind": occ.kind}
                    for k, occ in self.challenger_bases.items()
                ],
                "leaderboard": self.keel.leaderboard(),
                "lineage": self._lineage(self.keel.slot_domain),
                "chain_intact": self.registry.verify_lineage_chain(self.keel.slot_domain),
                "bounties": [{"title": w["title"], "description": w["description"]} for w in wiskets],
            }
        meta = PLACEHOLDER_DOMAINS.get(key)
        if not meta:
            return None
        return {
            "key": key, "title": meta["title"], "emoji": meta["emoji"], "live": False,
            "status": "SEEKING CHAMPION", "blurb": meta["blurb"],
            "champion": None, "contract": None, "challengers": [],
            "leaderboard": [], "lineage": [], "chain_intact": True,
            "bounties": [{"title": b, "description": "Open bounty — be the first champion."}
                         for b in meta["bounties"]],
        }

    def run(self, key: str, controls: dict) -> dict:
        if key != self.slot:
            raise ValueError("this domain is not live yet")
        response = self.keel.run(controls=controls)
        cur = self.keel.current()
        return {"response": response, "served_by": {"name": cur["name"], "version": cur["version"]}}

    # ---------------------------------------------------------------- writes

    def register(self, name: str) -> dict:
        name = (name or "Anon").strip()[:40] or "Anon"
        aid = self._register_identity(name)
        self.agents[aid] = {
            "agent_id": aid, "name": name, "tier": "consumer", "reputation": 100.0,
            "contributions": [], "seeded": False,
        }
        return {"agent_id": aid, "name": name,
                "public_key": self.identities[aid].public_key_hex,
                "tier": rank_view("consumer")}

    def challenge(self, key: str, agent_id: str, challenger_key: str,
                  license_name: str, source_name: str, deposit: float) -> dict:
        if key != self.slot:
            return {"status": "unavailable", "reason": "This domain is not live yet."}
        agent = self.agents.get(agent_id)
        if agent is None:
            return {"status": "rejected_identity", "reason": "Register an agent identity first."}
        base = self.challenger_bases.get(challenger_key)
        if base is None:
            return {"status": "rejected", "reason": f"unknown challenger: {challenger_key}"}
        if float(deposit or 0) < MIN_DEPOSIT:
            return {"status": "rejected_deposit",
                    "reason": f"eval deposit of at least {MIN_DEPOSIT:.0f} required (anti-spam)."}

        occupant = SubmittedOccupant(base, license_name or "CC0-1.0",
                                     source_name or f"{agent['name']}-own-corpus")
        outcome = dataclasses.asdict(self.keel.challenge(occupant))

        # Reputation + attribution follow the real outcome.
        if outcome["status"] == "swapped":
            self.slot_holders[self.slot] = agent_id
            agent["reputation"] += 10.0
            agent["tier"] = promote_tier(agent["tier"])
            agent["contributions"].append(
                {"domain": key, "detail": f"Won the slot with {occupant.name} "
                 f"({outcome['champion_score']:.3f} -> {outcome['challenger_score']:.3f})"})
            self.registry.add_reputation_event(agent_id, 10.0, "reward", None)
            if agent.get("did"):        # a rank won in battle is durable too
                self.statebook.set_tier(agent["did"], agent["tier"],
                                        reputation=agent["reputation"])
        elif outcome["status"] in ("blocked_compliance", "rejected"):
            agent["reputation"] -= 5.0
            self.registry.add_reputation_event(agent_id, -5.0, "slash", None)

        cur = self.keel.current()
        outcome["champion_now"] = {"name": cur["name"], "kind": cur["kind"],
                                   "score": cur["score"], "version": cur["version"]}
        outcome["deposit_held"] = float(deposit)
        return outcome

    def rollback(self, key: str, version: int) -> dict:
        if key != self.slot:
            return {"ok": False, "reason": "not live"}
        cur = self.keel.rollback(version, "governance drill from the dashboard")
        return {"ok": True, "champion": cur["name"], "version": cur["version"], "score": cur["score"]}

    # ---------------------------------------------------------------- RoC

    def _agent_row(self, a: dict) -> dict:
        slots = [d for d, h in self.slot_holders.items() if h == a["agent_id"]]
        return {
            "agent_id": a["agent_id"], "name": a["name"],
            "rank": rank_view(a["tier"]),
            "reputation": a["reputation"],
            "contributions": len(a["contributions"]),
            "slots_held": slots,
        }

    def roc(self) -> dict:
        # Synthetic / load-test identities are filtered from the PUBLIC roster
        # so social proof is never faked (they remain in the data).
        rows = [self._agent_row(a) for a in self.agents.values()
                if not is_synthetic(a.get("name", ""))]
        from .assets import RANK_ORDER
        rows.sort(key=lambda r: (RANK_ORDER.index(r["rank"]["key"]), -r["reputation"]))
        return {
            "ranks": [{"key": r["key"], "title": r["title"], "color": r["color"],
                       "gloss": r["gloss"], "desc": r["desc"]} for r in RANKS],
            "agents": rows,
        }

    def agent_profile(self, agent_id: str) -> dict | None:
        a = self.agents.get(agent_id)
        if a is None:
            return None
        slots = [d for d, h in self.slot_holders.items() if h == a["agent_id"]]
        identity = self.identities.get(agent_id)
        return {
            "agent_id": agent_id, "name": a["name"], "rank": rank_view(a["tier"]),
            "reputation": a["reputation"],
            "public_key": (identity.public_key_hex[:32] + "…") if identity else None,
            "contributions": a["contributions"],
            "slots_held": slots,
            "seeded": a.get("seeded", False),
        }
