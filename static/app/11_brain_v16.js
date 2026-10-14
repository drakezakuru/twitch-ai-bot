// [P5-split] 11_brain_v16.js ← static/app.js, исходные строки 7422–7985; грузится после предыдущего чанка, порядок = порядку строк

// ==================== v16 BRAIN_PLAN: Мозг (Lore / Learning / Summarizer / Shift / Memory) ====================

function _brainAcc() { const v = document.getElementById('brainBotSelect')?.value; return v ? parseInt(v) : null; }
// Q17: память/обучение живут во вкладке бота — аккаунт берётся из карточки (_currentBotId).
function _memoryAcc() { return _currentBotId || _brainAcc(); }
// Скоуп из селекта канала: '*' = все каналы, иначе имя канала (''/name). §2 PLAN_FEEDBACK_3008
function _brainCh() { return (document.getElementById('brainChannel')?.value || '*').replace(/^#/, ''); }
// Канал для ДОБАВЛЕНИЯ факта: «все каналы» → глобальный ('' = виден на всех)
function _brainChForAdd() { const ch = _brainCh(); return ch === '*' ? '' : ch; }

async function loadBrainChannels() {
    const sel = document.getElementById('brainChannel');
    if (!sel) return;
    let channels = [];
    try {
        const data = await api('/api/streamer-channels');
        channels = data.channels || [];
    } catch (e) { /* некритично — останется только «все каналы» */ }
    const cur = sel.value;
    sel.innerHTML = `<option value="*" data-i18n="label.all_channels">${esc(t('label.all_channels'))}</option>` +
        channels.map(c => `<option value="${esc(c)}">#${esc(c)}</option>`).join('');
    if (cur && (cur === '*' || channels.some(c => c === cur))) sel.value = cur;
}

function initBrain() {
    const sel = document.getElementById('brainBotSelect');
    if (!sel) return;
    loadBrainChannels();
    if (!sel.options.length) {
        (_allBots || []).forEach(b => {
            const o = document.createElement('option');
            o.value = b.id; o.textContent = b.nickname || ('bot ' + b.id);
            sel.appendChild(o);
        });
        if (_currentBotId) sel.value = _currentBotId;
    }
    loadBrainAll();
}

function onBrainBotChange() { loadBrainAll(); }

function loadBrainAll() {
    // Q09d/Q18b: редакторы lore/профиля/сводок/запреток переехали из «Мозга»
    // (модалка «Профиль канала»); здесь остаётся браузер прогонов.
    loadSummarizerRuns();
}

// ---------- PROMPT-BASE PB-1: общая база запреток ----------
async function loadPromptBase() {
    const box = document.getElementById('promptBaseText');
    if (!box || box.dataset.loading) return;
    box.dataset.loading = '1';
    try {
        const res = await api('/api/prompt-base');
        if (document.activeElement !== box) box.value = res.text || '';
    } catch (e) { console.error('loadPromptBase', e); }
    finally { delete box.dataset.loading; }
}

async function savePromptBase() {
    const box = document.getElementById('promptBaseText');
    if (!box) return;
    try {
        const res = await api('/api/prompt-base', jopts('PUT', { text: box.value }));
        if (!res.ok) { toast(t('toast.error_detail', { detail: res.error || 'error' }), 'error'); return; }
        toast(t('msg.saved'), 'success');
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

// ---------- Lore ----------
async function loadLore() {
    const box = document.getElementById('loreList');
    const acc = _brainAcc(); if (!box || !acc) return;
    try {
        const res = await api(`/api/accounts/${acc}/lore?channel=${encodeURIComponent(_brainCh())}&limit=100`);
        const items = res.items || [];
        if (!items.length) { box.innerHTML = `<div class="empty-state text-muted text-sm">${panelI18n('sharedfacts.empty')}</div>`; return; }
        box.innerHTML = items.map(it => {
            const st = it.status || 'suggested';
            const badge = st === 'approved' ? `<span class="badge badge-success">${panelI18n('dynamic.status.approved')}</span>`
                : st === 'rejected' ? `<span class="badge">${panelI18n('dynamic.status.rejected')}</span>`
                : `<span class="badge badge-warning">${panelI18n('dynamic.status.suggested')}</span>`;
            // §2.1: бейдж скоупа — факт для конкретного канала или «все каналы»
            const scope = it.channel ? `<span class="badge" ${panelI18nAttrs('dynamic.channel_scope')}>#${esc(it.channel)}</span>`
                : `<span class="badge badge-success" ${panelI18nAttrs('dynamic.all_scope')}>${panelI18n('label.all_channels')}</span>`;
            const acts = [];
            if (st !== 'approved') acts.push(`<button class="btn btn-sm btn-primary" ${panelI18nAttrs('dynamic.approve')} onclick="loreAct(${it.id}, 'approve')">✓</button>`);
            if (st !== 'rejected') acts.push(`<button class="btn btn-sm btn-secondary" ${panelI18nAttrs('dynamic.reject')} onclick="loreAct(${it.id}, 'reject')">✕</button>`);
            acts.push(`<button class="btn btn-sm btn-secondary" ${panelI18nAttrs('btn.delete')} onclick="loreDelete(${it.id})">🗑</button>`);
            return `<div class="p-2 mb-1" style="border-bottom:1px solid var(--border,#eee)">
                <div class="flex justify-between items-start gap-2">
                    <div><div class="text-sm" data-user-content>${esc(it.fact)}</div>
                    <div class="text-xs text-muted">${panelI18n('dynamic.source')}: ${panelEnumI18n('brain.src.', it.source)} · ${panelI18n('sharedfacts.confidence')} ${(it.confidence ?? 0).toFixed(2)} · ${panelI18n('dynamic.importance')} ${it.importance ?? 50}${it.evidence ? ' · ' + esc(it.evidence) : ''}</div></div>
                    <div class="flex gap-1 items-center">${scope}${badge}${acts.join('')}</div>
                </div></div>`;
        }).join('');
    } catch (e) { box.innerHTML = `<div class="text-error text-sm">${esc(e.message)}</div>`; }
}

function loreShowAdd() { document.getElementById('loreAddForm')?.classList.remove('hidden'); }
function hideLoreAdd() { document.getElementById('loreAddForm')?.classList.add('hidden'); }

async function loreAdd(approved) {
    const acc = _brainAcc(); if (!acc) return toast(t('dynamic.pick_bot'), 'error');
    const fact = document.getElementById('loreNewFact')?.value.trim();
    if (!fact) return toast(t('dynamic.enter_fact'), 'error');
    const importance = parseInt(document.getElementById('loreNewImportance')?.value || '50');
    const source = document.getElementById('loreNewSource')?.value || 'manual';
    const res = await api(`/api/accounts/${acc}/lore`, jopts('POST', { fact, importance, source, channel: _brainChForAdd(), approved }));
    if (res.ok) { toast(t('dynamic.fact_added'), 'success'); document.getElementById('loreNewFact').value = ''; hideLoreAdd(); loadLore(); }
    else toast(res.error || t('label.error'), 'error');
}

async function loreAct(id, action) {
    const acc = _brainAcc(); if (!acc) return;
    const res = await api(`/api/accounts/${acc}/lore/${id}/${action}`, jopts('POST', {}));
    if (res.ok) loadLore(); else toast(res.error || t('label.error'), 'error');
}

async function loreDelete(id) {
    const acc = _brainAcc(); if (!acc) return;
    const res = await api(`/api/accounts/${acc}/lore/${id}`, jopts('DELETE', {}));
    if (res.ok) loadLore(); else toast(res.error || t('label.error'), 'error');
}

// ---------- Learning ----------
async function loadLearning() {
    const box = document.getElementById('botLearningList');
    const acc = _memoryAcc(); if (!box || !acc) return;
    try {
        const res = await api(`/api/accounts/${acc}/learning?limit=100`);
        const items = res.items || [];
        if (!items.length) { box.innerHTML = `<div class="empty-state text-muted text-sm">${panelI18n('dynamic.learning_empty')}</div>`; return; }
        box.innerHTML = items.map(it => {
            const st = it.status || 'pending';
            const scope = it.channel ? `<span class="badge">#${esc(it.channel)}</span>`
                : `<span class="badge badge-success">${panelI18n('label.all_channels')}</span>`;
            const badge = st === 'applied' ? `<span class="badge badge-success">${panelI18n('dynamic.status.applied')}</span>`
                : st === 'rejected' ? `<span class="badge">${panelI18n('dynamic.status.rejected')}</span>`
                : st === 'reverted' ? `<span class="badge">${panelI18n('dynamic.status.reverted')}</span>`
                : `<span class="badge badge-warning">${panelI18n('dynamic.status.pending')}</span>`;
            const acts = [];
            if (st === 'pending') {
                acts.push(`<button class="btn btn-sm btn-primary" onclick="learningAct(${it.id}, 'apply')">${panelI18n('dynamic.apply')}</button>`);
                acts.push(`<button class="btn btn-sm btn-secondary" onclick="learningAct(${it.id}, 'reject')">${panelI18n('dynamic.reject')}</button>`);
            }
            if (st === 'applied') acts.push(`<button class="btn btn-sm btn-secondary" onclick="learningAct(${it.id}, 'revert')">${panelI18n('dynamic.revert')}</button>`);
            const payload = esc(JSON.stringify(it.payload || {}));
            return `<div class="p-2 mb-1" style="border-bottom:1px solid var(--border,#eee)">
                <div class="flex justify-between items-start gap-2">
                    <div><div class="text-sm"><b>${esc(it.kind)}</b> ${payload}</div>
                    <div class="text-xs text-muted">${esc(it.reason || '')} · ${panelI18n('dynamic.source')}: ${panelEnumI18n('brain.src.', it.source || '')}</div></div>
                    <div class="flex gap-1 items-center">${scope}${badge}${acts.join('')}</div>
                </div></div>`;
        }).join('');
    } catch (e) { box.innerHTML = `<div class="text-error text-sm">${esc(e.message)}</div>`; }
}

async function learningAct(id, action) {
    const acc = _memoryAcc(); if (!acc) return;
    const res = await api(`/api/accounts/${acc}/learning/${id}/${action}`, jopts('POST', {}));
    if (res.ok) { toast(t('dynamic.status.done'), 'success'); loadLearning(); }
    else toast(res.error || t('label.error'), 'error');
}

// ---------- Summarizer ----------
async function loadSummarizerRuns() {
    const box = document.getElementById('summarizerRunsList');
    const acc = _brainAcc(); if (!box || !acc) return;
    try {
        const res = await api(`/api/accounts/${acc}/summarizer/runs?channel=${encodeURIComponent(_brainCh())}&limit=30`);
        const items = res.items || [];
        if (!items.length) {
            box.innerHTML = `<div class="empty-state text-muted text-sm">${panelI18n('brain.runs_empty')}</div>`;
            return;
        }
        box.innerHTML = items.map(r => {
            const st = r.status || 'pending';
            const badge = st === 'done' ? `<span class="badge badge-success">${panelI18n('dynamic.status.done')}</span>`
                : st === 'failed' ? `<span class="badge" style="color:#e74c3c">${panelI18n('dynamic.status.failed')}</span>`
                : st === 'running' ? `<span class="badge badge-warning">${panelI18n('dynamic.status.running')}</span>`
                : `<span class="badge">${panelI18n('dynamic.status.pending')}</span>`;
            return `<div class="p-2 mb-1 flex justify-between items-center gap-2" style="border-bottom:1px solid var(--border,#eee)">
                <div class="text-sm">${badge} <b>${esc(r.channel)}</b> · ${esc(r.run_date)} · ${esc(String(r.period_start || '').slice(0, 16))} → ${esc(String(r.period_end || '').slice(0, 16))}
                ${st === 'failed' && r.error ? ` · <span class="text-error">${esc(r.error)}</span>` : ''}</div>
                <div class="flex gap-1">
                    <button class="btn btn-sm btn-secondary" onclick="summarizerViewRun(${r.id})">${panelI18n('clips.open')}</button>
                    <button class="btn btn-sm btn-secondary" ${panelI18nAttrs('btn.delete')} onclick="summarizerDeleteRun(${r.id})">🗑</button>
                </div></div>`;
        }).join('');
    } catch (e) { box.innerHTML = `<div class="text-error text-sm">${esc(e.message)}</div>`; }
}

function summarizerShowRun() {
    const f = document.getElementById('summarizerRunForm');
    if (!f) return;
    const end = new Date(); const start = new Date(end.getTime() - 3 * 3600 * 1000);
    const fmt = d => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    document.getElementById('sumRunStart').value = fmt(start);
    document.getElementById('sumRunEnd').value = fmt(end);
    // BRAIN_PLAN §4 (решение владельца): язык отчётов = язык панели (en → EN, иначе RU)
    const panelLang = localStorage.getItem('lang') || 'ru';
    const sel = document.getElementById('sumRunLang');
    if (sel) sel.value = panelLang === 'en' ? 'en' : 'ru';
    f.classList.remove('hidden');
}
function hideSummarizerRun() { document.getElementById('summarizerRunForm')?.classList.add('hidden'); }

async function summarizerStartRun() {
    const acc = _brainAcc(); const ch = _brainCh();
    if (!acc) return toast(t('dynamic.pick_bot'), 'error');
    if (!ch || ch === '*') return toast(t('dynamic.run_channel'), 'error');
    const ps = document.getElementById('sumRunStart')?.value;
    const pe = document.getElementById('sumRunEnd')?.value;
    if (!ps || !pe) return toast(t('dynamic.run_period'), 'error');
    const lang = document.getElementById('sumRunLang')?.value || 'ru';
    const res = await api(`/api/accounts/${acc}/summarizer/runs`, jopts('POST', {
        channel: ch, period_start: ps + ':00Z', period_end: pe + ':00Z', lang,
    }));
    if (res.ok) { toast(t('dynamic.run_started'), 'success'); hideSummarizerRun(); loadSummarizerRuns(); }
    else toast(res.error || t('label.error'), 'error');
}

async function summarizerViewRun(runId) {
    const acc = _brainAcc(); const view = document.getElementById('summarizerRunView');
    if (!view) return;
    try {
        const res = await api(`/api/accounts/${acc}/summarizer/runs/${runId}`);
        if (!res.ok) return toast(res.error || t('api.error.not_found'), 'error');
        const r = res.run;
        view.classList.remove('hidden');
        view.innerHTML = `<div class="card p-3">
            <div class="flex justify-between items-center mb-2">
                <b>${esc(r.channel)} · ${esc(r.run_date)}</b>
                <span class="flex gap-1">
                    <button class="btn btn-sm btn-secondary" ${panelI18nAttrs('dynamic.export_md')} onclick="summarizerExportRun(${r.id}, 'md')">⬇ MD</button>
                    <button class="btn btn-sm btn-secondary" ${panelI18nAttrs('dynamic.export_json')} onclick="summarizerExportRun(${r.id}, 'json')">⬇ JSON</button>
                    <button class="btn btn-sm btn-secondary" ${panelI18nAttrs('btn.close')} onclick="document.getElementById('summarizerRunView').classList.add('hidden')">✕</button>
                </span>
            </div>
            <pre class="text-sm" style="white-space:pre-wrap; max-height:420px; overflow:auto">${r.summary_md ? esc(r.summary_md) : panelI18n('dynamic.empty')}</pre>
        </div>`;
    } catch (e) { toast(e.message, 'error'); }
}

async function summarizerDeleteRun(runId) {
    const acc = _brainAcc(); if (!acc) return;
    const res = await api(`/api/accounts/${acc}/summarizer/runs/${runId}`, jopts('DELETE', {}));
    if (res.ok) loadSummarizerRuns(); else toast(res.error || t('label.error'), 'error');
}

// ---------- Shift — УДАЛЕНО (P8-C4: ручной Personality Shift убран) ----------

// ---------- Memory (confirm) ----------
async function loadBotViewerMemory() {
    const box = document.getElementById('botViewerMemoryList');
    const acc = _memoryAcc(); if (!box || !acc) return;
    try {
        const res = await api(`/api/accounts/${acc}/memory?limit=30`);
        const users = Array.isArray(res) ? res : (res.items || res.users || []);
        if (!users.length) {
            box.innerHTML = `<div class="empty-state text-muted text-sm">${panelI18n('brain.memory_empty')}</div>`;
            return;
        }
        box.innerHTML = users.map(u => {
            const facts = (u.facts_structured || []).map(f => {
                const conf = f.confirmed
                    ? `<button class="btn btn-sm btn-secondary" ${panelI18nAttrs('dynamic.unconfirm')} onclick="brainConfirmFact('${esc(u.username)}', '${esc(f.fact)}', false)">✓✓</button>`
                    : `<button class="btn btn-sm btn-secondary" ${panelI18nAttrs('dynamic.confirm_fact')} onclick="brainConfirmFact('${esc(u.username)}', '${esc(f.fact)}', true)">✓</button>`;
                const edit = `<button class="btn btn-sm btn-secondary" ${panelI18nAttrs('dynamic.edit_fact')} onclick="brainEditFact('${esc(u.username)}', '${esc(f.fact)}', ${f.priority ?? 50}, ${f.expires_at ? 1 : 0})">✎</button>`;
                return `<div class="flex justify-between items-center gap-2 text-sm mb-1">
                    <span><span data-user-content>${esc(f.fact)}</span> <span class="text-xs text-muted">${panelI18n('dynamic.priority')} ${f.priority ?? 50} · ${panelI18n('sharedfacts.confidence')} ${(f.confidence ?? 0).toFixed(2)}${f.expires_at ? ' · ' + panelI18n('dynamic.expires') + ' ' + esc(String(f.expires_at).slice(0, 10)) : ''}</span></span>
                    <span class="flex gap-1">${edit}${conf}</span></div>`;
            }).join('');
            return `<div class="p-2 mb-1" style="border-bottom:1px solid var(--border,#eee)">
                <div class="text-sm font-semibold mb-1">${esc(u.username)} <span class="text-xs text-muted">(${u.msg_count || 0} ${panelI18n('dynamic.messages')})</span></div>
                ${facts || `<div class="text-xs text-muted">${panelI18n('sharedfacts.no_facts')}</div>`}</div>`;
        }).join('');
    } catch (e) { box.innerHTML = `<div class="text-error text-sm">${esc(e.message)}</div>`; }
}

async function brainConfirmFact(username, fact, confirmed) {
    const acc = _memoryAcc(); if (!acc) return;
    const res = await api(`/api/accounts/${acc}/memory/${encodeURIComponent(username)}/confirm`, jopts('POST', { fact, confirmed }));
    if (res.ok) loadBotViewerMemory(); else toast(res.error || t('label.error'), 'error');
}

// ── §9e/§9g/§9h/§6: карточки на главной странице бота ──
function _firstChannel() {
    return (_channelsCache[0]?.channel_name || (_botStatuses[_currentBotId]?.channels || [])[0] || '');
}

async function loadBotOverviewExtras() {
    loadQuickBehavior();
    loadClipMoments();
    loadClipConfig();
    loadReplaySessionsList();
}

async function loadQuickBehavior() {
    if (!_currentBotId) return;
    try {
        const cfg = await api(`/api/accounts/${_currentBotId}/analyzer`);
        setToggle('quickAutoChat', !(cfg.auto_chat === false));
        setToggle('quickSilent', !!cfg.silent_mode);
        if ($('quickCooldown')) $('quickCooldown').value = (cfg.cooldown ?? 10);
        setToggle('quickAntiDeadAir', !!cfg.anti_dead_air_enabled);
        if ($('quickAntiDeadAirMin')) $('quickAntiDeadAirMin').value = cfg.anti_dead_air_minutes ?? 3;
        if ($('quickAntiDeadAirCooldown')) $('quickAntiDeadAirCooldown').value = cfg.anti_dead_air_cooldown_min ?? 10;
        if ($('quickAntiDeadAirPrompt')) $('quickAntiDeadAirPrompt').value = cfg.anti_dead_air_prompt || '';
        setToggle('quickEmoteHumanizer', !!cfg.emote_humanizer_enabled);
    } catch (e) { console.warn('quick behavior', e); }
    try {
        const bot = _allBots.find(b => b.id === _currentBotId);
        setToggle('quickObservation', !!(bot && bot.observation_only));
    } catch (e) { /* noop */ }
}

async function saveQuickBehavior() {
    if (!_currentBotId) return;
    try {
        const cdRaw = $('quickCooldown')?.value;
        const cooldown = Math.max(0, Math.min(3600, parseInt(cdRaw ?? '', 10) || 0));
        const data = {
            auto_chat: toggleChecked('quickAutoChat'),
            silent_mode: toggleChecked('quickSilent'),
            cooldown,
            anti_dead_air_enabled: toggleChecked('quickAntiDeadAir'),
            emote_humanizer_enabled: toggleChecked('quickEmoteHumanizer'),
        };
        if ($('quickAntiDeadAirMin')) {
            data.anti_dead_air_minutes = Math.max(1, Math.min(60, parseInt($('quickAntiDeadAirMin').value, 10) || 3));
        }
        if ($('quickAntiDeadAirCooldown')) {
            data.anti_dead_air_cooldown_min = Math.max(1, Math.min(120, parseInt($('quickAntiDeadAirCooldown').value, 10) || 10));
        }
        if ($('quickAntiDeadAirPrompt')) {
            data.anti_dead_air_prompt = $('quickAntiDeadAirPrompt').value.trim();
        }
        // переехало из удалённой вкладки «Поведение» (B3)
        const sp = $('analyzerSystemPrompt')?.value;
        if (sp && sp.trim()) data.system_prompt = sp.trim();
        if ($('analyzerResponseLength')) data.response_length = $('analyzerResponseLength').value || 'short';
        // PROMPT-BASE PB-3: декор исходящих сообщений (пусто = выключен)
        if ($('outEmojiPrefix')) data.outgoing_emoji_prefix = $('outEmojiPrefix').value.trim();
        if ($('outEmojiSuffix')) data.outgoing_emoji_suffix = $('outEmojiSuffix').value.trim();
        await api(`/api/accounts/${_currentBotId}/analyzer`, jopts('PUT', data));
        toast(t('msg.saved'), 'success');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function saveQuickObservation() {
    if (!_currentBotId) return;
    const value = toggleChecked('quickObservation');
    try {
        await api(`/api/accounts/${_currentBotId}`, jopts('PUT', { observation_only: value }));
        const bot = _allBots.find(b => b.id === _currentBotId);
        if (bot) bot.observation_only = value;
        toast(t(value ? 'toast.observation_enabled' : 'toast.observation_disabled'), 'success');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

// AI-BUDGET AB-1: переключатели внимания (источники платного AI)
async function saveAttentionSources() {
    if (!_currentBotId) return;
    try {
        await api(`/api/accounts/${_currentBotId}/analyzer`, jopts('PUT', {
            attention_vision: toggleChecked('attnVision'),
            attention_hearing: toggleChecked('attnHearing'),
            attention_chat_ai: toggleChecked('attnChatAi'),
        }));
        toast(t('msg.saved'), 'success');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

// §9e: настроение стримера (read-only)

// §9g: клипы
async function checkClipSpike() {
    if (!_currentBotId) return;
    const channel = _firstChannel();
    const box = $('clipCheckResult');
    if (!channel) { toast(t('status.no_channel_bot'), 'error'); return; }
    try {
        const res = await api(`/api/bot/clip-detector/check/${_currentBotId}/${encodeURIComponent(channel)}`);
        box.innerHTML = res.spike
            ? `<span class="text-success">🔥 ${esc(t('clips.spike_yes'))} — ${esc(t('dynamic.clip_rate', {rate: res.rate, average: res.avg_rate}))}</span>`
            : `<span class="text-muted">${esc(t('clips.spike_no'))} — ${esc(t('dynamic.clip_rate', {rate: res.rate, average: res.avg_rate}))}</span>`;
    } catch (e) { box.innerHTML = `<span class="text-error">${esc(e.message)}</span>`; }
}

async function createClipManually() {
    if (!_currentBotId) return;
    const channel = _firstChannel();
    if (!channel) { toast(t('status.no_channel_bot'), 'error'); return; }
    try {
        const res = await api('/api/bot/clip-detector/create-clip', jopts('POST', {
            account_id: _currentBotId, channel,
        }));
        if (res.ok) toast(t('clips.created', {detail: (res.clip_url || res.clip_id || '').toString().substring(0, 50)}), 'success');
        else toast(t('toast.error_detail', {detail: res.error || t('send.reason.unknown')}), 'error');
        await loadClipMoments();
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function loadClipMoments() {
    const box = $('clipMomentsList');
    if (!box || !_currentBotId) return;
    try {
        const res = await api(`/api/bot/clip-detector/moments/${_currentBotId}`);
        const moments = res.items || [];
        box.innerHTML = moments.slice(0, 5).map(m => `
            <div class="flex items-center gap-2 text-sm">
                <span class="badge">🎬</span>
                <span style="flex:1">${esc(String(m.timestamp || m.created_at || '').substring(0, 19))} · ${esc(String(m.rate ?? ''))} ${esc(t('clips.per_sec'))}</span>
                ${m.clip_url ? `<a href="https://clips.twitch.tv/${esc(m.clip_url)}" target="_blank" rel="noopener" class="text-accent text-xs">${esc(t('clips.open'))}</a>` : ''}
            </div>`).join('') || `<div class="text-muted text-sm">${esc(t('clips.no_moments'))}</div>`;
    } catch (e) { box.innerHTML = `<div class="text-muted text-sm">${esc(t('clips.no_moments'))}</div>`; }
}

// §9g: конфиг чувствительности детектора всплесков
// §4.4: с PLAN_FEEDBACK_2908 настройки per-bot (account_id), глобальные — fallback
async function loadClipConfig() {
    if (!$('clipThreshold')) return;
    try {
        const q = _currentBotId ? `?account_id=${_currentBotId}` : '';
        const cfg = await api('/api/bot/clip-detector/config' + q);
        $('clipThreshold').value = cfg.threshold_multiplier ?? 3.0;
        $('clipWindow').value = cfg.window_sec ?? 60;
        $('clipCooldown').value = cfg.cooldown_sec ?? 30;
    } catch (e) { console.warn('clip config', e); }
}

async function saveClipConfig() {
    try {
        const body = {
            threshold_multiplier: Math.max(1, parseFloat($('clipThreshold')?.value || '3') || 3),
            window_sec: Math.max(10, parseInt($('clipWindow')?.value || '60', 10) || 60),
            cooldown_sec: Math.max(0, parseInt($('clipCooldown')?.value || '30', 10) || 30),
        };
        if (_currentBotId) body.account_id = _currentBotId;
        await api('/api/bot/clip-detector/config', jopts('PUT', body));
        toast(t('msg.saved'), 'success');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

// §9h: replay sessions
const REPLAY_KIND_I18N = {
    chat_in: 'replay.kind_chat_in', bot_out: 'replay.kind_bot_out',
    vision_frame: 'replay.kind_vision_frame', whisper_seg: 'replay.kind_whisper_seg',
    trigger: 'replay.kind_trigger', setting: 'replay.kind_setting',
    mood: 'replay.kind_mood', thread: 'replay.kind_thread',
};
const _replayPlayTimers = {};

async function loadReplaySessionsList() {
    const box = $('replaySessionsList');
    if (!box) return;
    try {
        const res = await api('/api/replay/sessions?limit=20');
        const sessions = (res.sessions || []).filter(s => !s.account_id || Number(s.account_id) === Number(_currentBotId));
        box.innerHTML = sessions.map(s => {
            const active = !s.ended_at;
            const dur = (s.started_at && s.ended_at) ? Math.max(1, Math.round((s.ended_at - s.started_at) / 60)) : null;
            return `<div class="p-2" style="border-bottom:1px solid var(--border-light)">
                <div class="flex items-center gap-2 text-sm flex-wrap">
                    <span class="badge">${active ? '⏺' : '✓'}</span>
                    <span class="font-semibold">${esc(s.name || '#' + s.id)}</span>
                    <span class="text-muted" style="flex:1">#${esc(s.channel || '')} · ${tPlural('events', s.n_events ?? 0)}${dur !== null ? ' · ' + tPlural('minutes', dur) : ''}</span>
                    <button class="btn btn-sm btn-secondary" onclick="toggleReplayEvents(${s.id})" title="${esc(t('replay.view'))}">📋</button>
                    ${active ? '' : `<button id="replayPlayBtn-${s.id}" class="btn btn-sm btn-secondary" onclick="playReplaySession(${s.id})" title="${esc(t('replay.play'))}">▶</button>`}
                    <button class="btn btn-sm btn-danger" onclick="deleteReplaySession(${s.id})" title="${esc(t('replay.delete'))}">🗑</button>
                </div>
                <div id="replayEvents-${s.id}" class="hidden mt-2"></div>
            </div>`;
        }).join('') || `<div class="text-muted text-sm">${esc(t('replay.empty'))}</div>`;
    } catch (e) { box.innerHTML = `<div class="text-muted text-sm">${esc(t('replay.empty'))}</div>`; }
}

async function toggleReplayEvents(sessionId) {
    const box = $('replayEvents-' + sessionId);
    if (!box) return;
    if (!box.classList.contains('hidden')) { box.classList.add('hidden'); return; }
    box.classList.remove('hidden');
    box.innerHTML = `<span class="text-xs text-muted">${esc(t('label.loading'))}</span>`;
    try {
        const res = await api(`/api/replay/sessions/${sessionId}/events`);
        const events = res.events || [];
        if (!events.length) { box.innerHTML = `<span class="text-xs text-muted">${esc(t('replay.empty'))}</span>`; return; }
        const t0 = events[0].ts ?? 0;
        box.innerHTML = events.map((ev, i) => {
            const at = ev.ts ? new Date((ev.ts - t0) * 1000).toISOString().substring(14, 19) : '--:--';
            const p = ev.payload || {};
            const bodyRaw = p.text != null
                ? (p.author ? `${p.author}: ${p.text}` : String(p.text))
                : JSON.stringify(p);
            const kindKey = REPLAY_KIND_I18N[ev.kind];
            return `<div class="replay-event flex gap-2 text-xs py-1" data-idx="${i}" style="border-top:1px solid var(--border-light)">
                <span class="text-muted">+${at}</span>
                <span class="badge">${esc(kindKey ? t(kindKey) : String(ev.kind))}</span>
                <span style="flex:1">${esc(bodyRaw.substring(0, 110))}</span>
            </div>`;
        }).join('');
    } catch (e) { box.innerHTML = `<span class="text-xs text-error">${esc(e.message)}</span>`; }
}

async function playReplaySession(sessionId) {
    const box = $('replayEvents-' + sessionId);
    const btn = $('replayPlayBtn-' + sessionId);
    if (!box) return;
    if (_replayPlayTimers[sessionId]) {
        clearInterval(_replayPlayTimers[sessionId]);
        delete _replayPlayTimers[sessionId];
        box.querySelectorAll('.replay-event').forEach(el => { el.style.background = ''; });
        if (btn) btn.textContent = '▶';
        return;
    }
    let rows = [...box.querySelectorAll('.replay-event')];
    if (!rows.length) {
        await toggleReplayEvents(sessionId);
        rows = [...box.querySelectorAll('.replay-event')];
        if (!rows.length) return;
    }
    if (btn) btn.textContent = '⏸';
    let i = 0;
    _replayPlayTimers[sessionId] = setInterval(() => {
        if (i >= rows.length) {
            clearInterval(_replayPlayTimers[sessionId]);
            delete _replayPlayTimers[sessionId];
            if (btn) btn.textContent = '▶';
            return;
        }
        rows[i].style.background = 'var(--accent-soft, rgba(145,70,255,0.18))';
        i += 1;
    }, 350);
}

async function deleteReplaySession(sessionId) {
    if (!confirm(t('confirm.delete_replay'))) return;
    try {
        await api(`/api/replay/sessions/${sessionId}`, { method: 'DELETE' });
        toast(t('msg.deleted'), 'success');
        await loadReplaySessionsList();
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function startReplaySession() {
    if (!_currentBotId) return;
    const channel = _firstChannel();
    if (!channel) { toast(t('status.no_channel_bot'), 'error'); return; }
    try {
        const res = await api('/api/replay/sessions/start', jopts('POST', {
            account_id: _currentBotId, channel,
            name: `stream_${new Date().toISOString().slice(0, 16)}`,
        }));
        if (res.ok) toast(t('replay.started'), 'success');
        else toast(t('toast.error_detail', {detail: res.error || t('send.reason.unknown')}), 'error');
        await loadReplaySessionsList();
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function endReplaySession() {
    if (!_currentBotId) return;
    try {
        const res = await api('/api/replay/sessions');
        const sessions = res.sessions || [];
        const mine = sessions.find(s => s.account_id === _currentBotId && !s.ended_at);
        if (!mine) { toast(t('replay.none_active'), 'info'); return; }
        const end = await api(`/api/replay/sessions/${mine.id}/end`, { method: 'POST' });
        if (end.ok) toast(t('replay.ended'), 'success');
        await loadReplaySessionsList();
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

