package orch

import (
	"context"
	"errors"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"unica-wb/desktop/internal/config"
)

// Orchestrator owns the whole "make the stack runnable, then start it"
// sequence: host checks, images, compose, health
type Orchestrator struct {
	cfg     config.Config
	emitter *Emitter
	docker  *docker

	composeFiles   []string
	composeEnvFile string
	composeStarted atomic.Bool

	runMu   sync.Mutex
	running atomic.Bool
}

func New(cfg config.Config, emitter *Emitter, askSudo func() (string, bool)) *Orchestrator {
	return &Orchestrator{
		cfg:     cfg,
		emitter: emitter,
		docker:  newDocker(emitter, cfg.DockerContext, cfg.DockerHost, askSudo),
	}
}

func (o *Orchestrator) Emitter() *Emitter { return o.emitter }

func (o *Orchestrator) Running() bool { return o.running.Load() }

func (o *Orchestrator) StopKeepalive() { o.docker.stopKeepalive() }

// Startup runs the full sequence. A recoverable failure is reported to the
// splash screen with a fix button and leaves the app waiting for the user;
// anything else tears the stack back down so a half-started project is not left
// behind
func (o *Orchestrator) Startup(ctx context.Context) error {
	o.runMu.Lock()
	defer o.runMu.Unlock()
	if o.running.Load() {
		return nil
	}
	o.running.Store(true)
	defer o.running.Store(false)

	err := o.startupSequence(ctx)
	if err == nil {
		o.emitter.Emit(Progress{Stage: "health", Progress: 100, TotalProgress: 100, Message: "Startup complete"})
		return nil
	}

	var recoverable *RecoverableError
	if errors.As(err, &recoverable) {
		o.emitter.Fail(recoverable.Failure)
		return err
	}

	o.emitter.Emit(Progress{Stage: "shutdown", Message: "Startup failed, cleaning up compose services..."})
	shutdownCtx, cancel := context.WithTimeout(context.Background(), o.cfg.ComposeDownTimeout)
	o.ComposeDown(shutdownCtx)
	cancel()

	text := errorText(err)
	kind, label := fixHintsFromText(text)
	o.emitter.Fail(Failure{Message: text, FixKind: kind, FixLabel: label})
	return err
}

func (o *Orchestrator) startupSequence(ctx context.Context) error {
	if err := o.prepareRuntimeFiles(); err != nil {
		return err
	}
	o.emitter.Stage("check", 5, "Preparing startup sequence")
	o.emitter.Stage("check", 20, "Checking Docker daemon")
	if err := o.docker.configureAccess(ctx, o.cfg.RequireRootfulDocker, o.cfg.PrivMode); err != nil {
		return err
	}
	if _, err := o.docker.Run(ctx, []string{"version"}, RunOptions{Timeout: 30 * time.Second}); err != nil {
		return err
	}

	o.emitter.Stage("check", 70, "Checking loop devices")
	if err := o.assertLoopDevices(); err != nil {
		return err
	}
	o.emitter.Stage("check", 75, "Checking FUSE support")
	if err := o.assertFuse(); err != nil {
		return err
	}
	o.emitter.Stage("check", 80, "Checking f2fs support")
	if err := o.assertF2fs(); err != nil {
		return err
	}
	o.emitter.Stage("check", 100, "Docker is available")

	images := o.loadManifest()
	if err := o.ensureSeedImages(ctx, images); err != nil {
		return err
	}
	if err := o.updateImages(ctx, images); err != nil {
		return err
	}
	if err := o.composeUp(ctx); err != nil {
		return err
	}
	if err := o.waitUntilReady(ctx); err != nil {
		return err
	}
	o.cleanupImages(ctx, images)
	return nil
}

// ApplyFix runs one of the host repairs and reports the outcome the same way
// Startup does
func (o *Orchestrator) ApplyFix(ctx context.Context, kind string) error {
	if o.running.Load() {
		return errors.New("startup is already running")
	}

	var err error
	switch kind {
	case "loop":
		err = o.FixLoopDevices(ctx)
	case "f2fs":
		err = o.FixF2fs(ctx)
	case "fuse":
		err = o.FixFuse(ctx)
	default:
		return errors.New("unknown fix: " + kind)
	}
	if err == nil {
		return nil
	}

	var recoverable *RecoverableError
	if errors.As(err, &recoverable) {
		o.emitter.Fail(recoverable.Failure)
		return err
	}
	text := errorText(err)
	hintKind, label := fixHintsFromText(text)
	if hintKind == "" {
		hintKind, label = kind, "Retry fix"
	}
	o.emitter.Fail(Failure{Message: text, Code: kind + "_fix_failed", FixKind: hintKind, FixLabel: label})
	return err
}

func errorText(err error) string {
	if err == nil {
		return ""
	}
	var runErr *RunError
	if errors.As(err, &runErr) {
		return strings.TrimSpace(runErr.Error() + "\n" + runErr.Output())
	}
	return err.Error()
}
