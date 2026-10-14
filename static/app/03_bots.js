// [P5-split] 03_bots.js ← static/app.js, исходные строки 1849–3464; грузится после предыдущего чанка, порядок = порядку строк

// ── Bots list ───────────────────────────────────────
async function loadBotsList() {
    try {
        const [accounts, statuses, stats, tokenStatuses, healthRes] = await Promise.all([
            api('/api/accounts'),
            api('/api/bots/status'),
            api('/api/stats/all'),
            api('/api/token-status/accounts').catch(() => ({ statuses: {} })),
            api('/api/accounts/health-status').catch(() => ({ statuses: {} })),
        ]);
        _allBots = Array.isArray(accounts) ? accounts : (accounts.accounts || []);
        _botStatuses = statuses || {};
        _botTokenStatuses = tokenStatuses.statuses || {};
        _botHealthStatuses = (healthRes && healthRes.statuses) || {};
        _botStats = {};
        (Array.isArray(stats) ? stats : []).forEach(s => { _botStats[s.account_id] = { sent: s.sent, read: s.read }; });
        botsFiltersSync();
        renderBotsList(_allBots);
        const savedBotId = Number(localStorage.getItem('panel_active_bot_id'));
        if (savedBotId && !_currentBotId && _allBots.some(b => b.id === savedBotId)) {
            openBotSettings(savedBotId);
        }
        if (localStorage.getItem('compactBotList') === '1') $('botsList')?.classList.add('compact-bot-list');
        _busyBots.clear();
        loadBotPacks();
    } catch (e) {
        console.error('loadBotsList', e);
        const el = $('botsList');
        if (el) el.innerHTML = `<div class="card text-error p-4">${esc(t('empty.load_failed', {detail: e.message}))}</div>`;
    }
}

let _selectedBots = new Set();
const _busyBots = new Set(); // боты, по которым выполняется старт/стоп — кнопки disabled (§4)
let _botTokenStatuses = {};
let _botHealthStatuses = {};

function botFleetHealthBadge(accountId) {
    const h = _botHealthStatuses[String(accountId)] || _botHealthStatuses[accountId];
    if (!h) {
        return `<span class="bot-card-badge text-muted" title="Светофор: еще не проверялся">⚪ Не проверен</span>`;
    }
    const when = h.checked_at ? new Date(h.checked_at * 1000).toLocaleTimeString() : '';
    if (h.status === 'ok') {
        return `<span class="bot-card-badge" style="color:var(--color-success,#22c55e);font-weight:600" title="Светофор [${when}]: Токен валиден, прокси в норме">🟢 Здоров</span>`;
    } else if (h.status === 'proxy_error') {
        return `<span class="bot-card-badge" style="color:var(--color-warn,#eab308);font-weight:600" title="Светофор [${when}]: Ошибка прокси (${esc(h.error || '')})">🟡 Прокси ошибка</span>`;
    } else if (h.status === 'auth_error') {
        return `<span class="bot-card-badge" style="color:var(--color-error,#ef4444);font-weight:600" title="Светофор [${when}]: Ошибка токена 401 (${esc(h.error || '')})">🔴 Ошибка токена</span>`;
    }
    return `<span class="bot-card-badge text-muted" title="Светофор: ${esc(h.status_ru || h.status)}">⚪ ${esc(h.status_ru || 'Не проверен')}</span>`;
}

function tokenStatusBadge(accountId) {
    const rawStatus = _botTokenStatuses[String(accountId)] || 'unknown';
    const meta = {
        valid: ['🟢', 'token.status.valid'],
        expiring: ['🟡', 'token.status.expiring'],
        expired: ['🔴', 'token.status.expired'],
        not_refreshable: ['⚪', 'token.status.not_refreshable'],
        unknown: ['⚫', 'token.status.unknown'],
    };
    const status = Object.hasOwn(meta, rawStatus) ? rawStatus : 'unknown';
    const statusMeta = meta[status];
    return `<span class="bot-card-badge token-status token-status-${status}" title="${esc(t(statusMeta[1]))}">${statusMeta[0]} ${esc(t(statusMeta[1]))}</span>`;
}

function renderBotsList(bots) {
    const el = $('botsList');
    if (!el) return;
    renderBotsBulkBar();
    const renderCards = items => items.map(b => {
        const st = _botStatuses[b.id] || {};
        const isDirector = (b.bot_role || 'chatter') === 'director';
        const displayChannels = botDisplayChannels(b, st);
        const chans = displayChannels.length
            ? displayChannels.map(c => `<span class="badge">#${esc(c)}</span>`).join(' ')
            : `<span class="text-muted text-xs">${esc(t('label.no_channels'))}</span>`;
        const s = _botStats[b.id] || { sent: 0, read: 0 };
        const obs = b.observation_only ? `👀 ${t('btn.observer')}` : '';
        const aiModel = b.ai_chat_model_override || '';
        const aiBadge = aiModel ? `<span class="bot-card-badge">🧠 ${esc(aiModel.split('/').pop())}</span>` : '';
        const visionModel = b.ai_vision_model_override || '';
        const visionBadge = visionModel ? `<span class="bot-card-badge">👁️ ${esc(visionModel.split('/').pop())}</span>` : '';
        const checked = !isDirector && _selectedBots.has(b.id) ? 'checked' : '';
        const busy = _busyBots.has(b.id);
        return `
        <div class="bot-card role-${esc(b.bot_role || 'chatter')} ${checked ? 'selected' : ''}" role="button" tabindex="0" data-bot-card="${b.id}" onclick="${isDirector ? `openDirectorPanel(${b.id})` : `selectBotCard(${b.id})`}" ondblclick="event.stopPropagation();${isDirector ? `openDirectorPanel(${b.id})` : `openBotSettings(${b.id})`}" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();${isDirector ? `openDirectorPanel(${b.id})` : `selectBotCard(${b.id})`}}">
            <span class="role-stripe"></span>
            <div class="bot-card-row">
                ${isDirector ? '' : `<input type="checkbox" ${checked} title="${esc(t('label.selected'))}" onclick="event.stopPropagation()" onchange="toggleBotSelect(${b.id}, this.checked)">`}
                <span class="bot-card-nick">${esc(b.nickname)}</span>
                ${botStatusBadge(b)}
            </div>
            <div class="bot-card-channel">${chans}</div>
            ${botHealthLine(b)}
            <div class="bot-card-meta">
                ${roleBadgeHtml(b)}
                ${botFleetHealthBadge(b.id)}
                ${tokenStatusBadge(b.id)}
                <span class="bot-card-badge">✉️ ${countLabel(s.sent, {one:'написал', few:'написали', many:'написали', ua:{one:'написав',few:'написали',many:'написано'}, en:'sent'})}</span>
                <span class="bot-card-badge">👁️ ${countLabel(s.read, {one:'прочитал', few:'прочитали', many:'прочитали', ua:{one:'прочитав',few:'прочитали',many:'прочитано'}, en:'read'})}</span>
                ${aiBadge}
                ${visionBadge}
                ${obs ? `<span class="bot-card-badge" style="background:var(--bg-warn);color:#fff">${obs}</span>` : ''}
            </div>
            <div class="bot-card-actions">
                ${isDirector ? `<button class="btn btn-sm btn-primary" onclick="event.stopPropagation();openDirectorPanel(${b.id})">🎬 ${esc(t('director.open_panel'))}</button>` : `
                ${!_selectedBots.has(b.id) ? `<button class="btn btn-sm ${st.connected || b.enabled ? 'btn-danger' : 'btn-primary'}"
                        ${busy ? 'disabled' : ''} onclick="event.stopPropagation();quickToggleBot(${b.id}, this)">
                    ${busy ? '…' : (st.connected || b.enabled ? t('btn.stop') : t('btn.start'))}
                </button>` : ''}
                <button class="btn btn-sm btn-secondary" onclick="event.stopPropagation();openBotSettings(${b.id})">⚙️ ${t('btn.configure')}</button>
                <button class="btn btn-sm btn-secondary" title="🔊 Прослушать голос бота (HTML5 Audio)" onclick="event.stopPropagation();quickPreviewBotVoice(${b.id}, '${esc(b.nickname)}')">🔊 Голос</button>
                <button class="btn btn-sm btn-secondary" onclick="event.stopPropagation();openBotChannelModal(${b.id}, '${esc(b.nickname)}')">${t('bots.change_channel')}</button>
                ${b.has_refresh_token ? `<button class="btn btn-sm btn-secondary" onclick="event.stopPropagation();refreshBotToken(${b.id}, this)">${t('token.refresh')}</button>` : ''}
                <button class="btn btn-sm btn-secondary" onclick="event.stopPropagation();showLastObservation(${b.id})">${t('btn.observe')}</button>`}
            </div>
        </div>`;
    }).join('');
    // Q08 (DEC-OWNER-010): один список без принудительной секции «Луркеры» —
    // вид настраивают фильтры по роли и каналу (botsRoleFilter/botsChannelFilter).
    if (!bots.length) {
        el.innerHTML = `<div class="card empty-state"><div class="empty-icon">🤖</div>${esc(t('empty.no_bots_add'))}</div>`;
        return;
    }
    el.innerHTML = `<div class="grid-cards bots-grid">${renderCards(bots)}</div>`;
}

async function refreshBotToken(id, button) {
    if (button) button.disabled = true;
    try {
        const result = await api(`/api/accounts/${id}/refresh-token`, { method: 'POST' });
        if (!result.ok) throw new Error(t('token.refresh_failed'));
        toast(t('token.refresh_done'), 'success');
        await loadBotsList();
    } catch (e) {
        toast(t('toast.error_detail', {detail: e.message}), 'error');
    } finally {
        if (button) button.disabled = false;
    }
}

function updateManualTokenHint(inputId, hintId, hasRefreshToken = false) {
    const input = $(inputId);
    const hint = $(hintId);
    if (input && hint) hint.classList.toggle('hidden', !input.value.trim() || hasRefreshToken);
}

function renderBotsBulkBar() {
    const bar = $('botsBulkBar');
    if (!bar) return;
    if (!_selectedBots.size) { bar.innerHTML = ''; return; }
    const n = _selectedBots.size;
    bar.innerHTML = `
        <div class="bots-bulk-bar flex items-center gap-2 flex-wrap">
            <span class="bots-bulk-count">${esc(t('common.selected', {count: n}))}</span>
            <button class="btn btn-sm btn-primary" onclick="bulkStartBots(this)">${t('btn.start')} (${n})</button>
            <button class="btn btn-sm btn-secondary" onclick="bulkStopBots(this)">${t('btn.stop')} (${n})</button>
            <button class="btn btn-sm btn-secondary" onclick="runFleetHealthCheck([..._selectedBots])" title="Проверить токены и прокси выбранных">🚦 Проверить (${n})</button>
            <button class="btn btn-sm btn-secondary" onclick="bulkChangeRolePrompt()">🎭 Роль (${n})</button>
            <button class="btn btn-sm btn-secondary" onclick="bulkAddChannelPrompt()">➕ Канал (${n})</button>
            <button class="btn btn-sm btn-secondary" onclick="bulkClaimProxiesFromPool()" title="Выдать свободные прокси из общего пула каждому выбранному боту">🌐 Прокси из пула (${n})</button>
            <button class="btn btn-sm btn-secondary" onclick="showBotCheckModal()">${t('check.open')} (${n})</button>
            <button class="btn btn-sm btn-secondary" onclick="openBotsToChannelsBulk()">${t('bulk.start')} (${n})</button>
            <button class="btn btn-sm btn-secondary" onclick="openBulkChangeChannel()">🔁 ${t('bulk.change_channel')} (${n})</button>
            <button class="btn btn-sm btn-secondary" onclick="openBulkAccountSettings()">⚙️ ${t('bulk.settings')} (${n})</button>
            <button class="btn btn-sm btn-danger" onclick="bulkDeleteBots(this)">${t('btn.delete')} (${n})</button>
            <button class="btn btn-sm btn-secondary text-danger" onclick="bulkRemoveDeadBots()" title="Удалить из базы всех ботов с мертвыми токенами (401)">🧹 Удалить мертвые (401)</button>
            <button class="btn btn-sm btn-secondary" onclick="_selectedBots.clear();renderBotsList(_allBots)">✕ ${t('btn.cancel')}</button>
        </div>`;
}

