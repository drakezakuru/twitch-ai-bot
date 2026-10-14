// Q23: сводка расклада вверху «Обзора» — боты, роли, каналы, живые подключения.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const read = file => fs.readFileSync(path.join(__dirname, '..', file), 'utf8');

const DASH = read('templates/partials/dashboard.html');
const DASH_JS = read('static/app/02_dashboard.js');
const APPJS = read('static/app.js');

test('summary block sits above the KPI cards and is aria-live', () => {
  const beforeKpi = DASH.indexOf('id="dashboardOverviewSummary"') < DASH.indexOf('id="dashboardKPI"');
  assert.ok(beforeKpi, 'summary renders before KPI');
  assert.match(DASH, /id="dashboardOverviewSummary" aria-live="polite"/);
});

test('renderDashboardSummary is wired into load and live updates', () => {
  assert.match(DASH_JS, /function renderDashboardSummary\(\)/);
  assert.match(DASH_JS, /renderDashboardBots\(\);\s*\n\s*renderDashboardSummary\(\);/);
  assert.match(DASH_JS, /function renderDashboardBots\(\) \{\s*const el = \$\('dashboardBots'\);\s*if \(!el\) return;\s*renderDashboardSummary\(\);/);
});

test('summary renders channel-centric mini table with roles and statuses', () => {
  const el = { innerHTML: '' };
  const context = {
    console,
    $: id => id === 'dashboardOverviewSummary' ? el : null,
    t: (key, params) => key + (params ? `:${JSON.stringify(params)}` : ''),
    esc: v => String(v),
    _roleMetaLabel: role => `label:${role}`,
    botDisplayChannels: (bot, st) => st.channels || [],
    _allBots: [
      { id: 1, nickname: 'alpha', bot_role: 'moderator' },
      { id: 2, nickname: 'beta', bot_role: 'chatter' },
    ],
    _botStatuses: { 1: { connected: true, channels: ['test_channel'] }, 2: { connected: false, channels: ['test_channel', 'other'] } },
  };
  vm.createContext(context);
  vm.runInContext(DASH_JS.slice(DASH_JS.indexOf('function renderDashboardSummary')), context);
  vm.runInContext('renderDashboardSummary();', context);
  const html = el.innerHTML;
  assert.match(html, /panel\.summary\.title/);
  assert.match(html, /label:moderator/);
  assert.match(html, /#test_channel/);
  assert.match(html, /#other/);
  assert.match(html, /🟢 alpha/);
  assert.match(html, /⚫ beta/);
  // Каналы отсортированы по алфавиту: other раньше test_channel.
  assert.ok(html.indexOf('other') < html.indexOf('test_channel'));
});

test('empty bot list shows empty state', () => {
  const el = { innerHTML: '' };
  const context = {
    console, $: () => el, t: k => k, esc: v => String(v), _roleMetaLabel: r => r,
    botDisplayChannels: () => [], _allBots: [], _botStatuses: {},
  };
  vm.createContext(context);
  vm.runInContext(DASH_JS.slice(DASH_JS.indexOf('function renderDashboardSummary')), context);
  vm.runInContext('renderDashboardSummary();', context);
  assert.match(el.innerHTML, /empty-state/);
});

test('i18n: RU/EN/UA for summary keys', () => {
  for (const key of ['panel.summary.title', 'panel.summary.online', 'panel.summary.channel', 'panel.summary.bots', 'panel.summary.connected']) {
    assert.equal(APPJS.split(`'${key}':`).length - 1, 3, key);
  }
});
