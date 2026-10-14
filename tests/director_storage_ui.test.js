const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function classes() {
  const values = new Set();
  return { add: (...xs) => xs.forEach(x => values.add(x)), remove: (...xs) => xs.forEach(x => values.delete(x)),
    contains: x => values.has(x), toggle(x, on) { on ??= !values.has(x); on ? values.add(x) : values.delete(x); } };
}
function node(id) {
  return { id, value: '', innerHTML: '', textContent: '', disabled: false, dataset: {}, classList: classes(),
    querySelectorAll: () => [], addEventListener() {}, closest() { return this; } };
}
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return {promise, resolve, reject}; }
function harness() {
  const nodes = new Map();
  const calls = [];
  const responses = {};
  const context = vm.createContext({
    console, LANGS: {ru: {}, en: {}, ua: {}}, lang: 'ru',
    $: id => { if (!nodes.has(id)) nodes.set(id, node(id)); return nodes.get(id); },
    esc: x => String(x ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
    jopts: (method, body) => ({method, body: JSON.stringify(body)}),
    api: async (url, options) => {
      calls.push({url, options});
      const key = `${(options?.method || 'GET').toUpperCase()} ${url.split('?')[0]}`;
      if (responses[key]) return structuredClone(responses[key]);
      if (key.startsWith('GET /api/director/alpha/sessions') && !key.includes('/storage')) return {sessions: []};
      if (key.endsWith('/storage')) return {session_missing: true};
      return {};
    },
    apiErrorInfo: payload => ({message: payload?.error?.code || 'internal_error'}),
    document: {querySelectorAll: () => []}, toast() {}, clearDirty() {}, bindDirtyWatch() {},
  });
  vm.runInContext("function t(key) { return LANGS[lang][key] || key; }", context);
  vm.runInContext(fs.readFileSync('static/app/20_director.js', 'utf8'), context);
  vm.runInContext(fs.readFileSync('static/app/25_director_storage.js', 'utf8'), context);
  const run = script => vm.runInContext(script, context);
  run("_directorChannel = 'alpha'; _directorState = {session: {id: 's1', state: 'paused', pause_reason: 'ai_errors'}, health: {ai: true, vision: false, speech: true, twitch: true}};");
  return {context, nodes, calls, run, responses};
}
const sessionsFixture = {sessions: [
  {id: 's1', state: 'paused', pause_reason: 'ai_errors', emergency_fence: false},
  {id: 's2', state: 'stopped', pause_reason: null, emergency_fence: false},
]};
const manifestFixture = {ok: true, session_id: 's1', total_size_bytes: 2048, limit_bytes: 1048576,
  pinned_bytes: 512, pinned_limit_bytes: 1048576, artifacts: [
    {id: 9, kind: 'frame', path: 'frames/live.jpg', size_bytes: 1024, pinned: false},
    {id: 10, kind: 'transcript', path: 'transcripts/s1.jsonl', size_bytes: 1024, pinned: true},
  ]};

test('storage panel renders usage, artifacts and distinct pause reasons', async () => {
  const h = harness();
  h.responses['GET /api/director/alpha/sessions'] = sessionsFixture;
  h.responses['GET /api/director/alpha/sessions/s1/storage'] = manifestFixture;
  await h.context.loadDirectorStorage(); // first pass discovers the session id
  await h.context.loadDirectorStorage(); // second pass fetches its manifest
  const html = h.nodes.get('directorStoragePanel').innerHTML;
  assert.match(html, /director\.storage_usage/);
  assert.match(html, /frames\/live\.jpg/);
  assert.match(html, /director\.storage_pinned_badge/);
  // Distinct pause reason, not a generic failure message.
  assert.match(html, /director\.pause_reason_ai_errors/);
  assert.ok(!html.includes('pause_reason_offline'));
  h.run("_directorState.session.pause_reason = 'offline'; renderDirectorStorage();");
  assert.match(h.nodes.get('directorStoragePanel').innerHTML, /director\.pause_reason_offline/);
});

test('export shows streaming download link and blocks double submit', async () => {
  const h = harness();
  h.run("_directorStorage.sessionId = 's1';");
  h.responses['POST /api/director/alpha/sessions/s1/export'] = {ok: true, path: 'director/exports/session-s1-123.zip'};
  const gate = deferred();
  h.context.api = async (url, options) => {
    h.calls.push({url, options});
    if (url.endsWith('/export')) return gate.promise;
    return {sessions: [], session_missing: true};
  };
  const first = h.context.directorStorageExport();
  await h.context.directorStorageExport(); // second click while pending: no extra call
  assert.equal(h.calls.filter(call => call.url.endsWith('/export')).length, 1);
  gate.resolve({ok: true, path: 'director/exports/session-s1-123.zip'});
  await first;
  assert.equal(h.calls.filter(call => call.url.endsWith('/export')).length, 1);
  const html = h.nodes.get('directorStoragePanel').innerHTML;
  assert.match(html, /export\/download\?path=director%2Fexports%2Fsession-s1-123\.zip/);
  assert.match(html, /director\.storage_download_ready/);
});

test('delete requires the exact УДАЛИТЬ phrase and sends confirmation', async () => {
  const h = harness();
  h.run("_directorStorage.sessionId = 's1';");
  h.context.directorStorageConfirmChanged('please'); // не слово-подтверждение ни на одном языке
  await h.context.directorStorageDelete();
  assert.equal(h.calls.filter(call => call.url.endsWith('/evidence')).length, 0);
  h.context.directorStorageConfirmChanged('УДАЛИТЬ');
  h.responses['DELETE /api/director/alpha/sessions/s1/evidence'] = {ok: true, deleted_artifact_count: 3};
  await h.context.directorStorageDelete();
  const call = h.calls.find(call => call.url.endsWith('/evidence'));
  assert.equal(call.options.method, 'DELETE');
  assert.deepEqual(JSON.parse(call.options.body), {confirmation: 'УДАЛИТЬ'});
});

test('pin toggles with the backend contract and refreshes the manifest', async () => {
  const h = harness();
  h.run("_directorStorage.sessionId = 's1';");
  h.responses['POST /api/director/alpha/sessions/s1/assets/9/pin'] = {ok: true, pinned: true};
  h.responses['GET /api/director/alpha/sessions/s1/storage'] = manifestFixture;
  await h.context.directorStoragePin('9', false);
  const call = h.calls.find(call => call.url.includes('/assets/9/pin'));
  assert.deepEqual(JSON.parse(call.options.body), {pinned: true});
});

test('late responses from another channel never render', async () => {
  const h = harness();
  const slow = deferred();
  h.context.api = async (url, options) => {
    h.calls.push({url, options});
    if (url.includes('/alpha/') && !url.includes('/storage')) return slow.promise;
    return {sessions: [], session_missing: true};
  };
  const first = h.context.loadDirectorStorage(); // alpha request hangs
  h.run("_directorChannel = 'beta';");
  await h.context.loadDirectorStorage(); // beta answers immediately
  h.run("_directorChannel = 'alpha';");
  slow.resolve({sessions: [{id: 'stale', state: 'live', pause_reason: null}]});
  await first;
  // The stale alpha response arrived after the channel switched away and back; it must not render.
  assert.ok(!h.nodes.get('directorStoragePanel').innerHTML.includes('stale'));
});

test('after emergency the panel offers the last working prompt for re-activation', async () => {
  const h = harness();
  h.run("_directorState.config = {provider: 'fake', model: 'model-a'}; _directorState.session.state = 'emergency';");
  h.context.promptFixture = {id: 7, version: 3, active: false, retired: false, tested: true,
    replay_metadata: {provider: 'fake', model: 'model-a', passed: true, cases: []}};
  h.run("_directorReview().prompts = [promptFixture]; renderDirectorStorage();");
  const html = h.nodes.get('directorStoragePanel').innerHTML;
  assert.match(html, /director\.last_working_prompt/);
  assert.match(html, /v3/);
  assert.match(html, /director\.prompt_activate/);
  // Off sessions show no hint.
  h.run("_directorState.session.state = 'off'; renderDirectorStorage();");
  assert.ok(!h.nodes.get('directorStoragePanel').innerHTML.includes('last_working_prompt'));
});

test('prompt diff fetch and delete use stable endpoints; active prompts cannot be deleted', async () => {
  const h = harness();
  h.context.promptFixture = {id: 7, version: 1, active: true, retired: false};
  h.run("_directorReview().prompts = [promptFixture]; renderDirectorStorage();");
  let html = h.nodes.get('directorStoragePanel').innerHTML;
  assert.match(html.split('director.prompt_delete')[0].slice(-140), /disabled/); // active → disabled
  h.context.promptFixture.active = false;
  h.run("_directorReview().prompts = [promptFixture]; renderDirectorStorage();");
  html = h.nodes.get('directorStoragePanel').innerHTML;
  assert.ok(!html.split('director.prompt_delete')[0].slice(-140).includes('disabled'));
  h.responses['GET /api/director/alpha/prompts/7/diff'] = {prompt_id: 7, diff: '- old\n+ new'};
  await h.context.directorPromptDiff('7');
  assert.match(h.nodes.get('directorStoragePanel').innerHTML, /\+ new/);
  h.responses['DELETE /api/director/alpha/prompts/7'] = {ok: true};
  await h.context.directorPromptDelete('7');
  assert.ok(h.calls.some(call => call.url.endsWith('/prompts/7') && call.options.method === 'DELETE'));
});

// DEF-06 (R-UI1): слово-подтверждение удаления локализовано (DELETE/ВИДАЛИТИ),
// а на бэкенд всегда уходит канонический sentinel «УДАЛИТЬ».
test('delete confirmation accepts localized words and sends canonical sentinel', async () => {
  const h = harness();
  h.run("_directorChannel = 'alpha'; _directorStorage.sessionId = 'sess1';");
  // кнопка разблокируется на любом из трёх языков ввода
  for (const word of ['УДАЛИТЬ', 'DELETE', 'ВИДАЛИТИ']) {
    h.run(`_directorStorage.confirmText = ${JSON.stringify(word)}; renderDirectorStorage();`);
    const html = h.nodes.get('directorStoragePanel').innerHTML;
    const m = html.match(/onclick="directorStorageDelete\(\)"([^>]*)/);
    assert.ok(m, 'кнопка удаления отрендерена');
    assert.ok(!m[1].includes('disabled'), `«${word}» разблокирует удаление`);
  }
  // чужое слово не разблокирует
  h.run("_directorStorage.confirmText = 'please'; renderDirectorStorage();");
  const m = h.nodes.get('directorStoragePanel').innerHTML.match(/onclick="directorStorageDelete\(\)"([^>]*)/);
  assert.ok(m && m[1].includes('disabled'), 'чужое слово оставляет кнопку заблокированной');
});

test('directorStorageDelete sends the canonical УДАЛИТЬ sentinel regardless of UI language', async () => {
  const h = harness();
  h.run("_directorChannel = 'alpha'; _directorStorage.sessionId = 'sess1';");
  h.run("_directorStorage.confirmText = 'DELETE'; renderDirectorStorage();");
  h.responses['DELETE /api/director/alpha/sessions/sess1/evidence'] = {ok: true};
  await h.context.directorStorageDelete();
  const call = h.calls.find(c => c.url.endsWith('/sessions/sess1/evidence') && c.options.method === 'DELETE');
  assert.ok(call, 'DELETE evidence ушёл');
  const body = JSON.parse(call.options.body);
  assert.equal(body.confirmation, 'УДАЛИТЬ', 'бэкенд-контракт не меняется');
});

test('UA/EN placeholders no longer force Russian input (DEF-06)', () => {
  const src = fs.readFileSync('static/app/25_director_storage.js', 'utf8');
  assert.match(src, /'director\.storage_delete_placeholder': 'Type DELETE'/);
  assert.match(src, /'director\.storage_delete_placeholder': 'Введіть ВИДАЛИТИ'/);
  assert.ok(!src.includes('Type УДАЛИТЬ'), 'EN-плейсхолдер без RU-слова');
  assert.ok(!src.includes('Введіть УДАЛИТЬ'), 'UA-плейсхолдер без RU-слова');
});
