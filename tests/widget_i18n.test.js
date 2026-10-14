const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');
const {environment, functionSource} = require('./panel_accessibility_harness');
const root = path.join(__dirname, '..');
const runtime = fs.readFileSync(path.join(root, 'widgets/_shared/i18n.js'), 'utf8');
const goals = fs.readFileSync(path.join(root, 'widgets/goals/index.html'), 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];

function localeEnv(search, pathname = '/widget/goals') {
  const env = environment();
  Object.assign(env.ctx, {URL, URLSearchParams, location: {search, pathname, origin: 'http://panel.test'}});
  vm.runInContext(runtime, env.ctx);
  env.ctx.WidgetI18n = env.ctx.window.WidgetI18n;
  return env;
}

test('UI locale precedence preserves legacy TTS voice lang', () => {
  for (const [search, route, expected] of [
    ['?ui_lang=en&lang=ru-RU', '/obs/tts', 'en'],
    ['?lang=en-US', '/obs/tts', 'ru'],
    ['?lang=en', '/widget/goals', 'en'],
    ['?lang=ua', '/widget/goals', 'ua'],
    ['?ui_lang=uk', '/widget/goals', 'ua'],
    ['?ui_lang=xx&lang=en', '/widget/goals', 'ru'],
  ]) {
    const {ctx, document} = localeEnv(search, route);
    assert.equal(ctx.WidgetI18n.lang, expected);
    assert.equal(document.documentElement.lang, expected === 'ua' ? 'uk' : expected);
  }
});

test('missing translations use Russian and unknown keys never leak', () => {
  const {ctx, element, document} = localeEnv('?ui_lang=en');
  ctx.WidgetI18n.add({ru: {'example': 'Привет, {name}', 'nested': '{one} {two}'}});
  assert.equal(ctx.WidgetI18n.t('example', {name: '<img onerror=x>'}), 'Привет, <img onerror=x>');
  assert.equal(ctx.WidgetI18n.t('nested', {one: '{two}', two: '$&'}), '{two} $&');
  for (const key of ['secret.internal.key', 'constructor', '__proto__', 'toString']) {
    assert.equal(ctx.WidgetI18n.t(key), 'Текст недоступен');
  }
  const node = element('button', {'data-widget-i18n': 'example', 'data-widget-i18n-title': 'missing'});
  ctx.WidgetI18n.apply(node);
  assert.equal(node.textContent, 'Привет, {name}');
  assert.equal(node.getAttribute('title'), 'Текст недоступен');
  assert.equal(node.children.length, 0);
  assert.equal(document.querySelectorAll('img').length, 0);
});

for (const lang of ['ru', 'en', 'ua']) {
  test(`Goals production preview, status, controls and user content: ${lang}`, async () => {
    const env = localeEnv(`?ui_lang=${lang}&preview=1&admin=1`);
    const {ctx, document, element} = env;
    const heading = element('h2', {id: 'title'}, document.body, 'Авторский заголовок');
    const list = element('ul', {id: 'list'});
    list.replaceChildren = () => { list.textContent = ''; };
    Object.defineProperty(list, 'innerHTML', {set(value) { assert.equal(value, ''); this.textContent = ''; }});
    element('div', {id: 'bar'});
    const summary = element('div', {id: 'summary'});
    Object.assign(ctx, {setTimeout() {}, setInterval() {}, widgetScopedUrl: value => value});
    vm.runInContext(goals, ctx);
    assert.equal(heading.textContent, 'Авторский заголовок');
    assert.equal(summary.textContent, ctx.WidgetI18n.t('goals.summary', {done: 1, total: 2, percent: 82}));
    const buttons = list.querySelectorAll('button');
    assert.equal(buttons.length, 4);
    assert.equal(buttons[0].getAttribute('aria-label'), ctx.WidgetI18n.t('goals.decrease'));
    assert.equal(buttons[1].getAttribute('aria-label'), ctx.WidgetI18n.t('goals.increase'));
    vm.runInContext('render([{id: 9, text: "<img src=x onerror=alert(1)>", percent: 10}])', ctx);
    assert.equal(list.querySelector('.label').textContent, '<img src=x onerror=alert(1)>');
    assert.equal(list.querySelectorAll('img').length, 0);
    ctx.fetch = async () => ({ok: true, json: async () => ({items: []})});
    await ctx.load();
    assert.equal(summary.textContent, ctx.WidgetI18n.t('goals.empty'));
    ctx.fetch = async () => ({ok: false, status: 503});
    await ctx.load();
    assert.equal(summary.textContent, ctx.WidgetI18n.t('goals.unavailable', {status: 503}));
    ctx.fetch = async () => { throw new Error('private internals'); };
    await ctx.load();
    assert.equal(summary.textContent, ctx.WidgetI18n.t('common.disconnected'));
    assert.ok(!summary.textContent.includes('private'));
  });
}

test('panel output URLs keep scope, voice language, appearance and user labels', async () => {
  const {ctx, storage} = localeEnv('');
  storage.set('lang', 'ua');
  vm.runInContext(functionSource('static/app/07_widgets.js', 'widgetOutputUrl'), ctx);
  const source = '/obs/tts?lang=en-US&channel=alpha&theme=light&label=%D0%A1%D0%B5%D0%B9%D1%87%D0%B0%D1%81';
  const result = new URL(ctx.widgetOutputUrl(source), ctx.location.origin);
  assert.equal(result.searchParams.get('ui_lang'), 'ua');
  for (const [key, value] of new URL(source, ctx.location.origin).searchParams) assert.equal(result.searchParams.get(key), value);
  const copied = [];
  ctx.navigator = {clipboard: {writeText: async value => copied.push(value)}};
  ctx.toast = () => {};
  vm.runInContext(functionSource('static/app/03_bots.js', 'copyWidgetUrl'), ctx);
  ctx.copyWidgetUrl(source);
  await Promise.resolve();
  assert.equal(copied[0], result.href);
  assert.equal(ctx.widgetOutputUrl('/api/widgets/public/goals'), '/api/widgets/public/goals');
  assert.equal(ctx.widgetOutputUrl('https://external.test/widget/goals'), 'https://external.test/widget/goals');
  ctx.localStorage.getItem = () => { throw new Error('denied'); };
  assert.equal(new URL(ctx.widgetOutputUrl('/widget/goals'), ctx.location.origin).searchParams.get('ui_lang'), 'ru');
});
