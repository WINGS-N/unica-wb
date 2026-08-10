package bridge

import (
	"embed"
	"encoding/json"
	"fmt"
	"io/fs"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strings"
	"sync"
	"time"

	"unica-wb/desktop/internal/orch"
	"unica-wb/desktop/internal/webui"
)

//go:embed assets
var assets embed.FS

// Server is the launcher's own loopback HTTP endpoint. It serves the startup
// splash over SSE, the embedded build interface, and a proxy to the backend
// container, plus the bridge the interface calls to keep the exit dialog
// translated
type Server struct {
	mu       sync.RWMutex
	clients  map[chan sseMessage]struct{}
	mode     string
	emitter  *orch.Emitter
	listener net.Listener
	baseURL  string
	apiProxy http.Handler

	sudoMu      sync.Mutex
	sudoWait    chan sudoAnswer
	pendingSudo *orch.SudoRequest

	exitMu     sync.Mutex
	exitShown  chan struct{}
	exitAnswer chan bool

	textsMu  sync.RWMutex
	language string
	ui       map[string]string
	messages map[string]string

	OnRetry    func()
	OnFix      func(kind string)
	OnLanguage func(lang string, strings map[string]string)
}

type sseMessage struct {
	event string
	data  []byte
}

type sudoAnswer struct {
	password string
	ok       bool
}

func New(emitter *orch.Emitter) *Server {
	return &Server{
		clients: map[chan sseMessage]struct{}{},
		mode:    "startup",
		emitter: emitter,
	}
}

// Start binds a random loopback port so several launchers never collide
func (s *Server) Start() (string, error) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return "", err
	}
	s.listener = ln
	s.baseURL = fmt.Sprintf("http://%s", ln.Addr().String())

	splash := http.FileServer(http.FS(mustSub(assets, "assets")))

	mux := http.NewServeMux()
	mux.HandleFunc("/events", s.handleEvents)
	mux.HandleFunc("/state", s.handleState)
	mux.HandleFunc("/action/retry", s.handleRetry)
	mux.HandleFunc("/action/fix", s.handleFix)
	mux.HandleFunc("/action/sudo", s.handleSudo)
	mux.HandleFunc("/action/exit", s.handleExit)
	mux.HandleFunc("/bridge/language", s.handleLanguage)
	mux.Handle("/splash/", http.StripPrefix("/splash/", splash))
	mux.Handle("/splash", http.RedirectHandler("/splash/", http.StatusMovedPermanently))
	if s.apiProxy != nil {
		mux.Handle("/api/", s.apiProxy)
	}
	if webui.Available() {
		mux.Handle("/", webui.Handler())
	} else {
		// Without an embedded build the splash is all this server has to show
		mux.Handle("/", splash)
	}

	server := &http.Server{Handler: withCORS(mux), ReadHeaderTimeout: 10 * time.Second}
	go func() { _ = server.Serve(ln) }()
	return s.baseURL, nil
}

// ProxyAPI forwards every /api request to the backend container, which is what
// lets the embedded interface talk to it from this origin. Websockets included:
// ReverseProxy passes an Upgrade through untouched
func (s *Server) ProxyAPI(target string) error {
	u, err := url.Parse(strings.TrimRight(target, "/"))
	if err != nil {
		return err
	}
	if u.Scheme == "" || u.Host == "" {
		return fmt.Errorf("bad api url: %s", target)
	}
	proxy := httputil.NewSingleHostReverseProxy(u)
	proxy.FlushInterval = -1
	proxy.ErrorHandler = func(w http.ResponseWriter, _ *http.Request, _ error) {
		w.WriteHeader(http.StatusBadGateway)
	}
	s.apiProxy = proxy
	return nil
}

// SplashURL is the address the startup window loads
func (s *Server) SplashURL() string { return s.baseURL + "/splash/" }

