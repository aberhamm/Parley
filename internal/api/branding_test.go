package api

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// The meeting-client handoff is rendered by Go rather than the React app.
// Keep its page title, accessible logo and sign-in action on the fork's brand.
func TestEmbeddedSigninUsesScrumProBrand(t *testing.T) {
	w := httptest.NewRecorder()
	renderEmbedSignin(w, http.StatusOK, embedSigninView{
		Title: "Sign in to Scrum Pro", Label: "your meeting", SigninURL: "/",
	})
	page := w.Body.String()
	for _, want := range []string{`<title>Sign in to your meeting — Scrum Pro</title>`, `aria-label="Scrum Pro"`, `>Sign in to Scrum Pro</a>`} {
		if !strings.Contains(page, want) {
			t.Errorf("meeting sign-in page missing %q", want)
		}
	}
	if strings.Contains(page, "Parley") {
		t.Error("meeting sign-in page still uses upstream brand")
	}
}
