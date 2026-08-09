from __future__ import annotations

import pytest

from fpga_dse.expressions import ExpressionError, evaluate_expression, referenced_names


def test_evaluates_arithmetic_boolean_and_conditional_expressions() -> None:
    context = {"WIDTH": 16, "LANES": 4, "MODE": "fast"}
    assert evaluate_expression("WIDTH * LANES <= 64 and MODE == 'fast'", context) is True
    assert evaluate_expression("ceil(WIDTH / 7)", context) == 3
    assert evaluate_expression("100 if LANES > 2 else 20", context) == 100


def test_referenced_names_excludes_allowed_functions() -> None:
    assert referenced_names("round(WIDTH / max(LANES, 1), 2)") == {"WIDTH", "LANES"}


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os')",
        "WIDTH.real",
        "values[0]",
        "[x for x in values]",
        "lambda: 1",
    ],
)
def test_rejects_unsafe_syntax(expression: str) -> None:
    with pytest.raises(ExpressionError):
        referenced_names(expression)


def test_unknown_name_and_large_exponent_are_rejected() -> None:
    with pytest.raises(ExpressionError, match="unknown name"):
        evaluate_expression("MISSING + 1", {})
    with pytest.raises(ExpressionError, match="exponent"):
        evaluate_expression("2 ** 100", {})
