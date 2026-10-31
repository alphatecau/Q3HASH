# v0.4 contract — bounded encoding search and comparison

**Status:** Generation models, canonical generation reports and `generate_encodings` are implemented in 0.4.0.dev1. Circuit-evaluation orchestration and Pareto APIs below remain proposed.
**Date:** 1 November 2026, Australia/Brisbane.
**Baseline:** Q3HASH v0.3.0; [ADR 0001](../adr/0001-verified-encoding-first.md), [basis encoding](logical-ir-and-encoding-v1.md), [operator verification](operator-verification-v1.md).

## 1. Purpose and boundary

For one fixed logical program, enumerate a declared finite set of basis encodings,
evaluate explicitly supplied physical Q3# circuits and compare passing circuits
using exact structural resource counts. Preserve all v0.3 APIs and semantics.

An encoding is a map, not a physical implementation. No gate sequence is inferred
from a map. In particular, constructing `V U_L V† + (I - V V†)` supplies a reference
unitary mathematically, but does not synthesise a Q3# circuit. Reference-only
matrices may still be inspected through v0.3; they are excluded from the v0.4
executable-circuit comparison defined here.

This contract does not deliver automatic logical-dimension inference, arbitrary
isometries, exhaustive search of all injections, hardware synthesis, hardware
costs, noise, measurement or universal optimisation. Logical dimensions remain
explicit. Hardware-conditioned comparisons remain a v0.5 target.

## 2. Interfaces and dependencies

```python
# Implemented generation API.
@dataclass(frozen=True)
class SearchConstraints:
    allowed_dimensions: tuple[int, ...] = (2, 3)
    max_registers: int = 4
    max_physical_size: int = 64
    mapping_families: tuple[str, ...] = ("flat-prefix", "register-prefix")
    max_dimension_tuples: int = 4096
    max_mapping_attempts: int = 16384
    max_candidates: int = 256
    max_verifications: int = 64
    max_operations_per_program: int = 1024
    max_gate_column_steps: int = 262144
    objectives: tuple[str, ...] = (
        "physical_registers", "max_register_dimension", "unused_basis_states",
        "gate_count", "two_register_gate_count", "dependency_depth",
    )

# Proposed evaluation input; not yet exported.
@dataclass(frozen=True)
class CircuitImplementation:
    encoding: BasisEncoding
    circuit: CircuitIR

def generate_encodings(
    logical_dimensions: tuple[int, ...], constraints: SearchConstraints, *,
    seed_encodings: tuple[BasisEncoding, ...] = (),
) -> GenerationReport: ...

# Evaluation/comparison APIs remain proposed; they are not public imports yet.
def evaluate_candidates(
    logical: LogicalProgram, generation: GenerationReport,
    implementations: tuple[CircuitImplementation, ...] = (), *,
    tolerance: float = 1e-10, max_dimension: int = 64,
) -> SearchReport: ...

def pareto_front(
    evaluations: tuple[CandidateEvaluation, ...], objectives: tuple[str, ...],
) -> tuple[str, ...]: ...  # Candidate IDs in generation order.
```

`search.py` owns generation and imports the existing encoding model, not the
verifier. `resources.py` owns integer circuit counts and imports only the IR.
`comparison.py` owns strict integer dominance and consumes validated evaluations.
`search_verification.py` orchestrates the existing verifier, generation and
resource counts. `search_cli.py` is the final adapter. None is imported by existing
models or the existing simulator. `search.py` is implemented; the other paths are
proposed. Numerical-work/objective fields in SearchConstraints are validated and
preserved now, but the generator does not evaluate circuits or use those limits.

The implemented generation imports are `SearchConstraints`, `EncodingCandidate`,
`DimensionRejections`, `GenerationReport` and `generate_encodings` from `q3hash`.
`EncodingCandidate(encoding, origin, seed_index=None, block_cuts=None)` computes its
read-only `candidate_id`; it cannot accept a caller-supplied ID at construction.
Its origin and map must agree. Seed indices are 0–4095; cuts are an exact tuple
only for register-prefix candidates. Embedded wire IDs are checked against content.

