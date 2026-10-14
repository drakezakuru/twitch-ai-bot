// [P5-split] 02_dashboard.js ← static/app.js, исходные строки 1692–1848; грузится после предыдущего чанка, порядок = порядку строк

// ── Dashboard ───────────────────────────────────────
async function loadDashboard() {
    try {
        const [accounts, statuses, stats] = await Promise.all([
            api('/api/accounts'),
            api('/api/bots/status'),
            api('/api/stats/all'),
        ]);
        _allBots = Array.isArray(accounts) ? accounts : (accounts.accounts || []);
        _botStatuses = statuses || {};
        _botStats = {};
        (Array.isArray(stats) ? stats : []).forEach(s => { _botStats[s.account_id] = { sent: s.sent, read: s.read }; });

        const online = _allBots.filter(b => b.enabled).length;
        const connected = Object.values(_botStatuses).filter(s => s.connected).length;
        const totalRead = Object.values(_botStats).reduce((a, s) => a + (s.read || 0), 0);
        const totalSent = Object.values(_botStats).reduce((a, s) => a + (s.sent || 0), 0);
        if ($('kpiBotsOnline')) $('kpiBotsOnline').textContent = `${connected} / ${_allBots.length}`;
        if ($('kpiBotsEnabled')) $('kpiBotsEnabled').textContent = online;
        if ($('kpiMessages')) $('kpiMessages').textContent = totalRead.toLocaleString();
        if ($('kpiBotReplies')) $('kpiBotReplies').textContent = totalSent.toLocaleString();
        // Q41b: подписи статичны (общий applyI18n по data-i18n) — число уже показано
        // большим значением ниже, дублировать его в подписи текстом не нужно.

        renderDashboardBots();
        renderDashboardSummary();
        renderEventFeed();
        loadRuntimeStatus();
        loadClipSpikesFeed();
        loadModerationWidget();
        loadRolesSummary();
        loadStreamHealth();
        loadDashboardRecentChat();
        maybeShowOnboarding();
    } catch (e) { console.error('loadDashboard', e); }
}

// ── Владелец 27.09 (вечер): дашборд «здоровье эфира» ──────────────
// Live-снимок: кто подключён, кто отвечает, кто молчит и почему — одной
// таблицей вместо чтения логов по одному боту (app/stream_health.py).
async function loadStreamHealth() {
    const el = $('streamHealthTable');
    if (!el) return;
    try {
        const data = await api('/api/stream-health');
        const channels = data.channels || [];
        el.innerHTML = channels.map(ch => {
            const liveBadge = ch.is_live === true
                ? `<span class="badge badge-success" style="font-weight:600">🔴 LIVE: ${esc(ch.game_name || 'Стрим')} (${(ch.viewer_count || 0).toLocaleString()} 👥)</span>`
                : (ch.is_live === false ? `<span class="badge text-muted" style="opacity:0.8">⚫ Offline</span>` : '');
            const streamTitle = ch.title ? `<span class="text-muted text-xs ml-2" title="${esc(ch.title)}">📺 ${esc(ch.title.slice(0, 45))}${ch.title.length > 45 ? '…' : ''}</span>` : '';
            return `
            <div>
                <div class="flex items-center gap-2 mb-1 flex-wrap">
                    <span class="text-sm font-semibold">#${esc(ch.channel)}</span>
                    ${liveBadge}
                    ${streamTitle}
                </div>
                <div class="space-y-1">
                    ${ch.bots.map(b => `
                        <div class="flex gap-2 items-center text-sm flex-wrap">
                            <span class="badge ${b.connected ? 'badge-success' : ''}">${b.connected ? '🟢' : '⚫'}</span>
                            <strong>${esc(b.nickname)}</strong>
                            <span class="text-muted">${esc(b.role)}</span>
                            ${b.proxy ? `
                                <span class="badge ${b.proxy_status === 'error' ? 'badge-danger' : (b.proxy_latency_ms >= 2000 ? 'badge-warning' : 'badge-subtle')}"
                                      title="${esc(b.proxy)}" style="font-size:0.75rem;">
                                    🌐 ${b.proxy_latency_ms > 0 ? `${Math.round(b.proxy_latency_ms)}ms` : (b.proxy_status === 'error' ? 'ошибка' : 'прокси')}
                                </span>` : ''}
                            ${b.silent
                                ? `<span class="badge badge-warning">${esc(t('health.silent'))}</span><span class="text-muted text-truncate">${esc(b.reason)}</span>`
                                : `<span class="badge badge-success">${esc(t('health.responds'))}</span>`}
                            ${b.last_activity_at ? `<span class="text-muted text-xs ml-auto">${esc(t('health.last_activity'))}: ${esc(b.last_activity_at.replace('T', ' ').slice(0, 16))}</span>` : ''}
                        </div>`).join('')}
                </div>
            </div>`;
        }).join('') || `<div class="empty-state"><div class="empty-icon">🩺</div><span>${esc(t('health.empty'))}</span></div>`;
    } catch (e) {
        el.innerHTML = `<div class="text-error text-sm">${esc(t('api.error.request_failed'))}</div>`;
    }
}