async function toggleObservationOnly(id) {
    const bot = _allBots.find(item => item.id === id);
    if (!bot) return;
    try {
        await api(`/api/accounts/${id}`, jopts('PUT', { observation_only: !bot.observation_only }));
        bot.observation_only = !bot.observation_only;
        renderBotsList(_allBots);
        toast(t(bot.observation_only ? 'toast.observation_enabled' : 'toast.observation_disabled'), 'success');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

function toggleBotSelect(id, checked) {
    if (checked) _selectedBots.add(id); else _selectedBots.delete(id);
    renderBotsList(_allBots);
}

async function bulkDeleteBots() {
    if (!_selectedBots.size) return;
    if (!confirm(t('confirm.delete_bots', {count: _selectedBots.size}))) return;
    try {
        const res = await api('/api/bulk/delete', jopts('POST', { type: 'accounts', ids: [..._selectedBots] }));
        toast(t('toast.bots_deleted', {detail: res.deleted}), 'success');
        _selectedBots.clear();
        await loadBotsList();
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function bulkStartBots(btn) {
    if (!_selectedBots.size) return;
    if (btn) btn.disabled = true;
    let started = 0;
    for (const id of _selectedBots) {
        _busyBots.add(id);
        try {
            // /start сам включает флаг accounts.enabled (owner report 27.09.2026) —
            // отдельный /toggle больше не нужен и раньше давал двойной старт.
            await api(`/api/accounts/${id}/start`, jopts('POST', {}));
            started++;
        } catch (e) { /* skip */ }
        _busyBots.delete(id);
    }
    toast(t('toast.bots_started', {detail: `${started} / ${_selectedBots.size}`}), 'success');
    _selectedBots.clear();
    await loadBotsList();
}

async function bulkStopBots(btn) {
    if (!_selectedBots.size) return;
    if (btn) btn.disabled = true;
    for (const id of _selectedBots) {
        _busyBots.add(id);
        try {
            // /stop сам выключает флаг accounts.enabled.
            await api(`/api/accounts/${id}/stop`, {method: 'POST'});
        } catch (e) { console.warn('bulk stop', id, e); }
        _busyBots.delete(id);
    }
    _selectedBots.clear(); await loadBotsList();
}

// ── Bot connectivity check ─────────────────────────
let _botCheckId = '';
let _botCheckTimer = null;
let _botCheckResults = [];

function showBotCheckModal() {
    if (!_selectedBots.size) return;
    const channels = [...new Set(_allBots.flatMap(bot => bot.persisted_channels || []))].sort();
    const list = $('botCheckChannels');
    if (list) list.innerHTML = channels.map(channel => `<option value="${esc(channel)}"></option>`).join('');
    $('botCheckSelected').textContent = t('common.selected', {count: _selectedBots.size});
    $('botCheckMessage').value = t('check.default_message');
    // Q07/DEC-OWNER-011: контрольное сообщение по умолчанию ВЫКЛ.
    $('botCheckSendEnabled').checked = false;
    $('botCheckMessage').disabled = true;
    $('botCheckResults').innerHTML = '';
    $('botCheckDownloads').classList.add('hidden');
    $('botCheckCancel').classList.add('hidden');
    $('botCheckStart').disabled = false;
    showModal('botCheckModal');
}

function botCheckSendToggled() {
    const enabled = $('botCheckSendEnabled')?.checked;
    const input = $('botCheckMessage');
    if (input) input.disabled = !enabled;
}

async function startBotCheck() {
    const channel = $('botCheckChannel').value.trim().replace(/^#/, '').toLowerCase();
    const sendEnabled = !!$('botCheckSendEnabled')?.checked;
    const message = $('botCheckMessage').value.trim();
    if (!channel || (sendEnabled && !message)) { toast(t('check.invalid_input'), 'error'); return; }
    try {
        const job = await api('/api/bot-checks', jopts('POST', {
            account_ids: [..._selectedBots], channel, message_template: message, send_message: sendEnabled,
        }));
        if (!job.ok) { toast(t(`check.error.${job.code || 'check_failed'}`), 'error'); return; }
        _botCheckId = job.check_id;
        _botCheckResults = [];
        $('botCheckStart').disabled = true;
        $('botCheckCancel').classList.remove('hidden');
        $('botCheckResults').innerHTML = `<div class="text-muted p-3">${esc(t('check.running'))}</div>`;
        clearInterval(_botCheckTimer);
        _botCheckTimer = setInterval(pollBotCheck, 1000);
        await pollBotCheck();
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function pollBotCheck() {
    if (!_botCheckId) return;
    try {
        const job = await api(`/api/bot-checks/${_botCheckId}`);
        if (job.status === 'running') return;
        clearInterval(_botCheckTimer);
        _botCheckTimer = null;
        $('botCheckCancel').classList.add('hidden');
        $('botCheckStart').disabled = false;
        _botCheckResults = job.results || [];
        renderBotCheckResults(job.status);
    } catch (e) {
        clearInterval(_botCheckTimer);
        _botCheckTimer = null;
        toast(t('toast.error_detail', {detail: e.message}), 'error');
    }
}

async function cancelBotCheck() {
    if (!_botCheckId) return;
    await api(`/api/bot-checks/${_botCheckId}/cancel`, jopts('POST', {}));
    await pollBotCheck();
}

function botCheckValue(value) {
    return t(`check.value.${value || 'not_run'}`);
}

function renderBotCheckResults(status) {
    if (!_botCheckResults.length) {
        $('botCheckResults').innerHTML = `<div class="text-muted p-3">${esc(t(`check.${status}`))}</div>`;
        return;
    }
    $('botCheckResults').innerHTML = `<div class="table-wrap"><table><thead><tr>
        <th>${esc(t('check.col.bot'))}</th><th>${esc(t('check.col.token'))}</th>
        <th>${esc(t('check.col.join'))}</th><th>${esc(t('check.col.read'))}</th>
        <th>${esc(t('check.col.send'))}</th><th>${esc(t('check.col.result'))}</th>
    </tr></thead><tbody>${_botCheckResults.map(item => `<tr>
        <td>${esc(item.nickname || `#${item.account_id}`)}</td>
        <td>${esc(botCheckValue(item.token_status))}</td><td>${esc(botCheckValue(item.join_status))}</td>
        <td>${esc(botCheckValue(item.read_status))}</td><td>${esc(botCheckValue(item.send_status))}</td>
        <td>${esc(botCheckValue(item.result))}: ${esc(t(`check.reason.${item.reason || 'check_failed'}`))}</td>
    </tr>`).join('')}</tbody></table></div>`;
    $('botCheckDownloads').classList.remove('hidden');
}

function downloadBotCheck(format) {
    if (!_botCheckResults.length) return;
    let body;
    let type;
    if (format === 'csv') {
        const quote = value => `"${String(value ?? '').replaceAll('"', '""')}"`;
        const rows = [['bot', 'channel', 'token', 'join', 'read', 'send', 'result', 'reason'],
            ..._botCheckResults.map(item => [item.nickname, item.channel, item.token_status, item.join_status,
                item.read_status, item.send_status, item.result, item.reason])];
        body = rows.map(row => row.map(quote).join(',')).join('\n');
        type = 'text/csv;charset=utf-8';
    } else {
        body = _botCheckResults.map(item => `${item.nickname || `#${item.account_id}`} @ #${item.channel}: ${botCheckValue(item.result)} — ${t(`check.reason.${item.reason || 'check_failed'}`)}`).join('\n');
        type = 'text/plain;charset=utf-8';
    }
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([body], {type}));
    link.download = `bot-check-${Date.now()}.${format === 'csv' ? 'csv' : 'txt'}`;
    link.click();
    URL.revokeObjectURL(link.href);
}

// Q08: фильтры списка ботов — роль и канал, состояние в localStorage
// (старые ключи отсутствуют → читаются с дефолтом «показывать всё»).
function botsChannelOptions() {
    const set = new Set();
    (_allBots || []).forEach(bot => botDisplayChannels(bot, _botStatuses[bot.id] || {})
        .forEach(channel => set.add(String(channel).toLowerCase())));
    return [...set].sort();
}

function botsFiltersSync() {
    const roleSel = $('botsRoleFilter');
    if (roleSel) {
        const saved = localStorage.getItem('botsRoleFilter') || '';
        const roles = ['chatter', 'lurker', 'moderator', 'director'];
        roleSel.innerHTML = `<option value="">${esc(t('bots.filter.all_roles'))}</option>` + roles.map(role =>
            `<option value="${role}">${esc(typeof _roleMetaLabel === 'function' ? _roleMetaLabel(role) : role)}</option>`).join('');
        roleSel.value = saved;
    }
    const channelSel = $('botsChannelFilter');
    if (channelSel) {
        const saved = localStorage.getItem('botsChannelFilter') || '';
        const options = botsChannelOptions();
        channelSel.innerHTML = `<option value="">${esc(t('bots.filter.all_channels'))}</option>` +
            options.map(channel => `<option value="${esc(channel)}">#${esc(channel)}</option>`).join('');
        channelSel.value = options.includes(saved) ? saved : '';
    }
}

function filterBots() {
    const q = ($('botsSearch')?.value || '').toLowerCase();
    const status = $('botsStatusFilter')?.value || '';
    const health = $('botsHealthFilter')?.value || '';
    const sort = $('botsSort')?.value || 'name';
    const role = $('botsRoleFilter')?.value || '';
    const channel = ($('botsChannelFilter')?.value || '').toLowerCase();
    try {
        localStorage.setItem('botsRoleFilter', role);
        localStorage.setItem('botsChannelFilter', channel);
    } catch (e) { /* private mode */ }
    const filtered = _allBots.filter(b => {
        const online = !!_botStatuses[b.id]?.connected;
        const channels = botDisplayChannels(b, _botStatuses[b.id] || {}).map(c => String(c).toLowerCase());
        const h = _botHealthStatuses[String(b.id)] || _botHealthStatuses[b.id];
        const hStatus = h ? h.status : '';
        return (b.nickname || '').toLowerCase().includes(q)
            && (!status || (status === 'online' ? online : !online))
            && (!health || hStatus === health)
            && (!role || (b.bot_role || 'chatter') === role)
            && (!channel || channels.includes(channel));
    });
    filtered.sort((a, b) => sort === 'status'
        ? Number(!!_botStatuses[b.id]?.connected) - Number(!!_botStatuses[a.id]?.connected)
        : (a.nickname || '').localeCompare(b.nickname || ''));
    renderBotsList(filtered);
}

function toggleBotCardMode() {
    const list = $('botsList');
    if (!list) return;
    list.classList.toggle('compact-bot-list');
    localStorage.setItem('compactBotList', list.classList.contains('compact-bot-list') ? '1' : '0');
}

async function showLastObservation(accountId) {
    const channel = (_botStatuses[accountId]?.channels || [])[0];
    if (!channel) { toast(t('status.no_connected_channel'), 'info'); return; }
    try {
        const result = await api(`/api/stream-vision/last-observation/${accountId}/${encodeURIComponent(channel)}`);
        const observation = result.observation;
        if (!observation) { toast(t('status.no_fresh_observation'), 'info'); return; }
        const content = $('observationContent');
        if (content) {
            content.innerHTML = `<div class="text-sm text-muted">#${esc(channel)} · ${esc(t('ui.observation_age', {seconds: observation.age_sec}))}</div>`
                + (observation.frame_url ? `<img src="${esc(observation.frame_url)}" alt="${esc(t('ui.observation_frame'))}" data-i18n-alt="ui.observation_frame">` : '')
                + `<div class="card p-3" data-user-content>${esc([observation.description, observation.transcript].filter(Boolean).join('\n\n') || t('ui.observation_no_text'))}</div>`;
        }
        showModal('observationModal');
    } catch (e) { toast(t('toast.observation_error', {detail: e.message}), 'error'); }
}

// ── Add / delete / toggle ───────────────────────────
function showAddBotModal() { showModal('addBotModal', {initialFocus: 'newBotNick'}); }

// ── Восстановление пачки ботов по токенам → ники из Twitch ──
if (typeof LANGS !== 'undefined') Object.assign(LANGS.ru, {
    'bots.bulk.open': '📥 Восстановить ботов по токенам',
    'bots.bulk.title': '📥 Восстановить ботов по токенам',
    'bots.bulk.hint': 'Вставьте токены из прежней базы: по одному в строке (oauth:… или без префикса). Панель сама узнает ники в Twitch, создаст ботов с выбранной ролью и привяжет их к одному каналу; битые и дубли пропустит с отчётом.',
    'bots.bulk.tokens': 'Токены *',
    'bots.bulk.role': 'Роль новых ботов',
    'bots.bulk.role_lurker': 'Люркер',
    'bots.bulk.role_chatter': 'Болтун',
    'bots.bulk.channel': 'Канал для всех (опционально)',
    'bots.bulk.proxy': 'Прокси для всех (опционально)',
    'bots.bulk.submit': 'Восстановить ботов',
    'bots.bulk.need_tokens': 'Вставьте хотя бы один токен',
    'bots.bulk.running': 'Проверяю токены в Twitch, это может занять до минуты…',
    'bots.bulk.report': 'Готово: добавлено {added}, пропущено {skipped}.',
    'bots.bulk.added_list': 'Добавлены',
    'bots.bulk.skipped_list': 'Пропущены',
    'bots.bulk.reason.invalid_token': 'токен не прошёл проверку Twitch',
    'bots.bulk.reason.duplicate_token': 'такой токен уже был в пачке',
    'bots.bulk.reason.duplicate_batch': 'такой ник уже был в пачке',
    'bots.bulk.reason.duplicate_nickname': 'бот с таким ником уже есть',
});
if (typeof LANGS !== 'undefined') Object.assign(LANGS.en, {
    'bots.bulk.open': '📥 Restore bots from tokens',
    'bots.bulk.title': '📥 Restore bots from tokens',
    'bots.bulk.hint': 'Paste tokens from the previous database, one per line (oauth:… or bare). Twitch provides the nicknames, creates bots with the selected role, and binds them to one channel; invalid tokens and duplicates are skipped with a report.',
    'bots.bulk.tokens': 'Tokens *',
    'bots.bulk.role': 'New bot role',
    'bots.bulk.role_lurker': 'Lurker',
    'bots.bulk.role_chatter': 'Chatter',
    'bots.bulk.channel': 'Channel for all (optional)',
    'bots.bulk.proxy': 'Proxy for all (optional)',
    'bots.bulk.submit': 'Restore bots',
    'bots.bulk.need_tokens': 'Paste at least one token',
    'bots.bulk.running': 'Validating tokens with Twitch, this can take up to a minute…',
    'bots.bulk.report': 'Done: {added} added, {skipped} skipped.',
    'bots.bulk.added_list': 'Added',
    'bots.bulk.skipped_list': 'Skipped',
    'bots.bulk.reason.invalid_token': 'token failed Twitch validation',
    'bots.bulk.reason.duplicate_token': 'token already appeared in this batch',
    'bots.bulk.reason.duplicate_batch': 'nickname already appeared in this batch',
    'bots.bulk.reason.duplicate_nickname': 'a bot with this nickname already exists',
});
if (typeof LANGS !== 'undefined') Object.assign(LANGS.ua, {
    'bots.bulk.open': '📥 Відновити ботів за токенами',
    'bots.bulk.title': '📥 Відновити ботів за токенами',
    'bots.bulk.hint': 'Вставте токени з попередньої бази: по одному в рядку (oauth:… або без префікса). Панель сама дізнається ніки у Twitch, створить ботів з вибраною роллю та прив’яже їх до одного каналу; биті та дублікати пропустить зі звітом.',
    'bots.bulk.tokens': 'Токени *',
    'bots.bulk.role': 'Роль нових ботів',
    'bots.bulk.role_lurker': 'Люркер',
    'bots.bulk.role_chatter': 'Балакун',
    'bots.bulk.channel': 'Канал для всіх (опціонально)',
    'bots.bulk.proxy': 'Проксі для всіх (опціонально)',
    'bots.bulk.submit': 'Відновити ботів',
    'bots.bulk.need_tokens': 'Вставте хоча б один токен',
    'bots.bulk.running': 'Перевіряю токени у Twitch, це може тривати до хвилини…',
    'bots.bulk.report': 'Готово: додано {added}, пропущено {skipped}.',
    'bots.bulk.added_list': 'Додано',
    'bots.bulk.skipped_list': 'Пропущено',
    'bots.bulk.reason.invalid_token': 'токен не пройшов перевірку Twitch',
    'bots.bulk.reason.duplicate_token': 'такий токен уже був у пачці',
    'bots.bulk.reason.duplicate_batch': 'такий нік уже був у пачці',
    'bots.bulk.reason.duplicate_nickname': 'бот із таким ніком уже існує',
});

// Q34a: пачки ботов (DEC-OWNER-019) — RU/EN/UA
if (typeof LANGS !== 'undefined') Object.assign(LANGS.ru, {
    'bots.packs.create': '📦 ➕ Создать пачку',
    'bots.packs.list_title': '📦 Пачки ботов',
    'bots.packs.list_hint': 'Сохранённые наборы ботов. Кнопки «Начать/Свернуть стрим» появятся на следующем шаге (Q34b).',
    'bots.packs.empty': 'Пачек пока нет. Создайте первую кнопкой «Создать пачку».',
    'bots.packs.members_count': 'Ботов: {n}',
    'bots.packs.window_value': 'окно {n} мин',
    'bots.packs.title_create': '📦 Создать пачку',
    'bots.packs.title_edit': '📦 Редактировать пачку',
    'bots.packs.hint': 'Отметьте ботов чекбоксами — это и есть пачка. Канал захода выбирается у каждого бота; «без канала» — оставить как есть сейчас.',
    'bots.packs.name': 'Название пачки *',
    'bots.packs.window': 'Окно захода, минут (0 — сразу)',
    'bots.packs.window_hint': 'Боты пачки зайдут не залпом, а с разбросом в течение этого окна (появится на шаге Q34c).',
    'bots.packs.bots_label': 'Боты пачки',
    'bots.packs.search': '🔍 Поиск по нику',
    'bots.packs.role_all': 'Все роли',
    'bots.packs.select_all': 'Выбрать всех',
    'bots.packs.clear_all': 'Снять всех',
    'bots.packs.no_match': 'Под фильтр ничего не попало.',
    'bots.packs.channel_none': '— без канала —',
    'bots.packs.selected_count': 'Выбрано: {n}',
    'bots.packs.save': 'Сохранить пачку',
    'bots.packs.saved': 'Пачка сохранена',
    'bots.packs.deleted': 'Пачка удалена',
    'bots.packs.confirm_delete': 'Удалить пачку «{name}»?',
    'bots.packs.edit': 'Редактировать',
    'bots.packs.delete': 'Удалить',
    'bots.packs.need_name': 'Введите название пачки',
    'bots.packs.need_members': 'Отметьте хотя бы одного бота',
    'bots.packs.start': 'Начать стрим',
    'bots.packs.collapse': 'Свернуть',
    'bots.packs.with_channels': 'и каналы',
    'bots.packs.confirm_apply': 'Начать стрим по пачке «{name}»? Ботов: {n} — они включатся и зайдут на каналы.',
    'bots.packs.confirm_collapse': 'Свернуть пачку «{name}»? Боты вернутся к состоянию «как было до пачки».',
    'bots.packs.applied': 'Пачка применена: ботов включено {n}',
    'bots.packs.applied_scheduled': 'Заход запланирован: {n} ботов в течение {minutes} мин',
    'bots.packs.collapsed': 'Пачка свернута: ботов выключено {n}',
    'bots.packs.joins_progress': 'Заходят: уже {joined}, ждут {waiting}, ошибок {failed}',
    'bots.packs.joins_done': 'Заход завершён: {joined}, ошибок {failed}',
    'bots.packs.joins_cancel': 'Отменить заходы',
    'bots.packs.joins_cancelled': 'Отменено ожидающих заходов: {n}',
    'api.error.pack_empty': 'В пачке нет ботов — добавьте их через редактирование.',
    'api.error.pack_name_invalid': 'Название пачки: 1–64 символа.',
    'api.error.pack_name_taken': 'Пачка с таким названием уже есть.',
    'api.error.pack_window_invalid': 'Окно захода: целое число 0–180 минут.',
    'api.error.pack_members_invalid': 'Некорректный состав пачки.',
    'api.error.pack_account_missing': 'В пачке есть несуществующий бот. Обновите список.',
    'api.error.pack_missing': 'Пачка не найдена. Обновите список.',
});
if (typeof LANGS !== 'undefined') Object.assign(LANGS.en, {
    'bots.packs.create': '📦 ➕ Create pack',
    'bots.packs.list_title': '📦 Bot packs',
    'bots.packs.list_hint': 'Saved bot sets. The “Start / Collapse stream” buttons arrive in the next step (Q34b).',
    'bots.packs.empty': 'No packs yet. Create the first one with “Create pack”.',
    'bots.packs.members_count': 'Bots: {n}',
    'bots.packs.window_value': 'window {n} min',
    'bots.packs.title_create': '📦 Create pack',
    'bots.packs.title_edit': '📦 Edit pack',
    'bots.packs.hint': 'Tick the bots — that is the pack. Each bot gets its own join channel; “no channel” keeps the current binding.',
    'bots.packs.name': 'Pack name *',
    'bots.packs.window': 'Join window, minutes (0 — immediate)',
    'bots.packs.window_hint': 'Pack bots join spread over this window instead of all at once (arrives in step Q34c).',
    'bots.packs.bots_label': 'Pack bots',
    'bots.packs.search': '🔍 Search by nickname',
    'bots.packs.role_all': 'All roles',
    'bots.packs.select_all': 'Select all',
    'bots.packs.clear_all': 'Clear all',
    'bots.packs.no_match': 'Nothing matches the filter.',
    'bots.packs.channel_none': '— no channel —',
    'bots.packs.selected_count': 'Selected: {n}',
    'bots.packs.save': 'Save pack',
    'bots.packs.saved': 'Pack saved',
    'bots.packs.deleted': 'Pack deleted',
    'bots.packs.confirm_delete': 'Delete pack “{name}”?',
    'bots.packs.edit': 'Edit',
    'bots.packs.delete': 'Delete',
    'bots.packs.need_name': 'Enter a pack name',
    'bots.packs.need_members': 'Tick at least one bot',
    'bots.packs.start': 'Start stream',
    'bots.packs.collapse': 'Collapse',
    'bots.packs.with_channels': 'and channels',
    'bots.packs.confirm_apply': 'Start the stream with pack “{name}”? Bots: {n} — they will be enabled and join their channels.',
    'bots.packs.confirm_collapse': 'Collapse pack “{name}”? Bots return to their pre-pack state.',
    'bots.packs.applied': 'Pack applied: {n} bots enabled',
    'bots.packs.applied_scheduled': 'Joins scheduled: {n} bots over {minutes} min',
    'bots.packs.collapsed': 'Pack collapsed: {n} bots disabled',
    'bots.packs.joins_progress': 'Joining: {joined} done, {waiting} waiting, {failed} failed',
    'bots.packs.joins_done': 'Join finished: {joined}, failed {failed}',
    'bots.packs.joins_cancel': 'Cancel joins',
    'bots.packs.joins_cancelled': 'Pending joins cancelled: {n}',
    'api.error.pack_empty': 'The pack has no bots — add some via Edit.',
    'api.error.pack_name_invalid': 'Pack name: 1–64 characters.',
    'api.error.pack_name_taken': 'A pack with this name already exists.',
    'api.error.pack_window_invalid': 'Join window: an integer 0–180 minutes.',
    'api.error.pack_members_invalid': 'Invalid pack members.',
    'api.error.pack_account_missing': 'The pack contains a missing bot. Refresh the list.',
    'api.error.pack_missing': 'Pack not found. Refresh the list.',
});
if (typeof LANGS !== 'undefined') Object.assign(LANGS.ua, {
    'bots.packs.create': '📦 ➕ Створити пачку',
    'bots.packs.list_title': '📦 Пачки ботів',
    'bots.packs.list_hint': 'Збережені набори ботів. Кнопки «Почати/Згорнути стрім» з’являться на наступному кроці (Q34b).',
    'bots.packs.empty': 'Пачок поки немає. Створіть першу кнопкою «Створити пачку».',
    'bots.packs.members_count': 'Ботів: {n}',
    'bots.packs.window_value': 'вікно {n} хв',
    'bots.packs.title_create': '📦 Створити пачку',
    'bots.packs.title_edit': '📦 Редагувати пачку',
    'bots.packs.hint': 'Позначте ботів галочками — це і є пачка. Канал заходу обирається у кожного бота; «без каналу» — лишити як є зараз.',
    'bots.packs.name': 'Назва пачки *',
    'bots.packs.window': 'Вікно заходу, хвилин (0 — одразу)',
    'bots.packs.window_hint': 'Боти пачки зайдуть не залпом, а з розкидом протягом цього вікна (з’явиться на кроці Q34c).',
    'bots.packs.bots_label': 'Боти пачки',
    'bots.packs.search': '🔍 Пошук за ніком',
    'bots.packs.role_all': 'Усі ролі',
    'bots.packs.select_all': 'Вибрати всіх',
    'bots.packs.clear_all': 'Зняти всіх',
    'bots.packs.no_match': 'Під фільтр нічого не потрапило.',
    'bots.packs.channel_none': '— без каналу —',
    'bots.packs.selected_count': 'Вибрано: {n}',
    'bots.packs.save': 'Зберегти пачку',
    'bots.packs.saved': 'Пачку збережено',
    'bots.packs.deleted': 'Пачку видалено',
    'bots.packs.confirm_delete': 'Видалити пачку «{name}»?',
    'bots.packs.edit': 'Редагувати',
    'bots.packs.delete': 'Видалити',
    'bots.packs.need_name': 'Введіть назву пачки',
    'bots.packs.need_members': 'Позначте хоча б одного бота',
    'bots.packs.start': 'Почати стрім',
    'bots.packs.collapse': 'Згорнути',
    'bots.packs.with_channels': 'й канали',
    'bots.packs.confirm_apply': 'Почати стрім із пачкою «{name}»? Ботів: {n} — вони увімкнуться й зайдуть на канали.',
    'bots.packs.confirm_collapse': 'Згорнути пачку «{name}»? Боти повернуться до стану «як було до пачки».',
    'bots.packs.applied': 'Пачку застосовано: ботів увімкнено {n}',
    'bots.packs.applied_scheduled': 'Заходи заплановано: {n} ботів протягом {minutes} хв',
    'bots.packs.collapsed': 'Пачку згорнуто: ботів вимкнено {n}',
    'bots.packs.joins_progress': 'Заходять: уже {joined}, чекають {waiting}, помилок {failed}',
    'bots.packs.joins_done': 'Заходи завершено: {joined}, помилок {failed}',
    'bots.packs.joins_cancel': 'Скасувати заходи',
    'bots.packs.joins_cancelled': 'Скасовано очікуваних заходів: {n}',
    'api.error.pack_empty': 'У пачці немає ботів — додайте їх через редагування.',
    'api.error.pack_name_invalid': 'Назва пачки: 1–64 символи.',
    'api.error.pack_name_taken': 'Пачка з такою назвою вже існує.',
    'api.error.pack_window_invalid': 'Вікно заходу: ціле число 0–180 хвилин.',
    'api.error.pack_members_invalid': 'Некоректний склад пачки.',
    'api.error.pack_account_missing': 'У пачці є неіснуючий бот. Оновіть список.',
    'api.error.pack_missing': 'Пачку не знайдено. Оновіть список.',
});

// ── Q34a: пачки ботов (DEC-OWNER-019): создание/редактирование лёгким выбором ──
let _botPacksCache = [];
let _botPackEditing = null;
const _botPackSelection = new Map(); // account_id -> channel_name ('' = без канала)
const _botPackJoinTimers = new Map();

async function loadBotPacks() {
    try {
        const data = await api('/api/packs');
        _botPacksCache = data.packs || [];
    } catch (e) { _botPacksCache = []; }
    renderBotPacks();
}

function renderBotPacks() {
    const box = $('botPacksList');
    if (!box) return;
    box.innerHTML = _botPacksCache.map(p => `
        <article class="flex items-center gap-2 flex-wrap p-2" style="border:1px solid var(--border-light);border-radius:10px">
            <strong>${esc(p.name)}</strong>
            <span class="text-muted text-xs">${esc(t('bots.packs.members_count', {n: p.members.length}))} · ${esc(t('bots.packs.window_value', {n: p.join_window_min}))}</span>
            <span class="flex gap-1" style="margin-left:auto">
                ${p.members.length ? `<button class="btn btn-primary btn-sm" onclick="applyBotPack(${p.id})">▶ <span>${esc(t('bots.packs.start'))}</span></button>
                <button class="btn btn-secondary btn-sm" onclick="collapseBotPack(${p.id})">⏹ <span>${esc(t('bots.packs.collapse'))}</span></button>
                <label class="text-xs text-muted"><input type="checkbox" id="botPackCh_${p.id}"> ${esc(t('bots.packs.with_channels'))}</label>` : ''}
                <button class="btn btn-secondary btn-sm" onclick="showBotPackModal(${p.id})">✏️ <span>${esc(t('bots.packs.edit'))}</span></button>
                <button class="btn btn-danger btn-sm" onclick="deleteBotPack(${p.id})">🗑 <span>${esc(t('bots.packs.delete'))}</span></button>
            </span>
            <div id="botPackJoin_${p.id}" class="text-xs text-muted" style="flex-basis:100%"></div>
        </article>`).join('') || `<div class="text-muted text-sm">${esc(t('bots.packs.empty'))}</div>`;
    const activeIds = new Set(_botPacksCache.filter(p => p.active_joins).map(p => p.id));
    for (const id of _botPackJoinTimers.keys()) if (!activeIds.has(id)) _botPackStopJoinPolling(id);
    for (const id of activeIds) pollBotPackJoins(id);
}

// Q34b/Q34c: применение/сворачивание и прогресс распределённого захода.
function _botPackStopJoinPolling(id) {
    const timer = _botPackJoinTimers.get(id);
    if (timer) clearTimeout(timer);
    _botPackJoinTimers.delete(id);
}

async function pollBotPackJoins(id) {
    _botPackStopJoinPolling(id);
    const target = $('botPackJoin_' + id);
    if (!target) return;
    try {
        const res = await api(`/api/packs/${id}/joins`);
        const counts = res.counts || {};
        const waiting = (counts.pending || 0) + (counts.running || 0);
        const joined = counts.joined || 0;
        const failed = counts.failed || 0;
        target.innerHTML = waiting
            ? `${esc(t('bots.packs.joins_progress', {joined, waiting, failed}))} <button class="btn btn-secondary btn-sm" onclick="cancelBotPackJoins(${id})">${esc(t('bots.packs.joins_cancel'))}</button>`
            : (joined || failed ? esc(t('bots.packs.joins_done', {joined, failed})) : '');
        if (waiting) _botPackJoinTimers.set(id, setTimeout(() => pollBotPackJoins(id), 3000));
    } catch (e) {
        target.textContent = t('toast.error_detail', {detail: e.message});
    }
}

async function cancelBotPackJoins(id) {
    try {
        const res = await api(`/api/packs/${id}/joins/cancel`, jopts('POST', {}));
        toast(t('bots.packs.joins_cancelled', {n: res.cancelled ?? 0}), 'success');
        await pollBotPackJoins(id);
    } catch (e) {
        toast(t('toast.error_detail', {detail: e.message}), 'error');
    }
}

async function applyBotPack(id) {
    const pack = _botPacksCache.find(p => p.id === id);
    if (!pack) return;
    if (!confirm(t('bots.packs.confirm_apply', {name: pack.name, n: pack.members.length}))) return;
    try {
        const res = await api(`/api/packs/${id}/apply`, jopts('POST', {connect: true}));
        if (res.scheduled) {
            toast(t('bots.packs.applied_scheduled', {n: res.scheduled, minutes: res.window_min}), 'success');
            await loadBotPacks(); // renderBotPacks подхватит active_joins и включит polling один раз
        } else {
            toast(t('bots.packs.applied', {n: res.enabled ?? 0}), 'success');
            await loadBotsList();
        }
    } catch (e) {
        toast(t('toast.error_detail', {detail: e.message}), 'error');
    }
}

async function collapseBotPack(id) {
    const pack = _botPacksCache.find(p => p.id === id);
    if (!pack) return;
    if (!confirm(t('bots.packs.confirm_collapse', {name: pack.name}))) return;
    const withChannels = $('botPackCh_' + id)?.checked === true;
    try {
        const res = await api(`/api/packs/${id}/collapse`, jopts('POST', {disable_channels: withChannels}));
        _botPackStopJoinPolling(id);
        toast(t('bots.packs.collapsed', {n: res.disabled ?? 0}), 'success');
        await loadBotsList();
    } catch (e) {
        toast(t('toast.error_detail', {detail: e.message}), 'error');
    }
}

function _botPackVisibleBots() {
    const q = ($('botPackSearch')?.value || '').trim().toLowerCase();
    const role = $('botPackRoleFilter')?.value || '';
    return (_allBots || []).filter(b =>
        (!role || b.bot_role === role) &&
        (!q || String(b.nickname || '').toLowerCase().includes(q)));
}

function renderBotPackBots() {
    const box = $('botPackBots');
    if (!box) return;
    const allChannels = [...new Set((_allBots || []).flatMap(b => b.persisted_channels || []))].sort();
    box.innerHTML = _botPackVisibleBots().map(b => {
        const channels = [...new Set([...(b.persisted_channels || []), ...allChannels])].sort();
        const checked = _botPackSelection.has(b.id);
        const current = _botPackSelection.has(b.id)
            ? _botPackSelection.get(b.id)
            : ((b.persisted_channels || [])[0] ?? '');
        return `<label class="flex items-center gap-2 py-1" style="border-bottom:1px solid var(--border-light)">
            <input type="checkbox" ${checked ? 'checked' : ''} onchange="botPackToggle(${b.id}, this.checked)">
            <span style="min-width:110px">${esc(b.nickname || '#' + b.id)} <small class="text-muted">${esc(b.bot_role || '')}</small></span>
            <select class="input compact-select" style="margin-left:auto;max-width:170px" onchange="botPackChannel(${b.id}, this.value)">
                <option value="">${esc(t('bots.packs.channel_none'))}</option>
                ${channels.map(c => `<option value="${esc(c)}" ${c === current ? 'selected' : ''}>${esc(c)}</option>`).join('')}
            </select>
        </label>`;
    }).join('') || `<div class="text-muted text-sm">${esc(t('bots.packs.no_match'))}</div>`;
    _botPackCountSync();
}

function _botPackCountSync() {
    const count = $('botPackCount');
    if (count) count.textContent = t('bots.packs.selected_count', {n: _botPackSelection.size});
}

function botPackToggle(id, on) {
    if (on && !_botPackSelection.has(id)) {
        const bot = (_allBots || []).find(x => x.id === id);
        _botPackSelection.set(id, (bot?.persisted_channels || [])[0] ?? '');
    } else if (!on) _botPackSelection.delete(id);
    _botPackCountSync();
}

function botPackChannel(id, value) {
    if (_botPackSelection.has(id)) _botPackSelection.set(id, value);
}

function botPackSelectAll(on) {
    if (!on) _botPackSelection.clear(); // «Снять всех» чистит всё выделение, не только видимое
    else for (const bot of _botPackVisibleBots()) {
        if (!_botPackSelection.has(bot.id)) _botPackSelection.set(bot.id, (bot.persisted_channels || [])[0] ?? '');
    }
    renderBotPackBots();
}

function botPackFilterChanged() { renderBotPackBots(); }

function showBotPackModal(packId) {
    _botPackEditing = packId || null;
    const pack = packId ? _botPacksCache.find(p => p.id === packId) : null;
    _botPackSelection.clear();
    if (pack) (pack.members || []).forEach(m => _botPackSelection.set(m.account_id, m.channel_name || ''));
    const title = $('botPackTitle');
    if (title) {
        const key = pack ? 'bots.packs.title_edit' : 'bots.packs.title_create';
        title.dataset.i18n = key;
        title.textContent = t(key);
    }
    if ($('botPackName')) $('botPackName').value = pack ? pack.name : '';
    if ($('botPackWindow')) $('botPackWindow').value = pack ? pack.join_window_min : 5;
    const roleSel = $('botPackRoleFilter');
    if (roleSel) {
        const roles = [...new Set((_allBots || []).map(b => b.bot_role).filter(Boolean))].sort();
        roleSel.innerHTML = `<option value="">${esc(t('bots.packs.role_all'))}</option>` +
            roles.map(r => `<option value="${esc(r)}">${esc(typeof _roleMetaLabel === 'function' ? _roleMetaLabel(r) : r)}</option>`).join('');
        roleSel.value = '';
    }
    if ($('botPackSearch')) $('botPackSearch').value = '';
    renderBotPackBots();
    showModal('botPackModal', {initialFocus: 'botPackName'});
}

async function submitBotPack() {
    const name = $('botPackName')?.value.trim() || '';
    const parsed = parseInt($('botPackWindow')?.value, 10);
    const windowMin = Number.isFinite(parsed) ? parsed : 5;
    if (!name) { toast(t('bots.packs.need_name'), 'error'); return; }
    if (!_botPackSelection.size) { toast(t('bots.packs.need_members'), 'error'); return; }
    const members = [..._botPackSelection.entries()].map(([account_id, channel_name]) => ({account_id, channel_name}));
    const body = {name, join_window_min: windowMin, members};
    const btn = $('botPackSaveBtn');
    if (btn) btn.disabled = true;
    try {
        if (_botPackEditing) await api(`/api/packs/${_botPackEditing}`, jopts('PUT', body));
        else await api('/api/packs', jopts('POST', body));
        hideModal('botPackModal');
        await loadBotPacks();
        toast(t('bots.packs.saved'), 'success');
    } catch (e) {
        toast(t('toast.error_detail', {detail: e.message}), 'error');
    } finally {
        if (btn) btn.disabled = false;
    }
}

async function deleteBotPack(id) {
    const pack = _botPacksCache.find(p => p.id === id);
    if (!pack) return;
    if (!confirm(t('bots.packs.confirm_delete', {name: pack.name}))) return;
    try {
        await api(`/api/packs/${id}`, {method: 'DELETE'});
        await loadBotPacks();
        toast(t('bots.packs.deleted'), 'success');
    } catch (e) {
        toast(t('toast.error_detail', {detail: e.message}), 'error');
    }
}

function setBulkTokensExample(format) {
    const box = $('bulkLurkerTokens');
    if (!box) return;
    const examples = {
        store: "bot_gamer_01:Pass1234:auth-token=a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4; unique_id=u123;\nbot_stream_02:SecretPass:oauth:9876543210abcdef9876543210ab",
        cookie: "auth-token=a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4; unique_id=u12345;\nauth-token=9876543210abcdef9876543210abcdef; unique_id=u67890;",
        json: `[\n  {"name": "auth-token", "value": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"}\n]`,
        proxy: "bot_eu1:pass:a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4:socks5://proxy1.example.com:1080\nbot_us2:pass:9876543210abcdef9876543210abcdef:192.168.1.100:8080:user:secret",
        token: "oauth:a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4\n9876543210abcdef9876543210abcdef"
    };
    box.value = examples[format] || '';
    onBulkTokensInput();
}

function onBulkTokensInput() {
    const box = $('bulkLurkerTokens');
    const counter = $('bulkLurkersParseCount');
    if (!box || !counter) return;
    const raw = box.value.trim();
    if (!raw) {
        counter.textContent = '0 ботов';
        return;
    }
    if ((raw.startsWith('[') && raw.endsWith(']')) || (raw.startsWith('{') && raw.endsWith('}'))) {
        try {
            const data = JSON.parse(raw);
            if (Array.isArray(data)) {
                const count = data.filter(item => (item && item.name === 'auth-token') || (item && item.token)).length || (data.some(i => i && i.name === 'auth-token') ? 1 : 0);
                counter.textContent = `JSON: ${count || 1} бот(ов)`;
                return;
            }
        } catch (_) {}
    }
    const lines = raw.split('\n').map(s => s.trim()).filter(s => s && !s.startsWith('#'));
    counter.textContent = `Строк: ${lines.length}`;
}

function onNewBotTokenInput(el) {
    if (!el) return;
    const val = el.value.trim();
    const nickInput = $('newBotNick');
    const proxyInput = $('newBotProxy');
    const hint = $('newBotParsedHint');
    if (!val) {
        if (hint) { hint.classList.add('hidden'); hint.textContent = ''; }
        return;
    }
    let detectedNick = '';
    let detectedProxy = '';
    const cookieMatch = val.match(/(?:^|[;\s])auth-token=([a-zA-Z0-9_-]+)/i);
    const protoProxy = val.match(/((?:https?|socks[45]?):\/\/[^\s|]+)/i);
    if (protoProxy) detectedProxy = protoProxy[1].replace(/[;,]+$/, '');

    const clean = protoProxy ? val.replace(protoProxy[0], '') : val;
    const parts = clean.split(/[:|]/).map(s => s.trim()).filter(Boolean);
    if (parts.length >= 2 && /^[a-zA-Z0-9_]{3,25}$/.test(parts[0]) && !parts[0].includes('@')) {
        detectedNick = parts[0];
    }
    if (parts.length >= 4 && !detectedProxy) {
        const candidate = parts.slice(-4);
        if (/^\d{1,3}(?:\.\d{1,3}){3}$/.test(candidate[0]) && /^\d{2,5}$/.test(candidate[1])) {
            detectedProxy = `http://${candidate[2]}:${candidate[3]}@${candidate[0]}:${candidate[1]}`;
        }
    }

    if (detectedNick && nickInput && !nickInput.value) {
        nickInput.value = detectedNick;
    }
    if (detectedProxy && proxyInput && !proxyInput.value) {
        proxyInput.value = detectedProxy;
    }
    if (hint) {
        if (detectedNick || detectedProxy || cookieMatch) {
            hint.classList.remove('hidden');
            const items = [];
            if (cookieMatch) items.push('auth-token найден');
            if (detectedNick) items.push(`ник: ${detectedNick}`);
            if (detectedProxy) items.push('прокси найден');
            hint.textContent = `✓ Распознано: ${items.join(', ')}`;
        } else {
            hint.classList.add('hidden');
            hint.textContent = '';
        }
    }
}

async function showBulkLurkersModal() {
    const report = $('bulkLurkersReport');
    if (report) { report.classList.add('hidden'); report.innerHTML = ''; }
    showModal('bulkLurkersModal', {initialFocus: 'bulkLurkerTokens'});
    onBulkTokensInput();
    try {
        const overview = await api('/api/channel-overview');
        const channels = [...new Set((overview.channels || []).map(item => item.channel).filter(Boolean))].sort();
        const options = $('bulkLurkerChannelOptions');
        if (options) options.innerHTML = channels.map(channel => `<option value="${esc(channel)}">#${esc(channel)}</option>`).join('');
    } catch (e) { /* Manual channel entry remains available if the suggestions cannot load. */ }
}

async function submitBulkLurkers() {
    const box = $('bulkLurkerTokens');
    const report = $('bulkLurkersReport');
    const btn = $('bulkLurkersSubmitBtn');
    if (!box) return;
    const rawInput = box.value.trim();
    if (!rawInput) { toast(t('bots.bulk.need_tokens'), 'error'); return; }
    let tokens;
    if (rawInput.startsWith('[') || rawInput.startsWith('{')) {
        tokens = [rawInput];
    } else {
        tokens = rawInput.split('\n').map(s => s.trim()).filter(Boolean);
    }
    if (!tokens.length) { toast(t('bots.bulk.need_tokens'), 'error'); return; }
    const role = $('bulkLurkerRole')?.value || 'lurker';
    const channel = $('bulkLurkerChannel')?.value.trim().replace('#', '') || '';
    const proxy = $('bulkLurkerProxy')?.value.trim() || '';
    if (btn) btn.disabled = true;
    if (report) { report.classList.remove('hidden'); report.innerHTML = `<div class="text-sm text-muted">${esc(t('bots.bulk.running'))}</div>`; }
    try {
        const res = await api('/api/accounts/bulk-lurkers', jopts('POST', { tokens, role, channel, proxy }));
        if (!res.ok) throw new Error(res.error || 'bulk_failed');
        const names = (res.added || []).map(a => a.nickname).join(', ');
        const skipped = res.skipped || [];
        let html = `<div class="card p-3" style="background:var(--bg-active)">
            <b class="text-sm">${esc(t('bots.bulk.report', { added: (res.added || []).length, skipped: skipped.length }))}</b>`;
        if (names) html += `<div class="text-xs mt-1">${esc(t('bots.bulk.added_list'))}: <span class="font-mono">${esc(names)}</span></div>`;
        if (skipped.length) {
            html += `<div class="text-xs mt-2">${esc(t('bots.bulk.skipped_list'))}:</div><ul class="text-xs text-muted mt-1">` +
                skipped.map(s => `<li><code>${esc(s.token || '?')}</code> — ${esc(t(`bots.bulk.reason.${s.reason || 'invalid_token'}`))}${s.nickname ? ` (${esc(s.nickname)})` : ''}</li>`).join('') +
                '</ul>';
        }
        html += '</div>';
        if (report) report.innerHTML = html;
        box.value = '';
        onBulkTokensInput();
        toast(t('bots.bulk.report', { added: (res.added || []).length, skipped: skipped.length }), 'success');
        await loadBotsList();
    } catch (e) {
        if (report) report.innerHTML = `<div class="text-sm" style="color:var(--danger)">${esc(t('toast.error_detail', { detail: e.message }))}</div>`;
        toast(t('toast.error_detail', { detail: e.message }), 'error');
    } finally {
        if (btn) btn.disabled = false;
    }
}

function hideAddBotModal() {
    hideModal('addBotModal');
    ['newBotNick', 'newBotToken', 'newBotProxy', 'newBotChannel'].forEach(id => { if ($(id)) $(id).value = ''; });
    const hint = $('newBotParsedHint');
    if (hint) { hint.classList.add('hidden'); hint.textContent = ''; }
    oauthFlowCancel(true);
}

// ── §9i: Twitch Device Code Flow (вход без ручного токена) ──
let _oauthPollTimer = null;
let _oauthDeviceCode = '';

async function oauthFlowStart() {
    const btn = $('oauthStartBtn');
    if (btn) btn.disabled = true;
    try {
        const res = await api('/api/twitch-oauth/start', jopts('POST', {}));
        if (!res.ok) {
            toast(t('toast.error_detail', {detail: res.error || 'oauth'}), 'error');
            return;
        }
        _oauthDeviceCode = res.device_code;
        $('oauthUserCode').textContent = res.user_code || '';
        $('oauthFlowBox').classList.remove('hidden');
        $('oauthStatus').textContent = t('oauth.waiting');
        if (res.verify_url) window.open(res.verify_url, '_blank', 'noopener');
        if (_oauthPollTimer) clearInterval(_oauthPollTimer);
        _oauthPollTimer = setInterval(oauthFlowPoll, 5000);
    } catch (e) {
        toast(t('toast.error_detail', {detail: e.message}), 'error');
    } finally {
        if (btn) btn.disabled = false;
    }
}

async function oauthFlowPoll() {
    if (!_oauthDeviceCode) return;
    try {
        const res = await api('/api/twitch-oauth/poll', jopts('POST', { device_code: _oauthDeviceCode }));
        if (res.ok) {
            // Успех: бэкенд сам создал/обновил аккаунт и вернул account_id + login
            stopOauthPolling();
            $('oauthStatus').textContent = t('oauth.done');
            toast(t('toast.bot_created', {detail: res.login || res.account_id}), 'success');
            hideModal('addBotModal');
            oauthFlowReset();
            await loadBotsList();
        } else if (res.status === 'pending' || res.status === 'slow_down') {
            $('oauthStatus').textContent = t('oauth.waiting');
        } else {
            stopOauthPolling();
            $('oauthStatus').textContent = res.error || res.status || t('send.reason.unknown');
        }
    } catch (e) { /* сеть дёрнулась — продолжаем поллинг */ }
}

async function oauthFlowCancel(silent = false) {
    stopOauthPolling();
    if (_oauthDeviceCode && !silent) {
        try { await api('/api/twitch-oauth/cancel', jopts('POST', { device_code: _oauthDeviceCode })); } catch (e) { /* noop */ }
    }
    oauthFlowReset();
    if (!silent) $('oauthFlowBox')?.classList.add('hidden');
}

function stopOauthPolling() {
    if (_oauthPollTimer) { clearInterval(_oauthPollTimer); _oauthPollTimer = null; }
}

function oauthFlowReset() {
    _oauthDeviceCode = '';
    if ($('oauthFlowBox')) $('oauthFlowBox').classList.add('hidden');
    if ($('oauthUserCode')) $('oauthUserCode').textContent = '';
}

async function createBot() {
    const nickname = $('newBotNick').value.trim();
    const token = $('newBotToken').value.trim();
    if (!nickname || !token) { toast(t('toast.required_nickname_token'), 'error'); return; }
    try {
        const bot = await api('/api/accounts', jopts('POST', {
            nickname, token, proxy: $('newBotProxy').value.trim(),
        }));
        const channel = $('newBotChannel').value.trim().replace('#', '');
        if (channel && bot.id) {
            await api(`/api/accounts/${bot.id}/channels`, jopts('POST', { channel_name: channel }));
        }
        hideAddBotModal();
        toast(t('toast.bot_created', {detail: nickname}), 'success');
        await loadBotsList();
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function deleteBot() {
    if (!_currentBotId || !_currentBot) return;
    if (!confirm(t('confirm.delete_bot', {name: _currentBot.nickname}))) return;
    try {
        await api(`/api/accounts/${_currentBotId}`, { method: 'DELETE' });
        toast(t('toast.bot_deleted'), 'success');
        closeBotSettings();
        await loadBotsList();
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function quickToggleBot(id, btn) {
    const bot = _allBots.find(b => b.id === id);
    if (!bot) return;
    // Owner report 27.09.2026: решение «старт/стоп» бралось из _botStatuses,
    // который к моменту клика мог быть пустым (только что открыли панель) —
    // тогда кнопка «Старт» вела себя как «Стоп». Спрашиваем живой статус.
    let st = _botStatuses[id] || {};
    try { st = (await api('/api/bots/status'))?.[id] || st; } catch (e) { /* останется кэш */ }
    const shouldStop = Boolean(st.connected) || Boolean(bot.enabled);
    if (btn) btn.disabled = true;
    _busyBots.add(id);
    try {
        // Один эндпоинт на действие: /start и /stop сами владеют флагом
        // accounts.enabled (двойной toggle+start давал «Ошибка» и рассинхрон).
        await api(`/api/accounts/${id}/${shouldStop ? 'stop' : 'start'}`, { method: 'POST' });
        toast(t(shouldStop ? 'toast.bot_stopped' : 'toast.bot_started'), 'success');
        await loadBotsList();
    } catch (e) {
        _busyBots.delete(id);
        if (btn) btn.disabled = false;
        toast(t('toast.error_detail', {detail: e.message}), 'error');
    }
}

async function toggleBot() {
    if (!_currentBotId) return;
    await quickToggleBot(_currentBotId);
    await loadBotGeneral(_currentBotId);
    // оновити кнопку в хедері
    await refreshHeaderToggle();
}

async function refreshHeaderToggle() {
    try {
        const statuses = await api('/api/bots/status');
        _botStatuses = statuses || {};
        const st = _botStatuses[_currentBotId] || {};
        const bot = _allBots.find(b => b.id === _currentBotId);
        const active = st.connected || (bot && bot.enabled);
        const btn = $('botHeaderToggle');
        if (btn) {
            btn.textContent = active ? t('btn.stop') : t('btn.start');
            btn.className = active ? 'btn btn-sm btn-danger' : 'btn btn-sm btn-primary';
        }
    } catch (e) { /* noop */ }
}

// ── Bot settings panel ──────────────────────────────
function openBotSettings(id, initialTab) {
    _currentBotId = id;
    _currentBot = _allBots.find(b => b.id === id);
    if ((_currentBot?.bot_role || 'chatter') === 'director') {
        openDirectorPanel(id);
        return;
    }
    try { localStorage.setItem('panel_active_bot_id', id); } catch (e) {}
    $('botsListView').classList.add('hidden');
    $('botSettingsPanel').classList.remove('hidden');
    $('botSettingsTitle').textContent = `⚙️ ${_currentBot?.nickname || t('dynamic.bot_number', {id})}`;
    applyBotRoleVisibility(_currentBot?.bot_role || 'chatter', 'silent');
    const tabToOpen = initialTab || localStorage.getItem('panel_active_bot_tab') || 'general';
    showBotTab(tabToOpen);
    loadBotGeneral(id);
    loadBotRole(id);
    loadBotPersona(id);
    loadAnalyzerSettings(id);
    loadBotChannels(id);
    loadBotTTS(id);
    loadBotAttention(id);
    loadBotLogs();
    loadBotStreamer(id);
    loadBotOverviewExtras();
    refreshHeaderToggle();
}

function openDirectorPanel() {
    // Q40: у Режиссёра снова своя страница с вкладкой на каждый канал;
    // карточка бота-режиссёра и старые кнопки ведут туда.
    showSection('director');
}

function closeBotSettings() {
    if (!confirmDirty()) return; // P8-C13: несохранённые изменения — спросить
    _currentBotId = null;
    _currentBot = null;
    try { localStorage.removeItem('panel_active_bot_id'); } catch (e) {}
    $('botsListView').classList.remove('hidden');
    $('botSettingsPanel').classList.add('hidden');
}

async function startAllBots() {
    if (!confirm('Запустить всех активных ботов?')) return;
    try {
        toast('Запускаем всех ботов...', 'info');
        const res = await api('/api/bots/start-all', jopts('POST', {}));
        if (res.ok) {
            toast(`Запущено ботов: ${res.started} из ${res.total}`, 'success');
            loadBotsList();
        } else {
            toast(res.error || 'Ошибка запуска', 'error');
        }
    } catch (e) {
        toast(t('toast.error_detail', { detail: e.message }), 'error');
    }
}

async function stopAllBots() {
    if (!confirm('Остановить всех запущенных ботов?')) return;
    try {
        const res = await api('/api/bots/stop-all', jopts('POST', {}));
        if (res.ok) {
            toast(`Остановлено ботов: ${res.stopped}`, 'success');
            loadBotsList();
        } else {
            toast(res.error || 'Ошибка остановки', 'error');
        }
    } catch (e) {
        toast(t('toast.error_detail', { detail: e.message }), 'error');
    }
}

const BOT_TAB_GROUPS = {
    overview: ['general'],
    'brain-x': ['brain-x'],
    identity: ['persona'],
    flow: ['channels', 'attention', 'triggers', 'events', 'filters', 'chat-users'],
    moderation: ['moderation'],
    voice: ['tts', 'voice-clones'],
    memory: ['memory', 'streamer', 'knowledge', 'snippets'],
    advanced: ['logs', 'files'],
    sandbox: ['sandbox'],
};
let _currentBotGroup = 'overview';
function showBotGroup(group) {
    let tabs = (BOT_TAB_GROUPS[group] || BOT_TAB_GROUPS.overview).filter(botRoleAllowsTab);
    if (!tabs.length) { group = 'overview'; tabs = ['general']; }
    _currentBotGroup = BOT_TAB_GROUPS[group] ? group : 'overview';
    document.querySelectorAll('.bot-tab').forEach(tab => tab.classList.toggle('hidden', !tabs.includes(tab.id.replace('botTab-', ''))));
    document.querySelectorAll('[data-bot-group]').forEach(btn => btn.classList.toggle('active', btn.dataset.botGroup === group));
    tabs.forEach(name => _botTabLoaders()[name]?.(_currentBotId));
}

let _botVisibleRole = 'chatter';
let _botRoleChatAllowed = true;
function botRoleAllowsTab(tab) {
    if (_botVisibleRole === 'director') return tab === 'general';
    if (_botVisibleRole === 'lurker') return ['general', 'channels'].includes(tab);
    if (_botVisibleRole === 'moderator' && !_botRoleChatAllowed) return ['general', 'channels', 'moderation', 'logs', 'files'].includes(tab);
    if (tab === 'moderation') return _botVisibleRole === 'moderator';
    if (['tts', 'voice-clones'].includes(tab)) return _botVisibleRole === 'voice_companion';
    return true;
}
function applyBotRoleVisibility(role, chatActivity = 'chatter') {
    _botVisibleRole = role;
    _botRoleChatAllowed = role !== 'moderator' || chatActivity === 'chatter';
    const hidden = Object.keys(BOT_TAB_GROUPS).filter(group => !BOT_TAB_GROUPS[group].some(botRoleAllowsTab));
    document.querySelectorAll('[data-bot-group]').forEach(btn => {
        btn.classList.toggle('hidden', hidden.includes(btn.dataset.botGroup));
    });
    document.querySelectorAll('[data-bot-tab]').forEach(btn => btn.classList.toggle('hidden', !botRoleAllowsTab(btn.dataset.botTab)));
    let hiddenActiveTab = false;
    document.querySelectorAll('.bot-tab').forEach(tab => {
        if (!botRoleAllowsTab(tab.id.replace('botTab-', ''))) {
            hiddenActiveTab ||= !tab.classList.contains('hidden');
            tab.classList.add('hidden');
        }
    });
    $('botQuickBehaviorCard')?.classList.toggle('hidden', ['lurker', 'director'].includes(role) || !_botRoleChatAllowed);
    for (const id of ['botAIProvider', 'clipCheckResult', 'replaySessionsList']) {
        $(id)?.closest('.card')?.classList.toggle('hidden', ['lurker', 'director'].includes(role));
    }
    if (hidden.includes(_currentBotGroup) || hiddenActiveTab) {
        _currentBotGroup = 'overview';
        document.querySelectorAll('.bot-tab').forEach(tab => tab.classList.toggle('hidden', tab.id !== 'botTab-general'));
        document.querySelectorAll('[data-bot-group]').forEach(btn => btn.classList.toggle('active', btn.dataset.botGroup === 'overview'));
    }
}

// Ролевые настройки всегда остаются рядом с выбором роли: иначе общие вкладки
// визуально скрывают главное различие между ролями.
function relocateRoleConfig(role) {
    const box = $('roleConfigBox');
    if (!box) return;
    const slot = $('roleSlotOverview');
    if (slot && box.parentElement !== slot) slot.appendChild(box);
    box.classList.remove('hidden');
}

// ── Tab: General ────────────────────────────────────
// Q15b (E3): named custom-провайдер бота (custom:<name>) или null.
function _botNamedProvider() {
    const provider = $('botAIProvider')?.value || '';
    if (!provider.startsWith('custom:')) return null;
    return _customProvidersCache.find(p => `custom:${p.name}` === provider) || null;
}

function _fillModelSelect(sel, models, current, defaultLabelKey) {
    sel.replaceChildren();
    const def = document.createElement('option');
    def.value = '';
    def.textContent = t(defaultLabelKey);
    sel.appendChild(def);
    for (const model of models) {
        const option = document.createElement('option');
        option.value = model;
        option.textContent = model;
        sel.appendChild(option);
    }
    sel.value = models.includes(current) ? current : '';
}

// Единый рефрешер AI-полей бота: у custom:*-провайдера чат- и vision-модели —
// дропдауны из его списков (ручной ввод строкой недоступен), у остальных —
// свободный ввод как раньше. Видимость синхронизируется с режимом vision (Q15a).
function refreshBotAIModels() {
    const named = _botNamedProvider();
    const chatSel = $('botAIModelSelect'), chatInput = $('botAIModel');
    const visSel = $('botAIVisionModelSelect'), visInput = $('botAIVisionModel');
    const own = ($('botAIVisionMode')?.value || 'shared') === 'own';
    if (chatSel && chatInput) {
        if (named) {
            chatInput.classList.add('hidden');
            chatSel.classList.remove('hidden');
            _fillModelSelect(chatSel, named.models || [], chatSel.value || chatInput.value, 'bot.model_default');
        } else {
            chatSel.classList.add('hidden');
            chatSel.replaceChildren();
            chatInput.classList.remove('hidden');
        }
    }
    if (visSel && visInput) {
        if (named && own) {
            visInput.classList.add('hidden');
            visSel.classList.remove('hidden');
            _fillModelSelect(visSel, named.vision_models || [], visSel.value || visInput.value, 'bot.vision_default');
        } else {
            visSel.classList.add('hidden');
            visSel.replaceChildren();
            visInput.classList.toggle('hidden', !own);
        }
    }
}

// Q15d (E5): заполнить форму smart-routing из конфига бота (null = глобальный legacy).
function _loadBotSmartRouting(sr) {
    const cfg = sr || {};
    $('botAISmartRouting')?.classList.toggle('active', !!cfg.enabled);
    $('botAISmartRouting')?.setAttribute('aria-checked', String(!!cfg.enabled));
    if ($('botAISRThreshold')) $('botAISRThreshold').value = cfg.threshold || 600;
    if ($('botAISimpleProvider')) $('botAISimpleProvider').value = cfg.simple_provider || '';
    if ($('botAISimpleModel')) $('botAISimpleModel').value = cfg.simple_model || '';
    if ($('botAIComplexProvider')) $('botAIComplexProvider').value = cfg.complex_provider || '';
    if ($('botAIComplexModel')) $('botAIComplexModel').value = cfg.complex_model || '';
}

// Смена провайдера: прежние значения моделей другого провайдера не сохраняются.
function onBotAIProviderChange() {
    if ($('botAIModel')) $('botAIModel').value = '';
    if ($('botAIVisionModel')) $('botAIVisionModel').value = '';
    refreshBotAIModels();
}

// Q15a (DEC-OWNER-016): Vision «общая (по умолчанию) / своя».
// Контракт хранения не меняется: пустой ai_vision_model_override = общая база.
// Видимость полей «своя» (свободный ввод / дропдаун custom-провайдера) — Q15b.
function onBotVisionModeChange() {
    refreshBotAIModels();
}

function _botVisionModeFromOverride(value) {
    return value ? 'own' : 'shared';
}

async function loadBotGeneral(id) {
    try {
        // §4.3: named custom-провайдеры (custom:<name>) должны попасть в
        // селект ДО выставления override, иначе значение потеряется.
        await loadCustomProviders();
        const [bot, ov] = await Promise.all([
            api(`/api/accounts/${id}`),
            api(`/api/accounts/${id}/ai-override`),
        ]);
        _currentBot = bot && !bot.error ? bot : _currentBot;
        $('botNick').value = (bot.nickname || '');
        $('botProxy').value = (bot.proxy || '');
        updateBotProxyStatusBadge(id, bot.proxy);
        $('botToken').value = '';
        $('botToken').placeholder = bot.token_masked ? bot.token_masked : 'oauth:...';
        $('botAIProvider').value = ov.ai_provider_override || '';
        $('botAIModel').value = ov.ai_chat_model_override || '';
        if ($('botAIVisionModel')) {
            $('botAIVisionModel').value = ov.ai_vision_model_override || '';
            // Q15a: селектор «общая/своя» выводится из пустоты override
            const mode = $('botAIVisionMode');
            if (mode) {
                mode.value = _botVisionModeFromOverride(ov.ai_vision_model_override);
                $('botAIVisionModel').classList.toggle('hidden', mode.value !== 'own');
            }
        }
        refreshBotAIModels();
        $('botAIProvider').onchange = onBotAIProviderChange;
        // Q15c (E4): резерв «локальная Ollama» — ручной opt-in per-бот
        $('botAILocalFallback')?.classList.toggle('active', !!ov.ai_local_fallback);
        $('botAILocalFallback')?.setAttribute('aria-checked', String(!!ov.ai_local_fallback));
        // Q15d (E5): smart-routing per-бот (null = наследовать глобальный)
        _loadBotSmartRouting(ov.ai_smart_routing);
        loadBotReplayAuto(); // Q16 F5: автозапись replay-сессий — настройка бота
        $('botAIKey').value = '';
        $('botAIKey').placeholder = (ov.has_openrouter_api_key_override || ov.has_ai_api_key_override) ? t('placeholder.eleven_key_set') : 'sk-...';
        // P8-C13: поля загружены — форма чистая; bind до загрузки, чтобы ловить ввод
        bindDirtyWatch('botGeneral', ['botNick', 'botToken', 'botProxy']);
        bindDirtyWatch('botAI', ['botAIProvider', 'botAIModel', 'botAIModelSelect', 'botAIVisionMode', 'botAIVisionModel', 'botAIVisionModelSelect', 'botAIKey']);
        clearDirty('botGeneral'); clearDirty('botAI');
        const st = _botStatuses[id] || {};
        const active = st.connected || bot.enabled;
        $('botStatusDot').className = 'bot-card-status ' + (active ? 'online' : 'offline');
        $('botStatusText').textContent = st.connected ? t('label.online') : (bot.enabled ? t('status.bot_enabled_not_connected') : t('label.offline'));
        const btn = $('botToggleBtn');
        btn.textContent = active ? t('btn.stop') : t('btn.start');
        btn.className = 'btn btn-sm ' + (active ? 'btn-danger' : 'btn-primary');
    } catch (e) { console.error('loadBotGeneral', e); }
}

async function saveBotGeneral() {
    if (!_currentBotId) return;
    const data = { nickname: $('botNick').value.trim(), proxy: $('botProxy').value.trim() };
    const token = $('botToken').value.trim();
    if (token) data.token = token;
    try {
        await api(`/api/accounts/${_currentBotId}`, jopts('PUT', data));
        toast(t('toast.general_saved'), 'success');
        clearDirty('botGeneral'); // P8-C13
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function saveBotAIOverride() {
    if (!_currentBotId) return;
    // Q15b (E3): у custom:*-провайдера модели читаются из дропдауна,
    // у остальных — из свободного ввода.
    const named = _botNamedProvider();
    const chatModel = named
        ? ($('botAIModelSelect')?.value || '')
        : $('botAIModel').value.trim();
    const data = {
        ai_provider_override: $('botAIProvider').value,
        ai_chat_model_override: chatModel,
    };
    const mode = $('botAIVisionMode')?.value || 'shared';
    const vm = mode === 'own'
        ? (named ? ($('botAIVisionModelSelect')?.value || '') : $('botAIVisionModel').value.trim())
        : '';
    // Q15a: режим «своя» с пустым полем = общая (пустая строка) — контракт тот же.
    // Пользователь всегда может очистить vision override и вернуться к «общей».
    data.ai_vision_model_override = mode === 'own' ? vm : '';
    // Q15c (E4): резерв «локальная Ollama» — состояние тумблера
    data.ai_local_fallback = $('botAILocalFallback')?.classList.contains('active') || false;
    // Q15d (E5): smart-routing per-бот (выключен = наследовать глобальный)
    data.ai_smart_routing = {
        enabled: $('botAISmartRouting')?.classList.contains('active') || false,
        threshold: parseInt($('botAISRThreshold')?.value, 10) || 600,
        simple_provider: $('botAISimpleProvider')?.value.trim() || '',
        simple_model: $('botAISimpleModel')?.value.trim() || '',
        complex_provider: $('botAIComplexProvider')?.value.trim() || '',
        complex_model: $('botAIComplexModel')?.value.trim() || '',
    };
    const key = $('botAIKey').value.trim();
    if (key) {
        if (data.ai_provider_override === 'openrouter') data.openrouter_api_key_override = key;
        else data.ai_api_key_override = key;
    }
    try {
        await api(`/api/accounts/${_currentBotId}/ai-override`, jopts('PUT', data));
        toast(t('toast.ai_override_saved'), 'success');
        clearDirty('botAI'); // P8-C13
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

// Q16 F5: автозапись replay-сессий при старте — настройка бота.
// Значение показывается по умолчанию из глобального fallback (inherited), явное
// сохранение делает его собственным для бота.
async function loadBotReplayAuto() {
    const el = $('botReplayAutoRecord');
    if (!el || !_currentBotId) return;
    try {
        const res = await api(`/api/accounts/${_currentBotId}/replay-settings`);
        el.classList.toggle('active', !!res.auto_record);
        el.setAttribute('aria-checked', String(!!res.auto_record));
    } catch (e) { console.warn('replay auto', e); }
}

async function saveBotReplayAuto() {
    if (!_currentBotId) return;
    const on = $('botReplayAutoRecord')?.classList.contains('active') || false;
    try {
        await api(`/api/accounts/${_currentBotId}/replay-settings`, jopts('PUT', { auto_record: on }));
        toast(t('msg.saved'), 'success');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

// ── P8-C3: отношение к стримеру — UI в карточке бота (вкладка «Роль») ──
// Данные per-bot × канал (streamer_attitude); канал — из подключённых бота.
const _SA_ATTITUDE_KEYS = {
    adore: 'streamer.attitude_adore',
    friendly: 'streamer.attitude_friendly',
    neutral: 'streamer.attitude_neutral',
    watching: 'streamer.attitude_watching',
    // P8-C3: негативные тона
    irritated: 'streamer.attitude_irritated',
    intolerable: 'streamer.attitude_intolerable',
    dismissive: 'streamer.attitude_dismissive',
};

async function loadBotAttitude() {
    const box = $('botAttitudeBox');
    if (!box || !_currentBotId) return;
    try {
        await loadBotChannels(_currentBotId);
        const chans = (_channelsCache || []).map(c => (c.channel_name || '').replace(/^#/, ''));
        const res = await api(`/api/streamer-attitude`);
        const mine = (res.items || []).find(it => it.account_id === _currentBotId);
        const _sel = (ch) => {
            const cur = (mine && mine._per_channel && mine._per_channel[ch]) || 'neutral';
            return `<select class="input sa-select" style="max-width:210px" onchange="saveBotAttitude('${ch}', this.value)">
                ${Object.entries(_SA_ATTITUDE_KEYS).map(([a, key]) => `<option value="${a}" ${a === cur ? 'selected' : ''}>${esc(t(key))}</option>`).join('')}
            </select>`;
        };
        box.innerHTML = chans.length ? chans.map(ch => `
            <div class="flex items-center gap-2 text-sm mb-1">
                <span style="min-width:170px">#${esc(ch)}</span>
                ${_sel(ch)}
            </div>`).join('') : `<div class="text-muted text-sm">${esc(t('streamer.channel_required'))}</div>`;
    } catch (e) { console.error('loadBotAttitude', e); }
}

async function saveBotAttitude(channel, attitude) {
    if (!_currentBotId) return;
    try {
        await api(`/api/streamer-attitude/${_currentBotId}`, jopts('PUT', { channel: channel || '', attitude }));
        toast(t('streamer.attitude_saved'), 'success');
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

// ── Tab: Persona ────────────────────────────────────
const PERSONA_FIELDS = [
    { key: 'humor_level', label: 'persona.f.humor', def: 50 },
    { key: 'sarcasm_level', label: 'persona.f.sarcasm', def: 30 },
    { key: 'darkness_level', label: 'persona.f.darkness', def: 10 },
    { key: 'crudeness_level', label: 'persona.f.crudeness', def: 0 },
    { key: 'adult_humor', label: 'persona.f.adult', def: 0 },
    { key: 'seriousness', label: 'persona.f.seriousness', def: 50 },
    { key: 'emotionality', label: 'persona.f.emotionality', def: 50 },
    { key: 'contact_level', label: 'persona.f.contact', def: 50 },
    { key: 'chat_affinity', label: 'persona.f.chat_affinity', def: 50 },
];

const PERSONA_TOGGLES = [
    { key: 'observation_only', label: 'persona.t.observation_only' },
    { key: 'asterisk_emotes', label: 'persona.t.asterisk_emotes' },
    { key: 'auto_adjust_contact', label: 'persona.t.auto_adjust_contact' },
    { key: 'humor_enabled', label: 'persona.t.dynamic_humor' },
    { key: 'sarcasm_enabled', label: 'persona.t.dynamic_sarcasm' },
    { key: 'adult_enabled', label: 'persona.t.dynamic_adult' },
];

function personaVal(key, def) {
    const v = _personaCache ? _personaCache[key] : undefined;
    return (v === undefined || v === null) ? def : v;
}

async function loadBotPersona(id) {
    try {
        const data = await api(`/api/accounts/${id}/persona`);
        _personaCache = data.persona || {};
        renderPersona();
        refreshPersonaCustomPresets();
        // attitude («Отношение к стримеру») теперь в Характерe; use_persona в шапке
        loadAnalyzerSettings(id);
        if (typeof loadBotAttitude === 'function') loadBotAttitude();
        const affinity = await api(`/api/accounts/${id}/affinity`);
        if ($('affinityContact')) $('affinityContact').value = affinity.contact_level ?? 50;
        if ($('affinityChat')) $('affinityChat').value = affinity.chat_affinity ?? 50;
        setToggle('affinityAuto', !!affinity.auto_adjust);
        loadConflictSettings(id);
    } catch (e) { console.error('loadBotPersona', e); }
}

// ── PLAN §9l: провокации в спорах (тумблер + интенсивность) ──
async function loadConflictSettings(id) {
    const acc = id ?? _currentBotId;
    if (!acc || !$('conflictEnabled')) return;
    try {
        const cfg = await api(`/api/accounts/${acc}/analyzer`);
        setToggle('conflictEnabled', !!cfg.conflict_provocation_enabled);
        if ($('conflictIntensity')) {
            $('conflictIntensity').value = cfg.conflict_provocation_intensity ?? 40;
            const v = document.getElementById('conflictIntensityVal');
            if (v) v.textContent = String(cfg.conflict_provocation_intensity ?? 40);
        }
    } catch (e) { console.warn('conflict settings', e); }
}

async function saveConflictSettings() {
    if (!_currentBotId) return;
    try {
        const intensity = Math.max(0, Math.min(100, parseInt($('conflictIntensity')?.value || '40', 10) || 0));
        await api(`/api/accounts/${_currentBotId}/analyzer`, jopts('PUT', {
            conflict_provocation_enabled: toggleChecked('conflictEnabled'),
            conflict_provocation_intensity: intensity,
        }));
        toast(t('msg.saved'), 'success');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function importPersonaFromChat() {
    const nickname = $('mimicNickname')?.value.trim();
    const streamer = $('mimicStreamer')?.value.trim();
    if (!nickname || !_currentBotId) { toast(t('toast.nickname_required'), 'error'); return; }
    try {
        toast(t('toast.analyzing_style'), 'info');
        const result = await api(`/api/persona/import?account_id=${_currentBotId}`, jopts('POST', { nickname, streamer }));
        if (!result.success) throw new Error(result.error || t('dynamic.style_failed'));
        _personaCache = { ...(_personaCache || {}), ...(result.persona || {}) };
        renderPersona();
        toast(t('toast.style_imported', {detail: nickname}), 'success');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

// ── H (REWORK_PLAN): импорт истории чата ФАЙЛОМ ─────
function _parseHistoryFile(text) {
    const trimmed = (text || '').trim();
    if (trimmed.startsWith('[') || trimmed.startsWith('{')) {
        try {
            const data = JSON.parse(trimmed);
            const arr = Array.isArray(data) ? data : (data.messages || data.history || []);
            return arr.map(m => typeof m === 'string' ? m : { author: m.author || m.username || m.user || '', text: m.text || m.message || '' })
                .filter(m => m.author && m.text);
        } catch (e) { return []; }
    }
    return trimmed.split('\n')
        .map(ln => {
            const i = ln.indexOf(': ');
            return i > 0 ? { author: ln.slice(0, i).trim(), text: ln.slice(i + 2).trim() } : null;
        })
        .filter(Boolean);
}

async function _readHistoryFile(event) {
    const file = event.target?.files?.[0];
    if (!file) return null;
    const text = await file.text();
    const parsed = _parseHistoryFile(text);
    event.target.value = '';
    if (!parsed.length) { toast(t('history.parse_error'), 'error'); return null; }
    toast(t('history.loaded', {detail: parsed.length}), 'info');
    return parsed;
}

async function importChatHistory(event, mode) {
    if (!_currentBotId) return;
    const messages = await _readHistoryFile(event);
    if (!messages) return;
    const user = $('mimicNickname')?.value.trim() || '';
    try {
        toast(t('role.c.building'), 'info');
        const res = await api(`/api/accounts/${_currentBotId}/mimic/import-history`, jopts('POST', { messages, user }));
        if (!res.ok) throw new Error(res.error || 'error');
        const ta = $('roleF_mimic_profile');
        if (ta) ta.value = res.profile;
        const modeEl = $('roleF_mimic_mode');
        if (modeEl) modeEl.value = 'profile';
        toast(t('role.c.built'), 'success');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function importHistoryDescribeCharacter() {
    if (!_currentBotId) return;
    const input = $('historyImportFile');
    if (!input) return;
    const messages = await _readHistoryFile({ target: input });
    if (!messages) return;
    const user = $('mimicNickname')?.value.trim() || '';
    try {
        toast(t('toast.analyzing_style'), 'info');
        const res = await api(`/api/accounts/${_currentBotId}/persona/from-history`, jopts('POST', { messages, user }));
        if (!res.ok) {
            const reasonKey = { no_json: 'gen.reason_no_json', json_parse_error: 'gen.reason_no_json', not_enough_history: 'history.too_short' }[res.error] || res.error;
            throw new Error(reasonKey.startsWith('gen.') || reasonKey === 'history.too_short' ? t(reasonKey) : reasonKey);
        }
        const p = res.proposal || {};
        if (p.name !== undefined) $('personaName').value = p.name || '';
        if (p.age !== undefined) $('personaAge').value = p.age || '';
        if (p.location !== undefined) $('personaLocation').value = p.location || '';
        if (p.occupation !== undefined) $('personaOccupation').value = p.occupation || '';
        if (p.personality) $('personaPersonality').value = (p.personality || []).join(', ');
        if (p.favorite_games) $('personaGames').value = (p.favorite_games || []).join(', ');
        if (p.catchphrases) $('personaCatchphrases').value = (p.catchphrases || []).join(', ');
        if (p.background !== undefined) $('personaBackground').value = p.background || '';
        _personaCache = { ...(_personaCache || {}), ...p };
        renderPersona();
        toast(t('history.proposal_done', {detail: res.messages_used}), 'success');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function saveAffinity() {
    if (!_currentBotId) return;
    try {
        await api(`/api/accounts/${_currentBotId}/affinity`, jopts('PUT', {
            contact_level: parseInt($('affinityContact').value),
            chat_affinity: parseInt($('affinityChat').value),
            auto_adjust: toggleChecked('affinityAuto'),
        }));
        toast(t('toast.affinity_saved'), 'success');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

function renderPersona() {
    const p = _personaCache || {};
    // Sliders
    $('personaSliders').innerHTML = PERSONA_FIELDS.map(f => `
        <div class="persona-slider">
            <label><span data-i18n="${esc(f.label)}">${esc(t(f.label))}</span><span class="val">${personaVal(f.key, f.def)}</span>
                <button type="button" class="slider-ai-toggle ${personaVal(f.key.replace('_level', '_enabled'), true) ? 'active' : ''}"
                        ${panelI18nAttrs('dynamic.ai_value')} onclick="this.classList.toggle('active')">AI</button>
            </label>
            <input type="range" min="0" max="100" value="${personaVal(f.key, f.def)}" data-i18n-aria-label="${esc(f.label)}" aria-label="${esc(t(f.label))}"
                   oninput="this.closest('.persona-slider').querySelector('.val').textContent=this.value">
        </div>
    `).join('');
    // Toggles
    $('personaToggles').innerHTML = PERSONA_TOGGLES.map(tg => `
        <div class="toggle-row">
            <span class="toggle-label" data-i18n="${esc(tg.label)}">${esc(t(tg.label))}</span>
            <div class="toggle ${personaVal(tg.key, false) ? 'active' : ''}" data-i18n-aria-label="${esc(tg.label)}" aria-label="${esc(t(tg.label))}"
                 onclick="this.classList.toggle('active')"></div>
        </div>
    `).join('');
    // Bio
    $('personaName').value = p.name || '';
    $('personaAge').value = p.age || '';
    const knownGenders = ['', 'м', 'ж', 'трансгендер', 'бі', 'інше'];
    $('personaGender').value = knownGenders.includes(p.gender) ? (p.gender || '') : 'інше';
    toggleCustomGender();
    if ($('personaGenderCustom')) $('personaGenderCustom').value = p.gender_custom || '';
    $('personaLocation').value = p.location || '';
    $('personaOccupation').value = p.occupation || '';
    $('personaPersonality').value = (p.personality || []).join(', ');
    $('personaGames').value = (p.favorite_games || []).join(', ');
    $('personaCatchphrases').value = (p.catchphrases || []).join(', ');
    $('personaBackground').value = p.background || '';
}

function collectPersona() {
    const data = _personaCache ? JSON.parse(JSON.stringify(_personaCache)) : {};
    PERSONA_FIELDS.forEach(f => {
        const sliders = $('personaSliders').querySelectorAll('input[type="range"]');
        const idx = PERSONA_FIELDS.indexOf(f);
        if (sliders[idx]) data[f.key] = parseInt(sliders[idx].value);
        const toggle = $('personaSliders').children[idx]?.querySelector('.slider-ai-toggle');
        const enabledKeys = {
            humor_level: 'humor_enabled', sarcasm_level: 'sarcasm_enabled', darkness_level: 'darkness_enabled',
            crudeness_level: 'crudeness_enabled', adult_humor: 'adult_enabled', seriousness: 'seriousness_enabled',
            emotionality: 'emotionality_enabled',
        };
        const enabledKey = enabledKeys[f.key];
        if (toggle) data[enabledKey] = toggle.classList.contains('active');
    });
    const toggles = $('personaToggles').querySelectorAll('.toggle');
    PERSONA_TOGGLES.forEach((tg, i) => { if (toggles[i]) data[tg.key] = toggles[i].classList.contains('active'); });
    data.name = $('personaName').value.trim();
    data.age = parseInt($('personaAge').value) || 0;
    data.gender = $('personaGender').value === 'інше' ? ($('personaGenderCustom').value.trim() || 'інше') : $('personaGender').value;
    data.gender_custom = $('personaGenderCustom')?.value.trim() || '';
    data.location = $('personaLocation').value.trim();
    data.occupation = $('personaOccupation').value.trim();
    data.personality = splitList($('personaPersonality').value);
    data.favorite_games = splitList($('personaGames').value);
    data.catchphrases = splitList($('personaCatchphrases').value);
    data.background = $('personaBackground').value.trim();
    return data;
}

function toggleCustomGender() {
    const custom = $('personaGenderCustom');
    if (custom) custom.classList.toggle('hidden', $('personaGender')?.value !== 'інше');
}

function splitList(s) {
    return (s || '').split(',').map(x => x.trim()).filter(Boolean);
}

async function exportCharacter() {
    if (!_currentBotId) return;
    try {
        const result = await api(`/api/accounts/${_currentBotId}/export`);
        const blob = new Blob([JSON.stringify(result.export, null, 2)], {type: 'application/json'});
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = `${_currentBot?.nickname || 'bot'}-persona.json`;
        link.click();
        URL.revokeObjectURL(link.href);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

function importCharacterFile(event) {
    const file = event.target.files?.[0];
    if (!file || !_currentBotId) return;
    const reader = new FileReader();
    reader.onload = async () => {
        try {
            const data = JSON.parse(reader.result);
            const result = await api(`/api/accounts/${_currentBotId}/export/import`, jopts('POST', {export: data}));
            if (!result.ok) throw new Error(result.error || t('dynamic.persona_import_failed'));
            await loadBotPersona(_currentBotId);
            toast(t('toast.character_imported'), 'success');
        } catch (e) { toast(t('toast.import_failed', {detail: e.message}), 'error'); }
    };
    reader.readAsText(file);
    event.target.value = '';
}

function copyWidgetUrl(path) {
    navigator.clipboard.writeText(location.origin + widgetOutputUrl(path)).then(() => toast(t('toast.copied'), 'success'));
}

const ONBOARDING_STEPS = ['ai', 'twitch', 'tts', 'bot', 'channel', 'obs'];
let _onboardingStep = 0;
let _onboardingBotId = null;

function dismissOnboarding() {
    localStorage.setItem('onboardingDismissed', '1');
    api('/api/onboarding', jopts('PUT', { dismissed: true })).catch(() => {});
    hideModal('onboardingOverlay');
}

function onboardingInput(id, label, type = 'text', placeholder = '') {
    return `<div class="form-group"><label>${esc(label)}</label><input id="onboard-${id}" class="input" type="${type}" placeholder="${esc(placeholder)}"></div>`;
}

function renderOnboardingStep() {
    const step = ONBOARDING_STEPS[_onboardingStep];
    const titles = Object.fromEntries(ONBOARDING_STEPS.map(step => [step, t(`onboarding.${step}_title`)]));
    const descriptions = Object.fromEntries(ONBOARDING_STEPS.map(step => [step, t(`onboarding.${step}_description`)]));
    let body = `<h4>${titles[step]}</h4><p>${descriptions[step]}</p>`;
    if (step === 'ai') body += `<div class="form-group"><label>${t('onboarding.label_ai_provider')}</label><select id="onboard-ai-provider" class="input"><option value="openrouter">OpenRouter</option><option value="ollama">Ollama</option><option value="gemini">Gemini</option><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option></select></div>${onboardingInput('ai-model', t('onboarding.label_model'), 'text', 'openai/gpt-4o-mini')}${onboardingInput('ai-key', t('onboarding.label_api_key'), 'password', '...')}${onboardingInput('ai-host', t('onboarding.label_base_url'), 'text', 'http://localhost:11434')}`;
    if (step === 'twitch') body += onboardingInput('twitch-id', t('onboarding.label_twitch_id'), 'text', 'Client ID') + onboardingInput('twitch-secret', t('onboarding.label_twitch_secret'), 'password', '...');
    if (step === 'tts') body += `<div class="form-group"><label>${t('onboarding.label_tts_provider')}</label><select id="onboard-tts-provider" class="input"><option value="web_speech">Web Speech</option><option value="piper">Piper</option><option value="elevenlabs">ElevenLabs</option></select></div>${onboardingInput('tts-voice', t('onboarding.label_voice'), 'text', 'ru-RU')}${onboardingInput('tts-key', t('onboarding.label_tts_key'), 'password', '...')}`;
    if (step === 'bot') body += onboardingInput('bot-name', t('onboarding.label_bot_name'), 'text', 'my_ai_bot') + onboardingInput('bot-token', t('onboarding.label_bot_token'), 'password', 'oauth:...');
    if (step === 'channel') body += onboardingInput('channel', t('onboarding.label_channel'), 'text', 'your_channel');
    if (step === 'obs') body += `<div class="card"><p class="text-sm">${t('onboarding.widget_url')}</p><code id="onboard-obs-url">${location.origin}/obs/tts</code><div class="flex gap-2 mt-3"><button class="btn btn-secondary" onclick="navigator.clipboard.writeText(location.origin+'/obs/tts');toast(t('toast.copied'),'success')">${t('onboarding.copy_url')}</button><button class="btn btn-secondary" onclick="window.open('/obs/tts','_blank')">${t('onboarding.preview')}</button></div></div>`;
    $('onboardingStep').innerHTML = body;
    $('onboardingProgress').innerHTML = ONBOARDING_STEPS.map((_, i) => `<span class="${i < _onboardingStep ? 'done' : ''} ${i === _onboardingStep ? 'active' : ''}"></span>`).join('');
    $('onboardingBack').classList.toggle('hidden', _onboardingStep === 0);
    $('onboardingSkip').classList.toggle('hidden', step === 'obs');
    $('onboardingNext').textContent = step === 'obs' ? t('onboarding.done') : t('onboarding.next');
}

function onboardingValue(id) { return $('onboard-' + id)?.value.trim() || ''; }

async function onboardingNextStep() {
    const step = ONBOARDING_STEPS[_onboardingStep];
    $('onboardingError').classList.add('hidden');
    try {
        if (step === 'ai') {
            const provider = $('onboard-ai-provider').value;
            const data = { provider };
            const fields = AI_PROVIDER_FIELDS[provider] || [];
            const model = onboardingValue('ai-model');
            const key = onboardingValue('ai-key');
            const host = onboardingValue('ai-host');
            const modelField = fields.find(f => f.key.endsWith('_chat'));
            const keyField = fields.find(f => f.key.endsWith('_key'));
            if (model && modelField) data[modelField.key] = model;
            if (key && keyField) data[keyField.key] = key;
            if (host && provider === 'ollama') data.ollama_host = host;
            await api('/api/ai/config', jopts('PUT', data));
        } else if (step === 'twitch') {
            const data = {}; const id = onboardingValue('twitch-id'); const secret = onboardingValue('twitch-secret');
            if (id) data.client_id = id; if (secret) data.client_secret = secret;
            if (Object.keys(data).length) await api('/api/settings/twitch-credentials', jopts('PUT', data));
        } else if (step === 'tts') {
            const ttsData = { provider: $('onboard-tts-provider').value, voice: onboardingValue('tts-voice'), speed: 1, volume: 1 };
            const ttsKey = onboardingValue('tts-key'); if (ttsKey) ttsData.elevenlabs_api_key = ttsKey;
            await api('/api/tts/config', jopts('PUT', ttsData));
        } else if (step === 'bot') {
            const name = onboardingValue('bot-name'); const token = onboardingValue('bot-token');
            if (!name || !token) throw new Error(t('error.bot_credentials'));
            const bot = await api('/api/accounts', jopts('POST', { nickname: name, token }));
            _onboardingBotId = bot.id;
            await loadBotsList();
        } else if (step === 'channel') {
            const channel = onboardingValue('channel');
            if (!_onboardingBotId) _onboardingBotId = _allBots[0]?.id;
            if (!channel || !_onboardingBotId) throw new Error(t('error.channel_and_bot'));
            await api(`/api/accounts/${_onboardingBotId}/channels`, jopts('POST', { channel_name: channel }));
        } else {
            await api('/api/onboarding', jopts('PUT', { completed: true, dismissed: true }));
            localStorage.setItem('onboardingDismissed', '1');
            hideModal('onboardingOverlay');
            toast(t('onboarding.complete'), 'success');
            return;
        }
        _onboardingStep++;
        renderOnboardingStep();
    } catch (e) { $('onboardingError').textContent = e.message; $('onboardingError').classList.remove('hidden'); }
}

function onboardingBackStep() { if (_onboardingStep > 0) { _onboardingStep--; $('onboardingError').classList.add('hidden'); renderOnboardingStep(); } }
function onboardingSkipStep() { _onboardingStep++; $('onboardingError').classList.add('hidden'); renderOnboardingStep(); }

async function maybeShowOnboarding() {
    if (_allBots.length || localStorage.getItem('onboardingDismissed')) return;
    try { const state = await api('/api/onboarding'); if (state.completed || state.dismissed) return; } catch (e) { /* local fallback */ }
    _onboardingStep = 0; _onboardingBotId = null; renderOnboardingStep(); showModal('onboardingOverlay');
}

function collectEmotionIntensity() {
    const sliders = $('personaSliders').querySelectorAll('input[type="range"]');
    // emotion_intensity is at index 6 after our additions
    const idx = PERSONA_FIELDS.findIndex(f => f.key === 'emotion_intensity');
    if (idx >= 0 && sliders[idx]) return parseInt(sliders[idx].value);
    return 50;
}


async function saveBotPersona() {
    if (!_currentBotId) return;
    try {
        const res = await api(`/api/accounts/${_currentBotId}/persona`, jopts('PUT', collectPersona()));
        _personaCache = res.persona || collectPersona();
        toast(t('toast.persona_saved'), 'success');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function applyPersonaPreset() {
    const presetId = $('personaPreset').value;
    if (!presetId || !_currentBotId) return;
    try {
        const res = await api(`/api/accounts/${_currentBotId}/persona/apply-preset`, jopts('POST', { preset_id: presetId }));
        if (res.error) { toast(res.error, 'error'); return; }
        _personaCache = res.persona || _personaCache;
        renderPersona();
        toast(t('toast.persona_preset_applied'), 'success');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function generatePersonaAI() {
    if (!_currentBotId) return;
    const description = prompt(t('prompt.persona'));
    if (!description) return;
    toast(t('toast.ai_generating_persona'), 'info');
    try {
        const res = await api(`/api/accounts/${_currentBotId}/generate-persona`, jopts('POST', { description }));
        if (res.error) { toast(res.error, 'error'); return; }
        _personaCache = res.persona || _personaCache;
        renderPersona();
        toast(t('toast.persona_generated'), 'success');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

// ── Tab: Behavior (анализатор; пресеты поведения удалены — остаются только пресеты Характера) ────

async function loadAnalyzerSettings(id) {
    try {
        const s = await api(`/api/accounts/${id}/analyzer`);
        const setT = (elId, val) => {
            const el = $(elId);
            if (el) el.classList.toggle('active', !!val);
        };
        // B3: use_persona живёт в шапке Характера; auto_chat/silent/cooldown — только Быстрые настройки (Обзор)
        setT('personaUsePersona', s.use_persona);
        // AI-BUDGET AB-1: переключатели внимания (источники платного AI)
        setT('attnVision', s.attention_vision !== false);
        setT('attnHearing', s.attention_hearing !== false);
        setT('attnChatAi', s.attention_chat_ai !== false);
        if ($('analyzerSystemPrompt')) $('analyzerSystemPrompt').value = s.system_prompt || '';
        if ($('analyzerResponseLength')) $('analyzerResponseLength').value = s.response_length || 'short';
        // PROMPT-BASE PB-3: декор исходящих сообщений
        if ($('outEmojiPrefix')) $('outEmojiPrefix').value = s.outgoing_emoji_prefix || '';
        if ($('outEmojiSuffix')) $('outEmojiSuffix').value = s.outgoing_emoji_suffix || '';
    } catch (e) { console.error('loadAnalyzerSettings', e); }
}

// B3: тумблер «Использовать характер бота» в шапке Характера
async function savePersonaUse() {
    if (!_currentBotId) return;
    try {
        await api(`/api/accounts/${_currentBotId}/analyzer`, jopts('PUT', { use_persona: $('personaUsePersona').classList.contains('active') }));
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function loadCustomPresets() {
    if (!_currentBotId || !$('customPresetsList')) return;
    try {
        const data = await api(`/api/accounts/${_currentBotId}/behavior-presets`);
        $('customPresetsList').innerHTML = (data.presets || []).map(p => `<button class="btn btn-secondary btn-sm" onclick="applyCustomPreset(${p.id})">${esc(p.name)}</button><button class="btn btn-sm btn-danger" onclick="deleteCustomPreset(${p.id})">✕</button>`).join('');
    } catch (e) { console.warn('custom presets', e); }
}

async function saveCustomPreset() {
    const name = $('customPresetName')?.value.trim();
    if (!name || !_currentBotId) { toast(t('toast.preset_name_required'), 'error'); return; }
    const persona = collectPersona();
    try {
        await api(`/api/accounts/${_currentBotId}/behavior-presets`, jopts('POST', { name, values: persona }));
        $('customPresetName').value = ''; loadCustomPresets();
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function applyCustomPreset(id) {
    const data = await api(`/api/accounts/${_currentBotId}/behavior-presets`);
    const preset = (data.presets || []).find(p => p.id === id);
    if (!preset) return;
    _personaCache = {...(_personaCache || {}), ...(preset.values || {})}; renderPersona();
}

async function deleteCustomPreset(id) {
    if (!confirm(t('confirm.delete_named', {name: t('bot.preset')}))) return;
    await api(`/api/behavior-presets/${id}`, { method: 'DELETE' }); loadCustomPresets();
}

// ── Tab: Channels ───────────────────────────────────
async function loadBotChannels(id) {
    try {
        const data = await api(`/api/accounts/${id}/channels`);
        _channelsCache = Array.isArray(data) ? data : (data.channels || []);
        renderChannels();
        // overrides
        const ov = await api(`/api/accounts/${id}/channel-overrides`);
        _overridesCache = ov.overrides || [];
        renderOverrides();
        // селект каналів для override
        const sel = $('overrideChannelSelect');
        const used = new Set(_overridesCache.map(o => o.channel));
        sel.innerHTML = `<option value="" data-i18n="select.channel">${esc(t('select.channel'))}</option>` +
            _channelsCache.filter(c => !used.has(c.channel_name))
                .map(c => `<option value="${esc(c.channel_name)}">#${esc(c.channel_name)}</option>`).join('');
    } catch (e) { console.error('loadBotChannels', e); }
}

let _expandedChannels = new Set();
let _channelInfoCache = {};

function renderChannels() {
    const el = $('channelsList');
    if (!el) return;
    if (!_channelsCache.length) {
        el.innerHTML = `<div class="text-muted text-sm">${esc(t('empty.no_channels'))}</div>`;
        return;
    }
    const connected = new Set((_botStatuses[_currentBotId]?.channels || []).map(ch => ch.toLowerCase().replace(/^#/, '')));
    el.innerHTML = _channelsCache.map(c => {
        const channel = (c.channel_name || '').toLowerCase().replace(/^#/, '');
        const isConnected = connected.has(channel);
        const open = _expandedChannels.has(channel);
        const info = _channelInfoCache[channel];
        return `
        <div class="card p-0 channel-card" style="overflow:hidden">
            <div class="flex justify-between items-center p-3 cursor-pointer" onclick="toggleChannelCard('${esc(channel)}')">
                <span class="font-semibold">#${esc(c.channel_name)} ${open ? '▾' : '▸'}</span>
                <div class="flex gap-2" onclick="event.stopPropagation()">
                    <span class="badge ${isConnected ? 'on' : 'off'}">${isConnected ? '🟢 ' + t('label.connected') : '🔴 ' + t('label.disconnected')}</span>
                    ${isConnected ? `<button class="btn btn-sm btn-secondary" onclick="leaveChannel(${c.account_id}, '${esc(c.channel_name)}')">↪ ${t('btn.leave')}</button>` : `<button class="btn btn-sm btn-secondary" onclick="joinChannel(${c.account_id}, '${esc(c.channel_name)}')">↩ ${t('btn.connect')}</button>`}
                    <button class="btn btn-sm btn-danger" onclick="removeChannel(${c.id})">✕</button>
                </div>
            </div>
            ${open ? `
            <div class="p-3" style="border-top:1px solid var(--border-light);background:var(--bg-active)">
                <div id="chStats-${esc(channel)}" class="text-sm text-muted mb-2">${esc(t('label.loading'))}</div>
                <div id="chInfo-${esc(channel)}" class="text-sm mb-3">${esc(t('channels.info_loading'))}</div>
                <div class="flex gap-2 flex-wrap">
                    <button class="btn btn-sm btn-secondary" onclick="loadChannelInfo('${esc(channel)}')">ℹ️ ${t('channels.info_btn')}</button>
                    <button class="btn btn-sm btn-secondary" onclick="jumpToChannelOverrides('${esc(channel)}')">🎛 ${t('channels.overrides_btn')}</button>
                </div>
            </div>` : ''}
        </div>
    `;
    }).join('');
    // Подгружаем статистику открытых карточек
    _expandedChannels.forEach(ch => loadChannelStats(ch));
}

function toggleChannelCard(channel) {
    if (_expandedChannels.has(channel)) _expandedChannels.delete(channel);
    else _expandedChannels.add(channel);
    renderChannels();
}

async function loadChannelStats(channel) {
    try {
        const s = await api(`/api/accounts/${_currentBotId}/channels/${encodeURIComponent(channel)}/stats`);
        const el = $(`chStats-${channel}`);
        if (!el) return;
        const last = s.last_message_at ? fmtTime(String(s.last_message_at).replace(' ', 'T') + 'Z') : '';
        el.innerHTML = `💬 ${esc(tPlural('messages', s.messages || 0))}${last ? ` · ${esc(t('channels.last_message'))}: ${esc(last)}` : ''}`;
    } catch (e) {
        const el = $(`chStats-${channel}`);
        if (el) el.textContent = '';
    }
}

async function loadChannelInfo(channel) {
    const box = $(`chInfo-${channel}`);
    if (!box) return;
    box.innerHTML = `<span class="text-muted">${esc(t('channels.info_loading'))}</span>`;
    try {
        const info = await api(`/api/channels/${encodeURIComponent(channel)}/info?account_id=${_currentBotId}`);
        if (!info.ok) {
            // §9.1: явно показываем, что без TWITCH_CLIENT_ID/SECRET инфа недоступна
            box.innerHTML = `<span class="text-warning">⚠ ${esc(info.error || t('channels.info_failed'))}</span>`;
            return;
        }
        box.innerHTML = `
            <div><strong>${esc(info.title || '')}</strong></div>
            <div class="text-muted">🎮 ${esc(info.game_name || info.game || '—')} · 👥 ${esc(String(info.viewer_count ?? 0))}</div>`;
    } catch (e) {
        box.innerHTML = `<span class="text-error">${esc(t('channels.info_failed'))} — ${esc(e.message)}</span>`;
    }
}

function jumpToChannelOverrides(channel) {
    // Быстрый переход к per-channel overrides этого канала (§9.1)
    const sel = $('overrideChannelSelect');
    showBotTab('channels');
    if (sel) {
        // Канал может уже иметь override — тогда просто выбираем его в селекте
        const opt = [...sel.options].find(o => o.value === channel);
        if (opt) { sel.value = channel; sel.dispatchEvent(new Event('change')); }
    }
    $('overrideChannelSelect')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

async function addChannel() {
    const name = $('newChannel').value.trim().replace('#', '');
    if (!name || !_currentBotId) return;
    try {
        await api(`/api/accounts/${_currentBotId}/channels`, jopts('POST', { channel_name: name }));
        $('newChannel').value = '';
        await loadBotChannels(_currentBotId);
        toast(t('toast.channel_added_for', {detail: name}), 'success');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function removeChannel(channelId) {
    try {
        let result = await api(`/api/channels/${channelId}`, { method: 'DELETE' });
        if (result.ok === false && result.code === 'channel_has_dependencies') {
            const tables = Object.keys(result.counts || {}).join(', ');
            if (!window.confirm(t('channels.delete_confirm_data', {total: result.total}) + ' ' + tables)) return;
            result = await api(`/api/channels/${channelId}?force=true`, { method: 'DELETE' });
        }
        if (result.ok === false) { toast(t('toast.channel_delete_failed'), 'error'); return; }
        await loadBotChannels(_currentBotId);
        toast(t('toast.channel_deleted'), 'success');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

// ── BC-1/BC-2: смена канала и привязка канала к боту прямо с карточки ──
function openBotChannelModal(accountId, nickname) {
    const previous = document.getElementById('botChannelModal');
    if (previous) previous.remove();
    const overlay = document.createElement('div');
    overlay.id = 'botChannelModal';
    overlay.className = 'modal-backdrop';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:999;display:flex;align-items:center;justify-content:center';
    overlay.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="botChannelTitle" style="background:var(--bg-card);border:1px solid var(--border);border-radius:12px;padding:18px;width:min(520px,94vw);max-height:88vh;overflow:auto">
        <div class="flex items-center justify-between mb-3">
            <b id="botChannelTitle">${esc(t('bots.change_channel'))} · ${esc(nickname || '')}</b>
            <button class="btn btn-sm btn-secondary" onclick="closePanelDialog('botChannelModal')" data-i18n-aria-label="btn.close" aria-label="${esc(t('btn.close'))}">✕</button>
        </div>
        <p class="text-sm text-muted mb-2" data-i18n="bots.change_channel_hint">${esc(t('bots.change_channel_hint'))}</p>
        <div id="botChannelCurrent" class="space-y-1 mb-3"><span class="text-muted text-sm">${esc(t('label.loading'))}</span></div>
        <div class="flex gap-2 mb-3">
            <select id="botChannelAddSelect" class="input"></select>
            <button class="btn btn-primary btn-sm" onclick="botChannelAttach(${accountId})" data-i18n="channels.add">${esc(t('channels.add'))}</button>
        </div>
        <div class="flex gap-2">
            <input id="botChannelNewName" class="input" placeholder="channel_name" aria-label="${esc(t('channels.add'))}">
            <button class="btn btn-secondary btn-sm" onclick="botChannelCreate(${accountId})">${esc(t('bots.change_channel_new'))}</button>
        </div>
        <div id="botChannelError" class="text-error text-sm mt-2" aria-live="polite"></div>
    </div>`;
    overlay.addEventListener('click', e => { if (e.target === overlay) closePanelDialog(overlay); });
    document.body.appendChild(overlay);
    openPanelDialog(overlay, {removeOnClose: true});
    botChannelLoad(accountId);
}

async function botChannelLoad(accountId) {
    const list = $('botChannelCurrent');
    if (!list) return;
    try {
        const [channels, _] = await Promise.all([
            api(`/api/accounts/${accountId}/channels`),
            _allBots.length ? Promise.resolve(_allBots) : loadBotsList(),
        ]);
        const rows = Array.isArray(channels) ? channels : (channels.channels || []);
        const known = new Set(rows.map(row => String(row.channel_name).toLowerCase()));
        const others = (_allBots || []).flatMap(bot =>
            botDisplayChannels(bot, _botStatuses[bot.id] || {}).map(ch => ({channel: ch, account_id: bot.id})));
        const select = $('botChannelAddSelect');
        if (select) {
            const options = others.filter(item => item.account_id !== accountId && !known.has(String(item.channel).toLowerCase()));
            select.innerHTML = options.map(item => `<option value="${esc(item.channel)}" data-account="${esc(item.account_id)}">#${esc(item.channel)}</option>`).join('');
            if (!options.length) select.innerHTML = `<option value="">${esc(t('bots.change_channel_none'))}</option>`;
        }
        list.innerHTML = rows.length ? rows.map(row => `<div class="flex items-center justify-between">
            <span>#${esc(row.channel_name)} ${row.enabled ? '' : `<span class="text-muted text-xs">${esc(t('health.disabled'))}</span>`}</span>
            <div class="flex gap-2">
                <button class="btn btn-sm btn-secondary" onclick="botChannelRename(${row.account_id}, '${esc(row.channel_name)}')">${esc(t('channels.rename'))}</button>
                <button class="btn btn-sm btn-danger" onclick="botChannelDetach(${accountId}, ${row.id})">${esc(t('channels.delete'))}</button>
            </div>
        </div>`).join('') : `<span class="text-muted text-sm">${esc(t('label.no_channels'))}</span>`;
    } catch (e) { $('botChannelError').textContent = e.message; }
}

async function botChannelError(code) {
    const box = $('botChannelError');
    if (box) box.textContent = code ? t(`toast.error_detail`, {detail: code}) : '';
}

async function botChannelCreate(accountId) {
    const name = $('botChannelNewName').value.trim().replace(/^#/, '');
    if (!name) return;
    try {
        const result = await api(`/api/accounts/${accountId}/channels`, jopts('POST', {channel_name: name}));
        if (result.ok === false) { await botChannelError(t('toast.channel_add_failed')); return; }
        $('botChannelNewName').value = '';
        await botChannelLoad(accountId);
        await loadBotsList();
        toast(t('toast.channel_added_for', {detail: name}), 'success');
    } catch (e) { await botChannelError(e.message); }
}

async function botChannelAttach(accountId) {
    const select = $('botChannelAddSelect');
    const option = select?.selectedOptions?.[0];
    if (!option || !option.value) return;
    const sourceAccount = Number(option.dataset.account || 0);
    try {
        if (sourceAccount && sourceAccount !== accountId) {
            const rows = await api(`/api/accounts/${sourceAccount}/channels`);
            const list = Array.isArray(rows) ? rows : (rows.channels || []);
            const binding = list.find(row => String(row.channel_name).toLowerCase() === option.value.toLowerCase());
            if (!binding) { await botChannelError(t('channels.deps_failed')); return; }
            const moved = await api(`/api/channels/${binding.id}`, jopts('PATCH', {account_id: accountId}));
            if (moved.ok === false) { await botChannelError(moved.code); return; }
        } else {
            await api(`/api/accounts/${accountId}/channels`, jopts('POST', {channel_name: option.value}));
        }
        await botChannelLoad(accountId);
        await loadBotsList();
        toast(t('toast.channel_added_for', {detail: option.value}), 'success');
    } catch (e) { await botChannelError(e.message); }
}

async function botChannelRename(accountId, channel) {
    const current = String(channel).replace(/^#/, '');
    const next = window.prompt(t('channels.rename_prompt'), current);
    if (next === null) return;
    const target = next.trim().replace(/^#/, '');
    if (!target || target === current) return;
    try {
        const rows = await api(`/api/accounts/${accountId}/channels`);
        const list = Array.isArray(rows) ? rows : (rows.channels || []);
        const binding = list.find(row => String(row.channel_name).toLowerCase() === current.toLowerCase());
        if (!binding) { await botChannelError(t('toast.channel_rename_failed')); return; }
        let result = await api(`/api/channels/${binding.id}`, jopts('PATCH', {channel_name: target}));
        if (result.ok === false && result.code === 'channel_data_conflict') {
            if (!window.confirm(t('channels.rename_conflict', {tables: (result.tables || []).join(', ')}))) return;
            result = await api(`/api/channels/${binding.id}`, jopts('PATCH', {channel_name: target, force: true}));
        }
        if (result.ok === false) { await botChannelError(t('toast.channel_rename_failed')); return; }
        await botChannelLoad(accountId);
        await loadBotsList();
        toast(t('toast.channel_renamed', {detail: target}), 'success');
    } catch (e) { await botChannelError(e.message); }
}

async function botChannelDetach(accountId, bindingId) {
    try {
        let result = await api(`/api/channels/${bindingId}`, {method: 'DELETE'});
        if (result.ok === false && result.code === 'channel_has_dependencies') {
            if (!window.confirm(t('channels.delete_confirm_data', {total: result.total}))) return;
            result = await api(`/api/channels/${bindingId}?force=true`, {method: 'DELETE'});
        }
        if (result.ok === false) { await botChannelError(t('toast.channel_delete_failed')); return; }
        await botChannelLoad(accountId);
        await loadBotsList();
        toast(t('toast.channel_deleted'), 'success');
    } catch (e) { await botChannelError(e.message); }
}

async function joinChannel(accountId, channel) {
    try {
        await api(`/api/accounts/${accountId}/join`, jopts('POST', { channel }));
        await loadBotChannels(_currentBotId);
        toast(t('toast.channel_joined', {detail: channel}), 'success');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function leaveChannel(accountId, channel) {
    try {
        await api(`/api/accounts/${accountId}/leave`, jopts('POST', { channel }));
        await loadBotChannels(_currentBotId);
        toast(t('toast.channel_left', {detail: channel}), 'success');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

// ── Channel overrides (per-channel поведінка) ───────
const OVERRIDE_FIELDS = [
    { key: 'humor_level', label: 'persona.f.humor' },
    { key: 'sarcasm_level', label: 'persona.f.sarcasm' },
    { key: 'adult_humor', label: 'persona.f.adult' },
    { key: 'contact_level', label: 'persona.f.contact' },
];

function addOverrideRow() {
    const channel = $('overrideChannelSelect').value;
    if (!channel) { toast(t('toast.select_channel'), 'error'); return; }
    _overridesCache.push({ channel, enabled: true, overrides: {} });
    renderOverrides();
}

function renderOverrides() {
    const el = $('channelOverridesList');
    if (!el) return;
    if (!_overridesCache.length) {
        el.innerHTML = `<div class="text-muted text-sm">${esc(t('overrides.empty'))}</div>`;
        return;
    }
    el.innerHTML = _overridesCache.map((o, i) => {
        const ov = o.overrides || {};
        const sliders = OVERRIDE_FIELDS.map(f => `
            <div class="persona-slider" style="margin-bottom:0">
                <label>${esc(t(f.label))}<span class="val">${ov[f.key] ?? '—'}</span></label>
                <input type="range" min="0" max="100" value="${ov[f.key] ?? 50}"
                       oninput="this.previousElementSibling.querySelector('.val').textContent=this.value">
            </div>
        `).join('');
        return `
        <div class="override-row">
            <div class="override-head">
                <span class="channel-name">#${esc(o.channel)}</span>
                <div class="flex gap-2 items-center">
                    <span class="text-xs text-muted">${esc(t('overrides.enabled'))}</span>
                    <div class="toggle ${o.enabled ? 'active' : ''}" onclick="this.classList.toggle('active')"></div>
                    <button class="btn btn-sm btn-danger" onclick="deleteOverride('${esc(o.channel)}')">✕</button>
                </div>
            </div>
            <div class="override-sliders">${sliders}</div>
            <div class="toggle-row mt-3">
                <span class="toggle-label">${esc(t('overrides.observation_only'))}</span>
                <div class="toggle ${ov.observation_only ? 'active' : ''}" onclick="this.classList.toggle('active')"></div>
            </div>
            <div class="mt-3 pt-2" style="border-top:1px solid var(--border-light)">
                <div class="text-xs font-semibold text-muted mb-2">${esc(t('overrides.activity_title'))}</div>
                <div class="flex gap-3 flex-wrap items-center text-sm">
                    <label class="flex items-center gap-1"><div class="toggle ${ov.auto_chat ? 'active' : ''}" data-ov-toggle="auto_chat" role="switch" aria-checked="${!!ov.auto_chat}" tabindex="0" onclick="uiToggle(this)"></div> ${esc(t('overrides.auto_chat'))}</label>
                    <label class="flex items-center gap-1"><div class="toggle ${ov.silent_mode ? 'active' : ''}" data-ov-toggle="silent_mode" role="switch" aria-checked="${!!ov.silent_mode}" tabindex="0" onclick="uiToggle(this)"></div> ${esc(t('overrides.silent'))}</label>
                    <label class="flex items-center gap-1"><div class="toggle ${ov.tts_mute ? 'active' : ''}" data-ov-toggle="tts_mute" role="switch" aria-checked="${!!ov.tts_mute}" tabindex="0" onclick="uiToggle(this)"></div> ${esc(t('overrides.tts_mute'))}</label>
                </div>
                <div class="flex gap-3 flex-wrap items-center text-sm mt-2">
                    <label class="flex items-center gap-1"><div class="toggle ${ov.context_source_chat ? 'active' : ''}" data-ov-toggle="context_source_chat" role="switch" aria-checked="${!!ov.context_source_chat}" tabindex="0" onclick="uiToggle(this)"></div> ${esc(t('overrides.ctx_chat'))}</label>
                    <label class="flex items-center gap-1"><div class="toggle ${ov.context_source_stream ? 'active' : ''}" data-ov-toggle="context_source_stream" role="switch" aria-checked="${!!ov.context_source_stream}" tabindex="0" onclick="uiToggle(this)"></div> ${esc(t('overrides.ctx_stream'))}</label>
                    <label class="flex items-center gap-1"><div class="toggle ${ov.context_source_streamer ? 'active' : ''}" data-ov-toggle="context_source_streamer" role="switch" aria-checked="${!!ov.context_source_streamer}" tabindex="0" onclick="uiToggle(this)"></div> ${esc(t('overrides.ctx_streamer'))}</label>
                </div>
                <label class="flex items-center gap-2 text-sm mt-2">${esc(t('overrides.cooldown'))}
                    <input type="number" data-ov-number="cooldown" class="input" style="width:90px" min="0" max="3600" value="${ov.cooldown ?? ''}" placeholder="—">
                </label>
            </div>
            <button class="btn btn-primary btn-sm mt-3" onclick="saveOverride(${i})">${esc(t('overrides.save_channel', {channel: o.channel}))}</button>
        </div>`;
    }).join('');
}

async function saveOverride(idx) {
    const o = _overridesCache[idx];
    if (!o || !_currentBotId) return;
    const row = $('channelOverridesList').children[idx];
    const sliders = row.querySelectorAll('.override-sliders input[type="range"]');
    const overrides = {};
    OVERRIDE_FIELDS.forEach((f, i) => { overrides[f.key] = parseInt(sliders[i].value); });
    const obsToggle = row.querySelector('.toggle-row .toggle');
    overrides.observation_only = obsToggle.classList.contains('active');
    // PLAN §2.1: активность/контекст/TTS per-channel
    row.querySelectorAll('[data-ov-toggle]').forEach(el => { overrides[el.dataset.ovToggle] = el.classList.contains('active'); });
    const cdEl = row.querySelector('[data-ov-number="cooldown"]');
    if (cdEl && cdEl.value !== '') overrides.cooldown = Math.max(0, Math.min(3600, parseInt(cdEl.value, 10) || 0));
    // enabled toggle у head
    const enabledToggle = row.querySelector('.override-head .toggle');
    try {
        await api(`/api/accounts/${_currentBotId}/channel-overrides`, jopts('PUT', {
            channel: o.channel,
            enabled: enabledToggle.classList.contains('active'),
            overrides,
        }));
        o.overrides = overrides;
        toast(t('toast.overrides_saved', {detail: o.channel}), 'success');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function deleteOverride(channel) {
    if (!_currentBotId) return;
    if (!confirm(t('confirm.delete_named', {name: `overrides #${channel}`}))) return;
    try {
        await api(`/api/accounts/${_currentBotId}/channel-overrides/${encodeURIComponent(channel)}`, { method: 'DELETE' });
        _overridesCache = _overridesCache.filter(o => o.channel !== channel);
        renderOverrides();
        toast(t('toast.overrides_deleted'), 'success');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

// ── Tab: TTS ────────────────────────────────────────
async function loadBotTTS(id) {
    loadTTSRoutingMap(); // Q16 F3: карта озвучки переехала из Настроек в карточку бота
    try {
        const data = await api(`/api/accounts/${id}/tts-config`);
        const cfg = data.config || {};
        const toggle = $('botTTSToggle');
        toggle.classList.toggle('active', !!cfg.enabled);
        $('botTTSProvider').value = cfg.provider || '';
        $('botTTSEmotion').value = cfg.emotion_preset || 'neutral';
        $('botTTSVolume').value = cfg.volume ?? 1.0;
        $('botTTSVolumeVal').textContent = Math.round((cfg.volume ?? 1.0) * 100) + '%';
        $('botTTSSpeed').value = cfg.speed ?? 1.0;
        $('botTTSSpeedVal').textContent = (cfg.speed ?? 1.0).toFixed(1) + 'x';
        // §6: голоса выбранного провайдера (пресеты + локальные клоны),
        // неизвестное значение — в «Расширенный режим» (ручной ввод).
        await fillBotTTSVoiceOptions(cfg.provider || '', cfg.voice || '');
        // §7.1 §12.1: статус последнего синтеза
        try {
            const last = await api(`/api/accounts/${id}/tts-last`);
            const el = $('botTTSLastStatus');
            if (el) {
                if (!last.has) el.textContent = t('tts.last_none');
                else el.textContent = t('tts.last_status', {
                    time: (last.created_at || '').substring(0, 19),
                    msg: last.message,
                });
            }
        } catch (e) { /* статус не критичен */ }
    } catch (e) { /* конфігу може не бути — дефолти вже в HTML */ }
}

// §6 PLAN_FEEDBACK_2908: селект голоса per-bot — реальные голоса провайдера
async function fillBotTTSVoiceOptions(provider, selectedVoice) {
    const select = $('botTTSVoice');
    if (!select || select.tagName !== 'SELECT') return;
    let voices = [];
    try { voices = (await api('/api/tts/voices')).voices || []; } catch (e) { /* пресетов нет */ }
    let localModels = [];
    try { localModels = (await api('/api/voice-clone/models')).models || []; } catch (e) { /* клонов нет */ }
    let clones = [];
    try { clones = (await api('/api/voice-clones')).clones || []; } catch (e) { /* таблица клонов недоступна */ }
    const opts = [`<option value="">${esc(t('option.voice_default'))}</option>`];
    if (provider === 'piper') {
        for (const v of voices.filter(x => x.provider === 'piper'))
            opts.push(`<option value="${esc(v.voice_id)}">${esc(v.label || v.voice_id)} (piper)</option>`);
    } else if (provider === 'elevenlabs') {
        for (const v of voices.filter(x => x.provider === 'elevenlabs'))
            opts.push(`<option value="${esc(v.voice_id)}">${esc(v.label || v.voice_id)} (elevenlabs)</option>`);
    }
    // §12.2: голосовые клоны (таблица voice_clones) — xtts/f5tts/elevenlabs
    for (const c of clones)
        opts.push(`<option value="${esc(c.name)}">🧬 ${esc(c.name)} (${esc(c.provider || 'clone')})</option>`);
    // web_speech: голос выбирается браузером (по языку) — пресетов нет
    for (const m of localModels)
        opts.push(`<option value="${esc(m.name)}">${esc(m.name)} (clone)</option>`);
    opts.push(`<option value="__manual__">${esc(t('option.voice_manual'))}</option>`);
    select.innerHTML = opts.join('');
    const manual = $('botTTSVoiceManual');
    if (selectedVoice && [...select.options].some(o => o.value === selectedVoice)) {
        select.value = selectedVoice;
        if (manual) manual.classList.add('hidden');
    } else if (selectedVoice) {
        select.value = '__manual__';
        if (manual) { manual.classList.remove('hidden'); manual.value = selectedVoice; }
    } else if (manual) {
        manual.classList.add('hidden');
    }
}

async function deleteClone(id) {
    if (!id || !confirm(t('confirm.delete_named', {name: t('bot.voice_clone')}))) return;
    try {
        await api(`/api/voice-clones/${id}`, { method: 'DELETE' });
        loadBotVoiceClones(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function saveBotTTS() {
    if (!_currentBotId) return;
    const voiceSel = $('botTTSVoice');
    const voice = (voiceSel?.value === '__manual__')
        ? ($('botTTSVoiceManual')?.value.trim() || '')
        : (voiceSel?.value.trim() || '');
    const data = {
        enabled: $('botTTSToggle').classList.contains('active') ? 1 : 0,
        provider: $('botTTSProvider').value,
        voice,
        emotion_preset: $('botTTSEmotion').value,
        volume: parseFloat($('botTTSVolume').value),
        speed: parseFloat($('botTTSSpeed').value),
    };
    try {
        await api(`/api/accounts/${_currentBotId}/tts-config`, jopts('PUT', data));
        toast(t('toast.tts_saved'), 'success');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function previewBotTTS(customText = null) {
    if (!_currentBotId) return;
    const provider = $('botTTSProvider') ? $('botTTSProvider').value : '';
    const voiceSelect = $('botTTSVoice');
    const voice = (voiceSelect && voiceSelect.value === '__manual__')
        ? ($('botTTSVoiceManual') ? $('botTTSVoiceManual').value : '')
        : (voiceSelect ? voiceSelect.value : '');
    const emotion = $('botTTSEmotion') ? $('botTTSEmotion').value : 'neutral';
    const volume = $('botTTSVolume') ? parseFloat($('botTTSVolume').value) : 1.0;
    const speed = $('botTTSSpeed') ? parseFloat($('botTTSSpeed').value) : 1.0;
    const text = customText || ($('botTTSTestText') ? $('botTTSTestText').value : '') || "Привет! Это проверка голоса бота.";

    try {
        toast("🔊 Синтезирую голос...", "info");
        const res = await api(`/api/accounts/${_currentBotId}/tts-preview`, jopts('POST', {
            provider,
            voice,
            emotion,
            volume,
            speed,
            text,
        }));
        if (!res.ok) {
            toast(res.error || "Ошибка предпрослушивания", "error");
            return;
        }
        if (res.mode === 'web_speech') {
            if ('speechSynthesis' in window) {
                window.speechSynthesis.cancel();
                const utter = new SpeechSynthesisUtterance(res.text);
                if (res.voice) {
                    const voices = window.speechSynthesis.getVoices();
                    const match = voices.find(v => v.name === res.voice || v.voiceURI === res.voice);
                    if (match) utter.voice = match;
                }
                utter.rate = res.rate || 1.0;
                utter.pitch = res.pitch || 1.0;
                utter.volume = res.volume !== undefined ? res.volume : 1.0;
                window.speechSynthesis.speak(utter);
                toast("Озвучено через Web Speech", "success");
            } else {
                toast("Web Speech не поддерживается браузером", "warning");
            }
        } else if (res.audio_b64) {
            const snd = new Audio(`data:${res.mime || 'audio/wav'};base64,${res.audio_b64}`);
            snd.volume = res.volume !== undefined ? res.volume : 1.0;
            await snd.play();
            toast("Воспроизведение голоса бота", "success");
        }
    } catch (e) {
        toast(t('toast.error_detail', {detail: e.message}), 'error');
    }
}

function testBotTTS() {
    previewBotTTS();
}

async function quickPreviewBotVoice(botId, nickname) {
    try {
        toast(`🔊 Загрузка голоса ${nickname || 'бота'}...`, 'info');
        const res = await api(`/api/accounts/${botId}/tts-preview`, jopts('POST', {
            text: `Привет! Я ${nickname || 'бот'}, проверяю озвучку голоса.`,
        }));
        if (!res.ok) {
            toast(res.error || 'Ошибка предпрослушивания', 'error');
            return;
        }
        if (res.mode === 'web_speech') {
            if ('speechSynthesis' in window) {
                window.speechSynthesis.cancel();
                const utter = new SpeechSynthesisUtterance(res.text);
                if (res.voice) {
                    const voices = window.speechSynthesis.getVoices();
                    const match = voices.find(v => v.name === res.voice || v.voiceURI === res.voice);
                    if (match) utter.voice = match;
                }
                utter.rate = res.rate || 1.0;
                utter.pitch = res.pitch || 1.0;
                utter.volume = res.volume !== undefined ? res.volume : 1.0;
                window.speechSynthesis.speak(utter);
                toast(`Озвучено (${nickname}) через Web Speech`, 'success');
            } else {
                toast('Web Speech не поддерживается браузером', 'warning');
            }
        } else if (res.audio_b64) {
            const snd = new Audio(`data:${res.mime || 'audio/wav'};base64,${res.audio_b64}`);
            snd.volume = res.volume !== undefined ? res.volume : 1.0;
            await snd.play();
            toast(`Воспроизведение голоса ${nickname}`, 'success');
        }
    } catch (e) {
        toast(t('toast.error_detail', { detail: e.message }), 'error');
    }
}

async function testBotTTSObs() {
    if (!_currentBotId) return;
    const provider = $('botTTSProvider') ? $('botTTSProvider').value : '';
    const voiceSelect = $('botTTSVoice');
    const voice = (voiceSelect && voiceSelect.value === '__manual__')
        ? ($('botTTSVoiceManual') ? $('botTTSVoiceManual').value : '')
        : (voiceSelect ? voiceSelect.value : '');
    const emotion = $('botTTSEmotion') ? $('botTTSEmotion').value : 'neutral';
    const volume = $('botTTSVolume') ? parseFloat($('botTTSVolume').value) : 1.0;
    const speed = $('botTTSSpeed') ? parseFloat($('botTTSSpeed').value) : 1.0;
    const text = ($('botTTSTestText') ? $('botTTSTestText').value : '') || "Тест звука в OBS: проверка голоса бота.";

    try {
        toast("📡 Отправляю в OBS оверлей...", "info");
        const res = await api(`/api/accounts/${_currentBotId}/tts-test-obs`, jopts('POST', {
            provider,
            voice,
            emotion,
            volume,
            speed,
            text,
        }));
        if (res.ok) {
            toast("📡 Тестовая реплика отправлена в OBS!", "success");
        } else {
            toast(res.error || "Ошибка отправки в OBS", "error");
        }
    } catch (e) {
        toast(t('toast.error_detail', { detail: e.message }), 'error');
    }
}

function openBotTTSWidget() {
    window.open(location.origin + '/obs/tts?rate=1.0&volume=' + ($('botTTSVolume') ? $('botTTSVolume').value : '1.0'), '_blank');
    toast(t('toast.tts_opened'), 'info');
}


// ── Tab: Attention ──────────────────────────────────
async function loadBotAttention(id) {
    try {
        const data = await api(`/api/accounts/${id}/attention-config`);
        const cfg = data.config || {};
        $('botAttentionMode').value = cfg.attention_mode || 'everyone';
        $('botIgnoreNoise').classList.toggle('active', cfg.ignore_noise === undefined ? true : !!cfg.ignore_noise);
        $('botBatchWindow').value = cfg.batch_window_sec ?? 5;
        $('botBatchMax').value = cfg.batch_max_size ?? 5;
        $('botMinToReply').value = cfg.min_messages_to_respond ?? 2;
        $('botCooldownReply').value = cfg.cooldown_after_reply_sec ?? 30;
        $('botMaxPerMin').value = cfg.max_replies_per_minute ?? 3;
        // §7.1 §9: ответы стримеру/упоминаниям/озвучка
        setToggle('botReplyMentions', cfg.reply_to_mentions === undefined ? true : !!cfg.reply_to_mentions);
        $('botInterruptGuard').value = cfg.dont_interrupt_streamer_sec ?? 0;
        $('botTTSPercent').value = cfg.tts_reply_percent ?? 100;
        // О6: ключевые слова
        setToggle('botReplyKeywords', !!cfg.reply_to_keywords);
        $('botReplyKeywordsList').value = cfg.reply_keywords || '';
    } catch (e) { /* дефолти в HTML */ }
}

async function saveBotAttention() {
    if (!_currentBotId) return;
    const data = {
        attention_mode: $('botAttentionMode').value,
        ignore_noise: $('botIgnoreNoise').classList.contains('active') ? 1 : 0,
        batch_window_sec: parseFloat($('botBatchWindow').value),
        batch_max_size: parseInt($('botBatchMax').value),
        min_messages_to_respond: parseInt($('botMinToReply').value),
        cooldown_after_reply_sec: parseFloat($('botCooldownReply').value),
        max_replies_per_minute: parseInt($('botMaxPerMin').value),
        reply_to_mentions: $('botReplyMentions').classList.contains('active') ? 1 : 0,
        dont_interrupt_streamer_sec: Math.max(0, parseInt($('botInterruptGuard').value, 10) || 0),
        tts_reply_percent: Math.max(0, Math.min(100, parseInt($('botTTSPercent').value, 10))),
        reply_to_keywords: $('botReplyKeywords').classList.contains('active') ? 1 : 0,
        reply_keywords: $('botReplyKeywordsList')?.value.trim() || '',
    };
    try {
        await api(`/api/accounts/${_currentBotId}/attention-config`, jopts('PUT', data));
        toast(t('toast.attention_saved'), 'success');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

// ── Tab: Logs ───────────────────────────────────────
const LOG_ICONS = { chat: '💬', ai: '🧠', tts: '🔊', trigger: '⚡', event: '🔔', system: '⚙️' };

function renderLogLine(l) {
    const icon = LOG_ICONS[l.category] || '📝';
    // Фидбек 29.08: чей лог — ник бота, а без бота = событие самой панели.
    const who = l.nickname
        ? `<span class="badge log-who">${esc(l.nickname)}</span>`
        : (l.account_id
            ? `<span class="badge log-who">#${esc(String(l.account_id))}</span>`
            : `<span class="badge log-who log-who-panel">${esc(t('logs.panel'))}</span>`);
    return `<div class="log-line level-${esc(l.level || 'info')}">
        <span class="log-time">${l.created_at ? fmtTime(l.created_at.replace(' ', 'T')) : ''}</span>
        <span>${icon}</span>
        ${who}
        <span>[${esc(l.level || '')}] ${esc(l.message)}</span>
    </div>`;
}

async function loadBotLogs() {
    if (!_currentBotId) return;
    const bot = _allBots.find(b => b.id === _currentBotId);
    const nick = bot?.nickname || '';
    if (!nick) return;
    const el = $('botLogsContent');
    if (!el) return;
    try {
        el.innerHTML = `<div class="text-muted text-sm p-3">${panelI18n('label.loading')}</div>`;
        const data = await api(`/api/logs/${encodeURIComponent(nick)}/tail?lines=200`);
        if (!data.content || !data.content.trim()) {
            el.innerHTML = `<div class="text-muted text-sm p-3">${panelI18n('status.no_logs')}</div>`;
            return;
        }
        const lines = data.content.split('\n').filter(Boolean);
        el.innerHTML = lines.map(line => {
            const isWarn = line.includes('[WARNING]');
            const isError = line.includes('[ERROR]');
            const cls = isError ? 'text-error' : isWarn ? 'text-warn' : '';
            return `<div class="log-line ${cls}" style="font-size:11px;line-height:1.4;padding:1px 4px;border-bottom:1px solid var(--border-light)">${esc(line)}</div>`;
        }).join('');
        el.scrollTop = el.scrollHeight;
    } catch (e) {
        el.innerHTML = `<div class="text-error text-sm p-3">${panelI18n('label.error')}: ${esc(e.message)}</div>`;
    }
}

function prependBotLogLive(msg) {
    // Live-лог у вкладці «Логи» поточного бота
    const el = $('botLogsContent');
    if (!el || !_currentBotId || msg.account_id !== _currentBotId) return;
    const line = document.createElement('div');
    line.className = 'log-line level-info';
    const icon = LOG_ICONS[msg.channel === 'tts' ? 'tts' : (msg.event || '').includes('tts') ? 'tts' : 'ai'] || '🧠';
    line.innerHTML = `<span class="log-time">${new Date().toLocaleTimeString()}</span><span>${icon}</span><span>${esc(msg.event)}: ${esc(msg.detail)}</span>`;
    el.prepend(line);
    while (el.children.length > 300) el.lastChild.remove();
}

async function downloadBotLogs() {
    if (!_currentBotId) return;
    const bot = _allBots.find(b => b.id === _currentBotId);
    const nick = bot?.nickname || '';
    if (!nick) return;
    try {
        window.open(`/api/logs/${encodeURIComponent(nick)}/file`, '_blank');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function clearBotLogs() {
    if (!_currentBotId) return;
    if (!confirm(t('confirm.clear_logs'))) return;
    try {
        await api(`/api/accounts/${_currentBotId}/bot-logs`, { method: 'DELETE' });
        loadBotLogs();
        toast(t('toast.logs_cleared'), 'success');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

// ── Bot Files (OPS_PLAN §1: per-bot папки) ──────────
let _botFilesOpenPath = null;

function _fmtFileSize(n) {
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    return (n / 1024 / 1024).toFixed(1) + ' MB';
}

async function loadBotFiles(id) {
    const botId = id || _currentBotId;
    if (!botId) return;
    const listEl = $('botFilesList');
    try {
        const res = await api(`/api/accounts/${botId}/files`);
        if (!res.ok) { listEl.innerHTML = `<div class="text-muted p-2">${esc(res.error || 'error')}</div>`; return; }
        $('botFilesDir').textContent = res.bot_dir ? ('data/bots/' + res.bot_dir) : '';
        _botFilesOpenPath = null;
        $('botFilesEditorPath').textContent = '';
        $('botFilesEditor').value = '';
        $('botFilesEditor').disabled = true;
        $('botFilesSaveBtn').classList.add('hidden');
        $('botFilesDeleteBtn').classList.add('hidden');
        if (!res.files.length) {
            listEl.innerHTML = `<div class="text-muted p-2">${t('botfiles.empty')}</div>`;
            return;
        }
        listEl.innerHTML = res.files.map(f => {
            const cls = f.editable ? '' : 'locked';
            return `<button class="${cls}" data-path="${esc(f.path)}" onclick="${f.editable ? `openBotFile('${esc(f.path).replace(/'/g, "\\'")}')` : 'return false'}" title="${esc(f.path)}">${esc(f.path)}<span class="size">${_fmtFileSize(f.size)}</span></button>`;
        }).join('');
    } catch (e) {
        listEl.innerHTML = `<div class="text-muted p-2">${esc(e.message)}</div>`;
    }
}

async function openBotFile(path) {
    if (!_currentBotId || !path) return;
    try {
        const res = await api(`/api/accounts/${_currentBotId}/files/${path.split('/').map(encodeURIComponent).join('/')}`);
        if (!res.ok) { toast(t('toast.error_detail', {detail: res.error || 'error'}), 'error'); return; }
        _botFilesOpenPath = path;
        document.querySelectorAll('#botFilesList button').forEach(b => b.classList.toggle('active', b.dataset.path === path));
        $('botFilesEditorPath').textContent = path;
        $('botFilesEditor').value = res.content;
        $('botFilesEditor').disabled = false;
        $('botFilesSaveBtn').classList.remove('hidden');
        $('botFilesDeleteBtn').classList.remove('hidden');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function saveBotFile() {
    if (!_currentBotId || !_botFilesOpenPath) return;
    try {
        const res = await api(`/api/accounts/${_currentBotId}/files/${_botFilesOpenPath.split('/').map(encodeURIComponent).join('/')}`, {
            method: 'PUT',
            body: JSON.stringify({ content: $('botFilesEditor').value }),
            headers: { 'Content-Type': 'application/json' }
        });
        if (!res.ok) { toast(t('toast.error_detail', {detail: res.error || 'error'}), 'error'); return; }
        toast(t('toast.saved'), 'success');
        loadBotFiles();
        openBotFile(_botFilesOpenPath);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function deleteBotFile() {
    if (!_currentBotId || !_botFilesOpenPath) return;
    if (!confirm(t('confirm.delete_file'))) return;
    try {
        const res = await api(`/api/accounts/${_currentBotId}/files/${_botFilesOpenPath.split('/').map(encodeURIComponent).join('/')}`, { method: 'DELETE' });
        if (!res.ok) { toast(t('toast.error_detail', {detail: res.error || 'error'}), 'error'); return; }
        toast(t('toast.deleted'), 'success');
        loadBotFiles();
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

// ── Q39: массовые настройки — одна настройка сразу на все выбранные боты ──
const BULK_SETTINGS_FIELDS = ['observation_only', 'eventsub_enabled', 'enabled', 'bot_role'];

function _bulkSettingsValueControl(field) {
    if (field === 'bot_role') {
        const roles = ['chatter', 'lurker', 'moderator', 'voice_companion'];
        return `<select id="bulkSettingsValue" class="input">${roles.map(role => `<option value="${role}">${esc(typeof _roleMetaLabel === 'function' ? _roleMetaLabel(role) : role)}</option>`).join('')}</select>`;
    }
    return `<select id="bulkSettingsValue" class="input"><option value="true">${esc(t('bulk.settings_on'))}</option><option value="false">${esc(t('bulk.settings_off'))}</option></select>`;
}

function bulkSettingsFieldChanged() {
    const holder = $('bulkSettingsValueHolder');
    if (holder) holder.innerHTML = _bulkSettingsValueControl($('bulkSettingsField')?.value || BULK_SETTINGS_FIELDS[0]);
}

function openBulkAccountSettings() {
    if (!_selectedBots.size) return;
    const previous = document.getElementById('bulkAccountSettingsModal');
    if (previous) previous.remove();
    const overlay = document.createElement('div');
    overlay.id = 'bulkAccountSettingsModal';
    overlay.className = 'modal-backdrop';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:999;display:flex;align-items:center;justify-content:center';
    overlay.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="bulkSettingsTitle" style="background:var(--bg-card);border:1px solid var(--border);border-radius:12px;padding:18px;width:min(560px,94vw);max-height:88vh;overflow:auto">
        <div class="flex items-center justify-between mb-3">
            <b id="bulkSettingsTitle">${esc(t('bulk.settings'))} · ${esc(t('common.selected', {count: _selectedBots.size}))}</b>
            <button class="btn btn-sm btn-secondary" onclick="closeBulkAccountSettingsModal()" data-i18n-aria-label="btn.close" aria-label="${esc(t('btn.close'))}">✕</button>
        </div>
        <p class="text-sm text-muted mb-2">${esc(t('bulk.settings_hint'))}</p>
        <div class="flex gap-2 mb-3 flex-wrap items-end">
            <div class="form-group">
                <label class="text-xs" for="bulkSettingsField">${esc(t('bulk.settings_field'))}</label>
                <select id="bulkSettingsField" class="input" onchange="bulkSettingsFieldChanged()">
                    <option value="observation_only">${esc(t('bulk.settings_field_observation_only'))}</option>
                    <option value="eventsub_enabled">${esc(t('bulk.settings_field_eventsub_enabled'))}</option>
                    <option value="enabled">${esc(t('bulk.settings_field_enabled'))}</option>
                    <option value="bot_role">${esc(t('bulk.settings_field_bot_role'))}</option>
                </select>
            </div>
            <div class="form-group" id="bulkSettingsValueHolder">${_bulkSettingsValueControl('observation_only')}</div>
        </div>
        <button class="btn btn-primary btn-sm" id="bulkSettingsStart" onclick="applyBulkAccountSettings()">${esc(t('bulk.settings_apply'))}</button>
        <div id="bulkSettingsError" class="text-error text-sm mt-2" aria-live="polite"></div>
        <div id="bulkSettingsResults" class="mt-3"></div>
    </div>`;
    overlay.addEventListener('click', e => { if (e.target === overlay) closeBulkAccountSettingsModal(); });
    document.body.appendChild(overlay);
    openPanelDialog(overlay, {removeOnClose: true});
}

function closeBulkAccountSettingsModal() { closePanelDialog('bulkAccountSettingsModal'); }

async function applyBulkAccountSettings() {
    const field = $('bulkSettingsField')?.value || '';
    const raw = $('bulkSettingsValue')?.value;
    const value = field === 'bot_role' ? raw : raw === 'true';
    const errorBox = $('bulkSettingsError');
    if (errorBox) errorBox.textContent = '';
    $('bulkSettingsStart').disabled = true;
    try {
        const job = await api('/api/bulk/account-settings', jopts('POST', { ids: [..._selectedBots], field, value }));
        if (!job.ok) { if (errorBox) errorBox.textContent = t(`bulk.error.${job.error || 'bulk_failed'}`); return; }
        const rows = (job.results || []).map(item => `<tr>
            <td>${esc(item.nickname || `#${item.account_id}`)}</td>
            <td>${item.ok ? esc(t('bulk.value.changed')) : esc(t(`bulk.reason.${item.reason || 'change_failed'}`))}</td>
        </tr>`).join('');
        $('bulkSettingsResults').innerHTML = `<div class="text-sm mb-1">${esc(t('bulk.settings_done', {updated: job.updated, total: job.total}))}</div>
            <table class="table text-xs"><tbody>${rows}</tbody></table>`;
        await loadBotsList();
    } catch (e) { if (errorBox) errorBox.textContent = e.message; } finally { $('bulkSettingsStart').disabled = false; }
}

if (typeof LANGS !== 'undefined') Object.assign(LANGS.ru, {
    'bulk.settings': '⚙️ Массовые настройки', 'bulk.settings_hint': 'Одно значение применится сразу ко всем выбранным ботам.',
    'bulk.settings_field': 'Что менять', 'bulk.settings_field_observation_only': 'Только наблюдает',
    'bulk.settings_field_eventsub_enabled': 'EventSub', 'bulk.settings_field_enabled': 'Включён',
    'bulk.settings_field_bot_role': 'Роль', 'bulk.settings_on': 'Включить', 'bulk.settings_off': 'Выключить',
    'bulk.settings_apply': 'Применить', 'bulk.settings_done': 'Готово: {updated} из {total}.',
    'bulk.reason.not_found': 'бот не найден', 'bulk.reason.update_failed': 'не удалось применить', 'bulk.reason.unknown_role': 'неизвестная роль',
    'bulk.error.ids_required': 'Не выбрано ни одного бота', 'bulk.error.ids_invalid': 'Некорректный список ботов', 'bulk.error.invalid_value': 'Некорректное значение', 'bulk.error.unknown_field': 'Неизвестное поле настройки',
});
if (typeof LANGS !== 'undefined') Object.assign(LANGS.en, {
    'bulk.settings': '⚙️ Bulk settings', 'bulk.settings_hint': 'One value is applied to all the selected bots at once.',
    'bulk.settings_field': 'What to change', 'bulk.settings_field_observation_only': 'Observation only',
    'bulk.settings_field_eventsub_enabled': 'EventSub', 'bulk.settings_field_enabled': 'Enabled',
    'bulk.settings_field_bot_role': 'Role', 'bulk.settings_on': 'Turn on', 'bulk.settings_off': 'Turn off',
    'bulk.settings_apply': 'Apply', 'bulk.settings_done': 'Done: {updated} of {total}.',
    'bulk.reason.not_found': 'bot not found', 'bulk.reason.update_failed': 'could not apply', 'bulk.reason.unknown_role': 'unknown role',
    'bulk.error.ids_required': 'No bots selected', 'bulk.error.ids_invalid': 'Invalid bot list', 'bulk.error.invalid_value': 'Invalid value', 'bulk.error.unknown_field': 'Unknown setting field',
});
if (typeof LANGS !== 'undefined') Object.assign(LANGS.ua, {
    'bulk.settings': '⚙️ Масові налаштування', 'bulk.settings_hint': 'Одне значення застосується одразу до всіх вибраних ботів.',
    'bulk.settings_field': 'Що змінити', 'bulk.settings_field_observation_only': 'Лише спостерігає',
    'bulk.settings_field_eventsub_enabled': 'EventSub', 'bulk.settings_field_enabled': 'Увімкнений',
    'bulk.settings_field_bot_role': 'Роль', 'bulk.settings_on': 'Увімкнути', 'bulk.settings_off': 'Вимкнути',
    'bulk.settings_apply': 'Застосувати', 'bulk.settings_done': 'Готово: {updated} із {total}.',
    'bulk.reason.not_found': 'бота не знайдено', 'bulk.reason.update_failed': 'не вдалося застосувати', 'bulk.reason.unknown_role': 'невідома роль',
    'bulk.error.ids_required': 'Жодного бота не вибрано', 'bulk.error.ids_invalid': 'Некоректний список ботів', 'bulk.error.invalid_value': 'Некоректне значення', 'bulk.error.unknown_field': 'Невідоме поле налаштування',
});

// ── Tab: Sandbox (Песочница тестирования ответа) ──
const _SANDBOX_RANDOM_PROMPTS = [
    'Привет! Как настроение на стриме?',
    'Какой билд сейчас качаешь?',
    'За кого болеешь на турнире?',
    'Слушай, а какую игру посоветуешь поиграть на выходных?',
    'Бот, расскажи какую-нибудь забавную историю!',
    'Как думаешь, стример сегодня затащит катку?',
    'Сколько уже часов стрим идёт?',
    'Кто твой любимый персонаж?',
    'Что думаешь по поводу последнего обновления?',
    'Привет из чата! Кому передать привет?',
    'Объясни для новичка, что тут вообще происходит?',
    'Какая твоя любимая музыка для каток?',
    'Стример, дай совет по игре!',
    'Чат, вы за какую команду топите?',
];

function pickRandomSandboxPrompt() {
    const input = $('sandboxInput');
    if (!input) return;
    const current = (input.value || '').trim();
    let choices = _SANDBOX_RANDOM_PROMPTS;
    if (choices.length > 1 && current) {
        choices = choices.filter(p => p !== current);
    }
    const picked = choices[Math.floor(Math.random() * choices.length)];
    input.value = picked;
    input.focus();
}

function loadBotSandbox(id) {
    const sel = $('sandboxChannel');
    if (!sel) return;
    sel.innerHTML = '';
    const account = (_bots || []).find(b => Number(b.id) === Number(id));
    const channels = (account?.channels || []).filter(ch => ch.enabled !== false && ch.enabled !== 0);
    if (channels.length) {
        channels.forEach(ch => {
            const name = String(ch.channel_name || ch.name || ch).replace(/^#/, '');
            if (name) sel.insertAdjacentHTML('beforeend', `<option value="${esc(name)}">#${esc(name)}</option>`);
        });
    } else {
        sel.insertAdjacentHTML('beforeend', `<option value="testchannel">#testchannel (по умолчанию)</option>`);
    }
    updateSandboxMemoryBadge();
}

function clearSandboxChat() {
    const log = $('sandboxChatLog');
    if (log) {
        log.innerHTML = `<div class="text-center text-muted text-xs py-4" id="sandboxEmptyHint">Здесь появятся ответы бота. Введите вопрос или реплику в поле ниже.</div>`;
    }
}

async function sendSandboxMessage() {
    if (!_currentBotId) return;
    const input = $('sandboxInput');
    const text = (input?.value || '').trim();
    if (!text) return;

    const author = ($('sandboxAuthor')?.value || '').trim() || 'ТестовыйЗритель';
    const channel = $('sandboxChannel')?.value || '';
    const account = (_bots || []).find(b => Number(b.id) === Number(_currentBotId));
    const botNick = account?.nickname || 'Бот';

    const log = $('sandboxChatLog');
    $('sandboxEmptyHint')?.remove();

    // User message bubble
    const userRow = document.createElement('div');
    userRow.style.cssText = 'align-self:flex-end; max-width:80%; background:var(--primary-bg, #3b82f6); color:#fff; border-radius:12px 12px 2px 12px; padding:8px 12px; font-size:13px; margin-bottom:4px;';
    userRow.innerHTML = `<div style="font-size:10px; opacity:0.8; margin-bottom:2px;">👤 ${esc(author)} <span style="opacity:0.6;">(#${esc(channel)})</span></div><div>${esc(text)}</div>`;
    log.appendChild(userRow);
    log.scrollTop = log.scrollHeight;

    input.value = '';
    const sendBtn = $('sandboxSendBtn');
    if (sendBtn) {
        sendBtn.disabled = true;
        sendBtn.textContent = '⏳ Генерация...';
    }

    try {
        const res = await api(`/api/accounts/${_currentBotId}/sandbox-reply`, jopts('POST', {
            text,
            author,
            channel,
        }));

        if (!res.ok) {
            const errRow = document.createElement('div');
            errRow.style.cssText = 'align-self:flex-start; max-width:85%; background:rgba(239, 68, 68, 0.1); border:1px solid rgba(239,68,68,0.4); border-radius:12px; padding:8px 12px; font-size:12px; color:#ef4444;';
            errRow.innerHTML = `⚠️ Ошибка: ${esc(res.error || 'Сбой генерации')}`;
            log.appendChild(errRow);
            return;
        }

        const botRow = document.createElement('div');
        botRow.style.cssText = 'align-self:flex-start; max-width:85%; background:var(--card-bg, #242938); border:1px solid var(--border); border-radius:12px 12px 12px 2px; padding:10px 14px; font-size:13px; margin-bottom:4px;';

        let modBadge = '';
        if (res.moderation?.flagged) {
            modBadge = `<span class="badge badge-danger" style="font-size:10px;">⚠️ Модерация: ${esc(res.moderation.action || 'flagged')}</span>`;
        } else {
            modBadge = `<span class="badge badge-success" style="font-size:10px;">🛡️ Чисто</span>`;
        }

        const safeReply = res.reply || '(молчание)';
        botRow.innerHTML = `
            <div class="flex items-center gap-2 mb-1 flex-wrap">
                <b style="color:var(--accent, #a78bfa);">🤖 ${esc(botNick)}</b>
                <span class="badge badge-sm" style="font-size:10px;">⏱️ ${res.latency_ms} ms</span>
                <span class="badge badge-sm" style="font-size:10px;">⚙️ ${esc(res.provider || 'ai')}</span>
                ${modBadge}
                <button type="button" class="btn btn-ghost btn-xs text-muted" onclick="previewBotTTS(${JSON.stringify(safeReply)})" title="Предпрослушать озвучку ответа">🔊 Озвучить</button>
                <button type="button" class="btn btn-ghost btn-xs text-muted" onclick="saveSandboxStyleExample(this, ${JSON.stringify(safeReply)}, ${JSON.stringify(text)}, ${JSON.stringify(channel)})" title="Сохранить ответ в примеры стиля бота (Few-shot)">⭐ В примеры стиля</button>
                <button type="button" class="btn btn-ghost btn-xs text-muted" onclick="requestSandboxVariation(this, ${JSON.stringify(text)}, ${JSON.stringify(author)}, ${JSON.stringify(channel)})" title="Сгенерировать альтернативный ответ на этот же вопрос">🔄 Вариация</button>
            </div>
            <div style="line-height:1.4; margin-top:4px;">${esc(safeReply)}</div>
            ${res.allowed_topics_applied ? `<div class="text-xs text-muted mt-2" style="font-size:10px;">🌱 Учтён список разрешённых тем канала</div>` : ''}
        `;
        log.appendChild(botRow);
        log.scrollTop = log.scrollHeight;

        const badge = $('sandboxMemoryBadge');
        if (badge && res.context_count !== undefined) {
            badge.textContent = `🧠 Память: ${res.context_count}/50`;
            badge.className = res.context_count > 0 ? 'badge badge-primary badge-sm' : 'badge badge-sm text-muted';
        }
    } catch (e) {
        toast('Ошибка песочницы: ' + e.message, 'error');
    } finally {
        if (sendBtn) {
            sendBtn.disabled = false;
            sendBtn.textContent = '🚀 Проверить ответ';
        }
    }
}

async function saveSandboxStyleExample(btn, replyText, triggerMsg, channel) {
    if (!_currentBotId) return;
    try {
        btn.disabled = true;
        btn.textContent = '⏳...';
        const res = await api(`/api/accounts/${_currentBotId}/sandbox-save-style`, jopts('POST', {
            reply: replyText,
            trigger_msg: triggerMsg,
            channel: channel || '',
        }));
        if (res.ok) {
            btn.textContent = '⭐ В примерах';
            btn.style.color = 'var(--success, #22c55e)';
            toast('Ответ добавлен в примеры стиля бота!', 'success');
            if (typeof loadKnowledge === 'function') {
                loadKnowledge(_currentBotId);
            }
        } else {
            btn.disabled = false;
            btn.textContent = '⭐ В примеры стиля';
            toast(res.error || 'Ошибка сохранения примера', 'error');
        }
    } catch (e) {
        btn.disabled = false;
        btn.textContent = '⭐ В примеры стиля';
        toast(t('toast.error_detail', { detail: e.message }), 'error');
    }
}

async function requestSandboxVariation(btn, text, author, channel) {
    if (!_currentBotId) return;
    const account = (_bots || []).find(b => Number(b.id) === Number(_currentBotId));
    const botNick = account?.nickname || 'Бот';
    const log = $('sandboxChatLog');

    btn.disabled = true;
    btn.textContent = '⏳...';

    try {
        const res = await api(`/api/accounts/${_currentBotId}/sandbox-reply`, jopts('POST', {
            text,
            author,
            channel,
            variation: true,
        }));

        if (!res.ok) {
            toast(res.error || 'Ошибка вариации', 'error');
            return;
        }

        const botRow = document.createElement('div');
        botRow.style.cssText = 'align-self:flex-start; max-width:85%; background:var(--card-bg, #242938); border:1px dashed var(--accent, #a78bfa); border-radius:12px 12px 12px 2px; padding:10px 14px; font-size:13px; margin-bottom:4px;';

        const safeReply = res.reply || '(молчание)';
        botRow.innerHTML = `
            <div class="flex items-center gap-2 mb-1 flex-wrap">
                <b style="color:var(--accent, #a78bfa);">🤖 ${esc(botNick)}</b>
                <span class="badge badge-sm" style="font-size:10px; background:rgba(168,85,247,0.2); color:#c084fc;">🔄 Вариация</span>
                <span class="badge badge-sm" style="font-size:10px;">⏱️ ${res.latency_ms} ms</span>
                <button type="button" class="btn btn-ghost btn-xs text-muted" onclick="previewBotTTS(${JSON.stringify(safeReply)})" title="Предпрослушать озвучку ответа">🔊 Озвучить</button>
                <button type="button" class="btn btn-ghost btn-xs text-muted" onclick="saveSandboxStyleExample(this, ${JSON.stringify(safeReply)}, ${JSON.stringify(text)}, ${JSON.stringify(channel)})" title="Сохранить ответ в примеры стиля бота (Few-shot)">⭐ В примеры стиля</button>
                <button type="button" class="btn btn-ghost btn-xs text-muted" onclick="requestSandboxVariation(this, ${JSON.stringify(text)}, ${JSON.stringify(author)}, ${JSON.stringify(channel)})" title="Сгенерировать ещё вариант">🔄 Ещё вариант</button>
            </div>
            <div style="line-height:1.4; margin-top:4px;">${esc(safeReply)}</div>
        `;
        log.appendChild(botRow);
        log.scrollTop = log.scrollHeight;

        const badge = $('sandboxMemoryBadge');
        if (badge && res.context_count !== undefined) {
            badge.textContent = `🧠 Память: ${res.context_count}/50`;
            badge.className = res.context_count > 0 ? 'badge badge-primary badge-sm' : 'badge badge-sm text-muted';
        }
    } catch (e) {
        toast('Ошибка вариации: ' + e.message, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = '🔄 Вариация';
    }
}

async function resetBotContext() {
    if (!_currentBotId) return;
    const channel = $('sandboxChannel')?.value || '';
    try {
        const res = await api(`/api/accounts/${_currentBotId}/clear-context`, jopts('POST', { channel }));
        if (res.ok) {
            toast(`🧠 Контекст бота очищен (сообщений в буфере: ${res.cleared_messages || 0})`, 'success');
            const badge = $('sandboxMemoryBadge');
            if (badge) {
                badge.textContent = '🧠 Память: 0/50';
                badge.className = 'badge badge-sm text-muted';
            }
        } else {
            toast(res.error || 'Ошибка сброса контекста', 'error');
        }
    } catch (e) {
        toast(t('toast.error_detail', { detail: e.message }), 'error');
    }
}

async function updateSandboxMemoryBadge() {
    if (!_currentBotId) return;
    const badge = $('sandboxMemoryBadge');
    if (!badge) return;
    const channel = $('sandboxChannel')?.value || '';
    try {
        const res = await api(`/api/accounts/${_currentBotId}/context-status?channel=${encodeURIComponent(channel)}`);
        if (res.ok) {
            badge.textContent = `🧠 Память: ${res.count}/${res.max_size || 50}`;
            badge.className = res.count > 0 ? 'badge badge-primary badge-sm' : 'badge badge-sm text-muted';
        }
    } catch (_) {}
}

// ── Fleet Health & Bulk Actions (#1, #6) ──
async function runFleetHealthCheck(ids = null) {
    const isPartial = Array.isArray(ids) && ids.length > 0;
    toast(isPartial ? `Проверяю выбранных ботов (${ids.length})...` : 'Запущена проверка токенов и прокси всей базы...', 'info');
    try {
        const payload = isPartial ? { account_ids: ids } : {};
        const res = await api('/api/accounts/health-check', jopts('POST', payload));
        if (res && res.ok) {
            toast(`Проверка завершена: проверено ${res.total} аккаунтов`, 'success');
            if (res.results) {
                Object.assign(_botHealthStatuses, res.results);
            }
            filterBots();
        } else {
            toast('Ошибка проверки базы', 'error');
        }
    } catch (e) {
        toast(`Ошибка проверки: ${e.message}`, 'error');
    }
}

function toggleSelectAllBots() {
    const q = ($('botsSearch')?.value || '').toLowerCase();
    const status = $('botsStatusFilter')?.value || '';
    const health = $('botsHealthFilter')?.value || '';
    const role = $('botsRoleFilter')?.value || '';
    const channel = ($('botsChannelFilter')?.value || '').toLowerCase();
    const visibleBots = _allBots.filter(b => {
        const online = !!_botStatuses[b.id]?.connected;
        const chans = botDisplayChannels(b, _botStatuses[b.id] || {}).map(c => String(c).toLowerCase());
        const h = _botHealthStatuses[String(b.id)] || _botHealthStatuses[b.id];
        const hStatus = h ? h.status : '';
        return (b.nickname || '').toLowerCase().includes(q)
            && (!status || (status === 'online' ? online : !online))
            && (!health || hStatus === health)
            && (!role || (b.bot_role || 'chatter') === role)
            && (!channel || chans.includes(channel));
    });

    const allSelected = visibleBots.length > 0 && visibleBots.every(b => _selectedBots.has(b.id));
    if (allSelected) {
        visibleBots.forEach(b => _selectedBots.delete(b.id));
    } else {
        visibleBots.forEach(b => {
            if ((b.bot_role || 'chatter') !== 'director') _selectedBots.add(b.id);
        });
    }
    renderBotsList(_allBots);
}

async function bulkChangeRolePrompt() {
    if (!_selectedBots.size) return;
    const role = window.prompt('Введите новую роль для выбранных ботов:\nchatter — болтун\nlurker — люркер (тихий)\nmoderator — модератор\ndirector — режиссёр', 'chatter');
    if (!role) return;
    const cleanRole = role.trim().toLowerCase();
    if (!['chatter', 'lurker', 'moderator', 'director'].includes(cleanRole)) {
        toast('Недопустимая роль. Доступны: chatter, lurker, moderator, director', 'error');
        return;
    }
    try {
        const res = await api('/api/accounts/bulk-action', jopts('POST', {
            action: 'set_role',
            ids: [..._selectedBots],
            role: cleanRole
        }));
        if (res && res.ok) {
            toast(res.message || 'Роли обновлены', 'success');
            _selectedBots.clear();
            await loadBotsList();
        } else {
            toast(res.error || 'Ошибка смены ролей', 'error');
        }
    } catch (e) {
        toast(`Ошибка: ${e.message}`, 'error');
    }
}

async function bulkAddChannelPrompt() {
    if (!_selectedBots.size) return;
    const chan = window.prompt('Введите канал Twitch для привязки выбранных ботов:');
    if (!chan) return;
    const cleanChan = chan.trim().replace(/^#/, '').toLowerCase();
    if (!cleanChan) return;
    try {
        const res = await api('/api/accounts/bulk-action', jopts('POST', {
            action: 'add_channel',
            ids: [..._selectedBots],
            channel: cleanChan
        }));
        if (res && res.ok) {
            toast(res.message || 'Канал добавлен', 'success');
            await loadBotsList();
        } else {
            toast(res.error || 'Ошибка добавления канала', 'error');
        }
    } catch (e) {
        toast(`Ошибка: ${e.message}`, 'error');
    }
}

async function bulkRemoveDeadBots() {
    if (!window.confirm('Удалить из базы всех ботов со статусом "Ошибка токена (401)", обнаруженным чекером?')) return;
    try {
        const res = await api('/api/accounts/bulk-action', jopts('POST', {
            action: 'remove_dead'
        }));
        if (res && res.ok) {
            toast(res.message || 'Мертвые аккаунты удалены', 'success');
            _selectedBots.clear();
            await loadBotsList();
        } else {
            toast(res.error || 'Ошибка удаления мертвых аккаунтов', 'error');
        }
    } catch (e) {
        toast(`Ошибка: ${e.message}`, 'error');
    }
}

// ── Proxy Pool Functions (Общий пул прокси) ──

let _proxyPoolCache = [];
let _selectedProxyForBotId = null;

async function loadProxyPool() {
    try {
        const res = await api('/api/proxy-pool');
        if (!res || !res.ok) return;
        _proxyPoolCache = res.items || [];
        const stats = res.stats || {};

        if ($('ppStatTotal')) $('ppStatTotal').textContent = stats.total || 0;
        if ($('ppStatAvail')) $('ppStatAvail').textContent = stats.available || 0;
        if ($('ppStatAssigned')) $('ppStatAssigned').textContent = stats.assigned || 0;
        if ($('ppStatDead')) $('ppStatDead').textContent = stats.dead || 0;

        if ($('ppModalStatTotal')) $('ppModalStatTotal').textContent = stats.total || 0;
        if ($('ppModalStatAvail')) $('ppModalStatAvail').textContent = stats.available || 0;
        if ($('ppModalStatAssigned')) $('ppModalStatAssigned').textContent = stats.assigned || 0;
        if ($('ppModalStatDead')) $('ppModalStatDead').textContent = stats.dead || 0;

        renderProxyPoolList('proxyPoolList', _proxyPoolCache);
        renderProxyPoolList('proxyPoolModalList', _proxyPoolCache);
        loadProxyPoolSettings();
    } catch (e) {
        console.error('loadProxyPool error', e);
    }
}

function renderProxyPoolList(targetId, items) {
    const el = $(targetId);
    if (!el) return;
    if (!items || !items.length) {
        el.innerHTML = '<div class="text-xs text-muted p-3">Пул прокси пуст. Нажмите «＋ Добавить прокси», чтобы вставить список.</div>';
        return;
    }

    el.innerHTML = items.map(p => {
        let statusBadge = '<span class="badge" title="Не проверен">⚪</span>';
        if (p.status === 'ok') {
            statusBadge = `<span class="badge" style="color:var(--color-success,#22c55e)" title="Работает (${p.latency_ms}ms)">🟢 ${p.latency_ms ? Math.round(p.latency_ms) + 'ms' : 'OK'}</span>`;
        } else if (p.status === 'slow') {
            statusBadge = `<span class="badge" style="color:var(--color-warn,#eab308)" title="Медленный (${p.latency_ms}ms)">🟡 ${Math.round(p.latency_ms)}ms</span>`;
        } else if (p.status === 'error') {
            statusBadge = `<span class="badge" style="color:var(--color-error,#ef4444)" title="Ошибка: ${esc(p.last_error)}">🔴 Ошибка</span>`;
        }

        let assignedHtml = '<span class="badge" style="color:var(--color-success,#22c55e)">Свободен</span>';
        if (p.is_assigned) {
            assignedHtml = `<span class="badge" style="color:var(--color-primary,#6366f1)">📌 ${esc(p.assigned_nickname || 'Бот #' + p.assigned_account_id)}</span>`;
        }

        return `
            <div class="card p-2 flex items-center justify-between flex-wrap gap-2 text-xs" style="background:var(--bg-secondary,rgba(0,0,0,0.12));border:1px solid var(--border)">
                <div class="flex items-center gap-2 flex-wrap">
                    ${statusBadge}
                    <code class="font-mono text-xs font-semibold">${esc(p.masked_url)}</code>
                    ${p.label ? `<span class="badge text-muted">${esc(p.label)}</span>` : ''}
                    ${assignedHtml}
                </div>
                <div class="flex items-center gap-2">
                    <button class="btn btn-secondary btn-xs" onclick="checkSingleProxy(${p.id}, this)" title="Проверить соединение с Twitch">⚡ Тест</button>
                    ${p.is_assigned ? `<button class="btn btn-secondary btn-xs" onclick="releaseBotProxy(${p.assigned_account_id})" title="Отвязать бота">Отвязать</button>` : ''}
                    <button class="btn btn-danger btn-xs" onclick="deleteProxyFromPool(${p.id})" title="Удалить из пула">🗑️</button>
                </div>
            </div>`;
    }).join('');
}

function toggleProxyAddForm(show) {
    const f1 = $('proxyAddForm');
    const f2 = $('proxyModalAddForm');
    const isVisible = f1 && !f1.classList.contains('hidden');
    const targetState = (show !== undefined) ? show : !isVisible;
    if (f1) f1.classList.toggle('hidden', !targetState);
    if (f2) f2.classList.toggle('hidden', !targetState);
}

async function submitAddProxies() {
    const text = ($('ppInputText')?.value || '').trim();
    const proto = $('ppDefaultProto')?.value || 'http';
    const label = ($('ppLabel')?.value || '').trim();
    if (!text) { toast('Вставьте хотя бы одну строку прокси', 'warn'); return; }

    try {
        const res = await api('/api/proxy-pool/add', jopts('POST', { proxies_text: text, default_protocol: proto, label }));
        if (res.ok) {
            toast(`Добавлено ${res.added} прокси (дубликатов: ${res.duplicates}, ошибок: ${res.invalid})`, 'success');
            if ($('ppInputText')) $('ppInputText').value = '';
            toggleProxyAddForm(false);
            await loadProxyPool();
        } else {
            toast(res.error || 'Ошибка добавления', 'error');
        }
    } catch (e) {
        toast(`Ошибка: ${e.message}`, 'error');
    }
}

async function submitModalAddProxies() {
    const text = ($('ppModalInputText')?.value || '').trim();
    const proto = $('ppModalDefaultProto')?.value || 'http';
    const label = ($('ppModalLabel')?.value || '').trim();
    if (!text) { toast('Вставьте хотя бы одну строку прокси', 'warn'); return; }

    try {
        const res = await api('/api/proxy-pool/add', jopts('POST', { proxies_text: text, default_protocol: proto, label }));
        if (res.ok) {
            toast(`Добавлено ${res.added} прокси (дубликатов: ${res.duplicates})`, 'success');
            if ($('ppModalInputText')) $('ppModalInputText').value = '';
            toggleProxyAddForm(false);
            await loadProxyPool();
        } else {
            toast(res.error || 'Ошибка добавления', 'error');
        }
    } catch (e) {
        toast(`Ошибка: ${e.message}`, 'error');
    }
}

async function checkSingleProxy(id, btn) {
    if (btn) btn.disabled = true;
    try {
        const res = await api(`/api/proxy-pool/${id}/check`, jopts('POST', {}));
        if (res.ok) {
            toast(res.status === 'ok' ? `Прокси активен (${res.latency_ms}ms)` : `Статус: ${res.status} (${res.last_error || ''})`, res.status === 'ok' ? 'success' : 'warn');
            await loadProxyPool();
        }
    } catch (e) {
        toast(`Ошибка проверки: ${e.message}`, 'error');
    } finally {
        if (btn) btn.disabled = false;
    }
}

async function checkAllProxyPool() {
    toast('Запущена проверка всех прокси в пуле на подключение к Twitch...', 'info');
    try {
        const res = await api('/api/proxy-pool/check-all', jopts('POST', {}));
        if (res.ok) {
            const c = res.counts || {};
            toast(`Проверка завершена: 🟢 ${c.ok || 0} живых, 🟡 ${c.slow || 0} медленных, 🔴 ${c.error || 0} с ошибкой`, 'success');
            await loadProxyPool();
        }
    } catch (e) {
        toast(`Ошибка проверки: ${e.message}`, 'error');
    }
}

async function deleteProxyFromPool(id) {
    if (!window.confirm('Удалить этот прокси из общего пула?')) return;
    try {
        const res = await api(`/api/proxy-pool/${id}/delete`, jopts('POST', {}));
        if (res.ok) {
            toast('Прокси удален из пула', 'info');
            await loadProxyPool();
        }
    } catch (e) {
        toast(`Ошибка: ${e.message}`, 'error');
    }
}

async function cleanDeadProxyPool() {
    if (!window.confirm('Удалить из пула все нерабочие прокси (со статусом ошибки)?')) return;
    try {
        const res = await api('/api/proxy-pool/clean-dead', jopts('POST', {}));
        if (res.ok) {
            toast(`Удалено нерабочих прокси: ${res.deleted}`, 'success');
            await loadProxyPool();
        }
    } catch (e) {
        toast(`Ошибка: ${e.message}`, 'error');
    }
}

async function cleanSlowProxyPool(maxMs = 2000) {
    if (!window.confirm(`Удалить из пула все прокси с задержкой выше ${maxMs} мс и ошибки?`)) return;
    try {
        const res = await api('/api/proxy-pool/clean-slow', jopts('POST', { max_ping_ms: maxMs }));
        if (res.ok) {
            toast(`Удалено медленных прокси (> ${maxMs}мс): ${res.deleted}`, 'success');
            await loadProxyPool();
        }
    } catch (e) {
        toast(`Ошибка: ${e.message}`, 'error');
    }
}

async function cleanDuplicateProxyPool() {
    if (!window.confirm('Найти и удалить повторяющиеся прокси (с одинаковым IP-адресом)? Будет сохранен один наилучший живой прокси на каждый IP.')) return;
    try {
        const res = await api('/api/proxy-pool/clean-duplicates', jopts('POST', {}));
        if (res.ok) {
            if (res.deleted > 0) {
                toast(`Удалено повторок прокси: ${res.deleted} (осталось уникальных: ${res.unique_remaining})`, 'success');
            } else {
                toast('Повторяющихся прокси не обнаружено', 'info');
            }
            await loadProxyPool();
        } else {
            toast(res.error || 'Ошибка удаления повторок', 'error');
        }
    } catch (e) {
        toast(`Ошибка: ${e.message}`, 'error');
    }
}

async function claimBotProxyFromPool(botId) {
    if (!botId) return;
    try {
        toast('Поиск свободного живого прокси в пуле...', 'info');
        const res = await api(`/api/accounts/${botId}/claim-proxy`, jopts('POST', {}));
        if (res.ok) {
            toast(`Прокси ${res.masked_url} застолблен за ботом`, 'success');
            if ($('botProxy')) $('botProxy').value = res.proxy_url;
            updateBotProxyStatusBadge(botId, res.proxy_url);
            await loadBotsList();
            await loadProxyPool();
        } else {
            toast(res.error || 'Не удалось привязать прокси', 'error');
        }
    } catch (e) {
        toast(`Ошибка: ${e.message}`, 'error');
    }
}

function openSelectBotProxyModal(botId) {
    if (!botId) return;
    const bot = _allBots.find(b => b.id === botId);
    if ($('selectProxyBotNick')) $('selectProxyBotNick').textContent = bot ? bot.nickname : '#' + botId;
    _selectedProxyForBotId = null;
    if ($('confirmSelectProxyBtn')) $('confirmSelectProxyBtn').disabled = true;

    showModal('selectBotProxyModal');
    renderSelectBotProxyList(botId);
}

async function renderSelectBotProxyList(botId) {
    const el = $('selectBotProxyList');
    if (!el) return;
    el.innerHTML = '<div class="text-xs text-muted p-2">Загрузка свободных прокси...</div>';

    try {
        const res = await api('/api/proxy-pool');
        const items = (res.items || []).filter(p => !p.is_assigned || p.assigned_account_id === botId);
        if (!items.length) {
            el.innerHTML = '<div class="card p-3 text-xs text-muted">В пуле нет свободных прокси. Пополните пул в настройках.</div>';
            return;
        }

        el.innerHTML = items.map(p => {
            const isCurrent = p.assigned_account_id === botId;
            let statusIcon = p.status === 'ok' ? '🟢' : (p.status === 'slow' ? '🟡' : (p.status === 'error' ? '🔴' : '⚪'));
            return `
                <label class="card p-2 flex items-center justify-between gap-2 text-xs cursor-pointer hover-card" style="border:1px solid var(--border)">
                    <div class="flex items-center gap-2">
                        <input type="radio" name="selectProxyRadio" value="${p.id}" ${isCurrent ? 'checked' : ''} onchange="onSelectProxyRadioChanged(${p.id})">
                        <span>${statusIcon}</span>
                        <code class="font-mono font-semibold">${esc(p.masked_url)}</code>
                        ${p.label ? `<span class="badge">${esc(p.label)}</span>` : ''}
                    </div>
                    <div>
                        ${isCurrent ? '<span class="badge badge-primary">Текущий</span>' : (p.latency_ms ? `<span class="text-muted">${Math.round(p.latency_ms)}ms</span>` : '')}
                    </div>
                </label>`;
        }).join('');
    } catch (e) {
        el.innerHTML = `<div class="text-xs text-error p-2">Ошибка: ${esc(e.message)}</div>`;
    }
}

function onSelectProxyRadioChanged(proxyId) {
    _selectedProxyForBotId = proxyId;
    if ($('confirmSelectProxyBtn')) $('confirmSelectProxyBtn').disabled = false;
}

async function confirmSelectBotProxy() {
    if (!_currentBotId || !_selectedProxyForBotId) return;
    try {
        const res = await api(`/api/accounts/${_currentBotId}/claim-proxy`, jopts('POST', { proxy_id: _selectedProxyForBotId }));
        if (res.ok) {
            toast(`Прокси ${res.masked_url} привязан к боту`, 'success');
            if ($('botProxy')) $('botProxy').value = res.proxy_url;
            updateBotProxyStatusBadge(_currentBotId, res.proxy_url);
            hideModal('selectBotProxyModal');
            await loadBotsList();
            await loadProxyPool();
        } else {
            toast(res.error || 'Ошибка привязки прокси', 'error');
        }
    } catch (e) {
        toast(`Ошибка: ${e.message}`, 'error');
    }
}

async function releaseBotProxy(botId) {
    if (!botId) return;
    try {
        const res = await api(`/api/accounts/${botId}/release-proxy`, jopts('POST', {}));
        if (res.ok) {
            toast('Прокси отвязан и возвращен в пул свободных', 'info');
            if ($('botProxy')) $('botProxy').value = '';
            updateBotProxyStatusBadge(botId, '');
            await loadBotsList();
            await loadProxyPool();
        }
    } catch (e) {
        toast(`Ошибка: ${e.message}`, 'error');
    }
}

async function bulkClaimProxiesFromPool() {
    if (!_selectedBots.size) return;
    const n = _selectedBots.size;
    toast(`Раздаем свободные прокси для ${n} выбранных ботов...`, 'info');
    try {
        const res = await api('/api/accounts/bulk-claim-proxies', jopts('POST', { ids: [..._selectedBots] }));
        if (res.ok) {
            let msg = `Успешно привязано прокси: ${res.claimed_count}`;
            if (res.failed_count > 0) {
                msg += ` (не хватило свободных для ${res.failed_count} ботов)`;
            }
            toast(msg, res.claimed_count > 0 ? 'success' : 'warn');
            await loadBotsList();
            await loadProxyPool();
        } else {
            toast(res.error || 'Ошибка раздачи прокси', 'error');
        }
    } catch (e) {
        toast(`Ошибка: ${e.message}`, 'error');
    }
}

async function claimProxiesForActiveBots() {
    if (!window.confirm('Раздать свободные прокси всем включенным активным ботам? (Выключенные боты будут пропущены)')) return;
    toast('Раздаем свободные прокси активным ботам...', 'info');
    try {
        const res = await api('/api/accounts/claim-proxies-for-active', jopts('POST', {}));
        if (res.ok) {
            let msg = `Выдано прокси: ${res.claimed_count} из ${res.active_total} активных`;
            if (res.failed_count > 0) {
                msg += ` (${res.failed_count} без прокси — пополните пул)`;
            }
            toast(msg, res.claimed_count > 0 ? 'success' : 'warn');
            await loadBotsList();
            await loadProxyPool();
        } else {
            toast(res.error || 'Ошибка раздачи прокси', 'error');
        }
    } catch (e) {
        toast(`Ошибка: ${e.message}`, 'error');
    }
}

function updateBotProxyStatusBadge(botId, proxyUrl) {
    const badge = $('botProxyPoolStatusBadge');
    if (!badge) return;
    if (!proxyUrl) {
        badge.innerHTML = '<span class="text-muted">Прокси не задан</span>';
        return;
    }
    const inPool = _proxyPoolCache.find(p => p.assigned_account_id === botId || p.url === proxyUrl);
    if (inPool) {
        badge.innerHTML = `<span class="badge" style="color:var(--color-success,#22c55e);font-weight:600">🌐 Застолблен в пуле #${inPool.id}</span>`;
    } else {
        badge.innerHTML = '<span class="badge text-muted">✏️ Ручной ввод</span>';
    }
}

async function loadProxyPoolSettings() {
    try {
        const s = await api('/api/proxy-pool/settings');
        if (s) {
            if ($('ppAutoFailover')) $('ppAutoFailover').checked = !!s.auto_failover;
            if ($('ppNotifyOwner')) $('ppNotifyOwner').checked = !!s.notify_owner;
            if ($('ppAutoClean')) $('ppAutoClean').checked = s.auto_clean !== false;
        }
    } catch (_) {}
}

async function saveProxyPoolSettingsUi() {
    try {
        const payload = {
            auto_failover: !!$('ppAutoFailover')?.checked,
            notify_owner: !!$('ppNotifyOwner')?.checked,
            auto_clean: !!$('ppAutoClean')?.checked,
        };
        await api('/api/proxy-pool/settings', jopts('POST', payload));
        toast('Настройки пула прокси сохранены', 'success');
    } catch (e) {
        toast(`Ошибка сохранения: ${e.message}`, 'error');
    }
}

function openProxyPoolModal() {
    showModal('proxyPoolModal');
    loadProxyPool();
}
