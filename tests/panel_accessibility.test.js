const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');
const {environment, functionSource} = require('./panel_accessibility_harness');

function key(ctx, name, shiftKey = false) {
  const event = {key: name, shiftKey, prevented: false, stopped: false,
    preventDefault() { this.prevented = true; }, stopImmediatePropagation() { this.stopped = true; }};
  ctx.panelDialogKeydown(event);
  return event;
}

test('dialog opening names it, focuses requested field, isolates background and restores focus', () => {
  const {ctx, document, element, modal} = environment();
  document.body.style.overflow = 'auto';
  const opener = element('button', {}, document.body, 'Open');
  const preexisting = element('div'); preexisting.inert = true;
  const notices = element('div', {id: 'toastContainer', 'aria-live': 'polite'});
  const {root, dialog, title, description} = modal('edit');
  const first = element('button', {}, dialog, 'Close');
  const field = element('input', {id: 'draft'}, dialog);
  opener.focus();
  ctx.openPanelDialog('edit', {initialFocus: 'draft'});
  assert.equal(root.classList.contains('hidden'), false);
  assert.equal(document.activeElement, field);
  assert.equal(dialog.getAttribute('role'), 'dialog');
  assert.equal(dialog.getAttribute('aria-labelledby'), title.id);
  assert.equal(dialog.getAttribute('aria-describedby'), description.id);
  assert.equal(opener.inert, true);
  assert.equal(notices.inert, false, 'modal errors remain available to assistive technology');
  assert.equal(document.body.style.overflow, 'hidden');
  ctx.openPanelDialog('edit');
  ctx.closePanelDialog('edit');
  assert.equal(document.activeElement, opener);
  assert.equal(opener.inert, false);
  assert.equal(preexisting.inert, true);
  assert.equal(document.body.style.overflow, 'auto');
  assert.equal(first.disabled, false);
});

test('Tab and Shift+Tab wrap, ignoring hidden/disabled/negative-tabindex controls', () => {
  const {ctx, document, element, modal} = environment();
  const {dialog} = modal('tab');
  const first = element('input', {}, dialog);
  const disabled = element('button', {}, dialog); disabled.disabled = true;
  const hidden = element('div', {class: 'hidden'}, dialog); element('button', {}, hidden);
  element('button', {tabindex: '-1'}, dialog);
  const last = element('button', {}, dialog);
  ctx.openPanelDialog('tab');
  assert.equal(document.activeElement, first);
  assert.equal(key(ctx, 'Tab', true).prevented, true);
  assert.equal(document.activeElement, last);
  assert.equal(key(ctx, 'Tab').prevented, true);
  assert.equal(document.activeElement, first);
  assert.equal(key(ctx, 'Tab').prevented, false);
});

test('empty dialogs remain keyboard contained and removed opener falls back safely', () => {
  const {ctx, document, element, modal} = environment();
  const fallback = element('button', {class: 'nav-btn active'});
  const opener = element('button'); opener.focus();
  const {dialog} = modal('empty');
  ctx.openPanelDialog('empty');
  assert.equal(document.activeElement, dialog);
  assert.equal(key(ctx, 'Tab').prevented, true);
  opener.remove();
  ctx.closePanelDialog('empty');
  assert.equal(document.activeElement, fallback);
});

test('Escape closes only top dialog and preserves custom dismissal cleanup', () => {
  const {ctx, document, element, modal} = environment();
  const opener = element('button'); opener.focus();
  const one = modal('one'); const oneField = element('input', {}, one.dialog);
  const two = modal('two'); element('input', {}, two.dialog);
  ctx.openPanelDialog('one');
  let dismissed = 0;
  ctx.openPanelDialog('two', {onDismiss() { dismissed++; ctx.closePanelDialog('two'); }});
  assert.equal(one.root.inert, true);
  const event = key(ctx, 'Escape');
  assert.equal(event.prevented && event.stopped, true);
  assert.equal(dismissed, 1);
  assert.equal(one.root.classList.contains('hidden'), false);
  assert.equal(one.root.inert, false);
  assert.equal(document.activeElement, oneField);
  key(ctx, 'Escape');
  assert.equal(document.activeElement, opener);
});

test('dynamic removal releases inert and prevents lingering focus traps', () => {
  const {ctx, document, element, modal} = environment();
  const opener = element('button'); opener.focus();
  const {root, dialog} = modal('dynamic'); element('input', {}, dialog);
  ctx.openPanelDialog(root, {removeOnClose: true});
  root.remove(); ctx.reconcilePanelDialogs();
  assert.equal(opener.inert, false);
  assert.equal(document.activeElement, opener);
  assert.equal(key(ctx, 'Tab').prevented, false);
});

