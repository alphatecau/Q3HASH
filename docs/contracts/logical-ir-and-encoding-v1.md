# Q3# v0.3 — Logical IR and Encoding Data Contracts

**Status:** Proposed normative interface baseline; implementation not authorised by this document alone
**Date:** 2026-11-01 (Australia/Brisbane)
**Applies to:** `alphatecau/Q3HASH` v0.2.1, Python 3.10+
**Architecture decision:** Verified logical-to-physical encoding before automated optimisation
**Source of truth for existing behaviour:** `src/q3hash/ir.py`, `src/q3hash/core.py`, `docs/semantics.md`

## 1. Scope and non-goals

This specification fixes the v0.3 in-memory data interfaces and canonical on-disk wire format for (a) a dimension-defined *logical* quantum program, and (b) an injective computational-basis encoding into a possibly different *physical* Hilbert space. It does not implement a compiler, automatic dimension inference, gate synthesis, measurement, noisy channels, cost models, or formal proof. A reference physical matrix may be compared mathematically without implying it can be built from the existing Q3# gate set.

The word *logical* means **independent of physical encoding**, not dimension-free: logical Hilbert-space dimensions are always explicit in v0.3. No implicit inference or reinterpretation of existing gates is permitted.

### Frozen compatibility constraints

1. Keep `parse(source) -> Circuit`, `lower(Circuit) -> CircuitIR`, `simulate(Circuit | CircuitIR) -> tuple[complex, ...]`, and existing `Circuit`, `CircuitIR`, `Register`, `Gate`, `GateKind`, `Operation` intact.
2. Preserve `Register.dimension` as an **exact Python integer** from 2 to 32, exclusive of `bool`; keep nonempty register sets, unique valid identifiers and distinct SUM operands.
3. Preserve register declaration order; last register varies fastest in flat basis indexing. Preserve existing `shift`, positive-sign `fourier` and control-first source `sum` semantics.
4. Preserve compatibility of all v0.2.1 tests and examples. The existing interpreter begins in `|0,...,0>`; future arbitrary-state application is an additive API, not a change to `simulate`.

## 2. Normative terminology and ordering

Let logical register dimensions be `d = (d_0, ..., d_(n-1))` and physical register dimensions `p = (p_0, ..., p_(m-1))`, with each entry an exact integer in `[2, 32]`. Require `n >= 1`, `m >= 1`.

Define total dimensions `D_L = product(d)` and `D_P = product(p)`.

For any ordered dimension tuple `a = (a_0,...,a_(r-1))`, a basis label `k = (k_0,...,k_(r-1))`, `0 <= k_i < a_i`, has zero-based flat index:

```
flat_a(k) = sum(k_i * product(a_j for j > i) for i in range(r))
```

Equivalently, `flat_a(k)` is the row-major/mixed-radix index with the **rightmost register varying fastest**. For `(2,3)`, the order is `(0,0),(0,1),(0,2),(1,0),(1,1),(1,2)`. A statevector is a tuple of length `product(a)` indexed by this rule. Physical and logical orders are calculated separately from their respective tuples; no implicit reorder, endian conversion, ancilla allocation, or padding occurs.

## 3. Public Python interfaces — proposal

```python
from dataclasses import dataclass
from typing import Any
from .ir import CircuitIR

@dataclass(frozen=True)
class LogicalProgram:
    ir: CircuitIR

    @property
    def dimensions(self) -> tuple[int, ...]: ...
    @property
    def state_size(self) -> int: ...

    def to_dict(self) -> dict[str, Any]: ...
    def to_json(self) -> str: ...
    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "LogicalProgram": ...
    @classmethod
    def from_json(cls, text: str) -> "LogicalProgram": ...


def logical_from_source(source: str) -> LogicalProgram: ...

@dataclass(frozen=True)
class BasisEncoding:
    logical_dimensions: tuple[int, ...]
    physical_dimensions: tuple[int, ...]
    physical_basis_indices: tuple[int, ...]

    @property
    def logical_size(self) -> int: ...
    @property
    def physical_size(self) -> int: ...

    def encode_vector(
        self, logical_state: tuple[complex, ...]
    ) -> tuple[complex, ...]: ...

    def isometry_matrix(
        self, *, max_physical_dimension: int = 64
    ) -> tuple[tuple[complex, ...], ...]: ...

    def to_dict(self) -> dict[str, Any]: ...
    def to_json(self) -> str: ...
    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "BasisEncoding": ...
    @classmethod
    def from_json(cls, text: str) -> "BasisEncoding": ...
```

