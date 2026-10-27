package analyticsrelay

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"io"
	"mime"
	"net"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"
)

// Config is optional. Production URL/path validation belongs to the boot mapping;
// isolated tests may supply a local fixture URL without opening production egress.
type Config struct{ Upstream, StateDir, ArtifactSHA256, Origin, Version string }
type Relay struct {
	cfg      Config
	client   *http.Client
	inflight chan struct{}
	mu       sync.Mutex
	tokens   float64
	last     time.Time
	// Only package tests pause exactly after descriptor acquisition.
	afterOpen func()
}

func New(cfg Config) *Relay {
	tr := &http.Transport{Proxy: nil, DialContext: (&net.Dialer{Timeout: 2 * time.Second}).DialContext, MaxConnsPerHost: 8, MaxIdleConnsPerHost: 8, IdleConnTimeout: 30 * time.Second, ResponseHeaderTimeout: 3 * time.Second, DisableKeepAlives: true, DisableCompression: true}
	return &Relay{cfg: cfg, client: &http.Client{Transport: tr, Timeout: 5 * time.Second, CheckRedirect: func(_ *http.Request, _ []*http.Request) error { return http.ErrUseLastResponse }}, inflight: make(chan struct{}, 8), tokens: 40, last: time.Now()}
}
func hashValid(s string) bool {
	if len(s) != 64 || s != strings.ToLower(s) {
		return false
	}
	_, err := hex.DecodeString(s)
	return err == nil
}
func (r *Relay) enabled() bool {
	u, err := url.Parse(r.cfg.Upstream)
	o, oe := url.Parse(r.cfg.Origin)
	return err == nil && oe == nil && u.Scheme == "http" && u.Host != "" && u.User == nil && u.RawQuery == "" && u.Fragment == "" && u.Path == "" && o.Host != "" && hashValid(r.cfg.ArtifactSHA256) && r.cfg.Version != "" && r.cfg.Version != "dev" && r.cfg.StateDir != ""
}
func (r *Relay) take() bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	now := time.Now()
	r.tokens += now.Sub(r.last).Seconds() * 20
	if r.tokens > 40 {
		r.tokens = 40
	}
	r.last = now
	if r.tokens < 1 {
		return false
	}
	r.tokens--
	return true
}
func refuse(w http.ResponseWriter, status int) {
	http.Error(w, `{"error":"analytics unavailable"}`, status)
}
func (r *Relay) ServeHTTP(w http.ResponseWriter, req *http.Request) {
	// This deadline starts before parsing, acquisition or admission-file I/O.
	ctx, cancel := context.WithTimeout(req.Context(), 5*time.Second)
	defer cancel()
	w.Header().Set("Cache-Control", "no-store")
	script := req.Method == "GET" && req.URL.Path == "/a/script.js"
	send := req.Method == "POST" && req.URL.Path == "/a/api/send"
	if !script && !send || !r.enabled() {
		refuse(w, 404)
		return
	}
	origin, _ := url.Parse(r.cfg.Origin)
	if req.Host != origin.Host || req.URL.EscapedPath() != req.URL.Path || req.URL.RawQuery != "" || req.URL.ForceQuery || req.Header.Get("Authorization") != "" || req.Header.Get("DNT") == "1" {
		refuse(w, 403)
		return
	}
	if o := req.Header.Get("Origin"); o != "" && o != r.cfg.Origin {
		refuse(w, 403)
		return
	}
	if site := req.Header.Get("Sec-Fetch-Site"); site != "" && site != "same-origin" && site != "none" {
		refuse(w, 403)
		return
	}
	if ctx.Err() != nil {
		refuse(w, 503)
		return
	}
	select {
	case r.inflight <- struct{}{}:
		defer func() { <-r.inflight }()
	default:
		refuse(w, 429)
		return
	}
	if !r.take() {
		refuse(w, 429)
		return
	}
	deadline, _ := ctx.Deadline()
	if err := http.NewResponseController(w).SetWriteDeadline(deadline); err != nil {
		refuse(w, 503)
		return
	}
	var b []byte
	if send {
		media, _, err := mime.ParseMediaType(req.Header.Get("Content-Type"))
		if err != nil || media != "application/json" {
			refuse(w, 415)
			return
		}
		// Context cancellation alone cannot interrupt an HTTP body read.
		rc := http.NewResponseController(w)
		err = rc.SetReadDeadline(minDeadline(time.Now().Add(2*time.Second), deadline))
		if err != nil {
			refuse(w, 503)
			return
		}
		b, err = io.ReadAll(io.LimitReader(req.Body, 16385))
		if err != nil || len(b) > 16384 {
			refuse(w, 400)
			return
		}
		b, err = project(b)
		if err != nil {
			refuse(w, 400)
			return
		}
	}
	if !r.admitted(ctx) || ctx.Err() != nil {
		refuse(w, 503)
		return
	}
	path := "/api/send"
	method := "POST"
	if script {
		path = "/script.js"
		method = "GET"
		b = nil
	}
	// An explicit Body with nil GetBody must not be replayed by the transport.
	upstream, err := http.NewRequestWithContext(ctx, method, r.cfg.Upstream+path, nil)
	if err != nil {
		refuse(w, 503)
		return
	}
	if b != nil {
		upstream.Body = io.NopCloser(bytes.NewReader(b))
		upstream.ContentLength = int64(len(b))
	}
	upstream.Header.Set("User-Agent", "Parley-Analytics-Relay/1")
	if send {
		upstream.Header.Set("Content-Type", "application/json")
	}
	if ctx.Err() != nil {
		refuse(w, 503)
		return
	}
	resp, err := r.client.Do(upstream)
	if err != nil {
		refuse(w, 503)
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		refuse(w, 503)
		return
	}
	if script {
		data, e := io.ReadAll(io.LimitReader(resp.Body, 262145))
		sum := sha256.Sum256(data)
		if e != nil || len(data) > 262144 || hex.EncodeToString(sum[:]) != policy.TrackerSHA256 || ctx.Err() != nil {
			refuse(w, 503)
			return
		}
		w.Header().Set("Content-Type", "application/javascript; charset=utf-8")
		w.WriteHeader(200)
		w.Write(data)
		return
	}
	if ctx.Err() != nil {
		refuse(w, 503)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(200)
	w.Write([]byte("{}"))
}

func minDeadline(a, b time.Time) time.Time {
	if a.Before(b) {
		return a
	}
	return b
}
