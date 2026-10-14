const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {execFileSync} = require('node:child_process');
const {test} = require('node:test');
const {environment} = require('./panel_accessibility_harness');
const root = path.join(__dirname, '..');
const documents = JSON.parse(process.env.WIDGET_COMPAT_FIXTURES
  ? fs.readFileSync(process.env.WIDGET_COMPAT_FIXTURES, 'utf8')
  : execFileSync(process.env.PYTHON || 'python3', ['-c',
    'import json; from tests.test_widget_compat_i18n import compatibility_documents; print(json.dumps(compatibility_documents()))'],
  {cwd: root, encoding: 'utf8'}));
const runtime = fs.readFileSync(path.join(root, 'widgets/_shared/i18n.js'), 'utf8');
const retired = Object.keys(documents).filter(route => documents[route].includes('retired.reason'));
const periods = Object.keys(documents).filter(route => route.startsWith('/widget/top-donator-'));
const scripts = source => [...source.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)]
  .map(match => match[1]).filter(text => text.trim());

function setup(route, search) {
  const env = environment();
  const {ctx, document, element} = env;
  Object.assign(ctx, {URL, URLSearchParams, navigator: {},
    location: {pathname: route, search, origin: 'http://panel.test', host: 'panel.test', protocol: 'http:'},
    setTimeout() {}, setInterval() {}, clearTimeout() {}, clearInterval() {},
    fetch() { assert.fail('Unexpected fetch'); },
  });
  for (const match of documents[route].matchAll(/<(\w+)([^>]*(?:data-widget-i18n|\bid=)[^>]*)>/g)) {
    const attrs = Object.fromEntries([...match[2].matchAll(/([\w-]+)=["']([^"']*)["']/g)]
      .map(attribute => [attribute[1], attribute[2]]));
    element(match[1], attrs);
  }
  vm.runInContext(runtime, ctx);
  ctx.WidgetI18n = ctx.window.WidgetI18n;
  return env;
}

function ready(env) {
  for (const callback of env.document.listeners.DOMContentLoaded || []) callback();
}

