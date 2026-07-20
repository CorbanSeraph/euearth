#!/usr/bin/env python3
"""RATE-LIMIT + invite-log cap regression (issue #9 / public exposure).

Drives the public HTTP surface with a FastAPI TestClient (a throwaway world
in a temp dir) and asserts:

  * /api/request-invite, /api/validate-delegation, /api/try/{domain} return
    HTTP 429 once the per-IP window is exhausted;
  * /healthz and /.well-known/agent.json are NOT rate-limited;
  * var/invite_requests.jsonl is DEDUPED by DID and CAPPED (a flood of
    distinct DIDs from one IP is throttled AND the file stays bounded).

    .venv/bin/python stress/test_ratelimit.py     # exit 0 = all invariants held
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

RESULTS: list[tuple[str, bool]] = []


def check(name: str, ok: bool) -> None:
    RESULTS.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")


def main() -> int:
    world_root = tempfile.mkdtemp(prefix="rl_world_")
    os.environ["ARTISAN_HARNESS_ROOT"] = world_root
    os.environ["EUEARTH_FOUNDER_PHASE"] = "1"

    # Point the invite log into the throwaway world so the real var/ file is
    # NEVER touched (env override read by web.app._invite_log_path).
    log_path = Path(world_root) / "invite_requests.jsonl"
    os.environ["EUEARTH_INVITE_LOG"] = str(log_path)

    import importlib
    appmod = importlib.import_module("web.app")
    # Shrink the cap so the test is fast.
    appmod._INVITE_LOG_MAX_DIDS = 5

    from fastapi.testclient import TestClient
    from web.world import World
    app = appmod.create_app(World(Path(world_root) / "web"), with_mcp=False)
    client = TestClient(app)

    # -- request-invite per-IP 429 ------------------------------------- #
    codes = []
    for i in range(40):
        r = client.post("/api/request-invite",
                        json={"did": f"did:key:zFlood{i}"},
                        headers={"cf-connecting-ip": "9.9.9.9"})
        codes.append(r.status_code)
    check("request-invite eventually 429s a hammering IP", 429 in codes)
    check("request-invite served some before limiting", 200 in codes)

    # -- invite log is deduped + capped -------------------------------- #
    lines = [l for l in log_path.read_text().splitlines() if l.strip()] \
        if log_path.exists() else []
    dids = {__import__("json").loads(l)["did"] for l in lines}
    check("invite log capped at _INVITE_LOG_MAX_DIDS",
          len(lines) <= appmod._INVITE_LOG_MAX_DIDS)
    check("invite log has no duplicate DIDs", len(dids) == len(lines))

    # repeat DID does not grow the file
    before = len(lines)
    for _ in range(3):
        client.post("/api/request-invite",
                    json={"did": "did:key:zRepeat"},
                    headers={"cf-connecting-ip": "8.8.8.8"})
    after_lines = [l for l in log_path.read_text().splitlines() if l.strip()]
    check("repeat DID dedupes (file bounded)",
          len(after_lines) <= appmod._INVITE_LOG_MAX_DIDS)

    # -- try/{domain} per-IP 429 --------------------------------------- #
    try_codes = [client.get("/api/try/text-transform",
                            headers={"cf-connecting-ip": "7.7.7.7"}).status_code
                 for _ in range(60)]
    check("try/{domain} eventually 429s a hammering IP", 429 in try_codes)

    # -- validate-delegation per-IP 429 -------------------------------- #
    vd_codes = [client.post("/api/validate-delegation", json={"did": "did:key:zX"},
                            headers={"cf-connecting-ip": "6.6.6.6"}).status_code
                for _ in range(60)]
    check("validate-delegation eventually 429s a hammering IP", 429 in vd_codes)

    # -- health / well-known NOT limited ------------------------------- #
    health = [client.get("/healthz",
                         headers={"cf-connecting-ip": "5.5.5.5"}).status_code
              for _ in range(80)]
    check("/healthz never rate-limited", all(c == 200 for c in health))
    wk = [client.get("/.well-known/agent.json",
                     headers={"cf-connecting-ip": "5.5.5.5"}).status_code
          for _ in range(80)]
    check("/.well-known/agent.json never rate-limited", all(c == 200 for c in wk))

    passed = sum(1 for _, ok in RESULTS if ok)
    print(f"\n=== {passed}/{len(RESULTS)} rate-limit invariants held ===")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
