"""Complete small operators and phase-sensitive encoded-subspace mathematics."""

from dataclasses import dataclass
import math

from .core import apply_state
from .ir import CircuitIR, MAX_DIMENSION


MAX_DENSE_DIMENSION = 64
MAX_REFERENCE_ENTRIES = 65_536


def dense_limit(value):
    if type(value) is not int:
        raise TypeError("Q3-VERIFY-002: dense limit must be an exact integer")
    if not 1 <= value <= MAX_DENSE_DIMENSION:
        raise ValueError("Q3-VERIFY-002: dense limit must be in 1..64")
    return value


@dataclass(frozen=True)
class ReferenceOperator:
    """Finite explicit physical matrix, without any assumption of unitarity."""

    dimensions: tuple
    matrix: tuple

    def __post_init__(self):
        if type(self.dimensions) is not tuple or type(self.matrix) is not tuple:
            raise TypeError("Q3-REF-001: dimensions and matrix must be exact tuples")
        if not self.dimensions or any(type(d) is not int or not 2 <= d <= MAX_DIMENSION
                                      for d in self.dimensions):
            raise ValueError("Q3-REF-001: invalid physical dimensions")
        size = self.state_size
        if size * size > MAX_REFERENCE_ENTRIES:
            raise ValueError("Q3-REF-003: explicit reference exceeds 65536 matrix entries")
        if len(self.matrix) != size or any(type(row) is not tuple or len(row) != size for row in self.matrix):
            raise ValueError("Q3-REF-001: matrix must have physical_size squared entries in tuple rows")
        rows = []
        for row in self.matrix:
            values = []
            for value in row:
                if type(value) not in (int, float, complex):
                    raise ValueError("Q3-REF-002: matrix entries must be built-in finite numbers")
                try:
                    value = complex(value)
                except (ValueError, OverflowError) as error:
                    raise ValueError("Q3-REF-002: unrepresentable matrix entry") from error
                if not math.isfinite(value.real) or not math.isfinite(value.imag):
                    raise ValueError("Q3-REF-002: matrix entries must be finite")
                values.append(value)
            rows.append(tuple(values))
        object.__setattr__(self, "matrix", tuple(rows))

    @property
    def state_size(self):
        return math.prod(self.dimensions)


def operator_matrix(ir, *, max_dimension=64):
    """All basis columns of a small CircuitIR; never infer its role or encoding."""
    if not isinstance(ir, CircuitIR):
        raise TypeError("Q3-COMP-001: operator construction requires a CircuitIR")
    dense_limit(max_dimension)
    size = ir.state_size
    if size > max_dimension:
        raise ValueError("Q3-DENSE-001: operator exceeds the declared dense limit")
    columns = [apply_state(ir, tuple(complex(row == column) for row in range(size)))
               for column in range(size)]
    return tuple(tuple(columns[column][row] for column in range(size)) for row in range(size))


def _norm(values):
    return math.hypot(*(abs(value) for value in values))


def _unitarity(matrix):
    size = len(matrix)
    return _norm(sum(matrix[k][row].conjugate() * matrix[k][column] for k in range(size))
                 - int(row == column) for row in range(size) for column in range(size))


@dataclass(frozen=True)
class EquivalenceMetrics:
    global_phase: complex
    subspace_residual: float
    leakage_norm: float
    logical_unitarity_error: float
    physical_unitarity_error: float


def compare_operators(logical_matrix, physical_matrix, encoding):
    """Internal mathematics after the verifier's typed, dimensional preflight."""
    logical_size, physical_size = encoding.logical_size, encoding.physical_size
    mapping = encoding.physical_basis_indices
    inverse = {physical: logical for logical, physical in enumerate(mapping)}
    left = tuple(tuple(physical_matrix[row][mapping[column]] for column in range(logical_size))
                 for row in range(physical_size))
    right = tuple(tuple(logical_matrix[inverse[row]][column] if row in inverse else 0j
                        for column in range(logical_size)) for row in range(physical_size))
    inner = sum(right[row][column].conjugate() * left[row][column]
                for row in range(physical_size) for column in range(logical_size))
    phase = inner / abs(inner) if inner != 0 else 1 + 0j
    residual = _norm(left[row][column] - phase * right[row][column]
                     for row in range(physical_size) for column in range(logical_size))
    leakage = _norm(left[row][column] for row in range(physical_size) if row not in inverse
                    for column in range(logical_size))
    return EquivalenceMetrics(phase, residual, leakage, _unitarity(logical_matrix), _unitarity(physical_matrix))
