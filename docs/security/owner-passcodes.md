# Owner-only passcode changes

Scope: the fork's `POST /api/orgs/{org}/spaces/{slug}/passcode` route, based on
upstream commit `376ff9274981b776f65d6d4ffc36368955610c48`. Ordinary membership no longer authorizes rotating
or removing a space passcode. Removing the passcode makes a space open.

The route now uses `requireSpaceOwner`, which resolves the space inside the
request's org and reads the caller's current membership role. The handler uses
that resolved space rather than performing a second lookup. Owners can rotate
or remove the code; ordinary members, including org administrators who do not
own the space, get 403. Nonmembers get 404. Anonymous and signed-link guests
are refused by `RequireUser`, and embedded clients remain refused by the
embedded route allow-list. Existing membership and facilitator permissions are
unchanged. Members can still read and share the current code.

Affected control-register records: P-01 (tenant/object isolation) and P-02
(guest/embedded/admin permissions). These broader controls remain implemented
but unverified; this scoped regression is not a full assessment.

## Verification evidence, October 22, 2026

`TEST_DATABASE_URL` pointed to a dedicated disposable PostgreSQL 16 database.
`PARLEY_SKIP_DB_TESTS` was not used. No live preview data was touched.

- Built the embedded frontend with `npm ci` and `npm run build` before Go tests.
- Before the fix, `go test -p 1 ./internal/api -run
  '^TestPasscodeChangesRequireSpaceOwner$' -count=1` failed: an ordinary member's
  direct rotate request returned 200 instead of 403 and changed the passcode.
- After the fix, the same command passed. It covers owner rotate/open/re-protect success,
  direct member and org-admin-member denial, outsider and anonymous denial,
  demoted and removed owner denial, same-slug space isolation across orgs, and
  unchanged passcodes after refused requests.
- Existing exhaustive `TestLinkGuestRouteTable` and embedded route tests retain
  the passcode route's guest/embedded denial classifications.
- A mutation entry in `scripts/guard-mutation.sh` replaces the owner middleware
  with member middleware. Exercising that exact mutation locally failed: ordinary
  member and org-admin-member rotations returned 200, and the demoted owner's
  request also returned 200. Restoring the guard restored the passing test.
- Focused race checks passed with `go test -p 1 -race ./internal/api -run
  '^(TestPasscodeChangesRequireSpaceOwner|TestLinkGuestRouteTable|TestEmbeddedRouteTable|TestSpacePasscodeGate|TestVisibilityAndPasscodeAreIndependent|TestSpaceRoutesResolveWithinTheDefaultOrg|TestSecurity.*|TestCrossSite.*|TestRequireJSON.*)$'
  -count=1` against a second disposable database. No database opt-out was used.
- `TestEverySpaceLookupIsGated` passed after removing the handler's stale
  direct-lookup classification. Space resolution now occurs in the owner gate.
- `go vet ./...`, the docs site's `npm run build` (including its skip-link
  check), and `bash -n scripts/guard-mutation.sh` passed.

Limitations: no changes to plaintext passcode storage, existing member access,
OIDC identity recovery, or operator authentication and ingress controls. This
record describes local verification of the fork, not an upstream release or
production deployment. The parent integration owns combined full-suite and
browser verification.
