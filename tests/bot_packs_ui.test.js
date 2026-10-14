// Q34a anchors: pack editor (create/edit modal, selection, save) without a browser.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('static/app/03_bots.js', 'utf8');
const TEMPLATE = fs.readFileSync('templates/partials/bots.html', 'utf8');

function element(id) {
  return { id, innerHTML: '', value: '', textContent: '', disabled: false, dataset: {}, options: [] };
}

function createContext() {
  const ids = ['botPacksList', 'botPackBots', 'botPackTitle', 'botPackName', 'botPackWindow',
    'botPackSearch', 'botPackRoleFilter', 'botPackCount', 'botPackSaveBtn'];
  const elements = Object.fromEntries(ids.map(id => [id, element(id)]));
  const calls = [];
  const context = {
    console,
    _allBots: [],
    $: id => elements[id] || null,
    api: async (url, options) => { calls.push({ url, options }); return { ok: true, packs: [] }; },
    esc: v => String(v ?? ''),
    t: (key, params) => key + (params ? ` ${JSON.stringify(params)}` : ''),
    _roleMetaLabel: role => `label:${role}`,
    showModal: () => {}, hideModal: () => {}, toast: () => {}, confirm: () => true,
    setTimeout: () => 1, clearTimeout: () => {},
    jopts: (method, body) => ({ method, body: JSON.stringify(body) }),
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  return { context, elements, calls };
}

const bots = [
  { id: 1, nickname: 'alpha', bot_role: 'lurker', persisted_channels: ['chan_a'] },
  { id: 2, nickname: 'beta', bot_role: 'moderator', persisted_channels: [] },
  { id: 3, nickname: 'gamma', bot_role: 'lurker', persisted_channels: ['chan_b'] },
];

test('create flow: modal lists bots with channels, selection counts, save posts members', async () => {
  const h = createContext();
  h.context._allBots = structuredClone(bots);
  h.context.showBotPackModal();
  const html = h.elements.botPackBots.innerHTML;
  assert.match(html, /alpha/);
  assert.match(html, /botPackToggle\(1/);
  assert.match(html, /chan_a/);
  h.context.botPackToggle(1, true);
  h.context.botPackToggle(3, true);
  assert.match(h.elements.botPackCount.textContent, /"n":2/);
  h.elements.botPackName.value = 'Ночь';
  h.elements.botPackWindow.value = '7';
  await h.context.submitBotPack();
  assert.equal(h.calls[0].url, '/api/packs');
  const body = JSON.parse(h.calls[0].options.body);
  assert.deepEqual(body, { name: 'Ночь', join_window_min: 7, members: [{ account_id: 1, channel_name: 'chan_a' }, { account_id: 3, channel_name: 'chan_b' }] });
});

test('validation guards: empty name and empty selection never reach the API', async () => {
  const h = createContext();
  h.context._allBots = structuredClone(bots);
  h.context.showBotPackModal();
  await h.context.submitBotPack();
  h.elements.botPackName.value = 'ok';
  await h.context.submitBotPack();
  assert.equal(h.calls.length, 0);
});

test('edit flow prefills pack members and PUTs to the pack id', async () => {
  const h = createContext();
  h.context._allBots = structuredClone(bots);
  h.run = script => vm.runInContext(script, h.context);
  h.run('_botPacksCache = [{id: 5, name: "old", join_window_min: 2, members: [{account_id: 2, channel_name: ""}]}];');
  h.context.showBotPackModal(5);
  assert.equal(h.elements.botPackTitle.textContent, 'bots.packs.title_edit');
  assert.equal(h.elements.botPackName.value, 'old');
  assert.equal(h.elements.botPackWindow.value, 2);
  h.elements.botPackName.value = 'new';
  h.elements.botPackWindow.value = '9';
  h.context.botPackToggle(3, true);
  await h.context.submitBotPack();
  assert.equal(h.calls[0].url, '/api/packs/5');
  assert.equal(h.calls[0].options.method, 'PUT');
  const body = JSON.parse(h.calls[0].options.body);
  assert.deepEqual(body.members, [{ account_id: 2, channel_name: '' }, { account_id: 3, channel_name: 'chan_b' }]);
});

test('filter, search and select-all operate on visible bots only', () => {
  const h = createContext();
  h.context._allBots = structuredClone(bots);
  h.context.showBotPackModal();
  h.elements.botPackRoleFilter.value = 'lurker';
  h.context.botPackFilterChanged();
  assert.doesNotMatch(h.elements.botPackBots.innerHTML, /beta/);
  h.context.botPackSelectAll(true);
  assert.match(h.elements.botPackCount.textContent, /"n":2/);
  h.elements.botPackRoleFilter.value = '';
  h.elements.botPackSearch.value = 'gam';
  h.context.botPackFilterChanged();
  assert.match(h.elements.botPackBots.innerHTML, /gamma/);
  assert.doesNotMatch(h.elements.botPackBots.innerHTML, /alpha/);
  h.context.botPackSelectAll(false);
  assert.match(h.elements.botPackCount.textContent, /"n":0/);
});

test('pack list renders edit/delete actions; template wires the create button and modal', () => {
  const h = createContext();
  h.run = script => vm.runInContext(script, h.context);
  h.run('_botPacksCache = [{id: 5, name: "Ночь", join_window_min: 5, members: [{account_id: 1, channel_name: "chan_a"}]}];');
  h.context.renderBotPacks();
  const html = h.elements.botPacksList.innerHTML;
  assert.match(html, /Ночь/);
  assert.match(html, /showBotPackModal\(5\)/);
  assert.match(html, /deleteBotPack\(5\)/);
  assert.match(TEMPLATE, /showBotPackModal\(\)/);
  assert.match(TEMPLATE, /id="botPackModal"/);
  assert.match(TEMPLATE, /id="botPacksList"/);
});

test('scheduled apply polls join progress and exposes a cancellation request', async () => {
  const h = createContext();
  h.run = script => vm.runInContext(script, h.context);
  h.context.api = async (url, options) => {
    h.calls.push({url, options});
    if (url.endsWith('/apply')) return {ok:true, enabled:2, scheduled:2, window_min:5};
    if (url === '/api/packs') return {ok:true, packs:[{id:9, name:'Спред', join_window_min:5, members:[{account_id:1}, {account_id:2}], active_joins:1}]};
    if (url.endsWith('/joins')) return {ok:true, counts:{pending:1, running:0, joined:1, failed:0, cancelled:0}};
    if (url.endsWith('/joins/cancel')) return {ok:true, cancelled:1};
    return {ok:true};
  };
  h.run('_botPacksCache = [{id: 9, name: "Спред", join_window_min: 5, members: [{account_id: 1}, {account_id: 2}]}];');
  h.elements.botPackJoin_9 = element('botPackJoin_9');
  await h.context.applyBotPack(9);
  assert.equal(h.calls[0].url, '/api/packs/9/apply');
  assert.equal(h.calls[1].url, '/api/packs');
  assert.equal(h.calls[2].url, '/api/packs/9/joins');
  assert.match(h.elements.botPackJoin_9.innerHTML, /joins_progress/);
  assert.match(h.elements.botPackJoin_9.innerHTML, /cancelBotPackJoins\(9\)/);
  await h.context.cancelBotPackJoins(9);
  assert.equal(h.calls[3].url, '/api/packs/9/joins/cancel');
});

test('apply posts connect:true after confirm; collapse posts the channels checkbox', async () => {
  const h = createContext();
  h.run = script => vm.runInContext(script, h.context);
  h.context.loadBotsList = async () => {}; // не тянем полный список после мутации
  h.run('_botPacksCache = [{id: 7, name: "Ночь", join_window_min: 5, members: [{account_id: 1}]}];');
  await h.context.applyBotPack(7);
  assert.equal(h.calls[0].url, '/api/packs/7/apply');
  assert.deepEqual(JSON.parse(h.calls[0].options.body), {connect: true});
  h.elements['botPackCh_7'] = { checked: true };
  await h.context.collapseBotPack(7);
  assert.equal(h.calls[1].url, '/api/packs/7/collapse');
  assert.deepEqual(JSON.parse(h.calls[1].options.body), {disable_channels: true});
  // Отмена подтверждения не должна звать API.
  h.context.confirm = () => false;
  h.calls.length = 0;
  await h.context.applyBotPack(7);
  await h.context.collapseBotPack(7);
  assert.equal(h.calls.length, 0);
});
