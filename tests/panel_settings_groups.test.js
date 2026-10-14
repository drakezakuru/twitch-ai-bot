const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const settings = fs.readFileSync('templates/partials/settings.html', 'utf8');
const i18n = fs.readFileSync('static/app.js', 'utf8');

test('settings cards are separated into stable task groups', () => {
  const groups = [
    'settings.group_ai',
    'settings.group_diagnostics',
    'settings.group_twitch',
    'settings.group_security',
    'settings.group_maintenance',
    'settings.group_modsite',
  ];
  const positions = groups.map(key => settings.indexOf(`data-i18n="${key}"`));
  assert.ok(positions.every(position => position >= 0), 'every settings group heading is rendered');
  assert.deepEqual([...positions].sort((a, b) => a - b), positions, 'groups follow the settings workflow');
  assert.ok(positions[0] < settings.indexOf('id="globalAIProvider"') && settings.indexOf('id="offlineModeToggle"') < positions[1],
    'AI group keeps every provider card before diagnostics');
  assert.ok(positions[1] < settings.indexOf('id="panelLogTailLines"'), 'diagnostics heading precedes its log cards');
  for (const key of groups) assert.equal((i18n.match(new RegExp(`'${key}'`, 'g')) || []).length, 3, `${key} has three translations`);
});

test('FAQ points to the active TTS and bot log screens', () => {
  assert.match(i18n, /Боты → Настроить → «🔊 TTS»/);
  assert.match(i18n, /Статистика → «📋 Логи ботов»/);
  assert.doesNotMatch(i18n, /Настройки → «📋 Глобальные логи»/);
});
