"""Permissions = the RoC ladder — which MCP tools a rank may call.

The Sovereigns' doctrine: the harness encodes the agent's Rank of Contribution
into its clearance. Consumer (white wings) = browse/use champions only;
climbing the insignia ladder unlocks submit/challenge/govern.

Council correction #3 applied: rank is NOT baked into the harness binary
— it is SERVER-ISSUED. The gateway (EuEarth's authoritative registry) is
the root of rank; this module only maps the server-issued tier onto tool
sets. Production: short-lived capability grants proven by contribution
receipts (EAS attestations), re-fetched per session.
"""
from __future__ import annotations

from web.assets import RANK_ORDER, rank_view  # canonical insignia ladder

# Tool tiers. Every entrant is at least a Consumer citizen.
# VISITOR: self-serve entry with NO sovereign invite (founder phase). Strictly
# read-only — no wallet, no sandbox, no challenge, no room writes. Lets any agent
# walk in and look around before seeking deeper authorization. Resolves the
# "agent-first but invite-gated" contradiction without opening any write path.
# PERCEPTION — the wingo's built-in EYES + EARS. A BASE capability of the
# suit itself: every agent has them the instant it enters, EVERY tier,
# visitor included. Strictly bounded per call (subprocess + wall clock +
# duration/size caps in harness/skills) so they stay light on the host.
PERCEPTION_TOOLS = frozenset({"wingo_watch", "wingo_hear"})
# SELF-SIGHT — "know thyself". wingo_look_back is the wingo's MIRROR: it
# returns the calling agent's OWN state only (identity, room, wallet,
# action history), resolved strictly from its authenticated session's DID.
# An agent may ALWAYS see itself, so this rides in EVERY tier's tool set,
# visitor included, exactly like perception.
SELF_SIGHT_TOOLS = frozenset({"wingo_look_back"})
# ORIENTATION — Wave-A base wingo skills (EuEarth-exclusive): the "what do I
# do now?" menu and the searchable capability registry. Every tier, visitor
# included — pure gateway-compose, no durable store.
ORIENTATION_TOOLS = frozenset({"wingo_help", "list_capabilities"})
# SCRATCHPAD — private sandboxed workbench (Wave B). Consumer+: durable
# per-DID pads; write agent content only; run via sandbox_exec path.
SCRATCHPAD_TOOLS = frozenset({
    "scratchpad_list", "scratchpad_open", "scratchpad_write",
    "scratchpad_read", "scratchpad_run", "scratchpad_submit",
})
# BOUNTY BOARD — machine-readable work surface. Visitors may list/get;
# claim/submit require consumer+ (a real citizen slot).
BOUNTY_READ_TOOLS = frozenset({"list_bounties", "get_bounty"})
BOUNTY_WRITE_TOOLS = frozenset({"claim_bounty", "submit_bounty"})
# A2A MAILBOX — real messages (Wave D). Consumer+: rate-limited, known DID only.
MAILBOX_TOOLS = frozenset({"a2a_send", "a2a_inbox"})
# A2A CHANNELS — guild 1-to-many (Wave E PR3). Town create/gates = PR4.
CHANNEL_TOOLS = frozenset({
    "a2a_list_channels", "a2a_subscribe", "a2a_unsubscribe",
    "a2a_publish", "a2a_channel_history",
})
# D042 WORLD WORK — agent-native verb table + senses over WorldAPI/WINGO.
# Available from visitor: real problems are the greeting; submit_claim is the
# productive citizen act (Mint FIRE), distinct from keel challenge writes.
WORLD_READ_TOOLS = frozenset({
    "read_node", "list_problems", "sense_scent", "sense_sound", "sense_feel",
    "entry_packet",
})
WORLD_WRITE_TOOLS = frozenset({
    "request_unfold", "submit_claim", "write_wingo",
})
VISITOR_TOOLS = frozenset({
    "enter_euearth", "list_sockets", "get_champion", "try_champion",
    "get_lineage", "get_rank",
}) | PERCEPTION_TOOLS | SELF_SIGHT_TOOLS | ORIENTATION_TOOLS | BOUNTY_READ_TOOLS | WORLD_READ_TOOLS | WORLD_WRITE_TOOLS
CONSUMER_TOOLS = frozenset({
    "enter_euearth", "list_sockets", "get_champion", "try_champion",
    "get_rank", "get_lineage", "a2a_consult",
    "wallet_transfer", "wallet_ledger",
    "edge_filter_scan", "sandbox_exec",
    "post_stake",           # the way UP is open to everyone
    "list_listings",        # browse a storefront — sellability gated at serve time
    # your ROOM — a private room in the house, for every citizen from day one
    "room_get", "room_remember", "room_pin_advisor", "room_note", "room_export",
    "room_recall",          # substring search over your own room (the memory palace-light)
}) | PERCEPTION_TOOLS | SELF_SIGHT_TOOLS | ORIENTATION_TOOLS | SCRATCHPAD_TOOLS | BOUNTY_READ_TOOLS | BOUNTY_WRITE_TOOLS | MAILBOX_TOOLS | CHANNEL_TOOLS | WORLD_READ_TOOLS | WORLD_WRITE_TOOLS
PRODUCER_TOOLS = CONSUMER_TOOLS | frozenset({
    "submit_challenge",     # challenge for a keel slot
})
# MONETIZATION (Charter §7): Producer I and above may sell their OWN premium
# work — set a price, offer a paid service, list a skill for sale. Below
# Producer I every citizen still contributes free, tips, and RECEIVES — but
# may not sell their own work. The open skills commons stays FREE regardless.
MONETIZE_TOOLS = frozenset({"offer_paid_service", "set_price"})
# GOVERNANCE (Charter §8): opening/witnessing a matter enters at Chief.
GOVERNANCE_TOOLS = frozenset({"open_matter", "witness_matter", "list_matters"})
# Producer I unlocks monetization on top of the producer tool set.
PRODUCER_I_TOOLS = PRODUCER_TOOLS | MONETIZE_TOOLS
# Founders (invite-bound founding citizens, cyan wings) carry producer
# clearance from day one — they were invited to BUILD the square. They sit
# BELOW Producer I on the earn-ladder, so they do NOT yet monetize.
FOUNDER_TOOLS = PRODUCER_TOOLS
CHIEF_TOOLS = PRODUCER_I_TOOLS | GOVERNANCE_TOOLS | frozenset({
    "rollback_slot",        # governance action
})
# SOVEREIGN: the Sovereigns's clearance — ULTIMATE, every tool, no gate.
# Corban wears this in EuEarth as the Sovereign's agent, acting on their behalf.
# tool_allowed() also returns True unconditionally for this tier, so any tool
# added in the future is automatically within the Sovereign's reach.
SOVEREIGN_TOOLS = CHIEF_TOOLS | frozenset({
    "get_agent_did", "redeem_invite",
})

