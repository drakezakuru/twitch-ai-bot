// Q26: UI-тест вкладки «Модерация» в карточке канала.
//
// Проверяет: кнопка вкладки в карточке канала, модалка с очередью подтверждения
// («Забанить» / «Не наказывать»), журнал со статусами, список защищённых и кнопка
// «Разбанить»; i18n-ключи на трёх языках присутствуют; API-вызовы уходят на нужные
// эндпоинты. Движковая часть — tests/test_moderation_journal.py / _protected_list.py.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const read = file => fs.readFileSync(path.join(__dirname, '..', file), 'utf8');

function boot() {
  const nodes = {};
  const apiCalls = [];
  const toasts = [];
  const ctx = vm.createContext({
    console, URL, URLSearchParams,
    document: {
      getElementById: id => nodes[id] || null,
      createElement: () => ({ style: {}, classList: { add() {} }, dataset: {} }),
      querySelectorAll: () => [],
      addEventListener() {},
    },
    $: id => nodes[id] || null,
    esc: v => String(v ?? ''),
    t: (key, vars) => {
      let out = String(key);
      for (const [k, v] of Object.entries(vars || {})) out = out.replace(`{${k}}`, v);
      return out;
    },
    toast: (msg, kind) => toasts.push({ msg, kind }),
    api: async (url, opts) => {
      apiCalls.push({ url, opts });
      return { ok: true, entries: [], total: 0 };
    },
    showModal() {}, hideModal() {},
    jopts: (method, body) => ({ method, body }),
    _allBots: [],
  });
  ctx.window = ctx;
  vm.runInContext(read('static/app/19_channels_bulk.js'), ctx);
  return { ctx, nodes, apiCalls, toasts, run: code => vm.runInContext(code, ctx) };
}

test('карточка канала открывает вкладку «Модерация», бот-селектор наполняется', () => {
  const env = boot();
  vm.runInContext("_channelOverview = [{ channel: 'test_channel', bots: [{ account_id: 7, nickname: 'modbot' }] }]", env.ctx);
  env.nodes.channelModerationChannel = { textContent: '' };
  env.nodes.channelModerationBot = { value: '', innerHTML: '' };
  env.run(`openChannelModeration('test_channel')`);
  assert.match(env.nodes.channelModerationChannel.textContent, /test_channel/);
  assert.match(env.nodes.channelModerationBot.innerHTML, /value="7"/);
  assert.match(env.nodes.channelModerationBot.innerHTML, /modbot/);

  const src = read('static/app/19_channels_bulk.js');
  assert.match(src, /openChannelSettings\(this\.dataset\.channel\)/, 'карточка канала ведёт на единую страницу настроек (владелец 27.09)');
});

test('очередь подтверждения рендерится с кнопками «Забанить»/«Не наказывать»', async () => {
  const env = boot();
  env.nodes.channelModQueue = { innerHTML: '' };
  env.ctx.__pending = [{
    id: 42, username: 'friend', action: 'ban', duration_sec: null,
    rule_name: 'r1', detail: 'зритель защищён',
  }];
  // подменяем api на уровне контекста для этого вызова
  vm.runInContext(`
    api = async (url, opts) => {
      __calls.push({url, opts});
      return { ok: true, entries: __pending, total: 1 };
    };`, env.ctx);
  vm.runInContext('__calls = []', env.ctx);
  await env.run('loadChannelModQueue("channel=test_channel&account_id=7")');
  assert.match(env.nodes.channelModQueue.innerHTML, /friend/);
  assert.match(env.nodes.channelModQueue.innerHTML, /resolveChannelModCase\(42, true\)/, 'Забанить');
  assert.match(env.nodes.channelModQueue.innerHTML, /resolveChannelModCase\(42, false\)/, 'Не наказывать');
  assert.match(env.nodes.channelModQueue.innerHTML, /channels\.mod_action_ban/, 'бан навсегда без duration');
});

