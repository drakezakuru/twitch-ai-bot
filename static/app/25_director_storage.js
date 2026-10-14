// ── Director storage & sessions ────────────────────
// Session list, storage usage/pin/export/delete, prompt diff/delete and lifecycle
// diagnostics. Reuses the global helpers from 20_director.js (loaded earlier).
let _directorStorage = {
    channel: '', sessions: [], sessionId: '', manifest: null, request: 0,
    pending: new Set(), confirmText: '', diff: null, diffPromptId: null, error: null, exportResult: null,
};

function _directorStorageURL(channel, path) { return `/api/director/${encodeURIComponent(channel)}${path}`; }

// DEF-06 (R-UI1): слово-подтверждение удаления локализовано (DELETE/ВИДАЛИТИ), но на бэкенд
// всегда уходит канонический sentinel «УДАЛИТЬ» — контракт director.delete_session_evidence
// (app/director.py: «confirmation != "УДАЛИТЬ"») не меняется.
const DIRECTOR_DELETE_CONFIRM_SENTINEL = 'УДАЛИТЬ';
const DIRECTOR_DELETE_CONFIRM_ALIASES = { 'удалить': 1, 'delete': 1, 'видалити': 1 };

function _directorDeleteConfirm(value) {
    const word = String(value || '').trim().toLowerCase();
    return (word === 'удалить' || DIRECTOR_DELETE_CONFIRM_ALIASES[word]) ? DIRECTOR_DELETE_CONFIRM_SENTINEL : '';
}
function _directorPauseReasonKey(reason) {
    return { manual: 'pause_reason_manual', sources: 'pause_reason_sources', ai_errors: 'pause_reason_ai_errors', offline: 'pause_reason_offline' }[reason] || 'pause_reason_unknown';
}
function directorStorageConfirmChanged(value) { _directorStorage.confirmText = value; renderDirectorStorage(); }
function directorStorageSelect(sessionId) { _directorStorage.sessionId = sessionId; _directorStorage.manifest = null; loadDirectorStorage(); }

async function loadDirectorStorage() {
    const channel = _directorChannel;
    if (!channel) return;
    const request = ++_directorStorage.request;
    try {
        const calls = [api(_directorStorageURL(channel, '/sessions'))];
        if (_directorStorage.sessionId) calls.push(api(_directorStorageURL(channel, `/sessions/${encodeURIComponent(_directorStorage.sessionId)}/storage`)));
        const [sessions, manifest] = await Promise.all(calls);
        // Late responses from a previous channel must never render here.
        if (request !== _directorStorage.request || channel !== _directorChannel) return;
        _directorStorage.sessions = sessions.sessions || [];
        if (!_directorStorage.sessionId && _directorStorage.sessions[0]) _directorStorage.sessionId = _directorStorage.sessions[0].id;
        _directorStorage.manifest = manifest || null;
        _directorStorage.error = null;
    } catch (error) {
        if (request !== _directorStorage.request || channel !== _directorChannel) return;
        _directorStorage.error = error;
    }
    renderDirectorStorage();
}

