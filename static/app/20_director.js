// ── Director ───────────────────────────────────────
let _directorChannels = [];
let _directorChannel = '';
let _directorState = null;
let _directorStatusRequest = 0;
const _directorTabStatus = new Map(); // Q40: последний известный статус сессии по каналу для вкладок
const _directorModes = new Map(); // Q40b: channel → {mode: 'ai'|'manual', fenced}
const _directorManual = {sender: new Map(), messages: new Map(), pending: false, status: ''};
const _directorPresets = new Map(); // Q35: channel → [{id, text, position}], хоткеи Alt+1..Alt+9
let _directorPresetEditing = null; // id заготовки, редактируемой инлайн
const _directorReviews = new Map();

function _directorReview(channel = _directorChannel) {
    if (!_directorReviews.has(channel)) _directorReviews.set(channel, {
        prompts: [], suggestions: [], reactions: [], draft: '', edits: new Map(), quality: new Map(),
        pending: new Set(), request: 0, loaded: false, error: null,
    });
    return _directorReviews.get(channel);
}
function _directorPromptEditable() { return ['off', 'stopped', 'paused'].includes(_directorState?.session?.state || _directorState?.status || 'off'); }
function _directorPromptPending(review) { return [...review.pending].some(key => key === 'create' || key.startsWith('prompt:')); }
function _directorReviewURL(channel, path) { return `/api/director/${encodeURIComponent(channel)}${path}`; }
function _directorAttr(value) { return esc(value).replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }
function _directorLabel(key) { return `<span data-i18n="director.${key}">${esc(_directorT(key))}</span>`; }
function _directorError(error) {
    if (error?.localKey === 'prompt_empty') return _directorT('prompt_empty');
    return typeof apiErrorInfo === 'function' ? apiErrorInfo(error?.payload || {error: {code: error?.code || 'internal_error', params: error?.params || {}}}).message : _directorT('review_error');
}
function directorPromptDraftChanged(value) { _directorReview().draft = value; }
function directorSuggestionChanged(id, index, value) {
    const review = _directorReview();
    const suggestion = review.suggestions.find(item => String(item.id) === String(id));
    if (!suggestion) return;
    if (!review.edits.has(String(id))) review.edits.set(String(id), suggestion.messages.map(message => message.text));
    review.edits.get(String(id))[index] = value;
}
function _directorReplayKey(prompt) {
    return JSON.stringify([prompt.content_hash, prompt.replay_metadata, _directorState?.config?.provider, _directorState?.config?.model]);
}
function _directorReplayValid(prompt) {
    const replay = prompt.replay_metadata || {};
    const config = _directorState?.config || {};
    return prompt.tested && replay.passed === true && replay.provider === config.provider && replay.model === config.model;
}
function directorQualityChanged(id, checked) {
    const review = _directorReview();
    const prompt = review.prompts.find(item => String(item.id) === String(id));
    if (!prompt) return;
    if (checked) review.quality.set(String(id), _directorReplayKey(prompt));
    else review.quality.delete(String(id));
    renderDirectorReview();
}

async function loadDirectorReview() {
    const channel = _directorChannel;
    if (!channel) return;
    const review = _directorReview(channel);
    const request = ++review.request;
    try {
        const [prompts, suggestions, reactions] = await Promise.all([
            api(_directorReviewURL(channel, '/prompts')),
            api(_directorReviewURL(channel, '/suggestions')),
            api(_directorReviewURL(channel, '/reactions/live')),
        ]);
        if (request !== review.request) return;
        review.prompts = prompts.prompts || [];
        review.suggestions = suggestions.suggestions || [];
        review.reactions = reactions.reactions || [];
        review.loaded = true;
        review.error = null;
    } catch (error) {
        if (request !== review.request) return;
        review.error = error;
    }
    if (channel === _directorChannel) renderDirectorReview();
}

function _directorReviewHTML(container, html) {
    if (container._directorHTML === html) return;
    const active = document.activeElement;
    const focused = active && container.contains?.(active) ? {
        tag: active.tagName, type: active.type, action: active.getAttribute('onclick'), prompt: active.dataset.promptId,
        suggestion: active.dataset.suggestionId, reaction: active.dataset.reactionId, index: active.dataset.messageIndex,
        start: active.selectionStart, end: active.selectionEnd,
    } : null;
    const open = [...container.querySelectorAll('details')].map(detail => detail.open);
    container.innerHTML = html;
    container._directorHTML = html;
    container.querySelectorAll('details').forEach((detail, index) => { detail.open = Boolean(open[index]); });
    if (focused) {
        const replacement = [...container.querySelectorAll('[data-prompt-id], [data-suggestion-id], [data-reaction-id]')].find(el =>
            el.tagName === focused.tag && el.type === focused.type && el.getAttribute('onclick') === focused.action && el.dataset.promptId === focused.prompt &&
            el.dataset.suggestionId === focused.suggestion && el.dataset.reactionId === focused.reaction && el.dataset.messageIndex === focused.index);
        if (replacement && !replacement.disabled) {
            replacement.focus({preventScroll: true});
            if (typeof focused.start === 'number') replacement.setSelectionRange?.(focused.start, focused.end);
        }
    }
}
function renderDirectorReview() {
    if (!$('directorPrompts')) return;
    const review = _directorReview();
    const draft = $('directorPromptDraft');
    if (draft.value !== review.draft) draft.value = review.draft;
    $('directorPromptCreate').disabled = !_directorChannel || !_directorPromptEditable() || _directorPromptPending(review);
    $('directorReviewStatus').textContent = review.error ? _directorError(review.error) : review.pending.size ? _directorT('review_busy') : '';
    const promptsHTML = review.prompts.map(prompt => {
        const id = _directorAttr(prompt.id);
        const pending = _directorPromptPending(review) || !_directorPromptEditable();
        const valid = _directorReplayValid(prompt);
        const checked = valid && review.quality.get(String(prompt.id)) === _directorReplayKey(prompt);
        const replay = prompt.replay_metadata?.provider ? prompt.replay_metadata : null;
        const report = replay ? `<div class="text-sm"><strong>${esc(replay.provider)} / ${esc(replay.model)}</strong> · ${_directorLabel(replay.passed ? 'replay_passed' : 'replay_failed')}${(replay.cases || []).map(item => `<details><summary>${esc(item.id)} · ${_directorLabel(item.passed ? 'replay_passed' : 'replay_failed')}</summary><p data-user-content>${esc(item.reason || '')}</p><pre data-user-content style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(item.response || '')}</pre></details>`).join('')}</div>` : '';
        return `<article class="p-3 form-panel"><strong>${_directorLabel('prompt_version')} ${esc(prompt.version)}</strong> · ${_directorLabel(prompt.active ? 'prompt_active' : prompt.retired ? 'prompt_retired' : valid ? 'replay_passed' : 'prompt_untested')}
            <details><summary>${_directorLabel('prompt_text')}</summary><pre data-user-content style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(prompt.prompt_text || '')}</pre><small>${esc(prompt.content_hash || '')}</small></details>${report}
            <div class="flex gap-2 flex-wrap mt-2"><button type="button" class="btn btn-secondary btn-sm" data-prompt-id="${id}" onclick="directorReplayPrompt(this.dataset.promptId)" ${pending || prompt.retired ? 'disabled' : ''}>${_directorLabel('replay_run')}</button>
            <label class="text-sm"><input type="checkbox" data-prompt-id="${id}" onchange="directorQualityChanged(this.dataset.promptId,this.checked)" ${checked ? 'checked' : ''} ${!valid || pending || prompt.active || prompt.retired ? 'disabled' : ''}> ${_directorLabel('quality_confirm')}</label>
            <button type="button" class="btn btn-primary btn-sm" data-prompt-id="${id}" onclick="directorActivatePrompt(this.dataset.promptId)" ${!checked || pending || prompt.active || prompt.retired ? 'disabled' : ''}>${_directorLabel('prompt_activate')}</button></div></article>`;
    }).join('') || _directorLabel(review.loaded ? 'prompts_empty' : 'review_loading');
    // Keep the same nodes while polling unchanged data, including focused editors and open reports.
    const prompts = $('directorPrompts');
    _directorReviewHTML(prompts, promptsHTML);
    const suggestionsHTML = review.suggestions.filter(item => !item.decision).map(item => {
        const id = _directorAttr(item.id);
        const texts = review.edits.get(String(item.id)) || item.messages.map(message => message.text);
        const pending = review.pending.has(`suggestion:${item.id}`);
        return `<article class="p-3 form-panel"><strong>${_directorLabel('plan_id')}: ${esc(item.id)}</strong>${item.messages.map((message, index) => `<label class="form-group mt-2">${_directorLabel('suggest_message')} ${index + 1} · ${esc(message.worker_id ?? '')}<textarea class="input" rows="2" data-suggestion-id="${id}" data-message-index="${index}" oninput="directorSuggestionChanged(this.dataset.suggestionId,Number(this.dataset.messageIndex),this.value)" ${pending ? 'disabled' : ''}>${esc(texts[index])}</textarea></label>`).join('')}
            <div class="flex gap-2 mt-2"><button type="button" class="btn btn-primary btn-sm" data-suggestion-id="${id}" onclick="directorDecideSuggestion(this.dataset.suggestionId,'approve')" ${pending ? 'disabled' : ''}>${_directorLabel('suggest_approve')}</button><button type="button" class="btn btn-secondary btn-sm" data-suggestion-id="${id}" onclick="directorDecideSuggestion(this.dataset.suggestionId,'reject')" ${pending ? 'disabled' : ''}>${_directorLabel('suggest_reject')}</button></div></article>`;
    }).join('') || _directorLabel(review.loaded ? 'suggestions_empty' : 'review_loading');
    const suggestions = $('directorSuggestions');
    _directorReviewHTML(suggestions, suggestionsHTML);
    const reactionsHTML = review.reactions.filter(item => !item.decision).map(item => {
        const id = _directorAttr(item.id);
        const pending = review.pending.has(`reaction:${item.id}`);
        return `<article class="p-3 form-panel"><strong>${_directorLabel('plan_id')}: ${esc(item.id)}</strong>${item.messages.map((message, index) => `<p class="text-sm mt-2" data-user-content>${_directorLabel('reaction_message')} ${index + 1} · ${_directorLabel('reaction_worker')} ${esc(message.account_id ?? '')} · ${esc(message.sent_at ?? '')}<br>${esc(message.text)}</p>`).join('')}
            <div class="flex gap-2 mt-2"><button type="button" class="btn btn-primary btn-sm" data-reaction-id="${id}" onclick="directorDecideReaction(this.dataset.reactionId,'approve')" ${pending ? 'disabled' : ''}>${_directorLabel('reaction_approve')}</button><button type="button" class="btn btn-secondary btn-sm" data-reaction-id="${id}" onclick="directorDecideReaction(this.dataset.reactionId,'reject')" ${pending ? 'disabled' : ''}>${_directorLabel('reaction_reject')}</button></div></article>`;
    }).join('') || _directorLabel(review.loaded ? 'reactions_empty' : 'review_loading');
    const reactions = $('directorReactions');
    _directorReviewHTML(reactions, reactionsHTML);
}

async function _directorReviewAction(key, path, body, apply) {
    const channel = _directorChannel;
    const review = _directorReview(channel);
    if (!channel || review.pending.has(key)) return;
    if ((key === 'create' || key.startsWith('prompt:')) && (_directorPromptPending(review) || !_directorPromptEditable())) return;
    review.pending.add(key);
    ++review.request;
    review.error = null;
    renderDirectorReview();
    try {
        const result = await api(_directorReviewURL(channel, path), jopts('POST', body));
        ++review.request;
        apply(result, review);
    } catch (error) { review.error = error; }
    finally {
        review.pending.delete(key);
        if (channel === _directorChannel) renderDirectorReview();
    }
}
async function directorCreatePrompt() {
    const channel = _directorChannel;
    const text = _directorReview().draft;
    if (!text.trim()) { _directorReview().error = {localKey: 'prompt_empty'}; renderDirectorReview(); return; }
    return _directorReviewAction('create', '/prompts', {prompt_text: text}, (result, review) => {
        review.prompts = result.prompts || review.prompts;
        if (review.draft === text) review.draft = '';
        if (!result.prompts && channel === _directorChannel) loadDirectorReview();
    });
}
async function directorReplayPrompt(id) {
    const review = _directorReview();
    const prompt = review.prompts.find(item => String(item.id) === String(id));
    if (!prompt || prompt.retired || _directorPromptPending(review)) return;
    review.quality.delete(String(id));
    return _directorReviewAction(`prompt:${id}`, `/prompts/${encodeURIComponent(id)}/tested`, {}, (result, state) => { state.prompts = result.prompts || state.prompts; });
}
async function directorActivatePrompt(id) {
    const review = _directorReview();
    const prompt = review.prompts.find(item => String(item.id) === String(id));
    if (!prompt || prompt.active || prompt.retired || !_directorReplayValid(prompt) || review.quality.get(String(id)) !== _directorReplayKey(prompt)) return;
    return _directorReviewAction(`prompt:${id}`, `/prompts/${encodeURIComponent(id)}/activate`, {quality_confirmed: true, replay_run_id: prompt.replay_metadata.run_id}, (result, state) => { state.prompts = result.prompts || state.prompts; });
}
async function directorDecideSuggestion(id, decision) {
    if (!['approve', 'reject'].includes(decision)) return;
    const channel = _directorChannel;
    const review = _directorReview(channel);
    const item = review.suggestions.find(item => String(item.id) === String(id) && !item.decision);
    if (!item) return;
    const texts = review.edits.get(String(id)) || item.messages.map(message => message.text);
    const body = decision === 'approve' ? {messages: texts.map(text => ({text}))} : {};
    return _directorReviewAction(`suggestion:${id}`, `/suggestions/${encodeURIComponent(id)}/${decision}`, body, (result, state) => {
        state.suggestions = state.suggestions.filter(item => String(item.id) !== String(id));
        state.edits.delete(String(id));
        if (channel === _directorChannel) loadDirectorReview();
    });
}


