// [P5-split] 13_widgets_session.js ← static/app.js, исходные строки 8196–8599; грузится после предыдущего чанка, порядок = порядку строк

// ── Widgets session: §11.3 биндинги виджетов ──
Object.assign(LANGS.ru, {
    'bindings.scope_auto_prefix': 'Правило работает у бота',
    'bindings.scope_auto_on': 'на канале',
    'bindings.scope_hint': 'Канал — из селектора в шапке «Виджетов»; бот-модератор подставляется сам.',
    'bindings.scope_empty': 'Сначала добавьте боту канал Twitch.',
    'bindings.empty': 'Правил пока нет. Используйте быстрый старт или создайте своё.',
    'bindings.when': 'КОГДА', 'bindings.then': 'ТОГДА',
    'bindings.source_label': 'Что запускает правило', 'bindings.source_chat': 'Команда в чате',
    'bindings.source_event': 'Событие Twitch', 'bindings.source_hotkey': 'Сочетание клавиш',
    'bindings.match_chat_label': 'Команда', 'bindings.match_chat_placeholder': '!death',
    'bindings.match_chat_hint': 'Сообщение должно начинаться с этой команды.',
    'bindings.match_event_label': 'Событие Twitch', 'bindings.match_event_placeholder': 'channel.subscribe',
    'bindings.match_event_hint': 'Выберите follow, subscribe, cheer или raid.',
    'bindings.match_hotkey_label': 'Сочетание клавиш', 'bindings.match_hotkey_placeholder': 'ctrl+shift+d',
    'bindings.match_hotkey_hint': 'Нажмите «Записать клавиши», затем нужное сочетание.',
    'bindings.widget_counter': 'Счётчик', 'bindings.widget_goals': 'Цели', 'bindings.widget_sub_goal': 'Sub-цель',
    'bindings.action_label': 'Что сделать',
    'bindings.widget_countdown': 'Таймер', 'bindings.widget_now_playing': 'Сейчас играет',
    'bindings.widget_lower_third': 'Нижняя плашка', 'bindings.widget_moderation': 'Модерация',
    'bindings.widget_mascot': 'Маскот', 'bindings.widget_uptime': 'Uptime (сессия стрима)',
    'bindings.widget_subathon': 'Subathon', 'bindings.widget_donation_challenge': 'Донат-челлендж',
    'bindings.widget_song_request': 'Song request', 'bindings.widget_chat_highlight': 'Chat highlight',
    'bindings.widget_chat_roulette': 'Chat roulette', 'bindings.widget_recent_events': 'Recent events',
    'bindings.widget_blur_guard': 'Blur guard',
    'bindings.widget_soundboard': 'Soundboard', 'bindings.soundboard_pick': 'Выберите трек в карточке Soundboard выше.',
    'bindings.key_counter_label': 'Имя счётчика', 'bindings.key_counter_placeholder': 'death',
    'bindings.key_counter_hint': 'Например death, wins или streak.',
    'bindings.key_goal_label': 'ID цели', 'bindings.key_goal_placeholder': '1',
    'bindings.key_goal_hint': 'ID показан у цели в разделе управления выше.',
    'bindings.value_label': 'Значение', 'bindings.value_placeholder': '1',
    'bindings.value_hint': 'Оставьте пустым для стандартного значения.',
    'bindings.role_label': 'Кто может запустить', 'bindings.role_mod': 'Стример и модераторы',
    'bindings.role_streamer': 'Только стример', 'bindings.role_any': 'Все зрители',
    'bindings.add': 'Создать правило', 'bindings.open_builder': '🔗 Настроить правило',
    'bindings.active': 'Включено', 'bindings.disabled': 'Выключено',
    'bindings.delete': 'Удалить правило', 'bindings.condition': 'Условие', 'bindings.result': 'Действие',
    'bindings.rules_section': '⚡ Правила', 'bindings.press_keys': 'Нажать сочетание',
});
Object.assign(LANGS.en, {
    'bindings.scope_auto_prefix': 'The rule runs as bot',
    'bindings.scope_auto_on': 'on channel',
    'bindings.scope_hint': 'The channel comes from the header selector; the moderator bot is picked automatically.',
    'bindings.scope_empty': 'Add a Twitch channel to the bot first.',
    'bindings.empty': 'No rules yet. Use quick start or create your own.',
    'bindings.when': 'WHEN', 'bindings.then': 'THEN',
    'bindings.source_label': 'What starts the rule', 'bindings.source_chat': 'Chat command',
    'bindings.source_event': 'Twitch event', 'bindings.source_hotkey': 'Hotkey',
    'bindings.match_chat_label': 'Command', 'bindings.match_chat_placeholder': '!death',
    'bindings.match_chat_hint': 'The message must start with this command.',
    'bindings.match_event_label': 'Twitch event', 'bindings.match_event_placeholder': 'channel.subscribe',
    'bindings.match_event_hint': 'Choose follow, subscribe, cheer, or raid.',
    'bindings.match_hotkey_label': 'Hotkey', 'bindings.match_hotkey_placeholder': 'ctrl+shift+d',
    'bindings.match_hotkey_hint': 'Press “Record keys”, then the desired combination.',
    'bindings.widget_counter': 'Counter', 'bindings.widget_goals': 'Goals', 'bindings.widget_sub_goal': 'Sub goal',
    'bindings.action_label': 'What to do',
    'bindings.widget_countdown': 'Timer', 'bindings.widget_now_playing': 'Now playing',
    'bindings.widget_lower_third': 'Lower third', 'bindings.widget_moderation': 'Moderation',
    'bindings.widget_mascot': 'Mascot', 'bindings.widget_uptime': 'Uptime (stream session)',
    'bindings.widget_subathon': 'Subathon', 'bindings.widget_donation_challenge': 'Donation challenge',
    'bindings.widget_song_request': 'Song request', 'bindings.widget_chat_highlight': 'Chat highlight',
    'bindings.widget_chat_roulette': 'Chat roulette', 'bindings.widget_recent_events': 'Recent events',
    'bindings.widget_blur_guard': 'Blur guard',
    'bindings.widget_soundboard': 'Soundboard', 'bindings.soundboard_pick': 'Select a track in the Soundboard card above.',
    'bindings.key_counter_label': 'Counter name', 'bindings.key_counter_placeholder': 'death',
    'bindings.key_counter_hint': 'For example death, wins, or streak.',
    'bindings.key_goal_label': 'Goal ID', 'bindings.key_goal_placeholder': '1',
    'bindings.key_goal_hint': 'The ID is shown next to the goal in the controls above.',
    'bindings.value_label': 'Value', 'bindings.value_placeholder': '1',
    'bindings.value_hint': 'Leave blank to use the default value.',
    'bindings.role_label': 'Who can start it', 'bindings.role_mod': 'Streamer and moderators',
    'bindings.role_streamer': 'Streamer only', 'bindings.role_any': 'All viewers',
    'bindings.add': 'Create rule', 'bindings.open_builder': '🔗 Configure rule',
    'bindings.active': 'Enabled', 'bindings.disabled': 'Disabled',
    'bindings.delete': 'Delete rule', 'bindings.condition': 'Condition', 'bindings.result': 'Action',
    'bindings.rules_section': '⚡ Rules', 'bindings.press_keys': 'Press keys',
});
Object.assign(LANGS.ua, {
    'bindings.scope_auto_prefix': 'Правило працює у бота',
    'bindings.scope_auto_on': 'на каналі',
    'bindings.scope_hint': 'Канал — із селектора у шапці «Віджетів»; бота-модератора підставлено автоматично.',
    'bindings.scope_empty': 'Спочатку додайте боту канал Twitch.',
    'bindings.empty': 'Правил поки немає. Скористайтеся швидким стартом або створіть власне.',
    'bindings.when': 'КОЛИ', 'bindings.then': 'ТОДІ',
    'bindings.source_label': 'Що запускає правило', 'bindings.source_chat': 'Команда в чаті',
    'bindings.source_event': 'Подія Twitch', 'bindings.source_hotkey': 'Сполучення клавіш',
    'bindings.match_chat_label': 'Команда', 'bindings.match_chat_placeholder': '!death',
    'bindings.match_chat_hint': 'Повідомлення має починатися з цієї команди.',
    'bindings.match_event_label': 'Подія Twitch', 'bindings.match_event_placeholder': 'channel.subscribe',
    'bindings.match_event_hint': 'Оберіть follow, subscribe, cheer або raid.',
    'bindings.match_hotkey_label': 'Сполучення клавіш', 'bindings.match_hotkey_placeholder': 'ctrl+shift+d',
    'bindings.match_hotkey_hint': 'Натисніть «Записати клавіші», потім потрібне сполучення.',
    'bindings.widget_counter': 'Лічильник', 'bindings.widget_goals': 'Цілі', 'bindings.widget_sub_goal': 'Sub-ціль',
    'bindings.action_label': 'Що зробити',
    'bindings.widget_countdown': 'Таймер', 'bindings.widget_now_playing': 'Зараз грає',
    'bindings.widget_lower_third': 'Нижня плашка', 'bindings.widget_moderation': 'Модерація',
    'bindings.widget_mascot': 'Маскот', 'bindings.widget_uptime': 'Uptime (сесія стріму)',
    'bindings.widget_subathon': 'Subathon', 'bindings.widget_donation_challenge': 'Донат-челендж',
    'bindings.widget_song_request': 'Song request', 'bindings.widget_chat_highlight': 'Chat highlight',
    'bindings.widget_chat_roulette': 'Chat roulette', 'bindings.widget_recent_events': 'Recent events',
    'bindings.widget_blur_guard': 'Blur guard',
    'bindings.widget_soundboard': 'Soundboard', 'bindings.soundboard_pick': 'Оберіть трек у картці Soundboard вище.',
    'bindings.key_counter_label': 'Назва лічильника', 'bindings.key_counter_placeholder': 'death',
    'bindings.key_counter_hint': 'Наприклад death, wins або streak.',
    'bindings.key_goal_label': 'ID цілі', 'bindings.key_goal_placeholder': '1',
    'bindings.key_goal_hint': 'ID показано біля цілі в розділі керування вище.',
    'bindings.value_label': 'Значення', 'bindings.value_placeholder': '1',
    'bindings.value_hint': 'Залиште порожнім для стандартного значення.',
    'bindings.role_label': 'Хто може запустити', 'bindings.role_mod': 'Стример і модератори',
    'bindings.role_streamer': 'Лише стример', 'bindings.role_any': 'Усі глядачі',
    'bindings.add': 'Створити правило', 'bindings.open_builder': '🔗 Налаштувати правило',
    'bindings.active': 'Увімкнено', 'bindings.disabled': 'Вимкнено',
    'bindings.delete': 'Видалити правило', 'bindings.condition': 'Умова', 'bindings.result': 'Дія',
    'bindings.rules_section': '⚡ Правила', 'bindings.press_keys': 'Натиснути сполучення',
});