// ── v14 MODERATION_PLAN: мини-виджет «Последние нарушения» (Dashboard) ──
async function loadModerationWidget() {
    const el = $('moderationWidgetList');
    if (!el) return;
    try {
        const data = await api('/api/moderation/recent');
        const events = data.events || [];
        const total = $('moderationWidgetTotal');
        if (total) total.textContent = data.hour_total || 0;
        el.innerHTML = events.map(ev => `
            <div class="flex gap-2 items-center text-sm">
                <span class="badge">${esc(ev.category)}·${ev.severity}</span>
                <strong>${esc(ev.username || '?')}</strong>
                <span class="text-muted">#${esc(ev.channel || '')}</span>
                <span class="text-muted">${esc((ev.message_excerpt || '').slice(0, 60))}</span>
                <span class="text-muted ml-auto">${esc(ev.bot_nickname || '')}</span>
            </div>
        `).join('') || `<div class="empty-state"><div class="empty-icon">🛡</div><span>${esc(t('panel.dashboard.no_violations'))}</span></div>`;
    } catch (e) { console.error('loadModerationWidget', e); }
}

async function loadRuntimeStatus() {
    const el = $('runtimeStatus');
    if (!el) return;
    try {
        const status = await api('/api/runtime/status');
        el.textContent = t('status.runtime', {provider: status.ai_provider})
            + (status.ai_state === 'paused' ? t('status.ai_paused') : '')
            + (status.fallback_enabled ? t('status.fallback_enabled') : '');
        el.className = 'runtime-status card mb-4 text-sm ' + (status.ai_state === 'paused' ? 'text-warning' : status.fallback_enabled ? 'text-success' : 'text-muted');
    } catch (e) {
        el.textContent = t('status.runtime_error', {detail: e.message});
        el.className = 'runtime-status card mb-4 text-error text-sm';
    }
}

function sendReasonText(reason, fallbackMsg) {
    if (reason && t(`send.reason.${reason}`) !== `send.reason.${reason}`) return t(`send.reason.${reason}`);
    return fallbackMsg || t('send.reason.unknown');
}

function botStatusBadge(b) {
    // Health-индикаторы (план §5.1): зелёный — работает, жёлтый — подключается,
    // красный ⚠ — ошибка (с причиной и временем), серый — выключен вручную.
    // OPS_PLAN §3: в tooltip также число авто-переподключений (reconnect_count).
    const st = _botStatuses[b.id] || {};
    const reconTip = st.reconnect_count > 0 ? ' · ' + t('health.reconnects', {n: st.reconnect_count}) : '';
    if (st.connected) return `<span class="badge on" title="${esc((st.last_error || '') + reconTip)}">● ${t('health.online')}</span>`;
    if (st.state === 'connecting') return `<span class="badge connecting">● ${t('health.connecting')}</span>`;
    if (st.state === 'error') {
        const when = st.last_error_at ? new Date(st.last_error_at * 1000).toLocaleTimeString() : '';
        const tip = [st.last_error || t('health.no_reason'), when ? t('health.last_error_at', {time: when}) : '']
            .filter(Boolean).join(' · ') + reconTip;
        return `<span class="badge off" title="${esc(tip)}">⚠ ${t('health.error')}</span>`;
    }
    if (b.enabled) return `<span class="badge accent" title="${esc(t('status.bot_enabled_not_connected'))}">● ${t('label.enabled')}</span>`;
    return `<span class="badge off">● ${t('health.disabled')}</span>`;
}

function botHealthLine(b) {
    // Расшифровка ошибки + время + кнопка переподключения прямо в карточке (§5.1).
    const st = _botStatuses[b.id] || {};
    if (st.state !== 'error') return '';
    const when = st.last_error_at ? new Date(st.last_error_at * 1000).toLocaleString() : '';
    const reason = esc(st.last_error || t('health.no_reason'));
    return `
        <div class="bot-card-error">
            <div class="text-xs text-error">⚠ ${reason}${when ? ` — ${esc(t('health.last_error_at', {time: when}))}` : ''}</div>
            <button class="btn btn-sm btn-secondary" onclick="event.stopPropagation();reconnectBot(${b.id})">${t('btn.reconnect')}</button>
        </div>`;
}

