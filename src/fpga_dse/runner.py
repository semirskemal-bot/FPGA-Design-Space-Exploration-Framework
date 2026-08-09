from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined, TemplateError

from fpga_dse.expressions import ExpressionError, evaluate_expression
from fpga_dse.fingerprint import compute_study_fingerprint
from fpga_dse.models import DesignCandidate, MetricValue, ProjectConfig, RunRecord, Scalar
from fpga_dse.workspace import Workspace


class ExecutionError(RuntimeError):
    """Raised when an experiment cannot be prepared or interpreted."""


ProgressCallback = Callable[[RunRecord, int, int], None]


def run_study(
    config: ProjectConfig,
    candidates: Sequence[DesignCandidate],
    workspace: Workspace,
    *,
    jobs: int | None = None,
    resume: bool = True,
    progress: ProgressCallback | None = None,
) -> list[RunRecord]:
    study_fingerprint = compute_study_fingerprint(config)
    workspace.initialize(
        project=config.name,
        config_path=config.config_path,
        study_fingerprint=study_fingerprint,
    )
    worker_count = jobs or config.execution.jobs
    if worker_count <= 0:
        raise ExecutionError("jobs must be positive")

    completed: list[RunRecord] = []
    pending: list[DesignCandidate] = []
    total = len(candidates)

    for candidate in candidates:
        existing = workspace.read_record(candidate.design_id) if resume else None
        if (
            existing is not None
            and existing.status == "success"
            and existing.study_fingerprint == study_fingerprint
        ):
            completed.append(existing)
            if progress is not None:
                progress(existing, len(completed), total)
        else:
            pending.append(candidate)

    if worker_count == 1:
        for candidate in pending:
            record = _run_candidate(config, candidate, workspace, study_fingerprint)
            completed.append(record)
            if progress is not None:
                progress(record, len(completed), total)
    else:
        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="fpga-dse") as executor:
            futures: dict[Future[RunRecord], DesignCandidate] = {
                executor.submit(
                    _run_candidate, config, candidate, workspace, study_fingerprint
                ): candidate
                for candidate in pending
            }
            for future in as_completed(futures):
                candidate = futures[future]
                try:
                    record = future.result()
                except Exception as exc:  # Defensive boundary around worker failures.
                    record = RunRecord(
                        design_id=candidate.design_id,
                        project=config.name,
                        status="failed",
                        parameters=candidate.parameters,
                        study_fingerprint=study_fingerprint,
                        error=f"internal worker failure: {type(exc).__name__}: {exc}",
                        completed_at=_utc_now(),
                    )
                    workspace.write_record(record)
                completed.append(record)
                if progress is not None:
                    progress(record, len(completed), total)

    ordered = sorted(completed, key=lambda record: record.design_id)
    workspace.export_jsonl(ordered)
    return ordered


def _run_candidate(
    config: ProjectConfig,
    candidate: DesignCandidate,
    workspace: Workspace,
    study_fingerprint: str,
) -> RunRecord:
    run_directory = workspace.run_dir(candidate.design_id)
    run_directory.mkdir(parents=True, exist_ok=True)
    started_at = _utc_now()
    start = time.perf_counter()
    record = RunRecord(
        design_id=candidate.design_id,
        project=config.name,
        status="running",
        parameters=candidate.parameters,
        study_fingerprint=study_fingerprint,
        started_at=started_at,
    )
    workspace.write_record(record)

    try:
        if config.execution.adapter == "mock":
            metrics, metadata = _execute_mock(config, candidate.parameters)
            exit_code = 0
            command: list[str] | str | None = None
        else:
            metrics, metadata, exit_code, command = _execute_shell(
                config,
                candidate,
                workspace,
                run_directory,
            )
        final = replace(
            record,
            status="success",
            metrics=metrics,
            metadata=metadata,
            command=command,
            completed_at=_utc_now(),
            duration_seconds=time.perf_counter() - start,
            exit_code=exit_code,
        )
    except subprocess.TimeoutExpired as exc:
        _write_timeout_logs(run_directory, exc)
        final = replace(
            record,
            status="timeout",
            command=_normalize_command(exc.cmd),
            completed_at=_utc_now(),
            duration_seconds=time.perf_counter() - start,
            error=f"execution exceeded {config.execution.timeout_seconds:g} seconds",
        )
    except (ExecutionError, ExpressionError, OSError, TemplateError, ValueError) as exc:
        final = replace(
            record,
            status="failed",
            completed_at=_utc_now(),
            duration_seconds=time.perf_counter() - start,
            error=f"{type(exc).__name__}: {exc}",
        )

    workspace.write_record(final)
    return final


