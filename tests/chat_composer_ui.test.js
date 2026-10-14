// Q20: композер чата — бот и канал у кнопки «Отправить»; селектор канала
// с поиском и группировкой по ботам.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const read = file => fs.readFileSync(path.join(__dirname, '..', file), 'utf8');

const CHAT_HTML = read('templates/partials/chat.html');
const CHAT_JS = read('static/app/04_chat_settings.js');
const APP_JS = read('static/app.js');

function _slice(source, start, end) {
  const from = source.indexOf(start);
  const to = end ? source.indexOf(end, from) : -1;
  return to > from ? source.slice(from, to) : source.slice(from);
}

// Файл 04_chat_settings.js содержит прежние top-level document.addEventListener
// (например, botFeedbackMenu) — в vm-контексте даём минимальные стабы браузера.
function browserStubs() {
  return {
    document: { addEventListener() {}, getElementById: () => null, querySelector: () => null },
    window: { innerWidth: 1280, innerHeight: 800 },
    Element: class Element {},
    api: async () => ({}),
    jopts: () => ({}),
    toast: () => {},
    showModal: () => {},
    hideModal: () => {},
  };
}

test('composer holds bot, channel picker, input and send button in one row', () => {
  const composer = CHAT_HTML.slice(CHAT_HTML.indexOf('chat-composer'), CHAT_HTML.indexOf('Live chat'));
  const ids = ['chatBot', 'chatChannelPicker', 'chatChannelPick', 'chatChannelSearch',
    'chatChannelPanelList', 'chatChannel', 'chatMessage', 'chatSendButton'];
  for (const id of ids) assert.ok(composer.includes(`id="${id}"`), id);
  // Селекторы больше не в шапке — они у кнопки «Отправить».
  const header = CHAT_HTML.slice(0, CHAT_HTML.indexOf('chat-composer'));
  assert.doesNotMatch(header, /id="chatBot"/);
  assert.doesNotMatch(header, /id="chatChannel"/);
});

test('picker has search input and grouped bot rendering', () => {
  assert.match(CHAT_JS, /function _chatPickerGroups\(\)/);
  assert.match(CHAT_JS, /function renderChatChannelPanel\(\)/);
  assert.match(CHAT_JS, /function pickChatChannel\(botId, channel\)/);
  assert.match(CHAT_JS, /function toggleChatChannelPanel\(\)/);
  // Состояние канала — hidden #chatChannel; вся прежняя логика читает .value.
  assert.match(CHAT_JS, /\$\('chatChannel'\)\?\.value/);
});

test('pickChatChannel sets bot and channel, syncs composer and reloads the view', () => {
  const calls = [];
  const elements = {
    chatBot: { value: '' },
    chatChannel: { value: '' },
    chatChannelPanel: { classList: { add() {} } },
    chatChannelPick: { setAttribute() {}, textContent: '' },
  };
  const context = {
    console,
    ...browserStubs(),
    $: id => elements[id] || null,
    t: key => key,
    esc: value => String(value),
    syncChatComposer: () => calls.push('sync'),
    loadRecentChat: () => calls.push('reload'),
    updateChatChannelPick: () => calls.push('label'),
    closeChatChannelPanel: () => calls.push('close'),
  };
  vm.createContext(context);
  vm.runInContext(_slice(CHAT_JS, 'function pickChatChannel', '// Закрытие пикера по клику мимо'), context);
  vm.runInContext(`pickChatChannel(3, '#test_channel');`, context);
  assert.equal(elements.chatBot.value, '3');
  assert.equal(elements.chatChannel.value, 'test_channel');
  assert.deepEqual(calls, ['close', 'label', 'sync', 'reload']);
});

test('panel groups bots and filters by search', () => {
  const elements = {
    chatChannelSearch: { value: 'test_channel' },
    chatChannelPanelList: { innerHTML: '' },
    chatBot: { value: '1' },
    chatChannel: { value: '' },
  };
  const context = {
    console,
    ...browserStubs(),
    $: id => elements[id] || null,
    t: key => key,
    esc: value => String(value),
    _allBots: [
      { id: 1, nickname: 'alpha', channels: [{ channel_name: 'test_channel', enabled: 1 }] },
      { id: 2, nickname: 'beta', channels: [{ channel_name: 'other', enabled: 1 }] },
      { id: 3, nickname: 'gamma', channels: [{ channel_name: 'off', enabled: 0 }] },
    ],
  };
  vm.createContext(context);
  vm.runInContext(_slice(CHAT_JS, 'function _chatPickerGroups', 'function pickChatChannel(botId'), context);
  vm.runInContext('renderChatChannelPanel();', context);
  assert.match(elements.chatChannelPanelList.innerHTML, /alpha/);
  assert.match(elements.chatChannelPanelList.innerHTML, /test_channel/);
  assert.doesNotMatch(elements.chatChannelPanelList.innerHTML, /beta|other|gamma/);
});

