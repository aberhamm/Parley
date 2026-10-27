---
id: 003
title: Measure browser-observed entry and activation outcomes
status: pending
blocked-by: [001, 002]
goal: privacy-preserving-product-analytics
allows-migrations: false
needs-review: none
review-required: eng
created: 2026-10-27
reviews:
  - type=eng verdict=approved date=2026-10-27 by=codex-formal-plan-review
---

## Plain-English Summary

Page visits do not show whether someone successfully joins a workspace, accepts an invitation, or creates a meeting. Add a small set of signals at those successful actions, plus carefully classified workspace/session creation failures. This answers concrete activation questions without inspecting form contents or turning every click into an event.

**What changes in the code:** Add explicit calls at the initiating page's existing successful response callbacks. Use the reviewed adapter and enum catalog; keep analytics separate from fetching, navigation, and error presentation.

## Requirements

Matthew needs to distinguish successful entry paths and meeting creation by kind, and see whether browsers report creation friction. These observations cover only tracked browsers that receive a response, not all server actions.

**Acceptance criteria**

- [ ] `workspace_created`, `workspace_joined`, `invitation_accepted`, and `guest_link_redeemed` emit only after the corresponding initiating write returns success, using the exact plan 001 definitions. Page loads, cached memberships, invitation previews, existing membership reads, and restored identity do not emit these success events.
- [ ] `session_created` emits only after successful explicit UI creation and sends only normalized `kind=poker|standup|other`. Plugin-specific identifiers, configuration/mode/title, schedule, token, org/space/session IDs, and response objects never enter analytics.
- [ ] `creation_failed` is limited to workspace/session creation callbacks: `rejected` only for an explicit HTTP non-success, `outcome_unknown` for transport/response ambiguity where the server might have succeeded. Do not infer a precise validation reason or send exception text. Local validation, other forms, joins, invitation/link failures, and background requests produce no v1 error event.
- [ ] Each executed callback emits at most once; rerender, StrictMode, cache invalidation, and navigation do not duplicate it. A user's successful repeat/retry is a separate observed action. No analytics-level retry, persistent dedup key, or room/person identifier is introduced. Classify only the awaited write: navigation/cache/UI exceptions after an acknowledged creation cannot emit creation_failed or erase its success observation.
- [ ] Lost success responses are explicitly documented as unobserved success, even if a subsequent retry succeeds. These counts are not paired attempt outcomes and cannot establish exact success/failure conversion or authoritative creations.
- [ ] Throwing/unavailable analytics, disabled named events, DNT, and opt-out do not alter error messages, disabled-state behavior, one-time token consumption, navigation, or success results in `web/src/pages/InvitationPage.tsx` and `web/src/pages/LinkPage.tsx`.
- [ ] Tests use guest/account/denied paths without new permissions or routes. The boundaries covered by `internal/api/link_routes_test.go`, `internal/api/org_routes_test.go` and `internal/api/embed_routes_test.go` remain unchanged; embedded sessions stay uninstrumented.
- [ ] The measurement documentation maps each event to its callback, source test, repeated-action semantics, and known omissions; no claim of real-traffic collection before 006 acceptance.

## Design

Testing approach: browser-based

**Files expected to change:**

- `web/src/pages/Landing.test.tsx`: extend outcome and post-success navigation-failure tests.
- `web/src/pages/Landing.tsx`: workspace-create success and creation failure at `doCreate`'s actual write boundary.
- `web/src/pages/SpacePage.test.tsx`: extend join/create outcome and duplicate-callback tests.
- `web/src/pages/SpacePage.tsx`: explicit workspace join and create-session submit outcomes.
- `web/src/pages/InvitationPage.test.tsx`: extend success/preview/no-leak tests.
- `web/src/pages/InvitationPage.tsx`: invitation acceptance after successful redemption, not preview or authentication prompt.
- `web/src/pages/LinkPage.test.tsx`: extend redemption and credential-exclusion tests.
- `web/src/pages/LinkPage.tsx`: signed-link success without passing token, name, redemption body, or receipt.
- `docs/analytics/measurement-contract.md`, `site/src/content/docs/security/data-and-privacy.mdx`: event coverage and accurate disclosures/stamps.

Do not instrument the generic `api()` or `action()` helper: URLs/bodies would widen the data boundary and background calls would distort meaning. Site events are sent only through plan 002's adapter. Callers pass literal enum values and no body/response reference. Tests should assert exactly what leaves the projection, not merely spy on a function with the same implementation.

An explicit workspace join may be a repeat for an existing member; its signal is an acknowledged join action, not a newly acquired unique member. Invitation acceptance and signed-link redemption are separate paths, not sequential stages in one funnel. Scheduled session creation is intentionally not observed by this browser-only plan.

**Out of scope:** signup attribution, persistent user/session identifiers, all form validation errors, server-side counters, invitation-token diagnostics, auto-scheduled sessions, plugin analytics, exports, and production collection activation.

## Tasks

1. Add failing success/no-success tests at the five initiating callbacks with synthetic account and guest data, plus the two creation-failure categories.
2. Add the explicit nonblocking event calls and normalized ceremony kind after response success; keep data objects outside analytics calls.
3. Prove that retries, rerenders, invalid forms, invitation previews, and denied writes do not fabricate successes; preserve token and busy guards.
4. Exercise the complete local create/join/invite/link flows through an intercepted synthetic tracker and inspect event payloads for fixture secrets.
5. Update the source-to-event documentation and collect independent review before marking the plan complete.

## Verification

- [cmd] `cd web && npm test -- src/pages/Landing.test.tsx src/pages/SpacePage.test.tsx src/pages/InvitationPage.test.tsx src/pages/LinkPage.test.tsx` — tests seen failing before instrumentation; exercise explicit errors, ambiguous response loss, successful retry, navigation throwing after a successful write, duplicate callback/rerender protection, and disabled/throwing adapter.
- [cmd] `cd web && npm run build && npm run lint`.
- [browse] `/invite` verify 'a synthetic successful acceptance emits invitation_accepted once; preview, missing/invalid token and sign-in prompt do not; no token, name or workspace address appears in telemetry'.
- [browse] `/o/test-org/s/test-space` verify 'an explicit join and successful session creation emit their separate events; a rejected create emits creation_failed without title or error body'. Use agent-browser against local synthetic fixtures and an intercepted collector.
- [manual] Inspect full captured tracker requests, including default tracker metadata, not just the event-name spy. Compare emitted totals to the scripted callback expectations; label them observed actions, not users or meetings.

<!-- mstack:seam
produced:
assumed:
- from: 001; kind: file; name: web/src/lib/analyticsContract.ts; file: web/src/lib/analyticsContract.ts
- from: 002; kind: symbol; name: trackAnalyticsEvent; file: web/src/lib/analytics.ts
-->
