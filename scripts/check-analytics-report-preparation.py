#!/usr/bin/env python3
"""Check LOCAL report recipes and acceptance bindings; rollout always stays blocked.

No query, browser, collector, deployment or admission operation is performed.
Synthetic recipe totals and matching hashes do not establish accepted records.
"""
from collections import Counter
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("analytics_readiness_for_reports", ROOT / "scripts/check-analytics-readiness.py")
readiness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(readiness)
BINDING_KEYS = readiness.MANIFEST_KEYS | {"source_commit", "tracker_version", "gateway_sha256", "readiness_sha256"}
SCENARIOS = {
    "host_setup", "invited_browser", "signed_link", "poker_changes_manual_retry", "standup_first_save_flush",
    "unknown_creation_then_retry", "named_default_off", "dnt", "optout_before_load", "optout_after_load",
    "frame", "unapproved_host", "blocked_tracker", "offline_send", "websocket_replay", "maintenance_new_snapshot",
    "stale_admission", "old_artifact_hash", "old_snapshot_expired", "old_snapshot_timely", "new_artifact_bound",
    "rollback_all_collection_off", "native_cache_identity_stripped", "invitation_preview_or_denied",
    "guest_link_denied", "local_validation",
}
ZERO_NAMED_CASES = {
    "named_default_off", "dnt", "optout_before_load", "frame", "unapproved_host", "blocked_tracker",
    "offline_send", "websocket_replay", "maintenance_new_snapshot", "stale_admission",
    "old_artifact_hash", "old_snapshot_expired", "rollback_all_collection_off", "invitation_preview_or_denied",
    "guest_link_denied", "local_validation",
}
# These vectors describe no accepted collection, not merely no named actions.
ZERO_COLLECTION_CASES = {
    "dnt", "optout_before_load", "frame", "unapproved_host", "blocked_tracker", "offline_send",
    "maintenance_new_snapshot", "stale_admission", "old_artifact_hash", "old_snapshot_expired",
    "rollback_all_collection_off",
}
FLOW_STEPS = {
    "host_setup": (["/", "workspace_created", "session_created"], None),
    "invited_browser": (["/invite", "invitation_accepted", "room_opened"], None),
    "poker": (["room_opened", "poker_vote_saved"], "poker"),
    "standup": (["room_opened", "standup_participated"], "standup"),
}


def policy():
    raw = readiness.read_regular(ROOT / "web/src/lib/analytics-policy.json", 65536)
    if raw != readiness.read_regular(ROOT / "internal/analyticsrelay/policy.generated.json", 65536):
        raise ValueError("POLICY_DRIFT")
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def validate_catalog(catalog, canonical):
    readiness.exact_keys(catalog, {"schema", "scope", "default_tier", "reports", "flows", "scenarios"})
    if type(catalog["schema"]) is not int or catalog["schema"] != 1 or catalog["scope"] != "LOCAL" or catalog["default_tier"] != "actions":
        raise ValueError("CATALOG_INVALID")
    if any(not isinstance(catalog[key], list) for key in ("reports", "flows", "scenarios")):
        raise ValueError("CATALOG_INVALID")
    required = {"pageviews", *canonical["events"]}
    seen = set()
    for report in catalog["reports"]:
        readiness.exact_keys(report, {"id", "event", "unit", "aggregation", "dimensions", "schema_filter", "native_filter_status"})
        name = report["id"]
        if not isinstance(name, str) or name not in required or name in seen:
            raise ValueError("REPORT_INVALID")
        seen.add(name)
        if report["unit"] != "observations" or report["aggregation"] != "count" or report["native_filter_status"] != "unverified":
            raise ValueError("REPORT_INVALID")
        if name == "pageviews":
            if report["event"] is not None or report["dimensions"] != ["url"] or report["schema_filter"] is not None:
                raise ValueError("REPORT_INVALID")
        elif report["event"] != name or report["dimensions"] != list(canonical["events"][name]) or type(report["schema_filter"]) is not int or report["schema_filter"] != 1:
            raise ValueError("REPORT_INVALID")
    if seen != required:
        raise ValueError("REPORT_COVERAGE_MISSING")
    seen = set()
    for flow in catalog["flows"]:
        readiness.exact_keys(flow, {"id", "steps", "kind", "max_gap_minutes", "allow_intermediate", "unit", "availability"})
        name = flow["id"]
        if not isinstance(name, str) or name not in FLOW_STEPS or name in seen:
            raise ValueError("FLOW_INVALID")
        seen.add(name)
        steps, kind = FLOW_STEPS[name]
        if flow["steps"] != steps or flow["kind"] != kind or type(flow["max_gap_minutes"]) is not int or flow["max_gap_minutes"] != 60 or flow["allow_intermediate"] is not True:
            raise ValueError("FLOW_INVALID")
        if flow["unit"] != "collector-anonymous-context" or flow["availability"] != "unavailable-until-installed-proof":
            raise ValueError("FLOW_INVALID")
    if seen != set(FLOW_STEPS):
        raise ValueError("FLOW_COVERAGE_MISSING")
    seen = set()
    for scenario in catalog["scenarios"]:
        readiness.exact_keys(scenario, {"id", "scope", "pageviews", "events", "expected_counts"})
        name = scenario["id"]
        if not isinstance(name, str) or name not in SCENARIOS or name in seen or scenario["scope"] != "LOCAL":
            raise ValueError("SCENARIO_INVALID")
        seen.add(name)
        if type(scenario["pageviews"]) is not int or not 0 <= scenario["pageviews"] <= 100 or not isinstance(scenario["events"], list) or len(scenario["events"]) > 100:
            raise ValueError("SCENARIO_INVALID")
        if any(not isinstance(event, str) or event not in canonical["events"] for event in scenario["events"]):
            raise ValueError("SCENARIO_INVALID")
        if name in ZERO_COLLECTION_CASES and (scenario["pageviews"] or scenario["events"]):
            raise ValueError("DROP_ORACLE_INVALID")
        if name in ZERO_NAMED_CASES and scenario["events"]:
            raise ValueError("DROP_ORACLE_INVALID")
        counts = scenario["expected_counts"]
        if not isinstance(counts, dict) or any(type(count) is not int for count in counts.values()) or counts != dict(Counter(scenario["events"])):
            raise ValueError("SCENARIO_TOTAL_MISMATCH")
    if seen != SCENARIOS:
        raise ValueError("SCENARIO_COVERAGE_MISSING")


