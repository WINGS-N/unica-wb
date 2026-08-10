package orch

import (
	"context"
	"fmt"
	"os"
	"strings"
	"time"
)

// The build mounts partition images, which needs loop devices, FUSE and the
// f2fs driver on the host kernel. Each check knows how to repair itself, and
// the splash screen turns that into a one-click button

func requiredLoopDevices() []string {
	items := []string{"/dev/loop-control"}
	for i := 0; i <= 7; i++ {
		items = append(items, fmt.Sprintf("/dev/loop%d", i))
	}
	return items
}

func missingLoopDevices() []string {
	missing := []string{}
	for _, path := range requiredLoopDevices() {
		if _, err := os.Stat(path); err != nil {
			missing = append(missing, path)
		}
	}
	return missing
}

func loopMissingMessage(missing []string) string {
	return strings.Join([]string{
		"Required loop devices are missing on the host.",
		"Missing: " + strings.Join(missing, ", "),
		"",
		`Click "Fix loop devices" to run:`,
		"sudo modprobe loop max_loop=64",
		"sudo mknod /dev/loopN ... (for N=0..7)",
	}, "\n")
}

func (o *Orchestrator) assertLoopDevices() error {
	missing := missingLoopDevices()
	if len(missing) == 0 {
		return nil
	}
	return &RecoverableError{Failure: Failure{
		Message:  loopMissingMessage(missing),
		Code:     "loop_devices_missing",
		FixKind:  "loop",
		FixLabel: "Fix loop devices",
	}}
}

func hasFilesystemType(fsType string) bool {
	data, err := os.ReadFile("/proc/filesystems")
	if err != nil {
		return false
	}
	for _, line := range strings.Split(string(data), "\n") {
		for _, field := range strings.Fields(line) {
			if field == fsType {
				return true
			}
		}
	}
	return false
}

