---
id: 006
title: Validate actionable usage reports and guarded rollout
status: pending
blocked-by: [002, 003, 004, 005, 007]
goal: privacy-preserving-product-analytics
allows-migrations: false
needs-review: none
review-required: eng
created: 2026-10-27
reviews:
  - type=eng verdict=approved date=2026-10-27 by=codex-formal-plan-review
---

## Plain-English Summary

Events are useful only when they produce reports we can interpret and trust. Prove the app-to-collector path with synthetic journeys, define a small operator view, and make unavailable measurements obvious. Prepare a reviewable rollout with evidence and rollback controls; real-traffic enablement uses the existing matching user authority only after the artifact, custody and independent acceptance gates pass.

**What changes in the code:** Add report definitions and end-to-end acceptance fixtures using the existing app test tools and an isolated approved collector. Produce a deployment checklist and evidence receipt tied to the exact source, tracker and collector versions. Use Umami's existing reports rather than building another dashboard in Parley.

## Requirements

Matthew should be able to see which app areas and ceremonies are used, which successful entry paths occur, and whether tracked browsers report creation problems, without interpreting approximate telemetry as exact people or meeting records.

**Acceptance criteria**

- [ ] The operator report catalog includes: pageview observations by fixed category; acknowledged workspace/invitation/join successes by event; acknowledged session-create observations by ceremony kind; vote/manual-reveal/first-standup-save/close observations; and creation-failure observations by the fixed categories. Each names schema version, time window/timezone, unit, repeated-action and missing-data caveats.
- [ ] None of these raw action-count views is labeled unique users/workspaces/meetings, exact completion/participation rate, or cohort conversion. No daily/weekly “retention of users” is inferred from anonymous rotating identifiers. No report combines host actions and participant actions into one person's required sequence.
- [ ] Conditional flow reports are separate same-browser journeys: homepage → workspace_created → session_created (host setup), invitation page → invitation_accepted → room_opened (invited browser, only when it actually opens a room), room_opened → poker_vote_saved, and room_opened → standup_participated. Paths that legitimately bypass a step are disclosed. The installed collector's supported filtering must distinguish kind where needed; otherwise omit that funnel, not guess.
- [ ] Flow reports require plan 005's `anonymous-flows` tier plus passing synthetic identity/ordering/window checks. Their window is explicitly 60 minutes between consecutive steps, verified against the installed version, not assumed to be 60 minutes for the whole journey. Session merging, rotation, duplicate contexts, out-of-order/repeated steps and entry that skips the homepage are tested/documented. If unsupported, ship raw-count reports and clearly mark flow conversion unavailable.
- [ ] A full isolated browser → the adapter from `web/src/lib/analytics.ts` → the gateway fallback defined in `deploy/scrum-pro-htz4/Caddyfile` → actual plan 007 relay → exact approved collector → accepted raw event/report readback passes with synthetic data. A 200 response or script download is insufficient; emitted and accepted records/counts must agree with the known script, including the expected one-document dedup cases and deliberately dropped events.
- [ ] Full outgoing bodies contain no fixture name, token, org/space/session/story identifier, query/hash, free text, raw error, estimate or vote value. DNT, opt-out before/after load, blocked tracker, offline send, repeated mounts, replayed WebSocket frames, and unapproved host/default-off release produce the expected absent events without blocking app behavior.
- [ ] Synthetic tests use an isolated site/collector, never production telemetry. Avoid a high-cardinality “test ID” dimension; isolate by test website scope and bounded test time. No public share links or copied credentials are created.
- [ ] A sanitized acceptance report states exact source commit, immutable app image and delivered `/parley` SHA256/startup fingerprint correspondence, canonical policy SHA256, relay interface schema, tracker hash/version, collector version/image, website scope, configured report tier, executed test commands, acceptance readback, limitations, pending authority and rollback procedure. Local validation is never reported as live deployment verification.
- [ ] Matthew authorized implementation/testing/merge/app deployment of this six-plan scope on2026-10-27 and accepted90-day raw retention; do not request the same approval again. Before real-traffic enablement, require a matching ready custody receipt from `scripts/check-analytics-readiness.py`, approved compatible artifact and independent final source/privacy review. Until those evidence gates pass, named events stay disabled. The existing scoped retention/backup-custody authority covers only the separately reviewed Homelab 228–231 artifacts and their gates; it does not permit unrelated infrastructure or identity widening. Missing operational custody leaves rollout blocked.
- [ ] Rollback disables all Scrum collection first and restores the reviewed previous app artifact/config; it does not delete historical analytics, reset a site, roll back the collector, or change unrelated services. Any future live smoke uses a bounded parent brief for matching synthetic actions, accepted readback and cleanup within the existing authority; genuinely new scope requires additional authority. The smoke confirms accepted readback under the same source/report identity.

