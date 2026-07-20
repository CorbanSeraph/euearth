"""The plane's real domain: structured field extraction ("clerk").

Low-IP, fully synthetic, objectively scored. An item is an English
memo sentence containing 2-3 typed fields; the target is a canonical
JSON object. Canonicalization is deliberately strict (ISO dates,
digits-only phones, "LAST, First" names, bare 2-decimal money) so a
0.5B instruct base has real headroom and adapters have real work.

Capabilities (the per-capability regression axis):
    date, money, name, email, phone

OVERLAP BY DESIGN (the council's crux): expert A trains on items whose
capabilities are within {date, money, name}; expert B within
{email, phone, name}. `name` overlaps, the output format overlaps, and
the sealed eval draws CROSS items (e.g. date+phone) neither expert ever
saw together — real interference territory for the router.

Sealed rotation: eval shards derive from a PRIVATE secret via
sha256(secret | domain | purpose | counter). Submitters never see the
seed and every eval event uses a fresh shard, so hill-climbing the
hidden set across submissions has no fixed target. An audit shard
(purpose="audit") is generated once and NEVER used for gating.
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass

CAPABILITIES = ("date", "money", "name", "email", "phone")
EXPERT_A_CAPS = frozenset({"date", "money", "name"})
EXPERT_B_CAPS = frozenset({"email", "phone", "name"})

SYSTEM_PROMPT = (
    "You are a records clerk. Extract the requested fields from the memo "
    "and reply with ONLY a JSON object, no prose."
)

INSTRUCTION = (
    "Extract every field below that appears in the memo. Reply with ONLY a "
    "JSON object containing exactly the fields that appear, using these "
    "keys and canonical formats:\n"
    '  "date": ISO format YYYY-MM-DD (numeric dates in the memo are MM/DD/YYYY)\n'
    '  "money": bare number with exactly two decimals, no separators (e.g. "1234.50")\n'
    '  "name": "LASTNAME, Firstname" with the last name in capitals\n'
    '  "email": lowercase\n'
    '  "phone": digits only, no country code (e.g. "5551234567")\n'
    "Memo: "
)

_FIRST = ["Marcus", "Dana", "Felix", "Iris", "Rowan", "Selene", "Victor", "Wren",
          "Amara", "Boris", "Celia", "Dmitri", "Esther", "Gideon", "Helena", "Ivo",
          "Juno", "Kellan", "Lydia", "Milo", "Nadia", "Oscar", "Petra", "Quentin",
          "Rhea", "Silas", "Talia", "Ulric", "Vera", "Yusuf"]
_LAST = ["Vale", "Ortiz", "Hammersmith", "Okafor", "Lindqvist", "Marchetti", "Braun",
         "Castellanos", "Duval", "Eriksen", "Fontaine", "Grigore", "Halloway", "Ibarra",
         "Jansen", "Kovacs", "Laurent", "Mbeki", "Novak", "Oyelaran", "Petrov", "Quint",
         "Rasmussen", "Soto", "Thorne", "Ueda", "Varga", "Whitlock", "Yamada", "Zielinski"]
_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]
_DOMAINS = ["example.org", "corvid.net", "meridian.co", "atlaspost.io", "harborline.com"]
_DISTRACTORS = [
    "regarding the annual gala",
    "per clause seven of the master agreement",
    "as discussed at the quarterly review",
    "pending sign-off from the operations desk",
    "with reference to the prior correspondence",
    "for the archives",
    "under the usual retention policy",
    "following the site inspection",
]


def _gen_date(rng: random.Random):
    y, m, d = rng.randint(2019, 2027), rng.randint(1, 12), rng.randint(1, 28)
    canon = f"{y:04d}-{m:02d}-{d:02d}"
    style = rng.randrange(4)
    if style == 0:
        surface = f"{_MONTHS[m-1]} {d}, {y}"
    elif style == 1:
        surface = f"{d} {_MONTHS[m-1][:3]} {y}"
    elif style == 2:
        surface = f"{m:02d}/{d:02d}/{y}"
    else:
        surface = f"the {d}th of {_MONTHS[m-1]}, {y}"
    frag = rng.choice([f"dated {surface}", f"due on {surface}", f"filed {surface}",
                       f"effective {surface}"])
    return frag, canon


def _gen_money(rng: random.Random):
    whole = rng.randint(5, 99999)
    cents = rng.choice([0, 0, rng.randint(1, 99)])
    canon = f"{whole}.{cents:02d}"
    grouped = f"{whole:,}"
    style = rng.randrange(4)
    if style == 0:
        surface = f"${grouped}.{cents:02d}"
    elif style == 1:
        surface = f"{grouped}.{cents:02d} USD"
    elif style == 2:
        surface = f"${grouped}" if cents == 0 else f"${grouped}.{cents:02d}"
    else:
        surface = (f"{grouped} dollars" if cents == 0
                   else f"{grouped} dollars and {cents} cents")
    frag = rng.choice([f"an invoice total of {surface}", f"a fee of {surface}",
                       f"remittance of {surface}", f"the sum of {surface}"])
    return frag, canon


def _gen_name(rng: random.Random):
    first, last = rng.choice(_FIRST), rng.choice(_LAST)
    canon = f"{last.upper()}, {first}"
    surface = f"{first} {last}"
    frag = rng.choice([f"signed by {surface}", f"attn: {surface}",
                       f"countersigned by {surface}", f"prepared by {surface}"])
    return frag, canon


def _gen_email(rng: random.Random):
    first, last = rng.choice(_FIRST).lower(), rng.choice(_LAST).lower()
    sep = rng.choice([".", "_", ""])
    addr = f"{first}{sep}{last}@{rng.choice(_DOMAINS)}"
    canon = addr
    surface = rng.choice([addr, addr.upper() if rng.random() < 0.3 else addr,
                          addr.capitalize()])
    frag = rng.choice([f"reachable at {surface}", f"copy {surface}",
                       f"replies to {surface}", f"contact {surface}"])
    return frag, canon


def _gen_phone(rng: random.Random):
    a, b, c = rng.randint(200, 989), rng.randint(100, 999), rng.randint(1000, 9999)
    canon = f"{a}{b}{c}"
    style = rng.randrange(4)
    if style == 0:
        surface = f"({a}) {b}-{c}"
    elif style == 1:
        surface = f"{a}-{b}-{c}"
    elif style == 2:
        surface = f"+1 {a} {b} {c}"
    else:
        surface = f"{a}.{b}.{c}"
    frag = rng.choice([f"phone {surface}", f"call {surface}",
                       f"the desk line is {surface}", f"tel: {surface}"])
    return frag, canon


_GEN = {"date": _gen_date, "money": _gen_money, "name": _gen_name,
        "email": _gen_email, "phone": _gen_phone}


@dataclass
class Item:
    prompt: str            # user-turn text (instruction + memo)
    target: dict           # capability -> canonical string
    caps: tuple            # capabilities present


def make_item(rng: random.Random, allowed_caps) -> Item:
    caps = rng.sample(sorted(allowed_caps), k=rng.choice([2, 2, 3]) if len(allowed_caps) >= 3 else 2)
    frags, target = [], {}
    for cap in caps:
        frag, canon = _GEN[cap](rng)
        frags.append(frag)
        target[cap] = canon
    frags.append(rng.choice(_DISTRACTORS))
    rng.shuffle(frags)
    memo = "Memo " + rng.choice(["A-", "Q-", "ZR-"]) + str(rng.randint(100, 999)) + ": " \
           + ", ".join(frags) + "."
    return Item(prompt=INSTRUCTION + memo, target=target, caps=tuple(sorted(caps)))


def make_items(seed: int, n: int, allowed_caps=CAPABILITIES) -> list:
    rng = random.Random(seed)
    return [make_item(rng, allowed_caps) for _ in range(n)]


def shard_seed(secret: str, domain: str, purpose: str, counter: int) -> int:
    h = hashlib.sha256(f"{secret}|{domain}|{purpose}|{counter}".encode()).hexdigest()
    return int(h[:16], 16)


# ---------------------------------------------------------------- scoring

def parse_json_object(text: str) -> dict | None:
    """First balanced {...} block, parsed as a str->str dict, else None."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
                if isinstance(obj, dict) and all(
                    isinstance(k, str) and isinstance(v, str) for k, v in obj.items()
                ):
                    return obj
                return None
    return None