async function reconnectBot(id) {
    const bot = _allBots.find(item => item.id === id);
    if (!bot) return;
    toast(t('toast.reconnecting', {name: bot.nickname}), 'info');
    try {
        await api(`/api/accounts/${id}/stop`, {method: 'POST'});
        await api(`/api/accounts/${id}/start`, jopts('POST', {}));
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
    await loadBotsList();
}

function selectBotCard(id) {
    if (_selectedBots.has(id)) _selectedBots.delete(id); else _selectedBots.add(id);
    renderBotsList(_allBots);
}

function botDisplayChannels(b, st) {
    const runtimeChannels = Array.isArray(st.channels) ? st.channels : [];
    const persistedChannels = Array.isArray(b.persisted_channels) ? b.persisted_channels : [];
    return runtimeChannels.length ? runtimeChannels : persistedChannels;
}

function renderDashboardBots() {
    const el = $('dashboardBots');
    if (!el) return;
    renderDashboardSummary();
    if (!_allBots.length) {
        el.innerHTML = `<div class="card empty-state"><div class="empty-icon">🤖</div>${esc(t('empty.no_bots'))}</div>`;
        return;
    }
    el.innerHTML = _allBots.map(b => {
        const st = _botStatuses[b.id] || {};
        const displayChannels = botDisplayChannels(b, st);
        const chans = displayChannels.length
            ? displayChannels.map(c => `<span class="badge">#${esc(c)}</span>`).join(' ')
            : `<span class="text-muted text-xs">${esc(t('label.no_channels'))}</span>`;
        const s = _botStats[b.id] || { sent: 0, read: 0 };
        const model = b.ai_chat_model_override || t('status.model_global');
        const mode = st.connected ? t('status.online_mode') : t('status.offline_mode');
        return `
        <div class="bot-card" onclick="openBotSettings(${b.id})">
            ${botHealthLine(b)}
            <div class="bot-card-row">
                <span class="bot-card-nick">${esc(b.nickname)}</span>
                ${botStatusBadge(b)}
            </div>
            <div class="bot-card-channel" style="margin-bottom:6px">${chans}</div>
            <div class="text-xs text-muted">🧠 ${esc(model)} · ${mode}</div>
            <div class="bot-card-meta">
                <span class="bot-card-badge">✉️ ${countLabel(s.sent, {one:'написал', few:'написали', many:'написали', ua:{one:'написав',few:'написали',many:'написано'}, en:'sent'})}</span>
                <span class="bot-card-badge">👁️ ${countLabel(s.read, {one:'прочитал', few:'прочитали', many:'прочитали', ua:{one:'прочитав',few:'прочитали',many:'прочитано'}, en:'read'})}</span>
            </div>
        </div>`;
    }).join('');
}

// Q23: сводка расклада вверху «Обзора» — сколько ботов, роли, кто к какому
// каналу подключён (мини-таблица каналов + чипы ролей). Данные уже на клиенте.
function renderDashboardSummary() {
    const el = $('dashboardOverviewSummary');
    if (!el) return;
    if (!_allBots.length) {
        el.innerHTML = `<div class="empty-state"><div class="empty-icon">📊</div><span>${esc(t('empty.no_bots'))}</span></div>`;
        return;
    }
    const connected = id => !!(_botStatuses[id] || {}).connected;
    const onlineCount = _allBots.filter(b => connected(b.id)).length;
    const roleLabel = role => (typeof _roleMetaLabel === 'function' ? _roleMetaLabel(role) : role);
    const roles = {};
    _allBots.forEach(b => { const r = b.bot_role || 'chatter'; roles[r] = (roles[r] || 0) + 1; });
    const channels = new Map();
    _allBots.forEach(b => {
        botDisplayChannels(b, _botStatuses[b.id] || {}).forEach(channel => {
            const key = String(channel).toLowerCase();
            const entry = channels.get(key) || { channel: key, bots: [] };
            entry.bots.push({ nickname: b.nickname || `#${b.id}`, connected: connected(b.id) });
            channels.set(key, entry);
        });
    });
    const rows = [...channels.values()].sort((a, b) => a.channel.localeCompare(b.channel)).map(entry => `
        <tr>
            <td><strong>#${esc(entry.channel)}</strong></td>
            <td><div class="flex gap-1 flex-wrap">${entry.bots.map(bot => `
                <span class="badge ${bot.connected ? 'badge-success' : ''}">${bot.connected ? '🟢' : '⚫'} ${esc(bot.nickname)}</span>`).join('')}</div></td>
            <td class="text-muted">${entry.bots.filter(b => b.connected).length} / ${entry.bots.length}</td>
        </tr>`).join('');
    el.innerHTML = `
        <div class="card-header">
            <span class="card-title" data-i18n="panel.summary.title">📊 Расклад</span>
            <span class="badge">${esc(t('panel.summary.online', {online: onlineCount, total: _allBots.length}))}</span>
        </div>
        <div class="flex gap-2 flex-wrap mb-2">${Object.entries(roles).map(([role, count]) => `
            <span class="badge">${esc(roleLabel(role))}: ${count}</span>`).join('')}</div>
        ${rows ? `<div class="table-wrap"><table><thead><tr>
            <th>${esc(t('panel.summary.channel'))}</th>
            <th>${esc(t('panel.summary.bots'))}</th>
            <th>${esc(t('panel.summary.connected'))}</th>
        </tr></thead><tbody>${rows}</tbody></table></div>`
            : `<div class="text-muted text-sm">${esc(t('label.no_channels'))}</div>`}`;
}

// ── Живой мини-чат стрима на дашборде ────────────────
let _dashboardMiniChatCount = 0;

function renderDashboardMiniChatMessage(msg) {
    const rawTime = msg.timestamp || msg.created_at || new Date().toISOString();
    const timeStr = typeof fmtTime === 'function' ? fmtTime(String(rawTime).replace(' ', 'T')) : String(rawTime).slice(11, 19);
    const ch = (msg.channel || '').replace('#', '');
    const author = msg.author || msg.nickname || '?';
    const text = msg.message || msg.text || '';
    const isBot = !!msg.is_bot || (_allBots && _allBots.some(b => (b.nickname || '').toLowerCase() === author.toLowerCase()));
    const isStreamer = ch && author.toLowerCase() === ch.toLowerCase();

    const roleClass = isBot ? 'is-bot' : (isStreamer ? 'is-streamer' : 'is-viewer');
    const badgeHtml = isBot
        ? `<span class="badge badge-accent" style="font-size:10px; padding:1px 5px; margin-right:4px;">🤖 ${esc(t('label.role_bot') || 'Бот')}</span>`
        : (isStreamer
            ? `<span class="badge badge-warning" style="font-size:10px; padding:1px 5px; margin-right:4px;">👑 ${esc(t('label.role_streamer') || 'Стример')}</span>`
            : '');

    return `
    <div class="chat-msg ${roleClass}" style="display:flex; align-items:baseline; gap:6px; padding:3px 8px; border-radius:4px; font-size:13px; line-height:1.4;">
        <span class="chat-time" style="font-size:11px; color:var(--text-muted); flex-shrink:0;">${esc(timeStr)}</span>
        ${ch ? `<span class="badge text-muted" style="font-size:10px; padding:1px 4px; flex-shrink:0;">#${esc(ch)}</span>` : ''}
        <span class="chat-nick" style="font-weight:600; flex-shrink:0;">
            ${badgeHtml}${esc(author)}:
        </span>
        <span class="chat-text" style="word-break:break-word; flex-grow:1;">${esc(text)}</span>
    </div>`;
}

function appendDashboardMiniChat(msg) {
    const el = $('dashboardMiniChat');
    if (!el) return;
    const empty = el.querySelector('.empty-state');
    if (empty) empty.remove();

    el.insertAdjacentHTML('beforeend', renderDashboardMiniChatMessage(msg));
    _dashboardMiniChatCount++;
    const countEl = $('dashboardChatCount');
    if (countEl) countEl.textContent = _dashboardMiniChatCount;

    while (el.children.length > 60) {
        el.firstChild.remove();
    }
    el.scrollTop = el.scrollHeight;
}

async function loadDashboardRecentChat() {
    const el = $('dashboardMiniChat');
    if (!el) return;
    try {
        const rows = await api('/api/logs?limit=30');
        if (!Array.isArray(rows) || !rows.length) return;
        el.innerHTML = rows.map(r => renderDashboardMiniChatMessage(r)).join('');
        _dashboardMiniChatCount = rows.length;
        const countEl = $('dashboardChatCount');
        if (countEl) countEl.textContent = _dashboardMiniChatCount;
        el.scrollTop = el.scrollHeight;
    } catch (e) {
        console.error('loadDashboardRecentChat', e);
    }
}

function clearDashboardMiniChat() {
    const el = $('dashboardMiniChat');
    if (!el) return;
    el.innerHTML = `<div class="empty-state text-muted text-sm"><div class="empty-icon">💬</div><span data-i18n="panel.dashboard.mini_chat_waiting">${esc(t('panel.dashboard.mini_chat_waiting') || 'Ожидание сообщений из чата...')}</span></div>`;
    _dashboardMiniChatCount = 0;
    const countEl = $('dashboardChatCount');
    if (countEl) countEl.textContent = 0;
}

