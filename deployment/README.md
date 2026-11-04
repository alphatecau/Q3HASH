# Q3HASH private Render API — preparation only

This package does not replace `tools/web_app.py` or change `src/q3hash`.

## Prerequisites

* Python 3.10+; `python -m pip install -e .` from the repository root.
* `Q3HASH_API_KEY`: randomly generated secret, at least 32 characters.
* The Render web service must terminate HTTPS. This adapter serves HTTP only **behind** Render; never expose the Termux port through a tunnel.

## Check before committing

```sh
python -m unittest discover -s tests -p 'test_web_app.py' -v
python -m unittest discover -s tests -p 'test_render_api.py' -v
python tools/check_three_way_oracle.py
python tools/check_three_way_benchmark.py
git status --short
```

## Local test, optional

```sh
export Q3HASH_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(36))')"
PORT=10000 python deployment/render_api.py
```

From a second Termux session:

```sh
curl --fail -s http://127.0.0.1:10000/healthz
curl -s -H "Authorization: Bearer $Q3HASH_API_KEY" http://127.0.0.1:10000/api/v1/capabilities
```

The secret variable is per Termux session; set it separately if using a second session.

## Security boundary and limitations

- API requires `Authorization: Bearer <secret>` for all research operations.
- Browser-origin requests and CORS preflights are denied; the API key must **never** be embedded in public website JavaScript.
- A trusted server-side proxy or user-authenticated session-based relay is required to integrate the existing Q3HASH Lab site safely.
- Worker uses only Q3HASH engine functions imported from `tools/web_app.py` and runs in a separate Python process with 12-second wall-time and Linux memory/CPU limits.
- Worker concurrency is 1; up to 8 simultaneous connections and a minimal global request interval are enforced. These are resource guards, not a substitute for Render edge protections or a comprehensive third-party audit.
- `render.yaml` disables automatic redeployment but **creating the service still initiates an initial deployment**. Do not create a service before verification and authorization.
- `/healthz` only reports process responsiveness. It is not proof that a specific quantum calculation passes.
- Benchmarks use only committed fixtures; timings are synthetic, `(3,2)` is unimplemented and Pareto results may be partial.
- No changes are made to existing site URLs, old tags, or prior local server.

## Recommended next gates

1. Verify all local tests and positive/negative controls in Termux.
2. Review Git diff, then push the new branch only (not `main`).
3. Review PR and CI checks before any cloud deployment.
4. Create a Render service manually only when ready. Configure the secret in Render Dashboard; never commit it.
5. Verify HTTPS auth, timeout handling, 4xx errors and engine-generated numerical results against known fixtures.
6. Investigate availability of a trusted server-side website proxy; do not expose this bearer token to browser code.
