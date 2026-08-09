from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode

from fpga_dse.expressions import ExpressionError, referenced_names
from fpga_dse.models import (
    ExecutionSpec,
    Objective,
    ParameterSpec,
    ProjectConfig,
    Scalar,
    SearchSpec,
)


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader, node: MappingNode, deep: bool = False
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


class ConfigError(ValueError):
    """Raised when a DSE configuration is malformed."""


def load_config(path: str | Path) -> ProjectConfig:
    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise ConfigError(f"configuration file does not exist: {config_path}")

    try:
        raw = yaml.load(
            config_path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader
        )
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {config_path}: {exc}") from exc

    if not isinstance(raw, Mapping):
        raise ConfigError("configuration root must be a mapping")
    _reject_unknown(
        raw,
        {
            "version",
            "project",
            "parameters",
            "parameter_constraints",
            "search",
            "execution",
            "metric_constraints",
            "objectives",
        },
        "configuration root",
    )

    version = _require_int(raw, "version")
    if version != 1:
        raise ConfigError(f"unsupported configuration version {version}; expected 1")

    project = _require_mapping(raw, "project")
    _reject_unknown(project, {"name", "workspace"}, "project")
    name = _require_nonempty_string(project, "name")
    project_root = config_path.parent
    workspace_value = project.get("workspace", ".dse")
    if not isinstance(workspace_value, str) or not workspace_value.strip():
        raise ConfigError("project.workspace must be a non-empty string")
    workspace = (project_root / workspace_value).resolve()

    parameters = _parse_parameters(_require_mapping(raw, "parameters"))
    parameter_names = {parameter.name for parameter in parameters}
    parameter_constraints = _parse_string_list(raw.get("parameter_constraints", []), "parameter_constraints")
    metric_constraints = _parse_string_list(raw.get("metric_constraints", []), "metric_constraints")
    objectives = _parse_objectives(raw.get("objectives"))
    search = _parse_search(raw.get("search", {}))
    execution = _parse_execution(_require_mapping(raw, "execution"))

    _validate_expression_names(parameter_constraints, parameter_names, "parameter constraint")
    for metric_name, expression in execution.mock_metrics.items():
        _validate_expression_names((expression,), parameter_names, f"mock metric {metric_name!r}")

    return ProjectConfig(
        version=version,
        name=name,
        config_path=config_path,
        project_root=project_root,
        workspace=workspace,
        parameters=parameters,
        parameter_constraints=parameter_constraints,
        metric_constraints=metric_constraints,
        objectives=objectives,
        search=search,
        execution=execution,
    )


def _parse_parameters(raw: Mapping[str, Any]) -> tuple[ParameterSpec, ...]:
    if not raw:
        raise ConfigError("parameters must contain at least one parameter")

    parameters: list[ParameterSpec] = []
    for name, specification in raw.items():
        if not isinstance(name, str) or not name.isidentifier():
            raise ConfigError(f"parameter name {name!r} must be a valid identifier")
        if not isinstance(specification, Mapping):
            raise ConfigError(f"parameter {name!r} must be a mapping")
        _reject_unknown(specification, {"values", "range"}, f"parameter {name!r}")

        has_values = "values" in specification
        has_range = "range" in specification
        if has_values == has_range:
            raise ConfigError(f"parameter {name!r} must define exactly one of values or range")

        values = (
            _parse_explicit_values(name, specification["values"])
            if has_values
            else _parse_range_values(name, specification["range"])
        )
        if len({repr(value) for value in values}) != len(values):
            raise ConfigError(f"parameter {name!r} contains duplicate values")
        parameters.append(ParameterSpec(name=name, values=tuple(values)))
    return tuple(parameters)


def _parse_explicit_values(name: str, raw: Any) -> list[Scalar]:
    if not isinstance(raw, list) or not raw:
        raise ConfigError(f"parameter {name!r}.values must be a non-empty list")
    values: list[Scalar] = []
    for value in raw:
        if not isinstance(value, (str, int, float, bool)) or isinstance(value, complex):
            raise ConfigError(f"parameter {name!r} contains unsupported value {value!r}")
        if isinstance(value, float) and not math.isfinite(value):
            raise ConfigError(f"parameter {name!r} contains a non-finite float")
        values.append(value)
    return values


