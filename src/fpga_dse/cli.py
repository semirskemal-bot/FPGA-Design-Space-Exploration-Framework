from __future__ import annotations

import argparse
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from fpga_dse import __version__
from fpga_dse.analysis import AnalysisError, analyze_records
from fpga_dse.config import ConfigError, load_config
from fpga_dse.fingerprint import FingerprintError, compute_study_fingerprint, fingerprinted_files
from fpga_dse.models import DesignCandidate, ProjectConfig, RunRecord
from fpga_dse.reporting import write_reports
from fpga_dse.runner import ExecutionError, run_study
from fpga_dse.scaffold import ScaffoldError, create_scaffold
from fpga_dse.space import DesignSpaceError, materialize_candidates, total_combinations
from fpga_dse.workspace import Workspace, WorkspaceError, write_json_atomic


class CliError(RuntimeError):
    """Raised for expected command-line errors."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fpga-dse",
        description="Explore FPGA architecture parameters and identify Pareto-optimal designs.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command_name", required=True)

    init_parser = subparsers.add_parser("init", help="create a runnable starter study")
    init_parser.add_argument("directory", nargs="?", default=".")
    init_parser.add_argument("--force", action="store_true", help="overwrite generated files")
    init_parser.set_defaults(handler=_command_init)

    validate_parser = subparsers.add_parser("validate", help="validate a study configuration")
    validate_parser.add_argument("config")
    validate_parser.set_defaults(handler=_command_validate)

    plan_parser = subparsers.add_parser("plan", help="enumerate or sample candidate designs")
    _add_search_arguments(plan_parser)
    plan_parser.add_argument("config")
    plan_parser.add_argument("--output", help="write the complete plan to a JSON file")
    plan_parser.add_argument("--preview", type=_positive_int, default=10)
    plan_parser.set_defaults(handler=_command_plan)

    run_parser = subparsers.add_parser("run", help="execute a study and generate reports")
    _add_search_arguments(run_parser)
    run_parser.add_argument("config")
    run_parser.add_argument("--workspace", help="override project.workspace")
    run_parser.add_argument("--jobs", type=_positive_int, help="number of parallel workers")
    run_parser.add_argument("--no-resume", action="store_true", help="rerun successful designs")
    run_parser.add_argument("--no-report", action="store_true", help="skip report generation")
    run_parser.add_argument("--top", type=_positive_int, default=20, help="rows in summary reports")
    run_parser.set_defaults(handler=_command_run)

    analyze_parser = subparsers.add_parser("analyze", help="rebuild reports from stored runs")
    analyze_parser.add_argument("config")
    analyze_parser.add_argument("--workspace", help="override project.workspace")
    analyze_parser.add_argument("--output", help="report directory; defaults to WORKSPACE/reports")
    analyze_parser.add_argument("--top", type=_positive_int, default=20)
    analyze_parser.set_defaults(handler=_command_analyze)

    status_parser = subparsers.add_parser("status", help="summarize the current workspace")
    status_parser.add_argument("config")
    status_parser.add_argument("--workspace", help="override project.workspace")
    status_parser.set_defaults(handler=_command_status)

    doctor_parser = subparsers.add_parser("doctor", help="check configuration and external tools")
    doctor_parser.add_argument("config")
    doctor_parser.set_defaults(handler=_command_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        return int(arguments.handler(arguments))
    except (
        ConfigError,
        DesignSpaceError,
        ExecutionError,
        FingerprintError,
        AnalysisError,
        WorkspaceError,
        ScaffoldError,
        CliError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


def _command_init(arguments: argparse.Namespace) -> int:
    files = create_scaffold(arguments.directory, force=arguments.force)
    print("Created starter study:")
    for path in files:
        print(f"  {path}")
    print(f"\nNext: fpga-dse run {files[0]}")
    return 0


def _command_validate(arguments: argparse.Namespace) -> int:
    config = load_config(arguments.config)
    total = total_combinations(config.parameters)
    print(f"Configuration is valid: {config.config_path}")
    print(f"Project: {config.name}")
    print(f"Raw Cartesian combinations: {total:,}")
    print(f"Search: {config.search.strategy}")
    print(f"Execution adapter: {config.execution.adapter}")
    print(f"Objectives: {', '.join(objective.metric for objective in config.objectives)}")
    return 0


def _command_plan(arguments: argparse.Namespace) -> int:
    config = load_config(arguments.config)
    candidates = _candidates_from_arguments(config, arguments)
    print(f"Planned {len(candidates):,} feasible candidate designs.")
    print("Design ID      Parameters")
    for candidate in candidates[: arguments.preview]:
        rendered = ", ".join(f"{key}={value}" for key, value in candidate.parameters.items())
        print(f"{candidate.design_id}  {rendered}")
    if len(candidates) > arguments.preview:
        print(f"... {len(candidates) - arguments.preview:,} more")
    if arguments.output:
        output = Path(arguments.output).expanduser().resolve()
        write_json_atomic(
            output,
            {
                "schema_version": 1,
                "project": config.name,
                "count": len(candidates),
                "designs": [
                    {"design_id": candidate.design_id, "parameters": candidate.parameters}
                    for candidate in candidates
                ],
            },
        )
        print(f"Plan written to {output}")
    return 0


def _command_run(arguments: argparse.Namespace) -> int:
    config = load_config(arguments.config)
    workspace = _workspace(config, arguments.workspace)
    candidates = _candidates_from_arguments(config, arguments)
    print(
        f"Running {len(candidates):,} designs with {arguments.jobs or config.execution.jobs} worker(s) "
        f"using the {config.execution.adapter} adapter."
    )

    def progress(record: RunRecord, completed: int, total: int) -> None:
        metric_preview = ", ".join(
            f"{key}={value}" for key, value in list(sorted(record.metrics.items()))[:3]
        )
        suffix = f" — {metric_preview}" if metric_preview else (f" — {record.error}" if record.error else "")
        print(f"[{completed:>{len(str(total))}}/{total}] {record.design_id} {record.status}{suffix}")

    records = run_study(
        config,
        candidates,
        workspace,
        jobs=arguments.jobs,
        resume=not arguments.no_resume,
        progress=progress,
    )
    counts = Counter(record.status for record in records)
    print("\nRun summary: " + ", ".join(f"{status}={count}" for status, count in sorted(counts.items())))
    print(f"Results ledger: {workspace.root / 'results.jsonl'}")

    if not arguments.no_report:
        result = analyze_records(config, records)
        paths = write_reports(result, workspace.reports_dir, top=arguments.top)
        _print_report_summary(result, paths)

    return 1 if any(record.status != "success" for record in records) else 0


def _command_analyze(arguments: argparse.Namespace) -> int:
    config = load_config(arguments.config)
    workspace = _workspace(config, arguments.workspace)
    fingerprint = compute_study_fingerprint(config)
    records = [
        record
        for record in workspace.all_records()
        if record.study_fingerprint == fingerprint
    ]
    if not records:
        raise CliError(f"no run records found in {workspace.runs_dir}")
    result = analyze_records(config, records)
    output = Path(arguments.output).expanduser().resolve() if arguments.output else workspace.reports_dir
    paths = write_reports(result, output, top=arguments.top)
    _print_report_summary(result, paths)
    return 0


def _command_status(arguments: argparse.Namespace) -> int:
    config = load_config(arguments.config)
    workspace = _workspace(config, arguments.workspace)
    fingerprint = compute_study_fingerprint(config)
    all_records = workspace.all_records()
    records = [record for record in all_records if record.study_fingerprint == fingerprint]
    stale_count = len(all_records) - len(records)
    counts = Counter(record.status for record in records)
    print(f"Workspace: {workspace.root}")
    print(f"Current experiment fingerprint: {fingerprint[:12]}")
    print(f"Recorded designs for current experiment: {len(records):,}")
    if stale_count:
        print(f"Stale records retained from earlier experiment definitions: {stale_count:,}")
    for status in ("queued", "running", "success", "failed", "timeout"):
        if counts[status]:
            print(f"  {status}: {counts[status]:,}")
    if records:
        succeeded = [record for record in records if record.status == "success"]
        if succeeded:
            durations = [record.duration_seconds for record in succeeded if record.duration_seconds is not None]
            if durations:
                print(f"Average successful runtime: {sum(durations) / len(durations):.3f}s")
    return 0


def _command_doctor(arguments: argparse.Namespace) -> int:
    config = load_config(arguments.config)
    print("[ok] configuration is valid")
    print(f"[ok] Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    fingerprint = compute_study_fingerprint(config)
    print(f"[ok] experiment fingerprint: {fingerprint[:12]}")
    files = fingerprinted_files(config)
    print(f"[ok] fingerprinted source files: {len(files)}")
    if config.execution.adapter == "mock":
        print("[ok] mock adapter needs no external FPGA toolchain")
        return 0

    command = config.execution.command
    if isinstance(command, tuple):
        executable = command[0]
        if "{{" in executable:
            print("[info] executable is templated and will be resolved per run")
        elif shutil.which(executable):
            print(f"[ok] executable found: {shutil.which(executable)}")
        else:
            raise CliError(f"executable not found on PATH: {executable}")
    else:
        shell = shutil.which("cmd" if sys.platform == "win32" else "sh")
        if shell:
            print(f"[ok] shell available: {shell}")
        else:
            raise CliError("no command shell found")
    return 0


def _candidates_from_arguments(
    config: ProjectConfig,
    arguments: argparse.Namespace,
) -> list[DesignCandidate]:
    strategy = arguments.strategy or config.search.strategy
    samples = arguments.samples if arguments.samples is not None else config.search.samples
    return materialize_candidates(
        config.parameters,
        config.parameter_constraints,
        strategy=strategy,
        samples=samples,
        seed=arguments.seed if arguments.seed is not None else config.search.seed,
        limit=arguments.limit,
        max_designs=config.search.max_designs,
    )


def _workspace(config: ProjectConfig, override: str | None) -> Workspace:
    return Workspace(Path(override).expanduser().resolve() if override else config.workspace)


def _print_report_summary(result: Any, paths: dict[str, Path]) -> None:
    recommended = result.recommended
    print(f"Feasible designs: {len(result.feasible_designs):,}")
    print(f"Pareto-optimal designs: {len(result.pareto_designs):,}")
    if recommended is not None:
        print(f"Recommended design: {recommended.record.design_id} (score={recommended.score:.4f})")
    print(f"HTML report: {paths['html']}")


def _add_search_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--strategy", choices=("grid", "random"))
    parser.add_argument("--samples", type=_positive_int)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--limit", type=_positive_int)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed
