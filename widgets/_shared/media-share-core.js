(function (global) {
  'use strict';

  function statusStore(render, priority) {
    var active = Object.create(null);
    function flush() {
      var key = priority.find(function (candidate) { return active[candidate]; }) || '';
      render(key, key ? active[key] : '');
    }
    return {
      set: function (key, message) { active[key] = String(message || ''); flush(); },
      clear: function (key) { delete active[key]; flush(); },
      has: function (key) { return Boolean(active[key]); },
    };
  }

  function reconnectingSocket(options) {
    var socket = null;
    var retryTimer = null;
    var disposed = false;
    var generation = 0;

    function connect() {
      if (disposed) return;
      var mine = ++generation;
      var current = new options.WebSocket(options.url);
      socket = current;
      options.onState('connecting');
      current.onopen = function () {
        if (disposed || mine !== generation) return;
        options.onState('connected');
      };
      current.onmessage = function (event) {
        if (!disposed && mine === generation) options.onMessage(event);
      };
      current.onerror = function () {
        if (!disposed && mine === generation && current.close) current.close();
      };
      current.onclose = function () {
        if (disposed || mine !== generation || retryTimer !== null) return;
        options.onState('reconnecting');
        retryTimer = options.setTimeout(function () {
          retryTimer = null;
          connect();
        }, options.retryMs || 3000);
      };
    }

    connect();
    return {
      close: function () {
        disposed = true;
        generation += 1;
        if (retryTimer !== null) options.clearTimeout(retryTimer);
        retryTimer = null;
        if (socket && socket.close) socket.close();
      },
    };
  }

  global.MediaShareCore = {
    statusStore: statusStore,
    reconnectingSocket: reconnectingSocket,
  };
})(window);
