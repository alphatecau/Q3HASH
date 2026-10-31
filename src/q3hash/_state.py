"""Finite built-in amplitudes for linear APIs; no normalisation or coercion."""

import math


def checked_vector(values, size):
    if type(values) is not tuple:
        raise TypeError("Q3-STATE-001: state must be an exact tuple")
    if len(values) != size or any(type(value) not in (int, float, complex) for value in values):
        raise ValueError("Q3-STATE-001: incorrect state length or amplitude type")
    result = []
    for value in values:
        try:
            amplitude = complex(value)
        except (ValueError, OverflowError) as error:
            raise ValueError("Q3-STATE-002: unrepresentable amplitude") from error
        if not math.isfinite(amplitude.real) or not math.isfinite(amplitude.imag):
            raise ValueError("Q3-STATE-002: amplitude must be finite")
        result.append(amplitude)
    return tuple(result)
