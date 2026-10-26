#!/usr/bin/env python3
"""Scrum-only journal custody and 30-day NAS database-dump expiry.

Python 3.8 compatible for Synology DSM. No database credentials, package
installation or shared backup configuration is required. Expiry is a dry run
unless --apply is supplied, and never removes other applications' artifacts.
"""
import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

MAX_BYTES = 10 * 1024 * 1024
MAX_SNAPSHOTS = 10000
DUMP_NAME = "scrum-pro-parley.dump"
BACKUP_ROOT = Path("/volume1/backups/htz-4g-nbg")
CUSTODY = Path("/volume1/backups/scrum-pro-privacy")
UTC = dt.timezone.utc
RETENTION = dt.timedelta(days=30)


def private_directory(path, create=False):
    path = Path(path)
    if create:
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
    info = path.lstat()
    # DSM's ACL-backed backup roots have Unix mode 000. Root ownership and
    # absence of group/other bits are the boundary, not an exact 0700 match.
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & 0o077):
        raise ValueError("use an owned private nonsymlink directory")
    return path


def check_file(info):
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_nlink != 1 or info.st_mode & 0o077):
        raise ValueError("backup and custody files must be owned private regular files without links")


@contextlib.contextmanager
def lock(directory, name):
    fd = os.open(str(directory / name), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        check_file(os.fstat(fd))
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def load_maintenance(path):
    path = Path(path)
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_nlink != 1 or info.st_mode & 0o022):
        raise ValueError("the copied maintenance module must be owned and not writable by others")
    spec = importlib.util.spec_from_file_location("scrum_privacy_maintenance_nas", str(path))
    if spec is None or spec.loader is None:
        raise ValueError("cannot load the copied privacy maintenance module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest_file(stream):
    # hashlib.file_digest is unavailable in DSM's Python 3.8.
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(64 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def receive_journal(raw, custody, maintenance):
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError("journal input must be bounded to 10 MiB")
    data = maintenance.validate_journal(maintenance.decode_json(raw))
    root = private_directory(custody, create=True)
    journal_dir = private_directory(root / "journal", create=True)
    target = journal_dir / "deletions.json"
    # The common writer locks, validates the existing instance and unions
    # receipts before an atomic/fsynced replacement. Old pulls cannot truncate
    # newer erasure decisions already held by NAS custody.
    maintenance.write_journal(target, data)
    stored = maintenance.read_journal(target)
    fd = os.open(str(target), os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        check_file(os.fstat(stream.fileno()))
        checksum = digest_file(stream)
    return {"version": 1, "status": "ok", "instance_id": stored["instance_id"],
            "journal_sha256": checksum, "receipt_count": len(stored["deletions"])}


def snapshot_name(name):
    if re.fullmatch(r"[0-9]{8}_[0-9]{6}", name) is None:
        return False
    try:
        dt.datetime.strptime(name, "%Y%m%d_%H%M%S")
    except ValueError:
        return False
    return True


def audit(directory_fd, record):
    fd = os.open("expiry-audit.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW,
                 0o600, dir_fd=directory_fd)
    with os.fdopen(fd, "a") as stream:
        check_file(os.fstat(stream.fileno()))
        stream.write(json.dumps(record, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def identity(info):
    return (info.st_ino, info.st_dev, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def write_expiry_status(custody, data):
    root = private_directory(custody)
    target = root / "expiry-status.json"
    if target.exists() or target.is_symlink():
        check_file(target.lstat())
    raw = (json.dumps(data, sort_keys=True, indent=2) + "\n").encode()
    if len(raw) > 4096:
        raise ValueError("expiry status exceeds its metadata bound")
    fd, temporary = tempfile.mkstemp(prefix=".expiry-status-", dir=str(root))
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, str(target))
        directory_fd = os.open(str(root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run_expiry_command(backup_root, custody, apply=False, now=None):
    """Persist a fresh result even when no file is old enough to delete."""
    root = private_directory(custody, create=True)
    # Cron and the Studio mirror may invoke expiry concurrently. Serialize the
    # result publication too, so an older invocation cannot overwrite a newer
    # success/failure after releasing the archive-operation lock.
    with lock(root, ".nas-expiry-command.lock"):
        return _run_expiry_command_locked(backup_root, root, apply=apply, now=now)


def _run_expiry_command_locked(backup_root, root, apply=False, now=None):
    status_path = root / "expiry-status.json"
    if status_path.exists() or status_path.is_symlink():
        check_file(status_path.lstat())
    now = now or dt.datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("expiry clock must include its timezone")
    checked_at = now.astimezone(UTC).isoformat()
    try:
        result = expire_backups(backup_root, root, apply=apply, now=now)
        result["checked_at"] = checked_at
        write_expiry_status(root, result)
        return result
    except Exception:
        # Fixed fields only: a cron failure must be visible without persisting
        # filenames, dump bytes, raw input or exception/connection strings.
        try:
            write_expiry_status(root, {"version": 1, "status": "failed", "apply": bool(apply),
                                       "checked_at": checked_at})
        except (OSError, ValueError):
            pass  # Unsafe/unwritable custody is refused, never bypassed.
        raise


def expire_backups(backup_root, custody, apply=False, now=None):
    root = private_directory(backup_root)
    custody = private_directory(custody, create=True)
    now = now or dt.datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("expiry clock must include its timezone")
    cutoff = (now.astimezone(UTC) - RETENTION).timestamp()
    result = {"version": 1, "status": "ok", "apply": bool(apply),
              "scanned": 0, "expired": 0, "deleted": 0, "skipped": 0}
    with lock(custody, ".nas-expiry.lock"):
        root_fd = os.open(str(root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        custody_fd = os.open(str(custody), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            names = sorted(os.listdir(root_fd))
            if len(names) > MAX_SNAPSHOTS:
                raise ValueError("snapshot inventory exceeds the reviewed bound")
            candidates = []
            # Validate the whole known snapshot inventory before any unlink.
            for name in names:
                if not snapshot_name(name):
                    result["skipped"] += 1
                    continue
                info = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
                if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                        or info.st_mode & 0o077):
                    raise ValueError("dated snapshot directory is not owned/private or is a link")
                try:
                    directory_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
                except OSError:
                    raise ValueError("dated snapshot directory cannot be opened safely") from None
                try:
                    if identity(os.fstat(directory_fd)) != identity(info):
                        raise ValueError("snapshot directory changed during validation")
                    try:
                        fd = os.open(DUMP_NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                     dir_fd=directory_fd)
                    except FileNotFoundError:
                        result["skipped"] += 1
                        continue
                    except OSError:
                        raise ValueError("Scrum backup cannot be opened safely") from None
                    with os.fdopen(fd, "rb") as stream:
                        original = os.fstat(stream.fileno())
                        check_file(original)
                        if stream.read(5) != b"PGDMP":
                            raise ValueError("Scrum backup has no custom-format PostgreSQL header")
                        stream.seek(0)
                        checksum = digest_file(stream)
                        if identity(os.fstat(stream.fileno())) != identity(original):
                            raise ValueError("Scrum backup changed during validation")
                    candidates.append((name, info, original, checksum))
                    result["scanned"] += 1
                finally:
                    os.close(directory_fd)

            for name, directory_info, original, checksum in candidates:
                if original.st_mtime > cutoff:
                    continue
                result["expired"] += 1
                if not apply:
                    continue
                current_dir = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
                # Directory mtime can legitimately change as another app's
                # backup artifact arrives; its device/inode/type must not.
                if (current_dir.st_ino, current_dir.st_dev, current_dir.st_mode) != (
                        directory_info.st_ino, directory_info.st_dev, directory_info.st_mode):
                    raise ValueError("snapshot directory changed before expiry")
                directory_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
                try:
                    current = os.stat(DUMP_NAME, dir_fd=directory_fd, follow_symlinks=False)
                    check_file(current)
                    if identity(current) != identity(original):
                        raise ValueError("Scrum backup changed before expiry")
                    record = {"snapshot": name, "artifact": DUMP_NAME, "sha256": checksum,
                              "captured_at": dt.datetime.fromtimestamp(original.st_mtime, UTC).isoformat(),
                              "at": now.astimezone(UTC).isoformat(), "status": "deletion_planned"}
                    audit(custody_fd, record)
                    os.unlink(DUMP_NAME, dir_fd=directory_fd)
                    os.fsync(directory_fd)
                    audit(custody_fd, dict(record, status="deleted"))
                    result["deleted"] += 1
                finally:
                    os.close(directory_fd)
        finally:
            os.close(custody_fd)
            os.close(root_fd)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    receive = commands.add_parser("receive", help="receive a bounded cumulative journal from stdin")
    receive.add_argument("--custody", type=Path, default=CUSTODY)
    receive.add_argument("--maintenance", type=Path, default=Path(__file__).with_name("privacy-maintenance.py"))
    expire = commands.add_parser("expire", help="preview exact Scrum-dump expiry after 30 days")
    expire.add_argument("--backup-root", type=Path, default=BACKUP_ROOT)
    expire.add_argument("--custody", type=Path, default=CUSTODY)
    expire.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "receive":
            result = receive_journal(sys.stdin.buffer.read(MAX_BYTES + 1), args.custody,
                                     load_maintenance(args.maintenance))
        else:
            result = run_expiry_command(args.backup_root, args.custody, apply=args.apply)
        print(json.dumps(result, sort_keys=True))
    except (ValueError, OSError, ImportError, RecursionError):
        # Never echo raw JSON, environment values, DB data or private paths.
        print("Scrum privacy operation refused; review protected custody, instance identity and archive metadata.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
