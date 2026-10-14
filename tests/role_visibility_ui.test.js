const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

function classes() {
  const values = new Set();
  return { add: (...xs) => xs.forEach(x => values.add(x)), remove: (...xs) => xs.forEach(x => values.delete(x)), contains: x => values.has(x),
    toggle(x, on) { on ??= !values.has(x); on ? values.add(x) : values.delete(x); } };
}
function element(id) {
  return {id, value:'', innerHTML:'', textContent:'', classList:classes(), dataset:{},
    closest() { return this; }, appendChild(child) { child.parentElement = this; }, querySelectorAll:()=>[]};
}
function harness() {
  const groups = ['overview','brain-x','identity','flow','moderation','voice','memory','advanced'].map(group => ({dataset:{botGroup:group},classList:classes()}));
  const tabs = ['general','brain-x','persona','channels','attention','triggers','events','filters','chat-users','moderation','tts','voice-clones','memory','streamer','knowledge','snippets','logs','files'].map(name => element(`botTab-${name}`));
  const buttons = tabs.map(tab => ({dataset:{botTab:tab.id.slice(7)},classList:classes()}));
  const nodes = new Map(tabs.map(tab => [tab.id,tab]));
  const loads = [];
  const context = vm.createContext({
    console, LANGS:{ru:{},en:{},ua:{}}, localStorage:{getItem:()=>null},
    $: id => { if (!nodes.has(id)) nodes.set(id,element(id)); return nodes.get(id); },
    document:{querySelectorAll: selector => selector === '[data-bot-group]' ? groups : selector === '[data-bot-tab]' ? buttons : selector === '.bot-tab' ? tabs : [], querySelector:()=>null},
    esc:String, t:key=>key, hasTranslation:()=>false, panelI18n:key=>key, panelI18nAttrs:()=>'',
    api:async()=>({}), renderBotsList(){}, toast(){}, toggleChecked:()=>false,
  });
  const run = code => vm.runInContext(code,context);
  run('var _allBots=[]; var _currentBotId=1; var _currentBot=null;');
  run(fs.readFileSync('static/app/03_bots.js','utf8'));
  run(fs.readFileSync('static/app/06_roles.js','utf8'));
  context.loader = name => loads.push(name);
  run("_botTabLoaders = () => Object.fromEntries(Object.values(BOT_TAB_GROUPS).flat().map(name=>[name,()=>loader(name)])); renderBotsList=()=>{};");
  return {context, run, groups, tabs, nodes, loads};
}

test('lurker flow contains only channel scope and direct navigation cannot expose AI behavior', () => {
  const h=harness();
  h.run("applyBotRoleVisibility('lurker'); showBotGroup('flow');");
  assert.deepEqual(h.loads,['channels']);
  for(const tab of h.tabs) assert.equal(tab.classList.contains('hidden'),tab.id!=='botTab-channels',tab.id);
  h.run("showBotTab('persona');");
  assert.equal(h.nodes.get('botTab-persona').classList.contains('hidden'),true);
  assert.equal(h.nodes.get('botTab-general').classList.contains('hidden'),false);
  assert.equal(h.nodes.get('botAIProvider').classList.contains('hidden'),true);
  h.run("_roleCfg={configs:{lurker:{mention_reply:true}}}; _roleEditing='lurker'; renderRoleTab();");
  assert.match(h.nodes.get('roleConfigForm').innerHTML,/roleF_mention_reply/);
  assert.doesNotMatch(h.nodes.get('roleConfigForm').innerHTML,/roleF_chat_activity|roleF_preset_key/);
});

test('Moderator chat activity gates persona and chat AI while retaining moderation and technical settings', () => {
  const h=harness();
  for(const activity of ['moderation_only','silent']) {
    h.run(`applyBotRoleVisibility('moderator','${activity}'); showBotGroup('flow');`);
    assert.equal(h.run("botRoleAllowsTab('persona')"),false);
    assert.equal(h.run("botRoleAllowsTab('attention')"),false);
    assert.equal(h.run("botRoleAllowsTab('moderation')"),true);
    assert.equal(h.run("botRoleAllowsTab('logs')"),true);
    assert.equal(h.nodes.get('botQuickBehaviorCard').classList.contains('hidden'),true);
  }
  h.run("applyBotRoleVisibility('moderator','chatter'); showBotGroup('identity');");
  assert.equal(h.nodes.get('botTab-persona').classList.contains('hidden'),false);
  assert.equal(h.run("botRoleAllowsTab('attention')"),true);
  assert.equal(h.nodes.get('botQuickBehaviorCard').classList.contains('hidden'),false);
});

