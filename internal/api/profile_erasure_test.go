package api

import (
	"net/http"
	"testing"
	"time"

	"github.com/gorilla/websocket"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/lets-parley/parley/internal/store"
)

func storeTokenForProfileTest(t *testing.T, pool *pgxpool.Pool, id string) (string, []byte) {
	t.Helper()
	plain, hash := store.NewToken()
	if _, err := pool.Exec(t.Context(), "insert into session_tokens(token_hash,user_id) values($1,$2)", hash, id); err != nil {
		t.Fatal(err)
	}
	return plain, hash
}

func TestProfileErasureRefusesLastOwnerAndAnonymous(t *testing.T) {
	pool := testPool(t)
	srv := testServerWith(t, pool, Options{InviteOnly: true})
	resp, _ := doJSON(t, srv, "POST", "/api/me/erase", `{"confirm":"DELETE"}`, nil)
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatal(resp.StatusCode)
	}
	owner := inviteHost(t, srv, pool, "Sole owner")
	resp, _ = createSpace(t, srv, "Profile handoff test", owner)
	if resp.StatusCode != http.StatusCreated {
		t.Fatal(resp.StatusCode)
	}
	resp, _ = doJSON(t, srv, "POST", "/api/me/erase", `{"confirm":"DELETE"}`, owner)
	if resp.StatusCode != http.StatusConflict {
		t.Fatalf("last owner erase=%d, want409", resp.StatusCode)
	}
	resp, _ = doJSON(t, srv, "GET", "/api/me", "", owner)
	if resp.StatusCode != http.StatusOK {
		t.Fatal("refusal invalidated the identity")
	}
}

func TestProfileErasureClosesAllOwnSocketsAndPreservesOthers(t *testing.T) {
	srv := testServer(t)
	slug, owner, _, member, _ := spaceWithTwo(t, srv)
	_, sess := createSession(t, srv, slug, "poker", "Profile socket test", owner)
	id := sess["id"].(string)
	memberWS, _, err := dialWS(t, srv, id, member, "")
	if err != nil {
		t.Fatal(err)
	}
	defer memberWS.Close()
	ownerWS, _, err := dialWS(t, srv, id, owner, "")
	if err != nil {
		t.Fatal(err)
	}
	defer ownerWS.Close()
	if _, ok := readEnvelope(t, memberWS, 2*time.Second); !ok {
		t.Fatal("member initial envelope absent")
	}
	if _, ok := readEnvelope(t, ownerWS, 2*time.Second); !ok {
		t.Fatal("owner initial envelope absent")
	}
	resp, _ := doJSON(t, srv, "POST", "/api/me/erase", `{"confirm":"DELETE"}`, member)
	if resp.StatusCode != http.StatusNoContent {
		t.Fatal(resp.StatusCode)
	}
	memberWS.SetReadDeadline(time.Now().Add(2 * time.Second))
	for {
		_, _, err = memberWS.ReadMessage()
		if err != nil {
			break
		}
	}
	if closeErr, ok := err.(*websocket.CloseError); !ok || closeErr.Code != websocket.ClosePolicyViolation {
		t.Fatalf("own socket close=%v", err)
	}
	if _, ok := readEnvelope(t, ownerWS, 2*time.Second); !ok {
		t.Fatal("other member did not retain a working room socket")
	}
}

func TestProfileErasureRequiresConfirmationAndInvalidatesEveryToken(t *testing.T) {
	pool := testPool(t)
	srv := testServerWith(t, pool, Options{InviteOnly: true})
	account := signup(t, srv, "Erase this private name")
	_, me := doJSON(t, srv, "GET", "/api/me", "", account)
	userID := me["id"].(string)
	_, secondHash := storeTokenForProfileTest(t, pool, userID)
	resp, _ := doJSON(t, srv, "POST", "/api/me/erase", `{"confirm":"wrong"}`, account)
	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("confirmation: got %d, want 400", resp.StatusCode)
	}
	resp, _ = doJSON(t, srv, "POST", "/api/me/erase", `{"confirm":"DELETE"}`, account)
	if resp.StatusCode != http.StatusNoContent {
		t.Fatalf("erase: got %d, want 204", resp.StatusCode)
	}
	resp, _ = doJSON(t, srv, "GET", "/api/me", "", account)
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("old identity still valid: %d", resp.StatusCode)
	}
	var count int
	if err := pool.QueryRow(t.Context(), "select count(*) from session_tokens where user_id=$1 or token_hash=$2", userID, secondHash).Scan(&count); err != nil || count != 0 {
		t.Fatalf("all login tokens must be gone: count=%d err=%v", count, err)
	}
}