async function directorDecideReaction(id, decision) {
    if (!['approve', 'reject'].includes(decision)) return;
    const channel = _directorChannel;
    const review = _directorReview(channel);
    const item = review.reactions.find(item => String(item.id) === String(id) && !item.decision);
    if (!item) return;
    // Sent texts are immutable: an empty body — the backend stores exactly what was dispatched.
    return _directorReviewAction(`reaction:${id}`, `/reactions/live/${encodeURIComponent(id)}/${decision}`, {}, (result, state) => {
        state.reactions = state.reactions.filter(item => String(item.id) !== String(id));
        if (channel === _directorChannel) loadDirectorReview();
    });
}


async function directorExportTraining() {
    const channel = _directorChannel;
    if (!channel) return;
    try {
        const data = await api(_directorReviewURL(channel, '/training/export'));
        const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `director-training-${channel}.json`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
    } catch (error) {
        _directorReview(channel).error = error;
        if (channel === _directorChannel) renderDirectorReview();
    }
}
async function directorImportTraining(input) {
    const file = input?.files?.[0];
    if (input) input.value = '';
    if (!file) return;
    const channel = _directorChannel;
    if (!channel) return;
    let data;
    try {
        data = JSON.parse(await file.text());
    } catch {
        _directorReview(channel).error = {payload: {error: {code: 'invalid_training_export', params: {}}}};
        if (channel === _directorChannel) renderDirectorReview();
        return;
    }
    const replace = $('directorTrainingReplace')?.checked === true;
    // Server still requires explicit confirm; imported prompt versions start untested.
    return _directorReviewAction('training-import', '/training/import', {data, replace, confirm: true}, () => {});
}


const DIRECTOR_REVIEW_I18N = {
    prompts: ['Версии промпта и проверка', 'Prompt versions and replay', 'Версії промпту та перевірка'],
    replay_hint: ['Проверка вызывает сохранённые provider/model без отправки в Twitch. Перед активацией изучите ответы и подтвердите качество.', 'Replay calls the saved provider/model without sending to Twitch. Review the responses and confirm their quality before activation.', 'Перевірка викликає збережені provider/model без надсилання в Twitch. Перед активацією перегляньте відповіді й підтвердьте якість.'],
    prompt_text: ['Инструкции владельца', 'Owner instructions', 'Інструкції власника'],
    prompt_hint: ['Новая неизменяемая версия. Системные правила и правила безопасности не изменяются.', 'Creates an immutable version. System and safety rules cannot be changed.', 'Нова незмінна версія. Системні правила та правила безпеки не змінюються.'],
    prompt_empty: ['Введите инструкции для новой версии.', 'Enter instructions for the new version.', 'Введіть інструкції для нової версії.'],
    prompt_create: ['Создать версию', 'Create version', 'Створити версію'],
    training_export: ['⬇️ Экспорт базы обучения', '⬇️ Export training base', '⬇️ Експорт бази навчання'],
    training_import: ['⬆️ Импорт базы обучения', '⬆️ Import training base', '⬆️ Імпорт бази навчання'],
    training_import_replace: ['Заменить существующую базу канала', 'Replace the existing channel base', 'Замінити наявну базу каналу'],
    training_import_hint: ['Импорт переносит промпты, примеры, чанты и шаблоны из файла экспорта. Без галочки замены дубликаты пропускаются; импортированные версии промпта требуют повторной проверки перед активацией.', 'Import moves prompts, examples, chants and templates from an export file. Without the replace box duplicates are skipped; imported prompt versions require a fresh replay before activation.', 'Імпорт переносить промпти, приклади, чанти й шаблони з файлу експорту. Без прапорця заміни дублікати пропускаються; імпортовані версії промпту потребують повторної перевірки перед активацією.'],
    prompt_version: ['Версия', 'Version', 'Версія'],
    prompt_active: ['Активна', 'Active', 'Активна'],
    prompt_retired: ['Архивная', 'Retired', 'Архівна'],
    prompt_untested: ['Нужна проверка для сохранённых provider/model', 'Replay required for the saved provider/model', 'Потрібна перевірка для збережених provider/model'],
    replay_run: ['Проверить через provider/model', 'Run provider/model replay', 'Перевірити через provider/model'],
    replay_passed: ['Проверка пройдена', 'Replay passed', 'Перевірку пройдено'],
    replay_failed: ['Проверка не пройдена', 'Replay failed', 'Перевірку не пройдено'],
    quality_confirm: ['Я проверил качество ответов этой версии', 'I have reviewed the quality of this version’s responses', 'Я перевірив якість відповідей цієї версії'],
    prompt_activate: ['Активировать', 'Activate', 'Активувати'],
    prompts_empty: ['Версий пока нет.', 'No prompt versions yet.', 'Версій поки немає.'],
    suggestions: ['Предложения для обучения', 'Training suggestions', 'Пропозиції для навчання'],
    suggest_hint: ['Просмотрите и отредактируйте весь план. Одобрение сохраняет пример для будущих решений, но никогда не отправляет сообщения в Twitch.', 'Review and edit the whole plan. Approval saves an example for future decisions and never sends messages to Twitch.', 'Перегляньте й відредагуйте весь план. Схвалення зберігає приклад для майбутніх рішень, але ніколи не надсилає повідомлення в Twitch.'],
    suggest_message: ['Сообщение', 'Message', 'Повідомлення'],
    suggest_approve: ['Сохранить как одобренный пример', 'Save as approved example', 'Зберегти як схвалений приклад'],
    suggest_reject: ['Отклонить', 'Reject', 'Відхилити'],
    suggestions_empty: ['Ожидающих предложений нет. Они появляются только в режиме Suggest.', 'No pending suggestions. They appear only in Suggest mode.', 'Немає пропозицій на розгляді. Вони з’являються лише в режимі Suggest.'],
    reactions: ['Отправленные вживую', 'Sent live reactions', 'Надіслані наживо'],
    reaction_hint: ['Реакции, реально отправленные в Twitch в режиме Live. Одобрение сохраняет их как позитивный пример обучения, отклонение — как негативный. Тексты уже отправлены и не редактируются.', 'Reactions actually sent to Twitch in Live mode. Approval saves them as a positive training example, rejection as a negative one. Sent texts cannot be edited.', 'Реакції, реально надіслані в Twitch у режимі Live. Схвалення зберігає їх як позитивний приклад навчання, відхилення — як негативний. Надіслані тексти не редагуються.'],
    reaction_message: ['Сообщение', 'Message', 'Повідомлення'],
    reaction_worker: ['Бот', 'Bot', 'Бот'],
    reaction_approve: ['Сохранить как позитивный пример', 'Save as positive example', 'Зберегти як позитивний приклад'],
    reaction_reject: ['Отклонить как негативный пример', 'Reject as negative example', 'Відхилити як негативний приклад'],
    reactions_empty: ['Отправленных вживую реакций, ожидающих ревью, нет. Они появляются только в режиме Live после реальной отправки.', 'No sent live reactions awaiting review. They appear only in Live mode after actual dispatch.', 'Немає надісланих наживо реакцій на розгляді. Вони з’являються лише в режимі Live після реальної надсилки.'],
    review_loading: ['Загрузка…', 'Loading…', 'Завантаження…'],
    review_busy: ['Выполняется…', 'Working…', 'Виконується…'],
    review_error: ['Не удалось выполнить запрос. Попробуйте ещё раз.', 'The request failed. Please try again.', 'Не вдалося виконати запит. Спробуйте ще раз.'],
    mode_hint: ['Training и Suggest не отправляют в Twitch. Suggest сохраняет только одобренные примеры.', 'Training and Suggest never send to Twitch. Suggest only saves approved examples.', 'Training і Suggest не надсилають у Twitch. Suggest зберігає лише схвалені приклади.'],
};
for (const [key, values] of Object.entries(DIRECTOR_REVIEW_I18N)) {
    ['ru', 'en', 'ua'].forEach((lang, index) => { LANGS[lang][`director.${key}`] = values[index]; });
}

const DIRECTOR_REVIEW_ERRORS = {
    settings_locked: ['Приостановите или остановите сессию перед изменением промпта.', 'Pause or stop the session before changing the prompt.', 'Призупиніть або зупиніть сесію перед зміною промпту.'],
    config_missing: ['Сначала сохраните конфигурацию Director.', 'Save the Director configuration first.', 'Спочатку збережіть конфігурацію Director.'],
    director_provider_not_ready: ['Выбранный AI-провайдер не готов. Проверьте его настройки.', 'The selected AI provider is not ready. Check its configuration.', 'Вибраний AI-провайдер не готовий. Перевірте його налаштування.'],
    prompt_missing: ['Версия промпта не найдена. Обновите список.', 'Prompt version not found. Refresh the list.', 'Версію промпту не знайдено. Оновіть список.'],
    replay_config_changed: ['Конфигурация изменилась во время проверки. Запустите проверку снова.', 'Configuration changed during replay. Run replay again.', 'Конфігурація змінилася під час перевірки. Запустіть її знову.'],
    replay_in_progress: ['Проверка этого канала уже выполняется.', 'A replay is already running for this channel.', 'Перевірка цього каналу вже виконується.'],
    prompt_not_tested: ['Сначала выполните успешную проверку этой версии.', 'This version must pass replay first.', 'Спочатку ця версія має пройти перевірку.'],
    prompt_replay_stale: ['Результат проверки устарел. Проверьте версию с текущими настройками.', 'Replay is outdated. Test this version with the current configuration.', 'Результат перевірки застарів. Перевірте версію з поточними налаштуваннями.'],
    prompt_quality_confirmation_required: ['Проверьте ответы и явно подтвердите их качество.', 'Review the responses and explicitly confirm their quality.', 'Перегляньте відповіді та явно підтвердьте їхню якість.'],
    suggestion_missing: ['Предложение не найдено. Обновите список.', 'Suggestion not found. Refresh the list.', 'Пропозицію не знайдено. Оновіть список.'],
    suggestion_already_reviewed: ['Предложение уже рассмотрено. Обновите список.', 'This suggestion has already been reviewed. Refresh the list.', 'Цю пропозицію вже розглянуто. Оновіть список.'],
    reaction_missing: ['Реакция не найдена. Обновите список.', 'Reaction not found. Refresh the list.', 'Реакцію не знайдено. Оновіть список.'],
    reaction_not_sent: ['У этой реакции нет реально отправленных сообщений.', 'This reaction has no actually sent messages.', 'Ця реакція не має реально надісланих повідомлень.'],
    invalid_reaction_texts: ['Можно сохранить только фактически отправленные тексты без изменений.', 'Only the actually sent texts, unchanged, can be saved.', 'Зберегти можна лише фактично надіслані тексти без змін.'],
    reaction_already_reviewed: ['Реакция уже рассмотрена. Обновите список.', 'This reaction has already been reviewed. Refresh the list.', 'Цю реакцію вже розглянуто. Оновіть список.'],
    import_confirmation_required: ['Импорт требует явного подтверждения.', 'Import requires explicit confirmation.', 'Імпорт потребує явного підтвердження.'],
    invalid_training_export: ['Файл не является корректным экспортом базы обучения Режиссёра.', 'The file is not a valid Director training-base export.', 'Файл не є коректним експортом бази навчання Режисера.'],
    invalid_example_messages: ['Сохраните исходное количество и порядок сообщений.', 'Keep the original message count and order.', 'Збережіть початкову кількість і порядок повідомлень.'],
    unsafe_example_text: ['Текст примера нарушает правила безопасности. Отредактируйте сообщения.', 'Example text violates safety rules. Edit the messages.', 'Текст прикладу порушує правила безпеки. Відредагуйте повідомлення.'],
    example_storage_full: ['Хранилище одобренных примеров заполнено.', 'Approved-example storage is full.', 'Сховище схвалених прикладів заповнене.'],
    pinned_storage_full: ['Достигнут лимит закреплённого хранилища. Снимите закрепление старых материалов.', 'The pinned-storage limit is reached. Unpin older evidence first.', 'Досягнуто ліміт закріпленого сховища. Спершу зніміть закріплення старих матеріалів.'],
    prompt_active_protected: ['Активную версию промпта удалить нельзя — сначала активируйте другую.', 'The active prompt version is protected — activate another one first.', 'Активну версію промпту не можна видалити — спершу активуйте іншу.'],
    prompt_last_working_protected: ['Последняя рабочая версия промпта защищена от удаления.', 'The last working prompt version is protected from deletion.', 'Останню робочу версію промпту захищено від видалення.'],
};
for (const [code, values] of Object.entries(DIRECTOR_REVIEW_ERRORS)) {
    ['ru', 'en', 'ua'].forEach((lang, index) => { LANGS[lang][`api.error.${code}`] = values[index]; });
}

