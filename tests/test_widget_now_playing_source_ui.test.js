const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'static', 'app', '12_dashboard_extras.js'),
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

function elements(values = {}) {
  return Object.fromEntries([
    'waNpSource', 'waNpLastfmUser', 'waNpLastfmKey', 'waNpMprisPlayer',
  ].map(id => [id, {value: values[id] || '', placeholder: ''}]));
}

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

test('loading source settings never renders a returned Last.fm secret', async () => {
  const fields = elements();
  const calls = [];
  const context = load({
    $: id => fields[id],
    wapi: async (...args) => {
      calls.push(args);
      return {
        source: 'lastfm', lastfm_user: 'streamer', mpris_player: 'player',
        has_lastfm_api_key: true, lastfm_api_key: 'must-not-render',
      };
    },
    t: key => key,
    _waHint() {},
  }, ['waNpSourceLoad']);

  await context.waNpSourceLoad();

  assert.deepEqual(plain(calls), [['/api/widgets/now-playing/source']]);
  assert.equal(fields.waNpSource.value, 'lastfm');
  assert.equal(fields.waNpLastfmUser.value, 'streamer');
  assert.equal(fields.waNpMprisPlayer.value, 'player');
  assert.equal(fields.waNpLastfmKey.value, '');
  assert.equal(fields.waNpLastfmKey.placeholder, 'placeholder.eleven_key_set');
});

test('saving sends the entered secret once and clears the password field', async () => {
  const fields = elements({
    waNpSource: 'lastfm', waNpLastfmUser: 'streamer',
    waNpLastfmKey: 'new-secret', waNpMprisPlayer: 'player',
  });
  const calls = [];
  const context = load({
    $: id => fields[id],
    wapi: async (...args) => {
      calls.push(args);
      return {has_lastfm_api_key: true};
    },
    t: key => key,
    _waHint() {},
  }, ['waNpSourceSave']);

  await context.waNpSourceSave();

  assert.deepEqual(plain(calls), [[
    '/api/widgets/now-playing/source', 'PUT', {
      source: 'lastfm', lastfm_user: 'streamer',
      lastfm_api_key: 'new-secret', mpris_player: 'player',
    },
  ]]);
  assert.equal(fields.waNpLastfmKey.value, '');
  assert.equal(fields.waNpLastfmKey.placeholder, 'placeholder.eleven_key_set');
});

test('loading is inert when the panel card is absent', async () => {
  let requests = 0;
  const context = load({
    $: () => null,
    wapi: async () => { requests += 1; },
  }, ['waNpSourceLoad']);

  await context.waNpSourceLoad();

  assert.equal(requests, 0);
});
