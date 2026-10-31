"""Independent NumPy/SciPy small-operator and explicit-encoding audit."""

import importlib.metadata
import math
import sys

try:
    import numpy as np
    import scipy
    from scipy.linalg import dft
except ImportError as error:
    raise SystemExit("Install optional validation dependencies: python -m pip install '.[validation]'") from error

from q3hash import (BasisEncoding, Circuit, CircuitIR, Gate, LogicalProgram, ReferenceOperator,
                    Register, apply_state, logical_from_source, lower, verify_equivalence)
from q3hash.equivalence import operator_matrix


SEED = 20261101
TOLERANCE = 1e-10


def reference(dimensions, gates):
    """Dense tensor-basis matrices, independently built without core helpers."""
    size = math.prod(dimensions)
    unitary = np.eye(size, dtype=complex)
    for kind, target, control in gates:
        gate = np.zeros((size, size), dtype=complex)
        dimension = dimensions[target]
        fourier = dft(dimension, scale="sqrtn").conjugate() if kind == "fourier" else None
        for labels in np.ndindex(dimensions):
            column = np.ravel_multi_index(labels, dimensions)
            outputs = (range(dimension) if kind == "fourier" else
                       [int((labels[target] + (1 if kind == "shift" else labels[control])) % dimension)])
            for value in outputs:
                output = list(labels)
                output[target] = value
                row = np.ravel_multi_index(tuple(output), dimensions)
                gate[row, column] = fourier[value, labels[target]] if fourier is not None else 1
        unitary = gate @ unitary
    return unitary


def program(dimensions, gates):
    registers = tuple(Register(f"q{axis}", dimension) for axis, dimension in enumerate(dimensions))
    operations = tuple(Gate(kind, f"q{target}", None if control is None else f"q{control}")
                       for kind, target, control in gates)
    return LogicalProgram(lower(Circuit(registers, operations)))


