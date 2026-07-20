"""The STABLE UI for a keel slot — the controls users learn once.

A single self-contained page (inline CSS/JS, zero external deps) served
by FastAPI. The control surface is rendered FROM the contract at load
time and is never re-rendered afterwards: challenges swap the engine and
refresh the champion card / leaderboard / lineage, while the form the
user is touching stays byte-for-byte the same DOM. That is the keel.

Run the demo slot (champion A seated, composite challenger waiting):

    .venv/bin/python -m keel.ui        # http://127.0.0.1:8777
"""
from __future__ import annotations

import shutil
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .contract import ContractViolation
from .occupants import Occupant
from .runtime import Keel

REPO_ROOT = Path(__file__).resolve().parent.parent


class RunBody(BaseModel):
    controls: dict


class ChallengeBody(BaseModel):
    name: str


def create_app(keel: Keel, challengers: dict[str, Occupant] | None = None) -> FastAPI:
    challengers = dict(challengers or {})
    app = FastAPI(title=f"KEEL — {keel.slot_domain}")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _PAGE

    @app.get("/api/state")
    def state() -> dict:
        current = keel.current()
        return {
            "slot_domain": keel.slot_domain,
            "contract": {**keel.contract.to_dict(),
                         "fingerprint": keel.contract.fingerprint,
                         "ref": keel.contract_ref},
            "champion": current,
            "challengers": [
                {"key": key, "name": occ.name, "kind": occ.kind,
                 "seated": current is not None and occ.name == current["name"]}
                for key, occ in challengers.items()
            ],
            "leaderboard": keel.leaderboard(),
            "lineage": [
                {k: e[k] for k in ("seq", "event", "head_version", "reason", "entry_hash")}
                for e in keel.lineage()
            ],
            "chain_intact": keel.orch.registry.verify_lineage_chain(keel.slot_domain),
        }

    @app.post("/api/run")
    def run(body: RunBody) -> dict:
        try:
            response = keel.run(controls=body.controls)
        except ContractViolation as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        current = keel.current()
        return {"response": response,
                "served_by": {"name": current["name"], "version": current["version"]}}

    @app.post("/api/challenge")
    def challenge(body: ChallengeBody) -> dict:
        occupant = challengers.get(body.name)
        if occupant is None:
            raise HTTPException(status_code=404, detail=f"unknown challenger: {body.name}")
        return asdict(keel.challenge(occupant))

    return app


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KEEL — stable socket</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; margin: 0; }
  body { background:#0d1117; color:#d7dde4; font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace; padding:24px; }
  h1 { font-size:18px; letter-spacing:.04em; }
  h1 .fp, .fp { color:#7ee2b8; font-size:12px; }
  .sub { color:#8b98a5; font-size:12px; margin:4px 0 20px; }
  .grid { display:grid; grid-template-columns: minmax(320px,1.1fr) minmax(320px,1fr); gap:16px; }
  @media (max-width:820px){ .grid{ grid-template-columns:1fr; } }
  .card { background:#161b22; border:1px solid #2d333b; border-radius:8px; padding:16px; margin-bottom:16px; }
  .card h2 { font-size:12px; text-transform:uppercase; letter-spacing:.12em; color:#8b98a5; margin-bottom:10px; }
  .champ { font-size:16px; color:#fff; }
  .tag { display:inline-block; border:1px solid #2d333b; border-radius:99px; padding:1px 9px; font-size:11px; color:#9fb0c0; margin-left:6px; }
  .score { color:#7ee2b8; }
  label { display:block; font-size:11px; color:#8b98a5; margin:10px 0 4px; text-transform:uppercase; letter-spacing:.1em; }
  select, input[type=text] { width:100%; background:#0d1117; color:#d7dde4; border:1px solid #2d333b; border-radius:6px; padding:8px 10px; font:inherit; }
  button { background:#1f6feb; color:#fff; border:0; border-radius:6px; padding:8px 16px; font:inherit; cursor:pointer; margin-top:12px; }
  button:hover { background:#2f7bff; }
  button.ghost { background:#21262d; border:1px solid #2d333b; }
  .out { background:#0d1117; border:1px dashed #2d333b; border-radius:6px; padding:10px; margin-top:12px; min-height:42px; white-space:pre-wrap; }
  .served { color:#8b98a5; font-size:11px; margin-top:6px; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th, td { text-align:left; padding:5px 8px; border-bottom:1px solid #21262d; }
  th { color:#8b98a5; font-size:11px; text-transform:uppercase; letter-spacing:.08em; }
  .crown { color:#e3b341; }
  .lineage { max-height:220px; overflow:auto; font-size:12px; }
  .lineage div { padding:3px 0; border-bottom:1px solid #1c2128; color:#9fb0c0; overflow-wrap:anywhere; }
  .ev { color:#7ee2b8; }
  #banner { display:none; background:#12261e; border:1px solid #1f6f4c; color:#7ee2b8; border-radius:8px; padding:10px 14px; margin-bottom:16px; }
  #banner.bad { background:#2a1517; border-color:#8b2d33; color:#ff9ba3; }
</style>
</head>
<body>
<h1>&#9875; KEEL <span id="slot"></span></h1>
<div class="sub">stable socket <span class="fp" id="fp"></span> &mdash; the engine behind it competes; these controls never change.</div>
<div id="banner"></div>
<div class="grid">
  <div>
    <div class="card">
      <h2>Reigning champion</h2>
      <div class="champ" id="champ"></div>
      <div class="served" id="champmeta"></div>
    </div>
    <div class="card">
      <h2>Run through the stable interface</h2>
      <form id="controls"></form>
      <button id="runbtn">Run</button>
      <div class="out" id="out"></div>
      <div class="served" id="served"></div>
    </div>
  </div>
  <div>
    <div class="card">
      <h2>Challengers</h2>
      <div id="challengers"></div>
    </div>
    <div class="card">
      <h2>Slot leaderboard</h2>
      <table><thead><tr><th>v</th><th>occupant</th><th>kind</th><th>score</th></tr></thead>
      <tbody id="board"></tbody></table>
    </div>
    <div class="card">
      <h2>Lineage <span class="fp" id="chain"></span></h2>
      <div class="lineage" id="lineage"></div>
    </div>
  </div>
</div>
<script>
let controlsRendered = false;

async function fetchState() {
  const s = await (await fetch('/api/state')).json();
  document.getElementById('slot').textContent = s.slot_domain;
  document.getElementById('fp').textContent = s.contract.fingerprint;
  const c = s.champion;
  document.getElementById('champ').innerHTML =
    `${esc(c.name)} <span class="tag">${esc(c.kind)}</span>` +
    ` <span class="score">${c.score.toFixed(4)}</span>`;
  document.getElementById('champmeta').textContent =
    `slot head v${c.version} — seated ${c.seated_at}`;

  // THE POINT: the control surface renders ONCE, from the contract.
  // Swaps never touch this DOM.
  if (!controlsRendered) { renderControls(s.contract.controls); controlsRendered = true; }

  const ch = document.getElementById('challengers');
  ch.innerHTML = '';
  s.challengers.forEach(x => {
    const b = document.createElement('button');
    b.className = 'ghost';
    b.textContent = x.seated ? `${x.name} (holds the slot)` : `Challenge with ${x.name}`;
    b.disabled = x.seated;
    b.onclick = () => challenge(x.key);
    ch.appendChild(b);
  });

  document.getElementById('board').innerHTML = s.leaderboard.map(r =>
    `<tr><td>${r.version}</td><td>${r.reigning ? '<span class="crown">&#9818;</span> ' : ''}${esc(r.name)}</td>` +
    `<td>${esc(r.kind)}</td><td class="score">${r.score.toFixed(4)}</td></tr>`).join('');

  document.getElementById('lineage').innerHTML = s.lineage.map(e =>
    `<div><span class="ev">${e.event}</span> ${e.head_version ? 'v'+e.head_version : '--'} ` +
    `[${e.entry_hash.slice(0,10)}&hellip;] ${esc(e.reason)}</div>`).join('');
  document.getElementById('chain').textContent =
    s.chain_intact ? 'hash chain intact' : 'HASH CHAIN BROKEN';
}

function renderControls(controls) {
  const form = document.getElementById('controls');
  controls.forEach(ctl => {
    const label = document.createElement('label');
    label.textContent = ctl.label;
    form.appendChild(label);
    if (ctl.kind === 'select') {
      const sel = document.createElement('select');
      sel.name = ctl.name;
      ctl.options.forEach(o => {
        const opt = document.createElement('option');
        opt.value = o.value; opt.textContent = o.label;
        sel.appendChild(opt);
      });
      form.appendChild(sel);
    } else {
      const inp = document.createElement('input');
      inp.type = 'text'; inp.name = ctl.name;
      inp.placeholder = ctl.placeholder || '';
      form.appendChild(inp);
    }
  });
}

async function run() {
  const form = document.getElementById('controls');
  const controls = {};
  new FormData(form).forEach((v, k) => controls[k] = v);
  const res = await fetch('/api/run', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({controls})});
  const data = await res.json();
  if (!res.ok) { banner(true, data.detail || 'contract violation'); return; }
  document.getElementById('out').textContent = data.response.text;
  document.getElementById('served').textContent =
    `served by ${data.served_by.name} (slot head v${data.served_by.version})`;
}

async function challenge(key) {
  const res = await fetch('/api/challenge', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify({name:key})});
  const o = await res.json();
  if (!res.ok) { banner(true, o.detail || 'challenge failed'); return; }
  if (o.status === 'swapped') {
    banner(false, `ENGINE SWAPPED: ${o.champion_before} → ${o.champion_after} ` +
      `(${o.champion_score.toFixed(4)} → ${o.challenger_score.toFixed(4)}). ` +
      `Contract ${o.contract_ref_before === o.contract_ref_after ? 'UNCHANGED' : 'CHANGED (!)'} ` +
      `— your controls did not move.`);
  } else {
    banner(true, `${o.status.toUpperCase()}: ${o.reason}`);
  }
  fetchState();
}

function banner(bad, text) {
  const el = document.getElementById('banner');
  el.className = bad ? 'bad' : '';
  el.style.display = 'block';
  el.textContent = text;
}

function esc(s) {
  return String(s).replace(/[&<>"]/g,
    c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
}

document.getElementById('runbtn').onclick = (e) => { e.preventDefault(); run(); };
fetchState();
</script>
</body>
</html>
"""


def main() -> None:
    import uvicorn

    from demo.prove_the_keel import build_world

    root = REPO_ROOT / "var" / "keel_ui"
    if root.exists():
        shutil.rmtree(root)
    keel, challengers = build_world(root)
    app = create_app(keel, challengers)
    print(f"KEEL dashboard for {keel.slot_domain} -> http://127.0.0.1:8777")
    uvicorn.run(app, host="127.0.0.1", port=8777, log_level="warning")


if __name__ == "__main__":
    main()
