package orch

import (
	"context"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// SeedImage is one entry of the seed manifest shipped next to the binary
type SeedImage struct {
	Archive      string `json:"archive"`
	LocalTag     string `json:"local_tag"`
	Remote       string `json:"remote"`
	RemoteLatest string `json:"remote_latest"`
	ImageID      string `json:"image_id"`
}

type seedManifest struct {
	Images []SeedImage `json:"images"`
}

// loadManifest reads the seed manifest, falling back to a list built from the
// configured image tags so a package without seeds can still check the registry
func (o *Orchestrator) loadManifest() []SeedImage {
	candidates := []string{
		filepath.Join(o.cfg.SeedDir, "manifest.json"),
		filepath.Join(o.cfg.SeedDir, "manifest.example.json"),
	}
	for _, path := range candidates {
		data, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		var manifest seedManifest
		if err := json.Unmarshal(data, &manifest); err != nil {
			continue
		}
		if len(manifest.Images) > 0 {
			return manifest.Images
		}
	}
	return o.defaultManifestImages()
}

func (o *Orchestrator) defaultManifestImages() []SeedImage {
	owner := o.cfg.GHCROwner
	build := func(localTag, name string) SeedImage {
		remote := fmt.Sprintf("ghcr.io/%s/%s:latest", owner, name)
		return SeedImage{LocalTag: localTag, Remote: remote, RemoteLatest: remote}
	}
	wanted := []struct{ tag, name string }{
		{o.cfg.ImageAPI, "unica-wb-api"},
		{o.cfg.ImageWorker, "unica-wb-worker"},
	}
	if !o.cfg.EmbeddedUI {
		wanted = append(wanted, struct{ tag, name string }{o.cfg.ImageFrontend, "unica-wb-frontend"})
	}
	out := []SeedImage{}
	for _, item := range wanted {
		if strings.TrimSpace(item.tag) == "" {
			continue
		}
		out = append(out, build(strings.TrimSpace(item.tag), item.name))
	}
	return out
}

func (o *Orchestrator) imageExists(ctx context.Context, tag string) bool {
	_, err := o.docker.Run(ctx, []string{"image", "inspect", tag}, RunOptions{Timeout: 20 * time.Second})
	return err == nil
}

func (o *Orchestrator) imageID(ctx context.Context, tag string) string {
	res, err := o.docker.Run(ctx, []string{"image", "inspect", "--format", "{{.Id}}", tag},
		RunOptions{Timeout: 20 * time.Second})
	if err != nil {
		return ""
	}
	return strings.TrimSpace(res.Stdout)
}

func repoFromImageRef(ref string) string {
	input := strings.TrimSpace(ref)
	if input == "" {
		return ""
	}
	noDigest := strings.SplitN(input, "@", 2)[0]
	slash := strings.LastIndex(noDigest, "/")
	colon := strings.LastIndex(noDigest, ":")
	if colon > slash {
		return noDigest[:colon]
	}
	return noDigest
}

func (o *Orchestrator) pullRemoteRef(item SeedImage) string {
	defaultRemote := strings.TrimSpace(item.Remote)
	remoteLatest := strings.TrimSpace(item.RemoteLatest)
	pullTag := strings.TrimSpace(o.cfg.PullTag)

	if pullTag == "" {
		if defaultRemote != "" {
			return defaultRemote
		}
		return remoteLatest
	}
	if pullTag == "latest" && remoteLatest != "" {
		return remoteLatest
	}
	base := defaultRemote
	if base == "" {
		base = remoteLatest
	}
	repo := repoFromImageRef(base)
	if repo == "" {
		return base
	}
	return repo + ":" + pullTag
}

func (o *Orchestrator) localRepoDigest(ctx context.Context, ref, repoHint string) string {
	res, err := o.docker.Run(ctx, []string{"image", "inspect", "--format", "{{json .RepoDigests}}", ref},
		RunOptions{Timeout: 20 * time.Second})
	if err != nil {
		return ""
	}
	var digests []string
	if err := json.Unmarshal([]byte(strings.TrimSpace(res.Stdout)), &digests); err != nil {
		return ""
	}
	repo := repoHint
	if repo == "" {
		repo = repoFromImageRef(ref)
	}
	for _, item := range digests {
		if repo != "" && !strings.HasPrefix(item, repo+"@sha256:") {
			continue
		}
		if idx := strings.Index(item, "@"); idx >= 0 {
			return item[idx+1:]
		}
	}
	return ""
}

type manifestDescriptor struct {
	Digest   string `json:"digest"`
	Platform struct {
		OS           string `json:"os"`
		Architecture string `json:"architecture"`
	} `json:"platform"`
}

type manifestEntry struct {
	Descriptor manifestDescriptor `json:"Descriptor"`
	Digest     string             `json:"digest"`
}

func pickDigest(entries []manifestEntry) string {
	if len(entries) == 0 {
		return ""
	}
	for _, entry := range entries {
		if strings.EqualFold(entry.Descriptor.Platform.OS, "linux") &&
			strings.EqualFold(entry.Descriptor.Platform.Architecture, "amd64") {
			if entry.Descriptor.Digest != "" {
				return entry.Descriptor.Digest
			}
		}
	}
	if entries[0].Descriptor.Digest != "" {
		return entries[0].Descriptor.Digest
	}
	return entries[0].Digest
}

func (o *Orchestrator) remoteDigest(ctx context.Context, remoteRef string) string {
	res, err := o.docker.Run(ctx, []string{"manifest", "inspect", "--verbose", remoteRef},
		RunOptions{Timeout: 30 * time.Second})
	if err != nil {
		return ""
	}
	raw := strings.TrimSpace(res.Stdout)
	if raw == "" {
		return ""
	}
	var list []manifestEntry
	if err := json.Unmarshal([]byte(raw), &list); err == nil {
		return pickDigest(list)
	}
	var single manifestEntry
	if err := json.Unmarshal([]byte(raw), &single); err == nil && single.Descriptor.Digest != "" {
		return single.Descriptor.Digest
	}
	var wrapper struct {
		Manifests []manifestEntry `json:"manifests"`
	}
	if err := json.Unmarshal([]byte(raw), &wrapper); err == nil {
		return pickDigest(wrapper.Manifests)
	}
	return ""
}

// ensureSeedImages loads any bundled image archive that is not in the local
// docker store yet
func (o *Orchestrator) ensureSeedImages(ctx context.Context, images []SeedImage) error {
	o.emitter.Stage("seed", 0, "Checking embedded seed images")
	if len(images) == 0 {
		o.emitter.Stage("seed", 100, "No seed images to load")
		return nil
	}
	for i, item := range images {
		progress := int(math.Round(float64(i+1) / float64(len(images)) * 100))
		if item.LocalTag == "" {
			continue
		}
		o.emitter.Stage("seed", progress, "Checking seed image "+item.LocalTag)
		if o.imageExists(ctx, item.LocalTag) {
			continue
		}
		if item.Archive == "" {
			continue
		}
		archive := filepath.Join(o.cfg.SeedDir, item.Archive)
		if _, err := os.Stat(archive); err != nil {
			o.emitter.Stage("seed", progress, "Seed archive missing for "+item.LocalTag+", skip")
			continue
		}
		o.emitter.Stage("seed", progress, "Loading seed image "+item.LocalTag)
		_, err := o.docker.Run(ctx, []string{"load", "-i", archive}, RunOptions{
			OnStdout: func(line string) { o.emitter.Stage("seed", progress, line) },
		})
		if err != nil {
			return err
		}
	}
	o.emitter.Stage("seed", 100, "Seed images are ready")
	return nil
}

var pullLayerRe = regexp.MustCompile(
	`(?i)^([a-f0-9]{6,12}):\s+Downloading\s+\[.*?\]\s+([\d.]+)([KMGTP]?i?B)/([\d.]+)([KMGTP]?i?B)`)

func toBytes(value, unit string) int64 {
	n, err := strconv.ParseFloat(value, 64)
	if err != nil {
		return 0
	}
	scale := map[string]float64{
		"B": 1, "KB": 1024, "MB": 1 << 20, "GB": 1 << 30, "TB": 1 << 40,
	}
	key := strings.ToUpper(strings.ReplaceAll(unit, "IB", "B"))
	mul, ok := scale[key]
	if !ok {
		mul = 1
	}
	return int64(n * mul)
}

type layerState struct{ current, total int64 }

// pullAndRetag pulls one image, turning docker's per-layer chatter into a
// single aggregated byte counter with a speed readout
func (o *Orchestrator) pullAndRetag(ctx context.Context, item SeedImage, index, total int, remoteRef string) error {
	pullRef := strings.TrimSpace(remoteRef)
	if pullRef == "" || item.LocalTag == "" {
		return nil
	}

	layers := map[string]layerState{}
	lastBytes := int64(0)
	lastAt := time.Now()
	progress := int(math.Round(float64(index+1) / float64(total) * 100))

	publish := func(line string) {
		match := pullLayerRe.FindStringSubmatch(line)
		if match == nil {
			if line != "" {
				o.emitter.Emit(Progress{
					Stage:         "pull",
					Progress:      progress,
					TotalProgress: stageTotal("pull", progress),
					Message:       line,
				})
			}
			return
		}
		layers[match[1]] = layerState{current: toBytes(match[2], match[3]), total: toBytes(match[4], match[5])}

		var downloaded, size int64
		for _, entry := range layers {
			if entry.total > 0 && entry.current > entry.total {
				downloaded += entry.total
			} else {
				downloaded += entry.current
			}
			if entry.total > 0 {
				size += entry.total
			} else {
				size += entry.current
			}
		}
		now := time.Now()
		elapsed := now.Sub(lastAt).Seconds()
		if elapsed < 0.2 {
			elapsed = 0.2
		}
		speed := float64(downloaded-lastBytes) / elapsed
		if speed < 0 {
			speed = 0
		}
		lastAt = now
		lastBytes = downloaded

		o.emitter.Emit(Progress{
			Stage:         "pull",
			Progress:      progress,
			TotalProgress: stageTotal("pull", progress),
			Message:       "Pulling " + pullRef,
			Downloaded:    downloaded,
			Total:         size,
			Speed:         speed,
		})
	}

	if _, err := o.docker.Run(ctx, []string{"pull", pullRef}, RunOptions{
		OnStdout: publish,
		OnStderr: publish,
	}); err != nil {
		return err
	}

	if pullRef != item.LocalTag {
		if _, err := o.docker.Run(ctx, []string{"tag", pullRef, item.LocalTag}, RunOptions{Timeout: 20 * time.Second}); err != nil {
			return err
		}
	}
	return nil
}

func stageTotal(stage string, progress int) int {
	r, ok := stageRange[stage]
	if !ok {
		r = [2]int{0, 100}
	}
	p := clampInt(progress, 0, 100)
	return clampInt(r[0]+int(math.Round(float64(r[1]-r[0])*float64(p)/100.0)), 0, 100)
}

// updateImages pulls newer images, but only when the local copy really differs
// from the registry, so a normal start does not re-download gigabytes
func (o *Orchestrator) updateImages(ctx context.Context, images []SeedImage) error {
	if !o.cfg.PullOnStart {
		return nil
	}
	if len(images) == 0 {
		o.emitter.Stage("pull", 100, "No docker images to pull")
		return nil
	}

	hasSeedMatch := false
	for _, item := range images {
		if item.Archive != "" && item.ImageID != "" {
			hasSeedMatch = true
			break
		}
	}

	failed := 0
	o.emitter.Stage("pull", 0, "Checking updates for Docker images")
	for i, item := range images {
		localTag := item.LocalTag
		if localTag == "" {
			localTag = "local image"
		}
		done := int(math.Round(float64(i+1) / float64(len(images)) * 100))
		remoteRef := o.pullRemoteRef(item)

		if item.LocalTag != "" && item.ImageID != "" && hasSeedMatch {
			if id := o.imageID(ctx, item.LocalTag); id != "" && id == item.ImageID {
				o.emitter.Stage("pull", done, "Image "+localTag+" already matches embedded seed, skip pull")
				continue
			}
		}

		if remoteRef != "" {
			repo := repoFromImageRef(remoteRef)
			remote := o.remoteDigest(ctx, remoteRef)
			if remote == "" && !o.cfg.PullIfUnknown {
				o.emitter.Stage("pull", done, "Remote digest unavailable for "+localTag+", skip pull")
				continue
			}
			if remote != "" {
				local := o.localRepoDigest(ctx, remoteRef, repo)
				if local == "" {
					local = o.localRepoDigest(ctx, item.LocalTag, repo)
				}
				if local != "" && local == remote {
					o.emitter.Stage("pull", done, "Image "+localTag+" already matches remote digest, skip pull")
					continue
				}
			}
		}

		target := remoteRef
		if target == "" {
			target = item.LocalTag
		}
		o.emitter.Stage("pull", int(math.Round(float64(i)/float64(len(images))*100)), "Pulling docker image "+target)

		if err := o.pullAndRetag(ctx, item, i, len(images), remoteRef); err != nil {
			failed++
			o.emitter.Stage("pull", done, "Pull failed, using local/seed image for "+localTag+" ("+err.Error()+")")
			if o.cfg.PullStrict {
				return err
			}
		}
	}

	if failed > 0 {
		o.emitter.Stage("pull", 100, fmt.Sprintf("Pull finished with %d warning(s), continuing with local images", failed))
	} else {
		o.emitter.Stage("pull", 100, "Docker images are up to date")
	}
	return nil
}

func isProjectImageRef(ref string) bool {
	s := strings.ToLower(ref)
	if s == "" || strings.Contains(s, "<none>") {
		return false
	}
	return strings.Contains(s, "/unica-wb-") || strings.HasPrefix(s, "unica-wb-")
}

// cleanupImages removes superseded project images so repeated updates do not
// fill the disk with orphaned layers
func (o *Orchestrator) cleanupImages(ctx context.Context, images []SeedImage) {
	if !o.cfg.CleanupImages {
		return
	}
	keep := map[string]bool{}
	refs := []string{o.cfg.ImageAPI, o.cfg.ImageWorker}
	if !o.cfg.EmbeddedUI {
		refs = append(refs, o.cfg.ImageFrontend)
	}
	for _, ref := range refs {
		if ref = strings.TrimSpace(ref); ref != "" {
			keep[ref] = true
		}
	}
	for _, item := range images {
		for _, ref := range []string{item.LocalTag, item.Remote, item.RemoteLatest, o.pullRemoteRef(item)} {
			if ref = strings.TrimSpace(ref); ref != "" {
				keep[ref] = true
			}
		}
	}

	res, err := o.docker.Run(ctx, []string{"image", "ls", "--format", "{{.Repository}}:{{.Tag}}"},
		RunOptions{Timeout: 15 * time.Second})
	if err != nil {
		return
	}
	candidates := []string{}
	for _, line := range strings.Split(res.Stdout, "\n") {
		ref := strings.TrimSpace(line)
		if isProjectImageRef(ref) && !keep[ref] {
			candidates = append(candidates, ref)
		}
	}
	if len(candidates) == 0 {
		o.emitter.Stage("health", 99, "Docker image cleanup: nothing to remove")
		return
	}

	o.emitter.Stage("health", 98, fmt.Sprintf("Cleaning unused docker images (%d)", len(candidates)))
	for _, ref := range candidates {
		o.emitter.Stage("health", 99, "Removing image "+ref)
		_, _ = o.docker.Run(ctx, []string{"image", "rm", ref}, RunOptions{Timeout: 15 * time.Second})
	}
	_, _ = o.docker.Run(ctx, []string{"image", "prune", "-f"}, RunOptions{Timeout: 15 * time.Second})
	o.emitter.Stage("health", 99, "Docker image cleanup complete")
}
