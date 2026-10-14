// Владелец 27.09 (вечер): дашборд «здоровье эфира» — карточка на Обзоре.
// Движковая часть (кто подключён/отвечает/молчит и почему) — tests/test_stream_health.py.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const read = file => fs.readFileSync(path.join(__dirname, '..', file), 'utf8');

test('карточка на Обзоре и вызов из loadDashboard() на месте', () => {
    const dashboard = read('templates/partials/dashboard.html');
    assert.match(dashboard, /id="streamHealthTable"/);
    assert.match(dashboard, /data-i18n="health\.title"/);

    const js = read('static/app/02_dashboard.js');
    assert.match(js, /function loadStreamHealth\(/);
    assert.match(js, /loadStreamHealth\(\);/, 'loadDashboard() зовёт loadStreamHealth()');
});

test('i18n-ключи health.* есть во всех трёх языках', () => {
    const src = read('static/app.js');
    for (const key of ['health.title', 'health.silent', 'health.responds', 'health.last_activity', 'health.empty']) {
        const count = (src.match(new RegExp(`'${key.replace('.', '\\.')}':`, 'g')) || []).length;
        assert.equal(count, 3, `${key} — ровно в ru/en/ua`);
    }
});

function bootDashboardUI(apiImpl) {
    const nodes = {};
    const ctx = vm.createContext({
        console,
        document: {
            getElementById: id => nodes[id] || null,
            querySelectorAll: () => [],
        },
        $: id => nodes[id] || null,
        esc: v => String(v ?? ''),
        t: key => key,
        api: apiImpl,
    });
    ctx.window = ctx;
    vm.runInContext(read('static/app/02_dashboard.js'), ctx);
    return { ctx, nodes, run: code => vm.runInContext(code, ctx) };
}

test('loadStreamHealth рендерит канал/бота/причину молчания и не падает на пустом ответе', async () => {
    const env = bootDashboardUI(async () => ({
        channels: [{
            channel: 'test_channel',
            bots: [
                { account_id: 1, nickname: 'lurky', role: 'lurker', connected: true, silent: true, reason: 'lurker молчит (mention_reply=off)', last_activity_at: '' },
                { account_id: 2, nickname: 'chatty', role: 'chatter', connected: true, silent: false, reason: '', last_activity_at: '2026-09-27T19:00:00' },
            ],
        }],
    }));
    env.nodes.streamHealthTable = { innerHTML: '' };
    await env.run('loadStreamHealth()');
    const html = env.nodes.streamHealthTable.innerHTML;
    assert.match(html, /test_channel/);
    assert.match(html, /lurky/);
    assert.match(html, /mention_reply=off/);
    assert.match(html, /chatty/);

    const env2 = bootDashboardUI(async () => ({ channels: [] }));
    env2.nodes.streamHealthTable = { innerHTML: '' };
    await env2.run('loadStreamHealth()');
    assert.match(env2.nodes.streamHealthTable.innerHTML, /health\.empty/);
});