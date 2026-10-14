// [P5-split] 07_widgets.js ← static/app.js, исходные строки 5576–5997; грузится после предыдущего чанка, порядок = порядку строк

// ── Widgets Admin (§24: наполнение контентом OBS-виджетов) ──
async function wapi(url, method = 'GET', body) {
    return api(url, method === 'GET' ? undefined : jopts(method, body));
}

function widgetOutputUrl(path) {
    const url = new URL(path, location.origin);
    if (url.origin !== location.origin || !(url.pathname.startsWith('/widget/') || url.pathname === '/obs/tts')) return path;
    let lang = 'ru';
    try { lang = localStorage.getItem('lang') || 'ru'; } catch (_) {}
    url.searchParams.set('ui_lang', ['ru', 'en', 'ua'].includes(lang) ? lang : 'ru');
    return url.pathname + url.search + url.hash;
}

function waRefreshWidgetLocale() {
    document.querySelectorAll('iframe.widget-preview').forEach(frame => {
        const source = frame.getAttribute('src');
        if (!source) return;
        const localized = widgetOutputUrl(source);
        if (localized !== source) frame.setAttribute('src', localized);
    });
    document.querySelectorAll('[data-design-widget] [data-design-url]').forEach(input => {
        if (input.value) input.value = widgetOutputUrl(input.value);
    });
}

// ── Пер-виджетный скоуп: канал можно задать отдельно для каждого виджета ──
// Переопределение хранится в localStorage «widgetScopeOverrides» как
// {family: "account_id:channel"}; family — имя виджета из пути
// ('/widget/goals' → 'goals', '/api/widgets/goals' → 'goals'). Если
// переопределения нет — действует общий скоуп биндеров (waBindingScope).
function waWidgetFamily(path) {
    try {
        const u = new URL(path, location.origin);
        if (u.pathname.startsWith('/widget/')) return u.pathname.split('/')[2] || '';
        if (u.pathname.startsWith('/api/widgets/')) {
            const parts = u.pathname.split('/');
            if (parts[3] === 'public') return parts[4] || '';
            return parts[3] || '';
        }
    } catch (_) {}
    return '';
}

function waWidgetScopeOverrides() {
    try { return JSON.parse(localStorage.getItem('widgetScopeOverrides') || '{}'); } catch (_) { return {}; }
}

