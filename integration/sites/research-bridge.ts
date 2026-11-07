import { compatibleError, compatibleResponse, isCommit, RESEARCH_LIMITS, type ResearchOperation } from './research-contract.ts';

export type ResearchEnvironment = { Q3_PYTHON_API_ORIGIN?: string; Q3_PYTHON_API_TOKEN?: string; Q3_PYTHON_DEPLOY_COMMIT?: string };
export const RESEARCH_TIMEOUT_MS = 20_000;
const headers = { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer' };
const response = (status: number, code: string, message: string, retryAfter?: number) => Response.json({
  schema: 'q3hash.site-bridge', schema_version: 1, kind: 'error',
  status: status >= 500 ? 'unavailable' : [401, 429].includes(status) ? 'error' : 'invalid',
  code, message,
}, { status, headers: { ...headers, ...(retryAfter ? { 'Retry-After': String(retryAfter) } : {}) } });

function configuration(env: ResearchEnvironment) {
  try {
    const url = new URL(env.Q3_PYTHON_API_ORIGIN ?? '');
    const host = url.hostname;
    const token = env.Q3_PYTHON_API_TOKEN;
    const deploymentCommit = env.Q3_PYTHON_DEPLOY_COMMIT;
    if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || url.pathname !== '/' || url.port ||
      !/^[a-z0-9][a-z0-9.-]*\.[a-z]{2,}$/.test(host) || /\.(localhost|local|internal|test|invalid)$/.test(host) ||
      !token || !/^[A-Za-z0-9._~-]{32,256}$/.test(token) || !isCommit(deploymentCommit)) return null;
    return { origin: url.origin, token, deploymentCommit };
  } catch { return null; }
}

async function boundedBytes(body: ReadableStream<Uint8Array> | null, limit: number, signal: AbortSignal) {
  signal.throwIfAborted();
  if (!body) return new Uint8Array();
  const reader = body.getReader();
  const cancel = () => { void reader.cancel().catch(() => {}); };
  const bytes = new Uint8Array(limit);
  let total = 0;
  signal.addEventListener('abort', cancel, { once: true });
  try {
    while (true) {
      const { done, value } = await reader.read();
      signal.throwIfAborted();
      if (done) return bytes.subarray(0, total);
      if (total + value.byteLength > limit) {
        cancel();
        throw new RangeError('Body limit');
      }
      bytes.set(value, total);
      total += value.byteLength;
    }
  } finally {
    signal.removeEventListener('abort', cancel);
    reader.releaseLock();
  }
}

const jsonType = (value: string | null) => value?.split(';', 1)[0].trim().toLowerCase() === 'application/json';
const decode = (bytes: Uint8Array): unknown => JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));

function decodeUpstream(bytes: Uint8Array): unknown {
  const source = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  const result: unknown = JSON.parse(source);
  // JSON.parse otherwise silently keeps the last duplicate, even for identity fields.
  const tokens = /"(?:[^"\\]|\\[\s\S])*"|[{}[\]]/g;
  const colon = /\s*:/y;
  const stack: (Set<string> | null)[] = [];
  for (const match of source.matchAll(tokens)) {
    const token = match[0];
    if (token === '{') stack.push(new Set());
    else if (token === '[') stack.push(null);
    else if (token === '}' || token === ']') stack.pop();
    else {
      const keys = stack.at(-1);
      colon.lastIndex = match.index + token.length;
      if (keys && colon.test(source)) {
        const key: string = JSON.parse(token);
        if (keys.has(key)) throw new SyntaxError('Duplicate response key');
        keys.add(key);
      }
    }
  }
  return result;
}

const timedOut = (error: unknown) => error instanceof Error && ['TimeoutError', 'AbortError'].includes(error.name);
const unverified = () => response(502, 'ENGINE_CONTRACT', 'Backend identity or numerical response could not be verified.');

function requestFields(value: unknown, operation: ResearchOperation) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const fields = operation === 'simulate' ? ['source'] : operation === 'verify' ? ['logical_source', 'physical_source', 'encoding'] : [];
  const input = value as Record<string, unknown>;
  if (Object.keys(input).length !== fields.length || !fields.every(field => Object.hasOwn(input, field))) return false;
  return fields.every(field => {
    const item = input[field];
    if (field === 'encoding') return !!item && typeof item === 'object' && !Array.isArray(item);
    if (typeof item !== 'string') return false;
    const length = Array.from(item).length;
    return length >= 1 && length <= RESEARCH_LIMITS.characters;
  });
}

function upstreamError(status: number) {
  if (status === 429) return response(429, 'ENGINE_RATE_LIMIT', 'The Python research worker is rate limited. Try again shortly.', 1);
  if (status === 504) return response(504, 'ENGINE_TIMEOUT', 'The Python research operation timed out.');
  if (status === 401 || status === 403) return response(502, 'ENGINE_AUTH', 'The Python service rejected the relay credentials.');
  if (status >= 500) return response(status === 503 ? 503 : 502, 'ENGINE_UNAVAILABLE', 'The Python research worker is unavailable.');
  return response(status, 'ENGINE_REJECTED', 'The Python engine rejected the input or request limits.');
}

