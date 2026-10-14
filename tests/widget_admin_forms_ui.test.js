const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'static', 'app', '15_feedback_2908.js'),
  'utf8',
);

function extractFunction(name) {
  const start = source.indexOf(`async function ${name}(`);
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

function load(context, names) {
  vm.createContext(context);
  vm.runInContext(names.map(extractFunction).join('\n'), context);
  return context;
}

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

test('lower-third save sends the complete scoped widget state', async () => {
  const values = {
    wa2LtName: 'Alekzz', wa2LtTagline: 'играет в CS2', wa2LtSocial: '@alekzz',
    wa2LtAvatar: 'https://example.test/avatar.png', wa2LtTheme: 'glass',
  };
  const calls = [];
  const context = load({
    $: id => ({value: values[id]}),
    toggleChecked: id => id === 'wa2LtVisible',
    wstateapi: async (...args) => { calls.push(args); },
    toast() {}, t: key => key, _waHint() {},
  }, ['wa2LtSave']);

  await context.wa2LtSave();

  assert.deepEqual(plain(calls), [[
    '/api/widgets/lower-third', 'PUT', {
      name: 'Alekzz', tagline: 'играет в CS2', social: '@alekzz',
      avatar_url: 'https://example.test/avatar.png', theme: 'glass', visible: true,
    },
  ]]);
});

test('roulette save trims participants, converts numbers, and refreshes previews', async () => {
  const values = {
    wa2RlParticipants: ' alice, , bob ', wa2RlSpin: '9', wa2RlAuto: '', wa2RlWinner: 'alice',
  };
  const calls = [];
  let refreshes = 0;
  const context = load({
    $: id => ({value: values[id]}),
    toggleChecked: id => id === 'wa2RlVisible',
    wstateapi: async (...args) => { calls.push(args); },
    waRefreshScopedWidgetPreviews: () => { refreshes += 1; },
    toast() {}, t: key => key, _waHint() {},
  }, ['wa2RouletteSave']);

  await context.wa2RouletteSave();

  assert.deepEqual(plain(calls), [[
    '/api/widgets/chat-roulette', 'PUT', {
      participants: ['alice', 'bob'], spin_duration_sec: 9,
      auto_interval_min: 0, winner: 'alice', visible: true,
    },
  ]]);
  assert.equal(refreshes, 1);
});

test('session and recent-event controls dispatch exact production actions', async () => {
  const values = {wa2ReKind: 'donation', wa2ReUser: 'viewer', wa2ReAmount: '250'};
  const calls = [];
  let reloads = 0;
  const context = load({
    $: id => ({value: values[id]}),
    wapi: async (...args) => { calls.push(args); },
    wa2LoadAll: () => { reloads += 1; },
    toast() {}, t: key => key, _waHint() {},
  }, ['wa2SessionStart', 'wa2SessionStop', 'wa2RecentAdd', 'wa2RecentClear']);

  await context.wa2SessionStart();
  await context.wa2SessionStop();
  await context.wa2RecentAdd();
  await context.wa2RecentClear();

  assert.deepEqual(plain(calls), [
    ['/api/widgets/stream-session/start', 'POST', {}],
    ['/api/widgets/stream-session/stop', 'POST', {}],
    ['/api/widgets/recent-events', 'POST', {kind: 'donation', username: 'viewer', amount: 250}],
    ['/api/widgets/recent-events', 'DELETE'],
  ]);
  assert.equal(reloads, 2);
});

test('widget admin loading is inert when its panel card is absent', async () => {
  let requests = 0;
  const context = load({
    $: () => null,
    wstateapi: async () => { requests += 1; },
  }, ['wa2LoadAll']);

  await context.wa2LoadAll();

  assert.equal(requests, 0);
});