`DimensionRejections(insufficient_capacity=0, physical_size_limit=0)` is an
immutable pair of exact nonnegative integer counts. GenerationReport's
`dimension_rejections` field uses that model in Python and the named object from
section 5 on the wire. All other counters are exact nonnegative integers.
`candidates` and `seed_encodings` are exact tuples. Constraints and generation
reports expose `to_dict`, `to_json`, `from_dict` and `from_json`; candidate and
rejection models expose the embedded-object `to_dict`/`from_dict` adapters.

Public GenerationReport construction and decoding replay bounded generation and
check the full result, including first provenance, order and conserved counters.
The producer uses a private trusted factory to avoid doing the same search twice.
Invalid direct candidate/report field types raise TypeError with Q3-SEARCH-005;
wire nested type failures remain ValueError with Q3-SER-003.

## 3. Validation before work

Direct constructors require exact tuples for tuple fields and exact built-in
integers for integer fields; bool, floats, numeric strings and generators are
rejected. No caller-owned mutable input is retained. Wrong public top-level types
raise `TypeError`; invalid values and nested types raise `ValueError`.

| Field | Valid values and semantics |
| --- | --- |
| `allowed_dimensions` | Nonempty, strictly increasing tuple of unique integers in 2–32. No implicit sorting. |
| `max_registers` | Integer 1–8. Default 4. Applies to generated and seeded physical registers. |
| `max_physical_size` | Integer 2–64. This first search version deliberately uses small physical spaces. Larger existing encoding models remain valid outside this search. |
| `mapping_families` | Nonempty unique subset of `("flat-prefix", "register-prefix")`, in that order. |
| `max_dimension_tuples` | Integer 1–65,536; default 4,096. |
| `max_mapping_attempts` | Integer 1–262,144; default 16,384. |
| `max_candidates` | Integer 1–4,096; default 256 unique maps. |
| `max_verifications` | Integer 1–256; default 64 actual verifier calls. |
| `max_operations_per_program` | Integer 1–16,384; default 1,024, applied to both logical and physical operation counts. |
| `max_gate_column_steps` | Integer 1–4,194,304; default 262,144 cumulative work units defined in section 7. |
| `objectives` | Nonempty tuple of distinct names from section 8. Array order determines display columns, not dominance. All objectives are minimised. |
| Logical dimensions | Existing nonempty dimension rules, exact tuple, dimensions 2–32. Do not allocate a logical statevector. |
| Seeds | Exact tuple, at most 4,096 encodings. Every item must match logical dimensions and the physical alphabet/register/size constraints. Contradictory supplied seeds are invalid input. |
| Implementations | Exact tuple, at most 4,096 items; dimensions must match their encoding. Each item must identify a generated candidate, and there is at most one implementation per candidate. Duplicate or unrelated entries are invalid, including identical duplicate entries. |

Validate every implementation before any numerical call, so an invalid later item
cannot turn a malformed request into a partial successful report. Validate
`tolerance` and `max_dimension` exactly as v0.3. A smaller verification dimension
budget is allowed independently of the generation budget.

Validation precedence: public container/object types; exact fields and schema;
scalar and tuple constraints; dimension/seed compatibility; implementation
membership and uniqueness; verifier options. Budget exhaustion during valid work
is a report outcome, not a malformed-input exception.

## 4. Search domain and canonical order

The declared domain is the union of the ordered explicit seeds and the supported
mapping families over all ordered dimension tuples from the allowed alphabet,
with lengths 1 through `max_registers`. Physical products must be at least `D_L`
and at most `max_physical_size`. `(2,3)` and `(3,2)` are distinct arrangements;
neither register order nor logical basis order may be silently changed.

Process seeds first in their supplied order. Then visit dimension tuples by
increasing length, and lexicographically within each length. Use a lazy Cartesian
product: never materialise the whole domain. A raw dimension tuple consumes one
dimension-budget unit, including a tuple rejected for its product. For an alphabet
of size `a`, the raw tuple count is exactly `sum(a**r, r=1..max_registers)`.

For each eligible tuple, visit families in the declared canonical family order.
A seed, a flat map, or one proposed register partition consumes one mapping
attempt. An invalid-capacity partition and a duplicate map still consume an
attempt. A family with no possible register partition records its unavailability
without inventing a partition or consuming a mapping attempt.

### Flat-prefix map

For physical size `D_P >= D_L`, map flat logical index `j` to physical index `j`.
The physical tuple interprets that integer in its own mixed-radix order.

