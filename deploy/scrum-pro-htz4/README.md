# Scrum Pro on htz-4g-nbg

Production: https://scrum.matthew.systems

Application release: `873780b2a584dd27dc8e830a6c35fbf4e7f99321`.
Linux/amd64 OCI image index digest:
`sha256:c94af0b9ce4d7e5865ae088b128ad597c70e43d598a270351ea9b3d32adebd76`.
The image was built on the Mac Studio, saved and loaded over SSH, and verified
on Hetzner by digest and architecture. It is not published to a registry.
The deployment Dockerfile uses native build stages and cross-compiles the same
application source; the original emulated Go stage crashed under QEMU.

## Host boundaries

Files live in `/opt/apps/scrum-pro`, owned by root, directory mode 0700.
Use `ssh root@htz-4g-nbg`, then `cd /opt/apps/scrum-pro` and `./manage.sh`.
App secrets are in `app.env`; Compose secrets are in `.env`, both mode 0600,
never in Git. These files were copied byte-for-byte from the Studio runtime.
The live app had no PLUGIN_SECRET_KEY or previous key and no stored plugin,
webhook or publication credentials. No keys were generated or rotated.

The dedicated Docker network is `scrum-pro_default`. No service publishes a
host port. The existing Cloudflare Tunnel is retained, including its token,
DNS record and ingress:

- Tunnel ID: `ac4fba4d-37c9-4049-be42-0424b592fbae`.
- Existing tunnel name: `scrum-pro-ms-128g-bln` (the historical name is retained).
- Hostname: `scrum.matthew.systems`.
- Service: `http://public-gateway:8080`, fallback `http_status:404`.
- Private gateway proxies `public-app:8080` and redirects HTTP to HTTPS.

The gateway is Scrum Pro's existing dedicated Caddy sidecar. It does not use
or change shared host Caddy, ports 80/443, or Leidenfrost's containers/network.
The chat “Track Hetzner staging server” owns shared routing. No shared proxy
snippet or routing change is required for this deployment.

## Resources and operations

All services retain `restart: unless-stopped`, health checks, explicit memory
limits, dropped capabilities and no-new-privileges. The privacy deployment
replaces Docker JSON-file logging with the dedicated private syslog path below;
its size rotation and seven-day expiry are separate controls. App and gateway/
tunnel filesystems are read-only. The table is the historical migration sample,
not a privacy-release load-test result.

| Service | Memory limit | Initial observed use |
| --- | --- | --- |
| public-app | 128 MiB | 5.5 MiB |
| db | 384 MiB | 47.6 MiB |
| public-gateway | 48 MiB | 10.3 MiB |
| cloudflared | 64 MiB | 25.0 MiB |

App + DB limits total 512 MiB; the two ingress sidecars add 112 MiB.
After the full restart and browser verification, measured app + DB use was
about 42 MiB and all four services about 71 MiB. No OOM kills or automatic
container restarts occurred. These are small-session measurements, not a load test. Postgres has 64 MB
shared buffers, 4 MB work_mem, 32 MB maintenance_work_mem and 32 connections;
the app's pool allows 10 connections. Go soft memory limits leave headroom
below the container limits. Docker must remain enabled at boot.

```sh
./manage.sh ps
./manage.sh up -d --wait --wait-timeout 120
./manage.sh stop
# Never add -v to down: it deletes the database volume.
docker stats --no-stream scrum-pro-public-app-1 scrum-pro-db-1 scrum-pro-public-gateway-1 scrum-pro-cloudflared-1
```

Docker restart policies restart exited containers; health checks report an
unhealthy service and do not themselves restart it. Use readiness and the
Cloudflare connector health when investigating availability.

## Backups and recovery custody

Migration backups on Hetzner:
`/opt/apps/scrum-pro/backups/{preflight,cutover,post-migration}.dump.enc`.
Verified off-host copies, image archive, build metadata and private evidence:
`/Users/matthew/.local/share/scrum-pro-migration-20261022/` on ms-128g-bln.
The directory is mode 0700. Dumps are PostgreSQL custom format encrypted with
OpenSSL AES-256-CBC, PBKDF2 SHA-256, 200000 iterations, a random high-entropy
key and recorded SHA-256 checksums. Retrieve backups as secrets.

