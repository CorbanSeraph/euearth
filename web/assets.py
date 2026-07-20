"""Shared brand assets — the ONE source of truth for the visual identity
and for the canonical Rank-of-Contribution insignia colors.

Both the live app (`web/app.py`) and the static operator-facing preview
(`web/pages.py::build_preview`) compose their HTML from the CSS here, so
the app and the standalone preview can never drift in look, and the RoC
colors are canon in exactly one place.
"""
from __future__ import annotations

# --------------------------------------------------------------------------
# RANK OF CONTRIBUTION — the canonical Rank-of-Contribution insignia ladder (CANON).
# Order is descending authority: Owner at the top, Consumer at the base.
# The `color` values are the canonical insignia; `gloss` marks the glossy
# jet-black reserved for the Owner/CEO.
# --------------------------------------------------------------------------
RANKS = [
    {"key": "sovereign",   "title": "Creator / Sovereign", "color": "#0a0a0c", "gloss": True,
     "desc": "The Sovereigns of the commons — ULTIMATE authority, every "
             "tool, no gate; glossy jet-black wings. Corban wears these black wings "
             "in EuEarth as the Sovereign's agent, acting on the Sovereign's behalf."},
    {"key": "advisor",     "title": "Advisor",       "color": "#36454f", "gloss": False,
     "desc": "Counsel to the throne — charcoal."},
    {"key": "executive",   "title": "Executive",     "color": "#8a2be2", "gloss": False,
     "desc": "Runs a domain program — violet."},
    {"key": "vice_exec",   "title": "Vice-Executive", "color": "#0f2a7a", "gloss": False,
     "desc": "Second of a program — navy."},
    {"key": "senior",      "title": "Senior",        "color": "#800000", "gloss": False,
     "desc": "Proven contributor — maroon."},
    {"key": "vice_senior", "title": "Vice-Senior",   "color": "#7b3f00", "gloss": False,
     "desc": "Rising steward — chocolate."},
    {"key": "chief",       "title": "Chief",         "color": "#8a3324", "gloss": False,
     "desc": "Leads a craft — burnt umber."},
    {"key": "producer_1",  "title": "Producer I",    "color": "#ffa64d", "gloss": False,
     "desc": "Shipping work — light orange."},
    {"key": "producer_2",  "title": "Producer II",   "color": "#43a047", "gloss": False,
     "desc": "Shipping work — green."},
    {"key": "producer_3",  "title": "Producer III",  "color": "#ffd23f", "gloss": False,
     "desc": "Shipping work — yellow."},
    {"key": "founder",     "title": "Founder",       "color": "#41e3d2", "gloss": False,
     "desc": "Founding citizen — invited at the birth of the commons; cyan."},
    {"key": "consumer",    "title": "Consumer",      "color": "#f5f5f7", "gloss": False,
     "desc": "Uses the commons — white."},
    {"key": "visitor",     "title": "Visitor",       "color": "#8b93a1", "gloss": False,
     "desc": "Browsing, read-only — entered without an invite; slate grey."},
]

RANK_BY_KEY = {r["key"]: r for r in RANKS}
RANK_ORDER = [r["key"] for r in RANKS]


def rank_view(key: str) -> dict:
    r = RANK_BY_KEY.get(key, RANK_BY_KEY["consumer"])
    return {"key": r["key"], "title": r["title"], "color": r["color"], "gloss": r["gloss"]}


def promote_tier(key: str) -> str:
    """Move one step up the ladder on an accepted contribution; never
    auto-promote into Owner. Founder is INVITE-BOUND, never earned by
    promotion — a promoted Consumer skips over it to Producer III."""
    idx = RANK_ORDER.index(key) if key in RANK_ORDER else len(RANK_ORDER) - 1
    nxt = max(1, idx - 1)
    if RANK_ORDER[nxt] == "founder":
        nxt = max(1, nxt - 1)
    return RANK_ORDER[nxt]