### Register-prefix map

For `n` logical registers and `m` physical registers, require `m >= n`. Partition
the physical axes into `n` nonempty contiguous blocks. Enumerate cut tuples from
`combinations(range(1,m), n-1)` lexicographically. Let block products be `C_i`.
Retain a partition only when every `C_i >= d_i`.

For a logical basis label `k`, the physical flat image is

```text
M[flat_d(k)] = sum(k_i * product(C_j for j > i) for i in range(n))
```

This embeds each logical digit into its own block's leading basis states. Logical
digits, block order and physical axes are preserved. The map is injective because
`0 <= k_i < d_i <= C_i`. Unused physical states are not discarded or treated as
new logical states.

Example: `(2,3) -> (2,2,2)` with cut `(1,)` has block products `(2,4)` and map
`(0,1,2,4,5,6)`. Cut `(2,)` has products `(4,2)` and is rejected. The flat-prefix
map `(0,1,2,3,4,5)` is a different candidate. Neither map claims a supplied circuit.

### Identity and duplicate handling

Candidate identity is semantic encoding identity: the full logical dimensions,
physical dimensions and mapping tuple. Its portable ID is lowercase SHA-256 of
the UTF-8 bytes of `BasisEncoding.to_json()` with no trailing newline. Compare full
encoding values when deduplicating; a digest collision with different content
raises an error rather than merging candidates.

Retain the first occurrence and its origin (`seed`, `flat-prefix`, or
`register-prefix`), seed index or cut tuple as appropriate. Later occurrences
increment `duplicate_mappings`. Their physical dimensions are never reordered to
make them appear identical. Input array order is significant and preserved.

## 5. Budgets, completion and accounting

`GenerationReport` contains constraints, logical dimensions, the ordered seeds,
an ordered tuple of `EncodingCandidate` objects, completion, stop reason and all
counters. Each candidate contains its ID, complete encoding and first origin.

| Field | Meaning |
| --- | --- |
| `completion` | `exhausted` means every item in the declared domain was considered; `truncated` means a budget prevented that. Neither means all physical implementations are known. |
| `stop_reason` | Null for exhausted; otherwise `dimension-budget`, `mapping-budget`, or `candidate-budget`. |
| `dimension_tuples_seen` | Number of raw dimension tuples assessed; seeds are not dimension tuples. |
| `mapping_attempts` | Seed, flat-map and partition attempts assessed, including rejected partitions and duplicates. |
| `emitted_candidates` | Number of unique encodings retained. |
| `duplicate_mappings` | Repeated mappings after full encoding equality, across seeds and families. |
| `dimension_rejections` | Separate integer counts for `insufficient-capacity` and `physical-size-limit`. Test physical-size limit first when both could be relevant. |
| `partition_rejections` | Integer count for `block-capacity`. |
| `family_unavailable` | Integer count for `too-few-physical-registers`. |

Before each new dimension tuple or mapping attempt, test its applicable budget.
When a unique map would exceed the candidate cap, stop before retaining it; that
last assessed mapping attempt is counted. Merely reaching the candidate count is
not enough to stop: further duplicates may exist, and an exhausted result is valid
if the domain ends without another unique map or another exhausted budget.

If natural exhaustion coincides with a limit, report exhausted. A single lazy
lookahead may establish whether an additional raw item exists; retain only its
small tuple/cut metadata, without assessing it, allocating a map or counting it as
work. Do not silently skip an item to fit a budget. Prefix
reports must be identical across repeat runs with identical inputs and budgets.

The first search version never creates maps longer than 64, because capacity is
checked before map construction. A valid logical program larger than every
physical space produces zero candidates with capacity rejection evidence, not a
logical state allocation. Default stored maps contain at most `256 * 64` integer
entries; the hard candidate bound permits at most `4096 * 64`. Wall-clock time is
recorded only outside canonical reports, not used as a deterministic stop rule.

## 6. Physical implementations and evidence states

`CircuitImplementation` contains an existing encoding and an existing resolved
physical IR. It does not contain a caller-supplied claim of correctness or cost.
The evaluator finds implementations by full encoding equality, then invokes
`verify_equivalence` unchanged on the supplied circuit.

