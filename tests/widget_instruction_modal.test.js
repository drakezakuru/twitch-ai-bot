// P5 / C-010: production OBS instruction modal behavior in Node VM.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const {functionSource} = require('./panel_accessibility_harness');

const SOURCE = fs.readFileSync(
  path.join(__dirname, '..', 'static', 'app', '09_brain_p3.js'),
  'utf8',
);

function extractFunction(source, name) {
  const patterns = [`async function ${name}(`, `function ${name}(`];
  const starts = patterns.map(pattern => source.indexOf(pattern)).filter(index => index >= 0);
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

function extractObjectConst(source, name) {
  const start = source.indexOf(`const ${name} =`);
  assert.notEqual(start, -1, `missing ${name}`);
  const brace = source.indexOf('{', start);
  let depth = 0;
  for (let index = brace; index < source.length; index += 1) {
    if (source[index] === '{') depth += 1;
    if (source[index] === '}') depth -= 1;
    if (depth === 0) return source.slice(start, source.indexOf(';', index) + 1);
  }
  throw new Error(`unterminated ${name}`);
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function overlayNode() {
  return {
    id: '',
    innerHTML: '',
    style: { cssText: '' },
    listeners: {},
    removed: false,
    addEventListener(type, fn) { this.listeners[type] = fn; },
    remove() { this.removed = true; },
  };
}

function load() {
  const state = {
    current: null,
    appended: [],
    created: [],
  };
  const ctx = {
    location: { origin: 'http://127.0.0.1:8000' },
    URL, localStorage: {getItem: () => 'en'},
    t: key => key === 'instr.params_topdonator' ? 'URL-варианты: /widget/top-donator-alltime | -month | -day' : key,
    openPanelDialog(node, options) { node.dialogOptions = options; },
    closePanelDialog(node) { node.remove(); },
    esc: escapeHtml,
    document: {
      getElementById(id) {
        return id === 'widgetInstrModal' ? state.current : null;
      },
      createElement(tag) {
        assert.equal(tag, 'div');
        const node = overlayNode();
        state.created.push(node);
        return node;
      },
      body: {
        appendChild(node) {
          state.current = node;
          state.appended.push(node);
        },
      },
    },
  };
  vm.createContext(ctx);
  vm.runInContext([
    functionSource('static/app/07_widgets.js', 'widgetOutputUrl'),
    extractObjectConst(SOURCE, 'WIDGET_INSTR_PARAMS'),
    extractFunction(SOURCE, 'showWidgetInstr'),
  ].join('\n'), ctx);
  return { ctx, state };
}

test('known widget: replaces old modal and renders URL, size and slug-specific parameters', () => {
  const { ctx, state } = load();
  const old = overlayNode();
  state.current = old;

  ctx.showWidgetInstr('/widget/animated-bg', 'animated-bg', 1920, 1080);

  assert.equal(old.removed, true, 'opening a modal removes the previous one');
  assert.equal(state.appended.length, 1);
  const modal = state.current;
  assert.equal(modal.id, 'widgetInstrModal');
  assert.match(modal.style.cssText, /position:fixed/);
  assert.match(modal.innerHTML, /http:\/\/127\.0\.0\.1:8000\/widget\/animated-bg/);
  assert.match(modal.innerHTML, /1920 × 1080/);
  assert.match(modal.innerHTML, /type=snow\|stars\|rain/, 'hyphenated slug normalized to animatedbg');
  assert.match(modal.innerHTML, /instr\.params/);
  assert.match(modal.innerHTML, /instr\.common_params/);
});

test('unknown widget: default size and common parameters without a fake widget-specific section', () => {
  const { ctx, state } = load();
  ctx.showWidgetInstr('/widget/custom', 'custom');
  const html = state.current.innerHTML;
  assert.match(html, /800 × 600/);
  assert.doesNotMatch(html, /instr\.params/);
  assert.match(html, /\?theme=dark\|light\|neon\|glass\|fire\|minimal/);
  assert.match(html, /\?scale=1\.5/);
  assert.match(html, /\?api=http:\/\/panel:8000/);
});

test('backdrop click closes modal; child click does not', () => {
  const { ctx, state } = load();
  ctx.showWidgetInstr('/widget/goals', 'goals', 500, 500);
  const modal = state.current;
  assert.equal(typeof modal.listeners.click, 'function');

  modal.listeners.click({ target: {} });
  assert.equal(modal.removed, false, 'click inside the card must keep modal open');
  modal.listeners.click({ target: modal });
  assert.equal(modal.removed, true, 'click on backdrop closes modal');
});

test('URL and translated strings are escaped before insertion into innerHTML', () => {
  const { ctx, state } = load();
  ctx.location.origin = 'http://local.test';
  ctx.t = key => `${key}<img src=x onerror=bad()>`;
  ctx.showWidgetInstr('/widget/<script>bad()</script>', 'unknown', 1, 2);
  const html = state.current.innerHTML;
  assert.doesNotMatch(html, /<script>bad\(\)<\/script>/);
  assert.doesNotMatch(html, /<img src=x onerror=bad\(\)>/);
  assert.match(html, /%3Cscript%3Ebad\(\)%3C\/script%3E/);
  assert.match(html, /ui_lang=en/);
  assert.match(html, /instr\.title&lt;img/);
});

test('top-donator hyphenated slug resolves documented URL variants', () => {
  const { ctx, state } = load();
  ctx.showWidgetInstr('/widget/top-donator', 'top-donator', 500, 240);
  assert.match(state.current.innerHTML, /top-donator-alltime \| -month \| -day/);
});