def main():
    generator = np.random.default_rng(SEED)
    operator_checks = 0
    embedding_checks = 0
    verified = 0
    unsupported = 0
    rejected = 0
    maximum_error = 0.0
    maximum_residual = 0.0

    def check_operator(dimensions, gates):
        nonlocal operator_checks, maximum_error
        logical = program(dimensions, gates)
        expected = reference(dimensions, gates)
        actual = np.asarray(operator_matrix(logical.ir))
        error = float(np.max(np.abs(actual - expected)))
        # Unnormalised complex inputs exercise the additive linear API too.
        vector = 3 * (generator.normal(size=logical.state_size) + 1j * generator.normal(size=logical.state_size))
        applied = np.asarray(apply_state(logical.ir, tuple(complex(value) for value in vector)))
        vector_error = float(np.max(np.abs(applied - expected @ vector)))
        if not np.all(np.isfinite(actual)) or max(error, vector_error) > TOLERANCE:
            raise AssertionError(("operator", dimensions, gates, error, vector_error))
        maximum_error = max(maximum_error, error, vector_error)
        operator_checks += 1
        return logical, expected

    for dimension in range(2, 33):
        for kind in ("shift", "fourier"):
            logical, unitary = check_operator((dimension,), [(kind, 0, None)])
            for base in (2, 3):
                capacity, count = base, 1
                while capacity < dimension:
                    capacity *= base
                    count += 1
                for permuted in (False, True):
                    step = (3 if base == 2 else 2) if permuted else 1
                    offset = int(permuted)
                    mapping = tuple((step * index + offset) % capacity for index in range(dimension))
                    encoding = BasisEncoding((dimension,), (base,) * count, mapping)
                    isometry = np.zeros((capacity, dimension), dtype=complex)
                    isometry[np.asarray(mapping), np.arange(dimension)] = 1
                    if not np.array_equal(np.asarray(encoding.isometry_matrix(max_physical_dimension=capacity)), isometry):
                        raise AssertionError("isometry matrix differs from independent index assignment")
                    vector = tuple(complex(value) for value in generator.normal(size=dimension))
                    if not np.array_equal(np.asarray(encoding.encode_vector(vector)), isometry @ np.asarray(vector)):
                        raise AssertionError("matrix-free encoding differs from independent isometry")
                    embedding_checks += 1
                    phase = np.exp(0.37j) if permuted else 1
                    physical = isometry @ (phase * unitary) @ isometry.conj().T + np.eye(capacity) - isometry @ isometry.conj().T
                    candidate = ReferenceOperator(encoding.physical_dimensions,
                                                  tuple(tuple(complex(value) for value in row) for row in physical))
                    report = verify_equivalence(logical, candidate, encoding)
                    if capacity > 64:
                        if report.status != "unsupported":
                            raise AssertionError("oversized dense comparison was not unsupported")
                        unsupported += 1
                    else:
                        if report.status != "pass" or report.evidence != "reference-only":
                            raise AssertionError(("encoded reference", dimension, base, permuted, report))
                        maximum_residual = max(maximum_residual, report.subspace_residual)
                        verified += 1

    for control_dimension in range(2, 9):
        for target_dimension in range(2, 9):
            for control in (0, 1):
                target = 1 - control
                dimensions = ((control_dimension, target_dimension) if control == 0 else
                              (target_dimension, control_dimension))
                check_operator(dimensions, [("sum", target, control)])
    for target in range(3):
        check_operator((2, 3, 4), [("fourier", target, None)])
        for control in range(3):
            if control != target:
                check_operator((2, 3, 4), [("fourier", control, None), ("sum", target, control),
                                          ("shift", target, None)])

    for dimensions, physical_dimensions in (((2, 3), (3, 2)), ((2, 3, 4), (3, 2, 2, 2))):
        for _ in range(12):
            gates = [("fourier", 0, None), ("sum", 1, 0), ("fourier", 1, None), ("shift", 0, None)]
            logical, unitary = check_operator(dimensions, gates)
            size = math.prod(dimensions)
            mapping = tuple(int(value) for value in generator.permutation(size))
            encoding = BasisEncoding(dimensions, physical_dimensions, mapping)
            isometry = np.eye(size, dtype=complex)[np.argsort(mapping)]
            physical = isometry @ unitary @ isometry.conj().T
            candidate = ReferenceOperator(physical_dimensions,
                                          tuple(tuple(complex(value) for value in row) for row in physical))
            report = verify_equivalence(logical, candidate, encoding)
            if report.status != "pass":
                raise AssertionError(("permuted mixed dimensions", report))
            maximum_residual = max(maximum_residual, report.subspace_residual)
            verified += 1

    logical = logical_from_source("qutrit q\nshift q")
    encoding = BasisEncoding((3,), (2, 2), (0, 1, 2))
    physical_ir = lower(Circuit((Register("a", 2), Register("b", 2)),
                                (Gate("sum", "b", "a"), Gate("sum", "a", "b"), Gate("shift", "b"))))
    report = verify_equivalence(logical, physical_ir, encoding)
    if report.status != "pass" or report.evidence != "q3hash-circuit":
        raise AssertionError("explicit three-gate physical circuit did not verify")
    verified += 1

    _, logical_matrix = check_operator((3,), [("shift", 0, None)])
    isometry = np.eye(4, dtype=complex)[:, :3]
    good = isometry @ logical_matrix @ isometry.conj().T + np.diag([0, 0, 0, 1])
    relative_phase = good @ np.diag([1, -1, 1, 1])
    leaking = np.eye(4, dtype=complex)[[3, 1, 2, 0]] @ good
    nonunitary = good @ np.diag([1, 1, 1, 0])
    for invalid in (relative_phase, leaking, nonunitary):
        candidate = ReferenceOperator((2, 2), tuple(tuple(complex(value) for value in row) for row in invalid))
        if verify_equivalence(logical, candidate, encoding).status != "fail":
            raise AssertionError("adversarial reference was not rejected")
        rejected += 1

    print("Independent encoding and operator audit: passed")
    print(f"Python {sys.version.split()[0]} | q3hash {importlib.metadata.version('q3hash')} | "
          f"NumPy {np.__version__} | SciPy {scipy.__version__} | seed {SEED}")
    print(f"Complete operator and arbitrary-state comparisons: {operator_checks}")
    print(f"Independent basis embeddings: {embedding_checks}")
    print(f"Full-subspace passes: {verified} | declared dense-limit unsupported: {unsupported} | adversarial failures: {rejected}")
    print(f"Maximum independent amplitude error: {maximum_error:.17g}")
    print(f"Maximum passing subspace residual: {maximum_residual:.17g} | tolerance {TOLERANCE}")
    print("Evidence: numerical full small operators; reference matrices remain reference-only; no hardware execution.")


if __name__ == "__main__":
    main()
