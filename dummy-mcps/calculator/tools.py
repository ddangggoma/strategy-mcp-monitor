from __future__ import annotations

from calculator.safe_eval import UnsafeExpression, safe_eval

__all__ = ["add", "subtract", "multiply", "divide", "evaluate", "UnsafeExpression"]


def add(a: float, b: float) -> float:
    return a + b


def subtract(a: float, b: float) -> float:
    return a - b


def multiply(a: float, b: float) -> float:
    return a * b


def divide(a: float, b: float) -> float:
    if b == 0:
        raise ValueError("division by zero")
    return a / b


def evaluate(expression: str) -> float | int:
    return safe_eval(expression)
