# Hosted research API v2

- **Integration version** 0.6.0-rc.1
- **Numerical core** 0.5.0
- **Wire contract** `q3hash.web-response`, schema version 2
- **Authoritative shapes** [Hosted API JSON Schema](q3hash-hosted-v2.schema.json)

The hosted adapter executes the same pinned Python functions as the localhost console. The localhost API retains its version 1 response. The public Site and the Render service use separate credentials and enforce separate trust boundaries.

| Method and route | Exact JSON request fields | Successful HTTP 200 evidence |
| --- | --- | --- |
| `GET /healthz` | No body. Public process readiness after startup verification. | `{"status":"ok"}` |
| `GET /api/v1/capabilities` | No body. Service bearer required. | `capabilities / pass`, provenance and effective limits |
| `POST /api/v1/simulate` | `source` | `simulation / pass` or `unsupported` |
| `POST /api/v1/verify` | `logical_source`, `physical_source`, `encoding` | `verification / pass`, `fail` or `unsupported` |
| `POST /api/v1/compare` | Empty object `{}` | `comparison / partial` for the fixed workload |

Every research operation requires exactly one service `Authorization: Bearer …` header. Send POST bodies as uncompressed UTF-8 `application/json` with one Content-Length. Limits are up to 16,384 request bytes, 4,096 Unicode characters per source, 64 operations, 64 simulated states and dense physical dimension 32 for verification. Register dimensions are integers in 2–32. The source grammar admits `shift`, `fourier` and controlled `sum` as defined in the [language specification](../language-spec.md). Other operator representations are outside the hosted request contract.

All research results and application-generated errors carry `engine_version`, `web_version`, `source_commit` and `deployment_commit`. The backend verifies SHA-256 digests of 42 files covering the installed modules, actual web adapter, benchmark inputs and licence before listening. The manifest digests are checked against the pinned Git source in CI. Render provides the deploy commit. The Site checks that the returned commit exactly matches its separately configured review pin and rejects legacy, missing, malformed, duplicated or conflicting fields. This is a deployment check over trusted TLS, a trusted build and the shared service credential. It carries no independent signature or runtime attestation.

## Numerical invariants

- Simulation preserves declaration order with the **last register fastest**. Each basis row uses a zero-based flat index and amplitude `[real, imaginary]`. The squared magnitude agrees with the probability and all probabilities sum to one within the transport validator's numerical tolerance. The unsupported state count is a decimal string to preserve exact large integers.
- Verification accepts only a versioned `q3hash.basis-encoding` basis injection. Mapping length, range, uniqueness and dimensions are checked by the core. Evaluated reports supply a unit global phase, full-subspace residual, leakage and both unitarity errors. The fixed tolerance is `1e-10`. A FAIL reports at least one criterion above tolerance. An unsupported dense dimension has null numerical metrics and a decimal-string physical dimension.
- The comparison checks the same logical qutrit shift on native (3), binary (2,2) and mixed (2,3) circuits. Residual, leakage and unitarity establish equivalence within the fixed tolerance, with zero residual for the committed permutation fixture. The (3,2) candidate is unsupported and has no circuit, metrics or hardware result. Costs are synthetic intervals in picoseconds. The partial front applies to verified supplied placements under one profile, using conservative interval dominance. The fixture includes no device runs or noisy fidelity measurements.

## HTTP errors and Site status

| HTTP | Meaning |
| --- | --- |
| 400, 411, 413, 414, 415, 417, 422, 431 | Request framing, header, size, media type, JSON, source or encoding validation failure |
| 401 | Missing or incorrect Render service bearer. The Site independently sends 401 for missing visitor session. |
| 403 | Browser-origin request denied at Render or cross-origin request denied at the Site relay |
| 404, 405 | Unknown operation or unsupported method |
| 429 | Authenticated request quota exceeded |
| 500, 503, 504 | Worker failure, worker busy or timeout |

Errors use `kind: error`, a bounded safe message and a stable code. The Site maps validated service errors to its own safe envelope. The Site uses UNVERIFIED for incompatible results and BACKEND UNAVAILABLE for failures reaching or running the service. Neither an HTTP 200 nor a capability check establishes that a particular quantum operation passed.
