# Privacy deletion and recovery operations

These controls distinguish deleting application data from expiring recovery
copies. Deleting a live session/workspace does not reach into an old database
dump, someone else's CSV export, an external integration, analytics, or a
container log. Removing a file is a filesystem unlink, not a claim of physical
secure erasure of SSD blocks or storage-provider replicas.

The application supplies minimal database deletion receipts and the generic
`scripts/privacy-maintenance.py` operator tool. The generic tool installs no
scheduler. The Scrum Pro deployment additionally supplies dedicated host,
Studio and NAS helpers with explicitly scoped scheduling and expiry policies.
Their policy is described below. The 27 October 2026 deployment record verifies
activation and the live checks; a manifest or source file alone would not prove
that expiry or off-host journal replication ran successfully.

## Keep deletion decisions outside database backups

`privacy_deletions` contains only `kind`, object UUID and deletion time. It records
session, workspace (`space`) and profile erasure decisions in the transaction
that performs them. `privacy_meta` carries a unique instance UUID, preserved by a
full database backup. A receipt is recovery data, not a copy of erased meeting
text, names, tokens or passcodes. Treat its identifiers as private nevertheless.

Export a cumulative journal into a dedicated directory owned by the operator,
mode 0700. Store it separately from the database backups it can reconcile. Keep
its off-host copy protected, with access independent of a compromised or lost app
host. The file is written atomically, mode 0600; existing records are merged so a
restored older database cannot truncate known deletion decisions. Journal limits
are 10 MiB and 100,000 receipts; a limit failure leaves the existing file intact
and needs an operator-reviewed archival strategy, not a reset to an empty file.

```sh
mkdir -p /private/operator-custody/scrum-pro
chmod 700 /private/operator-custody/scrum-pro
# Set DATABASE_URL from protected runtime configuration; never paste it in logs.
python3 scripts/privacy-maintenance.py export \
  --journal /private/operator-custody/scrum-pro/deletions.json
```

The tool splits a PostgreSQL URI into libpq environment fields rather than
putting connection credentials in command arguments, and suppresses raw
database error output. Unknown/duplicate connection options are refused rather
than silently dropping a TLS setting. Do not enable shell
tracing, publish its environment, or use a wrapper that prints credentials.

Export and replicate the journal frequently, after a deletion operation and
before taking a controlled cutover backup. Verify the off-host copy matches by
checksum. A successful database receipt does not prove a later off-host export
succeeded. Track/export failures; do not claim disaster-recovery erasure beyond
the most recent verified journal copy. The export interval is an operator
recovery boundary. The journal must outlive every backup/rollback copy that
could contain its erased records; do not expire it as a content log.

## Reapply deletions before exposing a restored database

1. Stop every app replica, scheduler and worker. Keep ingress and outbound
   effects restricted. Start only Postgres. Preserve the current database,
   journal and encrypted backup before any restore.
2. Restore the intended backup into the isolated database and apply the
   compatible schema migrations. Do not start the server to perform migrations
   if that would start workers or serve requests under restored grants.
3. Verify the backup belongs to this deployment and obtain the latest protected
   journal independently of the backup. Run replay with the explicit stopped
   writer acknowledgment:

   ```sh
   python3 scripts/privacy-maintenance.py replay \
     --journal /private/operator-custody/scrum-pro/deletions.json \
     --writers-stopped
   ```

4. Replay validates the complete document before any database writes, verifies
   the instance UUID again inside a single database transaction, and invokes
   the same erasure functions as the application. One failed erasure rolls back
   the whole replay. Successful repetition is idempotent. A profile that was
   allowed to erase after an ownership handoff may be a last owner/admin in
   an older backup. Reconcile that verified handoff first; do not reopen
   access or bypass the guard merely to get a successful command.
5. Also reconcile authorization changes not represented by deletion receipts:
   token/link/invitation revocations, memberships, hosting grants, plugin grants,
   connections and queued deliveries. This journal is not a general permission
   change log. If reliable later records are unavailable, keep the service
   isolated and choose a conservative reset with deliberate reauthorization.
6. Verify deleted IDs/content are absent, old credentials fail and unrelated
   records still exist. Re-export the cumulative journal, then start the app
   under restricted ingress/egress and verify HTTP/WebSockets. Reopen only after
   the recovery checks pass.