`logical_from_source` is strictly `LogicalProgram(lower(parse(source)))`. It must preserve existing parser diagnostics, including source line numbers. The public constructor must take a real `CircuitIR` instance, with no string parsing or implicit coercion. `LogicalProgram` holds the existing immutable IR and does not create another gate representation. An empty operation tuple is valid; an empty register tuple is not.

`BasisEncoding` deliberately does not store physical gates, hardware properties, a score, or verification status. Those belong to later stages. In-memory core constructors accept **tuples only** for their own tuple-valued fields, to ensure immutable/canonical state. JSON decoders convert validated arrays to tuples. No implicit string-to-int, float-to-int, dimension inference or register renaming is allowed.

## 4. LogicalProgram field validation

| Field | Type | Validations | Failure |
|---|---|---|---|
| `ir` | `CircuitIR` | `isinstance(ir, CircuitIR)`; existing IR invariants already applied | `TypeError`, `Q3-LIR-001` |
| `dimensions` | Derived read-only tuple | Exactly `tuple(r.dimension for r in ir.registers)` | N/A |
| `state_size` | Derived read-only int | `math.prod(dimensions)` | N/A |
| register `name` | Existing `Register.name` | Existing identifier regex, distinct names, exact declaration order | Existing IR `ValueError` |
| register `dimension` | Existing `Register.dimension` | Exact `int`, `2 <= value <= 32` | Existing IR `ValueError` |
| operation `kind` | Existing `GateKind` | Only `shift`, `fourier`, `sum` | Existing IR `ValueError` |
| operation `target` | Existing `Operation.target` | Exact nonnegative int, less than register count | Existing IR `ValueError` |
| operation `control` | Existing `Operation.control` | `None` for unary gates; distinct in-range exact int for SUM | Existing IR `ValueError` |

**Resource policy:** A `LogicalProgram` may represent an existing, otherwise-valid `CircuitIR` larger than the v0.2.1 simulator limit; constructing it shall not allocate a statevector. Simulation still refuses more than 65,536 amplitudes. A logical program may therefore be well-formed but not executable or verifiable under current resource limits.

**Source round-tripping:** Canonical logical-program JSON preserves register names/order, resolved operations, gate kinds and operand order. It does **not** preserve comments, blank lines, source line numbers or the original interleaving of register declarations and gates. It is semantic IR serialization, not lossless source-code serialization.

## 5. BasisEncoding field validation and semantics

| Field | Type | Validations | Failure code |
|---|---|---|---|
| `logical_dimensions` | Exact `tuple[int, ...]` | Nonempty; each exact int in `2..32`, never bool | `Q3-ENC-001` |
| `physical_dimensions` | Exact `tuple[int, ...]` | Nonempty; each exact int in `2..32`, never bool | `Q3-ENC-001` |
| `physical_basis_indices` | Exact `tuple[int, ...]` | Elements exact int, never bool; length exactly `D_L` | `Q3-ENC-003` |
| Capacity | Derived | `D_P >= D_L` | `Q3-ENC-002` |
| Mapping range | Per mapped index | `0 <= index < D_P` | `Q3-ENC-005` |
| Injection | Entire mapping | All `D_L` mapped physical indices distinct | `Q3-ENC-004` |
| Explicit-map resource cap | Derived | `D_L <= 65536` mappings in v0.3; **no physical-space cap at construction** | `Q3-ENC-006` |

The 65,536 *mapping-entry* cap bounds the v0.3 **explicit mapping representation**, not the size of the physical Hilbert space. A small logical system may be encoded into an arbitrarily large physical space without allocating its full statevector. The physical capacity is not capped in the data model; operations that allocate a physical vector or dense matrix must enforce their own limits. This separation avoids embedding a simulator restriction in future hardware-aware compiler data. `LogicalProgram` is not capped by the explicit-map limit. Check products and limits **before** expensive allocation; never truncate input.

Define `M = physical_basis_indices`, where `M[j]` is the flat physical basis index of the **j-th flat logical basis state**. The encoding matrix `V` has shape `(D_P, D_L)` and exactly one nonzero entry per column:

```
V[k][j] = 1+0j if k == M[j] else 0+0j
```

There are no arbitrary per-basis phases in the v0.3 representation. Injection implies `V.conj().T @ V = identity(D_L)` **exactly** over the defined integers. Rows corresponding to unused physical states are zero in `V`.