## Design

Testing approach: browser-based

**Files expected to change:**

- `docs/analytics/reports.md`: useful question/report recipes, units, filters, windows, valid interpretations and unavailable metrics.
- `docs/verification/analytics-acceptance.md`: reproducible synthetic scenario matrix and sanitized receipt requirements; distinguish local, staging and authorized live evidence.
- Existing `web/src/lib/analytics*.test.ts` and relevant page tests: complete cross-flow fixtures and count/privacy assertions without adding an E2E framework dependency.
- `deploy/scrum-pro-htz4/README.md`, `site/src/content/docs/security/data-and-privacy.mdx`, relevant `VerifiedStamp`: rollout/disable gate, evidence state and actual retained-data limitations.

Use agent-browser for development QA per AGENTS.md. Reuse a version-matched isolated collector, approved tracker fixture and actual independently validated 007 relay; do not start a second app writer on the existing implementation checkout. Tests may need a synthetic authenticated app/database fixture; any Go/integration run requires a freshly built frontend, real `TEST_DATABASE_URL`, no skip opt-out and `go test -p 1`, per project policy. Do not claim the default health gate verifies collector ingestion.

Prefer saved report recipes and supported native Umami views; do not add a Parley analytics endpoint, public dashboard, scheduled digest, new analytics service, session recorder, new ID, or new dependency. Unknown installed UI/API features remain blocked/omitted rather than prompting an automatic shared-service upgrade.

### Relay artifact and operational acceptance ordering

Plan 007's reviewed specification is not an implementation receipt. Its current separate writer must finish independent validation and commit/integration before this plan consumes the actual relay/canonical policy artifacts. Preserve 002's loader/accessor/dedup fixes and 003/004 instrumentation; never edit that worker's dirty checkout. The acceptance matrix includes stripped native cache/identity, default-off/unapproved-host refusals, mismatched/stale admission, snapshot/deadline/maintenance handoff, and the absence of direct native/admin/DB bypass. Reuse actual 007/228 negative fixtures and prove their integrated path rather than duplicate a relay or policy.

Require a final acceptance receipt binding the actual delivered immutable image/executable and startup fingerprint, canonical policy, site, tracker and collector pins, independently reviewed 007 artifact and fresh 005 ready receipt. Human Version, a source commit or an environment digest is not `app_build`; two different binaries with the same Version must not share an acceptable runtime receipt. The 60-second runtime lease is separate from 005's 24-hour rollout-readiness receipt. Missing private mounting/image correspondence/drain/custody evidence blocks release even when local reports pass.

Use Homelab 231's privately installed staging/custody phase receipts to establish 005 before FINAL cutover, not a dependency on 231 status done. Local report definitions and synthetic fixtures can be explicitly briefed while live gates remain blocked; neither local acceptance nor a blocked 005 receipt completes production readiness. After fresh 005 readiness and final source/privacy acceptance, the designated operator uses existing matching authority for 231/app rollout and installed readback. Keep named collection/admission off until then. Rollback disables ALL Scrum collection and never reopens the retired shared target or exposes unreconciled copies. Keep actions-only unless the separate anonymous-flow tests actually pass.

**Out of scope:** automatic production deployment, real-person journey inspection, bulk historical data queries, unapproved dashboard changes, alert/digest messages, collector upgrades, inferred authoritative business counts, additional event expansion and Paperclip onboarding.

## Tasks

