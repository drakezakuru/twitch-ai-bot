// [P5-split] 05_bots_tabs.js ← static/app.js, исходные строки 4104–5048; грузится после предыдущего чанка, порядок = порядку строк

// ── TAB: AI (persona + account settings) ─────────────────────
async function loadBotAI(id) {
    try {
        const persona = await api(`/api/accounts/${id}/persona`);
        const p = persona.persona || {};
        const sliders = ['humor_level','sarcasm_level','darkness_level','crudeness_level','adult_humor','seriousness','emotionality','contact_level','chat_affinity'];
        sliders.forEach((k, i) => {
            const el = $('personaSliders')?.children[i];
            if (el && p[k] !== undefined) {
                el.querySelector('input').value = p[k];
                el.querySelector('.val').textContent = p[k];
            }
        });
    } catch (e) { console.error('loadBotAI', e); }
}

// ── TAB: Triggers ───────────────────────────────────────
async function loadBotTriggers(id) {
    try {
        const triggers = await api(`/api/accounts/${id}/triggers`);
        _triggersCache = triggers || [];
        renderTriggersList(_triggersCache);
    } catch (e) { console.error('loadBotTriggers', e); }
}

let _triggersCache = [];

function renderTriggersList(triggers) {
    const el = $('triggersList');
    if (!el) return;
    if (!triggers.length) {
        el.innerHTML = `<div class="text-muted text-sm">${esc(t('empty.no_triggers'))}</div>`;
        return;
    }
    el.innerHTML = triggers.map(tr => {
        // §10: канал, количество срабатываний и последний запуск прямо в карточке.
        const chBadge = tr.channel
            ? `<span class="badge">#${esc(tr.channel)}</span>`
            : `<span class="badge">${esc(t('triggers.channel_all'))}</span>`;
        const fires = t('triggers.fires', {count: tr.fires || 0});
        // SQLite CURRENT_TIMESTAMP хранится как "YYYY-MM-DD HH:MM:SS" (UTC) → приводим к ISO.
        const last = tr.last_fired_at
            ? esc(t('triggers.last_fired', {time: fmtTime(String(tr.last_fired_at).replace(' ', 'T') + 'Z')}))
            : esc(t('triggers.never_fired'));
        const mode = tr.use_ai ? `🤖 ${esc(t('events.ai'))}` : `💬 ${esc((tr.response || '').substring(0, 40))}`;
        return `
        <div class="card p-3 flex justify-between items-center">
            <div>
                <div class="font-semibold">⚡ ${esc(tr.keyword)} ${chBadge} ${tr.enabled ? '' : `<span class="badge off">${esc(t('health.disabled'))}</span>`}</div>
                <div class="text-xs text-muted">${mode}</div>
                <div class="text-xs text-muted">🔥 ${esc(fires)} · ${last}</div>
            </div>
            <div class="flex gap-2">
                <button class="btn btn-sm btn-secondary" onclick="testTrigger(${tr.id})">${t('triggers.test')}</button>
                <button class="btn btn-sm btn-secondary" onclick="toggleTrigger(${tr.id})">${tr.enabled ? t('btn.toggle_off') : t('btn.toggle_on')}</button>
                <button class="btn btn-sm btn-secondary" onclick="editTrigger(${tr.id})">${t('btn.edit')}</button>
                <button class="btn btn-sm btn-danger" onclick="deleteTrigger(${tr.id})">✕</button>
            </div>
        </div>
    `;}).join('');
}

