"""Disposable local fixtures; no real SSH, databases, or deployment files."""
import base64
import datetime as dt
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import stat
import tempfile
import unittest
import sys
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / "privacy-studio.py"
spec = importlib.util.spec_from_file_location("privacy_studio", SOURCE)
studio = importlib.util.module_from_spec(spec)
spec.loader.exec_module(studio)
NOW = dt.datetime(2026, 10, 27, 12, tzinfo=dt.timezone.utc)
INSTANCE = "0a79b002-2da8-44ef-88a7-d5403b0429f7"
OBJECT = "ac2f7e43-0637-4205-9d6c-69ece747e781"


def receipt(kind="session", when="2026-10-26T00:00:00Z"):
    return {"kind": kind, "object_id": OBJECT, "deleted_at": when}


def envelope(records=None, *, exported="2026-10-27T12:00:00Z", instance=INSTANCE):
    journal = {"version": 1, "instance_id": instance, "deletions": records or []}
    raw = (json.dumps(journal, indent=2) + "\n").encode()
    return {"status": {"version": 1, "instance_id": instance, "exported_at": exported,
                       "journal_sha256": hashlib.sha256(raw).hexdigest(),
                       "receipt_count": len(records or []), "status": "ok"},
            "journal_b64": base64.b64encode(raw).decode()}


