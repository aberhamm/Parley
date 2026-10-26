package store

import (
	"encoding/json"
	"errors"
	"testing"

	"github.com/jackc/pgx/v5/pgxpool"
)

func privacySession(t *testing.T, pool *pgxpool.Pool, sp Space, u User) Session {
	t.Helper()
	sess, err := (&Sessions{Pool: pool}).Create(t.Context(), sp.ID, "poker", "Private meeting", json.RawMessage(`{}`), u.ID, 100)
	if err != nil {
		t.Fatal(err)
	}
	return sess
}

func TestPrivacySweepDeletesOnlyExpiredEndedSessionsAndRelatedData(t *testing.T) {
	pool := testPool(t)
	sp, u := newSpaceWithCreator(t, pool)
	keep, other := newSpaceWithCreator(t, pool)
	expired := privacySession(t, pool, sp, u)
	fresh := privacySession(t, pool, sp, u)
	active := privacySession(t, pool, sp, u)
	defaultOff := privacySession(t, pool, keep, other)
	// Retention uses the end time, never the age of a still-active meeting.
	if _, err := pool.Exec(t.Context(), "update sessions set created_at=clock_timestamp()-interval '8 days' where id=$1", active.ID); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(t.Context(), "update sessions set ended_at=clock_timestamp()-interval '1 hour' where id=$1", fresh.ID); err != nil {
		t.Fatal(err)
	}
	var story string
	if err := pool.QueryRow(t.Context(), "insert into stories(session_id,title,notes,position) values($1,'Sensitive title','Sensitive notes',1) returning id::text", expired.ID).Scan(&story); err != nil {
		t.Fatal(err)
	}
	for _, s := range []Session{expired, defaultOff} {
		if _, err := pool.Exec(t.Context(), "update sessions set ended_at=clock_timestamp()-interval '8 days' where id=$1", s.ID); err != nil {
			t.Fatal(err)
		}
	}
	for _, q := range []string{"insert into votes(story_id,user_id,value) values($1,$2,'5')", "insert into standup_entries(session_id,user_id,today,position) values($1,$2,'Sensitive update',1)"} {
		target := expired.ID
		if q[12:17] == "votes" {
			target = story
		}
		if _, err := pool.Exec(t.Context(), q, target, u.ID); err != nil {
			t.Fatal(err)
		}
	}
	if err := (&Orgs{Pool: pool}).GrantMember(t.Context(), defaultOrgID(t, pool), u.ID, "member"); err != nil {
		t.Fatal(err)
	}
	privacy := &Privacy{Pool: pool}
	if err := privacy.SetRetention(t.Context(), sp.ID, u.ID, 7, false); err != nil {
		t.Fatal(err)
	}
	n, err := privacy.SweepExpired(t.Context())
	if err != nil || n < 1 {
		t.Fatalf("expiry deletion: %d %v", n, err)
	}
	for _, q := range []string{"select count(*) from sessions where id=$1", "select count(*) from stories where session_id=$1", "select count(*) from standup_entries where session_id=$1"} {
		var count int
		if err = pool.QueryRow(t.Context(), q, expired.ID).Scan(&count); err != nil || count != 0 {
			t.Fatalf("related content remains: %d %v", count, err)
		}
	}
	var votes int
	if err = pool.QueryRow(t.Context(), "select count(*) from votes where story_id=$1", story).Scan(&votes); err != nil || votes != 0 {
		t.Fatalf("votes remain: %d %v", votes, err)
	}
	for _, s := range []Session{fresh, active, defaultOff} {
		var yes bool
		if err = pool.QueryRow(t.Context(), "select exists(select 1 from sessions where id=$1)", s.ID).Scan(&yes); err != nil || !yes {
			t.Fatalf("non-expired session removed: %s %v", s.ID, err)
		}
	}
	var receipt int
	if err = pool.QueryRow(t.Context(), "select count(*) from privacy_deletions where kind='session' and object_id=$1", expired.ID).Scan(&receipt); err != nil || receipt != 1 {
		t.Fatalf("missing atomic receipt: %d %v", receipt, err)
	}
	if _, err = pool.Exec(t.Context(), "select privacy_erase_space($1)", sp.ID); err != nil {
		t.Fatal(err)
	}
	if err = pool.QueryRow(t.Context(), "select count(*) from privacy_deletions where kind='space' and object_id=$1", sp.ID).Scan(&receipt); err != nil || receipt != 1 {
		t.Fatalf("missing workspace receipt: %d %v", receipt, err)
	}
}

