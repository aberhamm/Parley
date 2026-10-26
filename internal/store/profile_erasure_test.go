package store

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
)

func TestProfileErasureRemovesPersonalDataAndPreservesSharedMeeting(t *testing.T) {
	pool := testPool(t)
	ctx := t.Context()
	sp, owner := newSpaceWithCreator(t, pool)
	target, _ := newUser(t, pool, "Sensitive profile name")
	spaces := &Spaces{Pool: pool}
	if err := spaces.Join(ctx, sp.ID, target.ID); err != nil {
		t.Fatal(err)
	}
	sess, err := (&Sessions{Pool: pool}).Create(ctx, sp.ID, "poker", "Shared meeting stays", []byte(`{}`), owner.ID, 50)
	if err != nil {
		t.Fatal(err)
	}
	var storyID string
	if err := pool.QueryRow(ctx, "insert into stories(session_id,title,position) values($1,'Shared story stays',1) returning id", sess.ID).Scan(&storyID); err != nil {
		t.Fatal(err)
	}
	for _, q := range []string{
		"update users set issuer='https://idp.example',subject=id::text,avatar_icon='owl',notification_sounds=true where id=$1",
		"insert into votes(story_id,user_id,value) values($2,$1,'5')",
		"insert into round_voters(story_id,user_id) values($2,$1)",
		"insert into session_participants(session_id,user_id) values($2,$1)",
		"insert into standup_entries(session_id,user_id,today,position) values($2,$1,'Sensitive daily note',1)",
		"insert into standup_away(user_id,starts_on,ends_on) values($1,current_date,current_date)",
		"insert into org_members(org_id,user_id) values('00000000-0000-0000-0000-000000000001',$1) on conflict do nothing",
		"insert into hosting_grants(org_id,user_id) values('00000000-0000-0000-0000-000000000001',$1)",
	} {
		args := []any{target.ID}
		if strings.Contains(q, "$2") {
			if strings.Contains(q, "story_id") {
				args = append(args, storyID)
			} else {
				args = append(args, sess.ID)
			}
		}
		if _, err := pool.Exec(ctx, q, args...); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := pool.Exec(ctx, "insert into kudos(space_id,from_user_id,to_user_id,text) values($1,$2,$3,'Private thank you')", sp.ID, target.ID, owner.ID); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(ctx, "insert into standup_commitments(space_id,user_id,text,opened_session_id) values($1,$2,'Private commitment',$3)", sp.ID, target.ID, sess.ID); err != nil {
		t.Fatal(err)
	}
	result, err := (&Users{Pool: pool}).EraseProfile(ctx, target.ID)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.TokenHashes) != 1 || len(result.Sessions) != 1 || result.Sessions[0] != sess.ID {
		t.Fatalf("invalidations: tokens=%d rooms=%v", len(result.TokenHashes), result.Sessions)
	}
	for _, table := range []string{"session_tokens", "members", "org_members", "hosting_grants", "votes", "round_voters", "session_participants", "standup_entries", "standup_away", "standup_commitments", "session_presence", "ics_feed_tokens", "embed_handoffs"} {
		var count int
		if err := pool.QueryRow(ctx, "select count(*) from "+table+" where user_id=$1", target.ID).Scan(&count); err != nil || count != 0 {
			t.Fatalf("%s: count=%d err=%v", table, count, err)
		}
	}
	var clean bool
	if err := pool.QueryRow(ctx, "select name='Deleted participant' and issuer='' and subject='' and avatar_icon='' and not notification_sounds and erased_at is not null from users where id=$1", target.ID).Scan(&clean); err != nil || !clean {
		t.Fatalf("profile not sanitized: %v", err)
	}
	var count int
	if err := pool.QueryRow(ctx, "select count(*) from stories where id=$1 and title='Shared story stays'", storyID).Scan(&count); err != nil || count != 1 {
		t.Fatalf("shared story removed: %v", err)
	}
	if err := pool.QueryRow(ctx, "select count(*) from privacy_deletions where kind='profile' and object_id=$1", target.ID).Scan(&count); err != nil || count != 1 {
		t.Fatalf("missing atomic receipt: %v", err)
	}
	var again bool
	if err := pool.QueryRow(ctx, "select privacy_erase_profile($1)", target.ID).Scan(&again); err != nil || again {
		t.Fatalf("replay not idempotent: again=%v err=%v", again, err)
	}
}