class StudioTests(unittest.TestCase):
    def test_sync_keeps_private_cumulative_journal_and_durable_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            config = {"version": 1, "instance_id": INSTANCE, "managed_directories": []}
            studio.sync_once(config, root, transport=lambda: envelope([receipt()]), now=NOW)
            journal = root / "journal/deletions.json"
            self.assertTrue(journal.exists(), "off-host sync must durably create a private journal")
            data = json.loads(journal.read_text())
            self.assertEqual(data["deletions"], [receipt()])
            self.assertEqual(stat.S_IMODE(journal.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(journal.parent.stat().st_mode), 0o700)
            state = json.loads((root / "status.json").read_text())
            self.assertEqual(state["status"], "ok")
            self.assertEqual(state["last_success"]["receipt_count"], 1)
            self.assertEqual(state["last_success"]["journal_sha256"], hashlib.sha256(journal.read_bytes()).hexdigest())
            self.assertEqual(stat.S_IMODE((root / "status.json").stat().st_mode), 0o600)

    def test_older_host_export_and_reruns_never_drop_known_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            config = {"version": 1, "instance_id": INSTANCE, "managed_directories": []}
            fresh = envelope([receipt(), receipt("space")])
            studio.sync_once(config, root, transport=lambda: fresh, now=NOW)
            before = (root / "journal/deletions.json").read_bytes()
            older = envelope([receipt(when="2026-10-27T00:00:00Z")], exported="2026-10-27T11:59:00Z")
            for source in [older, older, fresh]:
                state = studio.sync_once(config, root, transport=lambda: source, now=NOW)
                self.assertEqual((root / "journal/deletions.json").read_bytes(), before)
                self.assertEqual(state["last_success"]["receipt_count"], 2)

    def test_bad_source_keeps_journal_and_last_success_without_raw_failure(self):
        for source in [envelope(instance=OBJECT), envelope(exported="2026-10-27T11:54:59Z"),
                       envelope(exported="2026-10-27T12:01:01Z"),
                       {"status": {"version": 1, "status": "failed", "failed_at": "2026-10-27T12:00:00Z"}, "journal_b64": ""}]:
            with self.subTest(source=source["status"].get("status")), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                config = {"version": 1, "instance_id": INSTANCE, "managed_directories": []}
                good = studio.sync_once(config, root, transport=lambda: envelope([receipt()]), now=NOW)
                before = (root / "journal/deletions.json").read_bytes()
                with self.assertRaises(studio.SyncError):
                    studio.sync_once(config, root, transport=lambda: source, now=NOW)
                self.assertEqual((root / "journal/deletions.json").read_bytes(), before)
                state = json.loads((root / "status.json").read_text())
                self.assertEqual(state["last_success"], good["last_success"])
                self.assertEqual(state["status"], "failed")
                with self.assertRaises(studio.SyncError):
                    studio.sync_once(config, root, transport=mock.Mock(side_effect=ValueError("never-log-private-stderr")), now=NOW)
                self.assertNotIn("never-log-private-stderr", (root / "status.json").read_text())
                self.assertEqual((root / "journal/deletions.json").read_bytes(), before)

    def test_checksum_count_duplicate_keys_and_oversize_are_rejected(self):
        changed = envelope([receipt()])
        changed["status"]["receipt_count"] = 2
        badsum = envelope([receipt()])
        badsum["status"]["journal_sha256"] = "0" * 64
        duplicates = envelope()
        raw = ('{"version":1,"version":1,"instance_id":"' + INSTANCE + '","deletions":[]}').encode()
        duplicates["journal_b64"] = base64.b64encode(raw).decode()
        duplicates["status"]["journal_sha256"] = hashlib.sha256(raw).hexdigest()
        for source in [changed, badsum, duplicates]:
            with self.assertRaises(ValueError):
                studio._validate_export(source, INSTANCE, NOW)
        with mock.patch.object(studio.privacy, "MAX_BYTES", 10):
            with self.assertRaises(ValueError):
                studio._validate_export(envelope(), INSTANCE, NOW)

    def test_fsync_and_atomic_replacement_protect_journal_and_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with mock.patch.object(os, "fsync", wraps=os.fsync) as sync, mock.patch.object(os, "replace", wraps=os.replace) as replace:
                studio.sync_once({"version": 1, "instance_id": INSTANCE, "managed_directories": []}, root,
                                 transport=lambda: envelope([receipt()]), now=NOW)
            self.assertGreaterEqual(sync.call_count, 4)
            self.assertEqual(replace.call_count, 2)

    def test_nas_mirror_failure_keeps_local_custody_and_is_not_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            config = {"version": 1, "instance_id": INSTANCE, "managed_directories": [],
                      "nas_mirror": {"target": "matthew.aberham@100.84.185.146"}}
            mirror = mock.Mock(side_effect=ValueError("NAS raw private output"))
            with self.assertRaises(studio.SyncError):
                studio.sync_once(config, root, transport=lambda: envelope([receipt()]), mirror=mirror, now=NOW)
            saved = json.loads((root / "journal/deletions.json").read_text())
            self.assertEqual(saved["deletions"], [receipt()])
            state = json.loads((root / "status.json").read_text())
            self.assertFalse(state["nas_mirror"])
            self.assertEqual(state["local_sync"]["receipt_count"], 1)
            self.assertNotIn("NAS raw private output", json.dumps(state))

    def test_pinned_config_cannot_replace_a_different_local_instance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            config = {"version": 1, "instance_id": INSTANCE, "managed_directories": []}
            studio.sync_once(config, root, transport=lambda: envelope([receipt()]), now=NOW)
            before = (root / "journal/deletions.json").read_bytes()
            wrong = dict(config, instance_id=OBJECT)
            with self.assertRaises(studio.SyncError):
                studio.sync_once(wrong, root, transport=lambda: envelope(instance=OBJECT), now=NOW)
            self.assertEqual((root / "journal/deletions.json").read_bytes(), before)

    def test_nas_acknowledgment_must_match_the_exact_durable_journal(self):
        raw = base64.b64decode(envelope([receipt()])["journal_b64"])
        good = {"version": 1, "status": "ok", "instance_id": INSTANCE,
                "journal_sha256": hashlib.sha256(raw).hexdigest(), "receipt_count": 1}
        with mock.patch.object(studio, "_ssh_bytes", return_value=json.dumps(good).encode()) as transport:
            self.assertEqual(studio.mirror_journal(raw, {"target": "matthew@100.84.185.146"}), good)
            self.assertEqual(transport.call_args.args[0], "matthew@100.84.185.146")
            self.assertTrue(transport.call_args.args[1].endswith("privacy-nas.py receive"))
            self.assertEqual(transport.call_args.args[2], raw)
        for changed in [dict(good, receipt_count=0), dict(good, journal_sha256="0"*64), dict(good, instance_id=OBJECT)]:
            with mock.patch.object(studio, "_ssh_bytes", return_value=json.dumps(changed).encode()):
                with self.assertRaises(studio.SyncError):
                    studio.mirror_journal(raw, {"target": "matthew@100.84.185.146"})

    def test_host_expiry_summary_is_strict_and_receipts_stay_private(self):
        source = envelope([receipt()])
        source["status"]["expiry"] = {"deleted": 1, "kept": 2, "missing": 0,
                                      "backup_retention_days": 30, "log_retention_days": 7}
        studio._validate_export(source, INSTANCE, NOW)
        source["status"]["expiry"]["private_filename"] = "must-not-be-forwarded"
        with self.assertRaises(ValueError):
            studio._validate_export(source, INSTANCE, NOW)

    def test_optional_nas_expiry_accepts_its_fresh_persisted_status_schema(self):
        raw = base64.b64decode(envelope([receipt()])["journal_b64"])
        acknowledgment = {"version": 1, "status": "ok", "instance_id": INSTANCE,
                          "journal_sha256": hashlib.sha256(raw).hexdigest(), "receipt_count": 1}
        expiry = {"version": 1, "status": "ok", "apply": True, "scanned": 2,
                  "expired": 1, "deleted": 1, "skipped": 0,
                  "checked_at": dt.datetime.now(dt.timezone.utc).isoformat()}
        with mock.patch.object(studio, "_ssh_bytes", side_effect=[
                json.dumps(acknowledgment).encode(), json.dumps(expiry).encode()]) as transport:
            self.assertEqual(studio.mirror_journal(raw, {"target": "matthew@100.84.185.146",
                                                        "apply_expiry": True}), acknowledgment)
            self.assertTrue(transport.call_args.args[1].endswith("privacy-nas.py expire --apply"))

    def test_optional_nas_expiry_refuses_stale_future_missing_or_unknown_status_fields(self):
        raw = base64.b64decode(envelope([receipt()])["journal_b64"])
        acknowledgment = {"version": 1, "status": "ok", "instance_id": INSTANCE,
                          "journal_sha256": hashlib.sha256(raw).hexdigest(), "receipt_count": 1}
        now = dt.datetime.now(dt.timezone.utc)
        base = {"version": 1, "status": "ok", "apply": True, "scanned": 0,
                "expired": 0, "deleted": 0, "skipped": 0, "checked_at": now.isoformat()}
        missing = dict(base)
        del missing["checked_at"]
        cases = [dict(base, checked_at=(now-dt.timedelta(minutes=6)).isoformat()),
                 dict(base, checked_at=(now+dt.timedelta(minutes=2)).isoformat()),
                 dict(base, checked_at="invalid"), missing,
                 dict(base, extra="unrecognized-field")]
        for expiry in cases:
            with self.subTest(keys=sorted(expiry)), mock.patch.object(studio, "_ssh_bytes", side_effect=[
                    json.dumps(acknowledgment).encode(), json.dumps(expiry).encode()]):
                with self.assertRaises(ValueError):
                    studio.mirror_journal(raw, {"target": "matthew@100.84.185.146", "apply_expiry": True})


class EnrollmentTests(unittest.TestCase):
    def test_local_expiry_is_independent_of_source_or_mirror_outages(self):
        for failure in ["ssh", "wrong_instance", "nas"]:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                custody = root / "custody"
                custody.mkdir(mode=0o700)
                archive = custody / "expired.dump.enc"
                archive.write_bytes(b"synthetic expired archive")
                archive.chmod(0o600)
                created = dt.datetime(2026, 9, 20, tzinfo=dt.timezone.utc)
                os.utime(archive, (created.timestamp(), created.timestamp()))
                config = {"version": 1, "instance_id": INSTANCE,
                          "managed_directories": [str(custody)]}
                if failure == "nas":
                    config["nas_mirror"] = {"target": "matthew@100.84.185.146"}
                with mock.patch.object(studio, "ALLOWED_DIRECTORIES", frozenset({str(custody)})):
                    studio.enroll_artifact(custody, archive.name, hashlib.sha256(archive.read_bytes()).hexdigest(), "2026-10-20T00:00:00Z", now=NOW)
                    good = studio.sync_once(config, root, transport=lambda: envelope([receipt()]), mirror=lambda *_: None, now=NOW)
                    before = (root / "journal/deletions.json").read_bytes()
                    transport = (mock.Mock(side_effect=ValueError("private SSH error")) if failure == "ssh"
                                 else lambda: envelope([receipt()], instance=OBJECT if failure == "wrong_instance" else INSTANCE))
                    mirror = mock.Mock(side_effect=ValueError("private NAS error")) if failure == "nas" else lambda *_: None
                    with self.assertRaises(studio.SyncError):
                        studio.sync_once(config, root, transport=transport, mirror=mirror, now=NOW, apply_expiry=True)
                self.assertFalse(archive.exists(), "valid owned archive expiry must not depend on remote availability")
                self.assertEqual((root / "journal/deletions.json").read_bytes(), before)
                state = json.loads((root / "status.json").read_text())
                self.assertEqual(state["status"], "failed")
                self.assertEqual(state["last_success"], good["last_success"])
                self.assertEqual(state["expiry_status"], "ok")
                self.assertEqual(state["expiry"]["deleted"], 1)
                self.assertNotIn("private SSH error", json.dumps(state))
                self.assertNotIn("private NAS error", json.dumps(state))

    def test_exact_enrollment_does_not_reset_the_creation_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            archive = root / "cutover.dump.enc"
            archive.write_bytes(b"synthetic encrypted archive fixture")
            archive.chmod(0o600)
            original = dt.datetime(2026, 10, 22, tzinfo=dt.timezone.utc)
            os.utime(archive, (original.timestamp(), original.timestamp()))
            checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
            with mock.patch.object(studio, "ALLOWED_DIRECTORIES", frozenset({str(root)})):
                record = studio.enroll_artifact(root, archive.name, checksum, "2026-11-21T00:00:00Z", now=NOW)
                self.assertEqual(record["created_at"], "2026-10-22T00:00:00Z")
                self.assertTrue(archive.exists(), "enrollment prepares a manifest, never deletes")
                manifest = root / studio.MANIFEST
                self.assertEqual(stat.S_IMODE(manifest.stat().st_mode), 0o600)
                before = manifest.read_bytes()
                with self.assertRaises(ValueError):
                    studio.enroll_artifact(root, archive.name, checksum, "2026-11-22T00:00:00Z", now=NOW)
                self.assertEqual(manifest.read_bytes(), before)
                with self.assertRaises(ValueError):
                    studio.enroll_artifact(root, archive.name, checksum, "2026-11-21T00:00:00Z", created_at="2026-10-27T00:00:00Z", now=NOW)
                self.assertEqual(manifest.read_bytes(), before)

    def test_unenrolled_directory_links_active_logs_and_bad_checksum_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            path = root / "server.log"
            path.write_bytes(b"private active content")
            path.chmod(0o600)
            with self.assertRaises(ValueError):
                studio.enroll_artifact(root, path.name, "0" * 64, "2026-11-01T00:00:00Z", now=NOW)
            with mock.patch.object(studio, "ALLOWED_DIRECTORIES", frozenset({str(root)})):
                with self.assertRaises(ValueError):
                    studio.enroll_artifact(root, path.name, hashlib.sha256(path.read_bytes()).hexdigest(), "2026-11-01T00:00:00Z", kind="log", now=NOW)
                path = root / "old.dump.enc"
                path.symlink_to(root / "server.log")
                with self.assertRaises(ValueError):
                    studio.enroll_artifact(root, path.name, "0" * 64, "2026-11-01T00:00:00Z", now=NOW)
            self.assertTrue((root / "server.log").exists())

    def test_scheduled_expiry_only_removes_exact_enrolled_expired_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            custody = root / "custody"
            custody.mkdir(mode=0o700)
            old = custody / "old.dump.enc"
            keep = custody / "unlisted.dump.enc"
            old.write_bytes(b"expired synthetic archive")
            keep.write_bytes(b"unlisted synthetic archive")
            for path in [old, keep]:
                path.chmod(0o600)
            created = dt.datetime(2026, 9, 20, tzinfo=dt.timezone.utc)
            os.utime(old, (created.timestamp(), created.timestamp()))
            config = {"version": 1, "instance_id": INSTANCE,
                      "managed_directories": [{"directory": str(custody), "manifest": "backup-expiry.json"}]}
            with mock.patch.object(studio, "ALLOWED_DIRECTORIES", frozenset({str(custody)})):
                studio.enroll_artifact(custody, old.name, hashlib.sha256(old.read_bytes()).hexdigest(), "2026-10-20T00:00:00Z", now=NOW)
                state = studio.sync_once(config, root, transport=lambda: envelope([receipt()]), now=NOW, apply_expiry=True)
            self.assertFalse(old.exists())
            self.assertTrue(keep.exists())
            self.assertEqual(state["expiry"]["deleted"], 1)

    def test_closed_log_enrollment_uses_original_mtime_and_seven_day_maximum(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            log = root / "closed-test.archived.log"
            log.write_bytes(b"synthetic closed historical log")
            log.chmod(0o600)
            original = dt.datetime(2026, 10, 18, tzinfo=dt.timezone.utc)
            os.utime(log, (original.timestamp(), original.timestamp()))
            checksum = hashlib.sha256(log.read_bytes()).hexdigest()
            with mock.patch.object(studio, "ALLOWED_DIRECTORIES", frozenset({str(root)})):
                record = studio.enroll_artifact(root, log.name, checksum, "2026-10-25T00:00:00Z", kind="log", now=NOW)
                self.assertEqual(record["created_at"], "2026-10-18T00:00:00Z")
                before = (root / studio.MANIFEST).read_bytes()
                with self.assertRaises(ValueError):
                    studio.enroll_artifact(root, log.name, checksum, "2026-10-26T00:00:00Z", kind="log", now=NOW)
                self.assertEqual((root / studio.MANIFEST).read_bytes(), before)

    def test_all_manifests_validate_before_any_root_expires(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            first, second = root / "first", root / "second"
            first.mkdir(mode=0o700)
            second.mkdir(mode=0o700)
            archive = first / "old.dump.enc"
            archive.write_bytes(b"synthetic old backup")
            archive.chmod(0o600)
            original = dt.datetime(2026, 9, 20, tzinfo=dt.timezone.utc)
            os.utime(archive, (original.timestamp(), original.timestamp()))
            config = {"version": 1, "instance_id": INSTANCE, "managed_directories": [str(first), str(second)]}
            with mock.patch.object(studio, "ALLOWED_DIRECTORIES", frozenset({str(first), str(second)})):
                studio.enroll_artifact(first, archive.name, hashlib.sha256(archive.read_bytes()).hexdigest(), "2026-10-20T00:00:00Z", now=NOW)
                (second / studio.MANIFEST).write_text('{"not":"a manifest"}')
                (second / studio.MANIFEST).chmod(0o600)
                with self.assertRaises(ValueError):
                    studio.sync_once(config, root, transport=lambda: envelope(), now=NOW, apply_expiry=True)
                self.assertTrue(archive.exists())


def retirement():
    return {"version": 1, "owner": "scrum-pro-frozen-production", "cutover_at": "2026-10-21T23:58:00Z",
            "expires_at": "2026-11-20T23:58:00Z",
            "volume": {"name": "parley-local_parley-data", "created_at": "2026-10-21T21:00:00Z", "compose_project": "parley-local"},
            "containers": [{"id": "a" * 64, "name": "parley-local-db-1"}]}


class FakeDocker:
    def __init__(self):
        self.ids = ["a" * 64]
        self.users = list(self.ids)
        self.volumes = ["parley-local_parley-data"]
        self.container = {"Id": "a" * 64, "Name": "/parley-local-db-1", "Created": "2026-10-21T21:00:00Z",
                          "Config": {"Labels": {"com.docker.compose.project": "parley-local"}},
                          "State": {"Running": False, "Status": "exited"}}
        self.volume = {"Name": "parley-local_parley-data", "CreatedAt": "2026-10-21T21:00:00Z",
                       "Labels": {"com.docker.compose.project": "parley-local"}}
        self.removed = []

    def container_ids(self): return self.ids
    def volume_names(self): return self.volumes
    def inspect_container(self, identifier): return self.container
    def inspect_volume(self, name): return self.volume
    def volume_users(self, name): return self.users
    def remove_containers(self, identifiers):
        self.removed.extend(identifiers)
        self.ids = []
        self.users = []
    def remove_volume(self, name):
        self.removed.append(name)
        self.volumes = []


class RetirementTests(unittest.TestCase):
    def test_docker_created_at_offset_is_compared_in_utc_but_identity_stays_exact(self):
        record = retirement()
        record["volume"]["created_at"] = "2026-10-22T00:36:24+02:00"
        docker = FakeDocker()
        docker.volume["CreatedAt"] = record["volume"]["created_at"]
        docker.container["Created"] = "2026-10-22T00:36:24+02:00"
        late = NOW + dt.timedelta(days=40)
        self.assertEqual(studio.retire_frozen_runtime(record, docker=docker, now=late), "would_retire")
        docker.volume["CreatedAt"] = "2026-10-21T22:36:24Z"
        with self.assertRaises(ValueError):
            studio.retire_frozen_runtime(record, docker=docker, now=late)
        self.assertEqual(docker.removed, [])

    def test_offline_host_does_not_prevent_due_frozen_volume_retirement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            docker = FakeDocker()
            config = {"version": 1, "instance_id": INSTANCE, "managed_directories": [],
                      "docker_retirements": [retirement()]}
            good = studio.sync_once(config, root, transport=lambda: envelope([receipt()]), docker=docker, now=NOW)
            before = (root / "journal/deletions.json").read_bytes()
            with self.assertRaises(studio.SyncError):
                studio.sync_once(config, root, transport=mock.Mock(side_effect=ValueError("offline")),
                                 docker=docker, now=NOW + dt.timedelta(days=40), apply_expiry=True)
            self.assertEqual(docker.removed, ["a" * 64, "parley-local_parley-data"])
            self.assertEqual((root / "journal/deletions.json").read_bytes(), before)
            state = json.loads((root / "status.json").read_text())
            self.assertEqual(state["status"], "failed")
            self.assertEqual(state["last_success"], good["last_success"])
            self.assertEqual(state["expiry_status"], "ok")
            self.assertEqual(state["frozen_runtimes"], ["retired"])

    def test_invalid_config_does_not_authorize_independent_retirement(self):
        with tempfile.TemporaryDirectory() as tmp:
            docker = FakeDocker()
            transport = mock.Mock(side_effect=ValueError("offline"))
            config = {"version": 2, "instance_id": INSTANCE, "managed_directories": [],
                      "docker_retirements": [retirement()]}
            with self.assertRaises(studio.SyncError):
                studio.sync_once(config, Path(tmp).resolve(), transport=transport, docker=docker,
                                 now=NOW + dt.timedelta(days=40), apply_expiry=True)
            transport.assert_not_called()
            self.assertEqual(docker.removed, [])

    def test_retirement_cannot_extend_the_thirty_day_policy(self):
        record = retirement()
        record["expires_at"] = "2099-01-01T00:00:00Z"
        with self.assertRaises(ValueError):
            studio.validate_retirement(record)

    def test_unexpired_skips_docker_entirely(self):
        docker = mock.Mock()
        self.assertEqual(studio.retire_frozen_runtime(retirement(), docker=docker, now=NOW, apply=True), "keep")
        self.assertEqual(docker.mock_calls, [])

    def test_running_unknown_volume_users_and_identity_mismatch_prevent_any_removal(self):
        late = NOW + dt.timedelta(days=40)
        for failure in ["running", "unknown", "created", "label", "name"]:
            with self.subTest(failure=failure):
                docker = FakeDocker()
                if failure == "running": docker.container["State"]["Running"] = True
                if failure == "unknown": docker.users.append("b" * 64)
                if failure == "created": docker.volume["CreatedAt"] = "2026-10-22T00:00:00Z"
                if failure == "label": docker.volume["Labels"] = {"com.docker.compose.project": "other-app"}
                if failure == "name": docker.container["Name"] = "/scrum-invitations-db-20261025"
                with self.assertRaises(ValueError):
                    studio.retire_frozen_runtime(retirement(), docker=docker, now=late, apply=True)
                self.assertEqual(docker.removed, [])

    def test_approved_retirement_removes_only_pinned_stopped_containers_then_volume(self):
        docker = FakeDocker()
        late = NOW + dt.timedelta(days=40)
        self.assertEqual(studio.retire_frozen_runtime(retirement(), docker=docker, now=late), "would_retire")
        self.assertEqual(docker.removed, [])
        self.assertEqual(studio.retire_frozen_runtime(retirement(), docker=docker, now=late, apply=True), "retired")
        self.assertEqual(docker.removed, ["a" * 64, "parley-local_parley-data"])
        self.assertEqual(studio.retire_frozen_runtime(retirement(), docker=docker, now=late, apply=True), "already_retired")

    def test_empty_container_enrollment_requires_no_volume_references(self):
        record = retirement()
        record["containers"] = []
        docker = FakeDocker()
        with self.assertRaises(ValueError):
            studio.retire_frozen_runtime(record, docker=docker, now=NOW + dt.timedelta(days=40), apply=True)
        self.assertEqual(docker.removed, [])
        docker.ids = []
        docker.users = []
        self.assertEqual(studio.retire_frozen_runtime(record, docker=docker, now=NOW + dt.timedelta(days=40), apply=True), "retired")
        self.assertEqual(docker.removed, ["parley-local_parley-data"])


class TransportAndScheduleTests(unittest.TestCase):
    def test_malformed_config_marks_failure_preserving_last_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            config = {"version": 1, "instance_id": INSTANCE, "managed_directories": []}
            good = studio.sync_once(config, root, transport=lambda: envelope([receipt()]), now=NOW)
            path = root / "config.json"
            path.write_text('{"private-value":"must-not-log",')
            path.chmod(0o600)
            errors = io.StringIO()
            with mock.patch.object(studio, "RUNTIME", root), mock.patch.object(sys, "stderr", errors):
                result = studio.main(["sync", "--config", str(path)])
            self.assertEqual(result, 1)
            self.assertNotIn("must-not-log", errors.getvalue())
            state = json.loads((root / "status.json").read_text())
            self.assertEqual(state["status"], "failed")
            self.assertEqual(state["last_success"], good["last_success"])

    def test_fake_ssh_receives_fixed_host_and_only_fixed_remote_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            args_path = root / "arguments.json"
            executable = root / "fake-ssh"
            source = envelope([receipt()])
            status_raw = json.dumps(source.pop("status")).encode()
            source["status_b64"] = base64.b64encode(status_raw).decode()
            executable.write_text("#!" + sys.executable + "\nimport os,json,sys\nopen(os.environ['ARGUMENTS'],'w').write(json.dumps(sys.argv[1:]))\nprint(os.environ['RESPONSE'])\n")
            executable.chmod(0o700)
            with mock.patch.object(studio, "SSH_EXECUTABLE", str(executable)), mock.patch.dict(os.environ, {"ARGUMENTS": str(args_path), "RESPONSE": json.dumps(source)}):
                result = studio.ssh_export()
            self.assertEqual(result["status"]["instance_id"], INSTANCE)
            arguments = json.loads(args_path.read_text())
            self.assertEqual(arguments[-2], "root@htz-4g-nbg")
            self.assertIn("BatchMode=yes", arguments)
            self.assertIn("StrictHostKeyChecking=yes", arguments)
            self.assertIn("/opt/apps/scrum-pro/privacy/journal/deletions.json", arguments[-1])
            self.assertIn("/opt/apps/scrum-pro/privacy/status.json", arguments[-1])
            self.assertNotIn("DATABASE_URL", arguments[-1])

    def test_ssh_failure_and_oversize_never_expose_raw_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "fake-ssh"
            executable.write_text("#!" + sys.executable + "\nimport sys\nprint('never-log-private-content')\nprint('never-log-private-stderr',file=sys.stderr)\nsys.exit(1)\n")
            executable.chmod(0o700)
            with mock.patch.object(studio, "SSH_EXECUTABLE", str(executable)):
                with self.assertRaises(studio.SyncError) as error:
                    studio.ssh_export()
            self.assertNotIn("private", str(error.exception))
            executable.write_text("#!" + sys.executable + "\nprint('x'*1024)\n")
            with mock.patch.object(studio, "SSH_EXECUTABLE", str(executable)):
                with self.assertRaises(studio.SyncError):
                    studio._ssh_bytes("root@htz-4g-nbg", "fixed-command", limit=20)

    def test_launchdaemon_runs_every_minute_as_matthew_without_unbounded_logs(self):
        path = SOURCE.parent / "launchd/com.matthew.scrum-pro-privacy.plist"
        data = plistlib.loads(path.read_bytes())
        self.assertEqual(data["UserName"], "matthew")
        self.assertEqual(data["StartInterval"], 60)
        self.assertTrue(data["RunAtLoad"])
        self.assertEqual(data["StandardOutPath"], "/dev/null")
        self.assertEqual(data["StandardErrorPath"], "/dev/null")
        self.assertIn("--apply-expiry", data["ProgramArguments"])


if __name__ == "__main__":
    unittest.main()
