// Q27b: поведение секции «⚡ Правила» в карточке виджета.
// waWidgetBindingAdd открывает секцию карточки (не общую модалку), скроллит к ней
// и умеет подставлять prefilled action (soundboard play_track:<id>).
// waRulesFormSync наполняет форму из контракта; waRulesRenderList фильтрует общий
// кэш правил по виджету секции.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'static', 'app', '13_widgets_session.js'),
  'utf8',
);

function extractFunction(name) {
  const starts = [`async function ${name}(`, `function ${name}(`]
    .map(pattern => source.indexOf(pattern))
    .filter(index => index >= 0);
  const start = Math.min(...starts);
  assert.notEqual(start, -1, `missing ${name}`);
  const brace = source.indexOf('{', start);
  let depth = 0;
  for (let index = brace; index < source.length; index += 1) {
    if (source[index] === '{') depth += 1;
    if (source[index] === '}') depth -= 1;
    if (depth === 0) return source.slice(start, index + 1);
  }
  throw new Error(`unterminated ${name}`);
}

// Минимальный фейк DOM: секция с dataset и querySelector по классам внутри body.
function makeEl(cls) {
  return {
    className: cls,
    value: '',
    innerHTML: '',
    textContent: '',
    placeholder: '',
    title: '',
    disabled: false,
    options: [],
    classList: {
      hidden: cls.split(/\s+/).includes('hidden'),
      toggle(token, force) {
        if (force === undefined) this.hidden = !this.hidden;
        else this.hidden = !!force;
      },
    },
  };
}

function makeSection(slug) {
  const fields = {};
  for (const cls of ['wa-rules-source', 'wa-rules-match', 'wa-rules-hotkey', 'wa-rules-action',
    'wa-rules-key-field', 'wa-rules-key', 'wa-rules-value-field', 'wa-rules-value',
    'wa-rules-role', 'wa-rules-add', 'wa-rules-list', 'wa-rules-autoline']) {
    fields[cls] = makeEl(cls);
  }
  fields['wa-rules-source'].options = [
    { value: 'chat_command', disabled: false },
    { value: 'eventsub', disabled: false },
    { value: 'hotkey', disabled: false },
  ];
  const body = {
    _fields: fields,
    innerHTML: '',
    querySelector(sel) { return this._fields[sel.replace(/^\./, '')] || null; },
  };
  const section = {
    dataset: { rulesSlug: slug },
    open: false,
    scrolled: 0,
    scrollIntoView() { this.scrolled += 1; },
    querySelector(sel) {
      if (sel === '.wa-widget-rules-body') return body;
      return body.querySelector(sel);
    },
  };
  return { section, fields };
}

const CONTRACT = {
  sources: {
    chat_command: { label: 'bindings.source_chat', roles: ['mod', 'streamer'] },
    eventsub: { label: 'bindings.source_event', roles: ['any'] },
    hotkey: { label: 'bindings.source_hotkey', roles: ['streamer'] },
  },
  roles: {
    mod: { label: 'bindings.role_mod' },
    streamer: { label: 'bindings.role_streamer' },
    any: { label: 'bindings.role_any' },
  },
  widgets: {
    goals: {
      label: 'bindings.widget_goals',
      key: { type: 'positive_integer', required: true, kind: 'goal' },
      actions: { increment: { label: 'bindings.action_goals_increment', value: { type: 'int' } } },
      sources: ['chat_command', 'hotkey'],
    },
    soundboard: {
      label: 'bindings.widget_soundboard',
      actions: {},
      dynamic_action: { prefix: 'play_track:', label: 'bindings.action_soundboard_play_track' },
      sources: ['hotkey'],
    },
  },
};

function makeContext(section, fields) {
  const context = {
    document: {
      querySelector: sel => (sel.startsWith('details.wa-widget-rules') ? section : null),
      addEventListener() {},
      removeEventListener() {},
    },
    window: { _hotkeyCapturing: false },
    setTimeout: () => 0,
    esc: v => String(v),
    t: key => key,
    $: () => null,
    toast: () => {},
    console,
    URLSearchParams,
    waBindingScope: () => ({ account_id: 1, channel: 'ch' }),
    waBindingWidgetContract: widget => CONTRACT.widgets[widget] || null,
    waBindingActionContract: (widget, action) => CONTRACT.widgets[widget]?.actions?.[action] || null,
    waBindingActionLabel: action => action,
    waBindingContractLabel: (_group, value) => value,
    uiToggle: () => {},
    _waHint: () => {},
    wapi: async () => ({}),
    waBindingsLoad: async () => {},
    waHotkeyComboFromEvent: () => 'ctrl+shift+d',
    WA_BINDING_CONTRACT: CONTRACT,
    __section: section,
    __list: makeEl('wa-rules-list'),
  };
  vm.createContext(context);
  vm.runInContext(
    ['waRulesEnsure', 'waRulesFormSync', 'waRulesHotkeyCapture', 'waRulesAdd',
      'waRulesRenderList', 'waRulesAutoLine', 'waRulesRenderAll', 'waWidgetBindingAdd']
      .map(extractFunction).join('\n'),
    context,
  );
  return context;
}

test('waWidgetBindingAdd opens the card section, scrolls, no modal', () => {
  const { section, fields } = makeSection('goals');
  const ctx = makeContext(section, fields);
  vm.runInContext(`waWidgetBindingAdd('goals')`, ctx);
  assert.equal(section.open, true);
  assert.equal(section.scrolled, 1);
});

test('waWidgetBindingAdd prefills action (soundboard play_track)', () => {
  const { section, fields } = makeSection('soundboard');
  const ctx = makeContext(section, fields);
  vm.runInContext(`waWidgetBindingAdd('soundboard', 'play_track:7')`, ctx);
  assert.equal(section.open, true);
  assert.match(fields['wa-rules-action'].innerHTML, /value="play_track:7"/);
  assert.equal(fields['wa-rules-action'].value, 'play_track:7');
});

test('waRulesFormSync fills actions, roles and toggles key/value fields', () => {
  const { section, fields } = makeSection('goals');
  const ctx = makeContext(section, fields);
  vm.runInContext('waRulesFormSync(__section)', ctx);
  assert.match(fields['wa-rules-action'].innerHTML, /increment/);
  assert.match(fields['wa-rules-role'].innerHTML, /value="mod"/);
  // goals требует ключ (kind=goal) — поле ключа показано
  assert.equal(fields['wa-rules-key-field'].classList.hidden, false);
  assert.match(fields['wa-rules-key'].placeholder, /bindings\.key_goal_placeholder/);
  // hotkey-кнопка скрыта для chat_command
  assert.equal(fields['wa-rules-hotkey'].classList.hidden, true);
});

test('waRulesRenderList filters shared cache by widget and wires delete', () => {
  const { section, fields } = makeSection('goals');
  const ctx = makeContext(section, fields);
  ctx.window._waBindingsCache = [
    { id: 1, widget: 'goals', source: 'chat_command', match: '!goal', action: 'increment', value: '1', enabled: true, widget_key: 'main' },
    { id: 2, widget: 'countdown', source: 'hotkey', match: 'ctrl+q', action: 'start', enabled: true },
  ];
  vm.runInContext('waRulesRenderList(__section)', ctx);
  const rendered = fields['wa-rules-list'].innerHTML;
  assert.match(rendered, /!goal/);
  assert.match(rendered, /waBindingDelete\(1\)/);
  assert.doesNotMatch(rendered, /ctrl\+q/);
});
