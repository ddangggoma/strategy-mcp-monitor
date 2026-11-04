"""Whitelist-based arithmetic evaluator (no eval/exec)."""
from __future__ import annotations

import ast
import math
import operator
from collections.abc import Callable

MAX_EXPR_LEN = 200
MAX_NODES = 100
MAX_EXPONENT = 100
MAX_INT_DIGITS = 1000
_INT_LIMIT = 10**MAX_INT_DIGITS


class UnsafeExpression(ValueError):
    """The expression is malformed, uses a disallowed construct, or exceeds a resource limit."""


_BINARY: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY: dict[type[ast.unaryop], Callable[[float], float]] = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _checked(value: object) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UnsafeExpression("result is not a real number")
    if isinstance(value, int):
        if abs(value) >= _INT_LIMIT:
            raise UnsafeExpression(f"integer result exceeds {MAX_INT_DIGITS} digits")
    elif not math.isfinite(value):
        raise UnsafeExpression("result is not finite")
    return value


def _eval(node: ast.AST) -> float | int:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise UnsafeExpression("only numeric constants are allowed")
        return _checked(node.value)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _checked(_UNARY[type(node.op)](_eval(node.operand)))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise UnsafeExpression(f"exponent magnitude exceeds {MAX_EXPONENT}")
        try:
            return _checked(_BINARY[type(node.op)](left, right))
        except ZeroDivisionError:
            raise UnsafeExpression("division by zero") from None
        except OverflowError:
            raise UnsafeExpression("result too large") from None
    raise UnsafeExpression(f"disallowed syntax: {type(node).__name__}")


def safe_eval(expression: str) -> float | int:
    if not isinstance(expression, str):
        raise UnsafeExpression("expression must be a string")
    if len(expression) > MAX_EXPR_LEN:
        raise UnsafeExpression(f"expression longer than {MAX_EXPR_LEN} characters")
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except (SyntaxError, ValueError, RecursionError):
        raise UnsafeExpression("invalid expression") from None
    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        raise UnsafeExpression(f"expression has more than {MAX_NODES} nodes")
    return _eval(tree.body)
