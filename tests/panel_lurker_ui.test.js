const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync('static/app/03_bots.js', 'utf8');

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
  return {
    id,
    innerHTML: '',
    children: [],
    classList: classList(),
    appendChild(child) { this.children.push(child); child.parent = this; },
  };
}

function createContext() {
  const ids = [
    'botsList', 'botsBulkBar', 'botQuickBehaviorCard', 'roleConfigBox',
    'roleSlotOverview', 'roleSlotChatter', 'roleSlotModeration', 'roleSlotVoice', 'roleSlotLurker',
  ];
  const elements = Object.fromEntries(ids.map(id => [id, element(id)]));
  const groupButtons = ['overview', 'brain-x', 'identity', 'flow', 'moderation', 'memory', 'voice', 'advanced']
    .map(group => ({ dataset: { botGroup: group }, classList: classList() }));
  const context = {
    console,
    localStorage: { getItem: () => null, setItem: () => {} },
    document: { querySelectorAll: selector => selector === '[data-bot-group]' ? groupButtons : [] },
    $: id => elements[id] || null,
    api: async () => ({}),
    esc: value => String(value),
    t: key => ({
      'bots.lurkers': 'Lurkers',
      'bots.no_lurkers': 'No lurkers',
      'label.connected': '🟢 Connected',
      'label.disconnected': '🔴 Disconnected',
    }[key] || key),
    botDisplayChannels: () => [],
    botStatusBadge: () => '',
    botHealthLine: () => '',
    roleBadgeHtml: bot => `<b>${bot.bot_role}</b>`,
    countLabel: count => String(count),
  };
  vm.createContext(context);
  vm.runInContext('var _botStatuses = {}; var _botStats = {}; var _allBots = [];', context);
  vm.runInContext(source, context);
  return { context, elements, groupButtons };
}

test('bots render as one list without a forced lurkers section (DEC-OWNER-010, Q08)', () => {
  const { context, elements } = createContext();
  vm.runInContext(`
    _botStatuses = { 1: { connected: false }, 2: { connected: true } };
    renderBotsList([
      { id: 1, nickname: 'lurker-offline', bot_role: 'lurker' },
      { id: 2, nickname: 'chatter', bot_role: 'chatter' },
    ]);
  `, context);
  const html = elements.botsList.innerHTML;
  // Принудительная секция «Луркеры» удалена — один список, порядок как на входе.
  assert.doesNotMatch(html, /bot-role-section/);
  assert.doesNotMatch(html, /<details/);
  assert.ok(html.indexOf('lurker-offline') < html.indexOf('chatter'));
});

test('empty list shows the empty state without any section', () => {
  const { context, elements } = createContext();
  vm.runInContext('renderBotsList([]);', context);
  const html = elements.botsList.innerHTML;
  assert.match(html, /empty-state/);
  assert.doesNotMatch(html, /bot-role-section/);
});

test('lurker keeps mention settings visible and hides unrelated settings', () => {
  const { context, elements, groupButtons } = createContext();
  vm.runInContext("applyBotRoleVisibility('lurker'); relocateRoleConfig('lurker');", context);

  assert.equal(elements.botQuickBehaviorCard.classList.contains('hidden'), true);
  for (const group of ['brain-x', 'identity', 'moderation', 'memory', 'voice', 'advanced']) {
    const button = groupButtons.find(item => item.dataset.botGroup === group);
    assert.equal(button.classList.contains('hidden'), true, `${group} should be hidden`);
  }
  assert.equal(elements.roleConfigBox.classList.contains('hidden'), false);
  assert.equal(elements.roleSlotOverview.children[0], elements.roleConfigBox);
});

test('quick cards omit observation-mode toggle and Director exposes only its panel', () => {
  const { context, elements } = createContext();
  vm.runInContext(`
    renderBotsList([
      { id: 1, nickname: 'chat-bot', bot_role: 'chatter' },
      { id: 2, nickname: 'director', bot_role: 'director' },
    ]);
  `, context);
  const html = elements.botsList.innerHTML;
  assert.doesNotMatch(html, /toggleObservationOnly/);
  const directorCard = html.slice(html.indexOf('data-bot-card="2"'));
  assert.match(directorCard, /openDirectorPanel/);
  assert.doesNotMatch(directorCard, /quickToggleBot|openBotSettings|showLastObservation/);
});