The matching encryption key is held separately, mode 0600, on the Studio at
`/Users/matthew/.config/scrum-pro-recovery/backup-20261022.key`.
It was not copied to Hetzner or committed. Matthew controls root SSH and the
Studio account. A loss of both Studio recovery custody and the active database
would require another recovery source. These files are migration backups;
recurring full-database NAS backups are managed separately. Enrolled encrypted
archives have a 30-day expiry; the NAS Scrum-only dump expiry is described below.

Decrypt on the Studio and stream through SSH, keeping all app replicas and
the connector stopped during a restore. Supply the exact encrypted file:

```sh
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -md sha256 \
  -in /path/to/backup.dump.enc \
  -pass file:/Users/matthew/.config/scrum-pro-recovery/backup-20261022.key |
  ssh root@htz-4g-nbg 'cd /opt/apps/scrum-pro; ./manage.sh exec -T db pg_restore -U parley -d parley --exit-on-error --no-owner'
```

The destination database must be empty; take a fresh backup before replacing
it. Preserve `.env`, `app.env`, manifests and any future plugin encryption keys
in protected off-host recovery custody. Never enable a connector to a stale
copy while another host accepts writes. Reconcile revocations/deletions and
queued jobs if restoring an older backup, as described in the application's
backups-and-recovery documentation.

The historical rollback instructions below predate privacy schema 63. Use the
privacy recovery procedure at the end of this document for the privacy release.
An older binary cannot start against a newer schema, and restoring a database
requires the latest independent deletion journal before exposure.

## Cutover and rollback, 2026-10-22

Cutover completed at approximately 23:58 UTC on 2026-10-21 (01:58 Berlin on
2026-10-22). The old Studio connector, public app, private gateway and local
preview were stopped before the final dump. The original Studio Postgres
volume was retained; its old container shells and Docker log caches have since
been removed after a verified backup. The same Cloudflare Tunnel then started on
Hetzner. Cloudflare reported healthy with origin IP only `46.224.225.122`.
DNS and ingress were unchanged.

Old runtime: `/Users/matthew/.local/share/parley-local/`.
Old database volume: `parley-local_parley-data`.
Historical app image: `parley-local:scrum-pro-preview` (linux/arm64).
The frozen volume has an explicit expiry of 2026-11-20 23:58 UTC, 30 days after
the original cutover. It is stale and is not the current production database.
The original raw runtime configuration remains protected for signing/key
recovery custody; it is not scheduled for deletion. Its encrypted
`legacy-studio-config-20261022.tar.gz.enc` archive is separately enrolled with
the original cutover plus 30-day expiry.
Do not run the old `manage.sh up -d` during normal operation: that would
reactivate the Studio connector and split traffic across separate databases.

Rollback owner: Matthew or the agent performing the rollback. The Studio
copy is frozen at cutover and is now stale. To preserve writes after cutover:

1. Stop Hetzner `cloudflared`, `public-gateway` and `public-app`; keep its DB up.
2. Dump the final Hetzner DB, encrypt it and verify a protected off-host copy.
3. Keep all Studio app services stopped. Back up its existing DB, then replace
   its database with the fresh Hetzner dump using pg_restore with exit-on-error.
   Preserve the existing Studio runtime secrets; migrate any key changes made
   since cutover. Compare table hashes and access state before exposure.
4. Start the Studio public app/gateway and verify readiness, then start its
   connector. Leave the Hetzner connector stopped. The hostname/ingress remains
   the same. Start the localhost preview only after this successful failback.
5. Check HTTPS, two-browser updates, existing identities and owner controls.

For a failure before accepting any new Hetzner writes, the original frozen
Studio DB can be used directly. That shortcut is no longer generally safe
now that verification and public traffic have reached Hetzner.

## Verification evidence

