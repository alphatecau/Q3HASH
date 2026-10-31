"""Explicit computational-basis injections; independent of programs and verification."""

from dataclasses import dataclass
import math

from . import _serialization as wire
from ._state import checked_vector
from .ir import MAX_DIMENSION


MAX_MAPPING_ENTRIES = 65_536
MAX_VECTOR_AMPLITUDES = 65_536
SCHEMA = "q3hash.basis-encoding"
_FIELDS = ("schema", "schema_version", "kind", "logical_dimensions",
           "physical_dimensions", "physical_basis_indices")


def _dimensions(values):
    if not values or any(type(value) is not int or not 2 <= value <= MAX_DIMENSION for value in values):
        raise ValueError("Q3-ENC-001: dimensions must be nonempty exact integers in 2..32")


@dataclass(frozen=True)
class BasisEncoding:
    logical_dimensions: tuple[int, ...]
    physical_dimensions: tuple[int, ...]
    physical_basis_indices: tuple[int, ...]

    def __post_init__(self):
        # All direct container types are checked before any semantic validation.
        for values in (self.logical_dimensions, self.physical_dimensions):
            if type(values) is not tuple:
                raise TypeError("Q3-ENC-001: dimension fields must be exact tuples")
        if type(self.physical_basis_indices) is not tuple:
            raise TypeError("Q3-ENC-003: mapping must be an exact tuple")
        _dimensions(self.logical_dimensions)
        _dimensions(self.physical_dimensions)
        if self.physical_size < self.logical_size:
            raise ValueError("Q3-ENC-002: physical capacity is below logical capacity")
        if self.logical_size > MAX_MAPPING_ENTRIES:
            raise ValueError("Q3-ENC-006: explicit logical mapping exceeds 65536 entries")
        mapping = self.physical_basis_indices
        if len(mapping) != self.logical_size or any(type(index) is not int for index in mapping):
            raise ValueError("Q3-ENC-003: mapping requires one exact integer per logical basis state")
        if any(not 0 <= index < self.physical_size for index in mapping):
            raise ValueError("Q3-ENC-005: mapped physical index is out of range")
        if len(set(mapping)) != len(mapping):
            raise ValueError("Q3-ENC-004: encoding map must be injective")

    @property
    def logical_size(self):
        return math.prod(self.logical_dimensions)

    @property
    def physical_size(self):
        return math.prod(self.physical_dimensions)

    def encode_vector(self, logical_state):
        state = checked_vector(logical_state, self.logical_size)
        if self.physical_size > MAX_VECTOR_AMPLITUDES:
            raise ValueError("Q3-STATE-003: physical output exceeds 65536 amplitudes")
        result = [0j] * self.physical_size
        for index, amplitude in zip(self.physical_basis_indices, state):
            result[index] = amplitude
        return tuple(result)

    def isometry_matrix(self, *, max_physical_dimension=64):
        if type(max_physical_dimension) is not int:
            raise TypeError("Q3-DENSE-001: dense limit must be an exact positive integer")
        if max_physical_dimension <= 0 or self.physical_size > max_physical_dimension:
            raise ValueError("Q3-DENSE-001: requested isometry exceeds the dense limit")
        positions = {physical: logical for logical, physical in enumerate(self.physical_basis_indices)}
        return tuple(tuple(complex(positions.get(row) == column) for column in range(self.logical_size))
                     for row in range(self.physical_size))

    def to_dict(self):
        return {"schema": SCHEMA, "schema_version": 1, "kind": "basis-injection",
                "logical_dimensions": list(self.logical_dimensions),
                "physical_dimensions": list(self.physical_dimensions),
                "physical_basis_indices": list(self.physical_basis_indices)}

    def to_json(self):
        return wire.write_json(self.to_dict())

    @classmethod
    def from_dict(cls, value):
        wire.header(value, SCHEMA, _FIELDS, kind="basis-injection")
        fields = [wire.array(value[name]) for name in
                  ("logical_dimensions", "physical_dimensions", "physical_basis_indices")]
        if any(type(item) is not int for array in fields[:2] for item in array):
            raise ValueError("Q3-SER-003: dimension arrays require exact integers")
        _dimensions(fields[0])
        _dimensions(fields[1])
        logical_size, physical_size = math.prod(fields[0]), math.prod(fields[1])
        if physical_size < logical_size:
            raise ValueError("Q3-ENC-002: physical capacity is below logical capacity")
        if logical_size > MAX_MAPPING_ENTRIES:
            raise ValueError("Q3-ENC-006: explicit logical mapping exceeds 65536 entries")
        if len(fields[2]) != logical_size:
            raise ValueError("Q3-ENC-003: mapping requires one index per logical basis state")
        if any(type(item) is not int for item in fields[2]):
            raise ValueError("Q3-SER-003: dimension and mapping arrays require exact integers")
        return cls(*(tuple(array) for array in fields))

    @classmethod
    def from_json(cls, text):
        return cls.from_dict(wire.read_json(text))
