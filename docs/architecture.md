# Architecture and scientific constraints

## Preserved logical interpreter pipeline

1. `core.parse` reads the small line-based notation, checks declarations before use and reports source-line errors.
2. `ir.Circuit`, `Register` and `Gate` provide immutable, runtime-validated named models.
3. `ir.lower` resolves register names to ordered axes and constructs `CircuitIR` / `Operation` objects. `GateKind` enumerates the supported operations; dimensions and operand bounds are explicit.
4. `core.simulate` interprets the resolved IR on a mixed-dimensional tensor-product statevector. It applies single-register cyclic shift and DFT, plus a two-register controlled-SUM permutation.
5. The CLI displays basis probabilities, declaration-ordered basis labels and optional complex amplitudes.

The named Python constructors remain available. Both Circuit and IR inputs are validated at construction, including programmatically supplied objects. Input sequences are copied to tuples to prevent later list mutation from changing a circuit.

The statevector size is the product of register dimensions. Simulation caps this at 65,536 amplitudes before allocation. Small Fourier matrices are cached; this is an implementation detail, not a benchmark result.

The v0.3 `apply_state` API shares the gate application loop with `simulate`. It accepts finite built-in numeric tuples linearly, including unnormalised and zero vectors. The existing `simulate` API still starts at the all-zero basis state.

## Explicit encoding and verification — v0.3

| Module | Responsibility | Dependencies |
| --- | --- | --- |
| `_state.py` | Exact finite linear-state inputs | Standard library |
| `_serialization.py` | Fail-closed canonical JSON mechanics | Standard library |
| `logical_ir.py` | LogicalProgram wrapper and semantic JSON | Existing parser/IR, serialization |
| `encoding.py` | Independent BasisEncoding model and matrix-free vector encoding | IR limits, state validator, serialization |
| `equivalence.py` | Reference matrices, complete operators and subspace mathematics | Existing IR, shared arbitrary-state interpreter |
| `verification.py` | Typed preflight, budgets and pass/fail/unsupported reports | Logical program, encoding, equivalence |
| `verify_cli.py` | Explicit logical/physical files and human-readable evidence | Logical program, encoding, verification |

The encoding model imports no logical-program or verification layer. A physical program is explicitly supplied as a physically dimensioned CircuitIR, or as a separately validated ReferenceOperator. It is never automatically generated from the logical program by verification. A reference matrix pass is labelled reference-only.

Encoding construction caps explicit logical mapping entries but does not allocate or cap the physical Hilbert space. Vector allocation, explicit reference matrices, the JSON wire format and dense verification each have distinct documented budgets. See [ADR 0001](adr/0001-verified-encoding-first.md), the [data contract](contracts/logical-ir-and-encoding-v1.md) and [operator criteria](contracts/operator-verification-v1.md).

## Bounded generation — v0.4

`search.py` implements immutable search constraints, encoding candidates, rejection
counts and generation reports. It lazily enumerates ordered physical tuples and
flat/register-prefix maps, accepts explicit seed encodings and retains first
provenance under deduplication. Tuple, mapping-attempt and unique-candidate budgets
are separate, with explicit exhausted/truncated outcomes.

The module depends only on the existing encoding model, dimension constant and
shared strict serialization. It imports no verifier or simulator. Public report
construction/decoding replay the bounded domain; the internal producer avoids
duplicating work. No physical circuit is synthesised or verified during generation.
See the [search contract](contracts/encoding-search-v1.md) for exact rules and the
[work packages](plans/v0.4-implementation.md) for the delivered dependency sequence.

## Exact structural comparison — v0.4

`resources.py` computes six exact counts from the IR, using per-axis dependency
layers without allocating a physical statevector. `comparison.py` performs exact
integer dominance and retains ties/input order among passing supplied circuits.
`evaluation.py` owns immutable circuit inputs and producer-only evaluation
records. The manual `search_verification.evaluate_candidate` adapter validates
dimensions/options, checks operation/dense limits and calls the unchanged v0.3
verifier before deriving counts. Reference matrices do not enter this circuit
comparison. Mixed logical workloads, mismatched settings and repeated IDs fail
preflight instead of becoming a partial front.

The manual adapter performs at most one numerical call. The aggregate
`evaluate_candidates` adapter validates all supplied bindings and program IDs,
then evaluates every candidate under a shared deterministic call/work ledger.
`search_report.py` owns pure preflight/planning, immutable aggregate reports and
strict recorded-evidence decoding. It replays generation, budgets, counts and
fronts without importing the numerical orchestrator or running the verifier.
`search_cli.py` is the file/transport adapter and emits readable or canonical JSON
results. Existing generator, simulator and verifier algorithms are unchanged.

Structural depth assumes disjoint operations can share a layer; it is not a hardware
schedule or cost model. Snapshot metadata is recorded provenance, not authentication.

## Verification implemented for this milestone

A separate test-only dense-matrix oracle enumerates explicit tensor basis labels. It does not call production stride, lowering or gate-matrix helpers. Tests compare full complex amplitudes, complete small gate matrices, SUM unitarity, reversed and non-adjacent axes, unequal dimensions, norm preservation and reduced-state purity for known pure entangled states.

These tests provide bounded numerical evidence. They are not formal verification or external validation. See [validation.md](validation.md).

## Proposed architecture beyond this milestone

- Richer front-end types, functions and hybrid classical/quantum control flow.
- Automatic logical-dimension inference, physical-circuit synthesis and hardware-conditioned comparisons beyond the implemented structural model.
- Hardware-conditioned cost models with topology, fidelity and gate availability.
- Semantics-preserving optimisation, equivalence tooling and independent external baselines.
- Hardware adapters and a hybrid runtime.

The current IR is an initial resolved representation, not a complete compiler type system. Lowering does not infer dimensions or emit machine instructions.

## Evaluation rules

Do not claim quantum advantage, runtime speedups, universal computation or hardware efficiency from these demonstrations. Future comparisons require equivalent workloads, platform details, reproducible baselines, resource accounting and uncertainty. Ternary representation is not intrinsically better on all hardware.