- Encrypted preflight dump restored into isolated target Postgres, with the
  connector absent. The customized amd64 app booted and readiness passed.
- No queued plugin jobs/deliveries or standup webhook deliveries existed.
- With all Studio writers stopped, the final restored rows matched count and
  canonical row hashes for all 48 public tables before target exposure.
  This includes session-token hashes, workspace owner roles and passcodes.
- HTTPS with certificate verification returned 200; HTTP redirected 308.
- Two isolated browsers created identities on the Studio deployment, then
  reconnected to Hetzner without signing in again. A vote created before
  cutover and a second vote after cutover revealed consensus in both browsers
  without reload, verifying the WSS update path through the retained tunnel.
- A member received 403 for both passcode rotation and making a workspace
  open. The owner received 200 for rotation, opening and protecting again.
- The entire stack, including Postgres, was stopped and started. Both browser
  identities, the revealed session and votes survived. Hashes for workspace
  ownership/passcodes, users, stories and votes stayed stable. Session-token
  last-used and facilitator heartbeat timestamps advance during reconnection.
- The temporary QA workspace was deleted and both test identities signed out.
- Leidenfrost container IDs and complete network attachments matched before
  and after deployment. Existing environment files matched byte-for-byte.
- A fresh post-migration encrypted backup was copied off-host, checksummed
  on both hosts, restored into a separate scratch database, and checked for
  the original workspace/session counts. The scratch database was removed.
- At migration completion the original Studio data and stopped app/tunnel
  containers were retained for rollback. The later privacy rollout removed the
  old container shells/log caches after verified backup and enrolled the frozen
  volume for its 30-day expiry. Migration archives have explicit retention.

Evidence and screenshots are kept outside Git in the protected Studio
migration directory. No application behavior or database schema changed.

## Umami rollout, 22 October 2026

The application with bounded page categories is source `43f181ec4ec8c4783e76bff4d7d71510c371956a`, Linux/amd64 image `sha256:d5f0eadbe5068590376c0893da89ce9d062b12bef2562b530cda630f61dad939`. The dedicated gateway serves `/a/script.js` and `/a/api/send`, strips app credentials and referrers, and forwards to `a.matthew.systems`. The previous image and configuration are retained on the host in `.umami-backup-20261022`. No schema, volume, tunnel or host ingress changes were made.

## Homepage rollout, 25 October 2026

Source `afd0913d7d5b5467b58c9d8565a8973791b91ca5` moves the workspace input above the fold and shortens first-visit copy. The amd64 image was built on the Studio using the pinned cross-build Dockerfile, then loaded on Hetzner. Runtime image reference: `scrum-pro@sha256:2386de3829f81513bf26ae9d42820a9156d48df9e98d12a9f695b95b049c52d2`. Only public-app is replaced; the database, dedicated gateway, tunnel, credentials and analytics routing are retained.

Before rollout, a fresh custom-format PostgreSQL dump was archive-validated, encrypted, copied to the Studio and Hetzner, and checked by SHA-256. Hetzner backup: `/opt/apps/scrum-pro/backups/homepage-predeploy-20261025.dump.enc`; Studio copy/build metadata/screenshots: `/Users/matthew/.local/share/scrum-home-release-20261025/`. Recovery key remains in the separate protected Studio recovery directory documented above.

For image rollback without reverting data, copy `/opt/apps/scrum-pro/compose.before-homepage-20261025.yaml` to `compose.yaml` and run `./manage.sh up -d --no-deps --wait public-app`. The prior image is retained on Hetzner. This release contains no schema change; do not restore an older database merely to revert this homepage.

Live verification passed: HTTPS readiness and version, desktop (1280×720) and mobile (390×844) homepage rendering with no horizontal overflow, HTTP-to-HTTPS redirect, and the existing analytics script route. Runtime secret/gateway hashes, DB/gateway/tunnel container IDs, and workspace/member/session counts matched before and after. The reviewed frontend passed all 79 Landing tests, build and lint (existing warnings only).