function _directorStorageBytes(key) { return _directorLabel(key); }
function _directorStorageUsage(manifest) {
    const fmt = value => value == null ? '—' : `${Math.round(value / 1024)} KiB`;
    const rows = [
        ['storage_total', manifest?.total_size_bytes],
        ['storage_limit', manifest?.limit_bytes],
        ['storage_pinned', manifest?.pinned_bytes],
        ['storage_pinned_limit', manifest?.pinned_limit_bytes],
    ];
    return `<table class="text-sm"><tbody>${rows.map(([key, value]) => `<tr><td>${_directorStorageBytes(key)}</td><td>${esc(fmt(value))}</td></tr>`).join('')}</tbody></table>`;
}
function _directorStorageArtifacts(manifest) {
    const artifacts = manifest?.artifacts || [];
    if (!artifacts.length) return `<p class="text-sm text-muted">${_directorLabel('storage_empty')}</p>`;
    return `<ul class="text-sm">${artifacts.map(item => {
        const id = _directorAttr(item.id);
        const busy = _directorStorage.pending.has(`pin:${id}`);
        return `<li><code>${esc(item.path)}</code> · ${_directorLabel('storage_' + (item.kind === 'transcript' ? 'kind_transcript' : item.kind === 'frame' ? 'kind_frame' : 'kind_other'))} · ${esc(String(item.size_bytes ?? ''))} B ${item.pinned ? `<strong>${_directorLabel('storage_pinned_badge')}</strong>` : ''}
            <button type="button" class="btn btn-secondary btn-sm" data-asset-id="${id}" data-pinned="${item.pinned ? '1' : '0'}" onclick="directorStoragePin(this.dataset.assetId,this.dataset.pinned==='1')" ${busy ? 'disabled' : ''}>${_directorLabel(item.pinned ? 'pin_remove' : 'pin_add')}</button></li>`;
    }).join('')}</ul>`;
}

function renderDirectorStorage() {
    const container = $('directorStoragePanel');
    if (!container) return;
    if (_directorStorage.error) {
        container.innerHTML = `<p class="text-sm text-muted" aria-live="polite">${_directorError(_directorStorage.error)}</p>`;
        return;
    }
    const state = _directorState || {};
    const session = state.session || {};
    const status = session.state || state.status || 'off';
    const pauseReason = session.pause_reason || (status === 'paused' ? 'manual' : null);
    const sessions = _directorStorage.sessions.map(item => {
        const selected = String(item.id) === String(_directorStorage.sessionId);
        return `<li><button type="button" class="btn ${selected ? 'btn-primary' : 'btn-secondary'} btn-sm" data-session-id="${_directorAttr(item.id)}" onclick="directorStorageSelect(this.dataset.sessionId)">
            <code>${esc(String(item.id).slice(0, 8))}</code> · ${_directorLabel('status_' + (item.state === 'stopped' ? 'off' : item.state))}
            ${item.pause_reason ? ` · ${_directorLabel(_directorPauseReasonKey(item.pause_reason))}` : ''}${item.emergency_fence ? ' · 🚫' : ''}</button></li>`;
    }).join('');
    const manifest = _directorStorage.manifest;
    const sessionForStorage = _directorStorage.sessionId;
    const exportBusy = _directorStorage.pending.has('export');
    const deleteBusy = _directorStorage.pending.has('delete');
    const confirmReady = _directorDeleteConfirm(_directorStorage.confirmText) !== '';
    const exportBlock = manifest?.session_missing ? '' : `
        <div class="flex gap-2 mt-2 flex-wrap">
            <button type="button" class="btn btn-primary btn-sm" onclick="directorStorageExport()" ${!sessionForStorage || exportBusy ? 'disabled' : ''}>${_directorLabel('storage_export')}</button>
            <input class="input" style="max-width:12rem" placeholder="${_directorAttr(_directorT('storage_delete_placeholder'))}" oninput="directorStorageConfirmChanged(this.value)">
            <button type="button" class="btn btn-danger btn-sm" onclick="directorStorageDelete()" ${!sessionForStorage || deleteBusy || !confirmReady ? 'disabled' : ''}>${_directorLabel('storage_delete')}</button>
        </div>
        <p class="text-sm text-muted">${_directorLabel('storage_delete_hint')}</p>
        ${_directorStorage.exportResult ? `<p class="text-sm"><a href="${_directorAttr(_directorStorage.exportResult.url)}" download>${_directorLabel('storage_download_ready')} (${esc(_directorStorage.exportResult.path)})</a></p>` : ''}`;
    const prompts = (_directorReview().prompts || []);
    const promptRows = prompts.map(prompt => {
        const id = _directorAttr(prompt.id);
        const busy = _directorStorage.pending.has(`prompt:${id}`);
        return `<li><strong>v${esc(String(prompt.version))}</strong> ${prompt.active ? _directorLabel('prompt_active') : ''} ${prompt.retired ? _directorLabel('prompt_retired') : ''}
            <button type="button" class="btn btn-secondary btn-sm" data-prompt-id="${id}" onclick="directorPromptDiff(this.dataset.promptId)" ${busy ? 'disabled' : ''}>${_directorLabel('prompt_diff')}</button>
            <button type="button" class="btn btn-secondary btn-sm" data-prompt-id="${id}" onclick="directorPromptDelete(this.dataset.promptId)" ${busy || prompt.active ? 'disabled' : ''}>${_directorLabel('prompt_delete')}</button></li>`;
    }).join('');
    const health = state.health || {};
    const emergency = status === 'emergency';
    const lastWorking = emergency
        ? (_directorReview().prompts || []).filter(prompt => _directorReplayValid(prompt)).sort((a, b) => b.version - a.version)[0] || null
        : null;
    const emergencyHint = lastWorking ? `<p class="text-sm" aria-live="polite">${_directorLabel('last_working_prompt')} <strong>v${esc(String(lastWorking.version))}</strong>
        <button type="button" class="btn btn-secondary btn-sm" data-prompt-id="${_directorAttr(lastWorking.id)}" onclick="directorActivatePrompt(this.dataset.promptId)">${_directorLabel('prompt_activate')}</button>
        ${_directorLabel('emergency_replay_hint')}</p>` : '';
    const diagnostics = `<p class="text-sm">${['ai', 'vision', 'speech', 'twitch'].map(source => `${_directorLabel('source_' + source)}: ${_directorLabel('status_' + (health[source] === true ? 'healthy' : health[source] === false ? 'unavailable' : 'unknown'))}`).join(' · ')}
        ${pauseReason ? ` · ${_directorLabel(_directorPauseReasonKey(pauseReason))}` : ''}</p>${emergencyHint}`;
    container.innerHTML = `
        <h2 class="section-subtitle">${_directorLabel('storage_title')}</h2>
        <ul class="text-sm">${sessions || `<li class="text-muted">${_directorLabel('storage_no_sessions')}</li>`}</ul>
        ${diagnostics}
        <h3 class="text-sm"><strong>${_directorLabel('storage_usage')}</strong></h3>
        ${manifest ? _directorStorageUsage(manifest) : `<p class="text-sm text-muted">${_directorLabel('storage_select_session')}</p>`}
        ${manifest ? _directorStorageArtifacts(manifest) : ''}
        ${exportBlock}
        <details class="mt-2"><summary>${_directorLabel('prompt_versions')}</summary><ul class="text-sm">${promptRows || `<li class="text-muted">${_directorLabel('prompt_versions_empty')}</li>`}</ul>
        ${_directorStorage.diff && _directorStorage.diffPromptId ? `<pre data-user-content style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(_directorStorage.diff.diff || '')}</pre>` : ''}</details>`;
}

