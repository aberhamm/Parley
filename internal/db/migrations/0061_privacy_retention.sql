-- Opt-in ended-session retention and minimal deletion receipts. Receipts have
-- no foreign key: restoring an old backup must not resurrect deleted objects.
create table privacy_meta (
    singleton boolean primary key default true check (singleton),
    instance_id uuid not null default gen_random_uuid()
);
insert into privacy_meta default values;
create table privacy_deletions (
    kind text not null check (kind in ('session','space','profile')),
    object_id uuid not null,
    deleted_at timestamptz not null default clock_timestamp(),
    primary key (kind,object_id)
);
alter table spaces add column retention_days integer not null default 0
    check (retention_days in (0,1,7,30,90));

-- Also covers operator SQL and organization purges, not only HTTP handlers.
create function privacy_record_deletion() returns trigger language plpgsql as $$
begin
    insert into privacy_deletions(kind,object_id)
        values (case when TG_TABLE_NAME='sessions' then 'session' else 'space' end, OLD.id)
        on conflict do nothing;
    return OLD;
end;
$$;
create trigger privacy_session_receipt before delete on sessions
    for each row execute function privacy_record_deletion();
create trigger privacy_space_receipt before delete on spaces
    for each row execute function privacy_record_deletion();

-- Replay functions are deliberately idempotent. Shared workspace-level kudos
-- and commitments retain their existing semantics on session deletion; erasing
-- the workspace removes those too. Arbitrary plugin/external copies are not
-- asserted to be erased by these functions.
create function privacy_erase_session(target uuid) returns boolean language plpgsql as $$
declare removed integer;
begin
    delete from sessions where id=target;
    get diagnostics removed = row_count;
    insert into privacy_deletions(kind,object_id) values('session',target) on conflict do nothing;
    return removed > 0;
end;
$$;
create function privacy_erase_space(target uuid) returns boolean language plpgsql as $$
declare removed integer;
begin
    delete from spaces where id=target;
    get diagnostics removed = row_count;
    insert into privacy_deletions(kind,object_id) values('space',target) on conflict do nothing;
    return removed > 0;
end;
$$;
