import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { compatibleResponse, RESEARCH_COMMIT } from './research-contract.ts';
import { researchBridge } from './research-bridge.ts';

const evidence = JSON.parse(readFileSync(process.env.Q3_CONTRACT_FIXTURES, 'utf8'));
const commit = evidence.capture.deployment_commit;
const token = 'test-only-service-bearer-' + 'x'.repeat(40);
const environment = { Q3_PYTHON_API_ORIGIN: 'https://python.example.com', Q3_PYTHON_API_TOKEN: token, Q3_PYTHON_DEPLOY_COMMIT: commit };
const allow = async () => true;
const body = op => op === 'simulate' ? { source: 'qutrit q' } : op === 'verify'
  ? { logical_source: 'qubit q', physical_source: 'qubit q', encoding: {} } : {};
const req = op => new Request('https://site.example/api/v1/' + op, {
  method: op === 'capabilities' ? 'GET' : 'POST',
  headers: { 'X-Q3-Research': '1', Origin: 'https://site.example', 'Content-Type': 'application/json' },
  ...(op === 'capabilities' ? {} : { body: JSON.stringify(body(op)) }),
});
const unexpected = async () => { assert.fail('Upstream called unexpectedly'); };

for (const { check, operation, http_status: status } of evidence.checks) {
  if (operation === 'health') continue;
  test('Python to Sites: ' + check, async () => {
    const original = evidence.responses[check];
    const response = await researchBridge(req(operation), operation, environment, true, allow, async (url, init) => {
      assert.equal(url, environment.Q3_PYTHON_API_ORIGIN + '/api/v1/' + operation);
      assert.equal(new Headers(init.headers).get('Authorization'), 'Bearer ' + token);
      assert.equal(new Headers(init.headers).get('Origin'), null);
      assert.equal(init.redirect, 'manual');
      return Response.json(original, { status });
    });
    assert.equal(response.headers.get('Cache-Control'), 'no-store');
    const raw = await response.text();
    assert.ok(!raw.includes(token));
    const decoded = JSON.parse(raw);
    if (status === 200) {
      assert.equal(response.status, 200);
      assert.equal(original.source_commit, RESEARCH_COMMIT);
      assert.deepEqual(decoded, original);
    } else {
      assert.equal(response.status, status === 401 || status === 403 ? 502 : status);
      assert.equal(decoded.kind, 'error');
      assert.ok(!('basis' in decoded) && !('verification' in decoded));
    }
  });
}

test('anonymous capability and compute requests cannot spend either budget', async () => {
  for (const operation of ['capabilities', 'simulate', 'verify', 'compare']) {
    const response = await researchBridge(req(operation), operation, environment, false, unexpected, unexpected);
    assert.equal(response.status, 401);
  }
});

test('backend unavailable yields a transport error without numerical output', async () => {
  const response = await researchBridge(req('simulate'), 'simulate', environment, true, allow, async () => {
    throw new Error('unreachable');
  });
  assert.equal(response.status, 503);
  assert.equal((await response.json()).code, 'ENGINE_UNREACHABLE');
});

for (const [label, value] of [
  ['invalid-schema', { ...evidence.responses.capabilities, schema_version: 1 }],
  ['wrong-source-identity', { ...evidence.responses.capabilities, source_commit: '0'.repeat(40) }],
  ['wrong-deployment-identity', { ...evidence.responses.capabilities, deployment_commit: '0'.repeat(40) }],
  ['conflicting-bridge-identity', { ...evidence.responses.capabilities, site_bridge: { deployment_commit: commit } }],
  ['malformed-response', ['pass']],
]) {
  test(label, async () => {
    const response = await researchBridge(req('capabilities'), 'capabilities', environment, true, allow,
      async () => Response.json(value));
    assert.equal(response.status, 502);
    assert.equal((await response.json()).code, 'ENGINE_CONTRACT');
  });
}

test('false partial front, unsupported evidence and altered probabilities fail closed', () => {
  const comparison = structuredClone(evidence.responses.compare);
  comparison.rows[1].on_front = true;
  assert.equal(compatibleResponse(comparison, 'compare', commit), false);
  const unsupported = structuredClone(evidence.responses.unsupported_large);
  unsupported.state_size = '72';
  assert.equal(compatibleResponse(unsupported, 'simulate', commit), false);
  const simulation = structuredClone(evidence.responses.mixed);
  simulation.basis[0].probability = 0;
  assert.equal(compatibleResponse(simulation, 'simulate', commit), false);
});

test('verification labels must agree with evidence and supported dimensions', () => {
  const passed = structuredClone(evidence.responses.active_mixed_reordered);
  passed.verification.leakage_norm = 1;
  assert.equal(compatibleResponse(passed, 'verify', commit), false);

  const failed = structuredClone(evidence.responses.active_mixed_reordered);
  failed.status = failed.verification.status = 'fail';
  assert.equal(compatibleResponse(failed, 'verify', commit), false);

  const unsupported = structuredClone(evidence.responses.verification_above_limit);
  unsupported.verification.physical_size = '32';
  assert.equal(compatibleResponse(unsupported, 'verify', commit), false);

  const partial = structuredClone(evidence.responses.compare);
  partial.rows = partial.rows.filter(row => row.source_status !== 'unimplemented');
  assert.equal(compatibleResponse(partial, 'compare', commit), false);
});
