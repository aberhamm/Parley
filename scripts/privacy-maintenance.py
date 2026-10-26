#!/usr/bin/env python3
"""Explicit operator tools for deletion recovery and managed archive expiry.

Uses Python's standard library and psql. It never schedules itself or touches
production unless the operator supplies that database or managed directory.
"""
import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import urllib.parse
import uuid

MAX_BYTES = 10 * 1024 * 1024
MAX_RECORDS = 100000
OWNER = "scrum-pro-privacy-maintenance"
KINDS = {"session", "space", "profile"}
UTC = dt.timezone.utc


def timestamp(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("timestamps must be bounded ISO 8601 UTC strings")
    try:
        result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("invalid UTC timestamp") from None
    if result.utcoffset() != dt.timedelta(0):
        raise ValueError("timestamps must include the UTC timezone")
    return result.astimezone(UTC)


def utc_string(value):
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def identifier(value):
    if not isinstance(value, str):
        raise ValueError("expected a UUID")
    try:
        result = str(uuid.UUID(value))
    except (ValueError, AttributeError):
        raise ValueError("invalid UUID") from None
    if result != value:
        raise ValueError("UUID must use canonical lowercase notation")
    return result


def exact_keys(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(label + " has missing or unknown fields")


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def decode_json(raw):
    if len(raw) > MAX_BYTES:
        raise ValueError("JSON input exceeds 10 MiB")
    return json.loads(raw, object_pairs_hook=_no_duplicates)


def private_directory(path):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("use an owned, nonsymlink private directory (mode 0700)")
    return path


def _check_file(info):
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise ValueError("use owned private regular files (mode 0600), without links")


def read_private_json(path):
    path = Path(path)
    private_directory(path.parent)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise ValueError("cannot read the private JSON file; links are refused") from None
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        _check_file(info)
        if info.st_size > MAX_BYTES:
            raise ValueError("JSON input exceeds 10 MiB")
        return decode_json(stream.read(MAX_BYTES + 1))


def validate_journal(data):
    exact_keys(data, {"version", "instance_id", "deletions"}, "journal")
    if type(data["version"]) is not int or data["version"] != 1:
        raise ValueError("unsupported journal version")
    identifier(data["instance_id"])
    if not isinstance(data["deletions"], list) or len(data["deletions"]) > MAX_RECORDS:
        raise ValueError("journal must contain at most 100000 receipts")
    seen = set()
    for record in data["deletions"]:
        exact_keys(record, {"kind", "object_id", "deleted_at"}, "deletion receipt")
        if not isinstance(record["kind"], str) or record["kind"] not in KINDS:
            raise ValueError("unsupported deletion kind")
        identifier(record["object_id"])
        timestamp(record["deleted_at"])
        key = (record["kind"], record["object_id"])
        if key in seen:
            raise ValueError("duplicate deletion receipt")
        seen.add(key)
    return data


def read_journal(path):
    return validate_journal(read_private_json(path))


@contextlib.contextmanager
def directory_lock(directory, name):
    fd = os.open(directory / name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        _check_file(os.fstat(fd))
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def write_journal(path, fresh):
    """Atomic cumulative export: an old restore cannot truncate known deletions."""
    fresh = validate_journal(fresh)
    path = Path(path)
    private_directory(path.parent)
    with directory_lock(path.parent, ".privacy-journal.lock"):
        records = {}
        if path.exists() or path.is_symlink():
            previous = read_journal(path)
            if previous["instance_id"] != fresh["instance_id"]:
                raise ValueError("journal belongs to another instance")
            records.update({(r["kind"], r["object_id"]): r for r in previous["deletions"]})
        for record in fresh["deletions"]:
            key = (record["kind"], record["object_id"])
            if key not in records or timestamp(record["deleted_at"]) < timestamp(records[key]["deleted_at"]):
                records[key] = record
        result = dict(fresh, deletions=[records[k] for k in sorted(records)])
        validate_journal(result)
        raw = (json.dumps(result, indent=2) + "\n").encode()
        if len(raw) > MAX_BYTES:
            raise ValueError("merged journal exceeds 10 MiB; preserve and partition under operator review")
        fd, temp = tempfile.mkstemp(prefix=".privacy-journal-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            os.replace(temp, path)
            parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
    return len(result["deletions"])


def connection_environment(dsn):
    """libpq does not expand a URI supplied through PGDATABASE itself."""
    try:
        parsed = urllib.parse.urlsplit(dsn)
        if parsed.scheme not in {"postgres", "postgresql"} or parsed.fragment:
            raise ValueError
        fields = {"dbname": urllib.parse.unquote(parsed.path[1:])}
        if not fields["dbname"]:
            raise ValueError
        if parsed.username is not None: fields["user"] = urllib.parse.unquote(parsed.username)
        if parsed.password is not None: fields["password"] = urllib.parse.unquote(parsed.password)
        if parsed.hostname is not None: fields["host"] = urllib.parse.unquote(parsed.hostname)
        if parsed.port is not None: fields["port"] = str(parsed.port)
        seen = set()
        for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True):
            if key in seen:
                raise ValueError
            seen.add(key); fields[key] = value
    except (ValueError, TypeError):
        raise ValueError("DATABASE_URL must be a valid PostgreSQL URI with a database name") from None
    names = {"dbname": "PGDATABASE", "user": "PGUSER", "password": "PGPASSWORD", "host": "PGHOST",
             "hostaddr": "PGHOSTADDR", "port": "PGPORT", "sslmode": "PGSSLMODE",
             "sslrootcert": "PGSSLROOTCERT", "sslcert": "PGSSLCERT", "sslkey": "PGSSLKEY",
             "sslpassword": "PGSSLPASSWORD", "sslcrl": "PGSSLCRL", "sslcrldir": "PGSSLCRLDIR",
             "ssl_min_protocol_version": "PGSSLMINPROTOCOLVERSION", "ssl_max_protocol_version": "PGSSLMAXPROTOCOLVERSION",
             "application_name": "PGAPPNAME", "options": "PGOPTIONS", "target_session_attrs": "PGTARGETSESSIONATTRS",
             "channel_binding": "PGCHANNELBINDING", "gssencmode": "PGGSSENCMODE", "passfile": "PGPASSFILE",
             "requirepeer": "PGREQUIREPEER", "krbsrvname": "PGKRBSRVNAME", "sslsni": "PGSSLSNI"}
    if "connect_timeout" in fields:
        try:
            if not 1 <= int(fields.pop("connect_timeout")) <= 30: raise ValueError
        except ValueError:
            raise ValueError("DATABASE_URL connect_timeout must be 1 to 30 seconds") from None
    env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    for key, value in fields.items():
        if key not in names or "\x00" in value:
            raise ValueError("DATABASE_URL contains an unsupported connection option")
        env[names[key]] = value
    env["PGCONNECT_TIMEOUT"] = "10"
    return env


class SQLClient:
    def query(self, statement):
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            raise ValueError("DATABASE_URL must name the intended database")
        env = connection_environment(dsn)
        # libpq fields stay in the environment, never DSN/password argv/logs.
        result = subprocess.run(["psql", "-X", "-q", "-A", "-t", "--no-password", "-v", "ON_ERROR_STOP=1"],
                                input=statement, text=True, capture_output=True, env=env, timeout=120)
        if result.returncode:
            raise ValueError("database operation failed; keep writers stopped and review schema, ownership handoff and connection privately")
        output = result.stdout.strip()
        if output.startswith("{"):
            return decode_json(output.encode())
        return None


def export_journal(path, client):
    data = client.query("""select json_build_object('version',1,'instance_id',
      (select instance_id from privacy_meta),'deletions',coalesce(
      (select json_agg(json_build_object('kind',kind,'object_id',object_id,
       'deleted_at',to_char(deleted_at at time zone 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'))
       order by kind,object_id) from privacy_deletions),'[]'::json));""")
    return write_journal(path, data)


def replay_journal(data, client, *, writers_stopped=False):
    data = validate_journal(data)
    if not writers_stopped:
        raise ValueError("replay requires --writers-stopped after stopping every app replica")
    current = client.query("select json_build_object('instance_id',(select instance_id from privacy_meta));")
    if not isinstance(current, dict) or current.get("instance_id") != data["instance_id"]:
        raise ValueError("journal and database instance IDs differ; no deletions replayed")
    instance = data["instance_id"]
    statements = ["begin;", "set local lock_timeout='10s';", "set local statement_timeout='90s';",
                  "lock table privacy_meta in share mode;",
                  "do $$ begin if (select count(*) from privacy_meta) <> 1 or not exists "
                  f"(select 1 from privacy_meta where instance_id='{instance}'::uuid) then "
                  "raise exception 'privacy instance mismatch'; end if; end $$;"]
    # Workspace deletions first can remove obsolete last-owner blockers before profile erasure.
    rank = {"space": 0, "session": 1, "profile": 2}
    for record in sorted(data["deletions"], key=lambda r: (rank[r["kind"]], r["object_id"])):
        kind, obj = record["kind"], record["object_id"]
        when = utc_string(timestamp(record["deleted_at"]))
        statements += [f"select privacy_erase_{kind}('{obj}'::uuid);",
                       "insert into privacy_deletions(kind,object_id,deleted_at) "
                       f"values('{kind}','{obj}'::uuid,'{when}'::timestamptz) "
                       "on conflict(kind,object_id) do update set deleted_at="
                       "least(privacy_deletions.deleted_at,excluded.deleted_at);"]
    statements.append("commit;")
    client.query("\n".join(statements))
    return len(data["deletions"])


def _artifact_name(record):
    name, kind = record["path"], record["kind"]
    if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,190}", name)
            or ".." in name or not isinstance(kind, str) or kind not in {"backup", "rollback", "log"}):
        raise ValueError("artifact names must be safe basenames of a supported kind")
    if name in {"privacy-expiry-audit.jsonl", "privacy-journal.jsonl"}:
        raise ValueError("privacy recovery/audit records cannot expire as content logs")
    encrypted = re.search(r"\.(?:dump|sql|tar\.gz)\.(?:enc|age|gpg)$", name)
    rotated_log = re.search(r"(?:-json\.log\.\d+|\.jsonl)$", name)
    if not (encrypted if kind in {"backup", "rollback"} else rotated_log):
        raise ValueError("only encrypted backup/rollback archives or archived JSON logs may expire; keys and active logs are refused")
    return name


def validate_manifest(manifest):
    exact_keys(manifest, {"version", "owner", "artifacts"}, "artifact manifest")
    if type(manifest["version"]) is not int or manifest["version"] != 1 or manifest["owner"] != OWNER:
        raise ValueError("artifact manifest must explicitly belong to scrum-pro-privacy-maintenance version1")
    if not isinstance(manifest["artifacts"], list) or len(manifest["artifacts"]) > MAX_RECORDS:
        raise ValueError("artifact manifest is too large")
    names = set()
    for record in manifest["artifacts"]:
        exact_keys(record, {"path", "kind", "created_at", "expires_at", "sha256"}, "artifact")
        name = _artifact_name(record)
        if name in names:
            raise ValueError("duplicate artifact path")
        names.add(name)
        if timestamp(record["created_at"]) >= timestamp(record["expires_at"]):
            raise ValueError("artifact expiry must follow creation")
        if not isinstance(record["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", record["sha256"]):
            raise ValueError("each artifact needs a lowercase SHA-256 checksum")
    return manifest


def expire_artifacts(directory, manifest, *, apply=False, now=None):
    manifest = validate_manifest(manifest)
    root = private_directory(Path(directory))
    now = now or dt.datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("expiry clock must include timezone")
    results = []
    with directory_lock(root, ".privacy-expiry.lock"):
        directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            candidates = []
            # Check every listed file before deleting any. A bad entry aborts the run.
            for record in manifest["artifacts"]:
                name = record["path"]
                try:
                    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
                except FileNotFoundError:
                    candidates.append((record, None)); continue
                except OSError:
                    raise ValueError("artifact cannot be opened safely; no deletion attempted") from None
                with os.fdopen(fd, "rb") as stream:
                    info = os.fstat(stream.fileno()); _check_file(info)
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                    if digest != record["sha256"]:
                        raise ValueError("artifact checksum changed; review manifest before expiry")
                    candidates.append((record, info))
            for record, original in candidates:
                status = "missing" if original is None else "keep"
                if original is not None and timestamp(record["expires_at"]) <= now:
                    status = "would_delete"
                    if apply:
                        current = os.stat(record["path"], dir_fd=directory_fd, follow_symlinks=False)
                        if (current.st_ino, current.st_dev, current.st_size, current.st_mtime_ns) != (
                                original.st_ino, original.st_dev, original.st_size, original.st_mtime_ns):
                            raise ValueError("artifact changed during expiry; stopped")
                        audit = {"kind": record["kind"], "path": record["path"], "sha256": record["sha256"],
                                 "at": utc_string(now), "status": "deletion_planned"}
                        _audit(directory_fd, audit)
                        os.unlink(record["path"], dir_fd=directory_fd)
                        os.fsync(directory_fd)
                        status = "deleted"
                        _audit(directory_fd, dict(audit, status=status))
                results.append({"path": record["path"], "kind": record["kind"], "status": status})
        finally:
            os.close(directory_fd)
    return results


def _audit(directory_fd, record):
    fd = os.open("privacy-expiry-audit.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
    with os.fdopen(fd, "a") as stream:
        _check_file(os.fstat(stream.fileno()))
        stream.write(json.dumps(record, sort_keys=True) + "\n"); stream.flush(); os.fsync(stream.fileno())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="merge deletion receipts into a protected off-backup journal")
    export.add_argument("--journal", type=Path, required=True)
    replay = commands.add_parser("replay", help="reapply deletion decisions while every app replica is stopped")
    replay.add_argument("--journal", type=Path, required=True)
    replay.add_argument("--writers-stopped", action="store_true")
    expire = commands.add_parser("expire", help="dry-run exact managed archive expiry; --apply enables deletion")
    expire.add_argument("--directory", type=Path, required=True)
    expire.add_argument("--manifest", type=Path, required=True)
    expire.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            print(json.dumps({"exported_receipts": export_journal(args.journal, SQLClient())}))
        elif args.command == "replay":
            print(json.dumps({"replayed_receipts": replay_journal(read_journal(args.journal), SQLClient(), writers_stopped=args.writers_stopped)}))
        else:
            print(json.dumps({"apply": args.apply, "artifacts": expire_artifacts(args.directory, read_private_json(args.manifest), apply=args.apply)}, indent=2))
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        # File paths and DB stderr can contain sensitive connection/user data.
        message = str(exc) if isinstance(exc, ValueError) else "operation failed; inspect protected inputs and database connection privately"
        print("Privacy maintenance refused: " + message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
