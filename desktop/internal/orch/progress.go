package orch

import (
	"fmt"
	"math"
	"sync"
	"time"
)

// Progress is the payload the splash screen renders
type Progress struct {
	Stage         string  `json:"stage"`
	Progress      int     `json:"progress"`
	TotalProgress int     `json:"totalProgress"`
	Message       string  `json:"message,omitempty"`
	Detail        string  `json:"detail,omitempty"`
	Downloaded    int64   `json:"downloaded,omitempty"`
	Total         int64   `json:"total,omitempty"`
	Speed         float64 `json:"speed,omitempty"`
}

// Failure is a startup error plus, when we recognise the cause, the one-click
// fix the splash screen should offer
type Failure struct {
	Message  string `json:"message"`
	Code     string `json:"code,omitempty"`
	FixKind  string `json:"fixKind,omitempty"`
	FixLabel string `json:"fixLabel,omitempty"`
}

// SudoRequest asks the splash screen for a password
type SudoRequest struct {
	Title   string `json:"title"`
	Message string `json:"message"`
}

// Each stage owns a slice of the overall bar
var stageRange = map[string][2]int{
	"check":    {0, 15},
	"seed":     {15, 30},
	"pull":     {30, 50},
	"compose":  {50, 75},
	"health":   {75, 99},
	"shutdown": {0, 100},
}

// RecoverableError is a failure the user can act on without restarting the app
type RecoverableError struct {
	Failure Failure
}

func (e *RecoverableError) Error() string { return e.Failure.Message }

// Emitter fans startup events out to the splash screen and keeps a log tail so
// a splash window opened late can catch up
type Emitter struct {
	mu          sync.RWMutex
	last        *Progress
	logs        []string
	lastMessage string
	lastFailure *Failure
	onEvent     func(kind string, payload any)
	shutdown    bool
}

func NewEmitter(onEvent func(kind string, payload any)) *Emitter {
	return &Emitter{onEvent: onEvent}
}

func (e *Emitter) SetShutdown(v bool) {
	e.mu.Lock()
	e.shutdown = v
	e.mu.Unlock()
}

func (e *Emitter) Last() *Progress {
	e.mu.RLock()
	defer e.mu.RUnlock()
	return e.last
}

func (e *Emitter) LogTail() []string {
	e.mu.RLock()
	defer e.mu.RUnlock()
	out := make([]string, len(e.logs))
	copy(out, e.logs)
	return out
}

func (e *Emitter) Emit(p Progress) {
	e.mu.Lock()
	// Once shutdown starts, stale startup events must not overwrite the
	// stopping progress the user is looking at
	if e.shutdown && p.Stage != "shutdown" {
		e.mu.Unlock()
		return
	}
	copied := p
	e.last = &copied
	e.lastFailure = nil
	// A stage that reports the same line while it walks a list of devices would
	// otherwise fill the log with copies of itself
	if p.Message != "" && p.Message != e.lastMessage {
		e.lastMessage = p.Message
		e.logs = append(e.logs, fmt.Sprintf("[%s] %s", time.Now().Format("15:04:05"), p.Message))
		if len(e.logs) > 300 {
			e.logs = e.logs[len(e.logs)-300:]
		}
	}
	cb := e.onEvent
	e.mu.Unlock()
	if cb != nil {
		cb("progress", copied)
	}
}

// Stage emits progress inside a stage, mapping the local 0-100 onto that
// stage's slice of the overall bar
func (e *Emitter) Stage(stage string, progress int, message string) {
	e.StageDetail(stage, progress, message, "")
}

func (e *Emitter) StageDetail(stage string, progress int, message, detail string) {
	r, ok := stageRange[stage]
	if !ok {
		r = [2]int{0, 100}
	}
	p := clampInt(progress, 0, 100)
	total := r[0] + int(math.Round(float64(r[1]-r[0])*float64(p)/100.0))
	e.Emit(Progress{
		Stage:         stage,
		Progress:      p,
		TotalProgress: clampInt(total, 0, 100),
		Message:       message,
		Detail:        detail,
	})
}

func (e *Emitter) Shutdown(progress int, message string) {
	p := clampInt(progress, 0, 100)
	e.Emit(Progress{Stage: "shutdown", Progress: p, TotalProgress: p, Message: message})
}

// LastFailure is the failure the user still has to act on, replayed to a
// window that connects after the sequence already failed
func (e *Emitter) LastFailure() *Failure {
	e.mu.RLock()
	defer e.mu.RUnlock()
	if e.lastFailure == nil {
		return nil
	}
	copied := *e.lastFailure
	return &copied
}

func (e *Emitter) Failed() bool { return e.LastFailure() != nil }

func (e *Emitter) Fail(f Failure) {
	e.mu.Lock()
	copied := f
	e.lastFailure = &copied
	cb := e.onEvent
	e.mu.Unlock()
	if cb != nil {
		cb("error", f)
	}
}

func (e *Emitter) AskSudo(req SudoRequest) {
	e.mu.RLock()
	cb := e.onEvent
	e.mu.RUnlock()
	if cb != nil {
		cb("sudo-request", req)
	}
}

func clampInt(v, lo, hi int) int {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}
