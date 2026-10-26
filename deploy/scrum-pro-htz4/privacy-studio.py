#!/usr/bin/env python3
"""Off-host deletion custody and explicitly enrolled Studio archive expiry.

The daemon runs as matthew, not root. SSH reads exactly two root-owned remote
files. Archive deletion is restricted to checksum-pinned manifests in the
listed application custody directories; the deletion journal never expires.
"""
import argparse
import base64
import binascii
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import selectors
import shlex
import stat
import subprocess
import sys
import tempfile
import time

RUNTIME = Path("/Users/matthew/.local/share/scrum-pro-privacy")
ALLOWED_DIRECTORIES = frozenset({
    "/Users/matthew/.local/share/scrum-pro-migration-20261022",
    "/Users/matthew/.local/share/scrum-home-release-20261025",
    "/Users/matthew/.local/share/scrum-invitations-20261025/production-readiness",
    "/Users/matthew/.local/share/scrum-invitations-deploy-20261026",
    "/Users/matthew/.local/share/scrum-privacy-production-20261027",
})
MANIFEST = "backup-expiry.json"
SSH_EXECUTABLE = "/usr/bin/ssh"
REMOTE_LIMIT = 15 * 1024 * 1024
UTC = dt.timezone.utc


def _maintenance():
    here = Path(__file__).resolve()
    candidates = [here.with_name("privacy-maintenance.py"), here.parents[2] / "scripts/privacy-maintenance.py"]
    for source in candidates:
        if source.is_file():
            spec = importlib.util.spec_from_file_location("scrum_privacy_maintenance", source)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    raise RuntimeError("privacy maintenance helper is not installed")


privacy = _maintenance()


class SyncError(ValueError):
    """Only fixed codes may reach the daemon's status or stderr."""


def _no_link_components(path):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise SyncError("unsafe_path")
    for item in [*reversed(path.parents), path]:
        if item.exists() or item.is_symlink():
            if item.is_symlink():
                raise SyncError("unsafe_path")
    return path


def _private_directory(path, *, create=False):
    path = _no_link_components(path)
    try:
        if create and not path.exists():
            path.mkdir(mode=0o700)
        return privacy.private_directory(path)
    except (OSError, ValueError):
        raise SyncError("unsafe_private_directory") from None


def _private_bytes(path):
    path = Path(path)
    _private_directory(path.parent)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            privacy._check_file(os.fstat(stream.fileno()))
            raw = stream.read(privacy.MAX_BYTES + 1)
            if len(raw) > privacy.MAX_BYTES:
                raise SyncError("private_file_too_large")
            return raw
    except OSError:
        raise SyncError("unsafe_private_file") from None


