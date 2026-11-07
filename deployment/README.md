# Q3HASH hosted integration RC

The Render adapter serves [hosted API v2](../docs/contracts/hosted-api-v2.md) behind the provider's HTTPS ingress. The existing localhost console retains its independent API and local run path.

## Local checks

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip==26.3 setuptools==84.2.1 wheel==0.48.0
python -m pip install --no-build-isolation --no-deps .
python -m pip install jsonschema==4.26.0
python -I -m unittest discover -s tests -v
python -I tools/check_hosted_api.py --commit "$(git rev-parse HEAD)" --validate-schema --output /tmp/q3hash-api.json
cd integration/sites
npm ci
npm run typecheck
npm run build
Q3_CONTRACT_FIXTURES=/tmp/q3hash-api.json npm test
```

The fixture command starts an authenticated ephemeral loopback server and runs the actual Python subprocess. The test bearer is random and only held in memory. The resulting fixture includes pass, fail, unsupported, invalid, denied and partial responses. The separate [three-way oracle](../tools/check_three_way_oracle.py) builds full matrices and timing independently of the core.

## Managed staging configuration

Use a distinct reviewed Render service so the current Site and its existing v1 backend can continue operating during acceptance. Initial service creation or Blueprint sync can deploy immediately. Stage only after the release review and explicit authorisation.

| Setting | Value |
| --- | --- |
| Runtime | Python 3.12.16 on Render in Singapore |
| Source | Exact reviewed commit on the development branch |
| Build | Build-tool versions in [render.yaml](../render.yaml) |
| Start | `python -I deployment/render_api.py` |
| Health | `GET /healthz` |
| Automatic deploys and PR previews | Off |
| Port and TLS | Render `PORT`, provider TLS at the HTTPS edge |
| Render credential | `Q3HASH_API_KEY` with 32–256 URL-safe ASCII characters, set through secret management |
| Site server settings | `Q3_PYTHON_API_ORIGIN`, secret `Q3_PYTHON_API_TOKEN` matching the service credential, `Q3_PYTHON_DEPLOY_COMMIT` matching the reviewed deploy |

Optional bounds use `Q3HASH_MAX_REQUEST_BYTES` (1024–16,384, default 16,384), `Q3HASH_WORKER_OUTPUT_BYTES` (4096–262,144, default 262,144), `Q3HASH_WORKER_TIMEOUT_SECONDS` (greater than 0 to 15, default 12), `Q3HASH_WORKER_CPU_SECONDS` (1–8, default 8), `Q3HASH_WORKER_MEMORY_MIB` (64–384, default 384) and `Q3HASH_RATE_INTERVAL_SECONDS` (0.25–60, default 0.25). Render provides `RENDER_GIT_COMMIT`. A deliberate local start instead requires `Q3HASH_DEPLOYMENT_COMMIT` set to the locally checked commit.

The service holds at most eight handler connections and one compute slot. The five-second read deadline starts when a handler accepts the connection. The worker runs isolated with a reduced environment and limits on CPU time, virtual memory, file output and wall time. The Android Termux compatibility path relies on CPU, output and wall-time bounds because virtual address limits on that runtime differ. Use managed Linux for staging. The rate interval is per instance. The Site uses its existing D1 table to apply 12 requests per minute per visitor and 60 per minute across visitors. Review provider ingress quotas and cost controls separately.

## Acceptance and rollback

1. Confirm the actual Render deploy record, source SHA, Python version, TLS and health path. Inject the approved staging bearer into the acceptance process via server-side secret management and run `python -I tools/check_hosted_api.py --commit <full-reviewed-sha> --https-origin <bare-https-origin> --validate-schema`. The script validates the certificate and refuses redirects.
2. Apply the Site patch to the reviewed Sites source and repeat its frozen install, type check, tests and build. Provision the three settings only in the authorised staged Site context. Confirm the trusted dispatch headers cannot be supplied by an anonymous HTTP caller at the live edge. Verify top-level sign-in, logout, session expiry, origin checks and capability/compute quotas.
3. Run real desktop and Android checks on the staged Site. Verify the qutrit, mixed, encoded-subspace and partial benchmark cases, and inspect response bodies and the built client bundle for credential exposure. An approved load test should cover ingress framing, flooding and timeouts on the real provider path.
4. A production cutover must pair the v2 Site source and v2 backend. Keep the working v1 endpoint available during review. Restore the prior Site version and its matching environment revision if verification fails. If the candidate Render service has begun serving the Site, switch the Site settings back to the prior origin and deployment pin together. Roll back Render to its recorded deploy only if the compatible Site version and settings are restored together.
