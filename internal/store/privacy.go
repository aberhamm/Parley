package store

import (
	"context"
	"errors"
	"log/slog"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

var ErrRetentionDays = errors.New("retention must be 0, 1, 7, 30, or 90 days")

type Privacy struct{ Pool *pgxpool.Pool }

func (p *Privacy) Retention(ctx context.Context, spaceID string) (int, error) {
	var days int
	err := p.Pool.QueryRow(ctx, "select retention_days from spaces where id=$1", spaceID).Scan(&days)
	if errors.Is(err, pgx.ErrNoRows) {
		err = ErrNoSpace
	}
	return days, err
}

// SetRetention repeats mutable hosting/ownership checks inside the write. The
// space lock also serializes retention changes with creation and expiry.
func (p *Privacy) SetRetention(ctx context.Context, spaceID, userID string, days int, inviteOnly bool) error {
	if days != 0 && days != 1 && days != 7 && days != 30 && days != 90 {
		return ErrRetentionDays
	}
	tx, err := p.Pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	if err = lockActiveProfile(ctx, tx, userID); err != nil {
		return err
	}
	var orgID string
	if err = tx.QueryRow(ctx, "select org_id::text from spaces where id=$1 for update", spaceID).Scan(&orgID); errors.Is(err, pgx.ErrNoRows) {
		return ErrNoSpace
	} else if err != nil {
		return err
	}
	var owner string
	err = tx.QueryRow(ctx, "select m.user_id::text from members m join org_members o on o.org_id=$3 and o.user_id=m.user_id and o.revoked_at is null where m.space_id=$1 and m.user_id=$2 and m.role='owner' for share of m,o", spaceID, userID, orgID).Scan(&owner)
	if errors.Is(err, pgx.ErrNoRows) {
		return ErrNotMember
	}
	if err != nil {
		return err
	}
	// Lock the grant until commit so an in-flight revocation cannot race it.
	if inviteOnly {
		var grant string
		err = tx.QueryRow(ctx, "select user_id::text from hosting_grants where org_id=$1 and user_id=$2 for share", orgID, userID).Scan(&grant)
		if errors.Is(err, pgx.ErrNoRows) {
			return ErrNotEligible
		}
		if err != nil {
			return err
		}
	}
	if _, err = tx.Exec(ctx, "update spaces set retention_days=$2 where id=$1", spaceID, days); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

// SweepExpired removes bounded batches of ended sessions only. A reopened room
// is protected by the row lock and the predicate is rechecked after locking.
// The database receipt trigger commits with the deletion. Socket revalidation
// observes the missing room on every replica without keeping content around.
func (p *Privacy) SweepExpired(ctx context.Context) (int64, error) {
	tx, err := p.Pool.Begin(ctx)
	if err != nil {
		return 0, err
	}
	defer tx.Rollback(ctx)
	// Lock spaces first, matching session creation, and skip busy workspaces.
	rows, err := tx.Query(ctx, `select id::text,retention_days from spaces where retention_days>0 and exists (select 1 from sessions se where se.space_id=spaces.id and se.ended_at is not null and se.ended_at < clock_timestamp()-make_interval(days=>spaces.retention_days)) order by id for update skip locked limit 100`)
	if err != nil {
		return 0, err
	}
	type policy struct {
		id   string
		days int
	}
	var policies []policy
	for rows.Next() {
		var v policy
		if err = rows.Scan(&v.id, &v.days); err != nil {
			rows.Close()
			return 0, err
		}
		policies = append(policies, v)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return 0, err
	}
	var total int64
	for _, v := range policies {
		if total >= 100 {
			break
		}
		tag, e := tx.Exec(ctx, `delete from sessions where id in (select id from sessions where space_id=$1 and ended_at is not null and ended_at < clock_timestamp()-make_interval(days=>$2) order by ended_at for update skip locked limit $3) and ended_at is not null and ended_at < clock_timestamp()-make_interval(days=>$2)`, v.id, v.days, 100-total)
		if e != nil {
			return 0, e
		}
		total += tag.RowsAffected()
	}
	if err = tx.Commit(ctx); err != nil {
		return 0, err
	}
	return total, nil
}

func (p *Privacy) RunRetention(ctx context.Context, interval time.Duration, log *slog.Logger) {
	tick := time.NewTicker(interval)
	defer tick.Stop()
	sweep := func() {
		n, err := p.SweepExpired(ctx)
		if err != nil && ctx.Err() == nil {
			log.Error("privacy retention failed; will retry", "error", err)
		} else if n > 0 {
			log.Info("privacy retention", "sessions_deleted", n)
		}
	}
	sweep()
	for {
		select {
		case <-ctx.Done():
			return
		case <-tick.C:
			sweep()
		}
	}
}
