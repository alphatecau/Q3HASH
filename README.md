<div align="center">

# Q3#

### Quantum programs. Explicit dimensions.

An experimental, ternary-first language, simulator and compiler research project.

[![Python tests](https://github.com/alphatecau/Q3HASH/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/alphatecau/Q3HASH/actions/workflows/tests.yml?query=branch%3Amain)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-64748B)](LICENSE)

[Quick start](#quick-start) · [First program](#your-first-program) · [Encoding example](#one-qutrit-two-qubits) · [Technical details](#technical-details) · [Documentation](#documentation)

<sub>Q3HASH · v0.4.0.dev3 · Pure Python · No third-party runtime dependencies</sub>

</div>

---

Q3# lets you write quantum programs with **qubits, qutrits and larger qudits in the same circuit**. You declare each register's dimension, simulate its amplitudes, and check whether a supplied physical implementation preserves the logical operation under an explicit encoding.

**Ternary-first** means three-state systems are a starting point for exploration. The research question is when different dimensions and encodings help, under stated assumptions and reproducible comparisons.

| You want to… | Q3# provides |
| :--- | :--- |
| Express a mixed-dimensional program | Small, line-based syntax and a validated intermediate representation (IR) |
| Inspect its behaviour | Complex amplitudes, probabilities and entanglement examples |
| Map a logical system into a physical space | Explicit, injective basis encodings with strict data contracts |
| Check a supplied implementation | Complete small-operator comparisons, including relative phase, leakage and unitarity |

## Quick start

Use **Python 3.10 or later**. For a fixed baseline, check out [v0.3.0](https://github.com/alphatecau/Q3HASH/releases/tag/v0.3.0). From the repository checkout, run:

```bash
python -m pip install -e .
python -m q3hash.cli examples/bell.q3 --amplitudes
```

You will see two nonzero basis states, `|0,0>` and `|1,1>`, each with probability **0.5**.

Explore a [qutrit pair](examples/qutrit-entangled.q3), a [mixed qubit–qutrit pair](examples/mixed-entangled.q3), or the complete [examples directory](examples).

## Your first program

Four lines prepare a qubit Bell state:

```text
qubit control
qubit target
fourier control
sum control target
```

The declarations create two two-state registers. `fourier` puts the control into an equal superposition; `sum` correlates the target with it. The resulting joint state is:

<p align="center"><strong>(|0,0⟩ + |1,1⟩) / √2</strong></p>

The same notation supports more than two states:

| Register | Basis labels | Declaration |
| :--- | :--- | :--- |
| Qubit | `0, 1` | `qubit q` |
| Qutrit | `0, 1, 2` | `qutrit q` |
| Qudit of dimension *d* | `0` through `d − 1` | `qudit 5 q`, for example |

## One qutrit, two qubits

A logical qutrit has three basis states. Two physical qubits have four. An **encoding** declares how the three logical states fit into that physical space:

| Logical basis label | Physical basis labels |
| :---: | :---: |
| `0` | `(0, 0)` |
| `1` | `(0, 1)` |
| `2` | `(1, 0)` |
| — | `(1, 1)` is unused |

The included example implements the logical cycle **0 → 1 → 2 → 0** with three existing Q3# gates on two qubits. It also fixes the unused fourth basis state.

```bash
q3hash-verify \
  examples/logical-qutrit-shift.q3 \
  examples/physical-qutrit-shift-binary.q3 \
  --encoding examples/qutrit-binary.encoding.json
```

The supplied example returns **`pass`**. The verifier checks the operation on the **entire encoded subspace**, so errors affecting other inputs or superpositions can be detected.

<details>
<summary><strong>Open the logical program, physical circuit and encoding</strong></summary>

**Logical program** — [logical-qutrit-shift.q3](examples/logical-qutrit-shift.q3)

```text
qutrit q
shift q
```

**Physical circuit** — [physical-qutrit-shift-binary.q3](examples/physical-qutrit-shift-binary.q3)

```text
qubit a
qubit b
sum a b
sum b a
shift b
```

**Basis injection** — [qutrit-binary.encoding.json](examples/qutrit-binary.encoding.json)

```json
{"kind":"basis-injection","logical_dimensions":[3],"physical_basis_indices":[0,1,2],"physical_dimensions":[2,2],"schema":"q3hash.basis-encoding","schema_version":1}
```

Flat physical indices `0, 1, 2` correspond to `|0,0>`, `|0,1>`, `|1,0>`. The caller supplies both the map and the physical circuit; automatic encoding search is planned for v0.4.

</details>

## Technical details

Start with the examples above; expand a section when you need its exact rules.

<details>
<summary><strong>Language, gates and basis ordering</strong></summary>

Each line contains a declaration or instruction. Register dimensions are explicit integers from **2 to 32**; declarations are checked before lowering names to resolved IR axes.

| Instruction | Meaning |
| :--- | :--- |
| `shift q` | Cyclically increment the target basis label modulo its dimension |
| `fourier q` | Apply the normalised discrete Fourier transform with a positive exponent |
| `sum control target` | Add the control label to the target, modulo the **target dimension**, leaving the control unchanged |

For two qubits, `sum` is CNOT. Unequal control and target dimensions are supported.

Multi-register labels follow declaration order, with the **last register varying fastest** in the statevector. Thus `(2, 3)` has flat basis order `(0,0), (0,1), (0,2), (1,0), (1,1), (1,2)`.

See the [language specification](docs/language-spec.md) and [gate semantics](docs/semantics.md) for the full conventions.

</details>

<details>
<summary><strong>Python API and canonical data</strong></summary>

Parse, lower and simulate a program directly:

```python
from q3hash import lower, parse, simulate

circuit = parse("qutrit c\nqutrit t\nfourier c\nsum c t")
ir = lower(circuit)
assert ir.dimensions == (3, 3)
state = simulate(ir)  # Nine complex amplitudes.
```

Declare an encoding and preserve amplitudes without normalising them:

```python
from q3hash import BasisEncoding, logical_from_source

logical = logical_from_source("qutrit q\nshift q")
encoding = BasisEncoding((3,), (2, 2), (0, 1, 2))
assert encoding.encode_vector((2, 1j, -3)) == (2, 1j, -3, 0j)
assert BasisEncoding.from_json(encoding.to_json()) == encoding
```

`LogicalProgram` wraps the validated circuit IR. `BasisEncoding` requires an injective map: every logical basis state has a distinct, in-range physical index. Both models are immutable and support versioned canonical JSON with sorted keys and no insignificant whitespace.

The decoder rejects duplicate keys, unknown fields, unsupported schema versions, malformed Unicode, nonfinite numbers and incorrect field types. Integer fields reject booleans and floats. See the [logical IR and encoding contracts](docs/contracts/logical-ir-and-encoding-v1.md).

`apply_state(circuit, initial_state)` applies the same gates to an exact tuple of finite built-in numeric amplitudes. Zero and unnormalised vectors are accepted, and their scale is preserved. `simulate(circuit)` starts in the all-zero **basis state**, with amplitude 1.

The original `Circuit`, `Register`, `Gate`, `parse`, `simulate` and `probabilities` imports remain available. In Python, construct SUM as `Gate("sum", target="t", control="c")`; source notation puts the control first.

</details>

<details>
<summary><strong>Bounded encoding generation — v0.4 development</strong></summary>

In a development checkout (`0.4.0.dev1` or later), generate a finite, explicitly
constrained set of maps for a logical qutrit:

```python
from q3hash import GenerationReport, SearchConstraints, generate_encodings

constraints = SearchConstraints(max_registers=2, max_physical_size=9)
report = generate_encodings((3,), constraints)
assert report.completion == "exhausted"
assert report.emitted_candidates == 5
assert [c.encoding.physical_dimensions for c in report.candidates] == [
    (3,), (2, 2), (2, 3), (3, 2), (3, 3)
]
assert GenerationReport.from_json(report.to_json()) == report
```

The generator visits tuples and map families in a fixed order, accepts optional
explicit seed encodings, retains the first occurrence of a map and reports every
capacity rejection, duplicate and budget stop. `exhausted` covers only the declared
families; `truncated` identifies a budget-limited prefix.

These results are encoding maps. A physical gate implementation must still be
supplied and checked with the existing verifier. Structural comparison is shown
below, followed by aggregate budgeted evaluation. A search CLI remains pending.
See the [search
contract](docs/contracts/encoding-search-v1.md) and [implementation
sequence](docs/plans/v0.4-implementation.md).

</details>

<details>
<summary><strong>Compare verified supplied circuits — v0.4 development</strong></summary>

In `0.4.0.dev2`, compare a native qutrit shift with its supplied two-qubit circuit:

```python
from q3hash import (
    CircuitImplementation, RESOURCE_OBJECTIVES, SearchConstraints,
    evaluate_candidate, generate_encodings, logical_from_source, pareto_front,
)

logical = logical_from_source("qutrit q\nshift q")
native, binary = generate_encodings(
    (3,), SearchConstraints(max_registers=2, max_physical_size=4)
).candidates
binary_ir = logical_from_source(
    "qubit a\nqubit b\nsum a b\nsum b a\nshift b"
).ir
rows = (
    evaluate_candidate(logical, native, CircuitImplementation(native.encoding, logical.ir)),
    evaluate_candidate(logical, binary, CircuitImplementation(binary.encoding, binary_ir)),
)
assert rows[0].resources.as_tuple() == (1, 3, 0, 1, 0, 1)
assert rows[1].resources.as_tuple() == (2, 2, 1, 3, 2, 3)
assert pareto_front(rows, RESOURCE_OBJECTIVES) == tuple(row.candidate_id for row in rows)
```

The counts are registers, maximum local dimension, unused basis states, primitive
gates, two-register gates and dependency depth. Both circuits remain on the default
front: binary uses fewer levels per register, while the native circuit uses fewer
registers and gates. Selecting a different objective subset can change the front.

Only circuits that pass the existing complete-subspace verifier are eligible.
Ties are retained; missing, failed and unsupported circuits are excluded. All rows
must describe the same logical program and verification settings. Counts are
structural, with an ideal disjoint-axis depth model, rather than device gate times
or hardware performance. The adapter checks one circuit at a time; use the aggregate
API below to enforce a shared call/work budget.

</details>

<details>
<summary><strong>Budgeted evaluation and portable reports — v0.4 development</strong></summary>

In `0.4.0.dev3`, evaluate all retained candidates under one shared numerical budget:

```python
from q3hash import (
    CircuitImplementation, SearchConstraints, SearchReport,
    evaluate_candidates, generate_encodings, logical_from_source,
)

logical = logical_from_source("qutrit q\nshift q")
generation = generate_encodings(
    (3,), SearchConstraints(max_registers=2, max_physical_size=4, max_verifications=1)
)
native, binary = generation.candidates
binary_ir = logical_from_source(
    "qubit a\nqubit b\nsum a b\nsum b a\nshift b"
).ir
report = evaluate_candidates(logical, generation, (
    CircuitImplementation(native.encoding, logical.ir),
    CircuitImplementation(binary.encoding, binary_ir),
))
assert [row.status for row in report.evaluations] == ["pass", "not-evaluated"]
assert report.evaluations[1].reason_code == "verification-call-budget"
assert (report.verification_calls, report.gate_column_steps) == (1, 6)
assert report.front_ids == (native.candidate_id,)
assert report.front_is_partial
recorded = SearchReport.from_json(report.to_json())
assert recorded == report
assert recorded.evidence_origin == "recorded"
```

Every retained candidate receives a status in generation order. All bindings and
options are validated before any numerical work. A failed check still consumes
its call/work budget; a skipped check consumes neither, allowing a later smaller
circuit to fit. Missing circuits remain unimplemented. Counts and fronts only use
passing supplied circuits.

Canonical reports retain inputs, generation/rejection evidence, circuit IDs,
verification snapshots, exact resources, budget totals and numerical environment.
Decoding checks generation replay, the budget plan, costs and front membership
without rerunning numerical verification. A decoded report is recorded evidence;
its metadata is not authenticated. The strict 1 MiB JSON limit raises an error
instead of truncating a large report. The search CLI is the next work package.

</details>

<details>
<summary><strong>Equivalence mathematics, evidence and CLI results</strong></summary>

Let `U_L` be the complete logical operator, `U_P` the complete physical operator, and `V` the basis injection. The verifier asks whether a **single global phase** aligns both operations:

<p align="center"><code>U_P V ≈ exp(iφ) V U_L</code></p>

The phase is chosen from the Hilbert–Schmidt inner product for the whole encoded operator. Relative phases are preserved; columns are never aligned independently. Every criterion below must be finite and within the declared absolute tolerance:

| Criterion | What it checks |
| :--- | :--- |
| Encoded-subspace Frobenius residual | Agreement on every encoded input, including superpositions |
| Leakage Frobenius norm | Amplitude escaping into unused physical states |
| Logical unitarity error | The complete logical operator preserves inner products |
| Physical unitarity error | The complete physical operator does so, including outside the encoded subspace |

Default tolerance: **`1e-10`**. See the [operator contract and test vectors](docs/contracts/operator-verification-v1.md) for exact formulas and boundary rules.

`verify_equivalence(logical, physical, encoding)` accepts a physical `CircuitIR` or an explicit `ReferenceOperator`. Reports label their evidence **`q3hash-circuit`** or **`reference-only`**. A matrix supplied for comparison does not demonstrate that a physical gate sequence has been synthesised.

| Result | Meaning | CLI exit code |
| :--- | :--- | :---: |
| `pass` | All numerical criteria meet the tolerance | `0` |
| `fail` | A criterion exceeds tolerance or its calculation is nonfinite | `1` |
| Invalid input | Types, dimensions, data or arguments are invalid | `2` |
| `unsupported` | A valid request exceeds the declared dense verification budget | `3` |

Use `python -m q3hash.verify_cli` as the module equivalent of `q3hash-verify`. Options include `--tolerance` and `--max-dimension`. Output includes the metrics and canonical semantic SHA-256 identifiers for the logical program, physical program and encoding. Numerical reports are in-memory objects and human-readable output; their public JSON format is deferred.

</details>

<details>
<summary><strong>Resource limits and validation evidence</strong></summary>

| Boundary | Limit |
| :--- | :--- |
| Dimension of each register | `2–32` |
| Simulator and allocated encoded vectors | `65,536` amplitudes |
| Explicit logical basis map | `65,536` entries |
| Physical space described by an encoding | No capacity cap at model construction |
| Dense verification and default diagnostic isometry | `64` physical basis states; verification can be limited further |
| Explicit reference matrix | `65,536` entries |
| Canonical JSON input and output | `1 MiB` of UTF-8 data |

Model construction, vector allocation and dense verification have separate budgets. An encoding can describe a large physical space without allocating its statevector; requests beyond a verifier's budget return `unsupported` before dense operators are allocated.

The development tree contains **120 unit tests**, including the unchanged **72-test v0.3 baseline** and **seven executable source examples**. Independent audits cover generation and structural comparison as well as the original numerical behaviour. CI builds and tests wheel/source distributions in clean environments across **Python 3.10–3.13**.

| Audit | Recorded coverage |
| :--- | :--- |
| Original statevector audit | `2,573` comparisons across dimensions `2–32` |
| Operator and arbitrary-state audit | `194` comparisons |
| Independent basis embeddings | `248` checks |
| Full-subspace positive cases | `253` passes |
| Expected resource-boundary cases | `20` unsupported |
| Adversarial reference cases | `3` correctly rejected |
| Bounded generation audit | `504` cases |
| Resource-count instruction sequences | `2,433` cases |
| Abstract dominance comparisons | `1,008` pairs |
| Verified supplied-circuit fronts | `189` cases |

Reproduce the tests and optional NumPy/SciPy audits:

```bash
python -m unittest discover -s tests -v
python -m pip install -e ".[validation]"
python tools/check_numerics.py
python tools/check_encoding.py
python tools/check_search_generation.py
python tools/check_resources_comparison.py
```

The [validation guide](docs/validation.md) explains the independent constructions; the [build and audit guide](docs/build-and-audit.md) covers isolated distribution checks. Consult CI for the exact commit you are using.

</details>

## Research direction

[ADR 0001](docs/adr/0001-verified-encoding-first.md) sets the order: **establish encoding correctness before searching for better encodings**.

| Milestone | Focus | Status |
| :--- | :--- | :--- |
| v0.2.1 | Parser, explicit dimensions, IR, simulator and distribution checks | Preserved regression baseline |
| v0.3 | Explicit encodings and complete small-operator checks | Implemented and merged into `main` |
| v0.4 | Bounded candidate generation and Pareto comparisons | Generation, budgeted supplied-circuit evaluation, structural fronts and strict reports implemented; CLI pending |
| v0.5 | Hardware-conditioned costs and equivalent benchmark workloads | Research target |
| v0.6 | Web/core integration and a reproducible research demonstration | Research target |

The [six-month roadmap](docs/roadmap.md) describes the milestones and acceptance criteria.

**Next development step:** add the search CLI and complete the v0.4 release gates, following the [v0.4 work packages](docs/plans/v0.4-implementation.md). Generated maps still require supplied physical circuits; hardware synthesis and a universal best-encoding claim remain outside this milestone.

**Current scope.** Q3# runs on a classical computer using floating-point amplitudes. Automatic logical-dimension inference, physical-circuit search/synthesis, hardware-aware optimisation, measurement, noise, hybrid control flow and hardware execution remain research targets. The gate set is not claimed to be universal. The numerical checks provide bounded evidence; formal proof, hardware performance and quantum advantage have not been demonstrated. Ternary encoding is not assumed to outperform binary encoding.

## Documentation

| Start here | Go deeper |
| :--- | :--- |
| [Language specification](docs/language-spec.md) | [Logical IR and encoding contracts](docs/contracts/logical-ir-and-encoding-v1.md) |
| [Gate semantics and basis order](docs/semantics.md) | [Operator verification contract](docs/contracts/operator-verification-v1.md) |
| [Examples](examples) | [Architecture](docs/architecture.md) |
| [Validation and reproduction](docs/validation.md) | [Distribution builds and audit](docs/build-and-audit.md) |
| [Changelog](CHANGELOG.md) | [Research roadmap](docs/roadmap.md) |

<details>
<summary><strong>Source map</strong></summary>

| Path | Responsibility |
| :--- | :--- |
| [ir.py](src/q3hash/ir.py) | Validated circuit models, resolved operations and lowering |
| [core.py](src/q3hash/core.py) · [cli.py](src/q3hash/cli.py) | Parsing, simulation and the example runner |
| [logical_ir.py](src/q3hash/logical_ir.py) | Logical programs and canonical semantic serialization |
| [encoding.py](src/q3hash/encoding.py) | Basis injections and vector embedding |
| [search.py](src/q3hash/search.py) | Bounded map generation, constraints, provenance and canonical generation reports |
| [resources.py](src/q3hash/resources.py) · [comparison.py](src/q3hash/comparison.py) | Exact structural counts and verified-circuit Pareto fronts |
| [evaluation.py](src/q3hash/evaluation.py) · [search_verification.py](src/q3hash/search_verification.py) | Supplied-circuit input/evidence models and the manual verification adapter |
| [equivalence.py](src/q3hash/equivalence.py) · [verification.py](src/q3hash/verification.py) | Complete small operators, comparison metrics and verification policy |
| [verify_cli.py](src/q3hash/verify_cli.py) | Logical/physical verification command |
| [tests](tests) · [tools](tools) | Regression suites and reproducible audit tools |
| [benchmarks](benchmarks) | Comparison methodology; performance results remain future work |
| [CI workflow](.github/workflows/tests.yml) | Distribution tests and independent numerical audits |

</details>

## Web preview

Visit the [Q3# research site](https://q3hash-lab.leafypony13.chatgpt.site).

The site currently uses a separate **web v0.1 runtime**, with `q3 0.1; register ...; F ...;` syntax. This Python project uses the line-based **v0.2 grammar** shown above. The implementations are not yet source-compatible, and results from one runtime do not validate the other.

---

Contributions, reproducible tests and scientifically grounded criticism are welcome. Comparisons should disclose equivalent workloads, dimensions, hardware assumptions, compiler choices and uncertainty. The independent numerical implementations live within this project; they are not an external audit.

[Contributing](CONTRIBUTING.md) · [Apache 2.0 license](LICENSE) · Q3# is independent of AiTec Australia.
