# Q3# / Q3HASH

**Early-stage, ternary-first, dimension-adaptive quantum language and compiler research.**

This public repository is a research workspace. The implemented v0.1 starter is a **small interpreted experimental notation and pure-Python statevector simulator**, not a production compiler. Q3# is independent of AiTec Australia.

## Implemented

- `qubit`, `qutrit` and `qudit d` declarations (dimensions 2–32)
- Mixed-dimensional tensor-product statevectors
- Cyclic `shift` and discrete `fourier` gates
- Syntax validation, CLI example runner and regression tests

## Not yet implemented

Automatic dimension inference, alternative encoding selection, optimisation, entangling gates, measurements, noise, quantum hardware, formal verification and hybrid workflow execution. These are *research targets*.

## Run locally

Requires Python 3.10+.

```bash
python -m pip install -e .
python -m q3hash.cli examples/qutrit.q3
python -m unittest discover -s tests -v
```

Example:

```text
qutrit q
shift q
fourier q
```

The simulator outputs basis-state **probabilities**; it does not run quantum hardware or perform sampled measurements.

## Repository contents

- `src/q3hash/`: parser, data model, statevector simulator and CLI
- `examples/`: qutrit and mixed-register programs
- `tests/`: automated correctness checks
- `docs/language-spec.md`: actual syntax and proposed additions
- `docs/architecture.md`: component architecture and scientific constraints
- `docs/roadmap.md`: six-month research plan
- `benchmarks/`: benchmark methodology (no results yet)
- `.github/workflows/tests.yml`: continuous-integration test workflow

## Scientific commitments

Design claims are hypotheses until independently tested. Any comparisons must use equivalent workloads and disclose circuit dimensions, target hardware, gate fidelity, compiler choices, reproducibility instructions and uncertainty. A ternary encoding is not automatically more efficient than a binary encoding.

## Website

https://q3hash-lab.leafypony13.chatgpt.site

## Contributions and licensing

See [CONTRIBUTING.md](CONTRIBUTING.md). Apache 2.0 license, see [LICENSE](LICENSE).