function waWidgetScopeOverrideFor(path) {
    const raw = waWidgetScopeOverrides()[waWidgetFamily(path)];
    if (!raw) return null;
    const sep = String(raw).indexOf(':');
    const account_id = parseInt(sep >= 0 ? String(raw).slice(0, sep) : '', 10) || 0;
    const channel = (sep >= 0 ? String(raw).slice(sep + 1) : '').trim().replace(/^#+/, '');
    if (!account_id || !channel) return null;
    return { account_id, channel };
}

// ── Q10a: channel-first скоуп — один селектор канала в шапке «Виджетов».
// Выбор хранится в localStorage «widgetChannelScope» как «account_id:channel»
// (account_id — первый подключённый бот канала). Per-widget override сильнее
// селектора (см. waWidgetStateUrl). До Q10a этой функции не существовало —
// действовали только пер-виджетные override, иначе был widget_scope_required.
function waChannelScopeStored() {
    try { return localStorage.getItem('widgetChannelScope') || ''; } catch (_) { return ''; }
}

function waChannelScopeMatch(items, saved) {
    if (!saved) return null;
    const exact = items.find(item => `${item.account_id}:${item.channel}` === saved);
    if (exact) return exact;
    const channel = String(saved).slice(String(saved).indexOf(':') + 1);
    return items.find(item => item.channel === channel) || null;
}

// Реализация waBindingScope() живёт в 13_widgets_session.js (грузится позже и
// нормализует channel через .toLowerCase() — здесь была устаревшая дублирующая
// копия без этой нормализации, которая никогда не выполнялась).

async function waLoadChannelScopeSelect() {
    const sel = $('waChannelScope');
    if (!sel) return;
    try {
        const data = await api('/api/channel-overview');
        const items = (data.channels || []).map(item => {
            const ch = (item.channel || '').replace(/^#/, '').toLowerCase();
            const bots = item.bots || [];
            // Q11a: бот-модератор канала подставляется сам (подключённый — первым);
            // кэш ботов нужен билдеру биндингов для ручного выбора при ≥2 модераторах
            window._waChannelScopeBots = window._waChannelScopeBots || {};
            window._waChannelScopeBots[ch] = bots;
            const bot = bots.find(b => b.connected && b.role === 'moderator')
                || bots.find(b => b.role === 'moderator')
                || bots.find(b => b.connected) || bots[0] || {};
            return { channel: ch, account_id: bot.account_id || 0 };
        }).filter(i => i.channel && i.account_id);
        const saved = waChannelScopeStored();
        sel.innerHTML = `<option value="" data-i18n="widgets.scope_demo">${esc(t('widgets.scope_demo'))}</option>` +
            items.map(i => `<option value="${esc(i.account_id)}:${esc(i.channel)}">#${esc(i.channel)}</option>`).join('');
        const matched = waChannelScopeMatch(items, saved);
        if (matched) {
            const value = `${matched.account_id}:${matched.channel}`;
            sel.value = value;
            // Бот канала мог измениться с момента прошлого выбора.
            if (value !== saved) localStorage.setItem('widgetChannelScope', value);
        } else if (saved) {
            localStorage.removeItem('widgetChannelScope');
        }
        waUpdateChannelScopeBadge();
    } catch (e) { /* некритично — остаётся демо-режим */ }
}

function waChannelScopeChanged() {
    const sel = $('waChannelScope');
    if (!sel) return;
    try {
        if (sel.value) localStorage.setItem('widgetChannelScope', sel.value);
        else localStorage.removeItem('widgetChannelScope');
    } catch (_) {}
    waUpdateChannelScopeBadge();
    loadWidgetsAdmin();
    waRefreshScopedWidgetPreviews();
}

function waUpdateChannelScopeBadge() {
    const badge = $('waChannelScopeBadge');
    if (!badge) return;
    const scope = waBindingScope();
    badge.textContent = scope.channel ? '#' + scope.channel : t('widgets.scope_demo');
}

function waWidgetStateUrl(path) {
    // Пер-виджетный override сильнее общего скоупа; иначе — как раньше.
    const scope = waWidgetScopeOverrideFor(path) ||
        (typeof waBindingScope === 'function' ? waBindingScope() : {});
    if (!scope.account_id || !scope.channel) throw new Error('widget_scope_required');
    const url = new URL(path, location.origin);
    url.searchParams.set('account_id', String(scope.account_id));
    url.searchParams.set('channel', scope.channel);
    return widgetOutputUrl(url.pathname + url.search);
}

// URL виджета «как получится»: со скоупом (общим или пер-виджетным), а если
// скоуп пуст — просто публичный URL виджета (для «↗ В новой вкладке»).
function waWidgetBestUrl(path) {
    try { return waWidgetStateUrl(path); } catch (e) { return widgetOutputUrl(path); }
}

async function wstateapi(path, method = 'GET', body) {
    // Q10b: без канала — демо-режим. GET не дёргает сеть (честный пустой/демо
    // контент вместо ошибки), записи просят выбрать канал. widget_scope_required
    // больше не показывается пользователю.
    const scope = waWidgetScopeOverrideFor(path) ||
        (typeof waBindingScope === 'function' ? waBindingScope() : {});
    if (!scope.account_id || !scope.channel) {
        if ((method || 'GET').toUpperCase() === 'GET') return { ok: true, demo: true };
        throw new Error(t('widgets.scope_demo'));
    }
    return wapi(waWidgetStateUrl(path), method, body);
}

const WA_SCOPED_WIDGET_PATHS = new Set([
    '/obs/tts', '/widget/goals', '/widget/sub-goal', '/widget/now-playing',
    '/widget/countdown', '/widget/lower-third', '/widget/clip-moments',
    '/widget/donation-challenge', '/widget/subathon-timer',
    '/widget/mascot', '/widget/chat-highlight', '/widget/chat-roulette',
    '/widget/song-request', '/widget/media-share', '/widget/schedule',
    '/widget/uptime', '/widget/follower-ticker', '/widget/top-donator',
    '/widget/latest-event-card', '/widget/tts-bot', '/widget/tts-chat-overlay',
    '/widget/hype-meter', '/widget/emoji-leaderboard', '/widget/chat-reader',
    '/widget/emoji-chat', '/widget/selected-chat', '/widget/mod-feed',
    '/widget/soundboard', '/widget/recent-events',
]);

function waCopyWidgetUrl(path) {
    const url = new URL(path, location.origin);
    // Q10b: без скоупа копируется публичный/demo-URL, а не падает
    copyWidgetUrl(WA_SCOPED_WIDGET_PATHS.has(url.pathname) ? waWidgetBestUrl(path) : path);
}

// ── Q16 F2 (DEC-OWNER-016): модалка-предупреждение Media Share убрана —
// в форме медиа-шары постоянная строка-подсказка (widgets.media_share_hint).
// Роуты /api/media-share/disclosure остаются legacy-контрактом (DEC-MEDIA-001).

Object.assign(LANGS.ru, {
    'widgets.media_share_hint': 'Media Share загружает YouTube IFrame API из сети: YouTube получает данные запроса и сведения браузера/OBS.',
});
Object.assign(LANGS.en, {
    'widgets.media_share_hint': 'Media Share loads the YouTube IFrame API over the network: YouTube receives request data and browser/OBS information.',
});
Object.assign(LANGS.ua, {
    'widgets.media_share_hint': 'Media Share завантажує YouTube IFrame API з мережі: YouTube отримує дані запиту та відомості браузера/OBS.',
});

function waRefreshScopedWidgetPreviews() {
    document.querySelectorAll('iframe.widget-preview').forEach(frame => {
        const original = frame.dataset.scopeBase || frame.getAttribute('src') || '';
        const url = new URL(original, location.origin);
        if (!WA_SCOPED_WIDGET_PATHS.has(url.pathname)) return;
        frame.dataset.scopeBase = original;
        // Q10b: без скоупа — демо-превью (?preview=1), а не старый URL прошлого канала
        try { frame.src = waWidgetStateUrl(url.pathname + url.search); }
        catch (e) { frame.src = widgetOutputUrl(url.pathname + '?preview=1'); }
    });
    const topDonatorUrl = $('waTdUrl');
    if (topDonatorUrl) {
        const period = $('waTdPeriod')?.value || 'alltime';
        try {
            topDonatorUrl.textContent = waWidgetStateUrl(`/widget/top-donator?period=${period}`);
        } catch (e) {
            topDonatorUrl.textContent = widgetOutputUrl(`/widget/top-donator?period=${period}&preview=1`);
        }
    }
}

function _waHint(err) {
    const el = $('widgetsAdminHint');
    if (el) {
        el.textContent = t('toast.error_detail', {detail: err.message || err});
        el.classList.remove('hidden');
        setTimeout(() => el.classList.add('hidden'), 5000);
    }
}

async function loadWidgetsAdmin() {
    if (!$('waGoalsList')) return;
    waInitDesignForms();
    waLoadChannelScopeSelect(); // Q10a: channel-first селектор в шапке «Виджетов»
    const loads = [waLoadGoals(), waLoadSubGoal(), waLoadNp(), waLoadSchedule(), waLoadCd(), waDonationChallengesLoad(), waLoadDonations(), waLoadSr(), waDesignLoad('chat-reader'), waDesignLoad('tts-raw'), waChatPanelLoad()];
    await Promise.allSettled(loads);
}

// ── Shared trusted chat list and selected-chat display ──
const _waChatDisplayFields = {
    max_messages: 'waChatMaxMessages', lifetime_sec: 'waChatLifetime',
    font_size: 'waChatFontSize', emote_size: 'waChatEmoteSize',
    history_limit: 'waChatHistoryLimit', history_minutes: 'waChatHistoryMinutes',
};

function waChatDisplayValues() {
    const values = {};
    Object.entries(_waChatDisplayFields).forEach(([key, id]) => { values[key] = Number($(id).value); });
    values.show_badges = $('waChatShowBadges').checked ? 1 : 0;
    return values;
}

function waChatDisplayPreview() {
    const frame = $('waChatOverlayPreview');
    if (!frame) return;
    const values = waChatDisplayValues();
    const url = new URL('/widget/selected-chat', location.origin);
    url.searchParams.set('preview', '1');
    url.searchParams.set('max', values.max_messages);
    url.searchParams.set('lifetime', values.lifetime_sec);
    url.searchParams.set('font_size', values.font_size);
    url.searchParams.set('emote_size', values.emote_size);
    url.searchParams.set('badges', values.show_badges);
    url.searchParams.set('history', values.history_limit);
    url.searchParams.set('history_minutes', values.history_minutes);
    frame.src = widgetOutputUrl(url.pathname + url.search);
}

async function waChatPanelLoad() {
    if (!$('waChatOverlayPanel')) return;
    try {
        if (!_allBots.length) {
            const accounts = await api('/api/accounts');
            _allBots = Array.isArray(accounts) ? accounts : (accounts.accounts || []);
        }
        $('waChatImportAccount').innerHTML = _allBots.map(account =>
            `<option value="${account.id}">${esc(account.nickname)}</option>`).join('');
        await waChatLoadChannels();
        const [trusted, display] = await Promise.all([
            wapi('/api/widgets/chat/trusted-users'),
            wapi('/api/widgets/chat/display/selected-chat'),
        ]);
        $('waChatTrustedUsers').value = (trusted.users || []).join('\n');
        Object.entries(display.settings || {}).forEach(([key, value]) => {
            const id = _waChatDisplayFields[key];
            if (id && $(id)) $(id).value = value;
        });
        $('waChatShowBadges').checked = Boolean(display.settings?.show_badges);
        document.querySelectorAll('#waChatOverlayPanel input').forEach(input => {
            if (input.dataset.chatPreviewBound) return;
            input.dataset.chatPreviewBound = '1';
            input.addEventListener('input', waChatDisplayPreview);
        });
        waChatDisplayPreview();
    } catch (e) { _waHint(e); }
}

async function waChatLoadChannels() {
    const accountId = $('waChatImportAccount')?.value;
    const select = $('waChatImportChannel');
    if (!accountId || !select) return;
    try {
        const channels = await api(`/api/accounts/${accountId}/channels`);
        select.innerHTML = (Array.isArray(channels) ? channels : (channels.channels || [])).map(channel =>
            `<option value="${esc(channel.channel_name)}">#${esc(channel.channel_name)}</option>`).join('');
    } catch (e) { _waHint(e); }
}

async function waChatTrustedSave() {
    try {
        const users = $('waChatTrustedUsers').value.split(/[\s,;]+/).filter(Boolean);
        const result = await wapi('/api/widgets/chat/trusted-users', 'PUT', {users});
        $('waChatTrustedUsers').value = result.users.join('\n');
        toast(t('msg.saved'), 'success');
    } catch (e) { _waHint(e); }
}

async function waChatImport(role) {
    try {
        const result = await wapi('/api/widgets/chat/trusted-users/import', 'POST', {
            role, account_id: Number($('waChatImportAccount').value), channel: $('waChatImportChannel').value,
        });
        $('waChatTrustedUsers').value = result.users.join('\n');
        toast(t('widgets.chat_imported', {count: result.imported}), 'success');
    } catch (e) {
        if (/^helix_(401|403)$/.test(e.message)) e.message = 'invalid_token_or_channel';
        const known = new Set(['helix_not_configured', 'invalid_token_or_channel', 'broadcaster_token_required', 'missing_scope', 'request_failed']);
        if (known.has(e.message)) e.message = t(`widgets.chat_import_error_${e.message}`);
        _waHint(e);
    }
}

async function waChatDisplaySave() {
    try {
        const result = await wapi('/api/widgets/chat/display/selected-chat', 'PUT', waChatDisplayValues());
        Object.entries(result.settings || {}).forEach(([key, value]) => {
            const id = _waChatDisplayFields[key];
            if (id && $(id)) $(id).value = value;
        });
        $('waChatShowBadges').checked = Boolean(result.settings?.show_badges);
        waChatDisplayPreview();
        toast(t('msg.saved'), 'success');
    } catch (e) { _waHint(e); }
}

// ── Chat Reader / raw TTS design ──
const _waDesignTimers = {};
const _waDesignThemeColors = {
    light: ['#2563eb', '#f8fafc'], neon: ['#d946ef', '#090014'],
    fire: ['#ff6b35', '#1a0800'], glass: ['#67e8f9', '#111827'],
    mono: ['#ffffff', '#111111'],
};

function _waDesignCard(widget) {
    return document.querySelector(`[data-design-widget="${widget}"]`);
}

function waInitDesignForms() {
    document.querySelectorAll('[data-design-widget]').forEach(card => {
        if (card.dataset.designBound) return;
        card.dataset.designBound = '1';
        card.querySelectorAll('[data-design-field]').forEach(input => {
            input.addEventListener('input', event => {
                if (event.target.dataset.designField === 'theme') {
                    const colors = event.target.value === 'dark'
                        ? (card.dataset.designWidget === 'tts-raw' ? ['#00ff7f', '#000000'] : ['#22d3ee', '#0f0f19'])
                        : _waDesignThemeColors[event.target.value];
                    if (colors) {
                        card.querySelector('[data-design-field="accent"]').value = colors[0];
                        card.querySelector('[data-design-field="bg"]').value = colors[1];
                    }
                }
                waDesignRefresh(card.dataset.designWidget);
            });
        });
    });
}

function waDesignValues(widget) {
    const card = _waDesignCard(widget);
    const values = {};
    if (!card) return values;
    card.querySelectorAll('[data-design-field]').forEach(input => {
        const key = input.dataset.designField;
        if (input.type === 'checkbox') values[key] = input.checked ? 1 : 0;
        else if (input.type === 'number' || input.type === 'range') values[key] = Number(input.value);
        else values[key] = input.value;
    });
    return values;
}

function _waDesignUrl(widget, preview) {
    const card = _waDesignCard(widget);
    if (!card) return '';
    const source = preview ? card.dataset.designPreview : card.dataset.designRoute;
    const url = new URL(source, location.origin);
    Object.entries(waDesignValues(widget)).forEach(([key, value]) => url.searchParams.set(key, value));
    const scope = waWidgetScopeOverrideFor(url.pathname) ||
        (typeof waBindingScope === 'function' ? waBindingScope() : {});
    if (scope.channel) url.searchParams.set('channel', scope.channel);
    if (scope.account_id) url.searchParams.set('account_id', String(scope.account_id));
    if (preview) url.searchParams.set('preview', '1');
    return widgetOutputUrl(url.pathname + url.search);
}

function waDesignRefresh(widget) {
    const card = _waDesignCard(widget);
    if (!card) return;
    const urlInput = card.querySelector('[data-design-url]');
    if (urlInput) urlInput.value = _waDesignUrl(widget, false);
    clearTimeout(_waDesignTimers[widget]);
    _waDesignTimers[widget] = setTimeout(() => {
        const frame = card.querySelector('[data-design-preview-frame]');
        if (frame) frame.src = _waDesignUrl(widget, true);
    }, 120);
}

async function waDesignLoad(widget) {
    const card = _waDesignCard(widget);
    if (!card) return;
    try {
        const data = await wapi(`/api/widgets/design/${widget}`);
        Object.entries(data.settings || {}).forEach(([key, value]) => {
            const input = card.querySelector(`[data-design-field="${key}"]`);
            if (!input) return;
            if (input.type === 'checkbox') input.checked = Boolean(value);
            else input.value = value;
        });
        waDesignRefresh(widget);
    } catch (e) { _waHint(e); }
}

async function waDesignSave(widget) {
    try {
        await wapi(`/api/widgets/design/${widget}`, 'PUT', waDesignValues(widget));
        waDesignRefresh(widget);
        toast(t('msg.saved'), 'success');
    } catch (e) { _waHint(e); }
}

function waDesignCopy(widget) {
    navigator.clipboard.writeText(location.origin + _waDesignUrl(widget, false))
        .then(() => toast(t('toast.copied'), 'success'));
}

// ── Goals (§11.1: percent вместо галочки, inline-редактирование) ──
async function waLoadGoals() {
    try {
        const data = await wstateapi('/api/widgets/goals');
        $('waGoalsList').innerHTML = (data.items || []).map(g => `
            <div class="flex items-center gap-2 text-sm">
                <input class="input" type="text" value="${esc(g.text)}" style="flex:1;min-width:120px" onchange="waGoalRename(${g.id}, this.value)">
                <input class="input" type="number" min="0" max="100" value="${g.percent != null ? g.percent : (g.done ? 100 : 0)}" style="width:74px" title="0–100%" onchange="waGoalPercent(${g.id}, this.value)">
                <span class="${(g.percent != null ? g.percent >= 100 : g.done) ? 'text-green' : 'text-muted'}">${(g.percent != null ? g.percent : (g.done ? 100 : 0))}%</span>
                <button class="btn btn-sm btn-danger" onclick="waGoalDelete(${g.id})">✕</button>
            </div>`).join('') || `<div class="text-muted text-sm">${esc(t('widgets.no_goals'))}</div>`;
    } catch (e) { _waHint(e); }
}
async function waGoalAdd() {
    const text = $('waGoalText').value.trim();
    if (!text) return;
    try { await wstateapi('/api/widgets/goals', 'POST', {text, percent: 0}); $('waGoalText').value = ''; await waLoadGoals(); }
    catch (e) { _waHint(e); }
}
async function waGoalRename(id, text) {
    try { await wstateapi(`/api/widgets/goals/${id}`, 'PUT', {text}); await waLoadGoals(); } catch (e) { _waHint(e); }
}
async function waGoalPercent(id, percent) {
    try { await wstateapi(`/api/widgets/goals/${id}`, 'PUT', {percent: Math.max(0, Math.min(100, parseInt(percent, 10) || 0))}); await waLoadGoals(); } catch (e) { _waHint(e); }
}
async function waGoalToggle(id, done) {
    // §11.1: галочка = 100% (обратная совместимость со старой панелью).
    try { await wstateapi(`/api/widgets/goals/${id}`, 'PUT', {percent: done ? 100 : 0}); await waLoadGoals(); } catch (e) { _waHint(e); }
}
async function waGoalDelete(id) {
    try { await wstateapi(`/api/widgets/goals/${id}`, 'DELETE'); await waLoadGoals(); } catch (e) { _waHint(e); }
}
async function waGoalsClearDone() {
    try { await wstateapi('/api/widgets/goals/clear-done', 'POST'); await waLoadGoals(); } catch (e) { _waHint(e); }
}

// ── Sub-goal ──
async function waLoadSubGoal() {
    try {
        const s = await wstateapi('/api/widgets/sub-goal');
        if ($('waSubTarget')) $('waSubTarget').value = s.target ?? 0;
        if ($('waSubCurrent')) $('waSubCurrent').value = s.current ?? 0;
        if ($('waSubTitle')) $('waSubTitle').value = s.title || '';
    } catch (e) { _waHint(e); }
}
async function waSubSave() {
    try {
        await wstateapi('/api/widgets/sub-goal', 'PUT', {
            target: parseInt($('waSubTarget')?.value, 10) || 0,
            current: parseInt($('waSubCurrent')?.value, 10) || 0,
            title: $('waSubTitle')?.value.trim() || '',
        });
        toast(t('msg.saved'), 'success');
    } catch (e) { _waHint(e); }
}
// ── Now Playing ──
async function waLoadNp() {
    try {
        const s = await wstateapi('/api/widgets/now-playing');
        if ($('waNpKind')) $('waNpKind').value = s.kind || 'music';
        if ($('waNpText')) $('waNpText').value = s.text || '';
        if ($('waNpSubtext')) $('waNpSubtext').value = s.subtext || '';
        if ($('waNpIcon')) $('waNpIcon').value = s.icon_url || '';
    } catch (e) { _waHint(e); }
}
async function waNpSave() {
    try {
        await wstateapi('/api/widgets/now-playing', 'PUT', {
            kind: $('waNpKind')?.value || 'custom',
            text: $('waNpText')?.value.trim() || '',
            subtext: $('waNpSubtext')?.value.trim() || '',
            icon_url: $('waNpIcon')?.value.trim() || '',
        });
        toast(t('msg.saved'), 'success');
    } catch (e) { _waHint(e); }
}
async function waNpClear() {
    try { await wstateapi('/api/widgets/now-playing/clear', 'POST'); await waLoadNp(); } catch (e) { _waHint(e); }
}

// ── Schedule ──
async function waLoadSchedule() {
    try {
        const items = await wapi('/api/widgets/schedule');
        $('waScheduleList').innerHTML = (items || []).map(b => `
            <div class="flex items-center gap-2 text-sm">
                <span class="badge">${esc(b.start_time || '')}</span>
                <span style="flex:1">${esc(b.emoji || '')} ${esc(b.title || '')}</span>
                <button class="btn btn-sm btn-danger" onclick="waScheduleDelete(${b.id})">✕</button>
            </div>`).join('') || `<div class="text-muted text-sm">${esc(t('widgets.no_schedule'))}</div>`;
    } catch (e) { _waHint(e); }
}
async function waScheduleAdd() {
    const start_time = $('waSchTime')?.value.trim();
    const title = $('waSchTitle')?.value.trim();
    if (!start_time || !title) { toast(t('widgets.sch_required'), 'error'); return; }
    try {
        await wapi('/api/widgets/schedule', 'POST', {start_time, title, emoji: $('waSchEmoji')?.value.trim() || ''});
        $('waSchTime').value = ''; $('waSchTitle').value = ''; $('waSchEmoji').value = '';
        await waLoadSchedule();
    } catch (e) { _waHint(e); }
}
async function waScheduleDelete(id) {
    try { await wapi(`/api/widgets/schedule/${id}`, 'DELETE'); await waLoadSchedule(); } catch (e) { _waHint(e); }
}

// ── Counters ──
// Оверлей /widget/counter выведен из эксплуатации (owner survey Q12), блок ручного
// управления счётчиками удалён (Q06): API счётчиков и чат-команды живут — их
// используют чат-команды и биндинги, панели они больше не требуют.

// ── Countdown ──
async function waLoadCd() {
    try {
        const s = await wstateapi('/api/widgets/countdown');
        if ($('waCdMode')) $('waCdMode').value = s.mode || 'countdown';
        if ($('waCdTitle')) $('waCdTitle').value = s.title || '';
        if ($('waCdDuration')) $('waCdDuration').value = Math.max(1, Math.round((s.duration_sec ?? 600) / 60));
    } catch (e) { _waHint(e); }
}
async function waCdSave() {
    try {
        await wstateapi('/api/widgets/countdown', 'PUT', {
            mode: $('waCdMode')?.value || 'countdown',
            duration_sec: Math.min(86400, Math.max(1, parseInt($('waCdDuration')?.value, 10) || 10) * 60),
            title: $('waCdTitle')?.value.trim() || '',
        });
        toast(t('msg.saved'), 'success');
    } catch (e) { _waHint(e); }
}
// ── Soundboard ──
async function waSoundboardLoad() {
    const box = $('soundboardInventory'); if (!box) return;
    try {
        const data = await wapi('/api/widgets/soundboard/tracks');
        window._soundboardHotkeys = (data.items || []).filter(track => (track.hotkey || '').trim());
        box.innerHTML = (data.items || []).map(track => `<div class="flex items-center gap-2 text-sm flex-wrap">
            <input id="sbName${Number(track.id)}" class="input" style="flex:2;min-width:150px" value="${esc(track.name)}" aria-label="${esc(t('soundboard.name'))}">
            <label class="text-xs">${esc(t('soundboard.volume'))}<input id="sbVolume${Number(track.id)}" class="input" type="number" min="0" max="2" step="0.05" value="${Number(track.volume ?? 1)}" style="width:76px"></label>
            <label class="text-xs">${esc(t('soundboard.cooldown'))}<input id="sbCooldown${Number(track.id)}" class="input" type="number" min="0" max="600" value="${Number(track.cooldown_sec ?? 0)}" style="width:76px"></label>
            <label class="text-xs">${esc(t('soundboard.order'))}<input id="sbOrder${Number(track.id)}" class="input" type="number" min="-10000" max="10000" value="${Number(track.sort_order ?? 0)}" style="width:76px"></label>
            <label class="text-xs">${esc(t('soundboard.hotkey'))}<input id="sbHotkey${Number(track.id)}" class="input" placeholder="1 / numpad1 / alt+1" value="${esc(track.hotkey || '')}" style="width:84px" title="${esc(t('soundboard.hotkey_hint'))}"></label>
            <button class="btn btn-secondary btn-sm" onclick="waSoundboardSave(${Number(track.id)})">${esc(t('btn.save'))}</button>
            <button class="btn btn-primary btn-sm" onclick="waSoundboardPlay(${Number(track.id)})">▶ ${esc(t('soundboard.play'))}</button>
            <button class="btn btn-secondary btn-sm" onclick="waSoundboardBind(${Number(track.id)})">⌨ ${esc(t('soundboard.bind'))}</button>
            <button class="btn btn-danger btn-sm" onclick="waSoundboardDelete(${Number(track.id)})">${esc(t('btn.delete'))}</button>
        </div>`).join('') || `<div class="text-muted text-sm">${esc(t('soundboard.empty'))}</div>`;
    } catch (e) { _waHint(e); }
}
async function waSoundboardUpload() {
    const input = $('soundboardFile'); const files = [...(input?.files || [])];
    if (!files.length) { toast(t('soundboard.file_required'), 'error'); return; }
    const form = new FormData(); files.forEach(file => form.append('files', file));
    try { const r = await fetch('/api/widgets/soundboard/tracks', {method:'POST', body:form}); if (!r.ok) throw new Error(await r.text()); const result=await r.json(); input.value=''; await waSoundboardLoad(); toast(t('soundboard.upload_result').replace('{accepted}', result.accepted).replace('{rejected}', result.rejected), result.rejected ? 'warning' : 'success'); } catch (e) { _waHint(e); }
}
async function waSoundboardPlay(id) { try { await wstateapi(`/api/widgets/soundboard/play/${id}`, 'POST'); toast(t('soundboard.played'), 'success'); } catch (e) { _waHint(e); } }
async function waSoundboardStop() { try { await wstateapi('/api/widgets/soundboard/stop', 'POST'); toast(t('soundboard.stopped'), 'success'); } catch (e) { _waHint(e); } }
async function waSoundboardSave(id) {
    try {
        await wapi(`/api/widgets/soundboard/tracks/${id}`, 'PATCH', {
            name: $(`sbName${id}`)?.value || '',
            volume: $(`sbVolume${id}`)?.value,
            cooldown_sec: $(`sbCooldown${id}`)?.value,
            sort_order: $(`sbOrder${id}`)?.value,
            hotkey: $(`sbHotkey${id}`)?.value || '',
        });
        await waSoundboardLoad(); toast(t('msg.saved'), 'success');
    } catch (e) { _waHint(e); }
}
async function waSoundboardDelete(id) {
    if (!confirm(t('soundboard.delete_confirm'))) return;
    try { await wapi(`/api/widgets/soundboard/tracks/${id}`, 'DELETE'); await waSoundboardLoad(); toast(t('msg.deleted'), 'success'); } catch (e) { _waHint(e); }
}
function waSoundboardBind(id) {
    // Q27b: действие soundboard всегда привязано к конкретному треку (play_track:<id>),
    // общего варианта в списке нет — открываем секцию правил карточки Soundboard
    // с предзаполненным действием; источник по умолчанию — хоткей.
    const action = `play_track:${id}`;
    waWidgetBindingAdd('soundboard', action);
    const section = document.querySelector('details.wa-widget-rules[data-rules-slug="soundboard"]');
    if (section) {
        const source = section.querySelector('.wa-rules-source');
        if (source) { source.value = 'hotkey'; waRulesFormSync(section); }
        section.querySelector('.wa-rules-match')?.focus();
    }
    toast(t('soundboard.bind_ready'), 'success');
}
if (!window._soundboardHotkeysBound) {
    window._soundboardHotkeysBound = true;
    document.addEventListener('keydown', async (e) => {
        const el = e.target;
        if (el && el.id && el.id.startsWith('sbHotkey')) {
            if (['Control', 'Alt', 'Shift', 'Meta'].includes(e.key)) return;
            if (e.key === 'Backspace' || e.key === 'Delete' || e.key === 'Tab' || e.key === 'Escape') return;
            const combo = typeof waHotkeyComboFromEvent === 'function' ? waHotkeyComboFromEvent(e) : '';
            if (combo) {
                e.preventDefault();
                el.value = combo;
            }
            return;
        }
        if (window._hotkeyCapturing) return;
        const tracks = window._soundboardHotkeys || [];
        if (!tracks.length) return;
        const tag = (el?.tagName || '').toLowerCase();
        if (tag === 'input' || tag === 'textarea' || tag === 'select' || el?.isContentEditable) return;
        const combo = typeof waHotkeyComboFromEvent === 'function' ? waHotkeyComboFromEvent(e) : '';
        if (!combo) return;
        const match = tracks.find(t => (t.hotkey || '').trim().toLowerCase() === combo.toLowerCase());
        if (!match) return;
        e.preventDefault();
        await waSoundboardPlay(match.id);
        toast(`${t('soundboard.hotkey_triggered') || 'Хоткей'}: ${match.name}`, 'info');
    });
}


// ── Top Donators ──
async function waLoadDonations() {
    try {
        const s = await wstateapi('/api/widgets/top-donators');
        $('waDonationsList').innerHTML = (s.recent_donations || []).slice(0, 10).map(d => `
            <div class="flex items-center gap-2 text-sm">
                <span class="badge">${esc(d.username)}</span>
                <span class="font-semibold">${esc(String(d.amount))} ${esc(d.currency || '')}</span>
                <span class="text-muted" style="flex:1">${esc((d.message || '').substring(0, 40))}</span>
                <button class="btn btn-sm btn-danger" onclick="waDonationDelete(${d.id})">✕</button>
            </div>`).join('') || `<div class="text-muted text-sm">${esc(t('widgets.no_donations'))}</div>`;
    } catch (e) { _waHint(e); }
}
// Wave 3 (owner survey Q15-17): один top-donator с выбором периода.
// Переключатель меняет и превью, и показанный URL для OBS.
function waTopDonatorPeriod(period) {
    const allowed = ['alltime', 'month', 'day'];
    const safe = allowed.includes(period) ? period : 'alltime';
    // Q10b: без скоупа — demo-URL (?preview=1)
    let url;
    try { url = waWidgetStateUrl(`/widget/top-donator?period=${safe}`); }
    catch (e) { url = widgetOutputUrl(`/widget/top-donator?period=${safe}&preview=1`); }
    const preview = $('waTdPreview');
    if (preview) preview.src = url;
    const code = $('waTdUrl');
    if (code) code.textContent = url;
}

async function waDonationAdd() {
    const username = $('waDonNick')?.value.trim();
    const amount = parseFloat($('waDonAmount')?.value);
    if (!username || !(amount > 0)) { toast(t('widgets.don_required'), 'error'); return; }
    try {
        await wstateapi('/api/widgets/top-donators/add', 'POST', {
            username, amount, currency: 'USD', message: $('waDonMsg')?.value.trim() || '',
        });
        $('waDonNick').value = ''; $('waDonAmount').value = ''; $('waDonMsg').value = '';
        await waLoadDonations();
    } catch (e) { _waHint(e); }
}
async function waDonationDelete(id) {
    try { await wstateapi(`/api/widgets/top-donators/${id}`, 'DELETE'); await waLoadDonations(); } catch (e) { _waHint(e); }
}

// ── Song Request ──
async function waLoadSr() {
    try {
        const s = await wstateapi('/api/widgets/song-request');
        setToggle('waSrEnabled', !!s.enabled);
        setToggle('waSrVisible', !!s.visible);
        if ($('waSrCooldown')) $('waSrCooldown').value = s.cooldown_sec != null ? s.cooldown_sec : 30;
        if ($('waSrPerUser')) $('waSrPerUser').value = s.max_per_user != null ? s.max_per_user : 2;
        if ($('waSrMaxQueue')) $('waSrMaxQueue').value = s.max_queue != null ? s.max_queue : 50;
        const queue = s.queue || [];
        const np = s.now_playing;
        if ($('waSrStatus')) $('waSrStatus').textContent =
            t('song_request.queue_status', {count: queue.length, current: np ? (np.title || '').substring(0, 30) : t('song_request.none')});
        $('waSrQueue').innerHTML = (np ? [np] : []).concat(queue).map((q, i) => `
            <div class="flex items-center gap-2 text-sm">
                <span class="badge">${i === 0 ? '▶' : i}</span>
                <span style="flex:1">${esc(q.title || '')} <span class="text-muted">— ${esc(q.requested_by || '')}</span></span>
                <button class="btn btn-sm btn-danger" onclick="waSrDelete(${q.id})">✕</button>
            </div>`).join('') || `<div class="text-muted text-sm">${esc(t('widgets.no_songs'))}</div>`;
        await waSrEntitlementsLoad();
    } catch (e) { _waHint(e); }
}
async function waSrToggle(field, value) {
    // §11.5: числовые поля (cooldown_sec / max_per_user) шлём как есть
    const payload = Number.isFinite(value) ? {[field]: value} : {[field]: !!value};
    try { await wstateapi('/api/widgets/song-request', 'PUT', payload); } catch (e) { _waHint(e); }
}
async function waSrAdd() {
    const title = $('waSrTitle')?.value.trim();
    if (!title) return;
    try {
        const result = await wstateapi('/api/widgets/song-request/add', 'POST', {title, requested_by: $('waSrBy')?.value.trim() || ''});
        if (!result.ok) throw new Error(t(`song_request.reason.${result.error}`));
        $('waSrTitle').value = ''; $('waSrBy').value = '';
        await waLoadSr();
    } catch (e) { _waHint(e); }
}
async function waSrSkip() {
    try { await wstateapi('/api/widgets/song-request/skip', 'POST'); await waLoadSr(); } catch (e) { _waHint(e); }
}
async function waSrClear() {
    try { await wstateapi('/api/widgets/song-request/clear', 'POST'); await waLoadSr(); } catch (e) { _waHint(e); }
}
async function waSrDelete(id) {
    try { await wstateapi(`/api/widgets/song-request/${id}`, 'DELETE'); await waLoadSr(); } catch (e) { _waHint(e); }
}

async function waSrEntitlementsLoad() {
    const data = await wstateapi('/api/widgets/song-request/entitlements');
    const s = data.settings || {};
    $('waSrPointsCreateId').value = s.points_create_reward_id || '';
    $('waSrPointsCreateTitle').value = s.points_create_reward_title || '';
    $('waSrPointsPriorityId').value = s.points_priority_reward_id || '';
    $('waSrPointsPriorityTitle').value = s.points_priority_reward_title || '';
    $('waSrDonationEnabled').checked = Boolean(s.donation_enabled);
    $('waSrDonationThreshold').value = s.donation_threshold == null ? '' : s.donation_threshold;
    $('waSrDonationCurrency').value = s.donation_currency || '';
    $('waSrDonationAction').value = s.donation_action || 'create';
}

async function waSrEntitlementsSave() {
    try {
        await wstateapi('/api/widgets/song-request/entitlements', 'PUT', {
            points_create_reward_id: $('waSrPointsCreateId').value.trim(),
            points_create_reward_title: $('waSrPointsCreateTitle').value.trim(),
            points_priority_reward_id: $('waSrPointsPriorityId').value.trim(),
            points_priority_reward_title: $('waSrPointsPriorityTitle').value.trim(),
            donation_enabled: $('waSrDonationEnabled').checked,
            donation_threshold: $('waSrDonationThreshold').value,
            donation_currency: $('waSrDonationCurrency').value.trim(),
            donation_action: $('waSrDonationAction').value,
        });
        toast(t('msg.saved'), 'success');
        await waSrEntitlementsLoad();
    } catch (e) { _waHint(e); }
}

async function waSrAuditLoad() {
    try {
        const data = await wstateapi('/api/widgets/song-request/audit');
        $('waSrAudit').innerHTML = (data.items || []).map(item => `
            <div class="flex items-center gap-2 text-xs">
                <span class="badge">${esc(item.accepted ? t('song_request.accepted') : t('song_request.rejected'))}</span>
                <span>${esc(item.request_text || '—')}</span>
                <span class="text-muted">${esc(item.actor || '—')} · ${esc(t(`song_request.reason.${item.reason}`))}</span>
            </div>`).join('') || `<div class="text-muted text-sm">${esc(t('song_request.audit_empty'))}</div>`;
    } catch (e) { _waHint(e); }
}

// ── §9j: Журнал действий (Action Log) с отменой ─────
async function loadActionLog(direction = 0) {
    const list = $('actionLogList');
    if (!list) return;
    const limit = 25;
    _actionLogOffset = Math.max(0, _actionLogOffset + direction * limit);
    const action = $('actionLogAction')?.value || '';
    const actor = $('actionLogActor')?.value || '';
    const q = $('actionLogQuery')?.value.trim() || '';
    const params = new URLSearchParams({ limit: String(limit), offset: String(_actionLogOffset) });
    if (action) params.set('action', action);
    if (actor) params.set('actor', actor);
    if (q) params.set('q', q);
    try {
        const data = await api(`/api/action-log?${params}`);
        // Наполняем фильтры один раз
        const actionSel = $('actionLogAction');
        const actorSel = $('actionLogActor');
        if (actionSel && actionSel.options.length <= 1) {
            (data.actions || []).forEach(a => actionSel.add(new Option(a, a)));
        }
        if (actorSel && actorSel.options.length <= 1) {
            (data.actors || []).forEach(a => actorSel.add(new Option(a, a)));
        }
        if (!data.items?.length) {
            list.innerHTML = `<div class="text-muted text-sm">${esc(t('actionlog.empty'))}</div>`;
            return;
        }
        list.innerHTML = data.items.map(item => `
            <div class="flex items-center gap-2 text-sm py-1" style="border-top:1px solid var(--border-light)">
                <span class="badge">${esc(item.action)}</span>
                <span style="flex:1" class="text-muted">${esc(item.detail || '')}</span>
                ${item.can_revert
                    ? `<button class="btn btn-sm btn-secondary" onclick="revertActionLog(${item.id})">${esc(t('actionlog.revert'))}</button>`
                    : ''}
            </div>`).join('');
    } catch (e) {
        list.innerHTML = `<div class="text-error text-sm">${esc(t('empty.load_failed', {detail: e.message}))}</div>`;
    }
}

function actionLogPage(delta) {
    loadActionLog(delta);
}

async function revertActionLog(id) {
    if (!confirm(t('confirm.delete_item'))) return;
    try {
        const res = await api(`/api/action-log/${id}/revert`, { method: 'POST' });
        if (res.ok) toast(t('actionlog.reverted'), 'success');
        else toast(t('toast.error_detail', {detail: res.error || t('send.reason.unknown')}), 'error');
        await loadActionLog();
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

function exportActionLogCSV() {
    const action = $('actionLogAction')?.value || '';
    const actor = $('actionLogActor')?.value || '';
    const q = $('actionLogQuery')?.value.trim() || '';
    const params = new URLSearchParams();
    if (action) params.set('action', action);
    if (actor) params.set('actor', actor);
    if (q) params.set('q', q);
    window.open(`${API}/api/action-log/export.csv?${params}`, '_blank');
}

// ── §17: Недостающие stats-виджеты ──────────────────
const HEATMAP_DOW = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];

async function loadHeatmap() {
    const el = $('heatmapGrid');
    if (!el) return;
    try {
        const data = await api('/api/stats/heatmap?days=30');
        const max = data.max_cell || 1;
        let html = '<div class="heatmap-row"><div class="heatmap-label"></div>'
            + Array.from({length: 24}, (_, h) => `<div class="heatmap-label">${h}</div>`).join('') + '</div>';
        for (let d = 0; d < 7; d++) {
            html += `<div class="heatmap-row"><div class="heatmap-label">${HEATMAP_DOW[d]}</div>`;
            for (let h = 0; h < 24; h++) {
                const cell = (data.grid || []).find(c => c.dow === d && c.hour === h);
                const cnt = cell?.count || 0;
                const alpha = cnt ? Math.max(0.15, cnt / max) : 0;
                html += `<div class="heatmap-cell" title="${d ? '' : ''}${h}:00 — ${cnt}" style="background:${cnt ? `color-mix(in srgb, var(--accent) ${Math.round(alpha * 100)}%, transparent)` : 'var(--bg-active)'}"></div>`;
            }
            html += '</div>';
        }
        el.innerHTML = html;
    } catch (e) { console.warn('heatmap', e); el.innerHTML = `<span class="text-muted text-sm">${esc(t('label.no_data'))}</span>`; }
}

// P8-C14: loadTrendingWords удалена вместе с карточкой «Растущие и угасающие темы»

async function loadChat24h() {
    const chart = $('chartHour24'), chatters = $('topChattersList');
    if (!chart) return;
    try {
        const data = await api('/api/stats/chat');
        const maxCnt = Math.max(1, ...(data.hourly || []).map(h => h.cnt || 0));
        chart.innerHTML = (data.hourly || []).map(h =>
            `<div class="bar-col" title="${esc(h.hour)}:00 — ${h.cnt}">
                <div class="bar-fill" style="height:${Math.round((h.cnt || 0) / maxCnt * 100)}%"></div>
                <span class="bar-label">${esc(h.hour)}</span>
            </div>`).join('') || `<span class="text-muted text-sm">${esc(t('label.no_data'))}</span>`;
        if (chatters) {
            chatters.innerHTML = (data.top_chatters || []).slice(0, 10).map((c, i) =>
                `<div class="flex justify-between py-0.5"><span>${i + 1}. ${esc(c.author)}</span><span class="text-muted">${c.cnt}</span></div>`
            ).join('') || `<span class="text-muted">${esc(t('label.no_data'))}</span>`;
        }
    } catch (e) { chart.innerHTML = `<span class="text-muted text-sm">${esc(t('label.no_data'))}</span>`; }
}

async function loadPerBotStatsSelect() {
    const sel = $('perBotStatsSelect');
    if (!sel) return;
    // P8-A2: секцию «Аналитика» можно открыть первой — список ботов ещё не грузился
    if (!_allBots.length) { try { await loadBotsList(); } catch (e) { /* пустой селект покажет «ботов нет» */ } }
    if (!sel.options.length) {
        sel.innerHTML = _allBots.map(b => `<option value="${b.id}">${esc(b.nickname)}</option>`).join('');
    }
    await loadPerBotStats();
}

async function loadPerBotStats() {
    const box = $('perBotStatsBox');
    if (!box) return;
    const id = $('perBotStatsSelect')?.value;
    if (!id) { box.innerHTML = `<span class="text-muted">${esc(t('empty.no_bots'))}</span>`; return; }
    try {
        const s = await api(`/api/accounts/${id}/stats`);
        const chans = (s.by_channel || []).slice(0, 5).map(c =>
            `<span class="bot-card-badge">#${esc(c.channel)}: ${c.count}</span>`).join(' ');
        box.innerHTML = `
            <div class="flex gap-3 flex-wrap">
                <span class="bot-card-badge">✉️ ${esc(t('label.bot_replies'))}: ${s.total_sent ?? 0}</span>
                <span class="bot-card-badge">👁️ ${esc(t('label.messages_read'))}: ${s.total_read ?? 0}</span>
                <span class="bot-card-badge">📅 24h: ${s.last_24h ?? 0}</span>
            </div>
            <div class="flex gap-2 mt-2 flex-wrap">${chans}</div>`;
    } catch (e) { box.innerHTML = `<span class="text-muted">${esc(t('label.no_data'))}</span>`; }
}


// ── WIDGETS-UI шаг 1: превью целиком — лайтбокс в реальных пропорциях виджета ──

function waZoomResolveTitle(title) {
    if (title && hasTranslation(title)) return t(title);
    if (title && title.startsWith('ui.catalog.title.')) return title.slice('ui.catalog.title.'.length);
    return title || '';
}

function waWidgetZoom(route, title, width = 800, height = 600) {
    const previous = document.getElementById('widgetZoomModal');
    if (previous) { closePanelDialog(previous); previous.remove(); }
    const w = Math.max(80, Number(width) || 800);
    const h = Math.max(60, Number(height) || 600);
    const scale = Math.min(1, (window.innerWidth - 72) / w, (window.innerHeight - 180) / h);
    const stageW = Math.round(w * scale);
    const stageH = Math.round(h * scale);
    const shownTitle = waZoomResolveTitle(title) || route;
    const src = waWidgetBestUrl(route);
    const overlay = document.createElement('div');
    overlay.id = 'widgetZoomModal';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.72);z-index:999;display:flex;align-items:center;justify-content:center';
    overlay.innerHTML = `
    <div class="modal widget-zoom-box" role="dialog" aria-modal="true" aria-labelledby="widgetZoomTitle" style="background:var(--bg-card);border:1px solid var(--border);border-radius:12px;padding:14px;max-width:96vw;max-height:94vh;overflow:auto">
        <div class="flex items-center justify-between mb-2" style="gap:12px">
            <b id="widgetZoomTitle">${esc(shownTitle)}</b>
            <div class="flex items-center gap-2">
                <span class="badge">${w} × ${h}${scale < 1 ? ' · ' + Math.round(scale * 100) + '%' : ''}</span>
                <button class="btn btn-sm btn-secondary" data-i18n-aria-label="btn.close" aria-label="${esc(t('btn.close'))}" onclick="closePanelDialog('widgetZoomModal')">✕</button>
            </div>
        </div>
        <div class="widget-zoom-stage" style="width:${stageW}px;height:${stageH}px">
            <iframe class="widget-zoom-frame" src="${esc(src)}" title="${esc(shownTitle)}" style="width:${w}px;height:${h}px;transform:scale(${scale});transform-origin:top left"></iframe>
        </div>
        <div class="flex gap-2 mt-2">
            <button class="btn btn-secondary btn-sm" data-i18n="widgets.preview_tab" onclick="window.open(widgetOutputUrl(${JSON.stringify(route)}),'_blank')">↗ В новой вкладке</button>
        </div>
    </div>`;
    overlay.addEventListener('click', e => { if (e.target === overlay) closePanelDialog(overlay); });
    document.body.appendChild(overlay);
    openPanelDialog(overlay, {removeOnClose: true});
}

Object.assign(LANGS.ru, {
    'widgets.zoom': '🔍 Увеличить',
    'widgets.preview_tab': '↗ В новой вкладке',
    'widgets.scope_select': 'Канал этого виджета',
    'widgets.scope_select_title': 'Задать канал отдельно для этого виджета — действует на превью, OBS-URL и его настройки',
    'widgets.scope_global': 'канал из общего выбора',
});
Object.assign(LANGS.en, {
    'widgets.zoom': '🔍 Zoom',
    'widgets.preview_tab': '↗ Open in new tab',
    'widgets.scope_select': 'Widget channel',
    'widgets.scope_select_title': 'Set a channel separately for this widget — applies to its preview, OBS URL and settings',
    'widgets.scope_global': 'channel from the shared selector',
});
Object.assign(LANGS.ua, {
    'widgets.zoom': '🔍 Збільшити',
    'widgets.preview_tab': '↗ Відкрити в новій вкладці',
    'widgets.scope_select': 'Канал цього віджета',
    'widgets.scope_select_title': 'Задати канал окремо для цього віджета — діє на прев’ю, OBS-URL і його налаштування',
    'widgets.scope_global': 'канал із загального вибору',
});