async function directorStorageExport() {
    const channel = _directorChannel, sessionId = _directorStorage.sessionId;
    if (!channel || !sessionId || _directorStorage.pending.has('export')) return;
    _directorStorage.pending.add('export'); renderDirectorStorage();
    try {
        const result = await api(_directorStorageURL(channel, `/sessions/${encodeURIComponent(sessionId)}/export`), jopts('POST', {}));
        if (channel !== _directorChannel) return;
        _directorStorage.exportResult = { url: _directorStorageURL(channel, `/sessions/${encodeURIComponent(sessionId)}/export/download?path=${encodeURIComponent(result.path || '')}`), path: result.path || '' };
    } catch (error) {
        if (channel !== _directorChannel) return;
        toast(_directorError(error), 'error');
    } finally {
        _directorStorage.pending.delete('export');
        if (channel === _directorChannel) renderDirectorStorage();
    }
}

async function directorStorageDelete() {
    const channel = _directorChannel, sessionId = _directorStorage.sessionId;
    if (!channel || !sessionId || _directorStorage.pending.has('delete') || !_directorDeleteConfirm(_directorStorage.confirmText)) return;
    _directorStorage.pending.add('delete'); renderDirectorStorage();
    try {
        await api(_directorStorageURL(channel, `/sessions/${encodeURIComponent(sessionId)}/evidence`), jopts('DELETE', {confirmation: 'УДАЛИТЬ'}));
        if (channel !== _directorChannel) return;
        _directorStorage.confirmText = '';
        _directorStorage.manifest = null;
        toast(_directorT('storage_deleted'), 'success');
        await loadDirectorStorage();
    } catch (error) {
        if (channel !== _directorChannel) return;
        toast(_directorError(error), 'error');
    } finally {
        _directorStorage.pending.delete('delete');
        if (channel === _directorChannel) renderDirectorStorage();
    }
}

