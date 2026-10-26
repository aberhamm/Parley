#!/usr/bin/env python3
"""Dedicated Scrum Pro journal export and enrolled archive expiry, not fleet cleanup."""
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

MODULE = Path(__file__).with_name("privacy-maintenance.py")
if not MODULE.exists():
    MODULE = Path(__file__).resolve().parents[2] / "scripts/privacy-maintenance.py"
spec = importlib.util.spec_from_file_location("privacy_maintenance", MODULE)
maintenance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(maintenance)
UTC = dt.timezone.utc
LOG_NAME = re.compile(r"scrum-pro-(\d{4}-\d{2}-\d{2})(?:\.([1-3]))?\.jsonl")
BACKUP_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,170}\.(?:dump|tar\.gz)\.enc")
DEFAULT_PATHS = {"state": Path("/opt/apps/scrum-pro/privacy"),
                 "logs": Path("/var/log/scrum-pro"),
                 "backups": Path("/opt/apps/scrum-pro/backups")}


class DockerSQL:
    """Use the database container's psql through a fixed local Docker invocation."""
    def query(self, statement):
        result = subprocess.run(["/usr/bin/docker", "exec", "-i", "scrum-pro-db-1", "psql",
                                 "-U", "parley", "-d", "parley", "-X", "-A", "-t", "-q",
                                 "--no-password", "-v", "ON_ERROR_STOP=1"],
                                input=statement.encode(), capture_output=True, timeout=45)
        if result.returncode:
            raise ValueError("dedicated database journal export failed")
        return maintenance.decode_json(result.stdout.strip())


