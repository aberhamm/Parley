"""Behavior checks use disposable artifacts and a fake SQL transport only."""
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

MODULE = Path(__file__).resolve().parents[1] / "privacy-maintenance.py"
spec = importlib.util.spec_from_file_location("privacy_maintenance", MODULE)
privacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(privacy)
INSTANCE = "0a79b002-2da8-44ef-88a7-d5403b0429f7"
OBJECT = "ac2f7e43-0637-4205-9d6c-69ece747e781"
NOW = dt.datetime(2026, 10, 26, tzinfo=dt.timezone.utc)


def receipt(when="2026-10-25T00:00:00Z", kind="session"):
    return {"kind": kind, "object_id": OBJECT, "deleted_at": when}


def journal(records=None, instance=INSTANCE):
    return {"version": 1, "instance_id": instance, "deletions": records or []}


class JournalTests(unittest.TestCase):
    def test_export_merges_existing_receipts_and_is_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.json"
            privacy.write_journal(path, journal([receipt()]))
            privacy.write_journal(path, journal([receipt("2026-10-26T00:00:00Z"), receipt(kind="space")]))
            saved = json.loads(path.read_text())
            self.assertEqual(len(saved["deletions"]), 2)
            self.assertEqual(saved["deletions"][0]["deleted_at"], "2026-10-25T00:00:00Z")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_export_refuses_to_replace_another_instance(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.json"
            privacy.write_journal(path, journal([receipt()]))
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                privacy.write_journal(path, journal(instance=OBJECT))
            self.assertEqual(path.read_bytes(), before)

    def test_invalid_records_rejected_before_any_sql(self):
        bad_records = [dict(receipt(), object_id="';delete from users;--"),
                       dict(receipt(), kind="users"), dict(receipt(), kind=[]),
                       dict(receipt(), deleted_at="tomorrow")]
        for record in bad_records:
            client = mock.Mock()
            with self.assertRaises(ValueError):
                privacy.replay_journal(journal([record]), client, writers_stopped=True)
            client.query.assert_not_called()

    def test_replay_requires_stopped_writer_acknowledgment(self):
        client = mock.Mock()
        with self.assertRaises(ValueError):
            privacy.replay_journal(journal([receipt()]), client, writers_stopped=False)
        client.query.assert_not_called()

    def test_wrong_instance_rejected_without_mutating_sql(self):
        client = mock.Mock()
        client.query.return_value = {"instance_id": OBJECT}
        with self.assertRaises(ValueError):
            privacy.replay_journal(journal([receipt()]), client, writers_stopped=True)
        self.assertEqual(client.query.call_count, 1)
        self.assertNotIn("begin", client.query.call_args.args[0].lower())

    def test_replay_is_one_transaction_with_instance_recheck(self):
        client = mock.Mock()
        client.query.side_effect = [{"instance_id": INSTANCE}, None]
        result = privacy.replay_journal(journal([receipt(), receipt(kind="profile")]), client, writers_stopped=True)
        self.assertEqual(result, 2)
        sql = client.query.call_args.args[0].lower()
        self.assertTrue(sql.startswith("begin;"))
        self.assertTrue(sql.rstrip().endswith("commit;"))
        self.assertIn("privacy_erase_session", sql)
        self.assertIn("privacy_erase_profile", sql)
        self.assertIn("privacy_meta", sql)
        self.assertIn("raise exception", sql)
        self.assertIn("least", sql)

    def test_journal_rejects_duplicate_unknown_and_excess_records(self):
        for data in [journal([receipt(), receipt()]), dict(journal(), names=[]),
                     journal([dict(receipt(), name="private")])]:
            with self.assertRaises(ValueError):
                privacy.validate_journal(data)
        with mock.patch.object(privacy, "MAX_RECORDS", 1):
            with self.assertRaises(ValueError):
                privacy.validate_journal(journal([receipt(), receipt(kind="space")]))

    def test_journal_refuses_symlink_and_public_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "journal.json"
            path.write_text(json.dumps(journal()))
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                privacy.read_journal(path)
            path.chmod(0o600)
            link = root / "link.json"
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                privacy.read_journal(link)

    def test_sql_transport_does_not_put_dsn_in_argv_or_failure_output(self):
        secret = "postgres://private:never-print-this@127.0.0.1/scratch"
        failed = mock.Mock(returncode=1, stdout="", stderr=secret)
        with mock.patch.dict(os.environ, {"DATABASE_URL": secret}), mock.patch.object(privacy.subprocess, "run", return_value=failed) as run:
            with self.assertRaises(ValueError) as error:
                privacy.SQLClient().query("select 1;")
            self.assertNotIn(secret, str(error.exception))
            self.assertNotIn(secret, " ".join(run.call_args.args[0]))
            self.assertEqual(run.call_args.kwargs["env"]["PGDATABASE"], "scratch")
            self.assertEqual(run.call_args.kwargs["env"]["PGPASSWORD"], "never-print-this")
            self.assertEqual(run.call_args.kwargs["env"]["PGUSER"], "private")
            self.assertEqual(run.call_args.kwargs["env"]["PGHOST"], "127.0.0.1")

    def test_connection_options_are_preserved_and_unknown_ones_refused(self):
        with mock.patch.dict(os.environ, {"PGHOST": "wrong-host", "PGPASSWORD": "stale-password"}):
            env = privacy.connection_environment("postgresql://parley@/scratch?sslmode=verify-full&sslrootcert=%2Fprivate%2Fca.pem")
        self.assertEqual(env["PGSSLMODE"], "verify-full")
        self.assertEqual(env["PGSSLROOTCERT"], "/private/ca.pem")
        self.assertNotIn("PGHOST", env)
        self.assertNotIn("PGPASSWORD", env)
        for dsn in ["postgresql://u@localhost/db?sslmode=disable&sslmode=require", "dbname=private", "postgresql://u@localhost/db?mystery=1"]:
            with self.assertRaises(ValueError): privacy.connection_environment(dsn)

    def test_sql_failure_is_not_reported_as_replay_success(self):
        client = mock.Mock()
        client.query.side_effect = [{"instance_id": INSTANCE}, ValueError("database operation failed")]
        with self.assertRaises(ValueError):
            privacy.replay_journal(journal([receipt()]), client, writers_stopped=True)


class ArtifactTests(unittest.TestCase):
    def setup_artifacts(self, root):
        artifacts = []
        for name, expiry in [("old.dump.enc", "2026-10-25T00:00:00Z"),
                             ("new.dump.enc", "2026-11-01T00:00:00Z")]:
            path = root / name
            path.write_bytes(b"not production data")
            path.chmod(0o600)
            artifacts.append({"path": name, "kind": "backup", "created_at": "2026-10-01T00:00:00Z",
                              "expires_at": expiry, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        return {"version": 1, "owner": "scrum-pro-privacy-maintenance", "artifacts": artifacts}

    def test_dry_run_keeps_all_and_apply_removes_only_expired(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.setup_artifacts(root)
            result = privacy.expire_artifacts(root, manifest, apply=False, now=NOW)
            self.assertEqual([x["status"] for x in result], ["would_delete", "keep"])
            self.assertTrue((root / "old.dump.enc").exists())
            result = privacy.expire_artifacts(root, manifest, apply=True, now=NOW)
            self.assertEqual([x["status"] for x in result], ["deleted", "keep"])
            self.assertFalse((root / "old.dump.enc").exists())
            self.assertTrue((root / "new.dump.enc").exists())
            audit = json.loads((root / "privacy-expiry-audit.jsonl").read_text().splitlines()[-1])
            self.assertEqual(audit["status"], "deleted")
            self.assertNotIn("content", audit)

    def test_bad_manifest_prevents_every_deletion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.setup_artifacts(root)
            manifest["artifacts"][1]["path"] = "../secret.key"
            with self.assertRaises(ValueError):
                privacy.expire_artifacts(root, manifest, apply=True, now=NOW)
            self.assertTrue((root / "old.dump.enc").exists())

    def test_symlink_checksum_mismatch_hardlink_and_key_refused(self):
        for failure in ["symlink", "checksum", "hardlink", "key"]:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest = self.setup_artifacts(root)
                old = root / "old.dump.enc"
                if failure == "symlink":
                    old.unlink(); old.symlink_to(root / "new.dump.enc")
                elif failure == "checksum": old.write_bytes(b"changed")
                elif failure == "hardlink": os.link(old, root / "other.dump.enc")
                else: manifest["artifacts"][0]["path"] = "backup.key"
                with self.assertRaises(ValueError):
                    privacy.expire_artifacts(root, manifest, apply=True, now=NOW)
                self.assertTrue((root / "new.dump.enc").exists())

    def test_ownership_and_future_dates_are_not_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for tweak in [lambda m: m.update(owner="someone-else"),
                          lambda m: m["artifacts"][0].update(created_at="2026-10-26T00:00:00Z")]:
                manifest = self.setup_artifacts(root); tweak(manifest)
                with self.assertRaises(ValueError):
                    privacy.expire_artifacts(root, manifest, apply=True, now=NOW)
            root.chmod(0o755)
            with self.assertRaises(ValueError):
                privacy.expire_artifacts(root, self.setup_artifacts(root), apply=True, now=NOW)

    def test_current_docker_log_and_recovery_audit_are_refused(self):
        for name in ["container-json.log", "privacy-expiry-audit.jsonl", "privacy-journal.jsonl"]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest = self.setup_artifacts(root)
                manifest["artifacts"][0].update(path=name, kind="log")
                with self.assertRaises(ValueError):
                    privacy.expire_artifacts(root, manifest, apply=True, now=NOW)

    def test_archived_json_log_expires_using_same_exact_file_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.setup_artifacts(root)
            (root / "old.dump.enc").rename(root / "container-json.log.1")
            manifest["artifacts"][0].update(path="container-json.log.1", kind="log")
            result = privacy.expire_artifacts(root, manifest, apply=True, now=NOW)
            self.assertEqual(result[0]["status"], "deleted")
            self.assertFalse((root / "container-json.log.1").exists())

    def test_explicit_closed_plain_archive_expires_but_active_plain_logs_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.setup_artifacts(root)
            (root / "old.dump.enc").rename(root / "readiness.archived.log")
            manifest["artifacts"][0].update(path="readiness.archived.log", kind="log")
            result = privacy.expire_artifacts(root, manifest, apply=True, now=NOW)
            self.assertEqual(result[0]["status"], "deleted")
            self.assertFalse((root / "readiness.archived.log").exists())
        for name in ["server.log", "preview.log", "container-json.log", "ordinary.log"]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest = self.setup_artifacts(root)
                manifest["artifacts"][0].update(path=name, kind="log")
                with self.assertRaises(ValueError):
                    privacy.expire_artifacts(root, manifest, apply=True, now=NOW)


if __name__ == "__main__":
    unittest.main()
