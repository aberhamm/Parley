-- A signed-link guest has a users row even after its link is removed. Session
-- deletion must erase that guest's profile rather than strand its chosen name
-- after the link foreign key becomes null. Link revocation alone keeps its
-- historical participation, preserving the existing separate operation.
create function privacy_erase_session_guests() returns trigger language plpgsql as $$
declare guest record;
begin
    -- Serialize against a redemption that has not committed its guest row yet.
    perform id from session_links where session_id=OLD.id order by id for update;
    for guest in select u.id from users u join session_links l on l.id=u.link_id
                  where l.session_id=OLD.id and u.erased_at is null order by u.id loop
        perform privacy_erase_profile(guest.id,OLD.id);
    end loop;
    return OLD;
end;
$$;
create trigger privacy_session_guest_profiles before delete on sessions
    for each row execute function privacy_erase_session_guests();
