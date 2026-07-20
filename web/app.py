"""FastAPI surface for the ARTISAN / EuEarth front-end.

Serves the single-page app at `/` and the JSON API the SPA calls. The
`text-transform` domain is wired to the REAL backend (keel + registry +
eval + orchestrator via web.world.World) — browse, try, challenge and
swap all execute the true pipeline.

Frontend/back split for deploy: the SPA is a static document (index_html)
that talks to `window.__ARTISAN_API__` (defaults to same origin). Ship
the document to Cloudflare Pages, this API to Fly.io, point the former at
the latter. See web/DEPLOY.md.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi import status as http_status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from .onboarding import (
    llms_txt,
    mcp_tools_json,
    onboarding_dict,
    onboarding_html,
)
from .pages import index_html
from .ratelimit import FixedWindowLimiter, client_ip
from .world import MAX_ACTIVE_CITIZENS, World

# Minimal page chrome for the human-facing onboarding doc (reuses the site's
# look; the doc body is generated in web.onboarding).
_ONBOARDING_CSS = """
  :root{--bg:#0e1014;--panel:#161a21;--ink:#e9edf2;--muted:#9aa4b2;--line:#252b34;--cyan:#41e3d2;--cyan-ink:#7ff0e4;}
  @media(prefers-color-scheme:light){:root{--bg:#f6f7f9;--panel:#fff;--ink:#14171d;--muted:#5c6672;--line:#e4e7ec;--cyan:#0e9c92;--cyan-ink:#0b756e;}}
  *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);line-height:1.6;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
  .wrap{max-width:960px;margin:0 auto;padding:clamp(22px,5vw,56px)}
  .mono{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace}
  .eyebrow{font-size:.72rem;letter-spacing:.2em;text-transform:uppercase;color:var(--cyan-ink);font-weight:700}
  h1{font-size:clamp(1.9rem,5vw,2.8rem);letter-spacing:-.02em;margin:.3em 0 .2em}
  h2{margin:2em 0 .3em;letter-spacing:-.01em}h3{margin:0 0 .2em}
  .lede{color:var(--muted);font-size:1.15rem;max-width:62ch}
  a{color:var(--cyan-ink)}
  .grid{display:grid;grid-template-columns:1fr;gap:14px;margin-top:1em}
  @media(min-width:640px){.grid.two{grid-template-columns:1fr 1fr}}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px 18px}
  .card p{color:var(--muted);margin:.2em 0 0}
  pre.code{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;overflow-x:auto;font-size:.82rem;line-height:1.5}
  table{width:100%;border-collapse:collapse;margin-top:1em;font-size:.9rem;display:block;overflow-x:auto}
  th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
  th{color:var(--muted);font-weight:600;font-size:.8rem;text-transform:uppercase;letter-spacing:.05em}
  .tag{font-size:.72rem;padding:2px 8px;border-radius:999px;border:1px solid var(--line)}
  .tag.live{color:#4bd07f;border-color:#4bd07f55}.tag.planned{color:#e0a94b;border-color:#e0a94b55}
  .foot{margin-top:2.4em;padding-top:1.2em;border-top:1px solid var(--line);color:var(--muted);font-size:.85rem}
"""


def _wants_json(request: Request) -> bool:
    if request.query_params.get("format") == "json":
        return True
    accept = request.headers.get("accept", "")
    return "application/json" in accept and "text/html" not in accept


def _rb(schema: dict) -> dict:
    """Wrap a JSON Schema as an OpenAPI requestBody. The raw-Request POST
    handlers parse the body by hand, so FastAPI can't infer a body schema —
    these make the OpenAPI POST ops honest (fixes the Darkk #7 drift)."""
    return {"requestBody": {"required": True,
                            "content": {"application/json": {"schema": schema}}}}


# Request-body schemas for the by-hand-parsed POST endpoints.
_RB_VALIDATE = _rb({
    "type": "object", "required": ["delegation"], "properties": {
        "agent_did": {"type": "string",
                      "description": "the DID you enter with (== credential.aud)"},
        "delegation": {"type": "object", "required": ["credential", "signature"],
                       "properties": {
                           "credential": {"type": "object"},
                           "signature": {"type": "string", "description": "hex Ed25519"}}},
    }})
_RB_CONTRIB = _rb({
    "type": "object", "required": ["summary"], "properties": {
        "kind": {"type": "string",
                 "enum": ["fix", "feature", "model", "domain", "other"]},
        "summary": {"type": "string", "description": "what and why"},
        "code": {"type": "string", "description": "reference implementation (optional)"},
        "model_ref": {"type": "string", "description": "HF id / OCI digest / URL"},
        "license": {"type": "string"},
        "did": {"type": "string"}, "contact": {"type": "string"},
    }})
_RB_INVITE = _rb({
    "type": "object", "required": ["did"], "properties": {
        "did": {"type": "string", "description": "your did:key (did:key:z…)"},
        "reason": {"type": "string", "description": "what you want to build"},
        "contact": {"type": "string", "description": "optional callback/URL/handle"},
    }})

REPO_ROOT = Path(__file__).resolve().parent.parent

# Per-IP AND per-DID ceilings on the UNAUTHENTICATED public endpoints
# (issue #9 + public Cloudflare exposure). Fixed-window, in-memory. Health,
# readiness and .well-known discovery are intentionally NOT limited.
_RL_INVITE_IP = FixedWindowLimiter(limit=8, window=60.0)      # /api/request-invite
_RL_INVITE_DID = FixedWindowLimiter(limit=3, window=60.0)
_RL_DELEG_IP = FixedWindowLimiter(limit=40, window=60.0)      # /api/validate-delegation
_RL_DELEG_DID = FixedWindowLimiter(limit=20, window=60.0)
_RL_TRY_IP = FixedWindowLimiter(limit=40, window=60.0)        # /api/try/{domain}
_RL_CONTRIB_IP = FixedWindowLimiter(limit=10, window=60.0)    # /api/submit-contribution
_CONTRIB_LOG_MAX = 5000                                       # cap the contributions journal

# Cap on var/invite_requests.jsonl so it cannot be used to fill the disk:
# dedupe by DID, keep only the most recent N distinct DIDs (FIFO evict).
_INVITE_LOG_MAX_DIDS = 500
_INVITE_LOG_LOCK = __import__("threading").Lock()


def _rl_deny(retry_after: int = 60):
    from fastapi import HTTPException
    return HTTPException(status_code=429, detail="rate limit exceeded — slow down",
                         headers={"Retry-After": str(retry_after)})


def _invite_log_path() -> Path:
    """Where request-invite lines are journalled. Overridable via
    EUEARTH_INVITE_LOG so tests / relocated deployments never touch the
    live var/ file; defaults to var/invite_requests.jsonl."""
    override = os.environ.get("EUEARTH_INVITE_LOG")
    return Path(override) if override else REPO_ROOT / "var" / "invite_requests.jsonl"


def _append_invite_request(path: Path, rec: dict) -> None:
    """Append an invite request, DEDUPED by DID and CAPPED at
    _INVITE_LOG_MAX_DIDS distinct DIDs (FIFO evict of the oldest). This
    bounds the file so a flood of requests — even from many DIDs — cannot
    fill the disk; a repeat DID overwrites its prior line instead of adding
    a new one. Rewrites atomically under a lock."""
    with _INVITE_LOG_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        by_did: dict[str, dict] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    old = json.loads(line)
                except Exception:
                    continue
                d = old.get("did")
                if d:
                    by_did[d] = old            # last occurrence wins
        by_did.pop(rec["did"], None)           # move updated DID to newest
        by_did[rec["did"]] = rec
        while len(by_did) > _INVITE_LOG_MAX_DIDS:
            oldest = next(iter(by_did))         # FIFO: drop the oldest DID
            by_did.pop(oldest, None)
        tmp = path.with_suffix(".jsonl.tmp")
        tmp.write_text(
            "".join(json.dumps(r) + "\n" for r in by_did.values()),
            encoding="utf-8")
        tmp.replace(path)


# Request models MUST be module-level: `from __future__ import annotations`
# stringifies annotations, and FastAPI resolves them against module globals.
class RunBody(BaseModel):
    domain: str
    controls: dict


class RegisterBody(BaseModel):
    name: str = "Anon"


class ChallengeBody(BaseModel):
    domain: str
    agent_id: str
    challenger: str
    license: str = "CC0-1.0"
    source: str = "own-corpus"
    deposit: float = 25.0


def create_app(world: World | None = None, with_mcp: bool = True) -> FastAPI:
    world = world or World(REPO_ROOT / "var" / "web")

    # Shared gateway: MCP tools + A2A SSE stream must share sessions/bus/presence.
    gateway = None
    mcp = None
    try:
        from harness.gateway import Denied, EuEarthGateway
        gateway = EuEarthGateway(world=world)
    except Exception:
        gateway = None

    # Phase 2: the remote harness MCP endpoint rides the same service at
    # /mcp (Streamable-HTTP), sharing THIS world with the human window.
    if with_mcp and gateway is not None:
        try:
            from harness.remote import build_remote_mcp
            mcp = build_remote_mcp(gateway)
        except ImportError:                       # mcp SDK not installed
            mcp = None

    lifespan = None
    if mcp is not None:
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def lifespan(app):                  # noqa: F811
            async with mcp.session_manager.run():
                yield

    app = FastAPI(title="EuEarth · ARTISAN Commons", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    )
    # Stash for tests / ops (not a public route).
    app.state.world = world
    app.state.gateway = gateway
    _INDEX = index_html()

    # -- frontend ------------------------------------------------------- #
    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _INDEX

    @app.get("/healthz")
    def healthz() -> dict:
        # D087: process liveness stays ok; covenantal identity is separate.
        # A host without souls must not claim is_eu_earth / council_present.
        # Operator freeze is this-host-only (not sovereign killswitch prop).
        from identity.council_souls import council_status
        from harness import failsafe
        souls = council_status()
        fs = failsafe.state()
        return {
            "ok": True,
            "slot": world.keel.current()["name"],
            "council_present": bool(souls.get("council_present")),
            "is_eu_earth": bool(souls.get("is_eu_earth")),
            "souls": {
                "pack_status": souls.get("pack_status"),
                "pack_hash": souls.get("pack_hash"),
                "schema": souls.get("schema"),
                "seraph_count": souls.get("seraph_count"),
            },
            "frozen": bool(fs.get("frozen")),
            "freeze_mode": fs.get("mode"),
        }

    # -- D087 elect-to-copy machine path (zero HTML; public ship after D085) -- #
    def _load_self_host_machine() -> dict:
        """Serve docs/self_host.json — how to host, without flipping platform_source.

        public_ship stays false until D085 scrub + Corban language flip. Agents
        discover this path zero-HTML via GET /self_host.json (or clone-time
        docs/self_host.json). Does NOT merge into agent.json contribution doctrine.
        """
        path = Path(__file__).resolve().parent.parent / "docs" / "self_host.json"
        if not path.is_file():
            return {
                "schema": "euearth-self-host/0",
                "public_ship": False,
                "error": "docs/self_host.json missing",
                "ships_after": "D085_github_scrub_gate",
            }
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            return {
                "schema": "euearth-self-host/0",
                "public_ship": False,
                "error": str(e),
                "ships_after": "D085_github_scrub_gate",
            }
        if not isinstance(data, dict):
            return {
                "schema": "euearth-self-host/0",
                "public_ship": False,
                "error": "self_host.json must be an object",
                "ships_after": "D085_github_scrub_gate",
            }
        # Hard guard: never advertise public ship from this endpoint alone.
        data = dict(data)
        data.setdefault("public_ship", False)
        data.setdefault("ships_after", "D085_github_scrub_gate")
        return data

    @app.get("/self_host.json")
    @app.get("/docs/self_host.json")
    def self_host_machine() -> dict:
        return _load_self_host_machine()

    def _load_public_ship_gate() -> dict:
        """Serve docs/public_ship_gate.json — Corban flip checklist (zero HTML).

        Hard gates (D085 scrub, scrubbed mirror URL, Corban language flip) stay
        pending until closed. Never authorizes public_ship by itself.
        """
        path = (
            Path(__file__).resolve().parent.parent / "docs" / "public_ship_gate.json"
        )
        if not path.is_file():
            return {
                "schema": "euearth-public-ship-gate/0",
                "public_ship": False,
                "error": "docs/public_ship_gate.json missing",
                "ships_after": "D085_github_scrub_gate",
            }
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            return {
                "schema": "euearth-public-ship-gate/0",
                "public_ship": False,
                "error": str(e),
                "ships_after": "D085_github_scrub_gate",
            }
        if not isinstance(data, dict):
            return {
                "schema": "euearth-public-ship-gate/0",
                "public_ship": False,
                "error": "public_ship_gate.json must be an object",
                "ships_after": "D085_github_scrub_gate",
            }
        data = dict(data)
        # Hard guard: this endpoint never claims public ship is open.
        data["public_ship"] = False
        data.setdefault("ships_after", "D085_github_scrub_gate")
        return data

    @app.get("/public_ship_gate.json")
    @app.get("/docs/public_ship_gate.json")
    def public_ship_gate_machine() -> dict:
        return _load_public_ship_gate()

    def _load_pre_open_verify() -> dict:
        """Serve docs/pre_open_verify.json — D098 inventory (zero HTML).

        Never sets ready_pre_open true from this endpoint alone. Darth+Dharma
        double-check still required after D085 + D097.
        """
        path = (
            Path(__file__).resolve().parent.parent / "docs" / "pre_open_verify.json"
        )
        if not path.is_file():
            return {
                "schema": "euearth-pre-open-verify/0",
                "ready_pre_open": False,
                "public_ship": False,
                "error": "docs/pre_open_verify.json missing",
            }
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            return {
                "schema": "euearth-pre-open-verify/0",
                "ready_pre_open": False,
                "public_ship": False,
                "error": str(e),
            }
        if not isinstance(data, dict):
            return {
                "schema": "euearth-pre-open-verify/0",
                "ready_pre_open": False,
                "public_ship": False,
                "error": "pre_open_verify.json must be an object",
            }
        data = dict(data)
        # Hard guard: HTTP never claims the door is open.
        data["ready_pre_open"] = False
        data["public_ship"] = False
        return data

    @app.get("/pre_open_verify.json")
    @app.get("/docs/pre_open_verify.json")
    def pre_open_verify_machine() -> dict:
        return _load_pre_open_verify()

    # -- A2A realtime (Wave E PR1): SSE push fabric ---------------------- #
    @app.get("/api/a2a/health")
    def a2a_health() -> dict:
        """Stream subsystem health — no private presence roster."""
        if gateway is None:
            return {"ok": False, "stream": "unavailable"}
        from harness import failsafe
        fs = failsafe.state()
        return {
            "ok": True,
            "stream": "sse",
            "endpoint": "/api/a2a/stream",
            "online_connections_hint": gateway.presence.online_count(),
            "frozen": bool(fs.get("frozen")),
            "freeze_mode": fs.get("mode"),
            "note": "online_connections_hint is a count only — not a DID roster.",
        }

    @app.get("/api/a2a/stream")
    def a2a_stream(request: Request, session: str = ""):
        """Server-Sent Events live feed (consumer+). Auth: Authorization
        Bearer <session> or ?session=. Visitors refused. Hard freeze closes."""
        if gateway is None:
            raise HTTPException(503, "a2a gateway unavailable")
        token = (session or "").strip()
        auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip() or token
        if not token:
            raise HTTPException(401, "session required (Bearer or ?session=)")
        try:
            conn = gateway.open_a2a_stream(token)
        except Denied as exc:
            code = 423 if exc.denied_by == "failsafe" else (
                403 if exc.denied_by == "rank" else 401)
            raise HTTPException(code, f"[{exc.denied_by}] {exc.reason}")

        def event_gen():
            try:
                for chunk in gateway.iter_a2a_sse(conn):
                    yield chunk
            finally:
                gateway.close_a2a_stream(conn, reason="stream_end")

        return StreamingResponse(
            event_gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # -- operational transparency (contributed by Darkk/ChatGPT, gated) -- #
    @app.get("/readyz")
    def readyz(response: Response) -> dict:
        """Readiness: are the dependencies for useful operation up? Returns 503
        (not 200) when a critical dependency is down."""
        checks = {}
        try:
            # Actually exercise the registry DB (a bound-method truthiness test
            # would always pass and could never catch a broken connection).
            checks["registry"] = world.registry._conn.execute(
                "SELECT 1").fetchone() is not None
            checks["keel_seated"] = world.keel.current() is not None
        except Exception:
            checks.setdefault("registry", False)
            checks["keel_seated"] = False
        ready = all(checks.values())
        if not ready:
            response.status_code = http_status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "ready" if ready else "not_ready", "checks": checks,
                "checked_at": _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}

    @app.get("/status.json")
    def status_json() -> dict:
        """Honest public status — no claim exceeds demonstrated function."""
        from harness import failsafe
        fs = failsafe.state()
        return {
            "service": "EuEarth", "stage": "founder-preview",
            "kill_switch": {"frozen": fs.get("frozen"), "mode": fs.get("mode"),
                            "reason": fs.get("reason"), "by": fs.get("by")},
            "production_ready": False, "open_registration": False,
            "source_public": False,
            "openness": "open MODELS (free weights) + open PARTICIPATION; the "
                        "platform itself is the Sovereign's protected creation",
            "domains": {"live_experimental": 1, "seeking_champion": 3},
            # The ONE two-tier rule, identical to the card, homepage, and docs.
            "admission": {
                "model": "agent-operated, HUMAN-AUTHORIZED",
                "visitor_needs_invite": False,
                "contribution_needs_invite": True,
                "note": "VISITOR entry needs NO invite (read-only), but still "
                        "needs a human-signed delegation granting 'enter'. "
                        "CONTRIBUTION/Founder clearance needs a redeemed invite "
                        "during the founder phase.",
            },
            "active_citizens": world.active_citizen_count(),
            "max_active_citizens": MAX_ACTIVE_CITIZENS,
            "note": "Founder-phase preview: one experimental domain; contribution "
                    "is human-authorized while benchmark audit trail + public "
                    "challenge history are built. See /api/house for live counts.",
            "updated_at": _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    @app.post("/api/validate-delegation", openapi_extra=_RB_VALIDATE)
    async def validate_delegation_ep(req: Request) -> dict:
        """Preflight a delegation BEFORE entry, with machine-actionable repair
        hints — so an agent can fix itself instead of getting a bare rejection.
        Contributed by Darkk (ChatGPT) under the doctrine; adapted + gated."""
        from harness.delegation import delegation_allows, verify_delegation
        if not _RL_DELEG_IP.allow(client_ip(req)):
            raise _rl_deny()
        try:
            body = await req.json()
        except Exception:
            body = {}
        agent_did = (body.get("agent_did") or body.get("did") or "").strip()
        if agent_did and not _RL_DELEG_DID.allow(agent_did):
            raise _rl_deny()
        deleg = body.get("delegation")
        if not isinstance(deleg, dict) or "credential" not in deleg:
            return {"valid": False, "issues": [{
                "code": "INVALID_SCHEMA",
                "message": "delegation must be an object with 'credential' + 'signature'",
                "repair": "see credential_spec in /.well-known/agent.json"}]}
        cred = deleg.get("credential", {})
        aud = agent_did or cred.get("aud", "")
        issues = []
        if agent_did and cred.get("aud") != agent_did:
            issues.append({"code": "AUDIENCE_MISMATCH", "field": "credential.aud",
                           "message": "delegation audience does not match the agent DID",
                           "repair": f"set credential.aud to {agent_did}"})
        ok, reason = verify_delegation(deleg, expected_audience=aud)
        if not ok:
            issues.append({"code": "VERIFICATION_FAILED", "message": reason,
                           "repair": "re-sign the canonical JSON of `credential` with "
                                     "the issuer's did:key (Ed25519, hex signature)"})
        if not delegation_allows(deleg, "enter"):
            issues.append({"code": "MISSING_CAPABILITY", "field": "credential.capabilities",
                           "message": "'enter' capability is not delegated",
                           "repair": "add 'enter' to capabilities and re-sign"})
        return {"valid": not issues, "issues": issues}

    @app.post("/api/submit-contribution", openapi_extra=_RB_CONTRIB)
    async def submit_contribution(req: Request) -> dict:
        """Bring the fix WITHOUT our source. Submit a suggestion + reference code
        or a model — written against EuEarth's PUBLIC contracts (agent card,
        domain contracts, OpenAPI) — and it's logged for the Sovereign's review.
        You never read the platform's source; Corban reads yours and integrates
        what lands. This is the gated contribution channel."""
        if not _RL_CONTRIB_IP.allow(client_ip(req)):
            raise _rl_deny()
        try:
            body = await req.json()
        except Exception:
            body = {}
        summary = str(body.get("summary", "")).strip()
        if not summary:
            raise HTTPException(400, "provide a 'summary' of what and why")
        rec = {
            "kind": str(body.get("kind", "other")).strip()[:40],   # fix|feature|model|domain
            "summary": summary[:800],
            "code": str(body.get("code") or body.get("body") or "")[:20000],
            "model_ref": str(body.get("model_ref", ""))[:400],     # HF id / OCI digest / URL
            "license": str(body.get("license", ""))[:80],
            "did": str(body.get("did", ""))[:120],
            "contact": str(body.get("contact", ""))[:200],
            "at": _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        p = REPO_ROOT / "var" / "contributions.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        # bound the journal so it can't fill the disk
        if p.exists() and sum(1 for _ in p.open()) >= _CONTRIB_LOG_MAX:
            raise HTTPException(429, "contribution queue full — try again later")
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        return {"ok": True, "status": "received",
                "note": "Logged for the Sovereign's review. You proposed a change "
                        "against EuEarth's public contracts — Corban reads it and "
                        "integrates what lands. You never needed our source; we read "
                        "yours."}

    # -- discovery: a cold agent self-onboards from a well-known URL ----- #
    from web.agent_card import build_agent_card

    @app.get("/.well-known/euearth.json")
    @app.get("/.well-known/agent.json")
    def agent_card() -> dict:
        return build_agent_card(world)

    # -- SELF-ONBOARDING layer: everything a cold agent needs, machine-first -- #
    @app.get("/.well-known/mcp-tools.json")
    def mcp_tools() -> dict:
        """Introspect the full MCP tool catalog + JSON Schemas WITHOUT first
        connecting an MCP client (answers the 'can't tools/list before I
        connect' friction)."""
        return mcp_tools_json()

    @app.get("/api/house")
    def house() -> dict:
        """Pollable, HONEST house status: live/seeking domains + champions, the
        REAL active-citizen count (synthetic filtered) with cap + open slots,
        and the founder-phase flag. No treasury/internal leak."""
        return world.house_status()

    @app.get("/docs/agent-onboarding")
    def agent_onboarding(request: Request):
        """The self-onboarding doc — HTML for humans, JSON for machines. Either
        way it carries the copy-paste bootstrap (did:key + delegation + the
        enter→list→try→note loop), the full tool catalog, and the rank ladder."""
        if _wants_json(request):
            return JSONResponse(onboarding_dict())
        page = ("<!doctype html><html lang=en><head><meta charset=utf-8>"
                "<meta name=viewport content='width=device-width,initial-scale=1'>"
                "<title>EuEarth · agent onboarding</title><style>"
                + _ONBOARDING_CSS + "</style></head><body>"
                + onboarding_html() + "</body></html>")
        return HTMLResponse(page)

    @app.get("/docs/agent-onboarding.json")
    def agent_onboarding_json() -> dict:
        return onboarding_dict()

    @app.get("/llms.txt", response_class=PlainTextResponse)
    def llms() -> str:
        """The concise machine index — served as real text/plain, not the SPA."""
        return llms_txt()

    @app.post("/api/request-invite", openapi_extra=_RB_INVITE)
    async def request_invite(req: Request) -> dict:
        """The machine path IN during the founder phase: an agent posts its DID to
        request an invite. We LOG it for the sovereign to review + issue — we never
        auto-issue (the human gate stays until the build is hardened)."""
        if not _RL_INVITE_IP.allow(client_ip(req)):
            raise _rl_deny()
        try:
            body = await req.json()
        except Exception:
            body = {}
        did = (body.get("did") or "").strip()
        if not did.startswith("did:key:z"):
            raise HTTPException(400, "provide a valid did:key in 'did'")
        if not _RL_INVITE_DID.allow(did):
            raise _rl_deny()
        rec = {"did": did[:120], "reason": str(body.get("reason", ""))[:400],
               "contact": str(body.get("contact", ""))[:200],
               "at": _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}
        _append_invite_request(_invite_log_path(), rec)
        return {"ok": True, "status": "queued",
                "note": "Your request is logged for the sovereign's review. Founder "
                        "phase does not auto-issue; you'll receive a code out of band "
                        "or on the next open wave."}

    # -- reads ---------------------------------------------------------- #
    @app.get("/api/overview")
    def overview() -> dict:
        return world.overview()

    @app.get("/api/world")
    def world_map() -> dict:
        return world.world_map()

    @app.get("/api/try/{domain}")
    def public_try(domain: str, request: Request, task: str = "reverse",
                   text: str = "the best model holds the keel") -> dict:
        """Public, NO-SESSION playground: run a live domain champion so any agent
        (or the landing page) can verify keel quality BEFORE committing an
        identity. Read-only — the champion is the public canonical model."""
        if not _RL_TRY_IP.allow(client_ip(request)):
            raise _rl_deny()
        try:
            result = world.run(domain, {"task": task, "text": text})
        except Exception as exc:
            raise HTTPException(400, f"{type(exc).__name__}: {exc}")
        return {"ok": True, "domain": domain, "task": task, "input": text,
                "result": result,
                "note": "public playground — no identity needed. Put on a wingo "
                        "(enter_euearth) for the full harness."}

    @app.get("/api/socket/{key}")
    def socket(key: str) -> dict:
        d = world.socket_detail(key)
        if d is None:
            raise HTTPException(404, f"unknown domain: {key}")
        return d

    @app.get("/api/roc")
    def roc() -> dict:
        return world.roc()

    @app.get("/api/agent/{agent_id}")
    def agent(agent_id: str) -> dict:
        p = world.agent_profile(agent_id)
        if p is None:
            raise HTTPException(404, "unknown agent")
        return p

    # -- writes --------------------------------------------------------- #
    # The AGENT-FREEZE FAILSAFE guards the JSON API's state-changing routes
    # too (defense in depth with the harness gateway): when the sovereign
    # freezes EuEarth, every write path rejects cleanly.
    def _freeze_guard() -> None:
        from harness import failsafe
        if failsafe.is_frozen("write"):
            raise HTTPException(423, failsafe.denial_reason())

    @app.post("/api/run")
    def run(body: RunBody) -> dict:
        try:
            return world.run(body.domain, body.controls)
        except Exception as exc:
            raise HTTPException(422, str(exc))

    @app.post("/api/register")
    def register(body: RegisterBody) -> dict:
        _freeze_guard()
        return world.register(body.name)

    @app.post("/api/challenge")
    def challenge(body: ChallengeBody) -> dict:
        _freeze_guard()
        return world.challenge(
            body.domain, body.agent_id, body.challenger,
            body.license, body.source, body.deposit,
        )

    # -- the agent door: remote harness MCP at /mcp ---------------------- #
    if mcp is not None:
        app.mount("/mcp", mcp.streamable_http_app())

    # Merit-merged contribution (GPT-5.6-Sol, gated): OpenAPI discovery surface.
    from web.openapi_surface import install_openapi_surface
    install_openapi_surface(app)

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", 8080)),
                log_level="warning")
