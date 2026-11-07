// Shared hosted wire validator. All scientific fields originate in Python.
export const RESEARCH_COMMIT = '19e44ada3a5a31deec7875c403b2efc0ee4c8488';
export const ENGINE_VERSION = '0.5.0';
export const WEB_VERSION = '0.6.0-rc.1';
export const RESEARCH_SCHEMA = 'q3hash.web-response';
export const SCHEMA_VERSION = 2;
export const BASIS_ORDER = 'last-register-fastest';
export const RESEARCH_LIMITS = { bytes: 16384, characters: 4096, operations: 64, states: 64, dimension: 32, responseBytes: 262144 } as const;
const TOLERANCE = 1e-10;
const ENDPOINTS = ['simulate', 'verify', 'compare'] as const;

export type ResearchOperation = 'capabilities' | typeof ENDPOINTS[number];
type RecordValue = Record<string, unknown>;
type Identity = {
  schema: typeof RESEARCH_SCHEMA;
  schema_version: typeof SCHEMA_VERSION;
  engine_version: typeof ENGINE_VERSION;
  web_version: typeof WEB_VERSION;
  source_commit: typeof RESEARCH_COMMIT;
  deployment_commit: string;
};
type Complex = [number, number];
type BasisRow = { index: number; amplitude: Complex; probability: number };
type Verification = {
  status: 'pass' | 'fail' | 'unsupported';
  reason: string;
  evidence: 'q3hash-circuit';
  logical_size: number;
  physical_size: number | string;
  tolerance: number;
  global_phase: Complex | null;
  subspace_residual: number | null;
  leakage_norm: number | null;
  logical_unitarity_error: number | null;
  physical_unitarity_error: number | null;
};
type Resources = {
  physical_registers: number;
  max_register_dimension: number;
  unused_basis_states: number;
  gate_count: number;
  two_register_gate_count: number;
  dependency_depth: number;
};
type BenchmarkRow = {
  name: string;
  dimensions: number[];
  source_status: 'pass' | 'unimplemented';
  source_reason: string;
  verification: Verification | null;
  resources: Resources | null;
  target_status: 'supported' | 'ineligible';
  target_reason: string;
  active_sites: number | null;
  operations: number | null;
  two_site_operations: number | null;
  critical_path_ps: [number, number] | null;
  on_front: boolean;
};
export type Capabilities = Identity & {
  kind: 'capabilities';
  status: 'pass';
  max_request_bytes: number;
};
type Simulation = Identity & { kind: 'simulation'; dimensions: number[]; basis_order: typeof BASIS_ORDER } & (
  { status: 'pass'; state_size: number; operations: number; basis: BasisRow[] } |
  { status: 'unsupported'; state_size: string; reason: string }
);
type VerificationResult = Identity & { kind: 'verification'; status: Verification['status']; verification: Verification };
type Comparison = Identity & {
  kind: 'comparison'; status: 'partial'; warning: string; workload: string;
  rows: BenchmarkRow[]; verification_calls: number;
};
export type ResearchResult = Simulation | VerificationResult | Comparison;
export type ResearchResponse = Capabilities | ResearchResult;
export type EngineError = Identity & { kind: 'error'; status: 'invalid' | 'error'; code: string; message: string };

const identityFields = ['schema', 'schema_version', 'engine_version', 'web_version', 'source_commit', 'deployment_commit', 'kind', 'status'];
const record = (v: unknown): v is RecordValue => !!v && typeof v === 'object' && !Array.isArray(v);
const fields = (v: RecordValue, names: readonly string[]) =>
  Object.keys(v).length === names.length && names.every(name => Object.hasOwn(v, name));
const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const integer = (v: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): v is number =>
  typeof v === 'number' && Number.isSafeInteger(v) && v >= min && v <= max;
const text = (v: unknown): v is string => typeof v === 'string' && v.length > 0 && v.length <= 384;
const pair = (v: unknown): v is Complex => Array.isArray(v) && v.length === 2 && v.every(finite);
const dimensions = (v: unknown): v is number[] =>
  Array.isArray(v) && v.length > 0 && v.length <= RESEARCH_LIMITS.characters && v.every(d => integer(d, 2, 32));
const product = (dims: number[]) => dims.reduce((size, dim) => size * BigInt(dim), BigInt(1));
const exactSize = (v: unknown): v is string => typeof v === 'string' && /^[1-9][0-9]{0,1023}$/.test(v);
const tuple = (v: unknown, expected: readonly string[]) =>
  Array.isArray(v) && v.length === expected.length && expected.every((item, i) => v[i] === item);
export const isCommit = (v: unknown): v is string => typeof v === 'string' && /^[0-9a-f]{40}$/.test(v);

function identity(v: unknown, expectedDeployment?: string): v is RecordValue {
  return record(v) && v.schema === RESEARCH_SCHEMA && v.schema_version === SCHEMA_VERSION &&
    v.source_commit === RESEARCH_COMMIT && v.engine_version === ENGINE_VERSION &&
    v.web_version === WEB_VERSION && isCommit(v.deployment_commit) &&
    (expectedDeployment === undefined || v.deployment_commit === expectedDeployment);
}

