"""Small arithmetic tools restricted to finite real numbers."""

import math
from numbers import Real

MAX_MAGNITUDE = 1e100
MAX_EXPONENT = 1000


def _number(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("Calculator arguments must be real numbers.")
    try:
        number = float(value)
    except (OverflowError, ValueError) as error:
        raise ValueError("Number is outside the supported range.") from error
    if not math.isfinite(number) or abs(number) > MAX_MAGNITUDE:
        raise ValueError("Numbers must be finite and have magnitude at most 1e100.")
    return number


def _result(value: float) -> float:
    if not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError("Calculation must produce a finite real result.")
    if abs(value) > MAX_MAGNITUDE:
        raise ValueError("Calculation result exceeds the supported magnitude of 1e100.")
    return float(value)


def add(a: float, b: float) -> float:
    """Add two numbers."""
    return _result(_number(a) + _number(b))


def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    return _result(_number(a) * _number(b))


def subtract(a: float, b: float) -> float:
    """Subtract the second number from the first."""
    return _result(_number(a) - _number(b))


def divide(a: float, b: float) -> float:
    """Divide the first number by the second."""
    numerator, denominator = _number(a), _number(b)
    if denominator == 0:
        raise ValueError("Cannot divide by zero.")
    return _result(numerator / denominator)


def power(a: float, b: float) -> float:
    """Raise the first number to the power of the second."""
    base, exponent = _number(a), _number(b)
    if abs(exponent) > MAX_EXPONENT:
        raise ValueError("Power exponent must have magnitude at most 1000.")
    if base == 0 and exponent < 0:
        raise ValueError("Zero cannot be raised to a negative power.")
    if base < 0 and not exponent.is_integer():
        raise ValueError("A negative base requires an integer exponent for a real result.")
    try:
        return _result(base**exponent)
    except OverflowError as error:
        raise ValueError("Power calculation exceeds the supported numeric range.") from error
