/* Wave 5 (WIDGET_IMPLEMENTATION_PLAN §3): общий transport и очередь озвучки
 * для TTS-семьи — tts (tts-raw), tts-bot, chat-reader, tts-chat-overlay.
 *
 * Что здесь общего у четырёх виджетов и вынесено сюда:
 *   • адрес панели (?api=http://panel:8000) и построение ws:// / wss:// URL;
 *   • WebSocket с автопереподключением каждые 3с и колбэками open/close;
 *   • фильтр по типу сообщения и по account_id;
 *   • последовательная очередь воспроизведения (audio/base64 и Web Speech),
 *     чтобы две реплики не перебивали друг друга.
 *
 * Чего здесь НЕТ и что остаётся в каждом виджете: вся вёрстка, режим показа,
 * фильтры ролей/каналов и реакция на состояние. Публичные URL, параметры и
 * формат WS-сообщений (`type:"tts"` / `type:"chat"`) не меняются.
 */
(function () {
  'use strict';

  var qs = new URLSearchParams(location.search);
  var API_BASE = qs.get('api') || '';

  function host() {
    return API_BASE
      ? String(API_BASE).replace(/^\w+:\/\//, '').replace(/\/$/, '')
      : location.host;
  }

  function wsUrl() {
    var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    return proto + '//' + host() + '/ws?channel=' + encodeURIComponent(qs.get('channel') || '');
  }

  function outputAllowed(source) {
    var accountId = qs.get('account_id');
    var channel = String(qs.get('channel') || '').replace(/^#/, '').toLowerCase();
    if (!accountId || !channel) return Promise.resolve(true);
    var url = API_BASE + '/api/tts-audio-output/public?account_id=' + encodeURIComponent(accountId)
      + '&channel=' + encodeURIComponent(channel);
    return fetch(url, { cache: 'no-store' }).then(function (response) {
      return response.ok ? response.json() : null;
    }).then(function (state) {
      return !state || !state.configured || state.source === source;
    }).catch(function () { return true; });
  }

  /* Транспорт: один WS на виджет, бесконечный реконнект.
   * opts: {types:[], accountId, onOpen, onClose, onMessage} */
  function connect(opts) {
    opts = opts || {};
    var types = opts.types || [];
    var accountId = Number(opts.accountId) || 0;
    var ws = null;
    var closed = false;
    var reconnectTimer = null;

    function reconnect() {
      if (closed || reconnectTimer !== null) return;
      reconnectTimer = setTimeout(function () {
        reconnectTimer = null;
        open();
      }, 3000);
    }

    function open() {
      if (closed) return;
      var socket;
      try {
        socket = new WebSocket(wsUrl());
      } catch (e) {
        reconnect();
        return;
      }
      ws = socket;
      socket.onopen = function () {
        if (ws === socket && opts.onOpen) opts.onOpen();
      };
      socket.onmessage = function (ev) {
        if (ws !== socket) return;
        var msg;
        try { msg = JSON.parse(ev.data); } catch (e) { return; }
        if (!msg) return;
        if (types.length && types.indexOf(msg.type) === -1) return;
        if (accountId && Number(msg.account_id) !== accountId) return;
        if (opts.onMessage) opts.onMessage(msg);
      };
      socket.onclose = function () {
        if (ws !== socket) return;
        ws = null;
        if (opts.onClose) opts.onClose();
        reconnect();
      };
      socket.onerror = function () {
        if (ws !== socket) return;
        try { socket.close(); } catch (e) {}
      };
    }

    open();
    return {
      close: function () {
        closed = true;
        if (reconnectTimer !== null) clearTimeout(reconnectTimer);
        reconnectTimer = null;
        var socket = ws;
        ws = null;
        try { if (socket) socket.close(); } catch (e) {}
      },
    };
  }

  /* Очередь: реплики звучат по очереди, а не поверх друг друга.
   * Каждый элемент — {audio_b64, mime, volume, speech:{...}, onStart, onEnd}. */
  function Queue(options) {
    options = options || {};
    var maxLen = options.max || 20;
    var items = [];
    var busy = false;

    function finish(item, guard) {
      if (guard.done) return;
      guard.done = true;
      clearTimeout(guard.timer);
      busy = false;
      if (item.onEnd) { try { item.onEnd(); } catch (e) {} }
      next();
    }

    function playBase64(item, guard) {
      var url = null;
      try {
        var bin = atob(item.audio_b64);
        var bytes = new Uint8Array(bin.length);
        for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
        var blob = new Blob([bytes], { type: item.mime || 'audio/mpeg' });
        url = URL.createObjectURL(blob);
        var audio = item.element || new Audio();
        audio.src = url;
        audio.volume = Math.max(0, Math.min(1, parseFloat(item.volume != null ? item.volume : 1)));
        var release = function () {
          if (url) { URL.revokeObjectURL(url); url = null; }
          finish(item, guard);
        };
        audio.onended = release;
        audio.onerror = release;
        audio.play().catch(release);
      } catch (e) {
        if (url) URL.revokeObjectURL(url);
        finish(item, guard);
      }
    }

    function playSpeech(item, guard) {
      var sp = item.speech || {};
      if (!('speechSynthesis' in window)) { finish(item, guard); return; }
      try {
        speechSynthesis.cancel();
        var u = new SpeechSynthesisUtterance(sp.text || '');
        u.lang = sp.lang || 'ru-RU';
        if (sp.rate != null) u.rate = sp.rate;
        if (sp.pitch != null) u.pitch = sp.pitch;
        if (sp.volume != null) u.volume = sp.volume;
        var voice = pickVoice(sp.voice, u.lang);
        if (voice) u.voice = voice;
        u.onend = u.onerror = function () { finish(item, guard); };
        speechSynthesis.speak(u);
      } catch (e) {
        finish(item, guard);
      }
    }

    function next() {
      if (busy || !items.length) return;
      var item = items.shift();
      busy = true;
      if (item.onStart) { try { item.onStart(item); } catch (e) {} }
      // Страховка: битый кодек может не позвать ни onended, ни onerror —
      // без неё очередь встаёт навсегда и виджет молча замолкает.
      var guard = { done: false };
      guard.timer = setTimeout(function () { finish(item, guard); },
                               Math.max(5000, Number(item.timeoutMs) || 30000));
      if (item.audio_b64) playBase64(item, guard);
      else if (item.speech) playSpeech(item, guard);
      else finish(item, guard);
    }

    return {
      push: function (item) {
        items.push(item);
        if (items.length > maxLen) items = items.slice(-maxLen);
        next();
      },
      get length() { return items.length; },
      get speaking() { return busy; },
      clear: function () { items = []; },
    };
  }

  function pickVoice(name, lang) {
    if (!('speechSynthesis' in window)) return null;
    var voices = speechSynthesis.getVoices();
    if (!voices || !voices.length) return null;
    var base = String(lang || '').split('-')[0];
    return (name && voices.find(function (v) { return v.name === name; }))
      || voices.find(function (v) { return v.lang === lang; })
      || voices.find(function (v) { return String(v.lang || '').startsWith(base); })
      || voices[0];
  }

  window.TtsCore = {
    apiBase: API_BASE,
    host: host,
    wsUrl: wsUrl,
    connect: connect,
    queue: function (options) { return new Queue(options); },
    pickVoice: pickVoice,
    outputAllowed: outputAllowed,
    isPreview: qs.get('preview') === '1',
  };
})();
