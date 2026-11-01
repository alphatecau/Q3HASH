# Build and audit procedure

The audit requires generation, budgeted verification, resource/front/report, CLI, hardware-input and internal cost modules plus their documentation/fixtures. Both clean installations run all 288 tests, seven source examples, simulator/verifier/search/hardware module and console entry points, and every existing contract/generation/resource/aggregate/CLI/cost audit. CI retains the original statevector and complete-operator numerical audits. The 0.2.1 findings and recorded results below are historical.

The v0.5.0 build requires hardware inputs/cost kernel, tests, guides, contract,
implementation plan, synthetic fixtures and audit tools in the source archive.
Both clean installations and numerical CI run the design and production cost audits.
A separate Python 3.12 CI job installs the pinned Cirq extra and actually runs the
external composition baseline. Verified hardware reports/fronts/replay and the
hardware CLI are implemented. The source archive requires the command contract,
28 CLI tests, two JSON examples, guide and 23 fixed acceptance vectors. Both clean
installations audit the hardware module and console commands, including repeated
canonical bytes, all exit classes and invalid-input diagnostics.

The repository is an experimental Python interpreter and IR project. Compiling its Python files, building distributions and running numerical tests does not establish that a complete hardware compiler exists.

## Reproduce the complete checks

Use Python 3.10–3.13. A virtual environment is recommended.

```bash
python -m pip install build "setuptools>=77.0.3" wheel
python -m compileall -q src tests tools
python -m build
python tools/check_distribution.py dist
python -m pip install ".[validation]"
python -I tools/check_numerics.py
python -I tools/check_encoding.py
python -I tools/check_search_contract.py
python -I tools/check_search_generation.py
python -I tools/check_resources_comparison.py
python -I tools/check_search_evaluation.py
python -I tools/check_search.py --isolated
python -I tools/check_hardware_contract.py
python -I tools/check_hardware_costs.py
python -I tools/check_hardware_reports.py
python -m pip install ".[external-validation]"
python -I tools/check_external_operators.py
```

The application itself still has no third-party runtime dependencies. NumPy and SciPy are optional validation tools. The separate external-validation extra pins Cirq 1.7.0 and requires Python 3.11+; use Python 3.12 to reproduce that CI job. Core/distribution checks still support Python 3.10–3.13. A build needs the declared setuptools backend; normal isolated builds obtain it automatically.

## Distribution checks

The distribution checker validates wheel contents, SPDX licence metadata and every hashed RECORD entry. It extracts the source archive, requires the examples and documentation, and uses two new virtual environments outside the repository checkout.

One environment installs the built wheel. The other installs a wheel rebuilt solely from the extracted source archive. Both run the full regression suite from the extracted source tree, compile the installed modules, run every example through both `python -m q3hash.cli` and the `q3hash` console command, and check dependency consistency. An import-path assertion verifies that tests use the installed package rather than an editable checkout.

The archive directory must contain exactly one wheel and one source archive. Remove or choose a new output directory before building a different version. The outer environment needs setuptools and wheel because the source rebuild deliberately disables network access and build isolation; the two runtime environments have no system-site packages.

## Exact-commit release procedure

After local clean distribution/numerical checks, submit the complete source tree
and require all six CI jobs: Python 3.10–3.13 distributions, independent numerical
audits and the pinned Cirq composition baseline. Merge only the reviewed head SHA, then check that the merged tree equals
the tested tree and that main CI passes for the merge commit. Once the milestone's
full release gates are complete, create the version
tag at that exact commit, verify its identity and CI, and publish source release
notes with the test counts, CI link and scope. Preserve older version tags.
The GitHub source release does not publish to PyPI or deploy the separate website.

## Independent numerical checks

The numerical checker uses SciPy's normalised DFT matrix, conjugated to match Q3#'s positive-exponent Fourier convention. Its tensor implementation uses NumPy contraction, axis movement and cyclic rolls, without production strides, gate matrices or lowering helpers.

It compares all Fourier columns for every dimension 2–32; exercises controlled SUM for all 961 control/target dimension pairs in both axis orders; runs 120 deterministic composed circuits with spectator registers; and checks known entanglement purities through singular values. It reports dependency versions, seed, comparison count and maximum amplitude/norm errors as JSON. The tolerance is 1e-11.

These checks are independent implementations and established numerical libraries within the project's automated validation. They are not an external peer review, formal proof, hardware test or performance benchmark.

## Defects identified in the initial full audit

The v0.2.0 source archive omitted examples and documentation. Its bundled regression suite consequently failed with missing example files: two failures and three errors. Editable checkout CI did not detect this. `MANIFEST.in` now includes the files required for reproduction, and CI tests real distributions on every supported Python version.

The old licence table produced a setuptools deprecation warning. Metadata now uses the SPDX expression `Apache-2.0` and explicitly includes the existing LICENSE file; the licence text and project ownership are unchanged.

The fixes are versioned as 0.2.1. Consult the GitHub Actions run for the exact commit for the final result; this procedure alone is not evidence of a passing run.

## Recorded local audit — 31 October 2026

The starting snapshot matched all 27 public file hashes at commit `40a4bb046f11f77f10233b85eaf822f59385580a`. The parser, IR, simulator and CLI implementation files are unchanged by the 0.2.1 packaging fixes.

| Check | Observed result |
| --- | --- |
| Python bytecode compilation | Passed for source, tests and audit tools |
| Built wheel installation | 44 tests and all five examples passed in a clean runtime environment |
| Source archive rebuild and installation | 44 tests and all five examples passed in a second clean runtime environment |
| CLI entry points | Module and installed console command both passed every example |
| Wheel integrity and metadata | RECORD hashes, SPDX licence and bundled licence passed |
| Independent statevector comparisons | 2,573 passed across dimensions 2–32 |
| Maximum amplitude difference | 5.9437286907191835e-15 |
| Maximum norm error | 1.3322676295501878e-15 |
| Numerical tolerance | 1e-11 |

Numerical environment: Python 3.12.14, NumPy 2.3.5, SciPy 1.17.0; seed 20261031. Cross-version results are recorded separately by CI. No arithmetic defect was detected by these bounded numerical checks; this is not a proof for every possible program.

## Hosted website boundary

The public website is a separate web v0.1.0 implementation. Its displayed limits are dimensions 2–5 and 4,096 states, and its source grammar begins with `q3 0.1;` and uses `register`, `F`, `SUM` and terminal measurement. This Python package uses its documented v0.2 grammar, dimensions 2–32 and 65,536 amplitudes; it does not implement measurement. These are not interchangeable compiler/runtime versions.

Live browser checks on 31 October 2026 confirmed the homepage example and playground run, compilation to Q3IR/0.1, numerical verification and rejection of an unknown register at the correct source line. The qutrit example produced probabilities 1/3 at 00, 11 and 22, with seeded counts 319, 371 and 334 for 1,024 shots and seed 42. The verification view reported normalisation error 2.22e-16, unitarity error 2.48e-16 and reduced purities 1/3. The deployment service separately reported success.

These checks cover the demonstrated flows. Workspace persistence, every learning/research page, owner administration, mobile layout and all possible web programs were not exhaustively re-tested. No website source or deployment was changed by this Python packaging audit.
