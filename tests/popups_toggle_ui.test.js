// Q24: тумблер «Не показывать всплывашки» — глобальное UI-предпочтение владельца.
// Проверяет разметку тумблера, localStorage-состояние, гейты попапов и i18n ×3.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const read = file => fs.readFileSync(path.join(__dirname, '..', file), 'utf8');

const DASHBOARD = read('templates/partials/dashboard.html');
const EXTRAS = read('static/app/12_dashboard_extras.js');
const SESSION = read('static/app/13_widgets_session.js');
const APP = read('static/app.js');
const LABELS = read('static/app/21_panel_labels.js');

test('dashboard has the popups toggle wired to the helper', () => {
  assert.match(DASHBOARD, /id="panelPopupsToggle"/);
  assert.match(DASHBOARD, /onchange="setPopupsHidden\(this\.checked\)"/);
  assert.match(DASHBOARD, /data-i18n="panel\.popups\.hide"/);
  // Accessible name and tooltip per DEC-UI-002 / R-UI2.
  assert.match(DASHBOARD, /data-i18n-aria-label="panel\.popups\.hide"/);
  assert.match(DASHBOARD, /data-i18n-title="panel\.popups\.hide_hint"/);
});

test('state lives in localStorage, default is popups shown', () => {
  assert.match(EXTRAS, /panelPopupsHidden/);
  assert.match(EXTRAS, /function popupsHidden\(\)/);
  assert.match(EXTRAS, /function setPopupsHidden\(hidden\)/);
  // Default OFF: enabled only when the stored value is exactly '1'.
  assert.match(EXTRAS, /getItem\(_POPUPS_HIDDEN_KEY\) === '1'/);
});

test('floating decision cards are gated by the toggle', () => {
  assert.match(SESSION, /if \(typeof popupsHidden === 'function' && popupsHidden\(\)\)/);
  // When hidden, the existing popup box is removed instead of accumulating cards.
  assert.match(SESSION, /modAskPopup/);
});

test('live-event toasts are gated by the toggle', () => {
  assert.match(APP, /msg\.status === 'disconnected' && !\(typeof popupsHidden === 'function' && popupsHidden\(\)\)/);
});

test('inline feeds are not affected', () => {
  // The dashboard live feed and the moderation widget list keep rendering.
  assert.match(APP, /function pushEvent\(kind, text, accountId\)/);
  assert.match(APP, /pushEvent\('system', `\$\{msg\.status === 'connected' \? '🟢' : '🔴'\}/);
});

test('i18n: RU/EN/UA for label and hint', () => {
  assert.equal(LABELS.split("'panel.popups.hide':").length - 1, 3);
  assert.equal(LABELS.split("'panel.popups.hide_hint':").length - 1, 3);
});
