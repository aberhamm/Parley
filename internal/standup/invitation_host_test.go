package standup

import (
	"testing"
	"time"
)

func TestInviteOnlyScheduleHost(t *testing.T) {
	for _, removal := range []string{"hosting", "organization", "membership", "ownership"} {
		t.Run(removal, func(t *testing.T) {
			pool := testPool(t)
			spaceID, owner := seedSchedule(t, pool, Schedule{Weekdays: []int{0, 1, 2, 3, 4, 5, 6}, OpenTime: "00:00", Timezone: "UTC", WindowMinutes: 60, Enabled: true})
			var orgID string
			if err := pool.QueryRow(t.Context(), `select org_id from spaces where id=$1`, spaceID).Scan(&orgID); err != nil {
				t.Fatal(err)
			}
			if _, err := pool.Exec(t.Context(), `insert into org_members(org_id,user_id,role) values($1,$2,'member') on conflict do nothing`, orgID, owner); err != nil {
				t.Fatal(err)
			}
			now := time.Date(2026, 10, 25, 12, 0, 0, 0, time.UTC)
			if _, err := TickWithPolicy(t.Context(), pool, now, 500, true); err != nil {
				t.Fatal(err)
			}
			if n := len(scheduledSessions(t, pool, spaceID)); n != 0 {
				t.Fatalf("uninvited owner opened %d sessions", n)
			}
			if _, err := pool.Exec(t.Context(), `insert into hosting_grants(org_id,user_id) values($1,$2)`, orgID, owner); err != nil {
				t.Fatal(err)
			}
			if _, err := TickWithPolicy(t.Context(), pool, now, 500, true); err != nil {
				t.Fatal(err)
			}
			sessions := scheduledSessions(t, pool, spaceID)
			if len(sessions) != 1 {
				t.Fatalf("host opened %d sessions", len(sessions))
			}
			queries := map[string]string{"hosting": `delete from hosting_grants where org_id=$1 and user_id=$2`, "organization": `update org_members set revoked_at=now() where org_id=$1 and user_id=$2`, "membership": `delete from members where space_id=$1 and user_id=$2`, "ownership": `update members set role='member' where space_id=$1 and user_id=$2`}
			scope := orgID
			if removal == "membership" || removal == "ownership" {
				scope = spaceID
			}
			if _, err := pool.Exec(t.Context(), queries[removal], scope, owner); err != nil {
				t.Fatal(err)
			}
			if _, err := TickWithPolicy(t.Context(), pool, now.AddDate(0, 0, 1), 500, true); err != nil {
				t.Fatal(err)
			}
			if n := len(scheduledSessions(t, pool, spaceID)); n != 1 {
				t.Fatalf("revoked host opened another session: %d", n)
			}
			var ended bool
			if err := pool.QueryRow(t.Context(), `select ended_at is not null from sessions where id=$1`, sessions[0].ID).Scan(&ended); err != nil {
				t.Fatal(err)
			}
			if ended {
				t.Fatal("refused scheduler ended the prior session")
			}
		})
	}
}

func TestScheduleHostRevocationRace(t *testing.T) {
	pool := testPool(t)
	spaceID, owner := seedSchedule(t, pool, Schedule{Weekdays: []int{0, 1, 2, 3, 4, 5, 6}, OpenTime: "00:00", Timezone: "UTC", WindowMinutes: 60, Enabled: true})
	var orgID string
	if err := pool.QueryRow(t.Context(), `select org_id from spaces where id=$1`, spaceID).Scan(&orgID); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(t.Context(), `insert into org_members(org_id,user_id,role) values($1,$2,'member') on conflict do nothing`, orgID, owner); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(t.Context(), `insert into hosting_grants(org_id,user_id) values($1,$2)`, orgID, owner); err != nil {
		t.Fatal(err)
	}
	tx, err := pool.Begin(t.Context())
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Rollback(t.Context())
	if _, err = tx.Exec(t.Context(), `delete from hosting_grants where org_id=$1 and user_id=$2`, orgID, owner); err != nil {
		t.Fatal(err)
	}
	result := make(chan error, 1)
	go func() {
		_, err := TickWithPolicy(t.Context(), pool, time.Date(2026, 10, 25, 12, 0, 0, 0, time.UTC), 500, true)
		result <- err
	}()
	completed := false
	var tickErr error
	select {
	case tickErr = <-result:
		completed = true
	case <-time.After(150 * time.Millisecond):
	}
	if err = tx.Commit(t.Context()); err != nil {
		t.Fatal(err)
	}
	if !completed {
		tickErr = <-result
	}
	if tickErr != nil {
		t.Fatal(tickErr)
	}
	if n := len(scheduledSessions(t, pool, spaceID)); n != 0 {
		t.Fatalf("revocation in progress allowed %d sessions", n)
	}
}
