from common.server import run
from calculator import tools


def add(a: float, b: float) -> float:
    """Return a + b."""
    return tools.add(a, b)


def subtract(a: float, b: float) -> float:
    """Return a - b."""
    return tools.subtract(a, b)


def multiply(a: float, b: float) -> float:
    """Return a * b."""
    return tools.multiply(a, b)


def divide(a: float, b: float) -> float:
    """Return a / b (error when b is 0)."""
    return tools.divide(a, b)


def evaluate(expression: str) -> float | int:
    """Safely evaluate an arithmetic expression: numbers, + - * / // % **, parentheses."""
    return tools.evaluate(expression)


if __name__ == "__main__":
    run("calculator", [add, subtract, multiply, divide, evaluate], None, 9102)
