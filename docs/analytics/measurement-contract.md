# Scrum Pro usage measurement contract

Schema: **numeric `1`**. Scope: the Scrum Pro fork, not upstream Parley's policy.
Reviewed against app source `179022c57764fc6b886a7ba8c178a2dbdad05edc` and the
27 October 2026 collector metadata receipt described below.

This contract defines useful aggregate observations without sending meeting
content or application identities. Plan 001 adds only the pure projection and
its tests. It does not load a tracker, change the existing pageview bootstrap,
start sending named events, or establish production collection readiness.

## Decisions this data can support

Use the last seven complete calendar days in **Europe/Berlin** by default;
show the exact start/end instants and timezone with every report. Store/filter
source timestamps consistently in UTC. Compare equal windows and schema
versions, and label partial days and release/coverage changes. Counts are
observations from browsers that were allowed to track and successfully reached
the collector, not a census of all application activity.

| Question and decision | Signal and unit | Numerator / denominator | Repeat and coverage rules |
| --- | --- | --- | --- |
| Which areas are visited, so navigation deserves attention? | Pageview observations by fixed category | Count per category; no person denominator | Navigation/reloads can repeat; unknown pages are `/other`; excluded pages are absent. |
| Which entry paths succeed, so onboarding work can be prioritized? | Separate `workspace_created`, `workspace_joined`, `invitation_accepted`, `guest_link_redeemed` action observations | Count each event separately; no conversion denominator | Acknowledged actions only; retries/rejoins can repeat; invitation and guest-link entry are alternatives, not sequential steps. |
| Are poker or standup creations observed? | `session_created`, by `kind` | Count of acknowledged UI creations per kind; no meeting denominator | Scheduled creation and untracked clients are absent. Lost responses can hide successful server writes. |
| Do browsers reach rooms? | `room_opened`, by `kind` | Count of document/room-mount observations; no participant denominator | Once per authorized mount; reloads, tabs and remounts can repeat. This is not a unique room or person count. |
| Is poker participation observed? | `poker_vote_saved` and `poker_reveal_requested` | Separate counts of acknowledged vote writes and manual reveal requests; no round denominator | Vote changes/retries can repeat. Auto-reveal and another browser's live update produce no event. |
| Is standup participation observed? | `standup_participated` | Count of first acknowledged local saves per document/room mount; no person denominator | Subsequent autosaves/flushes in that mount do not repeat; reloads/tabs can repeat; no text/content test is used to infer completeness. |
| Do hosts request closure? | `session_closed`, by `kind` | Count of acknowledged close requests; no completed-meeting denominator | A repeated acknowledged request may count; not deletion, scheduled expiry, or proof of a globally unique completion. |
| Do tracked browsers report creation friction? | `creation_failed`, by fixed `flow` and `category` | Count failure observations separately; no success/failure conversion ratio | Only workspace/session creation. A non-success response and an unknown outcome are distinct; repeated retries can repeat. Local validation is not tracked. |
| Which observed browser journeys reach the next step? | Conditional ordered page/event flows below | Collector-defined anonymous sessions reaching the next step divided by sessions entering that flow, within the validated window | Unavailable until identity separation and version-specific report semantics are proven. Never call these unique people or meeting conversion. |

Do not divide independently aggregated event totals to claim a cohort
conversion, completion rate, or participation rate. Retried actions, ambiguous
responses, different arrival times and multi-person meetings make those units
incompatible. Raw counts remain useful without a people/session identity.

### Conditional flow reports

The initial reporting tier is **actions only**, and even accepted event counts
need actual collector readback before being advertised as measured. Anonymous
flows are **unavailable** until an isolated, version-matched two-context test
proves that the gateway does not merge otherwise independent same-User-Agent
browsers, and ordered-step/window tests pass. Do not repair a failed experiment
by forwarding real IPs, adding a distinct ID, or changing the privacy contract.

If those gates pass and the installed report supports the necessary selection,
use separate same-browser flows:

- Host setup: homepage → workspace creation → session creation.
- Invited browser: invitation page → acceptance → room open, only for entry
  paths that subsequently open a room.
- Poker: room open → acknowledged vote write.
- Standup: room open → first acknowledged local save.

The proposed maximum is **60 minutes between consecutive steps**, not 60 minutes
for the entire journey; prove the installed collector's semantics. A journey
may contain other actions between steps. Separate ceremony kinds only when
supported filtering actually distinguishes them; otherwise omit that flow.
Do not require a participant to perform the host's closure action. Direct room
entry, existing workspaces, alternate invitation paths and anonymous identifier
rotation limit interpretation. No cross-device or longitudinal user-retention
claim is supported.

