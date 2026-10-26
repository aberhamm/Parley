# Privacy deletion and recovery operations

These controls distinguish deleting application data from expiring recovery
copies. Deleting a live session/workspace does not reach into an old database
dump, someone else's CSV export, an external integration, analytics, or a
container log. Removing a file is a filesystem unlink, not a claim of physical
secure erasure of SSD blocks or storage-provider replicas.

The local privacy implementation supplies minimal database deletion receipts and
`scripts/privacy-maintenance.py`. This tool uses Python's standard library plus
`psql`; it installs no scheduler and changes no production configuration.
Production log/archive expiry must be explicitly enrolled and verified before
promising a time limit to users. Existing size-bounded Docker logs are not a
calendar-based retention policy.

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
`.gpg`, and archived JSON logs ending `-json.log.<number>` or `.jsonl`. Active
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

Before enabling production enforcement, inventory every manual deployment
backup, rollback database/volume, local restore, offsite replica and log archive.
Enroll eligible archive files with a reviewed expiry, and handle database
volumes through their own deliberately scoped procedure. This file tool cannot
expire a running/frozen database volume, external analytics rows, NAS snapshots
or copies held by other people. Existing unlisted copies require separate
reconciliation. Keep recovery keys until their last permitted encrypted backup
has expired, then retire them through the operator's key-custody procedure.

Schedule the reviewed command in the operator's existing maintenance system and
alert on a nonzero exit; no schedule is installed by this change. Verify a run
actually deletes a disposable expired artifact and preserves an unexpired one
before making a production retention promise. Do not claim that configuration,
a manifest, a successful dry run or an encrypted backup alone proves deletion.

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