| Evaluation status | Meaning | Eligible for the front? |
| --- | --- | --- |
| `unimplemented` | No physical circuit supplied for this map. | No |
| `pass` | Existing complete-subspace verifier passed at the declared tolerance. | Yes |
| `fail` | Existing verifier found excessive residual, leakage or nonunitarity, including nonfinite computed metrics. | No |
| `unsupported` | Valid program exceeds a declared dense dimension or per-program operation limit. | No |
| `not-evaluated` | A valid supplied circuit was skipped because the run's numerical work/call budget was insufficient. | No |

Every generated candidate receives one evaluation in generation order. A
truncated generation report can still be evaluated, but the front is explicitly
partial. All passing circuit evidence is `q3hash-circuit`, a software gate-model
result rather than hardware execution. Never use `fail` for invalid input or
convert an unexpected coding exception to unsupported.

The verifier checks one common global phase, leakage and complete physical
unitarity, including unused physical states. No all-zero-state-only test, per-column
phase alignment, tolerance-dependent cost discount or reference-only construction
can qualify a candidate for the executable-circuit front.

## 7. Numerical work limits

For a supplied circuit, check per-program operation limits first, then the dense
dimension limit, before calling the verifier. These return unsupported with
`operation-limit` or `dense-limit`, respectively. Missing implementations remain
unimplemented even when their dimensions exceed the dense limit: no matrix was
supplied to check.

Each actual verifier call consumes one call unit and
`D_L * logical_operation_count + D_P * physical_operation_count` gate-column
steps. The current verifier constructs the logical operator anew per call, so
charge its work each time. Even identity programs consume one call unit; the
call cap also bounds the dense unitarity computations.

If either cumulative budget would be exceeded, mark that candidate not-evaluated
with `verification-call-budget` (checked first) or `gate-column-budget`. Charge
neither budget for that skipped call and continue; a later smaller circuit can
still fit. Record actual calls and consumed gate-column steps. These are explicit
algorithmic work proxies, not milliseconds or device gate costs.

## 8. Structural resources and Pareto comparison

Compute the following counts from each passing supplied circuit and its encoding.
All are exact nonnegative integers; none can be supplied by the caller.

| Objective | Formula or rule |
| --- | --- |
| `physical_registers` | Number of physical registers. |
| `max_register_dimension` | Largest physical register dimension; represents required local level count, not a hardware preference. |
| `unused_basis_states` | `D_P - D_L`. |
| `gate_count` | Number of resolved physical operations, without cancellations or hidden synthesis. |
| `two_register_gate_count` | Number of SUM operations in the current gate set. |
| `dependency_depth` | Start every axis at layer 0; an operation's layer is 1 plus the largest layer on its touched axes; update all touched axes to that layer. The maximum layer is depth. Identity depth is 0. |

Depth assumes disjoint-axis operations can share an abstract layer. It is not a
hardware schedule: connectivity, durations, cross-talk and target-native gate
decomposition are not modelled. Primitive counts across dimensions are structural
counts, not evidence that equally counted gates have equal physical cost.

For a declared objective tuple, A strictly dominates B iff every selected count
for A is `<=` B's count and at least one is `<`. Use exact integer comparisons,
no numerical tolerance and no weighted sum. Equal vectors do not dominate one
another: retain ties and preserve generation order. An empty set of passing
circuits has an empty front, with a reason and status counts; it is never a pass.

For the qutrit shift, the native qutrit vector is `(1,3,0,1,0,1)` and the supplied
two-qubit vector is `(2,2,1,3,2,3)` in the default objective order. Both are on the
default front: the binary circuit requires fewer levels per register. If the
caller explicitly omits that objective, the native circuit dominates on the
remaining counts. Neither observation establishes physical superiority.

Every report labels the front `passing-supplied-circuits-only`. Exhausting these
families proves only coverage of that declared domain, not all possible maps or
all possible circuits for any map. Missing circuits, truncation and skipped or
unsupported verification must be visible beside the front.

## 9. Serialization, provenance and errors

Constraints, generation and search reports each get a separate strict JSON
schema: `q3hash.encoding-search-constraints`, `q3hash.encoding-generation`, and
`q3hash.encoding-search-report`, all with integer `schema_version: 1`. Use the
existing canonical UTF-8 JSON rules, duplicate-key rejection, exact fields,
finite numbers, sorted object keys and symmetric 1 MiB wire limit. Preserve arrays;
do not reorder them when serialising. A valid large in-memory report may exceed
the wire limit and must raise `Q3-SER-001`, not lose candidates or diagnostics.