async function directorStoragePin(assetId, pinned) {
    const channel = _directorChannel, sessionId = _directorStorage.sessionId;
    if (!channel || !sessionId || _directorStorage.pending.has(`pin:${assetId}`)) return;
    _directorStorage.pending.add(`pin:${assetId}`); renderDirectorStorage();
    try {
        await api(_directorStorageURL(channel, `/sessions/${encodeURIComponent(sessionId)}/assets/${encodeURIComponent(assetId)}/pin`), jopts('POST', {pinned: !pinned}));
        if (channel !== _directorChannel) return;
        await loadDirectorStorage();
    } catch (error) {
        if (channel !== _directorChannel) return;
        toast(_directorError(error), 'error');
    } finally {
        _directorStorage.pending.delete(`pin:${assetId}`);
        if (channel === _directorChannel) renderDirectorStorage();
    }
}

async function directorPromptDiff(promptId) {
    const channel = _directorChannel;
    if (!channel || _directorStorage.pending.has(`prompt:${promptId}`)) return;
    _directorStorage.pending.add(`prompt:${promptId}`); renderDirectorStorage();
    try {
        const result = await api(_directorStorageURL(channel, `/prompts/${encodeURIComponent(promptId)}/diff`));
        if (channel !== _directorChannel) return;
        _directorStorage.diff = result; _directorStorage.diffPromptId = promptId;
    } catch (error) {
        if (channel !== _directorChannel) return;
        toast(_directorError(error), 'error');
    } finally {
        _directorStorage.pending.delete(`prompt:${promptId}`);
        if (channel === _directorChannel) renderDirectorStorage();
    }
}

async function directorPromptDelete(promptId) {
    const channel = _directorChannel;
    if (!channel || _directorStorage.pending.has(`prompt:${promptId}`)) return;
    _directorStorage.pending.add(`prompt:${promptId}`); renderDirectorStorage();
    try {
        await api(_directorStorageURL(channel, `/prompts/${encodeURIComponent(promptId)}`), jopts('DELETE', {}));
        if (channel !== _directorChannel) return;
        toast(_directorT('prompt_deleted'), 'success');
        await loadDirectorReview();
    } catch (error) {
        if (channel !== _directorChannel) return;
        toast(_directorError(error), 'error');
    } finally {
        _directorStorage.pending.delete(`prompt:${promptId}`);
        if (channel === _directorChannel) renderDirectorStorage();
    }
}

