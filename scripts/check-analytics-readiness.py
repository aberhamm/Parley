#!/usr/bin/env python3
"""Validate a local, sanitized rollout receipt; never contact or change a service.

A ready result checks structure/bindings and referenced bytes, not their truth,
authority or legal sufficiency. The operator and independent reviewer must
verify proof contents before any separately authorized rollout.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

UTC = dt.timezone.utc
MAX_RECEIPT_BYTES = 65536
MAX_EVIDENCE_BYTES = 1024 * 1024
MANIFEST_KEYS = {
    "contract_schema", "relay_interface_schema", "tracker_sha256", "policy_sha256",
    "collector_version", "collector_build", "collector_image", "website_id", "app_image", "app_build",
}
PROOF_BLOCKERS = {
    "owner": "OWNER_UNVERIFIED", "capabilities": "CAPABILITIES_UNVERIFIED",
    "ingestion": "INGESTION_UNVERIFIED", "policy_approval": "POLICY_APPROVAL_UNVERIFIED",
    "site_access": "ACCESS_UNVERIFIED", "expiry": "EXPIRY_UNVERIFIED",
    "all_copies": "ALL_COPIES_UNVERIFIED", "restore": "RESTORE_UNVERIFIED",
    "relay_artifact": "RELAY_ARTIFACT_UNVERIFIED",
    "installed_correspondence": "INSTALLED_CORRESPONDENCE_UNVERIFIED",
    "custody_phase": "CUSTODY_PHASE_UNVERIFIED", "independent_review": "REVIEW_UNVERIFIED",
    "identity": "IDENTITY_UNVERIFIED", "flow_reports": "FLOW_REPORTS_UNVERIFIED",
}
BLOCKERS = set(PROOF_BLOCKERS.values()) | {
    "COLLECTOR_IMAGE_UNAVAILABLE", "RETENTION_UNSUPPORTED", "RECEIPT_STALE", "RECEIPT_FUTURE",
    "EVIDENCE_STALE", "EVIDENCE_DRIFT", "EVIDENCE_MISSING", "EVIDENCE_BINDING_MISMATCH",
    "IDENTITY_NOT_DISTINCT", "PROXY_BOUNDARY_UNVERIFIED", "PUBLIC_SHARING_ENABLED",
    "COLLECTION_NOT_OFF", "EXPIRY_DEADLINE_MISSED", "OWNED_COPIES_UNKNOWN",
}
RECEIPT_KEYS = MANIFEST_KEYS | {
    "schema", "checked_at", "retention_days", "readiness", "blockers", "proxy_identity",
    "report_tier", "identity_inputs", "retention_support", "public_sharing", "collection_off",
    "expiry_deadline_met", "owned_copies_complete", "owner_role", "evidence",
}


def exact_keys(value, keys):
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("SCHEMA_INVALID")


def digest(value, image=False):
    pattern = r"sha256:[0-9a-f]{64}" if image else r"[0-9a-f]{64}"
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError("BINDING_INVALID")


def timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", value):
        raise ValueError("TIMESTAMP_INVALID")
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        raise ValueError("TIMESTAMP_INVALID") from None


def freshness(when, now):
    if when > now + dt.timedelta(minutes=5):
        return "RECEIPT_FUTURE"
    if when < now - dt.timedelta(hours=24):
        return "RECEIPT_STALE"
    return None


def manifest_binding(expected):
    return hashlib.sha256(json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_manifest(expected):
    exact_keys(expected, MANIFEST_KEYS)
    for key in ("contract_schema", "relay_interface_schema"):
        if type(expected[key]) is not int or expected[key] != 1:
            raise ValueError("BINDING_INVALID")
    for key in ("tracker_sha256", "policy_sha256", "app_build"):
        digest(expected[key])
    for key in ("collector_image", "app_image"):
        digest(expected[key], image=True)
    for key in ("collector_version", "collector_build"):
        if not isinstance(expected[key], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", expected[key]):
            raise ValueError("BINDING_INVALID")
    try:
        site = str(uuid.UUID(expected["website_id"]))
    except (ValueError, AttributeError, TypeError):
        raise ValueError("BINDING_INVALID") from None
    if site != expected["website_id"]:
        raise ValueError("BINDING_INVALID")


def private_ref(value):
    if not isinstance(value, str) or len(value) > 256:
        raise ValueError("REFERENCE_INVALID")
    parts = value.split("/")
    if len(parts) > 8 or any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", part) for part in parts):
        raise ValueError("REFERENCE_INVALID")
    return parts


def read_regular(path, limit):
    # Nonblocking prevents a FIFO from hanging this offline checker. O_NOFOLLOW
    # rejects final symlinks; proof path components are checked separately.
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("FILE_INVALID")
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("FILE_INVALID")
    return data


def proof_problem(proof, expected, root, now):
    exact_keys(proof, {"ref", "sha256", "binding_sha256", "checked_at", "scope"})
    parts = private_ref(proof["ref"])
    digest(proof["sha256"])
    digest(proof["binding_sha256"])
    if proof["scope"] != "website" or proof["binding_sha256"] != manifest_binding(expected):
        return "EVIDENCE_BINDING_MISMATCH"
    if freshness(timestamp(proof["checked_at"]), now):
        return "EVIDENCE_STALE"
    path = root
    try:
        if path.is_symlink() or not path.is_dir():
            return "EVIDENCE_MISSING"
        for part in parts:
            path = path / part
            if path.is_symlink():
                return "EVIDENCE_MISSING"
        content = read_regular(path, MAX_EVIDENCE_BYTES)
    except (OSError, ValueError):
        return "EVIDENCE_MISSING"
    if hashlib.sha256(content).hexdigest() != proof["sha256"]:
        return "EVIDENCE_DRIFT"
    return None


def check(receipt, expected, evidence_root, now):
    validate_manifest(expected)
    exact_keys(receipt, RECEIPT_KEYS)
    if type(receipt["schema"]) is not int or receipt["schema"] != 1:
        raise ValueError("SCHEMA_INVALID")
    actual = {key: receipt[key] for key in MANIFEST_KEYS}
    validate_manifest(actual)
    if actual != expected:
        raise ValueError("MANIFEST_MISMATCH")
    if type(receipt["retention_days"]) is not int or receipt["retention_days"] != 90:
        raise ValueError("POLICY_INVALID")
    if receipt["owner_role"] != "collector-operator":
        raise ValueError("OWNER_INVALID")
    for key in ("public_sharing", "collection_off", "expiry_deadline_met", "owned_copies_complete"):
        if type(receipt[key]) is not bool:
            raise ValueError("SCHEMA_INVALID")
    enums = {
        "readiness": {"ready", "blocked"}, "proxy_identity": {"distinct", "merged", "unknown"},
        "report_tier": {"actions", "anonymous-flows"},
        "identity_inputs": {"relay-minimized", "unknown"},
        "retention_support": {"dedicated-expiry", "unsupported", "unknown"},
    }
    for key, allowed in enums.items():
        if not isinstance(receipt[key], str) or receipt[key] not in allowed:
            raise ValueError("SCHEMA_INVALID")
    declared = receipt["blockers"]
    if not isinstance(declared, list) or any(not isinstance(code, str) or code not in BLOCKERS for code in declared):
        raise ValueError("BLOCKERS_INVALID")
    if len(declared) != len(set(declared)):
        raise ValueError("BLOCKERS_INVALID")
    problems = set()
    age = freshness(timestamp(receipt["checked_at"]), now)
    if age:
        problems.add(age)
    conditions = (
        (receipt["retention_support"] != "dedicated-expiry", "RETENTION_UNSUPPORTED"),
        (receipt["identity_inputs"] != "relay-minimized", "PROXY_BOUNDARY_UNVERIFIED"),
        (receipt["public_sharing"], "PUBLIC_SHARING_ENABLED"),
        (not receipt["collection_off"], "COLLECTION_NOT_OFF"),
        (not receipt["expiry_deadline_met"], "EXPIRY_DEADLINE_MISSED"),
        (not receipt["owned_copies_complete"], "OWNED_COPIES_UNKNOWN"),
    )
    problems.update(code for failed, code in conditions if failed)
    flows = receipt["report_tier"] == "anonymous-flows"
    if flows and receipt["proxy_identity"] != "distinct":
        problems.add("IDENTITY_NOT_DISTINCT")
    exact_keys(receipt["evidence"], set(PROOF_BLOCKERS))
    for name, code in PROOF_BLOCKERS.items():
        proof = receipt["evidence"][name]
        if proof is None:
            if flows or name not in ("identity", "flow_reports"):
                problems.add(code)
        else:
            problem = proof_problem(proof, expected, Path(evidence_root), now)
            if problem:
                problems.add(problem)
    if receipt["readiness"] == "ready":
        if declared or problems:
            raise ValueError("FALSE_READY")
    elif not declared or not problems.issubset(declared):
        raise ValueError("BLOCKERS_INCOMPLETE")
    return {"readiness": receipt["readiness"], "report_tier": receipt["report_tier"], "blockers": sorted(declared)}


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("JSON_INVALID")
        value[key] = item
    return value


def invalid_constant(_value):
    raise ValueError("JSON_INVALID")


class ReadinessArgumentParser(argparse.ArgumentParser):
    def error(self, _message):
        # argparse diagnostics can reflect operator-supplied values and paths.
        raise ValueError("ARGUMENTS_INVALID")


def main():
    parser = ReadinessArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--evidence-root", required=True, help="private local proof bundle; never fetched")
    parser.add_argument("--now", help="UTC clock injection for deterministic isolated tests only")
    for key in sorted(MANIFEST_KEYS):
        parser.add_argument("--" + key.replace("_", "-"), required=True,
                            type=int if key in ("contract_schema", "relay_interface_schema") else str)
    try:
        args = parser.parse_args()
        now = timestamp(args.now) if args.now else dt.datetime.now(UTC)
        raw = read_regular(args.receipt, MAX_RECEIPT_BYTES)
        receipt = json.loads(raw, object_pairs_hook=unique_object,
                             parse_constant=invalid_constant)
        expected = {key: getattr(args, key) for key in MANIFEST_KEYS}
        result = check(receipt, expected, Path(args.evidence_root), now)
    except (OSError, ValueError, TypeError, RecursionError):
        # Never echo paths, reference contents, parser exceptions or receipt data.
        print(json.dumps({"readiness": "invalid", "errors": ["RECEIPT_REFUSED"]}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["readiness"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
