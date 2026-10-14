// [P5-split] 04_chat_settings.js ← static/app.js, исходные строки 3465–4103; грузится после предыдущего чанка, порядок = порядку строк

// ── Chat ────────────────────────────────────────────
let _chatInited = false;
async function initChat() {
    const sel = $('chatBot');
    try {
        if (!_allBots.length) {
            const accounts = await api('/api/accounts');
            _allBots = Array.isArray(accounts) ? accounts : (accounts.accounts || []);
        }
        const cur = sel.value;
        sel.innerHTML = _allBots.map(a => `<option value="${a.id}">${esc(a.nickname)}</option>`).join('');
        if (cur) sel.value = cur;
        await refreshChatChannels();
        syncChatComposer();
        if (!_chatInited) {
            _chatInited = true;
            await loadRecentChat();
        }
    } catch (e) { console.error('initChat', e); }
}

// Q20: канал больше не <select> — это hidden-держатель состояния #chatChannel,
// а выбор идёт через поисковый пикер с группировкой по ботам (chatChannelPicker).
async function refreshChatChannels() {
    const botId = $('chatBot').value;
    const hidden = $('chatChannel');
    if (!botId || !hidden) return;
    updateChatChannelPick();
    syncChatComposer();
}

function updateChatChannelPick() {
    const btn = $('chatChannelPick');
    if (!btn) return;
    const channel = ($('chatChannel')?.value || '').replace('#', '');
    btn.textContent = channel ? `# ${channel}` : t('label.all_channels');
}