func hasDeviceNode(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

func f2fsMissingMessage() string {
	return strings.Join([]string{
		"Required filesystem support is missing on the host kernel: f2fs.",
		"",
		`Click "Enable f2fs module" to run:`,
		"sudo modprobe f2fs",
	}, "\n")
}

func (o *Orchestrator) assertF2fs() error {
	if hasFilesystemType("f2fs") {
		return nil
	}
	return &RecoverableError{Failure: Failure{
		Message:  f2fsMissingMessage(),
		Code:     "f2fs_missing",
		FixKind:  "f2fs",
		FixLabel: "Enable f2fs module",
	}}
}

func missingFuseRequirements() []string {
	missing := []string{}
	if !hasFilesystemType("fuse") {
		missing = append(missing, "fuse module")
	}
	if !hasDeviceNode("/dev/fuse") {
		missing = append(missing, "/dev/fuse")
	}
	return missing
}

func fuseMissingMessage(missing []string) string {
	lines := []string{
		"Required FUSE support is missing on the host kernel/runtime.",
		"Missing: " + strings.Join(missing, ", "),
		"",
		`Click "Enable FUSE support" to run:`,
	}
	for _, item := range missing {
		if item == "fuse module" {
			lines = append(lines, "sudo modprobe fuse")
		}
		if item == "/dev/fuse" {
			lines = append(lines, "sudo mknod -m 666 /dev/fuse c 10 229")
		}
	}
	return strings.Join(lines, "\n")
}

func (o *Orchestrator) assertFuse() error {
	missing := missingFuseRequirements()
	if len(missing) == 0 {
		return nil
	}
	return &RecoverableError{Failure: Failure{
		Message:  fuseMissingMessage(missing),
		Code:     "fuse_missing",
		FixKind:  "fuse",
		FixLabel: "Enable FUSE support",
	}}
}

func (o *Orchestrator) requireSudoForFix(ctx context.Context, kind, label string) error {
	if !commandExists(ctx, "sudo") {
		return &RecoverableError{Failure: Failure{
			Message:  "sudo is required to apply this fix automatically.",
			Code:     kind + "_fix_failed",
			FixKind:  kind,
			FixLabel: label,
		}}
	}
	if !o.docker.ensureSudoSession(ctx) {
		return &RecoverableError{Failure: Failure{
			Message:  "Sudo authentication was cancelled.",
			Code:     kind + "_fix_cancelled",
			FixKind:  kind,
			FixLabel: label,
		}}
	}
	return nil
}

const loopFixScript = `set -eu
modprobe loop max_loop=64
i=0
while [ "$i" -le 7 ]; do
  if [ ! -b "/dev/loop$i" ]; then
    mknod -m 660 "/dev/loop$i" b 7 "$i"
  fi
  chgrp disk "/dev/loop$i" || true
  i=$((i+1))
done`

func (o *Orchestrator) FixLoopDevices(ctx context.Context) error {
	o.emitter.Stage("check", 35, "Fixing loop devices on host")
	if err := o.requireSudoForFix(ctx, "loop_devices", "Fix loop devices"); err != nil {
		return err
	}
	if _, err := Run(ctx, "sudo", []string{"bash", "-lc", loopFixScript}, RunOptions{Timeout: 30 * time.Second}); err != nil {
		return err
	}
	if err := o.assertLoopDevices(); err != nil {
		return err
	}
	o.emitter.Stage("check", 45, "Loop devices are ready")
	return nil
}

func (o *Orchestrator) FixF2fs(ctx context.Context) error {
	o.emitter.Stage("check", 35, "Enabling f2fs kernel module")
	if err := o.requireSudoForFix(ctx, "f2fs", "Enable f2fs module"); err != nil {
		return err
	}
	if _, err := Run(ctx, "sudo", []string{"modprobe", "f2fs"}, RunOptions{Timeout: 20 * time.Second}); err != nil {
		return err
	}
	if err := o.assertF2fs(); err != nil {
		return err
	}
	o.emitter.Stage("check", 45, "f2fs support is ready")
	return nil
}

func (o *Orchestrator) FixFuse(ctx context.Context) error {
	o.emitter.Stage("check", 35, "Enabling FUSE support")
	if err := o.requireSudoForFix(ctx, "fuse", "Enable FUSE support"); err != nil {
		return err
	}
	_, _ = Run(ctx, "sudo", []string{"modprobe", "fuse"}, RunOptions{Timeout: 20 * time.Second})
	if !hasDeviceNode("/dev/fuse") {
		_, _ = Run(ctx, "sudo", []string{"mknod", "-m", "666", "/dev/fuse", "c", "10", "229"}, RunOptions{Timeout: 10 * time.Second})
	}
	if err := o.assertFuse(); err != nil {
		return err
	}
	o.emitter.Stage("check", 45, "FUSE support is ready")
	return nil
}

// fixHintsFromText recognises a failure that one of the host fixes can repair,
// so a mount error deep inside a build surfaces as an actionable button
func fixHintsFromText(text string) (kind string, label string) {
	s := strings.ToLower(text)
	if s == "" {
		return "", ""
	}
	switch {
	case strings.Contains(s, "failed to setup loop device"),
		strings.Contains(s, "loop device"),
		strings.Contains(s, "/dev/loop"),
		strings.Contains(s, "losetup"):
		return "loop", "Fix loop devices"
	case strings.Contains(s, "unknown filesystem type 'f2fs'"),
		strings.Contains(s, `unknown filesystem type "f2fs"`),
		strings.Contains(s, " f2fs"):
		return "f2fs", "Enable f2fs module"
	case strings.Contains(s, "fuse.erofs"),
		strings.Contains(s, "/dev/fuse"),
		strings.Contains(s, "fuse: device not found"),
		strings.Contains(s, "try 'modprobe fuse' first"),
		strings.Contains(s, "unknown filesystem type 'fuse'"),
		strings.Contains(s, `unknown filesystem type "fuse"`):
		return "fuse", "Enable FUSE support"
	}
	return "", ""
}
