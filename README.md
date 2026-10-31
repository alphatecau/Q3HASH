# Q3# / Q3HASH

**Early-stage, ternary-first, dimension-adaptive quantum language and compiler research.**

[![Python tests](https://github.com/alphatecau/Q3HASH/actions/workflows/tests.yml/badge.svg)](https://github.com/alphatecau/Q3HASH/actions/workflows/tests.yml)

The implemented v0.2 prototype is a small experimental notation, a validated dimension-aware intermediate representation (IR), and a pure-Python statevector interpreter. It is a foundation for compiler research, not a production compiler. Q3# is independent of AiTec Australia.

## Implemented

- Explicit qubit, qutrit and qudit declarations; dimensions 2–32
- Mixed-dimensional tensor-product statevectors
- Cyclic `shift`, positive-exponent discrete `fourier`, and controlled `sum` gates
- Two-register entanglement, including qubit and qutrit examples
- Immutable, validated circuit models; lowering of register names to typed operations over resolved axes
- Source-line diagnostics, CLI probabilities and optional complex amplitudes
- Independent small dense-matrix checks, entanglement checks and regression tests

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

## Scope and limitations

Automatic dimension inference, alternative encoding selection, hardware-aware optimisation, formal equivalence verification, measurement, noise, hardware execution and hybrid control flow remain research targets. The IR resolves explicitly declared dimensions; it does not choose dimensions or generate hardware code. The current gate set is not claimed to be universal.

Simulation runs on a classical computer, uses floating-point complex amplitudes, and is limited to 65,536 amplitudes. It demonstrates mathematical states within this model, not quantum hardware performance or quantum advantage.

## Repository contents

- `src/q3hash/ir.py`: validated circuit models, resolved operations and lowering
- `src/q3hash/core.py`: parser and statevector interpreter
- `src/q3hash/cli.py`: example runner
- `examples/`: original examples plus qubit, qutrit and mixed-dimensional entanglement
- `tests/`: regression, IR, CLI and independent matrix tests
- [Language specification](docs/language-spec.md)
- [Gate semantics and basis ordering](docs/semantics.md)
- [Validation method and reproduction](docs/validation.md)
- [Architecture](docs/architecture.md) and [six-month roadmap](docs/roadmap.md)
- `benchmarks/`: methodology; no performance results yet
- `.github/workflows/tests.yml`: Python 3.10–3.13 CI

## Scientific commitments

Design claims are hypotheses until independently tested. Comparisons must disclose equivalent workloads, dimensions, hardware, compiler choices, reproducibility instructions and uncertainty. Ternary encoding is not automatically more efficient than binary encoding. The test oracle is a separate matrix construction within this repository, not an external audit or formal proof.

## Website

https://q3hash-lab.leafypony13.chatgpt.site

## Contributions and licensing

See [CONTRIBUTING.md](CONTRIBUTING.md), [CHANGELOG.md](CHANGELOG.md) and the Apache 2.0 [LICENSE](LICENSE).
