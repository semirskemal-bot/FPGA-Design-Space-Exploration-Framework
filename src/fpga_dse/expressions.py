from __future__ import annotations

import ast
import math
import operator
from collections.abc import Callable, Mapping
from typing import Any

from fpga_dse.models import Scalar


class ExpressionError(ValueError):
    """Raised when an expression is invalid or cannot be evaluated safely."""


_ALLOWED_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "abs": abs,
    "bool": bool,
    "ceil": math.ceil,
    "float": float,
    "floor": math.floor,
    "int": int,
    "max": max,
    "min": min,
    "round": round,
}

_BINARY_OPERATORS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPERATORS: dict[type[ast.unaryop], Callable[[Any], Any]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Not: operator.not_,
}

_COMPARISON_OPERATORS: dict[type[ast.cmpop], Callable[[Any, Any], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}


def evaluate_expression(expression: str, context: Mapping[str, Scalar | int | float]) -> Any:
    """Evaluate a small arithmetic/boolean expression without Python builtins."""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"invalid expression {expression!r}: {exc.msg}") from exc
    return _evaluate_node(tree.body, context)


def referenced_names(expression: str) -> set[str]:
    """Return variable names referenced by an expression after validating its syntax."""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"invalid expression {expression!r}: {exc.msg}") from exc

    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id not in _ALLOWED_FUNCTIONS:
            names.add(node.id)
        if isinstance(node, (ast.Attribute, ast.Subscript, ast.Lambda, ast.Dict, ast.Set)):
            raise ExpressionError(f"unsupported syntax in expression {expression!r}")
    _evaluate_shape(tree.body)
    return names


def _evaluate_shape(node: ast.AST) -> None:
    """Validate the AST without requiring concrete variable values."""
    if isinstance(node, (ast.Constant, ast.Name)):
        return
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        _evaluate_shape(node.left)
        _evaluate_shape(node.right)
        return
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        _evaluate_shape(node.operand)
        return
    if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
        for value in node.values:
            _evaluate_shape(value)
        return
    if isinstance(node, ast.Compare):
        _evaluate_shape(node.left)
        for comparator in node.comparators:
            _evaluate_shape(comparator)
        if not all(type(op) in _COMPARISON_OPERATORS for op in node.ops):
            raise ExpressionError("unsupported comparison operator")
        return
    if isinstance(node, ast.IfExp):
        _evaluate_shape(node.test)
        _evaluate_shape(node.body)
        _evaluate_shape(node.orelse)
        return
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id not in _ALLOWED_FUNCTIONS or node.keywords:
            raise ExpressionError(f"function {node.func.id!r} is not allowed")
        for argument in node.args:
            _evaluate_shape(argument)
        return
    raise ExpressionError(f"unsupported expression node: {type(node).__name__}")


def _evaluate_node(node: ast.AST, context: Mapping[str, Scalar | int | float]) -> Any:
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (str, int, float, bool, type(None))):
            raise ExpressionError(f"unsupported constant: {node.value!r}")
        return node.value

    if isinstance(node, ast.Name):
        if node.id in context:
            return context[node.id]
        raise ExpressionError(f"unknown name {node.id!r}")

    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _evaluate_node(node.left, context)
        right = _evaluate_node(node.right, context)
        if isinstance(node.op, ast.Pow) and isinstance(right, (int, float)) and abs(right) > 12:
            raise ExpressionError("power exponent is limited to an absolute value of 12")
        try:
            return _BINARY_OPERATORS[type(node.op)](left, right)
        except (ArithmeticError, TypeError, ValueError) as exc:
            raise ExpressionError(f"failed to evaluate binary operation: {exc}") from exc

    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        value = _evaluate_node(node.operand, context)
        try:
            return _UNARY_OPERATORS[type(node.op)](value)
        except (ArithmeticError, TypeError, ValueError) as exc:
            raise ExpressionError(f"failed to evaluate unary operation: {exc}") from exc

    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            result: Any = True
            for value in node.values:
                result = _evaluate_node(value, context)
                if not result:
                    return result
            return result
        if isinstance(node.op, ast.Or):
            for value in node.values:
                result = _evaluate_node(value, context)
                if result:
                    return result
            return result

    if isinstance(node, ast.Compare):
        left = _evaluate_node(node.left, context)
        for operation, comparator in zip(node.ops, node.comparators, strict=True):
            if type(operation) not in _COMPARISON_OPERATORS:
                raise ExpressionError("unsupported comparison operator")
            right = _evaluate_node(comparator, context)
            try:
                if not _COMPARISON_OPERATORS[type(operation)](left, right):
                    return False
            except (TypeError, ValueError) as exc:
                raise ExpressionError(f"failed to evaluate comparison: {exc}") from exc
            left = right
        return True

    if isinstance(node, ast.IfExp):
        branch = node.body if _evaluate_node(node.test, context) else node.orelse
        return _evaluate_node(branch, context)

    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        function = _ALLOWED_FUNCTIONS.get(node.func.id)
        if function is None or node.keywords:
            raise ExpressionError(f"function {node.func.id!r} is not allowed")
        arguments = [_evaluate_node(argument, context) for argument in node.args]
        try:
            return function(*arguments)
        except (ArithmeticError, TypeError, ValueError) as exc:
            raise ExpressionError(f"function {node.func.id!r} failed: {exc}") from exc

    raise ExpressionError(f"unsupported expression node: {type(node).__name__}")
