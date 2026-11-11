# Scrum Pro usage report recipes — LOCAL preparation

These are report definitions, not measured usage. Production and rollout are
**blocked** until actual005 readiness, integrated ingestion/readback, final
artifact/privacy acceptance and231 installed staging/cutover gates pass. The
machine-readable companion is `report-recipes.json`; its synthetic vectors
are LOCAL expected arithmetic, never accepted collector records.

## Window, scope and units

Default to the last seven complete calendar days in **Europe/Berlin**. Show
both exact UTC endpoints and timezone; use an inclusive start/exclusive end.
Calendar windows can span167,168 or169hours around daylight-saving changes.
Compare the same schema, site, coverage and complete calendar windows; label
partial days, releases and missing coverage. The local checker verifies seven
Berlin calendar days ending at midnight, rather than assuming168hours.

Every view counts **observations**. There is no person, workspace, meeting,
round or paired-attempt denominator. Retries/rejoins/vote changes and repeated
mounts can add observations; blocked tracking, response loss, offline delivery,
bot filtering, device changes and collector identity rotation/merging can remove
or distort them. Do not divide independently summed actions into a conversion,
completion or participation rate, or infer daily/weekly retention of users.
An HTTP refusal is an observed response, not proof no transaction occurred.

## Declarative native query recipes

Use the exact isolated/approved website and bounded window. These selectors
are requirements to verify against the installed Umami3.0.3 native UI/API, not
claims that a particular endpoint supports combined filters. Do not invent a
Parley analytics endpoint or upgrade the shared collector to make a recipe fit.
The canonical event/category vocabulary is exclusively
`web/src/lib/analytics-policy.json`; the catalog adds no event or identifier.

| View / decision | Required selection and breakdown | Interpretation |
| --- | --- | --- |
| Broad navigation | Native pageviews by the nine fixed URL categories | Pageview observations, including reloads. Unknown paths are `/other`; excluded paths are absent. Pageview payloads have no `data.schema`; schema1 here names the projection contract, not a nonexistent pageview property filter. |
| Workspace creation | Event `workspace_created`, numeric `data.schema=1` | Acknowledged browser create callbacks; navigation failure still counts. Lost success responses can hide real creations. |
| Workspace entry | `workspace_joined`, schema1 | Explicit acknowledged joins, including rejoin; existing membership reads do not count. |
| Invitation acceptance | `invitation_accepted`, schema1 | Separate entry path; not previews/sign-in prompts or a required predecessor of every room visit. |
| Guest-link entry | `guest_link_redeemed`, schema1 | Acknowledged signed-link redemptions; no token/name diagnostics. |
| Session creation | `session_created`, schema1; group by `kind=poker|standup|other` | UI creation observations, excluding scheduled creation; plugin identifiers are reduced to `other`. |
| Poker saves | `poker_vote_saved`, schema1 | Acknowledged local vote writes, including changes; not voters or rounds. |
| Manual reveal | `poker_reveal_requested`, schema1 | Acknowledged manual requests, including a successful user retry; not auto-reveals or observed WebSocket frames. |
| Standup participation | `standup_participated`, schema1 | First accepted local save per mounted room; empty-but-accepted saves count without inspecting text. Reload/tab/remount can repeat. |
| Close requests | `session_closed`, schema1; group by kind | Acknowledged explicit closes, after standup final flush; not unique meetings or proof of completion. |
| Room visibility | `room_opened`, schema1; group by kind | Readable built-in room plus resolved identity, once per mounted room view; not unique rooms or participants. Plugin/unknown rooms are excluded. |
| Creation friction | `creation_failed`, schema1; group jointly by `flow=workspace_create|session_create` and `category=rejected|outcome_unknown` | Separate observations; local validation/other forms are absent. Unknown outcome plus later success is not one paired attempt. |

For event queries require native event-name selection **AND** numeric schema1,
plus each needed dimension, within the same website/window. Record the actual
supported filter combination and raw accepted-record oracle. If joint schema/
kind/flow/category filtering is not supported or independently proven, omit the
unproven breakdown instead of summing mismatched views or labeling an unfiltered
count schema1. A known-schema isolated synthetic site can establish a test
oracle, not automatically a production reporting capability. Every catalog
`native_filter_status` remains `unverified` in this LOCAL phase.

## Conditional anonymous flows — unavailable by default

Actions are the default reporting tier. Flows additionally require a fresh005
`anonymous-flows` receipt, actual two-context identity separation, installed
ordering/window behavior and supported per-step kind filtering where needed.
Same-UA browsers behind the minimized relay may merge. Never forward client
IPs, add distinct IDs or change the shared collector to improve a funnel.

| Separate same-browser journey | Required steps | Omission/limitation |
| --- | --- | --- |
| Host setup | `/` → workspace_created → session_created | Existing-workspace/direct entry can skip homepage or creation; no claim of acquired hosts or teams. |
| Invited browser | `/invite` → invitation_accepted → room_opened | Count only paths that subsequently open a room. Acceptance commonly lands in a workspace; a room is not guaranteed. Guest links are a separate path. |
| Poker | room_opened(kind poker) → poker_vote_saved | Verify native per-step kind filtering; otherwise omit. Host reveal/close is not a participant's required next step. |
| Standup | room_opened(kind standup) → standup_participated | First-save observations are not people or completeness of updates. Omit if needed kind filtering is unsupported. |

The intended maximum gap is **60minutes between consecutive steps**, not total
journey duration. Intermediate unrelated actions are allowed. Validate native
boundary precision rather than assuming this recipe establishes it. A flow at
minutes0,50,100 tests the distinction; a gap over60minutes must not count.
Check repeated and out-of-order steps, direct-entry bypass, separate contexts,
rotated anonymous context and same-UA merging. Ambiguous identity/ordering or
unsupported filters keep flows unavailable, with raw action views only after
their own ingestion/report proofs. Collector-defined anonymous contexts never
mean unique people, cross-device retention or authoritative conversion.

## Local preparation check

`scripts/check-analytics-report-preparation.py` reads this catalog and a private
LOCAL manifest plus a separately supplied expected binding object. It reuses
005's checker for an optional exact-hash fresh readiness receipt and local
proof bundle. It does not query Umami, inspect a browser, validate artifact
causality, attest opaque proof contents or authorize collection. A valid result
always has `scope=LOCAL`, `rollout=blocked`, and `LIVE_ACCEPTANCE_MISSING`.
Exit1 is a valid blocked preparation, exit2 is refusal, and only intentional
`--help` exits0. No ready output exists. Use no real data in local fixtures.

The LOCAL oracle requires zero pageviews and zero named entries for DNT,
opt-out before load, frames, unapproved hosts, blocked tracker, offline sends,
maintenance new snapshots, stale admission, wrong artifact hashes, expired old
snapshots and all-collection rollback. Named-default-off alone allows pageviews.
Opt-out-after-load totals can include earlier accepted observations; rejected
business actions and WebSocket replay do not by themselves prohibit unrelated
pageviews. These checks validate fixture expectations, not real delivery.

Run `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts/tests -p test_analytics_reports.py`
for bound synthetic recipe tests. Real collector/native report results still
need the separate [acceptance matrix](../verification/analytics-acceptance.md).
