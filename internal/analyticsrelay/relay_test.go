package analyticsrelay

import (
	"bufio"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"syscall"
	"testing"
	"time"
)

const artifactA = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

func fixture(t *testing.T) (*Relay, *atomic.Int32, string) {
	t.Helper()
	count := &atomic.Int32{}
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		count.Add(1)
		for _, h := range []string{"Cookie", "Authorization", "Referer", "Origin", "X-Forwarded-For", "X-Real-IP", "X-Umami-Cache", "X-Secret"} {
			if r.Header.Get(h) != "" {
				t.Errorf("forwarded %s", h)
			}
		}
		if r.URL.Path != "/api/send" && r.URL.Path != "/script.js" {
			t.Errorf("path %s", r.URL)
		}
		if r.Header.Get("User-Agent") != "Parley-Analytics-Relay/1" {
			t.Error("browser identity forwarded")
		}
		w.Header().Set("Set-Cookie", "secret=1")
		w.Header().Set("X-Native", "secret")
		io.WriteString(w, `{"cache":"secret"}`)
	}))
	t.Cleanup(upstream.Close)
	dir, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	cfg := Config{Upstream: upstream.URL, StateDir: dir, ArtifactSHA256: artifactA, Origin: "https://scrum.matthew.systems", Version: "test-release"}
	relay := New(cfg)
	writeReceipt(t, dir, relay, "ready")
	return relay, count, dir
}
func writeReceipt(t *testing.T, dir string, r *Relay, state string) {
	t.Helper()
	now := time.Now().UTC()
	receipt := map[string]any{"schema": 1, "generation": 1, "state": state, "checked_at": now.Format(time.RFC3339Nano), "valid_until": now.Add(60 * time.Second).Format(time.RFC3339Nano), "contract_schema": 1, "policy_sha256": PolicySHA256(), "website_id": policy.Website, "collector_version": policy.CollectorVersion, "collector_image": policy.CollectorImage, "tracker_sha256": policy.TrackerSHA256, "app_build": r.cfg.ArtifactSHA256}
	b, _ := json.Marshal(receipt)
	tmp := filepath.Join(dir, "next")
	if err := os.WriteFile(tmp, b, 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(tmp, filepath.Join(dir, "admission.json")); err != nil {
		t.Fatal(err)
	}
}
func body() string {
	return `{"type":"event","payload":{"website":"acc214c0-d772-493a-ad03-49fa8e72d77e","hostname":"scrum.matthew.systems","url":"/session","title":"Scrum Pro","referrer":"","name":"session_created","data":{"schema":1,"kind":"poker"}}}`
}
func request(r http.Handler, method, path, body string, headers map[string]string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(method, "https://scrum.matthew.systems"+path, strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	w := httptest.NewRecorder()
	r.ServeHTTP(deadlineRecorder{w}, req)
	return w
}
func TestProjectionAndPrivateResponse(t *testing.T) {
	r, count, _ := fixture(t)
	w := request(r, "POST", "/a/api/send", body(), map[string]string{"Cookie": "session=private", "Referer": "https://private/path", "X-Umami-Cache": "old", "X-Secret": "private", "X-Forwarded-For": "1.2.3.4"})
	if w.Code != 200 || strings.TrimSpace(w.Body.String()) != "{}" || count.Load() != 1 {
		t.Fatalf("%d %s calls=%d", w.Code, w.Body, count.Load())
	}
	if w.Header().Get("Set-Cookie") != "" || w.Header().Get("X-Native") != "" {
		t.Fatal("native response leaked")
	}
}
func TestRefusals(t *testing.T) {
	cases := []struct {
		name, body, path string
		headers          map[string]string
	}{
		{name: "duplicate", body: strings.Replace(body(), `"type":"event"`, `"type":"event","type":"event"`, 1)},
		{name: "extra", body: strings.Replace(body(), `"type":"event"`, `"type":"event","cache":"secret"`, 1)},
		{name: "trailing", body: body() + `{}`},
		{name: "identify", body: strings.Replace(body(), `"event"`, `"identify"`, 1)},
		{name: "site", body: strings.ReplaceAll(body(), policy.Website, "other")},
		{name: "rawurl", body: strings.Replace(body(), `"/session"`, `"/session/private?secret"`, 1)},
		{name: "id", body: strings.Replace(body(), `"schema":1`, `"schema":1,"id":"x"`, 1)},
		{name: "timestamp", body: strings.Replace(body(), `"hostname"`, `"timestamp":1,"hostname"`, 1)},
		{name: "nested", body: strings.Replace(body(), `"kind":"poker"`, `"kind":{"value":"poker"}`, 1)},
		{name: "dnt", headers: map[string]string{"DNT": "1"}},
		{name: "auth", headers: map[string]string{"Authorization": "Bearer private"}},
		{name: "origin", headers: map[string]string{"Origin": "https://evil.test"}},
		{name: "fetch", headers: map[string]string{"Sec-Fetch-Site": "same-site"}},
		{name: "query", path: "/a/api/send?website=other"},
		{name: "native", path: "/a/api/admin"},
		{name: "oversize", body: body() + strings.Repeat(" ", 16*1024)},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			r, count, _ := fixture(t)
			b := tc.body
			if b == "" {
				b = body()
			}
			path := tc.path
			if path == "" {
				path = "/a/api/send"
			}
			w := request(r, "POST", path, b, tc.headers)
			if w.Code < 400 || count.Load() != 0 {
				t.Fatalf("%d calls=%d", w.Code, count.Load())
			}
		})
	}
}
func TestAdmissionFailures(t *testing.T) {
	for _, mode := range []string{"missing", "maintenance", "blocked", "retention_failed", "stale", "future", "longlease", "artifact", "policy", "unknown", "duplicate", "symlink", "permissions", "oversize", "directory", "fifo", "parentpermissions"} {
		t.Run(mode, func(t *testing.T) {
			r, count, dir := fixture(t)
			path := filepath.Join(dir, "admission.json")
			b, _ := os.ReadFile(path)
			var rec map[string]any
			json.Unmarshal(b, &rec)
			switch mode {
			case "missing":
				os.Remove(path)
			case "maintenance", "blocked", "retention_failed":
				writeReceipt(t, dir, r, mode)
			case "stale":
				rec["checked_at"] = time.Now().Add(-40 * time.Second).UTC().Format(time.RFC3339Nano)
				rec["valid_until"] = time.Now().Add(-time.Second).UTC().Format(time.RFC3339Nano)
			case "future":
				rec["checked_at"] = time.Now().Add(10 * time.Second).UTC().Format(time.RFC3339Nano)
			case "longlease":
				rec["valid_until"] = time.Now().Add(90 * time.Second).UTC().Format(time.RFC3339Nano)
			case "artifact":
				rec["app_build"] = strings.Repeat("b", 64)
			case "policy":
				rec["policy_sha256"] = strings.Repeat("b", 64)
			case "unknown":
				rec["extra"] = true
			case "duplicate":
				b = append([]byte(`{"schema":1,`), b[1:]...)
				os.WriteFile(path, b, 0600)
			case "symlink":
				os.WriteFile(filepath.Join(dir, "target"), b, 0600)
				os.Remove(path)
				os.Symlink("target", path)
			case "permissions":
				os.Chmod(path, 0666)
			case "oversize":
				os.WriteFile(path, append(b, []byte(strings.Repeat(" ", 8192))...), 0600)
			case "directory":
				os.Remove(path)
				os.Mkdir(path, 0700)
			case "fifo":
				os.Remove(path)
				if err := syscall.Mkfifo(path, 0600); err != nil {
					t.Fatal(err)
				}
				r.afterOpen = func() {
					writer, err := os.OpenFile(path, os.O_WRONLY|syscall.O_NONBLOCK, 0)
					if err != nil {
						t.Fatal(err)
					}
					defer writer.Close()
					if _, err = writer.Write(b); err != nil {
						t.Fatal(err)
					}
				}
			case "parentpermissions":
				os.Chmod(dir, 0777)
			}
			if mode == "stale" || mode == "future" || mode == "longlease" || mode == "artifact" || mode == "policy" || mode == "unknown" {
				b, _ = json.Marshal(rec)
				os.WriteFile(path, b, 0600)
			}
			for _, m := range []string{"GET", "POST"} {
				p := "/a/script.js"
				if m == "POST" {
					p = "/a/api/send"
				}
				w := request(r, m, p, body(), nil)
				if w.Code < 400 || count.Load() != 0 {
					t.Fatalf("%s %d calls=%d", m, w.Code, count.Load())
				}
			}
		})
	}
}
func TestSameVersionDifferentArtifactAndRestart(t *testing.T) {
	r, count, dir := fixture(t)
	cfg := r.cfg
	cfg.ArtifactSHA256 = strings.Repeat("b", 64)
	other := New(cfg)
	if request(other, "POST", "/a/api/send", body(), nil).Code < 400 || count.Load() != 0 {
		t.Fatal("other binary accepted same version receipt")
	}
	writeReceipt(t, dir, other, "ready")
	if request(r, "POST", "/a/api/send", body(), nil).Code < 400 {
		t.Fatal("old binary accepted new receipt")
	}
	if request(New(cfg), "POST", "/a/api/send", body(), nil).Code != 200 {
		t.Fatal("correct restart failed")
	}
	cfg.ArtifactSHA256 = ""
	if request(New(cfg), "POST", "/a/api/send", body(), nil).Code < 400 {
		t.Fatal("missing identity accepted")
	}
}
func TestSnapshotAcrossAtomicPublication(t *testing.T) {
	for _, expired := range []bool{false, true} {
		t.Run(map[bool]string{false: "timely", true: "expired"}[expired], func(t *testing.T) {
			r, count, dir := fixture(t)
			opened := make(chan struct{})
			release := make(chan struct{})
			var once atomic.Bool
			r.afterOpen = func() {
				if once.CompareAndSwap(false, true) {
					close(opened)
					<-release
				}
			}
			done := make(chan *httptest.ResponseRecorder, 1)
			go func() { done <- request(r, "POST", "/a/api/send", body(), nil) }()
			<-opened
			writeReceipt(t, dir, r, "maintenance")
			if request(r, "POST", "/a/api/send", body(), nil).Code < 400 || count.Load() != 0 {
				t.Fatal("new snapshot admitted")
			}
			if expired {
				time.Sleep(5100 * time.Millisecond)
			}
			close(release)
			w := <-done
			if expired {
				if w.Code < 400 || count.Load() != 0 {
					t.Fatal("old snapshot outlived original budget")
				}
			} else if w.Code != 200 || count.Load() != 1 {
				t.Fatal("old ready descriptor failed within budget")
			}
		})
	}
}
func TestScriptHashAndRedirect(t *testing.T) {
	r, count, _ := fixture(t)
	if request(r, "GET", "/a/script.js", "", nil).Code < 400 || count.Load() != 1 {
		t.Fatal("invalid script served")
	}
	target := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { t.Error("followed redirect") }))
	defer target.Close()
	redirect := httptest.NewServer(http.RedirectHandler(target.URL, 302))
	defer redirect.Close()
	r.cfg.Upstream = redirect.URL
	if request(r, "POST", "/a/api/send", body(), nil).Code < 400 {
		t.Fatal("redirect accepted")
	}
	// Exact pinned fixture is exercised separately; never relax the production pin.
	sum := sha256.Sum256([]byte("wrong"))
	if hex.EncodeToString(sum[:]) == policy.TrackerSHA256 {
		t.Fatal("bad fixture")
	}
}
func TestCancellationAndSaturation(t *testing.T) {
	r, count, _ := fixture(t)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	req := httptest.NewRequest("POST", "https://scrum.matthew.systems/a/api/send", strings.NewReader(body())).WithContext(ctx)
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code < 400 || count.Load() != 0 {
		t.Fatal("cancelled forwarded")
	}
	for range 8 {
		r.inflight <- struct{}{}
	}
	if request(r, "POST", "/a/api/send", body(), nil).Code != 429 {
		t.Fatal("inflight unbounded")
	}
	for range 8 {
		<-r.inflight
	}
	r.mu.Lock()
	r.tokens = 0
	r.last = time.Now()
	r.mu.Unlock()
	if request(r, "POST", "/a/api/send", body(), nil).Code != 429 {
		t.Fatal("rate unbounded")
	}
}

