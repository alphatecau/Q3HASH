# Hardware CLI v1 contract

**Status:** Implemented in v0.5.0 after finalising this command contract.
The command is an adapter to the existing computed-source/report APIs.

## Command and inputs

`q3hash-hardware` and `python -m q3hash.hardware_cli` take:

| Input | Contract |
| --- | --- |
| `LOGICAL_Q3` | Required explicit-dimension logical source file. |
| `--profile FILE` | Required strict HardwareProfile JSON v1. URI metadata is never fetched. |
| `--context FILE` | Required HardwareContext JSON v1, including explicit as-of/age, objectives and work cap. No current-clock defaults. |
| `--constraints FILE` | Optional strict SearchConstraints JSON; otherwise documented defaults. |
| `--seed ENCODING_JSON` | Repeat in seed order; never inferred from an implementation or placement. |
| `--implementation ENCODING_JSON PHYSICAL_Q3` | Repeat explicit circuit bindings. |
| `--placement ENCODING_JSON SITE_INDICES_JSON` | Repeat placements. The second operand is a literal JSON array, such as `'[0]'` or `'[1,2]'`, mapping physical register order to sites. |
| `--tolerance NUMBER` | Positive finite source-verification tolerance, default 1e-10. |
| `--max-dimension N` | Dense source-verifier limit 1–64, default 64. |
| `--json` | Only HardwareReport.to_json(), without a trailing newline. |
| `--help` / `--version` | Standard command help / installed package version. |

Files and literal JSON have a 1 MiB UTF-8 transport limit. At most 4096 seeds,
implementations and placements are accepted per category. Exact integers exclude
bool/float site indices. All files, options, bindings, placements and available
identity inputs are validated before any numerical call. A placement must refer
to a retained encoding with a supplied circuit; duplicates are invalid.
Source/physical/profile/context/placement fingerprints must be representable.

Valid site-dimension or native-gate incompatibility is an assessment outcome.
It is not malformed input. No placement, routing, decomposition, device lookup,
dimension inference or circuit synthesis is added implicitly. The command writes
no files and does not accept recorded reports as fresh numerical evidence.

## Execution and output

Generate the declared bounded domain, run fresh source verification with the
existing API, then call assess_hardware with its computed SearchReport.
Do not parse another CLI's serialized source report and relabel it computed.
Source call/work budgets remain independent of hardware gate-check work.

Buffer a complete, wire-valid HardwareReport before writing stdout in either
output mode. Errors never leave partial JSON or a partial human report. Expected
input/representation errors go to stderr; unexpected runtime defects remain visible.

Human output includes source/hardware statuses, coverage/partial-front reason,
profile identity/provenance/freshness and explicit instants, objectives/scopes,
both work ledgers, numerical metrics, placement IDs and conditional cost ranges
or unknown reasons. Synthetic/stale/unknown data and absent noise composition stay
explicit. It does not describe model ranges as measured times or confidence bounds.

## Exit precedence

| Exit | Meaning |
| --- | --- |
| 2 | Invalid arguments/files/data, transport or representation failure; no stdout report. |
| 1 | At least one actual upstream numerical failure; takes precedence over partial coverage. Valid report emitted. |
| 3 | Valid partial/inconclusive result: missing/unverified/unplaced/skipped rows, unknown selected objectives, truncated or empty domain. Valid report emitted. |
| 4 | Complete assessment, empty front, all placed verified circuits rejected by the declared target. Valid report emitted. |
| 0 | Nonempty complete conditional front with no numerical failure. Known rejected alternatives may coexist with supported placements. |

Check invalid input/output first, then numerical failure, partial coverage,
complete target infeasibility, and nonempty complete front. No exit code establishes
hardware execution, global optimality, measured fidelity or encoding superiority.

Fixed process-level vectors, direct CLI tests, both installed entry points and
existing API/numerical/independent audits gate the stable 0.5.0 source release.
