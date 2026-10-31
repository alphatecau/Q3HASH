# Changelog

## 0.3.0 — 1 November 2026

- Adopt ADR 0001: verify explicit logical-to-physical encoding before candidate search or optimisation.
- Add `LogicalProgram` and `BasisEncoding`, strict canonical JSON v1, stable diagnostics and distinct model/wire/allocation budgets.
- Add linear arbitrary-state application while retaining the original zero-input simulator and shared gate application code.
- Verify complete small operators under one global phase with Frobenius subspace, leakage and unitarity criteria; distinguish pass, fail and unsupported requests.
- Add validated reference matrices labelled reference-only, a `q3hash-verify` CLI and a three-gate two-qubit implementation of logical qutrit shift.
- Add normative and adversarial tests, independent NumPy/SciPy operator checks, and installed-distribution verification of both CLI entry points.

The original source grammar and logical gate semantics are preserved. Candidate search, optimisation, hardware synthesis and report wire serialization are deferred. Numerical evidence is not formal proof or hardware execution.

## 0.2.1 — 31 October 2026

- Include examples, documentation, benchmark guidance and audit tools in source distributions.
- Replace deprecated licence metadata with an SPDX expression while retaining the Apache 2.0 licence text.
- Validate wheel integrity and run the full suite and both CLI entry points against isolated wheel/source installations.
- Add optional NumPy/SciPy comparisons across all supported dimensions and both SUM axis orders.
- Extend CI to compile sources, build actual distributions on Python 3.10–3.13 and run the independent numerical audit.

The interpreter and IR algorithms are unchanged from 0.2.0.

## 0.2.0 — 31 October 2026

- Define basis order, Fourier phase and controlled-SUM semantics.
- Add immutable, validated named circuit models and a resolved, dimension-aware IR.
- Add controlled SUM for equal and unequal register dimensions, including arbitrary operand axes.
- Add qubit Bell, qutrit entanglement and mixed-dimension entanglement examples.
- Add independent dense-matrix amplitude checks, SUM unitarity and reduced-purity tests.
- Preserve the existing Python imports and single-register gate constructors.
- Display joint basis labels in the CLI; add optional complex amplitudes and clean input errors.
- Run all examples and correctness tests in the Python 3.10–3.13 CI matrix.

This is an experimental interpreter/IR milestone. Automatic dimension inference, optimisation, hardware execution, measurement and formal verification remain future work.

## 0.1.0 — 31 October 2026

- Establish the public package layout, installable baseline, initial examples and CI.
- Implement the small parser, shift/Fourier statevector simulation and initial regression suite.
