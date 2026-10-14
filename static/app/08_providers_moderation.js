// [P5-split] 08_providers_moderation.js ← static/app.js, исходные строки 5998–6501; грузится после предыдущего чанка, порядок = порядку строк

// ── §25.4: Кастомные провайдеры (именованные, несколько моделей) ──
let _customProvidersCache = [];
let _cpEditingId = null;
// Q15b (E2): один список моделей с типом вместо двух textarea.
// Ряд: {name, type: 'chat'|'vision'|'both'}; при сохранении собирается в
// models/vision_models (контракт API не меняется), дубли имён схлопываются.
let _cpModelRows = [];

function cpAddModelRow() {
    _cpModelRows.push({ name: '', type: 'chat' });
    renderCpModelRows();
}

function cpRemoveModelRow(i) {
    _cpModelRows.splice(i, 1);
    renderCpModelRows();
}

function cpModelRowName(i, value) {
    if (_cpModelRows[i]) _cpModelRows[i].name = value;
}

function cpModelRowType(i, value) {
    if (_cpModelRows[i] && ['chat', 'vision', 'both'].includes(value)) _cpModelRows[i].type = value;
}

function renderCpModelRows() {
    const box = $('cpModelsEditor');
    if (!box) return;
    if (!_cpModelRows.length) {
        box.innerHTML = `<div class="text-muted text-sm">${t('cp.no_models')}</div>`;
        return;
    }
    box.innerHTML = _cpModelRows.map((row, i) => `
        <div class="flex items-center gap-2 mb-1">
            <input type="text" class="input flex-1" value="${esc(row.name)}" placeholder="${t('cp.model_name_ph')}" aria-label="${t('cp.model_name_ph')}" oninput="cpModelRowName(${i}, this.value)">
            <select class="input" style="max-width:170px" aria-label="${t('cp.model_type')}" onchange="cpModelRowType(${i}, this.value)">
                <option value="chat"${row.type === 'chat' ? ' selected' : ''}>💬 ${t('cp.type_chat')}</option>
                <option value="vision"${row.type === 'vision' ? ' selected' : ''}>👁 ${t('cp.type_vision')}</option>
                <option value="both"${row.type === 'both' ? ' selected' : ''}>💬👁 ${t('cp.type_both')}</option>
            </select>
            <button type="button" class="btn btn-sm btn-danger" aria-label="${t('btn.delete')}" onclick="cpRemoveModelRow(${i})">✕</button>
        </div>`).join('');
}

// Порядок имени при дубликате — первое написание; типы объединяются.
function _cpRowsFromProvider(p) {
    const chat = p.models || [];
    const vision = p.vision_models || [];
    const names = [...chat, ...vision.filter(v => !chat.includes(v))];
    return names.map(name => ({
        name,
        type: chat.includes(name) && vision.includes(name) ? 'both' : (vision.includes(name) ? 'vision' : 'chat'),
    }));
}

function _cpListsFromRows() {
    const seen = new Map();
    for (const row of _cpModelRows) {
        const name = (row.name || '').trim();
        if (!name) continue;
        const key = name.toLowerCase();
        if (!seen.has(key)) seen.set(key, { name, chat: false, vision: false });
        const entry = seen.get(key);
        if (row.type === 'chat' || row.type === 'both') entry.chat = true;
        if (row.type === 'vision' || row.type === 'both') entry.vision = true;
    }
    const entries = [...seen.values()];
    return {
        models: entries.filter(e => e.chat).map(e => e.name),
        vision_models: entries.filter(e => e.vision).map(e => e.name),
    };
}

async function loadCustomProviders() {
    try {
        const data = await api('/api/custom-providers');
        _customProvidersCache = data.items || [];
        renderCustomProvidersList();
        refreshCustomProviderOptions();
        // loadSettings ставит сохранённого провайдера (custom:<имя>) до того,
        // как этот список догрузится — селект сбрасывается в пусто. Восстанавливаем.
        const gsel = $('globalAIProvider');
        if (gsel && !gsel.value && typeof _aiConfig !== 'undefined' && _aiConfig && _aiConfig.provider) {
            gsel.value = _aiConfig.provider;
        }
        if (_cpEditingId) {
            // Обновляем форму редактирования актуальными данными
            const cur = _customProvidersCache.find(p => p.id === _cpEditingId);
            if (!cur) resetCustomProviderForm();
        }
    } catch (e) { console.warn('loadCustomProviders', e); }
}

function renderCustomProvidersList() {
    const el = $('customProvidersList');
    if (!el) return;
    if (!_customProvidersCache.length) {
        el.innerHTML = `<div class="text-muted text-sm">${panelI18n('cp.none')}</div>`;
        return;
    }
    el.innerHTML = _customProvidersCache.map(p => `
        <div class="flex items-center gap-2 text-sm p-2" style="background:var(--bg-active);border-radius:8px">
            <span class="badge">${p.enabled ? '🟢' : '⚫'}</span>
            <span class="font-semibold">${esc(p.name)}</span>
            <span class="text-muted" style="flex:1">${esc(p.base_url)} · ${(p.models || []).length} ${t('cp.models_word')}</span>
            <button class="btn btn-sm btn-secondary" ${panelI18nAttrs('btn.edit')} onclick="editCustomProvider(${p.id})">${panelI18n('btn.edit')}</button>
            <button class="btn btn-sm btn-danger" ${panelI18nAttrs('btn.delete')} onclick="deleteCustomProvider(${p.id})">✕</button>
        </div>`).join('');
}

