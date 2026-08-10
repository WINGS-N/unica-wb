import re

_HINTS = [
    (
        "loop-device",
        re.compile(r"failed to setup loop device|loop device", re.IGNORECASE),
        "Loop device not available",
        "Build container cannot mount system.img via loop device",
        "Run with privileged/rootful docker or enable loop devices in container runtime",
    ),
    (
        "submodule-shallow-sha",
        re.compile(
            r"did not contain [0-9a-f]{40}|Direct fetching of that commit failed|expected 'acknowledgments'",
            re.IGNORECASE,
        ),
        "Submodule pin is outside the shallow clone",
        "The nested module is marked shallow, so only the branch tip is fetched, and the "
        "pinned commit is not in it. Serving an arbitrary commit is off by default, so the "
        "fallback request is refused",
        "Update submodules without the shallow hint: git submodule update --init --recursive --no-recommend-shallow",
    ),
    (
        "git-identity",
        re.compile(r"Committer identity unknown|unable to auto-detect email address", re.IGNORECASE),
        "Git identity is not configured",
        "Git requires user.name and user.email to apply patches",
        "Set git config user.name and user.email inside the build environment",
    ),
    (
        "pkg-config-missing",
        re.compile(r"Could NOT find PkgConfig|PKG_CONFIG_EXECUTABLE", re.IGNORECASE),
        "pkg-config is missing",
        "Build needs pkg-config but it is not installed",
        "Install pkg-config (pkgconf) in the build image",
    ),
    (
        "fmt-missing",
        re.compile(r"fmtConfig\.cmake|fmt-config\.cmake", re.IGNORECASE),
        "fmt library is missing",
        "CMake cannot find fmt package",
        "Install libfmt-dev (or use bundled fmt) in the build image",
    ),
    (
        "patch-failed",
        re.compile(r"patch does not apply|patch failed", re.IGNORECASE),
        "Patch does not apply",
        "Source files differ from expected base",
        "Update sources to matching version or adjust the patch",
    ),
    (
        "samloader-400",
        re.compile(r"DownloadBinaryInform returned 400", re.IGNORECASE),
        "Firmware version not found",
        "Samsung firmware server rejected requested version",
        "Double-check model/CSC/firmware version or remove override",
    ),
]


def detect_build_hints(log_text: str) -> list[dict[str, str]]:
    hints = []
    for hint_id, pattern, title, detail, suggestion in _HINTS:
        if pattern.search(log_text):
            hints.append(
                {
                    "id": hint_id,
                    "title": title,
                    "detail": detail,
                    "suggestion": suggestion,
                }
            )
    return hints
