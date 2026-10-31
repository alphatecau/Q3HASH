"""Minimal mixed-dimensional circuit representation and statevector simulator."""
from dataclasses import dataclass
import cmath
import math
import re
from typing import Tuple

@dataclass(frozen=True)
class Register:
    name: str
    dimension: int

@dataclass(frozen=True)
class Gate:
    kind: str
    target: str

@dataclass(frozen=True)
class Circuit:
    registers: Tuple[Register, ...]
    gates: Tuple[Gate, ...]

def parse(source: str) -> Circuit:
    registers = []
    gates = []
    for line_number, raw in enumerate(source.splitlines(), 1):
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r'(qubit|qutrit|qudit\s+\d+)\s+([A-Za-z_][A-Za-z_0-9]*)', line)
        if match:
            kind, name = match.groups()
            dim = 2 if kind == 'qubit' else 3 if kind == 'qutrit' else int(kind.split()[1])
            if not 2 <= dim <= 32:
                raise ValueError(f'line {line_number}: dimension must be between 2 and 32')
            if any(r.name == name for r in registers):
                raise ValueError(f'line {line_number}: register {name!r} already exists')
            registers.append(Register(name, dim))
            continue
        match = re.fullmatch(r'(shift|fourier)\s+([A-Za-z_][A-Za-z_0-9]*)', line)
        if match:
            kind, name = match.groups()
            if not any(r.name == name for r in registers):
                raise ValueError(f'line {line_number}: unknown register {name!r}')
            gates.append(Gate(kind, name))
            continue
        raise ValueError(f'line {line_number}: invalid instruction {line!r}')
    if not registers:
        raise ValueError('a circuit requires at least one register')
    return Circuit(tuple(registers), tuple(gates))

def simulate(circuit: Circuit) -> Tuple[complex, ...]:
    dims = [r.dimension for r in circuit.registers]
    names = [r.name for r in circuit.registers]
    size = math.prod(dims)
    if size > 65536:
        raise ValueError('statevector too large for experimental simulator (limit 65536 amplitudes)')
    state = [0j] * size
    state[0] = 1 + 0j
    for gate in circuit.gates:
        axis = names.index(gate.target)
        dim = dims[axis]
        stride = math.prod(dims[axis + 1:])
        period = dim * stride
        result = [0j] * size
        for start in range(0, size, period):
            for offset in range(stride):
                original = [state[start + j * stride + offset] for j in range(dim)]
                if gate.kind == 'shift':
                    transformed = [original[(j - 1) % dim] for j in range(dim)]
                elif gate.kind == 'fourier':
                    norm = math.sqrt(dim)
                    transformed = [sum(original[k] * cmath.exp(2j * math.pi * j * k / dim) for k in range(dim)) / norm for j in range(dim)]
                else:
                    raise ValueError(f'unsupported gate {gate.kind}')
                for j, amp in enumerate(transformed):
                    result[start + j * stride + offset] = amp
        state = result
    return tuple(state)

def probabilities(state: Tuple[complex, ...]) -> Tuple[float, ...]:
    return tuple(abs(a) ** 2 for a in state)