let WA_BINDING_CONTRACT = null;
function waBindingWidgetContract(widget) {
    return WA_BINDING_CONTRACT?.widgets?.[widget] || null;
}
function waBindingActionContract(widget, action) {
    const contract = waBindingWidgetContract(widget);
    if (String(action || '').startsWith(contract?.dynamic_action?.prefix || '\0')) {
        return contract.dynamic_action;
    }
    return contract?.actions?.[action] || null;
}
function waBindingActionLabel(action, widget = '') {
    const key = waBindingActionContract(widget, action)?.label;
    return key ? t(key) : action;
}
function waBindingContractLabel(group, value) {
    return t(WA_BINDING_CONTRACT?.[group]?.[value]?.label || value);
}
async function waBindingContractLoad() {
    WA_BINDING_CONTRACT = await wapi('/api/widgets/binding-contract');
    const events = $('waBindEventOptions');
    if (events) events.innerHTML = (WA_BINDING_CONTRACT?.sources?.eventsub?.matches || [])
        .map(value => `<option value="${esc(value)}"></option>`).join('');
    waRulesRenderAll(); // Q27c: контракт приехал — можно строить/синкать inline-формы карточек
}

function waFilterWidgetInventory(value) {
    const query = String(value || '').trim().toLowerCase();
    let visible = 0;
    document.querySelectorAll('#canonicalWidgetInventory .widget-guide-card').forEach(card => {
        const show = !query || (card.dataset.widgetSearch || '').toLowerCase().includes(query);
        card.classList.toggle('hidden', !show);
        if (show) visible += 1;
    });
    $('widgetInventoryEmpty')?.classList.toggle('hidden', visible !== 0);
}

