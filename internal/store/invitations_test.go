package store

import (
	"context"
	"errors"
	"fmt"
	"testing"
	"time"
)

func TestInvitationIssuerRevocation(t *testing.T) {
	for _, boundary := range []string{"hosting", "ownership", "organization"} {
		t.Run(boundary, func(t *testing.T) {
			pool := testPool(t)
			sp, issuer := newSpaceWithCreator(t, pool)
			orgID := defaultOrgID(t, pool)
			if _, err := pool.Exec(t.Context(), `insert into org_members(org_id,user_id,role) values($1,$2,'member') on conflict do nothing`, orgID, issuer.ID); err != nil {
				t.Fatal(err)
			}
			if _, err := pool.Exec(t.Context(), `insert into hosting_grants(org_id,user_id) values($1,$2)`, orgID, issuer.ID); err != nil {
				t.Fatal(err)
			}
			invitations := &Invitations{Pool: pool}
			_, token, err := invitations.Mint(t.Context(), orgID, &sp.ID, &issuer.ID, "host")
			if err != nil {
				t.Fatal(err)
			}
			recipient, _ := newUser(t, pool, "Recipient")
			tx, err := pool.Begin(t.Context())
			if err != nil {
				t.Fatal(err)
			}
			defer tx.Rollback(t.Context())
			queries := map[string]string{
				"hosting":      `delete from hosting_grants where org_id=$1 and user_id=$2`,
				"ownership":    `update members set role='member' where space_id=$1 and user_id=$2`,
				"organization": `update org_members set revoked_at=now() where org_id=$1 and user_id=$2`,
			}
			scope := orgID
			if boundary == "ownership" {
				scope = sp.ID
			}
			if _, err = tx.Exec(t.Context(), queries[boundary], scope, issuer.ID); err != nil {
				t.Fatal(err)
			}
			ctx, cancel := context.WithTimeout(t.Context(), 5*time.Second)
			defer cancel()
			result := make(chan error, 1)
			go func() { _, err := invitations.Accept(ctx, token, recipient.ID); result <- err }()
			var early error
			completed := false
			select {
			case early = <-result:
				completed = true
			case <-time.After(150 * time.Millisecond):
			}
			if err := tx.Commit(t.Context()); err != nil {
				t.Fatal(err)
			}
			if !completed {
				early = <-result
			}
			if !errors.Is(early, ErrInvitation) {
				t.Fatalf("%s revocation must defeat redemption, got %v", boundary, early)
			}
			var granted bool
			if err := pool.QueryRow(t.Context(), `select exists(select 1 from hosting_grants where org_id=$1 and user_id=$2)`, orgID, recipient.ID).Scan(&granted); err != nil {
				t.Fatal(err)
			}
			if granted {
				t.Fatal("revoked issuer granted hosting")
			}
		})
	}
}

func TestInvitationPendingQuotaAndTokenCustody(t *testing.T) {
	pool := testPool(t)
	sp, issuer := newSpaceWithCreator(t, pool)
	orgID := defaultOrgID(t, pool)
	if _, err := pool.Exec(t.Context(), `insert into org_members(org_id,user_id,role) values($1,$2,'member') on conflict do nothing`, orgID, issuer.ID); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(t.Context(), `insert into hosting_grants(org_id,user_id) values($1,$2)`, orgID, issuer.ID); err != nil {
		t.Fatal(err)
	}
	invitations := &Invitations{Pool: pool}
	for n := 0; n < 50; n++ {
		i, token, err := invitations.Mint(t.Context(), orgID, &sp.ID, &issuer.ID, "participant")
		if err != nil {
			t.Fatal(err)
		}
		var hash []byte
		if err = pool.QueryRow(t.Context(), `select token_hash from workspace_invitations where id=$1`, i.ID).Scan(&hash); err != nil {
			t.Fatal(err)
		}
		if len(hash) != 32 || string(hash) == token {
			t.Fatal("raw token persisted")
		}
	}
	if _, _, err := invitations.Mint(t.Context(), orgID, &sp.ID, &issuer.ID, "host"); !errors.Is(err, ErrQuotaExceeded) {
		t.Fatalf("pending quota: %v", err)
	}
	rows, err := invitations.List(t.Context(), orgID, sp.ID)
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != 50 {
		t.Fatal(fmt.Sprintf("got %d pending invitations", len(rows)))
	}
	if err := invitations.Revoke(t.Context(), orgID, sp.ID, rows[0].ID); err != nil {
		t.Fatal(err)
	}
	if _, _, err := invitations.Mint(t.Context(), orgID, &sp.ID, &issuer.ID, "host"); err != nil {
		t.Fatal(err)
	}
}
