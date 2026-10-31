# v0.3 controlled implementation: operator checks and contract clarifications

Date: 1 November 2026. This specification precedes implementation of the operator
comparison. It follows ADR 0001 and the corrected logical/encoding contract whose
physical Hilbert space is not capped at encoding construction.

## Clarifications to the data contract

The v1 JSON limit is enforced on both decoding and encoding. An otherwise valid
in-memory object whose canonical UTF-8 representation exceeds 1 MiB raises
`Q3-SER-001` from `to_json`; it remains a valid in-memory object. This makes every
successfully serialised object round-trip under the same wire budget. Large
physical spaces and explicit mapping values otherwise remain representable.

Public top-level container checks precede semantic validation. Within a JSON
object, exact required fields are checked before discriminator values. A JSON
array at the root delegates to `from_dict` and therefore raises its top-level
`TypeError`. Nested type errors are `ValueError` with `Q3-SER-003`. Existing IR
semantic validation retains its original `ValueError` messages.

Linear state APIs accept exact tuples of built-in finite int/float/complex
amplitudes, excluding bool. Zero and unnormalised vectors are valid. They never
renormalise or silently discard values. The shared validator is also used by the
additive `core.apply_state` API; the existing `simulate` keeps its zero initial state.

## Physical inputs

`verify_equivalence(logical, physical, encoding, *, tolerance=1e-10,
max_dimension=64)` accepts a `LogicalProgram`, either a physical `CircuitIR` or
`ReferenceOperator`, and a `BasisEncoding`. The physical CircuitIR is an explicit
program in the existing Q3# gate set, interpreted with its own physical dimensions.
It is not automatically synthesised from the logical input.

`ReferenceOperator(dimensions, matrix)` is a frozen, separately validated dense
physical matrix. Dimensions are a nonempty exact tuple of exact ints 2–32. Matrix
and rows are exact tuples, shape `(product(dimensions), product(dimensions))`;
elements follow the finite built-in amplitude rule and are stored as complex.
No unitarity is assumed at construction: a nonunitary but well-formed candidate
must produce a verification failure. The explicit matrix representation is capped
at 65,536 entries before copying, independently of the smaller verifier limit.

New diagnostics: `Q3-REF-001` for reference containers, dimensions or shape;
`Q3-REF-002` for invalid/nonfinite matrix elements; `Q3-REF-003` for the explicit
matrix-entry cap; `Q3-VERIFY-001` for invalid tolerance; `Q3-VERIFY-002` for invalid
dense verifier limits. Top-level type failures are TypeError; semantic failures
are ValueError. Tolerance must be a built-in finite positive int/float, not bool.
`max_dimension` must be an exact integer 1–64; callers can lower the dense budget.

Preflight checks all public types, limits and logical/physical dimension matches.
Dimension mismatch raises `Q3-COMP-001`, even if the request also exceeds the dense
budget. A valid request with physical dimension above `max_dimension` returns
`unsupported` before allocating operator matrices. Coding exceptions are not
silently converted to unsupported results.

## Complete small-subspace criterion

Let U_L be the complete logical operator, U_P the complete physical operator and
V the validated basis injection. Matrix rows and columns use the independently
declared logical and physical basis orders. Build complete small operators by
applying each program to every computational basis column, using `apply_state`.

Define `A = U_P V`, `B = V U_L` and `P = V V†`. Choose one global phase
`phase = z/abs(z)` for `z = sum(conjugate(B[k,j])*A[k,j])`; if z is exactly zero,
choose phase 1. This is the Frobenius least-squares phase, common to all columns.
Relative phases must not be aligned separately.

Pass requires every following absolute Frobenius norm to be finite and at most
the declared tolerance:

- `||A - phase*B||_F` — full encoded-subspace residual.
- `||(I-P) A||_F` — leakage amplitude bound.
- `||U_L† U_L - I||_F` and `||U_P† U_P - I||_F` — full operator unitarity checks.

The Frobenius residual bounds the state error for every normalised logical input;
the squared leakage norm bounds its leakage probability. This is floating-point,
exhaustive small-operator evidence, not a formal theorem or a hardware experiment.
BasisEncoding injection establishes `V†V=I` exactly by integer validation.

Nonfinite computed metrics from a well-formed finite candidate produce `fail`
with an explicit numerical diagnostic and unavailable metrics represented by
None; they never produce pass or unsupported. A reference-matrix pass is labelled
`reference-only`. A Q3# physical circuit pass is labelled `q3hash-circuit`; neither
label asserts a hardware backend or a device-native synthesis result.

## Reports and CLI

`VerificationReport` is a frozen in-memory result with status `pass`, `fail` or
`unsupported`, reason, evidence kind, logical/physical sizes, tolerance, an optional
global phase and optional residual/leakage/unitarity metrics. Unsupported results
contain no computed metrics. Report wire serialization remains deferred.

`q3hash-verify LOGICAL.q3 PHYSICAL.q3 --encoding ENCODING.json` prints a human-readable
report and semantic SHA-256 identifiers for the logical program, physical program
and canonical encoding. Exit codes are 0 pass, 1 fail, 2 invalid input, 3 unsupported.
No numerical-report JSON schema is introduced in v0.3.

## Test vectors defined before implementation

1. Qutrit shift against the explicit two-qubit program `SUM a b; SUM b a; shift b`
   under map `(0,1,2)` must pass for all three logical basis columns and arbitrary
   superpositions. The unused physical state 3 is fixed.
2. Qutrit shift against ordinary dimension-4 shift must fail: inputs 0 and 1 can
   look correct, but logical input 2 leaks into physical state 3.
3. Logical qubit identity against `fourier q; shift q; fourier q` must fail for a
   relative phase, despite agreement on the all-zero input.
4. Logical identity against a physical reference `-I` must pass with global phase
   -1; independent per-column phases are prohibited.
5. A physical reference that is identity on the code but zero on the unused state
   must fail full physical unitarity.
6. Permuted mixed-dimensional basis maps must respect both independent flat orders.
7. Valid large-physical-space encodings must survive construction and canonical
   JSON; vector allocation must raise Q3-STATE-003 and dense checks be unsupported.
8. Malformed maps, duplicate JSON keys, unexpected fields, booleans/floats in
   integer fields, invalid Unicode and wire-size violations must fail closed.

The v0.2.1 regression suite and numerical oracle remain required. Independent
NumPy/SciPy matrices must audit the new arbitrary-state and encoding checks.
Candidate search and optimisation are deferred to v0.4.
