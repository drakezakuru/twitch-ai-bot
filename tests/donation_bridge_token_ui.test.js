const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('static/app/13_widgets_session.js', 'utf8');

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
    toast() {},
    clearTimeout() { pendingTimer = null; },
    setTimeout(callback, delay) { pendingTimer = {callback, delay}; return 1; },
    navigator: {clipboard: {async writeText(value) { copied = value; }}},
};
vm.createContext(context);
vm.runInContext(`
let _waDonationBridgeToken = '';
let _waDonationBridgeHideTimer = null;
${extractFunction('waDonationBridgeHide')}
${extractFunction('waDonationBridgeShow')}
${extractFunction('waDonationBridgeCopy')}
this.api = {waDonationBridgeHide, waDonationBridgeShow, waDonationBridgeCopy};
`, context);

(async () => {
    const token = 'local-bridge-secret';
    context.api.waDonationBridgeShow(token, 'donation.bridge.rotated');
    assert.equal(element('waDonBridgeValue').value, token);
    assert.equal(element('waDonBridgeSecret').classList.contains('hidden'), false);
    assert.equal(element('waDonBridgeMessage').textContent, 'donation.bridge.rotated');
    assert.equal(pendingTimer.delay, 30000);

    await context.api.waDonationBridgeCopy();
    assert.equal(copied, token);
    pendingTimer.callback();
    assert.equal(element('waDonBridgeValue').value, '');
    assert.equal(element('waDonBridgeSecret').classList.contains('hidden'), true);
    assert.equal(element('waDonBridgeMessage').textContent, 'donation.bridge.hidden');

    for (const lang of ['ru', 'en', 'ua']) {
        assert.match(source, new RegExp(`Object\\.assign\\(LANGS\\.${lang}`));
    }
    assert.match(source, /wstateapi\('\/api\/widgets\/donation-integration'\)/);
    assert.match(source, /wstateapi\('\/api\/widgets\/donation-bridge'\)/);
    assert.match(extractFunction('waBindingScopeChange'), /waDonationBridgeHide\(\)/);
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
