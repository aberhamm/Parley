---
id: 006
title: Validate actionable usage reports and guarded rollout
status: blocked
blocked-by: [003, 004, 005]
goal: privacy-preserving-product-analytics
allows-migrations: false
needs-review: eng
review-required: eng
created: 2026-10-27
---

## Plain-English Summary

Events are useful only when they produce reports we can interpret and trust. Prove the app-to-collector path with synthetic journeys, define a small operator view, and make unavailable measurements obvious. Prepare a reviewable rollout with evidence and rollback controls; real-traffic enablement still requires separate explicit authority.

**What changes in the code:** Add report definitions and end-to-end acceptance fixtures using the existing app test tools and an isolated approved collector. Produce a deployment checklist and evidence receipt tied to the exact source, tracker and collector versions. Use Umami's existing reports rather than building another dashboard in Parley.

## Requirements

Matthew should be able to see which app areas and ceremonies are used, which successful entry paths occur, and whether tracked browsers report creation problems, without interpreting approximate telemetry as exact people or meeting records.

**Acceptance criteria**

- [ ] The operator report catalog includes: pageview observations by fixed category; acknowledged workspace/invitation/join successes by event; acknowledged session-create observations by ceremony kind; vote/manual-reveal/first-standup-save/close observations; and creation-failure observations by the fixed categories. Each names schema version, time window/timezone, unit, repeated-action and missing-data caveats.
- [ ] None of these raw action-count views is labeled unique users/workspaces/meetings, exact completion/participation rate, or cohort conversion. No daily/weekly “retention of users” is inferred from anonymous rotating identifiers. No report combines host actions and participant actions into one person's required sequence.
- [ ] Conditional flow reports are separate same-browser journeys: homepage → workspace_created → session_created (host setup), invitation page → invitation_accepted → room_opened (invited browser, only when it actually opens a room), room_opened → poker_vote_saved, and room_opened → standup_participated. Paths that legitimately bypass a step are disclosed. The installed collector's supported filtering must distinguish kind where needed; otherwise omit that funnel, not guess.
- [ ] Flow reports require plan 005's `anonymous-flows` tier plus passing synthetic identity/ordering/window checks. Their window is explicitly 60 minutes between consecutive steps, verified against the installed version, not assumed to be 60 minutes for the whole journey. Session merging, rotation, duplicate contexts, out-of-order/repeated steps and entry that skips the homepage are tested/documented. If unsupported, ship raw-count reports and clearly mark flow conversion unavailable.
- [ ] A full isolated browser → existing app adapter → dedicated-gateway-equivalent route → exact approved collector → accepted raw event/report readback passes with synthetic data. A 200 response or script download is insufficient; emitted and accepted records/counts must agree with the known script, including the expected one-document dedup cases and deliberately dropped events.
- [ ] Full outgoing bodies contain no fixture name, token, org/space/session/story identifier, query/hash, free text, raw error, estimate or vote value. DNT, opt-out before/after load, blocked tracker, offline send, repeated mounts, replayed WebSocket frames, and unapproved host/default-off release produce the expected absent events without blocking app behavior.
- [ ] Synthetic tests use an isolated site/collector, never production telemetry. Avoid a high-cardinality “test ID” dimension; isolate by test website scope and bounded test time. No public share links or copied credentials are created.
- [ ] A sanitized acceptance report states exact source commit/build, tracker hash/version, collector version, website scope, configured report tier, executed test commands, acceptance readback, limitations, pending authority and rollback procedure. Local validation is never reported as live deployment verification.
- [ ] Before any real-traffic enablement, explicit current rollout authority, approved policy and ready custody receipt are required, plus independent final source/privacy review. Until then the implementation and checklist are local/reviewable and named events stay disabled. Missing access/approval leaves rollout blocked; do not mark production acceptance done or bypass gates.
- [ ] Rollback disables named events first and restores the reviewed previous app artifact/config; it does not delete historical analytics, reset a site, roll back the collector, or change unrelated services. Any future live smoke uses separately approved synthetic actions and confirms accepted readback under the same source/report identity.

## Design

