const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {functionSource} = require('./panel_accessibility_harness');
const read = file => fs.readFileSync(path.join(__dirname, '..', file), 'utf8');
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
const decode = value => value.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');

class Element {
  constructor() { this.children = []; this.style = {setProperty() {}}; this.dataset = {}; this.classList = {add() {}, toggle() {}}; }
  set textContent(value) { this.text = String(value ?? ''); this.html = null; }
  get textContent() { return this.text || ''; }
  set innerHTML(value) { this.html = value; }
  get innerHTML() { return this.html ?? String(this.text ?? '').replace(/[&<>]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;'}[c])); }
  appendChild(node) { this.children.push(node); node.parent = this; }
  remove() { if (this.parent) this.parent.children.splice(this.parent.children.indexOf(this), 1); }
  get firstChild() { return this.children[0]; }
  setAttribute() {}
}

function boot(lang, widget = false) {
  let locale = lang;
  const nodes = {feed: new Element(), dashboardEvents: new Element(), voiceControlSuggestions: new Element()};
  const leaves = [];
  const calls = [];
  const document = {
    documentElement: new Element(), body: new Element(), addEventListener() {},
    getElementById: id => nodes[id] || null,
    createElement: () => new Element(),
    querySelectorAll: selector => selector === '[data-mod-feed-field]' ? leaves : [],
  };
  const ctx = vm.createContext({document, console, URLSearchParams, URL, esc,
    location: new URL('http://offline.test/widget/mod-feed?ui_lang=' + lang),
    setTimeout() {}, setInterval() {}, localStorage: {getItem: () => locale, setItem: (_, value) => { locale = value; }},
    fetch: async url => { calls.push(url); return {json: async () => ({ok: true, events: []})}; },
    LANGS: {ru: {}, en: {}, ua: {}}, $: id => nodes[id], _allBots: [], _eventFeed: [],
    localizeLegacyNodes() {}, hasTranslation() { return false; }, fmtTime: () => '12:00',
  });
  ctx.window = ctx;
  if (widget) {
    vm.runInContext(read('widgets/_shared/i18n.js'), ctx);
    vm.runInContext(read('widgets/mod-feed/index.html').match(/<script>([^]*?)<\/script>/)[1], ctx);
  } else {
    vm.runInContext(functionSource('static/app.js', 'esc'), ctx);
    vm.runInContext(functionSource('static/app.js', 't'), ctx);
    vm.runInContext(read('static/app/24_dynamic_i18n.js'), ctx);
    for (const name of ['setLang', 'handleWSMessage', 'renderEventFeed']) vm.runInContext(functionSource('static/app.js', name), ctx);
    vm.runInContext(functionSource('static/app/10_stream_p4_p6.js', 'loadVoiceSuggestions'), ctx);
  }
  return {ctx, nodes, leaves, calls, run: code => vm.runInContext(code, ctx)};
}

const event = (key, params = {}, field = 'action') => ({kind: 'action', user: '<viewer>', text: 'USER', action: 'legacy action', localization: {[field]: {key, params}}});

for (const [lang, expected] of [['ru', 'Таймаут/блок применён'], ['en', 'Timeout/block applied'], ['ua', 'Таймаут/блок застосовано'], ['xx', 'Таймаут/блок применён']]) {
  test(`${lang}: panel and real OBS script render explicit caption, not user text`, () => {
    for (const widget of [false, true]) {
      const env = boot(lang, widget);
      const ev = event('mod-feed.caption.applied');
      ev.text = 'таймаут/блок применён <script>alert(1)</script>';
      assert.equal(env.ctx.modFeedField(ev, 'action'), expected);
      assert.equal(env.ctx.modFeedField(ev, 'text'), ev.text);
      if (widget) {
        env.ctx.show(ev);
        const html = env.nodes.feed.children.at(-1).innerHTML;
        assert.ok(html.includes(esc(ev.text)) && html.includes(expected));
        assert.ok(html.includes('&lt;viewer&gt;'));
        assert.ok(!html.includes('<script>'));
      } else {
        env.ctx.handleWSMessage({...ev, type: 'mod_feed'});
        const html = env.nodes.dashboardEvents.innerHTML;
        assert.ok(html.includes(expected) && html.includes(esc(ev.text)));
        assert.ok(!html.includes('<script>'));
      }
      assert.ok(env.calls.every(url => url.startsWith('/api/mod-feed/public/poll?')));
    }
  });
}

test('RU fallback for missing selected-language entry', () => {
  const panel = boot('en');
  delete panel.ctx.LANGS.en['mod-feed.caption.applied'];
  assert.equal(panel.ctx.modFeedField(event('mod-feed.caption.applied'), 'action'), 'Таймаут/блок применён');
  const widget = boot('en', true);
  widget.ctx.WidgetI18n.add({en: {'mod-feed.caption.applied': ''}});
  assert.equal(widget.ctx.modFeedField(event('mod-feed.caption.applied'), 'action'), 'Таймаут/блок применён');
});

test('legacy strings matching service captions/codes remain byte-for-byte data', () => {
  for (const widget of [false, true]) for (const lang of ['ru', 'en', 'ua']) {
    const {ctx} = boot(lang, widget);
    for (const text of ['таймаут/блок применён', 'slow_on', 'mod-feed.caption.applied', 'countdown:start', 'предлагаю таймаут 1 мин (swear)', '<b>{result}</b>']) {
      const ev = {text, action: text};
      assert.equal(ctx.modFeedField(ev, 'text'), text);
      assert.equal(ctx.modFeedField(ev, 'action'), text);
    }
  }
});

test('invalid and hostile descriptors fall back to legacy fields', () => {
  const invalid = [null, [], {key: '__proto__'}, {key: 'constructor'}, {key: []},
    {key: 'mod-feed.caption.timeout', params: {minutes: true}}, {key: 'mod-feed.caption.timeout', params: {minutes: Infinity}},
    {key: 'mod-feed.caption.moderation', params: {category: {toString: () => 'BAD'}}},
    {key: 'mod-feed.caption.moderation', params: {category: 'x'.repeat(201)}},
    {key: 'mod-feed.caption.stream_enable', params: {tool: '__proto__', result: 'done'}},
    {key: 'mod-feed.caption.stream_title', params: {value: 'title', result: 'constructor'}},
    {key: 'mod-feed.caption.result.done'}, {key: 'mod-feed.caption.rule', params: []}];
  for (const widget of [false, true]) {
    const {ctx} = boot('en', widget);
    for (const descriptor of invalid) assert.equal(ctx.modFeedField({text: 'USER', localization: {text: descriptor}}, 'text'), 'USER');
  }
});

test('interpolation preserves user parameters including braces and HTML', () => {
  for (const widget of [false, true]) {
    const {ctx} = boot('en', widget);
    const ev = event('mod-feed.caption.stream_title', {value: '<b>{result}</b>', result: 'done'}, 'text');
    assert.equal(ctx.modFeedField(ev, 'text'), 'Change title to “<b>{result}</b>” · Completed');
    const category = event('mod-feed.caption.category_severity', {category: '{severity}<img>', severity: 4});
    assert.equal(ctx.modFeedField(category, 'action'), 'Category: {severity}<img> · severity 4');
  }
});

test('all catalog entries have three locales and matching OBS values', () => {
  const panel = boot('ru'), widget = boot('ru', true);
  const entries = panel.run('MOD_FEED_CAPTIONS');
  assert.deepEqual(JSON.parse(JSON.stringify(entries)), JSON.parse(JSON.stringify(widget.run('MOD_FEED_CAPTIONS'))));
  for (const [key, values] of Object.entries(entries)) {
    assert.equal(values.length, 3, key);
    assert.ok(values.every(value => typeof value === 'string' && value.length > 0), key);
  }
});

test('panel language changes refresh captions without replacing user text or drafts', () => {
  const env = boot('ru');
  const ev = event('mod-feed.caption.timeout', {minutes: 5});
  ev.text = '\" onmouseover=\"alert(1)\"><img src=x> &amp;';
  const markup = env.ctx.panelModFeedField(ev, 'action');
  assert.ok(!markup.includes('onmouseover="alert(1)"'));
  const node = new Element();
  node.dataset = {modFeedField: 'action', modFeedEvent: decode(markup.match(/data-mod-feed-event="([^"]+)"/)[1])};
  const user = new Element(); user.textContent = '<b>таймаут/блок применён</b>';
  const draft = {value: 'unsaved draft'};
  env.leaves.push(node);
  for (const [lang, expected] of [['en', 'Timeout: 5 min'], ['ua', 'Таймаут 5 хв'], ['ru', 'Таймаут 5 мин']]) {
    env.ctx.setLang(lang);
    assert.equal(node.textContent, expected);
    assert.equal(user.textContent, '<b>таймаут/блок применён</b>');
    assert.equal(draft.value, 'unsaved draft');
  }
});

test('voice suggestions render localized action and literal transcript, with read-only API', async () => {
  const env = boot('en');
  env.ctx._voiceScope = () => ({accountId: 1, channel: 'ch'});
  const ev = event('mod-feed.caption.voice.countdown.start');
  ev.text = '<b>Таймер старт {result}</b>';
  ev.intent = {source: 'owner_voice', confidence: .1};
  const requests = [];
  env.ctx.api = async (...args) => { requests.push(args); return {intents: [ev]}; };
  await env.ctx.loadVoiceSuggestions();
  const html = env.nodes.voiceControlSuggestions.innerHTML;
  assert.ok(html.includes('Timer: start'));
  assert.ok(html.includes(esc(ev.text)));
  assert.equal(requests.length, 1);
  assert.equal(requests[0].length, 1);
  assert.ok(requests[0][0].startsWith('/api/mod-feed/events?'));
});