for (const locale of ['ru', 'en', 'ua', 'uk', 'unknown']) {
  const resolved = locale === 'uk' ? 'ua' : locale === 'unknown' ? 'ru' : locale;
  for (const route of retired) {
    test(`Retired document title, reason and removal copy: ${route} ${locale}`, () => {
      const env = setup(route, `?ui_lang=${locale}&lang=en`);
      for (const script of scripts(documents[route])) vm.runInContext(script, env.ctx);
      ready(env);
      const {document, ctx} = env;
      assert.equal(ctx.WidgetI18n.lang, resolved);
      assert.equal(document.documentElement.lang, resolved === 'ua' ? 'uk' : resolved);
      for (const node of document.querySelectorAll('[data-widget-i18n]')) {
        assert.equal(node.textContent, ctx.WidgetI18n.t(node.getAttribute('data-widget-i18n')));
        assert.ok(node.textContent && !node.textContent.includes('Текст недоступен'));
      }
      const reason = document.querySelectorAll('[data-widget-i18n]')
        .find(node => node.getAttribute('data-widget-i18n') === 'retired.reason');
      assert.match(reason.textContent,
        resolved === 'en' ? /retired/ : resolved === 'ua' ? /виведено/ : /выведен/);
      if (resolved !== 'ru') {
        const labels = JSON.parse(documents[route].split('WidgetI18n.add(')[1].split(');</script>')[0]);
        ctx.WidgetI18n.add({[resolved]: {'retired.title': '', 'retired.reason': ''}});
        ctx.WidgetI18n.apply();
        assert.equal(document.querySelector('h1').textContent, labels.ru['retired.title']);
        assert.equal(reason.textContent, labels.ru['retired.reason']);
      }
    });
  }

  test(`Legacy chat localizes only metadata and keeps safe messages: ${locale}`, () => {
    const env = setup('/obs-widget', `?ui_lang=${locale}`);
    const {ctx, document, element} = env;
    const connections = [];
    ctx.WebSocket = class {constructor(url) { this.url = url; connections.push(this); }};
    document.createTextNode = text => {
      const node = document.createElement('text'); node.nodeType = 3; node.textContent = text; return node;
    };
    const chat = document.getElementById('chat');
    Object.defineProperty(chat, 'firstChild', {get: () => chat.children[0]});
    chat.removeChild = node => node.remove();
    for (const script of scripts(documents['/obs-widget'])) vm.runInContext(script, ctx);
    ready(env);
    assert.equal(connections.length, 1);
    assert.equal(connections[0].url, 'ws://panel.test/ws');
    assert.equal(chat.getAttribute('aria-label'), ctx.WidgetI18n.t('legacy_chat.messages'));
    assert.equal(document.querySelector('title').textContent, ctx.WidgetI18n.t('legacy_chat.title'));
    const send = payload => connections[0].onmessage({data: JSON.stringify(payload)});
    send({type: 'not-chat', author: 'ignored', message: 'ignored'});
    assert.equal(chat.children.length, 0);
    for (let i = 0; i < 35; i++) send({type: 'chat', author: `Читач${i}`, message: `Message ${i}`});
    assert.equal(chat.children.length, 30);
    assert.equal(chat.children[0].textContent, 'Читач5:Message 5');
    const text = '<img src=x onerror=alert(1)> Привет / Hello / Привіт';
    send({type: 'chat', author: '<b>Автор</b>', message: text});
    const last = chat.children.at(-1);
    ctx.WidgetI18n.apply();
    assert.equal(last.textContent, '<b>Автор</b>:' + text);
    assert.equal(last.children[1].nodeType, 3);
    assert.equal(chat.querySelectorAll('img').length, 0);
    assert.equal(chat.children.length, 30);
    assert.equal(ctx.WidgetI18n.lang, resolved);
  });

  for (const route of ['/widget/moderator-media', '/api/moderator-media/preview']) {
    test(`Protected media metadata preserves silent output/preview: ${route} ${locale}`, async () => {
      const env = setup(route, `?ui_lang=${locale}&account_id=2&channel=alpha&token=local-test`);
      const {ctx, document} = env;
      const calls = [];
      ctx.fetch = async url => {
        calls.push(url); return {ok: true, json: async () => ({kill_switch: true})};
      };
      ctx.cue = document.getElementById('cue');
      if (ctx.cue) ctx.cue.replaceChildren = () => { ctx.cue.textContent = ''; };
      for (const script of scripts(documents[route])) vm.runInContext(script, ctx);
      ready(env);
      await Promise.resolve(); await Promise.resolve();
      assert.equal(document.querySelector('title').textContent, ctx.WidgetI18n.t('moderator_media.title'));
      assert.equal(ctx.WidgetI18n.lang, resolved);
      if (route.endsWith('/preview')) {
        assert.equal(calls.length, 0);
        assert.equal(document.getElementById('cue'), null);
        assert.ok(documents[route].includes('data-safe-preview="true" aria-hidden="true"'));
      } else {
        assert.deepEqual(calls, ['/api/moderator-media/public/state?account_id=2&channel=alpha&token=local-test']);
        assert.equal(ctx.cue.textContent, '');
      }
    });
  }

  for (const route of periods) {
    test(`Historical period preview, errors and owner content: ${route} ${locale}`, async () => {
      const env = setup(route, `?ui_lang=${locale}&preview=1&channel=alpha`);
      const {ctx, document} = env;
      for (const script of scripts(documents[route])) vm.runInContext(script, ctx);
      ready(env);
      const list = document.getElementById('list');
      assert.equal(document.getElementById('title').textContent, ctx.WidgetI18n.t('top-donator.title'));
      assert.equal(vm.runInContext('PERIOD', ctx), route.split('-').at(-1));
      ctx.render({title: 'Топ донатеров <user title>', donors: [{username: '<img src=x>', total: 7}]});
      assert.equal(document.getElementById('title').textContent, 'Топ донатеров <user title>');
      assert.ok(list.innerHTML.includes('&lt;img src=x&gt;'));
      ctx.render({title: 'User title', donors: []});
      assert.ok(list.innerHTML.includes(ctx.WidgetI18n.t('top-donator.empty')));
      ctx.fetch = async () => ({ok: false, status: 503});
      await ctx.poll();
      assert.ok(list.innerHTML.includes(ctx.WidgetI18n.t('common.unavailable_http', {status: 503})));
    });
  }
}

test('Compatibility pages inherit legacy lang and Russian unknown-locale fallback', () => {
  for (const route of Object.keys(documents)) {
    assert.equal(setup(route, '?lang=en').ctx.WidgetI18n.lang, 'en');
    assert.equal(setup(route, '?lang=uk').ctx.WidgetI18n.lang, 'ua');
    assert.equal(setup(route, '?ui_lang=unsupported&lang=en').ctx.WidgetI18n.lang, 'ru');
    assert.equal(setup(route, '').ctx.WidgetI18n.lang, 'ru');
  }
  for (const [search, expected] of [['?lang=en-US', 'ru'], ['?ui_lang=ua&lang=en-US', 'ua']]) {
    const env = setup('/obs-widget', search);
    env.ctx.location.pathname = '/obs/tts';
    vm.runInContext(runtime, env.ctx);
    assert.equal(env.ctx.window.WidgetI18n.lang, expected);
    assert.equal(new URLSearchParams(env.ctx.location.search).get('lang'), 'en-US');
  }
});
