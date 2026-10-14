const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('static/app/04_chat_settings.js', 'utf8');

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

const elements = {};
function element(id) {
    if (!elements[id]) {
        const classes = new Set(['hidden']);
        elements[id] = {
            id,
            type: '',
            value: '',
            textContent: '',
            classList: {
                add(value) { classes.add(value); },
                remove(value) { classes.delete(value); },
                contains(value) { return classes.has(value); },
            },
        };
    }
    return elements[id];
}

let pendingTimer = null;
let copied = '';
const context = {
    $: element,
    t: key => key,
    clearTimeout() { pendingTimer = null; },
    setTimeout(callback, delay) { pendingTimer = {callback, delay}; return 1; },
    navigator: {clipboard: {async writeText(value) { copied = value; }}},
};
vm.createContext(context);
vm.runInContext(`
let modMediaRevealTimer = null;
let modMediaRevealedUrl = '';
let modMediaTokenConfigured = false;
${extractFunction('hideModeratorMediaToken')}
${extractFunction('showModeratorMediaToken')}
${extractFunction('copyModeratorMediaToken')}
this.api = {hideModeratorMediaToken, showModeratorMediaToken, copyModeratorMediaToken};
`, context);

(async () => {
    const url = 'http://127.0.0.1/widget/moderator-media?token=secret';
    context.api.showModeratorMediaToken(url);
    assert.equal(element('modMediaObsUrl').type, 'text');
    assert.equal(element('modMediaObsUrl').value, url);
    assert.equal(element('modMediaCopy').classList.contains('hidden'), false);
    assert.equal(pendingTimer.delay, 30000);

    await context.api.copyModeratorMediaToken();
    assert.equal(copied, url);
    pendingTimer.callback();
    assert.equal(element('modMediaObsUrl').type, 'password');
    assert.equal(element('modMediaObsUrl').value, '••••••••');
    assert.equal(element('modMediaCopy').classList.contains('hidden'), true);
    assert.equal(element('modMediaTokenStatus').textContent, 'settings.mod_media_hidden');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
