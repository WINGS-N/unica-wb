package orch

import (
	"context"
	"fmt"
	"math"
	"net/http"
	"strings"
	"time"
)

func waitHTTPOK(ctx context.Context, url string, timeout time.Duration, onTick func(elapsed, total time.Duration)) error {
	client := &http.Client{Timeout: 3 * time.Second}
	started := time.Now()
	for {
		elapsed := time.Since(started)
		if onTick != nil {
			onTick(elapsed, timeout)
		}
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
		if err != nil {
			return err
		}
		resp, err := client.Do(req)
		if err == nil {
			code := resp.StatusCode
			resp.Body.Close()
			// Anything the server actually answers means it is up; a 4xx from
			// the SPA router still proves the port is serving
			if code >= 200 && code < 500 {
				return nil
			}
		}
		if elapsed > timeout {
			return fmt.Errorf("timed out waiting for %s", url)
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(1500 * time.Millisecond):
		}
	}
}

func (o *Orchestrator) serviceHealth(ctx context.Context, service string) string {
	res, err := o.docker.Run(ctx, []string{
		"ps", "-aq",
		"--filter", "label=com.docker.compose.project=" + o.cfg.ComposeProject,
		"--filter", "label=com.docker.compose.service=" + service,
	}, RunOptions{Timeout: 10 * time.Second})
	if err != nil {
		return "missing"
	}
	id := ""
	for _, field := range strings.Fields(res.Stdout) {
		id = field
		break
	}
	if id == "" {
		return "missing"
	}
	out, err := o.docker.Run(ctx, []string{
		"inspect", "--format",
		"{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}", id,
	}, RunOptions{Timeout: 10 * time.Second})
	if err != nil {
		return "unknown"
	}
	status := strings.ToLower(strings.TrimSpace(out.Stdout))
	if status == "" {
		return "unknown"
	}
	return status
}

func (o *Orchestrator) waitServiceHealthy(ctx context.Context, service string, timeout time.Duration, onTick func(elapsed, total time.Duration)) error {
	started := time.Now()
	for {
		elapsed := time.Since(started)
		if onTick != nil {
			onTick(elapsed, timeout)
		}
		switch o.serviceHealth(ctx, service) {
		case "healthy", "running":
			return nil
		case "unhealthy":
			return fmt.Errorf("service %s is unhealthy", service)
		}
		if elapsed > timeout {
			return fmt.Errorf("timed out waiting for %s health", service)
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(1500 * time.Millisecond):
		}
	}
}

func ratio(elapsed, total time.Duration, lo, hi int) int {
	if total <= 0 {
		return lo
	}
	span := float64(hi - lo)
	value := lo + int(math.Round(span*(float64(elapsed)/float64(total))))
	return clampInt(value, lo, hi)
}

func (o *Orchestrator) waitUntilReady(ctx context.Context) error {
	o.emitter.Stage("health", 2, "Waiting for API health")
	if err := waitHTTPOK(ctx, o.cfg.APIHealthURL, 8*time.Minute, func(elapsed, total time.Duration) {
		o.emitter.Stage("health", ratio(elapsed, total, 2, 65), "Waiting for API health")
	}); err != nil {
		return err
	}

	o.emitter.Stage("health", 68, "Waiting for worker health")
	if err := o.waitServiceHealthy(ctx, "worker", 5*time.Minute, func(elapsed, total time.Duration) {
		o.emitter.Stage("health", ratio(elapsed, total, 68, 80), "Waiting for worker health")
	}); err != nil {
		return err
	}

	if !o.cfg.EmbeddedUI {
		o.emitter.Stage("health", 82, "Waiting for frontend")
		if err := waitHTTPOK(ctx, o.cfg.FrontendURL, 3*time.Minute, func(elapsed, total time.Duration) {
			o.emitter.Stage("health", ratio(elapsed, total, 82, 95), "Waiting for frontend")
		}); err != nil {
			return err
		}
	}

	o.emitter.Stage("health", 100, "Services are ready")
	return nil
}