Testing approach: browser-based

**Files expected to change:**

- `docs/analytics/reports.md`: useful question/report recipes, units, filters, windows, valid interpretations and unavailable metrics.
- `docs/verification/analytics-acceptance.md`: reproducible synthetic scenario matrix and sanitized receipt requirements; distinguish local, staging and authorized live evidence.
- Existing `web/src/lib/analytics*.test.ts` and relevant page tests: complete cross-flow fixtures and count/privacy assertions without adding an E2E framework dependency.
- `deploy/scrum-pro-htz4/README.md`, `site/src/content/docs/security/data-and-privacy.mdx`, relevant `VerifiedStamp`: rollout/disable gate, evidence state and actual retained-data limitations.

Use agent-browser for development QA per AGENTS.md. Reuse a version-matched isolated collector and the approved tracker fixture; do not start a second app writer on the existing implementation checkout. Tests may need a synthetic authenticated app/database fixture; any Go/integration run requires a freshly built frontend, real `TEST_DATABASE_URL`, no skip opt-out and `go test -p 1`, per project policy. Do not claim the default health gate verifies collector ingestion.

Prefer saved report recipes and supported native Umami views; do not add a Parley analytics endpoint, public dashboard, scheduled digest, new analytics service, session recorder, new ID, or new dependency. Unknown installed UI/API features remain blocked/omitted rather than prompting an automatic shared-service upgrade.

**Out of scope:** automatic production deployment, real-person journey inspection, bulk historical data queries, unapproved dashboard changes, alert/digest messages, collector upgrades, inferred authoritative business counts, additional event expansion and Paperclip onboarding.

## Tasks

1. Define each action-count report and its decision; map every field to the approved contract and documented unit.
2. Build synthetic host, invited-browser, poker and standup scenarios with explicit expected event counts, losses and dedup behavior; add failing integration assertions before final wiring fixes.
3. Exercise the version-matched isolated collector through the gateway-equivalent path and read accepted records/reports back; inspect complete payloads and privacy exclusions.
4. Validate identity and ordered flow behavior; enable only the report tier supported by plan 005 and the synthetic evidence, recording unavailable metrics clearly.
5. Prepare the exact reviewed artifact/config, default-off or explicitly authorized enablement proposal, rollback steps and evidence receipt; obtain independent review.
6. Stop at the rollout gate without separate current authority. If later authority is granted, the existing designated operator performs the bounded rollout and readback, records the result, and owns cleanup after integration and process exit.

## Verification

- [cmd] `cd web && npm test -- src/lib/analyticsContract.test.ts src/lib/analytics.test.ts src/pages/Landing.test.tsx src/pages/SpacePage.test.tsx src/pages/InvitationPage.test.tsx src/pages/LinkPage.test.tsx src/pages/SessionPage.test.tsx src/pages/PokerRoom.test.tsx src/pages/StandupRoom.test.tsx`.
- [cmd] `cd web && npm run build && npm run lint`.
- [cmd] `python3 scripts/check-analytics-readiness.py --receipt "$ANALYTICS_READINESS_RECEIPT"` — accept only the source-compatible ready tier; preserve a failing gate as a blocker.
- [browse] `/` verify 'synthetic host setup through workspace/session creation yields exactly the expected coarse pages and acknowledged events in the isolated collector readback, with no fixture content or identities'.
- [browse] `/session/test-session` verify 'two browser contexts, reconnects, repeated frames, successful vote changes and manual/automatic reveals match the event definitions; opting out suppresses future sends while the meeting still works'.
- [manual] Compare native raw-count and conditional flow results with the synthetic oracle; include a flow with intermediate unrelated actions and a step delayed past the 60-minute window in a controlled test fixture. Reject unsupported/merged-identity conversion claims.
- [manual] Independent reviewer reads final source, full payload capture, collector readback and custody receipt; no implementation author's “done” or saved script-availability receipt substitutes for this check.
- [manual] Report `TEST_DATABASE_URL` set/unset and opt-out state for any actual Go checks. No Go build/test or production rollout is required merely to author these plans, and no deployment is authorized by this checklist.
