'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const base = fs.readFileSync(path.join(__dirname, '../templates/base.html'), 'utf8');
const boot = base.match(/<script id="panelThemeBoot">([\s\S]*?)<\/script>/)[1];

function context(storage) {
    const attributes = new Map([['data-theme', 'light'], ['data-panel-theme', 'dark']]);
    const sandbox = {
        document: { documentElement: { setAttribute: (name, value) => attributes.set(name, value) } },
        localStorage: storage,
    };
    return { sandbox, attributes };
}

for (const saved of [undefined, 'light', 'dark', 'invalid']) {
    test(`pre-paint boot normalizes persisted theme ${saved}`, () => {
        const storage = new Map([['theme', saved], ['widget-theme', 'light'], ['bgPreset', 'ocean']]);
        const { sandbox, attributes } = context({ setItem: (key, value) => storage.set(key, value) });
        vm.runInNewContext(boot, sandbox);
        assert.equal(attributes.get('data-theme'), 'dark');
        assert.equal(attributes.get('data-panel-theme'), 'dark');
        assert.equal(storage.get('theme'), 'dark');
        assert.equal(storage.get('widget-theme'), 'light');
        assert.equal(storage.get('bgPreset'), 'ocean');
    });
}

test('pre-paint dark does not depend on writable storage', () => {
    const { sandbox, attributes } = context({ setItem() { throw new Error('storage denied'); } });
    assert.doesNotThrow(() => vm.runInNewContext(boot, sandbox));
    assert.equal(attributes.get('data-theme'), 'dark');
});

test('pre-paint dark survives an unavailable storage getter', () => {
    const { sandbox, attributes } = context();
    Object.defineProperty(sandbox, 'localStorage', { get() { throw new Error('SecurityError'); } });
    assert.doesNotThrow(() => vm.runInNewContext(boot, sandbox));
    assert.equal(attributes.get('data-theme'), 'dark');
});

// Q22: плотная сетка карточек ботов — карточки по высоте контента, плотнее колонки.
test('bots grid is dense: content-height cards and tighter columns', () => {
    const css = fs.readFileSync(path.join(__dirname, '../static/app.css'), 'utf8');
    const botsJs = fs.readFileSync(path.join(__dirname, '../static/app/03_bots.js'), 'utf8');
    const rule = css.match(/\.bots-grid\s*\{[^}]*\}/);
    assert.ok(rule, '.bots-grid rule exists');
    assert.match(rule[0], /align-items:\s*start/);
    assert.match(rule[0], /minmax\(250px,\s*1fr\)/);
    assert.match(botsJs, /class="grid-cards bots-grid"/);
});

// Регрессия: форма роли модератора использует `flex-wrap`; без определения утилиты
// 16 полей становятся одной строкой и уходят за правую границу на desktop-ширине.
test('role configuration has a working flex-wrap utility', () => {
    const css = fs.readFileSync(path.join(__dirname, '../static/app.css'), 'utf8');
    const rolesJs = fs.readFileSync(path.join(__dirname, '../static/app/06_roles.js'), 'utf8');
    assert.match(rolesJs, /class="flex gap-3 flex-wrap"/);
    assert.match(css, /\.flex-wrap\s*\{\s*flex-wrap:\s*wrap;\s*\}/);
});