## Invitation rollout, 26 October 2026

Application source `88049156947c316ce705c4e466250bd73c8e9cae`, image
`sha256:80a644aa393bcfdda9ffd002d7faa81d4e03b48fd403438066f5e2fecc9cf8ee`,
is deployed with explicit `INVITE_ONLY=true` in the protected `app.env`.
Migration 0060 preserves identities, workspace ownership, passcodes and meeting
records. Existing owners are not automatically promoted. Only explicitly
invited hosts may create workspaces/sessions; workspace administration also
requires ownership. Participant is the default invitation role.

The reviewed image was built off-host for linux/amd64 and loaded by archive.
Local verification of this exact application source passed all 1775 frontend
tests, build/lint, Go vet, the full real-database Go race suite with
TEST_DATABASE_URL set and no opt-out, and ten scoped invitation guard mutations.
The delivered binary vulnerability scan was repeated immediately before rollout
and found no vulnerabilities. GitHub Actions has no run for this fork commit;
these are local execution results, not a claim of hosted CI success.

Public writes were paused for the final backup and migration. Fresh custom-format
preflight and cutover backups were encrypted before off-host persistence, copied
to both hosts, decrypted and fully restored into isolated scratch databases.
The actual delivered image migrated those restores from schema 59 to 60 with
unchanged hashes/counts for eight protected tables and zero automatic hosts.
The production cutover matched those protected hashes too. The previous image
and configuration remain available; signing/session secrets were retained.

Private backup/evidence directory on the Studio:
`/Users/matthew/.local/share/scrum-invitations-deploy-20261026/`.
Encrypted backups on Hetzner:
`/opt/apps/scrum-pro/backups/invitations-{preflight,cutover,postdeploy}-20261026.dump.enc`.
Configuration before rollout is retained in protected
`/opt/apps/scrum-pro/backups/invitations-20261026/`, with an encrypted off-host
configuration archive in the Studio evidence directory. Recovery-key custody
remains separate as documented above. The postdeploy encrypted database backup
was fully restored at schema 60 after test data cleanup.

The app manifest and backup coverage already register Scrum Pro in the homelab
repository. Nightly NAS artifacts for 20261026_040006 include the full database
dump and protected configuration archive. The full-database backup includes
hosting_grants and workspace_invitations without a backup-job change. The Home
Lab orchestrator was notified of this rollout and recovery boundary.

Live HTTPS verification passed: invitation-only auth configuration, anonymous
homepage on desktop/mobile, no horizontal overflow or browser errors, participant
invitation acceptance, five direct participant authorization denials, owner-only
passcode/open controls, revocation, and explicit host delegation followed by
workspace creation and further invitations. Two separate browsers received WSS
vote/reveal updates. A database-and-app stop/start preserved both identities,
workspace ownership/passcode, hosting grants and both revealed votes. Test
workspaces, accounts, invitations and hosting grants were removed afterward.
A private operator host invitation remains pending; accept it in the operator's
existing browser identity to preserve access to existing workspaces. The raw link
is held only in the protected Studio runtime directory, never in this repository.

Native post-verification memory sample: app 6.062 MiB plus DB 32.21 MiB, about
38.3 MiB combined, with explicit 128 + 384 MiB limits. Gateway 30.45 MiB and tunnel
38.79 MiB were within their 48/64 MiB limits. All services are healthy, with zero
OOM kills or automatic restarts. This is a small-session sample, not a load test.
The dedicated tunnel/hostname and routing configuration remain unchanged. Shared
host app container IDs and network attachments matched before and after cutover.

### Invitation-era rollback procedure (historical)

Do not merely select the previous image: it refuses schema 60. Keep public writers
stopped and use either a migration-compatible binary or the matching schema 59
cutover backup with the previous image/configuration. Take a new protected backup
before any restore. Reconcile later writes, accepted/revoked invitations, hosting
grants and memberships before exposing a restored store. Restoring the pre-upgrade
backup loses later writes. Setting INVITE_ONLY=false reopens public hosting and
is not a security-preserving rollback. The deployment operator owns rollback.