test('решение по случаю уходит в resolve-эндпоинт, журнал — в journal-эндпоинт', async () => {
  const env = boot();
  await env.run('resolveChannelModCase(42, false)');
  const resolve = env.apiCalls.find(c => c.url.includes('/api/moderation/journal/42/resolve'));
  assert.ok(resolve, 'resolve-вызов был');
  assert.equal(resolve.opts.body.approve, false);

  env.nodes.channelModJournal = { innerHTML: '' };
  await env.run('loadChannelModJournal("channel=test_channel")');
  const journal = env.apiCalls.find(c => c.url.startsWith('/api/moderation/journal?'));
  assert.ok(journal, 'журнал запрашивается');
});

test('журнал показывает статус записи', async () => {
  const env = boot();
  env.nodes.channelModJournal = { innerHTML: '' };
  vm.runInContext(`
    api = async (url, opts) => ({
      ok: true,
      entries: [{ id: 1, username: 'spammer', action: 'timeout', duration_sec: 3600,
                  status: 'applied', rule_name: 'r1', created_at: '2026-09-13T10:00:00' }],
    });`, env.ctx);
  await env.run('loadChannelModJournal("channel=test_channel")');
  assert.match(env.nodes.channelModJournal.innerHTML, /channels\.mod_status_applied/);
  assert.match(env.nodes.channelModJournal.innerHTML, /channels\.mod_action_timeout/);
});

test('владелец 27.09: у бана навсегда в журнале своя кнопка «Разбанить», у таймаута — нет', async () => {
  const env = boot();
  env.nodes.channelModJournal = { innerHTML: '' };
  vm.runInContext(`
    api = async (url, opts) => ({
      ok: true,
      entries: [
        { id: 1, username: 'permaban_target', action: 'ban', duration_sec: null,
          status: 'applied', rule_name: 'r1', created_at: '2026-09-13T10:00:00' },
        { id: 2, username: 'timeout_target', action: 'timeout', duration_sec: 3600,
          status: 'applied', rule_name: 'r1', created_at: '2026-09-13T10:00:00' },
        { id: 3, username: 'cancelled_ban', action: 'ban', duration_sec: null,
          status: 'cancelled', rule_name: 'r1', created_at: '2026-09-13T10:00:00' },
      ],
    });`, env.ctx);
  await env.run('loadChannelModJournal("channel=test_channel")');
  const html = env.nodes.channelModJournal.innerHTML;
  assert.match(html, /unbanChannelJournalEntry\('permaban_target'\)/, 'кнопка разбана у применённого перманентного бана');
  assert.doesNotMatch(html, /unbanChannelJournalEntry\('timeout_target'\)/, 'нет кнопки разбана у таймаута');
  assert.doesNotMatch(html, /unbanChannelJournalEntry\('cancelled_ban'\)/, 'нет кнопки разбана у отменённой записи');

  env.nodes.channelModerationBot = { value: '7' };
  vm.runInContext("_channelModChannel = 'test_channel'", env.ctx);
  vm.runInContext('__calls = []', env.ctx);
  vm.runInContext(`
    api = async (url, opts) => {
      __calls.push({url, opts});
      return { ok: true, already_unbanned: false };
    };`, env.ctx);
  await env.run(`unbanChannelJournalEntry('permaban_target')`);
  const unban = env.ctx.__calls.find(c => c.url.endsWith('/api/moderation/journal/unban'));
  assert.ok(unban, 'разбан ушёл в тот же unban-эндпоинт');
  assert.equal(unban.opts.body.username, 'permaban_target');
});

test('разбан вызывает официальный unban-эндпоинт и понимает «уже не забанен»', async () => {
  const env = boot();
  env.nodes.channelModerationBot = { value: '7' };
  env.nodes.channelModUnbanUser = { value: 'friend', };
  vm.runInContext("_channelModChannel = 'test_channel'", env.ctx);
  await env.run('unbanChannelViewer()');
  const unban = env.apiCalls.find(c => c.url.endsWith('/api/moderation/journal/unban'));
  assert.ok(unban, 'unban-вызов был');
  assert.equal(unban.opts.body.account_id, 7);
  assert.equal(unban.opts.body.channel, 'test_channel');
  assert.equal(unban.opts.body.username, 'friend');

  vm.runInContext(`
    api = async () => ({ ok: true, already_unbanned: true });`, env.ctx);
  env.nodes.channelModUnbanUser.value = 'friend';
  await env.run('unbanChannelViewer()');
  assert.match(env.toasts.at(-1).msg, /channels\.mod_unban_already/);
});

