# Scrum Pro on htz-4g-nbg

Production: https://scrum.matthew.systems

Application release: `88049156947c316ce705c4e466250bd73c8e9cae`.
Linux/amd64 OCI image index digest:
`sha256:80a644aa393bcfdda9ffd002d7faa81d4e03b48fd403438066f5e2fecc9cf8ee`.
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

All services have `restart: unless-stopped`, health checks, bounded JSON logs
(10 MB × 3 per service), explicit memory limits, dropped capabilities and
no-new-privileges. App and gateway/tunnel filesystems are read-only.

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
would require another recovery source; these are migration backups, not an
ongoing scheduled backup service.

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

The historical rollback instructions below predate invitation migration 0060.
For the current release, use the invitation rollback procedure at the end of
this document. An old binary cannot start against schema 60.

## Cutover and rollback, 2026-10-22

Cutover completed at approximately 23:58 UTC on 2026-10-21 (01:58 Berlin on
2026-10-22). The old Studio connector, public app, private gateway and local
preview were stopped before the final dump. The original Studio Postgres
container/volume remains intact. The same Cloudflare Tunnel then started on
Hetzner. Cloudflare reported healthy with origin IP only `46.224.225.122`.
DNS and ingress were unchanged.

Old runtime: `/Users/matthew/.local/share/parley-local/`.
Old database volume: `parley-local_parley-data`.
Old app image: `parley-local:scrum-pro-preview` (linux/arm64).
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
- Original Studio data and stopped app/tunnel containers are retained for
  rollback. Migration backups are held on both hosts.

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

### Current rollback procedure

Do not merely select the previous image: it refuses schema 60. Keep public writers
stopped and use either a migration-compatible binary or the matching schema 59
cutover backup with the previous image/configuration. Take a new protected backup
before any restore. Reconcile later writes, accepted/revoked invitations, hosting
grants and memberships before exposing a restored store. Restoring the pre-upgrade
backup loses later writes. Setting INVITE_ONLY=false reopens public hosting and
is not a security-preserving rollback. The deployment operator owns rollback.
