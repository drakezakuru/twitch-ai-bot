/** Safe renderer and bounded lifetime queue for chat-message overlays. */
(function () {
  'use strict';

  function clampInt(value, fallback, min, max) {
    var parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) ? Math.max(min, Math.min(max, parsed)) : fallback;
  }

  function apiBase() {
    return new URLSearchParams(location.search).get('api') || '';
  }

  async function loadSettings(slug, fallback) {
    var values = Object.assign({}, fallback || {});
    try {
      var response = await fetch(apiBase() + '/api/widgets/public/chat/display/' + encodeURIComponent(slug));
      if (response.ok) Object.assign(values, (await response.json()).settings || {});
    } catch (e) {}
    var query = new URLSearchParams(location.search);
    if (query.has('max')) values.max_messages = clampInt(query.get('max'), values.max_messages, 1, 50);
    if (query.has('lifetime')) values.lifetime_sec = clampInt(query.get('lifetime'), values.lifetime_sec, 0, 300);
    if (query.has('font_size')) values.font_size = clampInt(query.get('font_size'), values.font_size, 10, 72);
    if (query.has('emote_size')) values.emote_size = clampInt(query.get('emote_size'), values.emote_size, 12, 128);
    if (query.has('badges')) values.show_badges = query.get('badges') === '1' ? 1 : 0;
    if (query.has('history')) values.history_limit = clampInt(query.get('history'), values.history_limit, 0, 50);
    if (query.has('history_minutes')) values.history_minutes = clampInt(query.get('history_minutes'), values.history_minutes, 1, 1440);
    return values;
  }

  async function loadEmotes(channel) {
    try {
      var url = apiBase() + '/api/widgets/public/emotes?channel=' + encodeURIComponent(channel || '');
      var response = await fetch(url);
      return response.ok ? ((await response.json()).emotes || {}) : {};
    } catch (e) {
      return {};
    }
  }

  function appendMessageText(target, text, emotes, size) {
    String(text || '').split(/(\s+)/).forEach(function (part) {
      var src = emotes && emotes[part];
      if (!src) {
        target.appendChild(document.createTextNode(part));
        return;
      }
      var image = document.createElement('img');
      image.className = 'chat-emote';
      image.src = src;
      image.alt = part;
      image.title = part;
      image.loading = 'eager';
      image.style.width = size + 'px';
      image.style.height = size + 'px';
      image.addEventListener('error', function () {
        image.replaceWith(document.createTextNode(part));
      }, { once: true });
      target.appendChild(image);
    });
  }

  function createList(options) {
    var container = options.container;
    var settings = options.settings;
    var emotes = options.emotes || {};

    function remove(element) {
      if (!element || !element.parentNode) return;
      element.classList.add('chat-message-out');
      setTimeout(function () { if (element.parentNode) element.remove(); }, 350);
    }

    function add(message) {
      var row = document.createElement('div');
      row.className = 'chat-message widget-theme-surface';
      row.style.fontSize = settings.font_size + 'px';
      if (settings.show_badges && Array.isArray(message.badges)) {
        message.badges.slice(0, 5).forEach(function (badge) {
          var pill = document.createElement('span');
          pill.className = 'chat-badge';
          pill.textContent = String(badge || '').slice(0, 24);
          row.appendChild(pill);
        });
      }
      var author = document.createElement('span');
      author.className = 'chat-author widget-theme-accent';
      author.textContent = String(message.author || '') + ':';
      row.appendChild(author);
      var body = document.createElement('span');
      body.className = 'chat-message-text widget-theme-text';
      appendMessageText(body, message.message || message.text || '', emotes, settings.emote_size);
      row.appendChild(body);
      container.appendChild(row);
      while (container.children.length > settings.max_messages) remove(container.firstElementChild);
      if (settings.lifetime_sec > 0) {
        setTimeout(function () { remove(row); }, settings.lifetime_sec * 1000);
      }
      return row;
    }

    return { add: add, remove: remove };
  }

  window.ChatMessageCore = {
    apiBase: apiBase,
    appendMessageText: appendMessageText,
    clampInt: clampInt,
    createList: createList,
    loadEmotes: loadEmotes,
    loadSettings: loadSettings,
  };
})();
