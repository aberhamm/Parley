package main

import (
	"encoding/json"
	"github.com/lets-parley/parley/internal/api"
	"net/http/httptest"
	"testing"
)

func TestInviteOnlyDefaultsAndMainWiring(t *testing.T) {
	baseConfigEnv(t)
	t.Setenv("INVITE_ONLY", "")
	cfg, err := loadConfig()
	if err != nil {
		t.Fatal(err)
	}
	if !cfg.InviteOnly {
		t.Fatal("invite-only must default on")
	}
	opts := apiOptions(t.Context(), cfg, false, nil, nil, nil)
	handler := api.Router(nil, opts)
	defer handler.Shutdown()
	req := httptest.NewRequest("GET", "/api/auth", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	var out map[string]any
	json.Unmarshal(rec.Body.Bytes(), &out)
	if out["inviteOnly"] != true {
		t.Fatalf("main forgot invite-only: %s", rec.Body.String())
	}
	t.Setenv("INVITE_ONLY", "false")
	cfg, err = loadConfig()
	if err != nil || cfg.InviteOnly {
		t.Fatal("explicit legacy mode not honored")
	}
	t.Setenv("INVITE_ONLY", "garbage")
	if _, err = loadConfig(); err == nil {
		t.Fatal("bad flag accepted")
	}
}