func mustSub(fsys fs.FS, dir string) fs.FS {
	sub, err := fs.Sub(fsys, dir)
	if err != nil {
		panic(err)
	}
	return sub
}

func (s *Server) BaseURL() string { return s.baseURL }

func (s *Server) Close() {
	if s.listener != nil {
		_ = s.listener.Close()
	}
}

// SetTexts hands the startup screen the language the launcher resolved, so it
// speaks the same one as the rest of the app
func (s *Server) SetTexts(language string, ui, messages map[string]string) {
	s.textsMu.Lock()
	s.language, s.ui, s.messages = language, ui, messages
	s.textsMu.Unlock()
}

func (s *Server) texts() (string, map[string]string, map[string]string) {
	s.textsMu.RLock()
	defer s.textsMu.RUnlock()
	return s.language, s.ui, s.messages
}

func (s *Server) SetMode(mode string) {
	s.mu.Lock()
	s.mode = mode
	s.mu.Unlock()
	s.Publish("mode", map[string]string{"mode": mode})
}

// Publish fans an event out to every connected splash window
func (s *Server) Publish(event string, payload any) {
	data, err := json.Marshal(payload)
	if err != nil {
		return
	}
	msg := sseMessage{event: event, data: data}
	s.mu.RLock()
	defer s.mu.RUnlock()
	for ch := range s.clients {
		select {
		case ch <- msg:
		default:
		}
	}
}

func withCORS(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// The main window is same-origin when the interface is embedded, but
		// it lives on the frontend container's origin otherwise
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func (s *Server) handleEvents(w http.ResponseWriter, r *http.Request) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming unsupported", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")

	ch := make(chan sseMessage, 64)
	s.mu.Lock()
	s.clients[ch] = struct{}{}
	s.mu.Unlock()
	defer func() {
		s.mu.Lock()
		delete(s.clients, ch)
		s.mu.Unlock()
		close(ch)
	}()

	// A splash window that opens mid-startup gets the current state first, and
	// a password prompt raised before it connected would otherwise be lost
	if last := s.emitter.Last(); last != nil {
		writeSSE(w, "progress", last)
	}
	if failure := s.emitter.LastFailure(); failure != nil {
		writeSSE(w, "error-event", failure)
	}
	if req := s.PendingSudo(); req != nil {
		writeSSE(w, "sudo-request", req)
	}
	flusher.Flush()

	keepalive := time.NewTicker(20 * time.Second)
	defer keepalive.Stop()
	for {
		select {
		case <-r.Context().Done():
			return
		case msg := <-ch:
			fmt.Fprintf(w, "event: %s\ndata: %s\n\n", msg.event, msg.data)
			flusher.Flush()
		case <-keepalive.C:
			fmt.Fprint(w, ": ping\n\n")
			flusher.Flush()
		}
	}
}

func writeSSE(w http.ResponseWriter, event string, payload any) {
	data, err := json.Marshal(payload)
	if err != nil {
		return
	}
	fmt.Fprintf(w, "event: %s\ndata: %s\n\n", event, data)
}

func (s *Server) handleState(w http.ResponseWriter, _ *http.Request) {
	s.mu.RLock()
	mode := s.mode
	s.mu.RUnlock()
	language, ui, messages := s.texts()
	writeJSON(w, map[string]any{
		"mode":     mode,
		"progress": s.emitter.Last(),
		"logs":     s.emitter.LogTail(),
		"failure":  s.emitter.LastFailure(),
		"sudo":     s.PendingSudo(),
		"lang":     language,
		"ui":       ui,
		"messages": messages,
	})
}

func (s *Server) handleRetry(w http.ResponseWriter, _ *http.Request) {
	if s.OnRetry != nil {
		go s.OnRetry()
	}
	writeJSON(w, map[string]bool{"ok": true})
}

