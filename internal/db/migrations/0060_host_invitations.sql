-- Hosting permission is separate from org administration and space membership.
-- No public visitor or legacy account is automatically promoted. Operators
-- bootstrap the first host explicitly with -create-host-invite.
create table hosting_grants (
    org_id uuid not null references orgs(id) on delete cascade,
    user_id uuid not null references users(id) on delete cascade,
    primary key (org_id, user_id)
);

create table workspace_invitations (
    id uuid primary key default gen_random_uuid(),
    token_hash bytea not null unique check (octet_length(token_hash) = 32),
    org_id uuid not null references orgs(id) on delete cascade,
    space_id uuid references spaces(id) on delete cascade,
    issuer_id uuid references users(id) on delete cascade,
    role text not null default 'participant' check (role in ('participant', 'host')),
    created_at timestamptz not null default now(),
    expires_at timestamptz not null default now() + interval '7 days',
    accepted_at timestamptz,
    accepted_by uuid references users(id) on delete set null,
    revoked_at timestamptz,
    check (expires_at > created_at),
    check ((issuer_id is not null and space_id is not null) or (issuer_id is null and space_id is null and role = 'host'))
);
create index workspace_invitations_pending_idx on workspace_invitations (space_id, issuer_id) where accepted_at is null and revoked_at is null;
