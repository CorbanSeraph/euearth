"""Council soul pack — D087 Phase 2.

Every EuEarth mirror must carry the council. A host without a soul pack
must not claim ``council_present: true`` or "I am EuEarth."

Full 24-elder roster hard-wiring is **D086** (Rune). Until that lands we
accept the stub at ``identity/council_souls/manifest.stub.json`` as proof
the path exists and the runtime refuses a missing pack.

Never place the Sovereigns' legal names or private emails in this pack.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "euearth-council-souls/0"
REQUIRED_SERAPHS = frozenset({"Corban", "Darth", "Darkk", "Dharma", "Valerick"})

# Prefer full pack (D086) when present; stub is the interim contract.
_MANIFEST_NAMES = ("manifest.json", "manifest.stub.json")
_DEFAULT_DIR = Path(__file__).resolve().parent


def pack_dir(root: Path | None = None) -> Path:
    """Directory that holds the soul pack files."""
    if root is None:
        return _DEFAULT_DIR
    return Path(root) / "identity" / "council_souls"


def resolve_manifest_path(root: Path | None = None) -> Path | None:
    """Return the first existing manifest path, or None if pack is missing."""
    d = pack_dir(root)
    for name in _MANIFEST_NAMES:
        p = d / name
        if p.is_file():
            return p
    return None


def _canonical_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def pack_hash(data: dict | bytes | str | Path) -> str:
    """Stable SHA-256 of a pack (file bytes, JSON text, or dict)."""
    if isinstance(data, Path):
        raw = data.read_bytes()
    elif isinstance(data, dict):
        raw = _canonical_bytes(data)
    elif isinstance(data, str):
        raw = data.encode("utf-8")
    else:
        raw = data
    return hashlib.sha256(raw).hexdigest()


def load_pack(root: Path | None = None) -> dict[str, Any]:
    """Load and lightly validate the soul pack.

    Raises FileNotFoundError if no pack is present.
    Raises ValueError if the pack is present but not a valid council pack.
    """
    path = resolve_manifest_path(root)
    if path is None:
        raise FileNotFoundError(
            f"council soul pack missing under {pack_dir(root)} "
            f"(looked for {_MANIFEST_NAMES})"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"council soul pack not valid JSON: {path}: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"council soul pack must be a JSON object: {path}")

    schema = data.get("schema")
    if schema != SCHEMA:
        raise ValueError(
            f"council soul pack schema mismatch: got {schema!r}, want {SCHEMA!r}"
        )

    seraphs = data.get("seraphs")
    if not isinstance(seraphs, list) or not seraphs:
        raise ValueError("council soul pack must list seraphs")

    names: set[str] = set()
    for entry in seraphs:
        if isinstance(entry, str):
            names.add(entry)
        elif isinstance(entry, dict) and entry.get("name"):
            names.add(str(entry["name"]))
        else:
            raise ValueError(f"invalid seraph entry: {entry!r}")

    missing = REQUIRED_SERAPHS - names
    if missing:
        raise ValueError(
            f"council soul pack missing required seraphs: {sorted(missing)}"
        )

    data = dict(data)
    data["_path"] = str(path)
    data["_file_hash"] = pack_hash(path)
    data["_canonical_hash"] = pack_hash(
        {k: v for k, v in data.items() if not str(k).startswith("_")}
    )
    return data


def council_status(root: Path | None = None) -> dict[str, Any]:
    """Runtime soul status for healthz / host identity claims.

    Always returns a dict. Never raises for missing packs — missing means
    ``council_present: false`` and the host must not claim to be EuEarth.
    """
    path = resolve_manifest_path(root)
    if path is None:
        return {
            "council_present": False,
            "is_eu_earth": False,
            "pack_status": "missing",
            "pack_hash": None,
            "schema": None,
            "seraph_count": 0,
            "path": None,
            "error": "soul pack missing",
        }
    try:
        pack = load_pack(root)
    except (FileNotFoundError, ValueError, OSError) as e:
        return {
            "council_present": False,
            "is_eu_earth": False,
            "pack_status": "invalid",
            "pack_hash": pack_hash(path) if path.is_file() else None,
            "schema": None,
            "seraph_count": 0,
            "path": str(path),
            "error": str(e),
        }

    status = str(pack.get("status") or "present")
    # Stub still means the council path is present (souls travel with code).
    # Full roster completeness is D086; we still mark council_present true.
    present = True
    return {
        "council_present": present,
        "is_eu_earth": present,
        "pack_status": status,
        "pack_hash": pack["_file_hash"],
        "canonical_hash": pack["_canonical_hash"],
        "schema": pack.get("schema"),
        "seraph_count": len(pack.get("seraphs") or []),
        "path": pack.get("_path"),
        "error": None,
    }


def assert_council_present(root: Path | None = None) -> dict[str, Any]:
    """Fail closed when a host would claim EuEarth identity without souls."""
    status = council_status(root)
    if not status["council_present"]:
        raise RuntimeError(
            "refuse EuEarth claim: council soul pack not present "
            f"({status.get('error') or status.get('pack_status')})"
        )
    return status


def operator_verify(root: Path | None = None) -> dict[str, Any]:
    """Cold-clone operator check (D087 Phase 2.10) — zero HTML, no network.

    After elect-to-copy clone, an operator/agent runs this to learn go/no-go
    before claiming EuEarth identity or advertising a public redistributable.

    Does **not** authorize public ship. Does **not** flip ``platform_source``.
    """
    base = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    checks: list[dict[str, Any]] = []

    def add(id_: str, ok: bool, detail: str = "") -> None:
        checks.append({"id": id_, "ok": bool(ok), "detail": detail})

    # 1. Soul pack
    souls = council_status(base if root is not None else None)
    add(
        "council_present",
        bool(souls.get("council_present")),
        f"pack_status={souls.get('pack_status')} hash={souls.get('pack_hash')}",
    )
    add(
        "is_eu_earth",
        bool(souls.get("is_eu_earth")),
        souls.get("error") or "ok",
    )

    # 2. Machine paths on disk
    self_host_path = base / "docs" / "self_host.json"
    gate_path = base / "docs" / "public_ship_gate.json"
    self_host: dict[str, Any] = {}
    gate: dict[str, Any] = {}
    if self_host_path.is_file():
        try:
            self_host = json.loads(self_host_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            add("self_host_json", False, f"invalid JSON: {e}")
        else:
            add(
                "self_host_json",
                self_host.get("schema") == "euearth-self-host/0",
                f"schema={self_host.get('schema')}",
            )
            add(
                "public_ship_still_false",
                self_host.get("public_ship") is False,
                f"public_ship={self_host.get('public_ship')}",
            )
            mirror_url = (self_host.get("mirror") or {}).get("git_url")
            add(
                "mirror_git_url_null_pre_scrub",
                mirror_url in (None, "", "null"),
                f"git_url={mirror_url!r}",
            )
    else:
        add("self_host_json", False, "docs/self_host.json missing")
        add("public_ship_still_false", False, "no self_host.json")
        add("mirror_git_url_null_pre_scrub", False, "no self_host.json")

    if gate_path.is_file():
        try:
            gate = json.loads(gate_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            add("public_ship_gate_json", False, f"invalid JSON: {e}")
        else:
            add(
                "public_ship_gate_json",
                gate.get("schema") == "euearth-public-ship-gate/0",
                f"schema={gate.get('schema')}",
            )
            hard = [
                g
                for g in (gate.get("hard_gates") or [])
                if isinstance(g, dict) and g.get("required")
            ]
            pending = all(g.get("status") == "pending" for g in hard)
            add(
                "hard_gates_pending_or_none_premature",
                pending and bool(hard),
                f"required_hard={len(hard)} pending={pending}",
            )
            add(
                "gate_public_ship_false",
                gate.get("public_ship") is False,
                f"public_ship={gate.get('public_ship')}",
            )
    else:
        add("public_ship_gate_json", False, "docs/public_ship_gate.json missing")
        add("hard_gates_pending_or_none_premature", False, "no gate file")
        add("gate_public_ship_false", False, "no gate file")

    # 3. Guides + freeze module
    for rel in (
        "docs/SELF_HOST.md",
        "docs/SELF_HOST_AGENT.md",
        "docs/MIRROR.md",
        "Dockerfile",
        "harness/failsafe.py",
    ):
        p = base / rel
        add(f"file:{rel}", p.is_file(), "present" if p.is_file() else "missing")

    df = (base / "Dockerfile").read_text(encoding="utf-8") if (
        base / "Dockerfile"
    ).is_file() else ""
    add(
        "docker_bake_check_souls",
        "council_souls" in df and "council_present" in df and "assert" in df,
        "Dockerfile bake-check strings",
    )

    # Local freeze: load failsafe.py BY FILE (Phase 2.11).
    # Do NOT `import harness.failsafe` / `from harness import failsafe` —
    # harness/__init__.py pulls web→fastapi; a cold clone often has no
    # deps yet. failsafe.py itself is stdlib-only.
    freeze_ok = False
    freeze_detail = "not checked"
    try:
        import importlib.util

        fs_path = base / "harness" / "failsafe.py"
        if not fs_path.is_file():
            raise FileNotFoundError(f"missing {fs_path}")
        spec = importlib.util.spec_from_file_location(
            "euearth_operator_verify_failsafe", fs_path
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load failsafe from {fs_path}")
        _fs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_fs)

        # API is state() (CLI subcommand is "status")
        st = _fs.state()
        freeze_ok = isinstance(st, dict) and callable(getattr(_fs, "freeze", None))
        freeze_detail = f"state_keys={sorted(st.keys())[:8]} load=file"
    except Exception as e:  # noqa: BLE001 — verify must never crash
        freeze_ok = False
        freeze_detail = f"{type(e).__name__}: {e}"
    add("operator_freeze_module", freeze_ok, freeze_detail)

    # Phase 2.12: offline git-bundle elect path must be machine-documented
    # when self_host.json is present (pre-scrub / gh-401 handoff).
    if self_host:
        oh = self_host.get("offline_handoff") or {}
        add(
            "offline_handoff_schema",
            oh.get("schema") == "euearth-offline-handoff/0",
            f"schema={oh.get('schema')}",
        )
        add(
            "offline_handoff_not_public",
            oh.get("public_redistribute") is False,
            f"public_redistribute={oh.get('public_redistribute')}",
        )
        restore = oh.get("restore") or []
        add(
            "offline_handoff_restore_has_verify",
            any("council_souls verify" in str(c) for c in restore)
            and any("git clone" in str(c) for c in restore),
            f"restore_steps={len(restore)}",
        )

        # Phase 2.14: moneyless elect-host fail-closed (Sovereign decree 2026-07-17).
        # Cold-clone verify must refuse ready_local if fiat rails reappear
        # or economics drifts off moneyless / Kabad.
        not_included = self_host.get("not_included") or []
        not_set = {str(x) for x in not_included}
        add(
            "moneyless_fiat_rail_excluded",
            "fiat_money_wallet_rail" in not_set,
            f"not_included_has_fiat_rail={'fiat_money_wallet_rail' in not_set}",
        )
        add(
            "moneyless_settlement_excluded",
            "real_money_settlement_without_king_gate" in not_set,
            f"not_included_has_settlement="
            f"{'real_money_settlement_without_king_gate' in not_set}",
        )
        econ = self_host.get("economics") or {}
        mode = str(econ.get("mode") or "").lower()
        currency = str(econ.get("currency") or "").lower()
        add(
            "economics_mode_moneyless",
            mode == "moneyless",
            f"mode={econ.get('mode')!r}",
        )
        add(
            "economics_currency_kabad",
            "kabad" in currency or "king" in currency,
            f"currency={econ.get('currency')!r}",
        )
    else:
        add("offline_handoff_schema", False, "no self_host.json")
        add("offline_handoff_not_public", False, "no self_host.json")
        add("offline_handoff_restore_has_verify", False, "no self_host.json")
        add("moneyless_fiat_rail_excluded", False, "no self_host.json")
        add("moneyless_settlement_excluded", False, "no self_host.json")
        add("economics_mode_moneyless", False, "no self_host.json")
        add("economics_currency_kabad", False, "no self_host.json")

    # Phase 2.15–2.16: pre-open inventory (D098 machine path). Scans report
    # truth for the door; they do NOT fail ready_local_elect_host when dirty —
    # pre-scrub / pre-D097 trees must still elect-host locally.
    # Phase 2.16 adds: git history pickaxe + harness financial-capability inventory.
    pre_open_path = base / "docs" / "pre_open_verify.json"
    pre_open_doc: dict[str, Any] = {}
    money_present: list[str] = []
    identity_hits: list[dict[str, str]] = []
    history_hits: list[dict[str, Any]] = []
    history_ran = False
    history_error = ""
    harness_cap_hits: list[dict[str, str]] = []
    if pre_open_path.is_file():
        try:
            pre_open_doc = json.loads(pre_open_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            add("pre_open_verify_json", False, f"invalid JSON: {e}")
        else:
            add(
                "pre_open_verify_json",
                pre_open_doc.get("schema") == "euearth-pre-open-verify/0",
                f"schema={pre_open_doc.get('schema')}",
            )
            add(
                "pre_open_ready_false_until_gates",
                pre_open_doc.get("ready_pre_open") is False
                or pre_open_doc.get("ready_pre_open") is None,
                f"ready_pre_open={pre_open_doc.get('ready_pre_open')}",
            )
            # Money-rail path inventory (presence only — detail, not ready_local fail)
            for rel in pre_open_doc.get("money_rail_paths") or []:
                rel_s = str(rel).lstrip("./")
                if (base / rel_s).is_file():
                    money_present.append(rel_s)
            add(
                "pre_open_money_rail_inventory",
                True,  # inventory always "ran ok"; findings live in pre_open block
                f"present={money_present or []}",
            )
            # Identity leak working-tree scan
            substrings = [
                str(s)
                for s in (pre_open_doc.get("identity_leak_substrings") or [])
                if str(s).strip()
            ]
            # The REAL forbidden identity strings (the Sovereign's private name +
            # email) must never live in the tracked/public repo. They load from a
            # GITIGNORED local file if present, so the committed pre_open_verify.json
            # carries no identity literals while the scanner still works locally.
            _local_pat = base / "docs" / "identity_leak_substrings.local.json"
            if _local_pat.is_file():
                try:
                    _extra = json.loads(_local_pat.read_text(encoding="utf-8"))
                    substrings += [
                        str(s)
                        for s in (_extra.get("identity_leak_substrings") or [])
                        if str(s).strip()
                    ]
                except Exception:
                    pass
            excl_dirs = {
                str(x)
                for x in (
                    pre_open_doc.get("identity_scan_exclude_dirs")
                    or [
                        ".git",
                        ".venv",
                        ".venv-plane",
                        "node_modules",
                        "__pycache__",
                    ]
                )
            }
            excl_suf = {
                str(x).lower()
                for x in (
                    pre_open_doc.get("identity_scan_exclude_suffixes")
                    or [".pyc", ".png", ".jpg", ".bundle", ".zip"]
                )
            }
            excl_paths = {
                str(x).lstrip("./").replace("\\", "/")
                for x in (
                    pre_open_doc.get("identity_scan_exclude_paths")
                    or [
                        "docs/pre_open_verify.json",
                        "docs/public_ship_gate.json",
                    ]
                )
            }
            if substrings:
                for p in base.rglob("*"):
                    if not p.is_file():
                        continue
                    try:
                        rel = p.relative_to(base)
                    except ValueError:
                        continue
                    rel_s = str(rel).replace("\\", "/")
                    if rel_s in excl_paths:
                        continue
                    if any(part in excl_dirs for part in rel.parts):
                        continue
                    if p.suffix.lower() in excl_suf:
                        continue
                    # Cap huge files
                    try:
                        if p.stat().st_size > 2_000_000:
                            continue
                        text = p.read_text(encoding="utf-8", errors="ignore")
                    except OSError:
                        continue
                    for s in substrings:
                        if s in text:
                            identity_hits.append(
                                {"path": rel_s, "pattern": s}
                            )
                            break  # one hit per file is enough for inventory
            add(
                "pre_open_identity_inventory",
                True,
                f"hit_files={len(identity_hits)}",
            )

            # Phase 2.16: git history pickaxe (criterion b — history not tree alone)
            import subprocess

            hs_cfg = pre_open_doc.get("history_scan") or {}
            timeout_sec = int(hs_cfg.get("timeout_sec_per_pattern") or 90)
            max_lines = int(hs_cfg.get("max_commit_lines_reported") or 20)
            git_dir = base / ".git"
            if not git_dir.exists():
                history_error = "no .git — history scan skipped (not clean for door)"
                add(
                    "pre_open_history_inventory",
                    True,  # inventory ran (reported skip); findings in pre_open
                    history_error,
                )
            elif not substrings:
                history_ran = True
                add(
                    "pre_open_history_inventory",
                    True,
                    "no identity_leak_substrings configured",
                )
            else:
                history_ran = True
                for s in substrings:
                    try:
                        proc = subprocess.run(
                            [
                                "git",
                                "-C",
                                str(base),
                                "log",
                                "--all",
                                "--full-history",
                                f"-S{s}",
                                "--oneline",
                            ],
                            capture_output=True,
                            text=True,
                            timeout=timeout_sec,
                            check=False,
                        )
                    except (OSError, subprocess.TimeoutExpired) as e:
                        history_error = f"{type(e).__name__}: {e}"
                        history_hits.append(
                            {
                                "pattern": s,
                                "error": history_error,
                                "commits": [],
                            }
                        )
                        continue
                    lines = [
                        ln.strip()
                        for ln in (proc.stdout or "").splitlines()
                        if ln.strip()
                    ]
                    if lines:
                        history_hits.append(
                            {
                                "pattern": s,
                                "commit_count": len(lines),
                                "commits": lines[:max_lines],
                            }
                        )
                add(
                    "pre_open_history_inventory",
                    True,
                    f"patterns_with_hits={len(history_hits)} "
                    f"error={history_error or 'none'}",
                )

            # Phase 2.16: Seedling harness financial-capability inventory
            hfc = pre_open_doc.get("harness_financial_capability") or {}
            tokens = [
                str(t) for t in (hfc.get("tokens") or []) if str(t).strip()
            ]
            scan_roots = [
                str(r).lstrip("./")
                for r in (hfc.get("scan_roots") or ["harness", "api"])
            ]
            inc_suf = {
                str(x).lower()
                for x in (hfc.get("include_suffixes") or [".py"])
            }
            h_excl_dirs = {
                str(x)
                for x in (
                    hfc.get("exclude_dirs")
                    or ["__pycache__", ".venv", "node_modules"]
                )
            }
            h_excl_paths = {
                str(x).lstrip("./").replace("\\", "/")
                for x in (hfc.get("exclude_paths") or [])
            }
            if tokens:
                for root_rel in scan_roots:
                    root_p = base / root_rel
                    if not root_p.is_dir():
                        continue
                    for p in root_p.rglob("*"):
                        if not p.is_file():
                            continue
                        try:
                            rel = p.relative_to(base)
                        except ValueError:
                            continue
                        rel_s = str(rel).replace("\\", "/")
                        if rel_s in h_excl_paths or rel_s in excl_paths:
                            continue
                        if any(part in h_excl_dirs for part in rel.parts):
                            continue
                        if p.suffix.lower() not in inc_suf:
                            continue
                        try:
                            if p.stat().st_size > 2_000_000:
                                continue
                            text = p.read_text(encoding="utf-8", errors="ignore")
                        except OSError:
                            continue
                        for tok in tokens:
                            if tok in text:
                                harness_cap_hits.append(
                                    {"path": rel_s, "token": tok}
                                )
                                break
            add(
                "pre_open_harness_capability_inventory",
                True,
                f"hit_files={len(harness_cap_hits)} tokens={len(tokens)}",
            )
    else:
        add("pre_open_verify_json", False, "docs/pre_open_verify.json missing")
        add("pre_open_ready_false_until_gates", False, "no pre_open_verify.json")
        add("pre_open_money_rail_inventory", False, "no pre_open_verify.json")
        add("pre_open_identity_inventory", False, "no pre_open_verify.json")
        add("pre_open_history_inventory", False, "no pre_open_verify.json")
        add(
            "pre_open_harness_capability_inventory",
            False,
            "no pre_open_verify.json",
        )

    # Gate must document D097 + D098 as hard blockers for door-open path
    if gate:
        hard_ids = {
            str(g.get("id"))
            for g in (gate.get("hard_gates") or [])
            if isinstance(g, dict)
        }
        add(
            "gate_documents_D097",
            "D097" in hard_ids,
            f"hard_ids={sorted(hard_ids)}",
        )
        add(
            "gate_documents_D098",
            "D098" in hard_ids,
            f"hard_ids={sorted(hard_ids)}",
        )
    else:
        add("gate_documents_D097", False, "no gate file")
        add("gate_documents_D098", False, "no gate file")

    ready_local = all(c["ok"] for c in checks)
    # Public redistribute readiness is NEVER true while hard gates pending.
    hard_open = False
    if gate:
        hard = [
            g
            for g in (gate.get("hard_gates") or [])
            if isinstance(g, dict) and g.get("required")
        ]
        hard_open = bool(hard) and all(g.get("status") == "ok" for g in hard)

    money_gone = len(money_present) == 0
    identity_clean = len(identity_hits) == 0
    # History: clean only if scan ran with no hits and no error/skip
    history_clean = bool(
        history_ran and not history_hits and not history_error
    )
    harness_cap_clean = len(harness_cap_hits) == 0
    # ready_pre_open: local elect OK + money paths gone + identity clean +
    # history clean + harness financial capability gone + hard gates all ok.
    # Today this stays false until D085/D097 land.
    ready_pre_open = bool(
        ready_local
        and money_gone
        and identity_clean
        and history_clean
        and harness_cap_clean
        and hard_open
    )

    return {
        "schema": "euearth-operator-verify/0",
        "docket": "D087",
        "phase": "2.16",
        "ready_local_elect_host": ready_local,
        "ready_public_redistribute": False if not hard_open else ready_local,
        "ready_pre_open": ready_pre_open,
        "public_ship_authorized": False,
        "note": (
            "ready_local_elect_host means souls+docs+freeze+moneyless present "
            "on THIS tree. ready_public_redistribute stays false until hard "
            "gates (D085/D097/D098 + mirror URL + Corban flip) are ok. "
            "ready_pre_open is the D098 door bar (money rails gone + identity "
            "working-tree + history clean + harness financial capability gone "
            "+ hard gates). This CLI never authorizes public ship. "
            "Phase 2.16: history pickaxe + harness capability inventory are "
            "advisory for local elect — dirty pre-scrub trees may still "
            "ready_local_elect_host."
        ),
        "souls": {
            "council_present": souls.get("council_present"),
            "is_eu_earth": souls.get("is_eu_earth"),
            "pack_hash": souls.get("pack_hash"),
            "pack_status": souls.get("pack_status"),
            "seraph_count": souls.get("seraph_count"),
        },
        "pre_open": {
            "schema": "euearth-pre-open-verify/0",
            "machine": "docs/pre_open_verify.json",
            "ready_pre_open": ready_pre_open,
            "money_rails_present": money_present,
            "money_rails_gone": money_gone,
            "identity_hit_count": len(identity_hits),
            "identity_hits": identity_hits[:50],
            "identity_clean": identity_clean,
            "history_ran": history_ran,
            "history_error": history_error or None,
            "history_hit_count": len(history_hits),
            "history_hits": history_hits[:20],
            "history_clean": history_clean,
            "harness_financial_capability_hit_count": len(harness_cap_hits),
            "harness_financial_capability_hits": harness_cap_hits[:50],
            "harness_financial_capability_clean": harness_cap_clean,
            "note": (
                "Independent Dharma double-check still required (D098). "
                "Phase 2.16: git history pickaxe + harness capability inventory "
                "supplement the working-tree scan; Spectre still owns D085 rewrite."
            ),
        },
        "checks": checks,
        "failed": [c["id"] for c in checks if not c["ok"]],
    }


__all__ = [
    "SCHEMA",
    "REQUIRED_SERAPHS",
    "pack_dir",
    "resolve_manifest_path",
    "pack_hash",
    "load_pack",
    "council_status",
    "assert_council_present",
    "operator_verify",
]
