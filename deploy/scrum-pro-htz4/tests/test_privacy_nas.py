import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[3]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

nas = load("privacy_nas_test", ROOT / "deploy/scrum-pro-htz4/privacy-nas.py")
maintenance = load("privacy_maintenance_nas_test", ROOT / "scripts/privacy-maintenance.py")
UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 27, 0, 0, tzinfo=UTC)

class NASPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.backups = self.root / "htz-4g-nbg"
        self.custody = self.root / "scrum-pro-privacy"
        self.backups.mkdir(mode=0o700)

    def dump(self, name, age, contents=b"PGDMPdisposable synthetic test archive"):
        directory = self.backups / name
        directory.mkdir(mode=0o700)
        target = directory / "scrum-pro-parley.dump"
        target.write_bytes(contents)
        target.chmod(0o600)
        captured = (NOW-dt.timedelta(days=age)).timestamp()
        os.utime(target, (captured, captured))
        return target

    def journal(self, instance=None, records=None):
        return {"version": 1, "instance_id": instance or str(uuid.uuid4()),
                "deletions": records or []}

    def receive(self, data):
        return nas.receive_journal(json.dumps(data).encode(), self.custody, maintenance)

    def test_dry_run_keeps_expired_and_fresh_dumps(self):
        expired = self.dump("20260920_040006", 31)
        fresh = self.dump("20261026_040006", 1)
        result = nas.expire_backups(self.backups, self.custody, now=NOW)
        self.assertEqual(result["expired"], 1)
        self.assertEqual(result["deleted"], 0)
        self.assertTrue(expired.exists())
        self.assertTrue(fresh.exists())

    def test_apply_deletes_only_scrum_dump_and_preserves_other_apps_and_directories(self):
        expired = self.dump("20260920_040006", 31)
        fresh = self.dump("20261026_040006", 1)
        for name in ["config.tar.gz", "leidenfrost-db.sql.gz", "howthefrance.sqlite"]:
            (expired.parent / name).write_bytes(b"unrelated app, must stay")
        result = nas.expire_backups(self.backups, self.custody, apply=True, now=NOW)
        self.assertEqual(result["deleted"], 1)
        self.assertFalse(expired.exists())
        self.assertTrue(expired.parent.is_dir())
        self.assertTrue(fresh.exists())
        for name in ["config.tar.gz", "leidenfrost-db.sql.gz", "howthefrance.sqlite"]:
            self.assertEqual((expired.parent / name).read_bytes(), b"unrelated app, must stay")
        audit = self.custody / "expiry-audit.jsonl"
        self.assertEqual(audit.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("disposable synthetic", audit.read_text())

    def test_uses_file_capture_time_not_old_snapshot_name(self):
        old_name_fresh_file = self.dump("20200101_000000", 1)
        boundary = self.dump("20260927_000000", 30)
        result = nas.expire_backups(self.backups, self.custody, apply=True, now=NOW)
        self.assertTrue(old_name_fresh_file.exists())
        self.assertFalse(boundary.exists())
        self.assertEqual(result["deleted"], 1)

    def test_unknown_directory_is_never_traversed(self):
        unknown = self.dump("other-app", 100)
        malformed = self.dump("20269999_999999", 100)
        result = nas.expire_backups(self.backups, self.custody, apply=True, now=NOW)
        self.assertTrue(unknown.exists())
        self.assertTrue(malformed.exists())
        self.assertEqual(result["deleted"], 0)

    def test_snapshot_symlink_refused_before_any_deletion(self):
        expired = self.dump("20260920_040006", 31)
        outside = self.root / "outside"
        outside.mkdir(mode=0o700)
        (self.backups / "20260921_040006").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            nas.expire_backups(self.backups, self.custody, apply=True, now=NOW)
        self.assertTrue(expired.exists())

    def test_dump_symlink_or_hardlink_refused(self):
        for hard in [False, True]:
            with self.subTest(hard=hard):
                name = "20260922_040006" if hard else "20260923_040006"
                directory = self.backups / name
                directory.mkdir(mode=0o700)
                source = self.root / (name + ".dump")
                source.write_bytes(b"PGDMPmust not unlink linked source")
                source.chmod(0o600)
                target = directory / "scrum-pro-parley.dump"
                if hard:
                    os.link(source, target)
                else:
                    target.symlink_to(source)
                with self.assertRaises(ValueError):
                    nas.expire_backups(self.backups, self.custody, apply=True, now=NOW)
                self.assertTrue(source.exists())
                target.unlink()

    def test_invalid_archive_or_public_file_refused(self):
        bad = self.dump("20260920_040006", 31, b"not a database archive")
        with self.assertRaises(ValueError):
            nas.expire_backups(self.backups, self.custody, apply=True, now=NOW)
        self.assertTrue(bad.exists())
        bad.write_bytes(b"PGDMPsynthetic")
        bad.chmod(0o644)
        with self.assertRaises(ValueError):
            nas.expire_backups(self.backups, self.custody, apply=True, now=NOW)

    def test_journal_receive_is_private_cumulative_and_idempotent(self):
        record = {"kind": "session", "object_id": str(uuid.uuid4()), "deleted_at": "2026-10-26T00:00:00Z"}
        data = self.journal(records=[record])
        first = self.receive(data)
        path = self.custody / "journal/deletions.json"
        original = path.read_bytes()
        again = self.receive(data)
        merged = self.receive(self.journal(instance=data["instance_id"]))
        self.assertEqual(first, again)
        self.assertEqual(merged, first)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(first["status"], "ok")
        self.assertEqual(first["receipt_count"], 1)

    def test_wrong_instance_journal_cannot_replace_existing_custody(self):
        self.receive(self.journal())
        path = self.custody / "journal/deletions.json"
        original = path.read_bytes()
        with self.assertRaises(ValueError):
            self.receive(self.journal())
        self.assertEqual(path.read_bytes(), original)

    def test_receive_rejects_oversized_input_and_traversal_structure(self):
        with self.assertRaises(ValueError):
            nas.receive_journal(b" " * (10*1024*1024+1), self.custody, maintenance)
        data = self.journal()
        data["deletions"] = [{"kind": "../profile", "object_id": str(uuid.uuid4()), "deleted_at": "2026-10-26T00:00:00Z"}]
        with self.assertRaises(ValueError):
            self.receive(data)

    def test_expiry_command_writes_private_fresh_zero_deletion_status(self):
        self.dump("20261026_040006", 1)
        result = nas.run_expiry_command(self.backups, self.custody, apply=True, now=NOW)
        path = self.custody / "expiry-status.json"
        status = json.loads(path.read_text())
        self.assertEqual(status, result)
        self.assertEqual(status["status"], "ok")
        self.assertEqual(status["checked_at"], "2026-10-27T00:00:00+00:00")
        self.assertEqual(status["scanned"], 1)
        self.assertEqual(status["deleted"], 0)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_expiry_failure_records_only_sanitized_failed_status(self):
        self.dump("20261026_040006", 1)
        nas.run_expiry_command(self.backups, self.custody, apply=True, now=NOW)
        self.dump("20260920_040006", 31, contents=b"private sensitive invalid archive")
        later = NOW + dt.timedelta(minutes=1)
        with self.assertRaises(ValueError):
            nas.run_expiry_command(self.backups, self.custody, apply=True, now=later)
        raw = (self.custody / "expiry-status.json").read_text()
        status = json.loads(raw)
        self.assertEqual(status, {"version": 1, "status": "failed", "apply": True,
                                  "checked_at": "2026-10-27T00:01:00+00:00"})
        self.assertNotIn("private sensitive", raw)
        self.assertNotIn(str(self.root), raw)

    def test_unsafe_custody_or_linked_status_never_written(self):
        self.custody.mkdir(mode=0o755)
        with self.assertRaises(ValueError):
            nas.run_expiry_command(self.backups, self.custody, now=NOW)
        self.assertFalse((self.custody / "expiry-status.json").exists())
        self.custody.chmod(0o700)
        outside = self.root / "outside-status.json"
        outside.write_text("must remain unchanged")
        outside.chmod(0o600)
        (self.custody / "expiry-status.json").symlink_to(outside)
        with self.assertRaises(ValueError):
            nas.run_expiry_command(self.backups, self.custody, now=NOW)
        self.assertEqual(outside.read_text(), "must remain unchanged")

    def test_real_cli_persists_status_and_keeps_receiver_protocol_unchanged(self):
        command = [sys.executable, str(ROOT / "deploy/scrum-pro-htz4/privacy-nas.py")]
        run = subprocess.run(command + ["expire", "--backup-root", str(self.backups),
                             "--custody", str(self.custody)], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        status = json.loads(run.stdout)
        self.assertEqual(status["status"], "ok")
        self.assertTrue(status["checked_at"])
        self.assertEqual(json.loads((self.custody / "expiry-status.json").read_text()), status)
        received = subprocess.run(command + ["receive", "--custody", str(self.custody),
                                  "--maintenance", str(ROOT / "scripts/privacy-maintenance.py")],
                                  input=json.dumps(self.journal()), capture_output=True, text=True)
        self.assertEqual(received.returncode, 0, received.stderr)
        self.assertEqual(set(json.loads(received.stdout)),
                         {"version", "status", "instance_id", "journal_sha256", "receipt_count"})

if __name__ == "__main__":
    unittest.main()