Object.assign(LANGS.ru, {
    'director.storage_title': '📦 Сессии и хранилище', 'director.storage_no_sessions': 'Сессий пока нет.', 'director.storage_select_session': 'Выберите сессию, чтобы увидеть хранилище.',
    'director.storage_usage': 'Использование хранилища', 'director.storage_total': 'Всего', 'director.storage_limit': 'Лимит сессии', 'director.storage_pinned': 'Закреплено', 'director.storage_pinned_limit': 'Лимит закреплённых',
    'director.storage_kind_transcript': 'транскрипт', 'director.storage_kind_frame': 'кадр', 'director.storage_kind_other': 'файл', 'director.storage_pinned_badge': '📌 закреплён', 'director.storage_empty': 'Сохранённых файлов нет.',
    'director.storage_export': '⬇ Экспорт ZIP', 'director.storage_download_ready': 'Архив готов', 'director.storage_delete': '🗑 Удалить материалы', 'director.storage_delete_placeholder': 'Введите УДАЛИТЬ', 'director.storage_delete_hint': 'Удаление стирает транскрипт и кадры сессии, включая закреплённые; одобренные примеры и audit сохраняются. Введите слово УДАЛИТЬ для подтверждения.', 'director.storage_deleted': 'Материалы сессии удалены.',
    'director.pin_add': 'Закрепить', 'director.pin_remove': 'Открепить',
    'director.pause_reason_manual': 'Пауза владельцем — хвост сохраняется до исходного TTL.', 'director.pause_reason_sources': 'Источник пропал — unsent отменён; resume после 15 секунд стабильности.', 'director.pause_reason_ai_errors': 'Ошибки AI — нужен valid dry-run перед resume.', 'director.pause_reason_offline': 'Стрим offline — ожидание в пределах grace; после grace сессия закрывается.', 'director.pause_reason_unknown': 'Причина паузы неизвестна.',
    'director.prompt_versions': 'Версии промптов: diff и удаление', 'director.prompt_versions_empty': 'Версий промптов нет.', 'director.prompt_diff': 'Diff', 'director.prompt_delete': 'Удалить', 'director.prompt_deleted': 'Версия промпта удалена.',
    'director.last_working_prompt': 'После Emergency доступен последний рабочий промпт:', 'director.emergency_replay_hint': 'Активация требует нового replay и подтверждения качества.',
    'director.training_export': '⬇️ Экспорт базы обучения', 'director.training_import': '⬆️ Импорт базы обучения', 'director.training_import_replace': 'Заменить существующую базу канала',
    'director.training_import_hint': 'Импорт переносит промпты, примеры, чанты и шаблоны из файла экспорта. Без галочки замены дубликаты пропускаются; импортированные версии промпта требуют повторной проверки перед активацией.',
    'director.reactions': 'Отправленные вживую', 'director.reaction_hint': 'Реакции, реально отправленные в Twitch в режиме Live. Одобрение сохраняет их как позитивный пример обучения, отклонение — как негативный. Тексты уже отправлены и не редактируются.',
});
Object.assign(LANGS.en, {
    'director.storage_title': '📦 Sessions & storage', 'director.storage_no_sessions': 'No sessions yet.', 'director.storage_select_session': 'Select a session to see its storage.',
    'director.storage_usage': 'Storage usage', 'director.storage_total': 'Total', 'director.storage_limit': 'Session limit', 'director.storage_pinned': 'Pinned', 'director.storage_pinned_limit': 'Pinned limit',
    'director.storage_kind_transcript': 'transcript', 'director.storage_kind_frame': 'frame', 'director.storage_kind_other': 'file', 'director.storage_pinned_badge': '📌 pinned', 'director.storage_empty': 'No stored files.',
    'director.storage_export': '⬇ Export ZIP', 'director.storage_download_ready': 'Archive ready', 'director.storage_delete': '🗑 Delete evidence', 'director.storage_delete_placeholder': 'Type DELETE', 'director.storage_delete_hint': 'Deleting wipes the session transcript and frames, including pinned ones; approved examples and audit survive. Type DELETE to confirm.', 'director.storage_deleted': 'Session evidence deleted.',
    'director.pin_add': 'Pin', 'director.pin_remove': 'Unpin',
    'director.pause_reason_manual': 'Paused by owner — the tail survives until its original TTL.', 'director.pause_reason_sources': 'A source vanished — unsent cancelled; resume after 15 seconds of stability.', 'director.pause_reason_ai_errors': 'AI errors — a valid dry-run is required before resume.', 'director.pause_reason_offline': 'Stream offline — waiting within the grace; after the grace the session closes.', 'director.pause_reason_unknown': 'Pause reason unknown.',
    'director.prompt_versions': 'Prompt versions: diff & deletion', 'director.prompt_versions_empty': 'No prompt versions.', 'director.prompt_diff': 'Diff', 'director.prompt_delete': 'Delete', 'director.prompt_deleted': 'Prompt version deleted.',
    'director.last_working_prompt': 'After Emergency the last working prompt is available:', 'director.emergency_replay_hint': 'Activation requires a fresh replay and quality confirmation.',
    'director.training_export': '⬇️ Export training base', 'director.training_import': '⬆️ Import training base', 'director.training_import_replace': 'Replace the existing channel base',
    'director.training_import_hint': 'Import brings in prompts, examples, chants and templates from the export file. Without the replace checkbox duplicates are skipped; imported prompt versions require re-review before activation.',
    'director.reactions': 'Sent live', 'director.reaction_hint': 'Reactions actually sent to Twitch in Live mode. Approving saves them as a positive training example, rejecting as a negative one. The text is already sent and is not editable.',
});
Object.assign(LANGS.ua, {
    'director.storage_title': '📦 Сесії та сховище', 'director.storage_no_sessions': 'Сесій поки немає.', 'director.storage_select_session': 'Виберіть сесію, щоб побачити сховище.',
    'director.storage_usage': 'Використання сховища', 'director.storage_total': 'Всього', 'director.storage_limit': 'Ліміт сесії', 'director.storage_pinned': 'Закріплено', 'director.storage_pinned_limit': 'Ліміт закріплених',
    'director.storage_kind_transcript': 'транскрипт', 'director.storage_kind_frame': 'кадр', 'director.storage_kind_other': 'файл', 'director.storage_pinned_badge': '📌 закріплено', 'director.storage_empty': 'Збережених файлів немає.',
    'director.storage_export': '⬇ Експорт ZIP', 'director.storage_download_ready': 'Архів готовий', 'director.storage_delete': '🗑 Видалити матеріали', 'director.storage_delete_placeholder': 'Введіть ВИДАЛИТИ', 'director.storage_delete_hint': 'Видалення стирає транскрипт і кадри сесії, включно із закріпленими; схвалені приклади та audit зберігаються. Введіть слово ВИДАЛИТИ для підтвердження.', 'director.storage_deleted': 'Матеріали сесії видалено.',
    'director.pin_add': 'Закріпити', 'director.pin_remove': 'Відкріпити',
    'director.pause_reason_manual': 'Пауза власником — хвіст зберігається до початкового TTL.', 'director.pause_reason_sources': 'Джерело зникло — unsent скасовано; resume після 15 секунд стабільності.', 'director.pause_reason_ai_errors': 'Помилки AI — потрібен valid dry-run перед resume.', 'director.pause_reason_offline': 'Стрім offline — очікування в межах grace; після grace сесія закривається.', 'director.pause_reason_unknown': 'Причина паузи невідома.',
    'director.prompt_versions': 'Версії промптів: diff і видалення', 'director.prompt_versions_empty': 'Версій промптів немає.', 'director.prompt_diff': 'Diff', 'director.prompt_delete': 'Видалити', 'director.prompt_deleted': 'Версію промпта видалено.',
    'director.last_working_prompt': 'Після Emergency доступний останній робочий промпт:', 'director.emergency_replay_hint': 'Активація вимагає нового replay і підтвердження якості.',
    'director.training_export': '⬇️ Експорт бази навчання', 'director.training_import': '⬆️ Імпорт бази навчання', 'director.training_import_replace': 'Замінити наявну базу каналу',
    'director.training_import_hint': 'Імпорт переносить промпти, приклади, чанти та шаблони з файлу експорту. Без галочки заміни дублікати пропускаються; імпортовані версії промпта потребують повторної перевірки перед активацією.',
    'director.reactions': 'Надіслані наживо', 'director.reaction_hint': 'Реакції, реально надіслані в Twitch у режимі Live. Схвалення зберігає їх як позитивний приклад навчання, відхилення — як негативний. Текст уже надіслано і він не редагується.',
});
