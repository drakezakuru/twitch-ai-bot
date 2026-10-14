const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'static', 'app', '03_bots.js'),
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

function element(value = '') {
  return {
    value,
    classList: {
      active: false,
      contains(name) { return name === 'active' && this.active; },
      toggle(name, enabled) { if (name === 'active') this.active = enabled; },
    },
  };
}

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

test('attention load applies keyword state from the account-scoped response', async () => {
  const elements = Object.fromEntries([
    'botAttentionMode', 'botIgnoreNoise', 'botBatchWindow', 'botBatchMax',
    'botMinToReply', 'botCooldownReply', 'botMaxPerMin', 'botReplyMentions',
    'botInterruptGuard', 'botTTSPercent', 'botReplyKeywords', 'botReplyKeywordsList',
  ].map(id => [id, element()]));
  const calls = [];
  const context = load({
    $: id => elements[id],
    api: async url => {
      calls.push(url);
      return {config: {reply_to_keywords: 1, reply_keywords: ' вопрос, помоги '}};
    },
    setToggle: (id, enabled) => { elements[id].classList.active = enabled; },
  }, ['loadBotAttention']);

  await context.loadBotAttention(42);

  assert.deepEqual(calls, ['/api/accounts/42/attention-config']);
  assert.equal(elements.botReplyKeywords.classList.active, true);
  assert.equal(elements.botReplyKeywordsList.value, ' вопрос, помоги ');
  assert.equal(elements.botAttentionMode.value, 'everyone');
});

test('attention save trims keywords and sends the complete scoped configuration', async () => {
  const elements = {
    botAttentionMode: element('streamer_only'),
    botIgnoreNoise: element(),
    botBatchWindow: element('4.5'),
    botBatchMax: element('8'),
    botMinToReply: element('2'),
    botCooldownReply: element('15.5'),
    botMaxPerMin: element('4'),
    botReplyMentions: element(),
    botInterruptGuard: element('-20'),
    botTTSPercent: element('120'),
    botReplyKeywords: element(),
    botReplyKeywordsList: element('  вопрос, помоги  '),
  };
  elements.botIgnoreNoise.classList.active = true;
  elements.botReplyMentions.classList.active = true;
  elements.botReplyKeywords.classList.active = true;
  const calls = [];
  const context = load({
    $: id => elements[id],
    _currentBotId: 7,
    api: async (...args) => { calls.push(args); },
    jopts: (method, data) => ({method, data}),
    t: key => key,
    toast() {},
  }, ['saveBotAttention']);

  await context.saveBotAttention();

  assert.deepEqual(plain(calls), [[
    '/api/accounts/7/attention-config',
    {
      method: 'PUT',
      data: {
        attention_mode: 'streamer_only',
        ignore_noise: 1,
        batch_window_sec: 4.5,
        batch_max_size: 8,
        min_messages_to_respond: 2,
        cooldown_after_reply_sec: 15.5,
        max_replies_per_minute: 4,
        reply_to_mentions: 1,
        dont_interrupt_streamer_sec: 0,
        tts_reply_percent: 100,
        reply_to_keywords: 1,
        reply_keywords: 'вопрос, помоги',
      },
    },
  ]]);
});

test('attention save is inert without a selected account', async () => {
  const calls = [];
  const context = load({
    _currentBotId: 0,
    api: async (...args) => { calls.push(args); },
  }, ['saveBotAttention']);

  await context.saveBotAttention();

  assert.equal(calls.length, 0);
});