async function testTrigger(id) {
    // §10: тестовый запуск — показываем, сработал бы триггер и почему нет.
    const tr = _triggersCache.find(item => item.id === id);
    const sample = prompt(t('triggers.test_prompt'), tr?.keyword || '');
    if (sample === null) return;
    try {
        const res = await api(`/api/triggers/${id}/test`, jopts('POST', { text: sample }));
        if (res.fired) {
            const mode = res.use_ai
                ? t('triggers.test_ok_ai')
                : t('triggers.test_ok_fixed', {response: res.response || ''});
            toast(t('triggers.test_ok', {mode}), 'success');
        } else {
            const reason = t(`triggers.reason.${res.reason}`) !== `triggers.reason.${res.reason}`
                ? t(`triggers.reason.${res.reason}`) : (res.error || res.reason || t('send.reason.unknown'));
            toast(t('triggers.test_fail', {reason}), 'error');
        }
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

function showAddTriggerModal() {
    $('triggerKeyword').value = '';
    $('triggerResponse').value = '';
    $('triggerUseAI')?.classList.add('active');
    // Селект канала (§10): «Все каналы» + каналы текущего бота.
    const sel = $('triggerChannel');
    if (sel) {
        sel.innerHTML = `<option value="">${esc(t('triggers.channel_all'))}</option>`
            + (_channelsCache || []).map(c => `<option value="${esc(c.channel_name)}">#${esc(c.channel_name)}</option>`).join('');
        sel.value = '';
    }
    showModal('addTriggerModal');
}

async function toggleTrigger(id) {
    try {
        await api(`/api/triggers/${id}/toggle`, { method: 'POST' });
        await loadBotTriggers(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function editTrigger(id) {
    let current;
    try {
        const triggers = await api(`/api/accounts/${_currentBotId}/triggers`);
        current = (triggers || []).find(item => item.id === id);
    } catch (e) {
        toast(t('toast.error_detail', {detail: e.message}), 'error');
        return;
    }
    if (!current) return;
    const nextKeyword = prompt(t('prompt.keyword'), current.keyword);
    if (nextKeyword === null) return;
    const nextResponse = prompt(t('prompt.fixed_response'), current.response || '');
    if (nextResponse === null) return;
    const nextChannel = prompt(t('triggers.channel_hint'), current.channel || '');
    if (nextChannel === null) return;
    try {
        await api(`/api/triggers/${id}`, jopts('PUT', {
            keyword: nextKeyword, response: nextResponse, use_ai: !!current.use_ai,
            channel: nextChannel,
        }));
        toast(t('toast.trigger_updated'), 'success');
        await loadBotTriggers(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function createTrigger() {
    if (!_currentBotId) return;
    const data = {
        keyword: $('triggerKeyword').value.trim(),
        use_ai: $('triggerUseAI')?.classList.contains('active') ?? true,
        response: $('triggerResponse').value.trim(),
        channel: $('triggerChannel')?.value || '',
    };
    try {
        await api(`/api/accounts/${_currentBotId}/triggers`, jopts('POST', data));
        hideModal('addTriggerModal');
        toast(t('toast.trigger_added'), 'success');
        loadBotTriggers(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function deleteTrigger(id) {
    if (!confirm(t('confirm.delete_named', {name: 'trigger'}))) return;
    try {
        await api(`/api/triggers/${id}`, { method: 'DELETE' });
        toast(t('toast.trigger_deleted'), 'success');
        loadBotTriggers(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

function showAddEventModal() {
    showModal('addEventModal');
}

async function createEvent() {
    if (!_currentBotId) return;
    const eventType = $('eventType').value;
    const response = $('eventResponse').value.trim();
    const chance = Math.max(0, Math.min(100, parseInt($('eventChance').value, 10) || 100));
    try {
        await api(`/api/accounts/${_currentBotId}/events`, jopts('POST', {
            event_type: eventType,
            response,
            chance,
            use_ai: $('eventUseAI')?.classList.contains('active') ?? false,
        }));
        hideModal('addEventModal');
        toast(t('toast.event_added'), 'success');
        await loadBotEvents(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

// ── TAB: Events ───────────────────────────────────────
async function loadBotEvents(id) {
    try {
        const events = await api(`/api/accounts/${id}/events`);
        renderEventsList(events || []);
    } catch (e) { console.error('loadBotEvents', e); }
}

function renderEventsList(events) {
    const el = $('eventsList');
    if (!el) return;
    if (!events.length) {
        el.innerHTML = `<div class="text-muted text-sm">${esc(t('empty.no_events'))}</div>`;
        return;
    }
    el.innerHTML = events.map(ev => `
        <div class="card p-3 flex justify-between items-center">
            <div>
                <div class="font-semibold">${esc(ev.event_type || ev.event)}</div>
                <div class="text-xs text-muted">${esc(t('events.chance', {chance: ev.chance}))}, ${ev.use_ai ? esc(t('events.ai')) : esc(t('events.fixed'))}</div>
            </div>
            <button class="btn btn-sm btn-danger" onclick="deleteEvent(${ev.id})">✕</button>
        </div>
    `).join('');
}

async function deleteEvent(id) {
    if (!confirm(t('confirm.delete_named', {name: 'event'}))) return;
    try {
        await api(`/api/events/${id}`, { method: 'DELETE' });
        toast(t('toast.event_deleted'), 'success');
        loadBotEvents(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

// ── TAB: Filters (Banlist + Wordfilter) ─────────────────
async function loadBotFilters(id) {
    try {
        const [banlist, wordfilter] = await Promise.all([
            api(`/api/accounts/${id}/banlist`),
            api(`/api/accounts/${id}/wordfilter`),
        ]);
        renderBanlist(banlist), renderWordfilter(wordfilter);
        // PLAN §2.1: выбор канала для нового слова («Все каналы» + каналы бота)
        const chSel = $('badWordChannel');
        if (chSel) {
            const current = chSel.value;
            chSel.innerHTML = `<option value="">${esc(t('wordfilter.all_channels'))}</option>` +
                (_channelsCache || []).map(c =>
                    `<option value="${esc(c.channel_name)}">${esc('#' + c.channel_name)}</option>`).join('');
            chSel.value = current;
        }
    } catch (e) { console.error('loadBotFilters', e); }
}

function renderBanlist(list) {
    const el = $('banlistList');
    if (!el) return;
    el.innerHTML = (list || []).map(u => `
        <div class="flex gap-2 items-center">
            <span class="badge">${esc(u.user || u.username || u.nickname)}</span>
            <button class="btn btn-sm btn-danger" onclick="unbanUser(${u.id})">✕</button>
        </div>
    `).join('') || `<div class="text-muted text-sm">${esc(t('empty.no_banned'))}</div>`;
}

async function addBannedUser() {
    const name = $('newBannedUser').value.trim();
    if (!name) return;
    try {
        await api(`/api/accounts/${_currentBotId}/banlist`, jopts('POST', { username: name }));
        toast(t('toast.user_banned'), 'success');
        $('newBannedUser').value = '';
        loadBotFilters(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function unbanUser(id) {
    try {
        await api(`/api/banlist/${id}`, { method: 'DELETE' });
        toast(t('toast.user_unbanned'), 'success');
        loadBotFilters(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

function renderWordfilter(list) {
    const el = $('wordfilterList');
    if (!el) return;
    el.innerHTML = (list || []).map(w => `
        <div class="flex gap-2 items-center">
            <span class="badge">${esc(w.word || w.pattern)}</span>
            <span class="text-xs text-muted">${w.action}</span>
            ${w.channel ? `<span class="text-xs text-muted">${esc('#' + w.channel)}</span>` : ''}
            <button class="btn btn-sm btn-danger" onclick="deleteWord(${w.id})">✕</button>
        </div>
    `).join('') || `<div class="text-muted text-sm">${esc(t('empty.no_filtered_words'))}</div>`;
}

async function addBadWord() {
    const word = $('newBadWord').value.trim();
    const action = $('badWordAction').value;
    if (!word) return;
    try {
        await api(`/api/accounts/${_currentBotId}/wordfilter`, jopts('POST', {
            word, action, channel: ($('badWordChannel')?.value || '').toLowerCase(),
        }));
        toast(t('toast.word_added'), 'success');
        $('newBadWord').value = '';
        loadBotFilters(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function deleteWord(id) {
    try {
        await api(`/api/wordfilter/${id}`, { method: 'DELETE' });
        toast(t('toast.word_deleted'), 'success');
        loadBotFilters(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

// ── TAB: Chat Users (§9c) ───────────────────────────────
async function loadBotChatUsers(id) {
    if (!id) return;
    try {
        const q = $('chatUsersSearch') ? $('chatUsersSearch').value.trim() : '';
        const role = $('chatUsersRoleFilter') ? $('chatUsersRoleFilter').value : '';
        const params = new URLSearchParams();
        if (q) params.set('q', q);
        if (role) params.set('role', role);
        const qs = params.toString();
        const data = await api(`/api/accounts/${id}/chat-users${qs ? '?' + qs : ''}`);
        renderChatUsersList(data.users || []);
    } catch (e) { console.error('loadBotChatUsers', e); }
}

function renderChatUsersList(users) {
    const el = $('chatUsersList');
    if (!el) return;
    if (!users.length) {
        el.innerHTML = `<div class="text-muted text-sm">${esc(t('empty.no_chat_users'))}</div>`;
        return;
    }
    el.innerHTML = users.map(u => `
        <div class="card p-3 flex justify-between items-center">
            <div class="flex items-center gap-2">
                <span class="font-semibold">${esc(u.username)}</span>
                <span class="role-badge">${esc(t(`label.role_${u.role || 'viewer'}`))}</span>
                <span class="text-xs text-muted">#${esc(u.channel)} · ${u.message_count || 0} ${esc(t('chat_users.messages_short'))}</span>
            </div>
            <div class="flex gap-2 items-center">
                <span class="text-xs ${u.enabled ? 'text-success' : 'text-muted'}">${u.enabled ? esc(t('chat_users.enabled')) : esc(t('chat_users.disabled'))}</span>
                <div class="toggle ${u.enabled ? 'active' : ''}" onclick="toggleChatUser('${esc(u.username)}', ${u.enabled ? 0 : 1})"></div>
            </div>
        </div>
    `).join('');
}

async function toggleChatUser(username, enabled) {
    if (!_currentBotId) return;
    try {
        await api(`/api/accounts/${_currentBotId}/chat-users/${encodeURIComponent(username)}`, jopts('PUT', { enabled }));
        toast(enabled ? t('chat_users.toast_enabled') : t('chat_users.toast_disabled'), 'success');
        loadBotChatUsers(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

// ── TAB: Memory ───────────────────────────────────────
async function loadBotMemory(id) {
    try {
        const mem = await api(`/api/accounts/${id}/memory`);
        renderMemoryList(mem || {});
    } catch (e) { console.error('loadBotMemory', e); }
    // Q17: расширенная память о зрителях (гейт по use_long_term_memory) и обучение.
    loadViewerMemoryGate(id);
    loadLearning();
}

// Q17: «Факты о зрителях» видны только если у бота включена долгосрочная память.
async function loadViewerMemoryGate(id) {
    if (!$('botViewerMemoryCard')) return;
    let enabled = false;
    try {
        const cfg = await api(`/api/accounts/${id}/analyzer`);
        enabled = !!cfg.use_long_term_memory;
    } catch (e) { /* выключено по умолчанию */ }
    setToggle('botLongTermMemory', enabled);
    const note = $('botMemoryDisabled');
    const list = $('botViewerMemoryList');
    if (enabled) {
        note?.classList.add('hidden');
        loadBotViewerMemory();
    } else {
        if (list) list.innerHTML = '';
        if (note) {
            note.classList.remove('hidden');
            note.textContent = t('bot.memory.disabled_hint');
        }
    }
}

async function saveBotLongTermMemory() {
    if (!_currentBotId) return;
    try {
        await api(`/api/accounts/${_currentBotId}/analyzer`, jopts('PUT', { use_long_term_memory: toggleChecked('botLongTermMemory') }));
        toast(t('msg.saved'), 'success');
        loadViewerMemoryGate(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

function renderMemoryList(data) {
    const el = $('memoryList');
    if (!el) return;
    const users = Array.isArray(data) ? data.map(item => [item.username, item]) : Object.entries(data.users || {});
    if (!users.length) {
        el.innerHTML = `<div class="text-muted text-sm">${panelI18n('memory.empty')}</div>`;
        return;
    }
    el.innerHTML = users.map(([nick, facts]) => {
        const factList = facts.facts || [];
        return `
        <div class="card p-3">
            <div class="flex justify-between items-center mb-2">
                <div class="font-semibold" data-user-content>${esc(nick)}</div>
                <button class="btn btn-sm btn-danger" ${panelI18nAttrs('btn.delete')} onclick="deleteMemoryUser('${esc(nick)}')">🗑</button>
            </div>
            <div class="text-xs text-muted">${panelI18n('dynamic.messages')}: ${facts.msg_count || 0}, ${panelI18n('dynamic.last_seen')}: ${facts.last_seen ? esc(new Date(facts.last_seen).toLocaleString()) : panelI18n('label.no_data')}</div>
            <div class="mt-2">${factList.map(f => `<div class="memory-fact text-sm"><span data-user-content>• ${esc(typeof f === 'object' ? f.fact : f)}</span><button class="btn btn-sm btn-secondary" ${panelI18nAttrs('btn.edit')} onclick="editMemoryFact('${esc(nick)}', '${esc(typeof f === 'object' ? f.fact : f)}')">✎</button><button class="btn btn-sm btn-danger" ${panelI18nAttrs('btn.delete')} onclick="deleteMemoryFact('${esc(nick)}', '${esc(typeof f === 'object' ? f.fact : f)}')">✕</button></div>`).join('') || `<div class="text-xs text-muted">${panelI18n('sharedfacts.no_facts')}</div>`}</div>
            <div class="flex gap-2 mt-3"><input class="input" id="memoryFact-${esc(nick)}" data-i18n-placeholder="dynamic.new_fact" data-i18n-aria-label="dynamic.new_fact" placeholder="${esc(t('dynamic.new_fact'))}" aria-label="${esc(t('dynamic.new_fact'))}"><button class="btn btn-primary btn-sm" onclick="addMemoryFact('${esc(nick)}')">${panelI18n('btn.add')}</button></div>
        </div>
    `;
    }).join('');
}

async function addMemoryFact(username) {
    const input = $(`memoryFact-${username}`);
    const fact = input?.value.trim();
    if (!fact || !_currentBotId) return;
    try {
        await api(`/api/accounts/${_currentBotId}/memory/${encodeURIComponent(username)}`, jopts('POST', { fact }));
        toast(t('toast.fact_saved'), 'success');
        loadBotMemory(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function deleteMemoryFact(username, fact) {
    if (!_currentBotId || !confirm(t('confirm.delete_item'))) return;
    try {
        await api(`/api/accounts/${_currentBotId}/memory/${encodeURIComponent(username)}/fact`, { method: 'DELETE', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ fact }) });
        loadBotMemory(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function editMemoryFact(username, oldFact) {
    const fact = prompt(t('prompt.edit_fact'), oldFact)?.trim();
    if (!fact || fact === oldFact) return;
    await deleteMemoryFact(username, oldFact);
    await addMemoryFactValue(username, fact);
}

async function addMemoryFactValue(username, fact) {
    try {
        await api(`/api/accounts/${_currentBotId}/memory/${encodeURIComponent(username)}`, jopts('POST', { fact }));
        loadBotMemory(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function deleteMemoryUser(username) {
    if (!_currentBotId || !confirm(t('confirm.delete_memory', {name: username}))) return;
    try {
        await api(`/api/accounts/${_currentBotId}/memory/${encodeURIComponent(username)}`, { method: 'DELETE' });
        loadBotMemory(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

// ── TAB: Streamer Profile (§9a «О стримере») ───────────
const STREAMER_LIST_FIELDS = [
    ['streamerInterests', 'interests'],
    ['streamerGames', 'favorite_games'],
    ['streamerLikes', 'likes'],
    ['streamerDislikes', 'dislikes'],
];

async function loadBotStreamer(id) {
    try {
        const [res, face] = await Promise.all([
            api(`/api/accounts/${id}/streamer-profile?channel=${encodeURIComponent('#' + ((_channelsCache || [])[0]?.channel_name || ''))}`),
            api(`/api/accounts/${id}/streamer-face?include=1`),
        ]);
        // §9.2: модель хранения «один профиль на бота» — явно показываем, к каким каналам он применяется
        const hint = $('streamerChannelHint');
        if (hint) {
            const chans = (_channelsCache || []).map(c => '#' + c.channel_name).join(', ');
            hint.textContent = chans
                ? t('streamer.channel_hint', {channels: chans})
                : t('streamer.channel_hint_none');
            // §5: показать, какой профиль реально применится (fallback-цепочка)
            try {
                const firstCh = (_channelsCache || [])[0]?.channel_name;
                const resolved = await api(`/api/streamer-profile/resolve?account_id=${id}${firstCh ? `&channel=%23${encodeURIComponent(firstCh)}` : ''}`);
                if (resolved && resolved.scope_label) {
                    hint.textContent += ` · ${resolved.scope_label}`;
                }
            } catch (e) { /* сниппет не критичен */ }
        }
        const profile = res.profile;
        const empty = $('streamerEmptyState');
        const form = $('streamerForm');
        if (!profile) {
            if (empty) empty.classList.remove('hidden');
            if (form) form.classList.add('hidden');
        } else {
            if (empty) empty.classList.add('hidden');
            if (form) form.classList.remove('hidden');
            if ($('streamerAge')) $('streamerAge').value = profile.age || '';
            if ($('streamerGender')) $('streamerGender').value = profile.gender || '';
            if ($('streamerLocation')) $('streamerLocation').value = profile.location || '';
            if ($('streamerOccupation')) $('streamerOccupation').value = profile.occupation || '';
            if ($('streamerBio')) $('streamerBio').value = profile.bio || '';
            if ($('streamerStyle')) $('streamerStyle').value = profile.streaming_style || '';
            setToggle('streamerAutoUpdated', !!profile.auto_updated);
            const lists = { interests: [], favorite_games: [], likes: [], dislikes: [] };
            for (const key of Object.keys(lists)) {
                const raw = profile[key];
                if (Array.isArray(raw)) lists[key] = raw;
                else if (typeof raw === 'string' && raw.trim()) {
                    try { const parsed = JSON.parse(raw); lists[key] = Array.isArray(parsed) ? parsed : [raw]; }
                    catch (e) { lists[key] = raw.split(',').map(x => x.trim()).filter(Boolean); }
                }
            }
            for (const [elId, key] of STREAMER_LIST_FIELDS) {
                const el = $(elId);
                if (el) el.value = (lists[key] || []).join(', ');
            }
        }
        // Фото (§9a.2)
        const preview = $('streamerFacePreview');
        const delBtn = $('streamerFaceDelete');
        if (preview) {
            if (face && face.has_face) {
                preview.innerHTML = `<img src="data:${face.mime_type || 'image/jpeg'};base64,${face.face_image_base64 || ''}" alt="streamer" style="max-width:120px;max-height:120px;border-radius:10px">`;
            } else {
                preview.innerHTML = `<span class="text-xs text-muted">${esc(t('streamer.face_none'))}</span>`;
            }
        }
        if (delBtn) delBtn.classList.toggle('hidden', !(face && face.has_face));
    } catch (e) { console.error('loadBotStreamer', e); }
}

function fillStreamerProfile() {
    const empty = $('streamerEmptyState');
    const form = $('streamerForm');
    if (empty) empty.classList.add('hidden');
    if (form) form.classList.remove('hidden');
}

async function saveStreamerProfile() {
    if (!_currentBotId) return;
    const facts = {
        age: parseInt($('streamerAge')?.value, 10) || 0,
        gender: $('streamerGender')?.value.trim() || '',
        location: $('streamerLocation')?.value.trim() || '',
        occupation: $('streamerOccupation')?.value.trim() || '',
        bio: $('streamerBio')?.value.trim() || '',
        streaming_style: $('streamerStyle')?.value || '',
        auto_updated: toggleChecked('streamerAutoUpdated'),
    };
    for (const [elId, key] of STREAMER_LIST_FIELDS) {
        const el = $(elId);
        facts[key] = el ? splitList(el.value) : [];
    }
    try {
        const channel = (_channelsCache || [])[0]?.channel_name || '';
        if (!channel) { toast(t('streamer.channel_required'), 'error'); return; }
        await api(`/api/accounts/${_currentBotId}/streamer-profile?channel=${encodeURIComponent('#' + channel)}`, jopts('PUT', facts));
        toast(t('streamer.saved'), 'success');
        await loadBotStreamer(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function uploadStreamerFace(input) {
    if (!_currentBotId || !input?.files?.[0]) return;
    const file = input.files[0];
    // Валидация на клиенте (§9a.2): jpeg/png до 2 МБ
    const okType = ['image/jpeg', 'image/png'].includes(file.type);
    const okSize = file.size <= 2 * 1024 * 1024;
    if (!okType || !okSize) {
        toast(t('streamer.face_invalid'), 'error');
        input.value = '';
        return;
    }
    const form = new FormData();
    form.append('file', file);
    try {
        await fetch(`${API}/api/accounts/${_currentBotId}/streamer-face`, { method: 'POST', body: form })
            .then(async res => { if (!res.ok) throw new Error(res.statusText); });
        toast(t('streamer.face_uploaded'), 'success');
        await loadBotStreamer(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
    input.value = '';
}

async function deleteStreamerFace() {
    if (!_currentBotId || !confirm(t('confirm.delete_item'))) return;
    try {
        await api(`/api/accounts/${_currentBotId}/streamer-face`, { method: 'DELETE' });
        toast(t('streamer.face_deleted'), 'success');
        await loadBotStreamer(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

// ── TAB: Snippets ─────────────────────────────────────
let _snippetsCache = [];

async function loadBotSnippets(id) {
    try {
        const snippets = await api(`/api/accounts/${id}/snippets`);
        _snippetsCache = snippets || [];
        _selectedSnippets.clear();
        renderSnippetsList();
    } catch (e) { console.error('loadBotSnippets', e); }
}

let _selectedSnippets = new Set();

function renderSnippetsList() {
    const el = $('snippetsList');
    if (!el) return;
    if (!_snippetsCache.length) {
        el.innerHTML = `<div class="text-muted text-sm">${esc(t('empty.no_snippets'))}</div>`;
        return;
    }
    const bulkBar = _selectedSnippets.size > 0 ? `
        <div class="flex gap-2 mb-3 p-2" style="background:var(--bg-card);border-radius:8px;border:1px solid var(--border)">
            <span class="text-sm" style="line-height:32px">${esc(t('common.selected', {count: _selectedSnippets.size}))}</span>
            <button class="btn btn-sm btn-danger" onclick="bulkDeleteSnippets()">🗑 ${t('btn.delete')} (${_selectedSnippets.size})</button>
            <button class="btn btn-sm btn-secondary" onclick="_selectedSnippets.clear();renderSnippetsList()">✕ ${t('btn.cancel')}</button>
        </div>` : '';
    el.innerHTML = bulkBar + _snippetsCache.map(s => {
        const checked = _selectedSnippets.has(s.id) ? 'checked' : '';
        return `
        <div class="card p-3 flex justify-between items-center">
            <div class="flex items-center gap-2">
                <input type="checkbox" ${checked} onchange="toggleSnippetSelect(${s.id}, this.checked)">
                <div>
                    <div class="font-semibold">${esc(s.name)}</div>
                    <div class="text-xs text-muted">${esc(s.text).substring(0,60)}...</div>
                </div>
            </div>
            <div class="flex gap-1">
                <button class="btn btn-sm btn-secondary" onclick="sendSnippet(${s.id})">▶ ${panelI18n('btn.send')}</button>
                <button class="btn btn-sm btn-danger" onclick="deleteSnippet(${s.id})">✕</button>
            </div>
        </div>`;
    }).join('');
}

function toggleSnippetSelect(id, checked) {
    if (checked) _selectedSnippets.add(id); else _selectedSnippets.delete(id);
    renderSnippetsList();
}

async function bulkDeleteSnippets() {
    if (!_currentBotId || !_selectedSnippets.size) return;
    if (!confirm(t('confirm.delete_snippets', {count: _selectedSnippets.size}))) return;
    try {
        const ids = [..._selectedSnippets];
        await Promise.all(ids.map(id => api(`/api/accounts/${_currentBotId}/snippets/${id}`, { method: 'DELETE' })));
        toast(t('toast.snippets_deleted', {detail: ids.length}), 'success');
        _selectedSnippets.clear();
        loadBotSnippets(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function sendSnippet(id) {
    const s = _snippetsCache.find(x => x.id === id);
    if (!s || !_currentBotId) return;
    // Відправляємо в перший активний канал
    try {
        const chans = await api(`/api/accounts/${_currentBotId}/channels`);
        if (chans && chans.length) {
            const ch = chans[0].channel_name;
            await api('/api/send', jopts('POST', { account_id: _currentBotId, channel: ch, text: s.text }));
            toast(t('toast.sent_to_channel', {detail: ch}), 'success');
        } else {
            toast(t('toast.no_channels_send'), 'error');
        }
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function createSnippet() {
    if (!_currentBotId) return;
    const data = {
        name: $('snippetName').value.trim(),
        text: $('snippetText').value.trim()
    };
    try {
        await api(`/api/accounts/${_currentBotId}/snippets`, jopts('POST', data));
        hideModal('addSnippetModal');
        toast(t('toast.snippet_added'), 'success');
        loadBotSnippets(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function deleteSnippet(id) {
    if (!_currentBotId || !confirm(t('confirm.delete_item'))) return;
    try {
        await api(`/api/accounts/${_currentBotId}/snippets/${id}`, { method: 'DELETE' });
        toast(t('toast.snippet_deleted'), 'success');
        loadBotSnippets(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

// v12: генерація випадкових заготовок через AI (A4: без «молчаливых фейлов»)
async function generateRandomSnippets() {
    if (!_currentBotId) return;
    try {
        toast(t('toast.generating_snippets'), 'info');
        const res = await api('/api/ai/generate-snippets', jopts('POST', { account_id: _currentBotId, count: 5 }));
        if (res.ok === false) {
            toast(t('toast.error_detail', {detail: res.error || 'ai_error'}), 'error');
            return;
        }
        if (!res.snippets || !res.snippets.length) {
            const reasonKey = { no_json: 'gen.reason_no_json', empty: 'gen.reason_empty', json_parse_error: 'gen.reason_no_json' }[res.reason] || 'gen.reason_empty';
            toast(t('toast.snippets_zero', {reason: t(reasonKey)}), 'error');
            return;
        }
        for (const s of res.snippets) {
            await api(`/api/accounts/${_currentBotId}/snippets`, jopts('POST', { name: s.name, text: s.text }));
        }
        toast(t('toast.snippets_added', {detail: res.snippets.length}), 'success');
        loadBotSnippets(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

// ── Voice Clones ───────────────────────────────────────
async function loadBotVoiceClones(id) {
    try {
        const [cloneData, modelData] = await Promise.all([api(`/api/voice-clones`), api('/api/voice-clone/models')]);
        renderVoiceClonesList([...(cloneData.clones || []), ...(modelData.models || []).map(m => ({...m, provider: 'piper'}))]);
    } catch (e) { console.error('loadBotVoiceClones', e); }
}

async function openVoiceCloneGuide() {
    const guide = $('voiceCloneGuide');
    if (!guide) return;
    try {
        const result = await api('/api/voice-clone/setup-guide');
        guide.textContent = result.md || result.content || t('status.no_clones');
        guide.classList.toggle('hidden');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function createVoiceClone() {
    const name = $('voiceCloneName')?.value.trim();
    const file = $('voiceCloneSample')?.files?.[0];
    if (!name) { toast(t('toast.enter_snippet'), 'error'); return; }
    let sample_b64 = '';
    if (file) {
        const bytes = new Uint8Array(await file.arrayBuffer());
        let binary = ''; bytes.forEach(byte => { binary += String.fromCharCode(byte); });
        sample_b64 = btoa(binary);
    }
    try {
        const result = await api('/api/voice-clones', jopts('POST', {
            name, provider: $('voiceCloneProvider')?.value || 'xtts', sample_b64,
            sample_ext: file ? '.' + (file.name.split('.').pop() || 'wav') : '.wav',
        }));
        if (!result.ok) throw new Error(result.error || 'clone creation failed');
        toast(t('status.uploaded'), 'success');
        $('voiceCloneName').value = ''; if ($('voiceCloneSample')) $('voiceCloneSample').value = '';
        loadBotVoiceClones(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function uploadVoiceModel(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
        const bytes = await file.arrayBuffer();
        let binary = '';
        new Uint8Array(bytes).forEach(byte => { binary += String.fromCharCode(byte); });
        const result = await api('/api/voice-clone/upload', jopts('POST', {
            name: file.name.replace(/\.onnx$/i, ''),
            onnx_b64: btoa(binary),
        }));
        if (!result.ok) throw new Error(result.error || 'upload failed');
        toast(t('toast.voice_model_uploaded'), 'success');
        loadBotVoiceClones(_currentBotId);
        loadBotTTS(_currentBotId);
    } catch (e) { toast(t('toast.voice_upload_error', {detail: e.message}), 'error'); }
    event.target.value = '';
}

function renderVoiceClonesList(clones) {
    const el = $('voiceClonesList');
    if (!el) return;
    if (!clones.length) {
        el.innerHTML = `<div class="text-muted text-sm">${esc(t('voiceclones.empty'))}</div>`;
        return;
    }
    el.innerHTML = clones.map(c => `
        <div class="card p-3 flex justify-between items-center">
            <div><div class="font-semibold">${esc(c.name)}</div><div class="text-xs text-muted">${esc(c.provider || 'local')} ${esc(c.language || c.lang || '')}</div></div>
            <div class="flex gap-2">
                ${c.id ? `<button class="btn btn-sm btn-secondary" onclick="previewVoiceClone(${c.id})">🔊</button>` : ''}
                ${c.id ? `<button class="btn btn-sm btn-danger" onclick="deleteClone(${c.id})">✕</button>` : ''}
            </div>
        </div>
    `).join('');
}

async function previewVoiceClone(id) {
    try {
        const response = await fetch(`/api/voice-clones/${id}/preview`, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({text: 'Привет, чат!'})
        });
        if (!response.ok) throw new Error(await response.text());
        const type = response.headers.get('content-type') || '';
        if (type.includes('audio/')) {
            const audio = new Audio(URL.createObjectURL(await response.blob()));
            audio.onended = () => URL.revokeObjectURL(audio.src);
            await audio.play();
        } else {
            const data = await response.json();
            if (data.mode === 'web_speech' && window.speechSynthesis) {
                const utterance = new SpeechSynthesisUtterance(data.text);
                utterance.rate = data.rate || 1; utterance.pitch = data.pitch || 1;
                speechSynthesis.speak(utterance);
            }
        }
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

// ── TAB: Knowledge base + Mimicry (streamer KB / style examples) ──────────
// §2.2 PLAN_FEEDBACK_3008: скоуп записей KB — «🌐 все каналы» или конкретный канал
function fillKbChannelSelect() {
    const sel = $('kbChannel');
    if (!sel) return;
    const cur = sel.value;
    sel.innerHTML = `<option value="" data-i18n="label.all_channels">${esc(t('label.all_channels'))}</option>` +
        (_channelsCache || []).map(c => `<option value="${esc(c.channel_name)}">#${esc(c.channel_name)}</option>`).join('');
    if (cur && [...sel.options].some(o => o.value === cur)) sel.value = cur;
}

function kbChannelScope() { return $('kbChannel')?.value || ''; }

async function loadKnowledge(id) {
    fillKbChannelSelect();
    try {
        const [kb, styles] = await Promise.all([
            api(`/api/accounts/${id}/kb?channel=${encodeURIComponent(kbChannelScope())}`),
            api(`/api/accounts/${id}/style-examples`),
        ]);
        renderKnowledgeList(kb?.items || []);
        renderStyleExamplesList(styles?.items || []);
    } catch (e) { console.error('loadKnowledge', e); }
    await loadAbTest(id);
}

// ── Владелец 27.09 (вечер): A/B тест промптов — бэкенд (v8 Feature 3) был
// готов давно (app/ai_quality_db.py + app/ab_dashboard.py), экрана не было ──
function _abTestRecommendationBadge(rec) {
    if (rec === 'leader') return `<span class="badge badge-success">${esc(t('abtest.rec_leader'))}</span>`;
    if (rec === 'drop') return `<span class="badge badge-warning">${esc(t('abtest.rec_drop'))}</span>`;
    return '';
}

async function loadAbTest(id) {
    try {
        const [variants, dashboard] = await Promise.all([
            api(`/api/accounts/${id}/prompt-variants`),
            api(`/api/ab-dashboard?account_id=${id}`),
        ]);
        setToggle('abTestEnabled', (await api(`/api/accounts/${id}/analyzer`)).use_ab_variants);
        const recByVariantId = {};
        (dashboard?.variants || []).forEach(v => { recByVariantId[v.id] = v.recommendation; });
        renderAbTestVariants(variants?.items || [], recByVariantId);
        renderAbTestSummary(dashboard?.summary, dashboard?.variants || []);
    } catch (e) { console.error('loadAbTest', e); }
}

function renderAbTestSummary(summary, ranked) {
    const el = $('abTestSummary');
    if (!el) return;
    if (!summary || !summary.n_responses) {
        el.innerHTML = `<span class="text-muted">${esc(t('abtest.no_data'))}</span>`;
        return;
    }
    el.innerHTML = `
        <span class="badge">${esc(t('abtest.responses'))}: ${summary.n_responses}</span>
        <span class="badge badge-success">👍 ${summary.likes}</span>
        <span class="badge badge-warning">👎 ${summary.dislikes}</span>
        <span class="badge">${esc(t('abtest.like_ratio'))}: ${Math.round((summary.like_ratio || 0) * 100)}%</span>
        ${summary.leader ? `<span class="badge badge-success">${esc(t('abtest.leader'))}: ${esc(summary.leader)}</span>` : ''}
    `;
}

async function toggleAbTestEnabled() {
    if (!_currentBotId) return;
    try {
        await api(`/api/accounts/${_currentBotId}/analyzer`, jopts('PUT', { use_ab_variants: toggleChecked('abTestEnabled') }));
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

function renderAbTestVariants(items, recByVariantId = {}) {
    const el = $('abTestVariantsList');
    if (!el) return;
    if (!items.length) {
        el.innerHTML = `<div class="text-muted text-sm">${esc(t('abtest.empty'))}</div>`;
        return;
    }
    el.innerHTML = items.map(v => `
        <div class="card p-3">
            <div class="flex justify-between items-start gap-2 flex-wrap">
                <div class="flex items-center gap-2">
                    <strong>${esc(v.label)}</strong>
                    ${_abTestRecommendationBadge(recByVariantId[v.id])}
                    <span class="badge">${esc(t('abtest.weight'))}: ${v.weight}</span>
                    <span class="badge">${esc(t('abtest.responses'))}: ${v.count}</span>
                    <span class="badge badge-success">👍 ${v.likes}</span>
                    <span class="badge badge-warning">👎 ${v.dislikes}</span>
                    ${v.enabled ? '' : `<span class="badge off">${esc(t('health.disabled'))}</span>`}
                </div>
                <div class="flex gap-1">
                    <button class="btn btn-sm btn-secondary" onclick="toggleAbTestVariant(${v.id}, ${v.enabled ? 0 : 1})">${v.enabled ? '⏸' : '▶'}</button>
                    <button class="btn btn-sm btn-danger" onclick="deleteAbTestVariant(${v.id})">✕</button>
                </div>
            </div>
            <div class="text-xs text-muted mt-1" data-user-content>${esc(v.system_prompt)}</div>
        </div>`).join('');
}

async function addAbTestVariant() {
    if (!_currentBotId) return;
    const label = $('abTestNewLabel')?.value.trim() || 'A';
    const weight = parseInt($('abTestNewWeight')?.value, 10) || 50;
    const system_prompt = $('abTestNewPrompt')?.value.trim() || '';
    if (!system_prompt) { toast(t('abtest.error_prompt'), 'error'); return; }
    try {
        await api(`/api/accounts/${_currentBotId}/prompt-variants`, jopts('POST', { label, weight, system_prompt }));
        $('abTestNewLabel').value = ''; $('abTestNewWeight').value = '50'; $('abTestNewPrompt').value = '';
        toast(t('abtest.saved'), 'success');
        loadAbTest(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function toggleAbTestVariant(variantId, enabled) {
    try {
        await api(`/api/accounts/${_currentBotId}/prompt-variants/${variantId}`, jopts('PUT', { enabled: !!enabled }));
        loadAbTest(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function deleteAbTestVariant(variantId) {
    if (!confirm(t('confirm.delete_item'))) return;
    try {
        await api(`/api/accounts/${_currentBotId}/prompt-variants/${variantId}`, { method: 'DELETE' });
        loadAbTest(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

function renderKnowledgeList(items) {
    const el = $('knowledgeList');
    if (!el) return;
    if (!items.length) {
        el.innerHTML = `<div class="text-muted text-sm">${esc(t('kb.empty'))}</div>`;
        return;
    }
    el.innerHTML = items.map(k => {
        // §2.2: бейдж скоупа — запись для конкретного канала или «все каналы»
        const scope = k.channel ? `<span class="badge" ${panelI18nAttrs('dynamic.channel_scope')}>#${esc(k.channel)}</span>`
            : `<span class="badge badge-success" ${panelI18nAttrs('dynamic.all_scope')}>${panelI18n('label.all_channels')}</span>`;
        return `
        <div class="card p-3 flex justify-between items-center">
            <div>
                <div class="font-semibold">${esc(k.topic)} ${scope}</div>
                <div class="text-xs text-muted">${esc(k.content)}</div>
            </div>
            <button class="btn btn-sm btn-danger" onclick="deleteKnowledgeItem(${k.id})">✕</button>
        </div>`;
    }).join('');
}

async function addKnowledgeItem() {
    if (!_currentBotId) return;
    const topic = $('kbTopic')?.value.trim();
    const content = $('kbContent')?.value.trim();
    const tags = $('kbTags')?.value.trim() || '';
    if (!topic || !content) { toast(t('toast.error_detail', {detail: 'topic/content required'}), 'error'); return; }
    try {
        await api(`/api/accounts/${_currentBotId}/kb`, jopts('POST', { topic, content, tags, channel: kbChannelScope() }));
        $('kbTopic').value = ''; $('kbTags').value = ''; $('kbContent').value = '';
        toast(t('toast.fact_saved'), 'success');
        loadKnowledge(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function deleteKnowledgeItem(id) {
    if (!confirm(t('confirm.delete_item'))) return;
    try {
        await api(`/api/accounts/${_currentBotId}/kb/${id}`, { method: 'DELETE' });
        loadKnowledge(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

function renderStyleExamplesList(items) {
    const el = $('styleExamplesList');
    if (!el) return;
    if (!items.length) {
        el.innerHTML = `<div class="text-muted text-sm">${esc(t('mimicry.empty'))}</div>`;
        return;
    }
    el.innerHTML = items.map(s => `
        <div class="card p-3 flex justify-between items-center">
            <div class="text-sm">${esc(s.message)}</div>
            <button class="btn btn-sm btn-danger" onclick="deleteStyleExample(${s.id})">✕</button>
        </div>
    `).join('');
}

async function addStyleExample() {
    if (!_currentBotId) return;
    const message = $('styleExampleText')?.value.trim();
    if (!message) return;
    try {
        await api(`/api/accounts/${_currentBotId}/style-examples`, jopts('POST', { message }));
        $('styleExampleText').value = '';
        toast(t('toast.fact_saved'), 'success');
        loadKnowledge(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function deleteStyleExample(id) {
    if (!confirm(t('confirm.delete_item'))) return;
    try {
        await api(`/api/accounts/${_currentBotId}/style-examples/${id}`, { method: 'DELETE' });
        loadKnowledge(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

function showAddSnippetModal() {
    $('snippetName') && ($('snippetName').value = '');
    $('snippetText') && ($('snippetText').value = '');
    showModal('addSnippetModal');
}

function showAddVoiceCloneModal() {
    // No dedicated modal exists yet; voice clone creation form lives inline
    // in the TTS/voice-clones tab, so just focus the user on that tab.
    showBotTab('voice-clones');
}

// ── Modal helpers ─────────────────────────────────────
function showModal(name, options = {}) {
    const onDismiss = name === 'addBotModal' ? hideAddBotModal
        : name === 'onboardingOverlay' ? dismissOnboarding : undefined;
    openPanelDialog(name, {onDismiss, ...options});
}
function hideModal(name) {
    closePanelDialog(name);
}