test('picker accepts persisted channels returned by the accounts endpoint', () => {
  const context = {
    ...browserStubs(),
    _allBots: [{ id: 1, nickname: 'alpha', channels: [], persisted_channels: ['test_channel'] }],
  };
  vm.createContext(context);
  vm.runInContext(_slice(CHAT_JS, 'function _chatPickerGroups', 'function toggleChatChannelPanel'), context);
  const groups = JSON.parse(JSON.stringify(vm.runInContext('_chatPickerGroups()', context)));
  assert.deepEqual(groups, [{
    bot: { id: 1, nickname: 'alpha', channels: [], persisted_channels: ['test_channel'] },
    channels: ['test_channel'],
  }]);
});

test('sendChatMessage shows an unconfirmed hint when Twitch delivery is not confirmed', async () => {
  const toasts = [];
  const elements = {
    chatMessage: { value: 'hi there' },
    chatBot: { value: '1' },
    chatChannel: { value: 'test_channel' },
  };
  const context = {
    ...browserStubs(),
    $: id => elements[id] || null,
    t: key => key,
    api: async () => ({ ok: true, confirmed: false }),
    appendLiveChat: () => {},
    sendReasonText: () => 'err',
    toast: (msg) => toasts.push(msg),
  };
  vm.createContext(context);
  vm.runInContext(_slice(CHAT_JS, 'async function sendChatMessage', 'function clearLiveChat'), context);
  await vm.runInContext('sendChatMessage()', context);
  assert.ok(toasts.includes('send.unconfirmed_hint'));
});

test('renderChatChannelPanel offers manual channel entry and pickChatChannelManual applies it', () => {
  const calls = [];
  const elements = {
    chatChannelSearch: { value: '' },
    chatChannelPanelList: { innerHTML: '' },
    chatBot: { value: '1' },
    chatChannel: { value: '' },
    chatChannelManual: { value: '  newchannel  ' },
  };
  const context = {
    ...browserStubs(),
    $: id => elements[id] || null,
    t: key => key,
    esc: value => String(value),
    _allBots: [{ id: 1, nickname: 'alpha', channels: [] }],
    pickChatChannel: (botId, channel) => calls.push([botId, channel]),
  };
  vm.createContext(context);
  vm.runInContext(_slice(CHAT_JS, 'function _chatPickerGroups', 'function pickChatChannel(botId'), context);
  vm.runInContext('renderChatChannelPanel();', context);
  assert.match(elements.chatChannelPanelList.innerHTML, /id="chatChannelManual"/);
  assert.match(elements.chatChannelPanelList.innerHTML, /chat\.pick_manual_use/);
  vm.runInContext('pickChatChannelManual();', context);
  assert.deepEqual(calls, [['1', 'newchannel']]);
});

test('i18n: RU/EN/UA for picker strings', () => {
  for (const key of ['chat.pick_search', 'chat.pick_empty']) {
    assert.equal(APP_JS.split(`'${key}':`).length - 1, 3, key);
  }
});

test('i18n: RU/EN/UA for the unconfirmed-send hint', () => {
  const TAIL_JS = read('static/app/16_tail.js');
  assert.equal(TAIL_JS.split("'send.unconfirmed_hint':").length - 1, 3);
});

test('i18n: RU/EN/UA for manual channel entry', () => {
  for (const key of ['chat.pick_manual_label', 'chat.pick_manual_ph', 'chat.pick_manual_use']) {
    assert.equal(APP_JS.split(`'${key}':`).length - 1, 3, key);
  }
});

// Owner report 27.09.2026: список каналов перекрывался карточкой «Живой чат»
// (у .card есть backdrop-filter → свой stacking context, z-index панели не работал).
// Проверяем, что карточка композера поднимается на время открытого списка.
test('opening the channel picker raises the composer card above other cards', () => {
  const CSS = read('static/app.css');
  assert.match(CHAT_HTML, /class="card mb-4 chat-composer-card"/);
  assert.match(CSS, /\.chat-composer-card\s*\{[^}]*position:\s*relative/);
  assert.match(CSS, /\.chat-composer-card\.chat-picker-open\s*\{\s*z-index:\s*\d+/);

  const cardClasses = new Set();
  const panel = { classList: { contains: () => true, toggle() {}, add() {} } };
  const card = {
    classList: {
      toggle: (name, on) => (on ? cardClasses.add(name) : cardClasses.delete(name)),
      remove: name => cardClasses.delete(name),
    },
  };
  const picker = { closest: sel => (sel === '.card' ? card : null), setAttribute() {}, classList: { remove() {} } };
  const context = {
    ...browserStubs(),
    $: id => ({ chatChannelPanel: panel, chatChannelPicker: picker }[id] || null),
    t: key => key,
    renderChatChannelPanel: () => {},
  };
  vm.createContext(context);
  vm.runInContext(_slice(CHAT_JS, 'function toggleChatChannelPanel', 'function renderChatChannelPanel'), context);
  vm.runInContext('toggleChatChannelPanel();', context);
  assert.ok(cardClasses.has('chat-picker-open'));
  vm.runInContext('closeChatChannelPanel();', context);
  assert.ok(!cardClasses.has('chat-picker-open'));
});
