---
id: 001
title: Define the analytics measurement and privacy contract
status: done
blocked-by: []
goal: privacy-preserving-product-analytics
allows-migrations: false
needs-review: none
review-required: ceo,eng
created: 2026-10-27
completed: 2026-10-27
reviewed: false
qa: automated
reviews:
  - type=ceo verdict=approved date=2026-10-27 by=codex-formal-plan-review
  - type=eng verdict=approved date=2026-10-27 by=codex-formal-plan-review
  - type=code verdict=pass date=2026-10-27 by=mstack-code-review
---

## Plain-English Summary

Umami is installed, but the current data cannot explain which parts of Scrum Pro are useful or where people encounter friction. Before collecting more, define the questions, the smallest useful signals, and the limits of what those signals mean. This establishes a reviewed contract and tests without enabling additional collection.

**What changes in the code:** Add a small typed catalog and a pure projection that accepts only approved event names and fixed property values. Document the measurement definitions and evidence needed to trust the collector. The runtime integration follows in plan 002.

## Requirements

Matthew needs aggregate evidence for decisions about onboarding, planning poker, and standups, without recording meeting content or identifying individual people or teams.

**Acceptance criteria**

- [ ] `docs/analytics/measurement-contract.md` answers these questions: which page categories are visited; which workspace/invitation/join flows succeed; which ceremony kinds are created; whether browsers participate in poker/standups; whether creation failures are reported; and which observed browser flows reach their next step.
- [ ] Every proposed report names its unit, numerator, denominator if any, time window/timezone, source event, repeated-action rule, and known blind spots. Default reports are raw observed action counts. Totals divided by totals are never described as cohort conversion, completion rate, unique people, unique workspaces, or unique meetings.
- [ ] The initial event catalog is exactly the table below. Properties are closed enums; no unknown key, arbitrary string, nested object, exception, body, count, timestamp, identity, title, slug, token, URL, vote value, standup text, or plugin kind name can enter a payload.
- [ ] Page categories are a fixed set matched to real router templates, with identifiers discarded before sending: `/`, `/directory`, `/workspace`, `/workspace-settings`, `/session`, `/present`, `/invite`, `/link`, `/other`. Authentication, API, embedded/meeting-client, plugin-frame, catalog, and org-admin routes are excluded in v1. Unknown routes map to `/other`, never a partial raw path.
- [ ] A bounded authorized read-only collector-baseline receipt identifies the installed Umami version/build, website, proxy chain, owner, supported tracker interfaces, anonymous identification behavior, access/retention knowledge, and evidence date. Unknown facts remain explicitly unknown. Access unavailable means a named blocker, not a guessed version or fabricated live validation.
- [ ] Local contract/projection work can finish using a blocked collector-baseline receipt; version-specific transport acceptance, identity-based reports, and production readiness remain gated by the separate evidence required in `docs/analytics/measurement-contract.md`. Plans 001 and 006 do not require a future report to establish this baseline.
- [ ] No user IDs, hashed IDs, distinct IDs, real-IP forwarding change, cookies, new fingerprint, session replay, heatmap, autocapture, or persistent event queue is proposed. Umami-derived anonymous identifiers are a collector property, not proof of anonymity or accurate people counts.
- [ ] Matthew explicitly accepted 90 days of raw Scrum Pro analytics on 2026-10-27. Record that accepted policy without asking again, with restricted operator access and documented backup expiry/restore reconciliation. The app policies in `docs/privacy-operations.md` do not establish analytics retention; proof of the collector mechanism and backup/restore custody remains a production gate. No approved retention mechanism is claimed by this plan.

## Design

Testing approach: unit-only

**Files expected to change:**

- `docs/analytics/measurement-contract.md`: catalog, measurement matrix, data flow, evidence gaps, rollout gates, and official-reference/version notes.
- `web/src/lib/analyticsContract.ts`: create closed event/property types, `projectAnalyticsEvent(name, data)` and `analyticsPageCategory(pathname)` pure projections; no script loading, network, storage, or React. The event projection returns an approved event or null, and the route projection a fixed category or null for excluded routes.
- `web/src/lib/analyticsContract.test.ts`: catalog/route fixtures and adversarial red-first projection tests.
- `docs/security/control-register.csv`: affected P-03 projection, P-06 outbound scope, P-10 operator exposure, and P-11 retention references, without promoting evidence status merely because tests exist.

