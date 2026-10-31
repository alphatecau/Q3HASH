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
   Pareto comparisons. Not implemented in the v0.3 release.
   The [v1 search contract](contracts/encoding-search-v1.md) defines the proposed
   interfaces, finite domain, budgets, failure semantics and acceptance vectors.
   Follow the [implementation sequence](plans/v0.4-implementation.md); a contract
   or a passing reference vector does not establish a delivered search engine.
4. **v0.5 / Month 5 — Defensible hardware-conditioned costs:** gate requirements,
   connectivity, depth, durations, error models, synthesis overhead, external
   framework references and equivalent benchmark workloads with uncertainty.
   Remains a research target.
5. **v0.6 / Month 6 — Reproducible research demonstration:** reconcile the separate
   web/core runtimes, publish comparisons against a tagged core and deliver a
   technical report with peer-reviewable examples. Remains a target.

The next capability after v0.3 correctness is bounded encoding search under
explicit semantic and resource constraints. Existing interpreter semantics and
regressions remain the reference baseline. Every delivered milestone requires
executable tests, passing CI for its exact commit and documented limitations.
