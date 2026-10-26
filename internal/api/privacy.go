package api

import (
	"encoding/json"
	"errors"
	"net/http"

	"github.com/lets-parley/parley/internal/httprequest"
	"github.com/lets-parley/parley/internal/store"
)

func (a *app) handleGetPrivacy(w http.ResponseWriter, r *http.Request) {
	days, err := (&store.Privacy{Pool: a.pool}).Retention(r.Context(), spaceFrom(r.Context()).ID)
	if err != nil {
		http.Error(w, `{"error":"could not read retention"}`, http.StatusInternalServerError)
		return
	}
	writeJSON(w, http.StatusOK, map[string]int{"retentionDays": days})
}

func (a *app) handlePutPrivacy(w http.ResponseWriter, r *http.Request) {
	var raw map[string]json.RawMessage
	if err := httprequest.DecodeJSON(w, r, httprequest.MaxJSONBody, &raw); err != nil {
		httprequest.WriteDecodeError(w, err, `{"error":"invalid retention policy"}`)
		return
	}
	var days *int
	if len(raw) != 1 || raw["retentionDays"] == nil || json.Unmarshal(raw["retentionDays"], &days) != nil || days == nil {
		http.Error(w, `{"error":"choose a valid retention period"}`, http.StatusBadRequest)
		return
	}
	p, _ := PrincipalFrom(r.Context())
	err := (&store.Privacy{Pool: a.pool}).SetRetention(r.Context(), spaceFrom(r.Context()).ID, p.UserID, *days, a.inviteOnly)
	if errors.Is(err, store.ErrRetentionDays) {
		http.Error(w, `{"error":"retention must be 0, 1, 7, 30, or 90 days"}`, http.StatusBadRequest)
		return
	}
	if errors.Is(err, store.ErrNotMember) || errors.Is(err, store.ErrNotEligible) {
		http.Error(w, `{"error":"only a current host who owns this workspace can change retention"}`, http.StatusForbidden)
		return
	}
	if err != nil {
		http.Error(w, `{"error":"could not save retention"}`, http.StatusInternalServerError)
		return
	}
	writeJSON(w, http.StatusOK, map[string]int{"retentionDays": *days})
}