func TestPrivacyRetentionStoreRechecksAuthority(t *testing.T) {
	pool := testPool(t)
	ctx := t.Context()
	space, owner := newSpaceWithCreator(t, pool)
	orgID := defaultOrgID(t, pool)
	if err := (&Orgs{Pool: pool}).GrantMember(ctx, orgID, owner.ID, "member"); err != nil {
		t.Fatal(err)
	}
	privacy := &Privacy{Pool: pool}
	unchanged := func(want int) {
		t.Helper()
		got, err := privacy.Retention(ctx, space.ID)
		if err != nil || got != want {
			t.Fatalf("retention changed during refusal: got=%d want=%d err=%v", got, want, err)
		}
	}
	if err := privacy.SetRetention(ctx, space.ID, owner.ID, 7, true); !errors.Is(err, ErrNotEligible) {
		t.Fatalf("owner without host grant: got %v, want ErrNotEligible", err)
	}
	unchanged(0)
	if _, err := pool.Exec(ctx, "insert into hosting_grants(org_id,user_id) values($1,$2)", orgID, owner.ID); err != nil {
		t.Fatal(err)
	}
	if err := privacy.SetRetention(ctx, space.ID, owner.ID, 7, true); err != nil {
		t.Fatalf("current host owner: %v", err)
	}
	unchanged(7)
	if _, err := pool.Exec(ctx, "update members set role='member' where space_id=$1 and user_id=$2", space.ID, owner.ID); err != nil {
		t.Fatal(err)
	}
	if err := privacy.SetRetention(ctx, space.ID, owner.ID, 30, true); !errors.Is(err, ErrNotMember) {
		t.Fatalf("demoted owner: got %v, want ErrNotMember", err)
	}
	unchanged(7)
	if _, err := pool.Exec(ctx, "update members set role='owner' where space_id=$1 and user_id=$2", space.ID, owner.ID); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(ctx, "update org_members set revoked_at=clock_timestamp() where org_id=$1 and user_id=$2", orgID, owner.ID); err != nil {
		t.Fatal(err)
	}
	if err := privacy.SetRetention(ctx, space.ID, owner.ID, 90, true); !errors.Is(err, ErrNotMember) {
		t.Fatalf("revoked organization membership: got %v, want ErrNotMember", err)
	}
	unchanged(7)
}

func TestPrivacyRetentionDoesNotDeleteBusyOrReopenedSession(t *testing.T) {
	pool := testPool(t)
	sp, u := newSpaceWithCreator(t, pool)
	s := privacySession(t, pool, sp, u)
	if err := (&Orgs{Pool: pool}).GrantMember(t.Context(), defaultOrgID(t, pool), u.ID, "member"); err != nil {
		t.Fatal(err)
	}
	p := &Privacy{Pool: pool}
	if err := p.SetRetention(t.Context(), sp.ID, u.ID, 1, false); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(t.Context(), "update sessions set ended_at=clock_timestamp()-interval '2 days' where id=$1", s.ID); err != nil {
		t.Fatal(err)
	}
	tx, err := pool.Begin(t.Context())
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Rollback(t.Context())
	if _, err = tx.Exec(t.Context(), "select id from sessions where id=$1 for update", s.ID); err != nil {
		t.Fatal(err)
	}
	if _, err = p.SweepExpired(t.Context()); err != nil {
		t.Fatal(err)
	}
	if err = tx.Rollback(t.Context()); err != nil {
		t.Fatal(err)
	}
	if err = (&Sessions{Pool: pool}).SetEnded(t.Context(), s.ID, u.ID, false); err != nil {
		t.Fatal(err)
	}
	if _, err = p.SweepExpired(t.Context()); err != nil {
		t.Fatal(err)
	}
	if _, err = (&Sessions{Pool: pool}).ByID(t.Context(), s.ID); err != nil {
		t.Fatalf("reopened room was erased: %v", err)
	}
}