| Event | Allowed properties (required where stated) | Meaning; implementation owner |
| --- | --- | --- |
| `workspace_created` | none | Initiating browser receives successful workspace-create response; 003 |
| `workspace_joined` | none | Initiating browser receives successful explicit workspace-join response; 003 |
| `invitation_accepted` | none | Initiating browser receives successful invitation-accept response; 003 |
| `guest_link_redeemed` | none | Initiating browser receives successful signed-link redemption; 003 |
| `session_created` | required `kind`: `poker`, `standup`, `other` | Initiating browser receives successful session-create response; 003 |
| `creation_failed` | required `flow`: `workspace_create`, `session_create`; required `category`: `rejected`, `outcome_unknown` | Explicit HTTP non-success versus lost/ambiguous response; separate failure observations, not authoritative server failure; 003 |
| `room_opened` | required `kind`: `poker`, `standup`, `other` | First authorized readable room in the current document/room mount; 004 |
| `poker_vote_saved` | none | Initiating browser receives success for its vote write; repeated successful changes count; 004 |
| `poker_reveal_requested` | none | Initiating browser receives success for manual reveal request; not proof of a new unique reveal, and excludes auto-reveal; 004 |
| `standup_participated` | none | First successful locally initiated standup save during this document/room mount; not every autosave or distinct person; 004 |
| `session_closed` | required `kind`: `poker`, `standup`, `other` | Initiating browser receives success for close request; not deletion or observed global completion; 004 |

Use required fixed numeric `schema: 1` in emitted event data so later reports can separate incompatible semantics. No arbitrary release hash, local identifiers, or synthetic marker enters the contract. Unknown names/keys/enum values reject the whole event. Build output is never hand-edited.

The gateway currently strips forwarded headers and retains User-Agent (`deploy/scrum-pro-htz4/Caddyfile`). Official Umami documentation describes anonymous session generation using website, IP, User-Agent, and a rotating salt. This makes shared proxy identity a testable risk: two otherwise independent browsers can be merged. Preserve the current header boundary; failed separation downgrades reporting to raw counts. Do not quietly introduce identity collection to make a funnel work.

Current source baseline: `179022c57764fc6b886a7ba8c178a2dbdad05edc`. `web/public/analytics.js` rejects all named events and maps actual `/o/...` and `/session/...` routes to `/other`; `web/src/App.tsx` is the route authority. Saved deployment docs establish script availability, not successful ingestion or accurate sessions. Before runtime implementation, satisfy the scoped issue requirement under CONTRIBUTING or record Matthew's explicit exception; this plan does not open an external issue.

