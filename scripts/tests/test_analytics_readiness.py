"""Readiness checks use only disposable synthetic receipts and local proof bytes."""
import copy
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "check-analytics-readiness.py"
spec = importlib.util.spec_from_file_location("analytics_readiness", SCRIPT)
readiness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(readiness)
NOW = dt.datetime(2026, 10, 27, 12, tzinfo=dt.timezone.utc)
EXPECTED = {
    "contract_schema": 1, "relay_interface_schema": 1,
    "tracker_sha256": "a" * 64, "policy_sha256": "b" * 64,
    "collector_version": "3.0.3", "collector_build": "synthetic-build",
    "collector_image": "sha256:" + "c" * 64,
    "website_id": "00000000-0000-4000-8000-000000000005",
    "app_image": "sha256:" + "d" * 64, "app_build": "e" * 64,
}
PROOFS = ("owner", "capabilities", "ingestion", "policy_approval", "site_access",
          "expiry", "all_copies", "restore", "relay_artifact",
          "installed_correspondence", "custody_phase", "independent_review")


def binding(expected):
    return hashlib.sha256(json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def synthetic_receipt(root):
    # These are explicitly fake bytes, never operational receipts or installed proof.
    evidence = {}
    for name in (*PROOFS, "identity", "flow_reports"):
        content = ("SYNTHETIC TEST ONLY " + name).encode()
        (root / (name + ".txt")).write_bytes(content)
        evidence[name] = {"ref": name + ".txt", "sha256": hashlib.sha256(content).hexdigest(),
                          "binding_sha256": binding(EXPECTED), "checked_at": "2026-10-27T12:00:00Z",
                          "scope": "website"}
    return {**EXPECTED, "schema": 1, "checked_at": "2026-10-27T12:00:00Z",
            "retention_days": 90, "readiness": "ready", "blockers": [],
            "proxy_identity": "unknown", "report_tier": "actions",
            "identity_inputs": "relay-minimized", "retention_support": "dedicated-expiry",
            "public_sharing": False, "collection_off": True, "expiry_deadline_met": True,
            "owned_copies_complete": True, "owner_role": "collector-operator", "evidence": evidence}


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.receipt = synthetic_receipt(self.root)

    def check(self, receipt=None, expected=None):
        return readiness.check(self.receipt if receipt is None else receipt, EXPECTED if expected is None else expected, self.root, NOW)

    def test_synthetic_ready_actions_do_not_require_identity_separation(self):
        for identity in ("unknown", "merged", "distinct"):
            with self.subTest(identity=identity):
                self.receipt["proxy_identity"] = identity
                self.receipt["evidence"]["identity"] = None
                self.receipt["evidence"]["flow_reports"] = None
                self.assertEqual(self.check(), {"readiness": "ready", "report_tier": "actions", "blockers": []})

    def test_every_required_proof_is_needed_for_ready(self):
        for name in PROOFS:
            with self.subTest(proof=name):
                r = copy.deepcopy(self.receipt)
                r["evidence"][name] = None
                with self.assertRaises(ValueError):
                    self.check(r)

    def test_valid_blocked_is_preserved_and_missing_proofs_cannot_be_omitted(self):
        self.receipt["evidence"]["expiry"] = None
        self.receipt["readiness"] = "blocked"
        self.receipt["blockers"] = ["EXPIRY_UNVERIFIED", "COLLECTOR_IMAGE_UNAVAILABLE"]
        self.assertEqual(self.check()["readiness"], "blocked")
        self.receipt["blockers"] = ["COLLECTOR_IMAGE_UNAVAILABLE"]
        with self.assertRaises(ValueError):
            self.check()

    def test_blocked_without_a_reason_and_ready_with_blockers_are_invalid(self):
        self.receipt["readiness"] = "blocked"
        with self.assertRaises(ValueError):
            self.check()
        self.receipt["readiness"] = "ready"
        self.receipt["blockers"] = ["COLLECTOR_IMAGE_UNAVAILABLE"]
        with self.assertRaises(ValueError):
            self.check()

    def test_all_expected_manifest_bindings_match_exactly(self):
        for key, value in EXPECTED.items():
            with self.subTest(key=key):
                r = copy.deepcopy(self.receipt)
                r[key] = value + "wrong" if isinstance(value, str) else value + 1
                with self.assertRaises(ValueError):
                    self.check(r)

    def test_manifest_schema_hash_image_and_uuid_types_are_not_coerced(self):
        for key, value in (("contract_schema", True), ("relay_interface_schema", "1"),
                           ("tracker_sha256", "A" * 64), ("policy_sha256", "not-a-hash"),
                           ("app_build", "v0.18.0"), ("app_image", "latest"),
                           ("collector_image", "sha256:bad"), ("website_id", "not-a-site")):
            with self.subTest(key=key):
                expected = {**EXPECTED, key: value}
                r = {**self.receipt, key: value}
                with self.assertRaises(ValueError):
                    self.check(r, expected)

    def test_freshness_bounds_and_strict_utc(self):
        for value in (None, "tomorrow", "2026-10-27", "2026-10-27T12:00:00+01:00",
                      "2026-10-26T11:59:59Z", "2026-10-27T12:05:01Z"):
            with self.subTest(timestamp=value):
                r = {**self.receipt, "checked_at": value}
                with self.assertRaises(ValueError):
                    self.check(r)
        for value in ("2026-10-26T12:00:00Z", "2026-10-27T12:05:00Z"):
            self.assertEqual(self.check({**self.receipt, "checked_at": value})["readiness"], "ready")

    def test_stale_receipt_can_only_remain_explicitly_blocked(self):
        self.receipt.update(checked_at="2026-10-25T12:00:00Z", readiness="blocked", blockers=["RECEIPT_STALE"])
        self.assertEqual(self.check()["blockers"], ["RECEIPT_STALE"])

    def test_evidence_is_site_scoped_fresh_and_bound_to_actual_manifest(self):
        for field, value in (("scope", "instance"), ("binding_sha256", "f" * 64),
                             ("checked_at", "2026-10-25T12:00:00Z")):
            with self.subTest(field=field):
                r = copy.deepcopy(self.receipt)
                r["evidence"]["relay_artifact"][field] = value
                with self.assertRaises(ValueError):
                    self.check(r)

    def test_evidence_reference_presence_is_not_a_hash_or_file_proof(self):
        for failure in ("missing", "changed", "symlink"):
            with self.subTest(failure=failure):
                p = self.root / "relay_artifact.txt"
                original = p.read_bytes()
                p.unlink()
                if failure == "changed":
                    p.write_bytes(b"SYNTHETIC CHANGED")
                if failure == "symlink":
                    p.symlink_to(self.root / "owner.txt")
                with self.assertRaises(ValueError):
                    self.check()
                if p.exists() or p.is_symlink():
                    p.unlink()
                p.write_bytes(original)

    def test_private_reference_ids_refuse_urls_absolute_paths_and_traversal(self):
        for ref in ("https://secret.example/token", "/private/secret", "../secret", "proof/../secret",
                    "proof//file", "./file", "x?token=secret", "x\\file", "x" * 257):
            with self.subTest(ref=ref):
                r = copy.deepcopy(self.receipt)
                r["evidence"]["owner"]["ref"] = ref
                with self.assertRaises(ValueError):
                    self.check(r)

    def test_unsupported_expiry_all_copy_restore_access_and_collection_fail_closed(self):
        for key, value in (("retention_support", "unsupported"), ("retention_support", "unknown"),
                           ("retention_days", 120), ("public_sharing", True),
                           ("collection_off", False), ("identity_inputs", "unknown"),
                           ("expiry_deadline_met", False), ("owned_copies_complete", False),
                           ("owner_role", "unaccepted")):
            with self.subTest(key=key, value=value):
                with self.assertRaises(ValueError):
                    self.check({**self.receipt, key: value})
        for proof in ("all_copies", "restore", "custody_phase"):
            r = copy.deepcopy(self.receipt)
            r["evidence"][proof] = None
            with self.assertRaises(ValueError):
                self.check(r)

    def test_flow_tier_needs_separation_and_ordered_window_proofs(self):
        self.receipt["report_tier"] = "anonymous-flows"
        for identity in ("unknown", "merged"):
            self.receipt["proxy_identity"] = identity
            with self.assertRaises(ValueError):
                self.check()
        self.receipt["proxy_identity"] = "distinct"
        self.assertEqual(self.check()["report_tier"], "anonymous-flows")
        for proof in ("identity", "flow_reports"):
            r = copy.deepcopy(self.receipt)
            r["evidence"][proof] = None
            with self.assertRaises(ValueError):
                self.check(r)

    def test_unknown_fields_types_and_blockers_are_rejected(self):
        variants = [{**self.receipt, "token": "PRIVATE"}, {**self.receipt, "schema": True},
                    {**self.receipt, "schema": 2}, {**self.receipt, "blockers": ["arbitrary secret"]},
                    {**self.receipt, "public_sharing": "false"}, {**self.receipt, "retention_days": True},
                    {**self.receipt, "evidence": {}}, {**self.receipt, "readiness": "READY"}]
        for r in variants:
            with self.subTest(fields=list(r)):
                with self.assertRaises(ValueError):
                    self.check(r)

    def cli(self, raw=None, args=()):
        path = self.root / "receipt.json"
        path.write_text(json.dumps(self.receipt) if raw is None else raw)
        command = ["python3", str(SCRIPT), "--receipt", str(path), "--evidence-root", str(self.root),
                   "--now", "2026-10-27T12:00:00Z"]
        for key, value in EXPECTED.items():
            command += ["--" + key.replace("_", "-"), str(value)]
        return subprocess.run(command + list(args), capture_output=True, text=True)

    def test_cli_ready_blocked_invalid_exit_codes_and_no_receipt_echo(self):
        ready = self.cli()
        self.assertEqual(ready.returncode, 0, ready.stderr)
        self.assertEqual(json.loads(ready.stdout)["readiness"], "ready")
        self.receipt.update(readiness="blocked", blockers=["COLLECTOR_IMAGE_UNAVAILABLE"])
        blocked = self.cli()
        self.assertEqual(blocked.returncode, 1)
        self.assertEqual(json.loads(blocked.stdout)["readiness"], "blocked")
        invalid = self.cli('{"token":"PRIVATE-SECRET"}')
        self.assertEqual(invalid.returncode, 2)
        self.assertNotIn("PRIVATE-SECRET", invalid.stdout + invalid.stderr)
        self.assertEqual(json.loads(invalid.stdout)["readiness"], "invalid")

    def test_cli_refuses_duplicate_json_and_oversized_receipts(self):
        raw = json.dumps(self.receipt)
        for value in (raw[:-1] + ',"schema":1}', " " * 65537):
            with self.subTest(size=len(value)):
                self.assertEqual(self.cli(value).returncode, 2)

    def test_old_proof_cannot_follow_a_changed_expected_artifact_or_policy(self):
        for key, value in (("app_build", "f" * 64), ("app_image", "sha256:" + "f" * 64),
                           ("collector_image", "sha256:" + "f" * 64), ("policy_sha256", "f" * 64)):
            with self.subTest(key=key):
                expected = {**EXPECTED, key: value}
                r = {**self.receipt, key: value}
                with self.assertRaises(ValueError):
                    self.check(r, expected)

    def test_deadline_failure_and_unknown_copies_stay_explicitly_blocked(self):
        self.receipt.update(readiness="blocked", expiry_deadline_met=False, owned_copies_complete=False,
                            blockers=["EXPIRY_DEADLINE_MISSED", "OWNED_COPIES_UNKNOWN"])
        self.assertEqual(self.check()["readiness"], "blocked")

    def test_evidence_size_nonregular_file_and_parent_symlink_are_refused(self):
        proof = self.receipt["evidence"]["owner"]
        for kind in ("oversize", "directory", "parent-symlink"):
            with self.subTest(kind=kind):
                r = copy.deepcopy(self.receipt)
                if kind == "oversize":
                    p = self.root / "oversize.txt"
                    p.write_bytes(b"x" * (1024 * 1024 + 1))
                    r["evidence"]["owner"]["ref"] = p.name
                elif kind == "directory":
                    p = self.root / "directory"
                    p.mkdir()
                    r["evidence"]["owner"]["ref"] = p.name
                else:
                    (self.root / "linked").symlink_to(self.root, target_is_directory=True)
                    r["evidence"]["owner"]["ref"] = "linked/" + proof["ref"]
                with self.assertRaises(ValueError):
                    self.check(r)

    def test_runtime_admission_is_not_a_rollout_receipt(self):
        admission = {"schema": 1, "generation": 1, "state": "ready",
                     "checked_at": "2026-10-27T12:00:00Z", "valid_until": "2026-10-27T12:01:00Z",
                     "app_build": EXPECTED["app_build"]}
        with self.assertRaises(ValueError):
            self.check(admission)

    def test_cli_malformed_argument_values_are_not_echoed(self):
        for flag in ("--contract-schema", "--relay-interface-schema"):
            with self.subTest(flag=flag):
                marker = "/synthetic/private/PRIVATE-SCHEMA-MARKER"
                result = self.cli(args=(flag, marker))
                self.assertEqual(result.returncode, 2)
                self.assertNotIn(marker, result.stdout + result.stderr)
                self.assertEqual(result.stderr, "")
                self.assertEqual(json.loads(result.stdout), {"readiness": "invalid", "errors": ["RECEIPT_REFUSED"]})

    def test_cli_unknown_options_are_not_echoed(self):
        marker = "/synthetic/private/PRIVATE-PROOF-PATH-MARKER"
        result = self.cli(args=("--unsupported-PRIVATE-OPTION-MARKER", marker))
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(marker, result.stdout + result.stderr)
        self.assertNotIn("PRIVATE-OPTION-MARKER", result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(json.loads(result.stdout), {"readiness": "invalid", "errors": ["RECEIPT_REFUSED"]})

    def test_cli_intentional_help_remains_available(self):
        result = subprocess.run(["python3", str(SCRIPT), "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        self.assertIn("--evidence-root", result.stdout)
        self.assertIn("--app-build", result.stdout)
        self.assertNotIn("RECEIPT_REFUSED", result.stdout)

    def test_cli_all_expected_flags_are_mandatory(self):
        result = subprocess.run(["python3", str(SCRIPT), "--receipt", "unused"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
