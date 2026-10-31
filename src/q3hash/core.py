"""Parser and pure-Python mixed-dimensional statevector interpreter."""

import cmath
from functools import lru_cache
import math
import re
from typing import Tuple, Union

from .ir import Circuit, CircuitIR, Gate, GateKind, Register, lower


MAX_AMPLITUDES = 65_536
_IDENTIFIER = r"[A-Za-z_][A-Za-z_0-9]*"


def parse(source: str) -> Circuit:
    if not isinstance(source, str):
        raise TypeError("source must be a string")
    registers = []
    gates = []
    names = set()
    for line_number, raw in enumerate(source.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        try:
            declaration = re.fullmatch(
                rf"(qubit|qutrit|qudit\s+[0-9]+)\s+({_IDENTIFIER})", line
            )
            if declaration:
                kind, name = declaration.groups()
                dimension = 2 if kind == "qubit" else 3 if kind == "qutrit" else int(kind.split()[1])
                register = Register(name, dimension)
                if name in names:
                    raise ValueError(f"register {name!r} already exists")
                registers.append(register)
                names.add(name)
                continue
            single = re.fullmatch(rf"(shift|fourier)\s+({_IDENTIFIER})", line)
            controlled = re.fullmatch(rf"sum\s+({_IDENTIFIER})\s+({_IDENTIFIER})", line)
            if single:
                kind, target = single.groups()
                gate = Gate(kind, target)
            elif controlled:
                control, target = controlled.groups()
                gate = Gate("sum", target, control)
            else:
                raise ValueError(f"invalid instruction {line!r}")
            for name in (gate.target, gate.control):
                if name is not None and name not in names:
                    raise ValueError(f"unknown register {name!r}")
            gates.append(gate)
        except ValueError as error:
            raise ValueError(f"line {line_number}: {error}") from error
    return Circuit(tuple(registers), tuple(gates))


@lru_cache(maxsize=31)
def _fourier_matrix(dimension: int) -> Tuple[Tuple[complex, ...], ...]:
    norm = math.sqrt(dimension)
    return tuple(
        tuple(cmath.exp(2j * math.pi * row * column / dimension) / norm for column in range(dimension))
        for row in range(dimension)
    )


def simulate(circuit: Union[Circuit, CircuitIR]) -> Tuple[complex, ...]:
    if isinstance(circuit, Circuit):
        circuit = lower(circuit)
    if not isinstance(circuit, CircuitIR):
        raise TypeError("simulate expects a Circuit or CircuitIR")
    dimensions = circuit.dimensions
    size = circuit.state_size
    if size > MAX_AMPLITUDES:
        raise ValueError("statevector too large for experimental simulator (limit 65536 amplitudes)")
    strides = circuit.strides
    state = [0j] * size
    state[0] = 1 + 0j
    for operation in circuit.operations:
        dimension = dimensions[operation.target]
        stride = strides[operation.target]
        result = [0j] * size
        if operation.kind is GateKind.SUM:
            # For each fixed control value this is a bijective target permutation,
            # including when control and target have different dimensions.
            control_stride = strides[operation.control]
            control_dimension = dimensions[operation.control]
            for index, amplitude in enumerate(state):
                control = (index // control_stride) % control_dimension
                target = (index // stride) % dimension
                destination = index + (((target + control) % dimension) - target) * stride
                result[destination] = amplitude
        else:
            period = dimension * stride
            matrix = _fourier_matrix(dimension) if operation.kind is GateKind.FOURIER else None
            for start in range(0, size, period):
                for offset in range(stride):
                    original = [state[start + column * stride + offset] for column in range(dimension)]
                    if operation.kind is GateKind.SHIFT:
                        transformed = [original[(row - 1) % dimension] for row in range(dimension)]
                    else:
                        transformed = [
                            sum(matrix[row][column] * original[column] for column in range(dimension))
                            for row in range(dimension)
                        ]
                    for row, amplitude in enumerate(transformed):
                        result[start + row * stride + offset] = amplitude
        state = result
    return tuple(state)


def probabilities(state: Tuple[complex, ...]) -> Tuple[float, ...]:
    return tuple(abs(amplitude) ** 2 for amplitude in state)