def _parse_range_values(name: str, raw: Any) -> list[Scalar]:
    if not isinstance(raw, Mapping):
        raise ConfigError(f"parameter {name!r}.range must be a mapping")
    _reject_unknown(raw, {"start", "stop", "step", "inclusive"}, f"parameter {name!r}.range")
    start = raw.get("start")
    stop = raw.get("stop")
    step = raw.get("step", 1)
    inclusive = raw.get("inclusive", True)

    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in (start, stop, step)):
        raise ConfigError(f"parameter {name!r}.range start, stop, and step must be numeric")
    if step == 0:
        raise ConfigError(f"parameter {name!r}.range step cannot be zero")
    if not isinstance(inclusive, bool):
        raise ConfigError(f"parameter {name!r}.range inclusive must be boolean")
    if (stop - start) * step < 0:
        raise ConfigError(f"parameter {name!r}.range step points away from stop")

    values: list[Scalar] = []
    current = float(start) if any(isinstance(value, float) for value in (start, stop, step)) else int(start)
    tolerance = abs(float(step)) * 1e-10
    compare = (
        (lambda value: value <= float(stop) + tolerance)
        if step > 0 and inclusive
        else (lambda value: value < float(stop) - tolerance)
        if step > 0
        else (lambda value: value >= float(stop) - tolerance)
        if inclusive
        else (lambda value: value > float(stop) + tolerance)
    )

    count = 0
    while compare(float(current)):
        if count >= 100_000:
            raise ConfigError(f"parameter {name!r}.range expands to more than 100,000 values")
        values.append(current)
        current = current + step
        if isinstance(current, float):
            current = round(current, 12)
        count += 1

    if not values:
        raise ConfigError(f"parameter {name!r}.range produced no values")
    return values


def _parse_objectives(raw: Any) -> tuple[Objective, ...]:
    if not isinstance(raw, list) or not raw:
        raise ConfigError("objectives must be a non-empty list")
    objectives: list[Objective] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise ConfigError(f"objectives[{index}] must be a mapping")
        metric = _require_nonempty_string(item, "metric")
        goal = item.get("goal")
        if goal not in {"minimize", "maximize"}:
            raise ConfigError(f"objective {metric!r}.goal must be minimize or maximize")
        weight = item.get("weight", 1.0)
        if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0:
            raise ConfigError(f"objective {metric!r}.weight must be positive")
        if metric in seen:
            raise ConfigError(f"duplicate objective metric {metric!r}")
        seen.add(metric)
        objectives.append(Objective(metric=metric, goal=goal, weight=float(weight)))
    return tuple(objectives)


def _parse_search(raw: Any) -> SearchSpec:
    if not isinstance(raw, Mapping):
        raise ConfigError("search must be a mapping")
    _reject_unknown(raw, {"strategy", "samples", "seed", "max_designs"}, "search")
    strategy = raw.get("strategy", "grid")
    if strategy not in {"grid", "random"}:
        raise ConfigError("search.strategy must be grid or random")
    samples = raw.get("samples")
    if samples is not None and (not isinstance(samples, int) or isinstance(samples, bool) or samples <= 0):
        raise ConfigError("search.samples must be a positive integer")
    if strategy == "random" and samples is None:
        raise ConfigError("search.samples is required for random search")
    seed = raw.get("seed", 0)
    max_designs = raw.get("max_designs", 10_000)
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ConfigError("search.seed must be an integer")
    if not isinstance(max_designs, int) or isinstance(max_designs, bool) or max_designs <= 0:
        raise ConfigError("search.max_designs must be a positive integer")
    return SearchSpec(strategy=strategy, samples=samples, seed=seed, max_designs=max_designs)


