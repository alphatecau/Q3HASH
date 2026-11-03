# v0.6 deterministic three-way qutrit-shift acceptance benchmark

**Status:** Proposed development fixture. The v0.5.0 tag and commit `f09e980067ded467edc543a767c65233e8dca00c` remain unchanged. This fixture is not a device measurement, automatic dimension inference, synthesis, routing or proof of physical advantage.

## Same logical semantics

All three supplied physical circuits implement the **same** logical `qutrit q; shift q` map, the cyclic permutation `|0> → |1> → |2> → |0>`.

The basis injection always maps logical basis `(0,1,2)` onto physical flat indices `(0,1,2)`. The interpreter's *rightmost register fastest* convention applies. The logical operator, full physical operator and isometry are compared with a single allowed global phase; the acceptance conditions are the full encoded-subspace Frobenius residual, leakage, and the **full** unitarity of logical and physical operators, each at most `1e-10`. These bounded numerical checks are not formal proof for arbitrary programs.

| Case | Physical dimensions | Supplied circuit | Physical sites | Structural vector* | Synthetic critical path |
| --- | --- | --- | --- | --- | --- |
| Native | `(3,)` | `qutrit q; shift q` | `(0,)` | `[1,3,0,1,0,1]` | `40,000–60,000 ps` |
| Binary | `(2,2)` | `qubit a; qubit b; sum a b; sum b a; shift b` | `(1,2)` | `[2,2,1,3,2,3]` | `390,000–490,000 ps` |
| Mixed | `(2,3)` | `qubit a; qutrit b; shift b` | `(1,3)` | `[2,3,3,1,0,1]` | `5,000–8,000 ps` |

*Structural vector order: physical registers, maximum register dimension, unused physical basis states, gate count, two-register gate count, dependency depth. A spectator qubit is included in mixed-case active-site/resource counts.*

The mixed case is a **spectator-qubit** construction for equivalence coverage, **not** evidence that active mixed-dimensional computation outperforms a native qutrit. Its shorter synthetic interval is an intentionally chosen property of the fictitious site-3 `shift` duration in the **unchanged** `examples/qutrit-hybrid.hardware.json` fixture, and is not a physical speed claim.

## Generator coverage and partial front

`examples/qutrit-three-way.constraints.json` copies the existing fixture, changing **only** `max_physical_size` from `4` to `6`. The original v0.5 search constraints remain unchanged. The bounded generator consequently emits four physical dimension tuples: `(3,)`, `(2,2)`, `(2,3)` and `(3,2)`. We supply implementations only for the first three. The `(3,2)` candidate is explicitly `unimplemented` and must never be silently dropped or represented as a verified candidate.

The three supplied circuits pass the full source verifier before resources or synthetic hardware costs are evaluated. Under the included synthetic profile and the default four hardware objectives (active sites, native operations, two-site operations and critical path) the **conditional, partial** Pareto front contains native and mixed placements, while the binary implementation is dominated. This ranking applies **only to verified supplied placements**; it is not a complete search over possible physical circuits, and is not globally optimal.

## Independent and integrated acceptance checks

Run from the checked-out repository root after installing `q3hash`:

```bash
python -I tools/check_three_way_oracle.py
python -I tools/check_three_way_benchmark.py
python -m unittest discover -s tests -v
```

The independent oracle has no `q3hash` dependency: it constructs all full operators by explicit mixed-radix basis enumeration, recomputes resource vectors and the critical-path timing DAG, and tests adversarial leakage, relative phase, nonunitary unused complements and benign global phase. The integrated check exercises the public production API, strict report round-trip, exact status coverage, numerical metrics, resource and hardware ledgers, and the explicit partial front. Both checks fail closed on mismatches, and are included in GitHub Actions `numerics`; the regression suite also includes `tests/test_three_way_benchmark.py`.

The existing CI workflow must still pass clean wheel/sdist builds and isolated installed tests on Python 3.10–3.13, plus the NumPy/SciPy and pinned Cirq external reference jobs. A checked-in fixture and a locally passing independent oracle **do not** establish CI success until those jobs are actually run against the development commit.

## Explicit non-goals and evidence limits

- No circuit synthesis, routing, dimensional inference, device access or noise composition was added.
- The hardware profile uses static fictitious duration/error inputs; reported intervals are input-conditioned model calculations, not statistical confidence intervals.
- The `(3,2)` candidate remains an unexplored implementation; front completeness is false.
- Exact run commit, build logs, package versions and Actions URLs should be attached to the eventual pull request before marking integration verified.
