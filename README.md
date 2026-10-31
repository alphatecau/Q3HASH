# Q3# / Q3HASH

**Early-stage, ternary-first, dimension-adaptive quantum language and compiler research.**

[![Python tests](https://github.com/alphatecau/Q3HASH/actions/workflows/tests.yml/badge.svg)](https://github.com/alphatecau/Q3HASH/actions/workflows/tests.yml)

The implemented v0.3.0 prototype combines a small experimental notation, a validated dimension-aware IR, a pure-Python statevector interpreter, explicit basis encodings and complete small-operator numerical checks. It is a foundation for compiler research, not a production hardware compiler. Q3# is independent of AiTec Australia.

## Implemented

- Explicit qubit, qutrit and qudit declarations; dimensions 2–32
- Mixed-dimensional tensor-product statevectors
- Cyclic `shift`, positive-exponent discrete `fourier`, and controlled `sum` gates
- Two-register entanglement, including qubit and qutrit examples
- Immutable, validated circuit models; lowering of register names to typed operations over resolved axes
- Source-line diagnostics, CLI probabilities and optional complex amplitudes
- Independent small dense-matrix checks, entanglement checks and regression tests
- Logical-program wrappers and explicit injective logical-to-physical basis maps
- Strict, versioned canonical JSON with stable diagnostics and separate allocation limits
- Additive linear `apply_state` API for arbitrary finite, unnormalised state tuples
- Full small encoded-subspace checks for global phase, relative phase, leakage and unitarity
- Distinct `pass`, `fail` and `unsupported` results; reference matrices are labelled reference-only

## Run locally

Requires Python 3.10+; no third-party runtime dependencies.

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
python -m q3hash.cli examples/bell.q3 --amplitudes
python -m q3hash.cli examples/qutrit-entangled.q3 --amplitudes
python -m q3hash.cli examples/mixed-entangled.q3
```

A qubit Bell-state program:

```text
qubit control
qubit target
fourier control
sum control target
```

The resulting state is `(|0,0> + |1,1>) / sqrt(2)`. The CLI reports probabilities 0.5 for each of `|0,0>` and `|1,1>`. Multi-register labels follow declaration order; the last register varies fastest in the underlying statevector.

`sum control target` adds the control's basis label to the target, modulo the **target dimension**, without changing the control. For two qubits it is CNOT. Different control and target dimensions are explicitly supported; see the [semantics](docs/semantics.md).

## Python API

```python
from q3hash import lower, parse, simulate

circuit = parse("qutrit c\nqutrit t\nfourier c\nsum c t")
ir = lower(circuit)
assert ir.dimensions == (3, 3)
state = simulate(ir)  # nine complex amplitudes, not sampled measurements
```

The original `Circuit`, `Register`, `Gate`, `parse`, `simulate` and `probabilities` imports remain available. For programmatic SUM gates, use `Gate("sum", target="t", control="c")`; the source syntax puts the control first, while the Python constructor preserves the original target argument.

## Verify an explicit cross-dimension implementation

```bash
q3hash-verify examples/logical-qutrit-shift.q3 examples/physical-qutrit-shift-binary.q3 --encoding examples/qutrit-binary.encoding.json
```

The logical program cycles three qutrit basis states. The supplied physical program uses two qubits and three existing Q3# gates, fixes the unused fourth basis state, and implements the same cycle on every encoded logical input. The verifier constructs complete small operators; agreement on the all-zero input alone does not suffice.

Use `python -m q3hash.verify_cli` for the equivalent module command. It prints the numerical criteria and canonical semantic SHA-256 identifiers. Exit codes are 0 pass, 1 fail, 2 invalid input and 3 unsupported. The dense verification limit is 64 physical basis states; it can be lowered explicitly. See the [operator contract](docs/contracts/operator-verification-v1.md).

```python
from q3hash import BasisEncoding, logical_from_source

logical = logical_from_source("qutrit q\nshift q")
encoding = BasisEncoding((3,), (2, 2), (0, 1, 2))
assert encoding.encode_vector((2, 1j, -3)) == (2, 1j, -3, 0j)
assert BasisEncoding.from_json(encoding.to_json()) == encoding
```

Logical dimensions remain explicit. Physical maps and implementations are supplied by the caller. Candidate generation and optimisation are deferred to v0.4 under the [locked strategy](docs/adr/0001-verified-encoding-first.md).

## Scope and limitations

Automatic dimension inference, encoding search/selection, hardware-aware optimisation, formal equivalence verification, measurement, noise, hardware execution and hybrid control flow remain research targets. IR lowering resolves explicit declarations; it does not choose dimensions or generate hardware code. A reference-matrix verification pass does not establish a synthesised physical gate sequence. The current gate set is not claimed to be universal.

Simulation runs on a classical computer, uses floating-point complex amplitudes, and is limited to 65,536 amplitudes. It demonstrates mathematical states within this model, not quantum hardware performance or quantum advantage.

Encoding objects cap explicit logical mapping entries at 65,536 but may describe larger physical spaces without allocation. Vector embedding and dense verification enforce their own separate limits. Verification reports are currently in-memory objects and human-readable CLI output, without a public numerical-report JSON schema.

## Repository contents

- `src/q3hash/ir.py`: validated circuit models, resolved operations and lowering
- `src/q3hash/core.py`: parser and statevector interpreter
- `src/q3hash/cli.py`: example runner
- `src/q3hash/logical_ir.py`: logical wrapper and canonical semantic serialization
- `src/q3hash/encoding.py`: explicit basis injections and matrix-free vector encoding
- `src/q3hash/equivalence.py` and `verification.py`: complete small operators and verification policy
- `src/q3hash/verify_cli.py`: explicit logical/physical comparison
- `examples/`: original examples plus qubit, qutrit and mixed-dimensional entanglement
- `tests/`: regression, IR, CLI and independent matrix tests
- [Language specification](docs/language-spec.md)
- [Gate semantics and basis ordering](docs/semantics.md)
- [Validation method and reproduction](docs/validation.md)
- [Distribution builds and independent numerical audit](docs/build-and-audit.md)
- [Logical IR and encoding contracts](docs/contracts/logical-ir-and-encoding-v1.md)
- [Operator verification contract and test vectors](docs/contracts/operator-verification-v1.md)
- [Architecture](docs/architecture.md) and [six-month roadmap](docs/roadmap.md)
- `benchmarks/`: methodology; no performance results yet
- `.github/workflows/tests.yml`: Python 3.10–3.13 CI

## Scientific commitments

Design claims are hypotheses until independently tested. Comparisons must disclose equivalent workloads, dimensions, hardware, compiler choices, reproducibility instructions and uncertainty. Ternary encoding is not automatically more efficient than binary encoding. The test oracle is a separate matrix construction within this repository, supplemented by an optional NumPy/SciPy comparison. These checks are not an external audit or formal proof.

## Website

https://q3hash-lab.leafypony13.chatgpt.site

The hosted preview currently uses a separate web v0.1 runtime and its own `q3 0.1; register ...; F ...;` grammar. This Python package uses the line-based v0.2 grammar documented above. The two implementations are not yet source-compatible; a web compiler result is not evidence that this Python package compiled the same source.

## Contributions and licensing

See [CONTRIBUTING.md](CONTRIBUTING.md), [CHANGELOG.md](CHANGELOG.md) and the Apache 2.0 [LICENSE](LICENSE).
