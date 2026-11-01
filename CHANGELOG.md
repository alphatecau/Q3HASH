# Changelog

## 0.4.0 — 1 November 2026

- Complete the bounded encoding-comparison pipeline developed in dev1–dev3: explicit seeds and flat/register-prefix maps, deterministic generation budgets, complete supplied-circuit statuses, cumulative numerical budgets, exact structural resources/Pareto fronts and strict portable reports.
- Add `q3hash-search` and `python -m q3hash.search_cli` with explicit source/constraint/encoding inputs, bounded UTF-8 reads, readable coverage summaries and canonical JSON. Distinguish numerical failures, invalid input and valid partial/inconclusive results with documented exit codes.
- Include native/binary qutrit comparison inputs and a CLI guide. Update architecture, contracts, roadmap and reproduction instructions to match the delivered scope.
- Add 25 CLI tests to the preserved 161-test baseline, plus 17 fixed process-level acceptance cases. Clean wheel/source checks exercise both module and installed console entry points, repeated canonical reports and invalid-input diagnostics on Python 3.10–3.13.

This is a source release of a bounded research comparison tool. Physical circuits remain explicitly supplied. Hardware-conditioned cost models, general synthesis, automatic dimension inference and website integration remain research targets. The stable v0.3.0 tag is preserved.

## 0.4.0.dev3 — 1 November 2026

- Evaluate every retained candidate under shared call and gate-column budgets, validating all circuit bindings and program IDs before numerical work. Preserve operation/dense-limit precedence, charge failures, and allow later smaller circuits after a work-budget skip.
- Add immutable aggregate reports with complete inputs, statuses, exact resources/fronts, canonical program IDs, numerical environment and explicit partial-front diagnostics.
- Implement strict search-report JSON v1. Decode recorded evidence by replaying bounded generation, budgets, counts and fronts without invoking numerical verification; preserve historical provenance without authenticating it.
- Add 41 tests, retaining the original 120, and an independent remaining-budget/event-ledger audit of 324 runs, 236 actual circuit verifications and 324 snapshot replays. Require it in CI and clean wheel/source installations.

This completes the aggregate evaluation work package. The search CLI and final v0.4 release gates remain pending. The stable v0.3.0 tag and website are unchanged.

## 0.4.0.dev2 — 1 November 2026

- Derive exact primitive resource counts and dependency depth directly from resolved physical circuits, without allocating statevectors or claiming hardware costs.
- Add strict integer dominance and pass-only supplied-circuit Pareto fronts with retained ties, objective subsets and deterministic input order. Reject mixed workloads/settings and duplicate or colliding candidate IDs.
- Introduce validated circuit-implementation inputs and a manual single-candidate adapter to the unchanged v0.3 verifier. Comparison evidence and costs are producer-derived; failed, missing and unsupported circuits cannot enter a front.
- Add 24 focused tests and independent audits of 2,433 instruction sequences, 1,008 abstract dominance pairs and 189 verified-circuit fronts; require them in CI and clean distribution installations.

The global call/work ledger, aggregate search-report serialization and search CLI remain pending. The v0.3.0 tag and existing generator/simulator behaviour are preserved.

## 0.4.0.dev1 — 1 November 2026

- Implement bounded encoding generation with validated immutable constraints, candidates and reports; preserve explicit seeds, register order, first-origin provenance and semantic SHA-256 IDs.
- Generate flat/register-prefix maps lazily with independent tuple, mapping and unique-candidate limits, exact rejection/duplicate accounting and explicit exhausted/truncated results.
- Add strict canonical constraints/report JSON and bounded replay validation of constructed or decoded reports.
- Add 24 focused model/generation tests and an independent tensor-label/event-trace audit covering 504 parameter/budget/seed cases; run the audit in CI and clean distribution installations.

This development version completes the generation stage. Physical-circuit evaluation orchestration, structural resource/Pareto APIs and a search CLI remain pending. The stable v0.3.0 tag is unchanged.

## Design baseline — 1 November 2026

- Define bounded search interfaces, map families, deterministic generation and numerical-work budgets, evidence states, exact resource/Pareto rules and strict report contracts before production implementation.
- Add 21 executable reference-vector cases and require them in CI and clean distribution checks.
- Define the dependency-ordered v0.4 implementation and benchmark sequence.
- Point README CI references at `main` and identify the fixed v0.3.0 release baseline.

That design-only change retained package version 0.3.0 and did not implement production generation, search orchestration or comparison APIs.

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