def _execute_mock(
    config: ProjectConfig,
    parameters: Mapping[str, Scalar],
) -> tuple[dict[str, MetricValue], dict[str, Any]]:
    if config.execution.mock_delay_ms:
        time.sleep(config.execution.mock_delay_ms / 1_000)
    metrics: dict[str, MetricValue] = {}
    for name, expression in config.execution.mock_metrics.items():
        value = evaluate_expression(expression, parameters)
        if not _is_metric(value):
            raise ExecutionError(f"mock metric {name!r} produced non-numeric value {value!r}")
        metrics[name] = value
    return metrics, {"adapter": "mock", "deterministic": True}


def _execute_shell(
    config: ProjectConfig,
    candidate: DesignCandidate,
    workspace: Workspace,
    run_directory: Path,
) -> tuple[dict[str, MetricValue], dict[str, Any], int, list[str] | str]:
    context: dict[str, Any] = {
        "params": candidate.parameters,
        **candidate.parameters,
        "design_id": candidate.design_id,
        "project_root": str(config.project_root),
        "workspace": str(workspace.root),
        "run_dir": str(run_directory),
        "python_executable": sys.executable,
    }
    command = _render_command(config.execution.command, context)
    working_directory = (
        Path(_render_text(config.execution.working_directory, context)).expanduser().resolve()
        if config.execution.working_directory
        else run_directory
    )
    if not working_directory.is_dir():
        raise ExecutionError(f"working directory does not exist: {working_directory}")

    environment = os.environ.copy()
    environment.update(
        {
            "DSE_RUN_ID": candidate.design_id,
            "DSE_RUN_DIR": str(run_directory),
            "DSE_PROJECT_ROOT": str(config.project_root),
            "DSE_PARAMETERS_FILE": str(run_directory / "parameters.json"),
        }
    )
    for name, value in candidate.parameters.items():
        environment[f"DSE_PARAM_{name.upper()}"] = str(value)
    for key, value in config.execution.environment.items():
        environment[key] = _render_text(value, context)

    completed = subprocess.run(
        command,
        cwd=working_directory,
        env=environment,
        capture_output=True,
        text=True,
        timeout=config.execution.timeout_seconds,
        shell=config.execution.shell,
        check=False,
    )
    (run_directory / "stdout.log").write_text(completed.stdout, encoding="utf-8")
    (run_directory / "stderr.log").write_text(completed.stderr, encoding="utf-8")
    (run_directory / "command.txt").write_text(
        command if isinstance(command, str) else shlex.join(command),
        encoding="utf-8",
    )

    if completed.returncode != 0:
        tail = _tail(completed.stderr or completed.stdout)
        raise ExecutionError(f"command exited with code {completed.returncode}; log tail: {tail}")

    result_path = run_directory / _render_text(config.execution.result_file, context)
    metrics, metadata = _read_result_file(result_path)
    metadata = {"adapter": "shell", **metadata}
    return metrics, metadata, completed.returncode, command


def _read_result_file(path: Path) -> tuple[dict[str, MetricValue], dict[str, Any]]:
    if not path.is_file():
        raise ExecutionError(f"result file was not created: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ExecutionError(f"result file is not valid JSON: {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ExecutionError("result file root must be a JSON object")

    metric_source = raw.get("metrics", raw)
    if not isinstance(metric_source, dict) or not metric_source:
        raise ExecutionError("result file must contain a non-empty metrics object")
    metrics: dict[str, MetricValue] = {}
    for name, value in metric_source.items():
        if not isinstance(name, str) or not _is_metric(value):
            raise ExecutionError(f"metric {name!r} must be a finite integer or float")
        metrics[name] = value

    metadata_raw = raw.get("metadata", {}) if "metrics" in raw else {}
    if not isinstance(metadata_raw, dict):
        raise ExecutionError("result metadata must be a JSON object")
    return metrics, metadata_raw


def _render_command(
    command: str | tuple[str, ...] | None,
    context: Mapping[str, Any],
) -> list[str] | str:
    if command is None:
        raise ExecutionError("shell adapter has no command")
    if isinstance(command, str):
        return _render_text(command, context)
    return [_render_text(part, context) for part in command]


def _render_text(value: str | None, context: Mapping[str, Any]) -> str:
    if value is None:
        raise ExecutionError("cannot render a missing value")
    environment = Environment(undefined=StrictUndefined, autoescape=False)
    return environment.from_string(value).render(context)


def _write_timeout_logs(run_directory: Path, exc: subprocess.TimeoutExpired) -> None:
    stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else exc.stdout or ""
    stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else exc.stderr or ""
    (run_directory / "stdout.log").write_text(stdout, encoding="utf-8")
    (run_directory / "stderr.log").write_text(stderr, encoding="utf-8")


def _normalize_command(command: Any) -> list[str] | str | None:
    if isinstance(command, str):
        return command
    if isinstance(command, Sequence) and not isinstance(command, (str, bytes)):
        return [str(part) for part in command]
    return None


def _is_metric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value and abs(value) != float("inf")


def _tail(text: str, lines: int = 8) -> str:
    selected = text.strip().splitlines()[-lines:]
    return " | ".join(line.strip() for line in selected) or "<no output>"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
