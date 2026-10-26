package api

import (
	"errors"
	"net/http"

	"github.com/lets-parley/parley/internal/httprequest"
	"github.com/lets-parley/parley/internal/store"
)

func (a *app) handleEraseProfile(w http.ResponseWriter, r *http.Request) {
	p, ok := PrincipalFrom(r.Context())
	if !ok {
		http.Error(w, `{"error":"not signed in"}`, http.StatusUnauthorized)
		return
	}
	if p.IsLinkGuest() || p.Embedded {
		http.Error(w, `{"error":"profile deletion requires a full account"}`, http.StatusForbidden)
		return
	}
	var body struct {
		Confirm string `json:"confirm"`
	}
	if err := httprequest.DecodeJSON(w, r, httprequest.MaxJSONBody, &body); err != nil {
		httprequest.WriteDecodeError(w, err, `{"error":"invalid JSON body"}`)
		return
	}
	if body.Confirm != "DELETE" {
		http.Error(w, `{"error":"type DELETE to confirm profile deletion"}`, http.StatusBadRequest)
		return
	}
	result, err := a.users.EraseProfile(r.Context(), p.UserID)
	if errors.Is(err, store.ErrProfileHandoff) {
		http.Error(w, `{"error":"hand over workspace ownership or organization administration before deleting your profile"}`, http.StatusConflict)
		return
	}
	if errors.Is(err, store.ErrNoUser) {
		http.Error(w, `{"error":"session ended"}`, http.StatusUnauthorized)
		return
	}
	if err != nil {
		http.Error(w, `{"error":"could not delete your profile"}`, http.StatusInternalServerError)
		return
	}
	for _, hash := range result.TokenHashes {
		a.hub.DisconnectToken(string(hash))
		a.notifyRevoke(r.Context(), hash)
	}
	for _, id := range result.Sessions {
		a.broadcastState(r.Context(), id)
	}
	clearSessionCookie(w, a.secureCookies)
	w.WriteHeader(http.StatusNoContent)
}
