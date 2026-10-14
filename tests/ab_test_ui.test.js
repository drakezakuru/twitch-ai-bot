// Владелец 27.09 (вечер): «слепая» A/B-панель промптов получила экран.
// Бэкенд (v8 Feature 3, ai_quality_db.py + ab_dashboard.py) существовал давно
// без единой строчки UI — здесь тест на карточку в вкладке «Память и знания».
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const read = file => fs.readFileSync(path.join(__dirname, '..', file), 'utf8');

test('карточка A/B теста в bots.html и i18n на месте', () => {
  const bots = read('templates/partials/bots.html');
  assert.match(bots, /id="abTestEnabled"/);
  assert.match(bots, /id="abTestVariantsList"/);
  assert.match(bots, /id="abTestSummary"/);
  assert.match(bots, /onclick="addAbTestVariant\(\)"/);

  const src = read('static/app.js');
  for (const key of ['abtest.title', 'abtest.enable', 'abtest.label', 'abtest.weight',
    'abtest.responses', 'abtest.leader', 'abtest.rec_leader', 'abtest.rec_drop']) {
    const count = (src.match(new RegExp(`'${key.replace('.', '\\.')}':`, 'g')) || []).length;
    assert.equal(count, 3, `${key} — ровно в ru/en/ua`);
  }
});

function bootAbTestUI() {
  const nodes = {};
  const apiCalls = [];
  const toasts = [];
  const ctx = vm.createContext({
    console,
    document: {
      getElementById: id => nodes[id] || null,
      querySelectorAll: () => [],
    },
    $: id => nodes[id] || null,
    esc: v => String(v ?? ''),
    t: key => key,
    toast: (msg, kind) => toasts.push({ msg, kind }),
    confirm: () => true,
    api: async (url, opts) => { apiCalls.push({ url, opts }); return { ok: true }; },
    jopts: (method, body) => ({ method, body }),
    setToggle(id, val) { const el = nodes[id]; if (el) el.active = !!val; },
    toggleChecked(id) { return !!nodes[id]?.active; },
    _currentBotId: 7,
  });
  ctx.window = ctx;
  vm.runInContext(read('static/app/05_bots_tabs.js'), ctx);
  return { ctx, nodes, apiCalls, toasts, run: code => vm.runInContext(code, ctx) };
}

test('loadAbTest грузит варианты, состояние тумблера и дашборд с рекомендацией', async () => {
  const env = bootAbTestUI();
  env.nodes.kbChannel = null;
  env.nodes.abTestEnabled = { active: false };
  env.nodes.abTestVariantsList = { innerHTML: '' };
  env.nodes.abTestSummary = { innerHTML: '' };
  vm.runInContext(`
    api = async (url) => {
      if (url.includes('/prompt-variants')) return { items: [
        { id: 1, label: 'A', weight: 70, system_prompt: 'Ты дружелюбный', count: 10, likes: 8, dislikes: 1, enabled: 1 },
        { id: 2, label: 'B', weight: 30, system_prompt: 'Ты саркастичный', count: 4, likes: 0, dislikes: 3, enabled: 1 },
      ] };
      if (url.includes('/ab-dashboard')) return { summary: { n_responses: 14, likes: 8, dislikes: 4, like_ratio: 0.67, leader: 'A' },
        variants: [{ id: 1, recommendation: 'leader' }, { id: 2, recommendation: 'drop' }] };
      if (url.includes('/analyzer')) return { use_ab_variants: true };
      return {};
    };`, env.ctx);
  await env.run('loadKnowledge(7)');
  assert.equal(env.nodes.abTestEnabled.active, true, 'тумблер включён по данным аккаунта');
  const html = env.nodes.abTestVariantsList.innerHTML;
  assert.match(html, /Ты дружелюбный/);
  assert.match(html, /abtest\.rec_leader/, 'вариант A помечен лидером');
  assert.match(html, /abtest\.rec_drop/, 'вариант B помечен на выключение');
  assert.match(env.nodes.abTestSummary.innerHTML, /abtest\.leader.*A|A.*abtest\.leader/s);
});

test('addAbTestVariant шлёт POST с ярлыком/весом/промптом и требует непустой промпт', async () => {
  const env = bootAbTestUI();
  env.nodes.abTestNewLabel = { value: 'C' };
  env.nodes.abTestNewWeight = { value: '20' };
  env.nodes.abTestNewPrompt = { value: '' };
  await env.run('addAbTestVariant()');
  assert.equal(env.apiCalls.length, 0, 'без промпта запрос не уходит');
  assert.ok(env.toasts.length, 'показана ошибка');

  env.nodes.abTestNewPrompt = { value: 'Ты язвительный критик' };
  await env.run('addAbTestVariant()');
  const post = env.apiCalls.find(c => c.url === '/api/accounts/7/prompt-variants' && c.opts.method === 'POST');
  assert.ok(post, 'POST на создание варианта ушёл');
  assert.equal(post.opts.body.label, 'C');
  assert.equal(post.opts.body.weight, 20);
  assert.equal(post.opts.body.system_prompt, 'Ты язвительный критик');
});

test('toggleAbTestEnabled и toggleAbTestVariant/deleteAbTestVariant шлют правильные вызовы', async () => {
  const env = bootAbTestUI();
  env.nodes.abTestEnabled = { active: true };
  await env.run('toggleAbTestEnabled()');
  const put = env.apiCalls.find(c => c.url === '/api/accounts/7/analyzer' && c.opts.method === 'PUT');
  assert.ok(put, 'PUT /analyzer ушёл');
  assert.equal(put.opts.body.use_ab_variants, true);

  env.apiCalls.length = 0;
  await env.run('toggleAbTestVariant(5, 0)');
  const toggle = env.apiCalls.find(c => c.url === '/api/accounts/7/prompt-variants/5' && c.opts.method === 'PUT');
  assert.ok(toggle);
  assert.equal(toggle.opts.body.enabled, false);

  env.apiCalls.length = 0;
  await env.run('deleteAbTestVariant(5)');
  const del = env.apiCalls.find(c => c.url === '/api/accounts/7/prompt-variants/5' && c.opts.method === 'DELETE');
  assert.ok(del);
});