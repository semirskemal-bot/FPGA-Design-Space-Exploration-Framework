from __future__ import annotations

import hashlib
import itertools
import json
import math
import random
from collections.abc import Iterable, Iterator, Mapping

from fpga_dse.expressions import ExpressionError, evaluate_expression
from fpga_dse.models import DesignCandidate, ParameterSpec, Scalar


class DesignSpaceError(ValueError):
    """Raised when a design space cannot be generated safely."""


def stable_design_id(parameters: Mapping[str, Scalar]) -> str:
    canonical = json.dumps(parameters, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def total_combinations(parameters: Iterable[ParameterSpec]) -> int:
    return math.prod(len(parameter.values) for parameter in parameters)


def generate_candidates(
    parameters: tuple[ParameterSpec, ...],
    constraints: tuple[str, ...],
    *,
    strategy: str,
    samples: int | None = None,
    seed: int = 0,
    limit: int | None = None,
) -> Iterator[DesignCandidate]:
    if limit is not None and limit <= 0:
        raise DesignSpaceError("limit must be positive")

    if strategy == "grid":
        source: Iterator[dict[str, Scalar]] = _grid_assignments(parameters)
    elif strategy == "random":
        if samples is None or samples <= 0:
            raise DesignSpaceError("random strategy requires a positive sample count")
        source = _random_assignments(parameters, constraints, samples=samples, seed=seed)
        constraints = ()  # Random generation already filters constraints.
    else:
        raise DesignSpaceError(f"unsupported search strategy: {strategy}")

    emitted = 0
    for assignment in source:
        if constraints and not _satisfies_constraints(assignment, constraints):
            continue
        yield DesignCandidate(
            design_id=stable_design_id(assignment),
            parameters=assignment,
        )
        emitted += 1
        if limit is not None and emitted >= limit:
            break


def materialize_candidates(
    parameters: tuple[ParameterSpec, ...],
    constraints: tuple[str, ...],
    *,
    strategy: str,
    samples: int | None = None,
    seed: int = 0,
    limit: int | None = None,
    max_designs: int = 10_000,
) -> list[DesignCandidate]:
    effective_limit = min(limit, max_designs) if limit is not None else max_designs + 1
    candidates = list(
        generate_candidates(
            parameters,
            constraints,
            strategy=strategy,
            samples=samples,
            seed=seed,
            limit=effective_limit,
        )
    )
    if limit is None and len(candidates) > max_designs:
        raise DesignSpaceError(
            f"study exceeds search.max_designs={max_designs}; add constraints, use random search, "
            "raise max_designs intentionally, or pass --limit"
        )
    if limit is not None and limit > max_designs:
        raise DesignSpaceError(
            f"requested limit {limit} exceeds search.max_designs={max_designs}; "
            "raise max_designs in the configuration intentionally"
        )
    return candidates


def _grid_assignments(parameters: tuple[ParameterSpec, ...]) -> Iterator[dict[str, Scalar]]:
    names = [parameter.name for parameter in parameters]
    value_sets = [parameter.values for parameter in parameters]
    for values in itertools.product(*value_sets):
        yield dict(zip(names, values, strict=True))


def _random_assignments(
    parameters: tuple[ParameterSpec, ...],
    constraints: tuple[str, ...],
    *,
    samples: int,
    seed: int,
) -> Iterator[dict[str, Scalar]]:
    total = total_combinations(parameters)
    target = min(samples, total)
    rng = random.Random(seed)

    # For moderate spaces, shuffle exact mixed-radix indices. For very large spaces,
    # draw unique indices without ever constructing the Cartesian product.
    if total <= 1_000_000:
        indices = list(range(total))
        rng.shuffle(indices)
        candidate_indices: Iterable[int] = indices
    else:
        candidate_indices = _unique_random_indices(rng, total, max(target * 200, 10_000))

    emitted = 0
    for index in candidate_indices:
        assignment = _assignment_from_index(parameters, index)
        if not _satisfies_constraints(assignment, constraints):
            continue
        yield assignment
        emitted += 1
        if emitted >= target:
            return

    if emitted < target:
        raise DesignSpaceError(
            f"random search found only {emitted} feasible unique designs out of {target} requested; "
            "constraints may be too restrictive"
        )


def _unique_random_indices(rng: random.Random, upper_bound: int, attempts: int) -> Iterator[int]:
    seen: set[int] = set()
    while len(seen) < min(attempts, upper_bound):
        index = rng.randrange(upper_bound)
        if index in seen:
            continue
        seen.add(index)
        yield index


def _assignment_from_index(parameters: tuple[ParameterSpec, ...], index: int) -> dict[str, Scalar]:
    values: dict[str, Scalar] = {}
    remainder = index
    for parameter in reversed(parameters):
        radix = len(parameter.values)
        position = remainder % radix
        remainder //= radix
        values[parameter.name] = parameter.values[position]
    return {parameter.name: values[parameter.name] for parameter in parameters}


def _satisfies_constraints(parameters: Mapping[str, Scalar], constraints: tuple[str, ...]) -> bool:
    for expression in constraints:
        try:
            result = evaluate_expression(expression, parameters)
        except ExpressionError as exc:
            raise DesignSpaceError(f"failed to evaluate constraint {expression!r}: {exc}") from exc
        if not isinstance(result, bool):
            raise DesignSpaceError(f"constraint {expression!r} did not evaluate to a boolean")
        if not result:
            return False
    return True
