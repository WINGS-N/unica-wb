# Desktop launcher

Wails v3 launcher that brings the build stack up in Docker and then opens the
build interface in a native window.

The interface is compiled into the binary. The launcher serves it from its own
loopback endpoint and forwards `/api` to the API container, so a packaged desktop
app needs neither the `frontend` container nor its image. It is the very same
build the browser gets from `docker compose up`, and setting
`UNICA_WB_EMBEDDED_UI=0` switches back to pointing the window at the container.

## What it does

1. Checks Docker access, escalating to a rootful daemon when the local one is
   rootless (the worker container is privileged)
2. Checks the host for loop devices, FUSE and the f2fs module, and offers a
   one-click fix for each
3. Loads bundled seed images, then pulls newer ones only when the registry digest
   differs from the local copy
4. Starts the compose project and waits for API and worker health
5. Opens the interface, and on exit stops the stack with a force-kill fallback

## Build

```
task webui              # build the interface into internal/webui/dist
task build              # bin/unica-wb, carrying whatever is staged
task build:full         # both of the above
task package            # every artifact below, plus checksums
task test
```

`task package` writes into `dist/`:

| Artifact | What it is |
| --- | --- |
| `unica-wb_<version>_linux_<arch>.deb` | Debian package with compose files and seed images |
| `unica-wb_<version>_linux_<arch>.AppImage` | Single-file app carrying the same payload |
| `unica-wb_<version>_linux_<arch>.tar.gz` | Portable directory with the binary and compose files |
| `unica-wb_<version>_linux_<arch>` | The bare binary, interface included |
| `checksums_linux_<arch>.txt` | SHA-512/256 of everything above |

Build dependencies: Go 1.25, `pnpm`, `gcc`, `pkg-config`, GTK4 and WebKitGTK 6
development headers (`libgtk-4-dev`, `libwebkitgtk-6.0-dev` on Debian/Ubuntu),
plus `nfpm`, `appimagetool`, `openssl` and `task`.

Runtime dependencies are the same GTK4 and WebKitGTK libraries, which the AppImage
expects from the host rather than bundling.

## Where the compose files come from

The launcher looks for `docker-compose.yml` in `UNICA_WB_ROOT`, then next to the
binary, then in `../share/unica-wb`, then in the repo checkout. The package
installs them into `/usr/share/unica-wb`. They are copied into a writable runtime
directory before use, together with an `.env` merged from the repo `.env` and the
passthrough variables of the current run.

## Environment

| Variable | Default | Meaning |
| --- | --- | --- |
| `UNICA_WB_ROOT` | auto | Directory holding the compose files |
| `UNICA_WB_EMBEDDED_UI` | `1` | Serve the built-in interface instead of the container |
| `UNICA_WB_API_URL` | `http://127.0.0.1:8000` | Backend the embedded interface is proxied to |
| `UNICA_WB_FRONTEND_URL` | `http://127.0.0.1:8080` | Where the main window points when not embedded |
| `UNICA_WB_API_HEALTH_URL` | `http://127.0.0.1:8000/api/v1/healthz` | Health endpoint to wait for |
| `UNICA_WB_COMPOSE_PROJECT` | `unica-wb` | Compose project name |
| `UNICA_WB_COMPOSE_SERVICES` | `redis api worker` | Services to start, plus `frontend` when not embedded |
| `UNICA_WB_COMPOSE_LOCAL_REPO` | `0` | Also use `docker-compose.local-repo.yml` |
| `UNICA_WB_REQUIRE_ROOTFUL_DOCKER` | `1` | Reject or escalate a rootless daemon |
| `UNICA_WB_PRIV_MODE` | `session` | `session`, `sudo`, `pkexec` or `auto` |
| `UNICA_WB_DOCKER_CONTEXT` | `default` | Docker context to use |
| `UNICA_WB_DOCKER_HOST` | empty | Explicit daemon endpoint |
| `UNICA_WB_PULL_ON_START` | `1` | Check the registry for newer images |
| `UNICA_WB_PULL_STRICT` | `0` | Fail startup when a pull fails |
| `UNICA_WB_PULL_IF_UNKNOWN` | `1` | Pull when the remote digest cannot be read |
| `UNICA_WB_PULL_TAG` | `latest` | Tag to pull |
| `UNICA_WB_CLEANUP_IMAGES_ON_START` | `1` | Remove superseded project images |
| `UNICA_WB_COMPOSE_DOWN_ON_QUIT` | `1` | Stop the stack on exit |
| `UNICA_WB_COMPOSE_DOWN_TIMEOUT` | `120s` | Graceful stop budget |
| `UNICA_WB_SHUTDOWN_FORCE_KILL_TIMEOUT` | `30s` | When to start killing containers |
| `UNICA_WB_SEED_DIR` | `<root>/seed-images` | Seed archives and manifest |
| `UNICA_WB_RUNTIME_DIR` | user config dir | Where runtime compose files are written |
| `UNICA_WB_LANG` | system locale | Language of the exit dialog |

## Local bridge

The launcher serves a loopback HTTP endpoint on a random port:

- `GET /` - the embedded interface, with every unknown path falling back to it
- `GET /splash/` - the startup screen
- `ANY /api/...` - proxied to the API container, websockets included
- `GET /events` - progress, errors and password prompts over SSE
- `GET /state` - last progress plus the log tail
- `POST /action/retry`, `/action/fix?kind=loop|f2fs|fuse`, `/action/sudo`
- `POST /bridge/language` - what `window.desktopApi` in the web UI calls, so the
  exit dialog follows the language picked in the app

The bridge is a plain HTTP endpoint with CORS because the main window can also
run on the frontend container's origin when the embedded interface is turned off.
