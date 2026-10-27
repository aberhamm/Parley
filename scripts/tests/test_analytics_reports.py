"""LOCAL synthetic recipe checks, never real collector/acceptance evidence."""
import copy
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/check-analytics-report-preparation.py"
spec = importlib.util.spec_from_file_location("report_preparation", SCRIPT)
reports = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reports)
spec = importlib.util.spec_from_file_location("readiness_test_fixture", ROOT / "scripts/tests/test_analytics_readiness.py")
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
POLICY_PATH = ROOT / "web/src/lib/analytics-policy.json"
POLICY = json.loads(POLICY_PATH.read_text())
NOW = dt.datetime(2026, 10, 27, 12, tzinfo=dt.timezone.utc)


class ReportPreparationTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads((ROOT / "docs/analytics/report-recipes.json").read_text())
        self.expected = {**fixture.EXPECTED, "source_commit": "f" * 40, "tracker_version": "3.0.3", "gateway_sha256": "c" * 64,
                         "policy_sha256": hashlib.sha256(POLICY_PATH.read_bytes()).hexdigest(),
                         "website_id": POLICY["website"], "tracker_sha256": POLICY["tracker_sha256"],
                         "collector_version": POLICY["collector_version"], "collector_image": POLICY["collector_image"],
                         "readiness_sha256": None}
        self.manifest = {"scope": "LOCAL", "rollout": "blocked", "report_tier": "actions",
                         "bindings": copy.deepcopy(self.expected),
                         "window": {"start": "2026-10-19T22:00:00Z", "end": "2026-10-26T23:00:00Z", "timezone": "Europe/Berlin"}}
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def check(self, receipt=None):
        return reports.check(self.catalog, self.manifest, self.expected, NOW, receipt, self.root)

    def bind_receipt(self, tier="actions", blocked=False):
        receipt = fixture.synthetic_receipt(self.root)
        expected = {key:self.expected[key] for key in fixture.EXPECTED}
        receipt.update(expected)
        for proof in receipt["evidence"].values():proof["binding_sha256"] = fixture.binding(expected)
        receipt["report_tier"] = tier
        if tier == "anonymous-flows":receipt["proxy_identity"] = "distinct"
        if blocked:receipt.update(readiness="blocked",blockers=["COLLECTOR_IMAGE_UNAVAILABLE"])
        raw=json.dumps(receipt).encode()
        self.expected["readiness_sha256"] = hashlib.sha256(raw).hexdigest()
        self.manifest["bindings"] = copy.deepcopy(self.expected)
        return raw

    def test_local_preparation_never_reports_ready_without_live_evidence(self):
        self.assertEqual(self.check()["rollout"], "blocked")
        self.assertIn("READINESS_MISSING", self.check()["blockers"])
        for blocked in (False, True):
            result=self.check(self.bind_receipt(blocked=blocked))
            self.assertEqual(result["rollout"], "blocked")
            self.assertIn("LIVE_ACCEPTANCE_MISSING", result["blockers"])
            if blocked:self.assertIn("READINESS_BLOCKED",result["blockers"])

    def test_every_final_binding_must_match_explicit_expectation(self):
        for key,value in self.expected.items():
            with self.subTest(binding=key):
                original=copy.deepcopy(self.manifest)
                self.manifest["bindings"][key] = value+"wrong" if isinstance(value,str) else "wrong"
                with self.assertRaises(ValueError):self.check()
                self.manifest=original

    def test_policy_pins_cannot_be_replaced_by_matching_fake_inputs(self):
        for key in ("policy_sha256","website_id","tracker_sha256","collector_image","contract_schema","relay_interface_schema"):
            with self.subTest(binding=key):
                original=copy.deepcopy(self.expected)
                self.expected[key]="wrong"
                self.manifest["bindings"]=copy.deepcopy(self.expected)
                with self.assertRaises(ValueError):self.check()
                self.expected=original
                self.manifest["bindings"]=copy.deepcopy(original)

    def test_receipt_bytes_and_freshness_cannot_drift(self):
        raw=self.bind_receipt()
        with self.assertRaises(ValueError):self.check(raw+b" ")
        receipt=json.loads(raw);receipt["checked_at"]="2026-10-25T00:00:00Z"
        stale=json.dumps(receipt).encode();self.expected["readiness_sha256"]=hashlib.sha256(stale).hexdigest()
        self.manifest["bindings"]=copy.deepcopy(self.expected)
        with self.assertRaises(ValueError):self.check(stale)

    def test_flow_tier_requires_readiness_tier_and_still_needs_live_report_proof(self):
        self.manifest["report_tier"]="anonymous-flows"
        self.assertEqual(self.check(self.bind_receipt())["flow_status"],"unavailable")
        result=self.check(self.bind_receipt(tier="anonymous-flows"))
        self.assertEqual(result["flow_status"],"requires-installed-report-proof")
        self.assertEqual(result["rollout"],"blocked")

    def test_report_recipe_refuses_unique_counts_unknown_events_or_unproven_filters(self):
        for key,value in (("unit","unique-people"),("aggregation","conversion"),("event","private-event"),
                          ("schema_filter",2),("native_filter_status","verified"),("dimensions",["person_id"])):
            with self.subTest(field=key):
                old=copy.deepcopy(self.catalog)
                self.catalog["reports"][1][key]=value
                with self.assertRaises(ValueError):self.check()
                self.catalog=old

    def test_scenario_oracle_rejects_fabricated_totals_and_missing_negative_cases(self):
        self.catalog["scenarios"][0]["expected_counts"]["workspace_created"]=2
        with self.assertRaises(ValueError):self.check()
        self.catalog=json.loads((ROOT / "docs/analytics/report-recipes.json").read_text())
        self.catalog["scenarios"]=[x for x in self.catalog["scenarios"] if x["id"]!="old_artifact_hash"]
        with self.assertRaises(ValueError):self.check()

    def test_dropped_event_scenario_cannot_fabricate_a_named_observation(self):
        for name in ("named_default_off", "frame", "stale_admission", "rollback_all_collection_off"):
            with self.subTest(scenario=name):
                old=copy.deepcopy(self.catalog)
                scenario=next(x for x in self.catalog["scenarios"] if x["id"]==name)
                scenario["events"]=["poker_vote_saved"]
                scenario["expected_counts"]={"poker_vote_saved":1}
                with self.assertRaises(ValueError):self.check()
                self.catalog=old

    def test_all_collection_drop_scenarios_refuse_pageviews(self):
        for name in ("dnt", "optout_before_load", "frame", "unapproved_host", "blocked_tracker",
                     "offline_send", "maintenance_new_snapshot", "stale_admission", "old_artifact_hash",
                     "old_snapshot_expired", "rollback_all_collection_off"):
            with self.subTest(scenario=name):
                original = copy.deepcopy(self.catalog)
                scenario = next(x for x in self.catalog["scenarios"] if x["id"] == name)
                scenario["pageviews"] = 1
                with self.assertRaises(ValueError):
                    self.check()
                self.catalog = original

    def test_all_collection_drop_scenarios_refuse_named_observations(self):
        for name in ("dnt", "optout_before_load", "frame", "unapproved_host", "blocked_tracker",
                     "offline_send", "maintenance_new_snapshot", "stale_admission", "old_artifact_hash",
                     "old_snapshot_expired", "rollback_all_collection_off"):
            with self.subTest(scenario=name):
                original = copy.deepcopy(self.catalog)
                scenario = next(x for x in self.catalog["scenarios"] if x["id"] == name)
                scenario["events"] = ["poker_vote_saved"]
                scenario["expected_counts"] = {"poker_vote_saved": 1}
                with self.assertRaises(ValueError):
                    self.check()
                self.catalog = original

    def test_named_default_off_allows_pageviews_without_named_observations(self):
        scenario = next(x for x in self.catalog["scenarios"] if x["id"] == "named_default_off")
        for count in (0, 1, 2):
            with self.subTest(pageviews=count):
                scenario["pageviews"] = count
                self.assertEqual(self.check()["rollout"], "blocked")

    def test_cli_only_emits_blocked_local_or_fixed_refusal_and_keeps_help(self):
        manifest_path=self.root/"manifest.json"
        expected_path=self.root/"expected.json"
        manifest_path.write_text(json.dumps(self.manifest));expected_path.write_text(json.dumps(self.expected))
        command=["python3",str(SCRIPT),"--manifest",str(manifest_path),"--expected-manifest",str(expected_path),"--now","2026-10-27T12:00:00Z"]
        result=subprocess.run(command,capture_output=True,text=True)
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertEqual(json.loads(result.stdout)["rollout"],"blocked")
        marker="/synthetic/private/PRIVATE-PROOF-MARKER"
        invalid=subprocess.run(command+["--unsupported",marker],capture_output=True,text=True)
        self.assertEqual(invalid.returncode,2)
        self.assertEqual(invalid.stderr,"")
        self.assertNotIn(marker,invalid.stdout)
        self.assertEqual(json.loads(invalid.stdout),{"scope":"LOCAL","errors":["PREPARATION_REFUSED"]})
        help_result=subprocess.run(["python3",str(SCRIPT),"--help"],capture_output=True,text=True)
        self.assertEqual(help_result.returncode,0)
        self.assertIn("--expected-manifest",help_result.stdout)

    def test_flow_definitions_require_consecutive_sixty_minute_windows(self):
        for key,value in (("max_gap_minutes",120),("allow_intermediate",False),("unit","people")):
            with self.subTest(field=key):
                original=copy.deepcopy(self.catalog)
                self.catalog["flows"][0][key]=value
                with self.assertRaises(ValueError):self.check()
                self.catalog=original

    def test_seven_complete_berlin_days_include_dst_not_fixed_168_hours(self):
        self.check()
        start=dt.datetime.fromisoformat(self.manifest["window"]["start"].replace("Z","+00:00"))
        end=dt.datetime.fromisoformat(self.manifest["window"]["end"].replace("Z","+00:00"))
        self.assertEqual((end-start).total_seconds()/3600,169)
        for field,value in (("timezone","UTC"),("end","2026-10-26T22:00:00Z")):
            with self.subTest(field=field):
                original=copy.deepcopy(self.manifest)
                self.manifest["window"][field]=value
                with self.assertRaises(ValueError):self.check()
                self.manifest=original

    def test_source_receipt_does_not_accept_ready_or_unknown_scope(self):
        for field,value in (("scope","production"),("rollout","ready")):
            original=copy.deepcopy(self.manifest)
            self.manifest[field]=value
            with self.assertRaises(ValueError):self.check()
            self.manifest=original


if __name__=="__main__":unittest.main()
