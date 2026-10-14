const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('static/app.js', 'utf8');
const widgetsSource = fs.readFileSync('static/app/07_widgets.js', 'utf8');

function extractFunction(name) {
    const asyncStart = source.indexOf(`async function ${name}(`);
    const start = asyncStart === -1 ? source.indexOf(`function ${name}(`) : asyncStart;
    assert.notEqual(start, -1, `${name} missing`);
    const body = source.indexOf('{', start);
    let depth = 0;
    for (let index = body; index < source.length; index += 1) {
        if (source[index] === '{') depth += 1;
        if (source[index] === '}') depth -= 1;
        if (depth === 0) return source.slice(start, index + 1);
    }
    throw new Error(`${name} is incomplete`);
}

const translations = {
    'api.error.invalid_channel': 'Channel: {channel}',
    'api.error.unknown': 'Безопасная ошибка',
};
const replies = [];
const context = {
    LANGS: {ru: translations, en: {}, ua: {}},
    fetch: async () => replies.shift(),
    t(key, params = {}) {
        let value = translations[key] || key;
        for (const [name, replacement] of Object.entries(params)) {
            value = value.replaceAll(`{${name}}`, String(replacement));
        }
        return value;
    },
};
vm.createContext(context);
vm.runInContext(`
const API = '';
${extractFunction('apiErrorInfo')}
${extractFunction('api')}
this.api = api;
`, context);

function response(status, payload, statusText = '') {
    return {ok: status >= 200 && status < 300, status, statusText, async json() { return payload; }};
}

(async () => {
    replies.push(response(200, {ok: true, value: 1}));
    assert.equal((await context.api('/success')).value, 1);

    replies.push(response(200, {ok: false, error: 'legacy_problem'}));
    await assert.rejects(context.api('/legacy'), error => {
        assert.equal(error.message, 'legacy_problem');
        assert.equal(error.status, 200);
        return true;
    });

    replies.push(response(400, {
        ok: false,
        error: {code: 'invalid_channel', params: {channel: 'demo'}},
    }));
    await assert.rejects(context.api('/new'), error => {
        assert.equal(error.message, 'Channel: demo');
        assert.equal(error.code, 'invalid_channel');
        assert.equal(error.params.channel, 'demo');
        return true;
    });

    replies.push(response(500, {
        ok: false,
        error: {code: 'untranslated_server_detail', params: {detail: 'private-token'}},
    }));
    await assert.rejects(context.api('/unknown'), error => {
        assert.equal(error.message, 'Безопасная ошибка');
        assert.doesNotMatch(error.message, /private-token|untranslated_server_detail/);
        return true;
    });

    for (const lang of ['ru', 'en', 'ua']) {
        assert.match(source, new RegExp(`Object\\.assign\\(LANGS\\.${lang}, \\{[\\s\\S]*?'api\\.error\\.unknown'`));
    }
    assert.match(widgetsSource, /return api\(url,/);
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
