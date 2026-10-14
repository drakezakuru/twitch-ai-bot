// Q16 F2 (DEC-OWNER-016): модалка-предупреждение Media Share убрана —
// в форме медиа-шары постоянная строка-подсказка. Роуты disclosure остаются
// legacy-контрактом, но из UI недостижимы. Ранее здесь тестировался гейт
// waUseMediaShare → теперь контракт «подсказка в форме, кнопки работают напрямую».
const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const widgetsHtml = fs.readFileSync('templates/partials/widgets.html', 'utf8');
const baseHtml = fs.readFileSync('templates/base.html', 'utf8');
const settingsHtml = fs.readFileSync('templates/partials/settings.html', 'utf8');
const widgetsJs = fs.readFileSync('static/app/07_widgets.js', 'utf8');
const botsTabsJs = fs.readFileSync('static/app/05_bots_tabs.js', 'utf8');

test('media-share form carries a permanent hint line and no modal exists', () => {
  assert.match(widgetsHtml, /data-i18n="widgets\.media_share_hint"/),
    'подсказка YouTube в форме медиа-шары';
  assert.ok(!baseHtml.includes('mediaShareDisclosureModal'), 'модалка убрана из base.html');
  assert.ok(!settingsHtml.includes('waShowMediaDisclosureAgain'), 'кнопка «показать снова» убрана из Настроек');
  assert.ok(!settingsHtml.includes('media.settings_title'), 'карточка Media Share в Настройках убрана');
});

test('media-share buttons call widget actions directly, no gating left', () => {
  assert.ok(!widgetsJs.includes('waUseMediaShare'), 'гейт waUseMediaShare удалён');
  assert.ok(!widgetsJs.includes("'/api/media-share/disclosure'"), 'UI больше не дергает disclosure-API');
  assert.ok(!botsTabsJs.includes('mediaShareDisclosureModal'), 'onDismiss-ветка модалки удалена');
  // обе кнопки медиа-шары работают без посредников
  assert.match(widgetsHtml, /onclick="showWidgetInstr\('\{\{ widget\.route \}\}', '\{\{ widget\.slug \}\}'/),
    'инструкция вызывается напрямую';
  assert.ok(!widgetsHtml.includes('waUseMediaShare'), 'в шаблоне не осталось вызовов гейта');
});

test('hint is translated in all three languages, old disclosure keys removed', () => {
  assert.equal((widgetsJs.match(/'widgets\.media_share_hint':/g) || []).length, 3);
  for (const key of ('media.disclosure_title media.disclosure_body media.disclosure_limits ' +
    'media.disclosure_accept media.disclosure_close media.disclosure_again ' +
    'media.disclosure_load_error media.disclosure_save_error media.settings_title ' +
    'media.settings_hint').split(' ')) {
    assert.equal((widgetsJs.match(new RegExp(`'${key.replace(/\./g, '\\.')}'`)) || []).length, 0, key);
  }
});
