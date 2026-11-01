"""Exact structural counts from the resolved IR; no hardware or numerical model."""

from dataclasses import dataclass, fields

from .ir import CircuitIR, GateKind, MAX_DIMENSION


RESOURCE_OBJECTIVES = ("physical_registers", "max_register_dimension", "unused_basis_states",
                       "gate_count", "two_register_gate_count", "dependency_depth")


def checked_objectives(objectives):
    if type(objectives) is not tuple:
        raise TypeError("Q3-SEARCH-001: objectives must be an exact tuple")
    if (not objectives or len(objectives) > len(RESOURCE_OBJECTIVES) or
            any(type(name) is not str or name not in RESOURCE_OBJECTIVES for name in objectives) or
            len(set(objectives)) != len(objectives)):
        raise ValueError("Q3-SEARCH-001: objectives must be distinct known resource names")
    return objectives


@dataclass(frozen=True)
class ResourceCounts:
    physical_registers: int
    max_register_dimension: int
    unused_basis_states: int
    gate_count: int
    two_register_gate_count: int
    dependency_depth: int

    def __post_init__(self):
        values = tuple(getattr(self, item.name) for item in fields(self))
        if any(type(value) is not int for value in values):
            raise TypeError("Q3-SEARCH-005: resource counts must be exact integers")
        if (self.physical_registers < 1 or not 2 <= self.max_register_dimension <= MAX_DIMENSION or
                any(value < 0 for value in values) or
                self.two_register_gate_count > self.gate_count or
                (self.two_register_gate_count > 0 and self.physical_registers < 2) or
                self.dependency_depth > self.gate_count or
                (self.gate_count == 0) != (self.dependency_depth == 0)):
            raise ValueError("Q3-SEARCH-005: inconsistent structural resource counts")

    def to_dict(self):
        return {item.name: getattr(self, item.name) for item in fields(self)}

    def as_tuple(self, objectives=RESOURCE_OBJECTIVES):
        return tuple(getattr(self, name) for name in checked_objectives(objectives))


def count_resources(circuit, *, logical_size):
    """Count primitive operations and longest touched-axis dependency layers."""
    if not isinstance(circuit, CircuitIR) or type(logical_size) is not int:
        raise TypeError("Q3-SEARCH-001: expected a CircuitIR and an exact logical size")
    if not 2 <= logical_size <= circuit.state_size:
        raise ValueError("Q3-SEARCH-001: logical size must be between 2 and physical capacity")
    layers = [0] * len(circuit.registers)
    two_register = 0
    for operation in circuit.operations:
        axes = (operation.target,)
        if operation.kind is GateKind.SUM:
            axes += (operation.control,)
            two_register += 1
        layer = 1 + max(layers[axis] for axis in axes)
        for axis in axes:
            layers[axis] = layer
    return ResourceCounts(len(circuit.registers), max(circuit.dimensions),
        circuit.state_size - logical_size, len(circuit.operations), two_register, max(layers))