test('programmatic focus escapes and replaced form contents recover to the current dialog', () => {
  const {ctx, document, element, modal} = environment();
  const opener = element('button');
  const {dialog} = modal('replacement'); const field = element('input', {}, dialog);
  ctx.initPanelAccessibility(); ctx.openPanelDialog('replacement');
  opener.focus();
  assert.equal(document.activeElement, field);
  field.remove(); const next = element('input', {}, dialog);
  ctx.reconcilePanelDialogs();
  assert.equal(document.activeElement, next);
});

test('dynamic labels associate to controls without inventing labels or changing values', () => {
  const {ctx, element} = environment();
  const label = element('label', {}, undefined, 'Nickname');
  const input = element('input'); input.value = 'unsaved';
  const toggleLabel = element('span', {'data-i18n': 'test.label'}, undefined, 'Reply');
  const toggle = element('div', {class: 'toggle active'});
  const error = element('div', {class: 'error-state'});
  ctx.refreshPanelAccessibility();
  assert.equal(label.getAttribute('for'), input.id);
  assert.equal(input.value, 'unsaved');
  assert.equal(toggle.getAttribute('aria-labelledby'), toggleLabel.id);
  assert.equal(toggle.getAttribute('role'), 'switch');
  assert.equal(toggle.getAttribute('aria-checked'), 'true');
  assert.equal(toggle.tabIndex, 0);
  toggle.classList.remove('active'); ctx.refreshPanelAccessibility();
  assert.equal(toggle.getAttribute('aria-checked'), 'false');
  assert.equal(error.getAttribute('aria-live'), 'polite');
});

test('all three languages update labels without resetting form drafts; missing translations fall back to RU', () => {
  const {ctx, document, element, storage} = environment();
  vm.runInContext(functionSource('static/app.js', 'setLang'), ctx);
  ctx.LANGS.ru['test.label'] = 'Имя'; ctx.LANGS.en['test.label'] = 'Name';
  ctx.LANGS.ua['test.label'] = 'Ім’я';
  ctx.LANGS.ru['test.only_ru'] = 'Русский текст';
  const label = element('label', {'data-i18n': 'test.label'});
  const input = element('input'); input.value = 'unsaved';
  const fallback = element('span', {'data-i18n': 'test.only_ru'});
  const title = element('button', {'data-i18n-title': 'test.label'}, undefined, '✕');
  const hint = element('input', {'data-i18n-placeholder': 'test.label'});
  for (const lang of ['ru', 'en', 'ua']) {
    ctx.setLang(lang);
    assert.equal(label.textContent, ctx.LANGS[lang]['test.label']);
    assert.equal(input.value, 'unsaved');
    assert.equal(fallback.textContent, 'Русский текст');
    assert.equal(title.getAttribute('aria-label'), ctx.LANGS[lang]['test.label']);
    assert.equal(hint.getAttribute('placeholder'), ctx.LANGS[lang]['test.label']);
  }
  assert.equal(document.documentElement.getAttribute('lang'), 'uk');
  assert.equal(ctx.t('not.a.real.key'), 'Текст недоступен');
  ctx.setLang('invalid'); assert.equal(storage.get('lang'), 'ru');
});

test('preset changes and legacy theme toggle cannot make the panel light or modify widget state', () => {
  const {ctx, document, element, storage} = environment();
  for (const name of ['enforcePanelDarkTheme', 'toggleTheme', 'applyBgPreset', 'initBgPreset']) {
    vm.runInContext(functionSource('static/app.js', name), ctx);
  }
  ctx.THEME_PRESET_KEYS = ['--accent'];
  ctx.BG_PRESETS = [{id: 'default', vars: {dark: {}, light: {}}},
    {id: 'ocean', vars: {dark: {'--accent': 'dark-blue'}, light: {'--accent': 'light-blue'}}}];
  const iframe = element('iframe', {src: '/widget/animated-bg?theme=light'});
  storage.set('theme', 'light'); storage.set('bgPreset', 'ocean');
  document.documentElement.setAttribute('data-theme', 'light');
  ctx.toggleTheme();
  assert.equal(document.documentElement.getAttribute('data-theme'), 'dark');
  assert.equal(document.documentElement.style['--accent'], 'dark-blue');
  assert.equal(iframe.getAttribute('src'), '/widget/animated-bg?theme=light');
  ctx.localStorage.getItem = () => { throw new Error('blocked'); };
  ctx.localStorage.setItem = () => { throw new Error('blocked'); };
  assert.doesNotThrow(() => ctx.initBgPreset());
  assert.equal(document.documentElement.getAttribute('data-theme'), 'dark');
});

