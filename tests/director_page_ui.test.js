// Q40: страница Режиссёра — вкладки каналов и скин Пульт/Кокпит.
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
  const attrs = {};
  return { id, value: '', innerHTML: '', textContent: '', disabled: false, classList: classes(), dataset: {},
    setAttribute(k, v) { attrs[k] = v; }, getAttribute: k => attrs[k], attrs, querySelectorAll: () => [] };
}
function harness(stored = null) {
  const nodes = new Map();
  const store = new Map(stored ? [['directorSkin', stored]] : []);
  const options = ['pult', 'cockpit'].map(skin => ({ ...element(skin), dataset: { directorSkinOption: skin } }));
  const calls = [];
  const keydownHandlers = [];
  const sections = [];
  const context = vm.createContext({
    console, LANGS: { ru: {}, en: {}, ua: {} },
    localStorage: { getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) },
    $: id => { if (!nodes.has(id)) nodes.set(id, element(id)); return nodes.get(id); },
    document: {
      documentElement: element('html'),
      querySelectorAll: sel => (sel === '[data-director-skin-option]' ? options : []), activeElement: null,
      addEventListener: (type, fn) => { if (type === 'keydown') keydownHandlers.push(fn); },
    },
    esc: v => String(v ?? ''), t: k => k, toast() {}, confirmDirty: () => true, clearDirty() {}, bindDirtyWatch() {}, markDirty() {},
    api: async url => { calls.push(url); return {}; }, jopts: (m, b) => ({ method: m, body: b }),
    // Q36: очередь ручных отправок опрашивается через setInterval — узлу vm он не предоставляется по умолчанию.
    setInterval: (fn, ms) => setInterval(fn, ms), clearInterval: id => clearInterval(id),
    // Q37: быстрый ответ переключает секцию панели — здесь достаточно фиксировать факт вызова.
    showSection: name => { sections.push(name); },
  });
  vm.runInContext(fs.readFileSync('static/app/20_director.js', 'utf8'), context);
  return { context, nodes, store, options, calls, keydownHandlers, sections, run: code => vm.runInContext(code, context) };
}
const CHANNELS = `_directorChannels = [
  {channel: 'alpha', bots: [{bot_role: 'lurker', enabled: true, connected: true}, {bot_role: 'lurker', enabled: true, connected: false}, {bot_role: 'director', enabled: true}]},
  {channel: 'beta', bots: []}]; _directorChannel = 'alpha';`;

test('tabs render one tab per channel with online lurkers and the selected state', () => {
  const h = harness();
  h.run(CHANNELS + "_directorTabStatus.set('alpha', 'live'); renderDirectorChannelTabs();");
  const html = h.nodes.get('directorChannelTabs').innerHTML;
  assert.equal((html.match(/role="tab"/g) || []).length, 2);
  assert.match(html, /data-channel="alpha"[^>]*>.*director-tab-dot live.*🤖 1\/2.*state-live/s);
  assert.match(html, /class="director-channel-tab active" aria-selected="true" tabindex="0" data-channel="alpha"/);
  assert.match(html, /aria-selected="false" tabindex="-1" data-channel="beta"/);
});

test('clicking a tab switches the channel through the shared select and loads its status', async () => {
  const h = harness();
  h.run(CHANNELS);
  await h.context.directorChannelTab('beta');
  assert.equal(h.run('_directorChannel'), 'beta');
  assert.equal(h.nodes.get('directorChannelSelect').value, 'beta');
  assert.ok(h.calls.includes('/api/director/beta/status'));
  h.calls.length = 0;
  await h.context.directorChannelTab('beta'); // тот же канал — без перезагрузки
  assert.equal(h.calls.length, 0);
});

test('panel layout defaults to pult, migrates the former Director choice and applies globally', () => {
  const h = harness();
  assert.equal(h.nodes.get('section-director').attrs['data-director-skin'], 'pult');
  assert.equal(h.context.document.documentElement.attrs['data-panel-layout'], 'pult');
  h.context.applyPanelLayout('cockpit');
  assert.equal(h.store.get('panelLayout'), 'cockpit');
  assert.equal(h.nodes.get('section-director').attrs['data-director-skin'], 'cockpit');
  assert.equal(h.context.document.documentElement.attrs['data-panel-layout'], 'cockpit');
  assert.equal(h.options[1].attrs['aria-pressed'], 'true');
  assert.equal(h.options[0].attrs['aria-pressed'], 'false');
  h.context.applyPanelLayout('neon');
  assert.equal(h.store.get('panelLayout'), 'pult');
  assert.equal(harness('cockpit').context.document.documentElement.attrs['data-panel-layout'], 'cockpit');
});

