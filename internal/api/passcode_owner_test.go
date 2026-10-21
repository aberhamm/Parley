package api

import (
	"context"
	"net/http"
	"testing"
)

// The API must enforce ownership even if a member bypasses the settings UI.
func TestPasscodeChangesRequireSpaceOwner(t *testing.T) {
	pool := testPool(t)
	srv := testServerWith(t, pool, Options{AllowedOrigin: testOrigin})
	slug, owner, ownerID, code := privateSpace(t, srv)
	member, memberID := signupWithID(t, srv, "Member")
	custodyJoin(t, srv, slug, code, member)
	outsider := signup(t, srv, "Outsider")
	admin, adminID := signupWithID(t, srv, "Admin")
	makeOrgAdmin(t, pool, adminID)
	custodyJoin(t, srv, slug, code, admin)
	path := "/api/orgs/default/spaces/" + slug + "/passcode"
	assertCode := func(t *testing.T, want string) {
		t.Helper()
		_, view := getSpace(t, srv, slug, owner)
		if view["passcode"] != want {
			t.Fatalf("passcode changed after refused request: got %v, want %q", view["passcode"], want)
		}
	}
	for _, tc := range []struct {
		name   string
		cookie *http.Cookie
		want   int
	}{
		{"member", member, http.StatusForbidden},
		{"org admin who is a member", admin, http.StatusForbidden},
		{"outsider", outsider, http.StatusNotFound},
		{"anonymous", nil, http.StatusUnauthorized},
	} {
		t.Run(tc.name, func(t *testing.T) {
			for _, body := range []string{`{}`, `{"open":true}`} {
				resp, result := doJSON(t, srv, "POST", path, body, tc.cookie)
				if resp.StatusCode != tc.want {
					t.Errorf("body %s: got %d (%v), want %d", body, resp.StatusCode, result, tc.want)
				}
				assertCode(t, code)
			}
		})
	}
	// An owner's cookie confers no authority once their role is demoted or removed.
	if _, err := pool.Exec(context.Background(), "update members set role = 'owner' where user_id = $1", memberID); err != nil {
		t.Fatal(err)
	}
	resp, rotated := doJSON(t, srv, "POST", path, `{}`, member)
	next, _ := rotated["passcode"].(string)
	if resp.StatusCode != http.StatusOK || next == "" || next == code {
		t.Fatalf("second owner rotate = %d (%v)", resp.StatusCode, rotated)
	}
	code = next
	if _, err := pool.Exec(context.Background(), "update members set role = 'member' where user_id = $1", memberID); err != nil {
		t.Fatal(err)
	}
	for _, body := range []string{`{}`, `{"open":true}`} {
		resp, _ := doJSON(t, srv, "POST", path, body, member)
		if resp.StatusCode != http.StatusForbidden {
			t.Errorf("demoted owner = %d, want 403", resp.StatusCode)
		}
		assertCode(t, code)
	}
	if _, err := pool.Exec(context.Background(), "delete from members where user_id = $1", memberID); err != nil {
		t.Fatal(err)
	}
	resp, _ = doJSON(t, srv, "POST", path, `{"open":true}`, member)
	if resp.StatusCode != http.StatusNotFound {
		t.Errorf("removed owner = %d, want 404", resp.StatusCode)
	}
	assertCode(t, code)
	// The same slug in a different org never borrows ownership from this one.
	other := otherOrgHoldingSlug(t, pool, slug, ownerID, ownerID)
	resp, _ = doJSON(t, srv, "POST", "/api/orgs/"+other+"/spaces/"+slug+"/passcode", `{"open":true}`, owner)
	if resp.StatusCode != http.StatusNotFound {
		t.Errorf("other org's space = %d, want 404", resp.StatusCode)
	}
	assertCode(t, code)
	resp, opened := doJSON(t, srv, "POST", path, `{"open":true}`, owner)
	if resp.StatusCode != http.StatusOK || opened["protected"] != false || opened["passcode"] != "" {
		t.Fatalf("owner open = %d (%v)", resp.StatusCode, opened)
	}
	resp, protected := doJSON(t, srv, "POST", path, `{}`, owner)
	if resp.StatusCode != http.StatusOK || protected["protected"] != true || protected["passcode"] == "" {
		t.Fatalf("owner re-protect open space = %d (%v)", resp.StatusCode, protected)
	}
}