## Privacy release operations, 27 October 2026

Privacy application source: `873780b2a584dd27dc8e830a6c35fbf4e7f99321`.
Linux/amd64 image:
`sha256:c94af0b9ce4d7e5865ae088b128ad597c70e43d598a270351ea9b3d32adebd76`.
Migrations 0061 through 0063 add opt-in ended-session retention, profile erasure,
link-guest erasure and minimal deletion receipts. Cutover and the live privacy verification completed on 27 October 2026 at
https://scrum.matthew.systems, with database schema 63. The protected evidence
directory is `/Users/matthew/.local/share/scrum-privacy-production-20261027/`.
The application source/image above are distinct from the later operator/docs
commit, which does not rebuild or change the served application.

### Dedicated private logs and startup

All four Scrum containers use the existing dedicated network and Cloudflare
Tunnel. Their syslog driver sends RFC5424micro records to
`unixgram:///run/scrum-pro-logging/syslog.sock`, tags `{{.Name}}`, with a 1 MiB
nonblocking buffer and Docker's local log cache disabled. `docker logs` is no
longer the operational log source. Recreating the old JSON-file containers
removes those obsolete container log caches; the helper never prunes arbitrary
Docker storage paths.

`scrum-pro-logging.service` runs a separate rsyslog process with the system
socket disabled. It accepts only the four Scrum APP-NAMEs and writes root-private
UTC daily files `/var/log/scrum-pro/scrum-pro-YYYY-MM-DD.jsonl`, mode 0600 in a
0700 directory. It uses the standard RFC5424 parser: `UseSpecialParser=off`,
`ParseHostname=on`, and an anchored `$app-name` whitelist. It does not replace
shared rsyslog, Caddy, or any other application's logger.

The dedicated unit has a 32 MiB memory limit, an empty capability bounding set,
AF_UNIX-only networking and restricted writable paths. Its per-unit AppArmor
profile is `unconfined` because the host's binary-attached rsyslog profile covers
only shared paths; the global AppArmor profile is not changed. The unit starts
before Docker, waits at most ten seconds for its socket and makes it mode 0600.
`scrum-pro-stack.service` starts only this Compose project after Docker and the
logger. `PartOf` propagates Docker/logger restarts to this stack. The Docker Wants link is scoped to this logger; other app units are not
edited. Validate configuration and the dependency graph before activation.

Input rate limiting is 200 messages per five seconds per sender across all
severities. Docker's daemon is the expected sender for these four containers.
Bursts or buffer pressure can drop diagnostics; this is not a complete audit
history guarantee. Messages are capped at 16 KiB. The dedicated logrotate
configuration runs each minute with its own private state file, `copytruncate`,
a 10 MiB size threshold and three rotations. The threshold can be exceeded
between runs, and copytruncate can lose messages during rotation. Closed UTC
files and rotations expire seven days from their filename's UTC date. Today's
files are not enrolled while active. No shared logrotate configuration or timer
is changed.

### Journal custody and three independent expiry scopes

The host's `scrum-pro-privacy-maintenance.timer` runs every minute. Its fixed
Docker/psql adapter reads only `scrum-pro-db-1`; no database password is placed
in arguments. It cumulatively exports the 0600 journal to
`/opt/apps/scrum-pro/privacy/journal/deletions.json`, performs a dry validation
before deletion, runs dedicated log rotation, and applies log expiry and the
explicit 30-day encrypted-backup inventory. Host backup enrollment is limited to
named `.dump.enc` and `.tar.gz.enc` files in `/opt/apps/scrum-pro/backups` with
checksum, original creation time and exactly creation plus 30 days. Copying or
redeploying an archive does not restart its retention clock.

The root-private `/opt/apps/scrum-pro/privacy/status.json` reports only instance,
time, journal checksum/count and aggregate expiry results. Any maintenance
failure sets failed status and a nonzero exit. The independent protection checker below sends Healthchecks heartbeats and alerts. A successful API deletion does
not prove the subsequent off-host export has completed.