func TestProfileErasureRefusesLastOwnerAndAdmin(t *testing.T) {
	pool := testPool(t)
	sp, owner := newSpaceWithCreator(t, pool)
	users := &Users{Pool: pool}
	if _, err := users.EraseProfile(t.Context(), owner.ID); !errors.Is(err, ErrProfileHandoff) {
		t.Fatalf("sole owner: %v", err)
	}
	var live bool
	if err := pool.QueryRow(t.Context(), "select erased_at is null from users where id=$1", owner.ID).Scan(&live); err != nil || !live {
		t.Fatalf("refusal changed user: %v", err)
	}
	other, _ := newUser(t, pool, "Other owner")
	if _, err := pool.Exec(t.Context(), "insert into members(space_id,user_id,role) values($1,$2,'owner')", sp.ID, other.ID); err != nil {
		t.Fatal(err)
	}
	var orgID string
	if err := pool.QueryRow(t.Context(), "insert into orgs(slug,name,claim_value) values($1,'Private org',$1) returning id", "erasure-"+randSuffix(t)).Scan(&orgID); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(t.Context(), "insert into org_members(org_id,user_id,role) values($1,$2,'admin')", orgID, owner.ID); err != nil {
		t.Fatal(err)
	}
	if _, err := users.EraseProfile(t.Context(), owner.ID); !errors.Is(err, ErrProfileHandoff) {
		t.Fatalf("sole admin: %v", err)
	}
	if _, err := pool.Exec(t.Context(), "insert into org_members(org_id,user_id,role) values($1,$2,'admin')", orgID, other.ID); err != nil {
		t.Fatal(err)
	}
	if _, err := users.EraseProfile(t.Context(), owner.ID); err != nil {
		t.Fatal(err)
	}
	var count int
	if err := pool.QueryRow(t.Context(), "select count(*) from members where space_id=$1 and role='owner'", sp.ID).Scan(&count); err != nil || count != 1 {
		t.Fatalf("remaining owner lost: %d %v", count, err)
	}
}

func TestProfileErasureRejectsLateWritesAndCannotBeRevived(t *testing.T) {
	pool := testPool(t)
	target, _ := newUser(t, pool, "Private identity")
	sp := newSpace(t, pool)
	if _, err := (&Users{Pool: pool}).EraseProfile(t.Context(), target.ID); err != nil {
		t.Fatal(err)
	}
	_, hash := NewToken()
	for _, statement := range []string{
		"insert into session_tokens(user_id,token_hash) values($1,$2)",
		"update users set name='Resurrected identity' where id=$1",
		"insert into members(user_id,space_id) values($1,$2)",
		"insert into hosting_grants(user_id,org_id) values($1,$2)",
	} {
		args := []any{target.ID}
		if strings.Contains(statement, "token_hash") {
			args = append(args, hash)
		} else if strings.Contains(statement, "space_id") {
			args = append(args, sp.ID)
		} else if strings.Contains(statement, "org_id") {
			args = append(args, defaultOrgID(t, pool))
		}
		if _, err := pool.Exec(t.Context(), statement, args...); err == nil {
			t.Fatalf("late write accepted: %s", statement)
		}
	}
	called := false
	_, owner := newSpaceWithCreator(t, pool)
	sess, err := (&Sessions{Pool: pool}).Create(t.Context(), sp.ID, "poker", "Keep", []byte(`{}`), owner.ID, 50)
	if err != nil {
		t.Fatal(err)
	}
	err = (&Sessions{Pool: pool}).WithActiveSession(t.Context(), sess.ID, target.ID, false, func(pgx.Tx, Session) error { called = true; return nil })
	if !errors.Is(err, ErrNoUser) || called {
		t.Fatalf("preauthenticated request wrote after erase: called=%v err=%v", called, err)
	}
}

func TestProfileErasureSerializesConcurrentLateTokenIssuance(t *testing.T) {
	pool := testPool(t)
	target, _ := newUser(t, pool, "Private identity")
	ctx, cancel := context.WithTimeout(t.Context(), 5*time.Second)
	defer cancel()
	tx, err := pool.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Rollback(ctx)
	if _, err := tx.Exec(ctx, "select privacy_erase_profile($1)", target.ID); err != nil {
		t.Fatal(err)
	}
	_, hash := NewToken()
	done := make(chan error, 1)
	go func() {
		_, err := pool.Exec(ctx, "insert into session_tokens(user_id,token_hash) values($1,$2)", target.ID, hash)
		done <- err
	}()
	select {
	case err := <-done:
		t.Fatalf("issuance did not wait on erasure: %v", err)
	case <-time.After(50 * time.Millisecond):
	}
	if err := tx.Commit(ctx); err != nil {
		t.Fatal(err)
	}
	if err := <-done; err == nil {
		t.Fatal("late token issuance resurrected account")
	}
}

func TestProfileErasureConcurrentOwnersLeaveOneResponsibleOwner(t *testing.T) {
	pool := testPool(t)
	sp, first := newSpaceWithCreator(t, pool)
	second, _ := newUser(t, pool, "Second owner")
	if _, err := pool.Exec(t.Context(), "insert into members(space_id,user_id,role) values($1,$2,'owner')", sp.ID, second.ID); err != nil {
		t.Fatal(err)
	}
	start := make(chan struct{})
	done := make(chan error, 2)
	for _, id := range []string{first.ID, second.ID} {
		go func(id string) { <-start; _, err := (&Users{Pool: pool}).EraseProfile(t.Context(), id); done <- err }(id)
	}
	close(start)
	success, refused := 0, 0
	for range 2 {
		err := <-done
		if err == nil {
			success++
		} else if errors.Is(err, ErrProfileHandoff) {
			refused++
		} else {
			t.Fatal(err)
		}
	}
	if success != 1 || refused != 1 {
		t.Fatal(fmt.Sprintf("success=%d refused=%d", success, refused))
	}
}

