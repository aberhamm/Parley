package api

import (
	"github.com/go-chi/chi/v5"
	"github.com/lets-parley/parley/internal/analyticsrelay"
	"net/http"
)

// These routes deliberately do not resolve cookies, bearer sessions or a DB.
// Authorization is refused by the relay before any body/receipt/upstream work.
func mountAnalytics(r chi.Router, opts Options) {
	cfg := analyticsrelay.Config{}
	if opts.AnalyticsRelay != nil {
		cfg = *opts.AnalyticsRelay
		cfg.ArtifactSHA256 = opts.AnalyticsArtifactSHA256
	}
	relay := analyticsrelay.New(cfg)
	r.Method("GET", "/a/script.js", relay)
	r.Method("POST", "/a/api/send", relay)
	r.Handle("/a/*", http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		http.Error(w, `{"error":"analytics unavailable"}`, 404)
	}))
	r.Handle("/a", http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		http.Error(w, `{"error":"analytics unavailable"}`, 404)
	}))
}