On the Studio, LaunchDaemon `com.matthew.scrum-pro-privacy` runs every minute as
`matthew`. It lives under `/Users/matthew/.local/share/scrum-pro-privacy`, using
its protected `config.json`, `status.json` and `journal/deletions.json`. It pulls
the fixed host journal/status over SSH, checks private file custody, instance,
checksum, receipt count and freshness (at most five minutes, with 60 seconds
future-clock tolerance), then merges receipts without truncating prior
history. It mirrors the cumulative journal to the NAS and checks acknowledgment.
Host export and Studio pull are serial minute phases: end-to-end custody is
typically within two minutes plus execution/jitter, not a one-minute or
synchronous guarantee.
Previously verified receipts remain locally available on a failed pull; status
still reports failure. Known Studio archives and frozen-volume retirement are
processed independently of pull failure, using validated local enrollment.

Studio encrypted deployment/rollback archives have expiry deadlines no later
than 30 days after original creation; explicitly inventoried closed logs are
renamed `.archived.log` with deadlines no later than seven days. Expiry runs on
the next successful maintenance pass after a deadline. Active preview/server logs are not enrolled as closed
archives. The manifests restrict deletion to named, checksum-matching artifacts
inside the listed Scrum custody directories. Raw signing/key-recovery runtime
configuration is not claimed to be expired by these archive rules.

NAS custody is `/volume1/backups/scrum-pro-privacy/journal/deletions.json`.
The independent root cron entry runs every minute from `/etc/crontab`:

```cron
* * * * * root /usr/bin/python3 /volume1/backups/scrum-pro-privacy/privacy-nas.py expire --apply >/dev/null 2>&1 # scrum-pro-privacy-expiry
```

It scans only valid dated directories under `/volume1/backups/htz-4g-nbg` and
expires only the exact root-private custom-format `scrum-pro-parley.dump` when
its recorded file mtime is 30 days old. It validates the PostgreSQL header,
computes a checksum and rechecks file identity before unlinking, preserves unexpired dumps and
leaves other apps' files, shared config tarballs and directories untouched.
This NAS dump is protected as a secret; it is not described as an encrypted
archive. NAS expiry does not depend on the Studio's sync or the host exporter
succeeding. Its aggregate `expiry-status.json` and minimal audit remain under
NAS privacy custody. Both NAS and Studio journal receipts must outlive every backup
that could resurrect their objects; neither journal is expired by these tools.

### Privacy recovery and rollback at schema 63

Keep all writers, schedulers, workers and public ingress stopped while restoring.
Use a schema-63-compatible binary and replay the latest independently held
cumulative deletion journal before reopening the store. Verify its deployment
instance and freshness, reconcile any historical owner/admin handoff, and also
reconcile revocations and permissions not represented by deletion receipts.
A wrong instance, malformed journal, stale/missing custody or unresolved handoff
is a reason to keep the service isolated, not to bypass checks.

The invitation image at schema 60 cannot run directly against schema 63.
Restoring a pre-upgrade backup still requires a schema-63-compatible migration
and binary, plus the latest erasure decisions before exposure. It is recovery
from an older data snapshot, not permission to serve with the former binary.
Merely selecting the old image or setting INVITE_ONLY=false is not a
privacy-preserving rollback. Preserve a fresh protected backup before
starting recovery. The former Studio frozen database is stale and expires on
2026-11-20 at 23:58 UTC; do not activate its old connector or mistake it for a
current rollback store. Original raw runtime configuration remains separate
protected recovery-key custody.

Neither row deletion nor filesystem unlink is a physical media-sanitization
claim. External exports/integrations, arbitrary plugin copies, shared-content
mentions, analytics retained elsewhere and independent shared backup artifacts
need their own reviewed treatment. See `docs/privacy-operations.md` for operator
commands and the validation boundaries. Keep live rollout/backup/restore evidence
in the protected production release directory, outside Git.


### Completed privacy rollout verification