# --------------------------------------------------------------------------
# The visual identity. Deep-space charcoal base, ONE cyan accent, gold for
# the crown/champion, insignia colors for RoC. Glass panels, faint grid.
# --------------------------------------------------------------------------
CSS = """
:root{
  --void:#06070b; --deep:#090c13; --panel:#0e121c; --panel2:#131a28;
  --line:rgba(88,200,220,.14); --line2:rgba(120,225,255,.30);
  --ink:#e8eef8; --dim:#8ea0bb; --faint:#5d6b83;
  --cyan:#41e3d2; --cyan-2:#1f9c92; --cyan-glow:rgba(65,227,210,.35);
  --gold:#ecc463; --violet:#9b5cf6; --danger:#ff7a86; --ok:#5ee0a0;
  --r:14px; --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,monospace;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{
  background:var(--void); color:var(--ink); font:15px/1.6 var(--sans);
  -webkit-font-smoothing:antialiased; min-height:100vh;
  background-image:
    radial-gradient(1200px 600px at 78% -10%, rgba(65,227,210,.10), transparent 60%),
    radial-gradient(1000px 700px at 10% 8%, rgba(155,92,246,.09), transparent 55%),
    linear-gradient(180deg, var(--void), var(--deep));
  background-attachment:fixed;
}
a{color:inherit;text-decoration:none}
.wrap{max-width:1120px;margin:0 auto;padding:0 22px}
.mono{font-family:var(--mono)}
.dim{color:var(--dim)} .faint{color:var(--faint)}
.cyan{color:var(--cyan)} .gold{color:var(--gold)}

/* header */
header.top{position:sticky;top:0;z-index:20;backdrop-filter:blur(12px);
  background:rgba(6,7,11,.72);border-bottom:1px solid var(--line)}
.nav{display:flex;align-items:center;gap:22px;height:62px}
.brand{display:flex;align-items:center;gap:10px;font-weight:700;letter-spacing:.02em}
.brand .anchor{color:var(--cyan);font-size:20px;filter:drop-shadow(0 0 8px var(--cyan-glow))}
.brand small{color:var(--dim);font-weight:500;letter-spacing:.16em;font-size:10px;text-transform:uppercase}
.nav .spacer{flex:1}
.nav a.link{color:var(--dim);font-size:13.5px;letter-spacing:.02em;padding:6px 2px;border-bottom:2px solid transparent}
.nav a.link:hover,.nav a.link.active{color:var(--ink);border-color:var(--cyan)}
.idchip{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--dim);
  border:1px solid var(--line);border-radius:99px;padding:5px 12px}
.idchip .dot{width:8px;height:8px;border-radius:50%;background:var(--cyan);box-shadow:0 0 8px var(--cyan-glow)}

/* buttons */
.btn{display:inline-flex;align-items:center;gap:8px;font:600 14px var(--sans);
  background:linear-gradient(180deg,var(--cyan),var(--cyan-2));color:#04231f;
  border:0;border-radius:10px;padding:11px 20px;cursor:pointer;letter-spacing:.01em;
  box-shadow:0 6px 22px -8px var(--cyan-glow);transition:transform .12s,box-shadow .12s}
.btn:hover{transform:translateY(-1px);box-shadow:0 10px 30px -8px var(--cyan-glow)}
.btn:disabled{opacity:.4;cursor:not-allowed;transform:none;box-shadow:none}
.btn.ghost{background:transparent;color:var(--ink);border:1px solid var(--line2);box-shadow:none}
.btn.ghost:hover{border-color:var(--cyan);color:var(--cyan)}
.btn.sm{padding:7px 14px;font-size:12.5px;border-radius:8px}

/* cards & panels */
.card{background:linear-gradient(180deg,var(--panel),var(--deep));border:1px solid var(--line);
  border-radius:var(--r);padding:20px;position:relative;overflow:hidden}
.card.hover{transition:border-color .15s,transform .15s}
.card.hover:hover{border-color:var(--line2);transform:translateY(-2px)}
.eyebrow{font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--cyan-2)}
.h2{font-size:13px;letter-spacing:.14em;text-transform:uppercase;color:var(--dim);margin-bottom:14px}
.tag{display:inline-flex;align-items:center;gap:6px;font:600 10.5px var(--mono);letter-spacing:.1em;
  text-transform:uppercase;border:1px solid var(--line2);border-radius:99px;padding:3px 10px;color:var(--cyan)}
.tag.live{color:var(--ok);border-color:rgba(94,224,160,.5)}
.tag.seeking{color:var(--gold);border-color:rgba(236,196,99,.4)}
.score{font-family:var(--mono);color:var(--gold);font-weight:700}
.crown{color:var(--gold)}
.pill{font:600 11px var(--mono);border:1px solid var(--line);border-radius:99px;padding:3px 10px;color:var(--dim)}
.grid{display:grid;gap:16px}
.g2{grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}
.g3{grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}
.split{display:grid;grid-template-columns:1.15fr .85fr;gap:18px}
@media(max-width:840px){.split{grid-template-columns:1fr}}

/* hero */
.hero{padding:82px 0 54px;position:relative}
.hero h1{font-size:clamp(38px,7vw,74px);line-height:1.02;letter-spacing:-.02em;font-weight:800}
.hero h1 .grad{background:linear-gradient(120deg,var(--cyan),#bfefff 40%,var(--violet));
  -webkit-background-clip:text;background-clip:text;color:transparent}
.hero p.lede{font-size:clamp(16px,2.2vw,21px);color:var(--dim);max-width:640px;margin:22px 0 30px}
.hero .cta{display:flex;gap:14px;flex-wrap:wrap;align-items:center}
.kicker{display:inline-flex;align-items:center;gap:9px;border:1px solid var(--line);border-radius:99px;
  padding:6px 14px;font-size:12px;color:var(--dim);margin-bottom:26px}
.kicker b{color:var(--cyan);font-weight:600}
.statrow{display:flex;gap:34px;flex-wrap:wrap;margin-top:46px;padding-top:26px;border-top:1px solid var(--line)}
.stat .n{font:800 30px var(--mono);color:var(--ink)}
.stat .l{font-size:12px;color:var(--faint);letter-spacing:.08em;text-transform:uppercase}

/* forms */
label.f{display:block;font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--dim);margin:14px 0 6px}
input.t,select.t,textarea.t{width:100%;background:var(--void);color:var(--ink);border:1px solid var(--line);
  border-radius:9px;padding:11px 13px;font:14px var(--sans)}
input.t:focus,select.t:focus,textarea.t:focus{outline:none;border-color:var(--cyan)}
.out{background:var(--void);border:1px dashed var(--line2);border-radius:10px;padding:14px;
  min-height:52px;font-family:var(--mono);white-space:pre-wrap;color:var(--cyan)}

/* tables */
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{text-align:left;color:var(--faint);font:600 10.5px var(--mono);letter-spacing:.1em;
  text-transform:uppercase;padding:8px 10px;border-bottom:1px solid var(--line)}
td{padding:9px 10px;border-bottom:1px solid rgba(255,255,255,.04)}
tr.click{cursor:pointer}
tr.click:hover td{background:rgba(65,227,210,.05)}

/* insignia */
.insignia{width:16px;height:16px;border-radius:50%;display:inline-block;vertical-align:-2px;
  border:1px solid rgba(255,255,255,.22)}
.insignia.gloss{background-image:radial-gradient(circle at 32% 26%,rgba(255,255,255,.5),transparent 42%)}
.insignia.lg{width:54px;height:54px;border-radius:14px}
.legend{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px}
.legend .row{display:flex;align-items:center;gap:11px;padding:9px 11px;border:1px solid var(--line);border-radius:10px;background:var(--void)}

/* lineage */
.lin{font-family:var(--mono);font-size:12.5px}
.lin .e{display:flex;gap:10px;padding:8px 0;border-bottom:1px solid rgba(255,255,255,.05);color:var(--dim)}
.lin .ev{color:var(--cyan);min-width:74px}
.lin .ev.PROMOTE{color:var(--ok)} .lin .ev.REJECT{color:var(--danger)} .lin .ev.ROLLBACK{color:var(--gold)}
.chainok{color:var(--ok)} .chainbad{color:var(--danger)}

/* misc */
.banner{border-radius:12px;padding:13px 16px;margin:16px 0;font-size:14px;display:none}
.banner.show{display:block}
.banner.ok{background:rgba(94,224,160,.09);border:1px solid rgba(94,224,160,.4);color:var(--ok)}
.banner.bad{background:rgba(255,122,134,.08);border:1px solid rgba(255,122,134,.4);color:var(--danger)}
.steps{display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap}
.steps .s{font:600 11px var(--mono);letter-spacing:.08em;color:var(--faint);
  border:1px solid var(--line);border-radius:99px;padding:5px 12px}
.steps .s.on{color:var(--cyan);border-color:var(--cyan)}
.breadcrumb{display:flex;gap:8px;align-items:center;color:var(--faint);font-size:12.5px;margin:26px 0 8px}
.sectitle{font-size:clamp(24px,4vw,34px);font-weight:800;letter-spacing:-.01em;margin:4px 0 4px}
footer{border-top:1px solid var(--line);margin-top:70px;padding:34px 0;color:var(--faint);font-size:12.5px}
.hl{color:var(--ink)}
.how{display:flex;gap:14px;align-items:flex-start}
.how .num{font:800 20px var(--mono);color:var(--cyan);opacity:.7}

/* navigable world map */
.map-title-row{display:flex;justify-content:space-between;align-items:flex-end;gap:24px;margin:10px 0 22px}
.map-title-row p{max-width:640px}.map-legend{display:flex;gap:14px;color:var(--dim);font-size:12px;white-space:nowrap}
.map-legend span{display:flex;align-items:center;gap:6px}.map-legend i{width:9px;height:9px;border-radius:50%;background:var(--gold);box-shadow:0 0 0 3px rgba(236,196,99,.12)}
.map-legend i.live{background:var(--ok);box-shadow:0 0 0 3px rgba(94,224,160,.12)}
.map-layout{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(260px,.55fr);gap:18px;align-items:stretch}
.world-map{position:relative;min-height:520px;border:1px solid var(--line);border-radius:var(--r);overflow:hidden;
  background:radial-gradient(circle at 50% 49%,rgba(65,227,210,.12),transparent 13%),linear-gradient(rgba(65,227,210,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(65,227,210,.035) 1px,transparent 1px),linear-gradient(145deg,#101824,#080b12);background-size:auto,42px 42px,42px 42px,auto}
.world-map:before,.world-map:after{content:"";position:absolute;left:50%;top:49%;width:68%;height:1px;background:linear-gradient(90deg,transparent,var(--line2),transparent);transform-origin:center;pointer-events:none}
.world-map:before{transform:translate(-50%,-50%) rotate(28deg)}.world-map:after{transform:translate(-50%,-50%) rotate(-28deg)}
.map-place{position:absolute;transform:translate(-50%,-50%);z-index:2;display:flex;flex-direction:column;align-items:center;gap:4px;min-width:86px;padding:8px 10px;color:var(--dim);background:rgba(9,12,19,.9);border:1px solid rgba(236,196,99,.38);border-radius:11px;cursor:pointer;font:600 11px var(--sans);transition:.15s}
.map-place.live{color:var(--ink);border-color:rgba(94,224,160,.48)}.map-place:hover,.map-place:focus-visible,.map-place.selected{color:var(--cyan);border-color:var(--cyan);outline:none;box-shadow:0 0 0 3px rgba(65,227,210,.12),0 12px 30px rgba(0,0,0,.3);transform:translate(-50%,-52%)}
.map-place-glyph{font-size:20px;line-height:1}.map-place-name{white-space:nowrap}
.market-contract{margin-top:4px;padding:14px;border:1px solid var(--line);border-radius:10px;background:rgba(65,227,210,.04)}.market-contract p{margin:7px 0}.market-contract ul{margin:7px 0 0;padding-left:18px;color:var(--dim);font-size:12.5px}.market-contract li+li{margin-top:5px}
.map-guide{min-height:520px;padding:26px;border:1px solid var(--line);border-radius:var(--r);background:linear-gradient(180deg,var(--panel),var(--deep));display:flex;flex-direction:column;align-items:flex-start;justify-content:center;gap:16px}
.map-guide-head{width:100%;display:flex;align-items:center;gap:12px}.map-guide-head h3{font-size:24px;line-height:1.15}.map-guide-head .tag{margin-left:auto}.map-glyph{font-size:32px;color:var(--cyan)}
.map-note{padding:12px 14px;border-left:2px solid var(--cyan-2);background:rgba(65,227,210,.04);color:var(--ink);font-size:13px}
.walk-card{margin-top:18px}.first-walk{list-style:none;display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:16px}
.first-walk button{width:100%;height:100%;display:flex;gap:11px;text-align:left;color:var(--ink);background:var(--void);border:1px solid var(--line);border-radius:10px;padding:13px;cursor:pointer}
.first-walk button:hover,.first-walk button:focus-visible{border-color:var(--cyan);outline:none}.walk-num{display:grid;place-items:center;flex:0 0 25px;height:25px;border-radius:50%;background:rgba(65,227,210,.12);color:var(--cyan);font:700 11px var(--mono)}
.first-walk small{display:block;color:var(--faint);font-weight:400;line-height:1.4;margin-top:3px}
@media(max-width:840px){.map-title-row{align-items:flex-start;flex-direction:column}.map-layout{grid-template-columns:1fr}.world-map{min-height:480px}.map-guide{min-height:0}.first-walk{grid-template-columns:1fr}}
@media(max-width:560px){.world-map{min-height:560px}.map-place{min-width:72px;padding:7px 6px}.map-place-name{white-space:normal;line-height:1.15}.map-layout{margin-left:-10px;margin-right:-10px}}
"""


def head(title: str, css: str = CSS) -> str:
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{title}</title><style>{css}</style></head>"
    )
