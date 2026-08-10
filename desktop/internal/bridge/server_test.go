package bridge

import (
	"bufio"
	"bytes"
	"encoding/json"
	"net/http"
	"strings"
	"testing"
	"time"

	"unica-wb/desktop/internal/orch"
)

func startTestServer(t *testing.T) (*Server, string) {
	t.Helper()
	var srv *Server
	emitter := orch.NewEmitter(func(kind string, payload any) {
		if kind == "error" {
			kind = "error-event"
		}
		srv.Publish(kind, payload)
	})
	srv = New(emitter)
	base, err := srv.Start()
	if err != nil {
		t.Fatalf("start: %v", err)
	}
	t.Cleanup(srv.Close)
	return srv, base
}

func TestStateCarriesProgressAndLogs(t *testing.T) {
	srv, base := startTestServer(t)
	srv.emitter.Stage("check", 50, "Checking Docker daemon")

	resp, err := http.Get(base + "/state")
	if err != nil {
		t.Fatalf("get state: %v", err)
	}
	defer resp.Body.Close()

	var payload struct {
		Mode     string        `json:"mode"`
		Progress orch.Progress `json:"progress"`
		Logs     []string      `json:"logs"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&payload); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if payload.Mode != "startup" {
		t.Fatalf("mode = %q, want startup", payload.Mode)
	}
	if payload.Progress.Stage != "check" || payload.Progress.Progress != 50 {
		t.Fatalf("unexpected progress: %+v", payload.Progress)
	}
	// check spans 0-15 of the overall bar, so half of it is 8
	if payload.Progress.TotalProgress != 8 {
		t.Fatalf("total progress = %d, want 8", payload.Progress.TotalProgress)
	}
	if len(payload.Logs) != 1 || !strings.Contains(payload.Logs[0], "Checking Docker daemon") {
		t.Fatalf("unexpected logs: %v", payload.Logs)
	}
}

func TestEventsStreamDeliversProgressAndErrors(t *testing.T) {
	srv, base := startTestServer(t)

	resp, err := http.Get(base + "/events")
	if err != nil {
		t.Fatalf("get events: %v", err)
	}
	defer resp.Body.Close()

	events := make(chan string, 8)
	go func() {
		reader := bufio.NewReader(resp.Body)
		var current bytes.Buffer
		for {
			line, err := reader.ReadString('\n')
			if err != nil {
				return
			}
			line = strings.TrimRight(line, "\r\n")
			if line == "" {
				if current.Len() > 0 {
					events <- current.String()
					current.Reset()
				}
				continue
			}
			if strings.HasPrefix(line, ":") {
				continue
			}
			if current.Len() > 0 {
				current.WriteString("|")
			}
			current.WriteString(line)
		}
	}()

	// The first frame replays whatever the launcher is doing right now
	time.Sleep(150 * time.Millisecond)
	srv.emitter.Stage("pull", 10, "Pulling docker image")
	srv.emitter.Fail(orch.Failure{Message: "loop devices missing", FixKind: "loop", FixLabel: "Fix loop devices"})

	got := map[string]string{}
	deadline := time.After(3 * time.Second)
	for len(got) < 2 {
		select {
		case frame := <-events:
			switch {
			case strings.Contains(frame, "event: progress"):
				got["progress"] = frame
			case strings.Contains(frame, "event: error-event"):
				got["error"] = frame
			}
		case <-deadline:
			t.Fatalf("timed out, received: %v", got)
		}
	}
	if !strings.Contains(got["progress"], "Pulling docker image") {
		t.Fatalf("progress frame missing message: %s", got["progress"])
	}
	if !strings.Contains(got["error"], "Fix loop devices") {
		t.Fatalf("error frame missing fix label: %s", got["error"])
	}
}

func TestActionsInvokeCallbacks(t *testing.T) {
	srv, base := startTestServer(t)

	retried := make(chan struct{}, 1)
	fixed := make(chan string, 1)
	srv.OnRetry = func() { retried <- struct{}{} }
	srv.OnFix = func(kind string) { fixed <- kind }

	if _, err := http.Post(base+"/action/retry", "application/json", nil); err != nil {
		t.Fatalf("retry: %v", err)
	}
	select {
	case <-retried:
	case <-time.After(time.Second):
		t.Fatal("retry callback was not called")
	}

	if _, err := http.Post(base+"/action/fix?kind=f2fs", "application/json", nil); err != nil {
		t.Fatalf("fix: %v", err)
	}
	select {
	case kind := <-fixed:
		if kind != "f2fs" {
			t.Fatalf("fix kind = %q, want f2fs", kind)
		}
	case <-time.After(time.Second):
		t.Fatal("fix callback was not called")
	}

	resp, err := http.Post(base+"/action/fix", "application/json", nil)
	if err != nil {
		t.Fatalf("fix without kind: %v", err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", resp.StatusCode)
	}
}

func TestSudoPromptRoundTrip(t *testing.T) {
	srv, base := startTestServer(t)

	answer := make(chan string, 1)
	go func() {
		password, ok := srv.AskSudo()
		if !ok {
			answer <- "cancelled"
			return
		}
		answer <- password
	}()

	time.Sleep(100 * time.Millisecond)
	body := strings.NewReader(`{"password":"secret"}`)
	if _, err := http.Post(base+"/action/sudo", "application/json", body); err != nil {
		t.Fatalf("sudo: %v", err)
	}
	select {
	case got := <-answer:
		if got != "secret" {
			t.Fatalf("password = %q", got)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("AskSudo did not return")
	}

	go func() {
		_, ok := srv.AskSudo()
		if ok {
			answer <- "unexpected"
			return
		}
		answer <- "cancelled"
	}()
	time.Sleep(100 * time.Millisecond)
	if _, err := http.Post(base+"/action/sudo", "application/json", strings.NewReader(`{"cancel":true}`)); err != nil {
		t.Fatalf("sudo cancel: %v", err)
	}
	select {
	case got := <-answer:
		if got != "cancelled" {
			t.Fatalf("expected cancellation, got %q", got)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("AskSudo did not return after cancel")
	}
}

func TestLanguageBridge(t *testing.T) {
	srv, base := startTestServer(t)

	type call struct {
		lang    string
		strings map[string]string
	}
	got := make(chan call, 1)
	srv.OnLanguage = func(lang string, values map[string]string) { got <- call{lang, values} }

	payload := `{"lang":"ru","strings":{"exit":"Quit"}}`
	if _, err := http.Post(base+"/bridge/language", "application/json", strings.NewReader(payload)); err != nil {
		t.Fatalf("language: %v", err)
	}
	select {
	case c := <-got:
		if c.lang != "ru" || c.strings["exit"] != "Quit" {
			t.Fatalf("unexpected payload: %+v", c)
		}
	case <-time.After(time.Second):
		t.Fatal("language callback was not called")
	}
}

func TestSplashIsServed(t *testing.T) {
	_, base := startTestServer(t)
	resp, err := http.Get(base + "/splash/")
	if err != nil {
		t.Fatalf("get splash: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status = %d", resp.StatusCode)
	}
	buf := new(bytes.Buffer)
	if _, err := buf.ReadFrom(resp.Body); err != nil {
		t.Fatalf("read: %v", err)
	}
	if !strings.Contains(buf.String(), "UN1CA Build") {
		t.Fatal("splash markup does not look right")
	}
}
