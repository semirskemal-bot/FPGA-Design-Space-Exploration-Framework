from __future__ import annotations

from collections.abc import Mapping, Sequence

from fpga_dse.expressions import ExpressionError, evaluate_expression, referenced_names
from fpga_dse.models import (
    AnalysisResult,
    AnalyzedDesign,
    MetricValue,
    Objective,
    ProjectConfig,
    RunRecord,
    Scalar,
)


class AnalysisError(ValueError):
    """Raised when successful run data cannot be analyzed."""


def analyze_records(config: ProjectConfig, records: Sequence[RunRecord]) -> AnalysisResult:
    successful = [record for record in records if record.status == "success"]
    preliminary: list[tuple[RunRecord, bool, tuple[str, ...]]] = []

    for record in successful:
        violations = _constraint_violations(config.metric_constraints, record.parameters, record.metrics)
        missing = tuple(
            f"missing objective metric: {objective.metric}"
            for objective in config.objectives
            if objective.metric not in record.metrics
        )
        all_violations = (*violations, *missing)
        preliminary.append((record, not all_violations, all_violations))

    feasible_records = [record for record, feasible, _ in preliminary if feasible]
    pareto_ids = _pareto_ids(feasible_records, config.objectives)
    scores = _weighted_scores(feasible_records, config.objectives)

    designs = tuple(
        sorted(
            (
                AnalyzedDesign(
                    record=record,
                    feasible=feasible,
                    violations=violations,
                    pareto_optimal=feasible and record.design_id in pareto_ids,
                    score=scores.get(record.design_id),
                )
                for record, feasible, violations in preliminary
            ),
            key=_analysis_sort_key,
        )
    )
    return AnalysisResult(project=config.name, objectives=config.objectives, designs=designs)


def _constraint_violations(
    expressions: tuple[str, ...],
    parameters: Mapping[str, Scalar],
    metrics: Mapping[str, MetricValue],
) -> tuple[str, ...]:
    context: dict[str, Scalar | MetricValue] = {**parameters, **metrics}
    violations: list[str] = []
    for expression in expressions:
        try:
            unknown = referenced_names(expression) - context.keys()
        except ExpressionError as exc:
            raise AnalysisError(f"invalid metric constraint {expression!r}: {exc}") from exc
        if unknown:
            names = ", ".join(sorted(unknown))
            violations.append(f"cannot evaluate {expression!r}; missing metrics: {names}")
            continue
        try:
            value = evaluate_expression(expression, context)
        except ExpressionError as exc:
            raise AnalysisError(f"failed to evaluate metric constraint {expression!r}: {exc}") from exc
        if not isinstance(value, bool):
            raise AnalysisError(f"metric constraint {expression!r} did not evaluate to a boolean")
        if not value:
            violations.append(expression)
    return tuple(violations)


def _pareto_ids(records: Sequence[RunRecord], objectives: tuple[Objective, ...]) -> set[str]:
    frontier: set[str] = set()
    for candidate in records:
        dominated = any(
            other.design_id != candidate.design_id and _dominates(other, candidate, objectives)
            for other in records
        )
        if not dominated:
            frontier.add(candidate.design_id)
    return frontier


def _dominates(left: RunRecord, right: RunRecord, objectives: tuple[Objective, ...]) -> bool:
    no_worse = True
    strictly_better = False
    for objective in objectives:
        left_value = left.metrics[objective.metric]
        right_value = right.metrics[objective.metric]
        if objective.goal == "minimize":
            no_worse = no_worse and left_value <= right_value
            strictly_better = strictly_better or left_value < right_value
        else:
            no_worse = no_worse and left_value >= right_value
            strictly_better = strictly_better or left_value > right_value
        if not no_worse:
            return False
    return no_worse and strictly_better


def _weighted_scores(
    records: Sequence[RunRecord],
    objectives: tuple[Objective, ...],
) -> dict[str, float]:
    if not records:
        return {}
    total_weight = sum(objective.weight for objective in objectives)
    ranges: dict[str, tuple[float, float]] = {}
    for objective in objectives:
        values = [float(record.metrics[objective.metric]) for record in records]
        ranges[objective.metric] = (min(values), max(values))

    scores: dict[str, float] = {}
    for record in records:
        weighted = 0.0
        for objective in objectives:
            value = float(record.metrics[objective.metric])
            minimum, maximum = ranges[objective.metric]
            if maximum == minimum:
                desirability = 1.0
            elif objective.goal == "maximize":
                desirability = (value - minimum) / (maximum - minimum)
            else:
                desirability = (maximum - value) / (maximum - minimum)
            weighted += objective.weight * desirability
        scores[record.design_id] = weighted / total_weight
    return scores


def _analysis_sort_key(design: AnalyzedDesign) -> tuple[int, float, str]:
    return (
        0 if design.feasible else 1,
        -(design.score if design.score is not None else -1.0),
        design.record.design_id,
    )
