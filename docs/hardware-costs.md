# Hardware-cost kernel — v0.5.0

This stage implements native-gate feasibility, cumulative work accounting,
calibration freshness, exact duration ranges and used-error records in the
internal `hardware_costs.py` kernel. It completes work package 3 of the
[v0.5 sequence](plans/v0.5-implementation.md).

The kernel receives private typed requests from the [verified report producer](hardware-reports.md).
Its source-status fields are integration inputs, not newly established verification
evidence. The public `assess_hardware` API, complete HardwareReport, interval fronts
and recorded replay are implemented in v0.5.0, along with the [hardware CLI](hardware-cli.md).
The raw kernel itself remains internal.

## Derived outcomes and work

Every private input retains one output row in order. The kernel validates the
entire batch, explicit instants, placements and profile/context wire fingerprints
before inspecting gates. It then applies the contract's precedence:

| Condition | Outcome | Gate checks |
| --- | --- | --- |
| Source status is not pass | `ineligible` with the source reason | Zero |
| Passing source has no placement | `unplaced` | Zero |
| Any placed dimension differs | `unsupported` with every mismatched axis | Zero |
| Entire operation count exceeds remaining work | `not-evaluated` | Zero; later smaller rows can fit |
| A directed edge or exact native binding is missing | `unsupported` with all operation rejections | Full operation count |
| Every native operation is available | `supported` with counts and conditional timing | Full operation count |

SUM operands remain ordered as control/target. An edge does not imply a native gate,
and reverse direction uses its own binding. Rejection records preserve the exact
operation or axis index and ordered site tuple. No routing or decomposition is
inserted. An unsupported row has no cost vector.

A passing circuit is bounded by 16,384 operations; each batch has at most 4096
requests. An ineligible source-unsupported circuit may retain a larger supplied
operation sequence without gate inspection, preserving later complete-report
coverage. The shared hardware work cap is independent of numerical verification
budgets. Empty circuits use zero checks even after another row consumes the cap.

## Duration and error interpretation

The timing pass stores the latest lower and upper finish times for each site.
A gate starts after the maximum finish time of its touched sites, adds its declared
duration endpoints, and updates those sites. This produces the same extrema as
all-predecessor dependency paths under the exclusive-sites, zero-extra-latency
model. Disjoint gates may overlap. Serial time separately sums all durations.
The timing fold is linear in operations/touched sites; canonical used-error records
are ordered by their profile binding indices.

All arithmetic uses integer picoseconds, including totals above floating-point's
exact integer range. Zero duration is explicit. A used missing duration makes
both aggregate times unknown. Stale/unknown calibration takes precedence over
missing duration; unused missing data has no effect. Empty circuits retain
`[0,0]` timing even with stale calibration, excluding preparation/readout/idle costs.
Freshness uses explicit UTC instants and exact timedelta comparisons; no current
clock, floating-point age or numerical simulator is consulted.

Every used binding retains its error metric, missing value and occurrence count
in profile order. No circuit error or success estimate is inferred. These values
are conditional model outputs, not measured device execution or confidence bounds.

## Evidence and next integration boundary

`tests/test_hardware_costs.py` adds 26 tests to the retained 206, for 232 total.
They cover exact dimensions/directed bindings, complete rejection details, work
precedence, identities, timing joins/reorders, missing/stale data, error records,
maximum counts/ticks, whole-batch preflight and visible unexpected exceptions.
A 64-site dimension-32 case guards against state-size/simulator/verifier calls.

Reproduce the independent production audit with an installed package:

```bash
python -I tools/check_hardware_costs.py
```

The audit uses the unchanged design oracle's exhaustive tiny paths and a remaining
budget ledger, separate from the production per-site fold and cumulative charge
counter. It checks:

- 3,110 exhaustive timing circuits, including zero/unknown durations and large ticks.
- 2,752 gate-availability circuits under all 64 declared binding subsets.
- 5,000 three-row budget ledgers plus the five frozen ledgers.
- All 17 frozen target cases, nine timing DAGs and six freshness cases.
- The original 13 operator workloads, retaining actual supplied-source verification
  for the frozen target cases.

The exhaustive abstract cases exercise arithmetic through private inputs; they do
not create public verification evidence. All device numbers are synthetic and the
original fixture digest is retained. CI and both clean wheel/source installations
run this audit, alongside all original audits and the separate Cirq baseline.

The v0.5.0 producer validates fresh computed SearchReport evidence, complete
candidate/placement membership, source/physical/placement fingerprints and
collisions before calling this kernel. It preserves source coverage/budgets,
derives selected-objective interval fronts, and replays recorded reports without
numerical calls. See the [contract](contracts/hardware-profile-v1.md).
