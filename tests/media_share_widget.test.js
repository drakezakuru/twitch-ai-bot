const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const CORE = fs.readFileSync(path.join(__dirname, '..', 'widgets', '_shared', 'media-share-core.js'), 'utf8');
const WIDGET = fs.readFileSync(path.join(__dirname, '..', 'widgets', 'media-share', 'index.html'), 'utf8');

function runtime() {
  const timers = [];
  const sockets = [];
  class FakeWebSocket {
    constructor(url) { this.url = url; this.closed = false; sockets.push(this); }
    close() { this.closed = true; }
  }
  const context = {
    WebSocket: FakeWebSocket,
    setTimeout(callback) { timers.push(callback); return timers.length - 1; },
    clearTimeout(id) { timers[id] = null; },
  };
  context.window = context;
  vm.runInNewContext(CORE, context, {filename: 'media-share-core.js'});
  return {context, timers, sockets};
}

test('offline and provider errors remain visible until their own recovery', () => {
  const browser = runtime();
  const renders = [];
  const states = browser.context.MediaShareCore.statusStore(
    (key, message) => renders.push([key, message]),
    ['embed_error', 'youtube_api', 'autoplay', 'queue_offline', 'bus_reconnecting'],
  );

  states.set('queue_offline', 'offline');
  states.set('bus_reconnecting', 'reconnecting');
  assert.deepEqual(renders.at(-1), ['queue_offline', 'offline']);
  states.set('embed_error', 'embed blocked');
  assert.deepEqual(renders.at(-1), ['embed_error', 'embed blocked']);
  states.clear('embed_error');
  assert.deepEqual(renders.at(-1), ['queue_offline', 'offline']);
  states.clear('queue_offline');
  assert.deepEqual(renders.at(-1), ['bus_reconnecting', 'reconnecting']);
  states.clear('bus_reconnecting');
  assert.deepEqual(renders.at(-1), ['', '']);
});

test('websocket reconnect has one retry and ignores stale socket events', () => {
  const browser = runtime();
  const states = [];
  const transport = browser.context.MediaShareCore.reconnectingSocket({
    url: 'ws://panel.test/ws?channel=demo',
    WebSocket: browser.context.WebSocket,
    setTimeout: browser.context.setTimeout,
    clearTimeout: browser.context.clearTimeout,
    onState: state => states.push(state),
    onMessage() {},
  });
  const first = browser.sockets[0];
  first.onopen();
  first.onclose();
  first.onclose();
  assert.deepEqual(states, ['connecting', 'connected', 'reconnecting']);
  assert.equal(browser.timers.filter(Boolean).length, 1);

  const retryId = browser.timers.findIndex(Boolean);
  const retry = browser.timers[retryId];
  browser.timers[retryId] = null;
  retry();
  const second = browser.sockets[1];
  second.onopen();
  first.onclose();
  assert.deepEqual(states, ['connecting', 'connected', 'reconnecting', 'connecting', 'connected']);
  assert.equal(browser.timers.filter(Boolean).length, 0);

  transport.close();
  second.onclose();
  assert.equal(browser.timers.filter(Boolean).length, 0);
});

test('production widget wires offline, embed, and autoplay events to truthful states', () => {
  assert.match(WIDGET, /if \(st\.__error\)\{[\s\S]*statuses\.set\('queue_offline'/);
  assert.match(WIDGET, /onAutoplayBlocked: \(\) => statuses\.set\('autoplay'/);
  assert.match(WIDGET, /onError: \(\) => \{[\s\S]*failedGeneration = playbackGeneration[\s\S]*setTimeout\(\(\) => nextTrack\(failedVideoId, failedGeneration\), 5000\)/);
  assert.match(WIDGET, /generation !== youtubeLoadGeneration/);
  assert.match(WIDGET, /tag\.onerror = unavailable/);
  assert.match(WIDGET, /else if \(!CHANNEL\) \{[\s\S]*statuses\.set\('scope_required'/);
});