def _parse_execution(raw: Mapping[str, Any]) -> ExecutionSpec:
    _reject_unknown(
        raw,
        {
            "adapter",
            "jobs",
            "timeout_seconds",
            "command",
            "shell",
            "result_file",
            "working_directory",
            "environment",
            "mock_metrics",
            "mock_delay_ms",
            "fingerprint_files",
        },
        "execution",
    )
    adapter = raw.get("adapter")
    if adapter not in {"mock", "shell"}:
        raise ConfigError("execution.adapter must be mock or shell")
    jobs = raw.get("jobs", 1)
    timeout = raw.get("timeout_seconds", 3_600.0)
    if not isinstance(jobs, int) or isinstance(jobs, bool) or jobs <= 0:
        raise ConfigError("execution.jobs must be a positive integer")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        raise ConfigError("execution.timeout_seconds must be positive")

    command_raw = raw.get("command")
    command: str | tuple[str, ...] | None
    if command_raw is None:
        command = None
    elif isinstance(command_raw, str) and command_raw.strip():
        command = command_raw
    elif isinstance(command_raw, list) and command_raw and all(isinstance(item, str) for item in command_raw):
        command = tuple(command_raw)
    else:
        raise ConfigError("execution.command must be a non-empty string or list of strings")

    shell = raw.get("shell", False)
    if not isinstance(shell, bool):
        raise ConfigError("execution.shell must be boolean")
    if adapter == "shell" and command is None:
        raise ConfigError("execution.command is required for the shell adapter")
    if isinstance(command, tuple) and shell:
        raise ConfigError("execution.shell=true requires command to be a string")

    result_file = raw.get("result_file", "result.json")
    working_directory = raw.get("working_directory")
    if not isinstance(result_file, str) or not result_file.strip():
        raise ConfigError("execution.result_file must be a non-empty string")
    if working_directory is not None and (not isinstance(working_directory, str) or not working_directory.strip()):
        raise ConfigError("execution.working_directory must be a non-empty string")

    environment_raw = raw.get("environment", {})
    if not isinstance(environment_raw, Mapping) or not all(
        isinstance(key, str) and isinstance(value, (str, int, float, bool))
        for key, value in environment_raw.items()
    ):
        raise ConfigError("execution.environment must map strings to scalar values")
    environment = {str(key): str(value) for key, value in environment_raw.items()}

    mock_metrics_raw = raw.get("mock_metrics", {})
    if not isinstance(mock_metrics_raw, Mapping) or not all(
        isinstance(key, str)
        and isinstance(value, (str, int, float))
        and not isinstance(value, bool)
        for key, value in mock_metrics_raw.items()
    ):
        raise ConfigError("execution.mock_metrics must map metric names to expressions")
    mock_metrics = {str(key): str(value) for key, value in mock_metrics_raw.items()}
    if adapter == "mock" and not mock_metrics:
        raise ConfigError("execution.mock_metrics is required for the mock adapter")

    mock_delay_ms = raw.get("mock_delay_ms", 0)
    if not isinstance(mock_delay_ms, int) or isinstance(mock_delay_ms, bool) or mock_delay_ms < 0:
        raise ConfigError("execution.mock_delay_ms must be a non-negative integer")

    fingerprint_files_raw = raw.get("fingerprint_files", [])
    if not isinstance(fingerprint_files_raw, list) or not all(
        isinstance(item, str) and item.strip() for item in fingerprint_files_raw
    ):
        raise ConfigError("execution.fingerprint_files must be a list of non-empty strings")
    fingerprint_files = tuple(item.strip() for item in fingerprint_files_raw)
    if len(set(fingerprint_files)) != len(fingerprint_files):
        raise ConfigError("execution.fingerprint_files contains duplicate entries")

    return ExecutionSpec(
        adapter=adapter,
        jobs=jobs,
        timeout_seconds=float(timeout),
        command=command,
        shell=shell,
        result_file=result_file,
        working_directory=working_directory,
        environment=environment,
        mock_metrics=mock_metrics,
        mock_delay_ms=mock_delay_ms,
        fingerprint_files=fingerprint_files,
    )


def _validate_expression_names(expressions: tuple[str, ...], names: set[str], label: str) -> None:
    for expression in expressions:
        try:
            unknown = referenced_names(expression) - names
        except ExpressionError as exc:
            raise ConfigError(f"invalid {label} {expression!r}: {exc}") from exc
        if unknown:
            joined = ", ".join(sorted(unknown))
            raise ConfigError(f"{label} {expression!r} references unknown names: {joined}")


def _parse_string_list(raw: Any, field: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or not all(isinstance(item, str) and item.strip() for item in raw):
        raise ConfigError(f"{field} must be a list of non-empty strings")
    return tuple(raw)


def _reject_unknown(raw: Mapping[Any, Any], allowed: set[str], label: str) -> None:
    unknown = sorted((repr(key) for key in raw if key not in allowed))
    if unknown:
        suffix = "s" if len(unknown) != 1 else ""
        raise ConfigError(f"{label} contains unknown field{suffix}: {', '.join(unknown)}")


def _require_mapping(raw: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = raw.get(key)
    if not isinstance(value, Mapping):
        raise ConfigError(f"{key} must be a mapping")
    return value


def _require_int(raw: Mapping[str, Any], key: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f"{key} must be an integer")
    return value


def _require_nonempty_string(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{key} must be a non-empty string")
    return value.strip()