## Event contract

Every accepted event has `name` from this table and a **newly built** `data`
object containing numeric `schema: 1`. The `projectAnalyticsEvent(name, data)`
function in `web/src/lib/analyticsContract.ts` returns that projection or null.
It accepts an omitted data object for no-property events, and accepts an
already projected object only when its schema is exactly numeric 1. It never
passes an arbitrary caller object through.

| Name | Additional properties | Definition and call site |
| --- | --- | --- |
| `workspace_created` | None | Initiating `Landing` callback receives a successful create response. |
| `workspace_joined` | None | Initiating `SpacePage` callback receives successful explicit join response; may be a rejoin. |
| `invitation_accepted` | None | `InvitationPage.redeem` receives successful acceptance; not preview, sign-in prompt, or rendering membership. |
| `guest_link_redeemed` | None | `LinkPage.submit` receives successful signed-link redemption. |
| `session_created` | Required `kind`: `poker`, `standup`, `other` | Explicit create-session callback receives success; no scheduled creations. |
| `creation_failed` | Required `flow`: `workspace_create`, `session_create`; required `category`: `rejected`, `outcome_unknown` | Explicit HTTP non-success versus transport/response ambiguity. Neither is an authoritative statement about whether a server transaction occurred. |
| `room_opened` | Required `kind`: `poker`, `standup`, `other` | First authorized readable built-in poker/standup room and resolved identity during one document/room mount in `SessionPage`. Plugin and unknown rooms are not observed. |
| `poker_vote_saved` | None | Initiating vote callback receives success; not optimistic selection or server broadcast. |
| `poker_reveal_requested` | None | Initiating manual-reveal callback receives success; not automatic reveal or an observed revealed frame. |
| `standup_participated` | None | First acknowledged local standup save per document/room mount in `useOwnEntryDraft`; not seeded entries or every debounced save. An empty-but-successful save counts without inspecting content. |
| `session_closed` | Required `kind`: `poker`, `standup`, `other` | Initiating close callback receives success; standup flush must succeed first. |

No other properties are allowed. Unknown names, keys, enum values, nested data,
arrays, class instances, inherited properties, symbol keys and accessor
properties are refused. Names and properties are literal enums; normalize
ceremony kinds before calling rather than sending an arbitrary plugin name.
Do not send IDs (including hashed IDs), names, titles, story or standup text,
votes/estimates, slugs, tokens, error messages, URLs, count/timestamp fields,
release hashes, or test IDs. Rejection is deliberate; silently dropping an
unknown field would hide a caller that tried to send unreviewed data.

Ceremony instrumentation uses explicit initiating callbacks after awaited
writes. No generic `api()`/`action()` interceptor, React render, shared query,
WebSocket message, hub callback, or plugin frame may emit a success event.
Navigation/cache errors after an acknowledged write do not turn it into a
creation failure. A retained user-retry callback must include the same
post-success observation. Memory-only once-per-mount guards are bounded to the
active room and never become outbound identifiers or an offline queue.

Analytics is best effort. DNT/local opt-out, a not-ready or blocked tracker,
network loss, bot filtering and anonymous-session merging can remove or distort
observations. Do not delay a user action, change its result, add automatic
retries, persist a queue, or log raw payloads/errors to make collection succeed.

## Page projection

`analyticsPageCategory(pathname)` returns a fixed category or null to exclude
collection. It discards query/fragment text and never returns any input segment.
Its template decision follows `web/src/App.tsx`; the contract test enumerates
registered SPA routes so a new route needs an explicit tracking decision.

| Router path | Output |
| --- | --- |
| `/` | `/` |
| `/o/:org` | `/directory` |
| `/o/:org/s/:slug` | `/workspace` |
| `/o/:org/s/:slug/settings` | `/workspace-settings` |
| `/session/:id` | `/session` |
| `/session/:id/present` | `/present` |
| `/invite`, `/link` | Corresponding fixed category, never their fragments |
| Authentication/API/internal, catalog, embedded/meeting-client, plugin UI and org-admin paths | Excluded (null) |
| Other/unknown/malformed paths, legacy `/s/:slug`, unsupported locale-prefixed application routes | `/other` |

