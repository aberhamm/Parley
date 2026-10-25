package store

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

var ErrInvitation = errors.New("invitation is unavailable")

type Invitations struct{ Pool *pgxpool.Pool }
type Invitation struct {
	ID         string     `json:"id"`
	OrgID      string     `json:"-"`
	OrgSlug    string     `json:"orgSlug"`
	SpaceID    *string    `json:"-"`
	SpaceSlug  *string    `json:"spaceSlug,omitempty"`
	SpaceName  *string    `json:"spaceName,omitempty"`
	Role       string     `json:"role"`
	CreatedAt  time.Time  `json:"createdAt"`
	ExpiresAt  time.Time  `json:"expiresAt"`
	AcceptedAt *time.Time `json:"acceptedAt"`
	RevokedAt  *time.Time `json:"revokedAt"`
}

func (s *Invitations) CanHost(ctx context.Context, orgID, userID string) (bool, error) {
	var yes bool
	err := s.Pool.QueryRow(ctx, `select exists(select 1 from hosting_grants h join org_members m using(org_id,user_id) where h.org_id=$1 and h.user_id=$2 and m.revoked_at is null)`, orgID, userID).Scan(&yes)
	return yes, err
}

// Mint stores only a digest. A nil issuer/space is reserved for the operator's
// bootstrap command and has no HTTP equivalent. Pending invites are bounded.
func (s *Invitations) Mint(ctx context.Context, orgID string, spaceID, issuerID *string, role string) (Invitation, string, error) {
	if role != "participant" && role != "host" {
		return Invitation{}, "", ErrBadRole
	}
	if (spaceID == nil) != (issuerID == nil) || (issuerID == nil && role != "host") {
		return Invitation{}, "", ErrInvitation
	}
	tx, err := s.Pool.Begin(ctx)
	if err != nil {
		return Invitation{}, "", err
	}
	defer tx.Rollback(ctx)
	if issuerID != nil {
		// Serialize quota checks for one issuer/workspace, and validate the live
		// hosting, org and ownership grants in the same transaction.
		if _, err = tx.Exec(ctx, `select pg_advisory_xact_lock(hashtextextended($1,0))`, *spaceID+":"+*issuerID); err != nil {
			return Invitation{}, "", err
		}
		var allowed bool
		err = tx.QueryRow(ctx, `select exists(select 1 from spaces s join members m on m.space_id=s.id join hosting_grants h on h.org_id=s.org_id and h.user_id=m.user_id join org_members om on om.org_id=h.org_id and om.user_id=h.user_id where s.id=$1 and s.org_id=$2 and m.user_id=$3 and m.role='owner' and om.revoked_at is null)`, *spaceID, orgID, *issuerID).Scan(&allowed)
		if err != nil {
			return Invitation{}, "", err
		}
		if !allowed {
			return Invitation{}, "", ErrInvitation
		}
		var n int
		if err = tx.QueryRow(ctx, `select count(*) from workspace_invitations where space_id=$1 and issuer_id=$2 and accepted_at is null and revoked_at is null and expires_at>now()`, *spaceID, *issuerID).Scan(&n); err != nil {
			return Invitation{}, "", err
		}
		if n >= 50 {
			return Invitation{}, "", ErrQuotaExceeded
		}
	}
	plain, hash := NewToken()
	var out Invitation
	err = tx.QueryRow(ctx, `insert into workspace_invitations(token_hash,org_id,space_id,issuer_id,role) values($1,$2,$3,$4,$5) returning id,role,created_at,expires_at`, hash, orgID, spaceID, issuerID, role).Scan(&out.ID, &out.Role, &out.CreatedAt, &out.ExpiresAt)
	if err != nil {
		return Invitation{}, "", err
	}
	if err = tx.Commit(ctx); err != nil {
		return Invitation{}, "", err
	}
	return out, plain, nil
}

// The issuer must still be an owner/host in the same active org at redemption.
const liveInvitation = `i.accepted_at is null and i.revoked_at is null and i.expires_at>now() and (i.issuer_id is null or exists(select 1 from members m join hosting_grants h on h.user_id=m.user_id and h.org_id=i.org_id join org_members om on om.user_id=h.user_id and om.org_id=h.org_id where m.space_id=i.space_id and m.user_id=i.issuer_id and m.role='owner' and om.revoked_at is null))`
const invitationSelect = `select i.id,i.org_id,o.slug,i.space_id,s.slug,s.name,i.role,i.created_at,i.expires_at,i.accepted_at,i.revoked_at from workspace_invitations i join orgs o on o.id=i.org_id left join spaces s on s.id=i.space_id `

