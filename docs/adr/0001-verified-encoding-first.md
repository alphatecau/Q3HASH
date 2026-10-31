# Q3# / Q3HASH — Architecture Decision Record 0001

**Status:** Strategic direction locked by project owner; technical design pending
**Decision date:** 1 November 2026
**Project:** Q3# / Q3HASH
**Repository:** https://github.com/alphatecau/Q3HASH
**Document status:** Repository copy for the controlled v0.3 change series. The original standalone record's publication note below is historical.

## 1. Locked strategic objective

Q3# will become a **ternary-first, dimension-adaptive quantum-language and compiler research platform** whose defining contribution is to **construct, verify, compare and explain alternative physical encodings of the same logical quantum computation** under explicit constraints.

The program must not presume that qubits, qutrits, qudits or mixed-dimensional configurations are universally superior. It must state the objective, candidate search space, logical correctness requirements, physical gate model and uncertainty before making recommendations.

**Immediate priority: correct logical-to-physical encoding before automated inference or optimisation.**

## 2. Decisions that are locked

1. **Preserve the six-month Q3# research direction** and the independent identity of Q3# (separate from AiTec Australia).
2. **Preserve the existing v0.2.1 Python interpreter and dimension-aware IR as the regression baseline.** Existing semantics, tests, examples, build checks and validation evidence must remain intact unless explicitly superseded by a tested change.
3. **Separate logical and physical representations.** A Logical IR represents what a quantum computation means; a Physical IR represents how a particular dimensional encoding implements it.
4. **Introduce explicit encoding maps and verification.** For a unitary logical operation U_L and an encoding isometry V, require V†V = I and verify U_P V ≈ exp(iφ) V U_L on the declared encoded subspace, subject to specified ancilla and leakage conditions. This mathematical contract is a planning starting point; detailed treatment of global phase, compositionality and numerical tolerances remains to be designed.
5. **Verify complete small cases, not only all-zero-state examples.** Use exhaustive small-case operator/subspace checks and independent reference implementations. Numerical checks are evidence, not formal proof. Measurement, noise and hybrid processing require their own equivalence specifications.
6. **Generate candidates only within explicit constraints.** Consider binary, ternary, higher-dimensional and mixed register encodings. Reject candidates that fail semantic, capacity, gate or hardware constraints. State search bounds and pruning criteria.
7. **Compare defensible costs.** Report gate requirements, register resources, circuit depth, architecture connectivity, gate duration, errors, synthesis overhead and uncertainty as data becomes available. Prefer Pareto comparisons to unsupported universal rankings.
8. **Make results explainable and reproducible.** Report mappings, candidate rejection reasons, objective functions, verified properties, numerical bounds, assumptions, source/benchmark versions and unresolved limitations.
9. **Use the existing ChatGPT + GitHub + GitHub Actions workflow.** Do not introduce Termux, new hosting systems or unrelated tooling without a compelling identified need.
10. **Defer nonessential features.** AI coding assistants, GPU acceleration, bespoke hardware adapters and advanced dashboard design are subordinate to verified compiler correctness and benchmark evidence.

## 3. Milestone sequence (retained within the original six-month direction)

| Stage | Strategic deliverable | Exit criterion |
|---|---|---|
| Months 1–2 (existing foundation) | Explicit-dimension simulator, parser, typed resolved IR, CLI, reproducibility and regression tests | Preserve versioned baseline; review CI for exact commit |
| **v0.3 / Month 3** | Logical IR, explicit embedding/encoding maps, small-case equivalence checks | For defined workloads, full small logical operators are checked on the encoded subspace; results are independently reproducible |
| **v0.4 / Month 4** | Bounded candidate dimension/encoding generation, constraint rejection, deterministic Pareto comparisons | Search bounds, candidate reasons and output reproducibility are demonstrated |
| **v0.5 / Month 5** | Hardware-conditioned cost models, external framework references and comparable benchmarks | Workloads, compilation settings, target assumptions and uncertainties are published |
| **v0.6 / Month 6** | Unified web/core research demonstration, validated comparisons, technical report and public examples | Published demonstration is reproducible against a tagged core version |

Milestone numbering is **proposed** and not a release commitment. A month label does not mean the work has been completed or set a fixed delivery deadline.

## 4. Technical planning required before building v0.3

**A. Formal semantics.** Define the first supported logical gate family, input-state assumptions, data model, gate parameterisation, ancilla handling, global phase and compositional equivalence. Specify what is deliberately out of scope.

**B. Encoding representation.** Decide how logical basis states map to physical basis states, how unused states are treated, how encodings are serialised, and how an implementation handles leakage out of the encoded subspace.

**C. Verification.** Specify matrix/operator-level reference methods for small dimensions, tolerance rules, deterministic test cases, adversarial examples, independent oracles, and clear pass/fail/unknown statuses.

**D. Search contracts.** Define the constraints and feasible domain, candidate ordering, enumeration bounds, resource caps, objective functions, dominance/Pareto rules and rejection explanations. Identify which comparisons are structural versus physically credible.

**E. Comparative benchmarks.** Choose at least one nontrivial logical computation represented by more than one encoding; define equivalent workloads and baselines using an independently maintained quantum framework as appropriate.

**F. Software architecture.** Specify interfaces and backward compatibility between the existing v0.2.1 IR/simulator, the new Logical IR, encoding passes, verification reports and future cost models.

**G. Website reconciliation.** Plan how the separate hosted web v0.1 runtime and Python v0.2.1 implementation will converge on a common versioned grammar or a rigorously tested translation. Existing website outputs do not certify Python-core outputs.

**H. Quality and governance.** Define CI gates, test coverage, numerical precision requirements, release tagging, reproducibility evidence, issue ownership and conditions for accepting a material strategic change.

## 5. Non-goals and prohibited claims

Do not claim globally optimal compilation, general quantum advantage, verified physical-hardware superiority, universal gate support, formal theorem proving, noise-aware reliability or hardware execution until evidence supports the exact claim.

The initial v0.3 milestone is a *research foundation*, not a complete production compiler or an assurance of better performance than established frameworks.

## 6. Planning sequence — next actions, not implementation authorisation

1. Produce a **v0.3 formal specification** of Logical IR, Physical IR and EncodingMap, including exact equivalence and failure semantics.
2. Select a **reference problem** and determine the smallest independent check demonstrating meaningful cross-dimension equivalence.
3. Write **test vectors and acceptance criteria before implementation**; classify invariant checks, exhaustive tests, independent comparisons and unsupported cases.
4. Specify **interfaces and compatibility** with the existing v0.2.1 API and language syntax.
5. Review computational complexity, time/memory limits and the release/CI verification method.
6. Only then author implementation tasks and commence a controlled change series.

## 7. Change control

The strategic priorities, sequence and scientific guardrails in Sections 1–3 are accepted. Sections 4–6 explicitly identify unresolved design work. Core strategic changes require a new documented decision; ordinary implementation details may be resolved during detailed planning provided they conform to this decision.

**Historical publication note:** The original standalone record reported a connector write rejection on 1 November 2026 (HTTP 403, `Resource not accessible by integration`). This repository copy preserves its strategic decisions; see Git history for this copy's publication status.
