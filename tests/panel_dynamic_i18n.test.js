const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {environment, functionSource} = require('./panel_accessibility_harness');

const read = file => fs.readFileSync(path.join(__dirname, '..', file), 'utf8');
const decode = value => value.replace(/&quot;/g, '"').replace(/&#(?:39|x27);/g, "'")
  .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');

function setup() {
  const env = environment();
  const {ctx, document} = env;
  const prototype = Object.getPrototypeOf(document.body);
  Object.defineProperty(prototype, 'innerHTML', {
    configurable: true,
    get() { return this._html || ''; },
    set(html) {
      this._html = String(html); this.textContent = '';
      const stack = [this];
      for (const token of String(html).matchAll(/<\/?[^>]+>|[^<]+/g)) {
        const part = token[0];
        if (part.startsWith('</')) { stack.pop(); continue; }
        if (!part.startsWith('<')) { stack.at(-1)._text += decode(part); continue; }
        const tag = part.match(/^<([\w-]+)/)?.[1];
        if (!tag) continue;
        const node = document.createElement(tag);
        for (const attr of part.slice(tag.length + 1, -1).matchAll(/([^\s=]+)(?:="([^"]*)"|='([^']*)')?/g)) {
          node.setAttribute(attr[1], decode(attr[2] ?? attr[3] ?? ''));
        }
        if (node.hasAttribute('value')) node.value = node.getAttribute('value');
        stack.at(-1).appendChild(node);
        if (!['input', 'br', 'img', 'hr'].includes(tag)) stack.push(node);
      }
      this.querySelectorAll('select').forEach(select => {
        select.value = (select.querySelector('[selected]') || select.querySelector('option'))?.value || '';
      });
    },
  });
  prototype.prepend = function(node) { node.remove(); node.parentElement = this; this.children.unshift(node); };
  Object.defineProperty(prototype, 'options', {configurable: true, get() { return this.querySelectorAll('option'); }});
  const make = document.createElement.bind(document);
  document.createElement = tag => {
    const node = make(tag);
    node.dataset = new Proxy(node.dataset, {set(target, key, value) {
      target[key] = String(value);
      node.attributes.set('data-' + key.replace(/[A-Z]/g, c => '-' + c.toLowerCase()), String(value));
      return true;
    }});
    return node;
  };
  const element = (tag, id) => {
    const node = document.createElement(tag); if (id) node.id = id;
    document.body.appendChild(node); return node;
  };
  const source = read('static/app.js');
  vm.runInContext(source.slice(source.indexOf('const LANGS ='), source.indexOf('const _legacySourceByNode'))
    .replace('const LANGS =', 'LANGS ='), ctx);
  for (const file of ['21_panel_labels', '24_dynamic_i18n']) {
    vm.runInContext(read(`static/app/${file}.js`), ctx);
  }
  Object.assign(ctx, {
    $: id => document.getElementById(id),
    esc: value => String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;'),
    URLSearchParams, _currentBotId: 1, _brainAcc: () => 1, _memoryAcc: () => 1, _brainCh: () => '*',
    _modPendingShown: {}, _setToggle() {}, toast() {}, refreshPanelAccessibility() {},
    jopts: (method, body) => ({method, body}), api: async () => ({}), API: '',
  });
  vm.runInContext(functionSource('static/app.js', 'setLang'), ctx);
  const load = (file, ...names) => names.forEach(name => vm.runInContext(functionSource(`static/app/${file}.js`, name), ctx));
  const translate = lang => { ctx._allBots = []; ctx.setLang(lang); };
  return {...env, element, load, translate};
}

function translatedLeaves(env) {
  for (const node of env.document.querySelectorAll('[data-i18n]')) {
    const key = node.getAttribute('data-i18n');
    assert.ok(env.ctx.hasTranslation(key), key);
    assert.equal(node.textContent, env.ctx.t(key), key);
    assert.equal(node.querySelectorAll('input,select,textarea').length, 0, 'translation must not destroy a control');
  }
  for (const attr of ['title', 'aria-label', 'placeholder']) {
    for (const node of env.document.querySelectorAll(`[data-i18n-${attr}]`)) {
      const key = node.getAttribute(`data-i18n-${attr}`);
      assert.ok(env.ctx.hasTranslation(key), key);
      assert.equal(node.getAttribute(attr), env.ctx.t(key), key);
    }
  }
}

function namedButtons(root) {
  for (const node of root.querySelectorAll('button')) {
    if (!/[\p{L}]/u.test(node.textContent)) {
      assert.ok(node.getAttribute('aria-label'), 'icon needs an accessible label');
      assert.ok(node.getAttribute('title'), 'icon needs a tooltip');
    }
  }
}

test('every new dictionary key has three translations and identical interpolation variables', () => {
  const ctx = {LANGS: {ru: {}, en: {}, ua: {}}}; vm.createContext(ctx);
  vm.runInContext(read('static/app/24_dynamic_i18n.js'), ctx);
  const keys = Object.keys(ctx.LANGS.ru).sort();
  for (const lang of ['en', 'ua']) assert.deepEqual(Object.keys(ctx.LANGS[lang]).sort(), keys);
  for (const key of keys) {
    const vars = text => [...text.matchAll(/\{\w+\}/g)].map(m => m[0]).sort();
    for (const lang of ['ru', 'en', 'ua']) {
      assert.ok(ctx.LANGS[lang][key].trim(), `${lang}:${key}`);
      assert.deepEqual(vars(ctx.LANGS[lang][key]), vars(ctx.LANGS.ru[key]), key);
    }
  }
});

test('affinity levels, fact extraction and clip rates follow the selected language', async () => {
  const env = setup(); const {ctx, load, translate, element} = env;
  load('14_brain_memory', 'brainAutoExtract', 'brainAffinityLevel');
  load('11_brain_v16', 'checkClipSpike');
  ctx.toggleChecked = () => false;
  ctx._firstChannel = () => 'alpha'; ctx.loadLore = () => {};
  const notices = []; ctx.toast = text => notices.push(text);
  const clip = element('div', 'clipCheckResult');
  for (const lang of ['ru', 'en', 'ua']) {
    translate(lang);
    for (const [value, key] of [[0, 'stranger'], [20, 'viewer'], [40, 'familiar'], [60, 'regular'], [80, 'close']]) {
      assert.equal(ctx.brainAffinityLevel(value), ctx.t('dynamic.affinity_' + key));
    }
    ctx.api = async () => ({ok: true, candidates: ['fact']});
    await ctx.brainAutoExtract();
    assert.equal(notices.at(-1), ctx.t('dynamic.extracted', {count: 1}));
    ctx.api = async () => ({spike: true, rate: 4, avg_rate: 2});
    await ctx.checkClipSpike();
    assert.ok(clip.innerHTML.includes(ctx.t('dynamic.clip_rate', {rate: 4, average: 2})));
  }
});

test('memory editor switches language without losing fact identity, priority or TTL drafts', async () => {
  const env = setup(); const {ctx, element, document, load, translate} = env;
  element('div', 'botViewerMemoryList');
  load('14_brain_memory', 'brainEditFact', 'brainSaveFactEdit');
  ctx.loadBotViewerMemory = () => {};
  const fact = '✎ Факт: Зберегти <viewer> "quoted"';
  ctx.brainEditFact('viewer', fact, 40, true);
  const priority = document.getElementById('brainFactPr');
  const ttl = document.getElementById('brainFactTtl');
  priority.value = '83'; ttl.value = '9';
  for (const lang of ['en', 'ua', 'ru']) {
    translate(lang); translatedLeaves(env);
    assert.equal(document.getElementById('brainFactPr'), priority);
    assert.equal(priority.value, '83'); assert.equal(ttl.value, '9');
    assert.equal(document.getElementById('brainFactEditForm').dataset.fact, fact);
  }
  let saved;
  ctx.api = async (url, options) => { saved = {url, ...options}; return {ok: true}; };
  ctx.loadBrainMemory = () => {};
  await ctx.brainSaveFactEdit('viewer');
  assert.equal(saved.url, '/api/accounts/1/memory/viewer/fact');
  assert.equal(saved.body.fact, fact); assert.equal(saved.body.priority, 83);
  assert.equal(saved.body.ttl, 9 * 86400);
  ttl.value = '0'; await ctx.brainSaveFactEdit('viewer');
  assert.equal(saved.body.expires_at, null);
});

test('memory facts retain user text and new-fact drafts while action names switch', () => {
  const env = setup(); const {ctx, element, load, translate} = env;
  const box = element('div', 'memoryList'); load('05_bots_tabs', 'renderMemoryList');
  ctx.renderMemoryList({users: {viewer: {facts: ['Зберегти <literal>'], msg_count: 2}}});
  const input = box.querySelector('input'); input.value = 'unsaved fact';
  for (const lang of ['ru', 'en', 'ua']) {
    translate(lang); translatedLeaves(env); namedButtons(box);
    assert.equal(box.querySelector('input'), input); assert.equal(input.value, 'unsaved fact');
    assert.match(box.textContent, /Зберегти <literal>/);
  }
});

test('moderation modes, rules, verdicts and statistics translate without changing backend values', async () => {
  const env = setup(); const {ctx, element, load, translate} = env;
  const override = element('div', 'modChannelOverrides');
  const rules = element('div', 'moderationRulesList');
  const result = element('div', 'modTestResult'); element('input', 'modTestText').value = 'sample';
  element('div', 'moderationStats'); element('div', 'moderationEventsList');
  vm.runInContext(read('static/app/08_providers_moderation.js').match(/^const MOD_MODE_LABELS = .*;$/m)[0], ctx);
  load('08_providers_moderation', 'renderModerationChannelOverrides', 'renderModerationRules', 'moderationSpamDetail', 'testModeration', 'loadModerationEvents');
  ctx.renderModerationChannelOverrides({mode: 'full', channels: ['example'], channel_overrides: {example: 'replace'}});
  ctx.renderModerationRules([{id: 2, category: 'insult', pattern: '<sample>', action: 'block', severity: 3, enabled: true}]);
  const select = override.querySelector('select'); select.value = 'log_only';
  ctx.api = async url => url.includes('/test')
    ? {mode: 'full', summary: 'insult/block(3)', verdicts: [{category: 'insult', action: 'block', severity: 3, match: '<sample>'}],
      spam: [{category: 'repeat', detail: 'повтор 3x за 60с'}, {category: 'links', detail: 'содержит ссылку'},
        {category: 'caps', detail: 'caps 80% > 70%'}, {category: 'emote', detail: 'эмодзи/эмоуты 90% > 80%'},
        {category: 'copypasta', detail: 'copypasta sim=0.92'}]}
    : url.includes('/stats') ? {day: 4, by_category: [{category: 'spam', count: 2}]} : {events: []};
  await ctx.testModeration(1); await ctx.loadModerationEvents(1);
  for (const lang of ['ru', 'en', 'ua']) {
    translate(lang); translatedLeaves(env); namedButtons(rules);
    assert.equal(select.value, 'log_only');
    assert.deepEqual(select.options.map(o => o.value), ['', 'off', 'log_only', 'replace', 'shadow', 'full']);
    assert.match(result.textContent, /<sample>/);
    assert.ok(result.textContent.includes(ctx.t('panel.mod.action_block')));
    assert.ok(result.textContent.includes(ctx.t('dynamic.mod.verdict')));
    assert.ok(result.textContent.includes(ctx.t('dynamic.mod.contains_link')));
    assert.ok(result.textContent.includes(ctx.t('dynamic.mod.window_seconds')));
    assert.ok(result.textContent.includes('0.92'));
  }
  ctx.api = async () => { throw new Error('offline'); };
  await ctx.loadModerationEvents(1);
  assert.ok(env.document.getElementById('moderationEventsList').textContent.includes(ctx.t('api.error.request_failed')));
});

test('lore, learning, summary and memory states translate in place with accessible icon actions', async () => {
  const env = setup(); const {ctx, element, load, translate} = env;
  for (const id of ['loreList', 'botLearningList', 'summarizerRunsList', 'botViewerMemoryList']) element('div', id);
  load('11_brain_v16', 'loadLore', 'loadLearning', 'loadSummarizerRuns', 'loadBotViewerMemory');
  ctx.api = async url => url.includes('/lore?') ? {items: [{id: 1, status: 'suggested', fact: 'Зберегти', source: 'manual'}]}
    : url.includes('/learning?') ? {items: [{id: 2, status: 'pending', kind: 'style', source: 'chat'}]}
    : url.includes('/summarizer/') ? {items: [{id: 3, status: 'done', channel: 'example'}]}
    : {users: [{username: 'viewer', facts_structured: [{fact: 'keep me', confirmed: true}]}]};
  await ctx.loadLore(); await ctx.loadLearning(); await ctx.loadSummarizerRuns(); await ctx.loadBotViewerMemory();
  for (const lang of ['ru', 'en', 'ua']) {
    translate(lang); translatedLeaves(env); namedButtons(env.document.body);
    assert.ok(env.document.getElementById('loreList').textContent.includes('Зберегти'));
  }
  ctx.api = async () => ({items: [], users: []});
  await ctx.loadLore(); await ctx.loadLearning(); await ctx.loadSummarizerRuns(); await ctx.loadBotViewerMemory();
  translate('en'); translatedLeaves(env);
  assert.ok(env.document.getElementById('botLearningList').textContent.includes(ctx.t('dynamic.learning_empty')));
});

test('bot loading, panel empty state and retries localize without translating log data', async () => {
  const env = setup(); const {ctx, element, load, translate} = env;
  const bot = element('div', 'botLogsContent'); const panel = element('div', 'panelLogTailContent');
  load('03_bots', 'loadBotLogs'); load('13_widgets_session', 'loadPanelLogTail');
  ctx._allBots = [{id: 1, nickname: 'example'}];
  let finish;
  ctx.api = () => new Promise(resolve => { finish = resolve; });
  const loading = ctx.loadBotLogs();
  assert.ok(bot.textContent.includes(ctx.t('label.loading')));
  finish({content: ''}); await loading;
  ctx.fetch = async () => ({json: async () => ({ok: true, content: ''})});
  await ctx.loadPanelLogTail();
  for (const lang of ['en', 'ua', 'ru']) { translate(lang); translatedLeaves(env); }
  ctx.api = async () => { throw new Error('offline'); };
  ctx.fetch = ctx.api;
  await ctx.loadPanelLogTail();
  translate('en'); translatedLeaves(env);
  assert.equal(panel.querySelector('button').textContent, 'Retry');
  ctx.fetch = async () => ({json: async () => ({ok: true, content: 'Зберегти <log>'})});
  await ctx.loadPanelLogTail(); translate('ua');
  assert.equal(panel.querySelector('[data-user-content]').textContent, 'Зберегти <log>');
});

test('persona captions and AI controls switch without resetting slider drafts', () => {
  const env = setup(); const {ctx, element, load, translate} = env;
  const sliders = element('div', 'personaSliders'); element('div', 'personaToggles');
  for (const name of ['Name', 'Age', 'Gender', 'Location', 'Occupation', 'Personality', 'Games', 'Catchphrases', 'Background']) element('input', 'persona' + name);
  Object.assign(ctx, {_personaCache: {}, PERSONA_FIELDS: [{key: 'humor_level', label: 'persona.f.humor', def: 50}],
    PERSONA_TOGGLES: [], personaVal: (_key, fallback) => fallback, toggleCustomGender() {}});
  load('03_bots', 'renderPersona'); ctx.renderPersona();
  const input = sliders.querySelector('input'); input.value = '78';
  for (const lang of ['en', 'ua', 'ru']) {
    translate(lang); translatedLeaves(env);
    assert.equal(input.value, '78'); assert.equal(sliders.querySelector('input'), input);
    assert.equal(sliders.querySelector('button').getAttribute('title'), ctx.t('dynamic.ai_value'));
  }
});

test('custom-provider editing keeps its update label and draft when language changes', () => {
  const env = setup(); const {ctx, element, load, translate} = env;
  for (const id of ['cpName', 'cpBaseUrl', 'cpApiKey']) element('input', id);
  element('div', 'cpModelsEditor'); // Q15b: один редактор списка моделей вместо двух textarea
  const save = element('button', 'cpSaveBtn'); save.setAttribute('data-i18n', 'cp.add');
  element('button', 'cpCancelBtn');
  ctx._customProvidersCache = [{id: 1, name: 'draft provider', has_api_key: true}];
  load('08_providers_moderation', 'editCustomProvider', 'resetCustomProviderForm', '_cpRowsFromProvider', 'renderCpModelRows');
  ctx.editCustomProvider(1);
  const name = env.document.getElementById('cpName'); name.value = 'edited draft';
  for (const lang of ['ru', 'en', 'ua']) {
    translate(lang); translatedLeaves(env);
    assert.equal(save.textContent, ctx.t('cp.update')); assert.equal(name.value, 'edited draft');
  }
  ctx.resetCustomProviderForm(); translate('en'); assert.equal(save.textContent, ctx.t('cp.add'));
});

test('channel scope selector keeps machine value while options translate', async () => {
  // Q19: вкладка «Мозг» удалена; live-настройки переехали в модалку канала
  // (cpLoadSummarySettings, см. tests/test_channel_card_profile_ui.py).
  // Здесь остаётся контракт loadBrainChannels: опции переводятся, значения — нет.
  const env = setup(); const {ctx, element, load, translate} = env;
  const brain = element('select', 'brainChannel');
  load('11_brain_v16', 'loadBrainChannels');
  ctx.api = async url => ({channels: ['example']});
  await ctx.loadBrainChannels();
  brain.value = '*';
  for (const lang of ['ru', 'en', 'ua']) {
    translate(lang); translatedLeaves(env);
    assert.equal(brain.value, '*');
    assert.equal(brain.options[0].value, '*');
  }
});

test('timeout Yes/No switches live and preserves the approved boolean sent to the API', async () => {
  const env = setup(); const {ctx, load, translate, document} = env;
  load('13_widgets_session', 'showModerationAskPopup');
  ctx.showModerationAskPopup({id: 4, account_id: 2, username: 'viewer', channel: 'example', category: 'spam', severity: 2});
  const yes = document.querySelector('[data-ans="1"]');
  const no = document.querySelector('[data-ans="0"]');
  for (const lang of ['ru', 'en', 'ua']) {
    translate(lang); translatedLeaves(env);
    assert.ok(yes.textContent.includes(ctx.t('dynamic.yes')));
    assert.ok(no.textContent.includes(ctx.t('dynamic.no')));
  }
  let body; ctx.api = async (_url, options) => { body = options.body; return {ok: true}; };
  await yes.onclick(); assert.equal(body.approved, true); assert.equal(body.account_id, 2);
});
