# Scoped Scrum Pro protection monitoring

Affected operator controls: P-10 detection/response and P-11 backup/retention
recovery. This adds deployment monitoring; it is not a verification of the full
incident-response or recovery control, or a change to tenant/API boundaries.

Implementation: `deploy/scrum-pro-htz4/privacy-alerts.py`, its dedicated Studio
LaunchDaemon and `tests/test_privacy_alerts.py`. Existing backup, expiry and
journal writers remain independent. Private ping capabilities are outside Git.
Payloads/statuses contain only fixed reason codes and delivery metadata.

Failure checks reproduce overdue/missing/invalid/future backups; failed/stopped/
stale host, NAS and Studio jobs; wrong-instance or missing journals; failed
mirroring; independent persistent publication-gap timers; malformed endpoints;
failed notification transport; and unwritable local alert state before any
heartbeat. Valid temporary journal/status publication gaps are tolerated;
invalid identity and explicit job failures are not hidden by that grace.

On 27 October 2026 the operator verified three healthy live Healthchecks checks
on the existing devops Telegram channel. A separate, clearly labelled TEST check
received a synthetic overdue-backup failure and recovery; Telegram delivery was
confirmed by successful Notification rows. Withholding only TEST heartbeats
then produced an independent missed-run alert and a second recovery. All four
notifications had successful transport results. The disposable check was paused
afterward; production backup/deletion jobs were never stopped for these tests.
Private evidence: `scrum-alerts-20261027/delivery-proof.json` and the rollout
report under the operator's protected Studio custody.

This proves the observed notification route and missed-run behavior, not future
availability, phone presentation or human acknowledgment. Backup header/size/
freshness checks are not full restore drills. Healthchecks/Telegram availability,
SSH reachability and timely operator response remain dependencies. Pause checks
before intentionally removing their sender. See the deployment and privacy
operations runbooks for thresholds, custody, installation and rollback.