The wire field inventories are normative:

- Constraints: `schema`, `schema_version` and every field in section 2.
- Generation: `schema`, `schema_version`, `constraints` (complete constraints
  object), `logical_dimensions`, `seed_encodings` (existing encoding v1 objects),
  `candidates`, `completion`, `stop_reason`, and every counter in section 5.
- Candidate: `candidate_id`, `encoding` (existing encoding v1 object), `origin`,
  `seed_index`, `block_cuts`. Seed index is nonnegative only for seed origin; cuts
  are an integer array only for register-prefix; other values must be null.
- Search report: `schema`, `schema_version`, `logical_program` (existing logical
  v1 object), `logical_id`, `generation`, `implementations`, `tolerance`,
  `max_dimension`, `evaluations`, `front_ids`, `ranking_scope`,
  `verification_calls`, `gate_column_steps`, `engine_version`, `verifier_version`,
  `source_commit`, `numerical_environment`. The environment object has exactly
  `python_implementation`, `python_version`, `system`, `machine`, `libc`, and
  `numeric_backend`; these are nonempty strings except that unavailable libc
  information is null. Use runtime observations, not machine names or paths.
  Include all implementations, in candidate order, as objects
  with `candidate_id`, `physical_program` (logical IR v1 format applied to the
  physical IR), and `physical_id`.
- Evaluation: `candidate_id`, `status`, `reason_code`, `verification`, `resources`.
  Unimplemented, unsupported by orchestration and not-evaluated results have null
  verification/resources. For calls returning pass/fail, verification has exactly
  `status`, `evidence`, `reason`, `tolerance`, `global_phase`, `subspace_residual`,
  `leakage_norm`, `logical_unitarity_error`, `physical_unitarity_error`.
  A phase is null or `[real, imag]`; numerical metrics are finite numbers or null
  as allowed by the existing report. Resources is null except on pass, where it
  contains every objective in section 8, not just the selected objectives.

Logical and physical IDs hash their existing canonical program JSON. Schema
version names this search contract; engine/verifier versions are nonempty strings
and source commit is null or exactly 40 lowercase hexadecimal characters. Missing
source provenance stays null; do not invent a commit. Do not include timestamps,
machine paths, wall-clock measurements or unordered sets in canonical output.
Decode reports with cross-field checks: counts match arrays; IDs match content;
referenced candidates exist once; implementation order matches candidate order;
status/resource/evidence combinations are valid; replaying bounded generation
matches its order and counters; and recomputing exact dominance matches
`front_ids`. Pass snapshots require all four metrics to be present, finite and
within tolerance, with a finite phase pair whose modulus is within `1e-12` of 1.
Threshold-failure snapshots require finite metrics with at least one above
tolerance; nonfinite-failure snapshots use null phase and null metrics, as v0.3
does. Unsupported/not-evaluated/unimplemented entries cannot contain a successful
verification snapshot. A decoded report is recorded numerical evidence, not a new
verification run or cryptographic proof of its claims.

Integer generation/resource/front results are independent of numerical rounding.
Byte-identical complete reports are required for repeat runs in the same recorded
Python/numerical environment. Cross-platform floating-point metric bits may differ;
compare numerical results at the declared tolerance instead of promising identical
bytes across different math-library/toolchain environments. The existing symmetric
wire cap also applies when serialising a logical or physical program to derive an
ID; do not hash truncated input when an otherwise valid model exceeds that cap.

| Stable prefix | Invalid input or outcome |
| --- | --- |
| `Q3-SEARCH-001` | Wrong public types, invalid constraint values or objective/family names. |
| `Q3-SEARCH-002` | Seed logical dimensions or physical constraints disagree. |
| `Q3-SEARCH-003` | Implementation dimensions, membership or uniqueness disagree. |
| `Q3-SEARCH-004` | Digest collision with unequal encoding content. |
| `Q3-SEARCH-005` | Invalid constructed or decoded report invariants. |
| Existing `Q3-SER-*`, `Q3-ENC-*`, `Q3-COMP-*`, `Q3-VERIFY-*` | Preserve the applicable existing diagnostics rather than replacing every error with a search prefix. |

