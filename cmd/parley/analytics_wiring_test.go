package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"runtime"
	"sync/atomic"
	"time"

	"net/http/httptest"
	"net/url"

	"path/filepath"
	"strings"
	"testing"

	"github.com/lets-parley/parley/internal/analyticsrelay"
	"github.com/lets-parley/parley/internal/api"
)

func TestAnalyticsExecutableIdentity(t *testing.T) {
	for _, binary := range []string{"artifact-one", "artifact-two"} {
		got, err := hashExecutable(func() (io.ReadCloser, error) { return io.NopCloser(strings.NewReader(binary)), nil })
		sum := sha256.Sum256([]byte(binary))
		if err != nil || got != hex.EncodeToString(sum[:]) {
			t.Fatal("artifact not hashed")
		}
	}
	if got, err := hashExecutable(func() (io.ReadCloser, error) { return nil, errors.New("unavailable") }); got != "" || err == nil {
		t.Fatal("missing executable accepted")
	}
}
func TestAnalyticsMainMappingAndFailureIsolation(t *testing.T) {
	base, _ := url.Parse("https://scrum.matthew.systems")
	dir, _ := filepath.EvalSymlinks(t.TempDir())
	cfg := config{BaseURL: base, AnalyticsRelayURL: "http://scrum-analytics-collector:3000", AnalyticsRelayStateDir: dir, AnalyticsArtifactSHA256: strings.Repeat("a", 64)}
	opts := apiOptions(context.Background(), cfg, true, nil, nil, nil)
	if opts.AnalyticsRelay == nil || opts.AnalyticsArtifactSHA256 != cfg.AnalyticsArtifactSHA256 {
		t.Fatal("dead main wiring")
	}
	// A real router from main mapping must expose the relay refusal, not SPA,
	// with nil DB: analytics must not consult an app principal/database.
	for _, fp := range []string{cfg.AnalyticsArtifactSHA256, ""} {
		cfg.AnalyticsArtifactSHA256 = fp
		router := api.Router(nil, apiOptions(context.Background(), cfg, true, nil, nil, nil))
		for _, path := range []string{"/a/script.js", "/healthz"} {
			req := httptest.NewRequest("GET", base.String()+path, nil)
			w := httptest.NewRecorder()
			router.Handler.ServeHTTP(w, req)
			if path == "/healthz" && w.Code != 200 {
				t.Fatal("analytics broke app health")
			}
			if path == "/a/script.js" && (w.Code < 400 || strings.Contains(w.Body.String(), "<!doctype")) {
				t.Fatal("unproven analytics reached fallback")
			}
			if w.Header().Get("X-Frame-Options") != "DENY" {
				t.Fatal("missing security headers")
			}
		}
	}
}
func TestAnalyticsConfigFailsClosedOnly(t *testing.T) {
	t.Setenv("DATABASE_URL", "postgres://test:test@localhost:5432/test?sslmode=disable")
	t.Setenv("DATABASE_ALLOW_PLAINTEXT", "true")
	for _, url := range []string{"", "https://evil.test", "http://scrum-analytics-collector:3000/extra", "http://user@localhost:3000"} {
		t.Setenv("ANALYTICS_RELAY_URL", url)
		t.Setenv("ANALYTICS_RELAY_STATE_DIR", t.TempDir())
		cfg, err := loadConfig()
		if err != nil {
			t.Fatal(err)
		}
		if cfg.AnalyticsRelayURL != "" {
			t.Fatal("invalid config enabled analytics")
		}
	}
}

// The application process hashes its own delivered executable, never an env label.
func TestRunningExecutableFingerprint(t *testing.T) {
	got, err := runningExecutableSHA256()
	if runtime.GOOS != "linux" {
		if got != "" || err == nil {
			t.Fatal("unsupported custody enabled analytics")
		}
		return
	}
	if err != nil || len(got) != 64 {
		t.Fatalf("%s %v", got, err)
	}
}

func TestAnalyticsRealMainMappedRouterForwardsOnlyWithBoundProof(t *testing.T) {
	previous := version
	version = "relay-fixture-release"
	t.Cleanup(func() { version = previous })
	base, _ := url.Parse("https://scrum.matthew.systems")
	dir, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	cfg := config{BaseURL: base, AnalyticsRelayURL: "http://scrum-analytics-collector:3000", AnalyticsRelayStateDir: dir, AnalyticsArtifactSHA256: strings.Repeat("a", 64)}
	var calls atomic.Int32
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) { calls.Add(1); io.WriteString(w, `{"cache":"private"}`) }))
	defer upstream.Close()
	opts := apiOptions(context.Background(), cfg, true, nil, nil, nil)
	opts.AnalyticsRelay.Upstream = upstream.URL // Only the isolated typed test seam; production parser remains fixed.
	raw, err := os.ReadFile("../../web/src/lib/analytics-policy.json")
	if err != nil {
		t.Fatal(err)
	}
	var pins map[string]any
	if err = json.Unmarshal(raw, &pins); err != nil {
		t.Fatal(err)
	}
	now := time.Now().UTC()
	receipt := map[string]any{"schema": 1, "generation": 1, "state": "ready", "checked_at": now.Format(time.RFC3339Nano), "valid_until": now.Add(time.Minute).Format(time.RFC3339Nano), "contract_schema": 1, "policy_sha256": analyticsrelay.PolicySHA256(), "website_id": pins["website"], "collector_version": pins["collector_version"], "collector_image": pins["collector_image"], "tracker_sha256": pins["tracker_sha256"], "app_build": cfg.AnalyticsArtifactSHA256}
	raw, _ = json.Marshal(receipt)
	if err = os.WriteFile(filepath.Join(dir, "admission.json"), raw, 0600); err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(api.Router(nil, opts).Handler)
	defer server.Close()
	payload := `{"type":"event","payload":{"website":"acc214c0-d772-493a-ad03-49fa8e72d77e","hostname":"scrum.matthew.systems","url":"/","title":"Scrum Pro","referrer":""}}`
	req, _ := http.NewRequest("POST", server.URL+"/a/api/send", strings.NewReader(payload))
	req.Host = base.Host
	req.Header.Set("Content-Type", "application/json")
	req.AddCookie(&http.Cookie{Name: "parley_session", Value: "must-not-resolve"})
	resp, err := server.Client().Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	response, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != 200 || string(response) != "{}" || calls.Load() != 1 {
		t.Fatalf("real main mapping dead: %d %s calls=%d", resp.StatusCode, response, calls.Load())
	}
}
