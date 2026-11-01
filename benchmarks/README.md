# Benchmarks

## Correctness fixtures and acceptance audits

`encoding-search-v1.json` contains the original 21 tiny-domain contract vectors.
`search-cli-v1.json` adds 17 fixed CLI cases with declared candidate order,
statuses/reasons, call/work totals, resource vectors and fronts. Cases cover
native/binary qutrit shift, ties, objective subsets, budgets and precedence,
missing circuits, truncation, empty domains, complete nine-state entangling,
seeded mixed-axis reorder, leakage and relative-phase false positives.

Run `python tools/check_search.py` against an installed/source-selected package.
Clean distribution checks additionally pass `--console PATH --isolated` to test
both the module and installed console command. These fixtures are correctness
checks, not timing measurements. The separate generator/resource/aggregate audits
remain independent implementations of their mathematical/accounting rules.

## v0.5 hardware design fixtures

`hardware-cost-v1.json` freezes 13 operator-workload cases and eight synthetic
target profiles for the [hardware contract](../docs/contracts/hardware-profile-v1.md).
The workloads include native/binary/cyclic qutrit shift, reordered qutrit and mixed
entangling circuits, leakage, relative phase, a dense-limit boundary and an explicit
missing binary entangling implementation. Missing synthesis remains missing.

Run `python tools/check_hardware_contract.py` against an installed/source-selected
package. It checks 17 placements, nine timing DAGs, six freshness cases, 14 interval
fronts, five gate-check ledgers and 13 invalid inputs, plus 900 exhaustive abstract
interval comparisons. Expected values are fixed in the fixture or obtained by tiny
independent mathematical oracles. CI and clean distribution installations run it.

All profile numbers are synthetic, including profiles that exercise reported-device
metadata; `example.invalid` URLs are provenance placeholders and are never fetched.
The audit is a design reference outside the package. It does not implement the
hardware API, run an external SDK baseline, measure device performance or establish
circuit success probabilities. See the [implementation sequence](../docs/plans/v0.5-implementation.md).

## Performance methodology

No benchmark results have been collected or verified for this prototype.

Any future benchmark must record the exact source commit, Python version,
operating system, device, register dimensions, gates, sample count, timing
method, baseline implementation and uncertainty. Statevector timings alone
are not evidence of quantum advantage or hardware speedup.

Before reporting performance gains, establish an equivalent workload and
a reproducible external baseline. The current interpreter is unoptimised,
runs locally on classical hardware and supports shift, Fourier and controlled-SUM gates.
