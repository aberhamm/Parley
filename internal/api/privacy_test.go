package api

import (
	"fmt"
	"net/http"
	"testing"
)

func TestWorkspacePrivacyOwnerScopeAndValidation(t *testing.T) {
	pool := testPool(t)
	srv := testServerWith(t, pool, Options{InviteOnly: true})
	owner := inviteHost(t, srv, pool, "Privacy owner")
	r, sp := createSpace(t, srv, "Privacy "+randomSlugSuffix(t), owner)
	if r.StatusCode != 201 {
		t.Fatal(r.StatusCode)
	}
	path := "/api/orgs/default/spaces/" + sp["slug"].(string) + "/privacy"
	r, out := doJSON(t, srv, "GET", path, "", owner)
	if r.StatusCode != 200 || out["retentionDays"] != float64(0) {
		t.Fatalf("default privacy: %d %v", r.StatusCode, out)
	}
	r, out = doJSON(t, srv, "PUT", path, `{"retentionDays":7}`, owner)
	if r.StatusCode != 200 || out["retentionDays"] != float64(7) {
		t.Fatalf("save privacy: %d %v", r.StatusCode, out)
	}
	for _, body := range []string{`{}`, `{"retentionDays":-1}`, `{"retentionDays":2}`, `{"retentionDays":7,"unknown":true}`} {
		r, _ = doJSON(t, srv, "PUT", path, body, owner)
		if r.StatusCode != 400 {
			t.Fatalf("bad policy %s: %d", body, r.StatusCode)
		}
	}
	member := signup(t, srv, "Privacy participant")
	token, _ := mintWorkspaceInvite(t, srv, owner, sp["slug"].(string), "participant")
	r, _ = doJSON(t, srv, "POST", "/api/invitations/accept", fmt.Sprintf(`{"token":%q}`, token), member)
	if r.StatusCode != 200 {
		t.Fatal(r.StatusCode)
	}
	for _, method := range []string{"GET", "PUT"} {
		r, _ = doJSON(t, srv, method, path, `{"retentionDays":1}`, member)
		if r.StatusCode != http.StatusForbidden {
			t.Fatalf("participant %s: %d", method, r.StatusCode)
		}
		r, _ = doJSON(t, srv, method, "/api/orgs/missing/spaces/"+sp["slug"].(string)+"/privacy", `{"retentionDays":1}`, owner)
		if r.StatusCode != 404 {
			t.Fatalf("foreign org %s: %d", method, r.StatusCode)
		}
	}
}
