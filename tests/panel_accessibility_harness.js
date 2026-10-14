const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Element {
  constructor(tag, doc, attrs = {}) {
    this.tagName = tag.toUpperCase(); this.nodeType = 1; this.ownerDocument = doc; this.parentElement = null;
    this.children = []; this.attributes = new Map(); this._text = ''; this.inert = false;
    this.hidden = false; this.disabled = false; this.value = ''; this.open = false;
    this.style = {display: 'block', visibility: 'visible', overflow: '',
      setProperty(key, value) { this[key] = value; }, removeProperty(key) { delete this[key]; }};
    this.listeners = {}; this.dataset = {};
    this.classList = {values: new Set(), add: (...names) => names.forEach(n => this.classList.values.add(n)),
      remove: (...names) => names.forEach(n => this.classList.values.delete(n)), contains: n => this.classList.values.has(n),
      toggle: (name, force) => { const on = force ?? !this.classList.contains(name); this.classList[on ? 'add' : 'remove'](name); return on; }};
    for (const [key, value] of Object.entries(attrs)) this.setAttribute(key, value);
  }
  get id() { return this.getAttribute('id') || ''; }
  set id(value) { this.setAttribute('id', value); }
  get className() { return [...this.classList.values].join(' '); }
  set className(value) { this.classList.values = new Set(value.split(/\s+/).filter(Boolean)); }
  get isConnected() { return this === this.ownerDocument.documentElement || !!this.parentElement?.isConnected; }
  get textContent() { return this._text + this.children.map(c => c.textContent).join(''); }
  set textContent(value) { this._text = String(value); this.children.forEach(c => c.parentElement = null); this.children = []; }
  get firstElementChild() { return this.children[0] || null; }
  get nextElementSibling() { const list = this.parentElement?.children || []; return list[list.indexOf(this) + 1] || null; }
  get previousElementSibling() { const list = this.parentElement?.children || []; return list[list.indexOf(this) - 1] || null; }
  get tabIndex() { return this.hasAttribute('tabindex') ? Number(this.getAttribute('tabindex')) : /^(BUTTON|INPUT|SELECT|TEXTAREA|SUMMARY)$/.test(this.tagName) || this.hasAttribute('href') ? 0 : -1; }
  setAttribute(key, value) {
    this.attributes.set(key, String(value));
    if (key === 'class') this.className = String(value);
    if (key.startsWith('data-')) this.dataset[key.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = String(value);
  }
  getAttribute(key) { return this.attributes.get(key) ?? null; }
  hasAttribute(key) { return this.attributes.has(key); }
  removeAttribute(key) { this.attributes.delete(key); }
  appendChild(child) { child.remove(); child.parentElement = this; this.children.push(child); return child; }
  remove() { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(c => c !== this); this.parentElement = null; }
  contains(node) { return this === node || this.children.some(c => c.contains(node)); }
  focus() { this.ownerDocument.activeElement = this; this.ownerDocument.listeners.focusin?.forEach(fn => fn({target: this})); }
  click() { this.onclick?.(); (this.listeners.click || []).forEach(fn => fn({target: this, stopPropagation() {}})); }
  addEventListener(type, callback) { (this.listeners[type] ||= []).push(callback); }
  matches(selector) {
    return selector.split(',').some(raw => {
      let rule = raw.trim();
      const not = [...rule.matchAll(/:not\(([^)]+)\)/g)];
      if (not.some(m => this.matches(m[1]))) return false;
      rule = rule.replace(/:not\([^)]+\)/g, '');
      if (rule.includes(':disabled')) { if (!this.disabled) return false; rule = rule.replace(':disabled', ''); }
      const tag = rule.match(/^[a-z][a-z0-9-]*/i)?.[0];
      if (tag && this.tagName !== tag.toUpperCase()) return false;
      if ([...rule.matchAll(/\.([\w-]+)/g)].some(m => !this.classList.contains(m[1]))) return false;
      if ([...rule.matchAll(/#([\w-]+)/g)].some(m => this.id !== m[1])) return false;
      for (const m of rule.matchAll(/\[([\w-]+)(?:=["']?([^\]"']+)["']?)?\]/g)) {
        if (!this.hasAttribute(m[1]) || (m[2] !== undefined && this.getAttribute(m[1]) !== m[2])) return false;
      }
      return true;
    });
  }
  querySelectorAll(selector) {
    if (selector.startsWith(':scope > ')) {
      const [first, rest] = selector.slice(9).split(' > ');
      const nodes = this.children.filter(c => c.matches(first));
      return rest ? nodes.flatMap(n => n.children.filter(c => c.matches(rest))) : nodes;
    }
    return this.children.flatMap(child => [...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector)]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) { return this.matches(selector) ? this : this.parentElement?.closest(selector) || null; }
}

function functionSource(file, name) {
  const source = fs.readFileSync(path.join(__dirname, '..', file), 'utf8');
  const marker = source.indexOf(`function ${name}(`);
  if (marker < 0) throw new Error(`Missing function ${name}`);
  const start = source.slice(marker - 6, marker) === 'async ' ? marker - 6 : marker;
  return source.slice(start, source.indexOf('\n}', marker) + 2);
}

function environment() {
  const document = {listeners: {}, title: '',
    createElement(tag) { return new Element(tag, this); },
    addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); },
    getElementById(id) { return this.documentElement.querySelectorAll('[id]').find(n => n.id === id) || null; },
    querySelectorAll(selector) { return this.documentElement.querySelectorAll(selector); },
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; },
  };
  document.documentElement = new Element('html', document);
  document.body = document.documentElement.appendChild(document.createElement('body'));
  document.activeElement = document.body;
  const storage = new Map();
  const ctx = {document, console, LANGS: {ru: {'app.title': 'Панель'}, en: {'app.title': 'Panel'}, ua: {'app.title': 'Панель'}},
    localStorage: {getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value)},
    window: {getComputedStyle: element => element.style},
    MutationObserver: class { constructor(fn) { this.callback = fn; } observe() {} disconnect() {} },
    _allBots: [], localizeLegacyNodes() {},
  };
  vm.createContext(ctx);
  vm.runInContext(functionSource('static/app.js', 'hasTranslation') + '\n' + functionSource('static/app.js', 't'), ctx);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'static/app/22_panel_accessibility.js'), 'utf8'), ctx);
  const element = (tag, attrs = {}, parent = document.body, text = '') => {
    const node = new Element(tag, document, attrs); node.textContent = text; parent.appendChild(node); return node;
  };
  const modal = id => {
    const root = element('div', {id, class: 'modal-backdrop hidden'});
    const dialog = element('div', {class: 'modal'}, root);
    const title = element('h2', {}, dialog, id);
    const description = element('p', {}, dialog, 'Description');
    return {root, dialog, title, description};
  };
  return {ctx, document, storage, element, modal};
}

module.exports = {environment, functionSource};
