// Q08(а): один список ботов + фильтры по роли и каналу, состояние в localStorage.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('static/app/03_bots.js', 'utf8');
const TEMPLATE = fs.readFileSync('templates/partials/bots.html', 'utf8');

function classList() {
  const values = new Set();
  return {
    toggle(name, force) { if (force === undefined ? !values.has(name) : force) values.add(name); else values.delete(name); },
    add(name) { values.add(name); },
    remove(name) { values.delete(name); },
    contains(name) { return values.has(name); },
  };
}

function element(id) {
  return { id, innerHTML: '', value: '', options: [], classList: classList(), children: [] };
}

function createContext() {
  const ids = ['botsList', 'botsBulkBar', 'botsSearch', 'botsStatusFilter', 'botsSort',
    'botsRoleFilter', 'botsChannelFilter', 'botQuickBehaviorCard', 'roleConfigBox'];
  const elements = Object.fromEntries(ids.map(id => [id, element(id)]));
  const store = new Map();
  const context = {
    console,
    localStorage: {
      getItem: key => (store.has(key) ? store.get(key) : null),
      setItem: (key, value) => store.set(key, String(value)),
    },
    document: { querySelectorAll: () => [] },
    $: id => elements[id] || null,
    api: async () => ({}),
    esc: value => String(value),
    t: key => key,
    _roleMetaLabel: role => `label:${role}`,
    botDisplayChannels: (bot) => bot.channels || [],
    botStatusBadge: () => '',
    botHealthLine: () => '',
    roleBadgeHtml: bot => `<b>${bot.bot_role}</b>`,
    countLabel: count => String(count),
  };
  vm.createContext(context);
  vm.runInContext('var _botStatuses = {}; var _botStats = {}; var _allBots = [];', context);
  vm.runInContext(source, context);
  return { context, elements, store };
}

test('bots header has role and channel filter selects', () => {
  assert.match(TEMPLATE, /id="botsRoleFilter"/);
  assert.match(TEMPLATE, /id="botsChannelFilter"/);
  assert.match(TEMPLATE, /onchange="filterBots\(\)"/);
});

test('filters sync builds role options and channel options from bots', () => {
  const { context, elements } = createContext();
  vm.runInContext(`
    _allBots = [
      { id: 1, nickname: 'a', bot_role: 'chatter', channels: ['test_channel'] },
      { id: 2, nickname: 'b', bot_role: 'lurker', channels: ['other', 'test_channel'] },
    ];
    botsFiltersSync();
  `, context);
  assert.match(elements.botsRoleFilter.innerHTML, /label:chatter/);
  assert.match(elements.botsRoleFilter.innerHTML, /label:lurker/);
  assert.match(elements.botsRoleFilter.innerHTML, /label:moderator/);
  assert.match(elements.botsRoleFilter.innerHTML, /label:director/);
  assert.match(elements.botsChannelFilter.innerHTML, /#test_channel/);
  assert.match(elements.botsChannelFilter.innerHTML, /#other/);
});

test('filterBots applies role and channel filters and persists them', () => {
  const { context, elements, store } = createContext();
  vm.runInContext(`
    _allBots = [
      { id: 1, nickname: 'mod-bot', bot_role: 'moderator', channels: ['test_channel'] },
      { id: 2, nickname: 'chat-bot', bot_role: 'chatter', channels: ['test_channel'] },
      { id: 3, nickname: 'chat-other', bot_role: 'chatter', channels: ['elsewhere'] },
    ];
    elements_placeholder();
  `.replace('elements_placeholder();', ''), context);
  elements.botsSearch.value = '';
  elements.botsStatusFilter.value = '';
  elements.botsSort.value = 'name';
  elements.botsRoleFilter.value = 'moderator';
  elements.botsChannelFilter.value = 'test_channel';
  vm.runInContext('filterBots();', context);
  const html = elements.botsList.innerHTML;
  assert.match(html, /mod-bot/);
  assert.doesNotMatch(html, /chat-bot/);
  assert.doesNotMatch(html, /chat-other/);
  assert.equal(store.get('botsRoleFilter'), 'moderator');
  assert.equal(store.get('botsChannelFilter'), 'test_channel');
});

test('saved filters are restored into the selects', () => {
  const { context, elements, store } = createContext();
  store.set('botsRoleFilter', 'lurker');
  store.set('botsChannelFilter', 'test_channel');
  vm.runInContext(`
    _allBots = [{ id: 1, nickname: 'a', bot_role: 'lurker', channels: ['test_channel'] }];
    botsFiltersSync();
  `, context);
  assert.equal(elements.botsRoleFilter.value, 'lurker');
  assert.equal(elements.botsChannelFilter.value, 'test_channel');
});

test('saved channel filter that no longer exists falls back to all channels', () => {
  const { context, elements, store } = createContext();
  store.set('botsChannelFilter', 'deleted-channel');
  vm.runInContext(`
    _allBots = [{ id: 1, nickname: 'a', bot_role: 'chatter', channels: ['test_channel'] }];
    botsFiltersSync();
  `, context);
  assert.equal(elements.botsChannelFilter.value, '');
});

// Q08(б): группировка по ролям с «выбрать всех» в диалоге добавления ботов.
const BULK = fs.readFileSync('static/app/19_channels_bulk.js', 'utf8');
const APPJS = fs.readFileSync('static/app.js', 'utf8');

test('bulk add dialog groups bots by role with a select-all button', () => {
  assert.match(BULK, /function _bulkBotChoicesHtml\(\)/);
  assert.match(BULK, /data-bulk-role="\$\{role\}"/);
  assert.match(BULK, /onclick="bulkToggleRole\('\$\{role\}', this\)"/);
  assert.match(BULK, /_BULK_ROLE_ORDER/);
  assert.match(APPJS, /'bulk\.select_all'/g);
});

test('bulkToggleRole flips only its own role group', () => {
  const checked = [];
  const boxes = [
    { role: 'moderator', checked: false },
    { role: 'moderator', checked: true },
    { role: 'chatter', checked: false },
  ];
  const context = {
    document: {
      querySelectorAll: selector => {
        const role = selector.match(/data-bulk-role="([^"]+)"/)?.[1];
        return boxes.filter(box => box.role === role);
      },
    },
    t: key => key,
  };
  vm.createContext(context);
  vm.runInContext(BULK.slice(BULK.indexOf('function bulkToggleRole')), context);
  vm.runInContext(`bulkToggleRole('moderator');`, context);
  // Ни у кого в группе не было полного выбора → все включаются, чаттеры не тронуты.
  assert.deepEqual(boxes.map(box => box.checked), [true, true, false]);
});