type deadlineRecorder struct{ *httptest.ResponseRecorder }

func (deadlineRecorder) SetReadDeadline(time.Time) error { return nil }

func TestPinnedScriptAndFinitePage(t *testing.T) {
	r, _, _ := fixture(t)
	tracker, err := os.ReadFile("testdata/umami-3.0.3.js")
	if err != nil {
		t.Fatal(err)
	}
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		if req.URL.Path == "/script.js" {
			w.Write(tracker)
		} else {
			io.WriteString(w, `{"cache":"secret"}`)
		}
	}))
	defer upstream.Close()
	r.cfg.Upstream = upstream.URL
	if w := request(r, "GET", "/a/script.js", "", nil); w.Code != 200 || w.Body.String() != string(tracker) || !strings.HasPrefix(w.Header().Get("Content-Type"), "application/javascript") {
		t.Fatalf("script %d", w.Code)
	}
	// Every policy event, primitive enum and page category traverses the strict wire projection.
	for name, fields := range policy.Events {
		data := map[string]any{"schema": 1}
		for key, enums := range fields {
			data[key] = enums[0]
		}
		for _, page := range policy.Pages {
			b, _ := json.Marshal(map[string]any{"type": "event", "payload": map[string]any{"website": policy.Website, "hostname": policy.Hostname, "url": page, "title": policy.Title, "referrer": "", "name": name, "data": data}})
			if _, err := project(b); err != nil {
				t.Fatalf("%s %s %v", name, page, err)
			}
		}
	}
}
func TestWriteDeadlineIsReal(t *testing.T) {
	r, count, _ := fixture(t)
	req := httptest.NewRequest("POST", "https://scrum.matthew.systems/a/api/send", strings.NewReader(body()))
	req.Header.Set("Content-Type", "application/json")
	recorder := &writeDeadlineRecorder{ResponseRecorder: httptest.NewRecorder()}
	r.ServeHTTP(recorder, req)
	if !recorder.writeDeadlineSet || count.Load() != 1 {
		t.Fatal("whole-operation response deadline missing")
	}
}