def write_json(path, data):
    path = Path(path)
    maintenance.private_directory(path.parent)
    if path.exists() or path.is_symlink():
        maintenance._check_file(path.lstat())
    raw = (json.dumps(data, sort_keys=True, indent=2) + "\n").encode()
    if len(raw) > maintenance.MAX_BYTES:
        raise ValueError("host privacy metadata exceeds its bound")
    fd, temporary = tempfile.mkstemp(prefix=".privacy-host-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(parent)
        finally: os.close(parent)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def file_checksum(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno()); maintenance._check_file(before)
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise ValueError("archive changed while enrolling")
        return digest


def log_manifest(directory, now):
    directory = maintenance.private_directory(directory)
    records = []
    for path in sorted(directory.iterdir()):
        matched = LOG_NAME.fullmatch(path.name)
        if not matched: continue
        day = dt.date.fromisoformat(matched.group(1))
        maintenance._check_file(path.lstat())
        if day > now.astimezone(UTC).date():
            raise ValueError("future-dated dedicated log archive requires review")
        # The current UTC file and its size rotations remain active; never hash
        # or unlink them while the logger/logrotate may still be writing.
        if day == now.astimezone(UTC).date(): continue
        created = dt.datetime.combine(day, dt.time(), UTC)
        records.append({"path": path.name, "kind": "log", "created_at": maintenance.utc_string(created),
                        "expires_at": maintenance.utc_string(created + dt.timedelta(days=7)),
                        "sha256": file_checksum(path)})
    return {"version": 1, "owner": maintenance.OWNER, "artifacts": records}


def validate_backup_manifest(data, now):
    maintenance.validate_manifest(data)
    for record in data["artifacts"]:
        if record["kind"] not in {"backup", "rollback"} or not BACKUP_NAME.fullmatch(record["path"]):
            raise ValueError("only explicitly inventoried Scrum encrypted dump/config backups may expire")
        created = maintenance.timestamp(record["created_at"])
        expires = maintenance.timestamp(record["expires_at"])
        if created > now or expires - created != dt.timedelta(days=30):
            raise ValueError("backup inventory must declare creation plus exactly 30 days")
    return data


def rotate_logs(state):
    config = state / "logrotate-scrum-pro.conf"
    maintenance._check_file(config.lstat())
    status = state / "logrotate.status"
    try:
        fd = os.open(status, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        maintenance._check_file(status.lstat())
    else:
        with os.fdopen(fd, "w") as stream:
            stream.write("logrotate state -- version 2\n"); stream.flush(); os.fsync(stream.fileno())
    result = subprocess.run(["/usr/sbin/logrotate", "--state", str(status), str(config)],
                            capture_output=True, timeout=30)
    if result.returncode:
        raise ValueError("dedicated Scrum log rotation failed")
    fd = os.open(status, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise ValueError("logrotate private state changed unexpectedly")
        os.fchmod(fd, 0o600)
    finally: os.close(fd)


def expiry_counts(groups):
    records = [record for group in groups for record in group]
    return {"deleted": sum(r["status"] == "deleted" for r in records),
            "kept": sum(r["status"] in {"keep", "would_delete"} for r in records),
            "missing": sum(r["status"] == "missing" for r in records),
            "backup_retention_days": 30, "log_retention_days": 7}


def run_maintenance(paths, client, *, apply=False, now=None, rotate=rotate_logs):
    now = now or dt.datetime.now(UTC)
    state = maintenance.private_directory(paths["state"])
    try:
        with maintenance.directory_lock(state, ".privacy-host.lock"):
            maintenance.private_directory(paths["logs"])
            maintenance.private_directory(paths["backups"])
            journal = state / "journal/deletions.json"
            maintenance.private_directory(journal.parent)
            maintenance.export_journal(journal, client)
            data = maintenance.read_journal(journal)
            exported_at = maintenance.utc_string(now)
            if apply: rotate(state)
            logs = log_manifest(paths["logs"], now)
            backups = validate_backup_manifest(maintenance.read_private_json(state / "backup-manifest.json"), now)
            write_json(state / "log-manifest.json", logs)
            # Both sets must pass full dry-run validation before either set can
            # be deleted. Apply still repeats checksum/race checks per file.
            log_results = maintenance.expire_artifacts(paths["logs"], logs, apply=False, now=now)
            backup_results = maintenance.expire_artifacts(paths["backups"], backups, apply=False, now=now)
            if apply:
                log_results = maintenance.expire_artifacts(paths["logs"], logs, apply=True, now=now)
                backup_results = maintenance.expire_artifacts(paths["backups"], backups, apply=True, now=now)
            status = {"version": 1, "instance_id": data["instance_id"], "exported_at": exported_at,
                      "journal_sha256": hashlib.sha256(journal.read_bytes()).hexdigest(),
                      "receipt_count": len(data["deletions"]), "status": "ok" if apply else "dry_run",
                      "expiry": expiry_counts([log_results, backup_results])}
            write_json(state / "status.json", status)
            return status
    except Exception:
        # Never put database errors, record IDs or log/backup contents in status.
        write_json(state / "status.json", {"version": 1, "status": "failed", "failed_at": maintenance.utc_string(now)})
        raise


def run_fixture(root, *, apply=False, now=None):
    """Only an explicitly supplied empty private directory gets synthetic data."""
    now = now or dt.datetime.now(UTC)
    root = maintenance.private_directory(root)
    if any(root.iterdir()): raise ValueError("fixture directory must be empty")
    paths = {name: root / name for name in ["logs", "backups"]}
    for path in paths.values(): path.mkdir(mode=0o700)
    for age in [10, 1]:
        day = (now - dt.timedelta(days=age)).date().isoformat()
        path = paths["logs"] / ("scrum-pro-" + day + ".jsonl")
        path.write_bytes(b'{"fixture":"synthetic, no user data"}\n'); path.chmod(0o600)
    backups = {"version":1,"owner":maintenance.OWNER,"artifacts":[]}
    for label, age in [("old", 40), ("new", 1)]:
        path = paths["backups"] / (label + ".dump.enc")
        path.write_bytes(b"synthetic expiry fixture, not a production backup"); path.chmod(0o600)
        created = now - dt.timedelta(days=age)
        backups["artifacts"].append({"path":path.name,"kind":"backup","created_at":maintenance.utc_string(created),
                                     "expires_at":maintenance.utc_string(created+dt.timedelta(days=30)),"sha256":file_checksum(path)})
    logs = log_manifest(paths["logs"], now)
    validate_backup_manifest(backups, now)
    for name, data in [("logs", logs), ("backups", backups)]:
        maintenance.expire_artifacts(paths[name], data, apply=False, now=now)
    results = [maintenance.expire_artifacts(paths[name], data, apply=apply, now=now)
               for name, data in [("logs", logs), ("backups", backups)]]
    return {"fixture":True,"apply":apply,"expiry":expiry_counts(results)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="export cumulative journal, rotate private logs and expire enrolled archives")
    run.add_argument("--apply", action="store_true")
    fixture = commands.add_parser("fixture", help="create and expire synthetic files in an empty private directory")
    fixture.add_argument("--directory", type=Path, required=True)
    fixture.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_fixture(args.directory, apply=args.apply) if args.command == "fixture" else run_maintenance(DEFAULT_PATHS, DockerSQL(), apply=args.apply)
        print(json.dumps(result, sort_keys=True))
    except Exception:
        print(json.dumps({"version":1,"status":"failed","at":maintenance.utc_string(dt.datetime.now(UTC))}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__": sys.exit(main())
