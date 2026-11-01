# Six-month Q3# research roadmap

The six-month direction is retained. [ADR 0001](adr/0001-verified-encoding-first.md)
locks verified logical-to-physical encoding before automated search or optimisation.
Version/month labels are research milestones, not elapsed-time claims or deadlines.

1. **Months 1–2 — Preserve the foundation:** explicit-dimension notation, parser,
   typed resolved IR, statevector baseline, examples, regression tests and real
   distribution checks. v0.2.1 is the preserved regression baseline.
2. **v0.3 / Month 3 — Explicit encoding correctness:** LogicalProgram,
   BasisEncoding, canonical data contracts, additive arbitrary-state application
   and complete small-subspace numerical checks. The supplied qutrit-shift workload
   has an explicit two-qubit gate implementation. Reference-only matrices remain
   distinct from physical Q3# gate sequences. Formal proof and gate synthesis are
   not delivered by these numerical checks.
3. **v0.4 / Month 4 — Bounded candidates and comparisons:** dimension/encoding
   generation, constraint rejection, declared search bounds and deterministic
   Pareto comparisons. Implemented in v0.4.0: bounded maps, complete supplied-circuit
   statuses, cumulative verification budgets, strict aggregate reports and the
   [search CLI](search-cli.md). The [v1 search contract](contracts/encoding-search-v1.md)
   and [implementation sequence](plans/v0.4-implementation.md) define the delivered
   domain, evidence limits and acceptance gates. Every map still requires an
   explicitly supplied circuit; hardware cost models and general synthesis are deferred.
4. **v0.5 / Month 5 — Defensible hardware-conditioned costs:** gate requirements,
   connectivity, depth, durations, error models, synthesis overhead, external
   framework references and equivalent benchmark workloads with uncertainty.
   The [hardware contract](contracts/hardware-profile-v1.md), fixed equivalent
   workloads and executable mathematical reference cases are defined. They use
   synthetic profiles and preserve unknown duration, calibration and circuit-error
   data. v0.5.0.dev1 implements the [input models/strict JSON](hardware-profiles.md)
   and independent Cirq baseline. Cost assessment, reports and hardware CLI remain
   pending; the [work packages](plans/v0.5-implementation.md) define their order.
   Routing, synthesis and noise composition need later contracts.
5. **v0.6 / Month 6 — Reproducible research demonstration:** reconcile the separate
   web/core runtimes, publish comparisons against a tagged core and deliver a
   technical report with peer-reviewable examples. Remains a target.

The next implementation step is matrix-free native feasibility, bounded hardware
work accounting and conditional timing, followed by reports and a hardware CLI.
Existing interpreter semantics and
regressions remain the reference baseline. Every delivered milestone requires
executable tests, passing CI for its exact commit and documented limitations.
