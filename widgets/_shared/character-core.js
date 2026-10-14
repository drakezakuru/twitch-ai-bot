/* Wave 6 (WIDGET_IMPLEMENTATION_PLAN §3): общий runtime персонажей —
 * mascot (reactive) и anime-runner (runner).
 *
 * Общее у обоих и вынесено сюда:
 *   • poll собственного конфига (/api/widgets/public/<slug>) раз в 30с;
 *   • poll ленты событий (/api/widgets/public/recent-events) и распознавание
 *     «появилось новое событие» по возрастанию id;
 *   • переход в sleep после idle_timeout_sec без событий;
 *   • всплывающие частицы (сердечки, искры, zZz) с автоудалением из DOM.
 *
 * Чего здесь НЕТ: сам рендер. mascot остаётся SVG-реактивным, anime-runner —
 * canvas/DOM-раннером; каждый передаёт свои обработчики. Публичные URL,
 * параметры и JSON-контракты API не меняются.
 */
(function () {
  'use strict';

  var qs = new URLSearchParams(location.search);
  var API_BASE = qs.get('api') || '';

  function api(path) {
    return API_BASE + path + (path.indexOf('?') === -1 ? '?' : '&') + 't=' + Date.now();
  }

  /* Частица: div с классом, который сам исчезает. */
  function spawn(parent, className, text, style, lifeMs) {
    if (!parent) return null;
    var el = document.createElement('div');
    el.className = className;
    if (text != null) el.textContent = text;
    if (style) { for (var k in style) { if (style[k] != null) el.style[k] = style[k]; } }
    parent.appendChild(el);
    setTimeout(function () { el.remove(); }, lifeMs || 2000);
    return el;
  }

  /* Повторяющийся спавн (zZz во сне): idempotent start/stop. */
  function Repeater(fn, intervalMs) {
    var timer = null;
    return {
      start: function () {
        if (timer) return;
        timer = setInterval(fn, intervalMs);
      },
      stop: function () {
        if (!timer) return;
        clearInterval(timer);
        timer = null;
      },
      get running() { return timer !== null; },
    };
  }

  /* Общий цикл персонажа.
   * opts: {configUrl, onConfig, onEvent, onSleep, onWake,
   *        idleTimeoutSec, configMs, eventsMs, eventsLimit} */
  function start(opts) {
    opts = opts || {};
    var cfg = {};
    var lastEventId = null;
    var lastEventTime = Date.now();
    var asleep = false;

    async function pollConfig() {
      if (!opts.configUrl) return;
      try {
        var r = await fetch(api(opts.configUrl));
        cfg = await r.json();
        if (opts.onConfig) opts.onConfig(cfg);
      } catch (e) { /* панель недоступна — держим прошлый конфиг */ }
    }

    async function pollEvents() {
      try {
        var eventsUrl = opts.eventsUrl || ('/api/widgets/public/recent-events?limit='
                                           + (opts.eventsLimit || 5));
        var scopedUrl = new URL(eventsUrl, location.origin);
        if (qs.get('account_id')) scopedUrl.searchParams.set('account_id', qs.get('account_id'));
        if (qs.get('channel')) scopedUrl.searchParams.set('channel', qs.get('channel'));
        var r = await fetch(api(scopedUrl.pathname + scopedUrl.search));
        var evs = await r.json();
        if (evs && evs.length) {
          var top = evs[0];
          if (lastEventId === null) {
            lastEventId = top.id;
          } else if (top.id > lastEventId) {
            lastEventId = top.id;
            lastEventTime = Date.now();
            if (asleep) { asleep = false; if (opts.onWake) opts.onWake(); }
            if (opts.onEvent) opts.onEvent(top);
          }
        }
        var idle = (Date.now() - lastEventTime) / 1000;
        var limit = cfg.idle_timeout_sec || opts.idleTimeoutSec || 300;
        if (idle > limit && !asleep) {
          asleep = true;
          if (opts.onSleep) opts.onSleep();
        }
      } catch (e) { /* панель недоступна — персонаж продолжает свою анимацию */ }
    }

    pollConfig();
    pollEvents();
    setInterval(pollConfig, opts.configMs || 30000);
    setInterval(pollEvents, opts.eventsMs || 3000);

    return {
      get config() { return cfg; },
      get asleep() { return asleep; },
      /* Ручной прогон реакции — используется превью и window.*Test-хуками. */
      react: function (ev) {
        lastEventTime = Date.now();
        if (asleep) { asleep = false; if (opts.onWake) opts.onWake(); }
        if (opts.onEvent) opts.onEvent(ev);
      },
    };
  }

  window.CharacterCore = {
    apiBase: API_BASE,
    api: api,
    spawn: spawn,
    repeater: function (fn, ms) { return new Repeater(fn, ms); },
    start: start,
    isPreview: qs.get('preview') === '1',
    reducedMotion: window.matchMedia
      ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
      : false,
  };
})();
