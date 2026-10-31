# Architecture and scientific constraints

## Implemented baseline

`parse` converts a small text notation to immutable `Circuit`, `Register` and `Gate` objects. The statevector simulator applies one-register cyclic shift or DFT across mixed-dimensional tensor-product states; a CLI prints computed basis probabilities. Code uses only the Python standard library.

## Proposed architecture (not yet implemented)

1. Front-end lexer/parser, semantic analysis and typed dimension-aware IR.
2. Multiple candidate embeddings: qubit/qutrit/qudit and mixed.
3. Cost model with explicit hardware topology, gate fidelity, depth, qudit availability and compilation assumptions.
4. Verification: normalized semantics, equivalence checks, property tests and independent baselines.
5. Hardware adapters and hybrid classical/quantum runtime.

### Evaluation rules

Do not claim quantum advantage, runtime speedups or hardware efficiency without benchmark protocols, baselines, uncertainty, resources and platform details. A ternary representation is not intrinsically better on all hardware. The current simulator has exponential state size (product of register dimensions) and caps amplitudes at 65,536 to avoid accidental resource exhaustion.