test('manual mode: no auto-selected sender, send needs text + explicit bot and posts exactly that', async () => {
  const h = harness();
  const posts = [];
  h.context.api = async (url, opts) => { if (opts?.method === 'POST') posts.push([url, JSON.parse(opts.body)]); return {messages: []}; };
  h.context.jopts = (method, body) => ({method, body: JSON.stringify(body)});
  h.run(CHANNELS.replace("{bot_role: 'lurker', enabled: true, connected: true}", "{account_id: 7, nickname: 'lynx', bot_role: 'lurker', enabled: true, connected: true}")
    + "_directorModes.set('alpha', {mode: 'manual', fenced: false}); _directorState = {session: null}; renderDirectorMode();");
  assert.equal(h.nodes.get('section-director').attrs['data-director-mode'], 'manual');
  assert.match(h.nodes.get('directorManualSenders').innerHTML, /aria-checked="false"[^>]*data-account-id="7"/);
  h.nodes.get('directorManualText').value = 'клатч года';
  h.context.renderDirectorManualPreview();
  assert.equal(h.nodes.get('directorManualSend').disabled, true, 'без выбранного бота отправка недоступна');
  await h.context.directorManualSend();
  assert.equal(posts.length, 0);
  h.context.directorManualPick(7);
  assert.equal(h.nodes.get('directorManualSend').disabled, false);
  assert.match(h.nodes.get('directorManualPreview').innerHTML, /lynx:<\/b> <span data-user-content>клатч года/);
  await h.context.directorManualSend();
  assert.deepEqual(posts, [['/api/director/alpha/operator/send', {account_id: 7, text: 'клатч года'}]]);
  assert.equal(h.nodes.get('directorManualText').value, '');
});

test('Q37: quick reply from chat switches to the already-manual channel and prefills the @nick', async () => {
  const h = harness();
  h.run(CHANNELS.replace("{bot_role: 'lurker', enabled: true, connected: true}", "{account_id: 7, nickname: 'lynx', bot_role: 'lurker', enabled: true, connected: true}")
    + "_directorModes.set('alpha', {mode: 'manual', fenced: false}); _directorState = {session: null}; renderDirectorMode();");
  h.nodes.get('directorManualText').value = 'старый текст';
  await h.context.chatLogQuickReply('alpha', 'viewer42');
  assert.deepEqual(h.sections, ['director']);
  assert.equal(h.run('_directorChannel'), 'alpha'); // тот же канал — без лишнего похода в сеть
  assert.equal(h.nodes.get('directorManualText').value, '@viewer42 старый текст');
});

test('Q37: quick reply switches the Director tab to a different already-manual channel', async () => {
  const h = harness();
  h.run(CHANNELS.replace("{channel: 'beta', bots: []}", "{channel: 'beta', bots: [{account_id: 9, nickname: 'fox', bot_role: 'lurker', enabled: true, connected: true}]}"));
  h.context.api = async url => (url === '/api/director/beta/status' ? {control_mode: 'manual', manual_fenced: false} : {});
  await h.context.chatLogQuickReply('beta', 'chatter');
  assert.equal(h.run('_directorChannel'), 'beta');
  assert.equal(h.nodes.get('directorManualText').value, '@chatter ');
});

test('Q37: quick reply refuses an ai-mode channel and an unknown channel without touching the composer', async () => {
  const h = harness();
  h.run(CHANNELS + "_directorModes.set('alpha', {mode: 'ai', fenced: false}); _directorState = {session: null}; renderDirectorMode();");
  h.nodes.get('directorManualText').value = 'нетронуто';
  let warned = '';
  h.context.toast = msg => { warned = msg; };
  await h.context.chatLogQuickReply('alpha', 'someone');
  assert.equal(warned, 'director.quick_reply_manual_only');
  assert.equal(h.nodes.get('directorManualText').value, 'нетронуто');
  warned = '';
  await h.context.chatLogQuickReply('unknown_channel', 'someone');
  assert.equal(warned, 'director.quick_reply_no_channel');
  assert.equal(h.nodes.get('directorManualText').value, 'нетронуто');
});