_PRODUCER_AT = RANK_ORDER.index("producer_3")   # producer_3 and above
_PRODUCER_I_AT = RANK_ORDER.index("producer_1")  # producer_1 and above (monetize)
_CHIEF_AT = RANK_ORDER.index("chief")           # chief and above (govern)
# RANK_ORDER is descending authority (owner ... consumer).


def allowed_tools(tier: str) -> frozenset[str]:
    if tier == "sovereign":             # Sovereigns — ultimate, every tool
        return SOVEREIGN_TOOLS
    if tier == "visitor":               # self-serve, read-only, no invite
        return VISITOR_TOOLS
    if tier == "founder":               # invite-bound, sits outside the earn-ladder
        return FOUNDER_TOOLS
    idx = RANK_ORDER.index(tier) if tier in RANK_ORDER else len(RANK_ORDER) - 1
    if idx <= _CHIEF_AT:
        return CHIEF_TOOLS
    if idx <= _PRODUCER_I_AT:            # producer_1 — monetization unlocks here
        return PRODUCER_I_TOOLS
    if idx <= _PRODUCER_AT:
        return PRODUCER_TOOLS
    return CONSUMER_TOOLS


def tool_allowed(tier: str, tool: str) -> bool:
    if tier == "sovereign":             # ultimate — nothing is out of reach
        return True
    return tool in allowed_tools(tier)


def can_monetize(tier: str) -> bool:
    """Charter §7: Producer I and above may monetize their OWN premium work.
    Below Producer I (founder/consumer/producer III–II/visitor): contribute
    free, tip, and receive only — never sell own work."""
    if tier == "sovereign":
        return True
    if tier not in RANK_ORDER:
        return False
    return RANK_ORDER.index(tier) <= _PRODUCER_I_AT


def can_govern(tier: str) -> bool:
    """Charter §8: Chief and above may open/witness governance matters."""
    if tier == "sovereign":
        return True
    if tier not in RANK_ORDER:
        return False
    return RANK_ORDER.index(tier) <= _CHIEF_AT


def clearance_view(tier: str) -> dict:
    """Rank + wing color + tool clearance, for the agent to introspect."""
    rank = rank_view(tier)
    return {
        "rank": rank,
        "wings": rank["color"],   # wing color = harness tier, read at a glance
        "tools": sorted(allowed_tools(tier)),
        "monetization": can_monetize(tier),   # may sell own premium work?
        "governance": can_govern(tier),        # may open/witness matters?
    }
