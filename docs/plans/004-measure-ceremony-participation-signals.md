---
id: 004
title: Measure browser-observed ceremony participation
status: in-progress
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

Opening a meeting is different from participating in it. Record a few meaningful poker and standup actions so we can see which features tracked browsers actually use. Avoid counting every autosave or every live update received by everyone in the room.

**What changes in the code:** Instrument successful locally initiated writes in the existing ceremony components, and add one room-open observation after authorized data is available. Deduplicate only the observations whose definition is once per current document/room mount, keeping any local guard data out of the payload.

## Requirements

Matthew needs browser-observed participation signals, with clear distinctions between action counts, document observations, and actual meeting outcomes.

**Acceptance criteria**

- [ ] `room_opened` emits after the first authorized readable room plus resolved identity in the current document/room mount, normalized by `kind=poker|standup|other`. Loading/error/forbidden pages, guest identity recovery prompts, refreshes/reconnects, subsequent frames, and rerenders do not create additional observations within that mount. The lifecycle originates in `web/src/pages/SessionPage.tsx`.
- [ ] `poker_vote_saved` emits only after the initiating browser's vote write succeeds, after the optimistic UI's failure path is excluded. No card value, round/story/session identity, participant name, count, or estimate is sent. Successful vote changes count as additional actions, not additional people.
- [ ] `poker_reveal_requested` emits for successful explicit manual-reveal requests only. Auto-reveal, replayed frames, another facilitator's action, and merely rendering a revealed room do not emit. Acknowledged idempotent repeats are not advertised as unique revealed rounds.
- [ ] `standup_participated` emits for the first successful locally initiated standup save per current document/room mount, not every 800ms autosave. Failed saves and seed/server entries do not count. Later edits and flushes in the same mount do not duplicate it. Empty-but-successful saves follow this definition; do not inspect/send text or infer completion from content.
- [ ] `session_closed` emits only after the initiating browser receives success for the close action, with normalized kind; it is not session/workspace deletion. Standup flush failure prevents close and its analytics success. Broadcasts, scheduled expiry, other browsers, and loaded ended rooms do not emit.
- [ ] Memory-only guards are bounded to one mounted room; no persistent identifier, unbounded cross-room set, arbitrary payload key, new server ID, or analytics identifier is stored/sent. Reload/remount/multiple tabs may duplicate room/standup observations and must be disclosed.
- [ ] No event is emitted by `useSession`/socket message handling, generic API/action helpers, React render, server hub, or plugin frame. Analytics failures/opt-out cannot affect autosave sequencing, vote secrecy, websocket behavior, or close guards.
- [ ] Source/tests and measurement docs explicitly say that automatic/scheduled actions, blocked tracking, other devices, reloads and retries make this unsuitable for exact people, rounds, meetings, or completion rates.

## Design

Testing approach: browser-based

**Files expected to change:**

- `web/src/pages/SessionPage.test.tsx`: extend authorized observation/reconnect/remount tests.
- `web/src/pages/SessionPage.tsx`: authorized once-per-mount room observation, without instrumenting shared query/socket internals.
- `web/src/pages/PokerRoom.test.tsx`: extend vote/reveal/close and successful-retry observations.
- `web/src/pages/PokerRoom.tsx`: vote and manual reveal acknowledged success; find the existing close control and instrument only its explicit successful callback.
- `web/src/pages/StandupRoom.test.tsx`: extend first-save/flush/failed-close observations.
- `web/src/pages/StandupRoom.tsx`: first successful awaited action in `useOwnEntryDraft`'s `send` closure, with a mount-local guard, and successful `endStandup` after `flush`.
- The existing close control's component/test if outside those files: inspect before editing; do not infer closure from envelope transitions.
- `docs/analytics/measurement-contract.md`, `site/src/content/docs/security/data-and-privacy.mdx`: signal semantics and disclosure/stamp references.

Pass only a literal event and normalized enum to the adapter. A component may use its already-held room identity to reset a local guard when the mounted room changes, but must never pass that identity to analytics. Prefer the existing component lifecycle to adding any general event bus or analytics service. Put the action plus post-success telemetry inside any callback retained for user retry, so a successful retry follows the same observation rule; `PokerRoom.run` can otherwise retry the bare action without analytics. A failure from analytics is swallowed inside the adapter and cannot change action success.

Deduplication is best effort within one document, not exactly-once delivery. Do not persist a queue or duplicate-key ledger.

**Out of scope:** authoritative meeting aggregates, exact participation rate per room, votes/standup content, quality/scoring of people, automatic reveal/scheduler instrumentation, replay/heatmaps, plugins, downloads, and production enablement.

## Tasks

1. Add red-first tests for acknowledged vote/manual reveal, denied/failed writes, and authorized room-open observation.
2. Add explicit nonblocking poker success calls while preserving optimistic rollback and existing retry semantics.
3. Add first-success standup observation and close-success calls; prove autosave/flush/failed-close ordering stays intact.
4. Test initial ended data, guest views, multiple live recipients, reconnects, rerenders, room remounts, and analytics failure/opt-out.
5. Exercise two local synthetic browsers with an intercepted tracker and document expected events from the initiator only; update measurement limitations and obtain independent review.

## Verification

- [cmd] `cd web && npm test -- src/pages/SessionPage.test.tsx src/pages/PokerRoom.test.tsx src/pages/StandupRoom.test.tsx` — observe missing-event tests fail before implementation; include failed optimistic vote then successful user retry, auto-reveal no-event, repeated frames, multiple autosaves, rejected flush and close, StrictMode/remount behavior, and disabled/throwing adapter.
- [cmd] `cd web && npm run build && npm run lint`.
- [browse] `/session/test-session` verify 'two synthetic browser participants receive live updates, but only the browser performing an acknowledged vote emits poker_vote_saved; the payload contains no vote or room/story/user identity'.
- [browse] `/session/test-standup` verify 'several successful autosaves produce one standup_participated observation for this document; a failed flush prevents session_closed'. Use agent-browser and a local intercepted collector.
- [manual] Review full payloads and event counts against the exact scripted action sequence; document remount/duplicate/network-loss limits and preserve the privacy/guest boundaries.

<!-- mstack:seam
produced:
assumed:
- from: 001; kind: file; name: web/src/lib/analyticsContract.ts; file: web/src/lib/analyticsContract.ts
- from: 002; kind: symbol; name: trackAnalyticsEvent; file: web/src/lib/analytics.ts
-->
