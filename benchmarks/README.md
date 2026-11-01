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

## Performance methodology

No benchmark results have been collected or verified for this prototype.

Any future benchmark must record the exact source commit, Python version,
operating system, device, register dimensions, gates, sample count, timing
method, baseline implementation and uncertainty. Statevector timings alone
are not evidence of quantum advantage or hardware speedup.

Before reporting performance gains, establish an equivalent workload and
a reproducible external baseline. The current interpreter is unoptimised,
runs locally on classical hardware and supports shift, Fourier and controlled-SUM gates.
