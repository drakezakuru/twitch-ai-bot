// P8-C10 behavior tests: custom providers merged into AI selects — production
// panel code executes in Node VM. C-010 migration of source-marker tests.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const PROVIDERS_JS = fs.readFileSync(path.join(__dirname, '..', 'static', 'app', '08_providers_moderation.js'), 'utf8');

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

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

class FakeOption {
  constructor(value = '', text = '') {
    this.value = value;
    this.textContent = text;
    this.dataset = {};
    this._parent = null;
  }
  remove() {
    if (this._parent) {
      const i = this._parent.options.indexOf(this);
      if (i >= 0) this._parent.options.splice(i, 1);
    }
  }
}

class FakeSelect {
  constructor(id) {
    this.id = id;
    this.value = '';
    this.options = [new FakeOption('openai', 'OpenAI')];
  }
  querySelectorAll(sel) {
    assert.equal(sel, 'option[data-cp]', 'refreshCustomProviderOptions must scope removal to custom options');
    return this.options.filter(o => o.dataset && o.dataset.cp);
  }
  appendChild(node) {
    node._parent = this;
    this.options.push(node);
  }
  byValue(v) { return this.options.find(o => o.value === v); }
}

function load(names, { providers } = {}) {
  const elements = { globalAIProvider: new FakeSelect('globalAIProvider'), botAIProvider: new FakeSelect('botAIProvider') };
  const ctx = {
    document: {
      querySelectorAll: () => [],
      querySelector: () => null,
      createElement: tag => {
        assert.equal(tag, 'option', 'select options are built with document.createElement');
        return new FakeOption();
      },
      getElementById: () => null,
    },
    $: id => elements[id] || null,
    t: key => key,
    esc: s => String(s ?? ''),
    console: { warn() {}, error() {}, log() {} },
    _customProvidersCache: providers || [],
    _cpEditingId: null,
    _cpModelRows: [],
    toasts: [],
    toast(msg, type) { ctx.toasts.push([msg, type]); },
    apiCalls: [],
    apiReject: null,
    api: async (url, opts) => {
      ctx.apiCalls.push([url, opts]);
      if (ctx.apiReject) throw ctx.apiReject;
      return { items: ctx.apiResponseItems || [] };
    },
    jopts: (method, body) => ({ method, body }),
    renderCalls: 0,
    renderCustomProvidersList() { ctx.renderCalls += 1; },
    resetCalls: 0,
    resetCustomProviderForm() { ctx.resetCalls += 1; ctx._cpEditingId = null; },
  };
  const code = names.map(n => extractFunction(PROVIDERS_JS, n)).join('\n');
  vm.createContext(ctx);
  vm.runInContext(code, ctx);
  return { ctx, elements };
}

test('loadCustomProviders restores saved custom:<name> into an empty global select', async () => {
  // Решение владельца 15.09: глобальный провайдер = custom:dahl. loadSettings ставит
  // значение до прихода именованных провайдеров — селект сбрасывался в пусто.
  const { ctx, elements } = load(['refreshCustomProviderOptions', 'loadCustomProviders'], {
    providers: [{ name: 'dahl' }, { name: 'demo_provider' }],
  });
  ctx.apiResponseItems = [{ name: 'dahl' }, { name: 'demo_provider' }];
  ctx._aiConfig = { provider: 'custom:dahl' };
  elements.globalAIProvider.value = '';
  await ctx.loadCustomProviders();
  assert.equal(elements.globalAIProvider.value, 'custom:dahl');
  assert.ok(elements.globalAIProvider.byValue('custom:dahl'), 'named provider option appended');
});

test('refreshCustomProviderOptions appends custom:<name> options without touching selection', () => {
  const { ctx, elements } = load(['refreshCustomProviderOptions'], {
    providers: [{ name: 'Alpha' }, { name: 'Beta' }],
  });
  elements.globalAIProvider.value = 'openai';
  ctx.refreshCustomProviderOptions();
  const sel = elements.globalAIProvider;
  assert.deepEqual(sel.byValue('custom:Alpha').value, 'custom:Alpha', 'named providers appear as custom:<name>');
  assert.equal(sel.byValue('custom:Alpha').textContent, '🧩 Alpha');
  assert.equal(sel.byValue('custom:Alpha').dataset.cp, '1');
  assert.equal(sel.byValue('openai').value, 'openai', 'stock options untouched');
  assert.equal(sel.value, 'openai', 'cache refresh must not change the selected provider');
  assert.ok(elements.botAIProvider.byValue('custom:Beta'), 'per-bot override select also populated');
});

