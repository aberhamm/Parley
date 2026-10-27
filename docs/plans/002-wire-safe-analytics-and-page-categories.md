---
id: 002
title: Wire safe analytics and correct page categories
status: blocked
blocked-by: [001]
goal: privacy-preserving-product-analytics
allows-migrations: false
needs-review: design
review-required: eng,design
created: 2026-10-27
reviews:
  - type=eng verdict=approved date=2026-10-27 by=codex-formal-plan-review
---

## Plain-English Summary

Workspace and meeting pages currently appear together as “other,” so even basic navigation is misleading. Replace the current bootstrap with one tested path that categorizes pages correctly, permits only reviewed signals, and gives users a visible local analytics choice. Tracking failures must never prevent someone from joining or running a meeting.

**What changes in the code:** Connect the pure contract to the existing Umami script through one small browser adapter. Move initialization into the application bundle so the page and event paths share the same projection, and replace the old bootstrap without running both. Add an accessible local opt-out that takes effect for later sends immediately.

## Requirements

The deployment operator needs reliable coarse page categories; app users need to understand and control optional usage analytics without sending names, content, or addresses.

**Acceptance criteria**

- [ ] The app initializes analytics once from `main.tsx`, using the reviewed contract. Remove the old `web/index.html` script tag and obsolete `web/public/analytics.js` only after equivalent domain/DNT/sanitization behavior is covered; no duplicate public and bundled trackers remain.
- [ ] Actual router paths produce only plan 001's fixed categories. Query strings, fragments, raw page titles, referrers, org/space/session IDs, user-entered data, and excluded routes cannot reach the collector payload.
- [ ] The tracker is limited to the production hostname/site configured in `web/index.html`. Tests may inject a synthetic configuration in an isolated fixture; localhost/previews do not silently opt into the real site. Keep website ID/config public and credentials absent.
- [ ] A defined `beforeSend` exists before the approved tracker loads; pageviews and the finite reviewed named-event catalog are projected rather than passed through. Identity/session-data, replay, heatmap, performance, and unknown payload types are refused. Never call `identify` or set a distinct ID.
- [ ] DNT and local `umami.disabled` are checked before loading and on every attempted send, so opting out after load suppresses future pageviews/events. A visible keyboard-accessible identity-independent analytics choice appears on every tracking-eligible route, outside identity, loading, error and Suspense gates, including direct anonymous/invitation/link entry, guest rooms and presentation. It works with screen readers and says that it applies to this browser; it does not promise retroactive deletion or expose profile/space privileges.
- [ ] If local storage is unavailable, no exception escapes; the choice is applied for the active document and the UI honestly says it could not be persisted. Enabling after initial opt-out may require a reload, which is disclosed. No persistent analytics identifier or event queue is added.
- [ ] Events before a ready tracker, blocked script, offline collector, exceptions/rejected promises, and late callbacks after opt-out are safely dropped. No automatic retry, offline replay, persistent buffer, awaited analytics dependency in user actions, or unsanitized diagnostic logging is added.
- [ ] The exact tracker interface used is proven against an approved version-matching script/collector fixture supplied by 001's baseline. If unavailable/incompatible, named events fail closed and the compatibility gate remains blocked; do not upgrade shared Umami or assume modern attributes.
- [ ] Expanded named events remain disabled for real traffic until the 005 custody receipt and 006 separately authorized release gate are satisfied. Local instrumentation and tests in 003/004 may proceed. A small public, deployment-scoped enable switch defaults off for named events; pageview correction can ship independently. No new server env reader is needed for this frontend-only gate.
- [ ] Privacy docs and their VerifiedStamp explain configured coarse analytics, local opt-out, dropped-event limitations, and collector/backup boundaries. Correct the fork's stale “no analytics” known-limitations claim without changing upstream policy claims globally.

## Design

Testing approach: browser-based

**Files expected to change:**

- `web/src/lib/analytics.ts`: create `initializeAnalytics` and `trackAnalyticsEvent`, readiness/runtime gate and shared preference state, consuming the pure contract.
- `web/src/lib/analytics.test.ts`: create version-matched adapter and opt-out failure tests.
- `web/src/main.tsx`, `web/index.html`, `web/public/analytics.js`: replace the old bootstrap, preserve production site/domain configuration, and set named-event enablement false by default.
- `web/src/App.tsx`: mount the unprivileged analytics choice once beneath BrowserRouter, outside Suspense/route/identity gates, only where the pure route projection permits tracking.
- `web/src/components/AnalyticsChoice.tsx`: create the small unobtrusive accessible preference control; it never gates/dismisses the app or opens account navigation.
- `web/src/components/AnalyticsChoice.test.tsx`: create component/state/accessibility tests.
- `web/src/App.test.tsx`: create route-level placement tests for direct entry, guests, presentation, loading/error states and excluded routes.
- `site/src/content/docs/security/data-and-privacy.mdx`, `site/src/content/docs/known-limitations.mdx`, `deploy/scrum-pro-htz4/README.md`: fork-specific behavior and release gate; update stamps against the actual changed sources.
- `scripts/guard-mutation.sh`: add mutations that widen the projection, remove per-send opt-out, or enable unknown event types, following its existing setup-failure conventions.

