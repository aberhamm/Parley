# Bounded private analytics relay

Implementation evidence is local until a different validator reviews it. This
document describes the code contract, not installed-network, retention or
custody acceptance. The relay is off by default; Caddy activation is separate.

Canonical policy: `web/src/lib/analytics-policy.json`, copied byte-for-byte into
`internal/analyticsrelay/policy.generated.json` by
`node web/scripts/sync-analytics-policy.mjs`. Build runs `--check`; policy changes
require regenerated Go data and both browser/wire negative tests. TypeScript
public event types remain source compatibility, not separate runtime catalogs.
The browser emits website, hostname and title directly from that same policy;
metadata only activates the canonical site/host and named-event choice. Build
checks reject metadata website/host drift. Synthetic pins are injected only by
Vitest module fixtures, with no production window/env/runtime override.

The operator atomically replaces `admission.json` in the whole read-only app
mount. All directory ancestors must be real directories, controlled by root or
the app user without group/world write (sticky temporary ancestors are allowed
for local fixtures). The regular receipt is not a symlink, is at most 8 KiB,
and has no group/world write. Never log receipt or event bodies.

Runtime schema1 fields (all required): `schema`, `generation` (nonnegative
integer), `state` (`ready`, `maintenance`, `blocked`, `retention_failed`),
`checked_at`, `valid_until` (UTC RFC3339), `contract_schema`, `policy_sha256`,
`website_id`, `collector_version`, `collector_image`, `tracker_sha256`,
`app_build`. Only ready admits. The pins come from canonical policy; app_build
must equal the startup SHA256 of the actual loaded executable, independently
verified against the installed immutable image by the producer. No environment
or semantic-version digest substitutes. Producer refreshes at most every 30s;
lease is at most 60s, future skew at most 5s. Unknown/duplicate/null/unsafe or
mismatched input refuses without consulting app DB or principal.

Opening the receipt descriptor acquires the request snapshot. New snapshots
after non-ready publication refuse. Already opened ready snapshots may finish
only inside the original handler-entry five-second deadline, covering parsing,
receipt I/O, validation, scheduling and upstream work. No cache/retry/queue
extends this. After atomic publication completes, the producer waits at least
six seconds, stops/waits the dedicated collector and verifies DB writer drain
before purge. Client timeouts are not server transaction completion. Missed
retention deadlines stay retention_failed; admission closure is not deletion.

The public surface is only GET /a/script.js and POST /a/api/send. Strict
single-JSON parsing rejects duplicates/unknown keys, IDs, identify, timestamps,
selectors and raw strings outside finite categories/enums. No cookie, auth,
referrer, origin, IP or native cache reaches upstream. Successful send is 200{}
compatible with the pinned Umami3.0.3 SDK, never its native cache response.
Script bytes must match the canonical tracker hash before serving. No redirect,
retry, admin/pixel/link/native bypass or arbitrary proxy path exists.

Tests use synthetic local fixtures and a task-owned isolated Postgres. Separate
operator evidence must prove actual ACLs, image/binary correspondence, private
network, stop/drain, custody/expiry, and final cutover. No production receipt or
network is inferred from source tests.
