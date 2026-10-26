package store

import (
	"context"
	"errors"
	"fmt"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
)

var ErrProfileHandoff = errors.New("hand over workspace ownership or organization administration before deleting your profile")

// ProfileErasure contains only the transport invalidations needed after commit.
// It is never serialized or logged: token hashes are internal credentials.
type ProfileErasure struct {
	TokenHashes [][]byte
	Sessions    []string
}

func (s *Users) EraseProfile(ctx context.Context, userID string) (ProfileErasure, error) {
	for attempt := 0; ; attempt++ {
		result, err := s.eraseProfile(ctx, userID)
		var pgerr *pgconn.PgError
		if attempt < 2 && errors.As(err, &pgerr) && pgerr.Code == "40P01" {
			continue
		}
		return result, err
	}
}

func (s *Users) eraseProfile(ctx context.Context, userID string) (ProfileErasure, error) {
	tx, err := s.Pool.Begin(ctx)
	if err != nil {
		return ProfileErasure{}, fmt.Errorf("beginning profile erasure: %w", err)
	}
	defer tx.Rollback(ctx)
	var live bool
	if err := tx.QueryRow(ctx, "select erased_at is null from users where id=$1 for update", userID).Scan(&live); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return ProfileErasure{}, ErrNoUser
		}
		return ProfileErasure{}, fmt.Errorf("locking profile: %w", err)
	}
	if !live {
		return ProfileErasure{}, ErrNoUser
	}
	result := ProfileErasure{}
	rows, err := tx.Query(ctx, `select token_hash from session_tokens where user_id=$1 or user_id in
		(select u.id from users u join session_links l on l.id=u.link_id where l.created_by=$1)`, userID)
	if err != nil {
		return result, err
	}
	for rows.Next() {
		var hash []byte
		if err := rows.Scan(&hash); err != nil {
			rows.Close()
			return result, err
		}
		result.TokenHashes = append(result.TokenHashes, hash)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return result, err
	}
	rows, err = tx.Query(ctx, `select distinct s.id::text from sessions s where s.facilitator_id=$1
		or exists(select 1 from members m where m.space_id=s.space_id and m.user_id=$1)
		or exists(select 1 from standup_entries e where e.session_id=s.id and e.user_id=$1)
		or exists(select 1 from stories st join votes v on v.story_id=st.id where st.session_id=s.id and v.user_id=$1)`, userID)
	if err != nil {
		return result, err
	}
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			return result, err
		}
		result.Sessions = append(result.Sessions, id)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return result, err
	}
	var erased bool
	if err := tx.QueryRow(ctx, "select privacy_erase_profile($1::uuid)", userID).Scan(&erased); err != nil {
		var pgerr *pgconn.PgError
		if errors.As(err, &pgerr) && pgerr.Code == "P0062" {
			return result, ErrProfileHandoff
		}
		return result, fmt.Errorf("erasing profile: %w", err)
	}
	if !erased {
		return result, ErrNoUser
	}
	if len(result.Sessions) > 0 {
		if _, err := tx.Exec(ctx, "update sessions set version=version+1 where id=any($1::uuid[])", result.Sessions); err != nil {
			return result, err
		}
	}
	return result, tx.Commit(ctx)
}

// A request may have authenticated immediately before profile erasure. Holding
// this lock through a session mutation keeps that request from writing after
// the erasure commits, including writes without a direct user foreign key.
func lockActiveProfile(ctx context.Context, tx pgx.Tx, id string) error {
	var live bool
	err := tx.QueryRow(ctx, "select erased_at is null from users where id=$1 for share", id).Scan(&live)
	if errors.Is(err, pgx.ErrNoRows) || (err == nil && !live) {
		return ErrNoUser
	}
	return err
}