type writeDeadlineRecorder struct {
	*httptest.ResponseRecorder
	writeDeadlineSet bool
}

func (r *writeDeadlineRecorder) SetReadDeadline(time.Time) error { return nil }
func (r *writeDeadlineRecorder) SetWriteDeadline(d time.Time) error {
	r.writeDeadlineSet = time.Until(d) > 0 && time.Until(d) <= 5*time.Second
	return nil
}

func (deadlineRecorder) SetWriteDeadline(time.Time) error { return nil }

func TestRealSlowBodyDeadline(t *testing.T) {
	r, count, _ := fixture(t)
	server := httptest.NewServer(r)
	defer server.Close()
	parsed, _ := url.Parse(server.URL)
	conn, err := net.Dial("tcp", parsed.Host)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	started := time.Now()
	io.WriteString(conn, "POST /a/api/send HTTP/1.1\r\nHost: scrum.matthew.systems\r\nContent-Type: application/json\r\nContent-Length: 100\r\n\r\n{")
	conn.SetReadDeadline(time.Now().Add(4 * time.Second))
	response, err := http.ReadResponse(bufio.NewReader(conn), nil)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	if response.StatusCode < 400 || time.Since(started) > 3*time.Second || count.Load() != 0 {
		t.Fatalf("slow body not bounded: %d", response.StatusCode)
	}
}
func TestActualUpstreamTimeoutAndNoRetry(t *testing.T) {
	r, _, _ := fixture(t)
	var calls atomic.Int32
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		calls.Add(1)
		io.Copy(io.Discard, req.Body)
		select {
		case <-req.Context().Done():
		case <-time.After(6 * time.Second):
		}
	}))
	defer upstream.Close()
	r.cfg.Upstream = upstream.URL
	started := time.Now()
	w := request(r, "POST", "/a/api/send", body(), nil)
	if w.Code < 400 || time.Since(started) > 5500*time.Millisecond || calls.Load() != 1 {
		t.Fatalf("timeout/retry: %d calls %d", w.Code, calls.Load())
	}
}
func TestUnsupportedReadDeadlineFailsClosed(t *testing.T) {
	r, count, _ := fixture(t)
	req := httptest.NewRequest("POST", "https://scrum.matthew.systems/a/api/send", strings.NewReader(body()))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code < 400 || count.Load() != 0 {
		t.Fatal("unsupported deadline forwarded")
	}
}