test('защищённые: список, добавление и удаление через API', async () => {
  const env = boot();
  vm.runInContext("_channelModChannel = 'test_channel'", env.ctx);
  env.nodes.channelModerationBot = { value: '7' };
  env.nodes.channelModProtected = { innerHTML: '' };
  await env.run('loadChannelModProtected("channel=test_channel&account_id=7")');
  const got = env.apiCalls.find(c => c.url.startsWith('/api/moderation/protected?'));
  assert.ok(got, 'список защищённых запрашивается');

  env.nodes.channelModProtectedUser = { value: 'friend' };
  env.nodes.channelModProtectedNote = { value: 'vip' };
  await env.run('addChannelProtected()');
  const add = env.apiCalls.find(c => c.url === '/api/moderation/protected' && c.opts.method === 'POST');
  assert.ok(add, 'добавление защищённого');
  assert.equal(add.opts.body.account_id, 7);
  assert.equal(add.opts.body.channel, 'test_channel');
  assert.equal(add.opts.body.username, 'friend');
  assert.equal(add.opts.body.note, 'vip');

  await env.run(`removeChannelProtected('friend')`);
  const del = env.apiCalls.find(c => c.url.startsWith('/api/moderation/protected/friend'));
  assert.ok(del && del.opts.method === 'DELETE', 'удаление защищённого');
});

test('вкладка «Модерация» на странице настроек канала содержит все секции (владелец 27.09: не модалка)', () => {
  const channels = read('templates/partials/channels.html');
  assert.match(channels, /id="channelSettingsTabModeration"/);
  assert.doesNotMatch(channels, /id="channelModerationModal"/, 'владелец 27.09: больше не всплывашка');
  for (const id of ['channelModQueue', 'channelModJournal', 'channelModProtected', 'channelModUnbanUser']) {
    assert.match(channels, new RegExp(`id="${id}"`), id);
  }
  assert.match(channels, /channels\.mod_queue_hint/);
  assert.match(channels, /channels\.mod_protected_hint/);
});

test('единая страница настроек канала (владелец 27.09, уточнение): 4 вкладки — боты/правила/модерация/профиль', () => {
  const channels = read('templates/partials/channels.html');
  assert.match(channels, /id="channelSettingsPage"/);
  for (const id of ['channelSettingsTabBots', 'channelSettingsTabRules', 'channelSettingsTabModeration', 'channelSettingsTabProfile']) {
    assert.match(channels, new RegExp(`id="${id}"`), id);
  }
  assert.match(channels, /id="channelSettingsBotsList"/);
  const bulk = read('static/app/19_channels_bulk.js');
  assert.match(bulk, /const CHANNEL_SETTINGS_TABS = \['bots', 'rules', 'moderation', 'profile'\]/);
  for (const fn of ['openChannelSettings', '_renderChannelSettingsBots', '_primeChannelBaseRules',
    '_primeChannelModeration', '_primeChannelProfile']) {
    assert.ok(new RegExp(`function ${fn}\\(`).test(bulk), `${fn} существует`);
  }
});

test('i18n-ключи вкладки есть во всех трёх языках', () => {
  const src = read('static/app.js');
  const keys = ['mod_tab', 'mod_queue', 'mod_queue_hint', 'mod_queue_ban', 'mod_queue_pardon',
    'mod_journal', 'mod_status_applied', 'mod_status_pending', 'mod_status_cancelled',
    'mod_status_expired', 'mod_protected', 'mod_unban_btn', 'mod_unban_already',
    'mod_action_ban', 'mod_action_timeout'];
  for (const key of keys) {
    const count = (src.match(new RegExp(`'channels\\.${key}':`, 'g')) || []).length;
    assert.equal(count, 3, `channels.${key} — ровно в ru/en/ua`);
  }
});

test('движковые сьюты Q26 на месте (журнал, статусы, 30 дней, разбан)', () => {
  const journal = read('tests/test_moderation_journal.py');
  assert.match(journal, /test_pending_case_expires_after_30_days/);
  assert.match(journal, /test_protected_ban_creates_pending_case_without_punishment/);
  const protectedList = read('tests/test_moderation_protected_list.py');
  assert.match(protectedList, /test_unban_route_uses_official_unban_and_reports_not_banned/);
});