def validate_bindings(bindings, canonical, policy_hash):
    readiness.exact_keys(bindings, BINDING_KEYS)
    readiness.validate_manifest({key: bindings[key] for key in readiness.MANIFEST_KEYS})
    if not isinstance(bindings["source_commit"], str) or not re.fullmatch(r"[0-9a-f]{40}", bindings["source_commit"]):
        raise ValueError("SOURCE_INVALID")
    if not isinstance(bindings["tracker_version"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", bindings["tracker_version"]):
        raise ValueError("VERSION_INVALID")
    readiness.digest(bindings["gateway_sha256"])
    if bindings["readiness_sha256"] is not None:
        readiness.digest(bindings["readiness_sha256"])
    pins = {"website_id": canonical["website"], "policy_sha256": policy_hash,
            "tracker_sha256": canonical["tracker_sha256"], "collector_version": canonical["collector_version"],
            "collector_image": canonical["collector_image"]}
    if any(bindings[key] != value for key, value in pins.items()):
        raise ValueError("POLICY_BINDING_MISMATCH")


def check(catalog, manifest, expected, now, receipt=None, evidence_root=None):
    canonical, policy_hash = policy()
    validate_catalog(catalog, canonical)
    validate_bindings(expected, canonical, policy_hash)
    readiness.exact_keys(manifest, {"scope", "rollout", "report_tier", "bindings", "window"})
    if manifest["scope"] != "LOCAL" or manifest["rollout"] != "blocked" or manifest["bindings"] != expected:
        raise ValueError("MANIFEST_INVALID")
    # Validate types on BOTH sides; Python bool/int equality is insufficient.
    validate_bindings(manifest["bindings"], canonical, policy_hash)
    if not isinstance(manifest["report_tier"], str) or manifest["report_tier"] not in {"actions", "anonymous-flows"}:
        raise ValueError("TIER_INVALID")
    window = manifest["window"]
    readiness.exact_keys(window, {"start", "end", "timezone"})
    start, end = readiness.timestamp(window["start"]), readiness.timestamp(window["end"])
    zone = ZoneInfo("Europe/Berlin")
    local_start, local_end = start.astimezone(zone), end.astimezone(zone)
    if window["timezone"] != "Europe/Berlin" or local_start.time() != dt.time() or local_end.time() != dt.time() or (local_end.date() - local_start.date()).days != 7 or end > now:
        raise ValueError("WINDOW_INVALID")
    blockers = ["LIVE_ACCEPTANCE_MISSING"]
    flow_status = "unavailable"
    if receipt is None:
        blockers.append("READINESS_MISSING")
    else:
        if expected["readiness_sha256"] is None or hashlib.sha256(receipt).hexdigest() != expected["readiness_sha256"]:
            raise ValueError("READINESS_HASH_MISMATCH")
        value = json.loads(receipt, object_pairs_hook=readiness.unique_object, parse_constant=readiness.invalid_constant)
        if not isinstance(value, dict):
            raise ValueError("READINESS_INVALID")
        if readiness.freshness(readiness.timestamp(value.get("checked_at")), now):
            raise ValueError("READINESS_STALE")
        result = readiness.check(value, {key: expected[key] for key in readiness.MANIFEST_KEYS}, evidence_root, now)
        if result["readiness"] != "ready":
            blockers.append("READINESS_BLOCKED")
        elif manifest["report_tier"] == "anonymous-flows" and result["report_tier"] == "anonymous-flows":
            flow_status = "requires-installed-report-proof"
    return {"scope": "LOCAL", "rollout": "blocked", "blockers": blockers, "flow_status": flow_status}


def load(path):
    return json.loads(readiness.read_regular(path, 1048576), object_pairs_hook=readiness.unique_object,
                      parse_constant=readiness.invalid_constant)


def main():
    parser = readiness.ReadinessArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--expected-manifest", required=True)
    parser.add_argument("--readiness-receipt")
    parser.add_argument("--evidence-root")
    parser.add_argument("--now", help="deterministic isolated tests only")
    try:
        args = parser.parse_args()
        now = readiness.timestamp(args.now) if args.now else dt.datetime.now(readiness.UTC)
        receipt = readiness.read_regular(args.readiness_receipt, readiness.MAX_RECEIPT_BYTES) if args.readiness_receipt else None
        if receipt is not None and args.evidence_root is None:
            raise ValueError("EVIDENCE_ROOT_REQUIRED")
        result = check(load(ROOT / "docs/analytics/report-recipes.json"), load(args.manifest),
                       load(args.expected_manifest), now, receipt, args.evidence_root)
    except (ValueError, TypeError, OSError, AttributeError, RecursionError):
        print(json.dumps({"scope": "LOCAL", "errors": ["PREPARATION_REFUSED"]}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 1  # Even a valid LOCAL preparation never passes rollout.


if __name__ == "__main__":
    raise SystemExit(main())
