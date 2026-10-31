# Architecture and scientific constraints

## Implemented v0.2 pipeline

1. `core.parse` reads the small line-based notation, checks declarations before use and reports source-line errors.
2. `ir.Circuit`, `Register` and `Gate` provide immutable, runtime-validated named models.
3. `ir.lower` resolves register names to ordered axes and constructs `CircuitIR` / `Operation` objects. `GateKind` enumerates the supported operations; dimensions and operand bounds are explicit.
4. `core.simulate` interprets the resolved IR on a mixed-dimensional tensor-product statevector. It applies single-register cyclic shift and DFT, plus a two-register controlled-SUM permutation.
5. The CLI displays basis probabilities, declaration-ordered basis labels and optional complex amplitudes.

The named Python constructors remain available. Both Circuit and IR inputs are validated at construction, including programmatically supplied objects. Input sequences are copied to tuples to prevent later list mutation from changing a circuit.

The statevector size is the product of register dimensions. Simulation caps this at 65,536 amplitudes before allocation. Small Fourier matrices are cached; this is an implementation detail, not a benchmark result.

## Verification implemented for this milestone

A separate test-only dense-matrix oracle enumerates explicit tensor basis labels. It does not call production stride, lowering or gate-matrix helpers. Tests compare full complex amplitudes, complete small gate matrices, SUM unitarity, reversed and non-adjacent axes, unequal dimensions, norm preservation and reduced-state purity for known pure entangled states.

These tests provide bounded numerical evidence. They are not formal verification or external validation. See [validation.md](validation.md).

## Proposed architecture beyond this milestone

- Richer front-end types, functions and hybrid classical/quantum control flow.
- Automatic dimension inference and multiple candidate embeddings.
- Hardware-conditioned cost models with topology, fidelity and gate availability.
- Semantics-preserving optimisation, equivalence tooling and independent external baselines.
- Hardware adapters and a hybrid runtime.

The current IR is an initial resolved representation, not a complete compiler type system. Lowering does not infer dimensions or emit machine instructions.

## Evaluation rules

Do not claim quantum advantage, runtime speedups, universal computation or hardware efficiency from these demonstrations. Future comparisons require equivalent workloads, platform details, reproducible baselines, resource accounting and uncertainty. Ternary representation is not intrinsically better on all hardware.
