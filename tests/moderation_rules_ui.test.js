// Q04: сквозной UI-тест редактора модерации.
//
// UI-часть (этот файл): ключи action_ext в UI ровно совпадают с бэкендом
// (ACTION_EXT_CHOICES из app/moderation.py), селекты инициализируются, addModerationRule
// отправляет action_ext (в т.ч. «ban»), список правил показывает выбранное действие,
// редактор базы правил канала и таблица «категория → действие» на месте.
// Движковая часть (parse action_ext, category override, база только модераторам,
// ban через Helix-мок) исполняется Python-сьютами Q01–Q03 — см. docstring в PLAN_TODO.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const read = file => fs.readFileSync(path.join(__dirname, '..', file), 'utf8');

// Канонические ключи ACTION_EXT_CHOICES (app/moderation.py, Q01).
const EXPECTED_KEYS = [
  '', 'mask', 'block', 'timeout_600', 'timeout_3600', 'timeout_86400',
  'timeout_604800', 'timeout_1209600', 'ban',
];

function extractQuotedKeys(src, startMarker, endMarker) {
  const start = src.indexOf(startMarker);
  const end = src.indexOf(endMarker, start);
  assert.ok(start !== -1 && end !== -1, `не найден блок ${startMarker}`);
  const block = src.slice(start, end);
  return [...block.matchAll(/['"]([a-z0-9_]*)['"]\s*:/g)].map(m => m[1]);
}

function bootModerationUI() {
  const nodes = {};
  const apiCalls = [];
  const ctx = vm.createContext({
    console, URL, URLSearchParams,
    document: {
      getElementById: id => nodes[id] || null,
      createElement: () => ({ style: {}, classList: { add() {}, toggle() {} }, dataset: {} }),
      querySelectorAll: () => [],
      addEventListener() {},
    },
    $: id => nodes[id] || null,
    esc: v => String(v ?? ''),
    t: key => key,
    panelI18n: key => key,
    panelI18nAttrs: () => '',
    panelEnumI18n: (prefix, value) => prefix + value,
    toast() {},
    api: async (url, opts) => { apiCalls.push({ url, opts }); return { ok: true, id: 1 }; },
    showModal() {}, hideModal() {},
    hasTranslation: () => true,
    _currentBotId: 7,
    jopts: (method, body) => ({ method, body }),
    localStorage: { getItem: () => 'ru', setItem() {} },
  });
  ctx.window = ctx;
  vm.runInContext(read('static/app/08_providers_moderation.js'), ctx);
  return { ctx, nodes, apiCalls, run: code => vm.runInContext(code, ctx) };
}

const optionValues = html => [...String(html).matchAll(/value="([^"]*)"/g)].map(m => m[1]);

function selectStub(initialHtml = '') {
  const node = { _html: initialHtml };
  Object.defineProperty(node, 'innerHTML', {
    set(v) { node._html = String(v); node.options = optionValues(v).map(value => ({ value })); },
    get() { return node._html; },
  });
  node.innerHTML = initialHtml;
  return node;
}

test('ключи action_ext в UI ровно совпадают с ACTION_EXT_CHOICES бэкенда', () => {
  const src = read('static/app/08_providers_moderation.js');
  const start = src.indexOf('const MOD_RULE_ACTION_EXT');
  const end = src.indexOf('];', start);
  const block = src.slice(start, end);
  const keys = [...block.matchAll(/key:\s*'([^']*)'/g)].map(m => m[1]);
  assert.deepEqual(keys, EXPECTED_KEYS, 'MOD_RULE_ACTION_EXT = ровно ключи ACTION_EXT_CHOICES');

  const py = read('app/moderation.py');
  for (const key of EXPECTED_KEYS.filter(k => k && k !== 'auto')) {
    assert.ok(py.includes(`"${key}"`) || py.includes(`'${key}'`), `бэкенд знает ${key}`);
  }
  assert.ok(/ACTION_EXT_CHOICES[^=]*=/.test(py), 'словарь ACTION_EXT_CHOICES существует');
});

test('селекты действия в шаблонах содержат ровно те же значения', () => {
  const bots = read('templates/partials/bots.html');
  const botsSelect = bots.match(/<select id="modRuleActionExt"[^>]*>([\s\S]*?)<\/select>/);
  assert.ok(botsSelect, 'в bots.html есть селект modRuleActionExt');
  assert.deepEqual(optionValues(botsSelect[1]), EXPECTED_KEYS);

  const channels = read('templates/partials/channels.html');
  const chanSelect = channels.match(/<select id="channelBaseRuleExt"[^>]*>([\s\S]*?)<\/select>/);
  assert.ok(chanSelect, 'в channels.html есть селект channelBaseRuleExt');
  assert.deepEqual(optionValues(chanSelect[1]), EXPECTED_KEYS);
});

test('initModerationRuleForm заполняет пустой селект 9 опциями и не трогает заполненный', () => {
  const env = bootModerationUI();
  env.nodes.modRuleActionExt = selectStub('');
  env.run('initModerationRuleForm()');
  assert.equal(env.nodes.modRuleActionExt.options.length, 9);
  assert.match(env.nodes.modRuleActionExt.innerHTML, /value="ban"/);
  assert.match(env.nodes.modRuleActionExt.innerHTML, /value="timeout_1209600"/);

  env.nodes.modRuleActionExt = selectStub('<option value="x"></option>');
  env.run('initModerationRuleForm()');
  assert.equal(env.nodes.modRuleActionExt.innerHTML, '<option value="x"></option>');
});

test('addModerationRule отправляет action_ext, выбранный в селекте (ban доходит до API)', async () => {
  const env = bootModerationUI();
  env.nodes.modRulePattern = { value: 'плохослово' };
  env.nodes.modRuleCategory = { value: 'insult' };
  env.nodes.modRuleAction = { value: 'log' };
  env.nodes.modRuleActionExt = { value: 'ban' };
  env.nodes.modRuleSeverity = { value: '5' };
  env.nodes.modRuleChannel = { value: '' };
  await env.run('addModerationRule(_currentBotId)');
  const post = env.apiCalls.find(c => c.opts.method === 'POST');
  assert.ok(post, 'POST /moderation/rules ушёл');
  const body = post.opts.body;
  assert.equal(body.action_ext, 'ban', 'бан навсегда уходит в API как action_ext=ban');
  assert.equal(body.pattern, 'плохослово');
});

test('importModerationRules тоже передаёт action_ext', async () => {
  const env = bootModerationUI();
  env.nodes.modRuleImportText = { value: 'слово1\nслово2' };
  env.nodes.modRuleAction = { value: 'block' };
  env.nodes.modRuleActionExt = { value: 'timeout_86400' };
  env.nodes.modRuleCategory = { value: 'spam' };
  env.nodes.modRuleSeverity = { value: '3' };
  env.nodes.modRuleChannel = { value: '' };
  await env.run('importModerationRules(_currentBotId)');
  assert.equal(env.apiCalls[0].opts.body.action_ext, 'timeout_86400');
});

test('renderModerationRules показывает выбранное явное действие бейджем', () => {
  const env = bootModerationUI();
  env.nodes.moderationRulesList = { innerHTML: '' };
  env.run('renderModerationRules([{id:1, pattern:"слово", category:"insult", action:"block", severity:3, action_ext:"ban", enabled:1}])');
  assert.match(env.nodes.moderationRulesList.innerHTML, /panel\.mod\.ext_ban/);
  env.run('renderModerationRules([{id:2, pattern:"слово2", category:"spam", action:"block", severity:3, action_ext:"", enabled:1}])');
  assert.doesNotMatch(env.nodes.moderationRulesList.innerHTML, /panel\.mod\.ext_/);
});

test('редактор базы правил канала: отдельная страница (не модалка), засев пресета, кнопка в карточке канала', () => {
  const channels = read('templates/partials/channels.html');
  assert.match(channels, /id="channelSettingsTabRules"/);
  assert.doesNotMatch(channels, /id="channelBaseRulesModal"/, 'владелец 27.09: больше не всплывашка');
  assert.match(channels, /seedChannelBaseRules\(\)/);
  const bulk = read('static/app/19_channels_bulk.js');
  assert.match(bulk, /openChannelSettings\(this\.dataset\.channel\)/, 'единая кнопка «Настройки канала» в карточке (владелец 27.09: настоящая единая страница)');
  assert.match(bulk, /function closeChannelSettings\(/, 'общая функция закрытия страницы настроек канала');
  assert.match(bulk, /function openChannelSettings\(/, 'единая точка входа на страницу настроек канала');
  const mod = read('static/app/08_providers_moderation.js');
  for (const fn of ['openChannelBaseRules', 'loadChannelBaseRules', 'addChannelBaseRule',
    'toggleChannelBaseRule', 'deleteChannelBaseRule', 'seedChannelBaseRules']) {
    assert.ok(new RegExp(`(async )?function ${fn}\\(`).test(mod), `${fn} существует`);
  }
});

test('таблица «категория → действие» в роли модератора: 5 категорий, ключи действий', () => {
  const roles = read('static/app/06_roles.js');
  const start = roles.indexOf('const ROLE_CATPOLICY_CATEGORIES');
  const end = roles.indexOf('];', start);
  const cats = [...roles.slice(start, end).matchAll(/\['([a-z_]+)',/g)].map(m => m[1]);
  assert.deepEqual(cats, ['insult', 'hate', 'threat', 'sexual', 'spam']);

  const actionsStart = roles.indexOf('const ROLE_CATPOLICY_ACTIONS');
  const actionsEnd = roles.indexOf('];', actionsStart);
  const actionKeys = [...roles.slice(actionsStart, actionsEnd).matchAll(/\['([a-z0-9_]*)',/g)].map(m => m[1]);
  assert.deepEqual(actionKeys, EXPECTED_KEYS);

  assert.match(roles, /\['category_policy', 'role\.f\.category_policy', 'catpolicy', \{\}\]/);
  assert.match(roles, /roleF_\$\{key\}_\$\{cat\}/, 'форма собирает 5 селектов категории');
});

test('движковые сьюты Q01–Q03 на месте (parse/override/база-только-модераторам/Helix-мок)', () => {
  for (const f of ['tests/test_moderation_action_ext.py', 'tests/test_moderation_category_policy.py',
    'tests/test_moderation_base_rules.py']) {
    assert.ok(fs.existsSync(path.join(__dirname, '..', f)), `${f} существует`);
  }
  const actionExt = read('tests/test_moderation_action_ext.py');
  assert.match(actionExt, /test_ban_user_posts_without_duration/, 'ban через Helix-мок покрыт');
  const base = read('tests/test_moderation_base_rules.py');
  assert.match(base, /test_non_moderator_bot_ignores_channel_base/, 'база только модераторам покрыта');
  const cat = read('tests/test_moderation_category_policy.py');
  assert.match(cat, /test_policy_overrides_severity_ladder_for_custom_rule/, 'category override покрыт');
});
