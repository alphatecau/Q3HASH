"""Validated circuit models and a dimension-aware, resolved intermediate form."""

from dataclasses import dataclass
from enum import Enum
import math
import re
from typing import Optional, Tuple


MAX_DIMENSION = 32
_NAME = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")


def _name(value: str) -> None:
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise ValueError(f"invalid register name {value!r}")


class GateKind(str, Enum):
    SHIFT = "shift"
    FOURIER = "fourier"
    SUM = "sum"


def _kind(value: str) -> GateKind:
    try:
        return GateKind(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"unsupported gate {value!r}") from error


@dataclass(frozen=True)
class Register:
    name: str
    dimension: int

    def __post_init__(self) -> None:
        _name(self.name)
        if type(self.dimension) is not int or not 2 <= self.dimension <= MAX_DIMENSION:
            raise ValueError("dimension must be an integer between 2 and 32")


@dataclass(frozen=True)
class Gate:
    # Keep the original Gate(kind, target) constructor for single-register gates.
    kind: GateKind
    target: str
    control: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _kind(self.kind))
        _name(self.target)
        if self.kind is GateKind.SUM:
            if self.control is None:
                raise ValueError("sum requires a control register")
            _name(self.control)
            if self.control == self.target:
                raise ValueError("control and target must be different registers")
        elif self.control is not None:
            raise ValueError(f"{self.kind.value} does not accept a control register")


def _registers(values: Tuple[Register, ...]) -> Tuple[Register, ...]:
    try:
        result = tuple(values)
    except TypeError as error:
        raise ValueError("registers must be a sequence of Register objects") from error
    if not result:
        raise ValueError("a circuit requires at least one register")
    names = set()
    for register in result:
        if not isinstance(register, Register):
            raise ValueError("registers must contain Register objects")
        if register.name in names:
            raise ValueError(f"register {register.name!r} already exists")
        names.add(register.name)
    return result


def _sequence(values, item_type, label):
    try:
        result = tuple(values)
    except TypeError as error:
        raise ValueError(f"{label} must be a sequence") from error
    if any(not isinstance(value, item_type) for value in result):
        raise ValueError(f"{label} must contain {item_type.__name__} objects")
    return result


@dataclass(frozen=True)
class Circuit:
    registers: Tuple[Register, ...]
    gates: Tuple[Gate, ...]

    def __post_init__(self) -> None:
        registers = _registers(self.registers)
        gates = _sequence(self.gates, Gate, "gates")
        names = {register.name for register in registers}
        for gate in gates:
            for name in (gate.target, gate.control):
                if name is not None and name not in names:
                    raise ValueError(f"unknown register {name!r}")
        object.__setattr__(self, "registers", registers)
        object.__setattr__(self, "gates", gates)


@dataclass(frozen=True)
class Operation:
    """A typed gate with resolved register indices; SUM retains operand order."""

    kind: GateKind
    target: int
    control: Optional[int] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _kind(self.kind))
        if type(self.target) is not int or self.target < 0:
            raise ValueError("target index must be a non-negative integer")
        if self.kind is GateKind.SUM:
            if type(self.control) is not int or self.control < 0:
                raise ValueError("sum requires a non-negative integer control index")
            if self.control == self.target:
                raise ValueError("control and target must be different registers")
        elif self.control is not None:
            raise ValueError(f"{self.kind.value} does not accept a control index")


@dataclass(frozen=True)
class CircuitIR:
    """Resolved operations over an ordered, validated mixed-dimensional register set."""

    registers: Tuple[Register, ...]
    operations: Tuple[Operation, ...]

    def __post_init__(self) -> None:
        registers = _registers(self.registers)
        operations = _sequence(self.operations, Operation, "operations")
        for operation in operations:
            for index in (operation.target, operation.control):
                if index is not None and index >= len(registers):
                    raise ValueError(f"register index {index} is out of range")
        object.__setattr__(self, "registers", registers)
        object.__setattr__(self, "operations", operations)

    @property
    def dimensions(self) -> Tuple[int, ...]:
        return tuple(register.dimension for register in self.registers)

    @property
    def state_size(self) -> int:
        return math.prod(self.dimensions)

    @property
    def strides(self) -> Tuple[int, ...]:
        dimensions = self.dimensions
        return tuple(math.prod(dimensions[index + 1:]) for index in range(len(dimensions)))


def lower(circuit: Circuit) -> CircuitIR:
    """Resolve validated names to axes; this pass performs no dimension inference."""
    if not isinstance(circuit, Circuit):
        raise TypeError("lower expects a Circuit")
    indices = {register.name: index for index, register in enumerate(circuit.registers)}
    return CircuitIR(
        circuit.registers,
        tuple(
            Operation(
                gate.kind,
                indices[gate.target],
                None if gate.control is None else indices[gate.control],
            )
            for gate in circuit.gates
        ),
    )