Place the control in app layout rather than relying on ProfileDialog: `web/src/components/AppShell.tsx` hides profile access from guests, and invite/link/presentation routes are standalone. Make the control usable at 390px with a 44px target and visible keyboard focus; no fullscreen overlay or must-dismiss banner. Account, guest and anonymous users share the same local preference state; tests assert placement even while route data loads/fails.

Keep only the small transport needed by callers, not a generic analytics-provider framework. Umami's automatic SPA tracking may be retained only when the installed compatible tracker fixture proves one sanitized pageview for initial load and supported navigation. Do not introduce newer `data-auto-pageview` settings without version proof. Keep unknown routes and all default payload fields out through projection, even if the tracker adds fields later.

Use the existing gateway paths unchanged. Client projection is a guard for this app's trusted call sites, not an integrity/security boundary against a malicious visitor forging public collector requests. State this limit; do not claim analytic events are authoritative business records.

**Out of scope:** production deployment/enablement, changing proxy identity or ingress, recording session contents or replay, universal click tracking, backend telemetry/routes, new dependencies, cross-device preferences, and deleting past analytics.

## Tasks

1. Add failing tests that reproduce `/o/...` and `/session/...` collapsing to `/other`, named-event refusal, and opt-out changes after initialization.
2. Implement one version-compatible bundled initialization and safe nonblocking event bridge; remove duplicate bootstrap only after parity tests cover it.
3. Add the always-reachable unprivileged analytics choice, immediate suppression, and honest storage-unavailable behavior on every tracked route.
4. Cover script/load/send failures and duplicate initialization; add the focused guard mutations.
5. Update fork privacy/known-limitations/operator docs and stamps, with named-event activation still disabled.
6. Obtain independent source and browser review using synthetic fixtures, including privacy payload inspection and the default-off gate.

## Verification

- [cmd] `cd web && npm test -- src/lib/analyticsContract.test.ts src/lib/analytics.test.ts` — red before fix, green after; execute the approved matching tracker fixture against an intercepted local collector and inspect complete bodies.
- [cmd] `cd web && npm test -- src/components/AnalyticsChoice.test.tsx src/App.test.tsx` — include opt-out before and after load, denied storage, keyboard control, and no user-flow failure.
- [cmd] `cd web && npm run build && npm run lint`.

Rebuild embedded assets before later Go checks; never hand-edit build output.
- [browse] `/o/test-org/s/test-space/settings` verify 'one sanitized /workspace-settings pageview, with no raw slug, query, fragment, title, or referrer in the intercepted payload'. Use agent-browser and synthetic local fixtures, not real analytics.
- [browse] `/` verify 'DNT or local opt-out suppresses script loading; opting out after readiness suppresses subsequent events and navigation without breaking the app'.
- [manual] Run the newly added scoped mutations in the existing harness during implementation; record exact mutations and restore source. Compatibility and full payload verification must fail when the guard is deliberately broken.
- [browse] `/link` verify 'the unprivileged analytics choice remains reachable for anonymous and guest journeys, loading/error views and presentation, at 390px and by keyboard, without profile access'.
- [manual] Confirm real-traffic named events stay off and collector-version evidence is present before any release proposal.

<!-- mstack:seam
produced:
- kind: file; name: web/src/components/AnalyticsChoice.tsx; file: web/src/components/AnalyticsChoice.tsx
- kind: file; name: web/src/lib/analytics.ts; file: web/src/lib/analytics.ts
- kind: symbol; name: initializeAnalytics; file: web/src/lib/analytics.ts
- kind: symbol; name: trackAnalyticsEvent; file: web/src/lib/analytics.ts
assumed:
- from: 001; kind: file; name: web/src/lib/analyticsContract.ts; file: web/src/lib/analyticsContract.ts
- from: 001; kind: symbol; name: analyticsPageCategory; file: web/src/lib/analyticsContract.ts
- from: 001; kind: symbol; name: projectAnalyticsEvent; file: web/src/lib/analyticsContract.ts
-->
