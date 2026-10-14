// P8-A2 behavior tests: analytics loading/empty/error states execute production code in Node VM.
// C-010 migration: replaces static source-marker assertions for the analytics surfaces.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const FILES = {
  app: fs.readFileSync(path.join(__dirname, '..', 'static', 'app.js'), 'utf8'),
  chat: fs.readFileSync(path.join(__dirname, '..', 'static', 'app', '04_chat_settings.js'), 'utf8'),
  widgets: fs.readFileSync(path.join(__dirname, '..', 'static', 'app', '07_widgets.js'), 'utf8'),
  feedback: fs.readFileSync(path.join(__dirname, '..', 'static', 'app', '08_providers_moderation.js'), 'utf8'),
  i18n: fs.readFileSync(path.join(__dirname, '..', 'static', 'app', '24_dynamic_i18n.js'), 'utf8'),
  logs: fs.readFileSync(path.join(__dirname, '..', 'static', 'app', '15_feedback_2908.js'), 'utf8'),
};

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

// Elements default to the "still loading" placeholder state the panel ships with,
// so every test proves the loader replaced it.
function loadingElement(id) {
  return {
    id,
    value: '',
    options: [],
    innerHTML: '<div class="text-muted">Загрузка...</div>',
    textContent: '',
    style: {},
    classList: { add() {}, remove() {}, contains: () => false, toggle() {} },
    appendChild() {},
    setAttribute() {},
  };
}

function load(codeSpec, { responses } = {}) {
  const elements = {};
  const ctx = {
    document: {
      querySelectorAll: () => [],
      querySelector: () => null,
      // esc() from app.js relies on textContent → innerHTML round-trip.
      createElement: () => {
        const node = {
          innerHTML: '',
          style: {},
          classList: { add() {}, remove() {}, contains: () => false, toggle() {} },
          appendChild() {},
          setAttribute() {},
        };
        Object.defineProperty(node, 'textContent', {
          set(v) {
            node.innerHTML = String(v)
              .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
          },
          get() { return node.innerHTML; },
        });
        return node;
      },
    },
    window: { innerWidth: 1024 },
    history: { replaceState() {} },
    $: id => (elements[id] = elements[id] || loadingElement(id)),
    t: key => key,
    esc: s => String(s ?? ''),
    console: { error() {}, warn() {}, log() {} },
    apiCalls: [],
    apiReject: null,
    api: async (url, opts) => {
      ctx.apiCalls.push(url);
      if (ctx.apiReject) throw ctx.apiReject;
      const hit = (responses || []).find(([prefix]) => url.startsWith(prefix));
      return hit ? hit[1] : {};
    },
    HEATMAP_DOW: ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'],
    _allBots: [],
  };
  const code = codeSpec.map(([file, name]) => extractFunction(FILES[file], name)).join('\n');
  vm.createContext(ctx);
  vm.runInContext(extractFunction(FILES.i18n, 'panelI18n'), ctx);
  vm.runInContext(code, ctx);
  return { ctx, elements };
}

const LOAD_ANALYTICS = [
  ['app', 'esc'],
  ['logs', 'logsEmptyHtml'],
  ['chat', 'renderLogLine'],
  ['chat', 'renderAnalyticsLogs'],
  ['chat', 'loadAnalytics'],
];

test('showSection("analytics") runs the full sub-loader chain, trending excluded', async () => {
  const ctx = {
    document: {
      querySelectorAll: () => [],
      querySelector: () => null,
      createElement: () => ({
        innerHTML: '',
        style: {},
        classList: { add() {}, remove() {}, contains: () => false, toggle() {} },
        appendChild() {},
        setAttribute() {},
      }),
    },
    window: { innerWidth: 1024 },
    history: { replaceState() {} },
    $: () => null,
    t: key => key,
    confirmDirty: () => true,
  };
  const hooks = ['loadAnalytics', 'loadHeatmap', 'loadChat24h', 'loadFeedbackSummary', 'loadPerBotStatsSelect'];
  hooks.forEach(name => {
    ctx[name] = () => { (ctx.__called = ctx.__called || []).push(name); };
  });
  vm.createContext(ctx);
  vm.runInContext(extractFunction(FILES.app, 'showSection'), ctx);
  vm.runInContext('showSection("analytics")', ctx);
  assert.deepEqual(ctx.__called, hooks, 'loadAnalytics + all four sub-loaders run');
  assert.ok(!ctx.__called.includes('loadTrendingWords'), 'trending loader removed (P8-C14)');
});

test('loadAnalytics success with empty data replaces every loading stub', async () => {
  const { ctx, elements } = load(LOAD_ANALYTICS, {
    responses: [
      ['/api/stats/all', []],
      ['/api/bot-logs?limit=200', { logs: [] }],
      ['/api/stats/sentiment?hours=24', { summary: {} }],
      ['/api/stats/wordcloud?hours=24&top_n=20', { items: [] }],
    ],
  });
  await ctx.loadAnalytics();
  assert.match(elements.wordCloudSummary.innerHTML, /analytics\.empty/);
  assert.match(elements.chartActivity.innerHTML, /stats\.nodata/);
  assert.ok(elements.analyticsBotFilter.innerHTML.includes('analytics.all_bots'), 'bot filter keeps its default option');
  assert.match(elements.analyticsLogsContent.innerHTML, /logs\.empty_hint/, 'logs box shows the empty state, not «Загрузка...»');
  assert.equal(elements.sentimentSummary.textContent, '🙂 0  😐 0  🙁 0  | net 0');
});