function verification(v: unknown, status: unknown): v is Verification {
  const metricFields = ['subspace_residual', 'leakage_norm', 'logical_unitarity_error', 'physical_unitarity_error'];
  if (!record(v) || !fields(v, ['status', 'reason', 'evidence', 'logical_size', 'physical_size', 'tolerance', 'global_phase', ...metricFields]) ||
    v.status !== status || !text(v.reason) || v.evidence !== 'q3hash-circuit' ||
    !integer(v.logical_size, 2, 65536) || v.tolerance !== TOLERANCE) return false;
  if (status === 'unsupported') {
    return exactSize(v.physical_size) && BigInt(v.physical_size) > BigInt(RESEARCH_LIMITS.dimension) &&
      BigInt(v.physical_size) >= BigInt(v.logical_size) && v.global_phase === null && metricFields.every(key => v[key] === null);
  }
  if ((status !== 'pass' && status !== 'fail') ||
    !integer(v.physical_size, v.logical_size, RESEARCH_LIMITS.dimension) ||
    !pair(v.global_phase) || Math.abs(Math.hypot(...v.global_phase) - 1) > 1e-8) return false;
  const metrics = metricFields.map(key => v[key]);
  return metrics.every(finite) && metrics.every(m => m >= 0) && metrics.every(m => m <= TOLERANCE) === (status === 'pass');
}

function simulation(v: RecordValue): boolean {
  const common = [...identityFields, 'dimensions', 'basis_order', 'state_size'];
  if (!dimensions(v.dimensions) || v.basis_order !== BASIS_ORDER) return false;
  const size = product(v.dimensions);
  if (v.status === 'unsupported') {
    return fields(v, [...common, 'reason']) && text(v.reason) &&
      exactSize(v.state_size) && BigInt(v.state_size) === size && size > BigInt(RESEARCH_LIMITS.states);
  }
  if (v.status !== 'pass' || !fields(v, [...common, 'operations', 'basis']) ||
    !integer(v.state_size, 2, RESEARCH_LIMITS.states) || BigInt(v.state_size) !== size ||
    !integer(v.operations, 0, RESEARCH_LIMITS.operations) || !Array.isArray(v.basis) || v.basis.length !== v.state_size) return false;
  let total = 0;
  for (let i = 0; i < v.basis.length; i++) {
    const row: unknown = v.basis[i];
    if (!record(row) || !fields(row, ['index', 'amplitude', 'probability']) || row.index !== i ||
      !pair(row.amplitude) || !finite(row.probability) || row.probability < 0 || row.probability > 1 + 1e-8 ||
      Math.abs(row.amplitude[0] ** 2 + row.amplitude[1] ** 2 - row.probability) > 1e-8) return false;
    total += row.probability;
  }
  return Math.abs(total - 1) < 1e-8;
}

const candidateNames = new Map([['3', 'native'], ['2,2', 'binary'], ['2,3', 'mixed'], ['3,2', 'unimplemented']]);
const objectives = ['active_sites', 'native_operations', 'two_site_operations', 'critical_path_ps'];
const resourceFields = ['physical_registers', 'max_register_dimension', 'unused_basis_states',
  'gate_count', 'two_register_gate_count', 'dependency_depth'];

type EvaluatedRow = BenchmarkRow & {
  active_sites: number; operations: number; two_site_operations: number; critical_path_ps: [number, number];
};
function rowEvidence(row: RecordValue, dims: number[]): row is RecordValue & EvaluatedRow {
  const size = Number(product(dims));
  const resources = row.resources;
  return row.source_status === 'pass' && row.source_reason === 'verified' &&
    row.target_status === 'supported' && row.target_reason === 'native-model-supported' &&
    verification(row.verification, 'pass') && row.verification.logical_size === 3 && row.verification.physical_size === size &&
    row.active_sites === dims.length && integer(row.operations, 1, RESEARCH_LIMITS.operations) &&
    integer(row.two_site_operations, 0, row.operations) && typeof row.on_front === 'boolean' &&
    pair(row.critical_path_ps) && integer(row.critical_path_ps[0]) && integer(row.critical_path_ps[1], row.critical_path_ps[0]) &&
    record(resources) && fields(resources, resourceFields) && resources.physical_registers === dims.length &&
    resources.max_register_dimension === Math.max(...dims) && resources.unused_basis_states === size - 3 &&
    resources.gate_count === row.operations && resources.two_register_gate_count === row.two_site_operations &&
    integer(resources.dependency_depth, 1, row.operations);
}

function dominates(left: EvaluatedRow, right: EvaluatedRow): boolean {
  const upper = [left.active_sites, left.operations, left.two_site_operations, left.critical_path_ps[1]];
  const lower = [right.active_sites, right.operations, right.two_site_operations, right.critical_path_ps[0]];
  return upper.every((a, i) => a <= lower[i]) && upper.some((a, i) => a < lower[i]);
}

function counts(v: unknown, expected: Record<string, number>) {
  return record(v) && fields(v, Object.keys(expected)) && Object.entries(expected).every(([key, count]) => v[key] === count);
}