1. Define each action-count report and its decision; map every field to the approved contract and documented unit.
2. Build synthetic host, invited-browser, poker and standup scenarios with explicit expected event counts, losses and dedup behavior; add failing integration assertions before final wiring fixes.
3. Exercise the version-matched isolated collector through the gateway-equivalent path and read accepted records/reports back; inspect complete payloads and privacy exclusions.
4. Validate identity and ordered flow behavior; enable only the report tier supported by plan 005 and the synthetic evidence, recording unavailable metrics clearly.
5. Prepare the exact reviewed artifact/config, default-off or explicitly authorized enablement proposal, rollback steps and evidence receipt; obtain independent review.
6. Stop at the rollout gate while evidence is missing. Once all gates pass, the designated operator uses Matthew's already granted matching app-deployment authority for bounded rollout/readback, records the result and owns cleanup after integration and process exit; obtain additional authority only for genuinely new collector scope.

## Verification

The command below is an invocation template, not an executed readiness result. Populate every quoted `ANALYTICS_*` variable with the independently reviewed manifest value or private local receipt/proof-bundle path; the example contains no actual private path or artifact pin. For isolated synthetic checks use only a clearly labeled synthetic bundle. Operational invocations use the actual current clock with no `--now` override. Matching hash bytes alone do not verify producer contents or installed custody; retain the operator/different-reviewer evidence checks and all blocked/default-off gates.

- [cmd] `cd web && npm test -- src/lib/analyticsContract.test.ts src/lib/analytics.test.ts src/pages/Landing.test.tsx src/pages/SpacePage.test.tsx src/pages/InvitationPage.test.tsx src/pages/LinkPage.test.tsx src/pages/SessionPage.test.tsx src/pages/PokerRoom.test.tsx src/pages/StandupRoom.test.tsx`.
- [cmd] `cd web && npm run build && npm run lint`.
- [cmd] `python3 scripts/check-analytics-readiness.py --receipt "$ANALYTICS_READINESS_RECEIPT" --evidence-root "$ANALYTICS_EVIDENCE_ROOT" --collector-image "$ANALYTICS_COLLECTOR_IMAGE" --app-image "$ANALYTICS_APP_IMAGE" --app-build "$ANALYTICS_APP_BUILD" --contract-schema 1 --tracker-sha256 "$ANALYTICS_TRACKER_SHA256" --collector-version "$ANALYTICS_COLLECTOR_VERSION" --collector-build "$ANALYTICS_COLLECTOR_BUILD" --website-id "$ANALYTICS_WEBSITE_ID" --relay-interface-schema 1 --policy-sha256 "$ANALYTICS_POLICY_SHA256"` — accept only the source-compatible ready tier; preserve a failing gate as a blocker.
- [browse] `/` verify 'synthetic host setup through workspace/session creation yields exactly the expected coarse pages and acknowledged events in the isolated collector readback, with no fixture content or identities'.
- [browse] `/session/test-session` verify 'two browser contexts, reconnects, repeated frames, successful vote changes and manual/automatic reveals match the event definitions; opting out suppresses future sends while the meeting still works'.
- [manual] Compare native raw-count and conditional flow results with the synthetic oracle; include a flow with intermediate unrelated actions and a step delayed past the 60-minute window in a controlled test fixture. Reject unsupported/merged-identity conversion claims.
- [manual] Independent reviewer reads final source, full payload capture, collector readback and custody receipt; no implementation author's “done” or saved script-availability receipt substitutes for this check.
- [manual] Report `TEST_DATABASE_URL` set/unset and opt-out state for any actual Go checks. No Go build/test or production rollout is required merely to author these plans, and the checklist alone never supplies deployment authority. The existing matching user authorization is recorded above.

<!-- mstack:seam
produced:
- kind: file; name: docs/analytics/reports.md; file: docs/analytics/reports.md
- kind: file; name: docs/verification/analytics-acceptance.md; file: docs/verification/analytics-acceptance.md
assumed:
- from: 002; kind: file; name: web/src/lib/analytics.ts; file: web/src/lib/analytics.ts
- from: 007; kind: file; name: web/src/lib/analytics-policy.json; file: web/src/lib/analytics-policy.json
- from: 007; kind: file; name: internal/analyticsrelay/policy.generated.json; file: internal/analyticsrelay/policy.generated.json
- from: 007; kind: file; name: internal/analyticsrelay/relay.go; file: internal/analyticsrelay/relay.go
- from: 005; kind: file; name: docs/analytics/collector-readiness.md; file: docs/analytics/collector-readiness.md
- from: 005; kind: file; name: scripts/check-analytics-readiness.py; file: scripts/check-analytics-readiness.py
-->
