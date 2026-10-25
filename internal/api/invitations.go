package api

import (
	"errors"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/lets-parley/parley/internal/httprequest"
	"github.com/lets-parley/parley/internal/store"
)

func (a *app) invitationStore() *store.Invitations { return &store.Invitations{Pool: a.pool} }
func (a *app) hostingAllowed(w http.ResponseWriter, r *http.Request, orgID string) bool {
	if !a.inviteOnly {
		return true
	}
	p, ok := PrincipalFrom(r.Context())
	if !ok || p.IsLinkGuest() || p.Embedded {
		http.Error(w, `{"error":"hosting requires a host invitation"}`, http.StatusForbidden)
		return false
	}
	yes, err := a.invitationStore().CanHost(r.Context(), orgID, p.UserID)
	if err != nil {
		http.Error(w, `{"error":"could not check hosting access"}`, http.StatusInternalServerError)
		return false
	}
	if !yes {
		http.Error(w, `{"error":"hosting requires a host invitation"}`, http.StatusForbidden)
		return false
	}
	return true
}
func invitationFailure(w http.ResponseWriter, err error) {
	if errors.Is(err, store.ErrInvitation) {
		http.Error(w, `{"error":"this invitation is expired, revoked, already used, or unavailable"}`, http.StatusGone)
		return
	}
	http.Error(w, `{"error":"could not process invitation"}`, http.StatusInternalServerError)
}
func (a *app) handleMintInvitation(w http.ResponseWriter, r *http.Request) {
	sp := spaceFrom(r.Context())
	p, _ := PrincipalFrom(r.Context())
	var body struct {
		Role string `json:"role"`
	}
	if err := decodeOptional(w, r, &body); err != nil {
		httprequest.WriteDecodeError(w, err, `{"error":"invalid JSON body"}`)
		return
	}
	if body.Role == "" {
		body.Role = "participant"
	}
	if body.Role != "host" && body.Role != "participant" {
		http.Error(w, `{"error":"role must be participant or host"}`, http.StatusBadRequest)
		return
	}
	i, token, err := a.invitationStore().Mint(r.Context(), orgFrom(r.Context()).ID, &sp.ID, &p.UserID, body.Role)
	if errors.Is(err, store.ErrQuotaExceeded) {
		http.Error(w, `{"error":"too many pending invitations; revoke an unused invitation first"}`, http.StatusConflict)
		return
	}
	if err != nil {
		invitationFailure(w, err)
		return
	}
	// Only the creating response contains the raw capability. URL fragments
	// never reach access logs; subsequent list responses have no token field.
	writeJSON(w, http.StatusCreated, map[string]any{"invitation": i, "path": "/invite#t=" + token})
	logSecEvent(r, secEvent{Event: "invitation.create", Target: i.ID, Org: orgFrom(r.Context()).Slug, Space: sp.Slug})
}
func (a *app) handleListInvitations(w http.ResponseWriter, r *http.Request) {
	out, err := a.invitationStore().List(r.Context(), orgFrom(r.Context()).ID, spaceFrom(r.Context()).ID)
	if err != nil {
		invitationFailure(w, err)
		return
	}
	writeJSON(w, http.StatusOK, out)
}
func (a *app) handleRevokeInvitation(w http.ResponseWriter, r *http.Request) {
	err := a.invitationStore().Revoke(r.Context(), orgFrom(r.Context()).ID, spaceFrom(r.Context()).ID, chi.URLParam(r, "invitationId"))
	if err != nil {
		invitationFailure(w, err)
		return
	}
	logSecEvent(r, secEvent{Event: "invitation.revoke", Target: chi.URLParam(r, "invitationId"), Org: orgFrom(r.Context()).Slug, Space: spaceFrom(r.Context()).Slug})
	w.WriteHeader(http.StatusNoContent)
}
func invitationToken(w http.ResponseWriter, r *http.Request) (string, bool) {
	var b struct {
		Token string `json:"token"`
	}
	if err := httprequest.DecodeJSON(w, r, httprequest.MaxJSONBody, &b); err != nil {
		httprequest.WriteDecodeError(w, err, `{"error":"invalid JSON body"}`)
		return "", false
	}
	return b.Token, true
}
func (a *app) handlePreviewInvitation(w http.ResponseWriter, r *http.Request) {
	token, ok := invitationToken(w, r)
	if !ok {
		return
	}
	i, err := a.invitationStore().Preview(r.Context(), token)
	if err != nil {
		invitationFailure(w, err)
		return
	}
	writeJSON(w, http.StatusOK, i)
}
func (a *app) handleAcceptInvitation(w http.ResponseWriter, r *http.Request) {
	token, ok := invitationToken(w, r)
	if !ok {
		return
	}
	p, _ := PrincipalFrom(r.Context())
	i, err := a.invitationStore().Accept(r.Context(), token, p.UserID)
	if err != nil {
		invitationFailure(w, err)
		return
	}
	logSecEvent(r, secEvent{Event: "invitation.accept", Target: i.ID, Org: i.OrgSlug})
	writeJSON(w, http.StatusOK, i)
}
