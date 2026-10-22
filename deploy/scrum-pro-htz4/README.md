# Scrum Pro on htz-4g-nbg

Production: https://scrum.matthew.systems

Application release: `d6e22b74dbcf21612a0fb35c0f75671de44bf0d1`.
Linux/amd64 OCI image index digest:
`sha256:2c635eed966411b4497eb5915ada5bbcd7cbc8c4c8fb860a07e41dd5dbf8b549`.
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
