package api

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/lets-parley/parley/internal/analyticsrelay"
)

func TestAnalyticsDisabledOrIncompleteRoutesNoDatabaseOrIdentity(t *testing.T) {
	for _, cfg := range []*analyticsrelay.Config{nil, {Upstream: "http://127.0.0.1:1", StateDir: t.TempDir(), Version: "release"}} {
		router := Router(nil, Options{AllowedOrigin: "https://scrum.matthew.systems", AnalyticsRelay: cfg, AnalyticsArtifactSHA256: strings.Repeat("a", 64)})
		for _, path := range []string{"/a/script.js", "/a/api/send", "/a/api/admin"} {
			method := "GET"
			if path == "/a/api/send" {
				method = "POST"
			}
			req := httptest.NewRequest(method, "https://scrum.matthew.systems"+path, strings.NewReader(`{}`))
			req.Header.Set("Content-Type", "application/json")
			req.Header.Set("Cookie", "parley_session=never-resolve")
			req.Header.Set("Authorization", "Bearer never-resolve")
			w := httptest.NewRecorder()
			router.Handler.ServeHTTP(w, req)
			if w.Code < 400 || strings.Contains(w.Body.String(), "<!doctype") {
				t.Fatalf("%s %d %s", path, w.Code, w.Body)
			}
			if w.Header().Get("X-Frame-Options") != "DENY" {
				t.Fatal("missing normal header profile")
			}
		}
	}
}

// Both positive baselines must work before the bearer negatives mean anything.
// A nil app pool plus a session cookie proves no identity/database resolution.
func TestAnalyticsEnabledRouterRejectsBearerWithReadyReceipt(t *testing.T) {
	policyBytes, err := os.ReadFile("../../web/src/lib/analytics-policy.json")
	if err != nil {
		t.Fatal(err)
	}
	var pins map[string]any
	if err = json.Unmarshal(policyBytes, &pins); err != nil {
		t.Fatal(err)
	}
	tracker, err := os.ReadFile("../analyticsrelay/testdata/umami-3.0.3.js")
	if err != nil {
		t.Fatal(err)
	}
	var calls atomic.Int32
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		calls.Add(1)
		for _, key := range []string{"Cookie", "Authorization", "Origin", "Referer", "X-Forwarded-For"} {
			if req.Header.Get(key) != "" {
				t.Errorf("identity forwarded: %s", key)
			}
		}
		w.Header().Set("Set-Cookie", "native=private")
		if req.URL.Path == "/script.js" {
			w.Write(tracker)
		} else {
			io.Copy(io.Discard, req.Body)
			io.WriteString(w, `{"cache":"private"}`)
		}
	}))
	defer upstream.Close()
	dir, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	artifact := strings.Repeat("a", 64)
	now := time.Now().UTC()
	sum := sha256.Sum256(policyBytes)
	receipt := map[string]any{"schema": 1, "generation": 1, "state": "ready", "checked_at": now.Format(time.RFC3339Nano), "valid_until": now.Add(time.Minute).Format(time.RFC3339Nano), "contract_schema": 1, "policy_sha256": hex.EncodeToString(sum[:]), "website_id": pins["website"], "collector_version": pins["collector_version"], "collector_image": pins["collector_image"], "tracker_sha256": pins["tracker_sha256"], "app_build": artifact}
	receiptBytes, _ := json.Marshal(receipt)
	if err = os.WriteFile(filepath.Join(dir, "admission.json"), receiptBytes, 0600); err != nil {
		t.Fatal(err)
	}
	origin := "https://" + pins["hostname"].(string)
	router := Router(nil, Options{AllowedOrigin: origin, AnalyticsArtifactSHA256: artifact, AnalyticsRelay: &analyticsrelay.Config{Upstream: upstream.URL, StateDir: dir, Origin: origin, Version: "relay-fixture"}})
	defer router.Shutdown()
	server := httptest.NewServer(router.Handler)
	defer server.Close()
	body, _ := json.Marshal(map[string]any{"type": "event", "payload": map[string]any{"website": pins["website"], "hostname": pins["hostname"], "url": "/", "title": pins["title"], "referrer": ""}})
	fetch := func(path, method, bearer string) (int, []byte) {
		req, err := http.NewRequest(method, server.URL+path, bytes.NewReader(body))
		if err != nil {
			t.Fatal(err)
		}
		req.Host = pins["hostname"].(string)
		req.Header.Set("Origin", origin)
		req.Header.Set("Content-Type", "application/json")
		req.AddCookie(&http.Cookie{Name: "parley_session", Value: "never-resolve"})
		if bearer != "" {
			req.Header.Set("Authorization", bearer)
		}
		resp, err := server.Client().Do(req)
		if err != nil {
			t.Fatal(err)
		}
		defer resp.Body.Close()
		data, err := io.ReadAll(resp.Body)
		if err != nil {
			t.Fatal(err)
		}
		if resp.Header.Get("X-Frame-Options") != "DENY" || resp.Header.Get("X-Content-Type-Options") != "nosniff" || resp.Header.Get("Content-Security-Policy") == "" {
			t.Error("ordinary security headers missing")
		}
		if resp.Header.Get("Set-Cookie") != "" {
			t.Error("native cookie reflected")
		}
		return resp.StatusCode, data
	}
	code, script := fetch("/a/script.js", "GET", "")
	if code != 200 || !bytes.Equal(script, tracker) {
		t.Fatalf("script baseline disabled: %d", code)
	}
	code, reply := fetch("/a/api/send", "POST", "")
	if code != 200 || string(reply) != "{}" || calls.Load() != 2 {
		t.Fatalf("send baseline disabled: %d count=%d", code, calls.Load())
	}
	for _, endpoint := range []struct{ path, method string }{{"/a/script.js", "GET"}, {"/a/api/send", "POST"}} {
		code, _ := fetch(endpoint.path, endpoint.method, "Bearer synthetic-embedded-token")
		if code != 403 || calls.Load() != 2 {
			t.Errorf("enabled bearer reached upstream for %s: status=%d calls=%d", endpoint.path, code, calls.Load())
		}
	}
}
