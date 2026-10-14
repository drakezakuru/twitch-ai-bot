// Владелец 27.09 (вечер): «Календарь недели» — новая вкладка сайдбара, сетка 7 дней.
// Движковая часть (CRUD события) — tests/test_weekly_schedule.py.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const read = file => fs.readFileSync(path.join(__dirname, '..', file), 'utf8');

test('раздел, кнопка сайдбара и include на месте', () => {
    const base = read('templates/base.html');
    assert.match(base, /data-section="calendar"/);
    assert.match(base, /\{% include 'partials\/calendar\.html' %\}/);
    assert.match(base, /27_weekly_calendar\.js/);

    const calendar = read('templates/partials/calendar.html');
    assert.match(calendar, /id="section-calendar"/);
    assert.match(calendar, /id="calendarGrid"/);
    assert.match(calendar, /id="calendarEventModal"/);

    const appJs = read('static/app.js');
    assert.match(appJs, /if \(name === 'calendar'\) loadCalendarSection\(\);/);
    const chatSettingsJs = read('static/app/04_chat_settings.js');
    const m = chatSettingsJs.match(/const valid = \[(.*?)\];/);
    assert.ok(m && m[1].includes("'calendar'"), "'calendar' в hash-whitelist showSection");
});

test('i18n-ключи calendar.* есть во всех трёх языках', () => {
    const src = read('static/app.js');
    for (const key of ['nav.calendar', 'calendar.title', 'calendar.add', 'calendar.kind_channel',
        'calendar.kind_pack', 'calendar.kind_tts', 'calendar.mon', 'calendar.sun']) {
        const count = (src.match(new RegExp(`'${key.replace('.', '\\.')}':`, 'g')) || []).length;
        assert.equal(count, 3, `${key} — ровно в ru/en/ua`);
    }
});

function bootCalendarUI(apiImpl) {
    const nodes = {};
    const apiCalls = [];
    const ctx = vm.createContext({
        console,
        document: {
            getElementById: id => nodes[id] || null,
            querySelectorAll: () => [],
        },
        $: id => nodes[id] || null,
        esc: v => String(v ?? ''),
        t: key => key,
        toast() {},
        showModal() {}, hideModal() {},
        confirm: () => true,
        api: apiImpl || (async (url, opts) => { apiCalls.push({ url, opts }); return { ok: true, id: 1 }; }),
        jopts: (method, body) => ({ method, body }),
    });
    ctx.window = ctx;
    vm.runInContext(read('static/app/27_weekly_calendar.js'), ctx);
    return { ctx, nodes, apiCalls, run: code => vm.runInContext(code, ctx) };
}

test('renderCalendarGrid раскладывает события по правильным дням недели', async () => {
    const env = bootCalendarUI(async (url) => {
        if (url === '/api/weekly-schedule') {
            return {
                events: [
                    { id: 1, day_of_week: 0, time: '19:00', kind: 'channel', title: 'Эфир', channel: 'test_channel', pack_id: null, pack_name: '', note: '' },
                    { id: 2, day_of_week: 6, time: '10:00', kind: 'tts', title: 'TTS-момент', channel: '', pack_id: null, pack_name: '', note: 'заранее объявить' },
                ],
            };
        }
        return { packs: [] };
    });
    env.nodes.calendarGrid = { innerHTML: '' };
    await env.run('loadCalendarSection()');
    const html = env.nodes.calendarGrid.innerHTML;
    assert.match(html, /Эфир/);
    assert.match(html, /test_channel/);
    assert.match(html, /TTS-момент/);
    assert.match(html, /заранее объявить/);
});

test('calendarEventKindChanged переключает поля канал/пачка', () => {
    const env = bootCalendarUI();
    env.nodes.calendarEventKind = { value: 'pack' };
    env.nodes.calendarEventChannelGroup = { classList: { toggled: false, toggle(_, v) { this.toggled = v; } } };
    env.nodes.calendarEventPackGroup = { classList: { toggled: false, toggle(_, v) { this.toggled = v; } } };
    env.run('calendarEventKindChanged()');
    assert.equal(env.nodes.calendarEventChannelGroup.classList.toggled, true, 'канал скрыт при kind=pack');
    assert.equal(env.nodes.calendarEventPackGroup.classList.toggled, false, 'пачка показана при kind=pack');
});

test('submitCalendarEvent шлёт POST на create и PUT на edit', async () => {
    const env = bootCalendarUI();
    env.nodes.calendarEventId = { value: '' };
    env.nodes.calendarEventDay = { value: '2' };
    env.nodes.calendarEventTime = { value: '20:00' };
    env.nodes.calendarEventKind = { value: 'channel' };
    env.nodes.calendarEventTitleInput = { value: 'Эфир' };
    env.nodes.calendarEventChannel = { value: 'test_channel' };
    env.nodes.calendarEventPack = { value: '' };
    env.nodes.calendarEventNote = { value: '' };
    env.nodes.calendarEventError = { textContent: '' };
    await env.run('submitCalendarEvent()');
    const post = env.apiCalls.find(c => c.url === '/api/weekly-schedule' && c.opts.method === 'POST');
    assert.ok(post, 'POST на создание ушёл');
    assert.equal(post.opts.body.title, 'Эфир');

    env.apiCalls.length = 0;
    env.nodes.calendarEventId = { value: '5' };
    await env.run('submitCalendarEvent()');
    const put = env.apiCalls.find(c => c.url === '/api/weekly-schedule/5' && c.opts.method === 'PUT');
    assert.ok(put, 'PUT на редактирование ушёл');
});