/* §1/§4 WIDGETS_PLAN: Widget Bus client — готовый JS-сниппет для сторонних
 * (самописных) OBS-виджетов, которые должны реагировать на звук/видео бота.
 *
 * Подключение в своём виджете:
 *   <script src="http://panel:8000/widget/_shared/widget-bus-client.js"></script>
 *   <script>
 *     WidgetBus.onDuck((msg) => { /* снизить громкость / замолчать *\/ });
 *     WidgetBus.onDuckEnd(() => { /* вернуть громкость *\/ });
 *     WidgetBus.onPauseMedia(() => video.pause());
 *     WidgetBus.onResumeMedia(() => video.play());
 *   </script>
 *
 * События приходят через общий WebSocket /ws панели (type: widget_bus):
 *   {type:"widget_bus", kind:"duck_start"|"duck_end", source, reason, duration_ms}
 *   {type:"widget_bus", kind:"pause_media"|"resume_media", source}
 *
 * Виджет, играющий звук (TTS-оверлей и т.п.), сам ПУБЛИКУЕТ сигналы —
 * см. app/widget_bus.py (backend) — здесь только подписка.
 */
(function () {
  'use strict';
  const API_BASE = new URLSearchParams(location.search).get('api') || '';
  const CHANNEL = new URLSearchParams(location.search).get('channel') || '';
  const handlers = { duck_start: [], duck_end: [], pause_media: [], resume_media: [] };

  function connect() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = API_BASE
      ? API_BASE.replace(/^\w+:\/\//, '').replace(/\/$/, '')
      : location.host;
    const ws = new WebSocket(`${proto}//${host}/ws?channel=${encodeURIComponent(CHANNEL)}`);
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (!msg || msg.type !== 'widget_bus' || !handlers[msg.kind]) return;
      handlers[msg.kind].forEach((fn) => {
        try { fn(msg); } catch (e) { console.error('widget_bus handler', e); }
      });
    };
    ws.onclose = () => setTimeout(connect, 3000);
    ws.onerror = () => ws.close();
  }

  function subscribe(kind, fn) { handlers[kind].push(fn); }

  window.WidgetBus = {
    onDuck: (fn) => subscribe('duck_start', fn),
    onDuckEnd: (fn) => subscribe('duck_end', fn),
    onPauseMedia: (fn) => subscribe('pause_media', fn),
    onResumeMedia: (fn) => subscribe('resume_media', fn),
  };
  connect();
})();
