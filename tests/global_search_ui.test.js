// Владелец 27.09 (вечер): глобальный поиск (Ctrl+K) раньше находил только
// разделы и ботов по нику — теперь ищет и внутри карточек «Настроек», и во
// вкладках карточки бота (TTS живёт только там, DEC-OWNER-016), не только
// в самих названиях разделов.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const read = file => fs.readFileSync(path.join(__dirname, '..', file), 'utf8');

// Изолированный блок вместо vm-исполнения всего app.js (2800+ строк с
// top-level side-эффектами) — тот же паттерн, что и в остальных UI-тестах
// этого репозитория для static/app.js (строковые ассерты), но здесь ещё и
// поведенчески проверяем сами функции поиска.
function extractSearchBlock() {
    const src = read('static/app.js');
    const start = src.indexOf('// ── Global search');
    const end = src.indexOf('\n// ── WebSocket');
    if (start === -1 || end === -1) throw new Error('search block markers not found');
    return src.slice(start, end);
}

test('блок глобального поиска на месте (маркеры не съехали)', () => {
    const block = extractSearchBlock();
    assert.match(block, /GLOBAL_SETTINGS_CARD_SEARCH_KEYS/);
    assert.match(block, /function findBotTabBySearch/);
    assert.match(block, /async function handleGlobalSearch/);
});

test('id-шники в GLOBAL_SETTINGS_CARD_SEARCH_KEYS реально существуют в settings.html', () => {
    const block = extractSearchBlock();
    const m = block.match(/const GLOBAL_SETTINGS_CARD_SEARCH_KEYS = \{([\s\S]*?)\n\};/);
    assert.ok(m, 'реестр карточек настроек найден');
    const ids = [...m[1].matchAll(/'([A-Za-z0-9_-]+)':/g)].map(x => x[1]);
    assert.ok(ids.length >= 10, 'реестр не пустой');
    const settingsHtml = read('templates/partials/settings.html');
    for (const id of ids) {
        assert.match(settingsHtml, new RegExp(`id="${id}"`), `#${id} есть в settings.html`);
    }
});

function bootSearchBlock(botTabGroups) {
    const nodes = {};
    const calls = { toasts: [], sections: [], scroll: [], botTabs: [], openedBotId: null };
    const ctx = vm.createContext({
        console,
        LANGS: { ru: {}, en: {} },
        document: {
            getElementById: id => nodes[id] || null,
        },
        BOT_TAB_GROUPS: botTabGroups,
        toast: (msg) => calls.toasts.push(msg),
        t: key => key,
        showSection: (s) => calls.sections.push(s),
        showBotTab: (tab) => calls.botTabs.push(tab),
        openBotSettings: (id) => { calls.openedBotId = id; },
        // Реалистичный стаб: как настоящий loadBotsList(), переприсваивает _allBots
        // после рефетча — тест должен ловить гонку, если код читает id ПОСЛЕ этого.
        loadBotsList: () => Promise.resolve().then(() => { ctx._allBots = [{ id: 999, nickname: 'refetched-other-bot' }]; }),
        api: async () => ({ accounts: [] }),
        _allBots: [],
    });
    ctx.window = ctx;
    vm.runInContext(extractSearchBlock(), ctx);
    return { ctx, nodes, calls, run: code => vm.runInContext(code, ctx) };
}

test('findSettingsCardBySearch находит карточку по любому языку из LANGS', () => {
    const env = bootSearchBlock({});
    env.ctx.LANGS = {
        ru: { 'settings.backup': '💾 Резервная копия' },
        en: { 'settings.backup': '💾 Backup' },
    };
    assert.equal(env.run("findSettingsCardBySearch('резерв')"), 'settingsCard-backup');
    assert.equal(env.run("findSettingsCardBySearch('backup')"), 'settingsCard-backup');
    assert.equal(env.run("findSettingsCardBySearch('совсем не то')"), undefined);
});

test('findBotTabBySearch ищет по стабильному id вкладки, не по переводу', () => {
    const env = bootSearchBlock({ voice: ['tts', 'voice-clones'], moderation: ['moderation'] });
    assert.equal(env.run("findBotTabBySearch('tts')"), 'tts');
    assert.equal(env.run("findBotTabBySearch('voice')"), 'voice-clones');
    assert.equal(env.run("findBotTabBySearch('нет такого')"), null);
});

test('handleGlobalSearch: один бот — сразу открывает его на найденной вкладке', async () => {
    const env = bootSearchBlock({ voice: ['tts'] });
    env.ctx._allBots = [{ id: 42, nickname: 'onlybot' }];
    env.ctx.LANGS = { ru: {} };
    await env.run("handleGlobalSearch({ key: 'Enter', target: { value: 'tts' } })");
    assert.deepEqual(env.calls.sections, ['bots']);
    assert.equal(env.calls.openedBotId, 42, 'id захвачен ДО loadBotsList(), а не после его переприсваивания _allBots');
    assert.deepEqual(env.calls.botTabs, ['tts']);
    assert.equal(env.calls.toasts.length, 0, 'один бот — без уточняющего тоста');
});

test('handleGlobalSearch: несколько ботов — уточняющий тост, бот не выбирается за владельца', async () => {
    const env = bootSearchBlock({ voice: ['tts'] });
    env.ctx._allBots = [{ id: 1, nickname: 'a' }, { id: 2, nickname: 'b' }];
    env.ctx.LANGS = { ru: {} };
    await env.run("handleGlobalSearch({ key: 'Enter', target: { value: 'tts' } })");
    assert.deepEqual(env.calls.sections, ['bots']);
    assert.equal(env.calls.openedBotId, null, 'за владельца бот не выбирается');
    assert.equal(env.calls.toasts.length, 1);
});