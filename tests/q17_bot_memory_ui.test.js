// Q17: «Факты о зрителях» и «Обучение» переехали из «Мозга» во вкладку бота,
// память видна только при включённой долгосрочной памяти; KB-импорт/экспорт удалён.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const read = file => fs.readFileSync(path.join(__dirname, '..', file), 'utf8');

const BRAIN = read('templates/partials/brain.html');
const BOTS = read('templates/partials/bots.html');
const BRAIN_V16 = read('static/app/11_brain_v16.js');
const BRAIN_MEMORY = read('static/app/14_brain_memory.js');
const BOTS_TABS = read('static/app/05_bots_tabs.js');
const APPJS = read('static/app.js');

test('brain no longer hosts memory, learning or KB import/export', () => {
  for (const token of ['learningList', 'brainMemoryList', 'brainKbExport', 'brainKbImport',
    'panel.brain.kb', 'brainAutoExtract']) {
    assert.ok(!BRAIN.includes(token), `brain.html must not contain ${token}`);
  }
});

test('bot memory tab hosts viewer facts (gated) and learning suggestions', () => {
  const memoryTab = BOTS.slice(BOTS.indexOf('id="botTab-memory"'), BOTS.indexOf('id="botTab-streamer"'));
  for (const token of ['botViewerMemoryCard', 'botViewerMemoryList', 'botLongTermMemory',
    'botMemoryDisabled', 'botLearningList', 'brainAutoExtract', 'learningRevertLast',
    'saveBotLongTermMemory', 'panel.brain.viewer_facts', 'panel.brain.learning']) {
    assert.ok(memoryTab.includes(token), `bot memory tab must contain ${token}`);
  }
});

test('memory/learning helpers resolve the account from the bot card', () => {
  assert.match(BRAIN_V16, /function _memoryAcc\(\) \{ return _currentBotId \|\| _brainAcc\(\); \}/);
  assert.match(BRAIN_V16, /function loadBotViewerMemory\(\) \{\s*const box = document\.getElementById\('botViewerMemoryList'\);/);
  assert.match(BRAIN_V16, /function loadLearning\(\) \{\s*const box = document\.getElementById\('botLearningList'\);/);
  // «Мозг» больше не перезагружает переехавшие разделы.
  assert.match(BRAIN_V16, /loadSummarizerRuns\(\);/);
  for (const fn of ['brainSaveFactEdit', 'learningRevertLast', 'brainAutoExtract']) {
    const body = BRAIN_MEMORY.slice(BRAIN_MEMORY.indexOf(`async function ${fn}`));
    assert.match(body.slice(0, 200), /_memoryAcc\(\)/, fn);
  }
  const confirm = BRAIN_V16.slice(BRAIN_V16.indexOf('async function brainConfirmFact'));
  assert.match(confirm.slice(0, 200), /_memoryAcc\(\)/);
});

test('KB import/export helpers are removed', () => {
  assert.ok(!BRAIN_MEMORY.includes('brainKbExport'));
  assert.ok(!BRAIN_MEMORY.includes('brainKbImport'));
});

test('viewer memory is gated by use_long_term_memory with honest disabled note', () => {
  assert.match(BOTS_TABS, /function loadViewerMemoryGate\(id\)/);
  assert.match(BOTS_TABS, /cfg\.use_long_term_memory/);
  assert.match(BOTS_TABS, /function saveBotLongTermMemory\(\)/);
  assert.match(BOTS_TABS, /use_long_term_memory: toggleChecked\('botLongTermMemory'\)/);
  assert.match(BOTS_TABS, /loadBotMemory\(id\) \{[\s\S]*?loadViewerMemoryGate\(id\);/);
  assert.match(APPJS, /'bot\.memory\.disabled_hint'/);
});
