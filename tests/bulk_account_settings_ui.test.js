// Q39: массовые настройки — модалка «применить одно значение сразу ко всем выбранным ботам».
const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function classes() {
  const values = new Set();
  return { add: x => values.add(x), remove: x => values.delete(x), contains: x => values.has(x),
    toggle(x, on) { on ??= !values.has(x); on ? values.add(x) : values.delete(x); } };
}
function element(id) {
  return { id, value: '', innerHTML: '', textContent: '', disabled: false, classList: classes(),
    appendChild() {}, addEventListener() {}, style: {} };
}
function harness() {
  const nodes = new Map();
  const calls = [];
  const dialogs = [];
  const context = vm.createContext({
    console,
    $: id => { if (!nodes.has(id)) nodes.set(id, element(id)); return nodes.get(id); },
    document: {
      createElement: () => element('overlay'),
      getElementById: id => nodes.get(id) || null,
      body: { appendChild() {} },
      querySelectorAll: () => [],
    },
    esc: v => String(v ?? ''), t: (k, params) => (params ? `${k}(${JSON.stringify(params)})` : k),
    toast() {}, jopts: (m, b) => ({ method: m, body: JSON.stringify(b) }),
    _roleMetaLabel: role => `role:${role}`,
    localStorage: { getItem: () => null, setItem() {} },
    openPanelDialog: (el, opts) => dialogs.push({ el, opts }),
    closePanelDialog: id => dialogs.push({ closed: id }),
    loadBotsList: async () => { calls.push('loadBotsList'); },
    api: async (url, opts) => { calls.push([url, opts]); return { ok: true, updated: 1, total: 1, results: [] }; },
  });
  vm.runInContext(fs.readFileSync('static/app/03_bots.js', 'utf8'), context);
  return { context, nodes, calls, dialogs, run: code => vm.runInContext(code, context) };
}

test('Q39: opening bulk settings does nothing without a selection and builds the default control otherwise', () => {
  const h = harness();
  h.context.openBulkAccountSettings();
  assert.equal(h.dialogs.length, 0, 'без выбранных ботов модалка не открывается');
  h.run('_selectedBots.add(1); _selectedBots.add(2);');
  h.context.openBulkAccountSettings();
  assert.equal(h.dialogs.length, 1);
});

test('Q39: switching the field to bot_role rebuilds the value control with role options', () => {
  const h = harness();
  h.run('_selectedBots.add(1);');
  h.context.openBulkAccountSettings();
  h.context.$('bulkSettingsField').value = 'bot_role';
  h.context.bulkSettingsFieldChanged();
  const html = h.nodes.get('bulkSettingsValueHolder').innerHTML;
  assert.match(html, /id="bulkSettingsValue"/);
  assert.match(html, /value="lurker"/);
  assert.doesNotMatch(html, /role:director/); // Q35/Q40b: director не переключают массово через это поле
});

test('Q39: apply posts the chosen field/value for exactly the selected ids and refreshes the bots list', async () => {
  const h = harness();
  h.run('_selectedBots.add(1); _selectedBots.add(2);');
  h.context.openBulkAccountSettings();
  h.context.$('bulkSettingsField').value = 'eventsub_enabled';
  h.context.$('bulkSettingsValue').value = 'false';
  h.context.api = async (url, opts) => {
    if (url === '/api/bulk/account-settings') {
      h.calls.push([url, JSON.parse(opts.body)]);
      return { ok: true, updated: 2, total: 2, results: [
        { account_id: 1, nickname: 'alpha', ok: true },
        { account_id: 2, nickname: 'beta', ok: true },
      ] };
    }
    h.calls.push([url, null]);
    return {};
  };
  await h.context.applyBulkAccountSettings();
  assert.deepEqual(h.calls[0], ['/api/bulk/account-settings', { ids: [1, 2], field: 'eventsub_enabled', value: false }]);
  assert.match(h.nodes.get('bulkSettingsResults').innerHTML, /alpha/);
  assert.match(h.nodes.get('bulkSettingsResults').innerHTML, /beta/);
  assert.ok(h.calls.some(call => Array.isArray(call) && call[0] === '/api/accounts'), 'после применения список ботов обновляется через loadBotsList()');
});

test('Q39: apply surfaces a validation error from the backend without touching the results box', async () => {
  const h = harness();
  h.run('_selectedBots.add(1);');
  h.context.openBulkAccountSettings();
  h.context.$('bulkSettingsField').value = 'observation_only';
  h.context.$('bulkSettingsValue').value = 'true';
  h.context.api = async () => ({ ok: false, error: 'ids_required' });
  await h.context.applyBulkAccountSettings();
  assert.equal(h.nodes.get('bulkSettingsError').textContent, 'bulk.error.ids_required');
  assert.equal(h.nodes.has('bulkSettingsResults'), false, 'блок результатов не трогается при ошибке валидации');
});
