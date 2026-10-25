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
