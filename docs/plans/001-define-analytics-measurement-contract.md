---
id: 001
title: Define the analytics measurement and privacy contract
status: blocked
blocked-by: []
goal: privacy-preserving-product-analytics
allows-migrations: false
needs-review: ceo,eng
review-required: ceo,eng
created: 2026-10-27
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
- [ ] Local contract/projection work can finish with an unavailable collector receipt, but version-specific transport acceptance, identity-based reports, and production readiness remain blocked until the appropriate owner supplies evidence. Neither plan 001 nor plan 006 depends on a future report existing to establish this baseline.
- [ ] No user IDs, hashed IDs, distinct IDs, real-IP forwarding change, cookies, new fingerprint, session replay, heatmap, autocapture, or persistent event queue is proposed. Existing Umami-derived anonymous identifiers are a collector property, not proof of anonymity or accurate people counts.
- [ ] Privacy/retention decisions are visibly proposed, not approved by writing this plan: recommend 90 days of raw Scrum Pro analytics, restricted operator access, and documented backup expiry/restore reconciliation. Current app backup/log policies do not establish analytics retention. Human acceptance and collector-owner evidence are production activation gates.

## Design

Testing approach: unit-only

**Files expected to change:**

- `docs/analytics/measurement-contract.md`: catalog, measurement matrix, data flow, evidence gaps, rollout gates, and official-reference/version notes.
- `web/src/lib/analyticsContract.ts`: closed event/property types plus pure event and route projection functions; no script loading, network, storage, or React.
- `web/src/lib/analyticsContract.test.ts`: catalog/route fixtures and adversarial red-first projection tests.
- `docs/security/control-register.csv`: affected P-03 projection, P-06 outbound scope, P-10 operator exposure, and P-11 retention references, without promoting evidence status merely because tests exist.

| Event | Fixed optional properties | Meaning; implementation owner |
| --- | --- | --- |
| `workspace_created` | none | Initiating browser receives successful workspace-create response; 003 |
| `workspace_joined` | none | Initiating browser receives successful explicit workspace-join response; 003 |
| `invitation_accepted` | none | Initiating browser receives successful invitation-accept response; 003 |
| `guest_link_redeemed` | none | Initiating browser receives successful signed-link redemption; 003 |
| `session_created` | `kind`: `poker`, `standup`, `other` | Initiating browser receives successful session-create response; 003 |
| `creation_failed` | required `flow`: `workspace_create`, `session_create`; required `category`: `rejected`, `outcome_unknown` | Explicit HTTP non-success versus lost/ambiguous response; separate failure observations, not authoritative server failure; 003 |
| `room_opened` | required `kind`: `poker`, `standup`, `other` | First authorized readable room in the current document/room mount; 004 |
| `poker_vote_saved` | none | Initiating browser receives success for its vote write; repeated successful changes count; 004 |
| `poker_reveal_requested` | none | Initiating browser receives success for manual reveal request; not proof of a new unique reveal, and excludes auto-reveal; 004 |
| `standup_participated` | none | First successful locally initiated standup save during this document/room mount; not every autosave or distinct person; 004 |
| `session_closed` | required `kind`: `poker`, `standup`, `other` | Initiating browser receives success for close request; not deletion or observed global completion; 004 |

Use fixed schema value `1` in emitted event data so later reports can separate incompatible semantics. No arbitrary release hash, local identifiers, or synthetic marker enters the contract. Unknown names/keys/enum values reject the whole event. Build output is never hand-edited.

The gateway currently strips forwarded headers and retains User-Agent (`deploy/scrum-pro-htz4/Caddyfile`). Official Umami documentation describes anonymous session generation using website, IP, User-Agent, and a rotating salt. This makes shared proxy identity a testable risk: two otherwise independent browsers can be merged. Preserve the current header boundary; failed separation downgrades reporting to raw counts. Do not quietly introduce identity collection to make a funnel work.

Current source baseline: `179022c57764fc6b886a7ba8c178a2dbdad05edc`. `web/public/analytics.js` rejects all named events and maps actual `/o/...` and `/session/...` routes to `/other`; `web/src/App.tsx` is the route authority. Saved deployment docs establish script availability, not successful ingestion or accurate sessions. Before runtime implementation, locate the required existing scoped issue or ask for one under CONTRIBUTING; this plan does not open an external issue.

References checked 2026-10-27; implementation must compare them with the installed version: [tracker functions](https://docs.umami.is/docs/tracker-functions), [tracker configuration](https://docs.umami.is/docs/tracker-configuration), [anonymous session model](https://docs.umami.is/docs/sessions), [funnel semantics](https://docs.umami.is/docs/funnel), [self-hosted retention](https://docs.umami.is/docs/faq). Modern docs describe features absent from older versions; do not infer deployment support from a current documentation page.

**Out of scope:** runtime collection, collector upgrades, server counters, generic API/hub instrumentation, production access beyond separately authorized read-only evidence, dashboard changes, historical backfill, new dependencies/schema, and legal/compliance certification.

## Tasks

1. Review current source and the relevant privacy/security references; locate the scoped issue and resolve the baseline receipt owner without contacting a Claude-owned session.
2. Write the question-to-metric matrix, v1 event table, page categories, payload exclusions, and count/identity/coverage limitations.
3. Obtain only already authorized collector facts or record exact unavailable facts and their owner; keep secret configuration and raw user records out of the receipt.
4. Add red-first projection tests for real routes, hostile IDs/tokens/content, unknown events/properties, and enum widening; implement the pure typed contract.
5. Record the proposed retention/access policy and separate human/collector-owner acceptance gates; update only affected evidence references.
6. Have an independent reviewer check that every catalog signal answers a named question and cannot escape the projection; retain both findings and unresolved decisions.

## Verification

Checks below are future implementation checks, not checks performed while authoring these plans.

- [cmd] `cd web && npm test -- src/lib/analyticsContract.test.ts` — observe failures before adding the projection, then green; include actual router paths, locale/encoding/unknown paths, invitation fragments, raw query/title/referrer, nested data, forged schema, and identifiers in every rejected field.
- [cmd] `cd web && npm run build && npm run lint` — use existing tooling and name existing warnings honestly.
- [manual] Review the metric matrix and baseline receipt against exact source/version; explicitly reject claims of unique people, meeting completion, long-term user retention, or cohort conversion without supporting evidence.
- [manual] Preserve missing collector authority/version/retention decisions as blockers for the appropriate downstream gates; no production read or write is authorized just by passing this plan.