const DIRECTOR_CONFIG_FIELDS = {
    provider: 'directorProvider', model: 'directorModel', temperature: 'directorTemperature',
    max_tokens: 'directorMaxTokens', mode: 'directorMode',
    language: 'directorLanguage', assignment_mode: 'directorAssignmentMode', reaction_mode: 'directorReactionMode', analysis_interval_sec: 'directorAnalysisInterval',
    priority_cooldown_sec: 'directorWakeCooldown', send_delay_min_sec: 'directorDelayMin',
    send_delay_max_sec: 'directorDelayMax', ttl_sec: 'directorTtl', ai_error_limit: 'directorAiErrors',
    vision_stale_sec: 'directorVisionStale', speech_stale_sec: 'directorSpeechStale', offline_grace_sec: 'directorOfflineGrace',
};
const DIRECTOR_RANGE_FIELDS = {
    small: ['directorRangeSmallMin', 'directorRangeSmallMax'],
    medium: ['directorRangeMediumMin', 'directorRangeMediumMax'],
    large: ['directorRangeLargeMin', 'directorRangeLargeMax'],
};
const DIRECTOR_DEFAULT_CONFIG = {
    provider: '', model: '', temperature: 0.4, max_tokens: 300, mode: 'live', language: 'auto',
    reaction_mode: 'absolute', analysis_interval_sec: 15, priority_cooldown_sec: 5, send_delay_min_sec: 1,
    send_delay_max_sec: 20, ttl_sec: 45, ai_error_limit: 3, assignment_mode: 'backend_random',
    vision_stale_sec: 45, speech_stale_sec: 15, offline_grace_sec: 60,
    ranges: {small: [0, 3], medium: [4, 12], large: [13, 30]},
};

function _directorEndpoint(path = '') {
    return `/api/director/channels/${encodeURIComponent(_directorChannel)}${path}`;
}
function _directorT(key, params = {}) { return t(`director.${key}`, params); }
function _directorStatus(value) { return _directorT(`status_${String(value || 'unknown')}`); }
function _directorSetLoad(message, error = false) {
    const el = $('directorLoadState');
    el.textContent = message;
    el.classList.toggle('text-error', error);
    el.classList.toggle('text-muted', !error);
}
function _directorConfig() {
    const numeric = new Set(['temperature', 'max_tokens', 'analysis_interval_sec', 'priority_cooldown_sec', 'send_delay_min_sec', 'send_delay_max_sec', 'ttl_sec', 'ai_error_limit', 'vision_stale_sec', 'speech_stale_sec', 'offline_grace_sec']);
    const config = Object.fromEntries(Object.entries(DIRECTOR_CONFIG_FIELDS).map(([key, id]) => [key, numeric.has(key) ? Number($(id).value) : $(id).value.trim()]));
    config.ranges = Object.fromEntries(Object.entries(DIRECTOR_RANGE_FIELDS).map(([level, ids]) => [level, ids.map(id => Number($(id).value))]));
    return config;
}
function _directorApplyConfig(config = {}) {
    Object.entries(DIRECTOR_CONFIG_FIELDS).forEach(([key, id]) => {
        if (config[key] !== undefined && config[key] !== null) $(id).value = config[key];
    });
    Object.entries(DIRECTOR_RANGE_FIELDS).forEach(([level, ids]) => {
        (config.ranges?.[level] || []).forEach((value, index) => { $(ids[index]).value = value; });
    });
}
function _directorConfigDirty() { return typeof _dirtyScopes !== 'undefined' && _dirtyScopes.has('directorConfig'); }
function _directorFormIds() { return ['directorAccountSelect', ...Object.values(DIRECTOR_CONFIG_FIELDS), ...Object.values(DIRECTOR_RANGE_FIELDS).flat()]; }

async function loadDirectorSection() {
    _directorSetLoad(t('label.loading'));
    $('directorLoadState').classList.remove('hidden');
    $('directorWorkspace').classList.add('hidden');
    try {
        const [data, accounts] = await Promise.all([api('/api/channel-overview'), api('/api/accounts')]);
        const accountById = new Map((Array.isArray(accounts) ? accounts : accounts.accounts || []).map(account => [account.id, account]));
        _directorChannels = (data.channels || []).map(channel => ({
            ...channel,
            bots: channel.bots.map(bot => ({...bot, ...(accountById.get(bot.account_id) || {})})),
        }));
        if (!_directorChannels.length) {
            _directorSetLoad(_directorT('no_channels'));
            return;
        }
        if (!_directorChannels.some(channel => channel.channel === _directorChannel)) {
            _directorChannel = _directorChannels[0].channel;
        }
        const select = $('directorChannelSelect');
        select.innerHTML = _directorChannels.map(channel => `<option value="${esc(channel.channel)}">#${esc(channel.channel)}</option>`).join('');
        select.value = _directorChannel;
        await loadDirectorModes();
        renderDirectorChannelTabs();
        $('directorLoadState').classList.add('hidden');
        $('directorWorkspace').classList.remove('hidden');
        directorCheckQuickStatus();
        await loadDirectorChannel();
    } catch (e) { _directorSetLoad(e.message, true); }
}

async function selectDirectorChannel(channel) {
    if (!confirmDirty()) { $('directorChannelSelect').value = _directorChannel; renderDirectorChannelTabs(); return; }
    _directorChannel = channel;
    _directorState = null;
    renderDirectorChannelTabs();
    renderDirectorReview();
    await loadDirectorChannel();
}

async function loadDirectorChannel() {
    if (!_directorChannel) return;
    const channel = _directorChannel;
    const request = ++_directorStatusRequest;
    try {
        const state = await api(`/api/director/${encodeURIComponent(channel)}/status`);
        if (channel !== _directorChannel || request !== _directorStatusRequest) return;
        _directorState = state;
        _directorModes.set(channel, {mode: state.control_mode || 'ai', fenced: Boolean(state.manual_fenced)});
        if (!_directorConfigDirty()) {
            _directorApplyConfig(_directorState.config || DIRECTOR_DEFAULT_CONFIG);
            clearDirty('directorConfig');
        }
        bindDirtyWatch('directorConfig', _directorFormIds());
        renderDirectorWorkerChoices();
        renderDirectorAccountChoices();
        renderDirectorState();
        await Promise.all([loadDirectorAudit(), loadDirectorReview(), loadDirectorManualMessages(), loadDirectorManualPresets()]);
    } catch (e) {
        if (channel === _directorChannel && request === _directorStatusRequest) toast(t('toast.error_detail', {detail: e.message}), 'error');
    }
}

function renderDirectorState() {
    const state = _directorState || {};
    const session = state.session || {};
    const status = session.state === 'stopped' ? 'off' : (session.state || state.status || 'off');
    const live = status === 'live';
    const configEditable = status === 'off' || status === 'paused';
    const emergency = Boolean(session.emergency_fence || state.emergency_stop);
    if ($('directorChannelTitle')) $('directorChannelTitle').textContent = _directorChannel;
    if (_directorChannel) _directorTabStatus.set(_directorChannel, emergency ? 'emergency' : status);
    renderDirectorChannelTabs();
    $('directorSessionStatus').textContent = _directorStatus(emergency ? 'emergency' : status);
    $('directorSessionStatus').className = `badge ${live ? 'badge-success' : status === 'paused' || emergency ? 'badge-warning' : ''}`;
    const latEl = $('directorLatencyBadge');
    const latencyMs = state.ai_latency_ms ?? (state.current_plan?.latency_ms);
    if (latEl) {
        if (latencyMs != null && latencyMs > 0) {
            const sec = (latencyMs / 1000).toFixed(2);
            latEl.textContent = `⚡ ${sec}s`;
            latEl.title = `Задержка ИИ (Latency): ${Math.round(latencyMs)} ms`;
            latEl.className = `badge ${latencyMs < 2000 ? 'badge-success' : latencyMs < 4500 ? 'badge-warning' : 'badge-danger'}`;
            latEl.classList.remove('hidden');
        } else {
            latEl.classList.add('hidden');
        }
    }
    $('directorConfigFields').disabled = !configEditable;
    $('directorSaveButton').disabled = !configEditable;
    $('directorConfigStatus').textContent = configEditable ? '' : _directorT('config_locked');
    $('directorStartButton').disabled = live || emergency;
    $('directorPauseButton').disabled = !live;
    $('directorResumeButton').disabled = status !== 'paused' || emergency;
    $('directorDryRunButton').classList.toggle('hidden', !emergency);
    $('directorStopButton').disabled = status === 'off';
    $('directorLifecycleHint').textContent = emergency ? _directorT('emergency_hint') : _directorT(`lifecycle_${status}`);
    renderDirectorHealth(state);
    renderDirectorWorkers(state.workers || []);
    renderDirectorPlan(state.plan || state.current_plan || null);
    renderDirectorReview();
    renderDirectorMode();
}

function renderDirectorHealth(state) {
    const health = state.health || {};
    // Q29 (DEF-04): AI — трёхсостоянийный: работает / пауза между планами / ошибка
    // («ошибка» — только реальная ошибка провайдера, pause_reason='ai_errors').
    const sources = ['vision', 'speech', 'twitch'];
    const aiState = state.ai_state || (health.ai === true ? 'working' : 'pause');
    const aiLabel = esc(_directorT('source_ai'));
    const aiBadge = aiState === 'working'
        ? `<span class="badge badge-success">${aiLabel}: ${esc(_directorT('status_healthy'))}</span>`
        : aiState === 'error'
            ? `<span class="badge badge-danger" title="${esc(state.ai_last_error || '')}">${aiLabel}: ${esc(_directorT('status_error'))}</span>`
            : `<span class="badge">${aiLabel}: ${esc(_directorT('status_pause'))}</span>`;
    const latencyMs = state.ai_latency_ms ?? (state.current_plan?.latency_ms);
    const latencyBadge = (latencyMs != null && latencyMs > 0)
        ? `<span class="badge ${latencyMs < 2000 ? 'badge-success' : latencyMs < 4500 ? 'badge-warning' : 'badge-danger'}" title="Задержка ответа ИИ: ${Math.round(latencyMs)} ms">⚡ ${(latencyMs / 1000).toFixed(2)}s</span>`
        : '';
    $('directorHealth').innerHTML = aiBadge + latencyBadge + sources.map(source => {
        const detail = health[source];
        const status = detail === true ? 'healthy' : detail === false ? 'stale' : 'unknown';
        return `<span class="badge ${status === 'healthy' ? 'badge-success' : 'badge-warning'}">${esc(_directorT(`source_${source}`))}: ${esc(_directorStatus(status))}</span>`;
    }).join('');
}

function renderDirectorWorkers(workers) {
    const el = $('directorWorkers');
    if (!workers.length) { el.textContent = _directorT('no_workers'); return; }
    el.innerHTML = workers.map(worker => {
        const status = worker.state || 'unknown';
        const joinNow = status === 'scheduled'
            ? `<button class="btn btn-secondary btn-sm" type="button" data-worker-id="${esc(worker.account_id)}" onclick="directorJoinNow(this.dataset.workerId)">${esc(_directorT('join_now'))}</button>` : '';
        return `<div class="flex gap-2 items-center flex-wrap"><span class="badge">${esc(worker.nickname || `#${worker.account_id}`)}</span><span class="text-sm">${esc(_directorStatus(status))}</span>${joinNow}</div>`;
    }).join('');
}

function renderDirectorWorkerChoices() {
    const channel = _directorChannels.find(item => item.channel === _directorChannel);
    const selected = new Set(_directorConfigDirty()
        ? [...$('directorWorkerChoices').querySelectorAll('[data-director-worker]:checked')].map(input => Number(input.value))
        : _directorState?.selected_workers || []);
    const candidates = (channel?.bots || []).filter(bot => bot.enabled && bot.bot_role === 'lurker');
    const el = $('directorWorkerChoices');
    if (!candidates.length) { el.textContent = _directorT('no_eligible_workers'); return; }
    el.innerHTML = candidates.map(bot => `<label class="director-worker-item" data-nick="${_directorAttr(String(bot.nickname || '').toLowerCase())}" data-online="${bot.connected ? 1 : 0}"><input type="checkbox" data-director-worker value="${esc(bot.account_id)}" ${selected.has(bot.account_id) ? 'checked' : ''}><span class="director-tab-dot${bot.connected ? ' live' : ''}" aria-hidden="true"></span>${esc(bot.nickname)}</label>`).join('');
    el.querySelectorAll('[data-director-worker]').forEach(input => input.addEventListener('change', () => { markDirty('directorConfig'); renderDirectorWorkerCount(); }));
    renderDirectorWorkerFilter();
}

// Q40: массовый выбор workers — поиск по нику, «все / + онлайн / снять» действуют на видимые (отфильтрованные).
function renderDirectorWorkerFilter() {
    const query = ($('directorWorkerSearch')?.value || '').trim().toLowerCase();
    $('directorWorkerChoices')?.querySelectorAll('.director-worker-item').forEach(item => {
        item.classList.toggle('hidden', Boolean(query) && !String(item.dataset.nick || '').includes(query));
    });
    renderDirectorWorkerCount();
}
function renderDirectorWorkerCount() {
    const inputs = [...($('directorWorkerChoices')?.querySelectorAll('[data-director-worker]') || [])];
    if ($('directorWorkerCount')) $('directorWorkerCount').textContent = inputs.length ? _directorT('workers_count', {selected: inputs.filter(input => input.checked).length, total: inputs.length}) : '';
}
function directorWorkersBulk(action) {
    const items = [...($('directorWorkerChoices')?.querySelectorAll('.director-worker-item') || [])].filter(item => !item.classList.contains('hidden'));
    let changed = false;
    items.forEach(item => {
        const input = item.querySelector('[data-director-worker]');
        if (!input || input.disabled) return;
        const next = action === 'none' ? false : action === 'online' ? (input.checked || item.dataset.online === '1') : true;
        if (input.checked !== next) { input.checked = next; changed = true; }
    });
    if (changed) markDirty('directorConfig');
    renderDirectorWorkerCount();
}