test('Q38: history row repeat button prefills text and reselects the sender when still available', () => {
  const h = harness();
  h.run(CHANNELS.replace("{bot_role: 'lurker', enabled: true, connected: true}", "{account_id: 7, nickname: 'lynx', bot_role: 'lurker', enabled: true, connected: true}"));
  h.run("_directorManual.messages.set('alpha', [{id: 11, account_id: 7, nickname: 'lynx', text: 'гл гг', state: 'sent', created_at: 0}, {id: 12, account_id: 99, nickname: 'retired', text: 'старьё', state: 'sent', created_at: 0}]); renderDirectorManualLog();");
  const html = h.nodes.get('directorManualLog').innerHTML;
  assert.match(html, /data-msg-id="11"[^>]*>↻/);
  assert.match(html, /data-msg-id="12"[^>]*>↻/);
  h.context.directorManualRepeat('11');
  assert.equal(h.nodes.get('directorManualText').value, 'гл гг');
  assert.equal(h.run("_directorManual.sender.get('alpha')"), 7);
  // Отправитель истории больше не lurker в канале — текст подставляется, выбор отправителя не трогаем.
  h.context.directorManualRepeat('12');
  assert.equal(h.nodes.get('directorManualText').value, 'старьё');
  assert.equal(h.run("_directorManual.sender.get('alpha')"), 7);
});

test('Q36: send status shows the channel queue depth while waiting for the rate-limit slot', async () => {
  const h = harness();
  h.context.api = async (url) => {
    if (url === '/api/director/alpha/operator/queue') return {ok: true, channel: 'alpha', pending: 3};
    if (url.endsWith('/operator/send')) return new Promise(resolve => setTimeout(() => resolve({ok: true}), 350));
    return {messages: []};
  };
  h.context.jopts = (method, body) => ({method, body: JSON.stringify(body)});
  h.run(CHANNELS.replace("{bot_role: 'lurker', enabled: true, connected: true}", "{account_id: 7, nickname: 'lynx', bot_role: 'lurker', enabled: true, connected: true}")
    + "_directorModes.set('alpha', {mode: 'manual', fenced: false}); _directorState = {session: null}; renderDirectorMode();");
  h.nodes.get('directorManualText').value = 'ждём слот';
  h.context.directorManualPick(7);
  const pending = h.context.directorManualSend();
  await new Promise(resolve => setTimeout(resolve, 320));
  assert.equal(h.nodes.get('directorManualStatus').textContent, 'director.manual_queued');
  await pending;
  assert.equal(h.nodes.get('directorManualStatus').textContent, 'director.manual_sent');
});

test('mode switch is locked while a session runs and fenced channel cannot send', () => {
  const h = harness();
  const buttons = ['ai', 'manual'].map(mode => ({ ...element(mode), dataset: { directorMode: mode } }));
  h.context.document.querySelectorAll = sel => (sel === '.director-mode-btn' ? buttons : []);
  h.run(CHANNELS + "_directorModes.set('alpha', {mode: 'ai', fenced: false}); _directorState = {session: {state: 'live'}}; renderDirectorMode();");
  assert.equal(buttons[1].disabled, true);
  assert.equal(h.nodes.get('directorModeHint').textContent, 'director.mode_locked');
  h.run("_directorModes.set('alpha', {mode: 'manual', fenced: true}); _directorState = {session: null}; _directorManual.sender.set('alpha', 1); renderDirectorMode();");
  assert.equal(h.nodes.get('directorManualFenced').classList.contains('hidden'), false);
  assert.equal(h.nodes.get('directorManualSend').disabled, true);
});

test('every configured channel becomes a Director tab so it can be prepared before a lurker is added', async () => {
  const h = harness();
  h.context.api = async url => {
    if (url === '/api/channel-overview') return {channels: [
      {channel: 'mod_only', bots: [{account_id: 1}]},
      {channel: 'streamer', bots: [{account_id: 1}, {account_id: 2}]},
      {channel: 'tts_only', bots: [{account_id: 3}]},
    ]};
    if (url === '/api/accounts') return [{id: 1, bot_role: 'moderator'}, {id: 2, bot_role: 'lurker', enabled: true}, {id: 3, bot_role: 'voice_companion'}];
    return {};
  };
  await h.context.loadDirectorSection();
  assert.deepEqual(h.run('_directorChannels.map(c => c.channel)'), ['mod_only', 'streamer', 'tts_only']);
  h.context.api = async url => (url === '/api/channel-overview' ? {channels: [{channel: 'mod_only', bots: [{account_id: 1}]}]} : [{id: 1, bot_role: 'moderator'}]);
  await h.context.loadDirectorSection();
  assert.deepEqual(h.run('_directorChannels.map(c => c.channel)'), ['mod_only']);
  assert.match(h.nodes.get('directorChannelSelect').innerHTML, /mod_only/);
});

