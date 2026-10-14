const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const analytics = fs.readFileSync('templates/partials/analytics.html', 'utf8');
const settings = fs.readFileSync('templates/partials/settings.html', 'utf8');
const chat = fs.readFileSync('static/app/04_chat_settings.js', 'utf8');
const bots = fs.readFileSync('static/app/03_bots.js', 'utf8');

test('bot logs have one main screen with all filters and CSV export', () => {
  for (const id of ['analyticsBotFilter', 'analyticsLevelFilter', 'analyticsLogsFrom', 'analyticsLogsTo']) {
    assert.match(analytics, new RegExp(`id="${id}"`));
  }
  assert.match(analytics, /onclick="exportAnalyticsLogs\(\)"/);
  assert.match(chat, /\/api\/bot-logs\/export\?/);
  assert.doesNotMatch(chat, /toast\.select_bot_export/);
});

test('settings keeps diagnostics and links to the main bot log screen', () => {
  assert.match(settings, /data-i18n="settings\.diagnostics"/);
  assert.match(settings, /onclick="openBotLogs\(\)"/);
  assert.doesNotMatch(settings, /settingsLogsContent|settingsLogsFrom|settingsLogsTo/);
  assert.doesNotMatch(bots, /function loadGlobalLogs|function loadSettingsLogs|function exportSettingsLogs/);
});
