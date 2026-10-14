// P8-C13 behavior tests: production dirty-guard code executes in Node VM.
// Replaces static source-marker assertions (C-010 migration, E13-style).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const APP_JS = fs.readFileSync(path.join(__dirname, '..', 'static', 'app.js'), 'utf8');
const BOTS_JS = fs.readFileSync(path.join(__dirname, '..', 'static', 'app', '03_bots.js'), 'utf8');

function extractFunction(source, name) {
  const patterns = [`async function ${name}(`, `function ${name}(`];
  const starts = patterns.map(p => source.indexOf(p)).filter(i => i >= 0);
  const start = Math.min(...starts);
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

function extractBeforeunload(source) {
  const start = source.indexOf("window.addEventListener('beforeunload'");
  assert.notEqual(start, -1, 'missing beforeunload registration');
  const end = source.indexOf('});', start);
  assert.notEqual(end, -1, 'unterminated beforeunload block');
  return source.slice(start, end + 3);
}

function fakeElement(id, initialClasses = []) {
  const classes = new Set(initialClasses);
  return {
    id,
    dataset: {},
    listeners: {},
    classList: {
      contains: name => classes.has(name),
      add: name => classes.add(name),
      remove: name => classes.delete(name),
      toggle(name, on) { if (on) classes.add(name); else classes.delete(name); },
      _set: classes,
    },
    addEventListener(type, fn) {
      (this.listeners[type] = this.listeners[type] || []).push(fn);
    },
  };
}

function loadApp(names) {
  const elements = {};
  const handlers = {};
  const ctx = {
    window: {
      innerWidth: 1024,
      addEventListener(type, fn) { (handlers[type] = handlers[type] || []).push(fn); },
    },
    history: { replaceState() {} },
    document: {
      querySelectorAll: () => [],
      querySelector: () => null,
    },
    $: (id, initial) => (elements[id] = elements[id] || fakeElement(id, initial)),
    t: key => key,
    confirmCalls: [],
    confirm(msg) { ctx.confirmCalls.push(msg); return ctx.confirmAnswer; },
    confirmAnswer: true,
    _dirtyScopes: new Set(),
  };
  const code = [
    ...names.map(n => extractFunction(APP_JS, n)),
    extractBeforeunload(APP_JS),
  ].join('\n');
  vm.createContext(ctx);
  vm.runInContext(code, ctx);
  return { ctx, elements, handlers };
}

function fireBeforeunload(handlers, prevented) {
  const event = { returnValue: undefined, calls: 0, preventDefault() { this.calls += 1; } };
  (handlers.beforeunload || []).forEach(fn => fn(event));
  return event;
}

test('clean state: navigation allowed and beforeunload is a no-op', () => {
  const { ctx, handlers } = loadApp(['markDirty', 'clearDirty', 'isDirty', 'confirmDirty', 'bindDirtyWatch']);
  assert.equal(ctx.isDirty(), false);
  assert.equal(ctx.confirmDirty(), true);
  assert.equal(ctx.confirmCalls.length, 0, 'confirm must not be called when clean');
  const event = fireBeforeunload(handlers);
  assert.equal(event.calls, 0, 'beforeunload must not preventDefault when clean');
  assert.equal(event.returnValue, undefined);
});

test('beforeunload warns when dirty: preventDefault + returnValue set', () => {
  const { ctx, handlers } = loadApp(['markDirty', 'clearDirty', 'isDirty', 'confirmDirty', 'bindDirtyWatch']);
  ctx.markDirty('globalAI');
  const event = fireBeforeunload(handlers);
  assert.equal(event.calls, 1, 'beforeunload must preventDefault when dirty');
  assert.equal(event.returnValue, '');
});

test('confirmDirty cancel: returns false and keeps the dirty scope', () => {
  const { ctx } = loadApp(['markDirty', 'clearDirty', 'isDirty', 'confirmDirty', 'bindDirtyWatch']);
  ctx.markDirty('botGeneral');
  ctx.confirmAnswer = false;
  assert.equal(ctx.confirmDirty(), false);
  assert.equal(ctx.confirmCalls.join(','), 'dirty.confirm', 'confirm prompt uses i18n key');
  assert.equal(ctx.isDirty(), true, 'cancelled navigation must keep unsaved state');
});

test('confirmDirty accept: returns true and clears dirty state', () => {
  const { ctx } = loadApp(['markDirty', 'clearDirty', 'isDirty', 'confirmDirty', 'bindDirtyWatch']);
  ctx.markDirty('botAI');
  ctx.markDirty('globalTTS');
  ctx.confirmAnswer = true;
  assert.equal(ctx.confirmDirty(), true);
  assert.equal(ctx.isDirty(), false, 'accepting must clear all dirty scopes');
});

test('bindDirtyWatch marks dirty on input and is idempotent per scope', () => {
  const { ctx, elements } = loadApp(['markDirty', 'clearDirty', 'isDirty', 'confirmDirty', 'bindDirtyWatch']);
  ctx.bindDirtyWatch('botGeneral', ['botName', 'botPersona']);
  ctx.bindDirtyWatch('botGeneral', ['botName', 'botPersona']);
  assert.equal(elements.botName.listeners.input.length, 1, 'double bind must not duplicate listeners');
  assert.equal(elements.botPersona.dataset.dirtyBound, 'botGeneral');
  elements.botName.listeners.input[0]();
  assert.equal(ctx.isDirty(), true);
  ctx.clearDirty('botGeneral');
  assert.equal(ctx.isDirty(), false);
});

test('closeBotSettings: cancel keeps the editor open, accept closes it', () => {
  const app = loadApp(['markDirty', 'clearDirty', 'isDirty', 'confirmDirty', 'bindDirtyWatch']);
  const botsCode = extractFunction(BOTS_JS, 'closeBotSettings');
  const listView = app.ctx.$('botsListView', ['hidden']);
  const settingsPanel = app.ctx.$('botSettingsPanel');
  vm.createContext(app.ctx);
  vm.runInContext('var _currentBotId = "b1"; var _currentBot = { id: "b1" };', app.ctx);
  // Q21 перенес панель Режиссёра в карточку бота: closeBotSettings зовёт
  // setDirectorPanelVisible — в харнесе достаточно стаба.
  vm.runInContext('var setDirectorPanelVisible = function () {};', app.ctx);
  vm.runInContext(botsCode, app.ctx);

  app.ctx.markDirty('botGeneral');
  app.ctx.confirmAnswer = false;
  vm.runInContext('closeBotSettings()', app.ctx);
  assert.equal(vm.runInContext('_currentBotId', app.ctx), 'b1', 'cancel must not close the editor');
  assert.equal(listView.classList.contains('hidden'), true, 'list stays hidden on cancel');
  assert.equal(settingsPanel.classList.contains('hidden'), false, 'settings stay visible on cancel');

  app.ctx.confirmAnswer = true;
  vm.runInContext('closeBotSettings()', app.ctx);
  assert.equal(vm.runInContext('_currentBotId', app.ctx), null, 'accept must reset current bot');
  assert.equal(listView.classList.contains('hidden'), false, 'list becomes visible');
  assert.equal(settingsPanel.classList.contains('hidden'), true, 'settings become hidden');
});

test('showSection: cancel keeps the current section, accept switches and runs init hooks', () => {
  const { ctx, elements } = loadApp(['markDirty', 'clearDirty', 'isDirty', 'confirmDirty', 'bindDirtyWatch', 'showSection']);
  ctx.loadAnalyticsCalls = 0;
  ctx.loadAnalytics = () => { ctx.loadAnalyticsCalls += 1; };
  ctx.loadHeatmap = () => {};
  ctx.loadChat24h = () => {};
  ctx.loadFeedbackSummary = () => {};
  ctx.loadPerBotStatsSelect = () => {};
  const section = ctx.$('section-analytics');
  ctx.markDirty('globalTTS');
  ctx.confirmAnswer = false;
  vm.runInContext('showSection("analytics")', ctx);
  assert.equal(section.classList.contains('active'), false, 'cancel must not switch section');
  assert.equal(ctx.loadAnalyticsCalls, 0, 'cancel must not run section init hooks');
  ctx.confirmAnswer = true;
  vm.runInContext('showSection("analytics")', ctx);
  assert.equal(section.classList.contains('active'), true, 'accept switches section');
  assert.equal(ctx.loadAnalyticsCalls, 1, 'accept runs section init hooks');
});