test('removed provider disappears; stale selection is retained, not reset', () => {
  const { ctx, elements } = load(['refreshCustomProviderOptions'], { providers: [{ name: 'Alpha' }] });
  const sel = elements.globalAIProvider;
  ctx.refreshCustomProviderOptions();
  sel.value = 'custom:Alpha';
  ctx._customProvidersCache = [];
  ctx.refreshCustomProviderOptions();
  assert.ok(!sel.options.some(o => o.dataset.cp === '1'), 'deleted provider option removed');
  const stale = sel.options.find(o => o.dataset.cp === 'stale');
  assert.ok(stale, 'stale selected value retained for UI safety');
  assert.equal(sel.value, 'custom:Alpha', 'selection preserved while provider list refreshes');
});

test('saveCustomProvider create: builds lists from model rows, posts once, resets and reloads', async () => {
  // Q15b (E2): один список моделей с типами вместо двух textarea
  const { ctx, elements } = load(['saveCustomProvider', '_cpListsFromRows', 'loadCustomProviders', 'refreshCustomProviderOptions']);
  elements.cpName = { value: ' MyLLM ' };
  elements.cpBaseUrl = { value: ' http://x ' };
  elements.cpApiKey = { value: 'sk-1' };
  ctx._cpModelRows = [
    { name: ' m1 ', type: 'chat' },
    { name: 'm2', type: 'both' },
    { name: ' v1 ', type: 'vision' },
  ];
  ctx.apiResponseItems = [{ name: 'MyLLM' }];
  await ctx.saveCustomProvider();
  assert.deepEqual(plain(ctx.apiCalls[0]), ['/api/custom-providers', {
    method: 'POST',
    body: { name: 'MyLLM', base_url: 'http://x', api_key: 'sk-1', models: ['m1', 'm2'], vision_models: ['m2', 'v1'] },
  }], 'trimmed payload posted once, typed rows split into chat/vision lists');
  assert.deepEqual(ctx.apiCalls[1], ['/api/custom-providers', undefined], 'list reloaded via GET after save');
  assert.deepEqual(ctx.toasts.at(-1), ['cp.created', 'success']);
  assert.equal(ctx.resetCalls, 1, 'form reset after save');
  assert.equal(ctx.renderCalls, 1, 'list reloaded after save');
  assert.deepEqual(ctx._customProvidersCache, [{ name: 'MyLLM' }]);
});

test('saveCustomProvider edit: PUT to provider id', async () => {
  const { ctx, elements } = load(['saveCustomProvider', '_cpListsFromRows', 'loadCustomProviders', 'refreshCustomProviderOptions']);
  elements.cpName = { value: 'Renamed' };
  elements.cpBaseUrl = { value: 'http://y' };
  elements.cpApiKey = { value: '' };
  ctx._cpModelRows = [];
  ctx._cpEditingId = 'p7';
  await ctx.saveCustomProvider();
  assert.deepEqual(plain(ctx.apiCalls[0]), ['/api/custom-providers/p7', {
    method: 'PUT',
    body: { name: 'Renamed', base_url: 'http://y', api_key: '', models: [], vision_models: [] },
  }]);
  assert.deepEqual(ctx.toasts.at(-1), ['cp.updated', 'success']);
});

test('saveCustomProvider without a name: error toast, no API call', async () => {
  const { ctx, elements } = load(['saveCustomProvider', '_cpListsFromRows']);
  elements.cpName = { value: '   ' };
  elements.cpBaseUrl = { value: 'http://x' };
  await ctx.saveCustomProvider();
  assert.deepEqual(ctx.apiCalls, [], 'empty name must not hit the API');
  assert.deepEqual(ctx.toasts, [['cp.name_required', 'error']]);
});

test('saveCustomProvider failure: error toast with detail, form kept for retry', async () => {
  const { ctx, elements } = load(['saveCustomProvider', '_cpListsFromRows']);
  elements.cpName = { value: 'X' };
  elements.cpBaseUrl = { value: 'http://x' };
  ctx.apiReject = new Error('boom');
  await ctx.saveCustomProvider();
  assert.deepEqual(ctx.toasts, [['toast.error_detail', 'error']]);
  assert.equal(ctx.resetCalls, 0, 'failed save must not clear the form');
});

test('loadCustomProviders: caches items, renders, refreshes selects; failure keeps cache', async () => {
  const ok = load(['loadCustomProviders', 'refreshCustomProviderOptions']);
  ok.ctx.apiResponseItems = [{ name: 'A' }];
  await ok.ctx.loadCustomProviders();
  assert.deepEqual(ok.ctx._customProvidersCache, [{ name: 'A' }]);
  assert.equal(ok.ctx.renderCalls, 1);

  const fail = load(['loadCustomProviders', 'refreshCustomProviderOptions'], { providers: [{ name: 'Keep' }] });
  fail.ctx.apiReject = new Error('boom');
  await fail.ctx.loadCustomProviders();
  assert.deepEqual(fail.ctx._customProvidersCache, [{ name: 'Keep' }], 'failed refresh must not wipe the cache');
});