A wrong instance UUID fails without replay. Backups from before the privacy
migration have no matching instance metadata after a fresh migration; do not
silently rewrite the journal or accept an unrelated database. The operator must
verify the source deployment and deliberately reconcile its metadata/deletions
before exposure. With no trustworthy journal, fail closed rather than claiming
that a restored database respects later erasure requests.

## Enforce expiry only on enrolled archives

The expiry command accepts an exact manifest for one private directory, not a
wildcard, recursive search or general cleanup command. It permits encrypted
`.dump`, `.sql` and `.tar.gz` backup/rollback archives ending in `.enc`, `.age` or
`.gpg`, archived JSON logs ending `-json.log.<number>` or `.jsonl`, and
explicitly closed plain-text archives ending `.archived.log`. Historical plain
logs must be deliberately renamed to that closed suffix, with the original
filename/creation-time mapping retained in protected enrollment evidence. No
automatic plain `.log` scan is authorized. Active
Docker `*-json.log` files, keys, directories, symlinks, hardlinks, traversal paths
and the tool's own recovery/audit files are refused. Never point this at the
Docker daemon's storage directory. Use the runtime's supported rotation and
place owned, closed log archives in managed custody before age-based expiry.

Every enrolled artifact must name its type, creation and expiry in UTC, and a
SHA-256 checksum. The directory and manifest must be operator-owned and private
(0700/0600), as must the files. Files not listed are never removed. A mismatch
or malformed entry aborts validation before any deletion begins. Runtime races
or I/O failures stop subsequent deletions and leave a minimal audit trail;
file deletion is not an all-or-nothing transaction across a directory.

Example manifest, with illustrative dates and checksum only:

```json
{
  "version": 1,
  "owner": "scrum-pro-privacy-maintenance",
  "artifacts": [
    {
      "path": "predeploy.dump.enc",
      "kind": "backup",
      "created_at": "2026-10-26T00:00:00Z",
      "expires_at": "2026-11-25T00:00:00Z",
      "sha256": "replace with the actual lowercase 64-character checksum"
    }
  ]
}
```

Review the default dry run first:

```sh
python3 scripts/privacy-maintenance.py expire \
  --directory /private/managed-scrum-archives \
  --manifest /private/managed-scrum-archives/manifest.json
```

Only after reviewing the exact filenames and policy, apply it:

```sh
python3 scripts/privacy-maintenance.py expire \
  --directory /private/managed-scrum-archives \
  --manifest /private/managed-scrum-archives/manifest.json --apply
```

The command removes only checksum-matching files whose explicit expiry has
passed, preserving unexpired files. It writes minimal planned/deleted records
without content to `privacy-expiry-audit.jsonl`, mode 0600. Protect that audit
separately and give it its own reviewed lifecycle. Missing listed files are
reported without being recreated. A dry run does not remove files.

Before enrolling additional copies, inventory every manual deployment
backup, rollback database/volume, local restore, offsite replica and log archive.
Enroll eligible archive files with a reviewed expiry, and handle database
volumes through their own deliberately scoped procedure. This file tool cannot
expire a running/frozen database volume, external analytics rows, NAS snapshots
or copies held by other people. Existing unlisted copies require separate
reconciliation. Keep recovery keys until their last permitted encrypted backup
has expired, then retire them through the operator's key-custody procedure.

For another deployment, schedule the reviewed command in the operator's
maintenance system and alert on a nonzero exit; the generic CLI does not install
that schedule. Scrum Pro uses the dedicated units/daemon/cron described below. Verify a run
actually deletes a disposable expired artifact and preserves an unexpired one
before making a production retention promise. Do not claim that configuration,
a manifest, a successful dry run or an encrypted backup alone proves deletion.


## Scrum Pro deployment policy

The privacy release artifact is application source
`873780b2a584dd27dc8e830a6c35fbf4e7f99321`, linux/amd64 image
`sha256:c94af0b9ce4d7e5865ae088b128ad597c70e43d598a270351ea9b3d32adebd76`.
It is deployed with database schema 63. The 27 October 2026 live checks passed:
HTTPS, distinct-vote two-browser WSS updates, role/last-owner denials, profile
erasure preserving unrelated contributions and full owned-stack restart
persistence. Scheduled host/Studio/NAS journal copies converged on the same five
receipts without manual kicks, and independent NAS expiry status was observed.
A real pre-erasure production snapshot was restored locally, reconciled with the
automatically synced journal and replayed twice; deleted test data stayed absent
and six original protected table hashes were preserved. The fresh postdeploy
backup was copied off-host and fully restored at schema 63. See protected
evidence in `/Users/matthew/.local/share/scrum-privacy-production-20261027/`.
These observations verify the executed checks, not every future maintenance run
or a host reboot recovery test.

