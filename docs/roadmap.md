# Six-month Q3# research roadmap

The six-month sequence remains the project direction. A code milestone is not evidence that the elapsed month or every broader research question is complete.

1. **Month 1 — Foundations:** public repository, reproducible examples, parser, statevector baseline and regression tests. Implemented in the v0.1 baseline.
2. **Month 2 — Formalise semantics:** typed IR, richer gate set and multi-register operations; independent correctness tests. The v0.2 milestone implements documented gate/basis semantics, validated named and resolved IR, controlled SUM, entanglement examples and independent small dense-matrix tests. A complete compiler type system, universal gate set and external audit are not delivered.
3. **Month 3 — Inference:** candidate dimension/encoding generation, constraints and exhaustive small-case validation. Not implemented.
4. **Month 4 — Resource models:** benchmark design and hardware-conditioned depth/gate/fidelity tradeoffs with uncertainty reporting. Methodology only; no results.
5. **Month 5 — Verification:** equivalence tooling, external reference implementations and benchmark reproducibility. Formal verification remains unimplemented; current numerical regression tests are groundwork.
6. **Month 6 — Demonstration:** end-to-end benchmark suite, technical report and peer-reviewable public examples. Remains a target.

The next planned capability is dimension/encoding inference under explicit constraints. Keep current interpreter semantics and regressions as its reference baseline.

Every delivered milestone requires executable tests, a passing CI run for its commit and documented limitations. Future capabilities must remain labelled as targets until demonstrated.
