from __future__ import annotations

import hashlib
import json
from pathlib import Path, PureWindowsPath
from typing import Any

from fpga_dse.models import ProjectConfig


class FingerprintError(RuntimeError):
    """Raised when reproducibility inputs cannot be fingerprinted safely."""


def compute_study_fingerprint(config: ProjectConfig) -> str:
    """Return a stable digest for every input that can change execution results."""
    files = fingerprinted_files(config)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "configuration_version": config.version,
        "execution": {
            "adapter": config.execution.adapter,
            "timeout_seconds": config.execution.timeout_seconds,
            "command": (
                list(config.execution.command)
                if isinstance(config.execution.command, tuple)
                else config.execution.command
            ),
            "shell": config.execution.shell,
            "result_file": config.execution.result_file,
            "working_directory": config.execution.working_directory,
            "environment": dict(sorted(config.execution.environment.items())),
            "mock_metrics": dict(sorted(config.execution.mock_metrics.items())),
        },
        "files": [
            {
                "path": path.relative_to(config.project_root).as_posix(),
                "sha256": _sha256_file(path),
            }
            for path in files
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def fingerprinted_files(config: ProjectConfig) -> tuple[Path, ...]:
    """Resolve configured source paths and globs into a deterministic file list."""
    project_root = config.project_root.resolve()
    workspace = config.workspace.resolve()
    selected: dict[str, Path] = {}

    for pattern in config.execution.fingerprint_files:
        _validate_pattern(pattern)
        matches = sorted(project_root.glob(pattern))
        if not matches:
            raise FingerprintError(f"fingerprint input did not match any path: {pattern}")

        pattern_files: list[Path] = []
        for match in matches:
            if match.is_dir():
                pattern_files.extend(path for path in match.rglob("*") if path.is_file())
            elif match.is_file():
                pattern_files.append(match)

        accepted = 0
        for path in sorted(pattern_files):
            resolved = path.resolve()
            if not resolved.is_relative_to(project_root):
                raise FingerprintError(f"fingerprint input escapes the project root: {pattern}")
            relative = resolved.relative_to(project_root)
            if ".git" in relative.parts or resolved.is_relative_to(workspace):
                continue
            selected[relative.as_posix()] = resolved
            accepted += 1

        if accepted == 0:
            raise FingerprintError(
                f"fingerprint input matched no usable files after excluding .git and the workspace: {pattern}"
            )

    return tuple(selected[key] for key in sorted(selected))


def _validate_pattern(pattern: str) -> None:
    native = Path(pattern)
    windows = PureWindowsPath(pattern)
    if native.is_absolute() or windows.is_absolute() or ".." in native.parts or ".." in windows.parts:
        raise FingerprintError(
            f"fingerprint input must be a project-relative path or glob without '..': {pattern}"
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise FingerprintError(f"cannot hash fingerprint input {path}: {exc}") from exc
    return digest.hexdigest()