func TestPrivacyDeleteSessionErasesGuestCurrentSpeaker(t *testing.T) {
	pool := testPool(t)
	ctx := t.Context()
	sp, owner := newSpaceWithCreator(t, pool)
	sessions := &Sessions{Pool: pool}
	sess, err := sessions.Create(ctx, sp.ID, "standup", "Guest privacy", []byte(`{}`), owner.ID, 50)
	if err != nil {
		t.Fatal(err)
	}
	link, _ := newLink(t, &Links{Pool: pool}, sess.ID, owner.ID, time.Hour)
	_, hash := NewToken()
	guest, err := (&Users{Pool: pool}).CreateForLink(ctx, "Sensitive guest name", link.ID, hash, link.ExpiresAt, LinkRedemptionCap, "profile-speaker-test", 100, 10000)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(ctx, "update sessions set current_speaker_id=$1,speaker_started_at=now() where id=$2", guest.ID, sess.ID); err != nil {
		t.Fatal(err)
	}
	if err := sessions.Delete(ctx, sess.ID, sp.ID); err != nil {
		t.Fatalf("deleting guest's speaking session: %v", err)
	}
	var erased bool
	if err := pool.QueryRow(ctx, "select erased_at is not null and name='Deleted participant' from users where id=$1", guest.ID).Scan(&erased); err != nil || !erased {
		t.Fatalf("guest identity remained: %v", err)
	}
}

func TestProfileErasureCoversEveryUserForeignKey(t *testing.T) {
	pool := testPool(t)
	var missing int
	err := pool.QueryRow(t.Context(), `select count(*) from pg_constraint c
        where c.contype='f' and c.confrelid='users'::regclass and not exists
        (select 1 from pg_trigger t where t.tgrelid=c.conrelid and t.tgname='privacy_active_user')`).Scan(&missing)
	if err != nil || missing != 0 {
		t.Fatalf("user-bearing tables missing the erasure guard: %d err=%v", missing, err)
	}
}

func TestPrivacyDeleteSessionSerializesGuestRedemption(t *testing.T) {
	pool := testPool(t)
	ctx, cancel := context.WithTimeout(t.Context(), 5*time.Second)
	defer cancel()
	sp, owner := newSpaceWithCreator(t, pool)
	sess, err := (&Sessions{Pool: pool}).Create(ctx, sp.ID, "poker", "Guest privacy race", []byte(`{}`), owner.ID, 50)
	if err != nil {
		t.Fatal(err)
	}
	link, _ := newLink(t, &Links{Pool: pool}, sess.ID, owner.ID, time.Hour)
	redemption, err := pool.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer redemption.Rollback(ctx)
	// Pause a valid redemption after it has claimed the link but before the
	// guest identity is committed, matching CreateForLink's transaction order.
	if _, err := redemption.Exec(ctx, "update session_links set redemptions=redemptions+1 where id=$1", link.ID); err != nil {
		t.Fatal(err)
	}
	deleting, err := pool.Acquire(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer deleting.Release()
	pid := deleting.Conn().PgConn().PID()
	done := make(chan error, 1)
	go func() {
		var erased bool
		err := deleting.QueryRow(ctx, "select privacy_erase_session($1)", sess.ID).Scan(&erased)
		done <- err
	}()
	for {
		var waiting bool
		if err := pool.QueryRow(ctx, "select coalesce(wait_event_type='Lock',false) from pg_stat_activity where pid=$1", pid).Scan(&waiting); err != nil {
			t.Fatal(err)
		}
		if waiting {
			break
		}
		select {
		case err := <-done:
			t.Fatalf("delete did not wait for redemption: %v", err)
		case <-ctx.Done():
			t.Fatal(ctx.Err())
		case <-time.After(time.Millisecond):
		}
	}
	var guestID string
	if err := redemption.QueryRow(ctx, "insert into users(name,link_id) values('Sensitive racing guest',$1) returning id", link.ID).Scan(&guestID); err != nil {
		t.Fatal(err)
	}
	if err := redemption.Commit(ctx); err != nil {
		t.Fatal(err)
	}
	if err := <-done; err != nil {
		t.Fatal(err)
	}
	var clean bool
	if err := pool.QueryRow(ctx, "select erased_at is not null and name='Deleted participant' from users where id=$1", guestID).Scan(&clean); err != nil || !clean {
		t.Fatalf("racing guest profile survived deletion: %v", err)
	}
}