func TestWireBoundaries(t *testing.T) {
	variants := []string{
		strings.Replace(body(), `"hostname":"scrum.matthew.systems"`, `"hostname":"evil"`, 1),
		strings.Replace(body(), `"title":"Scrum Pro"`, `"title":"private"`, 1),
		strings.Replace(body(), `"referrer":""`, `"referrer":"private"`, 1),
		strings.Replace(body(), `"referrer":"",`, "", 1),
		strings.Replace(body(), `"referrer":""`, `"referrer":null`, 1),
		strings.Replace(body(), `"schema":1`, `"schema":2`, 1),
		strings.Replace(body(), `"schema":1`, `"schema":1,"schema":1`, 1),
		strings.Replace(body(), `"kind":"poker"`, `"kind":"unknown"`, 1),
		strings.Replace(body(), `"name":"session_created"`, `"name":"unknown"`, 1),
		strings.Replace(body(), `"name":"session_created"`, `"name":null`, 1),
		strings.Replace(body(), `"type":"event"`, `"type":"event","payload":{}`, 1),
	}
	for i, b := range variants {
		if _, err := project([]byte(b)); err == nil {
			t.Errorf("variant %d accepted", i)
		}
	}
	page := `{"type":"event","payload":{"website":"acc214c0-d772-493a-ad03-49fa8e72d77e","hostname":"scrum.matthew.systems","url":"/","title":"Scrum Pro","referrer":""}}`
	if _, err := project([]byte(page)); err != nil {
		t.Fatal(err)
	}
	if _, err := project([]byte(strings.Replace(page, `"referrer":""`, `"referrer":"","data":{}`, 1))); err == nil {
		t.Fatal("page data accepted")
	}
}
func TestEveryAdmissionPin(t *testing.T) {
	for _, key := range []string{"schema", "contract_schema", "website_id", "collector_version", "collector_image", "tracker_sha256", "generation", "checked_at", "valid_until"} {
		t.Run(key, func(t *testing.T) {
			r, count, dir := fixture(t)
			path := filepath.Join(dir, "admission.json")
			b, _ := os.ReadFile(path)
			var data map[string]any
			json.Unmarshal(b, &data)
			if key == "schema" || key == "contract_schema" {
				data[key] = 2
			} else if key == "generation" {
				data[key] = -1
			} else {
				data[key] = "invalid"
			}
			b, _ = json.Marshal(data)
			os.WriteFile(path, b, 0600)
			if request(r, "GET", "/a/script.js", "", nil).Code < 400 || count.Load() != 0 {
				t.Fatal("pin bypass")
			}
		})
	}
}
func TestConfigAndOriginBoundaries(t *testing.T) {
	for _, mode := range []string{"defaultoff", "dev", "missingfingerprint", "host", "contenttype", "scriptorigin", "scriptquery", "method"} {
		t.Run(mode, func(t *testing.T) {
			r, count, _ := fixture(t)
			method, path, b := "POST", "/a/api/send", body()
			if strings.HasPrefix(mode, "script") {
				method, path, b = "GET", "/a/script.js", ""
			}
			if mode == "scriptquery" {
				path += "?x=1"
			}
			if mode == "method" {
				method = "PUT"
			}
			req := httptest.NewRequest(method, "https://scrum.matthew.systems"+path, strings.NewReader(b))
			req.Header.Set("Content-Type", "application/json")
			switch mode {
			case "defaultoff":
				r.cfg.Upstream = ""
			case "dev":
				r.cfg.Version = "dev"
			case "missingfingerprint":
				r.cfg.ArtifactSHA256 = ""
			case "host":
				req.Host = "evil.test"
			case "contenttype":
				req.Header.Set("Content-Type", "text/plain")
			case "scriptorigin":
				req.Header.Set("Origin", "https://evil.test")
			}
			w := httptest.NewRecorder()
			r.ServeHTTP(deadlineRecorder{w}, req)
			if (mode == "defaultoff" && w.Code != 404) || w.Code < 400 || count.Load() != 0 {
				t.Fatal("configuration/origin bypass")
			}
		})
	}
}