Sensitive prefixes remain excluded on language-prefixed or malformed addresses.
Decoded path segments are used only for the local decision; they are never
copied into the result. No route existence or permission is established by this
categorization. The future adapter must also project tracker defaults: fixed
app title, empty referrer and the approved hostname/site, without raw paths,
queries, fragments, screen/language data or arbitrary tracker-added properties.

## Collector baseline and ownership

The protected scout receipt `scrum-analytics-20261027/collector-readiness.md`
was checked **2026-10-27T10:08:38Z**. It establishes deployment metadata, not
accepted event ingestion, a restore drill, independent behavior validation, or
an assumption that today's upstream docs match the deployed version:

- Installed collector: **Umami 3.0.3**, PostgreSQL mode, on the Homelab-managed
  Umami service. The designated Homelab/Umami operator owns operational custody;
  runtime Unix ownership does not appoint an agent or grant new authority.
- Tracker SHA256: `a1471487eb3e8eb93b1a9e056386019ff5eedadea29bbb725b5494fb2e9ad90a`;
  build ID `rs9-wqSJ-ngIhUwrcgvXp`.
- Scrum website: `acc214c0-d772-493a-ad03-49fa8e72d77e`, hostname
  `scrum.matthew.systems`; public sharing was disabled in that metadata read.
- The source supports named events, before-send projection and action/report
  APIs. A script download or bot-shaped HTTP 200 does not prove persistence.
- The app gateway serves `/a/script.js` and `/a/api/send`, stripping original
  headers and restoring only Host, User-Agent and JSON content type for send.
  It also removes the tracker's cache header. No real-client IP is intentionally
  forwarded by the app gateway. Final proxy identity behavior is unverified.
- Umami derives anonymous session identity using website, detected IP,
  User-Agent and rotating salt; it may derive device/location metadata. Same-UA
  browsers behind the gateway may merge. No claim of unique people, absence of
  potentially personal metadata, or automatic legal compliance follows.

The pure projection is a boundary for the app's reviewed call sites, not an
integrity or abuse boundary against someone forging public collector requests.
Keep default-off named collection until adapter, ingestion, privacy, custody and
release evidence pass; no collector upgrade or identity widening is needed by
this contract.

## Accepted retention and unresolved operational gates

Matthew accepted **90 days of raw Scrum Pro Umami data** on 27 October 2026.
He also explicitly authorized the scoped retention/backup-custody work and
using these six reviewed plans instead of an issue. This records decisions,
not a claim that the retention mechanism is already implemented.

The reviewed Umami 3.0.3 native API exposes a whole-site reset, not a verified
rolling timestamp purge. That reset cannot substitute for retention. Analytics
full-database backups include other websites; their nominal 30-day rotation,
effective access and expiry/restore reconciliation were not proven. The app's
30-day archive and seven-day closed-log policies, and its deletion journal,
do not apply to this separate analytics store.

Required operational evidence remains:

1. The scoped, version-matched 90-day site expiry mechanism, proven using fake
   expired/fresh records and a second untouched site, with failure/idempotence
   checks and no broad reset.
2. Restricted effective analytics access and private backup custody, including
   directory/ACL behavior rather than inferring access from POSIX mode alone.
3. A bounded backup lifetime and restore-time expiry reconciliation before
   collector ingress/reports resume. Do not silently reinterpret 90 days as
   90 days plus an assumed backup grace period.
4. Isolated accepted-record ingestion, payload inspection and source/tracker/
   collector compatibility; anonymous flow reporting additionally needs the
   two-context identity and ordered-window proof.
5. Independent final review and a guarded release/rollback receipt. The matching
   implementation/deployment authority already exists; the technical evidence
   gates still have to pass.

Local opt-out stops future sends from that browser; it is not retroactive
analytics deletion. App profile/session/workspace erasure does not automatically
remove analytics or its backups, and the contract sends no stable app identity
with which to locate those observations. Do not introduce such an identity to
claim individual erasure. Previously stored data, exports, caches and backups
need separate operator treatment; no physical-media sanitization or legal
certification is claimed.

## Evidence and change control

Unit tests cover actual router templates and hostile input rejection. They do
not prove browser behavior or deployment. Plans 002–004 add the runtime adapter
and explicit call sites; 005 establishes custody readiness; 006 validates
accepted collector records and reports. Do not promote a control to verified
merely because a test file exists or this document states the intended rule.

Official version-specific source references, reviewed 27 October 2026:

- [Umami 3.0.3 tracker](https://github.com/umami-software/umami/blob/v3.0.3/src/tracker/index.js)
  for event/before-send interfaces.
- [Umami 3.0.3 collection handler](https://github.com/umami-software/umami/blob/v3.0.3/src/app/api/send/route.ts)
  for identity, cache and acceptance behavior.
- [Umami 3.0.3 reset query](https://github.com/umami-software/umami/blob/v3.0.3/src/queries/prisma/website.ts)
  for why a whole-site reset is not rolling expiry.
- [Umami self-hosting FAQ](https://docs.umami.is/docs/faq) for the absence of
  automatic retention as a self-hosting guarantee. Installed source and actual
  executed receipts remain authoritative for this deployment.


## Entry and activation callback coverage (plan 003)

Named collection remains disabled by default. These source callbacks are wired
for local validation; this is not evidence of real-traffic collection.

| Event | Initiating acknowledged callback | Source test and repeats/omissions |
| --- | --- | --- |
| `workspace_created` | `Landing.doCreate`, immediately after POST `/api/spaces` | `Landing.test.tsx`, observed creation outcomes: once per successful callback, including successful hand retry; rerender and failed navigation do not repeat it. Local validation and restored identity alone are absent. |
| `workspace_joined` | `SpacePage.doJoin`, after the explicit join POST, including a submitted invite credential | `SpacePage.test.tsx`, observed outcomes and creation failure boundaries: cached membership reads do not count; rerenders do not respend an invite; denied joins emit nothing. An acknowledged rejoin may count again. |
| `invitation_accepted` | `InvitationPage.redeem`, after acceptance POST | `InvitationPage.test.tsx`: preview, missing token, sign-in prompt and failed acceptance emit nothing; successful user retry counts. No invitation data leaves the callback. |
| `guest_link_redeemed` | `LinkPage.submit`, after signed-link redemption POST | `LinkPage.test.tsx`: busy/re-render guards preserve one redemption; denied/missing credentials emit nothing. No token, name or receipt leaves the callback. |
| `session_created` | `SpacePage` create-dialog `submit`, after creation POST | `SpacePage.test.tsx`: poker/standup remain exact; plugin kinds map to `other`. Dialog opening and local instant validation emit nothing; scheduled creations are absent. Each acknowledged repeat is another action. |
| `creation_failed` | Only `Landing.doCreate` and create-dialog `submit`'s awaited write catches | Both page tests exercise explicit `ApiError` refusal (`rejected`) versus transport/response loss (`outcome_unknown`), then a successful retry. Navigation/cache/response-use exceptions after the write resolved never fabricate a creation failure. |

A lost response can hide a successful server creation. Its unknown-outcome
observation and a later acknowledged retry are not paired outcomes of the same
attempt, unique workspaces or meetings, or an exact success/failure conversion.
The API helper can resolve a successful HTTP response without a usable body;
that acknowledged response still counts, even if opening the result fails.
These callbacks do not add retries, identifiers, queues, routes or permissions.
Embedded meeting clients do not mount these entry pages and remain excluded by
the adapter. Optional analytics transport throws/rejections, missing scripts,
DNT, opt-out and disabled named events leave acceptance/redemption intact.

The page tests use a synthetic tracker that passes its complete candidate
payload through the real before-send projection and checks emitted records,
not a mocked event function. This establishes local app projection behavior;
it does not establish accepted collector records or collector-derived metadata.

## Ceremony observation limits

`PokerRoom` counts acknowledged local vote changes as additional actions and
explicit manual reveal requests (including successful user retries), never
unique people or revealed rounds. `StandupRoom` awaits its serialized save and
final flush before close: a failed flush or denied close has no close success.
`SessionPage` observes a readable built-in room once per mounted room view after
identity resolution, including authorized guest views, but never name recovery
prompts or plugin frames. A new room mounts fresh local draft/observation state.

Only that initiating browser emits action observations. Receiving the same
WebSocket update, reconnecting, rendering ended/revealed state, and automatic
or scheduled actions emit no action success. Reloads, real remounts and multiple
tabs can duplicate room-open and first-save observations; blocked tracking,
other devices, network loss and acknowledged retries also distort counts.
These signals cannot establish exact people, rounds, meetings or completion
rates. Memory-only guards expire with the mounted room; no queue or identifier
is persisted or transmitted. The adapter can drop an observation without
changing vote rollback, autosave sequencing or close guards.
