"""Independent NumPy/SciPy statevector comparisons; optional validation dependencies."""

import importlib.metadata
import json
import math
import random
import sys
from functools import lru_cache

try:
    import numpy as np
    import scipy
    from scipy.linalg import dft, svdvals
except ImportError as error:
    raise SystemExit("Install optional validation dependencies: python -m pip install '.[validation]'") from error

from q3hash import Circuit, Gate, Register, simulate


SEED = 20261031
TOLERANCE = 1e-11


@lru_cache(maxsize=31)
def positive_fourier(dimension):
    # SciPy uses a negative exponent; conjugation matches Q3#'s documented sign.
    return dft(dimension, scale="sqrtn").conjugate()


def reference(dimensions, operations):
    state = np.zeros(dimensions, dtype=complex)
    state[(0,) * len(dimensions)] = 1
    for kind, target, control in operations:
        if kind == "shift":
            state = np.roll(state, 1, axis=target)
        elif kind == "fourier":
            state = np.moveaxis(np.tensordot(positive_fourier(dimensions[target]), state,
                                            axes=(1, target)), 0, target)
        elif kind == "sum":
            result = np.empty_like(state)
            for label in range(dimensions[control]):
                selection = [slice(None)] * len(dimensions)
                selection[control] = label
                selection = tuple(selection)
                axis = target - int(control < target)
                result[selection] = np.roll(state[selection], label, axis=axis)
            state = result
        else:
            raise ValueError(kind)
    return state.reshape(-1)


def production(dimensions, operations):
    registers = tuple(Register(f"q{axis}", dimension) for axis, dimension in enumerate(dimensions))
    gates = tuple(Gate(kind, f"q{target}", None if control is None else f"q{control}")
                  for kind, target, control in operations)
    return np.asarray(simulate(Circuit(registers, gates)))


def main():
    count = 0
    maximum_error = 0.0
    maximum_norm_error = 0.0

    def compare(dimensions, operations):
        nonlocal count, maximum_error, maximum_norm_error
        actual = production(dimensions, operations)
        expected = reference(dimensions, operations)
        error = float(np.max(np.abs(actual - expected)))
        norm_error = abs(float(np.vdot(actual, actual).real) - 1)
        if not np.all(np.isfinite(actual)) or error > TOLERANCE or norm_error > TOLERANCE:
            raise AssertionError((dimensions, operations, error, norm_error))
        maximum_error = max(maximum_error, error)
        maximum_norm_error = max(maximum_norm_error, norm_error)
        count += 1
        return actual

    for dimension in range(2, 33):
        for column in range(dimension):
            operations = [("shift", 0, None)] * column + [("fourier", 0, None)]
            compare((dimension,), operations)

    for control_dimension in range(2, 33):
        for target_dimension in range(2, 33):
            for control in (0, 1):
                target = 1 - control
                dimensions = ((control_dimension, target_dimension) if control == 0 else
                              (target_dimension, control_dimension))
                operations = [("shift", control, None), ("fourier", control, None),
                              ("shift", target, None), ("sum", target, control)]
                compare(dimensions, operations)

    generator = random.Random(SEED)
    for dimensions in ((2, 3), (3, 2), (2, 3, 4), (3, 2, 5), (4, 3, 2), (7, 5)):
        for _ in range(20):
            operations = []
            for _ in range(20):
                kind = generator.choice(("shift", "fourier", "sum"))
                target = generator.randrange(len(dimensions))
                control = (generator.choice([axis for axis in range(len(dimensions)) if axis != target])
                           if kind == "sum" else None)
                operations.append((kind, target, control))
            compare(dimensions, operations)

    for left, right, purity in ((2, 2, 0.5), (3, 3, 1 / 3), (2, 3, 0.5), (3, 2, 5 / 9)):
        state = compare((left, right), [("fourier", 0, None), ("sum", 1, 0)])
        singular_values = svdvals(state.reshape(left, right))
        if abs(float(np.sum(singular_values ** 4)) - purity) > TOLERANCE:
            raise AssertionError(("reduced purity", left, right))

    print(json.dumps({
        "python": sys.version.split()[0], "q3hash": importlib.metadata.version("q3hash"),
        "numpy": np.__version__, "scipy": scipy.__version__, "seed": SEED,
        "dimensions": [2, 32], "statevector_comparisons": count,
        "maximum_amplitude_error": maximum_error, "maximum_norm_error": maximum_norm_error,
        "tolerance": TOLERANCE, "result": "passed",
    }, indent=2))


if __name__ == "__main__":
    main()