test('role config chat activity select updates visibility immediately and role changes retain drafts', async () => {
  const h=harness();
  h.run("_roleCfg={configs:{moderator:{chat_activity:'moderation_only'},lurker:{mention_reply:false}}}; _roleEditing='moderator'; renderRoleTab();");
  assert.match(h.nodes.get('roleConfigForm').innerHTML,/onchange="applyBotRoleVisibility\('moderator',this.value\)"/);
  h.context.$('roleF_chat_activity').value='silent';
  await h.context.roleChange('lurker');
  assert.equal(h.run('_roleCfg.configs.moderator.chat_activity'),'silent');
  assert.equal(h.run("botRoleAllowsTab('persona')"),false);
});

test('Voice companion exposes persona, AI/TTS, not moderation; role filter can be reversed', () => {
  const h=harness();
  h.run("applyBotRoleVisibility('lurker'); applyBotRoleVisibility('voice_companion'); showBotGroup('voice');");
  assert.equal(h.run("botRoleAllowsTab('persona')"),true);
  assert.equal(h.run("botRoleAllowsTab('attention')"),true);
  assert.equal(h.run("botRoleAllowsTab('moderation')"),false);
  assert.deepEqual(h.loads,['tts','voice-clones']);
  assert.equal(h.nodes.get('botAIProvider').classList.contains('hidden'),false);
});

test('assigned Director opens the Director page, bypassing regular loaders (Q40)', () => {
  const h=harness();
  h.context.showSection=name=>h.loads.push(name);
  h.run("_allBots=[{id:4,bot_role:'director'}]; openBotSettings(4);");
  // Q40: у Режиссёра своя страница — карточка бота ведёт туда, обычные загрузчики не зовутся.
  assert.deepEqual(h.loads,['director']);
});

test('late role response cannot change a different bot panel', async () => {
  const h=harness(); let resolve;
  h.context.api=()=>new Promise(yes=>{resolve=yes;});
  const action=h.context.loadBotRole(1);
  h.run('_currentBotId=2;');
  resolve({bot_role:'lurker',configs:{lurker:{mention_reply:true}}}); await action;
  assert.equal(h.run('_roleCfg'),null);
});

// ── D1 (bugfix 3e0cdd3, 12.09.2026) ──

test('D1: roleSelect always shows the current bot role, not one left over from a previously opened bot', () => {
  const h = harness();
  h.run("_roleCfg={configs:{lurker:{mention_reply:true}}}; _roleEditing='lurker'; renderRoleTab();");
  assert.equal(h.nodes.get('roleSelect').value, 'lurker');
  // Раньше сохранённый .value чужого бота «переезжал», даже если у нового бота этой роли
  // нет в списке опций — сюда специально не подставляем chatter, чтобы поймать регресс.
  h.nodes.get('roleSelect').value = 'moderator';
  h.run("_roleEditing='chatter'; _roleCfg.configs.chatter={}; renderRoleTab();");
  assert.equal(h.nodes.get('roleSelect').value, 'chatter');
});

test('D1: changing the role select applies it immediately via PUT role-config, not only on a later Save', async () => {
  const h = harness();
  const calls = [];
  h.context.api = async (url, opts) => {
    calls.push([url, opts]);
    return { ok: true, bot_role: 'chatter', config: {}, observation_only_cleared: false };
  };
  h.context.jopts = (method, body) => ({ method, body });
  h.run("_currentBotId=5; _allBots=[{id:5,bot_role:'lurker'}]; _roleCfg={configs:{lurker:{mention_reply:true},chatter:{}}}; _roleEditing='lurker'; renderRoleTab();");
  h.context.loadBotGeneral = () => {}; // фиксируем именно роль-часть, а не общий рефреш карточки
  await h.context.roleChange('chatter');
  const roleCalls = calls.filter(([url]) => url === '/api/accounts/5/role-config');
  assert.equal(roleCalls.length, 1);
  assert.equal(roleCalls[0][1].method, 'PUT');
  assert.equal(roleCalls[0][1].body.role, 'chatter');
  assert.equal(h.run('_allBots[0].bot_role'), 'chatter');
});

test('D1: leaving lurker refreshes the quick-behavior toggle only when the backend actually cleared it', async () => {
  const h = harness();
  const refreshed = [];
  h.context.loadQuickBehavior = () => refreshed.push('loadQuickBehavior');
  h.context.api = async () => ({ ok: true, bot_role: 'chatter', config: {}, observation_only_cleared: true });
  h.context.jopts = (method, body) => ({ method, body });
  h.run("_currentBotId=5; _allBots=[{id:5,bot_role:'lurker'}]; _roleCfg={configs:{lurker:{},chatter:{}}}; _roleEditing='lurker'; renderRoleTab();");
  h.context.loadBotGeneral = () => {};
  await h.context.roleChange('chatter');
  assert.deepEqual(refreshed, ['loadQuickBehavior']);
});
