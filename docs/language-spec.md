# Q3# prototype notation (v0.2; experimental)

This specification describes the executable interpreter subset. It is not a specification for a complete compiler.

Package v0.3 adds a separate logical wrapper, explicit basis encodings and complete small-operator verification without changing this v0.2 source grammar. Logical and physical programs each use the existing notation with their own explicit dimensions; neither is inferred from the other.

## Syntax

| Instruction | Meaning |
| --- | --- |
| `qubit <name>` | Declare a dimension-2 register |
| `qutrit <name>` | Declare a dimension-3 register |
| `qudit <dimension> <name>` | Declare an integer dimension from 2 through 32 |
| `shift <target>` | Increment the target basis label modulo its dimension |
| `fourier <target>` | Apply the positive-exponent, normalised discrete Fourier transform |
| `sum <control> <target>` | Add the control basis label to the target modulo the target dimension |

One instruction per line. Comments begin with `#`. Identifiers match `[A-Za-z_][A-Za-z_0-9]*`; names are case-sensitive and unique. All registers begin in `|0>`. A name must be declared before any source instruction uses it. Declarations can be interleaved with operations: a later register is an initially zero spectator of earlier operations.

SUM requires two different, declared registers. Their dimensions may differ. It leaves the control unchanged. It does not change either register's declared dimension. There is no separate `cnot` keyword: SUM on two qubits has the CNOT action.

The joint basis follows declaration order, with the last register varying fastest. Complete equations, the Fourier phase convention and the mixed-dimension SUM rule are specified in [semantics.md](semantics.md).

## Example

```text
qutrit control
qutrit target
fourier control
sum control target
```

This yields `(|0,0> + |1,1> + |2,2>) / sqrt(3)`.

## Python model and lowering

`parse(source)` returns a validated immutable `Circuit`. `lower(circuit)` returns a `CircuitIR` with ordered `Register` objects and `Operation` objects whose operands are resolved integer axes. Each operation has a `GateKind`. Dimensions, axis bounds, arity and distinct SUM operands are checked at the public model/IR construction boundaries.

`simulate` accepts either representation and returns a tuple of complex amplitudes. `probabilities` computes their squared magnitudes. `Gate("shift", "q")` remains valid; construct a controlled gate as `Gate("sum", target="t", control="c")`.

The IR exposes `dimensions`, `strides` and `state_size`. Lowering resolves explicit declarations; it performs no automatic dimension inference, encoding search, optimisation or hardware code generation.

The additive `apply_state(circuit, initial_state)` uses the same gate application code on an exact finite tuple, without normalising it. Zero and unnormalised states are valid. `LogicalProgram(lower(parse(source)))` wraps this IR and provides canonical semantic JSON; it does not preserve source comments or source-line locations. See the [data contracts](contracts/logical-ir-and-encoding-v1.md).

## Diagnostics and resource limits

Invalid source instructions and register uses raise `ValueError` with a source line number. An empty program is rejected. Programmatic model validation also raises `ValueError`; passing the wrong top-level API object raises `TypeError`.

Simulation rejects state spaces larger than 65,536 amplitudes before allocating a statevector. The CLI reports invalid programs and unreadable files with exit status 2. Its multi-register labels use commas, and `--amplitudes` includes complex amplitudes.

## Not implemented

Measurement, shots, parameterised rotations, noise, quantum/classical control flow, functions, automatic dimension inference, alternative encoding selection, hardware backends and formal equivalence verification remain future work. The available gates are not a universal gate set claim.
