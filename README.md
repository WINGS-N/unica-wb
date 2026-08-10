# UN1CA Builder

Interface for building [UN1CA](https://github.com/salvogiangri/UN1CA) custom firmware for Samsung Galaxy devices.
Pick a device, a source and a target firmware, press build, watch it run

## Requirements

- A Linux host with `loop` devices, `FUSE` and the `f2fs` kernel module. The builder checks all three on startup and
  offers to enable whatever is missing
- Docker with Compose, running rootful: the build container is privileged. The launcher asks for the password and
  escalates on its own when the local daemon is rootless
- amd64
- Around 100 GB of free disk per device you build for

## Install

Grab a package from the [releases](https://github.com/WINGS-N/unica-wb/releases): `.deb`,
`.AppImage`, a tarball or a bare binary

```
sudo dpkg -i unica-wb_*_linux_amd64.deb
unica-wb
```

The launcher starts the whole stack in Docker and opens the interface in its own window, so nothing has to be typed in
a terminal. It carries the interface inside the binary and pulls the rest of the images itself

The first start clones the firmware sources and downloads the Samsung firmware, which takes a while

See [desktop/README.md](desktop/README.md) for how it is built and configured

## Run on a server

Without a desktop, run the same stack directly and open the interface in a browser

```
git clone https://github.com/WINGS-N/unica-wb.git
cd unica-wb
docker compose up -d
```

The interface is on port 8080, the API on 8000

## What it does

- **Builds** a ROM from a source and a target firmware, with live stage progress and a full log
- **Workspaces** - several checkouts side by side, each with its own repository, targets and settings, optionally
  sharing one firmware cache
- **Mods** - turn any mod off for a single build, or upload an archive of extra mods and pick which of them apply
- **Debloat and floating features** - edit the lists and the feature flags per build
- **Queue** - jobs run one at a time, can be stopped, and keep their logs and artifacts

## Interface

Works as a PWA: installable, and sends a push notification when a build finishes. English and Russian

## Configuration

The launcher reads `UNICA_WB_*` environment variables, listed in [desktop/README.md](desktop/README.md). It has no
`.env` of its own

The stack reads a `.env` next to `docker-compose.yml`, which the launcher passes through when there is one

| Variable | Meaning |
| --- | --- |
| `GIT_URL` | Firmware repository to clone |
| `GIT_REF` | Branch or tag to check out |
| `LOCAL_UN1CA_PATH` | Build from a local checkout instead, with `docker-compose.local-repo.yml` |

Set a password in Settings to close the interface off, and add a git token there if the repository is private

## License

GPL-3.0-or-later