The deployed source, immutable image digest, schema 63 and HTTPS readiness were
verified. Two separate browser identities cast distinct votes and both received
live reveal updates through WSS. Host retention changes returned 200, participant
changes returned 403 and the last-owner profile erasure was refused with 409.
The profile erasure UI removed its personal rows while preserving the other
participant's vote and shared story. Ending/erasing the temporary workspace,
its two sessions and the test host profile produced five deletion receipts.

A full restart of the owned Scrum stack, including Postgres, preserved the
snapshots, retention policy, deletion receipts and instance UUID. Shared host
application container IDs/network attachments stayed unchanged. All owned
services are healthy; no OOM kill or automatic restart was observed. This is a
scoped stack restart and dependency validation, not a claim of a host reboot
recovery test. Restarting only the dedicated logger also automatically restarted
the dependent stack through `PartOf`, without a manual application start; data
and receipts were preserved.

Without manually kicking their schedules, the host and Studio minute jobs
copied all five receipts to the host/Studio/NAS journals with identical bytes.
The independent NAS expiry job also reported successful status. This verifies
the scheduled path for the observed run; ongoing failures still require status
inspection. The subsequent protection-alert rollout below adds live notifications.

A real pre-erasure production snapshot was fully restored into an isolated local
database. Replaying the latest automatically synchronized Studio journal removed
the temporary workspace, sessions, profiles and personal contributions again.
The second replay was idempotent, and the six original protected table hashes
remained unchanged. A fresh postdeployment backup was copied off-host and fully
restored at schema 63. The latest Python 3.14 operator suites passed 57 checks,
plus all 18 foundation maintenance tests. The docs site build passed separately.

Post-QA native memory sample: app 5.59 MiB + DB 31.84 MiB = 37.43 MiB within the
128 + 384 MiB caps; gateway 10.14 MiB, tunnel 16.87 MiB and dedicated logger about
1.1 MiB were within their 48/64/32 MiB limits. These are small-session samples,
not load-test results. Operator maintenance has its own explicit memory limit.


## Protection alerts, 27 October 2026

The independent Studio LaunchDaemon `com.matthew.scrum-pro-protection` runs
`privacy-alerts.py` every 60 seconds as `matthew`. It reads only protection
metadata over bounded SSH requests and never runs a backup, expiry operation,
SQL query, or journal replay. Existing maintenance jobs remain independent.

| Healthchecks name | Failure condition |
| --- | --- |
| Scrum Pro backup freshness | No private custom-format Scrum dump in a dated NAS snapshot with the final `docker-ps.txt` artifact, or its capture mtime is over 30 hours old, over 60 seconds in the future, too small, or has the wrong header. |
| Scrum Pro expiry jobs | Failed/stale host maintenance, stopped dedicated logger/timer, failed/stale Studio expiry, or failed/stale independent NAS expiry. Success timestamps must be no more than five minutes old. |
| Scrum Pro deletion journal sync | Failed/stale host export or Studio/NAS sync; missing/invalid journal or wrong instance; or a journal/status/mirror mismatch that persists for more than five minutes. |

All three checks use the existing devops Telegram channel. The checker pings
healthy or `/fail` every run; Healthchecks sends failure/recovery notifications
on state changes. An explicit failed result is reported on the next checker
run, normally within a minute. Stale status and persistent divergence alerts
occur after five minutes plus the next poll. The journal/status files are
published separately; each transient mismatch has its own durable grace clock.
Those clocks are saved before any green heartbeat, so a broken state file
cannot make the checker forget divergence indefinitely.

Each external check has a 60-second period plus 240-second grace. If the
checker, Studio, interpreter, SSH collection, or notification transport stops
producing valid heartbeats, Healthchecks independently raises a missed-run
alert about five minutes after the last success. A stopped checker can cause
all three alerts. The delivery path still depends on Healthchecks and Telegram;
it does not prove that a phone displayed or a person read a notification.