`encode_vector(a)` applies `V` linearly: returns a new tuple `b` of length `D_P`, initialised to zero and populated by `b[M[j]] = a[j]`. It accepts **unnormalised states, including the zero vector**; it must not normalise, measure, silently discard amplitudes or invent ancilla states. Validation: tuple of exactly `D_L` built-in finite `int`, `float` or `complex` amplitudes (excluding `bool`), converted to built-in `complex`; reject strings, bytes, generators, incorrect length, NaN, infinity and unrepresentable values. Return type is `tuple[complex,...]`. Before allocating the physical vector, require `D_P <= 65536` and otherwise raise `Q3-STATE-003`; this does **not** invalidate the encoding object. This operation has cost `O(D_P + D_L)` and does not require a dense matrix.

`isometry_matrix` is **diagnostic only** and restricted to `D_P <= max_physical_dimension`, default 64; this call also requires the limit to be an exact positive int. It returns `D_P` immutable row tuples each containing `D_L` built-in complex numbers. It raises a resource-limit error rather than allocating a larger dense matrix. The encoding object itself may describe a larger physical space.

### Worked example — one logical qutrit to two physical qubits

```
logical_dimensions       = (3,)
physical_dimensions      = (2, 2)
physical_basis_indices   = (0, 1, 2)

|0>  -> |00>   (physical flat index 0)
|1>  -> |01>   (physical flat index 1)
|2>  -> |10>   (physical flat index 2)
unused physical basis    = |11> (physical flat index 3)

encode_vector((a,b,c)) -> (a,b,c,0j)

V = [[1,0,0],
     [0,1,0],
     [0,0,1],
     [0,0,0]]
```

A dimension-4 physical space alone does not guarantee that physical Q3# gates can realise any desired embedded qutrit unitary. Mathematically valid matrices may require gate synthesis that has not been implemented.

## 6. Canonical wire format v1

Use UTF-8 JSON, with top-level `schema` and `schema_version` discriminator fields. The schema version is an **exact JSON integer `1`**, independent of Python package version `0.3.x`. Every field listed below is required. Unknown fields and unknown schema versions fail closed; a future version may add fields under a new schema version without silently redefining v1.

### Logical program JSON example

```json
{
  "schema": "q3hash.logical-program",
  "schema_version": 1,
  "registers": [
    {"name": "control", "dimension": 3},
    {"name": "target", "dimension": 3}
  ],
  "operations": [
    {"kind": "fourier", "target": 0, "control": null},
    {"kind": "sum", "target": 1, "control": 0}
  ]
}
```

Schema keys are exactly `schema`, `schema_version`, `registers`, `operations`. Every register element has exactly `name`, `dimension`. Every operation element has exactly `kind`, `target`, `control`. The `control` key is **required** and is JSON `null` for unary gates. A SUM control must be a JSON integer and refer to a different valid register index. Array order is semantically significant: do not sort `registers` or `operations`.

### Basis encoding JSON example

```json
{
  "schema": "q3hash.basis-encoding",
  "schema_version": 1,
  "kind": "basis-injection",
  "logical_dimensions": [3],
  "physical_dimensions": [2, 2],
  "physical_basis_indices": [0, 1, 2]
}
```

Schema keys are exactly `schema`, `schema_version`, `kind`, `logical_dimensions`, `physical_dimensions`, `physical_basis_indices`. `kind` is required and must equal `"basis-injection"`. Dimension and index arrays are required, and their order must not change. No `null` is accepted unless a field is expressly nullable (the logical operation `control` is the sole nullable field in these schemas).

### Deterministic canonicalisation rules

- `to_dict()` returns a freshly allocated hierarchy of only native JSON-compatible primitives: dict, list, str, int, and `None`. It returns no enums, tuples, `complex` values or internal object references.
- `to_json()` uses `json.dumps(to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)` and returns **no trailing newline**.
- `from_json(text)` requires `type(text) is str`, rejects invalid UTF-8 surrogate material, non-standard `NaN` and `Infinity`, duplicate object keys (via `object_pairs_hook`), and payloads over 1 MiB encoded as UTF-8. It delegates all type and schema checks to `from_dict()`.
- JSON numeric types must be exact integers for dimensions, indices and schema version; JSON `true`, `false`, `1.0`, `"3"` are **not** accepted as integers.
- `from_dict()` requires `type(value) is dict`, exact required field sets at every object level, exact list types for arrays, and correct nested types. Convert validated arrays to canonical tuples internally; do not coerce malformed data.
- Semantic round-trip: `from_json(to_json(x)) == x`; canonical bytes must match after reserialising any semantically valid, field-order-permuted input object. JSON object-key order is insignificant; JSON array order is significant.
- Do not serialise numerical output amplitudes through either contract; numerical results and verification reports get their own separately versioned schemas later.
- Hashing for reproducibility may use SHA-256 of the UTF-8 canonical JSON bytes. A hash is an identifier of the exact canonical representation, not a quantum correctness proof.

