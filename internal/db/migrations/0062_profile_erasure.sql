-- Retain a non-login placeholder for shared creator/facilitator foreign keys.
-- Names, sign-in identities and attributable personal contributions are erased.
alter table users add column erased_at timestamptz;

create function privacy_guard_erased_user() returns trigger
language plpgsql as $$
declare
    column_name text;
    account_id uuid;
    erased timestamptz;
begin
    foreach column_name in array tg_argv loop
        if tg_op = 'UPDATE' and to_jsonb(new)->column_name is not distinct from to_jsonb(old)->column_name then
            continue;
        end if;
        account_id := (to_jsonb(new)->>column_name)::uuid;
        if account_id is null then continue; end if;
        -- SHARE conflicts with the profile eraser's UPDATE lock, including
        -- non-key changes; KEY SHARE would let the two pass one another.
        select erased_at into erased from users where id=account_id for share;
        if found and erased is not null then
            raise exception 'this profile has been erased' using errcode='P0001';
        end if;
    end loop;
    return new;
end $$;

-- Every current foreign key to users receives the guard. A later migration
-- adding a user-bearing write must add the same trigger and its race test.
do $$
declare relation record;
begin
    for relation in
        select c.conrelid::regclass as table_name,
               string_agg(quote_literal(a.attname), ',' order by a.attnum) as arguments
          from pg_constraint c
          join pg_attribute a on a.attrelid=c.conrelid and a.attnum=any(c.conkey)
         where c.contype='f' and c.confrelid='users'::regclass
         group by c.conrelid
    loop
        execute format('create trigger privacy_active_user before insert or update on %s for each row execute function privacy_guard_erased_user(%s)', relation.table_name, relation.arguments);
    end loop;
end $$;

create function privacy_guard_profile_update() returns trigger
language plpgsql as $$
begin
    if old.erased_at is not null then
        raise exception 'this profile has been erased' using errcode='P0001';
    end if;
    return new;
end $$;
create trigger privacy_erased_profile_immutable before update on users
    for each row execute function privacy_guard_profile_update();

-- Also used by the offline recovery replay. Ownership checks remain active
-- during replay: an old backup requiring handoff must not be exposed first.
create function privacy_erase_profile(target uuid, deleting_session uuid default null) returns boolean
language plpgsql as $$
declare previous_erasure timestamptz;
begin
    select erased_at into previous_erasure from users where id=target for update;
    if not found or previous_erasure is not null then return false; end if;

    -- Match the membership stores' locking snapshots. These locks make two
    -- concurrent owners/admins unable to remove the final responsible person.
    perform om.user_id from org_members om
     where om.org_id in (select org_id from org_members where user_id=target)
     order by om.org_id,om.user_id for update;
    perform m.user_id from members m
     where m.space_id in (select space_id from members where user_id=target)
     order by m.space_id,m.user_id for update;
    if exists(select 1 from members own where own.user_id=target and own.role='owner'
              and not exists(select 1 from members other where other.space_id=own.space_id and other.user_id<>target and other.role='owner')) then
        raise exception 'hand over workspace ownership before deleting your profile' using errcode='P0062';
    end if;
    if exists(select 1 from org_members own where own.user_id=target and own.role='admin' and own.revoked_at is null
              and not exists(select 1 from org_members other where other.org_id=own.org_id and other.user_id<>target and other.role='admin' and other.revoked_at is null)) then
        raise exception 'hand over organization administration before deleting your profile' using errcode='P0062';
    end if;

    -- End capabilities the account issued without erasing other people's
    -- contributions merely because their participation used one of its links.
    delete from session_tokens where user_id in
        (select u.id from users u join session_links l on l.id=u.link_id where l.created_by=target);
    update session_links set revoked_at=coalesce(revoked_at,clock_timestamp()) where created_by=target;
    delete from session_tokens where user_id=target;
    delete from embed_handoffs where user_id=target;
    delete from ics_feed_tokens where user_id=target;
    delete from standup_away where user_id=target;
    delete from workspace_invitations where issuer_id=target or accepted_by=target;
    delete from hosting_grants where user_id=target;
    delete from poker_publication_connections where principal_id=target;
    delete from poker_publication_reviews where principal_id=target;
    delete from votes where user_id=target;
    delete from round_voters where user_id=target;
    delete from session_participants where user_id=target;
    delete from standup_entries where user_id=target;
    delete from standup_commitments where user_id=target;
    delete from standup_mentions where from_user_id=target or to_user_id=target;
    delete from kudos where from_user_id=target or to_user_id=target;
    delete from session_presence where user_id=target;
    delete from members where user_id=target;
    delete from org_members where user_id=target;
    update sessions set current_speaker_id=null,speaker_started_at=null where current_speaker_id=target and (deleting_session is null or id<>deleting_session);
    update standup_schedules set updated_by=null where updated_by=target;
    update standup_webhooks set updated_by=null where updated_by=target;
    update org_audit_log set actor_id=null where actor_id=target;
    update plugin_bundles set uploaded_by=null where uploaded_by=target;
    update users set name='Deleted participant',avatar_icon='',notification_sounds=false,
                     issuer='',subject='',link_id=null,erased_at=clock_timestamp()
     where id=target;
    insert into privacy_deletions(kind,object_id,deleted_at) values('profile',target,clock_timestamp())
    on conflict(kind,object_id) do nothing;
    return true;
end $$;
