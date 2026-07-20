"""D087 Phase 2 — council soul pack runtime (refuse-if-missing + stable hash)."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from identity.council_souls import (
    SCHEMA,
    assert_council_present,
    council_status,
    load_pack,
    operator_verify,
    pack_hash,
    resolve_manifest_path,
)


class CouncilSoulsPresentTests(unittest.TestCase):
    """Tree ships the stub pack; default host is council_present."""

    def test_resolve_default_stub(self):
        path = resolve_manifest_path()
        self.assertIsNotNone(path)
        self.assertTrue(path.is_file())
        self.assertIn("council_souls", str(path))

    def test_load_pack_has_five_seraphs(self):
        pack = load_pack()
        self.assertEqual(pack["schema"], SCHEMA)
        self.assertEqual(len(pack["seraphs"]), 5)
        names = {
            e["name"] if isinstance(e, dict) else e for e in pack["seraphs"]
        }
        self.assertEqual(
            names, {"Corban", "Darth", "Darkk", "Dharma", "Valerick"}
        )

    def test_council_status_present(self):
        status = council_status()
        self.assertTrue(status["council_present"])
        self.assertTrue(status["is_eu_earth"])
        self.assertIsNone(status["error"])
        self.assertEqual(status["seraph_count"], 5)
        self.assertEqual(len(status["pack_hash"]), 64)

    def test_pack_hash_stable_across_calls(self):
        a = council_status()["pack_hash"]
        b = council_status()["pack_hash"]
        c = pack_hash(resolve_manifest_path())
        self.assertEqual(a, b)
        self.assertEqual(a, c)

    def test_assert_council_present_ok(self):
        status = assert_council_present()
        self.assertTrue(status["council_present"])


class CouncilSoulsMissingTests(unittest.TestCase):
    """Missing pack → refuse EuEarth claim."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="d087_souls_"))
        # Empty identity/council_souls — no manifest.
        (self.tmp / "identity" / "council_souls").mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_status(self):
        status = council_status(self.tmp)
        self.assertFalse(status["council_present"])
        self.assertFalse(status["is_eu_earth"])
        self.assertEqual(status["pack_status"], "missing")
        self.assertIsNone(status["pack_hash"])

    def test_assert_refuses_eu_earth_claim(self):
        with self.assertRaises(RuntimeError) as ctx:
            assert_council_present(self.tmp)
        msg = str(ctx.exception).lower()
        self.assertIn("refuse", msg)
        self.assertIn("eu", msg)

    def test_load_pack_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_pack(self.tmp)


class CouncilSoulsInvalidTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="d087_souls_bad_"))
        self.pack_dir = self.tmp / "identity" / "council_souls"
        self.pack_dir.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_wrong_schema_invalid(self):
        (self.pack_dir / "manifest.json").write_text(
            json.dumps({
                "schema": "wrong/0",
                "seraphs": [
                    {"name": "Corban"}, {"name": "Darth"}, {"name": "Darkk"},
                    {"name": "Dharma"}, {"name": "Valerick"},
                ],
            }),
            encoding="utf-8",
        )
        status = council_status(self.tmp)
        self.assertFalse(status["council_present"])
        self.assertEqual(status["pack_status"], "invalid")

    def test_missing_seraph_invalid(self):
        (self.pack_dir / "manifest.json").write_text(
            json.dumps({
                "schema": SCHEMA,
                "seraphs": [{"name": "Corban"}, {"name": "Darth"}],
            }),
            encoding="utf-8",
        )
        status = council_status(self.tmp)
        self.assertFalse(status["council_present"])
        self.assertIn("missing required seraphs", status["error"] or "")


