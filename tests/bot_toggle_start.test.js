// Owner report 27.09.2026: кнопка «Старт»/«Стоп» на карточке бота дёргала
// `toggle` + `/start` одним кликом. Toggle сам поднимал бота → второй `/start`
// отвечал «Уже запущен» → тост «Ошибка», а флаг accounts.enabled расходился с
// живым ботом («Бот выключен» в чате). Теперь один эндпоинт на действие, а
// решение старт/стоп принимается по живому статусу, а не по устаревшему кэшу.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const BOTS_JS = fs.readFileSync(path.join(__dirname, '..', 'static/app/03_bots.js'), 'utf8');

function _slice(source, start, end) {
  const from = source.indexOf(start);
  const to = source.indexOf(end, from);
  return to > from ? source.slice(from, to) : source.slice(from);
}

function makeContext({ status, enabled }) {
  const calls = [];
  const context = {
    console,
    _allBots: [{ id: 1, nickname: 'bot', enabled }],
    _botStatuses: {},
    _busyBots: new Set(),
    api: async (url) => {
      calls.push(url);
      if (url === '/api/bots/status') return { 1: status };
      return { ok: true };
    },
    toast: () => {},
    t: key => key,
    loadBotsList: async () => calls.push('reload'),
  };
  vm.createContext(context);
  vm.runInContext(_slice(BOTS_JS, 'async function quickToggleBot', 'async function toggleBot'), context);
  return { context, calls };
}

test('start click calls only /start and never /toggle', async () => {
  const { context, calls } = makeContext({ status: { connected: false }, enabled: false });
  await vm.runInContext('quickToggleBot(1)', context);
  assert.ok(calls.includes('/api/accounts/1/start'));
  assert.ok(!calls.some(url => url.includes('/toggle')));
});

test('stop click calls only /stop and never /toggle', async () => {
  const { context, calls } = makeContext({ status: { connected: true }, enabled: true });
  await vm.runInContext('quickToggleBot(1)', context);
  assert.ok(calls.includes('/api/accounts/1/stop'));
  assert.ok(!calls.some(url => url.includes('/toggle')));
});

test('a stale flag does not turn "start" into "stop" (live status wins)', async () => {
  // Флаг enabled=1, но бот уже подключён и в кэше статуса пусто —
  // раньше выбор ветки опирался только на кэш (_botStatuses пустой).
  const { context, calls } = makeContext({ status: { connected: true }, enabled: true });
  await vm.runInContext('quickToggleBot(1)', context);
  assert.ok(calls.includes('/api/accounts/1/stop'));
  assert.ok(calls.includes('/api/bots/status'), 'живой статус запрашивается перед решением');
});

test('bulk start/stop no longer pair /toggle with the state endpoints', () => {
  const bulkStart = _slice(BOTS_JS, 'async function bulkStartBots', 'async function bulkStopBots');
  const bulkStop = _slice(BOTS_JS, 'async function bulkStopBots', '// ── Bot connectivity check');
  const reconnect = _slice(BOTS_JS, 'async function reconnectBot', 'function selectBotCard');
  for (const [name, code] of [['bulkStart', bulkStart], ['bulkStop', bulkStop], ['reconnect', reconnect]]) {
    assert.doesNotMatch(code, /accounts\/\$\{id\}\/toggle/, name);
  }
});