### Cross-object compatibility

Before comparing a logical program, physical implementation and encoding, validate:

```
logical.ir.dimensions == encoding.logical_dimensions
physical_ir.dimensions == encoding.physical_dimensions
```

For a reference physical matrix, its shape must be `(D_P, D_P)`; for the logical operator `(D_L, D_L)`. A missing or mismatched dimension contract is an invalid comparison input, **not** an equivalence failure.

## 7. Error and unsupported-result behaviour

### Exception policy

Keep Python's existing `TypeError`/`ValueError` patterns. New public APIs:

- Raise `TypeError` for wrong *top-level* Python argument types (e.g., passing a string instead of `CircuitIR`, non-dict to `from_dict`, non-str to `from_json`, or a list instead of the tuple required by a direct core constructor).
- Raise `ValueError` for incorrect semantic values, unexpected/missing JSON fields, bad nested types or malformed encodings, using **stable diagnostic code prefixes** listed below. Internal error text after the prefix may change; client code should key on the prefix, not English wording. If a later typed exception hierarchy is introduced, it must remain compatible with the built-ins.
- Do not convert a user-input failure to a generic verifier `fail`. A `fail` result is reserved for well-formed, supported candidates that violate the equivalence criterion. A `unsupported` result is reserved for valid candidates beyond explicit verification limits or capabilities.
- Do not catch an arbitrary exception and silently label it `unsupported`. Coding defects should remain visible in CI.

| Code | Trigger | Outcome |
|---|---|---|
| `Q3-LIR-001` | LogicalProgram receives wrong `ir` type | `TypeError` |
| `Q3-ENC-001` | Empty/non-tuple/invalid dimensions, bool or noninteger entries | `TypeError` for direct non-tuple; otherwise `ValueError` |
| `Q3-ENC-002` | Physical capacity below logical capacity | `ValueError` |
| `Q3-ENC-003` | Mapping is wrong type, length or element type | `TypeError` for direct non-tuple; otherwise `ValueError` |
| `Q3-ENC-004` | Two logical basis states map to one physical index | `ValueError` |
| `Q3-ENC-005` | Mapped physical index outside `[0,D_P)` | `ValueError` |
| `Q3-ENC-006` | Explicit logical basis map requires over 65,536 entries | `ValueError` |
| `Q3-STATE-001` | Initial state wrong container type, element type or length | `TypeError` for container; otherwise `ValueError` |
| `Q3-STATE-002` | Nonfinite or unrepresentable amplitude | `ValueError` |
| `Q3-STATE-003` | Physical output space exceeds 65,536 amplitudes for `encode_vector` | `ValueError` |
| `Q3-DENSE-001` | Request for dense isometry exceeds caller's explicit limit | `ValueError` |
| `Q3-SER-001` | Malformed JSON, nonfinite JSON literal, invalid Unicode or payload too large | `ValueError` |
| `Q3-SER-002` | Duplicate object key | `ValueError` |
| `Q3-SER-003` | Missing or unknown field, or wrong nested JSON type | `ValueError` |
| `Q3-SER-004` | Wrong `schema`, unsupported `schema_version` or encoding `kind` | `ValueError` |
| `Q3-COMP-001` | Logical/physical dimensions do not match the encoding contract | `ValueError` |

**Validation precedence for deterministic diagnostics:** (1) public top-level types, (2) schema discriminator/version and exact object fields, (3) dimensions and their products/caps, (4) mapping length/element type, (5) mapping range, (6) mapping uniqueness, (7) vector values or requested allocation limit. This ordering ensures consistent errors when several defects coexist. Existing `CircuitIR` invariants remain authoritative when building logical programs.

### Verification statuses (future verification layer)

- `pass`: mathematical criterion verified at the declared tolerance and evidence level.
- `fail`: valid, supported candidate exceeds a numerical correctness/leakage/unitarity threshold.
- `unsupported`: valid request cannot be checked because of a declared backend/size/operator limitation.

A theoretical `ReferenceOperator` pass must be labelled **reference-only**, not a synthesised executable physical circuit. An explicit map requiring more than 65,536 entries is rejected by the constructor (`Q3-ENC-006`); an otherwise valid encoding with large physical capacity is representable, but `encode_vector` raises `Q3-STATE-003` and dense verification returns `unsupported`.

## 8. Normative tests before implementation approval

