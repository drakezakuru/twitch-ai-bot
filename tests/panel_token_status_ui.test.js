const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const botsSource = fs.readFileSync('static/app/03_bots.js', 'utf8');
const settingsSource = fs.readFileSync('static/app/04_chat_settings.js', 'utf8');
const botsTemplate = fs.readFileSync('templates/partials/bots.html', 'utf8');
const settingsTemplate = fs.readFileSync('templates/partials/settings.html', 'utf8');
const i18nSource = fs.readFileSync('static/app.js', 'utf8');

function classList() {
  const values = new Set();
  return {
    toggle(name, force) {
      if (force === undefined ? !values.has(name) : force) values.add(name);
      else values.delete(name);
    },
    add(name) { values.add(name); },
    remove(name) { values.delete(name); },
    contains(name) { return values.has(name); },
  };
}

function element(id) {
  return { id, value: '', innerHTML: '', disabled: false, classList: classList() };
}

function createContext() {
  const ids = ['botsList', 'botsBulkBar', 'manualToken', 'manualHint'];
  const elements = Object.fromEntries(ids.map(id => [id, element(id)]));
  const requests = [];
  const toasts = [];
  const translations = {
    'token.status.valid': 'Token is active',
    'token.status.expiring': 'Token is expiring',
    'token.status.expired': 'Token has expired',
    'token.status.not_refreshable': 'Not renewable',
    'token.status.unknown': 'Token status unknown',
    'token.refresh': 'Refresh token',
    'token.refresh_done': 'Token refreshed',
    'label.no_channels': 'no channels',
    'bots.lurkers': 'Lurkers',
    'bots.no_lurkers': 'No lurkers',
    'label.connected': 'Connected',
    'label.disconnected': 'Disconnected',
  };
  const context = {
    console,
    localStorage: { getItem: () => null, setItem: () => {} },
    document: { querySelectorAll: () => [] },
    $: id => elements[id] || null,
    esc: value => String(value),
    t: key => translations[key] || key,
    toast: (message, kind) => toasts.push({ message, kind }),
    api: async (url, options) => {
      requests.push({ url, options });
      if (url === '/api/accounts') return [{ id: 7, nickname: 'bot', bot_role: 'chatter', has_refresh_token: true }];
      if (url === '/api/token-status/accounts') return { statuses: { 7: 'expiring' } };
      if (url.includes('/refresh-token')) return { ok: true };
      if (url === '/api/stats/all') return [];
      return {};
    },
    botDisplayChannels: () => [],
    botStatusBadge: () => '',
    botHealthLine: () => '',
    roleBadgeHtml: () => '',
    countLabel: count => String(count),
  };
  vm.createContext(context);
  vm.runInContext('var _botStatuses = {}; var _botStats = {}; var _allBots = [];', context);
  vm.runInContext(botsSource, context);
  return { context, elements, requests, toasts };
}

test('bot cards show token status and refresh only refreshable accounts', () => {
  const { context, elements } = createContext();
  vm.runInContext(`
    _botTokenStatuses = { 1: 'valid', 2: 'expiring', 3: 'expired', 4: 'not_refreshable', 5: 'unknown' };
    renderBotsList([
      { id: 1, nickname: 'valid', bot_role: 'chatter', has_refresh_token: true },
      { id: 2, nickname: 'expiring', bot_role: 'chatter', has_refresh_token: true },
      { id: 3, nickname: 'expired', bot_role: 'chatter', has_refresh_token: false },
      { id: 4, nickname: 'manual', bot_role: 'chatter', has_refresh_token: false },
      { id: 5, nickname: 'unknown', bot_role: 'chatter', has_refresh_token: false },
    ]);
  `, context);

  const html = elements.botsList.innerHTML;
  for (const label of ['Token is active', 'Token is expiring', 'Token has expired', 'Not renewable', 'Token status unknown']) {
    assert.match(html, new RegExp(label));
  }
  assert.equal((html.match(/refreshBotToken\(/g) || []).length, 2);
});

test('manual token explanation appears softly without blocking input', () => {
  const { context, elements } = createContext();
  elements.manualToken.value = 'oauth:manual';
  vm.runInContext("updateManualTokenHint('manualToken', 'manualHint')", context);
  assert.equal(elements.manualHint.classList.contains('hidden'), false);

  elements.manualToken.value = '';
  vm.runInContext("updateManualTokenHint('manualToken', 'manualHint')", context);
  assert.equal(elements.manualHint.classList.contains('hidden'), true);
});

test('manual refresh calls the existing endpoint and reloads statuses', async () => {
  const { context, requests, toasts } = createContext();
  const button = element('refresh');

  await context.refreshBotToken(7, button);

  assert.ok(requests.some(item => item.url === '/api/accounts/7/refresh-token' && item.options.method === 'POST'));
  assert.ok(requests.some(item => item.url === '/api/token-status/accounts'));
  assert.deepEqual(toasts[0], { message: 'Token refreshed', kind: 'success' });
  assert.equal(button.disabled, false);
});

test('token settings and all user-facing strings are wired for three languages', () => {
  assert.match(settingsSource, /api\/settings\/auto-refresh/);
  assert.match(settingsSource, /warning_days/);
  assert.match(settingsTemplate, /id="autoRefreshTokens"/);
  assert.match(settingsTemplate, /id="tokenExpiryWarningDays"[^>]*min="1"[^>]*max="90"/);
  assert.match(botsTemplate, /id="newBotTokenManualHint"/);
  assert.match(botsTemplate, /id="botTokenManualHint"/);

  for (const key of [
    'token.status.valid', 'token.status.expiring', 'token.status.expired',
    'token.status.not_refreshable', 'token.status.unknown', 'token.manual_hint',
    'token.auto_refresh', 'token.warning_days',
  ]) {
    assert.equal((i18nSource.match(new RegExp(`'${key.replaceAll('.', '\\.')}'`, 'g')) || []).length, 3, key);
  }
});
