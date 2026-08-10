package orch

import (
	"context"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// prepareRuntimeFiles copies the compose files and a merged .env into a
// writable directory. Root-side docker commands cannot always read the install
// prefix, and the env file has to carry the passthrough variables of this run
func (o *Orchestrator) prepareRuntimeFiles() error {
	if err := os.MkdirAll(o.cfg.RuntimeDir, 0o755); err != nil {
		return err
	}

	files := []string{}
	for _, src := range o.cfg.ComposeFiles() {
		data, err := os.ReadFile(src)
		if err != nil {
			continue
		}
		dst := filepath.Join(o.cfg.RuntimeDir, filepath.Base(src))
		if err := os.WriteFile(dst, data, 0o644); err != nil {
			return err
		}
		files = append(files, dst)
	}
	if len(files) == 0 {
		return fmt.Errorf("docker-compose.yml not found under %s", o.cfg.RootDir)
	}
	o.composeFiles = files

	lines := []string{}
	if data, err := os.ReadFile(filepath.Join(o.cfg.RootDir, ".env")); err == nil {
		lines = append(lines, strings.TrimRight(string(data), "\n"))
	}
	for _, key := range o.cfg.PassthroughEnv {
		value := strings.TrimSpace(os.Getenv(key))
		if value == "" {
			continue
		}
		escaped := strings.ReplaceAll(value, `\`, `\\`)
		escaped = strings.ReplaceAll(escaped, `"`, `\"`)
		lines = append(lines, fmt.Sprintf("%s=%q", key, escaped))
	}
	kept := []string{}
	for _, line := range lines {
		if strings.TrimSpace(line) != "" {
			kept = append(kept, line)
		}
	}
	if len(kept) == 0 {
		o.composeEnvFile = ""
		return nil
	}
	envPath := filepath.Join(o.cfg.RuntimeDir, ".env")
	if err := os.WriteFile(envPath, []byte(strings.Join(kept, "\n")+"\n"), 0o600); err != nil {
		return err
	}
	o.composeEnvFile = envPath
	return nil
}

func (o *Orchestrator) composeArgs(action string, extra ...string) []string {
	args := []string{"compose", "-p", o.cfg.ComposeProject}
	if o.composeEnvFile != "" {
		args = append(args, "--env-file", o.composeEnvFile)
	}
	for _, file := range o.composeFiles {
		args = append(args, "-f", file)
	}
	args = append(args, action)
	return append(args, extra...)
}

// containerWeight turns a docker status string into how far along that
// container is, so the compose stage can show real movement instead of sitting
// at zero until everything is up
func containerWeight(status string) float64 {
	text := strings.ToLower(status)
	switch {
	case text == "":
		return 0
	case strings.Contains(text, "healthy"):
		return 1.0
	case strings.Contains(text, "up"):
		if strings.Contains(text, "health: starting") {
			return 0.85
		}
		return 0.95
	case strings.Contains(text, "starting"):
		return 0.75
	case strings.Contains(text, "created"):
		return 0.5
	case strings.Contains(text, "restarting"):
		return 0.45
	case strings.Contains(text, "exited"):
		return 0.15
	}
	return 0.2
}

func (o *Orchestrator) composeSnapshot(ctx context.Context) (int, string) {
	res, err := o.docker.Run(ctx, []string{
		"ps", "-a",
		"--filter", "label=com.docker.compose.project=" + o.cfg.ComposeProject,
		"--format", "{{.Names}}\t{{.Status}}",
	}, RunOptions{Timeout: 10 * time.Second})
	if err != nil {
		return 0, ""
	}

	weights := map[string]float64{}
	statuses := map[string]string{}
	for _, svc := range o.cfg.ComposeServices {
		weights[svc] = 0
		statuses[svc] = "not created yet"
	}

	prefix := o.cfg.ComposeProject + "-"
	for _, line := range strings.Split(res.Stdout, "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		parts := strings.SplitN(line, "\t", 2)
		name := parts[0]
		status := ""
		if len(parts) > 1 {
			status = parts[1]
		}
		service := name
		if strings.HasPrefix(name, prefix) {
			service = strings.TrimSuffix(name[len(prefix):], "")
			if idx := strings.LastIndex(service, "-"); idx > 0 {
				if _, err := parseUint(service[idx+1:]); err == nil {
					service = service[:idx]
				}
			}
		}
		if _, ok := weights[service]; !ok {
			continue
		}
		if w := containerWeight(status); w > weights[service] {
			weights[service] = w
			if status == "" {
				status = "created"
			}
			statuses[service] = status
		}
	}

	sum := 0.0
	for _, svc := range o.cfg.ComposeServices {
		sum += weights[svc]
	}
	pct := 0
	if len(o.cfg.ComposeServices) > 0 {
		pct = clampInt(int(math.Round(sum/float64(len(o.cfg.ComposeServices))*100)), 0, 100)
	}

	details := make([]string, 0, len(o.cfg.ComposeServices))
	for _, svc := range o.cfg.ComposeServices {
		details = append(details, svc+": "+statuses[svc])
	}
	return pct, strings.Join(details, " | ")
}

func parseUint(s string) (uint64, error) {
	var out uint64
	if s == "" {
		return 0, fmt.Errorf("empty")
	}
	for _, c := range s {
		if c < '0' || c > '9' {
			return 0, fmt.Errorf("not a number")
		}
		out = out*10 + uint64(c-'0')
	}
	return out, nil
}

func (o *Orchestrator) composeUp(ctx context.Context) error {
	o.emitter.Stage("compose", 3, "Starting...")
	o.composeStarted.Store(true)

	stop := make(chan struct{})
	defer close(stop)
	go func() {
		ticker := time.NewTicker(1200 * time.Millisecond)
		defer ticker.Stop()
		for {
			select {
			case <-stop:
				return
			case <-ticker.C:
				pct, detail := o.composeSnapshot(ctx)
				o.emitter.StageDetail("compose", clampInt(pct, 5, 100),
					fmt.Sprintf("Starting containers... %d%%", pct), detail)
			}
		}
	}()

	args := o.composeArgs("up", append([]string{"-d"}, o.cfg.ComposeServices...)...)
	onLine := func(line string) {
		if line != "" {
			o.emitter.Stage("compose", 10, line)
		}
	}
	if _, err := o.docker.Run(ctx, args, RunOptions{OnStdout: onLine, OnStderr: onLine}); err != nil {
		return err
	}
	o.emitter.Stage("compose", 100, "Containers are started")
	return nil
}

func (o *Orchestrator) projectContainerIDs(ctx context.Context, timeout time.Duration) []string {
	res, err := o.docker.Run(ctx, []string{
		"ps", "-aq",
		"--filter", "label=com.docker.compose.project=" + o.cfg.ComposeProject,
	}, RunOptions{Timeout: timeout})
	if err != nil {
		return nil
	}
	ids := []string{}
	for _, field := range strings.Fields(res.Stdout) {
		if field != "" {
			ids = append(ids, field)
		}
	}
	return ids
}

// ComposeDown stops the stack. compose down occasionally leaves containers
// behind, so anything still labelled with the project is removed afterwards
func (o *Orchestrator) ComposeDown(ctx context.Context) {
	if !o.composeStarted.Load() {
		o.emitter.Shutdown(100, "No running compose services")
		return
	}
	o.emitter.Shutdown(10, "Stopping docker compose services")
	args := o.composeArgs("down", "--remove-orphans", "--timeout", "20")
	_, _ = o.docker.Run(ctx, args, RunOptions{Timeout: o.cfg.ComposeDownTimeout})

	o.emitter.Shutdown(70, "Cleaning up leftover containers")
	if ids := o.projectContainerIDs(ctx, 15*time.Second); len(ids) > 0 {
		o.emitter.Shutdown(85, fmt.Sprintf("Removing %d leftover container(s)", len(ids)))
		_, _ = o.docker.Run(ctx, append([]string{"rm", "-f"}, ids...), RunOptions{Timeout: 30 * time.Second})
	}
	o.emitter.Shutdown(100, "Docker services stopped")
}

// ComposeForceKill is the last resort when a graceful shutdown runs out of time
func (o *Orchestrator) ComposeForceKill(ctx context.Context) {
	ids := o.projectContainerIDs(ctx, 10*time.Second)
	if len(ids) == 0 {
		return
	}
	o.emitter.Shutdown(95, fmt.Sprintf("Shutdown timeout reached, force-killing %d container(s)", len(ids)))
	_, _ = o.docker.Run(ctx, append([]string{"kill"}, ids...), RunOptions{Timeout: 15 * time.Second})
	_, _ = o.docker.Run(ctx, append([]string{"rm", "-f"}, ids...), RunOptions{Timeout: 15 * time.Second})
}
