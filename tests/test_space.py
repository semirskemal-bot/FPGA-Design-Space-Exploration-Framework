from __future__ import annotations

import pytest

from fpga_dse.models import ParameterSpec
from fpga_dse.space import (
    DesignSpaceError,
    generate_candidates,
    materialize_candidates,
    stable_design_id,
    total_combinations,
)


PARAMETERS = (
    ParameterSpec("WIDTH", (8, 16, 32)),
    ParameterSpec("LANES", (1, 2, 4)),
)


def test_grid_generation_filters_constraints_and_is_stable() -> None:
    candidates = list(
        generate_candidates(
            PARAMETERS,
            ("WIDTH * LANES <= 64",),
            strategy="grid",
        )
    )
    assert len(candidates) == 8
    assert candidates[0].parameters == {"WIDTH": 8, "LANES": 1}
    assert candidates[0].design_id == stable_design_id({"LANES": 1, "WIDTH": 8})
    assert total_combinations(PARAMETERS) == 9


def test_random_generation_is_unique_and_deterministic() -> None:
    first = list(
        generate_candidates(PARAMETERS, (), strategy="random", samples=5, seed=12)
    )
    second = list(
        generate_candidates(PARAMETERS, (), strategy="random", samples=5, seed=12)
    )
    assert [item.design_id for item in first] == [item.design_id for item in second]
    assert len({item.design_id for item in first}) == 5


def test_random_reports_overly_restrictive_constraints() -> None:
    with pytest.raises(DesignSpaceError, match="found only"):
        list(
            generate_candidates(
                PARAMETERS,
                ("WIDTH == 8 and LANES == 1",),
                strategy="random",
                samples=4,
                seed=2,
            )
        )


def test_max_design_guard_and_limit_validation() -> None:
    with pytest.raises(DesignSpaceError, match="max_designs"):
        materialize_candidates(PARAMETERS, (), strategy="grid", max_designs=4)
    with pytest.raises(DesignSpaceError, match="exceeds"):
        materialize_candidates(PARAMETERS, (), strategy="grid", max_designs=4, limit=5)
    with pytest.raises(DesignSpaceError, match="positive"):
        list(generate_candidates(PARAMETERS, (), strategy="grid", limit=0))