test('AI panes switch sections and mass worker tools act on filtered items only', () => {
  const h = harness();
  const tabs = ['control', 'settings'].map(pane => ({ ...element(pane), dataset: { pane } }));
  h.context.document.querySelectorAll = sel => (sel === '.director-pane-tab' ? tabs : []);
  h.context.directorShowPane('settings');
  assert.equal(h.nodes.get('section-director').attrs['data-director-pane-active'], 'settings');
  assert.equal(tabs[1].attrs['aria-selected'], 'true');
  h.context.directorShowPane('bogus');
  assert.equal(h.nodes.get('section-director').attrs['data-director-pane-active'], 'control');

  const make = (nick, online, checked) => {
    const input = { checked, disabled: false };
    return { classList: classes(), dataset: { nick, online: online ? '1' : '0' }, querySelector: () => input, input };
  };
  const items = [make('owl_1', true, false), make('owl_2', false, false), make('fox', true, false)];
  let dirty = 0;
  h.context.markDirty = () => { dirty += 1; };
  h.context.$('directorWorkerChoices').querySelectorAll = sel => (sel === '.director-worker-item' ? items : items.map(i => i.input));
  h.context.$('directorWorkerSearch').value = 'owl';
  h.context.renderDirectorWorkerFilter();
  assert.equal(items[2].classList.contains('hidden'), true);
  h.context.directorWorkersBulk('online');
  assert.deepEqual(items.map(i => i.input.checked), [true, false, false]);
  h.context.directorWorkersBulk('all');
  assert.deepEqual(items.map(i => i.input.checked), [true, true, false]);
  h.context.directorWorkersBulk('none');
  assert.deepEqual(items.map(i => i.input.checked), [false, false, false]);
  assert.equal(dirty, 3);
});

test('Q35: preset chips render hotkey badges, click loads text and Alt+digit acts as the same hotkey', () => {
  const h = harness();
  h.run(CHANNELS + "_directorModes.set('alpha', {mode: 'manual', fenced: false});"
    + "_directorPresets.set('alpha', [{id: 1, text: 'клатч года', position: 0}, {id: 2, text: 'гг', position: 1}]);"
    + "renderDirectorManualPresets();");
  const html = h.nodes.get('directorManualPresets').innerHTML;
  assert.match(html, /Alt\+1[\s\S]*клатч года/);
  assert.match(html, /Alt\+2[\s\S]*гг/);
  h.context.directorPresetInsert(2);
  assert.equal(h.nodes.get('directorManualText').value, 'гг');
  h.nodes.get('directorManualText').value = '';
  h.context.directorPresetHotkey(0);
  assert.equal(h.nodes.get('directorManualText').value, 'клатч года');
});

test('Q35: preset add/edit/delete call the presets API and refresh the local list', async () => {
  const h = harness();
  const calls = [];
  h.context.api = async (url, opts) => {
    calls.push([url, opts?.method || 'GET']);
    return {presets: [{id: 5, text: 'новая', position: 0}]};
  };
  h.context.jopts = (method, body) => ({method, body: JSON.stringify(body || {})});
  h.run(CHANNELS);
  h.context.$('directorPresetInput').value = 'новая';
  await h.context.directorPresetAdd();
  assert.deepEqual(calls[0], ['/api/director/alpha/manual/presets', 'POST']);
  assert.equal(h.nodes.get('directorPresetInput').value, '');
  assert.deepEqual(h.run('_directorPresets.get(\"alpha\")'), [{id: 5, text: 'новая', position: 0}]);

  h.context.directorPresetStartEdit(5);
  h.context.$('directorPresetEditInput').value = 'обновлено';
  await h.context.directorPresetSaveEdit(5);
  assert.deepEqual(calls[1], ['/api/director/alpha/manual/presets/5', 'PUT']);

  h.context.confirm = () => true;
  await h.context.directorPresetRemove(5);
  assert.deepEqual(calls[2], ['/api/director/alpha/manual/presets/5', 'DELETE']);
});

test('Q35: Alt+digit hotkey only fires on the active Director section in manual mode', () => {
  const h = harness();
  h.run(CHANNELS + "_directorModes.set('alpha', {mode: 'ai', fenced: false});"
    + "_directorPresets.set('alpha', [{id: 1, text: 'клатч года', position: 0}]);");
  h.context.$('directorManualText');
  const keydown = h.keydownHandlers[h.keydownHandlers.length - 1];
  const section = h.nodes.get('section-director');
  const event = { key: '1', altKey: true, ctrlKey: false, metaKey: false, shiftKey: false, preventDefault() { this.defaulted = true; } };
  keydown(event);
  assert.equal(h.nodes.get('directorManualText').value, '', 'вне активной секции/ИИ-режима хоткей молчит');
  section.classList.add('active');
  keydown(event);
  assert.equal(h.nodes.get('directorManualText').value, '', 'в ИИ-режиме хоткей молчит');
  h.run("_directorModes.set('alpha', {mode: 'manual', fenced: false});");
  keydown(event);
  assert.equal(h.nodes.get('directorManualText').value, 'клатч года');
  assert.equal(event.defaulted, true);
});