Runtime source/config/status are under
`/Users/matthew/.local/share/scrum-pro-privacy/`:
`privacy-alerts.py`, private `alerts.json`, and private `alerts-status.json`.
The config has version 1 and a `checks` object with `backup`, `expiry`, and
`journal` canonical HTTPS Healthchecks ping URLs. Ping UUIDs are capabilities:
keep them mode 0600, out of Git, reports, logs and chat. The checker reads the
existing `config.json` for deployment identity and the fixed NAS SSH target.
Only fixed diagnostic codes leave in ping bodies; no meeting content, user IDs,
passcodes, database credentials, journal records, or ping URLs are sent.

For a new installation, create the three checks in the existing Healthchecks
project, attach its enabled Telegram channel explicitly, set period/grace to
60/240 seconds, then install the config, script and LaunchDaemon. Run the
checker manually and verify all three checks are up before considering them
armed. Install only the new plist in `/Library/LaunchDaemons`; no app/DB restart
or shared service change is required. Inspect the private checker status and
`sudo launchctl print system/com.matthew.scrum-pro-protection` for run/exit state.

Before intentionally disabling/uninstalling the checker, pause its three checks
in Healthchecks first. Otherwise missed-heartbeat alerts are expected. To
resume, load the daemon and verify fresh green pings; do not disable the
underlying privacy jobs merely to silence an alert. Recover a failing job,
verify its data and status, and allow the next normal check to send recovery.

Monitoring checks backup freshness/header/size and the final snapshot artifact;
it does not perform a full restore every minute or prove physical erasure.
Retain scheduled restore drills and the independent deletion-journal recovery
procedure. The existing application source/image and schema are unchanged by
this monitoring rollout.

## Bundled usage analytics gate

The frontend replaces the legacy `/analytics.js` bootstrap with one bundled
adapter (`web/src/lib/analytics.ts`) initialized from `main.tsx`. Public
`meta[name="app-analytics"]` in `web/index.html` restricts the website ID to
`scrum.matthew.systems`. Keep `data-named-events="false"` until plan005 custody
and plan006 release evidence pass. This switch is public deployment
configuration, not a secret or an authorization boundary. No server environment
reader or endpoint change is introduced here. Gateway `/a/script.js` and
`/a/api/send` stay unchanged; do not independently activate or reroute a shared
collector based on this frontend change.

The adapter uses the Umami3.0.3-compatible manual-track/before-send interface,
with automatic tracking disabled to avoid duplicate SPA events. Route changes
and initial readiness share one page-attempt deduplication path. Only fixed
page categories, fixed title and empty referrer leave the projection. DNT and
browser-local `umami.disabled` are rechecked for every attempted send; denied
storage fails closed absent an explicit active-document choice. **Usage
privacy** is reachable without identity, including standalone guest/link and
presentation routes. Delivery failures drop signals without retry or persistent
queue. Existing analytics is not erased by this control.

The accepted90-day raw analytics policy remains an operator obligation distinct
from app-content erasure. No collector expiry/backup/restore guarantee is
established by these client tests. Keep expanded events off until the separately
reviewed collector custody changes and deployed ingestion/negative tests pass.

### Private Go relay activation gate

Plan007 adds a default-off relay in the app; this source change does **not**
activate it or change Caddy. At the separately validated cutover, remove only
the dedicated Caddy `/a` direct-upstream handlers so its existing app fallback
reaches `/a/script.js` and `/a/api/send`. Never expose native collector/DB ports.

Enable `ANALYTICS_RELAY_URL=http://scrum-analytics-collector:3000` together with
`ANALYTICS_RELAY_STATE_DIR=/run/parley-analytics` only after Homelab228–231 and
app005/006 acceptance. Mount the whole operator-owned directory read-only (no
single-file bind/subPath). The runtime schema and maintenance contract are in
`docs/analytics/relay.md`. The operator must independently hash `/parley` from
the installed immutable image and verify the running container uses it without
an executable override. That SHA256 becomes `app_build`; Version is display
metadata. No ready receipt is manufactured by the app, and an unavailable
fingerprint disables only analytics. No raw analytics backup is authorized here.