function _chatPickerGroups() {
    return (_allBots || []).map(bot => ({
        bot,
        channels: (bot.persisted_channels || bot.channels || [])
            .filter(ch => ch.enabled !== false && ch.enabled !== 0)
            .map(ch => String(ch.channel_name || ch.name || ch).replace(/^#/, ''))
            .filter(Boolean),
    })).filter(group => group.channels.length);
}

function toggleChatChannelPanel() {
    const panel = $('chatChannelPanel');
    if (!panel) return;
    const opening = panel.classList.contains('hidden');
    panel.classList.toggle('hidden', !opening);
    $('chatChannelPick')?.setAttribute('aria-expanded', opening ? 'true' : 'false');
    // Список живёт внутри .card, а .card с backdrop-filter образует свой stacking
    // context — без этого карточка «Живой чат» перекрывает его (см. app.css).
    $('chatChannelPicker')?.closest('.card')?.classList.toggle('chat-picker-open', opening);
    if (opening) {
        const search = $('chatChannelSearch');
        if (search) { search.value = ''; search.focus(); }
        renderChatChannelPanel();
    }
}

function closeChatChannelPanel() {
    $('chatChannelPanel')?.classList.add('hidden');
    $('chatChannelPick')?.setAttribute('aria-expanded', 'false');
    $('chatChannelPicker')?.closest('.card')?.classList.remove('chat-picker-open');
}

function renderChatChannelPanel() {
    const list = $('chatChannelPanelList');
    if (!list) return;
    const q = ($('chatChannelSearch')?.value || '').trim().toLowerCase();
    const groups = _chatPickerGroups().map(group => {
        const channels = q
            ? group.channels.filter(ch => ch.toLowerCase().includes(q) || (group.bot.nickname || '').toLowerCase().includes(q))
            : group.channels;
        return { ...group, channels };
    }).filter(group => group.channels.length);
    const currentBot = $('chatBot')?.value || '';
    const currentChannel = ($('chatChannel')?.value || '').replace('#', '');
    list.innerHTML =
        `<button type="button" class="btn btn-sm btn-secondary mb-1" style="width:100%" onclick="pickChatChannel(null, '')">${esc(t('label.all_channels'))}</button>` +
        groups.map(group => `
        <div class="mb-2">
            <div class="text-xs font-semibold text-muted mb-1">${esc(group.bot.nickname || `#${group.bot.id}`)}</div>
            <div class="flex gap-1 flex-wrap">${group.channels.map(channel => `
                <button type="button" class="btn btn-sm ${String(group.bot.id) === String(currentBot) && channel === currentChannel ? 'btn-primary' : 'btn-secondary'}"
                    onclick="pickChatChannel(${group.bot.id}, '${esc(channel)}')" data-i18n-aria-label="panel.chat_channel" aria-label="#${esc(channel)} · ${esc(group.bot.nickname || '')}">#${esc(channel)}</button>`).join('')}
            </div>
        </div>`).join('') ||
        `<div class="text-muted text-sm">${esc(t('chat.pick_empty'))}</div>`;
    list.innerHTML += `
        <div class="mt-2 pt-2" style="border-top:1px solid var(--border)">
            <label class="text-xs font-semibold text-muted mb-1 block" for="chatChannelManual">${esc(t('chat.pick_manual_label'))}</label>
            <div class="flex gap-1">
                <input type="text" id="chatChannelManual" class="input" style="flex:1" placeholder="${esc(t('chat.pick_manual_ph'))}"
                    onkeypress="if(event.key==='Enter'){event.preventDefault();pickChatChannelManual();}">
                <button type="button" class="btn btn-sm btn-secondary" onclick="pickChatChannelManual()">${esc(t('chat.pick_manual_use'))}</button>
            </div>
        </div>`;
}

// Owner report 27.09.2026: канал можно было выбрать только кнопкой из уже
// сохранённых привязок бота — нельзя было вписать канал вручную (например
// для разовой ручной отправки без сохранения привязки).
function pickChatChannelManual() {
    const value = ($('chatChannelManual')?.value || '').trim();
    if (!value) return;
    const botId = $('chatBot')?.value || null;
    pickChatChannel(botId, value);
}

function pickChatChannel(botId, channel) {
    const botSel = $('chatBot');
    if (botSel && botId) botSel.value = String(botId);
    const hidden = $('chatChannel');
    if (hidden) hidden.value = (channel || '').replace('#', '');
    closeChatChannelPanel();
    updateChatChannelPick();
    syncChatComposer();
    loadRecentChat();
}

// Закрытие пикера по клику мимо и по Escape (один обработчик на страницу).
if (typeof document !== 'undefined' && !globalThis._chatPickerOutsideBound) {
    globalThis._chatPickerOutsideBound = true;
    document.addEventListener('click', e => {
        if (!(e.target instanceof Element) || !e.target.closest('#chatChannelPicker')) closeChatChannelPanel();
    });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeChatChannelPanel(); });
}

function syncChatComposer() {
    const input = $('chatMessage');
    const button = $('chatSendButton');
    if (!input || !button) return;
    const hasBot = Boolean($('chatBot')?.value);
    const hasChannel = Boolean($('chatChannel')?.value);
    const enabled = hasBot && hasChannel;
    input.disabled = !enabled;
    button.disabled = !enabled;
    input.placeholder = t(enabled ? 'label.message_from_bot' : (hasBot ? 'chat.select_channel' : 'chat.select_bot'));
    input.title = enabled ? '' : input.placeholder;
}

async function loadRecentChat() {
    try {
        const botId = $('chatBot')?.value || '';
        const channel = ($('chatChannel')?.value || '').replace('#', '');
        const params = new URLSearchParams({ limit: '100' });
        if (channel) params.set('channel', channel);
        if (botId) params.set('account_id', botId);
        const rows = await api('/api/logs?' + params);
        const el = $('liveChatContainer');
        if (!Array.isArray(rows) || !rows.length) {
            el.innerHTML = `<div class="empty-state"><div class="empty-icon">💬</div>${esc(t('label.no_messages'))}</div>`;
            return;
        }
        el.innerHTML = rows.map(r => chatMsgHTML(r.timestamp, r.author, r.message, r.is_bot, r.channel, r.account_id)).join('');
        el.scrollTop = el.scrollHeight;
    } catch (e) { console.error('loadRecentChat', e); }
}

function chatMsgHTML(ts, author, message, isBot, channel, accountId) {
    // §25.1: роль стримера определяем по каналу сообщения, не по селектору
    const msgChan = String(channel || '').replace('#', '').toLowerCase();
    const role = isBot ? 'bot'
        : (msgChan && String(author || '').toLowerCase() === msgChan ? 'streamer' : 'viewer');
    const chBadge = msgChan ? `<span class="chat-channel-badge" title="${t('chat.channel_of')}">#${esc(msgChan)}</span> ` : '';
    const fb = isBot ? `<span class="fb-buttons">
        <button class="chat-tts-btn" title="👍" onclick="rateBotReply(this, ${accountId || 0}, '${esc(msgChan)}', '${esc(message).replaceAll("'", '&#39;')}', 1)">👍</button>
        <button class="chat-tts-btn" title="👎" onclick="rateBotReply(this, ${accountId || 0}, '${esc(msgChan)}', '${esc(message).replaceAll("'", '&#39;')}', -1)">👎</button>
    </span>` : '';
    return `<div class="chat-msg is-${role}">
        <span class="chat-time">${fmtTime((ts || '').replace(' ', 'T'))}</span>
        ${chBadge}<span class="chat-nick">${esc(author)} <span class="role-badge">${t(`label.role_${role}`)}</span>:</span>
        <span>${esc(message)}</span>
        ${isBot ? fb + `<button class="chat-tts-btn" title="${esc(t('tts.test_bot_voice'))}" onclick="testBotChatTTS(${accountId || 0}, '${esc(msgChan)}', '${esc(message).replaceAll("'", '&#39;')}')">🔊</button>`
               + `<button class="chat-tts-btn" title="${esc(t('feedback.categories_title'))}" onclick="showBotFeedbackMenu(event, ${accountId || 0}, '${esc(msgChan)}', '${esc(message).replaceAll("'", '&#39;')}')">▾</button>`
               : `<button class="chat-tts-btn" title="TTS" onclick="testChatTTS('${esc(message).replaceAll("'", '&#39;')}')">🔊</button>`}
    </div>`;
}

// §7.1 §9k: расширенные категории оценки ответа бота (длинный/токсичный/не в стиле/мимо темы)
const BOT_FEEDBACK_CATEGORIES = [
    { id: 'too_long', key: 'feedback.cat_too_long' },
    { id: 'toxic', key: 'feedback.cat_toxic' },
    { id: 'off_style', key: 'feedback.cat_off_style' },
    { id: 'off_topic', key: 'feedback.cat_off_topic' },
    { id: 'other', key: 'feedback.cat_other' },
];

function showBotFeedbackMenu(ev, accountId, channel, message) {
    ev.stopPropagation();
    document.getElementById('botFeedbackMenu')?.remove();
    const menu = document.createElement('div');
    menu.id = 'botFeedbackMenu';
    menu.style.cssText = 'position:fixed;z-index:999;background:var(--bg-card);border:1px solid var(--border);border-radius:10px;padding:6px;display:flex;flex-direction:column;gap:2px;box-shadow:var(--shadow-card)';
    menu.innerHTML = BOT_FEEDBACK_CATEGORIES.map(c =>
        `<button class="btn btn-sm btn-secondary" onclick="rateBotReplyCategory(${accountId}, '${esc(channel)}', '${esc(message).replaceAll("'", '&#39;')}', '${c.id}'); this.closest('#botFeedbackMenu').remove()">${esc(t(c.key))}</button>`).join('');
    document.body.appendChild(menu);
    const r = ev.currentTarget.getBoundingClientRect();
    menu.style.left = Math.min(r.left, window.innerWidth - 220) + 'px';
    menu.style.top = Math.min(r.bottom + 4, window.innerHeight - menu.offsetHeight - 8) + 'px';
}
document.addEventListener('click', e => {
    if (!e.target.closest?.('#botFeedbackMenu')) document.getElementById('botFeedbackMenu')?.remove();
});

async function rateBotReplyCategory(accountId, channel, message, category) {
    try {
        const res = await api('/api/ai-feedback', jopts('POST', {
            account_id: accountId || 0, channel: channel || '', event_type: 'send',
            message: String(message || '').substring(0, 500), rating: -1, category,
        }));
        if (!res.ok) throw new Error(res.error || 'fail');
        toast(t('feedback.saved'), 'success');
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

function testChatTTS(text) {
    if ('speechSynthesis' in window) window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
}

// §7.1 §12.1: TTS test голосом ЭТОГО бота (per-bot конфиг → OBS TTS-оверлей)
async function testBotChatTTS(accountId, channel, text) {
    if (!accountId || !channel) { toast(t('chat.select_channel'), 'error'); return; }
    try {
        const res = await api(`/api/accounts/${accountId}/tts-test`, jopts('POST', { channel, text }));
        if (res.ok) toast(t('tts.sent_to_obs'), 'success');
        else throw new Error(res.error || 'tts failed');
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

function appendLiveChat(msg) {
    const el = $('liveChatContainer');
    if (!el) return;
    // фільтр каналу, якщо вибрано
    const chFilter = $('chatChannel')?.value;
    if (chFilter && msg.channel && msg.channel.replace('#', '') !== chFilter.replace('#', '')) return;
    // прибираємо empty-state
    const empty = el.querySelector('.empty-state');
    if (empty) empty.remove();
    el.insertAdjacentHTML('beforeend', chatMsgHTML(new Date().toISOString(), msg.author, msg.message, msg.is_bot, msg.channel, msg.account_id));
    while (el.children.length > 300) el.firstChild.remove();
    el.scrollTop = el.scrollHeight;
}

async function sendChatMessage() {
    const msg = $('chatMessage').value.trim();
    const botId = $('chatBot')?.value;
    const channel = ($('chatChannel')?.value || '').replace('#', '');
    if (!msg || !botId) { toast(t('toast.select_bot_text'), 'error'); return; }
    if (!channel) { toast(t('chat.select_channel'), 'error'); return; }
    try {
        const result = await api('/api/send', jopts('POST', { account_id: parseInt(botId), channel, text: msg }));
        if (!result.ok) throw new Error(sendReasonText(result.reason, result.error));
        $('chatMessage').value = '';
        appendLiveChat({ author: `→ ${t('send.sent_ok').replace('✅', '').trim()}`, message: msg, is_bot: true, channel });
        // Owner report 27.09.2026: TwitchIO не подтверждает обычную успешную
        // отправку положительно — молчание сервера не то же самое, что доставка.
        if (result.confirmed === false) toast(t('send.unconfirmed_hint'), 'info');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

function clearLiveChat() {
    $('liveChatContainer').innerHTML = '';
}

// ── Analytics ───────────────────────────────────────
async function loadAnalytics() {
    try {
        const bot = $('analyticsBotFilter')?.value || '';
        const level = $('analyticsLevelFilter')?.value || '';
        const fromTime = $('analyticsLogsFrom')?.value || '';
        const toTime = $('analyticsLogsTo')?.value || '';
        let logsUrl = '/api/bot-logs?limit=200';
        if (bot) logsUrl += `&account_id=${encodeURIComponent(bot)}`;
        if (level) logsUrl += `&level=${encodeURIComponent(level)}`;
        if (fromTime) logsUrl += `&from_time=${encodeURIComponent(fromTime.replace('T', ' '))}`;
        if (toTime) logsUrl += `&to_time=${encodeURIComponent(toTime.replace('T', ' '))}`;
        const [stats, logs, sentiment, wordcloud] = await Promise.all([
            api('/api/stats/all'),
            api(logsUrl),
            api('/api/stats/sentiment?hours=24'),
            api('/api/stats/wordcloud?hours=24&top_n=20'),
        ]);
        const list = Array.isArray(stats) ? stats : [];
        const totalRead = list.reduce((a, s) => a + (s.read || 0), 0);
        const totalSent = list.reduce((a, s) => a + (s.sent || 0), 0);
        if ($('statsTotalMessages')) $('statsTotalMessages').textContent = totalRead.toLocaleString();
        if ($('statsAIReplies')) $('statsAIReplies').textContent = totalSent.toLocaleString();
        if ($('sentimentSummary')) {
            const s = sentiment.summary || {};
            $('sentimentSummary').textContent = `🙂 ${s.pos || 0}  😐 ${s.neu || 0}  🙁 ${s.neg || 0}  | net ${s.net || 0}`;
        }
        if ($('wordCloudSummary')) {
            $('wordCloudSummary').innerHTML = (wordcloud.items || []).slice(0, 20).map(item => `<span style="font-size:${12 + Math.min(18, item.count * 2)}px">${esc(item.word)}</span>`).join(' ')
                || `<div class="text-muted text-sm">${esc(t('analytics.empty'))}</div>`;
        }
        // Активність per-bot (bars)
        const maxSent = Math.max(1, ...list.map(s => s.sent || 0));
        const bars = $('chartActivity');
        if (bars) {
            bars.innerHTML = list.length ? list.map(s => `
                <div class="stat-bar-row">
                    <span>${esc(s.nickname)}</span>
                    <div class="stat-bar"><div class="stat-bar-fill" style="width:${Math.round((s.sent || 0) / maxSent * 100)}%"></div></div>
                    <span class="text-right">${s.sent || 0}</span>
                </div>
            `).join('') : `<div class="text-muted text-sm">${esc(t('stats.nodata'))}</div>`;
        }
        // фільтр ботів
        const sel = $('analyticsBotFilter');
        if (sel && !sel.options.length) {
            sel.innerHTML = `<option value="">${esc(t('analytics.all_bots'))}</option>` +
                list.map(s => `<option value="${s.account_id}">${esc(s.nickname)}</option>`).join('');
        }
        renderAnalyticsLogs(logs.logs || []);
    } catch (e) {
        console.error('loadAnalytics', e);
        const target = $('chartActivity');
        if (target) target.innerHTML = `<div class="text-error">${esc(e.message)} <button class="btn btn-sm btn-secondary" onclick="loadAnalytics()">${t('status.retry')}</button></div>`;
        // P8-A2: не оставляем вечное «Загрузка...» в соседних блоках
        if ($('sentimentSummary')) $('sentimentSummary').innerHTML = `<span class="text-muted text-sm">${esc(t('analytics.empty'))}</span>`;
        if ($('wordCloudSummary')) $('wordCloudSummary').innerHTML = `<span class="text-muted text-sm">${esc(t('analytics.empty'))}</span>`;
        const logsBox = $('analyticsLogsContent');
        if (logsBox) logsBox.innerHTML = `<div class="text-muted text-sm p-3">${esc(t('logs.empty_hint'))}</div>`;
    }
}

function renderAnalyticsLogs(logs) {
    const el = $('analyticsLogsContent');
    if (!el) return;
    if (!logs.length) { el.innerHTML = logsEmptyHtml(); return; }
    el.innerHTML = logs.map(renderLogLine).join('');
}

async function loadAnalyticsLogs() {
    const bot = $('analyticsBotFilter')?.value || '';
    const level = $('analyticsLevelFilter')?.value || '';
    const fromTime = $('analyticsLogsFrom')?.value || '';
    const toTime = $('analyticsLogsTo')?.value || '';
    let url = '/api/bot-logs?limit=200';
    if (bot) url += `&account_id=${encodeURIComponent(bot)}`;
    if (level) url += `&level=${encodeURIComponent(level)}`;
    if (fromTime) url += `&from_time=${encodeURIComponent(fromTime.replace('T', ' '))}`;
    if (toTime) url += `&to_time=${encodeURIComponent(toTime.replace('T', ' '))}`;
    try {
        const data = await api(url);
        renderAnalyticsLogs(data.logs || []);
    } catch (e) {
        // P8-A2: ошибка ручки не должна оставлять вечное «Загрузка...»
        const el = $('analyticsLogsContent');
        if (el) el.innerHTML = `<div class="text-muted text-sm p-3">${esc(t('logs.empty_hint'))}</div>`;
    }
}

function exportAnalyticsLogs() {
    const bot = $('analyticsBotFilter')?.value || '';
    const level = $('analyticsLevelFilter')?.value || '';
    const fromTime = $('analyticsLogsFrom')?.value || '';
    const toTime = $('analyticsLogsTo')?.value || '';
    const params = [];
    if (bot) params.push(`account_id=${encodeURIComponent(bot)}`);
    if (level) params.push(`level=${encodeURIComponent(level)}`);
    if (fromTime) params.push(`from_time=${encodeURIComponent(fromTime.replace('T', ' '))}`);
    if (toTime) params.push(`to_time=${encodeURIComponent(toTime.replace('T', ' '))}`);
    window.open(API + '/api/bot-logs/export?' + params.join('&'), '_blank');
}

function openBotLogs() {
    showSection('analytics');
}

// ── Settings ────────────────────────────────────────
const AI_PROVIDER_FIELDS = {
    openrouter: [
        { key: 'openrouter_key', label: 'API Ключ', type: 'password' },
        { key: 'openrouter_chat', label: 'Модель для тексту' },
        { key: 'openrouter_vision', label: 'Модель для vision' },
    ],
    ollama: [
        { key: 'ollama_host', label: 'Хост', placeholder: 'http://localhost:11434' },
        { key: 'ollama_chat', label: 'Модель для тексту' },
        { key: 'ollama_vision', label: 'Модель для vision' },
    ],
    gemini: [
        { key: 'gemini_key', label: 'API Ключ', type: 'password' },
        { key: 'gemini_chat', label: 'Модель для тексту' },
        { key: 'gemini_vision', label: 'Модель для vision' },
    ],
    openai: [
        { key: 'openai_key', label: 'API Ключ', type: 'password' },
        { key: 'openai_chat', label: 'Модель для тексту' },
        { key: 'openai_vision', label: 'Модель для vision' },
    ],
    anthropic: [
        { key: 'anthropic_key', label: 'API Ключ', type: 'password' },
        { key: 'anthropic_chat', label: 'Модель для тексту' },
        { key: 'anthropic_vision', label: 'Модель для vision' },
    ],
};

function renderAIProviderFields() {
    const provider = $('globalAIProvider').value;
    const box = $('aiProviderFields');
    const fields = AI_PROVIDER_FIELDS[provider] || [];
    box.innerHTML = fields.map(f => {
        let val = _aiConfig[f.key] || '';
        if (f.key.endsWith('_key')) val = '';  // ключі не показуємо
        const masked = f.key.endsWith('_key') && _aiConfig[f.key] ? 'ключ задано' : '';
        return `<div>
            <label class="text-sm text-muted mb-2 block">${f.label}</label>
            <input type="${f.type || 'text'}" id="ai_${f.key}" class="input" value="${esc(val)}"
                   placeholder="${f.placeholder || masked || ''}">
        </div>`;
    }).join('');
}

let _actionLogOffset = 0;

async function loadSettings() {
    loadActionLog();
    const cpReady = loadCustomProviders();
    // Q16 F4: консоль модератора TTS грузится в loadBotModeration (карточка бота)
    // P8-C12: глобальная карточка «О стримере» убрана из Настроек — gsp-формы нет,
    // вызов loadGlobalStreamerChannels('gsp') удалён (профиль живёт в Мозге, bsp)
    // P8-C3: loadStreamerAttitudes перенесено в карточку бота (loadBotAttitude)
    // AI config
    try {
        const cfg = await api('/api/ai/config');
        _aiConfig = cfg || {};
        // сохранённый custom:<имя> появляется в селекте только после loadCustomProviders
        await cpReady;
        $('globalAIProvider').value = cfg.provider || 'openrouter';
        renderAIProviderFields();
        if ($('globalVisionModel')) $('globalVisionModel').value = cfg.global_vision_override || '';
        // P8-C13: guard несохранённых изменений для глобальных форм
        bindDirtyWatch('globalAI', ['globalAIProvider', 'globalVisionModel']);
        const aiIds = Array.from(document.querySelectorAll('[id^="ai_"]')).map(e => e.id);
        bindDirtyWatch('globalAI', aiIds);
        clearDirty('globalAI');
    } catch (e) { console.error('ai config', e); }
    // Q16 F3: глобальная TTS-форма убрана — TTS полностью per-бот (loadBotTTS)
    loadProviderStatus();
    loadOfflineMode();
    refreshDbStats();
    loadTtsDuckingSettings();
    // Twitch credentials
    try {
        const [tc, refreshConfig] = await Promise.all([
            api('/api/settings/twitch-credentials'),
            api('/api/settings/auto-refresh'),
        ]);
        if ($('twitchClientID')) $('twitchClientID').value = tc.client_id || '';
        if ($('twitchClientSecret')) $('twitchClientSecret').placeholder = tc.client_secret_set ? t('placeholder.twitch_secret_set') : t('placeholder.client_secret');
        if ($('autoRefreshTokens')) $('autoRefreshTokens').checked = refreshConfig.auto_refresh !== false;
        if ($('tokenExpiryWarningDays')) $('tokenExpiryWarningDays').value = refreshConfig.warning_days || 7;
        bindDirtyWatch('twitchApp', ['twitchClientID', 'twitchClientSecret']); // P8-C13
        bindDirtyWatch('tokenRefresh', ['autoRefreshTokens', 'tokenExpiryWarningDays']);
        clearDirty('twitchApp');
        clearDirty('tokenRefresh');
    } catch (e) { /* noop */ }
    // Security status
    try {
        const st = await api('/api/security/status');
        const access = $('secAuth');
        if (access) {
            access.className = 'badge on';
            access.textContent = '✅ ' + t(st.local_passwordless ? 'security.local_no_password' : 'security.network_auth');
        }
        const map = [
            ['secEnc', st.encryption_enabled, t('security.token_encryption')],
            ['secHelix', st.helix_configured, t('security.helix_api')],
            ['secOAuth', st.device_oauth_configured, t('security.device_oauth')],
        ];
        map.forEach(([id, on, label]) => {
            const el = $(id);
            if (el) {
                el.className = 'badge ' + (on ? 'on' : 'off');
                el.textContent = (on ? '✅ ' : '❌ ') + label;
            }
        });
        const plaintextWarning = $('plaintextSecurityWarning');
        if (plaintextWarning) {
            plaintextWarning.classList.toggle('hidden', !st.plaintext_warning);
        }
    } catch (e) { /* noop */ }
    // Widget URL
    if ($('ttsWidgetUrl')) $('ttsWidgetUrl').textContent = location.origin + '/obs/tts';
    if ($('obsWidgetUrl')) $('obsWidgetUrl').textContent = location.origin + '/obs-widget';
    // Proxy pool
    if (typeof loadProxyPool === 'function') {
        loadProxyPool();
    }
}

// ── Track 6.6: owner controls for the exact-scoped Moderator TTS console ──
const MOD_TTS_SOURCES = [
    'bot_reply', 'voice_companion_reply', 'moderation_announcement',
    'twitch_moderator_message', 'ordinary_chat', 'channel_points_reward',
];
let _modTTSAdminPolicy = {aliases: [], policies: []};

function modTTSScope() {
    const raw = $('modTTSAdminScope')?.value || '';
    const split = raw.indexOf(':');
    return split < 1 ? null : {accountId: Number(raw.slice(0, split)), channel: decodeURIComponent(raw.slice(split + 1))};
}

function modTTSStatus(message, error = false) {
    const box = $('modTTSAdminStatus');
    if (!box) return;
    box.textContent = message;
    box.style.color = error ? 'var(--danger)' : '';
}

async function loadModeratorTTSAdmin() {
    const select = $('modTTSAdminScope');
    if (!select) return;
    try {
        const map = await api('/api/tts/routing-map');
        const scopes = new Map();
        (map.rows || []).forEach(row => scopes.set(`${row.account.id}:${row.channel}`, row));
        const previous = select.value;
        select.innerHTML = [...scopes.values()].map(row =>
            `<option value="${row.account.id}:${encodeURIComponent(row.channel)}">${esc(row.account.nickname)} · #${esc(row.channel)}</option>`
        ).join('');
        // Q16 F4: карточка бота открывает консоль в скоупе этого бота
        const botScope = (typeof _currentBotId !== 'undefined' && _currentBotId)
            ? [...select.options].find(option => option.value.startsWith(`${_currentBotId}:`))
            : null;
        if ([...select.options].some(option => option.value === previous)) select.value = previous;
        else if (botScope && !previous) select.value = botScope.value;
        const source = $('modTTSSource');
        source.innerHTML = MOD_TTS_SOURCES.map(value => `<option value="${value}">${esc(t(`settings.mod_tts_source_${value}`))}</option>`).join('');
        await loadModeratorTTSScope();
    } catch (e) {
        modTTSStatus(t('settings.mod_tts_load_error'), true);
    }
}

async function loadModeratorTTSScope() {
    const scope = modTTSScope();
    if (!scope) {
        modMediaTokenConfigured = false;
        hideModeratorMediaToken();
        modTTSStatus(t('settings.mod_tts_no_scope'), true);
        return;
    }
    const base = `/api/accounts/${scope.accountId}/channels/${encodeURIComponent(scope.channel)}/tts-voice-policy`;
    const admin = `/api/moderator-console/admin/accounts/${scope.accountId}/channels/${encodeURIComponent(scope.channel)}`;
    try {
        const [policy, grants, chat] = await Promise.all([api(base), api(`${admin}/grants`), api(`${admin}/chat-tts`)]);
        _modTTSAdminPolicy = policy;
        $('modTTSVoiceList').innerHTML = (policy.aliases || []).map(voice =>
            `<span class="badge ${voice.enabled ? 'on' : 'off'} mr-2">${esc(voice.alias)} · ${esc(voice.label)}</span>`
        ).join('') || `<span class="text-muted">${esc(t('settings.mod_tts_no_voices'))}</span>`;
        const aliases = (policy.aliases || []).filter(voice => voice.enabled);
        $('modTTSDefaultAlias').innerHTML = `<option value="">${esc(t('settings.mod_tts_provider_default'))}</option>` +
            aliases.map(voice => `<option value="${esc(voice.alias)}">${esc(voice.alias)} · ${esc(voice.label)}</option>`).join('');
        $('modTTSChatEnabled').checked = !!chat.enabled;
        $('modTTSChatAlias').value = chat.command_alias || '!tts';
        renderModeratorTTSGrants(grants.grants || []);
        renderModeratorTTSPolicy();
        await Promise.all([loadModeratorMediaAdmin(), loadModeratorSoundAdmin(), loadModeratorTTSOutput()]);
        modTTSStatus(t('settings.mod_tts_loaded'));
    } catch (e) {
        modTTSStatus(t('settings.mod_tts_load_error'), true);
    }
}

function renderModeratorTTSPolicy() {
    const source = $('modTTSSource')?.value;
    if (!source) return;
    const policy = (_modTTSAdminPolicy.policies || []).find(item => item.source === source) || {};
    $('modTTSRole').value = policy.allowed_role || (source === 'twitch_moderator_message' ? 'moderator' : 'owner');
    $('modTTSDefaultAlias').value = policy.default_alias || '';
    $('modTTSPolicyEnabled').checked = !!policy.enabled;
    $('modTTSVoiceChoice').checked = !!policy.allow_voice_choice;
    $('modTTSCooldown').value = policy.cooldown_sec ?? 5;
    $('modTTSRate').value = policy.max_per_minute ?? 5;
    $('modTTSMaxLength').value = policy.max_length ?? 300;
    $('modTTSBlacklist').value = policy.blacklist || '';
}

async function saveModeratorTTSVoice() {
    const scope = modTTSScope();
    const alias = $('modTTSAlias').value.trim().toLowerCase();
    if (!scope || !alias) return modTTSStatus(t('settings.mod_tts_invalid_input'), true);
    const url = `/api/accounts/${scope.accountId}/channels/${encodeURIComponent(scope.channel)}/tts-voice-policy/aliases/${encodeURIComponent(alias)}`;
    try {
        const result = await api(url, jopts('PUT', {provider: $('modTTSProvider').value.trim(), voice_id: $('modTTSVoiceId').value.trim()}));
        if (!result.ok) throw new Error(result.error);
        $('modTTSAlias').value = ''; $('modTTSVoiceId').value = '';
        await loadModeratorTTSScope();
    } catch (e) { modTTSStatus(`${t('settings.mod_tts_save_error')}: ${e.message}`, true); }
}

async function saveModeratorTTSPolicy() {
    const scope = modTTSScope();
    const source = $('modTTSSource').value;
    if (!scope) return;
    const body = {
        allowed_role: $('modTTSRole').value, default_alias: $('modTTSDefaultAlias').value,
        enabled: $('modTTSPolicyEnabled').checked, allow_voice_choice: $('modTTSVoiceChoice').checked,
        cooldown_sec: Number($('modTTSCooldown').value), max_per_minute: Number($('modTTSRate').value),
        max_length: Number($('modTTSMaxLength').value), blacklist: $('modTTSBlacklist').value,
    };
    const url = `/api/accounts/${scope.accountId}/channels/${encodeURIComponent(scope.channel)}/tts-voice-policy/sources/${source}`;
    try {
        const result = await api(url, jopts('PUT', body));
        if (!result.ok) throw new Error(result.error);
        await loadModeratorTTSScope();
    } catch (e) { modTTSStatus(`${t('settings.mod_tts_save_error')}: ${e.message}`, true); }
}

function moderatorTTSPermissions() {
    return [...document.querySelectorAll('#modTTSPermissions input:checked')].map(input => input.value);
}

async function saveModeratorTTSGrant(enabled) {
    const scope = modTTSScope();
    const userId = $('modTTSUserId').value.trim();
    if (!scope || !/^\d{1,32}$/.test(userId)) return modTTSStatus(t('settings.mod_tts_invalid_user'), true);
    const base = `/api/moderator-console/admin/accounts/${scope.accountId}/channels/${encodeURIComponent(scope.channel)}/grants/${userId}`;
    try {
        const result = await api(base, jopts('PUT', {twitch_user_id: userId, twitch_login: $('modTTSLogin').value.trim(), permissions: moderatorTTSPermissions(), enabled}));
        if (!result.ok) throw new Error(result.error);
        await loadModeratorTTSScope();
    } catch (e) { modTTSStatus(`${t('settings.mod_tts_save_error')}: ${e.message}`, true); }
}

function renderModeratorTTSGrants(grants) {
    $('modTTSGrantList').innerHTML = grants.map(grant => `<div class="flex gap-2 items-center flex-wrap mb-2">
        <b>${esc(grant.twitch_login || grant.twitch_user_id)}</b><span class="text-muted">${esc(grant.twitch_user_id)}</span>
        <span class="badge ${grant.enabled ? 'on' : 'off'}">${grant.enabled ? esc(t('settings.mod_tts_active')) : esc(t('settings.mod_tts_revoked'))}</span>
        <span class="text-xs text-muted">${grant.permissions.map(esc).join(', ')} · ${grant.active_sessions} ${esc(t('settings.mod_tts_sessions'))}</span>
        ${grant.enabled ? `<button class="btn btn-secondary btn-sm" onclick="createModeratorTTSInvite('${grant.twitch_user_id}')">${esc(t('settings.mod_tts_invite'))}</button>` : ''}
    </div>`).join('') || `<span class="text-muted">${esc(t('settings.mod_tts_no_grants'))}</span>`;
}

async function createModeratorTTSInvite(userId) {
    const scope = modTTSScope();
    if (!scope) return;
    const url = `/api/moderator-console/admin/accounts/${scope.accountId}/channels/${encodeURIComponent(scope.channel)}/grants/${userId}/invite`;
    try {
        const result = await api(url, jopts('POST', {ttl_minutes: 15}));
        if (!result.ok) throw new Error(result.error);
        const inviteUrl = `${location.origin}/moderator-console#invite=${encodeURIComponent(result.invite_token)}`;
        $('modTTSInviteResult').innerHTML = `<label class="text-xs text-muted">${esc(t('settings.mod_tts_one_time_link'))}</label><div class="flex gap-2"><input class="input" readonly value="${esc(inviteUrl)}"><button class="btn btn-secondary btn-sm" onclick="navigator.clipboard.writeText(this.previousElementSibling.value)">${esc(t('widgets.copy_url'))}</button></div>`;
    } catch (e) { modTTSStatus(`${t('settings.mod_tts_save_error')}: ${e.message}`, true); }
}

async function saveModeratorTTSChat() {
    const scope = modTTSScope();
    if (!scope) return;
    const url = `/api/moderator-console/admin/accounts/${scope.accountId}/channels/${encodeURIComponent(scope.channel)}/chat-tts`;
    try {
        const result = await api(url, jopts('PUT', {enabled: $('modTTSChatEnabled').checked, command_alias: $('modTTSChatAlias').value.trim()}));
        if (!result.ok) throw new Error(result.error);
        await loadModeratorTTSScope();
    } catch (e) { modTTSStatus(`${t('settings.mod_tts_save_error')}: ${e.message}`, true); }
}

let modMediaRevealTimer = null;
let modMediaRevealedUrl = '';
let modMediaTokenConfigured = false;

function hideModeratorMediaToken(messageKey = '') {
    if (modMediaRevealTimer) clearTimeout(modMediaRevealTimer);
    modMediaRevealTimer = null;
    modMediaRevealedUrl = '';
    const input = $('modMediaObsUrl');
    if (input) { input.type = 'password'; input.value = modMediaTokenConfigured ? '••••••••' : ''; }
    $('modMediaCopy')?.classList.add('hidden');
    if (messageKey && $('modMediaTokenStatus')) $('modMediaTokenStatus').textContent = t(messageKey);
}

function showModeratorMediaToken(url) {
    hideModeratorMediaToken();
    modMediaTokenConfigured = true;
    modMediaRevealedUrl = url;
    const input = $('modMediaObsUrl');
    input.type = 'text'; input.value = url;
    $('modMediaCopy').classList.remove('hidden');
    $('modMediaTokenStatus').textContent = t('settings.mod_media_revealed');
    modMediaRevealTimer = setTimeout(() => hideModeratorMediaToken('settings.mod_media_hidden'), 30000);
}

async function loadModeratorMediaTokenStatus() {
    const scope = modTTSScope(); if (!scope) return;
    hideModeratorMediaToken();
    const data = await api(`/api/moderator-media/admin/${scope.accountId}/${encodeURIComponent(scope.channel)}/token`);
    modMediaTokenConfigured = !!data.configured;
    $('modMediaReveal').disabled = !data.reveal_available;
    const key = data.rotation_required ? 'settings.mod_media_rotation_required' : data.configured ? 'settings.mod_media_hidden' : 'settings.mod_media_obs_missing';
    hideModeratorMediaToken(key);
}

async function loadModeratorMediaAdmin() {
    const scope = modTTSScope(); if (!scope) return;
    const [data] = await Promise.all([
        api(`/api/moderator-media/admin/${scope.accountId}/${encodeURIComponent(scope.channel)}/library`),
        loadModeratorMediaTokenStatus(),
    ]);
    $('modMediaLibrary').innerHTML = (data.items || []).map(item => `<label class="flex gap-2 items-center mb-1"><input type="checkbox" ${item.approved ? 'checked' : ''} onchange="approveModeratorMedia(${item.id},this.checked)"><span>${esc(item.name)} · ${esc(item.mime)}</span></label>`).join('') || `<span class="text-muted">${esc(t('settings.mod_media_empty'))}</span>`;
}

async function uploadModeratorMedia() {
    const scope = modTTSScope(), file = $('modMediaFile')?.files?.[0]; if (!scope || !file) return;
    const form = new FormData(); form.append('file', file);
    const response = await fetch(`${API}/api/moderator-media/admin/${scope.accountId}/${encodeURIComponent(scope.channel)}/library`, {method:'POST', body:form});
    if (!response.ok) return modTTSStatus(`${t('settings.mod_tts_save_error')}: ${await response.text()}`, true);
    $('modMediaFile').value = ''; await loadModeratorMediaAdmin();
}

async function approveModeratorMedia(id, approved) {
    const scope = modTTSScope(); if (!scope) return;
    await api(`/api/moderator-media/admin/${scope.accountId}/${encodeURIComponent(scope.channel)}/library/${id}`, jopts('PUT', {approved}));
    await loadModeratorMediaAdmin();
}

async function saveModeratorMediaConfig() {
    const scope = modTTSScope(); if (!scope) return;
    await api(`/api/moderator-media/admin/${scope.accountId}/${encodeURIComponent(scope.channel)}/config`, jopts('PUT', {queue_policy:$('modMediaQueuePolicy').value,position:$('modMediaPosition').value,width_pct:Number($('modMediaWidth').value),duration_ms:Number($('modMediaDuration').value),fade_ms:Number($('modMediaFade').value)}));
    modTTSStatus(t('settings.mod_tts_loaded'));
}

async function controlModeratorMedia(action, enabled = false) {
    const scope = modTTSScope(); if (!scope) return;
    const result = await api(`/api/moderator-media/admin/${scope.accountId}/${encodeURIComponent(scope.channel)}/control`, jopts('POST', {action, enabled}));
    $('modMediaKill').checked = !!result.state?.kill_switch;
}

async function rotateModeratorMediaToken() {
    const scope = modTTSScope(); if (!scope) return;
    if (!confirm(t('settings.mod_media_rotate_confirm'))) return;
    const result = await api(`/api/moderator-media/admin/${scope.accountId}/${encodeURIComponent(scope.channel)}/token`, jopts('POST', {}));
    $('modMediaReveal').disabled = false;
    showModeratorMediaToken(`${location.origin}${result.url}`);
}

async function revealModeratorMediaToken() {
    const scope = modTTSScope(); if (!scope) return;
    try {
        const result = await api(`/api/moderator-media/admin/${scope.accountId}/${encodeURIComponent(scope.channel)}/token/reveal`, jopts('POST', {}));
        showModeratorMediaToken(`${location.origin}${result.url}`);
    } catch (error) {
        hideModeratorMediaToken('settings.mod_media_reveal_error');
    }
}

async function copyModeratorMediaToken() {
    if (!modMediaRevealedUrl) return;
    try {
        await navigator.clipboard.writeText(modMediaRevealedUrl);
        $('modMediaTokenStatus').textContent = t('settings.mod_media_copied');
    } catch (error) {
        $('modMediaTokenStatus').textContent = t('settings.mod_media_copy_error');
    }
}

async function loadModeratorSoundAdmin() {
    const scope = modTTSScope(); if (!scope) return;
    const data = await api(`/api/moderator-console/admin/sounds/accounts/${scope.accountId}/channels/${encodeURIComponent(scope.channel)}`);
    $('modSoundEnabled').checked = !!data.policy.enabled; $('modSoundCooldown').value = data.policy.cooldown_sec; $('modSoundRate').value = data.policy.max_per_minute;
    $('modSoundLibrary').innerHTML = (data.tracks || []).map(track => `<label class="flex gap-2 items-center mb-1"><input type="checkbox" ${track.approved ? 'checked' : ''} onchange="approveModeratorSound(${track.id},this.checked)"><span>${esc(track.name)} · ${esc(track.mime)}</span></label>`).join('') || `<span class="text-muted">${esc(t('settings.mod_sound_empty'))}</span>`;
    $('modSoundObsStatus').textContent = t(data.obs_configured ? 'settings.mod_sound_obs_configured' : 'settings.mod_sound_obs_missing');
    $('modSoundObsUrl').innerHTML = '';
}

async function approveModeratorSound(id, enabled) {
    const scope = modTTSScope(); if (!scope) return;
    await api(`/api/moderator-console/admin/sounds/accounts/${scope.accountId}/channels/${encodeURIComponent(scope.channel)}/tracks/${id}`, jopts('PUT', {enabled}));
    await loadModeratorSoundAdmin();
}

async function saveModeratorSoundPolicy() {
    const scope = modTTSScope(); if (!scope) return;
    await api(`/api/moderator-console/admin/sounds/accounts/${scope.accountId}/channels/${encodeURIComponent(scope.channel)}/policy`, jopts('PUT', {enabled:$('modSoundEnabled').checked,cooldown_sec:Number($('modSoundCooldown').value),max_per_minute:Number($('modSoundRate').value)}));
    await loadModeratorSoundAdmin();
}

async function rotateModeratorSoundObsToken() {
    const scope = modTTSScope(); if (!scope) return;
    const data = await api(`/api/moderator-console/admin/sounds/accounts/${scope.accountId}/channels/${encodeURIComponent(scope.channel)}/obs-token`, jopts('POST', {}));
    const url = `${location.origin}${data.widget_url}`;
    $('modSoundObsStatus').textContent = t('settings.mod_sound_obs_configured');
    $('modSoundObsUrl').innerHTML = `<div class="flex gap-2"><input class="input" readonly value="${esc(url)}"><button class="btn btn-secondary btn-sm" onclick="navigator.clipboard.writeText(this.previousElementSibling.value)">${esc(t('widgets.copy_url'))}</button></div>`;
}

async function loadModeratorTTSOutput() {
    const scope = modTTSScope(); if (!scope) return;
    const data = await api(`/api/tts-audio-output/${scope.accountId}/${encodeURIComponent(scope.channel)}`);
    $('modTTSOutput').value = data.source || 'tts-bot';
    $('modTTSOutputWarning').style.color = data.configured ? '' : 'var(--warning)';
}

async function saveModeratorTTSOutput() {
    const scope = modTTSScope(); if (!scope) return;
    await api(`/api/tts-audio-output/${scope.accountId}/${encodeURIComponent(scope.channel)}`, jopts('PUT', {source:$('modTTSOutput').value}));
    await loadModeratorTTSOutput();
}

async function testModeratorTTSOutput() {
    const scope = modTTSScope(); if (!scope) return;
    await saveModeratorTTSOutput();
    const result = await api(`/api/tts-audio-output/${scope.accountId}/${encodeURIComponent(scope.channel)}/test`, jopts('POST', {text:t('settings.tts_output_test_text')}));
    modTTSStatus(`${result.status}: ${result.source} · ${result.telemetry}`);
}

const TTS_SOURCE_KEYS = {
    bot_reply: 'settings.tts_source_bot',
    voice_companion_reply: 'settings.tts_source_companion',
    moderation_announcement: 'settings.tts_source_mod_announcement',
    twitch_moderator_message: 'settings.tts_source_twitch_mod',
    ordinary_chat: 'settings.tts_source_chat',
    channel_points_reward: 'settings.tts_source_reward',
};

function ttsPolicyText(row) {
    const p = row.policy || {};
    const legacyScope = row.source === 'channel_points_reward' && p.storage === 'legacy_per_account'
        ? ` · ${t('settings.tts_policy_legacy_account')}` : '';
    if (!p.enabled) {
        if (p.channel_muted) return t('settings.tts_policy_channel_muted') + legacyScope;
        if (p.reason === 'not_automatically_spoken') return t('settings.tts_policy_not_spoken');
        return t('settings.tts_policy_off') + legacyScope;
    }
    if (row.source === 'bot_reply' || row.source === 'voice_companion_reply') {
        return t('settings.tts_policy_percent', { percent: p.reply_percent });
    }
    if (row.source === 'channel_points_reward') {
        const policy = p.reward_names ? t('settings.tts_policy_rewards', { rewards: p.reward_names }) : t('settings.tts_policy_any_reward');
        return policy + legacyScope;
    }
    return t('settings.tts_policy_on');
}

function ttsVoiceText(voice) {
    if (!voice) return t('settings.tts_voice_unassigned');
    const inherited = voice.inherited ? ` · ${t('settings.tts_voice_inherited')}` : '';
    const warning = voice.resolution === 'unknown_id' ? ` ⚠ ${t('settings.tts_voice_unknown')}`
        : (voice.resolution === 'browser_voice_unverified' ? ` · ${t('settings.tts_voice_browser')}` : '');
    return `${esc(voice.provider)} / ${esc(voice.label)}${inherited}${warning}`;
}

async function loadTTSRoutingMap() {
    const box = $('ttsRoutingMap');
    if (!box) return;
    try {
        const data = await api('/api/tts/routing-map');
        const rows = Array.isArray(data.rows) ? data.rows : [];
        if (!rows.length) {
            box.innerHTML = `<div class="empty-state">${esc(t('settings.tts_map_empty'))}</div>`;
            return;
        }
        box.innerHTML = `<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse">
            <thead><tr><th>${esc(t('settings.tts_col_scope'))}</th><th>${esc(t('settings.tts_col_source'))}</th><th>${esc(t('settings.tts_col_policy'))}</th><th>${esc(t('settings.tts_col_voice'))}</th><th>${esc(t('settings.tts_col_output'))}</th></tr></thead>
            <tbody>${rows.map(row => `<tr style="border-top:1px solid var(--border-light)">
                <td class="py-1.5 pr-2"><b>${esc(row.account.nickname)}</b><br><span class="text-muted">#${esc(row.channel)}</span></td>
                <td class="py-1.5 pr-2">${esc(t(TTS_SOURCE_KEYS[row.source] || row.source))}</td>
                <td class="py-1.5 pr-2"><span class="badge ${row.policy.enabled ? 'on' : 'off'}">${esc(ttsPolicyText(row))}</span></td>
                <td class="py-1.5 pr-2">${ttsVoiceText(row.voice)}</td>
                <td class="py-1.5 text-muted">${esc(t('settings.tts_output_unverified'))}<br><span class="text-xs">${esc((row.obs_output.audio_consumers || []).join(', '))}</span></td>
            </tr>`).join('')}</tbody></table></div>`;
    } catch (e) {
        box.innerHTML = `<div class="text-sm" style="color:var(--danger)">${esc(t('settings.tts_map_error'))}</div>`;
    }
}

async function loadProviderStatus() {
    const summary = $('providerStatusSummary');
    const grid = $('providerStatusGrid');
    if (!summary || !grid) return;
    try {
        const status = await api('/api/providers/status');
        const ai = Object.entries(status.ai || {}).map(([name, item]) => ({name, configured: item.configured, model: item.model, state: item.state}));
        const tts = Object.entries(status.tts || {}).filter(([name]) => name.endsWith('_configured') || name.endsWith('_available')).map(([name, value]) => ({name: name.replace(/_(configured|available)$/, ''), configured: !!value}));
        const all = [...ai, ...tts, {name: 'twitch', configured: !!status.twitch?.helix_configured}];
        summary.textContent = t('label.status_checked_note');
        grid.innerHTML = all.map(item => `<div class="provider-status-item ${item.configured && item.state !== 'paused' ? '' : 'is-cooldown'}">
            <div class="provider-status-name">${item.state === 'paused' ? '🟡' : item.configured ? '🟢' : '🔴'} ${esc(item.name)}</div>
            <div class="provider-status-meta">${item.state === 'paused' ? t('status.ai_paused_short') : item.configured ? t('status.configured') : t('status.not_configured')}${item.model ? ` · ${esc(item.model)}` : ''}</div>
            <div class="flex gap-1 mt-2">
                <button class="btn btn-secondary btn-sm flex-1" onclick="testProvider('${esc(item.name)}', this)">${t('btn.test')}</button>
                <button class="btn btn-secondary btn-sm flex-1" onclick="configureProvider('${esc(item.name)}')">${t('btn.configure_short')}</button>
            </div>
        </div>`).join('');
    } catch (e) {
        summary.textContent = t('toast.status_unavailable', {detail: e.message});
        grid.innerHTML = '';
    }
}

function configureProvider(name) {
    // §25.3: «Настроить» у карточки провайдера — прыжок к соответствующим полям
    const map = {
        openrouter: 'globalAIProvider', gemini: 'globalAIProvider', openai: 'globalAIProvider',
        anthropic: 'globalAIProvider', ollama: 'globalAIProvider',
        twitch: 'twitchClientID',
        // Q16 F3: TTS-провайдеры настраиваются у бота
        web_speech: 'botTTSProvider', piper: 'botTTSProvider', elevenlabs: 'botTTSProvider',
    };
    const n = String(name || '');
    if (n.startsWith('custom:')) {
        const el0 = $('customProvidersCard');
        if (el0) { el0.scrollIntoView({ behavior: 'smooth', block: 'center' }); el0.classList.add('flash-highlight'); setTimeout(() => el0.classList.remove('flash-highlight'), 1600); }
        return;
    }
    const targetId = map[n.toLowerCase()] || 'globalAIProvider';
    const el = $(targetId);
    if (!el) return;
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.classList.add('flash-highlight');
    setTimeout(() => el.classList.remove('flash-highlight'), 1600);
    el.focus?.();
}

async function loadOfflineMode() {
    try {
        const cfg = await api('/api/offline/config');
        const toggle = $('offlineModeToggle');
        const status = $('offlineModeStatus');
        toggle?.classList.toggle('active', !!cfg.enabled);
        if (status) { status.className = `badge ${cfg.enabled ? 'on' : 'off'}`; status.textContent = cfg.enabled ? t('status.offline_enabled') : t('status.offline_disabled'); }
    } catch (e) { console.warn('offline config', e); }
}
async function toggleOfflineMode() {
    const enabled = !$('offlineModeToggle')?.classList.contains('active');
    try { await api('/api/offline/config', jopts('PUT', {enabled})); await loadOfflineMode(); await loadProviderStatus(); toast(enabled ? t('status.offline_enabled') : t('status.offline_disabled'), 'success'); }
    catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}
async function testOfflineMode() {
    try {
        const results = await Promise.all(['ollama', 'piper'].map(provider => api('/api/providers/test', jopts('POST', {provider}))));
        const failed = results.filter(result => !result.ok);
        toast(failed.length ? t('toast.local_services_not_ready', {count: failed.length}) : t('toast.local_services_ready'), failed.length ? 'error' : 'success');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function testProvider(provider, button) {
    const original = button.textContent;
    button.disabled = true; button.textContent = t('toast.checking');
    try {
        const result = await api('/api/providers/test', jopts('POST', {provider}));
        toast(result.ok ? `${provider}: OK` : `${provider}: ${result.error || t('toast.unknown_error')}`, result.ok ? 'success' : 'error');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
    finally { button.disabled = false; button.textContent = original; }
}
async function testAllProviders() {
    try {
        const status = await api('/api/providers/status');
        const names = [...Object.keys(status.ai || {}), 'twitch', 'web_speech', 'piper', 'elevenlabs'];
        const results = await Promise.all(names.map(provider => api('/api/providers/test', jopts('POST', {provider}))));
        const failed = results.filter(result => !result.ok);
        toast(failed.length ? t('toast.providers_check_done', {count: failed.length}) : t('toast.providers_all_ready'), failed.length ? 'error' : 'success');
        loadProviderStatus();
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function saveGlobalAI() {
    const data = { provider: $('globalAIProvider').value };
    const fields = AI_PROVIDER_FIELDS[data.provider] || [];
    fields.forEach(f => {
        const el = $('ai_' + f.key);
        if (!el) return;
        const v = el.value;
        if (f.key.endsWith('_key')) { if (v.trim()) data[f.key] = v.trim(); }
        else data[f.key] = v;
    });
    data.global_vision_override = $('globalVisionModel')?.value.trim() || '';
    try {
        _aiConfig = await api('/api/ai/config', jopts('PUT', data));
        toast(t('toast.ai_settings_saved'), 'success');
        renderAIProviderFields();
        clearDirty('globalAI'); // P8-C13
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function testGlobalAI() {
    toast(t('toast.checking_connection'), 'info');
    const statusEl = $('globalAiTestStatus');
    if (statusEl) statusEl.innerHTML = `<span class="text-muted">⏳ ${esc(t('toast.checking_connection'))}</span>`;
    try {
        const prov = $('globalAIProvider')?.value;
        const res = await api('/api/ai/test', jopts('POST', { provider: prov }));
        if (res.ok) {
            const timeStr = res.latency_ms ? ` (${res.latency_ms} ms)` : '';
            const modelStr = res.model ? ` [${res.model}]` : '';
            toast(t('toast.ai_connected') + timeStr, 'success');
            if (statusEl) statusEl.innerHTML = `<span style="color:var(--success,#2ecc71)">🟢 OK${esc(timeStr)}${esc(modelStr)}</span>`;
        } else {
            toast(t('toast.ai_error', { detail: res.error || 'неизвестно' }), 'error');
            if (statusEl) statusEl.innerHTML = `<span class="text-error">🔴 ${esc(res.error || 'error')}</span>`;
        }
    } catch (e) {
        toast(t('toast.error_detail', { detail: e.message }), 'error');
        if (statusEl) statusEl.innerHTML = `<span class="text-error">🔴 ${esc(e.message)}</span>`;
    }
}

// Q16 F3: сохранение глобальной TTS-формы удалено. Endpoint /api/tts/config остался:
// PUT использует онбординг, tts_settings — legacy-fallback рантайма.

// §3 PLAN_CURRENT: проверка подключения к Twitch через /api/stream-tools/check-connection
// P8-A4: честный вывод шага ошибки (сеть / Client ID / токен) — тост + строка-результат
async function checkTwitchConnection() {
    const el = $('twitchCheckResult');
    if (!el) return;
    toast(t('toast.checking_connection'), 'info');
    el.innerHTML = `<span class="text-muted">${esc(t('label.runtime_check'))}</span>`;
    try {
        // нужен account_id включённого бота — берём первый включённый
        const bots = await api('/api/accounts');
        const acc = bots.find(a => a.enabled) || bots[0];
        if (!acc) throw new Error(t('bots.empty'));
        const res = await api(`/api/stream-tools/check-connection?account_id=${acc.id}`);
        if (res.ok) {
            el.innerHTML = `<span style="color:var(--success,#2ecc71)">✅ ${esc(t('settings.twitch_check_ok', { name: res.display_name || res.login || '' }))}</span>`;
            toast(t('settings.twitch_check_ok', { name: res.display_name || res.login || '' }), 'success');
        } else {
            const title = res.error || '';
            const detail = res.message || '';
            el.innerHTML = `<span class="text-error">❌ ${esc(title)}</span>`
                + (detail ? `<div class="text-xs text-muted mt-1">${esc(detail)}</div>` : '')
                + (res.help_url ? ` <a href="${esc(res.help_url)}" target="_blank" rel="noopener" class="text-xs">dev.twitch.tv/console</a>` : '');
            toast(t('toast.error_detail', { detail: title }), 'error');
        }
    } catch (e) {
        const p = e.payload || {};
        const title = p.error || e.message;
        const detail = p.message || '';
        el.innerHTML = `<span class="text-error">❌ ${esc(title)}</span>`
            + (detail && detail !== title ? `<div class="text-xs text-muted mt-1">${esc(detail)}</div>` : '')
            + (p.help_url ? ` <a href="${esc(p.help_url)}" target="_blank" rel="noopener" class="text-xs">dev.twitch.tv/console</a>` : '');
        toast(t('toast.error_detail', { detail: title }), 'error');
    }
}

async function saveTwitchApp() {
    const data = {};
    const cid = $('twitchClientID').value.trim();
    const csec = $('twitchClientSecret').value.trim();
    if (cid) data.client_id = cid;
    if (csec) data.client_secret = csec;
    if (!Object.keys(data).length) { toast(t('toast.no_changes'), 'info'); return; }
    try {
        await api('/api/settings/twitch-credentials', jopts('PUT', data));
        toast(t('toast.twitch_app_saved'), 'success');
        clearDirty('twitchApp'); // P8-C13
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function saveTokenRefreshSettings() {
    try {
        await api('/api/settings/auto-refresh', jopts('PUT', {
            auto_refresh: $('autoRefreshTokens').checked,
            warning_days: Number($('tokenExpiryWarningDays').value || 7),
        }));
        toast(t('token.settings_saved'), 'success');
        clearDirty('tokenRefresh');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

function downloadBackup() {
    window.location.href = API + '/api/backup/download';
    toast('Подготовка zip-бэкапа...', 'info');
}

function downloadDatabase() {
    window.location.href = API + '/api/backup/download-db';
    toast('Скачивание актуального bot.db...', 'info');
}

// OPS_PLAN §4: БД — статистика + кнопка «Оптимизировать» (PRAGMA optimize + VACUUM)
// OPS_PLAN §5: версия приложения в footer (GET /api/version)
async function loadAppVersion() {
    try {
        const v = await api('/api/version');
        const el = $('appVersionBadge');
        if (el && v && v.label) el.textContent = v.label;
    } catch (e) { /* оставляем хардкод из шаблона */ }
}

function _fmtBytes(n) {
    if (!n && n !== 0) return '?';
    if (n < 1024) return n + ' Б';
    if (n < 1048576) return (n / 1024).toFixed(1) + ' КБ';
    return (n / 1048576).toFixed(1) + ' МБ';
}

async function refreshDbStats() {
    const el = $('dbStatsInfo');
    if (!el) return;
    try {
        const st = await api('/api/maintenance/db-stats');
        const lines = [];
        lines.push(t('label.db_size') + ' ' + _fmtBytes(st.size_bytes));
        const counts = st.counts || {};
        const recs = Object.entries(counts)
            .filter(([, v]) => v >= 0)
            .map(([k, v]) => `${k}: ${v}`)
            .join(', ');
        lines.push(t('label.db_records') + ' ' + (recs || '—'));
        if (st.retention_days > 0) lines.push('retention: ' + st.retention_days + ' d');
        el.textContent = lines.join('\n');
    } catch (e) { el.textContent = '—'; }
}

async function optimizeDatabase() {
    try {
        const r = await api('/api/maintenance/optimize', { method: 'POST' });
        if (r && r.ok) {
            toast(t('msg.db_optimized'), 'success');
            refreshDbStats();
        } else {
            toast((r && r.error) || t('msg.error'), 'error');
        }
    } catch (e) { toast(t('msg.error'), 'error'); }
}

async function cleanupDatabaseLogs() {
    const daysStr = window.prompt(t('prompt.cleanup_logs_days') || 'Удалить логи старше скольких дней? (по умолчанию 30):', '30');
    if (!daysStr) return;
    const days = parseInt(daysStr, 10);
    if (isNaN(days) || days <= 0) {
        toast(t('toast.invalid_days') || 'Укажите положительное число дней', 'error');
        return;
    }
    try {
        const res = await api('/api/maintenance/cleanup', jopts('POST', { days }));
        if (res && res.ok) {
            const tmpl = t('msg.logs_cleaned') || 'Очищено {count} старых записей логов.';
            toast(tmpl.replace('{count}', res.total_deleted || 0), 'success');
            refreshDbStats();
        } else {
            toast((res && res.error) || t('msg.error'), 'error');
        }
    } catch (e) {
        toast(t('msg.error') + ': ' + (e.message || e), 'error');
    }
}

async function uploadBackup(event) {
    const file = event.target.files[0];
    if (!file) return;
    if (!confirm(t('confirm.restore_backup'))) return;
    const fd = new FormData();
    fd.append('file', file);
    try {
        const res = await fetch(API + '/api/backup/restore', { method: 'POST', body: fd });
        const j = await res.json();
        if (j.ok) { toast(t('toast.backup_restored'), 'success'); location.reload(); }
        else toast(t('toast.restore_error'), 'error');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

function copyText(id) {
    const text = $(id).textContent;
    navigator.clipboard.writeText(text).then(() => toast(t('toast.copied'), 'success'));
}

// ── Uptime ──────────────────────────────────────────
const _startTime = Date.now();
setInterval(() => {
    const el = $('uptimeDisplay');
    if (!el) return;
    const s = Math.floor((Date.now() - _startTime) / 1000);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
    el.textContent = h > 0 ? t('ui.uptime_hours', {h, m}) : t('ui.uptime_minutes', {m, s: s % 60});
}, 1000);

// ── Init ────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    enforcePanelDarkTheme();

    // версия в footer (OPS_PLAN §5)
    loadAppVersion();

    // язык
    initLang();
    localizeLegacyNodes();
    initBgPreset();

    // секція з hash
    const hash = (location.hash || '').replace('#', '');
    const valid = ['dashboard', 'bots', 'chat', 'analytics', 'settings', 'widgets', 'chatlogger', 'channels', 'director', 'calendar'];
    showSection(valid.includes(hash) ? hash : 'dashboard');

    // Ctrl+K — фокус на пошук
    document.addEventListener('keydown', (e) => {
        if (e.defaultPrevented || e.target.closest?.('[role="dialog"]')) return;
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
            e.preventDefault();
            $('globalSearch').focus();
        }
    });

    // пресети характеру для дропдауну
    api('/api/persona-presets').then(data => {
        const sel = $('personaPreset');
        if (sel && data.presets) {
            sel.innerHTML = `<option value="">${esc(t('persona.preset_placeholder'))}</option>` +
                data.presets.map(p => {
                    const key = `persona.preset.${p.id}`;
                    const name = hasTranslation(key) ? t(key) : (p.label || p.id);
                    return `<option value="${esc(p.id)}">${esc(name)} — ${esc(p.description || '')}</option>`;
                }).join('');
        }
    }).catch(() => {});

    connectWS();
});

// ── Авто-приглушение TTS (Ducking & Речь стримера) ──

const _EVENT_KIND_LABELS = {
    subscribe: '🌟 Подписка (Sub)',
    cheer: '💎 Биты (Cheer / Bits)',
    raid: '🚀 Рейд (Raid)',
    redemption: '🎁 Баллы канала (Redemption)',
    follow: '👤 Фоллоу (Follow)',
};

let _ttsDuckData = null;

async function loadTtsDuckingSettings() {
    const list = $('ttsDuckEventsList');
    if (!list) return;
    try {
        const res = await api('/api/tts/duck-settings');
        if (!res || !res.ok) return;
        _ttsDuckData = res;

        if ($('ttsDuckVolumePercent')) $('ttsDuckVolumePercent').value = String(res.streamer_duck_volume ?? 15);
        if ($('ttsDuckRecoveryMs')) $('ttsDuckRecoveryMs').value = String(res.streamer_duck_recovery_ms ?? 1200);

        const rows = res.settings || [];
        const streamerRow = rows.find(r => r.event_kind === 'streamer_speech');
        if ($('ttsDuckStreamerEnabled')) {
            $('ttsDuckStreamerEnabled').checked = streamerRow ? !!streamerRow.enabled : false;
        }

        const alertRows = rows.filter(r => r.event_kind !== 'streamer_speech');
        list.innerHTML = alertRows.map(r => {
            const label = _EVENT_KIND_LABELS[r.event_kind] || r.event_kind;
            return `
                <div class="flex items-center gap-3 bg-base-100 p-2 rounded" data-kind="${esc(r.event_kind)}">
                    <label class="flex items-center gap-2 text-sm flex-1">
                        <input type="checkbox" class="checkbox tts-duck-event-cb" ${r.enabled ? 'checked' : ''} data-kind="${esc(r.event_kind)}">
                        <span>${esc(label)}</span>
                    </label>
                    <div class="flex items-center gap-1 text-xs">
                        <span class="text-muted">Пауза:</span>
                        <input type="number" class="input input-sm field-80 tts-duck-event-dur" value="${esc(r.duration_ms || 0)}" min="0" max="60000" step="500" data-kind="${esc(r.event_kind)}">
                        <span class="text-muted">мс</span>
                    </div>
                </div>
            `;
        }).join('');
    } catch (e) {
        console.error('loadTtsDuckingSettings error', e);
    }
}

async function saveTtsDuckingSettings() {
    const btn = $('ttsDuckSaveBtn');
    const status = $('ttsDuckStatus');
    if (btn) btn.disabled = true;
    if (status) status.textContent = 'Сохранение...';

    try {
        const settings = [];
        const streamerEnabled = $('ttsDuckStreamerEnabled')?.checked ? 1 : 0;
        settings.push({
            event_kind: 'streamer_speech',
            enabled: streamerEnabled,
            duration_ms: 2000,
        });

        document.querySelectorAll('.tts-duck-event-cb').forEach(cb => {
            const kind = cb.dataset.kind;
            const durInput = document.querySelector(`.tts-duck-event-dur[data-kind="${kind}"]`);
            const dur = parseInt(durInput?.value || '0', 10);
            settings.push({
                event_kind: kind,
                enabled: cb.checked ? 1 : 0,
                duration_ms: dur,
            });
        });

        const vol = parseInt($('ttsDuckVolumePercent')?.value || '15', 10);
        const rec = parseInt($('ttsDuckRecoveryMs')?.value || '1200', 10);

        const res = await api('/api/tts/duck-settings', jopts('PUT', {
            settings,
            streamer_duck_volume: vol,
            streamer_duck_recovery_ms: rec,
        }));

        if (res && res.ok) {
            toast('Настройки приглушения TTS сохранены', 'success');
            if (status) status.textContent = '✓ Сохранено';
            setTimeout(() => { if (status) status.textContent = ''; }, 3000);
        } else {
            toast('Ошибка сохранения настроек Ducking', 'error');
            if (status) status.textContent = 'Ошибка';
        }
    } catch (e) {
        toast(`Ошибка: ${e.message}`, 'error');
        if (status) status.textContent = 'Ошибка';
    } finally {
        if (btn) btn.disabled = false;
    }
}

async function testTtsDucking() {
    try {
        const res = await api('/api/tts/duck-test', jopts('POST', { duration_ms: 3000 }));
        if (res && res.ok) {
            toast('Сигнал Ducking (3 сек) отправлен в OBS виджеты', 'info');
        } else {
            toast(res?.error || 'Ошибка теста Ducking', 'error');
        }
    } catch (e) {
        toast(`Ошибка: ${e.message}`, 'error');
    }
}
