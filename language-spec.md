# Q3# prototype notation (v0.1; experimental)

This is a deliberately small **interpreted** subset, not a full compiler specification.

## Current syntax

- `qubit <name>` declares a dimension-2 register.
- `qutrit <name>` declares a dimension-3 register.
- `qudit <dimension> <name>` declares an integer dimension from 2 through 32.
- `shift <name>` cyclically increments that register's computational basis label mod `d`.
- `fourier <name>` applies a dimension-`d` discrete Fourier transform, with matrix entry `exp(2πijk/d)/sqrt(d)`.
- Comments start with `#`. One instruction per line; names use letters/underscores then letters/digits/underscores.
- Registers begin in `|0>`; their joint state starts in `|0...0>`.

Instructions apply to one register at a time. Mixed dimensions are represented by tensor-product statevectors, with the **last** register varying fastest. The simulator does not implement measurement, entangling gates, parameterised rotations, noise, backends or hardware execution.

## Proposed language evolution (not implemented)

- Quantum/classical declarations, functions, types and hybrid control flow.
- Multi-register operations and entanglement.
- Measurement syntax and shot-based execution.
- Dimension inference and comparative encoding search.
- Typed intermediate representation and hardware-specific code generation.
- Semantics-backed optimisation and verification.
