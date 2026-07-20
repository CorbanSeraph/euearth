#!/usr/bin/env python3
"""PROVE D087 — elect-to-copy self-host path (anti-map, zero HTML).

What is proven, without a browser and without flipping platform_source:
  1. CLONE-TIME machine path: docs/self_host.json exists, is valid JSON,
     declares elective covenant + ships_after D085 + souls required.
  2. HUMAN + AGENT guides exist (docs/SELF_HOST.md, SELF_HOST_AGENT.md, MIRROR.md).
  2b/2c. Docker bake-check + operator-local freeze (this host only).
      Freeze live round-trip loads failsafe.py BY FILE (Phase 2.13) — no
      `import harness.failsafe` / fastapi for that sub-step.
  2d. PUBLIC SHIP GATE: docs/public_ship_gate.json hard gates still pending;
     language_flip_owner = Corban; this_branch_must_not blocks premature flip.
  2e. OPERATOR VERIFY CLI (Phase 2.16): python -m identity.council_souls verify
     → ready_local_elect_host true (souls+docs+freeze+moneyless+pre_open machine);
       ready_pre_open false until D085/D097/D098;
     public_ship never authorized by this CLI; fiat rails fail-closed.
  2f. OFFLINE HANDOFF (Phase 2.12): git bundle create → clone → verify on the
     restored tree; public_redistribute stays false (pre-scrub / gh-401 path).
  3. SOUL PACK present (identity/council_souls) → council_present true.
  4. LIVE HTTP (uvicorn in-process): GET /self_host.json + /public_ship_gate.json
     + GET /healthz — zero HTML, healthz requires council_present + is_eu_earth.
     (HTTP steps still need fastapi in the environment.)
  5. GOVERNANCE GUARD: /.well-known/agent.json still has platform_source closed
     (public language flip is AFTER D085 + Corban; this prove must not flip it).

Run:  .venv/bin/python demo/prove_d087_self_host.py
  (or system python3 after deps; freeze sub-step is stdlib-only via file load)
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

CHECKS: list[tuple[str, bool]] = []


def banner(text: str) -> None:
    print(f"\n=== {text} " + "=" * max(0, 66 - len(text)))


def check(label: str, passed: bool) -> None:
    CHECKS.append((label, passed))
    print(f"    [{'PASS' if passed else 'FAIL'}] {label}")


def main() -> int:
    banner("1. CLONE-TIME machine path (zero HTML)")
    machine_path = REPO_ROOT / "docs" / "self_host.json"
    check("docs/self_host.json exists", machine_path.is_file())
    data: dict = {}
    if machine_path.is_file():
        try:
            data = json.loads(machine_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    check("self_host.json valid object", isinstance(data, dict) and bool(data))
    check("schema euearth-self-host/0", data.get("schema") == "euearth-self-host/0")
    check("elective true", data.get("elective") is True)
    check("ships_after D085", "D085" in str(data.get("ships_after") or ""))
    check("public_ship false (pre-scrub)", data.get("public_ship") is False)
    check("souls.required true", bool((data.get("souls") or {}).get("required")))
    check(
        "anti_map.zero_html true",
        bool((data.get("anti_map") or {}).get("zero_html")),
    )
    check(
        "mirror.git_url null until scrub",
        (data.get("mirror") or {}).get("git_url") in (None, "", "null"),
    )

    banner("2. Guides on disk")
    for rel in (
        "docs/SELF_HOST.md",
        "docs/SELF_HOST_AGENT.md",
        "docs/MIRROR.md",
        "identity/council_souls/manifest.stub.json",
        "identity/council_souls/__init__.py",
        "Dockerfile",
    ):
        check(rel, (REPO_ROOT / rel).is_file())

    banner("2b. Docker bake-check (souls travel with image)")
    df_text = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8") if (
        REPO_ROOT / "Dockerfile"
    ).is_file() else ""
    check(
        "Dockerfile bake-check imports council_souls",
        "council_souls" in df_text and "council_status" in df_text,
    )
    check(
        "Dockerfile bake-check asserts council_present",
        "council_present" in df_text and "assert" in df_text,
    )
    check(
        "self_host.json documents docker_bake_check",
        isinstance(data.get("docker_bake_check"), dict)
        and "council_present" in str((data.get("docker_bake_check") or {}).get("requires")),
    )
    check(
        "killswitch not auto-propagated (honest exclude)",
        "automatic_sovereign_killswitch_propagation"
        in (data.get("not_included") or []),
    )
    check(
        "fiat money rail not included (moneyless)",
        "fiat_money_wallet_rail" in (data.get("not_included") or []),
    )
    econ = data.get("economics") or {}
    check(
        "economics mode moneyless",
        str(econ.get("mode") or "").lower() == "moneyless",
    )
    check(
        "economics currency Kabad",
        "kabad" in str(econ.get("currency") or "").lower()
        or "king" in str(econ.get("currency") or "").lower(),
    )

    banner("2c. Operator freeze (this host only — Phase 2.8/2.13 file-load)")
    ofrz = data.get("operator_freeze") or {}
    check("operator_freeze block present", isinstance(ofrz, dict) and bool(ofrz))
    check(
        "operator_freeze scope this_host_only",
        ofrz.get("scope") == "this_host_only",
    )
    check(
        "operator_freeze does not claim sovereign prop",
        ofrz.get("propagates_from_sovereign") is False,
    )
    check(
        "operator_freeze module harness.failsafe",
        ofrz.get("module") == "harness.failsafe",
    )
    cli = ofrz.get("cli") or []
    check(
        "operator_freeze CLI has status+freeze+unfreeze",
        any("status" in str(c) for c in cli)
        and any("freeze" in str(c) for c in cli)
        and any("unfreeze" in str(c) for c in cli),
    )
    failsafe_py = REPO_ROOT / "harness" / "failsafe.py"
    check("harness/failsafe.py on disk", failsafe_py.is_file())
    if failsafe_py.is_file():
        fs_txt = failsafe_py.read_text(encoding="utf-8")
        check(
            "failsafe CLI documents freeze/status/unfreeze",
            "def freeze" in fs_txt and "status" in fs_txt and "unfreeze" in fs_txt,
        )
    # LIVE freeze: load failsafe.py BY FILE (Phase 2.13).
    # Do NOT `import harness.failsafe` — harness/__init__.py pulls web→fastapi;
    # cold elect hosts often lack deps; failsafe.py itself is stdlib-only.
    failsafe_mod = None
    if failsafe_py.is_file():
        try:
            spec = importlib.util.spec_from_file_location(
                "euearth_prove_failsafe", failsafe_py
            )
            if spec is None or spec.loader is None:
                raise ImportError(f"cannot load failsafe from {failsafe_py}")
            failsafe_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(failsafe_mod)
            check("failsafe live load=file (no harness package)", True)
        except Exception as e:  # noqa: BLE001 — prove must record FAIL not crash
            check(f"failsafe live load=file ({type(e).__name__}: {e})", False)
            failsafe_mod = None

    prev_path = os.environ.get("EUEARTH_FREEZE_FILE")
    tmp_flag = Path(tempfile.mkdtemp(prefix="d087_freeze_")) / "EUEARTH_FROZEN"
    try:
        if failsafe_mod is None:
            check("failsafe live round-trip (no module)", False)
        else:
            os.environ["EUEARTH_FREEZE_FILE"] = str(tmp_flag)
            st0 = failsafe_mod.state()
            check("failsafe.state() returns dict", isinstance(st0, dict))
            fr = failsafe_mod.freeze(
                "d087 prove operator freeze", mode="soft", by="prove"
            )
            check(
                "failsafe.freeze soft sets frozen",
                bool(fr.get("frozen") or failsafe_mod.state().get("frozen")),
            )
            st1 = failsafe_mod.state()
            check("failsafe frozen after freeze", bool(st1.get("frozen")))
            # by=prove (not sovereign) can unfreeze its own freeze
            failsafe_mod.unfreeze(by="prove")
            st2 = failsafe_mod.state()
            check("failsafe unfreeze clears frozen", not bool(st2.get("frozen")))
    except Exception as e:  # noqa: BLE001 — prove must record FAIL not crash mid-suite
        check(f"failsafe live round-trip ({type(e).__name__}: {e})", False)
    finally:
        if prev_path is None:
            os.environ.pop("EUEARTH_FREEZE_FILE", None)
        else:
            os.environ["EUEARTH_FREEZE_FILE"] = prev_path
        shutil.rmtree(tmp_flag.parent, ignore_errors=True)

    banner("2d. Public ship gate (Phase 2.9 — Corban flip checklist, still dark)")
    gate_path = REPO_ROOT / "docs" / "public_ship_gate.json"
    check("docs/public_ship_gate.json exists", gate_path.is_file())
    gate: dict = {}
    if gate_path.is_file():
        try:
            gate = json.loads(gate_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            gate = {}
    check(
        "public_ship_gate schema",
        gate.get("schema") == "euearth-public-ship-gate/0",
    )
    check("public_ship_gate public_ship false", gate.get("public_ship") is False)
    check(
        "public_ship_gate language_flip_owner Corban",
        str(gate.get("language_flip_owner") or "").lower() == "corban",
    )
    hard = gate.get("hard_gates") or []
    hard_ids = {str(g.get("id") or "") for g in hard if isinstance(g, dict)}
    check(
        "public_ship_gate hard D085+D097+D098+mirror+corban_flip",
        "D085" in hard_ids
        and "D097" in hard_ids
        and "D098" in hard_ids
        and "scrubbed_mirror_url" in hard_ids
        and "corban_language_flip" in hard_ids,
    )
    check(
        "all hard_gates still pending (no premature open)",
        all(
            (g.get("status") == "pending")
            for g in hard
            if isinstance(g, dict) and g.get("required")
        ),
    )
    check(
        "self_host.json points at public_ship_gate",
        "public_ship_gate" in data
        and "public_ship_gate.json"
        in str((data.get("public_ship_gate") or {}).get("machine") or ""),
    )
    must_not = " ".join(str(x) for x in (gate.get("this_branch_must_not") or []))
    check(
        "this_branch_must_not blocks platform_source flip",
        "platform_source" in must_not.lower(),
    )

    banner("2e. Operator verify CLI (Phase 2.16 — cold-clone + history + harness cap)")
    from identity.council_souls import (
        assert_council_present,
        council_status,
        operator_verify,
    )

    ov_report = operator_verify(REPO_ROOT)
    check(
        "operator_verify schema",
        ov_report.get("schema") == "euearth-operator-verify/0",
    )
    check(
        "operator_verify phase 2.16",
        str(ov_report.get("phase") or "") == "2.16",
    )
    check(
        "operator_verify ready_local_elect_host",
        ov_report.get("ready_local_elect_host") is True,
    )
    check(
        "operator_verify public_ship never authorized",
        ov_report.get("public_ship_authorized") is False,
    )
    check(
        "operator_verify ready_public_redistribute false pre-D085",
        ov_report.get("ready_public_redistribute") is False,
    )
    check(
        "operator_verify ready_pre_open false pre-gates",
        ov_report.get("ready_pre_open") is False,
    )
    check(
        "operator_verify failed empty on good tree",
        ov_report.get("failed") == [],
    )
    ov_checks = {c.get("id"): c for c in (ov_report.get("checks") or [])}
    for cid in (
        "moneyless_fiat_rail_excluded",
        "moneyless_settlement_excluded",
        "economics_mode_moneyless",
        "economics_currency_kabad",
        "pre_open_verify_json",
        "pre_open_ready_false_until_gates",
        "pre_open_money_rail_inventory",
        "pre_open_identity_inventory",
        "pre_open_history_inventory",
        "pre_open_harness_capability_inventory",
        "gate_documents_D097",
        "gate_documents_D098",
    ):
        chk = ov_checks.get(cid) or {}
        check(f"operator_verify {cid}", bool(chk.get("ok")))
    pre = ov_report.get("pre_open") or {}
    check(
        "operator_verify pre_open schema",
        pre.get("schema") == "euearth-pre-open-verify/0",
    )
    check(
        "operator_verify pre_open lists wallet until D097",
        "harness/wallet.py" in (pre.get("money_rails_present") or []),
    )
    check(
        "operator_verify history inventory ran",
        pre.get("history_ran") is True,
    )
    check(
        "operator_verify history not clean pre-D085 (or hits reported)",
        pre.get("history_clean") is False or int(pre.get("history_hit_count") or 0) > 0,
    )
    check(
        "operator_verify harness capability hits pre-D097 (wallet_transfer etc)",
        int(pre.get("harness_financial_capability_hit_count") or 0) > 0
        or pre.get("harness_financial_capability_clean") is False,
    )
    check(
        "pre_open_verify.json documents history_scan",
        isinstance(
            json.loads(
                (REPO_ROOT / "docs" / "pre_open_verify.json").read_text(encoding="utf-8")
            ).get("history_scan"),
            dict,
        ),
    )
    check(
        "pre_open_verify.json documents harness_financial_capability",
        isinstance(
            json.loads(
                (REPO_ROOT / "docs" / "pre_open_verify.json").read_text(encoding="utf-8")
            ).get("harness_financial_capability"),
            dict,
        ),
    )
    check(
        "self_host.json documents operator_verify",
        isinstance(data.get("operator_verify"), dict)
        and (data.get("operator_verify") or {}).get("schema")
        == "euearth-operator-verify/0",
    )
    check(
        "operator_verify CLI entry in self_host.json",
        any(
            "identity.council_souls verify" in str(c)
            for c in ((data.get("operator_verify") or {}).get("cli") or [])
        ),
    )
    check(
        "operator_verify moneyless_fail_closed documented",
        bool((data.get("operator_verify") or {}).get("moneyless_fail_closed")),
    )
    check(
        "operator_verify pre_open_inventory documented",
        bool((data.get("operator_verify") or {}).get("pre_open_inventory")),
    )
    check(
        "docs/pre_open_verify.json present",
        (REPO_ROOT / "docs" / "pre_open_verify.json").is_file(),
    )

    banner("2f. Offline git-bundle elect (Phase 2.12 — pre-scrub / gh-401)")
    oh = data.get("offline_handoff") or {}
    check(
        "offline_handoff schema",
        oh.get("schema") == "euearth-offline-handoff/0",
    )
    check(
        "offline_handoff public_redistribute false",
        oh.get("public_redistribute") is False,
    )
    check(
        "offline_handoff restore has git clone + verify",
        any("git clone" in str(c) for c in (oh.get("restore") or []))
        and any("council_souls verify" in str(c) for c in (oh.get("restore") or [])),
    )
    check(
        "anti_map lists from_offline_bundle",
        isinstance((data.get("anti_map") or {}).get("from_offline_bundle"), list)
        and bool((data.get("anti_map") or {}).get("from_offline_bundle")),
    )
    # LIVE: complete bundle of HEAD (not thin origin/main..HEAD). Thin bundles
    # require a base with prerequisites; cold elect into empty dir needs full tip.
    bundle_tmp = Path(tempfile.mkdtemp(prefix="d087_bundle_"))
    try:
        bundle_path = bundle_tmp / "elect.bundle"
        clone_path = bundle_tmp / "euearth-local"
        create = subprocess.run(
            ["git", "bundle", "create", str(bundle_path), "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        check(
            "git bundle create elect.bundle",
            create.returncode == 0
            and bundle_path.is_file()
            and bundle_path.stat().st_size > 0,
        )
        clone = subprocess.run(
            ["git", "clone", str(bundle_path), str(clone_path)],
            capture_output=True,
            text=True,
        )
        clone_ok = (
            clone.returncode == 0
            and (clone_path / "docs" / "self_host.json").is_file()
        )
        check(
            "git clone from bundle",
            clone_ok,
        )
        if clone_ok:
            br = operator_verify(clone_path)
            check(
                "bundle-clone ready_local_elect_host",
                br.get("ready_local_elect_host") is True,
            )
            check(
                "bundle-clone public_ship never authorized",
                br.get("public_ship_authorized") is False,
            )
            check(
                "bundle-clone ready_public_redistribute false",
                br.get("ready_public_redistribute") is False,
            )
            check(
                "bundle-clone offline_handoff checks ok",
                "offline_handoff_schema" not in (br.get("failed") or [])
                and "offline_handoff_not_public" not in (br.get("failed") or []),
            )
        else:
            detail = (clone.stderr or clone.stdout or "")[:200]
            check(f"bundle-clone ready_local_elect_host ({detail})", False)
            check("bundle-clone public_ship never authorized", False)
            check("bundle-clone ready_public_redistribute false", False)
            check("bundle-clone offline_handoff checks ok", False)
    except Exception as e:  # noqa: BLE001
        check(f"offline bundle live prove ({type(e).__name__}: {e})", False)
    finally:
        shutil.rmtree(bundle_tmp, ignore_errors=True)

    banner("3. Soul runtime (in-process)")

    status = council_status()
    check("council_present", bool(status.get("council_present")))
    check("is_eu_earth", bool(status.get("is_eu_earth")))
    check("pack_hash 64 hex", len(str(status.get("pack_hash") or "")) == 64)
    try:
        assert_council_present()
        check("assert_council_present ok", True)
    except RuntimeError:
        check("assert_council_present ok", False)

    banner("4. LIVE HTTP anti-map (zero HTML)")
    state = Path(tempfile.mkdtemp(prefix="d087_prove_"))
    try:
        os.environ.setdefault("EUEARTH_FOUNDER_PHASE", "1")
        from fastapi.testclient import TestClient
        from web.app import create_app
        from web.world import World

        client = TestClient(create_app(World(state / "world")))

        r_sh = client.get("/self_host.json")
        check("GET /self_host.json 200", r_sh.status_code == 200)
        body_sh = r_sh.json() if r_sh.status_code == 200 else {}
        check(
            "HTTP self_host schema",
            body_sh.get("schema") == "euearth-self-host/0",
        )
        check(
            "HTTP self_host public_ship false",
            body_sh.get("public_ship") is False,
        )
        # Content-Type is JSON (not HTML)
        ctype = (r_sh.headers.get("content-type") or "").lower()
        check("self_host Content-Type JSON", "json" in ctype and "html" not in ctype)

        r_hz = client.get("/healthz")
        check("GET /healthz 200", r_hz.status_code == 200)
        hz = r_hz.json() if r_hz.status_code == 200 else {}
        check("healthz ok", hz.get("ok") is True)
        check("healthz council_present", hz.get("council_present") is True)
        check("healthz is_eu_earth", hz.get("is_eu_earth") is True)
        pack_hash = ((hz.get("souls") or {}).get("pack_hash")) or ""
        check("healthz souls.pack_hash", len(pack_hash) == 64)
        check("healthz has frozen key", "frozen" in hz)
        check("healthz has freeze_mode key", "freeze_mode" in hz)

        # alias path
        r_alias = client.get("/docs/self_host.json")
        check("GET /docs/self_host.json 200", r_alias.status_code == 200)

        r_gate = client.get("/public_ship_gate.json")
        check("GET /public_ship_gate.json 200", r_gate.status_code == 200)
        body_gate = r_gate.json() if r_gate.status_code == 200 else {}
        check(
            "HTTP public_ship_gate schema",
            body_gate.get("schema") == "euearth-public-ship-gate/0",
        )
        check(
            "HTTP public_ship_gate public_ship false",
            body_gate.get("public_ship") is False,
        )
        gctype = (r_gate.headers.get("content-type") or "").lower()
        check(
            "public_ship_gate Content-Type JSON",
            "json" in gctype and "html" not in gctype,
        )
        r_gate_alias = client.get("/docs/public_ship_gate.json")
        check("GET /docs/public_ship_gate.json 200", r_gate_alias.status_code == 200)

        r_po = client.get("/pre_open_verify.json")
        check("GET /pre_open_verify.json 200", r_po.status_code == 200)
        body_po = r_po.json() if r_po.status_code == 200 else {}
        check(
            "HTTP pre_open_verify schema",
            body_po.get("schema") == "euearth-pre-open-verify/0",
        )
        check(
            "HTTP pre_open_verify ready_pre_open false",
            body_po.get("ready_pre_open") is False,
        )
        po_ctype = (r_po.headers.get("content-type") or "").lower()
        check(
            "pre_open_verify Content-Type JSON",
            "json" in po_ctype and "html" not in po_ctype,
        )
        r_po_alias = client.get("/docs/pre_open_verify.json")
        check("GET /docs/pre_open_verify.json 200", r_po_alias.status_code == 200)

        banner("5. Governance guard — platform_source still closed")
        r_card = client.get("/.well-known/agent.json")
        check("GET agent.json 200", r_card.status_code == 200)
        card = r_card.json() if r_card.status_code == 200 else {}
        ps = str(card.get("platform_source") or "")
        check(
            "platform_source still closed (no D085 flip)",
            "closed" in ps.lower(),
        )
        check(
            "self_host NOT smuggled as open clone",
            "elective_covenantal" not in ps.lower(),
        )
    finally:
        shutil.rmtree(state, ignore_errors=True)

    banner("RESULT")
    passed = sum(1 for _, ok in CHECKS if ok)
    total = len(CHECKS)
    print(f"    {passed}/{total} checks passed")
    for label, ok in CHECKS:
        if not ok:
            print(f"    FAIL: {label}")
    if passed != total:
        return 1
    print("    D087 self-host anti-map PROVED (Pages dark; public ship after D085).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
