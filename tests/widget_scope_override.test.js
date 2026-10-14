// Пер-виджетный канал: override-логика waWidgetStateUrl (семейство из пути +
// localStorage «widgetScopeOverrides», фолбэк на общий скоуп биндеров).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'static', 'app', '07_widgets.js'),
  'utf8',
);

function extractFunction(name) {
  const patterns = [`async function ${name}(`, `function ${name}(`];
  const starts = patterns.map(pattern => source.indexOf(pattern)).filter(index => index >= 0);
  const start = Math.min(...starts);
  assert.notEqual(start, -1, `missing ${name}`);
  const brace = source.indexOf('{', start);
  let depth = 0;
  for (let index = brace; index < source.length; index += 1) {
    if (source[index] === '{') depth += 1;
    if (source[index] === '}') depth -= 1;
    if (depth === 0) return source.slice(start, index + 1);
  }
  throw new Error(`unterminated ${name}`);
}

function makeContext() {
  const store = {};
  const context = {
    URL, // vm-контекст не наследует глобали Node
    localStorage: {
      getItem: key => (key in store ? store[key] : null),
      setItem: (key, value) => { store[key] = String(value); },
      removeItem: key => { delete store[key]; },
      _store: store,
    },
    location: { origin: 'http://panel.local' },
    widgetOutputUrl: p => p,
    waBindingScope: () => ({ account_id: 1, channel: 'globalch' }),
  };
  vm.createContext(context);
  vm.runInContext(
    ['waWidgetFamily', 'waWidgetScopeOverrides', 'waWidgetScopeOverrideFor', 'waWidgetStateUrl', 'waWidgetBestUrl', 'waChannelScopeMatch']
      .map(extractFunction).join('\n'),
    context,
  );
  return context;
}

test('family extracted from widget and api paths', () => {
  const ctx = makeContext();
  assert.equal(vm.runInContext(`waWidgetFamily('/widget/goals')`, ctx), 'goals');
  assert.equal(vm.runInContext(`waWidgetFamily('/widget/recent-events?preview=1')`, ctx), 'recent-events');
  assert.equal(vm.runInContext(`waWidgetFamily('/api/widgets/goals')`, ctx), 'goals');
  assert.equal(vm.runInContext(`waWidgetFamily('/api/widgets/counter/main')`, ctx), 'counter');
  assert.equal(vm.runInContext(`waWidgetFamily('/obs/tts')`, ctx), '');
});

test('no override falls back to global binding scope', () => {
  const ctx = makeContext();
  const url = vm.runInContext(`waWidgetStateUrl('/widget/goals')`, ctx);
  assert.ok(url.includes('account_id=1'), url);
  assert.ok(url.includes('channel=globalch'), url);
});

test('per-widget override wins over global scope', () => {
  const ctx = makeContext();
  vm.runInContext(`localStorage.setItem('widgetScopeOverrides', JSON.stringify({ goals: '3:test_channel' }))`, ctx);
  const goals = vm.runInContext(`waWidgetStateUrl('/widget/goals')`, ctx);
  assert.ok(goals.includes('account_id=3'), goals);
  assert.ok(goals.includes('channel=test_channel'), goals);
  // другой виджет остаётся на общем скоупе
  const other = vm.runInContext(`waWidgetStateUrl('/api/widgets/sub-goal')`, ctx);
  assert.ok(other.includes('account_id=1'), other);
  assert.ok(other.includes('channel=globalch'), other);
});

test('override applies by family for both preview page and settings api', () => {
  const ctx = makeContext();
  vm.runInContext(`localStorage.setItem('widgetScopeOverrides', JSON.stringify({ 'recent-events': '4:test_channel' }))`, ctx);
  const page = vm.runInContext(`waWidgetStateUrl('/widget/recent-events?preview=1')`, ctx);
  const api = vm.runInContext(`waWidgetStateUrl('/api/widgets/public/recent-events')`, ctx);
  for (const url of [page, api]) {
    assert.ok(url.includes('account_id=4'), url);
    assert.ok(url.includes('channel=test_channel'), url);
  }
});

test('invalid override value falls back to global scope', () => {
  const ctx = makeContext();
  vm.runInContext(`localStorage.setItem('widgetScopeOverrides', JSON.stringify({ goals: 'oops', 'sub-goal': ':', countdown: '0' }))`, ctx);
  for (const route of ['/widget/goals', '/widget/sub-goal', '/widget/countdown']) {
    const url = vm.runInContext(`waWidgetStateUrl('${route}')`, ctx);
    assert.ok(url.includes('account_id=1'), `${route}: ${url}`);
    assert.ok(url.includes('channel=globalch'), `${route}: ${url}`);
  }
});

test('channel normalizes leading hashes', () => {
  const ctx = makeContext();
  vm.runInContext(`localStorage.setItem('widgetScopeOverrides', JSON.stringify({ goals: '3:#test_channel' }))`, ctx);
  const url = vm.runInContext(`waWidgetStateUrl('/widget/goals')`, ctx);
  assert.ok(url.includes('channel=test_channel'), url);
  assert.ok(!url.includes('channel=%23'), url);
});

test('throws widget_scope_required when no scope anywhere', () => {
  const ctx = makeContext();
  ctx.waBindingScope = () => ({ account_id: 0, channel: '' });
  vm.runInContext('waBindingScope = ' + ctx.waBindingScope.toString(), ctx);
  assert.throws(() => vm.runInContext(`waWidgetStateUrl('/widget/goals')`, ctx), /widget_scope_required/);
});

test('waWidgetBestUrl falls back to plain widget url when scope empty', () => {
  const ctx = makeContext();
  ctx.waBindingScope = () => ({ account_id: 0, channel: '' });
  vm.runInContext('waBindingScope = ' + ctx.waBindingScope.toString(), ctx);
  const url = vm.runInContext(`waWidgetBestUrl('/widget/goals')`, ctx);
  assert.equal(url, '/widget/goals');
});

test('saved widget channel follows its current bot after reconnect', () => {
  const ctx = makeContext();
  const match = vm.runInContext(
    `waChannelScopeMatch([
      { account_id: 2, channel: 'test_channel' },
      { account_id: 3, channel: 'other-channel' },
    ], '1:test_channel')`,
    ctx,
  );
  assert.deepEqual(JSON.parse(JSON.stringify(match)), { account_id: 2, channel: 'test_channel' });
});

test('saved widget channel does not match an unavailable channel', () => {
  const ctx = makeContext();
  const match = vm.runInContext(
    `waChannelScopeMatch([{ account_id: 2, channel: 'other-channel' }], '1:test_channel')`,
    ctx,
  );
  assert.equal(match, null);
});