// Q11a: скоуп правил — общий скоуп «Виджетов» (селектор канала в шапке, Q10a);
// бот-модератор канала подставляется сам. Q27c: общая карточка билдера удалена —
// авто-строку «у бота X на канале #Y» показывает каждая секция правил (waRulesAutoLine).
function waBindingScope() {
    const raw = waChannelScopeStored();
    if (!raw) return {};
    const sep = String(raw).indexOf(':');
    const account_id = parseInt(sep >= 0 ? String(raw).slice(0, sep) : '', 10) || 0;
    const channel = (sep >= 0 ? String(raw).slice(sep + 1) : '').trim().toLowerCase().replace(/^#+/, '');
    if (!account_id || !channel) return {};
    return { account_id, channel };
}

async function waBindingScopeChange() {
    waDonationBridgeHide();
    await waBindingsLoad();
    await waBrandPaletteLoad(); // Q28: палитра нового канала
    waWidgetScopeSelectsSync();
    await Promise.allSettled([
        waLoadGoals(), waLoadSubGoal(), waLoadNp(), waLoadCd(),
        waDonationChallengesLoad(), waDonationIntLoad(), loadSubathonCard(), waLoadSr(), wa2LoadAll(),
    ]);
    waRefreshScopedWidgetPreviews();
}

// ── Пер-виджетный канал: селектор на карточке каждого виджета ──
// По умолчанию «как в общем выборе» (биндеры); выбранный на карточке канал
// хранится в localStorage и действует на превью, OBS-URL и настройки этого
// виджета (всё идёт через waWidgetStateUrl → override по family).

async function waWidgetScopePairs() {
    // Пары (бот, канал) по всем включённым ботам — кэш на сессию.
    if (window._waWidgetScopePairs) return window._waWidgetScopePairs;
    let accounts = window._waAccountsCache;
    if (!accounts) {
        const response = await api('/api/accounts');
        accounts = Array.isArray(response) ? response : (response.accounts || []);
        window._waAccountsCache = accounts;
    }
    const pairs = [];
    for (const item of accounts) {
        if (item.enabled === 0) continue;
        let channels = [];
        try {
            const response = await api(`/api/accounts/${item.id}/channels`);
            channels = Array.isArray(response) ? response : (response.channels || []);
        } catch (e) { continue; }
        channels.filter(ch => ch.enabled !== 0).forEach(ch => {
            const value = (ch.channel_name || '').trim().toLowerCase().replace(/^#+/, '');
            if (value) pairs.push({ account_id: item.id, nickname: item.nickname || `#${item.id}`, channel: value });
        });
    }
    window._waWidgetScopePairs = pairs;
    return pairs;
}

function waWidgetScopeSelectsSync() {
    document.querySelectorAll('iframe.widget-preview').forEach(frame => {
        const base = frame.dataset.scopeBase || frame.getAttribute('src') || '';
        const family = waWidgetFamily(base);
        if (!family || !WA_SCOPED_WIDGET_PATHS.has('/widget/' + family)) return;
        const toolbar = frame.parentElement?.querySelector('.widget-preview-toolbar')
            || frame.closest('.card')?.querySelector('.widget-preview-toolbar');
        if (!toolbar || toolbar.querySelector('.widget-scope-select')) return;
        const sel = document.createElement('select');
        sel.className = 'input widget-scope-select';
        sel.style.maxWidth = '190px';
        sel.dataset.scopeFamily = family;
        sel.setAttribute('aria-label', t('widgets.scope_select'));
        sel.title = t('widgets.scope_select_title');
        sel.innerHTML = `<option value="">${esc(t('widgets.scope_global'))}</option>`;
        sel.onchange = () => {
            const overrides = waWidgetScopeOverrides();
            if (sel.value) overrides[family] = sel.value; else delete overrides[family];
            try { localStorage.setItem('widgetScopeOverrides', JSON.stringify(overrides)); } catch (e) {}
            waBindingScopeChange(false); // перезагрузить превью/настройки с новым скоупом
        };
        toolbar.prepend(sel);
        waWidgetScopeSelectFill(sel);
    });
}

async function waWidgetScopeSelectFill(sel) {
    const family = sel.dataset.scopeFamily;
    const overrides = waWidgetScopeOverrides();
    const current = overrides[family] || '';
    const pairs = await waWidgetScopePairs();
    // не затираем селекты не-того семейства (двойной прогон по карточкам)
    if (sel.dataset.scopeFamily !== family || !sel.isConnected) return;
    sel.innerHTML = `<option value="">${esc(t('widgets.scope_global'))}</option>` +
        pairs.map(p =>
            `<option value="${p.account_id}:${esc(p.channel)}">${esc(p.nickname)} · #${esc(p.channel)}</option>`
        ).join('');
    sel.value = pairs.some(p => `${p.account_id}:${p.channel}` === current) ? current : '';
    if (!sel.value && current) {
        // сохранённый бот/канал больше не существует — забываем override
        delete overrides[family];
        try { localStorage.setItem('widgetScopeOverrides', JSON.stringify(overrides)); } catch (e) {}
    }
}


async function waBindingsLoad() {
    // Q27c: общий список правил удалён — загрузка только наполняет кэш
    // (window._waBindingsCache + хоткеи) и перерисовывает секции карточек.
    try {
        const scope = waBindingScope();
        if (!scope.account_id || !scope.channel) {
            window._waBindingsCache = [];
            window._hotkeyCombos = [];
        } else {
            const query = new URLSearchParams(scope).toString();
            const data = await wapi(`/api/widgets/bindings?${query}`);
            window._waBindingsCache = data.items || [];
            // §3.1: кэш хоткеев для глобального keydown-матчера панели
            window._hotkeyCombos = (data.items || [])
                .filter(b => b.enabled && b.source === 'hotkey')
                .map(b => (b.match || '').toLowerCase());
        }
    } catch (e) { _waHint(e); }
    waRulesRenderAll();
}

function waWidgetBindingAdd(slug, prefillAction) {
    const section = document.querySelector(`details.wa-widget-rules[data-rules-slug="${slug}"]`);
    if (!section || !waBindingWidgetContract(slug)) return;
    waRulesEnsure(section);
    section.open = true;
    if (prefillAction) {
        const sel = section.querySelector('.wa-rules-action');
        if (sel) {
            sel.innerHTML = `<option value="${esc(prefillAction)}">${esc(waBindingActionLabel(prefillAction, slug))}</option>`;
            sel.value = prefillAction;
        }
    }
    waRulesFormSync(section);
    if (typeof section.scrollIntoView === 'function') section.scrollIntoView({behavior: 'smooth', block: 'center'});
    setTimeout(() => section.querySelector('.wa-rules-match')?.focus(), 350);
}

// ── Q27b (DEC-OWNER-017): секция «⚡ Правила» живёт в карточке виджета ──
// Виджет уже выбран (data-rules-slug) — селекта виджета в форме нет; inline-форма
// КОГДА → ТОГДА строится один раз на карточку, правила берутся из общего кэша
// window._waBindingsCache (его наполняет waBindingsLoad).
function waRulesEnsure(section) {
    if (!section || section.dataset.rulesBuilt) return section;
    const body = section.querySelector('.wa-widget-rules-body');
    if (!body) return section;
    body.innerHTML = `
        <p class="text-xs text-muted wa-rules-autoline" aria-live="polite"></p>
        <div class="wa-rules-list"></div>
        <div class="wa-rules-form">
            <div class="wa-rules-when">
                <div class="wa-binding-flow-label">${esc(t('bindings.when'))}</div>
                <label class="text-xs"><span>${esc(t('bindings.source_label'))}</span>
                    <select class="input wa-rules-source">
                        <option value="chat_command">${esc(t('bindings.source_chat'))}</option>
                        <option value="eventsub">${esc(t('bindings.source_event'))}</option>
                        <option value="hotkey">${esc(t('bindings.source_hotkey'))}</option>
                    </select>
                </label>
                <label class="text-xs"><span class="wa-rules-match-label"></span>
                    <span class="flex gap-2">
                        <input type="text" class="input wa-rules-match" list="waBindEventOptions">
                        <button type="button" class="btn btn-secondary btn-sm wa-rules-hotkey hidden">⌨ ${esc(t('bindings.press_keys'))}</button>
                    </span>
                    <small class="text-muted wa-rules-match-hint"></small>
                </label>
            </div>
            <div class="wa-rules-then">
                <div class="wa-binding-flow-label">${esc(t('bindings.then'))}</div>
                <label class="text-xs"><span>${esc(t('bindings.action_label'))}</span>
                    <select class="input wa-rules-action"></select>
                </label>
                <label class="text-xs wa-rules-key-field hidden"><span class="wa-rules-key-label"></span>
                    <input type="text" class="input wa-rules-key">
                    <small class="text-muted wa-rules-key-hint"></small>
                </label>
                <label class="text-xs wa-rules-value-field hidden"><span>${esc(t('bindings.value_label'))}</span>
                    <input type="text" class="input wa-rules-value">
                    <small class="text-muted">${esc(t('bindings.value_hint'))}</small>
                </label>
                <label class="text-xs"><span>${esc(t('bindings.role_label'))}</span>
                    <select class="input wa-rules-role"></select>
                </label>
            </div>
            <button type="button" class="btn btn-primary wa-rules-add">${esc(t('bindings.add'))}</button>
        </div>`;
    const source = body.querySelector('.wa-rules-source');
    const hotkeyBtn = body.querySelector('.wa-rules-hotkey');
    const addBtn = body.querySelector('.wa-rules-add');
    if (source) source.onchange = () => waRulesFormSync(section);
    if (hotkeyBtn) hotkeyBtn.onclick = () => waRulesHotkeyCapture(hotkeyBtn);
    if (addBtn) addBtn.onclick = () => waRulesAdd(section);
    section.dataset.rulesBuilt = '1';
    return section;
}

function waRulesFormSync(section) {
    const slug = section?.dataset.rulesSlug || '';
    const body = section?.querySelector('.wa-widget-rules-body');
    if (!body || !WA_BINDING_CONTRACT) return;
    const contract = waBindingWidgetContract(slug) || {};
    const sourceSel = body.querySelector('.wa-rules-source');
    const actionSel = body.querySelector('.wa-rules-action');
    const roleSel = body.querySelector('.wa-rules-role');
    const match = body.querySelector('.wa-rules-match');
    const addBtn = body.querySelector('.wa-rules-add');
    const source = sourceSel?.value || 'chat_command';
    // действия виджета; value уже выставлен (soundboard play_track:<id>) — не затираем
    if (actionSel && !actionSel.value) {
        actionSel.innerHTML = Object.entries(contract.actions || {}).map(([action, spec]) =>
            `<option value="${esc(action)}">${esc(t(spec.label || action))}</option>`).join('');
    }
    const allowedSources = contract.sources || Object.keys(WA_BINDING_CONTRACT.sources || {});
    [...(sourceSel?.options || [])].forEach(option => { option.disabled = !allowedSources.includes(option.value); });
    if (sourceSel && !allowedSources.includes(sourceSel.value)) sourceSel.value = allowedSources[0] || '';
    const matchKey = source === 'eventsub' ? 'event' : source === 'hotkey' ? 'hotkey' : 'chat';
    const matchLabel = body.querySelector('.wa-rules-match-label');
    const matchHint = body.querySelector('.wa-rules-match-hint');
    if (matchLabel) matchLabel.textContent = t(`bindings.match_${matchKey}_label`);
    if (matchHint) matchHint.textContent = t(`bindings.match_${matchKey}_hint`);
    if (match) match.placeholder = t(`bindings.match_${matchKey}_placeholder`);
    body.querySelector('.wa-rules-hotkey')?.classList.toggle('hidden', source !== 'hotkey');
    if (roleSel) {
        const allowedRoles = WA_BINDING_CONTRACT?.sources?.[source]?.roles || [];
        roleSel.innerHTML = Object.entries(WA_BINDING_CONTRACT.roles || {}).map(([value, spec]) =>
            `<option value="${esc(value)}"${allowedRoles.includes(value) ? '' : ' disabled'}>${esc(t(spec.label || value))}</option>`).join('');
        if (!allowedRoles.includes(roleSel.value)) roleSel.value = allowedRoles[0] || '';
        roleSel.disabled = slug === 'moderation' || source !== 'chat_command';
    }
    const needsKey = !!contract.key;
    body.querySelector('.wa-rules-key-field')?.classList.toggle('hidden', !needsKey);
    const keyKind = contract.key?.kind || 'counter';
    const keyLabel = body.querySelector('.wa-rules-key-label');
    const keyHint = body.querySelector('.wa-rules-key-hint');
    const keyInput = body.querySelector('.wa-rules-key');
    if (keyLabel) keyLabel.textContent = t(`bindings.key_${keyKind}_label`);
    if (keyHint) keyHint.textContent = t(`bindings.key_${keyKind}_hint`);
    if (keyInput) keyInput.placeholder = t(`bindings.key_${keyKind}_placeholder`);
    const action = actionSel?.value || '';
    const actionContract = waBindingActionContract(slug, action) || {};
    body.querySelector('.wa-rules-value-field')?.classList.toggle('hidden', !actionContract.value || actionContract.value.type === 'none');
    if (addBtn) {
        addBtn.disabled = !action;
        addBtn.title = slug === 'soundboard' ? t('bindings.soundboard_pick') : '';
    }
}

// Хоткей пишется в форму своей карточки (кнопка «⌨ Нажать сочетание»).
function waRulesHotkeyCapture(btn) {
    const section = btn?.closest?.('details.wa-widget-rules');
    const match = section?.querySelector('.wa-rules-match');
    const sourceSel = section?.querySelector('.wa-rules-source');
    if (!match || !sourceSel) return;
    sourceSel.value = 'hotkey';
    waRulesFormSync(section);
    window._hotkeyCapturing = true;
    btn.textContent = t('bindings.pressing');
    const done = (e) => {
        e.preventDefault();
        e.stopPropagation();
        document.removeEventListener('keydown', done, true);
        window._hotkeyCapturing = false;
        btn.textContent = `⌨ ${t('bindings.press_keys')}`;
        const combo = typeof waHotkeyComboFromEvent === 'function' ? waHotkeyComboFromEvent(e) : '';
        if (combo) match.value = combo;
    };
    document.addEventListener('keydown', done, true);
}

async function waRulesAdd(section) {
    const slug = section?.dataset.rulesSlug || '';
    const body = section?.querySelector('.wa-widget-rules-body');
    if (!slug || !body) return;
    const val = cls => body.querySelector(cls)?.value || '';
    try {
        await wapi('/api/widgets/bindings', 'POST', {
            ...waBindingScope(),
            source: val('.wa-rules-source'),
            match: val('.wa-rules-match'),
            widget: slug,
            widget_key: val('.wa-rules-key'),
            action: val('.wa-rules-action'),
            value: val('.wa-rules-value'),
            role: val('.wa-rules-role'),
        });
        const match = body.querySelector('.wa-rules-match');
        const value = body.querySelector('.wa-rules-value');
        if (match) match.value = '';
        if (value) value.value = '';
        await waBindingsLoad();
    } catch (e) { _waHint(e); }
}

function waRulesRenderList(section) {
    const slug = section?.dataset.rulesSlug || '';
    const list = section?.querySelector('.wa-rules-list');
    if (!slug || !list) return;
    const items = (window._waBindingsCache || []).filter(b => b.widget === slug);
    list.innerHTML = items.map(b => {
        const rawAction = String(b.action || '');
        const action = rawAction.startsWith('play_track:') ? 'play_track' : rawAction;
        const trackId = rawAction.startsWith('play_track:') ? rawAction.split(':', 2)[1] : '';
        const key = b.widget_key ? `<code>${esc(b.widget_key)}</code>` : '';
        const value = b.value ? `<code>${esc(b.value)}</code>` : '';
        const track = trackId ? `<code>#${esc(trackId)}</code>` : '';
        return `<article class="wa-binding-item ${b.enabled ? '' : 'is-disabled'}">
            <div class="wa-binding-item-status">
                <div class="toggle ${b.enabled ? 'active' : ''}" role="switch" aria-label="${esc(b.enabled ? t('bindings.active') : t('bindings.disabled'))}" aria-checked="${!!b.enabled}" tabindex="0" onclick="uiToggle(this, v => waBindingToggle(${b.id}, v))"></div>
                <span>${esc(b.enabled ? t('bindings.active') : t('bindings.disabled'))}</span>
            </div>
            <div class="wa-binding-sentence">
                <div class="wa-binding-clause"><small>${esc(t('bindings.condition'))}</small><strong>${esc(waBindingContractLabel('sources', b.source))}</strong><code>${esc(b.match || '?')}</code></div>
                <span class="wa-binding-arrow">→</span>
                <div class="wa-binding-clause"><small>${esc(t('bindings.result'))}</small><span>${esc(waBindingActionLabel(action, slug))} ${track} ${key} ${value}</span></div>
            </div>
            <button class="btn btn-sm btn-danger" onclick="waBindingDelete(${b.id})" title="${esc(t('bindings.delete'))}" aria-label="${esc(t('bindings.delete'))}">✕</button>
        </article>`;
    }).join('') || `<div class="wa-binding-empty text-muted text-sm">${esc(t('bindings.empty'))}</div>`;
}

function waRulesAutoLine(section) {
    const line = section?.querySelector('.wa-rules-autoline');
    if (!line) return;
    const scope = waBindingScope();
    if (!scope.account_id || !scope.channel) { line.textContent = t('bindings.scope_empty'); return; }
    const bots = (window._waChannelScopeBots || {})[scope.channel] || [];
    const current = bots.find(b => b.account_id === scope.account_id) || {};
    const nick = current.nickname || `#${scope.account_id}`;
    line.textContent = `${t('bindings.scope_auto_prefix')} ${nick} ${t('bindings.scope_auto_on')} #${scope.channel}`;
}

function waRulesRenderAll() {
    document.querySelectorAll('details.wa-widget-rules[data-rules-slug]').forEach(section => {
        waRulesEnsure(section);
        waRulesAutoLine(section);
        waRulesRenderList(section);
        waRulesFormSync(section);
    });
}

async function waBindingToggle(id, enabled) {
    try { await wapi(`/api/widgets/bindings/${id}`, 'PUT', {...waBindingScope(), enabled}); await waBindingsLoad(); } catch (e) { _waHint(e); }
}
async function waBindingDelete(id) {
    try {
        const query = new URLSearchParams(waBindingScope()).toString();
        await wapi(`/api/widgets/bindings/${id}?${query}`, 'DELETE');
        await waBindingsLoad();
    } catch (e) { _waHint(e); }
}
const _loadWidgetsAdminPrev2 = loadWidgetsAdmin;
loadWidgetsAdmin = async function() {
    await _loadWidgetsAdminPrev2();
    await waBindingContractLoad(); // контракт + datalist событий + waRulesRenderAll внутри
    await waBrandPaletteLoad(); // Q28: палитра канала + полоски в карточках
};

// ── Q28 (DEC-OWNER-017): брендовая палитра канала + пипетка + готовые темы ──
// Палитра per-канал (app/widget_brand_routes.py); цвета применяются к превью
// карточки одним кликом или пипеткой. Дизайн-виджетам (tts/chat-reader) цвет
// сохраняется в widget_design_* (через waDesignSave), остальным — живое
// перекрашивание превью через URL-параметры accent/bg (appearance.js).
const WA_CARD_THEMES = {
    neon: { accent: '#d946ef', bg: '#090014', opacity: 0.85 },
    minimal: { accent: '#2563eb', bg: '#f8fafc', opacity: 0.95 },
    gradient: { accent: '#a78bfa', bg: '#111827', opacity: 0.9 },
    dark: { accent: '', bg: '', opacity: '' }, // сброс к теме виджета
};

function waBrandPalette() { return window._waBrandPalette || null; }

// i18n Q28: палитра, пипетка, готовые темы (RU/EN/UA)
Object.assign(LANGS.ru, {
    'widgets.brand_palette': '🎨 Брендовая палитра канала',
    'widgets.brand_palette_hint': 'Свои цвета канала: они показываются в карточках виджетов одним кликом. Без своей палитры — стартовый набор.',
    'widgets.brand_color': 'Цвет палитры', 'widgets.brand_apply': 'Накрасить превью',
    'widgets.pick_color': 'Свой цвет', 'widgets.look_applied': 'Цвет применён к превью и URL',
    'widgets.theme_neon': 'Неон', 'widgets.theme_minimal': 'Минимал',
    'widgets.theme_gradient': 'Градиент', 'widgets.theme_dark': 'Сброс',
});
Object.assign(LANGS.en, {
    'widgets.brand_palette': '🎨 Channel brand palette',
    'widgets.brand_palette_hint': 'Custom channel colors: shown in widget cards, one click to apply. Without a custom palette a starter set is used.',
    'widgets.brand_color': 'Palette color', 'widgets.brand_apply': 'Recolor preview',
    'widgets.pick_color': 'Custom color', 'widgets.look_applied': 'Color applied to preview and URL',
    'widgets.theme_neon': 'Neon', 'widgets.theme_minimal': 'Minimal',
    'widgets.theme_gradient': 'Gradient', 'widgets.theme_dark': 'Reset',
});
Object.assign(LANGS.ua, {
    'widgets.brand_palette': '🎨 Брендова палітра каналу',
    'widgets.brand_palette_hint': 'Власні кольори каналу: показуються в картках віджетів одним кліком. Без власної палітри — стартовий набір.',
    'widgets.brand_color': 'Колір палітри', 'widgets.brand_apply': 'Фарбувати прев’ю',
    'widgets.pick_color': 'Свій колір', 'widgets.look_applied': 'Колір застосовано до прев’ю та URL',
    'widgets.theme_neon': 'Неон', 'widgets.theme_minimal': 'Мінімал',
    'widgets.theme_gradient': 'Градієнт', 'widgets.theme_dark': 'Скид',
});

async function waBrandPaletteLoad() {
    const scope = waBindingScope();
    try {
        if (!scope.channel) {
            window._waBrandPalette = null;
        } else {
            const data = await wapi(`/api/widgets/brand-palette?channel=${encodeURIComponent(scope.channel)}`);
            window._waBrandPalette = data.colors || null;
        }
    } catch (e) { _waHint(e); }
    waBrandPaletteEditorRender();
    waCardPalettesRender();
}

function waBrandPaletteEditorRender() {
    const box = $('waBrandPaletteEditor');
    if (!box) return;
    const colors = waBrandPalette() || ['#a78bfa', '#22d3ee', '#22c55e', '#f97316', '#f87171', '#ffd700'];
    box.innerHTML = colors.map((c, i) =>
        `<input type="color" class="wa-brand-swatch" value="${esc(c)}" data-brand-index="${i}" aria-label="${esc(t('widgets.brand_color'))} ${i + 1}">`
    ).join('') + `<button type="button" class="btn btn-primary btn-sm" onclick="waBrandPaletteSave()" aria-label="${esc(t('btn.save'))}">💾</button>`;
}

async function waBrandPaletteSave() {
    const scope = waBindingScope();
    if (!scope.channel) { _waHint(new Error(t('bindings.scope_empty'))); return; }
    const colors = [...document.querySelectorAll('#waBrandPaletteEditor .wa-brand-swatch')].map(el => el.value);
    try {
        const data = await wapi('/api/widgets/brand-palette', 'PUT', { channel: scope.channel, colors });
        window._waBrandPalette = data.colors || colors;
        waCardPalettesRender();
        toast(t('msg.saved'), 'success');
    } catch (e) { _waHint(e); }
}

function waCardPalettesRender() {
    const colors = waBrandPalette() || ['#a78bfa', '#22d3ee', '#22c55e', '#f97316', '#f87171', '#ffd700'];
    document.querySelectorAll('.wa-card-palette[data-palette-card]').forEach(strip => {
        const slug = strip.dataset.paletteCard;
        const route = strip.dataset.paletteRoute || `/widget/${slug}`;
        const swatches = colors.slice(0, 6).map(c =>
            `<button type="button" class="wa-card-swatch" style="background:${esc(c)}" title="${esc(c)}" aria-label="${esc(t('widgets.brand_apply'))} ${esc(c)}" onclick="waCardApplyAccent('${esc(slug)}', '${esc(route)}', '${esc(c)}')"></button>`
        ).join('');
        const themes = Object.keys(WA_CARD_THEMES).map(name =>
            `<button type="button" class="btn btn-sm btn-secondary wa-card-theme" onclick="waCardApplyTheme('${esc(slug)}', '${esc(route)}', '${name}')">${esc(t(`widgets.theme_${name}`))}</button>`
        ).join('');
        strip.innerHTML = `<span class="wa-card-swatches">${swatches}` +
            `<input type="color" class="wa-card-picker" value="#a78bfa" aria-label="${esc(t('widgets.pick_color'))}" title="${esc(t('widgets.pick_color'))}" onchange="waCardApplyAccent('${esc(slug)}', '${esc(route)}', this.value)"></span>` +
            `<span class="wa-card-themes">${themes}</span>`;
    });
}

function waCardApplyAccent(slug, route, color) {
    void route;
    waCardApplyLook(slug, { accent: color });
}

function waCardApplyTheme(slug, route, name) {
    const theme = WA_CARD_THEMES[name] || {};
    waCardApplyLook(slug, { accent: theme.accent, bg: theme.bg, opacity: theme.opacity });
}

function waCardApplyLook(slug, look) {
    const strip = document.querySelector(`[data-palette-card="${slug}"]`);
    const card = strip?.closest('.card');
    if (!card) return;
    // дизайн-виджеты: цвет через дизайн-форму карточки (сохраняется и в OBS URL)
    const designWidget = card.dataset.designWidget || '';
    if (designWidget && look.accent) {
        const accentInput = card.querySelector('[data-design-field="accent"]');
        const bgInput = card.querySelector('[data-design-field="bg"]');
        if (accentInput) accentInput.value = look.accent.toLowerCase();
        if (bgInput && look.bg) bgInput.value = look.bg.toLowerCase();
        if (typeof waDesignSave === 'function') waDesignSave(designWidget);
        return;
    }
    const applyToUrl = raw => {
        const url = new URL(raw, location.origin);
        if (look.accent) url.searchParams.set('accent', look.accent); else url.searchParams.delete('accent');
        if (look.bg) url.searchParams.set('bg', look.bg); else url.searchParams.delete('bg');
        if (look.opacity) url.searchParams.set('opacity', String(look.opacity));
        return url.pathname + url.search;
    };
    // остальные: живое перекрашивание превью (appearance.js читает accent/bg)
    const frame = card.querySelector('iframe.widget-preview');
    if (frame) frame.src = applyToUrl(frame.getAttribute('src') || '/');
    // честный OBS URL в карточке — с выбранными accent/bg/opacity
    const urlInput = card.querySelector('.widget-url-form input');
    if (urlInput) urlInput.value = applyToUrl(urlInput.value);
    if (look.accent || look.bg) toast(t('widgets.look_applied'), 'success');
}

// ── Widgets session: §11.4 донат-интеграции (мультиплатформенные) ──
Object.assign(LANGS.ru, {
    'donation.title': '💳 Донат-интеграции', 'donation.refresh': 'Обновить статусы',
    'donation.description': 'Реальные донаты выбранного канала попадают только в его топ, события, челленджи и subathon.',
    'donation.multiple': 'DonatePay, DonateX и DonationAlerts можно включать одновременно.',
    'donation.example': '👀 Например: донат «Nick · 100 · го рекорд» обновит виджеты только выбранного канала.',
    'donation.bridge.title': 'Локальный bridge',
    'donation.bridge.hint': 'Для Streamer.bot и тестовых событий: localhost POST с exact account_id, channel, event_id и этим токеном.',
    'donation.goal.id': 'Goal ID из ссылки на сбор', 'donation.goal.sync': 'Синхронизировать',
    'donation.provider.polling': 'опрос', 'donation.provider.websocket': 'WebSocket',
    'donation.token.empty': 'Access token', 'donation.token.saved': 'Токен задан ({mask}) — пусто = не менять',
    'donation.save': 'Сохранить', 'donation.reconnect': 'Переподключить',
    'donation.status.idle': 'не запускался', 'donation.status.disabled': 'выключен',
    'donation.status.missing_token': 'нужен токен', 'donation.status.connecting': 'подключение',
    'donation.status.polling': 'работает', 'donation.status.connected': 'подключён',
    'donation.status.retrying': 'ошибка, повторное подключение', 'donation.last_success': 'Последний успех: {value}',
    'donation.never': 'ещё не было', 'donation.plaintext_warning': '⚠️ Access tokens хранятся локально без шифрования. Настройте TOKEN_ENCRYPTION_KEY.',
    'donation.bridge.masked': 'Токен bridge: {mask}', 'donation.bridge.missing': 'Токен bridge ещё не создан',
    'donation.bridge.reveal': 'Показать', 'donation.bridge.copy': 'Копировать',
    'donation.bridge.rotate': 'Создать / сменить токен', 'donation.bridge.enabled': 'Bridge включён',
    'donation.bridge.hidden': 'Токен скрыт', 'donation.bridge.rotated': 'Старый токен отозван',
});
Object.assign(LANGS.en, {
    'donation.title': '💳 Donation integrations', 'donation.refresh': 'Refresh statuses',
    'donation.description': 'Real donations for the selected channel update only its top, events, challenges, and subathon.',
    'donation.multiple': 'DonatePay, DonateX, and DonationAlerts can run at the same time.',
    'donation.example': '👀 Example: “Nick · 100 · new record” updates widgets for the selected channel only.',
    'donation.bridge.title': 'Local bridge',
    'donation.bridge.hint': 'For Streamer.bot and test events: localhost POST with exact account_id, channel, event_id, and this token.',
    'donation.goal.id': 'Goal ID from the fundraiser link', 'donation.goal.sync': 'Synchronize',
    'donation.provider.polling': 'polling', 'donation.provider.websocket': 'WebSocket',
    'donation.token.empty': 'Access token', 'donation.token.saved': 'Token saved ({mask}) — leave empty to keep it',
    'donation.save': 'Save', 'donation.reconnect': 'Reconnect',
    'donation.status.idle': 'not started', 'donation.status.disabled': 'disabled',
    'donation.status.missing_token': 'token required', 'donation.status.connecting': 'connecting',
    'donation.status.polling': 'running', 'donation.status.connected': 'connected',
    'donation.status.retrying': 'error, retrying', 'donation.last_success': 'Last success: {value}',
    'donation.never': 'not yet', 'donation.plaintext_warning': '⚠️ Access tokens are stored locally without encryption. Configure TOKEN_ENCRYPTION_KEY.',
    'donation.bridge.masked': 'Bridge token: {mask}', 'donation.bridge.missing': 'Bridge token has not been created yet',
    'donation.bridge.reveal': 'Reveal', 'donation.bridge.copy': 'Copy',
    'donation.bridge.rotate': 'Create / rotate token', 'donation.bridge.enabled': 'Bridge enabled',
    'donation.bridge.hidden': 'Token hidden', 'donation.bridge.rotated': 'Old token revoked',
});
Object.assign(LANGS.ua, {
    'donation.title': '💳 Донат-інтеграції', 'donation.refresh': 'Оновити статуси',
    'donation.description': 'Реальні донати вибраного каналу потрапляють лише в його топ, події, челенджі та subathon.',
    'donation.multiple': 'DonatePay, DonateX і DonationAlerts можна вмикати одночасно.',
    'donation.example': '👀 Наприклад: донат «Nick · 100 · новий рекорд» оновить віджети лише вибраного каналу.',
    'donation.bridge.title': 'Локальний bridge',
    'donation.bridge.hint': 'Для Streamer.bot і тестових подій: localhost POST з точними account_id, channel, event_id і цим токеном.',
    'donation.goal.id': 'Goal ID із посилання на збір', 'donation.goal.sync': 'Синхронізувати',
    'donation.provider.polling': 'опитування', 'donation.provider.websocket': 'WebSocket',
    'donation.token.empty': 'Access token', 'donation.token.saved': 'Токен задано ({mask}) — порожньо = не змінювати',
    'donation.save': 'Зберегти', 'donation.reconnect': 'Перепідключити',
    'donation.status.idle': 'не запускався', 'donation.status.disabled': 'вимкнено',
    'donation.status.missing_token': 'потрібен токен', 'donation.status.connecting': 'підключення',
    'donation.status.polling': 'працює', 'donation.status.connected': 'підключено',
    'donation.status.retrying': 'помилка, повторне підключення', 'donation.last_success': 'Останній успіх: {value}',
    'donation.never': 'ще не було', 'donation.plaintext_warning': '⚠️ Access tokens зберігаються локально без шифрування. Налаштуйте TOKEN_ENCRYPTION_KEY.',
    'donation.bridge.masked': 'Токен bridge: {mask}', 'donation.bridge.missing': 'Токен bridge ще не створено',
    'donation.bridge.reveal': 'Показати', 'donation.bridge.copy': 'Копіювати',
    'donation.bridge.rotate': 'Створити / змінити токен', 'donation.bridge.enabled': 'Bridge увімкнено',
    'donation.bridge.hidden': 'Токен приховано', 'donation.bridge.rotated': 'Старий токен відкликано',
});
const _WA_DON_PLATFORMS = [
    {id: 'donatepay', label: 'DonatePay', mode: 'polling'},
    {id: 'donatex', label: 'DonateX', mode: 'polling'},
    {id: 'donationalerts', label: 'DonationAlerts', mode: 'websocket'},
];
let _waDonationBridgeToken = '';
let _waDonationBridgeHideTimer = null;
function _waDonRender(items) {
    const el = $('waDonRows');
    if (!el) return;
    el.innerHTML = _WA_DON_PLATFORMS.map(p => {
        const it = (items || []).find(x => x.platform === p.id) || {};
        const st = it.status || {};
        const state = st.state || (it.enabled ? 'idle' : 'disabled');
        const placeholder = it.token_set
            ? t('donation.token.saved').replace('{mask}', it.token_hint || '***')
            : t('donation.token.empty');
        const lastSuccess = st.last_success_at
            ? new Date(st.last_success_at).toLocaleString() : t('donation.never');
        return `<div class="flex gap-2 items-center flex-wrap" style="border-top:1px solid rgba(128,128,128,0.15);padding-top:8px">
            <label class="flex items-center gap-2 text-sm" style="min-width:0">
                <div class="toggle ${it.enabled ? 'active' : ''}" id="waDonEnabled_${p.id}" role="switch" aria-checked="${!!it.enabled}" tabindex="0" onclick="uiToggle(this)"></div>
                <span>${p.label} (${esc(t('donation.provider.' + p.mode))})</span>
            </label>
            <input type="password" id="waDonToken_${p.id}" class="input" style="max-width:240px"
                   aria-label="${esc(p.label + ' ' + t('donation.token.empty'))}" placeholder="${esc(placeholder)}">
            <button class="btn btn-primary btn-sm" onclick="waDonationIntSave('${p.id}')" aria-label="${esc(t('donation.save'))}">💾</button>
            <button class="btn btn-secondary btn-sm" onclick="waDonationIntReconnect('${p.id}')">${esc(t('donation.reconnect'))}</button>
            <span class="text-xs ${st.ok ? 'text-green' : 'text-muted'}" id="waDonStatus_${p.id}">${st.ok ? '✅' : '⏳'} ${esc(t('donation.status.' + state))} · ${esc(t('donation.last_success').replace('{value}', lastSuccess))}</span>
        </div>`;
    }).join('');
}
async function waDonationIntLoad() {
    if (!$('waDonRows')) return;
    try {
        const [s, bridge] = await Promise.all([
            wstateapi('/api/widgets/donation-integration'),
            wstateapi('/api/widgets/donation-bridge'),
        ]);
        _waDonRender(s.items || []);
        $('waDonStorageWarning')?.classList.toggle('hidden', s.storage_mode !== 'local_plaintext');
        if ($('waDonBridgeEnabled')) setToggle('waDonBridgeEnabled', !!bridge.enabled);
        if ($('waDonBridgeMask')) $('waDonBridgeMask').textContent = bridge.token_set
            ? t('donation.bridge.masked').replace('{mask}', bridge.token_hint || '***')
            : t('donation.bridge.missing');
        // синхронизация сбора DonateX → челлендж
        if ($('waGoalSyncId')) {
            const g = await wstateapi('/api/widgets/donation-goal-sync');
            $('waGoalSyncId').value = g.external_goal_id || '';
            setToggle('waGoalSyncEnabled', !!g.enabled);
        }
    } catch (e) { _waHint(e); }
}
async function waGoalSyncSave() {
    try {
        await wstateapi('/api/widgets/donation-goal-sync', 'PUT', {
            external_goal_id: $('waGoalSyncId').value,
            enabled: toggleChecked('waGoalSyncEnabled'),
        });
    } catch (e) { _waHint(e); }
}
async function waDonationIntSave(platform) {
    try {
        await wstateapi('/api/widgets/donation-integration', 'PUT', {
            platform,
            enabled: toggleChecked('waDonEnabled_' + platform),
            token: $('waDonToken_' + platform).value,
        });
        $('waDonToken_' + platform).value = '';
        await waDonationIntLoad();
    } catch (e) { _waHint(e); }
}
async function waDonationIntReconnect(platform) {
    try {
        await wstateapi(`/api/widgets/donation-integration/${platform}/reconnect`, 'POST', {});
        await waDonationIntLoad();
    } catch (e) { _waHint(e); }
}
async function waDonationBridgeToggle(enabled) {
    try {
        const result = await wstateapi('/api/widgets/donation-bridge', 'PUT', {enabled});
        if (result.ok === false) throw new Error(result.error || 'bridge_token_required');
        await waDonationIntLoad();
    } catch (e) { _waHint(e); await waDonationIntLoad(); }
}
function waDonationBridgeHide() {
    _waDonationBridgeToken = '';
    if (_waDonationBridgeHideTimer) clearTimeout(_waDonationBridgeHideTimer);
    _waDonationBridgeHideTimer = null;
    if ($('waDonBridgeValue')) $('waDonBridgeValue').value = '';
    if ($('waDonBridgeSecret')) $('waDonBridgeSecret').classList.add('hidden');
    if ($('waDonBridgeMessage')) $('waDonBridgeMessage').textContent = t('donation.bridge.hidden');
}
function waDonationBridgeShow(token, messageKey) {
    waDonationBridgeHide();
    _waDonationBridgeToken = token;
    $('waDonBridgeValue').value = token;
    $('waDonBridgeSecret').classList.remove('hidden');
    $('waDonBridgeMessage').textContent = t(messageKey || 'donation.bridge.enabled');
    _waDonationBridgeHideTimer = setTimeout(waDonationBridgeHide, 30000);
}
async function waDonationBridgeReveal() {
    try {
        const result = await wstateapi('/api/widgets/donation-bridge/reveal');
        waDonationBridgeShow(result.token);
    } catch (e) { _waHint(e); }
}
async function waDonationBridgeRotate() {
    try {
        const result = await wstateapi('/api/widgets/donation-bridge/rotate', 'POST', {});
        waDonationBridgeShow(result.token, 'donation.bridge.rotated');
        await waDonationIntLoad();
    } catch (e) { _waHint(e); }
}
async function waDonationBridgeCopy() {
    if (!_waDonationBridgeToken) return;
    await navigator.clipboard.writeText(_waDonationBridgeToken);
    toast(t('toast.copied'), 'success');
}
const _loadWidgetsAdminPrev3 = loadWidgetsAdmin;
loadWidgetsAdmin = async function() {
    await _loadWidgetsAdminPrev3();
    waDonationIntLoad();
};


// ── Widgets session: §13 Blur Guard ──
async function waBgLoad() {
    if (!$('waBgEnabled')) return;
    try {
        const s = await wapi('/api/blur-guard');
        setToggle('waBgEnabled', !!s.enabled);
        $('waBgSensitivity').value = s.sensitivity != null ? s.sensitivity : 70;
        $('waBgInterval').value = s.interval_sec != null ? s.interval_sec : 10;
        $('waBgPreDelay').value = s.pre_delay_ms != null ? s.pre_delay_ms : 800;
        $('waBgDuration').value = s.blur_duration_sec != null ? s.blur_duration_sec : 15;
        const bp = s.blur_percent != null ? s.blur_percent : 100;
        $('waBgProtectionMode').value = s.protection_mode || 'mask';
        $('waBgObsSource').value = s.obs_source_name || '';
        $('waBgObsFilter').value = s.obs_filter_name || '';
        waBgModeSync();
        $('waBgPercent').value = bp;
        $('waBgPercentRange').value = bp;
        $('waBgPrompt').value = s.custom_prompt || '';
        $('waBgCategories').value = (s.custom_categories || []).join(', ');
        waBgPreviewSync($('waBgDuration').value, bp);
        const st = await fetch('/api/widgets/public/blur-guard/state').then(r => r.json()).catch(() => ({}));
        $('waBgStatus').textContent = t(st.blur ? 'blur_guard.status_on' : 'blur_guard.status_off');
    } catch (e) { _waHint(e); }
}
let _waBgSaveTimer = null;
function waBgPreviewSync(dur, pct, persist = false) {
    const d = Math.max(1, Math.min(600, parseInt(dur, 10) || 15));
    const p = Math.max(1, Math.min(100, parseInt(pct, 10) || 100));
    if ($('waBgPrevDur')) $('waBgPrevDur').textContent = d;
    if ($('waBgPrevPct')) $('waBgPrevPct').textContent = p;
    if ($('waBgPreviewLayer')) {
        const strength = p / 100;
        $('waBgPreviewLayer').style.backdropFilter = `blur(${(p * 0.16).toFixed(1)}px)`;
        $('waBgPreviewLayer').style.webkitBackdropFilter = `blur(${(p * 0.16).toFixed(1)}px)`;
        $('waBgPreviewLayer').style.background = `rgba(15,15,26,${strength.toFixed(2)})`;
    }
    // Sync all three controls.
    if ($('waBgDuration')) $('waBgDuration').value = d;
    if ($('waBgPercent')) $('waBgPercent').value = p;
    if ($('waBgPercentRange')) $('waBgPercentRange').value = p;
    if (persist) {
        clearTimeout(_waBgSaveTimer);
        _waBgSaveTimer = setTimeout(() => waBgSave({ reload: false }), 350);
    }
}
function waBgModeSync() {
    const mode = $('waBgProtectionMode')?.value || 'mask';
    $('waBgImageFields')?.classList.toggle('hidden', mode !== 'image');
    $('waBgObsFields')?.classList.toggle('hidden', mode !== 'obs_filter');
}
async function waBgImageUpload() {
    const file = $('waBgImage')?.files?.[0];
    if (!file) return;
    const body = new FormData(); body.append('file', file);
    try {
        const r = await fetch('/api/blur-guard/image', {method: 'POST', body});
        if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`);
        toast(t('blur_guard.image_saved'), 'success');
    } catch (e) { _waHint(e); }
}
async function waBgSave(options = {}) {
    const reload = options.reload !== false;
    try {
        const cats = $('waBgCategories').value.split(',').map(s => s.trim()).filter(Boolean);
        await wapi('/api/blur-guard', 'PUT', {
            enabled: toggleChecked('waBgEnabled'),
            sensitivity: parseInt($('waBgSensitivity').value, 10) || 70,
            interval_sec: parseInt($('waBgInterval').value, 10) || 10,
            pre_delay_ms: parseInt($('waBgPreDelay').value, 10) || 0,
            blur_duration_sec: parseInt($('waBgDuration').value, 10) || 15,
            blur_percent: parseInt($('waBgPercent').value, 10) || 100,
            protection_mode: $('waBgProtectionMode').value,
            obs_source_name: $('waBgObsSource').value,
            obs_filter_name: $('waBgObsFilter').value,
            custom_prompt: $('waBgPrompt').value,
            categories: cats,
        });
        if (reload) await waBgLoad();
    } catch (e) { _waHint(e); }
}
async function waBgBind(action) {
    try { await wapi(`/api/widgets/public/blur-guard/${action}`, 'POST'); await waBgLoad(); } catch (e) { _waHint(e); }
}
const _loadWidgetsAdminPrev4 = loadWidgetsAdmin;
loadWidgetsAdmin = async function() {
    await _loadWidgetsAdminPrev4();
    waBgLoad();
};

Object.assign(LANGS.ru, {
    'blur_guard.description': 'Защитная маска поверх сцены в OBS: при срабатывании AI она закрывает контент. Browser Source не умеет размывать другие OBS-источники; для настоящего blur используй OBS-фильтр на source/group. 100% полностью скрывает пиксели.',
    'blur_guard.cover': 'Плотность маски, %',
    'blur_guard.status_on': 'Состояние маски: 🛡 ВКЛЮЧЕНА',
    'blur_guard.status_off': 'Состояние маски: выключена',
    'blur_guard.mode': 'Защита', 'blur_guard.advanced': 'Дополнительно', 'blur_guard.mode_mask': 'Цветная маска',
    'blur_guard.mode_image': 'Своя картинка', 'blur_guard.mode_filter': 'Настоящий OBS blur-фильтр',
    'blur_guard.upload': 'Загрузить картинку', 'blur_guard.image_saved': 'Картинка сохранена',
    'blur_guard.obs_source': 'Имя source/group в OBS', 'blur_guard.obs_filter': 'Имя blur-фильтра в OBS',
    'blur_guard.obs_hint': 'OBS WebSocket: ws://127.0.0.1:4455; пароль задаётся OBS_WEBSOCKET_PASSWORD.',
});
Object.assign(LANGS.en, {
    'blur_guard.description': 'A privacy mask over the OBS scene: AI activation covers the content. A Browser Source cannot blur other OBS sources; use an OBS filter on the source/group for real blur. 100% fully hides the pixels.',
    'blur_guard.cover': 'Mask coverage, %',
    'blur_guard.status_on': 'Mask status: 🛡 ON',
    'blur_guard.status_off': 'Mask status: off',
    'blur_guard.mode': 'Protection', 'blur_guard.advanced': 'Advanced', 'blur_guard.mode_mask': 'Color mask',
    'blur_guard.mode_image': 'Custom image', 'blur_guard.mode_filter': 'Real OBS blur filter',
    'blur_guard.upload': 'Upload image', 'blur_guard.image_saved': 'Image saved',
    'blur_guard.obs_source': 'OBS source/group name', 'blur_guard.obs_filter': 'OBS blur filter name',
    'blur_guard.obs_hint': 'OBS WebSocket: ws://127.0.0.1:4455; set the password with OBS_WEBSOCKET_PASSWORD.',
});
Object.assign(LANGS.ua, {
    'blur_guard.description': 'Захисна маска поверх сцени в OBS: після спрацювання AI вона закриває контент. Browser Source не може розмивати інші OBS-джерела; для справжнього blur використовуй OBS-фільтр на source/group. 100% повністю приховує пікселі.',
    'blur_guard.cover': 'Щільність маски, %',
    'blur_guard.status_on': 'Стан маски: 🛡 УВІМКНЕНА',
    'blur_guard.status_off': 'Стан маски: вимкнена',
    'blur_guard.mode': 'Захист', 'blur_guard.advanced': 'Додатково', 'blur_guard.mode_mask': 'Кольорова маска',
    'blur_guard.mode_image': 'Своя картинка', 'blur_guard.mode_filter': 'Справжній OBS blur-фільтр',
    'blur_guard.upload': 'Завантажити картинку', 'blur_guard.image_saved': 'Картинку збережено',
    'blur_guard.obs_source': 'Назва source/group в OBS', 'blur_guard.obs_filter': 'Назва blur-фільтра в OBS',
    'blur_guard.obs_hint': 'OBS WebSocket: ws://127.0.0.1:4455; пароль задається OBS_WEBSOCKET_PASSWORD.',
});


// ── session/fixes §I: Последние логи (panel.log tail) ──
async function loadPanelLogTail() {
    const el = $('panelLogTailContent');
    if (!el) return;
    const lines = parseInt($('panelLogTailLines')?.value, 10) || 100;
    try {
        const r = await fetch(API + `/api/logs/panel/tail?lines=${lines}`);
        const d = await r.json();
        if (d.ok && d.content) {
            el.innerHTML = '<pre data-user-content style="white-space:pre-wrap"></pre>';
            el.firstElementChild.textContent = d.content;
            el.scrollTop = el.scrollHeight;
        } else {
            el.innerHTML = `<div class="text-muted text-sm">${panelI18n('dynamic.panel_log_empty')}</div>`;
        }
    } catch (e) {
        el.innerHTML = `<div class="text-error text-sm">${panelI18n('label.error')}: ${esc(e.message)} <button class="btn btn-sm btn-secondary" onclick="loadPanelLogTail()" data-i18n="status.retry">${esc(t('status.retry'))}</button></div>`;
    }
}
function downloadPanelLog() {
    window.open(API + '/api/logs/panel/file', '_blank');
}

// ── Widgets session: i18n для новых блоков (§11.1/§11.2) ──
Object.assign(LANGS.ru, {
  'widgets.goals_percent_hint': 'Каждая цель — процент 0–100. Галочка появляется автоматически при 100%. В OBS-превью можно открыть виджет с ?admin=1 и кликать +/− прямо на стриме.',
  'widgets.np_source': 'Автозаполнение',
});
Object.assign(LANGS.en, {
  'widgets.goals_percent_hint': 'Each goal is a 0–100 percent. The checkmark appears automatically at 100%. Open the widget with ?admin=1 in OBS preview to click +/− live.',
  'widgets.np_source': 'Auto-fill',
});
Object.assign(LANGS.ua, {
  'widgets.goals_percent_hint': 'Кожна ціль — відсоток 0–100. Галочка з’являється автоматично при 100%. Відкрийте віджет з ?admin=1 у прев’ю OBS і клікайте +/− прямо на стрімі.',
  'widgets.np_source': 'Автозаповнення',
});


// ── Widgets session: голосование (Twitch Polls + !vote) ──
let _waPollChannel = '';
async function _waPollCtx() {
    // Канал и аккаунт — из выбранного бота; канал берём из его активного канала.
    const aid = _currentBotId || 0;
    let ch = _waPollChannel;
    if (aid && !ch) {
        try {
            const channels = await api(`/api/accounts/${aid}/channels`);
            const active = (channels || []).find(c => c.enabled !== 0) || (channels || [])[0];
            ch = (active?.channel_name || '').replace(/^#/, '');
            _waPollChannel = ch;
        } catch (e) { ch = ''; }
    }
    return {ch, aid};
}

function waPollSetStatus(message, invalid = false, validation = false) {
    const status = $('waPollStatus');
    status.textContent = message;
    status.classList.toggle('text-danger', invalid);
    status.dataset.validation = validation ? 'true' : '';
}

function waPollChoiceValues() {
    return [...document.querySelectorAll('#waPollChoices .wa-poll-choice')]
        .map(input => input.value.trim());
}

function waPollSyncChoices() {
    const count = document.querySelectorAll('#waPollChoices .wa-poll-choice').length;
    $('waPollAddChoice').disabled = count >= 5;
    $('waPollChoiceCount').textContent = t('widgets.poll.choice_count', {count});
}

function waPollValidateChoices() {
    const choices = waPollChoiceValues();
    if (choices.length < 2 || choices.length > 5 || choices.some(choice => !choice)) {
        waPollSetStatus(t('widgets.poll.invalid_choices'), true, true);
    } else if ($('waPollStatus').dataset.validation === 'true') {
        waPollSetStatus('');
    }
}

function waPollAddChoice() {
    const container = $('waPollChoices');
    if (container.querySelectorAll('.wa-poll-choice').length >= 5) return;
    const row = document.createElement('div');
    row.className = 'flex gap-2';
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'input wa-poll-choice';
    input.placeholder = t('widgets.poll.choice_placeholder');
    input.oninput = waPollValidateChoices;
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'btn btn-secondary btn-sm';
    remove.textContent = '×';
    remove.title = t('widgets.poll.remove');
    remove.onclick = () => waPollRemoveChoice(remove);
    row.append(input, remove);
    container.append(row);
    waPollSyncChoices();
    input.focus();
}

function waPollRemoveChoice(button) {
    const container = $('waPollChoices');
    if (container.querySelectorAll('.wa-poll-choice').length <= 2) {
        waPollSetStatus(t('widgets.poll.minimum_choices'), true, true);
        return;
    }
    button.parentElement.remove();
    waPollSyncChoices();
}

async function waTwitchPollCreate() {
    const {ch, aid} = await _waPollCtx();
    if (!ch || !aid) { waPollSetStatus(t('widgets.poll.choose_channel'), true); return; }
    const choices = waPollChoiceValues();
    if (choices.length < 2 || choices.length > 5 || choices.some(choice => !choice)) {
        waPollSetStatus(t('widgets.poll.invalid_choices'), true, true);
        return;
    }
    try {
        const r = await wapi('/api/widgets/twitch-poll', 'POST', {
            account_id: aid, channel: ch,
            title: $('waPollTitle').value,
            choices,
            duration_seconds: parseInt($('waPollDuration').value, 10) || 120,
        });
        waPollSetStatus(r.ok ? t('widgets.poll.created') : ('⛔ ' + (r.detail || r.error)), !r.ok);
    } catch (e) { _waHint(e); }
}
async function waTwitchPollEnd() {
    const {ch, aid} = await _waPollCtx();
    if (!ch || !aid) return;
    try {
        const r = await wapi('/api/widgets/twitch-poll/end', 'POST', {account_id: aid, channel: ch});
        waPollSetStatus(r.ok ? t('widgets.poll.ended') : ('⛔ ' + (r.error || '')), !r.ok);
    } catch (e) { _waHint(e); }
}

// ── Track 6.10: нативные Twitch Predictions ──
function waPredictionSetStatus(message, invalid = false, validation = false) {
    const status = $('waPredictionStatus');
    status.textContent = message;
    status.classList.toggle('text-danger', invalid);
    status.dataset.validation = validation ? 'true' : '';
}

function waPredictionOutcomeValues() {
    return [...document.querySelectorAll('#waPredictionOutcomes .wa-prediction-outcome')]
        .map(input => input.value.trim());
}

function waPredictionWindowSeconds() {
    const value = Number($('waPredictionWindow').value);
    return $('waPredictionWindowUnit').value === 'minutes' ? value * 60 : value;
}

function waPredictionWindowUnitSync() {
    const window = $('waPredictionWindow');
    if ($('waPredictionWindowUnit').value === 'minutes') {
        window.min = '1';
        window.max = '30';
    } else {
        window.min = '30';
        window.max = '1800';
    }
    waPredictionValidate();
}

function waPredictionSyncOutcomes() {
    const count = document.querySelectorAll('#waPredictionOutcomes .wa-prediction-outcome').length;
    $('waPredictionAddOutcome').disabled = count >= 10;
    $('waPredictionOutcomeCount').textContent = t('widgets.prediction.outcome_count', {count});
}

function waPredictionValidate() {
    const title = $('waPredictionTitle').value.trim();
    const outcomes = waPredictionOutcomeValues();
    const windowSeconds = waPredictionWindowSeconds();
    if (!title) {
        waPredictionSetStatus(t('widgets.prediction.invalid_title'), true, true);
    } else if (outcomes.length < 2 || outcomes.length > 10 || outcomes.some(outcome => !outcome)) {
        waPredictionSetStatus(t('widgets.prediction.invalid_outcomes'), true, true);
    } else if (!Number.isInteger(windowSeconds) || windowSeconds < 30 || windowSeconds > 1800) {
        waPredictionSetStatus(t('widgets.prediction.invalid_window'), true, true);
    } else if ($('waPredictionStatus').dataset.validation === 'true') {
        waPredictionSetStatus('');
    }
    return Boolean(title) && outcomes.length >= 2 && outcomes.length <= 10
        && outcomes.every(Boolean) && Number.isInteger(windowSeconds)
        && windowSeconds >= 30 && windowSeconds <= 1800;
}

function waPredictionAddOutcome() {
    const container = $('waPredictionOutcomes');
    if (container.querySelectorAll('.wa-prediction-outcome').length >= 10) return;
    const row = document.createElement('div');
    row.className = 'flex gap-2';
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'input wa-prediction-outcome';
    input.maxLength = 25;
    input.placeholder = t('widgets.prediction.outcome_placeholder');
    input.setAttribute('aria-label', t('widgets.prediction.outcome_placeholder'));
    input.oninput = waPredictionValidate;
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'btn btn-secondary btn-sm';
    remove.textContent = '×';
    remove.title = t('widgets.prediction.remove');
    remove.setAttribute('aria-label', t('widgets.prediction.remove'));
    remove.onclick = () => waPredictionRemoveOutcome(remove);
    row.append(input, remove);
    container.append(row);
    waPredictionSyncOutcomes();
    input.focus();
}

function waPredictionRemoveOutcome(button) {
    const container = $('waPredictionOutcomes');
    if (container.querySelectorAll('.wa-prediction-outcome').length <= 2) {
        waPredictionSetStatus(t('widgets.prediction.minimum_outcomes'), true, true);
        return;
    }
    button.parentElement.remove();
    waPredictionSyncOutcomes();
    waPredictionValidate();
}

async function waTwitchPredictionCreate() {
    const {ch, aid} = await _waPollCtx();
    if (!ch || !aid) { waPredictionSetStatus(t('widgets.prediction.choose_channel'), true); return; }
    if (!waPredictionValidate()) return;
    try {
        const r = await wapi('/api/widgets/twitch-prediction', 'POST', {
            account_id: aid,
            channel: ch,
            title: $('waPredictionTitle').value.trim(),
            outcomes: waPredictionOutcomeValues(),
            prediction_window: waPredictionWindowSeconds(),
        });
        waPredictionSetStatus(r.ok ? t('widgets.prediction.created') : t('widgets.prediction.request_failed'), !r.ok);
        if (r.ok) await waPredictionRefresh();
    } catch (e) { _waHint(e); }
}

function waPredictionRenderActive(prediction) {
    const target = $('waPredictionActive');
    if (!prediction) {
        target.textContent = t('widgets.prediction.no_active');
        return;
    }
    const outcomes = prediction.outcomes || [];
    const options = outcomes.map(outcome => `<option value="${esc(outcome.id)}">${esc(outcome.title)} (${Number(outcome.channel_points || 0)})</option>`).join('');
    target.innerHTML = `<b>${esc(prediction.title)}</b> · ${esc(prediction.status)}<br>`
        + outcomes.map(outcome => `${esc(outcome.title)}: ${Number(outcome.channel_points || 0)}`).join(' · ')
        + `<div class="flex gap-2 flex-wrap mt-2">`
        + (prediction.status === 'ACTIVE' ? `<button class="btn btn-secondary btn-sm" type="button" onclick="waPredictionEnd('LOCKED', '${esc(prediction.id)}')">${esc(t('widgets.prediction.lock'))}</button>` : '')
        + (prediction.status === 'LOCKED' ? `<select id="waPredictionWinner" class="input" style="width:auto"><option value="">${esc(t('widgets.prediction.choose_winner'))}</option>${options}</select><button class="btn btn-primary btn-sm" type="button" onclick="waPredictionEnd('RESOLVED', '${esc(prediction.id)}')">${esc(t('widgets.prediction.resolve'))}</button>` : '')
        + `<button class="btn btn-danger btn-sm" type="button" onclick="waPredictionEnd('CANCELED', '${esc(prediction.id)}')">${esc(t('widgets.prediction.cancel'))}</button></div>`;
}

async function waPredictionRefresh() {
    const {ch, aid} = await _waPollCtx();
    if (!ch || !aid) { waPredictionSetStatus(t('widgets.prediction.choose_channel'), true); return; }
    try {
        const r = await wapi('/api/widgets/twitch-prediction/active', 'POST', {account_id: aid, channel: ch});
        if (!r.ok) throw new Error(r.error || 'request_failed');
        waPredictionRenderActive(r.prediction);
    } catch (e) { _waHint(e); }
}

async function waPredictionEnd(status, predictionId) {
    const {ch, aid} = await _waPollCtx();
    if (!ch || !aid) return;
    const winner = status === 'RESOLVED' ? $('waPredictionWinner')?.value : null;
    if (status === 'RESOLVED' && !winner) { waPredictionSetStatus(t('widgets.prediction.choose_winner'), true); return; }
    if (status === 'CANCELED' && !confirm(t('widgets.prediction.cancel_confirm'))) return;
    try {
        const r = await wapi('/api/widgets/twitch-prediction/end', 'POST', {
            account_id: aid, channel: ch, prediction_id: predictionId, status,
            winning_outcome_id: winner, confirmed: status === 'CANCELED',
        });
        waPredictionSetStatus(r.ok ? t('widgets.prediction.updated') : ('⛔ ' + (r.error || '')), !r.ok);
        await waPredictionRefresh();
    } catch (e) { _waHint(e); }
}
// ── v14 MODERATION_PLAN: политика «кто таймаутит» (auto/ask/learn) + всплывашка ──
// auto — бот таймаутит сам; ask — владельцу приходит вопрос Да/Нет;
// learn — бот спрашивает, учится на ответах и потом решает сам.

async function loadModerationTimeoutPolicy(id) {
    if (!id) return;
    try {
        const data = await api(`/api/accounts/${id}/moderation/timeout-policy`);
        const sel = $('moderationTimeoutPolicy');
        if (sel) sel.value = data.policy || 'auto';
        renderLearnStats(data.learn_stats || []);
    } catch (e) { console.error('loadModerationTimeoutPolicy', e); }
}

async function saveModerationTimeoutPolicy(id) {
    if (!id) return;
    try {
        await api(`/api/accounts/${id}/moderation/timeout-policy`, jopts('PUT', { policy: $('moderationTimeoutPolicy').value }));
        toast(t('dynamic.timeout_saved'), 'success');
        loadModerationTimeoutPolicy(id);
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

function renderLearnStats(stats) {
    const sel = $('moderationTimeoutPolicy');
    if (!sel) return;
    let box = document.getElementById('modLearnStats');
    if (!box) {
        box = document.createElement('div');
        box.id = 'modLearnStats';
        box.className = 'text-sm text-muted mt-2';
        sel.parentElement.parentElement.appendChild(box);
    }
    const learned = (stats || []).filter(s => s.auto);
    const other = (stats || []).filter(s => !s.auto);
    const fmt = s => `<span class="badge">${panelEnumI18n('panel.mod.cat_', s.category)}</span> 👍${s.approved} 👎${s.rejected}`;
    let html = '';
    if (learned.length) html += `<div class="mt-1">✅ ${panelI18n('panel.mod.auto')}: ${learned.map(fmt).join(' ')}</div>`;
    if (other.length) html += `<div class="mt-1">${panelI18n('dynamic.timeout_asks')}: ${other.map(fmt).join(' ')}</div>`;
    box.innerHTML = html;
}

// Всплывашка «Да/Нет» по таймаутам. Опрашивает очередь раз в 20с.
let _modPendingTimer = null;
let _modPendingShown = {};

async function pollModerationPending() {
    // Q24: тумблер «Не показывать всплывашки» — плавающие карточки решений скрываются,
    // очередь остаётся доступной в журнале канала (Q26) и настройках бота.
    if (typeof popupsHidden === 'function' && popupsHidden()) {
        const box = document.getElementById('modAskPopup');
        if (box) box.remove();
        return;
    }
    let data;
    try {
        data = await api('/api/moderation/pending');
    } catch (e) {
        return; // тихо: не залогинены / сеть
    }
    const events = data.events || [];
    events.forEach(ev => {
        if (_modPendingShown[ev.id]) return;
        _modPendingShown[ev.id] = true;
        showModerationAskPopup(ev);
    });
    // подчищаем карточки решённых вопросов
    document.querySelectorAll('[data-mod-pending]').forEach(el => {
        const id = parseInt(el.dataset.modPending, 10);
        if (!events.some(ev => ev.id === id)) el.remove();
    });
}

function showModerationAskPopup(ev) {
    let box = document.getElementById('modAskPopup');
    if (!box) {
        box = document.createElement('div');
        box.id = 'modAskPopup';
        box.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:9999;display:flex;flex-direction:column;gap:8px;max-width:360px;';
        document.body.appendChild(box);
    }
    const card = document.createElement('div');
    card.dataset.modPending = ev.id;
    card.style.cssText = 'background:var(--bg-card,#1e1e2e);border:1px solid var(--border,#444);border-radius:10px;padding:12px;box-shadow:0 4px 16px rgba(0,0,0,.4);';
    const excerpt = ev.message_excerpt ? `<div class="text-muted" style="font-size:12px;margin-top:4px;">«${esc(ev.message_excerpt.slice(0, 120))}»</div>` : '';
    card.innerHTML = `
        <div style="font-weight:600;">🛡 ${panelI18n('dynamic.timeout_question')} ${esc(ev.username)}</div>
        <div class="text-muted" style="font-size:13px;margin-top:2px;">#${esc(ev.channel)} · ${panelEnumI18n('panel.mod.cat_', ev.category)} · ${panelI18n('dynamic.mod.severity')} ${ev.severity} · ${panelI18n('dynamic.timeout_duration')}</div>
        ${excerpt}
        <div class="flex gap-2" style="margin-top:8px;">
            <button class="btn btn-primary btn-sm" data-ans="1">✅ ${panelI18n('dynamic.yes')}</button>
            <button class="btn btn-secondary btn-sm" data-ans="0">❌ ${panelI18n('dynamic.no')}</button>
        </div>`;
    card.querySelectorAll('button[data-ans]').forEach(btn => {
        btn.onclick = async () => {
            const approved = btn.dataset.ans === '1';
            btn.disabled = true;
            try {
                await api(`/api/moderation/pending/${ev.id}/decision`, jopts('POST', { approved, account_id: ev.account_id }));
                toast(approved ? t('dynamic.timeout_approved') : t('dynamic.timeout_rejected'), 'success');
            } catch (e) {
                toast(t('toast.error_detail', { detail: e.message }), 'error');
            }
            card.remove();
            delete _modPendingShown[ev.id];
            if (_currentBotId === ev.account_id) loadModerationTimeoutPolicy(ev.account_id);
        };
    });
    box.appendChild(card);
}

function startModerationPendingPolling() {
    if (_modPendingTimer) return;
    _modPendingTimer = setInterval(pollModerationPending, 20000);
    pollModerationPending();
}
startModerationPendingPolling();

// ── Scoped Donation Challenge ──
Object.assign(LANGS.ru, {
    'donation_challenge.title': '💝 Донат-челлендж',
    'donation_challenge.scope_hint': 'Сбор работает только для выбранных выше аккаунта и канала.',
    'donation_challenge.name': 'Название сбора', 'donation_challenge.target': 'Цель',
    'donation_challenge.create': '+ Создать', 'donation_challenge.empty': 'Активных сборов пока нет.',
    'donation_challenge.add': 'Добавить сумму', 'donation_challenge.save': 'Сохранить',
});
Object.assign(LANGS.en, {
    'donation_challenge.title': '💝 Donation challenge',
    'donation_challenge.scope_hint': 'This goal works only for the account and channel selected above.',
    'donation_challenge.name': 'Goal name', 'donation_challenge.target': 'Target',
    'donation_challenge.create': '+ Create', 'donation_challenge.empty': 'No challenges yet.',
    'donation_challenge.add': 'Add amount', 'donation_challenge.save': 'Save',
});
Object.assign(LANGS.ua, {
    'donation_challenge.title': '💝 Донат-челендж',
    'donation_challenge.scope_hint': 'Збір працює лише для вибраних вище акаунта й каналу.',
    'donation_challenge.name': 'Назва збору', 'donation_challenge.target': 'Ціль',
    'donation_challenge.create': '+ Створити', 'donation_challenge.empty': 'Активних зборів поки немає.',
    'donation_challenge.add': 'Додати суму', 'donation_challenge.save': 'Зберегти',
});

async function waDonationChallengesLoad() {
    const list = $('waDonationChallengesList');
    if (!list) return;
    try {
        const data = await wstateapi('/api/widgets/donation-challenges');
        list.innerHTML = (data.challenges || []).map(item => `
            <div class="flex gap-2 items-center flex-wrap" data-dc-id="${item.id}">
                <input class="input flex-1" data-dc-title value="${esc(item.title)}">
                <span class="text-sm">${Number(item.current_amount || 0)} / ${Number(item.target_amount || 0)} ${esc(item.currency || '')}</span>
                <input class="input" data-dc-amount type="number" min="0.01" step="0.01" style="max-width:100px" aria-label="${esc(t('donation_challenge.add'))}">
                <button class="btn btn-secondary btn-sm" onclick="waDonationChallengeSave(${item.id})">💾 ${esc(t('donation_challenge.save'))}</button>
                <button class="btn btn-secondary btn-sm" onclick="waDonationChallengeAdd(${item.id})">+💰</button>
                <button class="btn btn-danger btn-sm" onclick="waDonationChallengeDelete(${item.id})">🗑</button>
            </div>`).join('') || `<div class="text-sm text-muted">${esc(t('donation_challenge.empty'))}</div>`;
    } catch (error) { _waHint(error); }
}

async function waDonationChallengeCreate() {
    try {
        const scope = waBindingScope();
        const result = await wapi('/api/widgets/donation-challenges', 'POST', {
            ...scope, title: $('waDcTitle').value.trim(),
            target_amount: Number($('waDcTarget').value), currency: $('waDcCurrency').value.trim(),
        });
        if (!result.ok) throw new Error(result.error || 'create_failed');
        $('waDcTitle').value = ''; $('waDcTarget').value = '';
        await waDonationChallengesLoad(); waRefreshScopedWidgetPreviews();
    } catch (error) { _waHint(error); }
}

function waDonationChallengeRow(id) {
    return document.querySelector(`[data-dc-id="${id}"]`);
}

async function waDonationChallengeSave(id) {
    try {
        const row = waDonationChallengeRow(id);
        await wstateapi(`/api/widgets/donation-challenges/${id}`, 'PUT', {title: row.querySelector('[data-dc-title]').value.trim()});
        await waDonationChallengesLoad(); waRefreshScopedWidgetPreviews();
    } catch (error) { _waHint(error); }
}

async function waDonationChallengeAdd(id) {
    try {
        const row = waDonationChallengeRow(id);
        await wstateapi(`/api/widgets/donation-challenges/${id}/add-funds`, 'POST', {amount: Number(row.querySelector('[data-dc-amount]').value)});
        await waDonationChallengesLoad(); waRefreshScopedWidgetPreviews();
    } catch (error) { _waHint(error); }
}

async function waDonationChallengeDelete(id) {
    try {
        await wstateapi(`/api/widgets/donation-challenges/${id}`, 'DELETE');
        await waDonationChallengesLoad(); waRefreshScopedWidgetPreviews();
    } catch (error) { _waHint(error); }
}

// ── WIDGETS-UI шаг 2: группы-папки виджетов (по умолчанию все свёрнуты) ──
const WIDGET_GROUPS_STORAGE_KEY = 'widgetsGroupsOpen';

function waWidgetGroupsInit() {
    let open = [];
    try { open = JSON.parse(localStorage.getItem(WIDGET_GROUPS_STORAGE_KEY) || '[]'); } catch (_) { open = []; }
    const openSet = new Set(Array.isArray(open) ? open.map(String) : []);
    document.querySelectorAll('details.widget-group').forEach(group => {
        const id = group.dataset.widgetGroup || '';
        group.open = openSet.has(id); // по умолчанию — свёрнуто
        const counter = group.querySelector('.widget-group-count');
        if (counter) counter.textContent = String(group.querySelectorAll('.card').length);
        if (group.dataset.groupToggleBound) return;
        group.dataset.groupToggleBound = '1';
        group.addEventListener('toggle', () => {
            let cur = [];
            try { cur = JSON.parse(localStorage.getItem(WIDGET_GROUPS_STORAGE_KEY) || '[]'); } catch (_) { cur = []; }
            const set = new Set(Array.isArray(cur) ? cur.map(String) : []);
            if (group.open) set.add(id); else set.delete(id);
            try { localStorage.setItem(WIDGET_GROUPS_STORAGE_KEY, JSON.stringify([...set])); } catch (_) {}
        });
    });
}

document.addEventListener('DOMContentLoaded', waWidgetGroupsInit);

Object.assign(LANGS.ru, {
    'widgets.group.basics': '🎯 Базовые виджеты',
    'widgets.group.donations': '💝 Донаты',
    'widgets.group.tts_sound': '🎙 TTS и звук',
    'widgets.group.automation': '🔗 Интеграции и автоматизация',
    'widgets.group.overlays': '🛡 Оверлеи и механики Twitch',
    'widgets.group.extras': '🧩 Прочее и гайды',
    'widgets.group.catalog': '📚 Каталог всех виджетов',
});
Object.assign(LANGS.en, {
    'widgets.group.basics': '🎯 Core widgets',
    'widgets.group.donations': '💝 Donations',
    'widgets.group.tts_sound': '🎙 TTS & sound',
    'widgets.group.automation': '🔗 Integrations & automation',
    'widgets.group.overlays': '🛡 Overlays & Twitch mechanics',
    'widgets.group.extras': '🧩 Extras & guides',
    'widgets.group.catalog': '📚 Full widget catalog',
});
Object.assign(LANGS.ua, {
    'widgets.group.basics': '🎯 Базові віджети',
    'widgets.group.donations': '💝 Донати',
    'widgets.group.tts_sound': '🎙 TTS та звук',
    'widgets.group.automation': '🔗 Інтеграції та автоматизація',
    'widgets.group.overlays': '🛡 Оверлеї та механіки Twitch',
    'widgets.group.extras': '🧩 Інше та гайди',
    'widgets.group.catalog': '📚 Каталог усіх віджетів',
});

// ── WIDGETS-UI шаг 4: настройки виджета открываются прямо из его карточки ──
// Форма наполнения остаётся единственной (в «Прочих виджетах»); модал лишь
// переносит её узел в оверлей и возвращает на исходное место при закрытии.
let _waSettingsHome = null;

function waWidgetSettingsReturn() {
    const overlay = document.getElementById('waWidgetSettingsModal');
    if (!overlay) return;
    overlay.querySelectorAll('[data-wa-settings-form]').forEach(form => {
        const home = _waSettingsHome?.[form.id];
        if (home?.parent) home.parent.insertBefore(form, home.anchor);
    });
    _waSettingsHome = null;
}

function waWidgetSettingsOpen(slug) {
    const form = document.getElementById('wa2Form-' + slug);
    if (!form) return;
    waWidgetSettingsReturn();
    const box = form.querySelector('b[data-i18n]');
    const title = box ? t(box.getAttribute('data-i18n')) : slug;
    let overlay = document.getElementById('waWidgetSettingsModal');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'waWidgetSettingsModal';
        overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.72);z-index:999;display:flex;align-items:center;justify-content:center';
        overlay.innerHTML = `
        <div class="modal" role="dialog" aria-modal="true" aria-labelledby="waWidgetSettingsTitle" style="background:var(--bg-card);border:1px solid var(--border);border-radius:12px;padding:16px;width:min(640px,94vw);max-height:90vh;overflow:auto">
            <div class="flex items-center justify-between mb-3" style="gap:12px">
                <b id="waWidgetSettingsTitle">${esc(t('widgets.settings'))}</b>
                <button class="btn btn-sm btn-secondary" data-i18n-aria-label="btn.close" aria-label="${esc(t('btn.close'))}" onclick="waWidgetSettingsClose()">✕</button>
            </div>
            <div id="waWidgetSettingsBody"></div>
        </div>`;
        overlay.addEventListener('click', e => { if (e.target === overlay) waWidgetSettingsClose(); });
        document.body.appendChild(overlay);
    }
    const heading = overlay.querySelector('#waWidgetSettingsTitle');
    heading.textContent = `${t('widgets.settings')} · ${title}`;
    _waSettingsHome = _waSettingsHome || {};
    _waSettingsHome[form.id] = {parent: form.parentElement, anchor: form.nextElementSibling};
    form.dataset.waSettingsForm = '1';
    overlay.querySelector('#waWidgetSettingsBody').appendChild(form);
    openPanelDialog(overlay, {onDismiss: waWidgetSettingsClose});
}

function waWidgetSettingsClose() {
    waWidgetSettingsReturn();
    const overlay = document.getElementById('waWidgetSettingsModal');
    if (overlay) closePanelDialog(overlay);
}

Object.assign(LANGS.ru, {
    'widgets.settings': '⚙ Настройки',
});
Object.assign(LANGS.en, {
    'widgets.settings': '⚙ Settings',
});
Object.assign(LANGS.ua, {
    'widgets.settings': '⚙ Налаштування',
});