test('media-share hint replaced the disclosure modal (Q16 F2)', () => {
  // Модалка убрана: ни разметки, ни гейт-функций. Подсказка живёт в форме виджета.
  const widgetsHtml = fs.readFileSync('templates/partials/widgets.html', 'utf8');
  const baseHtml = fs.readFileSync('templates/base.html', 'utf8');
  const widgetsJs = fs.readFileSync('static/app/07_widgets.js', 'utf8');
  assert.ok(!baseHtml.includes('mediaShareDisclosureModal'));
  assert.ok(!widgetsJs.includes('waUseMediaShare'));
  assert.match(widgetsHtml, /data-i18n="widgets\.media_share_hint"/);
});

test('role switches render enabled state and save both on and off instead of silently losing true', () => {
  const {ctx, document, element} = environment();
  const form = element('div', {id: 'roleConfigForm'});
  ctx.$ = id => document.getElementById(id); ctx.esc = String;
  ctx._roleT = key => key; ctx.renderBotsList = () => {};
  ctx.ROLE_META = {lurker: {label: 'Lurker', desc: 'Observer'}};
  ctx.ROLE_FIELDS = {lurker: [['mention_reply', 'role.l.mention_reply', 'toggle', {}]]};
  ctx._roleEditing = 'lurker'; ctx._roleCfg = {configs: {lurker: {mention_reply: true}}};
  for (const name of ['renderRoleTab', '_collectRoleForm']) vm.runInContext(functionSource('static/app/06_roles.js', name), ctx);
  vm.runInContext(functionSource('static/app/15_feedback_2908.js', 'toggleChecked'), ctx);
  ctx.renderRoleTab();
  assert.match(form.innerHTML, /class="toggle active"[^>]*aria-checked="true"/);
  assert.match(form.innerHTML, /aria-labelledby="roleF_mention_reply-label"/);
  const toggle = element('div', {id: 'roleF_mention_reply', class: 'toggle active'});
  assert.equal(ctx._collectRoleForm().mention_reply, true);
  toggle.classList.remove('active');
  assert.equal(ctx._collectRoleForm().mention_reply, false);
});

test('collapsible card provides a native labeled button with actual expanded state', () => {
  const {ctx, document, element} = environment();
  const card = element('div', {class: 'card'});
  const header = element('div', {class: 'card-header'}, card);
  const title = element('span', {class: 'card-title'}, header, 'Settings');
  const body = element('div', {}, card);
  for (const name of ['toggleCardCollapse', 'initCollapsibleCards']) vm.runInContext(functionSource('static/app/15_feedback_2908.js', name), ctx);
  ctx.initCollapsibleCards(document);
  const button = header.querySelector('button');
  assert.ok(button);
  assert.equal(button.getAttribute('aria-labelledby'), title.id);
  assert.equal(button.getAttribute('aria-controls'), body.id);
  assert.equal(button.getAttribute('aria-expanded'), 'true');
  button.click();
  assert.equal(card.classList.contains('collapsed'), true);
  assert.equal(button.getAttribute('aria-expanded'), 'false');
  button.click();
  assert.equal(card.classList.contains('collapsed'), false);
  assert.equal(button.getAttribute('aria-expanded'), 'true');
});

test('mutation updates stay scoped and include a newly inserted control itself', () => {
  const {ctx, document, element} = environment();
  ctx.initPanelAccessibility();
  const observer = vm.runInContext('_panelA11yObserver', ctx);
  const refreshed = [];
  const original = ctx.refreshPanelAccessibility;
  ctx.refreshPanelAccessibility = root => { refreshed.push(root); original(root); };
  const input = element('input', {id: 'modMediaWidth'});
  observer.callback([{type: 'childList', addedNodes: [input]}]);
  assert.deepEqual(refreshed, [input]);
  assert.equal(input.getAttribute('aria-label'), 'Ширина медиа, %');
  refreshed.length = 0;
  const card = element('div', {class: 'card'});
  observer.callback([{type: 'attributes', target: card}]);
  assert.equal(refreshed.length, 0, 'unrelated class updates must not scan the entire panel');
  const toggle = element('div', {class: 'toggle active'});
  observer.callback([{type: 'attributes', target: toggle}]);
  assert.equal(toggle.getAttribute('aria-checked'), 'true');
  assert.equal(refreshed.includes(document), false);
});