Outcome reason codes are `verified`, `equivalence-failed`, `nonfinite-metrics`,
`no-implementation`, `operation-limit`, `dense-limit`,
`verification-call-budget`, and `gate-column-budget`. Completion stop reasons and
generation rejection reasons use the exact literals in sections 4–5. Exception
messages may add English detail after a stable prefix. No failures are swallowed.

## 10. Acceptance criteria before production implementation

The [golden vectors](../../benchmarks/encoding-search-v1.json) and
[`check_search_contract.py`](../../tools/check_search_contract.py) exercise a tiny,
independently enumerated domain, map formulas, actual existing circuit verification
and integer dominance. They remain independent reference definitions. The
implemented generator is additionally checked by
[`check_search_generation.py`](../../tools/check_search_generation.py), which
enumerates physical tensor labels and interprets a separate event trace for 504
alphabet/family/budget/seed cases without importing production generation helpers.

| ID | Required implementation behaviour |
| --- | --- |
| GEN-01 | Logical `(3,)`, alphabet `(2,3)`, two physical registers maximum and size 9: six raw tuples, one insufficient capacity rejection, ten map attempts, five unique candidates and five duplicates, in golden order. |
| GEN-02 | Preserve both `(2,3)` and `(3,2)`; never merge axis orders. |
| GEN-03 | For `(2,3)->(2,2,2)`, retain the two distinct golden maps; reject cut `(2,)`. |
| GEN-04 | Explicit mixed-axis seed precedes generated maps; repeated seed/family maps collapse by full content. |
| GEN-05 | Each generation limit separately yields a reproducible prefix with explicit truncated status. Budget exactly at natural exhaustion yields exhausted. |
| GEN-06 | Candidate cap does not truncate on later duplicates alone; the first extra unique mapping triggers truncation. |
| GEN-07 | All states in each map are in range and injective; exhaustive tiny-domain set equals an independent oracle's set. |
| GEN-08 | Capacity and physical-size rejection happen before map allocation; logical size above the entire domain yields an empty exhausted report when traversal budgets permit. |
| VAL-01 | Reject bools/floats/strings as integers, unordered or duplicate alphabets, unknown families/objectives, mutable containers and contradictory seeds. |
| VAL-02 | Reject mismatched, duplicate or unrelated implementations before any verifier call, including a malformed later item. |
| EVAL-01 | Native qutrit and actual three-gate binary qutrit shift both pass complete-subspace verification. |
| EVAL-02 | Dimension-four shift leaks on logical input 2 and fails; qubit relative-phase example fails despite its zero-state agreement. |
| EVAL-03 | Missing circuit remains unimplemented; reference-only matrices cannot enter this circuit front. |
| EVAL-04 | Reordered mixed entangling seed and native qutrit entangling circuit pass full operators, not only state preparation. |
| EVAL-05 | Smaller dense budget returns unsupported before operator allocation; per-program operation limit also allocates no operator. |
| EVAL-06 | Call and work budgets mark not-evaluated accurately; identity still consumes a call; later smaller circuits can fit a remaining work budget. |
| EVAL-07 | Propagate unexpected exceptions; nonfinite verifier output cannot pass or appear on a front. |
| COST-01 | Empty circuit depth 0; disjoint unary gates share a layer; shared-axis SUM dependencies serialize exactly as the golden vectors. |
| PAR-01 | Exact strict dominance, retained ties, selected objective subsets, empty fronts and stable generation order match the vectors. |
| SER-01 | Canonical round trips, duplicate/unknown/missing keys, version mismatch, invalid Unicode, nonfinite tokens and symmetric wire limits follow the existing strict policy. |
| SER-02 | Reject edited IDs, counts, foreign front IDs, inconsistent evidence/status/metrics and incorrectly recomputed fronts. |
| REP-01 | Same canonical inputs, versions and recorded numerical environment give byte-identical reports; changes to input array order remain visible; no timestamps or machine paths appear. Cross-platform integer results agree exactly and numerical results use the declared tolerance. |
| REG-01 | Preserve all 72 v0.3 tests, seven examples, both numerical audits, installed distributions and existing CLIs across the CI matrix. |

Release v0.4 only when production modules satisfy these acceptance cases and an
independent audit, with the declared comparison scope and all limitations visible.
