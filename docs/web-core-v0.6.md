# Q3HASH v0.6: localhost web/core research vertical slice

**Development status:** This document defines a local research demonstration. The
v0.5.0 tag is immutable. The merged native/binary/mixed benchmark is not rewritten.
No claim is made of automatic dimension inference, circuit synthesis, real-device
execution, quantum advantage, or measured hardware performance.

## Start locally (including Termux)

From the Q3HASH repository root, on a branch containing this integration:

```sh
PYTHONPATH="$PWD/src" python tools/web_app.py --port 8765
```

Open **http://127.0.0.1:8765/** in a browser on the **same device**. Press
Ctrl+C in Termux to stop the server. If the port is occupied, use `--port 8766`
and update the browser address accordingly. No Node, npm, paid Codex access,
cloud server or third-party Python runtime package is required. Q3HASH's core
needs only the standard library; external-framework checks remain on CI.

The server binds to `127.0.0.1` only. It cannot be directly accessed from
another device without changing the implementation. **Do not expose it** via a
public reverse proxy, port forwarding, tunnel or Android network interface.
This is not an authenticated multi-user or public-host deployment.

## Versioned JSON API contract

All responses have `schema: "q3hash.web-response"`, `schema_version: 1`,
`kind`, `status` and `engine_version`. The `status` is one of `pass`, `fail`,
`unsupported`, `partial`, `invalid`, or `error`, as appropriate. Unsupported is
not a numerical failure; partial indicates incomplete evidence. Inputs are
strict JSON with exact property names, no duplicate keys, no NaN/Infinity.
All POSTs require `Content-Type: application/json` and a single Content-Length.

| Route | Input object | Result |
| --- | --- | --- |
| `GET /api/v1/capabilities` | none | Hard limits and explicit feature boundaries |
| `POST /api/v1/simulate` | `{"source":"qutrit q\nshift q"}` | Complete basis amplitudes/probabilities from Q3HASH core, up to 64 states |
| `POST /api/v1/verify` | `{"logical_source":"...","physical_source":"...","encoding":{...}}` | Complete-subspace residual, leakage and **full** unitarity using user-supplied encoding |
| `POST /api/v1/compare` | `{}` | Fresh assessment of **checked-in fixed** three-way qutrit-shift fixture |

Example verification encoding:

```json
{"schema":"q3hash.basis-encoding","schema_version":1,"kind":"basis-injection","logical_dimensions":[3],"physical_dimensions":[2,2],"physical_basis_indices":[0,1,2]}
```

HTTP 200 may carry `pass`, `fail`, `unsupported`, or `partial` results. Client
input errors use HTTP 4xx, `kind: error`, `status: invalid`, a stable `Q3-WEB-*`
code, and a human-readable reason. Unexpected server errors use 500 without
traceback data. No web request may supply local file paths or system commands.

### Explicit limits

* Maximum request size: 16,384 bytes; maximum source length: 4,096 characters.
* Maximum 64 operations per individual source program.
* Simulation: maximum 64 basis states in the web response.
* Explicit equivalence verification: maximum physical dimension 32.
* All core constraints, exact dimension assignments, encoding-map injectivity,
  and numerical tolerances remain enforced by the existing Python engine.
* `/api/v1/compare` always uses committed fixture paths and static synthetic
  model inputs; no user-specified workload or placement is accepted.

## Reproducibility and interpretation

The `compare` endpoint directly calls `generate_encodings`, `evaluate_candidates`
and `assess_hardware` against the existing shipped fixture. Three supplied
implementations must pass operator verification; `(3,2)` remains unimplemented.
The browser shows the **partial** Pareto front, provenance and synthetic timing
intervals. The values 40–60k, 390–490k and 5–8k ps are **conditional arithmetic**
from a fictitious profile, never measured execution times or statistical
confidence intervals. The mixed encoding has a spectator qubit; it is not proof
of active mixed-dimensional superiority.

## Security and scope

Only allowlisted static assets and three JSON API routes are served. The Host and
Origin checks, fetch metadata check, strict JSON decoding, body-size cap, CSP,
no-CORS policy and local binding reduce common accidental exposure risks. This
is **not a production security review**. It has no authentication, request
rate-limit policy, concurrency cap, HTTPS, accounts, persistent jobs, data storage
or sandboxed untrusted code runner. No user-provided source executes as Python,
shell, JS or filesystem path; it is parsed as restricted Q3# notation.

## Verification

```sh
PYTHONPATH="$PWD/src" python -m unittest discover -s tests -p 'test_web_app.py' -v
PYTHONPATH="$PWD/src" python -m unittest discover -s tests -v
PYTHONPATH="$PWD/src" python tools/check_three_way_oracle.py
PYTHONPATH="$PWD/src" python tools/check_three_way_benchmark.py
```

The existing GitHub Actions matrix performs clean wheel/sdist installs and tests
on Python 3.10–3.13; this patch adds the new web API tests and separate numerical
job acceptance. It leaves the pinned Cirq external validation unchanged.

**Verify against the exact development commit before merging.** Do not label a
passing local smoke test as an external-device measurement or complete compiler.
