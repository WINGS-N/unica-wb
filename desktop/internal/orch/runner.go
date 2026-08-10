package orch

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"sync"
	"time"
)

// RunOptions mirrors the knobs the startup sequence needs from a child process:
// a working directory, extra env, a hard timeout, stdin for sudo, and line
// callbacks so progress can be streamed while the command is still running
type RunOptions struct {
	Dir       string
	Env       []string
	Timeout   time.Duration
	StdinText string
	OnStdout  func(string)
	OnStderr  func(string)
}

type RunResult struct {
	Stdout string
	Stderr string
}

// RunError carries the captured output so callers can pattern-match on it for
// the loop/f2fs/fuse hints
type RunError struct {
	Cmd    string
	Err    error
	Stdout string
	Stderr string
}

func (e *RunError) Error() string {
	msg := fmt.Sprintf("%s failed: %v", e.Cmd, e.Err)
	if s := strings.TrimSpace(e.Stderr); s != "" {
		msg = fmt.Sprintf("%s\n%s", msg, s)
	}
	return msg
}

func (e *RunError) Unwrap() error { return e.Err }

// Output returns everything the command printed, used for the fix hints
func (e *RunError) Output() string {
	return strings.TrimSpace(e.Stdout + "\n" + e.Stderr)
}

type streamWriter struct {
	mu   sync.Mutex
	buf  bytes.Buffer
	line bytes.Buffer
	on   func(string)
}

func (w *streamWriter) Write(p []byte) (int, error) {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.buf.Write(p)
	if w.on == nil {
		return len(p), nil
	}
	// Docker writes progress with \r, so both terminators start a new line
	for _, b := range p {
		if b == '\n' || b == '\r' {
			if text := strings.TrimSpace(w.line.String()); text != "" {
				w.on(text)
			}
			w.line.Reset()
			continue
		}
		w.line.WriteByte(b)
	}
	return len(p), nil
}

func (w *streamWriter) flush() {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.on == nil {
		return
	}
	if text := strings.TrimSpace(w.line.String()); text != "" {
		w.on(text)
	}
	w.line.Reset()
}

func (w *streamWriter) String() string {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.buf.String()
}

// Run executes a command and returns its output. A timeout kills the whole
// process group so a stuck docker CLI cannot wedge the startup sequence
func Run(ctx context.Context, name string, args []string, opts RunOptions) (RunResult, error) {
	if opts.Timeout > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, opts.Timeout)
		defer cancel()
	}

	cmd := exec.CommandContext(ctx, name, args...)
	cmd.Dir = opts.Dir
	cmd.Env = append(os.Environ(), opts.Env...)
	cmd.Cancel = func() error { return cmd.Process.Kill() }
	cmd.WaitDelay = 5 * time.Second

	stdout := &streamWriter{on: opts.OnStdout}
	stderr := &streamWriter{on: opts.OnStderr}
	cmd.Stdout = stdout
	cmd.Stderr = stderr

	if opts.StdinText != "" {
		stdin, err := cmd.StdinPipe()
		if err != nil {
			return RunResult{}, err
		}
		go func() {
			defer stdin.Close()
			_, _ = io.WriteString(stdin, opts.StdinText)
		}()
	}

	err := cmd.Run()
	stdout.flush()
	stderr.flush()
	res := RunResult{Stdout: stdout.String(), Stderr: stderr.String()}
	if err != nil {
		if errors.Is(ctx.Err(), context.DeadlineExceeded) {
			err = fmt.Errorf("timed out after %s", opts.Timeout)
		}
		return res, &RunError{
			Cmd:    strings.TrimSpace(name + " " + strings.Join(args, " ")),
			Err:    err,
			Stdout: res.Stdout,
			Stderr: res.Stderr,
		}
	}
	return res, nil
}

func commandExists(ctx context.Context, name string) bool {
	_, err := exec.LookPath(name)
	if err == nil {
		return true
	}
	_, err = Run(ctx, "which", []string{name}, RunOptions{Timeout: 5 * time.Second})
	return err == nil
}