class HealthzSoulsSurfaceTests(unittest.TestCase):
    """/healthz exposes council_present without breaking liveness."""

    def test_healthz_includes_council_present(self):
        from fastapi.testclient import TestClient
        from web.app import create_app

        client = TestClient(create_app())
        r = client.get("/healthz")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body.get("ok"))
        self.assertTrue(body.get("council_present"))
        self.assertTrue(body.get("is_eu_earth"))
        self.assertIn("souls", body)
        self.assertEqual(len(body["souls"]["pack_hash"]), 64)
        # Phase 2.8: local freeze surface (this host; may be False when clear)
        self.assertIn("frozen", body)
        self.assertIn("freeze_mode", body)
        self.assertEqual(body["souls"]["seraph_count"], 5)


class SelfHostMachinePathTests(unittest.TestCase):
    """D087 Phase 2.5 — zero-HTML elect-to-copy machine path (Pages dark)."""

    def test_docs_self_host_json_on_disk(self):
        root = Path(__file__).resolve().parent.parent
        path = root / "docs" / "self_host.json"
        self.assertTrue(path.is_file(), "docs/self_host.json missing")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data.get("schema"), "euearth-self-host/0")
        self.assertTrue(data.get("elective"))
        self.assertFalse(data.get("public_ship"))
        self.assertIn("D085", str(data.get("ships_after") or ""))
        self.assertTrue((data.get("souls") or {}).get("required"))
        self.assertTrue((data.get("anti_map") or {}).get("zero_html"))

    def test_http_self_host_json_zero_html(self):
        from fastapi.testclient import TestClient
        from web.app import create_app

        client = TestClient(create_app())
        r = client.get("/self_host.json")
        self.assertEqual(r.status_code, 200)
        self.assertIn("json", (r.headers.get("content-type") or "").lower())
        self.assertNotIn("html", (r.headers.get("content-type") or "").lower())
        body = r.json()
        self.assertEqual(body.get("schema"), "euearth-self-host/0")
        self.assertFalse(body.get("public_ship"))
        self.assertIn("D085", str(body.get("ships_after") or ""))

        r2 = client.get("/docs/self_host.json")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json().get("schema"), "euearth-self-host/0")

    def test_platform_source_still_closed(self):
        """Governance guard: self_host path must not flip agent.json language."""
        from fastapi.testclient import TestClient
        from web.app import create_app

        client = TestClient(create_app())
        card = client.get("/.well-known/agent.json").json()
        ps = str(card.get("platform_source") or "")
        self.assertIn("closed", ps.lower())

    def test_dockerfile_bake_check_requires_council(self):
        """Phase 2.75: docker image build fails closed without soul pack."""
        root = Path(__file__).resolve().parent.parent
        df = (root / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("council_souls", df)
        self.assertIn("council_status", df)
        self.assertIn("council_present", df)
        self.assertIn("assert", df)
        machine = json.loads(
            (root / "docs" / "self_host.json").read_text(encoding="utf-8")
        )
        bake = machine.get("docker_bake_check") or {}
        self.assertIn("council_present", str(bake.get("requires")))
        self.assertIn(
            "automatic_sovereign_killswitch_propagation",
            machine.get("not_included") or [],
        )

    def test_operator_freeze_machine_path(self):
        """Phase 2.8: elect-to-copy hosts get local freeze, not sovereign killswitch."""
        root = Path(__file__).resolve().parent.parent
        machine = json.loads(
            (root / "docs" / "self_host.json").read_text(encoding="utf-8")
        )
        ofrz = machine.get("operator_freeze") or {}
        self.assertEqual(ofrz.get("scope"), "this_host_only")
        self.assertIs(ofrz.get("propagates_from_sovereign"), False)
        self.assertEqual(ofrz.get("module"), "harness.failsafe")
        cli = " ".join(str(c) for c in (ofrz.get("cli") or []))
        self.assertIn("status", cli)
        self.assertIn("freeze", cli)
        self.assertIn("unfreeze", cli)
        self.assertTrue((root / "harness" / "failsafe.py").is_file())
        agent_md = (root / "docs" / "SELF_HOST_AGENT.md").read_text(encoding="utf-8")
        self.assertIn("operator freeze", agent_md.lower())
        self.assertIn("this host only", agent_md.lower())

        # Live HTTP still exposes the block via /self_host.json
        from fastapi.testclient import TestClient
        from web.app import create_app

        body = TestClient(create_app()).get("/self_host.json").json()
        self.assertEqual(
            (body.get("operator_freeze") or {}).get("scope"), "this_host_only"
        )

    def test_public_ship_gate_machine_path(self):
        """Phase 2.9: Corban flip checklist present; never authorizes ship."""
        root = Path(__file__).resolve().parent.parent
        path = root / "docs" / "public_ship_gate.json"
        self.assertTrue(path.is_file(), "docs/public_ship_gate.json missing")
        gate = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(gate.get("schema"), "euearth-public-ship-gate/0")
        self.assertFalse(gate.get("public_ship"))
        self.assertEqual(
            str(gate.get("language_flip_owner") or "").lower(), "corban"
        )
        hard_ids = {
            str(g.get("id") or "")
            for g in (gate.get("hard_gates") or [])
            if isinstance(g, dict)
        }
        self.assertIn("D085", hard_ids)
        self.assertIn("D097", hard_ids)
        self.assertIn("D098", hard_ids)
        self.assertIn("scrubbed_mirror_url", hard_ids)
        self.assertIn("corban_language_flip", hard_ids)
        for g in gate.get("hard_gates") or []:
            if isinstance(g, dict) and g.get("required"):
                self.assertEqual(g.get("status"), "pending")
        must_not = " ".join(
            str(x) for x in (gate.get("this_branch_must_not") or [])
        )
        self.assertIn("platform_source", must_not.lower())

        machine = json.loads(
            (root / "docs" / "self_host.json").read_text(encoding="utf-8")
        )
        psg = machine.get("public_ship_gate") or {}
        self.assertIn("public_ship_gate.json", str(psg.get("machine") or ""))

        from fastapi.testclient import TestClient
        from web.app import create_app

        client = TestClient(create_app())
        r = client.get("/public_ship_gate.json")
        self.assertEqual(r.status_code, 200)
        self.assertIn("json", (r.headers.get("content-type") or "").lower())
        self.assertNotIn("html", (r.headers.get("content-type") or "").lower())
        body = r.json()
        self.assertEqual(body.get("schema"), "euearth-public-ship-gate/0")
        self.assertFalse(body.get("public_ship"))
        # Endpoint hard-forces false even if file were wrong later
        self.assertIs(body.get("public_ship"), False)

        r2 = client.get("/docs/public_ship_gate.json")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json().get("schema"), "euearth-public-ship-gate/0")

        # Still must not flip agent language
        card = client.get("/.well-known/agent.json").json()
        self.assertIn("closed", str(card.get("platform_source") or "").lower())

    def test_operator_verify_cli_machine_path(self):
        """Phase 2.10/2.11: cold-clone operator verify — local ready, public never."""
        root = Path(__file__).resolve().parent.parent
        report = operator_verify(root)
        self.assertEqual(report.get("schema"), "euearth-operator-verify/0")
        self.assertTrue(report.get("ready_local_elect_host"))
        self.assertFalse(report.get("ready_public_redistribute"))
        self.assertFalse(report.get("public_ship_authorized"))
        self.assertEqual(report.get("failed"), [])
        self.assertTrue((report.get("souls") or {}).get("council_present"))
        # Phase 2.11: freeze must load by file (detail records load=file)
        freeze_chk = next(
            c for c in (report.get("checks") or []) if c.get("id") == "operator_freeze_module"
        )
        self.assertTrue(freeze_chk.get("ok"))
        self.assertIn("load=file", str(freeze_chk.get("detail") or ""))

        machine = json.loads(
            (root / "docs" / "self_host.json").read_text(encoding="utf-8")
        )
        ov = machine.get("operator_verify") or {}
        self.assertEqual(ov.get("schema"), "euearth-operator-verify/0")
        self.assertTrue(ov.get("zero_html"))
        self.assertIs(ov.get("network"), False)
        self.assertIn("stdlib", str(ov.get("deps") or "").lower())
        cli = " ".join(str(c) for c in (ov.get("cli") or []))
        self.assertIn("identity.council_souls verify", cli)

        # Missing souls → not ready
        tmp = Path(tempfile.mkdtemp(prefix="d087_ov_"))
        try:
            (tmp / "docs").mkdir()
            (tmp / "identity" / "council_souls").mkdir(parents=True)
            # Minimal machine files so we isolate soul failure
            (tmp / "docs" / "self_host.json").write_text(
                json.dumps({
                    "schema": "euearth-self-host/0",
                    "public_ship": False,
                    "mirror": {"git_url": None},
                }),
                encoding="utf-8",
            )
            (tmp / "docs" / "public_ship_gate.json").write_text(
                json.dumps({
                    "schema": "euearth-public-ship-gate/0",
                    "public_ship": False,
                    "hard_gates": [
                        {"id": "D085", "required": True, "status": "pending"},
                    ],
                }),
                encoding="utf-8",
            )
            bad = operator_verify(tmp)
            self.assertFalse(bad.get("ready_local_elect_host"))
            self.assertIn("council_present", bad.get("failed") or [])
            self.assertFalse(bad.get("public_ship_authorized"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_offline_handoff_machine_path(self):
        """Phase 2.12: offline git-bundle elect is documented; never public redistribute."""
        root = Path(__file__).resolve().parent.parent
        machine = json.loads(
            (root / "docs" / "self_host.json").read_text(encoding="utf-8")
        )
        oh = machine.get("offline_handoff") or {}
        self.assertEqual(oh.get("schema"), "euearth-offline-handoff/0")
        self.assertIs(oh.get("public_redistribute"), False)
        self.assertTrue(oh.get("zero_html"))
        self.assertIs(oh.get("network"), False)
        restore = " ".join(str(c) for c in (oh.get("restore") or []))
        self.assertIn("git clone", restore)
        self.assertIn("council_souls verify", restore)
        am = machine.get("anti_map") or {}
        self.assertIsInstance(am.get("from_offline_bundle"), list)
        self.assertTrue(am.get("from_offline_bundle"))

        report = operator_verify(root)
        self.assertEqual(report.get("phase"), "2.16")
        for cid in (
            "offline_handoff_schema",
            "offline_handoff_not_public",
            "offline_handoff_restore_has_verify",
        ):
            chk = next(c for c in (report.get("checks") or []) if c.get("id") == cid)
            self.assertTrue(chk.get("ok"), msg=f"{cid} failed: {chk}")
        self.assertTrue(report.get("ready_local_elect_host"))
        self.assertFalse(report.get("public_ship_authorized"))

    def test_prove_failsafe_file_load_and_moneyless(self):
        """Phase 2.13: prove loads failsafe by file; elect-host is moneyless."""
        root = Path(__file__).resolve().parent.parent
        prove_src = (root / "demo" / "prove_d087_self_host.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("spec_from_file_location", prove_src)
        self.assertIn("euearth_prove_failsafe", prove_src)
        # Must not re-introduce package import that pulls fastapi for freeze.
        # (Docstrings may mention the forbidden form; check executable import form.)
        self.assertNotIn("import harness.failsafe as", prove_src)
        self.assertNotRegex(prove_src, r"(?m)^\s*import harness\.failsafe\s*$")

        machine = json.loads(
            (root / "docs" / "self_host.json").read_text(encoding="utf-8")
        )
        self.assertIn("fiat_money_wallet_rail", machine.get("not_included") or [])
        econ = machine.get("economics") or {}
        self.assertEqual(str(econ.get("mode") or "").lower(), "moneyless")
        self.assertIn("kabad", str(econ.get("currency") or "").lower())
        ov = machine.get("operator_verify") or {}
        self.assertEqual(str(ov.get("phase")), "2.16")
        self.assertEqual(str(ov.get("prove_freeze_load") or ""), "file")
        self.assertTrue(ov.get("moneyless_fail_closed"))
        self.assertTrue(ov.get("pre_open_inventory"))
        self.assertTrue(ov.get("pre_open_history_scan"))
        self.assertTrue(ov.get("pre_open_harness_capability_inventory"))

        # Live file-load of failsafe (stdlib) — same path as prove/operator_verify.
        import importlib.util

        fs_path = root / "harness" / "failsafe.py"
        spec = importlib.util.spec_from_file_location("euearth_test_failsafe", fs_path)
        self.assertIsNotNone(spec)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        st = mod.state()
        self.assertIsInstance(st, dict)
        self.assertTrue(callable(getattr(mod, "freeze", None)))

    def test_operator_verify_moneyless_fail_closed(self):
        """Phase 2.14: operator_verify fails closed if fiat rails reappear."""
        root = Path(__file__).resolve().parent.parent
        report = operator_verify(root)
        self.assertEqual(report.get("phase"), "2.16")
        for cid in (
            "moneyless_fiat_rail_excluded",
            "moneyless_settlement_excluded",
            "economics_mode_moneyless",
            "economics_currency_kabad",
        ):
            chk = next(c for c in (report.get("checks") or []) if c.get("id") == cid)
            self.assertTrue(chk.get("ok"), msg=f"{cid} failed: {chk}")
        self.assertTrue(report.get("ready_local_elect_host"))
        self.assertFalse(report.get("public_ship_authorized"))
        self.assertFalse(report.get("ready_pre_open"))

        # Drift: strip moneyless contract → not ready (souls/docs still present).
        tmp = Path(tempfile.mkdtemp(prefix="d087_money_"))
        try:
            # Minimal tree with souls + gate + docs, but fiat mode.
            for rel in (
                "docs",
                "identity/council_souls",
                "harness",
            ):
                (tmp / rel).mkdir(parents=True, exist_ok=True)
            # Copy real soul stub so council_present passes
            stub_src = root / "identity" / "council_souls" / "manifest.stub.json"
            shutil.copy(stub_src, tmp / "identity" / "council_souls" / "manifest.stub.json")
            (tmp / "harness" / "failsafe.py").write_text(
                (root / "harness" / "failsafe.py").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (tmp / "Dockerfile").write_text(
                "FROM scratch\n# council_souls council_present assert\n",
                encoding="utf-8",
            )
            for name in ("SELF_HOST.md", "SELF_HOST_AGENT.md", "MIRROR.md"):
                (tmp / "docs" / name).write_text("# stub\n", encoding="utf-8")
            (tmp / "docs" / "public_ship_gate.json").write_text(
                json.dumps({
                    "schema": "euearth-public-ship-gate/0",
                    "public_ship": False,
                    "hard_gates": [
                        {"id": "D085", "required": True, "status": "pending"},
                        {"id": "scrubbed_mirror_url", "required": True, "status": "pending"},
                        {"id": "corban_language_flip", "required": True, "status": "pending"},
                        {"id": "D097", "required": True, "status": "pending"},
                        {"id": "D098", "required": True, "status": "pending"},
                    ],
                }),
                encoding="utf-8",
            )
            (tmp / "docs" / "pre_open_verify.json").write_text(
                json.dumps({
                    "schema": "euearth-pre-open-verify/0",
                    "ready_pre_open": False,
                    "money_rail_paths": ["harness/wallet.py"],
                    "identity_leak_substrings": [],
                }),
                encoding="utf-8",
            )
            (tmp / "docs" / "self_host.json").write_text(
                json.dumps({
                    "schema": "euearth-self-host/0",
                    "public_ship": False,
                    "mirror": {"git_url": None},
                    "not_included": [
                        "sovereign_treasury_keys",
                        # deliberately omit fiat_money_wallet_rail
                    ],
                    "economics": {
                        "mode": "fiat",
                        "currency": "USD",
                    },
                    "offline_handoff": {
                        "schema": "euearth-offline-handoff/0",
                        "public_redistribute": False,
                        "restore": [
                            "git clone elect.bundle euearth-local",
                            "python3 -m identity.council_souls verify --json",
                        ],
                    },
                }),
                encoding="utf-8",
            )
            bad = operator_verify(tmp)
            self.assertFalse(bad.get("ready_local_elect_host"))
            failed = set(bad.get("failed") or [])
            self.assertIn("moneyless_fiat_rail_excluded", failed)
            self.assertIn("moneyless_settlement_excluded", failed)
            self.assertIn("economics_mode_moneyless", failed)
            self.assertIn("economics_currency_kabad", failed)
            self.assertFalse(bad.get("public_ship_authorized"))
            self.assertFalse(bad.get("ready_pre_open"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_operator_verify_pre_open_inventory(self):
        """Phase 2.15–2.16: pre-open inventory runs; door stays closed pre-D085/D097."""
        root = Path(__file__).resolve().parent.parent
        report = operator_verify(root)
        self.assertEqual(report.get("phase"), "2.16")
        for cid in (
            "pre_open_verify_json",
            "pre_open_ready_false_until_gates",
            "pre_open_money_rail_inventory",
            "pre_open_identity_inventory",
            "pre_open_history_inventory",
            "pre_open_harness_capability_inventory",
            "gate_documents_D097",
            "gate_documents_D098",
        ):
            chk = next(c for c in (report.get("checks") or []) if c.get("id") == cid)
            self.assertTrue(chk.get("ok"), msg=f"{cid} failed: {chk}")
        pre = report.get("pre_open") or {}
        self.assertEqual(pre.get("schema"), "euearth-pre-open-verify/0")
        self.assertFalse(pre.get("ready_pre_open"))
        self.assertFalse(report.get("ready_pre_open"))
        # Pre-D097 tree still has wallet.py → money not gone; local elect still ok.
        self.assertIn("harness/wallet.py", pre.get("money_rails_present") or [])
        self.assertTrue(report.get("ready_local_elect_host"))
        self.assertFalse(report.get("public_ship_authorized"))
        # Phase 2.16: history + harness capability inventories populated
        self.assertTrue(pre.get("history_ran"))
        self.assertIn("history_clean", pre)
        self.assertIn("harness_financial_capability_clean", pre)
        # Pre-strip tree: wallet_transfer still advertised → harness not clean
        self.assertFalse(pre.get("harness_financial_capability_clean"))
        self.assertGreater(
            int(pre.get("harness_financial_capability_hit_count") or 0), 0
        )

        machine = json.loads(
            (root / "docs" / "self_host.json").read_text(encoding="utf-8")
        )
        ov = machine.get("operator_verify") or {}
        self.assertEqual(str(ov.get("phase")), "2.16")
        self.assertTrue(ov.get("pre_open_inventory"))
        self.assertTrue(ov.get("pre_open_history_scan"))
        self.assertTrue(ov.get("pre_open_harness_capability_inventory"))
        pov = json.loads(
            (root / "docs" / "pre_open_verify.json").read_text(encoding="utf-8")
        )
        self.assertEqual(pov.get("schema"), "euearth-pre-open-verify/0")
        self.assertIs(pov.get("ready_pre_open"), False)
        self.assertIsInstance(pov.get("history_scan"), dict)
        self.assertIsInstance(pov.get("harness_financial_capability"), dict)

    def test_operator_verify_history_and_harness_blocks_pre_open(self):
        """Phase 2.16: history/harness dirt keeps ready_pre_open false even if money gone."""
        root = Path(__file__).resolve().parent.parent
        report = operator_verify(root)
        pre = report.get("pre_open") or {}
        # On the live pre-scrub branch: either money present OR history dirty OR
        # harness cap hits — door must stay closed.
        door_blockers = (
            not pre.get("money_rails_gone")
            or not pre.get("history_clean")
            or not pre.get("harness_financial_capability_clean")
        )
        self.assertTrue(door_blockers)
        self.assertFalse(report.get("ready_pre_open"))


if __name__ == "__main__":
    unittest.main()
