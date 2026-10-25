# Scrum Pro host invitations

This fork defaults to `INVITE_ONLY=true`. The API requires an active hosting
grant in the target organization to create a workspace or session. Workspace
administration additionally requires ownership. An organization admin is not
automatically a host, and a host in one organization gains nothing in another.

A participant invitation grants membership of one workspace. A host invitation
grants hosting in its organization and ownership of that workspace. Only a
current host who owns the workspace can issue, list or revoke invitations.
The dropdown defaults to Participant; mint requests omitting role do too.

Each invitation has a cryptographically random 256-bit token; only its SHA-256
digest is stored. The link places the raw token in a fragment. The browser
removes that fragment and uses a sessionStorage handoff bounded to 15 minutes
for sign-in redirects. Tokens are never returned by listing or placed in
security logs. Invites expire after seven days. Acceptance and revocation lock
the same row; a link can be accepted once, including concurrent requests.
Acceptance rechecks the issuer's current hosting, ownership and active org
membership. A revoked org membership cannot be resurrected by acceptance.
Participant acceptance cannot downgrade or upgrade an existing host grant.

There is no public bootstrap route or first-visitor ownership. An operator
with database configuration runs `parley -create-host-invite` (optionally
`-invite-org <slug>`) to issue a first host link. Keep stdout private: it is the
capability URL. Startup diagnostics remain on stderr for this command.
Existing identities are not automatically promoted. Before production rollout,
issue/accept host invitations for the trusted operators/owners who must keep
hosting. Existing ownership and meeting data remain unchanged.

Old passcodes and open-space links cannot admit a new member in invite-only
mode. Existing memberships can rejoin. Session-bound guest links still allow
participation in their one room, never hosting or workspace invitations.
Embedded-session credentials cannot issue, inspect or accept workspace invites.
Identity cookies keep the existing 90-day default: anonymous identities are
browser-specific and have no cross-device account recovery. OIDC remains
available for durable sign-in; invitations also work across its redirect.

`INVITE_ONLY=false` explicitly retains legacy open hosting and passcode entry.
Do not deploy this fallback as a security rollback without acknowledging that
it reopens public hosting. Database migration 0060 is append-only. To roll back
code after it runs, keep a migration-compatible binary; older binaries refuse
a database ahead of their migrations. Back up the full database first. Hosting
grants, invitation use/revocation and organization tombstones must be reconciled
if an older backup is restored, so revoked permissions/links do not return.
The existing full logical NAS database backup automatically includes both new
tables; raw invitation tokens need no recovery store.

Verification includes direct API denials, default role and role escalation,
delegated hosting, cross-org checks, expiry/revocation/replay, acceptance races,
org tombstones, guest/embedded route classification, frontend role selection,
fragment removal/retry, and local browser flows. Execution results and local
preview details are recorded outside Git under the task's protected runtime
folder. This is a scoped feature check, not a general security certification.

## Production release procedure

Policy for this deployment: only explicitly invited hosts. Do not backfill host
permissions from legacy workspace ownership, organization membership or admin
status. Existing memberships, ownership, passcodes and meeting records remain.
Workspace hosting permission and the facilitator role in an existing meeting
are separate: this feature gates workspace/session creation and workspace
administration, not the existing facilitator handoff and recovery controls.

Before changing production, build the linux/amd64 artifact off-host from the
reviewed commit and record its immutable digest. Run the complete database
suite using the CI toolchain (`GOTOOLCHAIN=go1.26.9 go test -p 1 -race ./...`),
with a real `TEST_DATABASE_URL`, without the database opt-out; build and test
the frontend first. Boot the delivered image against an isolated restored
production backup, with connectors and scheduled/external effects isolated.
Compare existing identities, owner memberships, passcodes and meeting state.
Confirm zero automatic host grants immediately after migration.

Take a fresh custom-format database backup and encrypt it before persisting
it off-host. Verify decryption, archive readability and an isolated restore.
Keep the current runtime configuration and immutable image reference. Check
that the nightly NAS backup has a recent `scrum-pro-parley.dump` and protected
config archive; source code or a registered backup target is not proof it ran.
Both new tables are included by the existing full-database dump. Do not print
row data, token hashes, environment values or invite URLs in evidence logs.

Pause public writes and stop every old app replica before migration 0060.
Keep the dedicated ingress, shared Caddy and other applications unchanged.
Start the reviewed image with `INVITE_ONLY=true` and verify `/api/auth`,
`/version` and readiness. Use the operator bootstrap command to issue a private
host invitation. The operator accepts it in their existing browser identity
when retaining ownership of existing workspaces. A new anonymous identity
will not inherit those workspaces. Issue normal host invitations only to
chosen hosts; verify participant creation/admin calls return 403. Test two
browser identities, live voting/reveal, revocation and restart persistence
before widening access.

Acceptance holds the issuer's active organization membership, hosting grant
and workspace ownership under row locks until commit. Revocations already in
progress are observed before a grant is applied. Deadlock victims retry up to
three complete transactions. Expiry is checked against wall-clock time at
consumption, including time spent waiting for a lock. An original recipient
may retry an accepted invitation until its expiry, provided their membership
is still active. This returns a receipt without reapplying permissions; another
identity cannot reuse the link, and preview remains unavailable after use.

## Operator recovery and revocation

Open mode uses browser-specific identities. Losing the browser cookie loses
that identity; a new display name is not proof of ownership. Use OIDC when
cross-device sign-in and identity-provider recovery are required. Invitations
work with either mode; never silently link accounts by name or email.

A trusted operator can generate a new bootstrap host invitation to recover
hosting access. For workspace ownership recovery, verify the person and exact
organization/workspace separately. Prefer a current owner issuing a host
invitation to that workspace. If every owner has lost access, the database
operator must deliberately grant ownership to an identified full account in
the selected workspace, preserving incumbent owners. Do not add a public
claim/recovery endpoint or promote the first visitor. Record the selected
organization, workspace and account IDs in protected incident evidence.

To remove hosting without removing participation, the operator deletes that
account's `hosting_grants` row for the exact organization. Pending invitations
issued by it become unavailable immediately; explicitly mark them revoked in
the same transaction if keeping a permanent revocation record is required.
Reissuing hosting does not restore invitations already marked revoked.
This does not remove workspace membership or an existing meeting's facilitator
role. To remove all access, use the existing organization/member revocation
procedure, preserving its last-owner/last-admin safeguards and socket eviction.
A recipient retry cannot restore a deleted hosting grant.

Rollback after migration requires a migration-compatible binary or restoring
the matching pre-upgrade backup with all public writers stopped. Restoring
an older backup discards later writes and can resurrect revoked/accepted
invitations and memberships. Reconcile those changes before reconnecting
public ingress. `INVITE_ONLY=false` is an explicit reopening of public hosting,
not a security-preserving rollback.
