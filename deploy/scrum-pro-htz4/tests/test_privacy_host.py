"""Dedicated host maintenance checks use only synthetic temporary artifacts."""
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HOST = Path(__file__).resolve().parents[1] / "privacy-host.py"
spec = importlib.util.spec_from_file_location("privacy_host", HOST)
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)
UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 27, 15, tzinfo=UTC)
INSTANCE = "0a79b002-2da8-44ef-88a7-d5403b0429f7"


class HostTests(unittest.TestCase):
    def private_dirs(self, root):
        paths = {name: root / name for name in ["state", "logs", "backups"]}
        for path in paths.values(): path.mkdir(mode=0o700)
        (paths["state"] / "journal").mkdir(mode=0o700)
        return paths

    def file(self, root, name, content=b"synthetic only"):
        path = root / name; path.write_bytes(content); path.chmod(0o600); return path

    def backup_manifest(self, paths, *, bad_expiry=False):
        records = []
        for name, created in [("old.dump.enc", NOW-dt.timedelta(days=40)), ("new.tar.gz.enc", NOW-dt.timedelta(days=1))]:
            path = self.file(paths["backups"], name)
            records.append({"path": name, "kind": "backup", "created_at": host.maintenance.utc_string(created),
                            "expires_at": host.maintenance.utc_string(created+dt.timedelta(days=31 if bad_expiry else 30)),
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        data = {"version": 1, "owner": host.maintenance.OWNER, "artifacts": records}
        p = paths["state"] / "backup-manifest.json"; p.write_text(json.dumps(data)); p.chmod(0o600)
        return data

    def client(self):
        client = mock.Mock()
        client.query.return_value = {"version": 1, "instance_id": INSTANCE, "deletions": []}
        return client

    def test_enrolls_only_previous_utc_days_and_strict_daily_rotations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.file(root, "scrum-pro-2026-10-10.jsonl")
            self.file(root, "scrum-pro-2026-10-26.1.jsonl")
            self.file(root, "scrum-pro-2026-10-27.jsonl")
            self.file(root, "other-app-2026-10-10.jsonl")
            self.file(root, "privacy-expiry-audit.jsonl")
            self.file(root, "scrum-pro-2026-10-10.4.jsonl")
            data = host.log_manifest(root, NOW)
            self.assertEqual([r["path"] for r in data["artifacts"]], ["scrum-pro-2026-10-10.jsonl", "scrum-pro-2026-10-26.1.jsonl"])
            self.assertEqual(data["artifacts"][0]["expires_at"], "2026-10-17T00:00:00Z")

    def test_recognized_symlinks_invalid_dates_and_future_files_refused(self):
        for case in ["symlink", "invalid-date", "future"]:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                if case == "symlink":
                    self.file(root, "outside.txt")
                    (root / "scrum-pro-2026-10-10.jsonl").symlink_to(root / "outside.txt")
                elif case == "invalid-date": self.file(root, "scrum-pro-2026-02-31.jsonl")
                else: self.file(root, "scrum-pro-2026-10-28.jsonl")
                with self.assertRaises(ValueError): host.log_manifest(root, NOW)

    def test_runs_dry_first_and_apply_removes_only_expired_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.private_dirs(Path(tmp)); self.backup_manifest(paths)
            old = self.file(paths["logs"], "scrum-pro-2026-10-10.jsonl")
            fresh = self.file(paths["logs"], "scrum-pro-2026-10-26.jsonl")
            today = self.file(paths["logs"], "scrum-pro-2026-10-27.jsonl")
            status = host.run_maintenance(paths, self.client(), apply=False, now=NOW, rotate=lambda _: None)
            self.assertEqual(status["status"], "dry_run")
            self.assertTrue(old.exists()); self.assertTrue((paths["backups"] / "old.dump.enc").exists())
            status = host.run_maintenance(paths, self.client(), apply=True, now=NOW, rotate=lambda _: None)
            self.assertEqual(status["status"], "ok")
            self.assertEqual(status["expiry"]["deleted"], 2)
            self.assertEqual(status["expiry"]["kept"], 2)
            self.assertFalse(old.exists()); self.assertFalse((paths["backups"] / "old.dump.enc").exists())
            self.assertTrue(fresh.exists()); self.assertTrue(today.exists())
            journal = paths["state"] / "journal/deletions.json"
            self.assertEqual(status["journal_sha256"], hashlib.sha256(journal.read_bytes()).hexdigest())
            self.assertEqual(journal.stat().st_mode & 0o777, 0o600)
            self.assertEqual((paths["state"] / "status.json").stat().st_mode & 0o777, 0o600)
            self.assertEqual(set(status), {"version","instance_id","exported_at","journal_sha256","receipt_count","status","expiry"})

    def test_bad_backup_policy_aborts_before_any_log_deletion(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.private_dirs(Path(tmp)); self.backup_manifest(paths, bad_expiry=True)
            old = self.file(paths["logs"], "scrum-pro-2026-10-10.jsonl")
            with self.assertRaises(ValueError):
                host.run_maintenance(paths, self.client(), apply=True, now=NOW, rotate=lambda _: None)
            self.assertTrue(old.exists())
            self.assertEqual(json.loads((paths["state"] / "status.json").read_text())["status"], "failed")

    def test_export_failure_preserves_existing_journal_and_marks_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.private_dirs(Path(tmp)); self.backup_manifest(paths)
            journal = paths["state"] / "journal/deletions.json"
            host.maintenance.write_journal(journal, {"version":1,"instance_id":INSTANCE,"deletions":[]})
            original = journal.read_bytes(); client = self.client(); client.query.side_effect = ValueError("private failure")
            with self.assertRaises(ValueError):
                host.run_maintenance(paths, client, apply=True, now=NOW, rotate=lambda _: None)
            self.assertEqual(journal.read_bytes(), original)
            self.assertNotIn("private failure", (paths["state"] / "status.json").read_text())
            self.assertEqual(json.loads((paths["state"] / "status.json").read_text())["status"], "failed")

    def test_only_explicit_encrypted_backup_inventory_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.private_dirs(Path(tmp)); data = self.backup_manifest(paths)
            for name in ["key.pem", "../old.dump.enc", "other.sql.enc", "old.dump.age"]:
                with self.subTest(name=name):
                    changed = json.loads(json.dumps(data)); changed["artifacts"][0]["path"] = name
                    with self.assertRaises(ValueError): host.validate_backup_manifest(changed, NOW)
            self.file(paths["backups"], "unenrolled.dump.enc")
            host.run_maintenance(paths, self.client(), apply=True, now=NOW, rotate=lambda _: None)
            self.assertTrue((paths["backups"] / "unenrolled.dump.enc").exists())

    def test_docker_sql_has_fixed_container_and_no_credentials_in_argv(self):
        done = subprocess.CompletedProcess([], 0, stdout=b'{"value":1}\n', stderr=b'')
        with mock.patch.object(host.subprocess, "run", return_value=done) as run:
            self.assertEqual(host.DockerSQL().query("select 1;"), {"value":1})
            argv = run.call_args.args[0]
            self.assertEqual(argv[:5], ["/usr/bin/docker","exec","-i","scrum-pro-db-1","psql"])
            self.assertIn("-q", argv); self.assertNotIn("DATABASE_URL", " ".join(argv))
            self.assertEqual(run.call_args.kwargs["input"], b"select 1;")

    def test_database_failure_does_not_expose_docker_stderr(self):
        done = subprocess.CompletedProcess([],1,stdout=b'{"value":1}\n',stderr=b"private log body/token")
        with mock.patch.object(host.subprocess,"run",return_value=done):
            with self.assertRaises(ValueError) as error:host.DockerSQL().query("select 1;")
        self.assertNotIn("private log body/token",str(error.exception))

    def test_checksum_failure_in_backup_preflight_prevents_log_deletion(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths=self.private_dirs(Path(tmp));self.backup_manifest(paths)
            old=self.file(paths["logs"],"scrum-pro-2026-10-10.jsonl")
            (paths["backups"] / "new.tar.gz.enc").write_bytes(b"changed after explicit enrollment")
            with self.assertRaises(ValueError):
                host.run_maintenance(paths,self.client(),apply=True,now=NOW,rotate=lambda _:None)
            self.assertTrue(old.exists())
            self.assertTrue((paths["backups"] / "old.dump.enc").exists())

    def test_fixture_deletes_synthetic_expired_files_and_requires_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = host.run_fixture(root, apply=True, now=NOW)
            self.assertEqual(result["expiry"]["deleted"], 2)
            self.assertFalse((root / "logs/scrum-pro-2026-10-17.jsonl").exists())
            self.assertTrue((root / "logs/scrum-pro-2026-10-26.jsonl").exists())
            with self.assertRaises(ValueError): host.run_fixture(root, apply=True, now=NOW)

    def test_fixture_cli_uses_only_explicit_disposable_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run([sys.executable,str(HOST),"fixture","--directory",tmp,"--apply"],
                                    text=True,capture_output=True,check=True)
            self.assertEqual(json.loads(result.stdout)["expiry"]["deleted"],2)

    def test_rotation_uses_private_config_and_state_not_shared_host_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp);self.file(state,"logrotate-scrum-pro.conf",b"# synthetic test config")
            with mock.patch.object(host.subprocess,"run",return_value=subprocess.CompletedProcess([],0,stdout=b"",stderr=b"")) as run:
                host.rotate_logs(state)
                self.assertEqual(run.call_args.args[0],["/usr/sbin/logrotate","--state",str(state/"logrotate.status"),str(state/"logrotate-scrum-pro.conf")])
            self.assertEqual((state/"logrotate.status").stat().st_mode & 0o777,0o600)

    def test_dedicated_config_contracts_do_not_include_shared_logging(self):
        # These assertions verify the reviewed contract, not daemon syntax/runtime.
        folder=HOST.parent
        config=(folder/"rsyslog-scrum-pro.conf").read_text()
        self.assertIn('SysSock.Use="off"',config)
        self.assertIn('Socket="/run/scrum-pro-logging/syslog.sock"',config)
        self.assertIn('UseSpecialParser="off"',config)
        self.assertIn('re_match($app-name,',config)
        self.assertIn('ParseHostname="on"',config)
        self.assertIn('RateLimit.Interval="5" RateLimit.Burst="200" RateLimit.Severity="0"',config)
        self.assertIn('queue.type="Direct"',config)
        # RainerScript expands '$' in double-quoted strings, including regexes.
        self.assertIn(r'(-[0-9]+)?\$"',config)
        self.assertEqual(config.count('date.inUTC="on"'),4)
        self.assertNotIn('module(load="imjournal"',config)
        self.assertNotIn('module(load="imtcp"',config)
        self.assertNotIn('include(file=',config)
        rotate=(folder/"logrotate-scrum-pro.conf").read_text()
        for setting in ["copytruncate","maxsize 10M","rotate 3","extension .jsonl"]:self.assertIn(setting,rotate)
        unit=(folder/"systemd/scrum-pro-logging.service").read_text()
        self.assertIn("MemoryMax=32M",unit)
        self.assertIn("Restart=always",unit)
        timer=(folder/"systemd/scrum-pro-privacy-maintenance.timer").read_text()
        self.assertIn("OnUnitActiveSec=60s",timer)

    def test_stack_restarts_with_its_required_runtime_and_logger(self):
        import configparser
        unit = configparser.ConfigParser(interpolation=None)
        unit.read(HOST.parent / "systemd/scrum-pro-stack.service")
        dependencies = {"docker.service", "scrum-pro-logging.service"}
        # Requires stops this RemainAfterExit stack when a dependency stops;
        # PartOf also propagates its restart rather than leaving the explicitly
        # stopped unless-stopped containers down afterward.
        self.assertEqual(set(unit["Unit"].get("PartOf", "").split()), dependencies)
        self.assertEqual(set(unit["Unit"]["Requires"].split()), dependencies)
        self.assertEqual(set(unit["Unit"]["After"].split()),
                         dependencies | {"network-online.target"})
        self.assertEqual(unit["Service"]["RemainAfterExit"], "yes")
        self.assertEqual(unit["Service"]["ExecStop"], "/opt/apps/scrum-pro/manage.sh stop")


if __name__ == "__main__": unittest.main()
