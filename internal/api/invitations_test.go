package api

import (
	"errors"
	"fmt"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/lets-parley/parley/internal/store"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestInviteOnlyRefusesUninvitedCreation(t *testing.T) {
	pool := testPool(t)
	srv := testServerWith(t, pool, Options{InviteOnly: true})
	stranger := signup(t, srv, "Uninvited")
	resp, _ := createSpace(t, srv, "Forbidden workspace", stranger)
	if resp.StatusCode != http.StatusForbidden {
		t.Fatalf("uninvited creation: got %d, want 403", resp.StatusCode)
	}
}

func inviteHost(t *testing.T, srv *httptest.Server, pool *pgxpool.Pool, name string) *http.Cookie {
	t.Helper()
	c := signup(t, srv, name)
	org, err := (&store.Orgs{Pool: pool}).Default(t.Context())
	if err != nil {
		t.Fatal(err)
	}
	_, token, err := (&store.Invitations{Pool: pool}).Mint(t.Context(), org.ID, nil, nil, "host")
	if err != nil {
		t.Fatal(err)
	}
	r, _ := doJSON(t, srv, "POST", "/api/invitations/accept", fmt.Sprintf(`{"token":%q}`, token), c)
	if r.StatusCode != 200 {
		t.Fatalf("bootstrap %d", r.StatusCode)
	}
	return c
}
func mintWorkspaceInvite(t *testing.T, srv *httptest.Server, host *http.Cookie, slug, role string) (string, string) {
	t.Helper()
	body := `{}`
	if role != "" {
		body = fmt.Sprintf(`{"role":%q}`, role)
	}
	r, out := doJSON(t, srv, "POST", "/api/orgs/default/spaces/"+slug+"/invitations", body, host)
	if r.StatusCode != 201 {
		t.Fatalf("mint %d: %v", r.StatusCode, out)
	}
	return strings.TrimPrefix(out["path"].(string), "/invite#t="), out["invitation"].(map[string]any)["id"].(string)
}
func TestInvitationsRolesAndDelegation(t *testing.T) {
	pool := testPool(t)
	srv := testServerWith(t, pool, Options{InviteOnly: true})
	host := inviteHost(t, srv, pool, "Host")
	r, sp := createSpace(t, srv, "Invited team", host)
	if r.StatusCode != 201 {
		t.Fatal(r.StatusCode)
	}
	slug := sp["slug"].(string)
	member := signup(t, srv, "Participant")
	token, _ := mintWorkspaceInvite(t, srv, host, slug, "")
	r, preview := doJSON(t, srv, "POST", "/api/invitations/preview", fmt.Sprintf(`{"token":%q}`, token), nil)
	if r.StatusCode != 200 || preview["role"] != "participant" {
		t.Fatalf("default: %d %v", r.StatusCode, preview)
	}
	r, _ = doJSON(t, srv, "POST", "/api/invitations/accept", fmt.Sprintf(`{"token":%q}`, token), member)
	if r.StatusCode != 200 {
		t.Fatal(r.StatusCode)
	}
	r, view := getSpace(t, srv, slug, member)
	if r.StatusCode != 200 || view["canHost"] != false || len(view["members"].([]any)) != 2 {
		t.Fatalf("participant view %v", view)
	}
	r, _ = createSpace(t, srv, "Denied", member)
	if r.StatusCode != 403 {
		t.Fatalf("participant create %d", r.StatusCode)
	}
	r, _ = createSession(t, srv, slug, "poker", "Denied", member)
	if r.StatusCode != 403 {
		t.Fatalf("participant session %d", r.StatusCode)
	}
	r, _ = doJSON(t, srv, "POST", "/api/orgs/default/spaces/"+slug+"/invitations", `{"role":"host"}`, member)
	if r.StatusCode != 403 {
		t.Fatalf("participant mint %d", r.StatusCode)
	}
	r, _ = createSession(t, srv, slug, "poker", "Allowed", host)
	if r.StatusCode != 201 {
		t.Fatalf("host session %d", r.StatusCode)
	}
	token, _ = mintWorkspaceInvite(t, srv, host, slug, "host")
	r, _ = doJSON(t, srv, "POST", "/api/invitations/accept", fmt.Sprintf(`{"token":%q}`, token), member)
	if r.StatusCode != 200 {
		t.Fatal(r.StatusCode)
	}
	_, view = getSpace(t, srv, slug, member)
	if view["canHost"] != true {
		t.Fatal("host permission missing")
	}
	r, _ = createSpace(t, srv, "Delegated team", member)
	if r.StatusCode != 201 {
		t.Fatalf("delegated host create %d", r.StatusCode)
	}
	mintWorkspaceInvite(t, srv, member, "delegated-team", "host")
	// Hosting in default does not confer hosting in a different organization.
	var other string
	if err := pool.QueryRow(t.Context(), `insert into orgs(slug,name,claim_value) values('other','Other','other') returning id`).Scan(&other); err != nil {
		t.Fatal(err)
	}
	_, me := getMe(t, srv, member)
	if err := (&store.Orgs{Pool: pool}).AddMember(t.Context(), other, me["id"].(string), store.OrgRoleMember); err != nil {
		t.Fatal(err)
	}
	r, _ = doJSON(t, srv, "POST", "/api/spaces", `{"name":"Other denied","org":"other"}`, member)
	if r.StatusCode != 403 {
		t.Fatalf("cross-org host %d", r.StatusCode)
	}
}
func TestInvitationsUnavailableAndAdmission(t *testing.T) {
	pool := testPool(t)
	srv := testServerWith(t, pool, Options{InviteOnly: true})
	host := inviteHost(t, srv, pool, "Host")
	_, sp := createSpace(t, srv, "Invite only", host)
	slug := sp["slug"].(string)
	outsider := signup(t, srv, "Outside")
	if r := joinSpace(t, srv, slug, outsider, sp["passcode"].(string)); r.StatusCode != 403 {
		t.Fatalf("legacy passcode admitted: %d", r.StatusCode)
	}
	r, _ := doJSON(t, srv, "POST", "/api/orgs/default/spaces/"+slug+"/passcode", `{"open":true}`, host)
	if r.StatusCode != 200 {
		t.Fatal(r.StatusCode)
	}
	if r := joinSpace(t, srv, slug, outsider); r.StatusCode != 403 {
		t.Fatalf("open admitted: %d", r.StatusCode)
	}
	for _, kind := range []string{"expired", "revoked", "used", "issuer-removed"} {
		t.Run(kind, func(t *testing.T) {
			token, id := mintWorkspaceInvite(t, srv, host, slug, "participant")
			switch kind {
			case "expired":
				_, err := pool.Exec(t.Context(), `update workspace_invitations set created_at=now()-interval '9 days',expires_at=now()-interval '1 day' where id=$1`, id)
				if err != nil {
					t.Fatal(err)
				}
			case "revoked":
				r, _ := doJSON(t, srv, "DELETE", "/api/orgs/default/spaces/"+slug+"/invitations/"+id, "", host)
				if r.StatusCode != 204 {
					t.Fatal(r.StatusCode)
				}
			case "used":
				r, _ := doJSON(t, srv, "POST", "/api/invitations/accept", fmt.Sprintf(`{"token":%q}`, token), outsider)
				if r.StatusCode != 200 {
					t.Fatal(r.StatusCode)
				}
			case "issuer-removed":
				_, me := getMe(t, srv, host)
				_, err := pool.Exec(t.Context(), `update members set role='member' where user_id=$1`, me["id"])
				if err != nil {
					t.Fatal(err)
				}
			}
			for _, path := range []string{"preview", "accept"} {
				r, _ := doJSON(t, srv, "POST", "/api/invitations/"+path, fmt.Sprintf(`{"token":%q}`, token), outsider)
				if r.StatusCode != 410 {
					t.Fatalf("%s %s got %d", kind, path, r.StatusCode)
				}
			}
		})
	}
}
func TestInvitationAcceptRaceAndRevokedOrg(t *testing.T) {
	pool := testPool(t)
	srv := testServerWith(t, pool, Options{InviteOnly: true})
	host := inviteHost(t, srv, pool, "Host")
	_, sp := createSpace(t, srv, "Race", host)
	slug := sp["slug"].(string)
	a, b := signup(t, srv, "A"), signup(t, srv, "B")
	token, _ := mintWorkspaceInvite(t, srv, host, slug, "host")
	_, am := getMe(t, srv, a)
	_, bm := getMe(t, srv, b)
	s := store.Invitations{Pool: pool}
	ch := make(chan error, 2)
	for _, id := range []string{am["id"].(string), bm["id"].(string)} {
		go func() { _, err := s.Accept(t.Context(), token, id); ch <- err }()
	}
	winners := 0
	for range 2 {
		if err := <-ch; err == nil {
			winners++
		} else if !errors.Is(err, store.ErrInvitation) {
			t.Fatal(err)
		}
	}
	if winners != 1 {
		t.Fatalf("%d winners", winners)
	}
	token, _ = mintWorkspaceInvite(t, srv, host, slug, "host")
	_, err := pool.Exec(t.Context(), `update org_members set revoked_at=now() where user_id=$1`, am["id"])
	if err != nil {
		t.Fatal(err)
	}
	if _, err = s.Accept(t.Context(), token, am["id"].(string)); !errors.Is(err, store.ErrInvitation) {
		t.Fatalf("org revocation resurrected: %v", err)
	}
}