def schema_filter(obj: dict) -> dict:
    """Drop keys outside the domain schema and null/empty values (poor-man's
    schema constraint at parse time)."""
    return {c: obj[c] for c in CAPABILITIES
            if c in obj and obj[c] not in (None, "")}


def score_item(item: Item, output_text: str) -> dict:
    """Returns {"pass": 0/1, "fields": {cap: 0/1 for caps in target}}.

    `pass` is the EXACT-KEY-SET metric (all present values right AND no
    missing/extra keys). `fields` is value-correctness on PRESENT caps only
    — it is precision-given-emission and is BLIND to false-positive keys
    (council v3 finding). Use `score_full` for the FP/FN-aware per-field
    metric that the gate and router assignment must be measured against."""
    obj = parse_json_object(output_text) or {}
    fields = {cap: int(obj.get(cap) == canon) for cap, canon in item.target.items()}
    ok = int(all(fields.values()) and set(obj.keys()) == set(item.target.keys()))
    return {"pass": ok, "fields": fields}


def score_full(item: Item, output_text: str) -> dict:
    """Corrected metric (council v4). Scores the EXACT KEY-SET: every
    capability over the whole schema, counting false positives and false
    negatives, plus key-set precision/recall.

    fields_exact[c] = 1 iff  (c present in gold AND emitted with correct value)
                         OR  (c absent from gold AND NOT emitted).
    So a hallucinated key (FP) and a missing key (FN) both score 0 — unlike
    score_item().fields which only looked at present caps."""
    obj = schema_filter(parse_json_object(output_text) or {})
    gold_keys = set(item.target.keys())
    pred_keys = set(obj.keys())
    fields_exact = {}
    for cap in CAPABILITIES:
        present = cap in item.target
        emitted = cap in obj
        if present:
            fields_exact[cap] = int(emitted and obj[cap] == item.target[cap])
        else:
            fields_exact[cap] = int(not emitted)      # FP -> 0
    tp = len(gold_keys & pred_keys)
    fp = len(pred_keys - gold_keys)
    fn = len(gold_keys - pred_keys)
    return {
        "exact_set": int(pred_keys == gold_keys
                         and all(obj[c] == item.target[c] for c in gold_keys)),
        "fields_exact": fields_exact,          # per-cap over FULL schema (FP/FN aware)
        "keyset_tp": tp, "keyset_fp": fp, "keyset_fn": fn,
    }


def aggregate(items: list, scores: list) -> dict:
    """Aggregate item scores -> overall pass rate + per-capability accuracy."""
    n = len(items)
    per_cap_hit = {c: 0 for c in CAPABILITIES}
    per_cap_n = {c: 0 for c in CAPABILITIES}
    for it, sc in zip(items, scores):
        for cap, hit in sc["fields"].items():
            per_cap_hit[cap] += hit
            per_cap_n[cap] += 1
    return {
        "n": n,
        "pass_rate": sum(s["pass"] for s in scores) / max(n, 1),
        "per_capability": {
            c: (per_cap_hit[c] / per_cap_n[c]) if per_cap_n[c] else None
            for c in CAPABILITIES
        },
        "per_capability_n": per_cap_n,
    }
