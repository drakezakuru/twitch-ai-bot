// [P5-split] 09_brain_p3.js ← static/app.js, исходные строки 6502–6888; грузится после предыдущего чанка, порядок = порядку строк

// ==================== P3 PLAN_PANEL_REWORK §1.2/§1.3: Мозг бота X ====================

let _brainxData = null;

// D (REWORK_PLAN): рубильники «Влияния» — карточка над сводкой «Мозг бота»
async function loadInfluences(id) {
    if (!id) return;
    try {
        const s = await api(`/api/accounts/${id}/analyzer`);
        const setT = (elId, val) => { const el = $(elId); if (el) el.classList.toggle('active', !!val); };
        setT('infMimicry', s.influence_mimicry !== false);
        setT('infObservations', s.influence_observations !== false);
        setT('infLore', s.streamer_lore_enabled !== false);
        setT('infLearning', s.influence_learning !== false);
    } catch (e) { console.warn('influences', e); }
}

async function saveInfluences() {
    if (!_currentBotId) return;
    try {
        await api(`/api/accounts/${_currentBotId}/analyzer`, jopts('PUT', {
            influence_mimicry: $('infMimicry')?.classList.contains('active') ?? true,
            influence_observations: $('infObservations')?.classList.contains('active') ?? true,
            streamer_lore_enabled: $('infLore')?.classList.contains('active') ?? true,
            influence_learning: $('infLearning')?.classList.contains('active') ?? true,
        }));
        toast(t('msg.saved'), 'success');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

function _brainxRow(icon, label, value, goFn) {
    return `<div class="flex gap-2 items-center text-sm">
        <span style="min-width:200px">${icon} ${esc(label)}</span>
        <span class="flex-1 text-muted">${value}</span>
        ${goFn ? `<button class="btn btn-secondary btn-sm" onclick="${goFn}" data-i18n="brainx.go">Настроить</button>` : ''}
    </div>`;
}

async function loadBrainPreview(id) {
    if (!id) return;
    const el = $('brainxSections');
    if (!el) return;
    loadInfluences(id);
    try {
        // P8-A1: GET /api/accounts/{id} не существует (только PUT/DELETE) —
        // вкладка «Мозг бота» падала 405; ник берём из уже загруженного списка.
        const d = await api(`/api/brain-preview/${id}`);
        const bot = (_allBots || []).find(b => b.id === id);
        _brainxData = d;
        if ($('brainxNick')) $('brainxNick').textContent = bot?.nickname || `#${id}`;
        const p = d.persona || {};
        const lv = p.levels || {};
        const personaShort = Object.keys(lv).length
            ? Object.entries(lv).map(([k, v]) => `${k.replace('_level', '')}: ${v}`).slice(0, 4).join(' · ')
            : '—';
        const counts = d.counts || {};
        el.innerHTML = [
            _brainxRow('🧩', t('brainx.base'), `<span class="text-truncate">${esc((d.base_system || '').slice(0, 80)) || '—'}…</span> (${d.base_system ? d.base_system.length : 0} симв)`, "showBotGroup('ai')"),
            _brainxRow('🎭', t('brainx.persona'), `${esc(p.name || '—')} · ${esc(personaShort)} · промпт-блок ${esc(String(d.persona_block_chars ?? 0))} симв`, "showBotGroup('identity')"),
            _brainxRow('⚙️', t('brainx.role'), esc(d.role || '—') + (d.chatter_style_chars ? ` · стиль-блок ${d.chatter_style_chars} симв` : ''), "showBotGroup('role')"),
            _brainxRow('👤', t('brainx.streamer_profile'), (d.streamer_profile?.scope ? esc(d.streamer_profile.scope) : '—') + ` · ${d.streamer_profile_chars || 0} симв`, "showBotGroup('memory')"),
            _brainxRow('📚', t('brainx.lore'), `${d.lore_count ?? 0} ${t('brainx.facts_approved')}`, "showBotGroup('memory')"),
            _brainxRow('💬', t('brainx.memory'), `${t('brainx.users_in_memory')}: ${counts.users_with_memory ?? '—'} · ${t('brainx.style_examples')}: ${counts.style_examples ?? '—'} · KB: ${counts.kb_entries ?? '—'}`, "showBotGroup('identity')"),
            _brainxRow('🤖', t('brainx.provider'), (d.provider?.ai_provider_override ? esc(d.provider.ai_provider_override) : t('brainx.provider_global')) + (d.provider?.proxy ? ' · proxy' : ''), "showBotGroup('ai')"),
        ].join('');
        // renderI18n() не существует — локализуем вставленные узлы легаси-проходом
        if (typeof localizeLegacyNodes === 'function') localizeLegacyNodes();
    } catch (e) {
        el.innerHTML = `<div class="text-error text-sm">${esc(t('empty.load_failed', { detail: e.message }))}</div>`;
    }
}

function brainxTogglePrompt() {
    const wrap = $('brainxPromptWrap');
    if (!wrap) return;
    const hidden = wrap.classList.toggle('hidden');
    if (!hidden && _brainxData) {
        const pre = $('brainxPrompt');
        if (pre) pre.textContent = _brainxData.static_prompt || t('brainx.prompt_empty');
    }
}

function brainxCopyPrompt() {
    if (_brainxData?.static_prompt) {
        navigator.clipboard.writeText(_brainxData.static_prompt)
            .then(() => toast(t('toast.copied'), 'success'));
    }
}

async function brainxSnapshot() {
    if (!_currentBotId) return;
    try {
        const res = await api(`/api/brain-preview/${_currentBotId}/snapshot`, jopts('POST', {}));
        if (!res.ok) throw new Error(res.error || 'error');
        toast(t('brainx.snapshot_ok', { n: (res.files || []).length }), 'success');
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

Object.assign(LANGS.ru, {
    'brainx.title': 'Мозг бота',
    'brainx.hint': 'Сводка всего, что влияет на этого бота. Кнопки-переходы открывают нужные разделы — редакторы не дублируются.',
    'brainx.base': 'База (system prompt)',
    'brainx.persona': 'Характер (персона)',
    'brainx.role': 'Роль',
    'brainx.streamer_profile': 'Профиль стримера',
    'brainx.lore': 'Lore (факты)',
    'brainx.facts_approved': 'утверждённых фактов',
    'brainx.memory': 'Память и знания',
    'brainx.users_in_memory': 'юзеров в памяти',
    'brainx.style_examples': 'примеров стиля',
    'brainx.provider': 'Провайдер AI',
    'brainx.provider_global': 'глобальные настройки',
    'brainx.go': 'Настроить',
    'brainx.show_prompt': '📄 Показать промпт',
    'brainx.static_note': 'Статическая часть system prompt (динамические блоки памяти подмешиваются на каждое сообщение)',
    'brainx.copy': '📋 Копировать',
    'brainx.snapshot': '💾 Снимок в папку',
    'brainx.snapshot_ok': 'Снапшот записан в data/bots: {n} файлов',
    'brainx.prompt_empty': 'Промпт пуст — задайте базовую инструкцию и/или характер.',
    'brainx.go_persona': '🎭 Характер',
    'brainx.go_memory': '🧠 Память и знания',
    'brainx.go_ai': '🧠 AI и TTS',
});
Object.assign(LANGS.en, {
    'brainx.title': 'Bot brain',
    'brainx.hint': 'Summary of everything that affects this bot. Buttons jump to the relevant sections — no duplicated editors.',
    'brainx.base': 'Base (system prompt)',
    'brainx.persona': 'Character (persona)',
    'brainx.role': 'Role',
    'brainx.streamer_profile': 'Streamer profile',
    'brainx.lore': 'Lore (facts)',
    'brainx.facts_approved': 'approved facts',
    'brainx.memory': 'Memory & knowledge',
    'brainx.users_in_memory': 'users in memory',
    'brainx.style_examples': 'style examples',
    'brainx.provider': 'AI provider',
    'brainx.provider_global': 'global settings',
    'brainx.go': 'Configure',
    'brainx.show_prompt': '📄 Show prompt',
    'brainx.static_note': 'Static part of the system prompt (dynamic memory blocks are mixed in per message)',
    'brainx.copy': '📋 Copy',
    'brainx.snapshot': '💾 Snapshot to folder',
    'brainx.snapshot_ok': 'Snapshot written to data/bots: {n} files',
    'brainx.prompt_empty': 'Prompt is empty — set the base instruction and/or character.',
    'brainx.go_persona': '🎭 Character',
    'brainx.go_memory': '🧠 Memory & knowledge',
    'brainx.go_ai': '🧠 AI & TTS',
});
Object.assign(LANGS.ua, {
    'brainx.title': 'Мозок бота',
    'brainx.hint': 'Зведення всього, що впливає на цього бота. Кнопки-переходи відкривають потрібні розділи — редактори не дублюються.',
    'brainx.base': 'База (system prompt)',
    'brainx.persona': 'Характер (персона)',
    'brainx.role': 'Роль',
    'brainx.streamer_profile': 'Профіль стрімера',
    'brainx.lore': 'Lore (факти)',
    'brainx.facts_approved': 'схвалених фактів',
    'brainx.memory': 'Памʼять і знання',
    'brainx.users_in_memory': 'юзерів у памʼяті',
    'brainx.style_examples': 'прикладів стилю',
    'brainx.provider': 'Провайдер AI',
    'brainx.provider_global': 'глобальні налаштування',
    'brainx.go': 'Налаштувати',
    'brainx.show_prompt': '📄 Показати промпт',
    'brainx.static_note': 'Статична частина system prompt (динамічні блоки памʼяті підмішуються на кожне повідомлення)',
    'brainx.copy': '📋 Копіювати',
    'brainx.snapshot': '💾 Знімок у папку',
    'brainx.snapshot_ok': 'Знімок записано в data/bots: {n} файлів',
    'brainx.prompt_empty': 'Промпт порожній — задайте базову інструкцію та/або характер.',
    'brainx.go_persona': '🎭 Характер',
    'brainx.go_memory': '🧠 Памʼять і знання',
    'brainx.go_ai': '🧠 AI та TTS',
});

// ── P3 §1.4: «чья память» в сводке Мозга ──
Object.assign(LANGS.ru, {
    'brainx.memory_scope': 'Память',
    'brainx.memory_shared': 'своя + общая',
    'brainx.memory_own': 'только своя',
});
Object.assign(LANGS.en, {
    'brainx.memory_scope': 'Memory',
    'brainx.memory_shared': 'own + shared',
    'brainx.memory_own': 'own only',
});
Object.assign(LANGS.ua, {
    'brainx.memory_scope': 'Памʼять',
    'brainx.memory_shared': 'свої + спільні',
    'brainx.memory_own': 'лише свої',
});

// ==================== P5 PLAN.md: «Инструкция» у карточек виджетов ====================

// Параметры/размеры по виджетам (из widgets/README.md). Размер по умолчанию — 800×600.
const WIDGET_INSTR_PARAMS = {
    tts: 'instr.params_tts',
    counter: 'instr.params_counter',
    animatedbg: 'type=snow|stars|rain',
    topdonator: 'instr.params_topdonator',
};

function showWidgetInstr(path, slug, width = 800, height = 600) {
    const previous = document.getElementById('widgetInstrModal');
    if (previous) { closePanelDialog(previous); previous.remove(); }
    const url = location.origin + widgetOutputUrl(path);
    const paramKey = WIDGET_INSTR_PARAMS[String(slug || '').replace(/-/g, '')] || '';
    const params = paramKey.startsWith('instr.') ? t(paramKey) : paramKey;
    const overlay = document.createElement('div');
    overlay.id = 'widgetInstrModal';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:999;display:flex;align-items:center;justify-content:center';
    overlay.innerHTML = `<div class="modal" role="dialog" aria-modal="true" aria-labelledby="widgetInstrTitle" aria-describedby="widgetInstrSteps" style="background:var(--bg-card);border:1px solid var(--border);border-radius:12px;max-width:560px;width:92%;padding:18px;max-height:85vh;overflow:auto">
        <div class="flex items-center justify-between mb-3">
            <b id="widgetInstrTitle" data-i18n="instr.title">${esc(t('instr.title'))}</b>
            <button class="btn btn-sm btn-secondary" data-i18n-aria-label="btn.close" aria-label="${esc(t('btn.close'))}" onclick="closePanelDialog('widgetInstrModal')">✕</button>
        </div>
        <p id="widgetInstrSteps" data-i18n="instr.steps" class="text-sm mb-2" style="white-space:pre-line">${esc(t('instr.steps'))}</p>
        <p class="text-sm mb-3"><b>${esc(t('widgets.obs_size'))}:</b> ${Number(width)} × ${Number(height)}</p>
        <p class="text-xs text-muted mb-3">${esc(t('instr.size_note'))}</p>
        <div class="mb-2"><span class="text-xs text-muted">${esc(t('tts_chat.url'))}:</span>
            <code class="text-xs" style="word-break:break-all">${esc(url)}</code></div>
        ${params ? `<p class="text-xs mb-1"><b>${esc(t('instr.params'))}:</b> ${esc(params)}</p>` : ''}
        <p class="text-xs mb-1">${esc(t('instr.common_params'))}: <code>?theme=dark|light|neon|glass|fire|minimal</code> · <code>?scale=1.5</code> · <code>?ui_lang=ru|en|ua</code> · <code>?api=http://panel:8000</code></p>
        <p class="text-xs text-muted">${esc(t('instr.transparent'))}</p>
    </div>`;
    overlay.addEventListener('click', e => { if (e.target === overlay) closePanelDialog(overlay); });
    document.body.appendChild(overlay);
    openPanelDialog(overlay, {removeOnClose: true});
}

Object.assign(LANGS.ru, {
    'widgets.instr': '❓ Инструкция',
    'widgets.obs_size': 'Размер Browser Source',
    'widgets.obs_layout_overlay': 'компактный оверлей',
    'widgets.obs_layout_strip': 'полоса сцены',
    'widgets.obs_layout_fullscreen': 'на весь кадр',
    'widgets.bindings_empty': 'Биндингов для этого виджета нет — добавьте ниже.',
    'widgets.bindings_add': '+ Биндинг',
    'instr.title': 'Как добавить виджет в OBS',
    'instr.steps': '1. В OBS: Источники → + → «Браузер» (Browser Source)\n2. Вставь URL (ниже)\n3. Укажи рекомендованные ширину и высоту → ОК',
    'instr.size_note': 'Рекомендация указана для этого виджета; при необходимости подгони холст под сцену.',
    'instr.params': 'Параметры этого виджета',
    'instr.common_params': 'Общие параметры',
    'instr.transparent': 'Фон у виджета прозрачный — в OBS ничего включать не нужно. Правки HTML подхватываются без рестарта (F5 в OBS).',
});
Object.assign(LANGS.en, {
    'widgets.instr': '❓ Instructions',
    'widgets.obs_size': 'Browser Source size',
    'widgets.obs_layout_overlay': 'compact overlay',
    'widgets.obs_layout_strip': 'scene-wide strip',
    'widgets.obs_layout_fullscreen': 'full frame',
    'widgets.bindings_empty': 'No bindings for this widget yet — add one below.',
    'widgets.bindings_add': '+ Binding',
    'instr.title': 'How to add the widget to OBS',
    'instr.steps': '1. In OBS: Sources → + → Browser (Browser Source)\n2. Paste the URL (below)\n3. Enter the recommended width and height → OK',
    'instr.size_note': 'The recommendation is specific to this widget; adjust the canvas for your scene if needed.',
    'instr.params': 'This widget’s parameters',
    'instr.common_params': 'Common parameters',
    'instr.transparent': 'The widget background is transparent — nothing to enable in OBS. HTML edits apply without restart (F5 in OBS).',
});
Object.assign(LANGS.ua, {
    'widgets.instr': '❓ Інструкція',
    'widgets.obs_size': 'Розмір Browser Source',
    'widgets.obs_layout_overlay': 'компактний оверлей',
    'widgets.obs_layout_strip': 'смуга сцени',
    'widgets.obs_layout_fullscreen': 'на весь кадр',
    'widgets.bindings_empty': 'Біндингів для цього віджета немає — додайте нижче.',
    'widgets.bindings_add': '+ Біндинг',
    'instr.title': 'Як додати віджет в OBS',
    'instr.steps': '1. В OBS: Джерела → + → «Браузер» (Browser Source)\n2. Встав URL (нижче)\n3. Вкажи рекомендовані ширину й висоту → ОК',
    'instr.size_note': 'Рекомендація вказана для цього віджета; за потреби підгони полотно під сцену.',
    'instr.params': 'Параметри цього віджета',
    'instr.common_params': 'Спільні параметри',
    'instr.transparent': 'Фон у віджета прозорий — в OBS нічого вмикати не треба. Правки HTML підхоплюються без рестарту (F5 в OBS).',
});

// ── К3 → P8-C3: отношение ботов к стримеру ПЕРЕНЕСЕНО в карточку бота
// (вкладка «Роль», loadBotAttitude в 03_bots.js); здесь остаются только
// i18n-ключи. Негативные тона добавлены по вердикту владельца.
Object.assign(LANGS.ru, {
    'streamer.attitude_title': '💞 Отношение к стримеру',
    'streamer.attitude_hint': '«Все каналы» — глобальное отношение; ниже — отдельно по каналам. Нейтральное = ничего не меняет в поведении бота.',
    'streamer.attitude_global': '🌐 Все каналы',
    'streamer.attitude_saved': 'Отношение сохранено',
    'streamer.attitude_adore': '🥰 Обожает стримера',
    'streamer.attitude_friendly': '😊 Дружелюбно',
    'streamer.attitude_neutral': '😐 Нейтрально (по умолчанию)',
    'streamer.attitude_watching': '👀 Просто смотрит',
    'streamer.attitude_irritated': '😖 Раздражает',
    'streamer.attitude_intolerable': '😤 Не выносит',
    'streamer.attitude_dismissive': '🙄 Пренебрегает',
});
Object.assign(LANGS.en, {
    'streamer.attitude_title': '💞 Attitude to the streamer',
    'streamer.attitude_hint': '“All channels” is the global attitude; below — per channel. Neutral = no behavior change.',
    'streamer.attitude_global': '🌐 All channels',
    'streamer.attitude_saved': 'Attitude saved',
    'streamer.attitude_adore': '🥰 Adores the streamer',
    'streamer.attitude_friendly': '😊 Friendly',
    'streamer.attitude_neutral': '😐 Neutral (default)',
    'streamer.attitude_watching': '👀 Just watching',
    'streamer.attitude_irritated': '😖 Irritated',
    'streamer.attitude_intolerable': '😤 Can’t stand them',
    'streamer.attitude_dismissive': '🙄 Dismissive',
});
Object.assign(LANGS.ua, {
    'streamer.attitude_title': '💞 Ставлення до стрімера',
    'streamer.attitude_hint': '«Усі канали» — глобальне ставлення; нижче — окремо по каналах. Нейтральне = нічого не змінює в поведінці бота.',
    'streamer.attitude_global': '🌐 Усі канали',
    'streamer.attitude_saved': 'Ставлення збережено',
    'streamer.attitude_adore': '🥰 Обожнює стрімера',
    'streamer.attitude_friendly': '😊 Дружньо',
    'streamer.attitude_neutral': '😐 Нейтрально (за замовчуванням)',
    'streamer.attitude_watching': '👀 Просто дивиться',
    'streamer.attitude_irritated': '😖 Дратує',
    'streamer.attitude_intolerable': '😤 Не виносить',
    'streamer.attitude_dismissive': '🙄 Зневажає',
});

// ── Субатон (карточка, решение владельца 31.08) ──
async function loadSubathonCard() {
    if (!$('subathonPerSub')) return;
    try {
        const s = await wstateapi('/api/widgets/subathon');
        if ($('subathonPerSub')) $('subathonPerSub').value = s.seconds_per_sub ?? 60;
        if ($('subathonPerDonation')) $('subathonPerDonation').value = s.seconds_per_donation ?? 30;
        if ($('subathonPerCurrency')) $('subathonPerCurrency').value = s.seconds_per_currency ?? 0;
        const st = $('subathonStatus');
        if (st) st.textContent = s.running ? `▶ ${esc(t('subathon.running'))} · ${s.remaining ?? '—'} c` : `⏸ ${t('subathon.stopped')}`;
    } catch (e) { _waHint(e); }
}
async function saveSubathonRates() {
    try {
        await wstateapi('/api/widgets/subathon', 'PUT', {
            seconds_per_sub: parseInt($('subathonPerSub').value, 10) || 60,
            seconds_per_donation: parseInt($('subathonPerDonation').value, 10) || 30,
            seconds_per_currency: parseFloat($('subathonPerCurrency').value) || 0,
        });
        toast(t('msg.saved'), 'success');
    } catch (e) { _waHint(e); }
}
async function subathonStart() {
    try { await wstateapi('/api/widgets/subathon/start', 'POST', {}); await loadSubathonCard(); toast('▶', 'success'); }
    catch (e) { _waHint(e); }
}
async function subathonStop() {
    try { await wstateapi('/api/widgets/subathon/stop', 'POST', {}); await loadSubathonCard(); toast('⏸', 'info'); }
    catch (e) { _waHint(e); }
}
const _loadWidgetsAdminPrev5 = loadWidgetsAdmin;
loadWidgetsAdmin = async function() {
    await _loadWidgetsAdminPrev5();
    loadSubathonCard();
};

// ── i18n: субатон + grid-карточки новых виджетов (решение владельца 31.08) ──
Object.assign(LANGS.ru, {
    'subathon.hint': 'Таймер, который продлевается за подписки и донаты (DonatePay, DonateX, DonationAlerts, webhook). Добавь URL в OBS. Тарифы: за каждый саб и за донат — плоско секунд ИЛИ по сумме доната.',
    'subathon.per_sub': 'Секунд за 1 саб',
    'subathon.per_donation': 'Секунд за 1 донат (плоско)',
    'subathon.per_currency': 'Секунд за 1 единицу валюты (0 = плоско)',
    'subathon.running': 'идёт',
    'subathon.stopped': 'остановлен',
    'widgets.guide.follower-ticker.viewer': 'Бегущая строка с никами последних фолловеров.',
    'widgets.guide.follower-ticker.obs': 'Тонкая полоса — низ/верх экрана, 800×80.',
    'widgets.guide.donation-challenge.viewer': 'Прогресс-бар сбора: сколько собрано из цели.',
    'widgets.guide.donation-challenge.obs': 'Компактная плашка, 500×160.',
    'widgets.guide.emoji-chat.viewer': 'Сообщения чата, где слова заменяются эмодзи.',
    'widgets.guide.emoji-chat.obs': 'Колонка сообщений, 400×600; ?theme=, ?max=, ?channel=.',
    'widgets.guide.hype-meter.viewer': 'Шкала, заполняющаяся от активности чата.',
    'widgets.guide.hype-meter.obs': 'Горизонтальная шкала, 600×140; ?threshold=, ?window=.',
});
Object.assign(LANGS.en, {
    'subathon.hint': 'A timer extended by subscriptions and donations (DonatePay, DonateX, DonationAlerts, webhook). Add the URL to OBS. Rates: per sub and per donation — flat seconds OR by donation amount.',
    'subathon.per_sub': 'Seconds per 1 sub',
    'subathon.per_donation': 'Seconds per 1 donation (flat)',
    'subathon.per_currency': 'Seconds per 1 currency unit (0 = flat)',
    'subathon.running': 'running',
    'subathon.stopped': 'stopped',
    'widgets.guide.follower-ticker.viewer': 'A ticker strip with the latest followers’ nicknames.',
    'widgets.guide.follower-ticker.obs': 'Thin strip — bottom/top of the screen, 800×80.',
    'widgets.guide.donation-challenge.viewer': 'A fund progress bar: raised out of goal.',
    'widgets.guide.donation-challenge.obs': 'Compact bar, 500×160.',
    'widgets.guide.emoji-chat.viewer': 'Chat messages where words turn into emojis.',
    'widgets.guide.emoji-chat.obs': 'Message column, 400×600; ?theme=, ?max=, ?channel=.',
    'widgets.guide.hype-meter.viewer': 'A meter filling up from chat activity.',
    'widgets.guide.hype-meter.obs': 'Horizontal meter, 600×140; ?threshold=, ?window=.',
});
Object.assign(LANGS.ua, {
    'subathon.hint': 'Таймер, що подовжується за підписки та донати (DonatePay, DonateX, DonationAlerts, webhook). Додай URL в OBS. Тарифи: за кожен саб і за донат — плоско секунд АБО за сумою донату.',
    'subathon.per_sub': 'Секунд за 1 саб',
    'subathon.per_donation': 'Секунд за 1 донат (плоско)',
    'subathon.per_currency': 'Секунд за 1 одиницю валюти (0 = плоско)',
    'subathon.running': 'триває',
    'subathon.stopped': 'зупинено',
    'widgets.guide.follower-ticker.viewer': 'Біжучий рядок з нікнеймами останніх фоловерів.',
    'widgets.guide.follower-ticker.obs': 'Тонка смуга — низ/верх екрана, 800×80.',
    'widgets.guide.donation-challenge.viewer': 'Прогрес-бар збору: скільки зібрано з цілі.',
    'widgets.guide.donation-challenge.obs': 'Компактна плашка, 500×160.',
    'widgets.guide.emoji-chat.viewer': 'Повідомлення чату, де слова перетворюються на емодзі.',
    'widgets.guide.emoji-chat.obs': 'Колонка повідомлень, 400×600; ?theme=, ?max=, ?channel=.',
    'widgets.guide.hype-meter.viewer': 'Шкала, що заповнюється від активності чату.',
    'widgets.guide.hype-meter.obs': 'Горизонтальна шкала, 600×140; ?threshold=, ?window=.',
});

