// Q15b (E2/E3): один список моделей провайдера с типами (чат/vision/оба);
// дубли схлопываются, типы объединяются; для бота — дропдауны из списков
// custom:*-провайдера. Логика собирается из продакшн-кода в Node VM.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const PROVIDERS_JS = fs.readFileSync(path.join(__dirname, '..', 'static', 'app', '08_providers_moderation.js'), 'utf8');

function extractFunction(source, name) {
  const start = source.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `missing ${name}`);
  const brace = source.indexOf('{', start);
  let depth = 0;
  for (let i = brace; i < source.length; i += 1) {
    if (source[i] === '{') depth += 1;
    if (source[i] === '}') depth -= 1;
    if (depth === 0) return source.slice(start, i + 1);
  }
  throw new Error(`unterminated ${name}`);
}

function load(names, modelRows) {
  const ctx = {
    _cpModelRows: modelRows || [],
  };
  const code = names.map(n => extractFunction(PROVIDERS_JS, n)).join('\n');
  vm.createContext(ctx);
  vm.runInContext(code, ctx);
  return ctx;
}

test('_cpRowsFromProvider merges chat and vision lists into typed rows', () => {
  const ctx = load(['_cpRowsFromProvider']);
  const rows = JSON.parse(JSON.stringify(ctx._cpRowsFromProvider({
    models: ['gpt-a', 'gpt-b'],
    vision_models: ['gpt-b', 'llava'],
  })));
  assert.deepEqual(rows, [
    { name: 'gpt-a', type: 'chat' },
    { name: 'gpt-b', type: 'both' },
    { name: 'llava', type: 'vision' },
  ], 'модель в обоих списках = both, без дублирования строки');
  assert.deepEqual(JSON.parse(JSON.stringify(ctx._cpRowsFromProvider({ models: [], vision_models: [] }))), []);
});

test('_cpListsFromRows dedupes case-insensitively and unions types', () => {
  const ctx = load(['_cpListsFromRows'], [
    { name: 'GPT-A', type: 'chat' },
    { name: ' gpt-a ', type: 'vision' },
    { name: 'llava', type: 'vision' },
    { name: '   ', type: 'chat' },
  ]);
  const lists = JSON.parse(JSON.stringify(ctx._cpListsFromRows()));
  assert.deepEqual(lists.models, ['GPT-A'], 'дубликат схлопнут, первое написание сохранено');
  assert.deepEqual(lists.vision_models, ['GPT-A', 'llava'], 'типы дубликатов объединяются');
  assert.ok(!lists.models.includes(''), 'пустые строки отбрасываются');
});
