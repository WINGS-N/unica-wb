package orch

import (
	"context"
	"errors"
	"runtime"
	"strings"
	"sync"
	"time"
)

const (
	modePlain  = "plain"
	modeSudo   = "sudo"
	modePkexec = "pkexec"
)

// docker wraps the docker CLI together with how it has to be invoked: plain, or
// escalated so the privileged worker container can be started
type docker struct {
	mu      sync.RWMutex
	mode    string
	context string
	host    string

	emitter  *Emitter
	askSudo  func() (string, bool)
	keepMu   sync.Mutex
	keepStop chan struct{}
}

func newDocker(e *Emitter, dockerContext, dockerHost string, askSudo func() (string, bool)) *docker {
	return &docker{
		mode:    modePlain,
		context: dockerContext,
		host:    dockerHost,
		emitter: e,
		askSudo: askSudo,
	}
}

func (d *docker) invocation(args []string, mode, dockerContext, host string) (string, []string) {
	prefix := []string{}
	if dockerContext != "" {
		prefix = append(prefix, "--context", dockerContext)
	}
	if host != "" {
		prefix = append(prefix, "-H", host)
	}
	full := append(prefix, args...)
	switch mode {
	case modeSudo:
		return "sudo", append([]string{"docker"}, full...)
	case modePkexec:
		return "pkexec", append([]string{"docker"}, full...)
	default:
		return "docker", full
	}
}

func (d *docker) current() (string, string, string) {
	d.mu.RLock()
	defer d.mu.RUnlock()
	return d.mode, d.context, d.host
}

// Run executes a docker command with the currently configured privilege mode
func (d *docker) Run(ctx context.Context, args []string, opts RunOptions) (RunResult, error) {
	mode, dockerContext, host := d.current()
	name, full := d.invocation(args, mode, dockerContext, host)
	return Run(ctx, name, full, opts)
}

func (d *docker) runAs(ctx context.Context, mode, dockerContext, host string, args []string, opts RunOptions) (RunResult, error) {
	name, full := d.invocation(args, mode, dockerContext, host)
	return Run(ctx, name, full, opts)
}

func (d *docker) isRootless(ctx context.Context, mode, dockerContext, host string) (bool, error) {
	res, err := d.runAs(ctx, mode, dockerContext, host,
		[]string{"info", "--format", "{{json .SecurityOptions}}"},
		RunOptions{Timeout: 30 * time.Second})
	if err != nil {
		return false, err
	}
	return strings.Contains(strings.ToLower(res.Stdout), "rootless"), nil
}

// sudoValidate reuses a live sudo ticket when there is one and otherwise asks
// the splash screen for a password, up to three times
func (d *docker) sudoValidate(ctx context.Context) bool {
	if _, err := Run(ctx, "sudo", []string{"-n", "-v"}, RunOptions{Timeout: 10 * time.Second}); err == nil {
		return true
	}
	if d.askSudo == nil {
		return false
	}
	for attempt := 1; attempt <= 3; attempt++ {
		password, ok := d.askSudo()
		if !ok {
			return false
		}
		_, err := Run(ctx, "sudo", []string{"-S", "-v"}, RunOptions{
			Timeout:   30 * time.Second,
			StdinText: password + "\n",
		})
		if err == nil {
			return true
		}
		d.emitter.Emit(Progress{
			Stage:         "check",
			Progress:      35,
			TotalProgress: 5,
			Message:       "Sudo authentication failed (" + itoa(attempt) + "/3), try again",
		})
	}
	return false
}

// startKeepalive refreshes the sudo ticket so a long startup does not hit a
// second password prompt halfway through
func (d *docker) startKeepalive() {
	d.keepMu.Lock()
	defer d.keepMu.Unlock()
	if d.keepStop != nil {
		return
	}
	stop := make(chan struct{})
	d.keepStop = stop
	go func() {
		ticker := time.NewTicker(50 * time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-stop:
				return
			case <-ticker.C:
				ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
				_, _ = Run(ctx, "sudo", []string{"-n", "-v"}, RunOptions{})
				cancel()
			}
		}
	}()
}

func (d *docker) stopKeepalive() {
	d.keepMu.Lock()
	defer d.keepMu.Unlock()
	if d.keepStop == nil {
		return
	}
	close(d.keepStop)
	d.keepStop = nil
}

// ensureSudoSession is used by the host fixes, which always need root even when
// docker itself does not
func (d *docker) ensureSudoSession(ctx context.Context) bool {
	if _, err := Run(ctx, "sudo", []string{"-n", "-v"}, RunOptions{Timeout: 10 * time.Second}); err == nil {
		return true
	}
	if !d.sudoValidate(ctx) {
		return false
	}
	d.startKeepalive()
	return true
}

// configureAccess picks the way docker has to be invoked. The worker container
// is privileged and needs loop devices, which a rootless daemon cannot provide,
// so a rootless daemon is escalated or rejected
func (d *docker) configureAccess(ctx context.Context, require bool, privMode string) error {
	if runtime.GOOS != "linux" || !require {
		return nil
	}

	_, dockerContext, host := d.current()

	rootless, err := d.isRootless(ctx, modePlain, dockerContext, host)
	if err == nil && !rootless {
		return nil
	}
	if err != nil {
		// An unreadable daemon is not the same as a rootless one, and saying so
		// saves a long hunt when the real problem is access or a stopped daemon
		d.emitter.Stage("check", 20, "Docker is not reachable as this user, trying sudo/pkexec")
	} else {
		d.emitter.Stage("check", 20, "Docker is rootless, the privileged worker needs a rootful daemon")
	}

	if dockerContext == "" {
		if rl, err := d.isRootless(ctx, modePlain, "default", host); err == nil && !rl {
			d.mu.Lock()
			d.context = "default"
			d.mu.Unlock()
			d.emitter.Stage("check", 40, "Switched to docker context: default")
			return nil
		}
	}

	canSudo := commandExists(ctx, "sudo")
	canPkexec := commandExists(ctx, "pkexec")

	// The session mode asks for the password once and keeps the ticket warm,
	// which avoids a pkexec dialog per docker call
	if (privMode == "session" || privMode == "sudo") && canSudo {
		if !d.sudoValidate(ctx) {
			return errors.New("sudo authentication was cancelled or failed")
		}
		if rl, err := d.isRootless(ctx, modeSudo, dockerContext, host); err == nil && !rl {
			d.mu.Lock()
			d.mode = modeSudo
			d.mu.Unlock()
			d.startKeepalive()
			d.emitter.Stage("check", 40, "Using rootful Docker session via sudo")
			return nil
		}
	}

	if (privMode == "pkexec" || privMode == "auto" || privMode == "session" || privMode == "sudo") && canPkexec {
		if rl, err := d.isRootless(ctx, modePkexec, dockerContext, host); err == nil && !rl {
			d.mu.Lock()
			d.mode = modePkexec
			d.mu.Unlock()
			d.emitter.Stage("check", 40, "Using rootful Docker via pkexec")
			return nil
		}
	}

	mode, dockerContext, host := d.current()
	if rl, err := d.isRootless(ctx, mode, dockerContext, host); err != nil || rl {
		return errors.New("rootful Docker is required for the privileged worker, but the daemon is rootless after all attempts")
	}
	return nil
}

func itoa(v int) string {
	if v == 0 {
		return "0"
	}
	neg := v < 0
	if neg {
		v = -v
	}
	var buf [20]byte
	i := len(buf)
	for v > 0 {
		i--
		buf[i] = byte('0' + v%10)
		v /= 10
	}
	if neg {
		i--
		buf[i] = '-'
	}
	return string(buf[i:])
}
