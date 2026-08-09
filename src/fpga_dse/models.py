from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypeAlias

Scalar: TypeAlias = str | int | float | bool
MetricValue: TypeAlias = int | float
Goal: TypeAlias = Literal["minimize", "maximize"]
Strategy: TypeAlias = Literal["grid", "random"]
Adapter: TypeAlias = Literal["mock", "shell"]
RunStatus: TypeAlias = Literal["queued", "running", "success", "failed", "timeout"]


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    name: str
    values: tuple[Scalar, ...]


@dataclass(frozen=True, slots=True)
class Objective:
    metric: str
    goal: Goal
    weight: float = 1.0


@dataclass(frozen=True, slots=True)
class SearchSpec:
    strategy: Strategy = "grid"
    samples: int | None = None
    seed: int = 0
    max_designs: int = 10_000


@dataclass(frozen=True, slots=True)
class ExecutionSpec:
    adapter: Adapter
    jobs: int = 1
    timeout_seconds: float = 3_600.0
    command: str | tuple[str, ...] | None = None
    shell: bool = False
    result_file: str = "result.json"
    working_directory: str | None = None
    environment: dict[str, str] = field(default_factory=dict)
    mock_metrics: dict[str, str] = field(default_factory=dict)
    mock_delay_ms: int = 0
    fingerprint_files: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    version: int
    name: str
    config_path: Path
    project_root: Path
    workspace: Path
    parameters: tuple[ParameterSpec, ...]
    parameter_constraints: tuple[str, ...]
    metric_constraints: tuple[str, ...]
    objectives: tuple[Objective, ...]
    search: SearchSpec
    execution: ExecutionSpec

    @property
    def parameter_names(self) -> tuple[str, ...]:
        return tuple(parameter.name for parameter in self.parameters)


@dataclass(frozen=True, slots=True)
class DesignCandidate:
    design_id: str
    parameters: dict[str, Scalar]


@dataclass(slots=True)
class RunRecord:
    design_id: str
    project: str
    status: RunStatus
    parameters: dict[str, Scalar]
    study_fingerprint: str | None = None
    metrics: dict[str, MetricValue] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    command: list[str] | str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    duration_seconds: float | None = None
    exit_code: int | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "design_id": self.design_id,
            "project": self.project,
            "status": self.status,
            "parameters": self.parameters,
            "study_fingerprint": self.study_fingerprint,
            "metrics": self.metrics,
            "metadata": self.metadata,
            "command": self.command,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "exit_code": self.exit_code,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunRecord:
        return cls(
            design_id=str(data["design_id"]),
            project=str(data["project"]),
            status=data["status"],
            parameters=dict(data.get("parameters", {})),
            study_fingerprint=data.get("study_fingerprint"),
            metrics=dict(data.get("metrics", {})),
            metadata=dict(data.get("metadata", {})),
            command=data.get("command"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            duration_seconds=data.get("duration_seconds"),
            exit_code=data.get("exit_code"),
            error=data.get("error"),
        )


@dataclass(frozen=True, slots=True)
class AnalyzedDesign:
    record: RunRecord
    feasible: bool
    violations: tuple[str, ...]
    pareto_optimal: bool
    score: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.record.to_dict(),
            "analysis": {
                "feasible": self.feasible,
                "violations": list(self.violations),
                "pareto_optimal": self.pareto_optimal,
                "score": self.score,
            },
        }


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    project: str
    objectives: tuple[Objective, ...]
    designs: tuple[AnalyzedDesign, ...]

    @property
    def successful_count(self) -> int:
        return len(self.designs)

    @property
    def feasible_designs(self) -> tuple[AnalyzedDesign, ...]:
        return tuple(design for design in self.designs if design.feasible)

    @property
    def pareto_designs(self) -> tuple[AnalyzedDesign, ...]:
        return tuple(design for design in self.designs if design.pareto_optimal)

    @property
    def recommended(self) -> AnalyzedDesign | None:
        feasible = [design for design in self.designs if design.feasible and design.score is not None]
        return max(feasible, key=lambda design: (design.score or 0.0, design.record.design_id), default=None)