References checked 2026-10-27; implementation must compare them with the installed version: [tracker functions](https://docs.umami.is/docs/tracker-functions), [tracker configuration](https://docs.umami.is/docs/tracker-configuration), [anonymous session model](https://docs.umami.is/docs/sessions), [funnel semantics](https://docs.umami.is/docs/funnel), [self-hosted retention](https://docs.umami.is/docs/faq). Modern docs describe features absent from older versions; do not infer deployment support from a current documentation page.

**Out of scope:** runtime collection, collector upgrades, server counters, generic API/hub instrumentation, production access beyond separately authorized read-only evidence, dashboard changes, historical backfill, new dependencies/schema, and legal/compliance certification.

### Collector baseline refreshed during plan review

The private scout receipt `/Users/matthew/.local/share/scrum-analytics-20261027/collector-readiness.md` (2026-10-27T10:08:38Z) identifies deployed Umami 3.0.3 and tracker SHA256 `a1471487eb3e8eb93b1a9e056386019ff5eedadea29bbb725b5494fb2e9ad90a`. Source supports named events and before-send. Local projection work uses an actions-only reporting target; ingestion remains unverified and anonymous flows unavailable pending isolated accepted-record and identity experiments. No API-supported rolling date-range purge was found; whole-site reset is not retention. The collector and full-database backups belong to the Homelab/Umami operator, with effective backup access and restore-time expiry reconciliation unverified. These block expanded production collection under 005/006, not local implementation/testing of 001–004. Preserve the existing proxy header boundary and do not upgrade the collector.

<!-- mstack:seam
produced:
- kind: file; name: docs/analytics/measurement-contract.md; file: docs/analytics/measurement-contract.md
- kind: file; name: web/src/lib/analyticsContract.ts; file: web/src/lib/analyticsContract.ts
- kind: symbol; name: analyticsPageCategory; file: web/src/lib/analyticsContract.ts
- kind: symbol; name: projectAnalyticsEvent; file: web/src/lib/analyticsContract.ts
assumed:
-->

## Tasks

1. Review source and the privacy/security references; use Matthew's explicit reviewed-plan tracking exception below and resolve the baseline receipt owner without contacting a Claude-owned session.
2. Write the question-to-metric matrix, v1 event table, page categories, payload exclusions, and count/identity/coverage limitations.
3. Obtain only already authorized collector facts or record exact unavailable facts and their owner; keep secret configuration and raw user records out of the receipt.
4. Add red-first projection tests for real routes, hostile IDs/tokens/content, unknown events/properties, and enum widening; implement the pure typed contract.
5. Record Matthew's accepted 90-day raw-retention decision and the separate unresolved mechanism/access/backup custody gates; update only affected evidence references.
6. Have an independent reviewer check that every catalog signal answers a named question and cannot escape the projection; retain both findings and unresolved decisions.

## Verification

Checks below are future implementation checks, not checks performed while authoring these plans.

- [cmd] `cd web && npm test -- src/lib/analyticsContract.test.ts` — observe failures before adding the projection, then green; include actual router paths, locale/encoding/unknown paths, invitation fragments, raw query/title/referrer, nested data, forged schema, and identifiers in every rejected field.
- [cmd] `cd web && npm run build && npm run lint` — use existing tooling and name existing warnings honestly.
- [manual] Review the metric matrix and baseline receipt against exact source/version; explicitly reject claims of unique people, meeting completion, long-term user retention, or cohort conversion without supporting evidence.
- [manual] Preserve missing collector authority/version/retention decisions as blockers for the appropriate downstream gates; no production read or write is authorized just by passing this plan.

### Execution authorization recorded 2026-10-27

Matthew explicitly directed: “Use the reviewed plans instead of an issue, and proceed with the scoped Scrum Pro analytics retention and backup-custody work. Delegate implementation and independent validation, then merge and deploy once the checks pass.” The six reviewed plans replace the issue requirement for this work only; no upstream/fork issue or repository setting is needed. The accepted raw Umami retention is90days. This plan001 invocation is limited to the pure measurement contract and local tests, with no runtime sends or collector changes. Parent owns later integration/deployment after independent evidence; no new approval round is implied for the already authorized scope.

## Implementation Notes

Implemented the pure typed measurement contract, finite event/property projection and real-route categories without enabling collection. Added the metric/privacy contract and scoped security-register references; evidence statuses remain unchanged. Red-first behavioral, encoded-path and revoked-proxy failures were observed, followed by 54 passing tests. Frontend build and full lint passed (existing lint warnings remain). Actual scoped native health is PASS8.9, with unchanged SHELL4/FAILURES:shell; this is not release-wide all-green evidence. TEST_DATABASE_URL was unset/unused; no Go/database checks ran.

Different independent Codex validator /root/analytics_validator executed the 54 tests, build, full lint and diff check, then applied named mstack-code-review with zero findings. Its actual structured artifact was copied to the native review cache and mapped through code_verdict_from_findings; the native code gate records pass. Evidence: /Users/matthew/.local/share/scrum-analytics-20261027/plan001/INDEPENDENT-VALIDATION.md and COMPLETION-REPORT.md. Accepted90-day policy and reviewed-plan tracking exception remain distinct from unresolved downstream collector mechanisms. No runtime sends, collector changes, plan002 work, push, merge or deployment occurred.

**Files changed:**

- `docs/security/control-register.csv` (modified)
- `docs/analytics/measurement-contract.md` (created)
- `web/src/lib/analyticsContract.ts` (created)
- `web/src/lib/analyticsContract.test.ts` (created)
- `docs/plans/001-define-analytics-measurement-contract.md` (completion bookkeeping)

**Commit:** `7d06679` — `feat(web): define the analytics measurement contract` (implementation commit before same-iteration hash backfill)