function comparison(v: RecordValue): boolean {
  if (!fields(v, [...identityFields, 'synthetic', 'measured_hardware', 'hardware_provenance', 'front_partial',
    'search_complete', 'warning', 'workload', 'ranking_scope', 'verification_calls', 'source_status_counts',
    'hardware_status_counts', 'objective_names', 'rows']) ||
    v.status !== 'partial' || v.synthetic !== true || v.measured_hardware !== false || v.hardware_provenance !== 'synthetic' ||
    v.front_partial !== true || v.search_complete !== true || !text(v.warning) || !v.warning.startsWith('Synthetic') ||
    v.workload !== 'v0.6-three-way-logical-qutrit-shift' || v.ranking_scope !== 'verified-supplied-placements-under-one-profile' ||
    v.verification_calls !== 3 || !tuple(v.objective_names, objectives) || !Array.isArray(v.rows) || v.rows.length !== 4 ||
    !counts(v.source_status_counts, { unimplemented: 1, pass: 3, fail: 0, unsupported: 0, 'not-evaluated': 0 }) ||
    !counts(v.hardware_status_counts, { ineligible: 1, supported: 3, unsupported: 0, unplaced: 0, 'not-evaluated': 0 })) return false;
  const seen = new Set<string>();
  const evaluated: EvaluatedRow[] = [];
  for (const raw of v.rows) {
    const row: unknown = raw;
    const nullable = ['verification', 'resources', 'active_sites', 'operations', 'two_site_operations', 'critical_path_ps'];
    if (!record(row) || !fields(row, ['name', 'dimensions', 'source_status', 'source_reason', 'target_status', 'target_reason', 'on_front', ...nullable]) ||
      !dimensions(row.dimensions)) return false;
    const key = row.dimensions.join(',');
    if (seen.has(key) || !candidateNames.has(key) || candidateNames.get(key) !== row.name) return false;
    seen.add(key);
    if (key === '3,2') {
      if (row.source_status !== 'unimplemented' || row.source_reason !== 'no-implementation' || row.target_status !== 'ineligible' ||
        row.target_reason !== 'source-unimplemented' || row.on_front !== false || !nullable.every(name => row[name] === null)) return false;
    } else {
      if (!rowEvidence(row, row.dimensions)) return false;
      evaluated.push(row);
    }
  }
  return evaluated.every(row => row.on_front === !evaluated.some(other => other !== row && dominates(other, row)));
}

export function compatibleResponse(value: unknown, operation: ResearchOperation, expectedDeployment?: string): value is ResearchResponse {
  if (!identity(value, expectedDeployment)) return false;
  const kinds = { capabilities: 'capabilities', simulate: 'simulation', verify: 'verification', compare: 'comparison' };
  if (value.kind !== kinds[operation]) return false;
  switch (operation) {
    case 'capabilities':
      return value.status === 'pass' && fields(value, [...identityFields, 'endpoints', 'max_request_bytes', 'max_program_characters',
        'max_operations', 'max_simulated_states', 'max_verified_dimension', 'max_register_dimension', 'basis_order', 'local_only',
        'public_browser_access', 'synthetic_hardware_only', 'automatic_synthesis', 'automatic_dimension_inference']) &&
        tuple(value.endpoints, ENDPOINTS) && integer(value.max_request_bytes, 1024, RESEARCH_LIMITS.bytes) &&
        value.max_program_characters === RESEARCH_LIMITS.characters && value.max_operations === RESEARCH_LIMITS.operations &&
        value.max_simulated_states === RESEARCH_LIMITS.states && value.max_verified_dimension === RESEARCH_LIMITS.dimension &&
        value.max_register_dimension === 32 && value.basis_order === BASIS_ORDER &&
        value.local_only === false && value.public_browser_access === false && value.synthetic_hardware_only === true &&
        value.automatic_synthesis === false && value.automatic_dimension_inference === false;
    case 'simulate': return simulation(value);
    case 'verify': return fields(value, [...identityFields, 'verification']) && verification(value.verification, value.status);
    case 'compare': return comparison(value);
  }
}

export function compatibleError(value: unknown, status: number, expectedDeployment: string): value is EngineError {
  const codes: Partial<Record<number, string[]>> = {
    400: ['HEADERS', 'TRANSFER', 'LENGTH', 'HTTP'], 401: ['AUTH'], 403: ['ORIGIN'], 404: ['NOTFOUND'],
    405: ['METHOD', 'HTTP'], 411: ['LENGTH'], 413: ['SIZE'], 414: ['HTTP'], 415: ['TYPE'], 417: ['EXPECT'],
    422: ['INPUT'], 429: ['RATE'], 431: ['HEADERS', 'HTTP'], 500: ['WORKER'], 503: ['BUSY'], 504: ['TIMEOUT'],
  };
  return identity(value, expectedDeployment) && fields(value, [...identityFields, 'code', 'message']) &&
    value.kind === 'error' && value.status === (status < 500 && status !== 401 && status !== 429 ? 'invalid' : 'error') &&
    typeof value.code === 'string' && (codes[status]?.some(code => value.code === 'Q3-HTTPS-' + code) ?? false) && text(value.message);
}