export async function researchBridge(
  request: Request, operation: string, env: ResearchEnvironment, authenticated: boolean,
  acquireBudget: () => Promise<boolean>, transport: typeof fetch = fetch,
): Promise<Response> {
  if (!['capabilities', 'simulate', 'verify', 'compare'].includes(operation)) return response(404, 'NOT_FOUND', 'Unknown research operation.');
  const op = operation as ResearchOperation;
  if (request.method !== (op === 'capabilities' ? 'GET' : 'POST')) return response(405, 'METHOD', 'This method is not supported.');
  if (!authenticated) return response(401, 'SIGN_IN_REQUIRED', 'Sign in with ChatGPT to access the hosted Python engine.');
  // The non-safelisted header prevents cross-origin navigation or subresource
  // loads from spending either quota, including on the authenticated GET.
  const origin = request.headers.get('origin');
  const fetchSite = request.headers.get('sec-fetch-site');
  if (request.headers.get('x-q3-research') !== '1' || (fetchSite !== null && fetchSite !== 'same-origin') ||
    ((origin !== null || op !== 'capabilities') && origin !== new URL(request.url).origin)) {
    return response(403, 'ORIGIN', 'Use the research console from this Site.');
  }
  const config = configuration(env);
  if (!config) return response(503, 'BACKEND_NOT_CONNECTED', 'The authenticated Python backend is not configured.');
  let raw: Uint8Array | undefined;
  if (op !== 'capabilities') {
    const encoding = request.headers.get('content-encoding');
    if (!jsonType(request.headers.get('content-type')) || (encoding !== null && encoding !== 'identity')) {
      return response(415, 'CONTENT_TYPE', 'Send uncompressed application/json.');
    }
    const length = request.headers.get('content-length');
    if (length !== null && !/^[0-9]{1,10}$/.test(length)) return response(400, 'INPUT_LENGTH', 'Invalid Content-Length.');
    if (length !== null && Number(length) > RESEARCH_LIMITS.bytes) return response(413, 'REQUEST_LIMIT', 'Request exceeds 16,384 bytes.');
    try {
      raw = await boundedBytes(request.body, RESEARCH_LIMITS.bytes, AbortSignal.any([request.signal, AbortSignal.timeout(5000)]));
    } catch (error) {
      if (timedOut(error)) return response(408, 'REQUEST_TIMEOUT', 'The request body timed out.');
      if (error instanceof RangeError) return response(413, 'REQUEST_LIMIT', 'Request exceeds 16,384 bytes.');
      return response(400, 'INPUT_BODY', 'The request body could not be read.');
    }
    // Forward the original bytes so Python can reject duplicate JSON keys.
    try {
      if (!requestFields(decode(raw), op)) throw new Error('Invalid input');
    } catch { return response(422, 'INPUT', 'Check the JSON fields and the 4,096-character source limit.'); }
  }
  try {
    if (!await acquireBudget()) return response(429, 'RATE_LIMIT', 'The hosted research allowance has been reached. Try again shortly.', 60);
  } catch {
    return response(503, 'REQUEST_BUDGET_UNAVAILABLE', 'The hosted research request budget is unavailable.');
  }

  const signal = AbortSignal.any([request.signal, AbortSignal.timeout(RESEARCH_TIMEOUT_MS)]);
  let upstream: Response;
  try {
    upstream = await transport(config.origin + '/api/v1/' + op, {
      method: request.method,
      headers: { Authorization: 'Bearer ' + config.token, Accept: 'application/json', ...(raw ? { 'Content-Type': 'application/json' } : {}) },
      body: raw ? new Blob([raw as BlobPart]) : undefined, redirect: 'manual', signal, cache: 'no-store',
    });
  } catch (error) {
    return timedOut(error) ? upstreamError(504) : response(503, 'ENGINE_UNREACHABLE', 'The Python engine could not be reached.');
  }
  if (upstream.status >= 300 && upstream.status < 400) {
    await upstream.body?.cancel().catch(() => {});
    return response(502, 'ENGINE_REDIRECT', 'The Python engine returned an unexpected redirect.');
  }
  if (!jsonType(upstream.headers.get('content-type'))) {
    await upstream.body?.cancel().catch(() => {});
    return upstream.status >= 500 ? upstreamError(upstream.status) : unverified();
  }
  try {
    const value = decodeUpstream(await boundedBytes(upstream.body, RESEARCH_LIMITS.responseBytes, signal));
    if (!upstream.ok) return compatibleError(value, upstream.status, config.deploymentCommit) ? upstreamError(upstream.status) : unverified();
    if (upstream.status !== 200 || !compatibleResponse(value, op, config.deploymentCommit) ||
      JSON.stringify(value).includes(config.token)) return unverified();
    return Response.json(value, { headers });
  } catch (error) {
    return timedOut(error) ? upstreamError(504) : unverified();
  }
}
