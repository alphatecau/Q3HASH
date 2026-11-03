'use strict';

const $ = id => document.getElementById(id);
const results = $('results');
const status = $('status');
const heading = $('results-heading');
const buttons = [$('run-simulation'), $('run-verification'), $('run-comparison')];

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = String(text);
  return node;
}
function put(parent, ...children) { for (const child of children) parent.appendChild(child); return parent; }
function clear(parent) { parent.replaceChildren(); }
function fmt(n) { return typeof n === 'number' ? Number(n.toPrecision(8)).toString() : '—'; }
function state(name) {
  status.className = 'status ' + (['pass','partial','fail','unsupported','invalid','error'].includes(name) ? name : 'neutral');
  status.textContent = name;
}
function metric(label, value) {
  return put(el('div','metric'), el('div','label',label), el('div','value',value));
}
function notice(text) { results.appendChild(el('p','warning',text)); }
function grid(items) {
  const section = el('div','metrics');
  for (const [label,value] of items) section.appendChild(metric(label,value));
  results.appendChild(section);
}
function showSimulation(data) {
  grid([['PHYSICAL DIMENSIONS', data.dimensions.join(' × ')],['BASIS STATES', data.state_size],['OPERATIONS',data.operations]]);
  const rows = el('div','rows');
  for (const item of data.basis.filter(x => x.probability > 1e-10)) {
    rows.appendChild(put(el('div','basis-row'), el('span','key','|'+item.index+'⟩'),
      el('span','result-value','P = '+fmt(item.probability)),
      el('span','info','amplitude: '+fmt(item.amplitude[0])+' + '+fmt(item.amplitude[1])+'i')));
  }
  results.appendChild(rows);
}
function showVerification(data) {
  const v = data.verification;
  if (!v) { notice(data.reason || 'No numerical report.'); return; }
  grid([['LOGICAL SIZE',v.logical_size], ['PHYSICAL SIZE',v.physical_size],
    ['SUBSPACE RESIDUAL',fmt(v.subspace_residual)], ['LEAKAGE',fmt(v.leakage_norm)],
    ['LOGICAL UNITARITY',fmt(v.logical_unitarity_error)],
    ['PHYSICAL UNITARITY',fmt(v.physical_unitarity_error)]]);
  results.appendChild(el('p','info',v.reason+' · '+v.evidence));
  if (v.status === 'unsupported') notice('This case exceeds the declared dense verification limit. No equivalence claim is made.');
}
function showComparison(data) {
  notice(data.warning);
  grid([['VERIFICATION CALLS',data.verification_calls],
        ['SOURCE PASS',data.source_status_counts.pass],
        ['UNIMPLEMENTED',data.source_status_counts.unimplemented],
        ['PARETO FRONT',data.front_partial ? 'Partial' : 'Complete']]);
  const rows = el('div','rows');
  for (const item of data.rows) {
    const left = put(el('div'),el('h3','',item.name+'  ('+item.dimensions.join(',')+')'),
      el('p','', 'Verification: '+item.source_status+' · Target: '+item.target_status));
    const time = item.critical_path_ps ? item.critical_path_ps.map(fmt).join('–')+' ps' : 'not assessed';
    const right = put(el('div'),el('div','result-value',time),
      el('div',item.on_front ? 'front' : 'info',item.on_front ? 'CONDITIONAL FRONT' : '—'));
    rows.appendChild(put(el('div','comparison-row'),left,right));
  }
  results.appendChild(rows);
}
async function run(route, payload, title, button) {
  for (const item of buttons) item.disabled = true;
  heading.textContent = title;
  state('neutral'); status.textContent = 'Computing';
  clear(results);
  try {
    const response = await fetch('/api/v1/'+route,{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),cache:'no-store'});
    const data = await response.json();
    state(data.status || 'error');
    if (!response.ok) { results.appendChild(el('p','error-details',data.message || 'Request rejected')); return; }
    if (route === 'simulate') {
      if (data.status === 'unsupported') notice(data.reason);
      else showSimulation(data);
    } else if (route === 'verify') showVerification(data);
    else showComparison(data);
  } catch (error) {
    state('error'); results.appendChild(el('p','error-details','Local engine unavailable: '+error.message));
  } finally { for (const item of buttons) item.disabled = false; }
}

for (const button of document.querySelectorAll('.tab')) button.addEventListener('click', () => {
  for (const item of document.querySelectorAll('.tab')) {
    const active = item === button;
    item.classList.toggle('active',active);
    item.setAttribute('aria-selected',String(active));
    $(item.dataset.panel).classList.toggle('hidden',!active);
  }
});
$('run-simulation').addEventListener('click', () => run('simulate',{source:$('source').value},'Statevector results',$('run-simulation')));
$('run-verification').addEventListener('click', () => {
  let encoding;
  try { encoding = JSON.parse($('encoding').value); }
  catch { state('invalid'); heading.textContent='Invalid encoding JSON'; clear(results);notice('Correct the encoding JSON and retry.');return; }
  run('verify',{logical_source:$('logical').value,physical_source:$('physical').value,encoding},'Encoded-subspace verification',$('run-verification'));
});
$('run-comparison').addEventListener('click', () => run('compare',{},'Same-workload benchmark',$('run-comparison')));
fetch('/api/v1/capabilities',{cache:'no-store'}).then(response => {if (!response.ok) throw new Error('unavailable');return response.json();})
  .then(data=>{$('connection').textContent='Local engine · '+data.engine_version;$('connection').classList.add('ready');})
  .catch(()=>{$('connection').textContent='Local engine · unavailable';});
