// [P5-split] 14_brain_memory.js ← static/app.js, исходные строки 8600–8814; грузится после предыдущего чанка, порядок = порядку строк

// ── Brain: память priority/TTL edit, KB import/export, revert-last, summarizer export, affinity levels (BRAIN_PLAN §1/§3/§4/§6/§7) ──

// ---------- §1: редактирование priority/TTL факта ----------
function brainEditFact(username, fact, priority, hasExpiry) {
    const box = document.getElementById('botViewerMemoryList');
    if (!box) return;
    const old = document.getElementById('brainFactEditForm');
    if (old) old.remove();
    const div = document.createElement('div');
    div.id = 'brainFactEditForm';
    div.className = 'p-2 mb-2 form-panel';
    div.dataset.fact = fact;
    div.innerHTML = `
        <div class="text-sm font-semibold mb-1">✎ ${panelI18n('dynamic.fact')}: <span data-user-content>${esc(fact)}</span></div>
        <div class="flex gap-2 mb-2 flex-wrap items-center text-sm">
            <label>${panelI18n('dynamic.priority')}: <input type="number" id="brainFactPr" class="input" style="max-width:90px" min="0" max="100" value="${Number(priority) || 50}"></label>
            <label>${panelI18n('dynamic.ttl')}: <input type="number" id="brainFactTtl" class="input" style="max-width:90px" min="0" value="0"></label>
            <span class="text-xs text-muted">${panelI18n(hasExpiry ? 'dynamic.has_expiry' : 'dynamic.no_expiry')}</span>
        </div>
        <div class="flex gap-2">
            <button class="btn btn-primary btn-sm" onclick="brainSaveFactEdit('${esc(username)}')">${panelI18n('btn.save')}</button>
            <button class="btn btn-secondary btn-sm" onclick="document.getElementById('brainFactEditForm')?.remove()">${panelI18n('btn.cancel')}</button>
        </div>`;
    box.prepend(div);
}

async function brainSaveFactEdit(username) {
    const acc = _memoryAcc(); if (!acc) return;
    const factText = document.getElementById('brainFactEditForm')?.dataset.fact || '';
    const priority = parseInt(document.getElementById('brainFactPr')?.value || '50');
    const ttlDays = parseInt(document.getElementById('brainFactTtl')?.value || '0');
    const body = { fact: factText, priority };
    if (ttlDays > 0) body.ttl = ttlDays * 86400;
    else body.expires_at = null;
    const res = await api(`/api/accounts/${acc}/memory/${encodeURIComponent(username)}/fact`, jopts('PUT', body));
    if (res.ok) { toast(t('dynamic.fact_updated'), 'success'); loadBotViewerMemory(); }
    else toast(res.error || t('label.error'), 'error');
}

// Q17: импорт/экспорт KB удалён вместе с карточкой «Мозга» (DEC-OWNER-003).

// ---------- §6: отменить последнее обучение ----------
async function learningRevertLast() {
    const acc = _memoryAcc(); if (!acc) return toast(t('dynamic.pick_bot'), 'error');
    if (!confirm(t('dynamic.revert_confirm'))) return;
    const res = await api(`/api/accounts/${acc}/learning/revert_last`, jopts('POST', {}));
    if (res.ok) { toast(t('dynamic.reverted', {kind: res.kind || ''}), 'success'); loadLearning(); }
    else toast(res.error === 'nothing_applied' ? t('dynamic.nothing_to_revert') : (res.error || t('label.error')), 'error');
}

// ---------- §4: экспорт прогона summarizer ----------
function _brainDownload(name, content, mime) {
    const blob = new Blob([content], { type: mime || 'text/plain' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    URL.revokeObjectURL(a.href);
}

async function summarizerExportRun(runId, fmt) {
    const acc = _brainAcc(); if (!acc) return;
    try {
        const res = await api(`/api/accounts/${acc}/summarizer/runs/${runId}`);
        if (!res.ok) return toast(res.error || t('api.error.not_found'), 'error');
        const r = res.run;
        if (fmt === 'json') {
            _brainDownload(`summary_${r.channel}_${r.run_date}.json`, JSON.stringify(r, null, 2), 'application/json');
        } else {
            _brainDownload(`summary_${r.channel}_${r.run_date}.md`, r.summary_md || '', 'text/markdown');
        }
    } catch (e) { toast(e.message, 'error'); }
}

// ---------- §7: уровни привязанности рядом с числом ----------
function brainAffinityLevel(v) {
    const n = parseInt(v) || 0;
    if (n >= 80) return t('dynamic.affinity_close');
    if (n >= 60) return t('dynamic.affinity_regular');
    if (n >= 40) return t('dynamic.affinity_familiar');
    if (n >= 20) return t('dynamic.affinity_viewer');
    return t('dynamic.affinity_stranger');
}

function brainAffinityLevels() {
    for (const [id, name] of [['affinityContact', 'стримеру'], ['affinityChat', 'чату']]) {
        const slider = document.getElementById(id);
        if (!slider) continue;
        const label = slider.closest('label');
        if (!label) continue;
        let badge = label.querySelector('.brain-aff-level');
        if (!badge) {
            badge = document.createElement('span');
            badge.className = 'brain-aff-level text-xs text-muted';
            badge.style.marginLeft = '6px';
            label.appendChild(badge);
            slider.addEventListener('input', brainAffinityLevels);
        }
        badge.textContent = `— ${brainAffinityLevel(slider.value)}`;
    }
}

(function brainAffinityPatch() {
    if (typeof window.loadBotPersona === 'function' && !window._brainAffPatched) {
        const orig = window.loadBotPersona;
        window.loadBotPersona = async function (...args) {
            const r = await orig.apply(this, args);
            setTimeout(brainAffinityLevels, 50);
            return r;
        };
        window._brainAffPatched = true;
    }
})();

// ---------- §1: авто-извлечение фактов из чата (предложения через lore) ----------
async function brainAutoExtract() {
    const acc = _memoryAcc(); if (!acc) return toast(t('dynamic.pick_bot'), 'error');
    toast(t('dynamic.extracting'), 'info');
    try {
        // Q17: во вкладке бота канальный скоуп не выбирается — извлекаем по всем каналам бота.
        const res = await api(`/api/accounts/${acc}/memory_auto_extract`, jopts('POST', { channel: '' }));
        if (res.ok) {
            const n = (res.candidates || []).length;
            toast(n ? t('dynamic.extracted', {count: n}) : t('dynamic.no_new_facts'), n ? 'success' : 'info');
            loadLore();
        } else toast(res.error || t('label.error'), 'error');
    } catch (e) { toast(e.message, 'error'); }
}

// Q09d/Q19: live-настройки и их DOM переехали в модалку «Профиль канала»
// (19_channels_bulk.js, cpLoadSummarySettings/cpSaveSummarySettings); «весь бот»
// больше нигде не выбирается — dead-код удалён.

// ── Фидбек 29.08: i18n источника лога (бот / панель) ──
Object.assign(LANGS.ru, { 'logs.panel': 'Панель' });
Object.assign(LANGS.en, { 'logs.panel': 'Panel' });
Object.assign(LANGS.ua, { 'logs.panel': 'Панель' });

