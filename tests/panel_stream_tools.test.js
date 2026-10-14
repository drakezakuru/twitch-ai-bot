// P8-A3 behavior tests: Stream Tools visibility for non-moderators executes
// production loadStreamTools in Node VM. C-010 migration of source-marker tests.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const STREAM_JS = fs.readFileSync(path.join(__dirname, '..', 'static', 'app', '10_stream_p4_p6.js'), 'utf8');

function extractFunction(source, name) {
  const patterns = [`async function ${name}(`, `function ${name}(`];
  const starts = patterns.map(p => source.indexOf(p)).filter(i => i >= 0);
  const start = Math.min(...starts);
  assert.notEqual(start, -1, `missing ${name}`);
  const brace = source.indexOf('{', start);
  let depth = 0;
  for (let i = brace; i < source.length; i += 1) {
    if (source[i] === '{') depth += 1;
    if (source[i] === '}') depth -= 1;
    if (depth === 0) return source.slice(start, i + 1);
  }
  throw new Error(`unterminated ${name}`);
}

function extractConst(source, name) {
  const start = source.indexOf(`const ${name} =`);
  assert.notEqual(start, -1, `missing ${name}`);
  const openers = ['{', '['].map(ch => source.indexOf(ch, start)).filter(i => i >= 0);
  const brace = Math.min(...openers);
  const closer = source[brace] === '{' ? '}' : ']';
  let depth = 0;
  for (let i = brace; i < source.length; i += 1) {
    if (source[i] === source[brace]) depth += 1;
    if (source[i] === closer) {
      depth -= 1;
      if (depth === 0) return source.slice(start, source.indexOf(';', i) + 1);
    }
  }
  throw new Error(`unterminated ${name}`);
}

function fakeElement(id) {
  return { id, innerHTML: '', classList: { hidden: false, toggle(name, on) { this.hidden = !!on; }, contains(n) { return !!this[n]; } } };
}

function load() {
  const elements = {};
  const ctx = {
    document: { querySelectorAll: () => [], querySelector: () => null },
    $: id => (elements[id] = elements[id] || fakeElement(id)),
    t: key => key,
    esc: s => String(s ?? ''),
    localStorage: { getItem: () => 'ru' },
    console: { error() {}, warn() {} },
    api: async () => ({}),
    loadStreamToolsHistoryCalls: [],
    loadStreamToolsHistory(id) { ctx.loadStreamToolsHistoryCalls.push(id); },
  };
  const code = [
    extractConst(STREAM_JS, 'STREAM_TOOL_ORDER'),
    extractConst(STREAM_JS, 'STREAM_TOOL_LABELS'),
    extractConst(STREAM_JS, 'STREAM_MODE_LABELS'),
    extractFunction(STREAM_JS, '_stLang'),
    extractFunction(STREAM_JS, 'loadStreamTools'),
  ].join('\n');
  vm.createContext(ctx);
  vm.runInContext(code, ctx);
  return { ctx, elements };
}

test('non-moderator: form and history hidden entirely, single not_moderator line', async () => {
  const { ctx, elements } = load();
  ctx.api = async () => ({ ok: false });
  await ctx.loadStreamTools('b1');
  assert.match(elements.streamToolsModes.innerHTML, /stream_tools\.not_moderator/);
  for (const id of ['streamToolsManual', 'streamToolsHistoryHead', 'streamToolsHistory']) {
    assert.equal(elements[id].classList.hidden, true, `#${id} must be hidden for non-moderator`);
  }
  assert.equal(elements.streamToolsHistory.innerHTML, '', 'stale history cleared');
  assert.deepEqual(ctx.loadStreamToolsHistoryCalls, [], 'history loader must not run for non-moderator');
});

test('moderator: form visible with a select per tool, current mode preselected', async () => {
  const { ctx, elements } = load();
  ctx.api = async () => ({
    ok: true,
    modes: { title: 'suggest', slow: 'auto' },
    scopes: { title: 'channel:manage:broadcast' },
  });
  await ctx.loadStreamTools('b1');
  for (const id of ['streamToolsManual', 'streamToolsHistoryHead', 'streamToolsHistory']) {
    assert.equal(elements[id].classList.hidden, false, `#${id} must be visible for moderator`);
  }
  assert.equal((elements.streamToolsModes.innerHTML.match(/<select/g) || []).length, 7, 'one select per tool in STREAM_TOOL_ORDER');
  assert.match(elements.streamToolsModes.innerHTML, /value="suggest" selected/);
  assert.match(elements.streamToolsModes.innerHTML, /value="auto" selected/);
  assert.match(elements.streamToolsModes.innerHTML, /channel:manage:broadcast/);
  assert.deepEqual(ctx.loadStreamToolsHistoryCalls, ['b1'], 'history loads for moderator');
});

test('missing mode defaults to off with it preselected', async () => {
  const { ctx, elements } = load();
  ctx.api = async () => ({ ok: true, modes: {} });
  await ctx.loadStreamTools('b1');
  assert.equal((elements.streamToolsModes.innerHTML.match(/value="off" selected/g) || []).length, 7);
});

test('api failure: error line instead of modes, no silent dead form', async () => {
  const { ctx, elements } = load();
  ctx.api = async () => { throw new Error('boom'); };
  await ctx.loadStreamTools('b1');
  assert.match(elements.streamToolsModes.innerHTML, /empty\.load_failed/);
  assert.ok(!elements.streamToolsModes.innerHTML.includes('stream_tools.not_moderator'));
});
