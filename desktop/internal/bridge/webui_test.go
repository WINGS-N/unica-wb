package bridge

import (
	"bufio"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"time"

	"unica-wb/desktop/internal/orch"
	"unica-wb/desktop/internal/webui"
)

func TestEmbeddedInterfaceIsServedWithRouterFallback(t *testing.T) {
	if !webui.Available() {
		t.Skip("no interface was embedded in this build")
	}
	_, base := startTestServer(t)

	// Every unknown path has to come back as the app shell, otherwise a reload
	// on a deep route lands on a 404
	for _, path := range []string{"/", "/jobs", "/settings/notifications"} {
		body, status := get(t, base+path)
		if status != http.StatusOK {
			t.Fatalf("%s status = %d", path, status)
		}
		if !strings.Contains(strings.ToLower(body), "<!doctype html") {
			t.Fatalf("%s did not return the app shell", path)
		}
	}

	body, status := get(t, base+"/manifest.webmanifest")
	if status != http.StatusOK || !strings.Contains(body, "UN1CA") {
		t.Fatalf("manifest not served: %d %s", status, body)
	}
}

func TestAPIRequestsReachTheBackend(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Seen-Path", r.URL.Path)
		_, _ = io.WriteString(w, "backend reached")
	}))
	t.Cleanup(backend.Close)

	var srv *Server
	emitter := orch.NewEmitter(func(kind string, payload any) { srv.Publish(kind, payload) })
	srv = New(emitter)
	if err := srv.ProxyAPI(backend.URL); err != nil {
		t.Fatalf("proxy: %v", err)
	}
	base, err := srv.Start()
	if err != nil {
		t.Fatalf("start: %v", err)
	}
	t.Cleanup(srv.Close)

	resp, err := http.Get(base + "/api/v1/jobs?workspace=x")
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	defer resp.Body.Close()
	if got := resp.Header.Get("X-Seen-Path"); got != "/api/v1/jobs" {
		t.Fatalf("backend saw %q", got)
	}
}

// Everything the interface reads arrives over a websocket, so an Upgrade that
// does not survive the proxy would leave the window blank
func TestWebsocketUpgradeSurvivesTheProxy(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !strings.EqualFold(r.Header.Get("Upgrade"), "websocket") {
			http.Error(w, "no upgrade header", http.StatusBadRequest)
			return
		}
		hj, ok := w.(http.Hijacker)
		if !ok {
			http.Error(w, "cannot hijack", http.StatusInternalServerError)
			return
		}
		conn, buf, err := hj.Hijack()
		if err != nil {
			return
		}
		defer conn.Close()
		_, _ = buf.WriteString("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
		_ = buf.Flush()
	}))
	t.Cleanup(backend.Close)

	srv := New(orch.NewEmitter(func(string, any) {}))
	if err := srv.ProxyAPI(backend.URL); err != nil {
		t.Fatalf("proxy: %v", err)
	}
	base, err := srv.Start()
	if err != nil {
		t.Fatalf("start: %v", err)
	}
	t.Cleanup(srv.Close)

	u, err := url.Parse(base)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	conn, err := net.DialTimeout("tcp", u.Host, 3*time.Second)
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(5 * time.Second))

	fmt.Fprintf(conn, "GET /api/v1/state/ws HTTP/1.1\r\nHost: %s\r\n", u.Host)
	fmt.Fprint(conn, "Upgrade: websocket\r\nConnection: Upgrade\r\n")
	fmt.Fprint(conn, "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n")

	resp, err := http.ReadResponse(bufio.NewReader(conn), nil)
	if err != nil {
		t.Fatalf("read response: %v", err)
	}
	if resp.StatusCode != http.StatusSwitchingProtocols {
		t.Fatalf("status = %d, want 101", resp.StatusCode)
	}
	if !strings.EqualFold(resp.Header.Get("Upgrade"), "websocket") {
		t.Fatal("the upgrade header did not survive the proxy")
	}
}

func TestProxyRejectsGarbageTarget(t *testing.T) {
	srv := New(orch.NewEmitter(func(string, any) {}))
	if err := srv.ProxyAPI("not-a-url"); err == nil {
		t.Fatal("expected an error for a target without a scheme")
	}
}

func get(t *testing.T, url string) (string, int) {
	t.Helper()
	resp, err := http.Get(url)
	if err != nil {
		t.Fatalf("get %s: %v", url, err)
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatalf("read %s: %v", url, err)
	}
	return string(body), resp.StatusCode
}

// A check can fail within milliseconds of launch, before any window has
// connected, and the failure still has to reach the screen
func TestFailureRaisedBeforeAnyoneConnectedIsStillDelivered(t *testing.T) {
	srv, base := startTestServer(t)
	srv.emitter.Stage("check", 80, "Checking f2fs support")
	srv.emitter.Fail(orch.Failure{
		Message:  "Required filesystem support is missing on the host kernel: f2fs.",
		FixKind:  "f2fs",
		FixLabel: "Enable f2fs module",
	})

	body, status := get(t, base+"/state")
	if status != http.StatusOK {
		t.Fatalf("state status = %d", status)
	}
	if !strings.Contains(body, "Enable f2fs module") {
		t.Fatalf("state carries no pending failure: %s", body)
	}

	resp, err := http.Get(base + "/events")
	if err != nil {
		t.Fatalf("events: %v", err)
	}
	defer resp.Body.Close()
	buf := make([]byte, 2048)
	n, _ := resp.Body.Read(buf)
	frame := string(buf[:n])
	if !strings.Contains(frame, "error-event") || !strings.Contains(frame, "Enable f2fs module") {
		t.Fatalf("a window connecting late got no failure: %s", frame)
	}

	// Progress means the run moved on, so the stale failure must not come back
	srv.emitter.Stage("check", 82, "Checking updates for Docker images")
	if srv.emitter.LastFailure() != nil {
		t.Fatal("the failure outlived the retry that cleared it")
	}
}
