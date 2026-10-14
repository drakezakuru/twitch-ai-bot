const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'static', 'app', '13_widgets_session.js'),
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

function load(context, names) {
  vm.createContext(context);
  vm.runInContext(names.map(extractFunction).join('\n'), context);
  return context;
}

function statusElement() {
  return {
    classList: {toggle() {}},
    dataset: {},
    textContent: '',
  };
}

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

test('poll keeps comma-containing choices and sends exact bot/channel scope', async () => {
  const calls = [];
  const elements = {
    waPollTitle: {value: 'Choose'},
    waPollDuration: {value: '90'},
    waPollStatus: statusElement(),
  };
  const context = load({
    $: id => elements[id],
    _waHint() {},
    _waPollCtx: async () => ({aid: 42, ch: 'channel'}),
    document: {
      querySelectorAll: () => [{value: 'Tea, coffee'}, {value: 'Water'}],
    },
    t: key => key,
    wapi: async (...args) => { calls.push(args); return {ok: true}; },
  }, ['waPollSetStatus', 'waPollChoiceValues', 'waTwitchPollCreate']);

  await context.waTwitchPollCreate();

  assert.deepEqual(plain(calls), [[
    '/api/widgets/twitch-poll',
    'POST',
    {
      account_id: 42,
      channel: 'channel',
      title: 'Choose',
      choices: ['Tea, coffee', 'Water'],
      duration_seconds: 90,
    },
  ]]);
});

test('poll add/remove behavior enforces two-to-five choice limits', () => {
  const inputs = [{value: 'A'}, {value: 'B'}];
  const elements = {
    waPollAddChoice: {disabled: false},
    waPollChoiceCount: {textContent: ''},
    waPollChoices: {
      append(row) { inputs.push(row.input); },
      querySelectorAll() { return inputs; },
    },
    waPollStatus: statusElement(),
  };
  const document = {
    createElement(tag) {
      const element = {
        append(input) { this.input = input; },
        focus() {},
      };
      if (tag === 'button') element.parentElement = {remove() { inputs.pop(); }};
      return element;
    },
    querySelectorAll() { return inputs; },
  };
  const context = load({$: id => elements[id], document, t: key => key}, [
    'waPollSetStatus',
    'waPollChoiceValues',
    'waPollSyncChoices',
    'waPollValidateChoices',
    'waPollAddChoice',
    'waPollRemoveChoice',
  ]);

  context.waPollRemoveChoice({parentElement: {remove() { throw new Error('removed below minimum'); }}});
  assert.equal(elements.waPollStatus.dataset.validation, 'true');
  for (let index = 0; index < 4; index += 1) context.waPollAddChoice();
  assert.equal(inputs.length, 5);
  assert.equal(elements.waPollAddChoice.disabled, true);
});

test('prediction converts minutes, validates locally, and sends scoped payload', async () => {
  const calls = [];
  const elements = {
    waPredictionStatus: statusElement(),
    waPredictionTitle: {value: 'Winner?'},
    waPredictionWindow: {value: '2'},
    waPredictionWindowUnit: {value: 'minutes'},
  };
  const context = load({
    $: id => elements[id],
    _waHint() {},
    _waPollCtx: async () => ({aid: 7, ch: 'streamer'}),
    document: {
      querySelectorAll: () => [{value: 'Alpha'}, {value: 'Beta'}],
    },
    t: key => key,
    waPredictionRefresh: async () => {},
    wapi: async (...args) => { calls.push(args); return {ok: true}; },
  }, [
    'waPredictionSetStatus',
    'waPredictionOutcomeValues',
    'waPredictionWindowSeconds',
    'waPredictionValidate',
    'waTwitchPredictionCreate',
  ]);

  await context.waTwitchPredictionCreate();

  assert.deepEqual(plain(calls[0]), [
    '/api/widgets/twitch-prediction',
    'POST',
    {
      account_id: 7,
      channel: 'streamer',
      title: 'Winner?',
      outcomes: ['Alpha', 'Beta'],
      prediction_window: 120,
    },
  ]);
  elements.waPredictionWindow.value = '0.4';
  assert.equal(context.waPredictionValidate(), false);
  assert.equal(elements.waPredictionStatus.textContent, 'widgets.prediction.invalid_window');
});

test('prediction add/remove behavior enforces two-to-ten outcome limits', () => {
  const inputs = [{value: 'A'}, {value: 'B'}];
  const elements = {
    waPredictionAddOutcome: {disabled: false},
    waPredictionOutcomeCount: {textContent: ''},
    waPredictionOutcomes: {
      append(row) { inputs.push(row.input); },
      querySelectorAll() { return inputs; },
    },
    waPredictionStatus: statusElement(),
  };
  const document = {
    createElement() {
      return {
        append(input) { this.input = input; },
        focus() {},
        setAttribute() {},
      };
    },
    querySelectorAll() { return inputs; },
  };
  const context = load({
    $: id => elements[id],
    document,
    t: key => key,
    waPredictionValidate() {},
  }, [
    'waPredictionSetStatus',
    'waPredictionSyncOutcomes',
    'waPredictionAddOutcome',
    'waPredictionRemoveOutcome',
  ]);

  context.waPredictionRemoveOutcome({parentElement: {remove() { throw new Error('removed below minimum'); }}});
  assert.equal(elements.waPredictionStatus.dataset.validation, 'true');
  for (let index = 0; index < 9; index += 1) context.waPredictionAddOutcome();
  assert.equal(inputs.length, 10);
  assert.equal(elements.waPredictionAddOutcome.disabled, true);
});

test('prediction cancellation requires confirmation and marks confirmed request', async () => {
  const calls = [];
  let confirmed = false;
  const elements = {waPredictionStatus: statusElement()};
  const context = load({
    $: id => elements[id],
    _waHint() {},
    _waPollCtx: async () => ({aid: 9, ch: 'channel'}),
    confirm: () => confirmed,
    t: key => key,
    waPredictionRefresh: async () => {},
    wapi: async (...args) => { calls.push(args); return {ok: true}; },
  }, ['waPredictionSetStatus', 'waPredictionEnd']);

  await context.waPredictionEnd('CANCELED', 'prediction-1');
  assert.equal(calls.length, 0);
  confirmed = true;
  await context.waPredictionEnd('CANCELED', 'prediction-1');
  assert.deepEqual(plain(calls[0]), [
    '/api/widgets/twitch-prediction/end',
    'POST',
    {
      account_id: 9,
      channel: 'channel',
      prediction_id: 'prediction-1',
      status: 'CANCELED',
      winning_outcome_id: null,
      confirmed: true,
    },
  ]);
});
