# Validation and reproduction

## Reproduce

From a fresh checkout with Python 3.10 or later:

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
python -m q3hash.cli examples/qutrit.q3
python -m q3hash.cli examples/mixed.q3
python -m q3hash.cli examples/bell.q3 --amplitudes
python -m q3hash.cli examples/qutrit-entangled.q3 --amplitudes
python -m q3hash.cli examples/mixed-entangled.q3 --amplitudes
```

GitHub Actions builds wheel and source distributions on Python 3.10, 3.11, 3.12 and 3.13. Each job tests the full suite and every example against isolated installations of the wheel and a wheel rebuilt from the source archive. A separate job runs the optional NumPy/SciPy comparison. See [build-and-audit.md](build-and-audit.md). Use the run associated with the exact source commit as the evidence for a published change; workflow configuration alone is not a passing result.

## Independent numerical construction

`tests/test_semantics.py` builds small dense matrices by enumerating tensor basis-label tuples with `itertools.product`. The production simulator uses resolved axes and statevector strides. The oracle does not import private production helpers or reuse production gate matrices.

- Every column of small SUM matrices is compared against an independently constructed basis permutation.
- SUM column inner products check the full small operators' unitarity.
- Fourier and shift matrices are compared across each axis of several tensor spaces.
- Seeded compositions exercise interference and compare real and imaginary amplitudes to 11 decimal places.
- Cases cover both control/target orders, unequal dimensions and non-adjacent axes with spectators.
- Bell, qutrit and mixed-dimension examples are checked against known amplitudes and reduced-state purity.
- Invalid source, model and IR inputs are rejected at their public boundaries.
- Original tests retain the statevector cap and single-register regression coverage.

The fixed pseudorandom seed is 20261031. The oracle is intentionally limited to small state spaces so it can build full matrices independently.

## Expected example results

| Example | Nonzero basis labels | Probabilities | Joint state |
| --- | --- | --- | --- |
| `qutrit.q3` | 0, 1, 2 | 1/3 each | Fourier applied after a shift of the initial qutrit |
| `mixed.q3` | (1,1) | 1 | A product basis state |
| `bell.q3` | (0,0), (1,1) | 1/2 each | Positive real amplitudes 1/sqrt(2) |
| `qutrit-entangled.q3` | (0,0), (1,1), (2,2) | 1/3 each | Positive real amplitudes 1/sqrt(3) |
| `mixed-entangled.q3` | (0,0), (1,1) | 1/2 each | Positive real amplitudes 1/sqrt(2) in a 2 x 3 space |

Equal probabilities alone do not establish equal states or entanglement. The first example has nontrivial complex phases. The entanglement tests use pure joint states and trace out one register to test reduced-state purity.

## Explicit encoding verification — v0.3

`tests/test_contracts.py` implements the data-contract vectors: tuple-only fields, exact integer rules, injective maps, independent logical/physical ordering, canonical round-trips, duplicate/unknown-field rejection, malformed Unicode, wire budgets and separate physical allocation limits. It also checks zero and unnormalised states and additive arbitrary-state application.

`tests/test_equivalence.py` checks complete encoded subspaces. Positive cases include logical qutrit shift implemented by three existing two-qubit Q3# gates, permuted mixed-dimensional maps, a global phase and a reference qutrit Fourier block. Negative cases detect leakage and relative-phase false positives that agree on the zero input, and nonunitarity outside the encoded subspace. Invalid inputs raise errors; valid oversized requests return unsupported before operator allocation.

`tools/check_encoding.py` independently constructs dense tensor matrices with NumPy/SciPy, compares every small operator column and arbitrary unnormalised vectors, checks basis injections, and audits reference-only full-subspace comparisons. Cases outside the declared dense limit are explicitly counted as unsupported rather than passing. This complements the unchanged 2,573-comparison v0.2.1 numerical oracle.

The new verifier uses absolute Frobenius norms with a default tolerance of 1e-10, a single phase for the entire operator, and full logical and physical unitarity checks. See the [operator contract](contracts/operator-verification-v1.md) for exact definitions. Reports are numerical evidence, not a formal proof or hardware demonstration.

## v0.4 contract reference vectors

Run `python tools/check_search_contract.py` from an installed checkout. Its 21
fixed cases audit tiny-domain candidate ordering and budget accounting, register
block maps, supplied complete-operator comparisons, structural dependency depth,
strict dominance and retained ties. The [search contract](contracts/encoding-search-v1.md)
defines further implementation acceptance cases, including schema validation and
orchestration budgets. Production encoding generation is implemented in the
development build; manual supplied-circuit comparison was added in dev2, and
aggregate budgeted evaluation with strict reports is implemented in dev3.

CI runs the vector audit, and clean wheel/source installation checks require the
fixture and run it using the installed package. It remains a design/reference
baseline; it is not evidence of a completed circuit-search pipeline or CLI.

## Bounded generation — 0.4.0.dev1

`tests/test_search_models.py` and `tests/test_search_generation.py` add 24 tests
for strict fields, provenance/IDs, canonical decoding with full generation replay,
immutable snapshots, independent budgets, capacity-before-allocation, lazy domain
traversal, seed ordering/deduplication, digest collisions and wire-size failures.
The original 72 tests remain intact.

`python tools/check_search_generation.py` checks 504 cases with an independent
oracle that enumerates actual tensor basis labels and interprets a separately
materialised tiny event trace. Production code uses flat-index strides and a lazy
stream. The audit compares complete candidate maps, first provenance, ordering,
IDs, completion and every counter, then checks canonical report replay. It imports
only public generation APIs. CI and clean distribution installations run it.

This establishes bounded map generation, not physical circuit synthesis,
equivalence of any generated implementation or a Pareto ranking.

## Exact resources and supplied-circuit comparison — 0.4.0.dev2

`tests/test_resources.py` and `tests/test_comparison.py` add 24 tests to the 96-test
baseline. Counts include both control/target dependencies and allocation-free
analysis of large physical spaces. Comparison tests preserve ties, objective
subsets and input order; reject mixed logical workloads/settings, repeated or
colliding IDs and reference-only matrices; and exclude missing, failed and
unsupported implementations. Corrupt/nonfinite verifier snapshots cannot become
passing comparison evidence. Unexpected verifier exceptions remain visible.

`python tools/check_resources_comparison.py` independently checks:

- 2,433 short circuits using an all-predecessor dependency DAG instead of the
  production per-axis layer algorithm, plus explicit tensor-label capacity counts.
- 1,008 exact abstract dominance pairs over all 63 nonempty objective subsets.
- 189 actual supplied-circuit fronts over those subsets and three input orders,
  using an independent all-pairs nondominance oracle. Cases include verified ties,
  a dominated padded circuit, leakage, missing circuits and operation-limit skips.

CI and clean wheel/source installations run this audit. Counts are structural
resources under the declared primitive model. Pareto eligibility is based on the
existing small-operator verifier, not hardware execution or a universal optimum.

## Aggregate evaluation and recorded reports — 0.4.0.dev3

`tests/test_search_verification.py` and `tests/test_search_report.py` add 41 tests
to the unchanged 120-test baseline. They check whole-input preflight before any
verifier call; exact call/work boundaries; failure charging and later smaller
circuits after a skip; operation/dense/budget precedence; zero-work identity calls;
missing circuits and partial fronts; complete nine-state entangling and seeded
mixed-axis workloads; and visible unexpected verifier exceptions.

Snapshot cases check canonical bytes/IDs, immutability, full generation replay,
recomputed budgets/resources/fronts with ties, historical environment preservation,
schema/field/type/order violations, forged pass/cost claims, invalid metrics/phases,
null-only nonfinite failures, duplicate keys, Unicode and symmetric wire limits.
Logical and physical program ID wire failures occur before numerical work. Tests
patch both verifier entry points to reject accidental calls during decoding.

`python tools/check_search_evaluation.py` audits 324 actual bounded runs using an
independent remaining-budget ledger, explicit (program, basis column, gate) events,
all-predecessor resource DAG and all-pairs nondominance. It checks 236 actual circuit
verifications and 324 strict snapshot replays. CI and clean wheel/source installations
run the audit. Complete reports repeat byte-for-byte in the same recorded environment;
decoded reports explicitly identify their evidence as recorded rather than computed.

## Search CLI and release acceptance — v0.4.0

`tests/test_search_cli.py` adds 25 tests to the preserved 161-test baseline. Cases
cover canonical process/API parity, readable coverage/objectives/metrics, default
missing implementations, explicit seeds and binding order, whole-file preflight,
all budget/exit precedences, identity calls, malformed source/JSON/options, bounded
UTF-8 byte reads, wire errors without partial output, unchanged inputs and visible
unexpected runtime exceptions.

`tools/check_search.py` runs 17 fixed vectors from `benchmarks/search-cli-v1.json`
through actual processes and checks independently declared candidate IDs/order,
statuses/reasons, exact call/work totals, resource vectors and front membership.
It additionally checks byte-identical repeated reports, human output, help/version
and three invalid-input diagnostics. Distribution audits run it through both the
module and installed console command: 36 JSON reports and six invalid-input cases
per clean installation, with Python isolated mode for module checks.

The fixtures include complete native/binary qutrit shift, objective subsets and
ties, call/work skips, operation/dense precedence, missing/truncated/empty domains,
complete nine-state entangling, seeded mixed-axis reorder, nonzero-input leakage
and a relative-phase false positive. These are correctness vectors, not hardware
performance benchmarks. CI runs all audits for the exact release source; publication
also checks merged/tagged source identity. Website runtime and deployment remain separate.

## Hardware design reference cases — v0.5 planning baseline

`python tools/check_hardware_contract.py` checks the fixed synthetic scenarios in
`benchmarks/hardware-cost-v1.json` against the proposed hardware contract. It runs
13 workload cases through the existing evidence rules: nine supplied circuits
pass complete-operator verification, two fail, one exceeds the dense limit and one
has no supplied implementation. The last case remains unimplemented and is not
sent to the verifier.

The audit additionally covers eight profile fixtures, 17 placed-target cases,
nine timing DAGs, six freshness boundaries, 14 interval-front cases, five bounded
work ledgers and 13 invalid-input cases. It compares interval dominance against
all integer realisations for 900 vector pairs. Timing uses exhaustive tiny
dependency paths, separate from the planned production per-site algorithm.
Target vectors check exact dimensions, ordered SUM edges, missing native gates,
zero versus missing duration, stale/unknown data and nonaggregated error records.

CI and both clean wheel/source installations run this audit. Its small reference
models are outside the package. They establish executable design expectations;
production hardware models, report codecs, hardware CLI and the independent Cirq
adapter are not delivered. The [contract](contracts/hardware-profile-v1.md) and
[implementation gates](plans/v0.5-implementation.md) specify the remaining work.
All target numbers are synthetic test values, including the fixtures exercising
reported-device metadata. No measured device costs or circuit-fidelity result is
claimed. Package version remains 0.4.0 and the 186-test regression suite is retained.

## Limits of the evidence

The dense oracle is independently implemented within the same repository. An optional numerical audit additionally compares against NumPy tensor operations and SciPy DFT matrices across the supported dimensions. Neither is an external review, a comparison with another quantum SDK, or formal verification. Finite examples do not prove correctness for every circuit. These checks establish a reproducible numerical baseline for this milestone.

No performance benchmark, quantum advantage, hardware execution, automatic dimension selection or compiler optimisation is demonstrated.
