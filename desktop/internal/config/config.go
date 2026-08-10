package config

import (
	"os"
	"path/filepath"
	"strings"
	"time"
)

// Config is the whole runtime configuration of the launcher. Every field can be
// overridden from the environment so the packaged app and a dev run behave the
// same way
type Config struct {
	EmbeddedUI   bool
	FrontendURL  string
	APIURL       string
	APIHealthURL string

	ComposeProject   string
	ComposeServices  []string
	ComposeLocalRepo bool

	RequireRootfulDocker bool
	PrivMode             string
	DockerContext        string
	DockerHost           string

	PullOnStart   bool
	PullStrict    bool
	PullIfUnknown bool
	PullTag       string
	CleanupImages bool

	ComposeDownOnQuit  bool
	ComposeDownTimeout time.Duration
	ForceKillTimeout   time.Duration

	GHCROwner      string
	ImageAPI       string
	ImageWorker    string
	ImageFrontend  string
	PassthroughEnv []string

	// RootDir holds docker-compose.yml; SeedDir holds the seed image archives
	RootDir    string
	SeedDir    string
	RuntimeDir string

	Language string
}

func env(key, fallback string) string {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		return v
	}
	return fallback
}

func envBool(key string, fallback bool) bool {
	v := strings.TrimSpace(os.Getenv(key))
	switch v {
	case "":
		return fallback
	case "0", "false", "no", "off":
		return false
	default:
		return true
	}
}

func envDuration(key string, fallback time.Duration) time.Duration {
	v := strings.TrimSpace(os.Getenv(key))
	if v == "" {
		return fallback
	}
	if d, err := time.ParseDuration(v); err == nil {
		return d
	}
	return fallback
}

// resolveRootDir finds the directory that ships docker-compose.yml: an explicit
// override, then the install prefix next to the binary, then the repo checkout
// when running from source
func resolveRootDir() string {
	if v := strings.TrimSpace(os.Getenv("UNICA_WB_ROOT")); v != "" {
		return v
	}
	candidates := []string{}
	if exe, err := os.Executable(); err == nil {
		exe, _ = filepath.EvalSymlinks(exe)
		dir := filepath.Dir(exe)
		candidates = append(candidates,
			dir,
			filepath.Join(dir, "..", "share", "unica-wb"),
			filepath.Join(dir, "..", "..", "share", "unica-wb"),
			filepath.Join(dir, "..", ".."),
			filepath.Join(dir, "..", "..", ".."),
		)
	}
	if wd, err := os.Getwd(); err == nil {
		candidates = append(candidates, wd, filepath.Join(wd, ".."))
	}
	candidates = append(candidates, "/usr/share/unica-wb", "/usr/local/share/unica-wb")
	for _, c := range candidates {
		abs, err := filepath.Abs(c)
		if err != nil {
			continue
		}
		if _, err := os.Stat(filepath.Join(abs, "docker-compose.yml")); err == nil {
			return abs
		}
	}
	if wd, err := os.Getwd(); err == nil {
		return wd
	}
	return "."
}

func userRuntimeDir() string {
	base, err := os.UserConfigDir()
	if err != nil || base == "" {
		base = os.TempDir()
	}
	return filepath.Join(base, "unica-wb", "runtime-compose")
}

func systemLanguage() string {
	for _, key := range []string{"UNICA_WB_LANG", "LC_ALL", "LC_MESSAGES", "LANG"} {
		if v := strings.ToLower(strings.TrimSpace(os.Getenv(key))); v != "" {
			if strings.HasPrefix(v, "ru") {
				return "ru"
			}
			if key == "UNICA_WB_LANG" {
				return "en"
			}
		}
	}
	return "en"
}

func Load() Config {
	root := resolveRootDir()
	seedDir := env("UNICA_WB_SEED_DIR", filepath.Join(root, "seed-images"))

	embedded := envBool("UNICA_WB_EMBEDDED_UI", true)
	// The frontend container only has to run when the interface is not served
	// from the binary itself
	services := "redis api worker"
	if !embedded {
		services += " frontend"
	}

	cfg := Config{
		EmbeddedUI:   embedded,
		FrontendURL:  env("UNICA_WB_FRONTEND_URL", "http://127.0.0.1:8080"),
		APIURL:       env("UNICA_WB_API_URL", "http://127.0.0.1:8000"),
		APIHealthURL: env("UNICA_WB_API_HEALTH_URL", "http://127.0.0.1:8000/api/v1/healthz"),

		ComposeProject:   env("UNICA_WB_COMPOSE_PROJECT", "unica-wb"),
		ComposeServices:  strings.Fields(env("UNICA_WB_COMPOSE_SERVICES", services)),
		ComposeLocalRepo: envBool("UNICA_WB_COMPOSE_LOCAL_REPO", false),

		RequireRootfulDocker: envBool("UNICA_WB_REQUIRE_ROOTFUL_DOCKER", true),
		PrivMode:             strings.ToLower(env("UNICA_WB_PRIV_MODE", "session")),
		DockerContext:        env("UNICA_WB_DOCKER_CONTEXT", ""),
		DockerHost:           env("UNICA_WB_DOCKER_HOST", ""),

		PullOnStart:   envBool("UNICA_WB_PULL_ON_START", true),
		PullStrict:    envBool("UNICA_WB_PULL_STRICT", false),
		PullIfUnknown: envBool("UNICA_WB_PULL_IF_UNKNOWN", true),
		PullTag:       env("UNICA_WB_PULL_TAG", "latest"),
		CleanupImages: envBool("UNICA_WB_CLEANUP_IMAGES_ON_START", true),

		ComposeDownOnQuit:  envBool("UNICA_WB_COMPOSE_DOWN_ON_QUIT", true),
		ComposeDownTimeout: envDuration("UNICA_WB_COMPOSE_DOWN_TIMEOUT", 120*time.Second),
		ForceKillTimeout:   envDuration("UNICA_WB_SHUTDOWN_FORCE_KILL_TIMEOUT", 30*time.Second),

		GHCROwner:     strings.ToLower(env("GHCR_OWNER", "wings-n")),
		ImageAPI:      env("IMAGE_API", "unica-wb-api:local"),
		ImageWorker:   env("IMAGE_WORKER", "unica-wb-worker:local"),
		ImageFrontend: env("IMAGE_FRONTEND", "unica-wb-frontend:local"),
		PassthroughEnv: []string{
			"LOCAL_UN1CA_PATH", "GIT_URL", "GIT_REF",
			"GHCR_OWNER", "IMAGE_API", "IMAGE_WORKER", "IMAGE_FRONTEND",
		},

		RootDir:    root,
		SeedDir:    seedDir,
		RuntimeDir: env("UNICA_WB_RUNTIME_DIR", userRuntimeDir()),

		Language: systemLanguage(),
	}
	return cfg
}

// ComposeFiles lists the compose files in the order they must be passed to
// docker compose
func (c Config) ComposeFiles() []string {
	files := []string{filepath.Join(c.RootDir, "docker-compose.yml")}
	if c.ComposeLocalRepo {
		files = append(files, filepath.Join(c.RootDir, "docker-compose.local-repo.yml"))
	}
	return files
}