| ID | Case | Expected result |
|---|---|---|
| LIR-01 | Wrap valid mixed-dimensional `CircuitIR` and round-trip JSON | Identical semantics, registration and operation order |
| LIR-02 | Existing source with interleaved declarations and operations | Consistent `logical_from_source`; canonical JSON has resolved operations |
| LIR-03 | Empty operation list with one register | Accepted |
| LIR-04 | Wrong `ir` object type | `Q3-LIR-001` |
| ENC-01 | `(3,) -> (2,2)` mapping `(0,1,2)` | Encodes `(a,b,c)` to `(a,b,c,0)`; `V†V = I_3` |
| ENC-02 | `(2,3) -> (3,2)` with a nontrivial permutation | Source and target flatten orders independently respected |
| ENC-03 | Physical capacity < logical capacity | `Q3-ENC-002` |
| ENC-04 | Missing, duplicate, negative, out-of-range or bool mapping entry | Correct deterministic failure code |
| ENC-05 | Zero/unnormalised complex state | Accepted, no automatic renormalisation |
| ENC-06 | `NaN`, `Infinity`, bad state length or string amplitude | Rejected |
| ENC-07 | Dense matrix request with physical dimension 65 and default limit 64 | `Q3-DENSE-001` |
| ENC-08 | `(3,) -> (32,32,32,32)` with mapping `(0,1,2)` | Encoding accepted; `encode_vector` raises `Q3-STATE-003`; dense verification unsupported |
| SER-01 | Two JSON objects with differing key order | Same canonical JSON output |
| SER-02 | Reordered register/mapping arrays | Not silently canonicalised; potentially different semantics |
| SER-03 | Duplicate JSON key | `Q3-SER-002` |
| SER-04 | Unknown key, missing control, wrong schema version, `true` as dimension, `3.0` as index | Rejected with appropriate code |
| SER-05 | 1 MiB+ UTF-8 JSON payload or nonstandard NaN token | Rejected |
| COMP-01 | Matching logical and encoding dimensions, physical circuit dimension | Accepted for verification preflight |
| COMP-02 | Any dimension mismatch | `Q3-COMP-001` |
| REG-01 | Existing v0.2.1 Python public imports, examples and regression suite | Remain unchanged and passing |

Additional end-to-end operator tests belong to `test_equivalence.py` and `test_verification.py`. In particular: a logical qutrit shift embedded in four physical basis states can be represented by a reference unitary cycling physical states 0→1→2→0 and fixing 3; it should pass against mapping `(0,1,2)` but must **not** be reported as an available physical gate sequence until synthesis is demonstrated. Negative tests must detect subspace leakage, relative-phase errors and state-only false positives.

## 9. Dependency rules and implementation order

- `logical_ir.py` imports existing `ir.py` and the existing `parse`/`lower` functions from `core.py`/`ir.py`. No changes to the existing gate enum are required.
- `encoding.py` uses the existing per-register limits and state-cap policy; it must not import `logical_ir.py`, `equivalence.py` or `verification.py`. Its representation is independently valid.
- `equivalence.py` consumes `LogicalProgram`, `BasisEncoding`, `CircuitIR` or a separately validated physical `ReferenceOperator`, with no reverse imports.
- `verification.py` depends on equivalence, reports and input objects; it must not own the numerical operator semantics or silently modify candidate inputs.
- A future `core.apply_state(circuit, initial_state)` is additive. It must reuse gate application code rather than rewrite `simulate` behaviour. For independent validation, tests must use separate numerical reference construction.

**Sequence:** (1) freeze schema and diagnostics; (2) add `LogicalProgram` with unit tests; (3) add `BasisEncoding` with tests and matrix-free encoding; (4) add arbitrary-state simulator API and regression tests; (5) add operator equivalence and verification reports; (6) run independent small-case audit and CI; (7) only then begin v0.4 candidate search.

## 10. Explicitly deferred decisions

1. Arbitrary complex isometries (including per-basis phases and superposition encodings), general entangled/error-correcting encodings, and non-unitary maps.
2. Logical programs without fixed logical dimensions, functions, measurement, reset, classical control and noisy channels.
3. Gate synthesis and hardware mapping of reference physical operators.
4. Encoding search, Pareto optimisation, target hardware and error models.
5. Serialization of numerical results and versioned `VerificationReport` wire schema (to be specified before its implementation).
6. Configurable higher-dimensional vector allocation and matrix-free verification for large encoded spaces.

## 11. Freeze and approval criteria

The data contract is ready for implementation only when (a) field and schema validators are accepted, (b) ordering examples and allocation limits are unambiguous, (c) exception/unsupported distinctions and stable codes are agreed, (d) positive and negative tests are identified, and (e) no conflict with the existing v0.2.1 public API remains. This document is a planning artefact; no Q3HASH repository files are created or modified by issuing it.