function renderDirectorAccountChoices() {
    const channel = _directorChannels.find(item => item.channel === _directorChannel);
    const candidates = (channel?.bots || []).filter(bot => bot.enabled && bot.bot_role === 'director');
    const select = $('directorAccountSelect');
    // Единственный бот-режиссёр канала подставляется сам (сохранение — по-прежнему кнопкой).
    const selected = _directorConfigDirty() ? select.value : _directorState?.director_account_id || (candidates.length === 1 ? candidates[0].account_id : '');
    select.innerHTML = `<option value="">${esc(_directorT('select_account_placeholder'))}</option>` + candidates.map(bot => `<option value="${esc(bot.account_id)}">${esc(bot.nickname)}</option>`).join('');
    select.value = selected;
}

function renderDirectorPlan(plan) {
    const el = $('directorPlan');
    if (!plan) { el.textContent = _directorT('no_plan'); return; }
    const groups = (plan.groups || []).map(group => `${esc(group.text)} (${esc(group.percentage)}%)`).join(' · ');
    const latencyHtml = plan.latency_ms ? `<div><strong>${esc(_directorT('plan_latency') || 'Задержка ИИ')}:</strong> ⚡ ${(plan.latency_ms / 1000).toFixed(2)} с (${Math.round(plan.latency_ms)} мс)</div>` : '';
    el.innerHTML = `<div class="space-y-1"><div><strong>${esc(_directorT('plan_id'))}:</strong> ${esc(plan.id || plan.plan_id || '—')}</div><div><strong>${esc(_directorT('plan_status'))}:</strong> ${esc(_directorStatus(plan.status))}</div><div><strong>${esc(_directorT('plan_timing'))}:</strong> ${esc(plan.delay_seconds ?? plan.delay_window ?? '—')} / ${esc(plan.ttl_seconds ?? '—')}</div>${latencyHtml}<div>${groups || esc(_directorT('no_groups'))}</div></div>`;
}

function _directorValidConfig(config) {
    const number = key => Number(config[key]);
    const between = (key, min, max) => Number.isFinite(number(key)) && number(key) >= min && number(key) <= max;
    return between('temperature', 0, 2)
        && between('max_tokens', 50, 1000)
        && between('analysis_interval_sec', 3, 120)
        && between('priority_cooldown_sec', 3, 30)
        && between('send_delay_min_sec', 0, 300)
        && between('send_delay_max_sec', 0, 300)
        && number('send_delay_min_sec') <= number('send_delay_max_sec')
        && between('ttl_sec', 1, 600)
        && number('ttl_sec') >= number('send_delay_max_sec')
        && between('ai_error_limit', 1, 10)
        && between('vision_stale_sec', 1, 300)
        && between('speech_stale_sec', 1, 300)
        && between('offline_grace_sec', 0, 300);
}