func (s *Server) handleFix(w http.ResponseWriter, r *http.Request) {
	kind := strings.TrimSpace(r.URL.Query().Get("kind"))
	if kind == "" {
		http.Error(w, "kind is required", http.StatusBadRequest)
		return
	}
	if s.OnFix != nil {
		go s.OnFix(kind)
	}
	writeJSON(w, map[string]bool{"ok": true})
}

func (s *Server) handleSudo(w http.ResponseWriter, r *http.Request) {
	var payload struct {
		Password string `json:"password"`
		Cancel   bool   `json:"cancel"`
	}
	_ = json.NewDecoder(r.Body).Decode(&payload)
	s.answerSudo(sudoAnswer{password: payload.Password, ok: !payload.Cancel})
	writeJSON(w, map[string]bool{"ok": true})
}

// BeginExitPrompt arms the channels the in-page confirmation answers on. The
// first channel fires as soon as the page has drawn the dialog, which is how a
// window whose script never ran falls back to a native one
func (s *Server) BeginExitPrompt() (<-chan struct{}, <-chan bool) {
	s.exitMu.Lock()
	defer s.exitMu.Unlock()
	s.exitShown = make(chan struct{}, 1)
	s.exitAnswer = make(chan bool, 1)
	return s.exitShown, s.exitAnswer
}

func (s *Server) EndExitPrompt() {
	s.exitMu.Lock()
	defer s.exitMu.Unlock()
	s.exitShown = nil
	s.exitAnswer = nil
}

func (s *Server) handleExit(w http.ResponseWriter, r *http.Request) {
	var payload struct {
		Shown bool  `json:"shown"`
		Ok    *bool `json:"ok"`
	}
	_ = json.NewDecoder(r.Body).Decode(&payload)

	s.exitMu.Lock()
	shown, answer := s.exitShown, s.exitAnswer
	s.exitMu.Unlock()

	if payload.Shown && shown != nil {
		select {
		case shown <- struct{}{}:
		default:
		}
	}
	if payload.Ok != nil && answer != nil {
		select {
		case answer <- *payload.Ok:
		default:
		}
	}
	writeJSON(w, map[string]bool{"ok": true})
}

func (s *Server) handleLanguage(w http.ResponseWriter, r *http.Request) {
	var payload struct {
		Lang    string            `json:"lang"`
		Strings map[string]string `json:"strings"`
	}
	if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
		http.Error(w, "bad payload", http.StatusBadRequest)
		return
	}
	if s.OnLanguage != nil {
		s.OnLanguage(payload.Lang, payload.Strings)
	}
	writeJSON(w, map[string]bool{"ok": true})
}

// AskSudo blocks until the splash screen answers the password prompt
func (s *Server) AskSudo() (string, bool) {
	req := orch.SudoRequest{
		Title:   "Rootful Docker access",
		Message: "Enter your sudo password to start privileged build containers",
	}

	s.sudoMu.Lock()
	ch := make(chan sudoAnswer, 1)
	s.sudoWait = ch
	s.pendingSudo = &req
	s.sudoMu.Unlock()

	s.emitter.AskSudo(req)

	var answer sudoAnswer
	select {
	case answer = <-ch:
	case <-time.After(5 * time.Minute):
	}
	s.sudoMu.Lock()
	s.sudoWait = nil
	s.pendingSudo = nil
	s.sudoMu.Unlock()
	return answer.password, answer.ok
}

// PendingSudo is the prompt still waiting for an answer, if any
func (s *Server) PendingSudo() *orch.SudoRequest {
	s.sudoMu.Lock()
	defer s.sudoMu.Unlock()
	return s.pendingSudo
}

func (s *Server) answerSudo(answer sudoAnswer) {
	s.sudoMu.Lock()
	ch := s.sudoWait
	s.pendingSudo = nil
	s.sudoMu.Unlock()
	if ch == nil {
		return
	}
	select {
	case ch <- answer:
	default:
	}
}

func writeJSON(w http.ResponseWriter, payload any) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(payload)
}
