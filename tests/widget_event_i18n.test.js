const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const ROOT = path.join(__dirname, '..', 'widgets');
const WIDGETS = ['follower-ticker', 'latest-event-card', 'recent-events', 'now-playing',
  'chat-roulette', 'anime-runner', 'blur-guard-v2', 'tts-raw', 'tts-bot',
  'tts-chat-overlay', 'chat-reader', 'chat-highlight', 'lower-third', 'mod-feed', 'media-share'];
const LOCALES = ['ru', 'en', 'ua'];
const read = widget => fs.readFileSync(path.join(ROOT, widget, 'index.html'), 'utf8');
const escape = value => String(value).replace(/[&<>\"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const decode = value => value.replace(/&(amp|lt|gt|quot|#39);/g, (_, entity) => ({amp: '&', lt: '<', gt: '>', quot: '"', '#39': "'"}[entity]));

class Element {
  constructor(tag, text = '') {
    this.tagName = tag;
    this.rawText = text;
    this.attributes = {};
    this.childNodes = [];
    this.parentNode = null;
    this.style = {setProperty(name, value) { this[name] = value; }};
    this.dataset = {};
    this.scrollWidth = 500;
    this.classList = {
      contains: name => this.className.split(/\s+/).includes(name),
      add: (...names) => { this.className = [...new Set([...this.className.split(/\s+/).filter(Boolean), ...names])].join(' '); },
      remove: (...names) => { this.className = this.className.split(/\s+/).filter(name => !names.includes(name)).join(' '); },
      toggle: (name, force) => {
        const on = force ?? !this.classList.contains(name);
        this.classList[on ? 'add' : 'remove'](name);
        return on;
      },
    };
  }
  get className() { return this.attributes.class || ''; }
  set className(value) { this.attributes.class = value; }
  get id() { return this.attributes.id; }
  set id(value) { this.attributes.id = value; }
  get children() { return this.childNodes.filter(node => node.tagName !== '#text'); }
  get firstChild() { return this.childNodes[0]; }
  get textContent() { return this.rawText + this.childNodes.map(node => node.textContent).join(''); }
  set textContent(value) {
    this.childNodes.forEach(node => { node.parentNode = null; });
    this.childNodes = [];
    this.rawText = String(value ?? '');
  }
  get innerHTML() { return escape(this.rawText) + this.childNodes.map(node => node.tagName === '#text' ? escape(node.rawText) : `<${node.tagName}>${node.innerHTML}</${node.tagName}>`).join(''); }
  set innerHTML(value) { this.textContent = ''; parseInto(this, String(value)); }
  appendChild(node) { node.parentNode = this; this.childNodes.push(node); return node; }
  removeChild(node) { this.childNodes.splice(this.childNodes.indexOf(node), 1); node.parentNode = null; }
  remove() { this.parentNode?.removeChild(this); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  matches(selector) {
    if (selector.startsWith('[')) return Object.hasOwn(this.attributes, selector.slice(1, -1));
    if (selector.startsWith('.')) return this.classList.contains(selector.slice(1));
    if (selector.startsWith('#')) return this.id === selector.slice(1);
    return this.tagName === selector;
  }
  querySelectorAll(selector) { return this.children.flatMap(node => [...(node.matches(selector) ? [node] : []), ...node.querySelectorAll(selector)]); }
  getBoundingClientRect() { return {left: 0, top: 0, width: 480, height: 160}; }
}

function parseInto(root, html) {
  const stack = [root];
  const voidTags = new Set(['meta', 'link', 'img', 'input', 'br', 'hr']);
  for (const token of html.match(/<!--[^]*?-->|<[^>]*>|[^<]+/g) || []) {
    if (token.startsWith('<!')) continue;
    if (token.startsWith('</')) { if (stack.length > 1) stack.pop(); continue; }
    if (token.startsWith('<')) {
      const tag = token.match(/^<([\w-]+)/)?.[1];
      if (!tag) continue;
      const node = new Element(tag);
      const attrs = token.slice(tag.length + 1, -1);
      for (const match of attrs.matchAll(/([\w-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g)) {
        node.setAttribute(match[1], decode(match[2] ?? match[3] ?? match[4] ?? ''));
      }
      stack.at(-1).appendChild(node);
      if (!voidTags.has(tag) && !token.endsWith('/>')) stack.push(node);
    } else {
      stack.at(-1).appendChild(new Element('#text', decode(token)));
    }
  }
}

function renderTemplate(html, options = {}) {
  const values = {
    TITLE: options.title || '', TITLE_OVERRIDE: '', THEME: 'neon', THEME_OVERRIDE: '',
    CHANNEL: '""', ROLE: '"any"', LANG: JSON.stringify(options.speechLang || 'ru-RU'),
    RATE: '1.25', VOL: '0.7', MAXCHARS: '250', DESIGN_POS: '"bl"',
    DESIGN_SHOW_STATUS: 'true', DESIGN_SCALE: '1', DESIGN_HOLD_MS: '5000',
    ACCOUNT_ID: '1', MAX_MSGS: '5', RETAIN_MS: '5000', TTS_FILTER: '"all"',
  };
  return html.replace(/__([A-Z_]+)__/g, (_, name) => values[name] ?? '');
}

async function boot(widget, options = {}) {
  const query = options.query ?? '?preview=1&ui_lang=' + (options.lang || 'ru');
  const html = renderTemplate(read(widget), options);
  const document = new Element('document');
  parseInto(document, html.replace(/<(script|style)\b[^>]*>[^]*?<\/\1>/g, ''));
  document.documentElement = document.querySelectorAll('html')[0];
  document.body = document.querySelectorAll('body')[0];
  document.head = document.querySelectorAll('head')[0];
  document.getElementById = id => document.querySelectorAll('#' + id)[0] || null;
  document.createElement = tag => new Element(tag);
  const ready = [];
  document.addEventListener = (name, callback) => { if (name === 'DOMContentLoaded') ready.push(callback); };
  const timers = [], sockets = [], connections = [], queue = [], dictionaries = [];
  let response = {ok: true, status: 200, json: async () => []};
  const location = new URL('http://offline.test' + (options.pathname || '/widget/' + widget) + query);
  class Socket {
    static OPEN = 1;
    constructor(url) { this.url = url; this.readyState = 1; this.sent = []; sockets.push(this); }
    send(value) { this.sent.push(JSON.parse(value)); }
    close() {}
  }
  const context = vm.createContext({
    document, location, URL, URLSearchParams, navigator: {}, console,
    innerWidth: 1280, innerHeight: 720, performance: {now: () => 0},
    addEventListener() {}, requestAnimationFrame() {},
    setTimeout(callback) { timers.push(callback); return timers.length; },
    clearTimeout(id) { timers[id - 1] = null; },
    setInterval(callback) { timers.push(callback); return timers.length; },
    clearInterval(id) { timers[id - 1] = null; },
    fetch: async () => { if (response instanceof Error) throw response; return response; },
    widgetScopedUrl: url => url,
    WebSocket: Socket,
    CharacterCore: {start: () => ({react() {}})},
    TtsCore: {
      queue: () => ({push(item) { queue.push(item); item.onStart?.(); }}),
      outputAllowed: async () => true,
      connect(config) { connections.push(config); if (options.openImmediately) config.onOpen?.(); },
    },
    speechSynthesis: {getVoices: () => []},
  });
  context.window = context;
  vm.runInContext(fs.readFileSync(path.join(ROOT, '_shared', 'i18n.js'), 'utf8'), context);
  const add = context.WidgetI18n.add;
  context.WidgetI18n.add = translations => {
    dictionaries.push(translations);
    if (options.omitEnglish) delete translations.en[options.omitEnglish];
    add(translations);
  };
  if (widget === 'media-share') vm.runInContext(fs.readFileSync(path.join(ROOT, '_shared', 'media-share-core.js'), 'utf8'), context);
  for (const match of html.matchAll(/<script\b([^>]*)>([^]*?)<\/script>/g)) {
    if (!/\bsrc=/.test(match[1])) vm.runInContext(match[2], context, {filename: widget + '/index.html'});
  }
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  ready.forEach(callback => callback());
  return {
    context, document, dictionaries, timers, sockets, connections, queue,
    node: id => document.getElementById(id),
    run: code => vm.runInContext(code, context),
    respond: value => { response = value; },
  };
}

for (const lang of LOCALES) {
  test(`${lang}: all fifteen production widgets compile and register complete dictionaries`, async () => {
    for (const widget of WIDGETS) {
      const app = await boot(widget, {lang});
      assert.equal(app.context.WidgetI18n.lang, lang, widget);
      assert.equal(app.document.documentElement.lang, lang === 'ua' ? 'uk' : lang, widget);
      assert.equal(app.dictionaries.length, 1, widget);
      const dict = app.dictionaries[0];
      for (const locale of LOCALES) {
        assert.deepEqual(Object.keys(dict[locale]).sort(), Object.keys(dict.ru).sort(), widget);
        for (const [key, text] of Object.entries(dict[locale])) {
          assert.ok(key.startsWith(widget + '.'), key);
          assert.equal(typeof text, 'string', key);
          assert.ok(text.length > 0, key);
          assert.doesNotMatch(text, /__(?:[A-Z_]+)__/);
        }
      }
      for (const node of app.document.querySelectorAll('[data-widget-i18n]')) {
        assert.equal(node.textContent, app.context.WidgetI18n.t(node.getAttribute('data-widget-i18n')), widget);
      }
      assert.equal(app.queue.length, 0, widget + ': preview must not speak');
      assert.equal(app.sockets.length, 0, widget + ': preview must not connect');
    }
  });

  test(`${lang}: event types and amounts translate without rewriting viewer names`, async () => {
    const latest = await boot('latest-event-card', {lang});
    latest.run(`showCard({kind:'raid', username:'Мой <viewer>', amount:42})`);
    assert.equal(latest.node('username').textContent, 'Мой <viewer>');
    assert.equal(latest.node('kindLabel').textContent,
      latest.context.WidgetI18n.t('latest-event-card.raid') + ' (' + latest.context.WidgetI18n.t('latest-event-card.viewers', {count: 42}) + ')');
    for (const kind of ['unknown_internal_event', '__proto__', 'constructor']) {
      latest.context.eventKind = kind;
      latest.run('showCard({kind:eventKind})');
      assert.equal(latest.node('kindLabel').textContent, latest.context.WidgetI18n.t('latest-event-card.manual'));
      assert.equal(latest.node('username').textContent, latest.context.WidgetI18n.t('common.viewer'));
      assert.equal(latest.node('icon').textContent, '🎉');
    }
    const recent = await boot('recent-events', {lang});
    recent.run(`draw([{kind:'follow',username:'<img onerror=x> & User'}, {kind:'raw_future_kind'}])`);
    assert.ok(recent.node('events').textContent.includes('<img onerror=x> & User'));
    assert.equal(recent.node('events').querySelectorAll('img').length, 0);
    assert.ok(recent.node('events').textContent.includes(recent.context.WidgetI18n.t('recent-events.follow')));
    assert.ok(recent.node('events').textContent.includes(recent.context.WidgetI18n.t('recent-events.manual')));
    assert.ok(!recent.node('events').textContent.includes('raw_future_kind'));
    const ticker = await boot('follower-ticker', {lang});
    ticker.run(`render([{kind:'cheer',username:'<Viewer>',amount:12}])`);
    assert.ok(ticker.node('track').textContent.includes('@<Viewer>'));
    assert.ok(ticker.node('track').textContent.includes('12'));
    ticker.run(`render([{kind:'constructor',username:'Custom user'}])`);
    assert.ok(ticker.node('track').textContent.includes('Custom user'));
    assert.ok(!ticker.node('track').textContent.includes('function'));
    ticker.run('render([])');
    assert.equal(ticker.node('track').textContent, ticker.context.WidgetI18n.t('follower-ticker.empty'));
    ticker.respond({ok: false, status: 503});
    await ticker.run('poll()');
    assert.equal(ticker.node('track').textContent, ticker.context.WidgetI18n.t('common.unavailable_http', {status: 503}));
    ticker.respond(new Error('private error'));
    await ticker.run('poll()');
    assert.equal(ticker.node('track').textContent, ticker.context.WidgetI18n.t('common.disconnected'));
  });

  test(`${lang}: now-playing defaults localize but configured labels and track content survive`, async () => {
    const app = await boot('now-playing', {lang});
    app.run(`apply({kind:'game',text:'User title',subtext:'User artist'})`);
    assert.equal(app.node('labelText').textContent, app.context.WidgetI18n.t('now-playing.game'));
    assert.equal(app.node('text').textContent, 'User title');
    assert.equal(app.node('subtext').textContent, 'User artist');
    app.run(`apply({kind:'constructor',text:'Custom'})`);
    assert.equal(app.node('labelText').textContent, app.context.WidgetI18n.t('now-playing.now'));
    assert.equal(app.node('cover').textContent, '✨');
    for (const options of [{title: 'Моя музыка'}, {title: 'Saved title', query: '?preview=1&ui_lang=' + lang + '&label=My%20label'}]) {
      const configured = await boot('now-playing', {lang, ...options});
      configured.run(`apply({kind:'music',text:'Track'})`);
      assert.equal(configured.node('labelText').textContent, options.query ? 'My label' : options.title);
    }
    app.respond(new Error('offline'));
    await app.run('poll()');
    assert.equal(app.node('np').classList.contains('hidden'), true);
  });

  test(`${lang}: speech UI translates without changing payload language or URL speech cleanup`, async () => {
    const raw = await boot('tts-raw', {lang, speechLang: 'de-DE', pathname: '/obs/tts', query: '?lang=de-DE&ui_lang=' + lang, openImmediately: true});
    assert.equal(raw.node('status').textContent, raw.context.WidgetI18n.t('tts-raw.connected'));
    raw.connections[0].onMessage({message: 'Hallo https://example.invalid/secret 😀', author: 'User nickname', badges: []});
    assert.equal(raw.queue.length, 1);
    const speech = raw.queue[0].speech;
    assert.equal(speech.lang, 'de-DE');
    assert.equal(speech.rate, 1.25);
    assert.equal(speech.volume, 0.7);
    assert.equal(speech.text, 'Hallo  ссылка  ');
    assert.equal(raw.node('current').textContent, 'User nickname: Hallo  ссылка  ');
    raw.context.WidgetI18n.apply();
    assert.equal(raw.node('current').textContent, 'User nickname: Hallo  ссылка  ');
    raw.connections[0].onClose();
    assert.equal(raw.node('status').textContent, raw.context.WidgetI18n.t('tts-raw.reconnecting'));
    const bot = await boot('tts-bot', {lang, query: '?ui_lang=' + lang, openImmediately: true});
    assert.equal(bot.node('status').textContent, bot.context.WidgetI18n.t('tts-bot.waiting'));
    bot.connections[0].onMessage({provider: 'web_speech', speaker: 'Автор', text: 'Original speech', display_text: '<User text>', emotion: 'happy', voice: 'saved-voice', rate: 1.1});
    assert.equal(bot.node('speaker-name').textContent, 'Автор');
    assert.equal(bot.node('text').textContent, '<User text>');
    assert.equal(bot.node('emotion').textContent, bot.context.WidgetI18n.t('tts-bot.happy'));
    assert.equal(bot.queue[0].speech.lang, 'ru-RU');
    assert.equal(bot.queue[0].speech.text, 'Original speech');
    assert.equal(bot.queue[0].speech.voice, 'saved-voice');
    bot.connections[0].onMessage({text: 'Message', emotion: 'internal_emotion'});
    assert.equal(bot.node('emotion').textContent, bot.context.WidgetI18n.t('tts-bot.neutral'));
    bot.connections[0].onClose();
    assert.equal(bot.node('status').textContent, bot.context.WidgetI18n.t('common.disconnected'));
    const overlay = await boot('tts-chat-overlay', {query: '?ui_lang=' + lang, openImmediately: true});
    assert.equal(overlay.node('statusText').textContent, '');
    overlay.connections[0].onMessage({speaker: 'Имя', display_text: '<My message>'});
    assert.ok(overlay.node('tts-chat').textContent.includes('Имя:<My message>'));
    overlay.connections[0].onClose();
    assert.equal(overlay.node('statusText').textContent, overlay.context.WidgetI18n.t('common.disconnected'));
  });

  test(`${lang}: roulette, runner, highlight, reader and lower-third preserve user content`, async () => {
    const roulette = await boot('chat-roulette', {lang});
    roulette.run(`renderNames(['Viewer'])`);
    assert.equal(roulette.node('idle').textContent, '🎰' + roulette.context.WidgetI18n.t('chat-roulette.few'));
    const runner = await boot('anime-runner', {lang});
    runner.run(`reactToEvent({kind:'follow',username:'Custom Nick'})`);
    assert.equal(runner.node('lane').querySelectorAll('.say').at(-1).textContent,
      runner.context.WidgetI18n.t('anime-runner.greeting', {user: 'Custom Nick'}));
    const highlight = await boot('chat-highlight', {lang});
    highlight.run(`show({author:'My Nick',text:'Мой текст',display_sec:0})`);
    assert.equal(highlight.node('bAuthor').textContent, 'My Nick');
    assert.equal(highlight.node('bMsg').textContent, 'Мой текст');
    const lower = await boot('lower-third', {lang});
    lower.run(`apply({visible:true,name:'My Name',tagline:'Моя подпись',social:'@custom'})`);
    assert.equal(lower.node('name').textContent, 'My Name');
    assert.equal(lower.node('tagline').textContent, 'Моя подпись');
    const reader = await boot('chat-reader', {query: '?preview=1&ui_lang=' + lang + '&label=My%20label'});
    reader.run(`show('Original message')`);
    assert.equal(reader.node('who').textContent, '🗣 My label');
    assert.equal(reader.node('text').textContent, 'Original message');
    const mod = await boot('mod-feed', {lang});
    mod.run(`show({kind:'action',user:'My User',text:'User content',action:'User action'})`);
    assert.ok(mod.node('feed').textContent.includes('My User User contentUser action'));
  });

  test(`${lang}: blur controls and modes localize while feedback machine values stay unchanged`, async () => {
    const blur = await boot('blur-guard-v2', {query: '?ui_lang=' + lang + '&mode=manual'});
    const socket = blur.sockets[0];
    socket.onopen();
    assert.equal(socket.sent[0].mode, 'manual');
    blur.context.BlurGuard.on({source: 'manual', persistent: false});
    assert.equal(blur.node('statusText').textContent, blur.context.WidgetI18n.t('blur-guard-v2.on'));
    assert.equal(blur.node('modeBadge').textContent, blur.context.WidgetI18n.t('blur-guard-v2.manual'));
    assert.equal(blur.node('modeBadge').title, blur.context.WidgetI18n.t('blur-guard-v2.source', {source: blur.context.WidgetI18n.t('blur-guard-v2.manual')}));
    for (const [id, value] of [['btnFalse', 'false_positive'], ['btnMissed', 'missed'], ['btnGood', 'correct']]) {
      blur.node(id).onclick();
      assert.equal(socket.sent.at(-1).feedback, value);
      assert.equal(socket.sent.at(-1).blur_mode, 'gaussian');
      assert.equal(socket.sent.at(-1).active, true);
    }
    blur.context.BlurGuard.on({persistent: true, source: 'private_internal_source'});
    assert.equal(blur.node('modeBadge').textContent, blur.context.WidgetI18n.t('blur-guard-v2.persist'));
    assert.ok(!blur.node('modeBadge').title.includes('private_internal_source'));
    socket.onclose();
    assert.equal(blur.node('conn').textContent, blur.context.WidgetI18n.t('blur-guard-v2.offline'));
  });

  test(`${lang}: Media Share localizes state copy with safe fallback and keeps titles`, async () => {
    const media = await boot('media-share', {query: '?preview=1&lang=ru&ui_lang=' + lang});
    assert.equal(media.context.WidgetI18n.lang, lang);
    assert.equal(media.node('idle').textContent, media.run('TEXT[widgetLang].empty'));
    media.run(`showInfo('My requested title')`);
    assert.equal(media.node('info').textContent, 'My requested title');
    assert.equal(media.run("tx('not_a_real_state')"), media.context.WidgetI18n.t('common.unavailable'));
    assert.equal(media.run("tx('constructor')"), media.context.WidgetI18n.t('common.unavailable'));
    if (lang !== 'ru') {
      media.run('delete TEXT[widgetLang].offline');
      assert.equal(media.run("tx('offline')"), media.run('TEXT.ru.offline'));
    }
  });
}

test('live failure-hiding policies are unchanged across UI languages', async () => {
  for (const lang of LOCALES) {
    const highlight = await boot('chat-highlight', {lang});
    const lower = await boot('lower-third', {lang});
    const roulette = await boot('chat-roulette', {lang});
    const latest = await boot('latest-event-card', {lang});
    for (const app of [highlight, lower, roulette, latest]) {
      app.respond(new Error('private transport exception'));
      await app.run('poll()');
    }
    assert.equal(highlight.node('bubble').classList.contains('show'), false);
    assert.equal(highlight.node('bubble').classList.contains('hide'), true);
    assert.equal(lower.node('lt').classList.contains('show'), false);
    assert.equal(roulette.document.body.style.display, 'none');
    assert.equal(latest.node('card').classList.contains('show'), true);
    const mod = await boot('mod-feed', {query: '?ui_lang=' + lang});
    mod.respond(new Error('private transport exception'));
    await mod.run('poll()');
    assert.equal(mod.node('feed').textContent, '');
    mod.run(`KINDS.push('constructor'); show({kind:'constructor'})`);
    assert.ok(mod.node('feed').textContent.includes(mod.context.WidgetI18n.t('mod-feed.event')));
    assert.ok(!mod.node('feed').textContent.includes('function'));
    const recent = await boot('recent-events', {query: '?ui_lang=' + lang});
    recent.respond(new Error('private transport exception'));
    await recent.run('load()');
    assert.equal(recent.node('events').textContent, '');
  }
});

test('shared Russian fallback is used for absent selected-language keys, never the key', async () => {
  const app = await boot('latest-event-card', {lang: 'en', omitEnglish: 'latest-event-card.follow'});
  app.run(`showCard({kind:'follow',username:'Untouched'})`);
  assert.equal(app.node('kindLabel').textContent, 'Новый фолловер');
  assert.equal(app.node('username').textContent, 'Untouched');
  assert.ok(!app.context.WidgetI18n.t('private_missing_key').includes('private_missing_key'));
});

test('/obs/tts legacy lang remains speech-only unless ui_lang is supplied', async () => {
  for (const lang of ['en', 'ua', 'en-US']) {
    const app = await boot('tts-raw', {pathname: '/obs/tts', query: '?preview=1&lang=' + lang, speechLang: lang});
    assert.equal(app.context.WidgetI18n.lang, 'ru');
    assert.equal(app.node('status').textContent, '🎙 TTS подключён');
    assert.equal(app.run('LANG'), lang);
  }
  const legacy = await boot('latest-event-card', {query: '?preview=1&lang=en'});
  assert.equal(legacy.context.WidgetI18n.lang, 'en');
});