func TestScriptConsumptionBound(t *testing.T) {
	r, _, _ := fixture(t)
	reader := &countedReader{Reader: strings.NewReader(strings.Repeat("x", 512*1024))}
	r.client.Transport = roundTripFunc(func(*http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: 200, Body: io.NopCloser(reader), Header: make(http.Header)}, nil
	})
	if w := request(r, "GET", "/a/script.js", "", nil); w.Code < 400 || reader.count > 262145 {
		t.Fatalf("script read unbounded: %d", reader.count)
	}
}

type countedReader struct {
	io.Reader
	count int
}

func (r *countedReader) Read(p []byte) (int, error) {
	n, err := r.Reader.Read(p)
	r.count += n
	return n, err
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

type writeOnlyRecorder struct{ *httptest.ResponseRecorder }

func (writeOnlyRecorder) SetWriteDeadline(time.Time) error { return nil }
func TestUnsupportedBodyReadDeadlineFailsClosed(t *testing.T) {
	r, count, _ := fixture(t)
	req := httptest.NewRequest("POST", "https://scrum.matthew.systems/a/api/send", strings.NewReader(body()))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(writeOnlyRecorder{w}, req)
	if w.Code < 400 || count.Load() != 0 {
		t.Fatal("read deadline unsupported but forwarded")
	}
}

func TestCaseVariantKeysRefused(t *testing.T) {
	for _, b := range []string{strings.Replace(body(), `"type"`, `"TYPE"`, 1), strings.Replace(body(), `"website"`, `"WEBSITE"`, 1), strings.Replace(body(), `"type":"event"`, `"type":"event","TYPE":"event"`, 1)} {
		if _, err := project([]byte(b)); err == nil {
			t.Fatal("noncanonical key variant accepted")
		}
	}
	r, count, dir := fixture(t)
	path := filepath.Join(dir, "admission.json")
	b, _ := os.ReadFile(path)
	b = []byte(strings.Replace(string(b), `"app_build"`, `"APP_BUILD"`, 1))
	os.WriteFile(path, b, 0600)
	if request(r, "GET", "/a/script.js", "", nil).Code < 400 || count.Load() != 0 {
		t.Fatal("noncanonical receipt key accepted")
	}
}