| Data/copy | Scoped retention mechanism |
| --- | --- |
| Hetzner encrypted deployment/config backups | Explicit checksum-pinned `.dump.enc` / `.tar.gz.enc` inventory in `/opt/apps/scrum-pro/privacy/backup-manifest.json`; declared creation plus 30 days. |
| Studio encrypted deployment/rollback archives | Exact manifests in the fixed Scrum custody directories; at most 30 days from original creation, never reset by copying. |
| Private host logs | Dedicated daily UTC JSON files and three size rotations; eligible closed files expire seven days from their filename date. |
| Studio historical closed logs | Explicit `.archived.log` enrollment with original creation time plus at most seven days; active server/preview logs are not enrolled as closed. |
| NAS Scrum database dumps | Exact `scrum-pro-parley.dump` only, in validated dated htz-4g directories, after recorded mtime reaches 30 days. Shared tarballs and other apps' backups remain untouched. |
| Frozen former Studio production volume | Pinned `parley-local_parley-data` rollback volume, expires 2026-11-20 at 23:58 UTC. Old container shells/log caches have been removed after verified backup. |
| Deletion journals and recovery-key configuration | Journals are not expired by content policies. Raw `/Users/matthew/.local/share/parley-local` configuration remains protected signing/key custody; it is not scheduled for deletion. Encrypted legacy config archives have separate 30-day enrollment. |

Expiry occurs on the next successful scheduled maintenance pass after a declared
deadline. Failures/outages must remain visible; do not describe a target period
as proof that an inaccessible or failed maintenance target has already erased
data. The schema-63 application and latest cumulative journal remain the
recovery authority even while older rollback copies approach expiry.

### Host scheduling and private logging

`scrum-pro-logging.service` is a dedicated 32 MiB rsyslog instance listening only
on `/run/scrum-pro-logging/syslog.sock`. It does not claim the system syslog
socket or edit shared rsyslog/Caddy. All four Scrum containers send
RFC5424micro through a nonblocking 1 MiB buffer, with Docker's local log cache
disabled. Standard parsing (`UseSpecialParser=off`, `ParseHostname=on`) and an
anchored `$app-name` filter select only Scrum's four service names. The root
0700/0600 output is `/var/log/scrum-pro/scrum-pro-YYYY-MM-DD.jsonl` in UTC.

The dedicated AppArmor override applies only to that unit; the shared profile
is not edited. The unit still has strict writable paths, AF_UNIX-only sockets,
no capabilities and no-new-privileges. It starts before Docker and waits at most
ten seconds for its private socket before permitting the scoped
`scrum-pro-stack.service` startup.

`scrum-pro-privacy-maintenance.timer` runs every minute. Its helper exports the
cumulative journal, invokes only the private logrotate config/state, validates
both archive sets without deletion, then applies expiry. Logrotate uses
copytruncate, a 10 MiB threshold and three rotations; the threshold can be
exceeded between minute runs and copytruncate can lose messages. Input rate
limiting is 200 messages per five seconds per sender across all severities;
bursts or buffer pressure can drop diagnostics. These are bounded operational
logs, not a complete audit-history promise.

Host status is `/opt/apps/scrum-pro/privacy/status.json`; the independent
journal is `/opt/apps/scrum-pro/privacy/journal/deletions.json`. Status contains
only timestamp, instance ID, journal checksum/count and aggregate expiry
metadata. A failure returns nonzero and failed status. The independent protection checker described below monitors these statuses and sends alerts. No arbitrary Docker log
paths or other apps' archives are pruned.

### Studio and NAS custody

LaunchDaemon `com.matthew.scrum-pro-privacy` runs every minute as `matthew` from
`/Users/matthew/.local/share/scrum-pro-privacy`. Its protected `config.json`
enrolls the exact local manifests and frozen-volume identity. The helper checks
the host export's instance, checksum, receipt count, private custody and
freshness (five-minute maximum, plus 60-second future-clock tolerance), then
atomically merges receipts locally and mirrors them to NAS custody at
`/volume1/backups/scrum-pro-privacy/journal/deletions.json`.