def _atomic_json(path, data):
    path = Path(path)
    _private_directory(path.parent)
    if path.exists() or path.is_symlink():
        privacy.read_private_json(path)
    raw = (json.dumps(data, indent=2, sort_keys=True) + "\n").encode()
    if len(raw) > privacy.MAX_BYTES:
        raise SyncError("status_too_large")
    fd, temporary = tempfile.mkstemp(prefix=".privacy-studio-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


# This is fixed code, not a configurable shell command or arbitrary remote path.
REMOTE_READ = r'''
import base64,json,os,pathlib,stat
limit=10*1024*1024
def read(path):
 p=pathlib.Path(path)
 for parent in [*reversed(p.parent.parents),p.parent]:
  if parent.is_symlink(): raise ValueError('unsafe')
 d=p.parent.lstat()
 if not stat.S_ISDIR(d.st_mode) or d.st_uid!=0 or d.st_mode&0o077: raise ValueError('unsafe')
 fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd,'rb') as stream:
  s=os.fstat(stream.fileno())
  if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_uid!=0 or s.st_mode&0o077 or s.st_size>limit: raise ValueError('unsafe')
  raw=stream.read(limit+1)
  if len(raw)>limit: raise ValueError('oversize')
  return raw
journal=read('/opt/apps/scrum-pro/privacy/journal/deletions.json')
status=read('/opt/apps/scrum-pro/privacy/status.json')
print(json.dumps({'status_b64':base64.b64encode(status).decode(),'journal_b64':base64.b64encode(journal).decode()}))
'''


def _ssh_bytes(target, command, payload=None, *, limit=REMOTE_LIMIT):
    argv = [SSH_EXECUTABLE, "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            "-o", "StrictHostKeyChecking=yes", target, command]
    incoming = tempfile.TemporaryFile() if payload is not None else None
    if incoming:
        incoming.write(payload)
        incoming.seek(0)
    try:
        process = subprocess.Popen(argv, stdin=incoming or subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL)
    except Exception:
        if incoming:
            incoming.close()
        raise SyncError("transport_failed") from None
    output = bytearray()
    deadline = time.monotonic() + 30
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise SyncError("transport_timeout")
                for key, _ in selector.select(min(remaining, 1)):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        output.extend(chunk)
                        if len(output) > limit:
                            raise SyncError("transport_oversize")
        if process.wait(timeout=max(0.1, deadline - time.monotonic())) != 0:
            raise SyncError("transport_failed")
        return bytes(output)
    except SyncError:
        raise
    except Exception:
        raise SyncError("transport_failed") from None
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()
        if incoming:
            incoming.close()


def ssh_export():
    try:
        output = _ssh_bytes("root@htz-4g-nbg", "python3 -c " + shlex.quote(REMOTE_READ))
        data = json.loads(output, object_pairs_hook=privacy._no_duplicates)
        privacy.exact_keys(data, {"status_b64", "journal_b64"}, "remote envelope")
        raw = base64.b64decode(data["status_b64"], validate=True)
        data["status"] = privacy.decode_json(raw)
        del data["status_b64"]
        return data
    except SyncError:
        raise
    except Exception:
        raise SyncError("transport_failed") from None


def mirror_journal(raw, settings):
    target = settings["target"]
    command = "/usr/bin/sudo -n /usr/bin/python3 /volume1/backups/scrum-pro-privacy/privacy-nas.py receive"
    result = privacy.decode_json(_ssh_bytes(target, command, raw, limit=16384))
    expected = privacy.validate_journal(privacy.decode_json(raw))
    privacy.exact_keys(result, {"version", "status", "instance_id", "journal_sha256", "receipt_count"}, "NAS receipt")
    if (type(result["version"]) is not int or result["version"] != 1 or result["status"] != "ok"
            or result["instance_id"] != expected["instance_id"]
            or result["journal_sha256"] != hashlib.sha256(raw).hexdigest()
            or type(result["receipt_count"]) is not int or result["receipt_count"] != len(expected["deletions"])):
        raise SyncError("nas_mirror_mismatch")
    if settings.get("apply_expiry", False):
        raw_expiry = _ssh_bytes(target, command.rsplit(" ", 1)[0] + " expire --apply", limit=16384)
        expiry = privacy.decode_json(raw_expiry)
        privacy.exact_keys(expiry, {"version", "status", "apply", "scanned", "expired", "deleted", "skipped", "checked_at"}, "NAS expiry")
        try:
            checked = privacy.timestamp(expiry["checked_at"])
        except ValueError:
            raise SyncError("nas_expiry_failed") from None
        now = dt.datetime.now(UTC)
        if (type(expiry["version"]) is not int or expiry["version"] != 1 or expiry["status"] != "ok"
                or expiry["apply"] is not True
                or now - checked > dt.timedelta(minutes=5) or checked - now > dt.timedelta(seconds=60)
                or any(type(expiry[k]) is not int or not 0 <= expiry[k] <= privacy.MAX_RECORDS
                       for k in ["scanned", "expired", "deleted", "skipped"])
                or expiry["deleted"] > expiry["expired"] or expiry["expired"] > expiry["scanned"]):
            raise SyncError("nas_expiry_failed")
    return result


def validate_config(config):
    required = {"version", "instance_id", "managed_directories"}
    if not isinstance(config, dict) or not required <= set(config) <= required | {"docker_retirements", "nas_mirror"}:
        raise SyncError("invalid_config")
    if type(config["version"]) is not int or config["version"] != 1:
        raise SyncError("invalid_config")
    privacy.identifier(config["instance_id"])
    if (not isinstance(config["managed_directories"], list)
            or len(config["managed_directories"]) > len(ALLOWED_DIRECTORIES)
            or len({json.dumps(item, sort_keys=True) for item in config["managed_directories"]}) != len(config["managed_directories"])):
        raise SyncError("invalid_config")
    seen = set()
    for item in config["managed_directories"]:
        root, _ = _managed_location(item)
        if str(root) in seen:
            raise SyncError("duplicate_managed_directory")
        seen.add(str(root))
    retirements = config.get("docker_retirements", [])
    if not isinstance(retirements, list) or len(retirements) > 1:
        raise SyncError("invalid_docker_retirements")
    for retirement in retirements:
        validate_retirement(retirement)
    mirror = config.get("nas_mirror")
    if mirror is not None:
        if (not isinstance(mirror, dict) or set(mirror) - {"target", "apply_expiry"}
                or not isinstance(mirror.get("target"), str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}@100\.84\.185\.146", mirror["target"])
                or type(mirror.get("apply_expiry", False)) is not bool):
            raise SyncError("invalid_nas_mirror")
    return config


def _allowed_directory(directory):
    if not isinstance(directory, str) or directory not in ALLOWED_DIRECTORIES:
        raise SyncError("directory_not_enrolled")
    return _private_directory(Path(directory))


def _validate_export(data, instance, now):
    privacy.exact_keys(data, {"status", "journal_b64"}, "remote envelope")
    status = data["status"]
    required = {"version", "instance_id", "exported_at", "journal_sha256", "receipt_count", "status"}
    if not isinstance(status, dict) or set(status) not in (required, required | {"expiry"}):
        raise SyncError("invalid_export_status")
    if type(status["version"]) is not int or status["version"] != 1 or status["status"] != "ok":
        raise SyncError("host_export_failed")
    if status["instance_id"] != instance:
        raise SyncError("instance_mismatch")
    exported = privacy.timestamp(status["exported_at"])
    if now - exported > dt.timedelta(minutes=5) or exported - now > dt.timedelta(seconds=60):
        raise SyncError("stale_or_future_export")
    if not isinstance(status["journal_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", status["journal_sha256"]):
        raise SyncError("invalid_export_checksum")
    if type(status["receipt_count"]) is not int or not 0 <= status["receipt_count"] <= privacy.MAX_RECORDS:
        raise SyncError("invalid_export_count")
    if "expiry" in status:
        expiry = status["expiry"]
        privacy.exact_keys(expiry, {"deleted", "kept", "missing", "backup_retention_days", "log_retention_days"}, "expiry summary")
        if (any(type(value) is not int or not 0 <= value <= privacy.MAX_RECORDS for value in expiry.values())
                or expiry["backup_retention_days"] != 30 or expiry["log_retention_days"] != 7):
            raise SyncError("invalid_expiry_summary")
    encoded = data["journal_b64"]
    if not isinstance(encoded, str) or len(encoded) > (privacy.MAX_BYTES + 2) // 3 * 4:
        raise SyncError("invalid_journal_size")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise SyncError("invalid_journal_encoding") from None
    if hashlib.sha256(raw).hexdigest() != status["journal_sha256"]:
        raise SyncError("export_checksum_mismatch")
    journal = privacy.validate_journal(privacy.decode_json(raw))
    if journal["instance_id"] != instance or len(journal["deletions"]) != status["receipt_count"]:
        raise SyncError("export_journal_mismatch")
    if any(privacy.timestamp(record["deleted_at"]) > exported + dt.timedelta(seconds=60) for record in journal["deletions"]):
        raise SyncError("invalid_receipt_clock")
    return journal, status


def _managed_location(item):
    if isinstance(item, str):
        return _allowed_directory(item), MANIFEST
    privacy.exact_keys(item, {"directory", "manifest"}, "managed directory")
    name = item["manifest"]
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}\.json", name) or ".." in name:
        raise SyncError("unsafe_manifest_name")
    return _allowed_directory(item["directory"]), name


def _managed_manifest(manifest):
    privacy.validate_manifest(manifest)
    for record in manifest["artifacts"]:
        created, expires = privacy.timestamp(record["created_at"]), privacy.timestamp(record["expires_at"])
        days = 7 if record["kind"] == "log" else 30
        if expires - created > dt.timedelta(days=days):
            raise SyncError("artifact_retention_exceeds_policy")
    return manifest


def enroll_artifact(directory, name, checksum, expires_at, *, created_at=None, now=None, kind="backup", manifest_name=MANIFEST):
    """Pin exactly one named archive; this prepares a manifest and never deletes."""
    root = _allowed_directory(str(directory))
    now = now or dt.datetime.now(UTC)
    # Name/type validation occurs before opening an operator-supplied basename.
    _, manifest_name = _managed_location({"directory": str(root), "manifest": manifest_name})
    record = {"path": name, "kind": kind, "created_at": "2000-01-01T00:00:00Z",
              "expires_at": "2000-01-02T00:00:00Z", "sha256": checksum}
    privacy.validate_manifest({"version": 1, "owner": privacy.OWNER, "artifacts": [record]})
    try:
        fd = os.open(root / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        raise SyncError("unsafe_enrollment_artifact") from None
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        privacy._check_file(info)
        if hashlib.file_digest(stream, "sha256").hexdigest() != checksum:
            raise SyncError("enrollment_checksum_mismatch")
    recorded = dt.datetime.fromtimestamp(info.st_mtime, UTC)
    created = privacy.timestamp(created_at) if created_at else recorded
    expires = privacy.timestamp(expires_at)
    if created > recorded + dt.timedelta(seconds=1) or created > now + dt.timedelta(seconds=60):
        raise SyncError("enrollment_cannot_reset_creation_clock")
    record.update(created_at=privacy.utc_string(created), expires_at=privacy.utc_string(expires))
    path = root / manifest_name
    with privacy.directory_lock(root, ".privacy-enrollment.lock"):
        manifest = privacy.read_private_json(path) if path.exists() or path.is_symlink() else {"version": 1, "owner": privacy.OWNER, "artifacts": []}
        _managed_manifest(manifest)
        previous = next((item for item in manifest["artifacts"] if item["path"] == name), None)
        if previous and (previous["sha256"] != checksum or expires > privacy.timestamp(previous["expires_at"])
                         or created > privacy.timestamp(previous["created_at"])):
            raise SyncError("enrollment_cannot_replace_or_extend_known_archive")
        manifest["artifacts"] = sorted([item for item in manifest["artifacts"] if item["path"] != name] + [record], key=lambda item: item["path"])
        _managed_manifest(manifest)
        _atomic_json(path, manifest)
    return record


def _docker_timestamp(value):
    # Docker may emit a local numeric offset. Preserve that exact identity
    # string in the pin; normalize only its time comparison with the cutover.
    if (not isinstance(value, str) or len(value) > 40
            or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})", value)):
        raise SyncError("invalid_docker_creation_timestamp")
    try:
        result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.utcoffset() is None:
            raise ValueError
        return result.astimezone(UTC)
    except ValueError:
        raise SyncError("invalid_docker_creation_timestamp") from None


def validate_retirement(record):
    privacy.exact_keys(record, {"version", "owner", "cutover_at", "expires_at", "volume", "containers"}, "frozen runtime")
    if type(record["version"]) is not int or record["version"] != 1 or record["owner"] != "scrum-pro-frozen-production":
        raise SyncError("invalid_frozen_runtime")
    cutover, expires = privacy.timestamp(record["cutover_at"]), privacy.timestamp(record["expires_at"])
    if expires != cutover + dt.timedelta(days=30):
        raise SyncError("frozen_runtime_requires_30_day_rollback")
    volume = record["volume"]
    privacy.exact_keys(volume, {"name", "created_at", "compose_project"}, "frozen volume")
    if (volume["name"] != "parley-local_parley-data" or volume["compose_project"] != "parley-local"
            or _docker_timestamp(volume["created_at"]) > cutover):
        raise SyncError("invalid_frozen_volume")
    containers = record["containers"]
    if not isinstance(containers, list) or len(containers) > 5:
        raise SyncError("invalid_frozen_containers")
    ids, names = set(), set()
    permitted = {"parley-local-db-1", "parley-local-public-app-1", "parley-local-public-gateway-1",
                 "parley-local-cloudflared-1", "parley-local-app-1"}
    for item in containers:
        privacy.exact_keys(item, {"id", "name"}, "frozen container")
        if (not isinstance(item["id"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["id"])
                or not isinstance(item["name"], str) or item["name"] not in permitted
                or item["id"] in ids or item["name"] in names):
            raise SyncError("invalid_frozen_containers")
        ids.add(item["id"])
        names.add(item["name"])
    return record


class DockerClient:
    def _run(self, arguments):
        try:
            result = subprocess.run(["/opt/homebrew/bin/docker", "--context", "colima", *arguments],
                                    stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
            if result.returncode or len(result.stdout) > 1024 * 1024:
                raise SyncError("frozen_runtime_docker_failed")
            return result.stdout.decode()
        except Exception:
            raise SyncError("frozen_runtime_docker_failed") from None

    def container_ids(self):
        return self._run(["ps", "-a", "--no-trunc", "--format", "{{.ID}}"]).splitlines()

    def volume_names(self):
        return self._run(["volume", "ls", "--format", "{{.Name}}"]).splitlines()

    def inspect_container(self, identifier):
        result = privacy.decode_json(self._run(["container", "inspect", identifier]).encode())
        if not isinstance(result, list) or len(result) != 1:
            raise SyncError("frozen_container_mismatch")
        return result[0]

    def inspect_volume(self, name):
        result = privacy.decode_json(self._run(["volume", "inspect", name]).encode())
        if not isinstance(result, list) or len(result) != 1:
            raise SyncError("frozen_volume_mismatch")
        return result[0]

    def volume_users(self, name):
        return self._run(["ps", "-a", "--no-trunc", "--filter", "volume=" + name, "--format", "{{.ID}}"]).splitlines()

    def remove_containers(self, identifiers):
        # No --force and no -v: Docker itself refuses newly running containers.
        self._run(["container", "rm", *identifiers])

    def remove_volume(self, name):
        # No --force: a new reference racing validation makes removal fail.
        self._run(["volume", "rm", name])


def retire_frozen_runtime(record, *, docker=None, now=None, apply=False):
    validate_retirement(record)
    now = now or dt.datetime.now(UTC)
    if privacy.timestamp(record["expires_at"]) > now:
        return "keep"
    docker = docker or DockerClient()
    volume = record["volume"]
    existing = set(docker.container_ids())
    expected = {item["id"] for item in record["containers"]}
    present = expected & existing
    has_volume = volume["name"] in docker.volume_names()
    if not has_volume and not present:
        return "already_retired"
    if not has_volume:
        raise SyncError("frozen_volume_missing_with_containers")
    observed = docker.inspect_volume(volume["name"])
    if (observed.get("Name") != volume["name"] or observed.get("CreatedAt") != volume["created_at"]
            or (observed.get("Labels") or {}).get("com.docker.compose.project") != volume["compose_project"]):
        raise SyncError("frozen_volume_mismatch")
    users = set(docker.volume_users(volume["name"]))
    if not users <= expected or not users <= present:
        raise SyncError("frozen_volume_has_unknown_references")
    for item in record["containers"]:
        if item["id"] not in present:
            continue  # A previous supported removal may already have removed it.
        value = docker.inspect_container(item["id"])
        state = value.get("State") or {}
        if (value.get("Id") != item["id"] or value.get("Name") != "/" + item["name"]
                or state.get("Running") is not False or state.get("Status") not in {"created", "exited"}
                or (value.get("Config", {}).get("Labels") or {}).get("com.docker.compose.project") != "parley-local"
                or _docker_timestamp(value.get("Created")) > privacy.timestamp(record["cutover_at"])):
            raise SyncError("frozen_container_mismatch_or_running")
        if item["name"] == "parley-local-db-1" and item["id"] not in users:
            raise SyncError("frozen_database_volume_mismatch")
    if not apply:
        return "would_retire"
    if present:
        docker.remove_containers(sorted(present))
    if docker.volume_users(volume["name"]):
        raise SyncError("frozen_volume_has_new_references")
    docker.remove_volume(volume["name"])
    return "retired"


def sync_once(config, runtime=RUNTIME, *, transport=ssh_export, now=None, apply_expiry=False,
              mirror=mirror_journal, docker=None):
    now = now or dt.datetime.now(UTC)
    runtime = _private_directory(runtime, create=True)
    with privacy.directory_lock(runtime, ".privacy-studio.lock"):
        return _sync_locked(config, runtime, transport=transport, now=now,
                            apply_expiry=apply_expiry, mirror=mirror, docker=docker)


def _run_expiry(config, *, docker, now, apply_expiry):
    # Local retention is independent of journal-source or NAS availability.
    # Validate every managed artifact and frozen-runtime pin before any removal.
    managed = []
    for item in config["managed_directories"]:
        root, manifest_name = _managed_location(item)
        manifest = _managed_manifest(privacy.read_private_json(root / manifest_name))
        privacy.expire_artifacts(root, manifest, apply=False, now=now)
        managed.append((root, manifest))
    for retirement in config.get("docker_retirements", []):
        retire_frozen_runtime(retirement, docker=docker, now=now, apply=False)
    counts = {"deleted": 0, "kept": 0, "missing": 0, "would_delete": 0}
    for root, manifest in managed:
        for item in privacy.expire_artifacts(root, manifest, apply=apply_expiry, now=now):
            key = "kept" if item["status"] == "keep" else item["status"]
            counts[key] += 1
    frozen = [retire_frozen_runtime(item, docker=docker, now=now, apply=apply_expiry)
              for item in config.get("docker_retirements", [])]
    return {"expiry": counts, "frozen_runtimes": frozen}


def _failure_reason(error):
    return str(error) if isinstance(error, SyncError) else "local_validation_or_io_failed"


def _sync_locked(config, runtime, *, transport, now, apply_expiry, mirror, docker):
    journal_dir = _private_directory(runtime / "journal", create=True)
    state_path = runtime / "status.json"
    previous = privacy.read_private_json(state_path) if state_path.exists() or state_path.is_symlink() else {}
    last_success = previous.get("last_success") if isinstance(previous, dict) else None
    state = {"version": 1, "status": "failed", "last_attempt_at": privacy.utc_string(now), "last_success": last_success}
    try:
        # Invalid configuration never authorizes expiry, even during an outage.
        validate_config(config)
        sync_error = expiry_error = None
        success = None
        try:
            journal, status = _validate_export(transport(), config["instance_id"], now)
            count = privacy.write_journal(journal_dir / "deletions.json", journal)
            durable = _private_bytes(journal_dir / "deletions.json")
            success = {"instance_id": config["instance_id"], "journal_sha256": hashlib.sha256(durable).hexdigest(),
                       "host_journal_sha256": status["journal_sha256"], "host_exported_at": status["exported_at"],
                       "local_durable_at": privacy.utc_string(now), "receipt_count": count,
                       "retained_receipts": count - len(journal["deletions"])}
            state["local_sync"] = success
            if config.get("nas_mirror") is not None:
                try:
                    mirror(durable, config["nas_mirror"])
                    state["nas_mirror"] = True
                except Exception:
                    state["nas_mirror"] = False
                    raise SyncError("nas_mirror_failed") from None
            state["sync_status"] = "ok"
        except Exception as error:
            sync_error = _failure_reason(error)
            state.update(sync_status="failed", sync_reason=sync_error)
        # A failed remote pull cannot extend the lifetime of known, locally
        # enrolled data. This phase trusts only the separately validated config,
        # exact manifests, artifact checksums and frozen Docker identity pins.
        try:
            state.update(_run_expiry(config, docker=docker, now=now, apply_expiry=apply_expiry))
            state["expiry_status"] = "ok"
        except Exception as error:
            expiry_error = _failure_reason(error)
            state.update(expiry_status="failed", expiry_reason=expiry_error)
        if sync_error or expiry_error:
            raise SyncError(sync_error or expiry_error)
        state.update(status="ok", last_success=success)
        _atomic_json(state_path, state)
        return state
    except Exception as error:
        state["reason"] = _failure_reason(error)
        try:
            _atomic_json(state_path, state)
        except Exception:
            pass
        raise SyncError(state["reason"]) from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    sync = commands.add_parser("sync")
    sync.add_argument("--config", type=Path, default=RUNTIME / "config.json")
    sync.add_argument("--apply-expiry", action="store_true")
    enroll = commands.add_parser("enroll", help="prepare an exact archive manifest; does not delete")
    enroll.add_argument("--directory", type=Path, required=True)
    enroll.add_argument("--artifact", required=True)
    enroll.add_argument("--sha256", required=True)
    enroll.add_argument("--created-at")
    enroll.add_argument("--expires-at", required=True)
    enroll.add_argument("--kind", choices=["backup", "rollback", "log"], default="backup")
    enroll.add_argument("--manifest", default=MANIFEST)
    args = parser.parse_args(argv)
    try:
        if args.command == "sync":
            config = privacy.read_private_json(args.config)
            sync_once(config, RUNTIME, apply_expiry=args.apply_expiry)
        else:
            enroll_artifact(args.directory, args.artifact, args.sha256, args.expires_at,
                            created_at=args.created_at, kind=args.kind, manifest_name=args.manifest)
        return 0
    except Exception as error:
        # Raw SSH stderr, filenames, UUIDs, environment values and JSON bodies
        # never reach the daemon log. Detailed state contains fixed codes only.
        print("Scrum Pro privacy maintenance failed; inspect protected status.", file=sys.stderr)
        if args.command == "sync" and not isinstance(error, SyncError):
            try:
                runtime = _private_directory(RUNTIME, create=True)
                with privacy.directory_lock(runtime, ".privacy-studio.lock"):
                    state_path = runtime / "status.json"
                    state = privacy.read_private_json(state_path) if state_path.exists() else {}
                    state.update(version=1, status="failed", reason="configuration_or_maintenance_failed",
                                 last_attempt_at=privacy.utc_string(dt.datetime.now(UTC)))
                    _atomic_json(state_path, state)
            except Exception:
                pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