test('loadAnalytics success with data renders real values', async () => {
  const { ctx, elements } = load(LOAD_ANALYTICS, {
    responses: [
      ['/api/stats/all', [{ read: 12, sent: 5, nickname: 'BotA', account_id: 'a1' }]],
      ['/api/bot-logs?limit=200', { logs: [] }],
      ['/api/stats/sentiment?hours=24', { summary: { pos: 3, neu: 2, neg: 1, net: 2 } }],
      ['/api/stats/wordcloud?hours=24&top_n=20', { items: [{ word: 'кот', count: 4 }] }],
    ],
  });
  await ctx.loadAnalytics();
  assert.equal(elements.statsTotalMessages.textContent, '12');
  assert.equal(elements.statsAIReplies.textContent, '5');
  assert.match(elements.sentimentSummary.textContent, /net 2/);
  assert.match(elements.wordCloudSummary.innerHTML, /кот/);
  assert.match(elements.chartActivity.innerHTML, /BotA/);
});

test('loadAnalytics failure resets loading stubs in all sibling boxes', async () => {
  const { ctx, elements } = load(LOAD_ANALYTICS);
  ctx.apiReject = new Error('boom');
  await ctx.loadAnalytics();
  assert.match(elements.chartActivity.innerHTML, /status\.retry/, 'error card offers retry');
  assert.match(elements.sentimentSummary.innerHTML, /analytics\.empty/);
  assert.match(elements.wordCloudSummary.innerHTML, /analytics\.empty/);
  assert.match(elements.analyticsLogsContent.innerHTML, /logs\.empty_hint/);
  const combined = elements.chartActivity.innerHTML + elements.sentimentSummary.innerHTML
    + elements.wordCloudSummary.innerHTML + elements.analyticsLogsContent.innerHTML;
  assert.ok(!combined.includes('Загрузка'), 'no box keeps the eternal «Загрузка...»');
});

test('loadAnalyticsLogs: all filters propagate to the API and failure resets the box', async () => {
  const { ctx, elements } = load([['chat', 'loadAnalyticsLogs']]);
  ctx.$('analyticsBotFilter').value = 'a1';
  ctx.$('analyticsLevelFilter').value = 'warn';
  ctx.$('analyticsLogsFrom').value = '2026-09-01T12:30';
  ctx.$('analyticsLogsTo').value = '2026-09-02T12:30';
  ctx.apiReject = new Error('boom');
  await ctx.loadAnalyticsLogs();
  assert.deepEqual(ctx.apiCalls, ['/api/bot-logs?limit=200&account_id=a1&level=warn&from_time=2026-09-01%2012%3A30&to_time=2026-09-02%2012%3A30']);
  assert.match(elements.analyticsLogsContent.innerHTML, /logs\.empty_hint/, 'failed call still resets the loading stub');
});

test('loadHeatmap: empty grid renders the week frame, failure shows no_data', async () => {
  const success = load([['widgets', 'loadHeatmap']], { responses: [['/api/stats/heatmap', { grid: [] }]] });
  await success.ctx.loadHeatmap();
  assert.match(success.elements.heatmapGrid.innerHTML, /heatmap-row/, 'week frame rendered');
  assert.equal((success.elements.heatmapGrid.innerHTML.match(/heatmap-cell/g) || []).length, 168, '7×24 cells rendered');
  assert.ok(!success.elements.heatmapGrid.innerHTML.includes('Загрузка'), 'loading stub replaced');

  const failure = load([['widgets', 'loadHeatmap']]);
  failure.ctx.apiReject = new Error('boom');
  await failure.ctx.loadHeatmap();
  assert.match(failure.elements.heatmapGrid.innerHTML, /label\.no_data/);
  assert.ok(!failure.elements.heatmapGrid.innerHTML.includes('Загрузка'));
});

test('loadChat24h: empty data shows no_data, failure resets the chart', async () => {
  const success = load([['widgets', 'loadChat24h']], { responses: [['/api/stats/chat', {}]] });
  await success.ctx.loadChat24h();
  assert.match(success.elements.chartHour24.innerHTML, /label\.no_data/);
  assert.match(success.elements.topChattersList.innerHTML, /label\.no_data/);

  const failure = load([['widgets', 'loadChat24h']]);
  failure.ctx.apiReject = new Error('boom');
  await failure.ctx.loadChat24h();
  assert.match(failure.elements.chartHour24.innerHTML, /label\.no_data/);
  assert.ok(!failure.elements.chartHour24.innerHTML.includes('Загрузка'));
});

test('loadFeedbackSummary: empty stats show empty state, failure shows no_data, bots populate the select', async () => {
  const empty = load([['feedback', 'loadFeedbackSummary']], { responses: [['/api/ai-feedback/stats', {}]] });
  await empty.ctx.loadFeedbackSummary();
  assert.match(empty.elements.feedbackSummaryBox.innerHTML, /analytics\.empty/);

  const withBots = load([['feedback', 'loadFeedbackSummary']], { responses: [['/api/ai-feedback/stats', { total: 4, positive: 3, negative: 1 }]] });
  withBots.ctx._allBots = [{ id: 'a1', nickname: 'BotA' }];
  await withBots.ctx.loadFeedbackSummary();
  assert.match(withBots.elements.feedbackSummaryBox.innerHTML, /75% 👍/);
  assert.match(withBots.elements.feedbackBotFilter.innerHTML, /BotA/, 'bot filter is populated from _allBots');

  const failure = load([['feedback', 'loadFeedbackSummary']]);
  failure.ctx.apiReject = new Error('boom');
  await failure.ctx.loadFeedbackSummary();
  assert.match(failure.elements.feedbackSummaryBox.innerHTML, /label\.no_data/);
  assert.ok(!failure.elements.feedbackSummaryBox.innerHTML.includes('Загрузка'));
});