async function directorEmergencyDryRun() {
    try {
        await api(`/api/director/${encodeURIComponent(_directorChannel)}/dry-run`, jopts('POST', {}));
        toast(_directorT('dry_run_done'), 'success');
        await loadDirectorChannel();
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function saveDirectorConfig() {
    const channel = _directorChannel;
    const config = _directorConfig();
    if (!_directorValidConfig(config)) { toast(_directorT('config_invalid'), 'error'); return; }
    try {
        const workerIds = [...document.querySelectorAll('[data-director-worker]:checked')].map(input => Number(input.value));
        const directorAccountId = Number($('directorAccountSelect').value);
        const result = await api(`/api/director/${encodeURIComponent(channel)}/config`, jopts('PUT', {config, worker_ids: workerIds, director_account_id: directorAccountId}));
        if (channel !== _directorChannel) return;
        _directorState.config = result.config || config;
        clearDirty('directorConfig');
        $('directorConfigStatus').textContent = _directorT('config_saved');
        toast(_directorT('config_saved'), 'success');
        await loadDirectorChannel();
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function directorSessionAction(action) {
    try {
        const endpoint = action === 'start' ? '/start' : `/${action}`;
        await api(`/api/director/${encodeURIComponent(_directorChannel)}${endpoint}`, jopts('POST', {}));
        await loadDirectorChannel();
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function directorStopSession() {
    if (!confirm(_directorT('stop_confirm'))) return;
    await directorSessionAction('stop');
}

async function directorEmergencyStop() {
    try {
        await api('/api/director/emergency', jopts('POST', {}));
        toast(_directorT('emergency_done'), 'success');
        if (_directorChannel) await loadDirectorChannel();
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function directorJoinNow(accountId) {
    try {
        await api(`/api/director/${encodeURIComponent(_directorChannel)}/workers/${encodeURIComponent(accountId)}/join-now`, jopts('POST', {}));
        await loadDirectorChannel();
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function loadDirectorAudit() {
    if (!_directorChannel) return;
    const channel = _directorChannel;
    const el = $('directorAudit');
    try {
        const data = await api(`/api/director/${encodeURIComponent(channel)}/audit`);
        if (channel !== _directorChannel) return;
        const entries = data.entries || [];
        if (!entries.length) { el.textContent = _directorT('audit_empty'); return; }
        el.innerHTML = entries.map(entry => `<div class="text-sm"><strong>${esc(entry.action || '—')}</strong> · ${esc(entry.result || '—')}<span class="text-muted"> · ${esc(entry.created_at || '')}</span></div>`).join('');
    } catch (e) { if (channel === _directorChannel) el.textContent = _directorT('audit_unavailable'); }
}

Object.assign(LANGS.ru, {
    'nav.director': 'Режиссёр', 'director.title': 'Режиссёр', 'director.hint': 'AI создаёт проверенные планы только для выбранных lurker-аккаунтов этого канала.',
    'director.emergency_stop': '⛔ Экстренная остановка', 'director.channel': 'Канал', 'director.channel_select': 'Канал Director', 'director.channel_hint': 'У каждого Twitch-канала — отдельные workers, конфигурация, сессия и audit.',
    'director.start': '▶ Запустить live', 'director.pause': '⏸ Пауза', 'director.resume': '▶ Продолжить', 'director.stop': '■ Остановить сессию', 'director.workers': '👀 Workers', 'director.workers_hint': 'Только явно выбранные enabled lurkers этого канала могут выполнить plan. Подключение планируется отдельно для каждого.',
    'director.plan': '📋 Текущий plan', 'director.plan_hint': 'Plan использует неизменный снимок свободных online workers. Невалидные части отклоняются, valid части не пересчитываются.', 'director.config': '⚙️ Конфигурация', 'director.config_hint': 'Настройки доступны только в состоянии off или paused. Сохранение создаёт новую версию конфигурации.',
    'director.provider': 'AI-провайдер', 'director.provider_hint': 'Модель должна пройти schema и hard-safety replay перед live.', 'director.model': 'Модель', 'director.model_hint': 'Автоматического fallback на другого provider или model нет.', 'director.mode': 'Режим', 'director.mode_live': 'Live', 'director.mode_suggest': 'Suggest', 'director.mode_training': 'Training',
    'director.assignment': 'Назначение workers', 'director.assignment_random': 'Случайное backend-назначение', 'director.assignment_ai': 'AI выбирает worker', 'director.assignment_hint': 'Worker не может входить в две text-группы одного plan.', 'director.analysis_interval': 'Интервал анализа, сек.', 'director.analysis_interval_hint': 'Разрешено от 3 до 120 секунд; default 15.', 'director.wake_cooldown': 'Cooldown высокого приоритета, сек.', 'director.wake_cooldown_hint': 'Сигналы объединяются; разрешено от 3 до 30 секунд.',
    'director.delay': 'Задержка отправки, сек.', 'director.delay_hint': 'Default 1–20 секунд; законный диапазон 0–300.', 'director.delay_max': 'Максимальная задержка, сек.', 'director.delay_max_hint': 'Не меньше начальной задержки.', 'director.ttl': 'TTL plan, сек.', 'director.ttl_hint': 'Default 45; TTL не меньше максимальной задержки. Непосланный хвост отменяется после TTL.', 'director.ai_errors': 'AI-ошибок до pause', 'director.ai_errors_hint': 'От 1 до 10; default 3 consecutive errors.', 'director.save': '💾 Сохранить конфигурацию',
    'director.audit': '🧾 Audit', 'director.audit_hint': 'Audit показывает source health, планы и безопасные результаты; скрытые рассуждения AI не сохраняются.', 'director.no_channels': 'Нет каналов для Режиссёра. Добавьте в канал стримера бота с ролью «Режиссёр» или lurker-ботов (Боты → роль и канал).', 'director.no_workers': 'Выбранных workers пока нет.', 'director.no_eligible_workers': 'В этом канале нет enabled lurker-аккаунтов.', 'director.select_workers': 'Выбранные workers', 'director.select_workers_hint': 'Выберите enabled lurker-аккаунты, подключённые к этому каналу. Новые lurkers не добавляются автоматически.', 'director.no_plan': 'Активного plan нет.', 'director.no_groups': 'Текстовых групп нет.', 'director.join_now': 'Зайти сейчас', 'director.config_locked': 'Настройки доступны после pause или stop.', 'director.config_invalid': 'Проверьте диапазоны времени и TTL: TTL не может быть меньше максимальной задержки.', 'director.config_saved': 'Конфигурация Director сохранена.', 'director.stop_confirm': 'Остановить Director session без финальной реакции? Непосланный хвост будет отменён.', 'director.emergency_done': 'Экстренная остановка выполнена.', 'director.emergency_hint': 'Новые планы запрещены. Для ручного возврата нужны 15 секунд health и valid dry-run.', 'director.lifecycle_off': 'Session не запущена.', 'director.lifecycle_live': 'Live: настройки заблокированы, plans проходят validation и idempotency.', 'director.lifecycle_paused': 'Пауза сохраняет хвост только до его исходного TTL.', 'director.status_healthy': 'готов', 'director.status_pause': 'пауза между планами', 'director.status_stale': 'устарел', 'director.status_unavailable': 'недоступен', 'director.status_unknown': 'неизвестно', 'director.status_off': 'выключен', 'director.status_live': 'live', 'director.status_paused': 'пауза', 'director.status_emergency': 'экстренная остановка', 'director.status_scheduled': 'запланирован', 'director.status_connecting': 'подключается', 'director.status_online': 'online', 'director.status_error': 'ошибка', 'director.source_ai': 'AI', 'director.source_vision': 'Vision', 'director.source_speech': 'Speech', 'director.plan_id': 'Plan ID', 'director.plan_status': 'Статус', 'director.plan_timing': 'Задержка / TTL', 'director.audit_empty': 'Записей audit пока нет.', 'director.audit_unavailable': 'Audit пока недоступен.', 'director.no_bot': 'Ботов с ролью «Режиссёр» нет — назначьте роль боту.',
});
Object.assign(LANGS.en, {
    'nav.director': 'Director', 'director.title': 'Director', 'director.hint': 'AI creates validated plans only for the selected lurker accounts of this channel.', 'director.emergency_stop': '⛔ Emergency Stop', 'director.channel': 'Channel', 'director.channel_select': 'Director channel', 'director.channel_hint': 'Each Twitch channel has its own workers, configuration, session, and audit.', 'director.start': '▶ Start live', 'director.pause': '⏸ Pause', 'director.resume': '▶ Resume', 'director.stop': '■ Stop session', 'director.workers': '👀 Workers', 'director.workers_hint': 'Only explicitly selected enabled lurkers for this channel may execute a plan. Each connection is scheduled separately.', 'director.plan': '📋 Current plan', 'director.plan_hint': 'A plan uses an immutable snapshot of free online workers. Invalid parts are rejected; valid parts are not recalculated.', 'director.config': '⚙️ Configuration', 'director.config_hint': 'Settings are available only when off or paused. Saving creates a new configuration version.', 'director.provider': 'AI provider', 'director.provider_hint': 'The model must pass schema and hard-safety replay before live.', 'director.model': 'Model', 'director.model_hint': 'There is no automatic fallback to another provider or model.', 'director.mode': 'Mode', 'director.mode_live': 'Live', 'director.mode_suggest': 'Suggest', 'director.mode_training': 'Training', 'director.assignment': 'Worker assignment', 'director.assignment_random': 'Random backend assignment', 'director.assignment_ai': 'AI selects worker', 'director.assignment_hint': 'A worker cannot join two text groups in one plan.', 'director.analysis_interval': 'Analysis interval, seconds', 'director.analysis_interval_hint': 'Allowed 3–120 seconds; default 15.', 'director.wake_cooldown': 'High-priority cooldown, seconds', 'director.wake_cooldown_hint': 'Signals are coalesced; allowed 3–30 seconds.', 'director.delay': 'Send delay, seconds', 'director.delay_hint': 'Default 1–20 seconds; legal range 0–300.', 'director.delay_max': 'Maximum delay, seconds', 'director.delay_max_hint': 'Must not be less than the initial delay.', 'director.ttl': 'Plan TTL, seconds', 'director.ttl_hint': 'Default 45; TTL cannot be less than maximum delay. The unsent tail is cancelled after TTL.', 'director.ai_errors': 'AI errors before pause', 'director.ai_errors_hint': '1–10; default 3 consecutive errors.', 'director.save': '💾 Save configuration', 'director.audit': '🧾 Audit', 'director.audit_hint': 'Audit shows source health, plans, and safe outcomes; hidden AI reasoning is never stored.', 'director.no_channels': 'No channels for the Director. Add a bot with the Director role or lurker bots to a streamer channel (Bots → role and channel).', 'director.no_bot': ': ', 'director.no_workers': 'No workers are selected yet.', 'director.no_plan': 'There is no active plan.', 'director.no_groups': 'There are no text groups.', 'director.join_now': 'Join now', 'director.config_locked': 'Settings are available after pause or stop.', 'director.config_invalid': 'Check timing ranges and TTL: TTL cannot be less than maximum delay.', 'director.config_saved': 'Director configuration saved.', 'director.stop_confirm': 'Stop the Director session without a final reaction? The unsent tail will be cancelled.', 'director.emergency_done': 'Emergency stop completed.', 'director.emergency_hint': 'New plans are blocked. Manual recovery requires 15 seconds of health and a valid dry-run.', 'director.lifecycle_off': 'The session is not running.', 'director.lifecycle_live': 'Live: settings are locked; plans pass validation and idempotency.', 'director.lifecycle_paused': 'Pause preserves the tail only until its original TTL.', 'director.status_healthy': 'healthy', 'director.status_pause': 'pause between plans', 'director.status_stale': 'stale', 'director.status_unavailable': 'unavailable', 'director.status_unknown': 'unknown', 'director.status_off': 'off', 'director.status_live': 'live', 'director.status_paused': 'paused', 'director.status_emergency': 'emergency stop', 'director.status_scheduled': 'scheduled', 'director.status_connecting': 'connecting', 'director.status_online': 'online', 'director.status_error': 'error', 'director.source_ai': 'AI', 'director.source_vision': 'Vision', 'director.source_speech': 'Speech', 'director.plan_id': 'Plan ID', 'director.plan_status': 'Status', 'director.plan_timing': 'Delay / TTL', 'director.audit_empty': 'No audit entries yet.', 'director.audit_unavailable': 'Audit is not available yet.', 'director.no_eligible_workers': 'This channel has no enabled lurker accounts.', 'director.select_workers': 'Selected workers', 'director.select_workers_hint': 'Select enabled lurker accounts connected to this channel. New lurkers are never added automatically.',
});
Object.assign(LANGS.ua, {
    'nav.director': 'Режисер', 'director.title': 'Режисер', 'director.hint': 'AI створює перевірені плани лише для вибраних lurker-акаунтів цього каналу.', 'director.emergency_stop': '⛔ Екстрена зупинка', 'director.channel': 'Канал', 'director.channel_select': 'Канал Director', 'director.channel_hint': 'Кожен Twitch-канал має окремі workers, конфігурацію, сесію та audit.', 'director.start': '▶ Запустити live', 'director.pause': '⏸ Пауза', 'director.resume': '▶ Продовжити', 'director.stop': '■ Зупинити сесію', 'director.workers': '👀 Workers', 'director.workers_hint': 'Лише явно вибрані enabled lurkers цього каналу можуть виконати plan. Кожне підключення планується окремо.', 'director.plan': '📋 Поточний plan', 'director.plan_hint': 'Plan використовує незмінний знімок вільних online workers. Невалідні частини відхиляються; valid частини не перераховуються.', 'director.config': '⚙️ Конфігурація', 'director.config_hint': 'Налаштування доступні лише в стані off або paused. Збереження створює нову версію конфігурації.', 'director.provider': 'AI-провайдер', 'director.provider_hint': 'Модель має пройти schema та hard-safety replay перед live.', 'director.model': 'Модель', 'director.model_hint': 'Автоматичного fallback на іншого provider або model немає.', 'director.mode': 'Режим', 'director.mode_live': 'Live', 'director.mode_suggest': 'Suggest', 'director.mode_training': 'Training', 'director.assignment': 'Призначення workers', 'director.assignment_random': 'Випадкове backend-призначення', 'director.assignment_ai': 'AI обирає worker', 'director.assignment_hint': 'Worker не може бути у двох text-групах одного plan.', 'director.analysis_interval': 'Інтервал аналізу, сек.', 'director.analysis_interval_hint': 'Дозволено 3–120 секунд; default 15.', 'director.wake_cooldown': 'Cooldown високого пріоритету, сек.', 'director.wake_cooldown_hint': 'Сигнали об’єднуються; дозволено 3–30 секунд.', 'director.delay': 'Затримка надсилання, сек.', 'director.delay_hint': 'Default 1–20 секунд; законний діапазон 0–300.', 'director.delay_max': 'Максимальна затримка, сек.', 'director.delay_max_hint': 'Не менше початкової затримки.', 'director.ttl': 'TTL plan, сек.', 'director.ttl_hint': 'Default 45; TTL не менше максимальної затримки. Ненадісланий хвіст скасовується після TTL.', 'director.ai_errors': 'AI-помилок до pause', 'director.ai_errors_hint': 'Від 1 до 10; default 3 consecutive errors.', 'director.save': '💾 Зберегти конфігурацію', 'director.audit': '🧾 Audit', 'director.audit_hint': 'Audit показує source health, плани й безпечні результати; приховані AI-міркування не зберігаються.', 'director.no_channels': 'Немає каналів для Режисера. Додайте в канал стримера бота з роллю «Режисер» або lurker-ботів (Боти → роль і канал).', 'director.no_bot': ': ', 'director.no_workers': 'Вибраних workers поки немає.', 'director.no_plan': 'Активного plan немає.', 'director.no_groups': 'Текстових груп немає.', 'director.join_now': 'Увійти зараз', 'director.config_locked': 'Налаштування доступні після pause або stop.', 'director.config_invalid': 'Перевірте діапазони часу й TTL: TTL не може бути меншим за максимальну затримку.', 'director.config_saved': 'Конфігурацію Director збережено.', 'director.stop_confirm': 'Зупинити Director session без фінальної реакції? Ненадісланий хвіст буде скасовано.', 'director.emergency_done': 'Екстрену зупинку виконано.', 'director.emergency_hint': 'Нові плани заборонені. Для ручного повернення потрібні 15 секунд health та valid dry-run.', 'director.lifecycle_off': 'Session не запущена.', 'director.lifecycle_live': 'Live: налаштування заблоковані, plans проходять validation та idempotency.', 'director.lifecycle_paused': 'Пауза зберігає хвіст лише до його початкового TTL.', 'director.status_healthy': 'готовий', 'director.status_pause': 'пауза між планами', 'director.status_stale': 'застарілий', 'director.status_unavailable': 'недоступний', 'director.status_unknown': 'невідомо', 'director.status_off': 'вимкнено', 'director.status_live': 'live', 'director.status_paused': 'пауза', 'director.status_emergency': 'екстрена зупинка', 'director.status_scheduled': 'запланований', 'director.status_connecting': 'підключається', 'director.status_online': 'online', 'director.status_error': 'помилка', 'director.source_ai': 'AI', 'director.source_vision': 'Vision', 'director.source_speech': 'Speech', 'director.plan_id': 'Plan ID', 'director.plan_status': 'Статус', 'director.plan_timing': 'Затримка / TTL', 'director.audit_empty': 'Записів audit поки немає.', 'director.audit_unavailable': 'Audit поки недоступний.', 'director.no_eligible_workers': 'У цьому каналі немає enabled lurker-акаунтів.', 'director.select_workers': 'Вибрані workers', 'director.select_workers_hint': 'Виберіть enabled lurker-акаунти, підключені до цього каналу. Нові lurkers не додаються автоматично.',
});

Object.assign(LANGS.ru, {
    'director.dry_run': '🧪 Проверить восстановление', 'director.mode_hint': 'Training и Suggest не отправляют в Twitch. Suggest сохраняет только одобренные примеры.',
    'director.prompts': 'Версии промпта и проверка', 'director.replay_hint': 'Проверка вызывает сохранённые provider/model без отправки в Twitch. Перед активацией изучите ответы и подтвердите качество.',
    'director.prompt_text': 'Инструкции владельца', 'director.prompt_hint': 'Новая неизменяемая версия. Системные правила и правила безопасности не изменяются.', 'director.prompt_create': 'Создать версию',
    'director.suggestions': 'Предложения для обучения', 'director.suggest_hint': 'Просмотрите и отредактируйте весь план. Одобрение сохраняет пример для будущих решений, но никогда не отправляет сообщения в Twitch.',
});
Object.assign(LANGS.ru, {
    'director.select_account': 'Аккаунт Режиссёра', 'director.select_account_hint': 'Один enabled аккаунт с ролью «Режиссёр» в этом канале анализирует, но никогда не пишет в чат.', 'director.select_account_placeholder': 'Выберите аккаунт Режиссёра',
});
Object.assign(LANGS.en, {
    'director.dry_run': '🧪 Recovery dry-run', 'director.mode_hint': 'Training and Suggest never post to Twitch. Suggest only stores approved examples.',
    'director.prompts': 'Prompt versions and replay', 'director.replay_hint': 'Replay calls the stored provider/model without posting to Twitch. Review the answers and confirm quality before activation.',
    'director.prompt_text': 'Owner instructions', 'director.prompt_hint': 'A new immutable version. System rules and safety rules are never modified.', 'director.prompt_create': 'Create version',
    'director.suggestions': 'Training suggestions', 'director.suggest_hint': 'Review and edit the whole plan. Approval stores an example for future decisions but never sends messages to Twitch.',
});
Object.assign(LANGS.en, {
    'director.select_account': 'Director account', 'director.select_account_hint': 'One enabled Director account in this channel analyzes but never posts in chat.', 'director.select_account_placeholder': 'Choose a Director account',
});
Object.assign(LANGS.ua, {
    'director.dry_run': '🧪 Перевірити відновлення', 'director.mode_hint': 'Training і Suggest не надсилають у Twitch. Suggest зберігає лише схвалені приклади.',
    'director.prompts': 'Версії промпта та перевірка', 'director.replay_hint': 'Перевірка викликає збережені provider/model без надсилання в Twitch. Перед активацією перегляньте відповіді та підтвердіть якість.',
    'director.prompt_text': 'Інструкції власника', 'director.prompt_hint': 'Нова незмінна версія. Системні правила та правила безпеки не змінюються.', 'director.prompt_create': 'Створити версію',
    'director.suggestions': 'Пропозиції для навчання', 'director.suggest_hint': 'Перегляньте й відредагуйте весь план. Схвалення зберігає приклад для майбутніх рішень, але ніколи не надсилає повідомлень у Twitch.',
});
Object.assign(LANGS.ua, {
    'director.select_account': 'Акаунт Режисера', 'director.select_account_hint': 'Один enabled акаунт з роллю «Режисер» у цьому каналі аналізує, але ніколи не пише в чат.', 'director.select_account_placeholder': 'Виберіть акаунт Режисера',
});

Object.assign(LANGS.ru, {'director.source_twitch': 'Twitch'});
Object.assign(LANGS.en, {'director.source_twitch': 'Twitch'});
Object.assign(LANGS.ua, {'director.source_twitch': 'Twitch'});

Object.assign(LANGS.ru, {
    'director.language': 'Язык канала', 'director.language_auto': 'Авто', 'director.language_mixed': 'Смешанный', 'director.language_hint': 'Авто определяет язык чата с поддержкой транслита.',
    'director.reaction_mode': 'Расчёт реакции', 'director.reaction_absolute': 'Количество', 'director.reaction_percentage': 'Проценты', 'director.reaction_mode_hint': 'Диапазоны реакции применяются к доступным workers текущего канала.',
    'director.vision_stale': 'Vision stale, сек.', 'director.vision_stale_hint': 'Свежий Vision heartbeat обязателен для live.', 'director.speech_stale': 'Speech stale, сек.', 'director.speech_stale_hint': 'Свежий speech heartbeat обязателен для live.', 'director.offline_grace': 'Offline grace, сек.', 'director.offline_grace_hint': 'После Twitch offline новые plans блокируются сразу.',
});
Object.assign(LANGS.en, {
    'director.language': 'Channel language', 'director.language_auto': 'Auto', 'director.language_mixed': 'Mixed', 'director.language_hint': 'Auto detects chat language and supports transliteration.',
    'director.reaction_mode': 'Reaction calculation', 'director.reaction_absolute': 'Count', 'director.reaction_percentage': 'Percentages', 'director.reaction_mode_hint': 'Reaction ranges apply to the available workers of this channel.',
    'director.vision_stale': 'Vision stale, sec.', 'director.vision_stale_hint': 'A fresh Vision heartbeat is required for live.', 'director.speech_stale': 'Speech stale, sec.', 'director.speech_stale_hint': 'A fresh speech heartbeat is required for live.', 'director.offline_grace': 'Offline grace, sec.', 'director.offline_grace_hint': 'New plans are blocked immediately after Twitch goes offline.',
});
Object.assign(LANGS.ua, {
    'director.language': 'Мова каналу', 'director.language_auto': 'Авто', 'director.language_mixed': 'Змішана', 'director.language_hint': 'Авто визначає мову чату з підтримкою трансліту.',
    'director.reaction_mode': 'Розрахунок реакції', 'director.reaction_absolute': 'Кількість', 'director.reaction_percentage': 'Відсотки', 'director.reaction_mode_hint': 'Діапазони реакції застосовуються до доступних workers цього каналу.',
    'director.vision_stale': 'Vision stale, сек.', 'director.vision_stale_hint': 'Свіжий Vision heartbeat обов’язковий для live.', 'director.speech_stale': 'Speech stale, сек.', 'director.speech_stale_hint': 'Свіжий speech heartbeat обов’язковий для live.', 'director.offline_grace': 'Offline grace, сек.', 'director.offline_grace_hint': 'Після Twitch offline нові plans блокуються одразу.',
});

Object.assign(LANGS.ru, {
    'director.reaction_ranges': 'Диапазоны реакций', 'director.reaction_ranges_hint': 'Границы уровней должны возрастать и не пересекаться.', 'director.range_small': 'Small', 'director.range_medium': 'Medium', 'director.range_large': 'Large',
});
Object.assign(LANGS.en, {
    'director.reaction_ranges': 'Reaction ranges', 'director.reaction_ranges_hint': 'Level boundaries must increase and not overlap.', 'director.range_small': 'Small', 'director.range_medium': 'Medium', 'director.range_large': 'Large',
});
Object.assign(LANGS.ua, {
    'director.reaction_ranges': 'Діапазони реакцій', 'director.reaction_ranges_hint': 'Межі рівнів мають зростати та не перетинатися.', 'director.range_small': 'Small', 'director.range_medium': 'Medium', 'director.range_large': 'Large',
});

// ── Q40: страница Режиссёра — вкладки каналов и выбор дизайна ──
function renderDirectorChannelTabs() {
    const el = $('directorChannelTabs');
    if (!el) return;
    el.innerHTML = _directorChannels.map(channel => {
        const name = channel.channel;
        const active = name === _directorChannel;
        const status = _directorTabStatus.get(name) || '';
        const live = status === 'live';
        const lurkers = (channel.bots || []).filter(bot => bot.enabled && bot.bot_role === 'lurker');
        const online = lurkers.filter(bot => bot.connected).length;
        const badge = status ? `<span class="director-tab-state state-${_directorAttr(status)}">${esc(_directorStatus(status))}</span>` : '';
        const mode = _directorMode(name);
        const modeTag = `<span class="director-tab-mode mode-${mode}">${esc(_directorT(mode === 'manual' ? 'tab_manual' : 'tab_ai'))}</span>`;
        return `<button type="button" role="tab" class="director-channel-tab${active ? ' active' : ''}" aria-selected="${active}" tabindex="${active ? 0 : -1}" data-channel="${_directorAttr(name)}" onclick="directorChannelTab(this.dataset.channel)" onkeydown="directorChannelTabKey(event)">`
            + `<span class="director-tab-name"><span class="director-tab-dot${live ? ' live' : ''}" aria-hidden="true"></span>#${esc(name)}</span>`
            + `<span class="director-tab-meta">${modeTag}<span title="${_directorAttr(_directorT('tab_workers'))}">🤖 ${online}/${lurkers.length}</span>${badge}</span></button>`;
    }).join('');
}

function directorChannelTab(channel) {
    if (!channel || channel === _directorChannel) return;
    $('directorChannelSelect').value = channel;
    return selectDirectorChannel(channel);
}

function directorChannelTabKey(event) {
    const keys = {ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1};
    if (!(event.key in keys)) return;
    event.preventDefault();
    const tabs = [...$('directorChannelTabs').querySelectorAll('[role="tab"]')];
    const next = tabs[(tabs.indexOf(event.currentTarget) + keys[event.key] + tabs.length) % tabs.length];
    next?.focus();
    next?.click();
}

const DIRECTOR_SKINS = ['pult', 'cockpit'];
function panelLayout() {
    try {
        const value = localStorage.getItem('panelLayout') || localStorage.getItem('directorSkin');
        return DIRECTOR_SKINS.includes(value) ? value : 'pult';
    }
    catch (_) { return 'pult'; }
}
function applyPanelLayout(skin) {
    if (!DIRECTOR_SKINS.includes(skin)) skin = 'pult';
    try { localStorage.setItem('panelLayout', skin); } catch (_) { /* private mode */ }
    document.documentElement?.setAttribute('data-panel-layout', skin);
    $('section-director')?.setAttribute('data-director-skin', skin);
    document.querySelectorAll('[data-director-skin-option]').forEach(button => {
        const on = button.dataset.directorSkinOption === skin;
        button.classList.toggle('active', on);
        button.setAttribute('aria-pressed', String(on));
    });
}
const applyDirectorSkin = applyPanelLayout;
if (typeof document !== 'undefined' && typeof document.querySelectorAll === 'function') {
    try { applyPanelLayout(panelLayout()); } catch (_) { /* test harness without DOM */ }
}

Object.assign(LANGS.ru, {
    'director.tab_workers': 'Lurkers онлайн / всего в канале',
    'settings.panel_layout': '🖥️ Дизайн панели', 'settings.panel_layout_hint': 'Меняет раскладку всей панели. Фон выбирается отдельно выше; выбор хранится в этом браузере.',
    'settings.director_skin_pult': 'Пульт', 'settings.panel_layout_pult_hint': 'Плотная раскладка, компактные карточки и прямые линии',
    'settings.director_skin_cockpit': 'Кокпит', 'settings.panel_layout_cockpit_hint': 'Крупные карточки, скругления и акцентные градиенты',
});
Object.assign(LANGS.en, {
    'director.tab_workers': 'Lurkers online / total in channel',
    'settings.panel_layout': '🖥️ Panel layout', 'settings.panel_layout_hint': 'Changes the layout of the whole panel. Choose the background separately above; the choice is stored in this browser.',
    'settings.director_skin_pult': 'Console', 'settings.panel_layout_pult_hint': 'Dense layout, compact cards and crisp edges',
    'settings.director_skin_cockpit': 'Cockpit', 'settings.panel_layout_cockpit_hint': 'Large cards, rounded surfaces and accent gradients',
});
Object.assign(LANGS.ua, {
    'director.tab_workers': 'Lurkers онлайн / всього в каналі',
    'settings.panel_layout': '🖥️ Дизайн панелі', 'settings.panel_layout_hint': 'Змінює компонування всієї панелі. Фон обирається окремо вище; вибір зберігається у цьому браузері.',
    'settings.director_skin_pult': 'Пульт', 'settings.panel_layout_pult_hint': 'Щільне компонування, компактні картки та чіткі лінії',
    'settings.director_skin_cockpit': 'Кокпіт', 'settings.panel_layout_cockpit_hint': 'Великі картки, заокруглення та акцентні градієнти',
});

// ── Q40b: режим ИИ / Ручной и ручная отправка ──
function _directorMode(channel = _directorChannel) { return _directorModes.get(channel)?.mode || 'ai'; }
function _directorSessionStatus() {
    const session = _directorState?.session || {};
    return session.state === 'stopped' ? 'off' : (session.state || _directorState?.status || 'off');
}
function _directorManualSenders() {
    const channel = _directorChannels.find(item => item.channel === _directorChannel);
    return (channel?.bots || []).filter(bot => bot.enabled && bot.bot_role === 'lurker');
}

async function loadDirectorModes() {
    try {
        const result = await api('/api/director/control-modes');
        _directorModes.clear();
        Object.entries(result.modes || {}).forEach(([channel, info]) => _directorModes.set(channel, info));
    } catch (_) { /* вкладки покажут ИИ по умолчанию */ }
}

function renderDirectorMode() {
    const mode = _directorMode();
    const fenced = Boolean(_directorModes.get(_directorChannel)?.fenced);
    const locked = _directorSessionStatus() !== 'off';
    $('section-director')?.setAttribute('data-director-mode', mode);
    document.querySelectorAll('.director-mode-btn').forEach(button => {
        const on = button.dataset.directorMode === mode;
        button.classList.toggle('active', on);
        button.setAttribute('aria-checked', String(on));
        button.disabled = locked && !on;
    });
    if ($('directorModeHint')) $('directorModeHint').textContent = _directorT(locked ? 'mode_locked' : mode === 'manual' ? 'mode_manual_hint' : 'mode_ai_hint');
    $('directorManualFenced')?.classList.toggle('hidden', !fenced);
    $('directorManualUnfence')?.classList.toggle('hidden', !fenced);
    renderDirectorManualSenders();
    renderDirectorManualPreview();
    renderDirectorManualLog();
    renderDirectorManualPresets();
}

async function directorSetMode(mode) {
    const channel = _directorChannel;
    if (!channel || mode === _directorMode(channel)) return;
    try {
        const result = await api(`/api/director/${encodeURIComponent(channel)}/control-mode`, jopts('PUT', {mode}));
        _directorModes.set(channel, {mode: result.mode, fenced: Boolean(result.fenced)});
        if (channel !== _directorChannel) return;
        renderDirectorMode();
        renderDirectorChannelTabs();
        if (result.mode === 'manual') loadDirectorManualMessages();
        if (result.mode === 'manual') loadDirectorManualPresets();
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

function directorManualPick(accountId) {
    if (_directorManual.sender.get(_directorChannel) === accountId) _directorManual.sender.delete(_directorChannel);
    else _directorManual.sender.set(_directorChannel, accountId);
    renderDirectorManualSenders();
    renderDirectorManualPreview();
}

function renderDirectorManualSenders() {
    const el = $('directorManualSenders');
    if (!el) return;
    const senders = _directorManualSenders();
    const selected = _directorManual.sender.get(_directorChannel);
    // Отправитель выбирается только явно; исчезнувший из канала — сбрасывается.
    if (selected && !senders.some(bot => bot.account_id === selected)) _directorManual.sender.delete(_directorChannel);
    if (!senders.length) { el.textContent = _directorT('manual_no_senders'); return; }
    const query = ($('directorManualSenderSearch')?.value || '').trim().toLowerCase();
    const current = _directorManual.sender.get(_directorChannel);
    const visible = senders.filter(bot => !query || bot.account_id === current || String(bot.nickname || '').toLowerCase().includes(query));
    $('directorManualSenderSearch')?.classList.toggle('hidden', senders.length <= 8 && !query);
    el.innerHTML = visible.map(bot => {
        const on = bot.account_id === _directorManual.sender.get(_directorChannel);
        return `<button type="button" role="radio" aria-checked="${on}" class="director-sender-chip${on ? ' active' : ''}" data-account-id="${_directorAttr(bot.account_id)}" onclick="directorManualPick(Number(this.dataset.accountId))"><span class="director-tab-dot${bot.connected ? ' live' : ''}" aria-hidden="true"></span>${esc(bot.nickname || `#${bot.account_id}`)}</button>`;
    }).join('');
}

function renderDirectorManualPreview() {
    const el = $('directorManualPreview');
    if (!el) return;
    const text = ($('directorManualText')?.value || '').trim();
    const senderId = _directorManual.sender.get(_directorChannel);
    const sender = senderId ? _directorManualSenders().find(bot => bot.account_id === senderId) : null;
    el.innerHTML = text && sender
        ? `<small>${esc(_directorT('manual_preview'))} · #${esc(_directorChannel)}</small><div><b>${esc(sender.nickname)}:</b> <span data-user-content>${esc(text)}</span></div>`
        : `<small>${esc(_directorT(sender ? 'manual_preview_text' : 'manual_preview_sender'))}</small>`;
    const fenced = Boolean(_directorModes.get(_directorChannel)?.fenced);
    if ($('directorManualSend')) $('directorManualSend').disabled = !text || !sender || fenced || _directorManual.pending || _directorMode() !== 'manual';
    if ($('directorManualStatus')) $('directorManualStatus').textContent = _directorManual.status;
}

function renderDirectorManualLog() {
    const el = $('directorManualLog');
    if (!el) return;
    const messages = _directorManual.messages.get(_directorChannel) || [];
    if (!messages.length) { el.textContent = _directorT('manual_history_empty'); return; }
    el.innerHTML = messages.map(message => {
        const time = new Date(Number(message.created_at) * 1000).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', hour12: false});
        // Q38: «Повторить» подставляет текст (и отправителя, если он ещё доступен) в композер —
        // отправка остаётся отдельным явным действием, автосендинга здесь нет. Текст передаём
        // через data-msg-id + поиск в уже загруженном _directorManual.messages, а не через onclick-
        // литерал — иначе кавычки/переносы строк в тексте сломали бы атрибут.
        const repeat = `<button type="button" class="director-manual-repeat" data-msg-id="${_directorAttr(message.id)}" title="${esc(_directorT('manual_repeat'))}" aria-label="${esc(_directorT('manual_repeat'))}" onclick="directorManualRepeat(this.dataset.msgId)">↻</button>`;
        return `<div class="director-manual-row state-${_directorAttr(message.state)}"><span class="director-manual-time">${esc(time)}</span><b>${esc(message.nickname || `#${message.account_id}`)}</b><span data-user-content>${esc(message.text)}</span><span class="director-manual-state">${esc(_directorT(`manual_state_${message.state}`))}</span>${repeat}</div>`;
    }).join('');
}

function directorManualRepeat(messageId) {
    const message = (_directorManual.messages.get(_directorChannel) || []).find(m => String(m.id) === String(messageId));
    if (!message || !$('directorManualText')) return;
    $('directorManualText').value = message.text;
    const sender = _directorManualSenders().find(bot => bot.account_id === Number(message.account_id));
    if (sender) _directorManual.sender.set(_directorChannel, sender.account_id);
    renderDirectorManualSenders();
    renderDirectorManualPreview();
    $('directorManualText').focus?.();
}

async function loadDirectorManualMessages() {
    const channel = _directorChannel;
    if (!channel) return;
    try {
        const result = await api(`/api/director/${encodeURIComponent(channel)}/operator/messages`);
        _directorManual.messages.set(channel, result.messages || []);
        if (channel === _directorChannel) renderDirectorManualLog();
    } catch (_) { /* журнал необязателен для отправки */ }
}

// ── Q35: заготовки — список, CRUD, хоткеи Alt+1..Alt+9 ──
async function loadDirectorManualPresets() {
    const channel = _directorChannel;
    if (!channel) return;
    try {
        const result = await api(`/api/director/${encodeURIComponent(channel)}/manual/presets`);
        _directorPresets.set(channel, result.presets || []);
        if (channel === _directorChannel) renderDirectorManualPresets();
    } catch (_) { /* заготовки необязательны для отправки */ }
}

function renderDirectorManualPresets() {
    const el = $('directorManualPresets');
    if (!el) return;
    const presets = _directorPresets.get(_directorChannel) || [];
    if (!presets.length) { el.innerHTML = `<span class="text-sm text-muted">${esc(_directorT('presets_empty'))}</span>`; return; }
    el.innerHTML = presets.map((preset, index) => {
        const editing = _directorPresetEditing === preset.id;
        const hotkey = index < 9 ? `<span class="director-preset-hotkey">Alt+${index + 1}</span>` : '';
        if (editing) {
            return `<span class="director-preset-chip editing" role="listitem" data-preset-id="${_directorAttr(preset.id)}">`
                + `<input id="directorPresetEditInput" class="input director-preset-edit-input" value="${_directorAttr(preset.text)}" maxlength="500" onkeydown="directorPresetEditKey(event, ${preset.id})">`
                + `<button type="button" class="btn btn-primary btn-sm" onclick="directorPresetSaveEdit(${preset.id})" data-i18n="director.preset_save">${esc(_directorT('preset_save'))}</button>`
                + `<button type="button" class="btn btn-secondary btn-sm" onclick="directorPresetCancelEdit()" data-i18n="director.preset_cancel">${esc(_directorT('preset_cancel'))}</button>`
                + `</span>`;
        }
        return `<span class="director-preset-chip" role="listitem" data-preset-id="${_directorAttr(preset.id)}">`
            + `<button type="button" class="director-preset-text" onclick="directorPresetInsert(${preset.id})">${hotkey}<span data-user-content>${esc(preset.text)}</span></button>`
            + `<button type="button" class="director-preset-icon" title="${esc(_directorT('preset_edit'))}" aria-label="${esc(_directorT('preset_edit'))}" onclick="directorPresetStartEdit(${preset.id})">✎</button>`
            + `<button type="button" class="director-preset-icon" title="${esc(_directorT('preset_delete'))}" aria-label="${esc(_directorT('preset_delete'))}" onclick="directorPresetRemove(${preset.id})">✕</button>`
            + `</span>`;
    }).join('');
}

function directorPresetInsert(presetId) {
    const preset = (_directorPresets.get(_directorChannel) || []).find(p => p.id === presetId);
    if (!preset || !$('directorManualText')) return;
    $('directorManualText').value = preset.text;
    renderDirectorManualPreview();
    $('directorManualText').focus?.();
}

function directorPresetHotkey(index) {
    if (_directorMode() !== 'manual') return;
    const preset = (_directorPresets.get(_directorChannel) || [])[index];
    if (preset) directorPresetInsert(preset.id);
}

function directorPresetInputKey(event) {
    if (event.key !== 'Enter' || event.isComposing) return;
    event.preventDefault();
    directorPresetAdd();
}

async function directorPresetAdd() {
    const channel = _directorChannel;
    const input = $('directorPresetInput');
    const text = (input?.value || '').trim();
    if (!channel || !text) return;
    try {
        const result = await api(`/api/director/${encodeURIComponent(channel)}/manual/presets`, jopts('POST', {text}));
        _directorPresets.set(channel, result.presets || []);
        if (input) input.value = '';
        if (channel === _directorChannel) renderDirectorManualPresets();
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

function directorPresetStartEdit(presetId) { _directorPresetEditing = presetId; renderDirectorManualPresets(); }
function directorPresetCancelEdit() { _directorPresetEditing = null; renderDirectorManualPresets(); }

function directorPresetEditKey(event, presetId) {
    if (event.key === 'Enter' && !event.isComposing) { event.preventDefault(); directorPresetSaveEdit(presetId); }
    else if (event.key === 'Escape') { event.preventDefault(); directorPresetCancelEdit(); }
}

async function directorPresetSaveEdit(presetId) {
    const channel = _directorChannel;
    const text = ($('directorPresetEditInput')?.value || '').trim();
    if (!text) return;
    try {
        const result = await api(`/api/director/${encodeURIComponent(channel)}/manual/presets/${presetId}`, jopts('PUT', {text}));
        _directorPresets.set(channel, result.presets || []);
        _directorPresetEditing = null;
        if (channel === _directorChannel) renderDirectorManualPresets();
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function directorPresetRemove(presetId) {
    if (!confirm(t('confirm.delete_item'))) return;
    const channel = _directorChannel;
    try {
        const result = await api(`/api/director/${encodeURIComponent(channel)}/manual/presets/${presetId}`, jopts('DELETE'));
        _directorPresets.set(channel, result.presets || []);
        if (channel === _directorChannel) renderDirectorManualPresets();
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

// Alt+1..Alt+9 подставляют заготовку в композер, пока открыт ручной режим Режиссёра.
// Глобальные хоткеи стримера: Alt+H (Хайп), Alt+Q (Оживить), Alt+M (Пауза/Возобновить).
document.addEventListener?.('keydown', (event) => {
    if (!event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    const tag = (event.target?.tagName || '').toUpperCase();
    if (tag === 'INPUT' || tag === 'TEXTAREA' || event.target?.isContentEditable) return;

    const key = (event.key || '').toLowerCase();
    if (key === 'h' || key === 'р') {
        event.preventDefault();
        directorQuickAction?.('hype_emotes');
        return;
    }
    if (key === 'q' || key === 'й') {
        event.preventDefault();
        directorQuickAction?.('break_silence');
        return;
    }
    if (key === 'm' || key === 'ь') {
        event.preventDefault();
        directorTogglePause?.();
        return;
    }
    if (key === 't' || key === 'е') {
        event.preventDefault();
        directorToggleTtsMute?.();
        return;
    }

    if (!$('section-director')?.classList?.contains('active')) return;
    if (_directorMode() !== 'manual') return;
    const index = Number(event.key) - 1;
    if (!Number.isInteger(index) || index < 0 || index > 8) return;
    event.preventDefault();
    directorPresetHotkey(index);
});

function directorManualKey(event) {
    if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return;
    event.preventDefault();
    directorManualSend();
}

async function directorManualSend() {
    const channel = _directorChannel;
    const text = ($('directorManualText')?.value || '').trim();
    const accountId = _directorManual.sender.get(channel);
    if (!text || !accountId || _directorManual.pending || _directorMode(channel) !== 'manual') return;
    _directorManual.pending = true;
    _directorManual.status = _directorT('manual_sending');
    renderDirectorManualPreview();
    // Q36: пока запрос ждёт своей очереди на бэке, подсказываем оператору, сколько отправок впереди.
    const queuePoll = setInterval(async () => {
        try {
            const q = await api(`/api/director/${encodeURIComponent(channel)}/operator/queue`);
            if (q.pending > 1 && channel === _directorChannel) {
                _directorManual.status = _directorT('manual_queued', {n: q.pending});
                renderDirectorManualPreview();
            }
        } catch (_) { /* индикатор очереди необязателен */ }
    }, 300);
    try {
        await api(`/api/director/${encodeURIComponent(channel)}/operator/send`, jopts('POST', {account_id: accountId, text}));
        if (channel === _directorChannel && ($('directorManualText').value || '').trim() === text) $('directorManualText').value = '';
        _directorManual.status = _directorT('manual_sent');
    } catch (e) {
        _directorManual.status = e.message;
        if (e.code === 'director_manual_fenced') _directorModes.set(channel, {mode: 'manual', fenced: true});
    } finally {
        clearInterval(queuePoll);
        _directorManual.pending = false;
        if (channel === _directorChannel) renderDirectorMode();
        await loadDirectorManualMessages();
    }
}

async function directorManualUnfence() {
    const channel = _directorChannel;
    try {
        const result = await api(`/api/director/${encodeURIComponent(channel)}/operator/unfence`, jopts('POST', {}));
        _directorModes.set(channel, {mode: result.mode, fenced: Boolean(result.fenced)});
        _directorManual.status = '';
        if (channel === _directorChannel) renderDirectorMode();
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

Object.assign(LANGS.ru, {
    'director.control_mode': 'Режим управления', 'director.control_ai': '🤖 ИИ', 'director.control_manual': '✍️ Ручной',
    'director.mode_ai_hint': 'Режиссёр сам планирует реакции (Live / Suggest / Training в конфигурации).', 'director.mode_manual_hint': 'ИИ не запускается: вы пишете текст и сами выбираете бота-отправителя.',
    'director.mode_locked': 'Режим меняется только при остановленной сессии.', 'director.tab_ai': 'ИИ', 'director.tab_manual': 'РУЧН',
    'director.manual_title': '✍️ Ручная отправка', 'director.manual_unfence': 'Снять экстренную блокировку', 'director.manual_fenced': 'Экстренная остановка: ручная отправка заблокирована до явного снятия.',
    'director.manual_text': 'Текст сообщения', 'director.manual_text_hint': 'Enter — отправить, Shift+Enter — новая строка. Ссылки, !команды и @упоминания запрещены.',
    'director.manual_sender': 'Бот-отправитель', 'director.manual_send': 'Отправить ⏎', 'director.manual_history': 'Последние ручные отправки', 'director.manual_history_empty': 'Ручных отправок пока нет.',
    'director.manual_no_senders': 'В этом канале нет включённых lurker-ботов.', 'director.manual_preview': 'Предпросмотр',
    'director.manual_preview_sender': 'Выберите бота-отправителя.', 'director.manual_preview_text': 'Напишите текст — здесь появится предпросмотр.',
    'director.manual_sending': 'Отправляем…', 'director.manual_sent': 'Сообщение отправлено.',
    'director.manual_queued': 'В очереди канала: {n} — темп отправки ограничен.',
    'director.manual_state_sent': 'отправлено', 'director.manual_state_blocked': 'заблокировано', 'director.manual_state_error': 'не доставлено',
    'director.manual_repeat': 'Повторить: подставить в композер',
    'director.presets_title': 'Заготовки', 'director.presets_empty': 'Заготовок пока нет.', 'director.presets_hint': 'Alt+1…Alt+9 подставляют заготовку в поле сообщения ниже.',
    'director.preset_add_placeholder': 'Новая заготовка…', 'director.preset_add': '+ Добавить', 'director.preset_edit': 'Изменить', 'director.preset_delete': 'Удалить',
    'director.preset_save': 'Сохранить', 'director.preset_cancel': 'Отмена',
    'api.error.director_manual_mode': 'Канал в ручном режиме — переключите на «ИИ», чтобы запустить сессию.', 'api.error.director_manual_required': 'Ручная отправка доступна только в режиме «Ручной».',
    'api.error.director_manual_fenced': 'Ручная отправка заблокирована экстренной остановкой.', 'api.error.manual_sender_required': 'Бот-отправитель не выбран.',
    'api.error.manual_sender_not_channel_lurker': 'Этот бот не включён как lurker в этом канале.', 'api.error.manual_send_too_fast': 'Сообщение только что ушло — повторная отправка отклонена.',
    'api.error.manual_url_forbidden': 'Ссылки в сообщении запрещены.', 'api.error.manual_command_forbidden': '!команды в сообщении запрещены.', 'api.error.manual_mention_forbidden': '@упоминания в сообщении запрещены.',
    'api.error.manual_code_like_forbidden': 'Код в сообщении запрещён.', 'api.error.manual_secret_or_personal_data_forbidden': 'Похоже на секрет или личные данные — не отправлено.',
    'api.error.manual_text_empty': 'Сообщение пустое.', 'api.error.manual_text_too_long': 'Сообщение слишком длинное.', 'api.error.manual_text_not_string': 'Некорректный текст сообщения.',
    'api.error.manual_send_failed': 'Twitch не принял сообщение ({reason}).', 'api.error.moderation_blocked': 'Сообщение заблокировано исходящей модерацией.', 'api.error.invalid_control_mode': 'Неизвестный режим управления.',
    'api.error.manual_preset_limit_reached': 'Заготовок не может быть больше 9 (по числу хоткеев Alt+1…Alt+9).', 'api.error.manual_preset_not_found': 'Заготовка не найдена.', 'api.error.manual_preset_order_invalid': 'Некорректный порядок заготовок.',
});
Object.assign(LANGS.en, {
    'director.control_mode': 'Control mode', 'director.control_ai': '🤖 AI', 'director.control_manual': '✍️ Manual',
    'director.mode_ai_hint': 'The Director plans reactions itself (Live / Suggest / Training in the configuration).', 'director.mode_manual_hint': 'AI does not run: you write the text and choose the sending bot yourself.',
    'director.mode_locked': 'The mode can change only while the session is stopped.', 'director.tab_ai': 'AI', 'director.tab_manual': 'MAN',
    'director.manual_title': '✍️ Manual send', 'director.manual_unfence': 'Lift emergency block', 'director.manual_fenced': 'Emergency stop: manual sending is blocked until explicitly lifted.',
    'director.manual_text': 'Message text', 'director.manual_text_hint': 'Enter sends, Shift+Enter adds a line. Links, !commands and @mentions are forbidden.',
    'director.manual_sender': 'Sending bot', 'director.manual_send': 'Send ⏎', 'director.manual_history': 'Recent manual sends', 'director.manual_history_empty': 'No manual sends yet.',
    'director.manual_no_senders': 'This channel has no enabled lurker bots.', 'director.manual_preview': 'Preview',
    'director.manual_preview_sender': 'Choose the sending bot.', 'director.manual_preview_text': 'Type a message to see the preview here.',
    'director.manual_sending': 'Sending…', 'director.manual_sent': 'Message sent.',
    'director.manual_queued': 'Channel queue: {n} — send rate is limited.',
    'director.manual_state_sent': 'sent', 'director.manual_state_blocked': 'blocked', 'director.manual_state_error': 'not delivered',
    'director.manual_repeat': 'Repeat: prefill the composer',
    'director.presets_title': 'Presets', 'director.presets_empty': 'No presets yet.', 'director.presets_hint': 'Alt+1…Alt+9 insert a preset into the message field below.',
    'director.preset_add_placeholder': 'New preset…', 'director.preset_add': '+ Add', 'director.preset_edit': 'Edit', 'director.preset_delete': 'Delete',
    'director.preset_save': 'Save', 'director.preset_cancel': 'Cancel',
    'api.error.director_manual_mode': 'The channel is in manual mode — switch to AI to start a session.', 'api.error.director_manual_required': 'Manual sending works only in Manual mode.',
    'api.error.director_manual_fenced': 'Manual sending is blocked by the emergency stop.', 'api.error.manual_sender_required': 'No sending bot selected.',
    'api.error.manual_sender_not_channel_lurker': 'This bot is not an enabled lurker in this channel.', 'api.error.manual_send_too_fast': 'A message was just sent — the repeat was rejected.',
    'api.error.manual_url_forbidden': 'Links are not allowed in the message.', 'api.error.manual_command_forbidden': '!commands are not allowed in the message.', 'api.error.manual_mention_forbidden': '@mentions are not allowed in the message.',
    'api.error.manual_code_like_forbidden': 'Code is not allowed in the message.', 'api.error.manual_secret_or_personal_data_forbidden': 'Looks like a secret or personal data — not sent.',
    'api.error.manual_text_empty': 'The message is empty.', 'api.error.manual_text_too_long': 'The message is too long.', 'api.error.manual_text_not_string': 'Invalid message text.',
    'api.error.manual_send_failed': 'Twitch did not accept the message ({reason}).', 'api.error.moderation_blocked': 'The message was blocked by outgoing moderation.', 'api.error.invalid_control_mode': 'Unknown control mode.',
    'api.error.manual_preset_limit_reached': 'No more than 9 presets (one per Alt+1…Alt+9 hotkey).', 'api.error.manual_preset_not_found': 'Preset not found.', 'api.error.manual_preset_order_invalid': 'Invalid preset order.',
});
Object.assign(LANGS.ua, {
    'director.control_mode': 'Режим керування', 'director.control_ai': '🤖 ШІ', 'director.control_manual': '✍️ Ручний',
    'director.mode_ai_hint': 'Режисер сам планує реакції (Live / Suggest / Training у конфігурації).', 'director.mode_manual_hint': 'ШІ не запускається: ви пишете текст і самі обираєте бота-відправника.',
    'director.mode_locked': 'Режим змінюється лише при зупиненій сесії.', 'director.tab_ai': 'ШІ', 'director.tab_manual': 'РУЧН',
    'director.manual_title': '✍️ Ручне надсилання', 'director.manual_unfence': 'Зняти екстрене блокування', 'director.manual_fenced': 'Екстрена зупинка: ручне надсилання заблоковано до явного зняття.',
    'director.manual_text': 'Текст повідомлення', 'director.manual_text_hint': 'Enter — надіслати, Shift+Enter — новий рядок. Посилання, !команди та @згадки заборонені.',
    'director.manual_sender': 'Бот-відправник', 'director.manual_send': 'Надіслати ⏎', 'director.manual_history': 'Останні ручні надсилання', 'director.manual_history_empty': 'Ручних надсилань поки немає.',
    'director.manual_no_senders': 'У цьому каналі немає увімкнених lurker-ботів.', 'director.manual_preview': 'Попередній перегляд',
    'director.manual_preview_sender': 'Оберіть бота-відправника.', 'director.manual_preview_text': 'Напишіть текст — тут з’явиться попередній перегляд.',
    'director.manual_sending': 'Надсилаємо…', 'director.manual_sent': 'Повідомлення надіслано.',
    'director.manual_queued': 'У черзі каналу: {n} — темп надсилання обмежений.',
    'director.manual_state_sent': 'надіслано', 'director.manual_state_blocked': 'заблоковано', 'director.manual_state_error': 'не доставлено',
    'director.manual_repeat': 'Повторити: підставити в композер',
    'director.presets_title': 'Заготовки', 'director.presets_empty': 'Заготовок поки немає.', 'director.presets_hint': 'Alt+1…Alt+9 підставляють заготовку в поле повідомлення нижче.',
    'director.preset_add_placeholder': 'Нова заготовка…', 'director.preset_add': '+ Додати', 'director.preset_edit': 'Змінити', 'director.preset_delete': 'Видалити',
    'director.preset_save': 'Зберегти', 'director.preset_cancel': 'Скасувати',
    'api.error.director_manual_mode': 'Канал у ручному режимі — перемкніть на «ШІ», щоб запустити сесію.', 'api.error.director_manual_required': 'Ручне надсилання доступне лише в режимі «Ручний».',
    'api.error.director_manual_fenced': 'Ручне надсилання заблоковано екстреною зупинкою.', 'api.error.manual_sender_required': 'Бота-відправника не обрано.',
    'api.error.manual_sender_not_channel_lurker': 'Цей бот не увімкнений як lurker у цьому каналі.', 'api.error.manual_send_too_fast': 'Повідомлення щойно пішло — повтор відхилено.',
    'api.error.manual_url_forbidden': 'Посилання в повідомленні заборонені.', 'api.error.manual_command_forbidden': '!команди в повідомленні заборонені.', 'api.error.manual_mention_forbidden': '@згадки в повідомленні заборонені.',
    'api.error.manual_code_like_forbidden': 'Код у повідомленні заборонений.', 'api.error.manual_secret_or_personal_data_forbidden': 'Схоже на секрет або особисті дані — не надіслано.',
    'api.error.manual_text_empty': 'Повідомлення порожнє.', 'api.error.manual_text_too_long': 'Повідомлення задовге.', 'api.error.manual_text_not_string': 'Некоректний текст повідомлення.',
    'api.error.manual_send_failed': 'Twitch не прийняв повідомлення ({reason}).', 'api.error.moderation_blocked': 'Повідомлення заблоковано вихідною модерацією.', 'api.error.invalid_control_mode': 'Невідомий режим керування.',
    'api.error.manual_preset_limit_reached': 'Заготовок не може бути більше 9 (за кількістю хоткеїв Alt+1…Alt+9).', 'api.error.manual_preset_not_found': 'Заготовку не знайдено.', 'api.error.manual_preset_order_invalid': 'Некоректний порядок заготовок.',
});

// ── Q40: подвкладки режима ИИ (Управление / Настройки ИИ / Обучение / Журнал) ──
const DIRECTOR_PANES = ['control', 'settings', 'training', 'log'];
function directorShowPane(pane) {
    if (!DIRECTOR_PANES.includes(pane)) pane = 'control';
    $('section-director')?.setAttribute('data-director-pane-active', pane);
    document.querySelectorAll('.director-pane-tab').forEach(tab => {
        const on = tab.dataset.pane === pane;
        tab.classList.toggle('active', on);
        tab.setAttribute('aria-selected', String(on));
    });
}

Object.assign(LANGS.ru, {
    'director.panes': 'Разделы Режиссёра', 'director.pane_control': '▶ Управление', 'director.pane_settings': '⚙️ Настройки ИИ', 'director.pane_training': '🎓 Обучение', 'director.pane_log': '🧾 Журнал',
    'director.worker_search': 'Поиск по нику…', 'director.workers_online': '+ онлайн', 'director.workers_count': 'Выбрано {selected} из {total}',
});
Object.assign(LANGS.en, {
    'director.panes': 'Director sections', 'director.pane_control': '▶ Control', 'director.pane_settings': '⚙️ AI settings', 'director.pane_training': '🎓 Training', 'director.pane_log': '🧾 Log',
    'director.worker_search': 'Search by nickname…', 'director.workers_online': '+ online', 'director.workers_count': '{selected} of {total} selected',
});
Object.assign(LANGS.ua, {
    'director.panes': 'Розділи Режисера', 'director.pane_control': '▶ Керування', 'director.pane_settings': '⚙️ Налаштування ШІ', 'director.pane_training': '🎓 Навчання', 'director.pane_log': '🧾 Журнал',
    'director.worker_search': 'Пошук за ніком…', 'director.workers_online': '+ онлайн', 'director.workers_count': 'Обрано {selected} з {total}',
});

// ── Q37: быстрый ответ из чата — одно действие «↩» на строке чат-логгера ──
// переносит оператора в ручную отправку Режиссёра нужного канала с подставленным @ником,
// без ручного переключения между экранами чата и отправки.
async function chatLogQuickReply(channel, username) {
    channel = (channel || '').trim().toLowerCase();
    username = (username || '').trim();
    if (!channel || !confirmDirty()) return;
    // Список каналов Режиссёра уже в памяти, если оператор туда заходил — лишний запрос не нужен.
    if (!_directorChannels.length) await loadDirectorSection();
    if (!_directorChannels.some(item => item.channel === channel)) {
        toast(t('director.quick_reply_no_channel', {channel}), 'error');
        return;
    }
    showSection('director');
    // Канал уже открыт — доверяем текущему состоянию панели, лишний повторный статус не нужен.
    if (channel !== _directorChannel) await directorChannelTab(channel);
    if (_directorMode(channel) !== 'manual') {
        toast(t('director.quick_reply_manual_only'), 'error');
        return;
    }
    const input = $('directorManualText');
    if (!input) return;
    const prefix = username ? `@${username} ` : '';
    if (prefix && !input.value.startsWith(prefix)) input.value = prefix + input.value;
    renderDirectorManualPreview();
    input.focus?.();
}

Object.assign(LANGS.ru, {
    'director.quick_reply_no_channel': 'Канал #{channel} недоступен для Режиссёра — быстрый ответ невозможен.',
    'director.quick_reply_manual_only': 'Быстрый ответ работает только в ручном режиме — переключите режим и повторите.',
});
Object.assign(LANGS.en, {
    'director.quick_reply_no_channel': 'Channel #{channel} is not available to Director — quick reply is not possible.',
    'director.quick_reply_manual_only': 'Quick reply only works in manual mode — switch the mode and retry.',
});
Object.assign(LANGS.ua, {
    'director.quick_reply_no_channel': 'Канал #{channel} недоступний для Режисера — швидка відповідь неможлива.',
    'director.quick_reply_manual_only': 'Швидка відповідь працює лише в ручному режимі — перемкніть режим і повторіть.',
});

// ── Director Quick-Actions (Хоткеи и Stream Deck) ──
let _directorPauseTimer = null;
let _directorPausedUntil = 0;

async function directorQuickAction(action) {
    const channel = _directorChannel || '';
    try {
        const res = await api(`/api/director/quick-action?action=${encodeURIComponent(action)}&channel=${encodeURIComponent(channel)}`, {
            method: 'POST'
        });
        if (res.ok) {
            toast(res.message || 'Готово', 'success');
            if (action === 'pause_2m' || action === 'pause') {
                _directorStartPauseCountdown(res.remaining_sec || 120);
            } else if (action === 'resume' || action === 'unpause') {
                _directorStopPauseCountdown();
            }
        } else {
            toast(res.error || res.message || 'Ошибка действия', 'error');
        }
    } catch (e) {
        toast('Ошибка: ' + (e.message || e), 'error');
    }
}

function directorTogglePause() {
    if (_directorPausedUntil > Date.now()) {
        directorQuickAction('resume');
    } else {
        directorQuickAction('pause_2m');
    }
}

function _directorStartPauseCountdown(sec) {
    _directorPausedUntil = Date.now() + sec * 1000;
    _directorUpdatePauseUI();
    if (_directorPauseTimer) clearInterval(_directorPauseTimer);
    _directorPauseTimer = setInterval(() => {
        if (_directorPausedUntil <= Date.now()) {
            _directorStopPauseCountdown();
        } else {
            _directorUpdatePauseUI();
        }
    }, 1000);
}

function _directorStopPauseCountdown() {
    _directorPausedUntil = 0;
    if (_directorPauseTimer) {
        clearInterval(_directorPauseTimer);
        _directorPauseTimer = null;
    }
    _directorUpdatePauseUI();
}

function _directorUpdatePauseUI() {
    const badge = $('directorGlobalPauseBadge');
    const secEl = $('directorGlobalPauseSec');
    const btnText = $('directorPauseBtnText');
    const remaining = Math.max(0, Math.ceil((_directorPausedUntil - Date.now()) / 1000));
    if (remaining > 0) {
        badge?.classList.remove('hidden');
        if (secEl) secEl.textContent = remaining;
        if (btnText) btnText.textContent = t('director.btn_resume');
    } else {
        badge?.classList.add('hidden');
        if (btnText) btnText.textContent = t('director.btn_pause_2m');
    }
}

function directorToggleStreamDeckInfo() {
    const el = $('directorStreamDeckInfo');
    if (el) el.classList.toggle('hidden');
}

async function directorCheckQuickStatus() {
    try {
        const res = await api('/api/director/quick-action?action=status');
        if (res.ok && res.paused && res.remaining_sec > 0) {
            _directorStartPauseCountdown(res.remaining_sec);
        } else {
            _directorStopPauseCountdown();
        }
    } catch (_) {}
}

async function directorToggleTtsMute() {
    try {
        const channel = _directorChannel || '';
        const statusRes = await api('/api/tts/mute/status' + (channel ? `?channel=${encodeURIComponent(channel)}` : ''));
        if (statusRes.muted) {
            const res = await api('/api/tts/unmute', jopts('POST', { channel }));
            toast(res.message || 'Озвучка (TTS) включена', 'success');
        } else {
            const res = await api('/api/tts/mute', jopts('POST', { channel, minutes: 5 }));
            toast(res.message || 'Озвучка (TTS) заглушена на 5 мин', 'success');
        }
    } catch (e) {
        toast('Ошибка: ' + (e.message || e), 'error');
    }
}