function refreshCustomProviderOptions() {
    // §25.4: named-провайдеры появляются в глобальном селекте и в per-bot AI Override.
    // Обновление кэша не должно само менять уже выбранного провайдера.
    const selects = [$('globalAIProvider'), $('botAIProvider')].filter(Boolean);
    for (const sel of selects) {
        const selectedValue = sel.value;
        sel.querySelectorAll('option[data-cp]').forEach(o => o.remove());
        for (const p of _customProvidersCache) {
            const opt = document.createElement('option');
            opt.value = `custom:${p.name}`;
            opt.textContent = `🧩 ${p.name}`;
            opt.dataset.cp = '1';
            sel.appendChild(opt);
        }
        if (selectedValue && ![...sel.options].some(o => o.value === selectedValue)) {
            const stale = document.createElement('option');
            stale.value = selectedValue;
            stale.textContent = selectedValue;
            stale.dataset.cp = 'stale';
            sel.appendChild(stale);
        }
        sel.value = selectedValue;
    }
    if (typeof refreshBotAIModels === 'function') refreshBotAIModels();
}

function renderCustomProviders() {}

async function saveCustomProvider() {
    const name = $('cpName')?.value.trim();
    const base_url = $('cpBaseUrl')?.value.trim();
    const api_key = $('cpApiKey')?.value;
    const lists = _cpListsFromRows();
    const models = lists.models;
    const vision_models = lists.vision_models;
    if (!name) { toast(t('cp.name_required'), 'error'); return; }
    try {
        if (_cpEditingId) {
            await api(`/api/custom-providers/${_cpEditingId}`, jopts('PUT', { name, base_url, api_key, models, vision_models }));
            toast(t('cp.updated'), 'success');
        } else {
            await api('/api/custom-providers', jopts('POST', { name, base_url, api_key, models, vision_models }));
            toast(t('cp.created'), 'success');
        }
        resetCustomProviderForm();
        await loadCustomProviders();
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

function editCustomProvider(id) {
    const p = _customProvidersCache.find(item => item.id === id);
    if (!p) return;
    _cpEditingId = id;
    $('cpName').value = p.name || '';
    $('cpBaseUrl').value = p.base_url || '';
    $('cpApiKey').value = '';
    $('cpApiKey').dataset.i18nPlaceholder = p.has_api_key ? 'cp.key_set' : 'cp.key_ph';
    $('cpApiKey').placeholder = t($('cpApiKey').dataset.i18nPlaceholder);
    $('cpModelsEditor') && (_cpModelRows = _cpRowsFromProvider(p), renderCpModelRows());
    $('cpSaveBtn').dataset.i18n = 'cp.update';
    $('cpSaveBtn').textContent = t('cp.update');
    $('cpCancelBtn')?.classList.remove('hidden');
}

function resetCustomProviderForm() {
    _cpEditingId = null;
    if ($('cpName')) $('cpName').value = '';
    if ($('cpBaseUrl')) $('cpBaseUrl').value = '';
    if ($('cpApiKey')) { $('cpApiKey').value = ''; $('cpApiKey').dataset.i18nPlaceholder = 'cp.key_ph'; $('cpApiKey').placeholder = t('cp.key_ph'); }
    if ($('cpModelsEditor')) { _cpModelRows = []; renderCpModelRows(); }
    if ($('cpSaveBtn')) { $('cpSaveBtn').dataset.i18n = 'cp.add'; $('cpSaveBtn').textContent = t('cp.add'); }
    $('cpCancelBtn')?.classList.add('hidden');
}

async function deleteCustomProvider(id) {
    if (!confirm(t('confirm.delete_item'))) return;
    try {
        await api(`/api/custom-providers/${id}`, { method: 'DELETE' });
        toast(t('cp.deleted'), 'success');
        resetCustomProviderForm();
        await loadCustomProviders();
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function testVision() {
    // §25.5: тестовая vision-генерация с заглушкой-картинкой
    toast(t('vision.testing'), 'info');
    try {
        const res = await api('/api/ai/test-vision', jopts('POST', {}));
        if (res.ok) toast(t('vision.test_ok', {detail: (res.response || '').substring(0, 60)}), 'success');
        else toast(t('toast.error_detail', {detail: res.error || t('send.reason.unknown')}), 'error');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

// ── §9d: Общие факты между ботами — УДАЛЕНО (P8-C2: общая память убрана,
// факты мигрировали в per-bot user_memory) ──

// ── §9k: 👍/👎 на ответах бота ──
async function rateBotReply(btn, accountId, channel, message, rating) {
    try {
        const res = await api('/api/ai-feedback', jopts('POST', {
            account_id: accountId || 0, channel: channel || '', event_type: 'send',
            message: String(message || '').substring(0, 500), rating,
        }));
        if (!res.ok) throw new Error(res.error || 'fail');
        // Визуальная отметка на кнопках
        const wrap = btn.closest('.fb-buttons') || btn.parentElement;
        wrap?.querySelectorAll('button').forEach(b => b.classList.remove('fb-active'));
        btn.classList.add('fb-active');
        toast(t('feedback.saved'), 'success');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function loadFeedbackSummary() {
    const box = $('feedbackSummaryBox');
    if (!box) return;
    // P8-C14: per-bot — селект бота над сводкой; пусто = все боты
    const sel = $('feedbackBotFilter');
    if (sel && !sel.options.length) {
        sel.innerHTML = `<option value="">${esc(t('analytics.all_bots'))}</option>` +
            _allBots.map(b => `<option value="${b.id}">${esc(b.nickname)}</option>`).join('');
    }
    if (sel && !_allBots.length && !sel.options.length) {
        // селект пуст и ботов нет — ничего не делаем, отрисуется no_data
    }
    const accId = sel?.value || '';
    try {
        const s = await api(`/api/ai-feedback/stats${accId ? `?account_id=${accId}` : ''}`);
        const total = s.total || 0;
        const pos = s.positive || 0;
        const neg = s.negative || 0;
        const pct = total ? Math.round(pos / total * 100) : 0;
        box.innerHTML = total
            ? `<div class="flex gap-2 flex-wrap items-center">
            <span class="bot-card-badge">👍 ${pos}</span>
            <span class="bot-card-badge">👎 ${neg}</span>
            <span class="bot-card-badge">${pct}% 👍</span>
            <span class="text-muted text-xs">${esc(t('feedback.total', {count: total}))}</span>
        </div>`
            : `<span class="text-muted text-sm">${panelI18n('analytics.empty')}</span>`;
    } catch (e) { box.innerHTML = `<span class="text-muted text-sm">${panelI18n('label.no_data')}</span>`; }
}

// ── v14 MODERATION_PLAN §4: вкладка «🛡 Модерация» ──────────────────────

function _setToggle(id, on) {
    const el = $(id);
    if (!el) return;
    el.classList.toggle('active', !!on);
}

const MOD_MODE_LABELS = { off: 'panel.mod.off', log_only: 'panel.mod.log', replace: 'panel.mod.replace_mode', full: 'panel.mod.full', shadow: 'panel.mod.shadow' };

// Q01-D: явное действие правила (action_ext). Ключи = ровно ACTION_EXT_CHOICES
// на бэкенде (app/moderation.py): ''/auto = прежняя лестница по severity.
const MOD_RULE_ACTION_EXT = [
    { key: '', label: 'panel.mod.ext_auto' },
    { key: 'mask', label: 'panel.mod.ext_mask' },
    { key: 'block', label: 'panel.mod.ext_block' },
    { key: 'timeout_600', label: 'panel.mod.ext_timeout_600' },
    { key: 'timeout_3600', label: 'panel.mod.ext_timeout_3600' },
    { key: 'timeout_86400', label: 'panel.mod.ext_timeout_86400' },
    { key: 'timeout_604800', label: 'panel.mod.ext_timeout_604800' },
    { key: 'timeout_1209600', label: 'panel.mod.ext_timeout_1209600' },
    { key: 'ban', label: 'panel.mod.ext_ban' },
];

function modRuleActionExtOptions() {
    return MOD_RULE_ACTION_EXT.map(a =>
        `<option value="${a.key}" data-i18n="${a.label}">${esc(t(a.label))}</option>`).join('');
}

function initModerationRuleForm() {
    const sel = $('modRuleActionExt');
    if (!sel || sel.options.length) return;
    sel.innerHTML = modRuleActionExtOptions();
}

async function loadBotModeration(id) {
    if (!id) return;
    if (typeof loadBeepPipeline === 'function') loadBeepPipeline(); // Q25: beep-конвейер живёт во вкладке модератора
    if (typeof loadModeratorTTSAdmin === 'function') loadModeratorTTSAdmin(); // Q16 F4: консоль TTS — только у бота-модератора
    try {
        initModerationRuleForm();
        const [settings, rules] = await Promise.all([
            api(`/api/accounts/${id}/moderation/settings`),
            api(`/api/accounts/${id}/moderation/rules`),
        ]);
        renderModerationSettings(settings);
        renderModerationChannelOverrides(settings);
        renderModerationRules(rules.rules || []);
        loadModerationEvents(id);
        loadModerationTimeoutPolicy(id);
        loadStreamTools(id);
        loadVoiceControl(id);
    } catch (e) {
        console.error('loadBotModeration', e);
        toast(t('toast.error_detail', { detail: e.message }), 'error');
    }
}

function renderModerationSettings(s) {
    _setToggle('moderationToggle', s.mode && s.mode !== 'off');
    _setToggle('moderationCanTimeoutToggle', s.can_timeout);
    _setToggle('moderationEventSubToggle', s.eventsub_chat_messages);
    _setToggle('antispamViewerToggle', s.antispam_enabled);
    _setToggle('modAntispamLinksToggle', s.antispam_links);
    const modeSel = $('moderationMode');
    if (modeSel) modeSel.value = s.mode || 'off';
    const caps = $('modAntispamCaps');
    if (caps) caps.value = s.antispam_caps_pct ?? 70;
    const rep = $('modAntispamRepeat');
    if (rep) rep.value = s.antispam_repeat_count ?? 3;
    const emote = $('modAntispamEmote');
    if (emote) emote.value = s.antispam_emote_pct ?? 80;
    const exempt = $('modAntispamExempt');
    if (exempt) exempt.value = s.antispam_exempt_roles || 'streamer,mod,vip';
    const badge = $('modModeBadge');
    if (badge) {
        badge.dataset.i18n = MOD_MODE_LABELS[s.mode || 'off'] || 'send.reason.unknown';
        badge.textContent = t(badge.dataset.i18n);
        badge.classList.toggle('off', !s.mode || s.mode === 'off');
    }
}

function renderModerationChannelOverrides(s) {
    const el = $('modChannelOverrides');
    if (!el) return;
    const channels = s.channels || [];
    const overrides = s.channel_overrides || {};
    if (!channels.length) {
        el.innerHTML = `<div class="text-muted text-sm">${panelI18n('channels.empty')}</div>`;
        return;
    }
    el.innerHTML = channels.map(ch => `
        <div class="flex gap-2 items-center">
            <span class="badge">#${esc(ch)}</span>
            <span class="text-muted text-sm">${panelI18n('dynamic.mod.global')}: ${panelI18n(MOD_MODE_LABELS[s.mode || 'off'] || 'send.reason.unknown')}</span>
            <select ${panelI18nAttrs('panel.mod.mode')} class="input select-140" onchange="saveModerationChannelOverride('${esc(ch)}', this.value)">
                <option value="" data-i18n="dynamic.mod.inherit">${esc(t('dynamic.mod.inherit'))}</option>
                <option value="off" ${overrides[ch] === 'off' ? 'selected' : ''} data-i18n="panel.mod.off">${esc(t('panel.mod.off'))}</option>
                <option value="log_only" ${overrides[ch] === 'log_only' ? 'selected' : ''} data-i18n="panel.mod.log">${esc(t('panel.mod.log'))}</option>
                <option value="replace" ${overrides[ch] === 'replace' ? 'selected' : ''} data-i18n="panel.mod.replace_mode">${esc(t('panel.mod.replace_mode'))}</option>
                <option value="shadow" ${overrides[ch] === 'shadow' ? 'selected' : ''} data-i18n="panel.mod.shadow">${esc(t('panel.mod.shadow'))}</option>
                <option value="full" ${overrides[ch] === 'full' ? 'selected' : ''} data-i18n="panel.mod.full">${esc(t('panel.mod.full'))}</option>
            </select>
        </div>
    `).join('');
}

async function saveModerationChannelOverride(channel, mode) {
    try {
        await api(`/api/accounts/${_currentBotId}/moderation/settings`, jopts('PUT', { channel, channel_mode: mode }));
        toast(t('dynamic.mod.channel_saved'), 'success');
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function saveModerationSettings() {
    if (!_currentBotId) return;
    try {
        await api(`/api/accounts/${_currentBotId}/moderation/settings`, jopts('PUT', {
            mode: $('moderationMode').value,
            antispam_caps_pct: parseInt($('modAntispamCaps').value, 10) || 0,
            antispam_repeat_count: parseInt($('modAntispamRepeat').value, 10) || 0,
            antispam_emote_pct: parseInt($('modAntispamEmote').value, 10) || 0,
            antispam_exempt_roles: $('modAntispamExempt').value.trim() || 'streamer,mod,vip',
        }));
        toast(t('dynamic.mod.saved'), 'success');
        loadBotModeration(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function toggleModeration() {
    if (!_currentBotId) return;
    const on = !$('moderationToggle').classList.contains('active');
    try {
        // Владелец просил один переключатель: включение → режим full без выбора техрежимов.
        await api(`/api/accounts/${_currentBotId}/moderation/settings`, jopts('PUT', { mode: on ? 'full' : 'off' }));
        loadBotModeration(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function toggleModerationCanTimeout() {
    if (!_currentBotId) return;
    const on = !$('moderationCanTimeoutToggle').classList.contains('active');
    try {
        await api(`/api/accounts/${_currentBotId}/moderation/settings`, jopts('PUT', { can_timeout: on }));
        loadBotModeration(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function toggleModerationEventSub() {
    if (!_currentBotId) return;
    const on = !$('moderationEventSubToggle').classList.contains('active');
    try {
        await api(`/api/accounts/${_currentBotId}/moderation/eventsub-chat`, jopts('POST', { enabled: on }));
        loadBotModeration(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function toggleAntispamViewer() {
    if (!_currentBotId) return;
    const on = !$('antispamViewerToggle').classList.contains('active');
    try {
        await api(`/api/accounts/${_currentBotId}/moderation/settings`, jopts('PUT', { antispam_enabled: on }));
        loadBotModeration(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function toggleAntispamLinks() {
    if (!_currentBotId) return;
    const on = !$('modAntispamLinksToggle').classList.contains('active');
    try {
        await api(`/api/accounts/${_currentBotId}/moderation/settings`, jopts('PUT', { antispam_links: on }));
        loadBotModeration(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

function renderModerationRules(rules) {
    const el = $('moderationRulesList');
    if (!el) return;
    el.innerHTML = (rules || []).map(r => `
        <div class="flex gap-2 items-center text-sm p-1.5 rounded" style="background:var(--bg-secondary, rgba(0,0,0,0.1)); border:1px solid var(--border);">
            <span class="badge">${panelEnumI18n('panel.mod.cat_', r.category)}</span>
            <strong>${esc(r.pattern)}</strong>
            <span class="text-muted">${panelEnumI18n('panel.mod.action_', r.action)}·${r.severity}</span>
            ${r.action_ext ? `<span class="badge">${esc(t('panel.mod.ext_' + r.action_ext))}</span>` : ''}
            ${r.channel ? `<span class="text-muted">#${esc(r.channel)}</span>` : ''}
            <div class="flex items-center gap-1.5 ml-auto cursor-pointer" onclick="toggleModerationRule(${r.id})" title="${r.enabled ? 'Включено (кликните для отключения)' : 'Отключено (кликните для включения)'}">
                <div class="toggle ${r.enabled ? 'active' : ''}" style="transform:scale(0.75); margin:0;" role="switch" aria-checked="${r.enabled ? 'true' : 'false'}"></div>
                <span class="text-xs font-semibold ${r.enabled ? 'text-success' : 'text-muted'}" style="min-width:32px;">${r.enabled ? 'Вкл' : 'Выкл'}</span>
            </div>
            <button class="btn btn-sm btn-danger" ${panelI18nAttrs('btn.delete')} onclick="deleteModerationRule(${r.id})" title="Удалить правило">✕</button>
        </div>
    `).join('') || `<div class="text-muted text-sm">${panelI18n('wordfilter.empty')}</div>`;
}

async function addModerationRule(id) {
    if (!id) return;
    const pattern = $('modRulePattern').value.trim();
    if (!pattern) return;
    try {
        await api(`/api/accounts/${id}/moderation/rules`, jopts('POST', {
            pattern,
            category: $('modRuleCategory').value,
            action: $('modRuleAction').value,
            action_ext: $('modRuleActionExt')?.value || '',
            severity: parseInt($('modRuleSeverity').value, 10) || 3,
            channel: $('modRuleChannel').value.trim(),
        }));
        toast(t('dynamic.mod.rule_added'), 'success');
        $('modRulePattern').value = '';
        loadModerationRules(id);
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function loadModerationRules(id) {
    if (!id) return;
    try {
        const data = await api(`/api/accounts/${id}/moderation/rules`);
        renderModerationRules(data.rules || []);
    } catch (e) {
        const el = $('moderationRulesList');
        if (el) el.innerHTML = `<div class="text-error text-sm">${panelI18n('api.error.request_failed')}</div>`;
    }
}

async function toggleModerationRule(ruleId) {
    try {
        await api(`/api/moderation/rules/${ruleId}/toggle`, jopts('POST', {}));
        loadModerationRules(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function bulkToggleModerationRules(enabled) {
    if (!_currentBotId) return;
    try {
        const res = await api(`/api/accounts/${_currentBotId}/moderation/rules/bulk-toggle`, jopts('POST', {
            enabled: !!enabled,
        }));
        if (res.ok === false) {
            toast(t('toast.error_detail', { detail: res.error }), 'error');
            return;
        }
        toast(enabled ? 'Все правила бота включены' : 'Все правила бота выключены', 'success');
        loadModerationRules(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function deleteModerationRule(ruleId) {
    try {
        await api(`/api/moderation/rules/${ruleId}`, jopts('DELETE', {}));
        loadModerationRules(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function importModerationRules(id) {
    if (!id) return;
    const text = $('modRuleImportText').value;
    if (!text.trim()) return;
    try {
        const res = await api(`/api/accounts/${id}/moderation/rules/import`, jopts('POST', {
            text,
            action: $('modRuleAction').value,
            action_ext: $('modRuleActionExt')?.value || '',
            severity: parseInt($('modRuleSeverity').value, 10) || 3,
            category: $('modRuleCategory').value,
            channel: $('modRuleChannel').value.trim(),
        }));
        toast(t('dynamic.mod.imported', {count: res.added}), 'success');
        $('modRuleImportText').value = '';
        loadModerationRules(id);
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function loadModerationEvents(id) {
    if (!id) return;
    try {
        const params = new URLSearchParams();
        if ($('modEventsUser')?.value.trim()) params.set('username', $('modEventsUser').value.trim());
        if ($('modEventsCategory')?.value) params.set('category', $('modEventsCategory').value);
        if ($('modEventsChannel')?.value.trim()) params.set('channel', $('modEventsChannel').value.trim());
        params.set('limit', '100');
        const [events, stats] = await Promise.all([
            api(`/api/accounts/${id}/moderation/events?${params}`),
            api(`/api/accounts/${id}/moderation/stats`),
        ]);
        const st = $('moderationStats');
        if (st) {
            const cats = (stats.by_category || []).map(c => `${panelEnumI18n('panel.mod.cat_', c.category)}: ${c.count}`).join(', ');
            st.innerHTML = `${panelI18n('dynamic.mod.day')}: <strong>${stats.day ?? 0}</strong>${cats ? ` · ${panelI18n('dynamic.mod.week')}: ${cats}` : ''}` +
                (stats.top_offenders?.length
                    ? `<br>${panelI18n('dynamic.mod.top')}: ${(stats.top_offenders.slice(0, 3)).map(o => `${esc(o.username)} (${o.count})`).join(', ')}`
                    : '');
        }
        const el = $('moderationEventsList');
        if (!el) return;
        el.innerHTML = (events.events || []).map(ev => `
            <div class="flex gap-2 items-center text-sm">
                <span class="text-muted">${esc((ev.created_at || '').replace('T', ' ').slice(5, 16))}</span>
                <span class="badge">${panelEnumI18n('panel.mod.cat_', ev.category)}·${ev.severity}</span>
                <strong>${esc(ev.username || '?')}</strong>
                <span class="text-muted">#${esc(ev.channel || '')}</span>
                <span class="text-muted">${panelEnumI18n('panel.mod.action_', ev.action_taken)}${ev.source && ev.source !== 'chat_in' ? ` (${panelEnumI18n('dynamic.source.', ev.source)})` : ''}</span>
                <span class="text-muted text-truncate">${esc((ev.message_excerpt || '').slice(0, 70))}</span>
            </div>
        `).join('') || `<div class="text-muted text-sm">${panelI18n('dynamic.mod.empty')}</div>`;
    } catch (e) {
        const el = $('moderationEventsList');
        if (el) el.innerHTML = `<div class="text-error text-sm">${panelI18n('api.error.request_failed')}</div>`;
    }
}

function exportModerationCSV(id) {
    if (!id) return;
    window.open(`/api/accounts/${id}/moderation/events/export.csv`, '_blank');
}

async function clearModerationEvents(id) {
    if (!id || !confirm(t('dynamic.mod.clear_confirm'))) return;
    try {
        await api(`/api/accounts/${id}/moderation/events`, jopts('DELETE', {}));
        toast(t('dynamic.mod.cleared'), 'success');
        loadModerationEvents(id);
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

// ── Q03: база правил модерации per-канал + пресет Twitch ──
// Владелец 27.09: своя страница вместо всплывашки (общая channelSettingsPage,
// вкладка «rules»; открытие/закрытие страницы и переключение вкладок — 19_channels_bulk.js)
let _channelBaseRulesChannel = '';

function openChannelBaseRules(channel) {
    const ch = (channel || '').replace(/^#/, '').toLowerCase();
    _channelSettingsChannel = ch;
    _primeChannelBaseRules(ch);
    openChannelSettingsPage('rules');
}

async function loadChannelBaseRules() {
    const el = $('channelBaseRulesList');
    if (!el) return;
    try {
        const data = await api(`/api/moderation/base-rules?channel=${encodeURIComponent(_channelBaseRulesChannel)}`);
        el.innerHTML = (data.rules || []).map(r => `
            <div class="flex gap-2 items-center text-sm p-1.5 rounded" style="background:var(--bg-secondary, rgba(0,0,0,0.1)); border:1px solid var(--border);">
                <span class="badge">${panelEnumI18n('panel.mod.cat_', r.category)}</span>
                <strong>${esc(r.pattern)}</strong>
                <span class="text-muted">${panelEnumI18n('panel.mod.action_', r.action)}·${r.severity}</span>
                ${r.action_ext ? `<span class="badge">${esc(t('panel.mod.ext_' + r.action_ext))}</span>` : ''}
                <div class="flex items-center gap-1.5 ml-auto cursor-pointer" onclick="toggleChannelBaseRule(${r.id}, ${r.enabled ? 0 : 1})" title="${r.enabled ? 'Включено (кликните для отключения)' : 'Отключено (кликните для включения)'}">
                    <div class="toggle ${r.enabled ? 'active' : ''}" style="transform:scale(0.75); margin:0;" role="switch" aria-checked="${r.enabled ? 'true' : 'false'}"></div>
                    <span class="text-xs font-semibold ${r.enabled ? 'text-success' : 'text-muted'}" style="min-width:32px;">${r.enabled ? 'Вкл' : 'Выкл'}</span>
                </div>
                <button class="btn btn-sm btn-danger" onclick="deleteChannelBaseRule(${r.id})" title="Удалить правило">✕</button>
            </div>`).join('') || `<div class="text-muted text-sm">${panelI18n('channels.base_rules_empty')}</div>`;
    } catch (e) {
        el.innerHTML = `<div class="text-error text-sm">${panelI18n('api.error.request_failed')}</div>`;
    }
}

async function addChannelBaseRule() {
    const pattern = $('channelBaseRulePattern').value.trim();
    if (!pattern || !_channelBaseRulesChannel) return;
    try {
        const res = await api('/api/moderation/base-rules', jopts('POST', {
            channel: _channelBaseRulesChannel,
            pattern,
            category: $('channelBaseRuleCategory').value,
            action: $('channelBaseRuleAction').value,
            action_ext: $('channelBaseRuleExt')?.value || '',
            severity: parseInt($('channelBaseRuleSeverity').value, 10) || 3,
        }));
        if (res.ok === false) { toast(t('toast.error_detail', { detail: res.error }), 'error'); return; }
        $('channelBaseRulePattern').value = '';
        loadChannelBaseRules();
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function toggleChannelBaseRule(ruleId, enabled) {
    try {
        await api(`/api/moderation/base-rules/${ruleId}`, jopts('PUT', { enabled: !!enabled }));
        loadChannelBaseRules();
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function bulkToggleChannelBaseRules(enabled) {
    if (!_channelBaseRulesChannel) return;
    try {
        const res = await api('/api/moderation/base-rules/bulk-toggle', jopts('POST', {
            channel: _channelBaseRulesChannel,
            enabled: !!enabled,
        }));
        if (res.ok === false) {
            toast(t('toast.error_detail', { detail: res.error }), 'error');
            return;
        }
        toast(enabled ? 'Все правила канала включены' : 'Все правила канала выключены', 'success');
        loadChannelBaseRules();
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function deleteChannelBaseRule(ruleId) {
    try {
        await api(`/api/moderation/base-rules/${ruleId}`, jopts('DELETE', {}));
        loadChannelBaseRules();
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function seedChannelBaseRules(preset = 'twitch') {
    if (!_channelBaseRulesChannel) return;
    try {
        const res = await api('/api/moderation/base-rules/seed', jopts('POST', {
            channel: _channelBaseRulesChannel,
            preset: preset || 'twitch',
        }));
        if (res.ok === false) { toast(t('toast.error_detail', { detail: res.error }), 'error'); return; }
        toast(t('channels.base_rules_seeded', { count: res.added }), 'success');
        loadChannelBaseRules();
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

function exportChannelBaseRules() {
    if (!_channelBaseRulesChannel) {
        toast('Канал не выбран', 'error');
        return;
    }
    window.location.href = `${API}/api/moderation/base-rules/export?channel=${encodeURIComponent(_channelBaseRulesChannel)}`;
    toast('Экспорт правил модерации...', 'info');
}

async function importChannelBaseRules(event) {
    const file = event.target.files?.[0];
    if (!file || !_channelBaseRulesChannel) return;
    try {
        const text = await file.text();
        let payload;
        try {
            payload = JSON.parse(text);
        } catch (_) {
            const lines = text.split('\n').map(l => l.trim()).filter(l => l && !l.startsWith('#'));
            payload = { rules: lines };
        }
        let rules = Array.isArray(payload) ? payload : (payload.rules || []);
        if (!rules.length) {
            toast('Файл не содержит правил', 'error');
            return;
        }
        const res = await api('/api/moderation/base-rules/import', jopts('POST', {
            channel: _channelBaseRulesChannel,
            rules: rules,
        }));
        if (!res.ok) {
            toast(res.error || 'Ошибка импорта правил', 'error');
            return;
        }
        toast(`Импортировано правил: ${res.imported} из ${res.total}`, 'success');
        loadChannelBaseRules();
    } catch (e) {
        toast(t('toast.error_detail', { detail: e.message }), 'error');
    } finally {
        event.target.value = '';
    }
}

async function clearChannelBaseRules() {
    if (!_channelBaseRulesChannel) {
        toast('Канал не выбран', 'error');
        return;
    }
    if (!confirm(`Точно удалить ВСЕ правила модерации для канала #${_channelBaseRulesChannel}?`)) return;
    try {
        const res = await api(`/api/moderation/base-rules/clear?channel=${encodeURIComponent(_channelBaseRulesChannel)}`, { method: 'DELETE' });
        if (res.ok) {
            toast(`Очищено правил: ${res.deleted || 0}`, 'info');
            loadChannelBaseRules();
        } else {
            toast(res.error || 'Ошибка очистки правил', 'error');
        }
    } catch (e) {
        toast(t('toast.error_detail', { detail: e.message }), 'error');
    }
}

function moderationSpamDetail(detail) {
    const text = String(detail || '');
    if (text === 'содержит ссылку') return panelI18n('dynamic.mod.contains_link');
    let match = text.match(/^(caps|эмодзи\/эмоуты) (\d+)% > (\d+)%$/);
    if (match) return `${panelI18n(match[1] === 'caps' ? 'panel.mod.cat_caps' : 'panel.mod.cat_emote')} ${match[2]}% > ${match[3]}%`;
    match = text.match(/^повтор (\d+)x за (\d+)с$/);
    if (match) return `${panelI18n('panel.mod.cat_repeat')}: ${match[1]}× · ${panelI18n('dynamic.mod.window_seconds')}: ${match[2]}`;
    match = text.match(/^copypasta sim=(\d+(?:\.\d+)?)$/);
    if (match) return `${panelI18n('panel.mod.cat_copypasta')} · ${panelI18n('dynamic.mod.similarity')}: ${match[1]}`;
    return `<span data-user-content>${esc(text)}</span>`;
}

async function testModeration(id) {
    if (!id) return;
    const text = $('modTestText').value;
    if (!text.trim()) return;
    const el = $('modTestResult');
    try {
        const res = await api(`/api/accounts/${id}/moderation/test`, jopts('POST', { text }));
        const verdicts = (res.verdicts || []).map(v =>
            `<div class="flex gap-2 items-center">
                <span class="badge">${panelEnumI18n('panel.mod.cat_', v.category)}</span>
                <strong>${panelEnumI18n('panel.mod.action_', v.action)}</strong>
                <span class="text-muted">${panelI18n('dynamic.mod.severity')} ${v.severity}</span>
                ${v.masked_text ? `<span class="text-muted">→ «${esc(v.masked_text)}»</span>` : ''}
                <span class="text-muted">${panelI18n('dynamic.mod.match')}: «${esc(v.match)}» (${esc(v.rule_name || '')})</span>
            </div>`).join('');
        const spam = (res.spam || []).map(s =>
            `<div class="flex gap-2 items-center">
                <span class="badge">${panelEnumI18n('panel.mod.cat_', s.category)}</span>
                <span class="text-muted">${moderationSpamDetail(s.detail)}</span>
            </div>`).join('');
        el.innerHTML = `<p class="mb-2">${panelI18n('panel.mod.mode')}: <strong>${panelI18n(MOD_MODE_LABELS[res.mode || 'off'] || 'send.reason.unknown')}</strong>${res.summary ? ` · ${panelI18n('dynamic.mod.verdict')}: ${(res.verdicts || []).map(v => `${panelEnumI18n('panel.mod.cat_', v.category)}/${panelEnumI18n('panel.mod.action_', v.action)} (${v.severity})`).join(', ')}` : ''}</p>`
            + (verdicts || spam ? verdicts + spam : `<div class="text-muted">${panelI18n('dynamic.mod.clean')}</div>`);
    } catch (e) {
        el.innerHTML = `<span class="text-error">${esc(e.message)}</span>`;
    }
}

async function testChannelModerationPhrase() {
    const input = $('channelRuleTestInput');
    const resultEl = $('channelRuleTestResult');
    if (!input || !resultEl) return;
    const text = input.value.trim();
    if (!text) return;
    resultEl.classList.remove('hidden');
    resultEl.innerHTML = `<span class="text-muted">Проверяем...</span>`;
    try {
        const res = await api('/api/moderation/test', jopts('POST', {
            text,
            channel: _channelBaseRulesChannel || '',
        }));
        renderSandboxResult(resultEl, res);
    } catch (e) {
        resultEl.innerHTML = `<div class="text-error text-xs">${esc(e.message)}</div>`;
    }
}

async function testBotModerationPhrase() {
    const input = $('modRuleTestInput');
    const resultEl = $('modRuleTestResult');
    if (!input || !resultEl) return;
    const text = input.value.trim();
    if (!text) return;
    resultEl.classList.remove('hidden');
    resultEl.innerHTML = `<span class="text-muted">Проверяем...</span>`;
    try {
        const res = await api('/api/moderation/test', jopts('POST', {
            text,
            account_id: _currentBotId || 0,
        }));
        renderSandboxResult(resultEl, res);
    } catch (e) {
        resultEl.innerHTML = `<div class="text-error text-xs">${esc(e.message)}</div>`;
    }
}

function renderSandboxResult(el, res) {
    el.classList.remove('hidden');
    if (!res.matched || !res.primary_verdict) {
        el.innerHTML = `
            <div class="p-2.5 rounded flex items-center gap-2" style="background:rgba(34, 197, 94, 0.15); border:1px solid rgba(34, 197, 94, 0.3); color:#86efac;">
                <span style="font-size:1.1rem;">✅</span>
                <div>
                    <strong>Нарушений не обнаружено</strong>
                    <div class="text-xs" style="color:#bbf7d0;">Фраза проходит фильтры без срабатывания правил.</div>
                </div>
            </div>`;
        return;
    }
    const v = res.primary_verdict;
    const actionName = panelEnumI18n('panel.mod.action_', v.action) || v.action;
    const catName = panelEnumI18n('panel.mod.cat_', v.category) || v.category;
    const extName = v.action_ext ? ` (${t('panel.mod.ext_' + v.action_ext) || v.action_ext})` : '';
    el.innerHTML = `
        <div class="p-2.5 rounded" style="background:rgba(239, 68, 68, 0.15); border:1px solid rgba(239, 68, 68, 0.3);">
            <div class="flex items-center gap-2 flex-wrap mb-1">
                <span class="badge" style="background:#ef4444; color:#fff;">⚠️ Нарушение</span>
                <span class="badge">${panelEnumI18n('panel.mod.cat_', v.category)}</span>
                <span class="font-semibold text-danger">Действие: ${esc(actionName)}${esc(extName)}</span>
                <span class="text-xs text-muted ml-auto">Уровень: ${v.severity}/5</span>
            </div>
            <div class="text-xs mt-1" style="color:var(--text-secondary);">
                <span>Правило: <strong>${esc(v.rule_name || '-')}</strong></span>
                ${v.match ? `<span class="ml-3">Слово: <code style="background:rgba(0,0,0,0.3); padding:1px 4px; border-radius:3px;">${esc(v.match)}</code></span>` : ''}
                ${v.masked_text ? `<div class="mt-1">Результат замены: <em>${esc(v.masked_text)}</em></div>` : ''}
            </div>
        </div>`;
}

