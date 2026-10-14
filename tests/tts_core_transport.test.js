// Runs tts-core in a deliberately tiny browser shim; no DOM test dependency needed.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const CORE = fs.readFileSync(path.join(__dirname, '..', 'widgets', '_shared', 'tts-core.js'), 'utf8');

function runtime() {
  const timers = [];
  const sockets = [];
  class FakeWebSocket {
    constructor(url) {
      this.url = url;
      this.closed = false;
      sockets.push(this);
    }
    close() {
      this.closed = true;
    }
  }
  const context = {
    URLSearchParams,
    Uint8Array,
    WebSocket: FakeWebSocket,
    location: { search: '', host: 'panel.test', protocol: 'http:' },
    setTimeout(callback) {
      timers.push(callback);
      return timers.length - 1;
    },
    clearTimeout(id) {
      timers[id] = null;
    },
  };
  context.window = context;
  vm.runInNewContext(CORE, context, { filename: 'tts-core.js' });
  context.sockets = sockets;
  context.timers = timers;
  return context;
}

test('reconnect ignores stale socket events and schedules one retry', () => {
  const browser = runtime();
  const closes = [];
  const transport = browser.TtsCore.connect({ onClose: () => closes.push('close') });
  const first = browser.sockets[0];

  first.onclose();
  first.onclose();
  assert.equal(closes.length, 1);
  assert.equal(browser.timers.filter(Boolean).length, 1);

  const retryId = browser.timers.findIndex(Boolean);
  const retry = browser.timers[retryId];
  browser.timers[retryId] = null;
  retry();
  const second = browser.sockets[1];
  assert.ok(second);

  first.onerror();
  first.onclose();
  assert.equal(second.closed, false, 'a stale socket must not close the active connection');
  assert.equal(browser.timers.filter(Boolean).length, 0, 'a stale close must not create another retry');

  transport.close();
  assert.equal(second.closed, true);
  second.onopen();
  second.onmessage({ data: JSON.stringify({ type: 'tts', text: 'late' }) });
  second.onclose();
  assert.equal(closes.length, 1, 'manual disposal must not emit a consumer close callback');
  assert.equal(browser.timers.filter(Boolean).length, 0, 'manual disposal must not reconnect');
});

test('base64 queue advances once when audio emits duplicate terminal events', () => {
  const browser = runtime();
  const audios = [];
  browser.atob = () => 'a';
  browser.Blob = class {};
  browser.URL = { createObjectURL: () => 'blob:audio', revokeObjectURL() {} };
  browser.Audio = class {
    constructor() { audios.push(this); }
    play() { return Promise.resolve(); }
  };

  const starts = [];
  const queue = browser.TtsCore.queue();
  queue.push({ audio_b64: 'YQ==', onStart: () => starts.push('first') });
  queue.push({ audio_b64: 'YQ==', onStart: () => starts.push('second') });
  assert.deepEqual(starts, ['first']);

  audios[0].onended();
  audios[0].onerror();
  assert.deepEqual(starts, ['first', 'second']);

  audios[1].onended();
  assert.equal(queue.speaking, false);
  assert.equal(queue.length, 0);
});