A sync failure preserves verified local receipts and reports failure. Known
Studio expiry is evaluated independently against validated local manifests even
if the remote pull fails. Inspect `sync_status`, `expiry_status`, `nas_mirror`
and `last_success` in the Studio's private `status.json`, rather than assuming
that one successful subprocess proves every phase succeeded. Host export and Studio pull are serial minute phases, so end-to-end off-host
custody is typically within two minutes plus execution/jitter. It is not
one-minute or synchronous delivery.
Before a controlled restore, obtain and verify the latest complete journal.

NAS dump expiry has its own minute root cron entry in `/etc/crontab`, independent
of Studio pull or host export success:

```cron
* * * * * root /usr/bin/python3 /volume1/backups/scrum-pro-privacy/privacy-nas.py expire --apply >/dev/null 2>&1 # scrum-pro-privacy-expiry
```

It validates the dated private directories and exact Scrum dump, checks its
custom-format header, computes a checksum and rechecks file identity before
unlinking an expired dump. It never removes shared `config.tar.gz`, another
app's data or the dated directory itself. This NAS dump is a root-private
custom-format archive, not an encrypted backup claim. Inspect its independent
`expiry-status.json` and minimal audit under NAS privacy custody. A missing or
failed journal mirror does not extend the lifetime of an already-expired NAS
dump. Journals must outlive every backup capable of resurrecting erased objects.

### Schema-63 recovery boundary

An old schema-60 invitation binary cannot start against schema 63. Keep writers,
workers and public ingress stopped, use a compatible binary/migration path,
reconcile historical handoffs and other later permission changes, and replay
the latest independently held cumulative deletion journal before exposure.
Returning an old backup to service without replay can restore erased content
and credentials. Merely selecting an old image or setting INVITE_ONLY=false is
not a privacy-preserving rollback. Backups predating privacy metadata require
verified operator reconciliation of instance identity; never silently adopt an
unrelated database UUID. Take a fresh protected backup before recovery and keep
failed reconciliation isolated.

The raw original runtime configuration and separate encryption/signing keys are
recovery dependencies, not meeting-content archives. Do not delete them under
content-expiry rules or assert that their continued protected custody restores
erased profiles/content. The frozen old Studio database is stale until its
scheduled volume retirement; never reactivate its old connector.

## Local verification

```sh
python3 -m unittest discover -s scripts/tests -p test_privacy_maintenance.py
```

The automated tool tests operate on disposable temporary files and fake SQL
transport. They verify dry-run/apply behavior, exact expiry, encrypted/archived
file types, checksum and file-ownership checks, path/link refusal, cumulative
journal preservation, malformed/wrong-instance refusal, transaction construction
and credential custody. Real-database restore/replay evidence is recorded
separately for the local review; the unit suite alone does not prove SQL erasure
functions or production backup/log deletion.

The explicit local-container drill uses only synthetic records and creates then
drops `scrum_privacy_recovery_test`:

```sh
python3 scripts/tests/privacy-recovery-integration.py \
  --container scrum-invitations-db-20261025
```

It takes a real custom-format backup, deletes session/workspace/profile data,
exports a separate journal, and restores the older dump. It verifies wrong-instance
refusal, all-or-nothing replay when an old ownership handoff is missing, successful
replay after verified handoff, unrelated data preservation, guest identity/token
cleanup and repeated replay. The actual CLI transport is exercised through the
local container's psql, without installing host database tools. It does not contact
production or operate on a production backup.


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


## Separate analytics custody readiness (local checker only)

Application journals, backup rotation and profile erasure do not govern Umami
or locate its anonymous records. The accepted90-day raw analytics boundary
includes owned copies; do not assume a30-day backup grace period. Restored
expired data, unknown exports/caches and missed expiry deadlines keep analytics
readiness blocked, even after admission is closed.

See `docs/analytics/collector-readiness.md` for the offline24-hour app005 receipt
schema and operator/private evidence handoff. Its hash-bound proof references
must be inspected by the accountable operator and a DIFFERENT reviewer; byte
matching does not attest proof contents. Actual Homelab229 expiry,230 copy and
restore reconciliation, and231 installed collection-off phase receipts remain
missing/blocked in this local phase. The checker cannot perform their work,
create a runtime lease or clear app005's operational block. Runtime007 uses a
separate maximum60-second lease and actual loaded-executable fingerprint;
maintenance still requires non-ready publication, at least6seconds, collector
exit and DB writer drain before purge. No production behavior is changed here.