func scanInvitation(row pgx.Row) (Invitation, error) {
	var i Invitation
	err := row.Scan(&i.ID, &i.OrgID, &i.OrgSlug, &i.SpaceID, &i.SpaceSlug, &i.SpaceName, &i.Role, &i.CreatedAt, &i.ExpiresAt, &i.AcceptedAt, &i.RevokedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return i, ErrInvitation
	}
	return i, err
}
func invitationHash(token string) ([]byte, error) {
	hash, err := HashToken(token)
	if err != nil || len(token) != 43 {
		return nil, ErrInvitation
	}
	return hash, nil
}
func (s *Invitations) Preview(ctx context.Context, token string) (Invitation, error) {
	hash, err := invitationHash(token)
	if err != nil {
		return Invitation{}, err
	}
	return scanInvitation(s.Pool.QueryRow(ctx, invitationSelect+`where i.token_hash=$1 and `+liveInvitation, hash))
}
func (s *Invitations) Accept(ctx context.Context, token, userID string) (Invitation, error) {
	hash, err := invitationHash(token)
	if err != nil {
		return Invitation{}, err
	}
	tx, err := s.Pool.Begin(ctx)
	if err != nil {
		return Invitation{}, err
	}
	defer tx.Rollback(ctx)
	// FOR UPDATE OF i makes concurrent acceptance/revocation single-winner.
	i, err := scanInvitation(tx.QueryRow(ctx, invitationSelect+`where i.token_hash=$1 and `+liveInvitation+` for update of i`, hash))
	if err != nil {
		return Invitation{}, err
	}
	var full bool
	if err = tx.QueryRow(ctx, `select exists(select 1 from users where id=$1 and link_id is null)`, userID).Scan(&full); err != nil {
		return i, err
	}
	if !full {
		return i, ErrInvitation
	}
	// A removed org membership is a tombstone, not an invitation to restore it.
	if _, err = tx.Exec(ctx, `insert into org_members(org_id,user_id,role) values($1,$2,'member') on conflict do nothing`, i.OrgID, userID); err != nil {
		return i, err
	}
	var active bool
	if err = tx.QueryRow(ctx, `select revoked_at is null from org_members where org_id=$1 and user_id=$2 for update`, i.OrgID, userID).Scan(&active); err != nil {
		return i, err
	}
	if !active {
		return i, ErrInvitation
	}
	if i.Role == "host" {
		if _, err = tx.Exec(ctx, `insert into hosting_grants(org_id,user_id) values($1,$2) on conflict do nothing`, i.OrgID, userID); err != nil {
			return i, err
		}
	}
	if i.SpaceID != nil {
		role := "member"
		if i.Role == "host" {
			role = "owner"
		}
		if _, err = tx.Exec(ctx, `insert into members(space_id,user_id,role) values($1,$2,$3) on conflict(space_id,user_id) do update set role=case when excluded.role='owner' then 'owner' else members.role end`, *i.SpaceID, userID, role); err != nil {
			return i, err
		}
	}
	if _, err = tx.Exec(ctx, `update workspace_invitations set accepted_at=now(),accepted_by=$2 where id=$1`, i.ID, userID); err != nil {
		return i, err
	}
	if err = tx.Commit(ctx); err != nil {
		return i, err
	}
	return i, nil
}
func (s *Invitations) List(ctx context.Context, orgID, spaceID string) ([]Invitation, error) {
	rows, err := s.Pool.Query(ctx, invitationSelect+`where i.org_id=$1 and i.space_id=$2 order by (i.accepted_at is null and i.revoked_at is null and i.expires_at>now()) desc,i.created_at desc limit 100`, orgID, spaceID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []Invitation{}
	for rows.Next() {
		i, err := scanInvitation(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, i)
	}
	return out, rows.Err()
}
func (s *Invitations) Revoke(ctx context.Context, orgID, spaceID, id string) error {
	tag, err := s.Pool.Exec(ctx, `update workspace_invitations set revoked_at=now() where id::text=$1 and org_id=$2 and space_id=$3 and accepted_at is null and revoked_at is null`, id, orgID, spaceID)
	if err != nil {
		return fmt.Errorf("revoking invitation: %w", err)
	}
	if tag.RowsAffected() == 0 {
		return ErrInvitation
	}
	return nil
}
