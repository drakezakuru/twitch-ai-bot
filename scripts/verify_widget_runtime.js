#!/usr/bin/env node
/* Прогон отданных панелью виджетов в реальном DOM (jsdom).
 *
 * Зачем: статический рендер и grep не видят, что виджет не подключил общее
 * ядро — страница молча падает на `CharacterCore is not defined`, а в OBS это
 * выглядит как «виджет перестал двигаться». Здесь страница реально
 * исполняется, WS/fetch/аудио заглушены, и любая ошибка старта — падение.
 *
 * Запуск (панель должна быть поднята на :8000):
 *   npm install --no-save jsdom && node scripts/verify_widget_runtime.js
 */
const path = require('path');
const http = require('http');

let JSDOM, VirtualConsole;
try {
  ({ JSDOM, VirtualConsole } = require('jsdom'));
} catch (e) {
  try {
    ({ JSDOM, VirtualConsole } = require(path.join(process.env.JSDOM_PATH || '/tmp/node_modules', 'jsdom')));
  } catch (e2) {
    console.error('jsdom не установлен: npm install --no-save jsdom');
    process.exit(2);
  }
}

const BASE = process.env.PANEL_BASE || 'http://127.0.0.1:8000';
const PAGES = [
  '/obs/tts?channel=demo',
  '/widget/tts-bot',
  '/widget/chat-reader',
  '/widget/tts-chat-overlay',
  '/widget/mascot',
  '/widget/anime-runner',
];

function get(p) {
  return new Promise((res, rej) => {
    http.get(BASE + p, (r) => {
      let d = '';
      r.on('data', (c) => (d += c));
      r.on('end', () => res(d));
    }).on('error', rej);
  });
}

(async () => {
  let failed = 0;
  for (const page of PAGES) {
    const html = await get(page);
    const errors = [];
    const vc = new VirtualConsole();
    vc.on('jsdomError', (e) => errors.push(e.message));

    const dom = new JSDOM(html, {
      virtualConsole: vc,
      runScripts: 'dangerously',
      resources: {
        fetch(url) {
          if (url.startsWith(BASE + '/widget/_shared/')) {
            return get(url.slice(BASE.length)).then((t) => Buffer.from(t));
          }
          return null;
        },
      },
      url: BASE + page,
      pretendToBeVisual: true,
      beforeParse(win) {
        win.WebSocket = class { constructor() { this.readyState = 0; } send() {} close() {} };
        win.fetch = () => Promise.resolve({ json: () => Promise.resolve({}) });
        win.speechSynthesis = { getVoices: () => [], speak() {}, cancel() {} };
        win.SpeechSynthesisUtterance = function () {};
        win.HTMLMediaElement.prototype.play = () => Promise.resolve();
      },
    });

    await new Promise((r) => setTimeout(r, 900));

    const w = dom.window;
    const usesTts = html.includes('_shared/tts-core.js');
    const usesChar = html.includes('_shared/character-core.js');
    if (usesTts && typeof w.TtsCore === 'undefined') errors.push('TtsCore не загрузился');
    if (usesChar && typeof w.CharacterCore === 'undefined') errors.push('CharacterCore не загрузился');

    const ok = errors.length === 0;
    if (!ok) failed++;
    console.log((ok ? 'OK   ' : 'FAIL ') + page +
      (usesTts ? ' [tts-core]' : '') + (usesChar ? ' [character-core]' : ''));
    errors.slice(0, 4).forEach((e) => console.log('       ' + String(e).split('\n')[0].slice(0, 160)));
    w.close();
  }
  console.log(failed ? `\n${failed} widget(s) FAILED` : '\nвсе виджеты стартовали без ошибок');
  process.exit(failed ? 1 : 0);
})();
