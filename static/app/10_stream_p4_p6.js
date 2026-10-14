// [P5-split] 10_stream_p4_p6.js ← static/app.js, исходные строки 6889–7421; грузится после предыдущего чанка, порядок = порядку строк

// ── §7 фаза 3: конвейер запикивания (beep_pipeline) ──
async function loadBeepPipeline() {
    const box = $('beepPipelineCard');
    if (!box) return;
    try {
        const r = await api('/api/beep-pipeline');
        const cfg = r.config || {}, st = r.status || {};
        setToggle('bpEnabled', !!st.running);
        if ($('bpSource')) $('bpSource').value = cfg.pulse_source || 'default';
        if ($('bpSink')) $('bpSink').value = cfg.sink_name || 'bot_beep_out';
        if ($('bpHz')) $('bpHz').value = cfg.beep_hz ?? 1000;
        if ($('bpSeg')) $('bpSeg').value = cfg.segment_sec ?? 5;
        const stEl = $('bpStatus');
        if (stEl) stEl.textContent = st.running
            ? `${t('bp.status_on')} · ${st.chunks_done ?? 0} ${t('bp.chunks')} · 🔇 ${st.beeps ?? 0}`
            : t('bp.status_off');
        if ($('bpWhisperWarn')) $('bpWhisperWarn').textContent = st.has_whisper ? '' : t('bp.no_whisper');
    } catch (e) { /* карточка не критична */ }
}

async function saveBeepPipeline() {
    try {
        await api('/api/beep-pipeline', jopts('PUT', {
            pulse_source: $('bpSource')?.value.trim() || 'default',
            sink_name: $('bpSink')?.value.trim() || 'bot_beep_out',
            beep_hz: parseInt($('bpHz')?.value, 10) || 1000,
            segment_sec: parseInt($('bpSeg')?.value, 10) || 5,
        }));
        toast(t('msg.saved'), 'success');
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function toggleBeepPipeline() {
    const on = $('bpEnabled')?.classList.contains('active');
    try {
        if (on) {
            await api('/api/beep-pipeline/stop', jopts('POST', {}));
            toast(t('bp.stopped'), 'info');
        } else {
            await saveBeepPipeline();
            await api('/api/beep-pipeline/start', jopts('POST', {}));
            toast(t('bp.started'), 'success');
        }
        await loadBeepPipeline();
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); await loadBeepPipeline(); }
}

Object.assign(LANGS.ru, {
    'bp.title': '🔇 Запикивание матов (фаза 3)',
    'bp.hint': 'Слушает источник звука (укажи свой микрофон/микс из Pulse), режет его на сегменты, ищет мат через Whisper и словари — найденное заменяет пипом и выводит всё в виртуальный sink, который бери в OBS («Устройство вывода» = monitor этого sink). Пип отстаёт от эфира на ~5–10 сек — включи задержку трансляции в OBS. Whisper не установлен → звук идёт без пипов (pass-through).',
    'bp.source': 'Источник звука (pactl name)',
    'bp.sink': 'Виртуальный sink (вывод в OBS)',
    'bp.hz': 'Частота пипа, Гц',
    'bp.seg': 'Сегмент, сек (2–15)',
    'bp.status_on': 'работает',
    'bp.status_off': 'pass-through (звук идёт без обработки)',
    'bp.chunks': 'сегментов',
    'bp.no_whisper': '⚠ Whisper не установлен (pip install openai-whisper) — работает pass-through: звук без пипов.',
    'bp.started': 'Конвейер запущен',
    'bp.stopped': 'Конвейер остановлен',
});
Object.assign(LANGS.en, {
    'bp.title': '🔇 Swear beep pipeline (phase 3)',
    'bp.hint': 'Listens to a Pulse source, slices it into segments, detects swear words via Whisper + dictionaries — beeps them and outputs to a virtual sink which you add in OBS as a monitor device. Beep lags the live feed by ~5–10 s — enable broadcast delay in OBS. No Whisper → pass-through (no beeps).',
    'bp.source': 'Audio source (pactl name)',
    'bp.sink': 'Virtual sink (output to OBS)',
    'bp.hz': 'Beep frequency, Hz',
    'bp.seg': 'Segment, sec (2–15)',
    'bp.status_on': 'running',
    'bp.status_off': 'pass-through (audio goes through untreated)',
    'bp.chunks': 'segments',
    'bp.no_whisper': '⚠ Whisper is not installed (pip install openai-whisper) — pass-through: audio without beeps.',
    'bp.started': 'Pipeline started',
    'bp.stopped': 'Pipeline stopped',
});
Object.assign(LANGS.ua, {
    'bp.title': '🔇 Запикання матів (фаза 3)',
    'bp.hint': 'Слухає джерело звуку (вкажи свій мікрофон/мікс з Pulse), ріже на сегменти, шукає мат через Whisper і словники — знайдене замінює піпом і виводить усе у віртуальний sink, який бери в OBS («Пристрій виводу» = monitor цього sink). Піп відстає від ефіру на ~5–10 сек — увімкни затримку трансляції в OBS. Whisper не встановлено → звук іде без піпів (pass-through).',
    'bp.source': 'Джерело звуку (pactl name)',
    'bp.sink': 'Віртуальний sink (вивід в OBS)',
    'bp.hz': 'Частота піпа, Гц',
    'bp.seg': 'Сегмент, сек (2–15)',
    'bp.status_on': 'працює',
    'bp.status_off': 'pass-through (звук іде без обробки)',
    'bp.chunks': 'сегментів',
    'bp.no_whisper': '⚠ Whisper не встановлено (pip install openai-whisper) — pass-through: звук без піпів.',
    'bp.started': 'Конвеєр запущено',
    'bp.stopped': 'Конвеєр зупинено',
});

// ==================== P4 PLAN.md: блюр по зонам (blur-guard-v2, always-on 100%) ====================

function buildBlurZonesUrl() {
    const list = ($('blurZonesList')?.value || '').split('\n').map(s => s.trim()).filter(Boolean);
    const zones = list.map(z => z.replace(/\s+/g, '')).join(';');
    const url = `${location.origin}/obs/blur-guard-v2?zones=${encodeURIComponent(zones)}`;
    if ($('blurZonesUrl')) $('blurZonesUrl').textContent = url;
    return url;
}

// P8-W1: живое применение зон — blur-guard-v2 в OBS обновится по WS,
// URL пересобирать не обязательно (зоны теперь ещё и в настройках).
async function applyBlurZonesLive() {
    const url = buildBlurZonesUrl();
    const zones = decodeURIComponent((url.split('zones=')[1] || ''));
    try {
        await api('/api/blur-guard', jopts('PUT', { always_zones: zones }));
        toast(t('blur_zones.applied'), 'success');
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

Object.assign(LANGS.ru, {
    'blur_zones.title': '📍 Блюр по зонам (всегда 100%)',
    'blur_zones.badge': 'beta · blur-guard-v2',
    'blur_zones.hint': 'Блюрить не весь экран, а выбранные области (код, поле пароля) — они закрыты ПОСТОЯННО, без «ослабления». Формат: x,y,w,h через точку с запятой; можно px или проценты (например 25%,40%). Координаты — левый верхний угол зоны.',
    'blur_zones.list': 'Зоны (одна строка = одна зона)',
    'blur_zones.apply': '⚡ Применить сейчас (по WS)',
    'blur_zones.build': '🔗 Собрать URL для OBS',
    'blur_zones.applied': 'Зоны применены — оверлеи обновились',
    'blur_zones.open': 'Открыть превью',
    'blur_zones.note': 'Заметка: это отдельный виджет blur-guard-v2 (в OBS добавь его URL отдельным Browser Source). Реактивный блюр по AI-анализу работает в нём так же, зоны просто накладываются сверху всегда.',
});
Object.assign(LANGS.en, {
    'blur_zones.title': '📍 Blur zones (always 100%)',
    'blur_zones.badge': 'beta · blur-guard-v2',
    'blur_zones.hint': 'Blur only selected areas (code, password field) — they stay covered CONSTANTLY, no “weakening”. Format: x,y,w,h semicolon-separated; px or percent (e.g. 25%,40%). Coordinates = top-left corner.',
    'blur_zones.list': 'Zones (one line = one zone)',
    'blur_zones.apply': '⚡ Apply now (via WS)',
    'blur_zones.build': '🔗 Build OBS URL',
    'blur_zones.applied': 'Zones applied — overlays updated',
    'blur_zones.open': 'Open preview',
    'blur_zones.note': 'Note: this is a separate blur-guard-v2 widget (add its URL as a separate Browser Source). AI-reactive blur works the same there; zones are simply overlaid on top, always.',
});
Object.assign(LANGS.ua, {
    'blur_zones.title': '📍 Блюр по зонах (завжди 100%)',
    'blur_zones.badge': 'beta · blur-guard-v2',
    'blur_zones.hint': 'Блюрити не весь екран, а вибрані області (код, поле пароля) — вони закриті ПОСТІЙНО, без «ослаблення». Формат: x,y,w,h через крапку з комою; можна px або відсотки (наприклад 25%,40%). Координати — лівий верхній кут зони.',
    'blur_zones.list': 'Зони (один рядок = одна зона)',
    'blur_zones.apply': '⚡ Застосувати зараз (по WS)',
    'blur_zones.build': '🔗 Зібрати URL для OBS',
    'blur_zones.applied': 'Зони застосовано — оверлеї оновились',
    'blur_zones.open': 'Відкрити превʼю',
    'blur_zones.note': 'Примітка: це окремий віджет blur-guard-v2 (додай його URL окремим Browser Source). Реактивний блюр по AI працює так само, зони просто накладаються завжди.',
});

// ==================== P4 PLAN.md: TTS за баллы канала (UI) ====================

function _cpTtsBotId() {
    const v = document.getElementById('cpTtsBot')?.value;
    return v ? parseInt(v, 10) : (_allBots.find(b => b.enabled)?.id ?? _allBots[0]?.id ?? 0);
}

function _cpTtsSetToggle(id, on) {
    const el = $(id);
    if (el) el.classList.toggle('active', !!on);
}

let _cpTtsVoiceCatalog = [];

function _cpTtsLang() {
    return (typeof localStorage !== 'undefined' && localStorage.getItem('lang')) || 'ru';
}

function _cpTtsPopulateVoices(selected = '', provider = '', query = '') {
    const select = $('cpTtsVoice');
    if (!select) return;
    const lang = _cpTtsLang();
    const needle = query.trim().toLowerCase();
    const match = _cpTtsVoiceCatalog.find(voice => voice.voice_id === selected && (!provider || voice.provider === provider));
    const visible = _cpTtsVoiceCatalog.filter(voice => voice === match || !needle || [voice.provider, voice.voice_id, voice.label, voice.language].join(' ').toLowerCase().includes(needle));
    select.innerHTML = `<option value="">${esc(t('cp_tts.voice_fallback'))}</option>` + visible.map(voice =>
        `<option value="${esc(voice.key)}">${esc((voice.labels || {})[lang] || voice.label)}${voice.language ? ` · ${esc(voice.language)}` : ''}</option>`
    ).join('');
    select.value = match?.key || '';
    if ($('cpTtsVoiceAdvanced')) $('cpTtsVoiceAdvanced').value = match ? '' : selected;
    cpTtsVoiceSelected();
}

async function _cpTtsLoadVoiceCatalog(selected = '', provider = '') {
    try {
        const data = await api('/api/tts/voice-catalog');
        _cpTtsVoiceCatalog = data.voices || [];
    } catch (e) { console.error('cp TTS voice catalog', e); }
    _cpTtsPopulateVoices(selected, provider);
}

function cpTtsFilterVoiceCatalog() {
    const selected = _cpTtsVoiceCatalog.find(voice => voice.key === $('cpTtsVoice')?.value);
    _cpTtsPopulateVoices(selected?.voice_id || '', selected?.provider || '', $('cpTtsVoiceSearch')?.value || '');
}

function cpTtsVoiceSelected() {
    const selected = _cpTtsVoiceCatalog.find(voice => voice.key === $('cpTtsVoice')?.value);
    if ($('cpTtsVoiceMeta')) $('cpTtsVoiceMeta').textContent = selected
        ? ((selected.license || {})[_cpTtsLang()] || t('cp_tts.voice_fallback'))
        : t('cp_tts.voice_fallback');
    if (selected && $('cpTtsVoiceAdvanced')) $('cpTtsVoiceAdvanced').value = '';
}

function cpTtsVoiceAdvancedChanged() {
    if ($('cpTtsVoiceAdvanced')?.value.trim() && $('cpTtsVoice')) $('cpTtsVoice').value = '';
    cpTtsVoiceSelected();
}

function _cpTtsVoicePayload() {
    const selected = _cpTtsVoiceCatalog.find(voice => voice.key === $('cpTtsVoice')?.value);
    const advanced = $('cpTtsVoiceAdvanced')?.value.trim() || '';
    return { voice: advanced || selected?.voice_id || '', voice_provider: advanced ? '' : (selected?.provider || '') };
}

async function loadChannelPointsTts() {
    const sel = $('cpTtsBot');
    if (!sel) return;
    if (_allBots?.length && !sel.options.length) {
        sel.innerHTML = _allBots.map(b =>
            `<option value="${b.id}">${esc(b.nickname)}${b.enabled ? '' : ' (выкл)'}</option>`).join('');
        const pref = _allBots.find(b => b.enabled);
        if (pref) sel.value = String(pref.id);
    }
    const id = _cpTtsBotId();
    if (!id) return;
    try {
        const res = await api(`/api/channel-points-tts/${id}`);
        const c = res.config || {};
        _cpTtsSetToggle('cpTtsEnabled', c.enabled);
        _cpTtsSetToggle('cpTtsAnnounce', c.announce_user);
        if ($('cpTtsRewards')) $('cpTtsRewards').value = c.reward_names || '';
        if ($('cpTtsMaxLen')) $('cpTtsMaxLen').value = c.max_len ?? 120;
        if ($('cpTtsCooldown')) $('cpTtsCooldown').value = c.cooldown_sec ?? 5;
        if ($('cpTtsMaxHour')) $('cpTtsMaxHour').value = c.max_per_hour ?? 10;
        if ($('cpTtsBlacklist')) $('cpTtsBlacklist').value = c.blacklist || '';
        if ($('cpTtsChannel')) $('cpTtsChannel').value = c.channel || '';
        await _cpTtsLoadVoiceCatalog(c.voice || '', c.voice_provider || '');
    } catch (e) { console.error('loadChannelPointsTts', e); }
}

async function saveChannelPointsTts() {
    const id = _cpTtsBotId();
    if (!id) return toast(t('bots.empty'), 'error');
    try {
        await api(`/api/channel-points-tts/${id}`, jopts('PUT', {
            enabled: toggleChecked('cpTtsEnabled') ? 1 : 0,
            announce_user: toggleChecked('cpTtsAnnounce') ? 1 : 0,
            reward_names: $('cpTtsRewards')?.value.trim() || '',
            max_len: parseInt($('cpTtsMaxLen')?.value, 10) || 120,
            cooldown_sec: parseInt($('cpTtsCooldown')?.value, 10) || 0,
            max_per_hour: parseInt($('cpTtsMaxHour')?.value, 10) || 10,
            blacklist: $('cpTtsBlacklist')?.value.trim() || '',
            channel: $('cpTtsChannel')?.value.trim() || '',
            ..._cpTtsVoicePayload(),
        }));
        toast(t('msg.saved'), 'success');
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function testChannelPointsTts() {
    const id = _cpTtsBotId();
    const text = $('cpTtsTestText')?.value.trim();
    const channel = $('cpTtsChannel')?.value.trim() || '';
    if (!id || !text) return toast(t('cp_tts.err_empty'), 'error');
    if (!channel) return toast(t('chat.select_channel'), 'error');
    try {
        await api(`/api/channel-points-tts/${id}/test`, jopts('POST', {
            text, channel, ..._cpTtsVoicePayload(),
        }));
        toast(t('cp_tts.test_sent'), 'success');
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

Object.assign(LANGS.ru, {
    'cp_tts.title': '🎙 TTS за баллы канала',
    'cp_tts.hint': 'Зритель тратит баллы канала на награду-активацию (например «Озвучить сообщение») — его текст озвучивается в OBS через TTS-движок бота. Создай награду в Twitch → Creator Dashboard → Rewards. Названия через запятую; пусто = озвучивать ЛЮБУЮ награду с текстом. Требуется включённый TTS-движок.',
    'cp_tts.bot': 'Legacy-бот', 'cp_tts.channel': 'Канал Twitch', 'cp_tts.voice': 'Голос награды',
    'cp_tts.voice_fallback': 'Не переопределять: голос TTS бота', 'cp_tts.voice_advanced': 'Дополнительно: legacy ID голоса', 'cp_tts.voice_search': 'Поиск голоса', 'cp_tts.voice_advanced_ph': 'ru-RU / ID голоса',
    'cp_tts.reward_names': 'Названия наград (через запятую, пусто = все)',
    'cp_tts.max_len': 'Макс. длина (симв.)',
    'cp_tts.cooldown': 'Cooldown юзера (сек)',
    'cp_tts.max_hour': 'Макс./час юзеру',
    'cp_tts.blacklist': 'Чёрный список слов (через запятую)',
    'cp_tts.announce': 'Говорить «Говорит Nick:»',
    'cp_tts.test_label': 'Тест (озвучить прямо сейчас)',
    'cp_tts.test': '🔊 Тест',
    'cp_tts.err_empty': 'Введите текст для теста',
    'cp_tts.test_sent': 'Отправлено в очередь озвучки — слушай OBS',
});
Object.assign(LANGS.en, {
    'cp_tts.title': '🎙 TTS for channel points',
    'cp_tts.hint': 'A viewer spends channel points on an activation reward (e.g. “Read my message”) — the text is voiced in OBS via the bot TTS engine. Create the reward in Twitch → Creator Dashboard → Rewards. Names comma-separated; empty = voice ANY reward with text. Requires the TTS engine enabled.',
    'cp_tts.bot': 'Legacy bot', 'cp_tts.channel': 'Twitch channel', 'cp_tts.voice': 'Reward voice',
    'cp_tts.voice_fallback': 'Do not override: bot TTS voice', 'cp_tts.voice_advanced': 'Advanced: legacy voice ID', 'cp_tts.voice_search': 'Search voices', 'cp_tts.voice_advanced_ph': 'en-US / voice ID',
    'cp_tts.reward_names': 'Reward names (comma-separated, empty = all)',
    'cp_tts.max_len': 'Max length (chars)',
    'cp_tts.cooldown': 'User cooldown (sec)',
    'cp_tts.max_hour': 'Max per hour per user',
    'cp_tts.blacklist': 'Blacklist words (comma-separated)',
    'cp_tts.announce': 'Say “Nick says:”',
    'cp_tts.test_label': 'Test (speak now)',
    'cp_tts.test': '🔊 Test',
    'cp_tts.err_empty': 'Enter test text',
    'cp_tts.test_sent': 'Queued for voicing — listen in OBS',
});
Object.assign(LANGS.ua, {
    'cp_tts.title': '🎙 TTS за бали каналу',
    'cp_tts.hint': 'Глядач витрачає бали каналу на нагороду-активацію (наприклад «Озвучити повідомлення») — його текст озвучується в OBS через TTS-двигун бота. Створи нагороду в Twitch → Creator Dashboard → Rewards. Назви через кому; пусто = озвучувати БУДЬ-ЯКУ нагороду з текстом. Потрібен увімкнений TTS-двигун.',
    'cp_tts.bot': 'Legacy-бот', 'cp_tts.channel': 'Канал Twitch', 'cp_tts.voice': 'Голос нагороди',
    'cp_tts.voice_fallback': 'Не перевизначати: голос TTS бота', 'cp_tts.voice_advanced': 'Додатково: legacy ID голосу', 'cp_tts.voice_search': 'Пошук голосу', 'cp_tts.voice_advanced_ph': 'uk-UA / ID голосу',
    'cp_tts.reward_names': 'Назви нагород (через кому, пусто = всі)',
    'cp_tts.max_len': 'Макс. довжина (симв.)',
    'cp_tts.cooldown': 'Cooldown юзера (сек)',
    'cp_tts.max_hour': 'Макс./год юзеру',
    'cp_tts.blacklist': 'Чорний список слів (через кому)',
    'cp_tts.announce': 'Казати «Говорить Nick:»',
    'cp_tts.test_label': 'Тест (озвучити зараз)',
    'cp_tts.test': '🔊 Тест',
    'cp_tts.err_empty': 'Введіть текст для тесту',
    'cp_tts.test_sent': 'Відправлено в чергу озвучки — слухай OBS',
});

// ==================== P6 PLAN.md: TTS-чат (озвучки) — карточка виджета ====================

function _ttsChatQuery() {
    const filter = $('ttsChatFilter')?.value || 'all';
    const hide = $('ttsChatHide')?.value || '30000';
    const max = $('ttsChatMax')?.value || '5';
    const color = ($('ttsChatColor')?.value || '').trim();
    let q = [];
    q.push(`filter=${filter}`);
    q.push(`retain_ms=${hide}`);
    q.push(`max_msgs=${max}`);
    if (color) q.push(`color=${encodeURIComponent(color)}`);
    return q.join('&');
}

function buildTtsChatUrl() {
    const url = `${location.origin}/widget/tts-chat-overlay?${_ttsChatQuery()}`;
    if ($('ttsChatUrl')) $('ttsChatUrl').textContent = url;
    return url;
}

function copyTtsChatUrl() {
    navigator.clipboard.writeText(buildTtsChatUrl()).then(() => toast(t('toast.copied'), 'success'));
}

async function loadTtsChatCard() {
    if ($('ttsChatFilter')) buildTtsChatUrl();
}

Object.assign(LANGS.ru, {
    'tts_chat.title': '💬 TTS-чат (озвучки)',
    'tts_chat.hint': 'Отдельный чат для озвучек: показывает строку «как в обычном чате» — кто говорит (бот или зритель, озвучивший сообщение за баллы) и что говорит. Каждое сообщение скрывается через выбранное время. Выведи URL в OBS как Browser Source.',
    'tts_chat.bot': 'Бот', 'tts_chat.filter': 'Какие озвучки показывать',
    'tts_chat.hide': 'Скрывать сообщение через',
    'tts_chat.max': 'Макс. сообщений',
    'tts_chat.color': 'Цвет акцента',
    'tts_chat.url': 'URL для OBS',
});
Object.assign(LANGS.en, {
    'tts_chat.title': '💬 TTS chat (voicelines)',
    'tts_chat.hint': 'A separate chat for voicelines: shows a regular-chat-style line — who is speaking (bot or viewer who redeemed a voicing) and what they say. Each message hides after the chosen time. Put the URL into OBS as a Browser Source.',
    'tts_chat.bot': 'Bot', 'tts_chat.filter': 'Voicelines to show',
    'tts_chat.hide': 'Hide message after',
    'tts_chat.max': 'Max messages',
    'tts_chat.color': 'Accent color',
    'tts_chat.url': 'URL for OBS',
});
Object.assign(LANGS.ua, {
    'tts_chat.title': '💬 TTS-чат (озвучки)',
    'tts_chat.hint': 'Окремий чат для озвучок: показує рядок «як у звичайному чаті» — хто говорить (бот або глядач, що озвучив повідомлення за бали) і що говорить. Кожне повідомлення ховається через обраний час. Встав URL в OBS як Browser Source.',
    'tts_chat.bot': 'Бот', 'tts_chat.filter': 'Які озвучки показувати',
    'tts_chat.hide': 'Ховати повідомлення через',
    'tts_chat.max': 'Макс. повідомлень',
    'tts_chat.color': 'Колір акценту',
    'tts_chat.url': 'URL для OBS',
});

// ==================== PLAN_REMAINING P1: §R3 стрим-инструменты (UI) ====================

const STREAM_TOOL_ORDER = ['category', 'ai_category', 'title', 'slow', 'follower', 'emote_only', 'unique'];
const STREAM_TOOL_LABELS = {
    ru: {
        category: 'Категория', ai_category: 'Категория (AI)', title: 'Название',
        slow: 'Slow-режим', follower: 'Фоллоу-режим', emote_only: 'Только эмодзи', unique: 'Уникальный чат',
    },
    en: {
        category: 'Category', ai_category: 'Category (AI)', title: 'Title',
        slow: 'Slow mode', follower: 'Follower mode', emote_only: 'Emote only', unique: 'Unique chat',
    },
    ua: {
        category: 'Категорія', ai_category: 'Категорія (AI)', title: 'Назва',
        slow: 'Slow-режим', follower: 'Фолов-режим', emote_only: 'Тільки емодзі', unique: 'Унікальний чат',
    },
};
const STREAM_MODE_LABELS = {
    ru: { off: 'Выкл', suggest: 'Предлагать', auto: 'Авто' },
    en: { off: 'Off', suggest: 'Suggest', auto: 'Auto' },
    ua: { off: 'Вимк', suggest: 'Пропонувати', auto: 'Авто' },
};

function _stLang() {
    return (typeof localStorage !== 'undefined' && localStorage.getItem('lang')) || 'ru';
}

async function loadStreamTools(id) {
    if (!id) return;
    const modesEl = $('streamToolsModes');
    if (!modesEl) return;
    // P8-A3: у не-модератора прячем мёртвую форму целиком — остаётся одна строка
    const _setFormVisible = (visible) => {
        ['streamToolsManual', 'streamToolsHistoryHead', 'streamToolsHistory'].forEach(elm => {
            const node = $(elm);
            if (node) node.classList.toggle('hidden', !visible);
        });
    };
    try {
        const data = await api(`/api/stream-intents/modes?account_id=${id}`);
        if (!data.ok) {
            modesEl.innerHTML = `<div class="text-muted text-sm">${esc(t('stream_tools.not_moderator'))}</div>`;
            _setFormVisible(false);
            const h = $('streamToolsHistory');
            if (h) h.innerHTML = '';
            return;
        }
        _setFormVisible(true);
        const lang = _stLang();
        const modes = data.modes || {};
        modesEl.innerHTML = STREAM_TOOL_ORDER.map(tool => {
            const cur = modes[tool] || 'off';
            const opts = ['off', 'suggest', 'auto'].map(m =>
                `<option value="${m}" ${m === cur ? 'selected' : ''}>${esc(STREAM_MODE_LABELS[lang][m] || m)}</option>`).join('');
            return `<div class="flex gap-2 items-center text-sm">
                <span style="min-width:170px">${esc(STREAM_TOOL_LABELS[lang][tool] || tool)}</span>
                <select class="input select-140" onchange="saveStreamToolMode('${tool}', this.value)">${opts}</select>
                <span class="text-muted text-xs">${esc((data.scopes && data.scopes[tool]) || '')}</span>
            </div>`;
        }).join('');
        loadStreamToolsHistory(id);
    } catch (e) {
        modesEl.innerHTML = `<div class="text-error text-sm">${esc(t('empty.load_failed', { detail: e.message }))}</div>`;
    }
}

async function saveStreamToolMode(tool, mode) {
    if (!_currentBotId) return;
    try {
        const cfgRes = await api(`/api/accounts/${_currentBotId}/role-config`);
        const cfg = { ...((cfgRes.configs || {}).moderator || {}) };
        cfg.stream_tool_modes = { ...(cfg.stream_tool_modes || {}), [tool]: mode };
        const res = await api(`/api/accounts/${_currentBotId}/role-config`, jopts('PUT', { role: 'moderator', config: cfg }));
        if (!res.ok) throw new Error(res.error || 'error');
        toast(t('msg.saved'), 'success');
    } catch (e) {
        toast(t('toast.error_detail', { detail: e.message }), 'error');
        loadStreamTools(_currentBotId);
    }
}

const STREAM_ERR_KEYS = {
    disabled: 'stream_tools.err_disabled',
    not_moderator: 'stream_tools.err_not_moderator',
    unknown_tool: 'stream_tools.err_unknown_tool',
    no_channel: 'stream_tools.err_no_channel',
    dedup: 'stream_tools.err_dedup',
    helix_not_configured: 'stream_tools.err_helix_not_configured',
};

async function proposeStreamAction(tool, params) {
    if (!_currentBotId) return;
    try {
        const res = await api('/api/stream-intents/propose', jopts('POST', {
            account_id: _currentBotId, tool, params,
        }));
        if (!res.ok) {
            toast(t(STREAM_ERR_KEYS[res.error] || 'stream_tools.err_other', { detail: res.error || '' }), 'error');
            return;
        }
        toast(t(res.mode === 'suggest' ? 'stream_tools.proposed_suggest' : 'stream_tools.proposed_auto'), 'success');
        loadStreamToolsHistory(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

function proposeStreamTitle() {
    const v = $('stTitleInput')?.value.trim();
    if (!v) return toast(t('stream_tools.err_empty'), 'error');
    if ($('stTitleInput')) $('stTitleInput').value = '';
    proposeStreamAction('title', { title: v });
}

function proposeStreamCategory() {
    const v = $('stCategoryInput')?.value.trim();
    if (!v) return toast(t('stream_tools.err_empty'), 'error');
    if ($('stCategoryInput')) $('stCategoryInput').value = '';
    proposeStreamAction('category', { game_name: v });
}

const STREAM_DECISION_LABELS = {
    ru: { pending: 'ожидает одобрения', approved: 'одобрено', auto: 'авто' },
    en: { pending: 'awaiting approval', approved: 'approved', auto: 'auto' },
    ua: { pending: 'очікує одобрення', approved: 'одобрено', auto: 'авто' },
};

async function loadStreamToolsHistory(id) {
    const el = $('streamToolsHistory');
    if (!el || !id) return;
    try {
        const data = await api(`/api/stream-intents/history?account_id=${id}&limit=50`);
        const lang = _stLang();
        el.innerHTML = (data.items || []).map(it => {
            let tool = '', params = {}, decision = '', ok = null, err = '';
            if (it.details && typeof it.details === 'object') {
                tool = it.details.tool || '';
                params = it.details.params || {};
                decision = it.details.decision || '';
                ok = it.details.result ? it.details.result.ok : null;
                err = (it.details.result && it.details.result.error) || '';
            }
            const cls = ok === false ? 'text-error' : '';
            const decisionBadge = decision ? ` · ${esc(STREAM_DECISION_LABELS[lang][decision] || decision)}` : '';
            const errTxt = err ? ` — ${esc(err.slice(0, 80))}` : '';
            return `<div class="flex gap-2 items-center text-sm">
                <span class="text-muted">${esc((it.created_at || '').replace('T', ' ').slice(5, 16))}</span>
                <span class="badge">${esc(STREAM_TOOL_LABELS[lang][tool] || tool || '?')}</span>
                <span class="${cls}">${esc(it.message || '')}${decisionBadge}${errTxt}</span>
            </div>`;
        }).join('') || `<div class="text-muted text-sm">${esc(t('stream_tools.history_empty'))}</div>`;
    } catch (e) { console.error('loadStreamToolsHistory', e); }
}

Object.assign(LANGS.ru, {
    'stream_tools.title': '🛠 Стрим-инструменты',
    'stream_tools.hint': 'Бот-модератор может предлагать действия для стрима: сменить категорию и название, переключить slow/фоллоу/эмодзи/уникальный чат. off — выключено, suggest — предложение в mod-feed с кнопкой «Одобрить», auto — исполнять сразу.',
    'stream_tools.manual_title': '✋ Предложить вручную',
    'stream_tools.title_label': 'Название стрима',
    'stream_tools.category_label': 'Категория (игра)',
    'stream_tools.suggest_btn': 'Отправить предложение',
    'stream_tools.history_title': '🕘 История действий',
    'stream_tools.history_empty': 'Действий пока не было.',
    'stream_tools.not_moderator': 'Этот бот не модератор — стрим-инструменты недоступны.',
    'stream_tools.proposed_suggest': 'Предложение отправлено в mod-feed — одобрите его там',
    'stream_tools.proposed_auto': 'Действие выполнено',
    'stream_tools.err_empty': 'Введите значение',
    'stream_tools.err_disabled': 'Инструмент выключен (off) — включите режим suggest/auto выше',
    'stream_tools.err_not_moderator': 'Бот не модератор',
    'stream_tools.err_unknown_tool': 'Неизвестный инструмент',
    'stream_tools.err_no_channel': 'У бота нет каналов',
    'stream_tools.err_helix_not_configured': 'Helix не настроен (Client-ID/токен)',
    'stream_tools.err_other': 'Ошибка: {detail}',
    'stream_tools.err_dedup': 'Такое предложение уже висит в фиде',
    'btn.download': '📥 Скачать',
    'settings.panel_log_tail': '📋 Последние логи',
    'settings.panel_log_tail_hint': 'Хвост panel.log — ошибки, запуск, события панели.',
    'widgets.preset_applied': 'Пресет «{name}» применён',
    'settings.twitch_check': '🔌 Проверить подключение',
    'settings.twitch_check_hint': 'Проверка выполняется от первого включённого бота (нужен его OAuth-токен).',
    'settings.twitch_check_ok': 'Подключение к Twitch OK — {name}',
    'bots.empty': 'Сначала добавьте бота',
});
Object.assign(LANGS.en, {
    'stream_tools.title': '🛠 Stream tools',
    'stream_tools.hint': 'The moderator bot can propose stream actions: change category and title, toggle slow/follower/emote/unique chat. off — disabled, suggest — proposal in mod-feed with an Approve button, auto — execute immediately.',
    'stream_tools.manual_title': '✋ Propose manually',
    'stream_tools.title_label': 'Stream title',
    'stream_tools.category_label': 'Category (game)',
    'stream_tools.suggest_btn': 'Send proposal',
    'stream_tools.history_title': '🕘 Action history',
    'stream_tools.history_empty': 'No actions yet.',
    'stream_tools.not_moderator': 'This bot is not a moderator — stream tools unavailable.',
    'stream_tools.proposed_suggest': 'Proposal sent to mod-feed — approve it there',
    'stream_tools.proposed_auto': 'Action executed',
    'stream_tools.err_empty': 'Enter a value',
    'stream_tools.err_disabled': 'Tool is off — switch it to suggest/auto above',
    'stream_tools.err_not_moderator': 'Bot is not a moderator',
    'stream_tools.err_unknown_tool': 'Unknown tool',
    'stream_tools.err_no_channel': 'Bot has no channels',
    'stream_tools.err_helix_not_configured': 'Helix is not configured (Client-ID/token)',
    'stream_tools.err_other': 'Error: {detail}',
    'stream_tools.err_dedup': 'Such a proposal is already pending in the feed',
    'btn.download': '📥 Download',
    'settings.panel_log_tail': '📋 Recent logs',
    'settings.panel_log_tail_hint': 'Tail of panel.log — errors, startup, panel events.',
    'widgets.preset_applied': 'Preset «{name}» applied',
    'settings.twitch_check': '🔌 Test connection',
    'settings.twitch_check_hint': 'The check runs as the first enabled bot (its OAuth token is used).',
    'settings.twitch_check_ok': 'Twitch connection OK — {name}',
    'bots.empty': 'Add a bot first',
});
Object.assign(LANGS.ua, {
    'stream_tools.title': '🛠 Стрім-інструменти',
    'stream_tools.hint': 'Бот-модератор може пропонувати дії для стріму: змінити категорію та назву, перемкнути slow/фолов/емодзі/унікальний чат. off — вимкнено, suggest — пропозиція в mod-feed з кнопкою «Одобрити», auto — виконувати одразу.',
    'stream_tools.manual_title': '✋ Запропонувати вручну',
    'stream_tools.title_label': 'Назва стріму',
    'stream_tools.category_label': 'Категорія (гра)',
    'stream_tools.suggest_btn': 'Надіслати пропозицію',
    'stream_tools.history_title': '🕘 Історія дій',
    'stream_tools.history_empty': 'Дій ще не було.',
    'stream_tools.not_moderator': 'Цей бот не модератор — стрім-інструменти недоступні.',
    'stream_tools.proposed_suggest': 'Пропозицію надіслано в mod-feed — одобріть її там',
    'stream_tools.proposed_auto': 'Дію виконано',
    'stream_tools.err_empty': 'Введіть значення',
    'stream_tools.err_disabled': 'Інструмент вимкнено (off) — увімкніть режим suggest/auto вище',
    'stream_tools.err_not_moderator': 'Бот не модератор',
    'stream_tools.err_unknown_tool': 'Невідомий інструмент',
    'stream_tools.err_no_channel': 'У бота немає каналів',
    'stream_tools.err_helix_not_configured': 'Helix не налаштовано (Client-ID/токен)',
    'stream_tools.err_other': 'Помилка: {detail}',
    'stream_tools.err_dedup': 'Така пропозиція вже висить у фіді',
    'btn.download': '📥 Завантажити',
    'settings.panel_log_tail': '📋 Останні логи',
    'settings.panel_log_tail_hint': 'Хвіст panel.log — помилки, запуск, події панелі.',
    'widgets.preset_applied': 'Пресет «{name}» застосовано',
    'settings.twitch_check': '🔌 Перевірити підключення',
    'settings.twitch_check_hint': 'Перевірка виконується від першого увімкненого бота (потрібен його OAuth-токен).',
    'settings.twitch_check_ok': 'Підключення до Twitch OK — {name}',
    'bots.empty': 'Спочатку додайте бота',
});

// ── Track 6.5: scoped owner voice control ─────────────────────
let _voiceRecorder = null;
let _voiceStream = null;
let _voiceChunks = [];
let _voiceBlob = null;
let _voiceStartedAt = 0;
let _voiceTimerHandle = null;

function _voiceScope() {
    return {
        accountId: _currentBotId || 0,
        channel: $('voiceControlChannel')?.value || '',
    };
}

async function loadVoiceControl(id) {
    const select = $('voiceControlChannel');
    if (!id || !select) return;
    try {
        const previous = select.value;
        const channels = await api(`/api/accounts/${id}/channels`);
        select.innerHTML = (channels || []).filter(c => c.enabled !== false).map(c => {
            const channel = String(c.channel_name || '').replace(/^#/, '').toLowerCase();
            return `<option value="${esc(channel)}">#${esc(channel)}</option>`;
        }).join('');
        if (previous && [...select.options].some(o => o.value === previous)) select.value = previous;
        const scope = _voiceScope();
        if (!scope.channel) return;
        const cfg = await api(`/api/voice-control?account_id=${scope.accountId}&channel=${encodeURIComponent(scope.channel)}`);
        if ($('voiceControlPhrase')) $('voiceControlPhrase').value = cfg.activation_phrase || '';
        if ($('voiceControlThreshold')) $('voiceControlThreshold').value = cfg.confidence_threshold ?? 0.65;
        setToggle('voiceControlEnabled', !!cfg.enabled);
        const status = cfg.profile_ready
            ? t('voice_control.profile_ready')
            : t('voice_control.profile_missing');
        $('voiceControlProfileStatus').textContent = cfg.verifier_ready
            ? status : `${status} · ${t('voice_control.verifier_missing')}`;
        await loadVoiceSuggestions();
    } catch (e) {
        if ($('voiceControlProfileStatus')) $('voiceControlProfileStatus').textContent = e.message;
    }
}

async function saveVoiceControl() {
    const scope = _voiceScope();
    if (!scope.accountId || !scope.channel) return;
    try {
        await api(`/api/voice-control?account_id=${scope.accountId}&channel=${encodeURIComponent(scope.channel)}`, jopts('PUT', {
            enabled: $('voiceControlEnabled')?.classList.contains('active'),
            activation_phrase: $('voiceControlPhrase')?.value.trim() || '',
            confidence_threshold: Number($('voiceControlThreshold')?.value || 0.65),
        }));
        toast(t('msg.saved'), 'success');
        await loadVoiceControl(scope.accountId);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function startVoiceEnrollment() {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
        return toast(t('voice_control.mic_error'), 'error');
    }
    try {
        _voiceStream = await navigator.mediaDevices.getUserMedia({audio: true});
        _voiceChunks = [];
        _voiceBlob = null;
        _voiceRecorder = new MediaRecorder(_voiceStream);
        _voiceRecorder.ondataavailable = event => { if (event.data.size) _voiceChunks.push(event.data); };
        _voiceRecorder.onstop = () => {
            _voiceBlob = new Blob(_voiceChunks, {type: _voiceRecorder.mimeType || 'audio/webm'});
            const playback = $('voiceControlPlayback');
            playback.src = URL.createObjectURL(_voiceBlob);
            playback.classList.remove('hidden');
            const elapsed = (Date.now() - _voiceStartedAt) / 1000;
            $('voiceControlEnroll').disabled = elapsed < 30 || elapsed > 65;
            _voiceStream?.getTracks().forEach(track => track.stop());
            clearInterval(_voiceTimerHandle);
        };
        _voiceStartedAt = Date.now();
        _voiceRecorder.start(1000);
        $('voiceControlRecord').classList.add('hidden');
        $('voiceControlStop').classList.remove('hidden');
        _voiceTimerHandle = setInterval(() => {
            const seconds = Math.floor((Date.now() - _voiceStartedAt) / 1000);
            $('voiceControlTimer').textContent = t('voice_control.seconds', {count: seconds});
            if (seconds >= 60) stopVoiceEnrollment();
        }, 500);
    } catch (e) { toast(t('voice_control.mic_error'), 'error'); }
}

function stopVoiceEnrollment() {
    if (_voiceRecorder?.state === 'recording') _voiceRecorder.stop();
    $('voiceControlRecord')?.classList.remove('hidden');
    $('voiceControlStop')?.classList.add('hidden');
}

async function uploadVoiceEnrollment() {
    const scope = _voiceScope();
    if (!_voiceBlob || !scope.accountId || !scope.channel) return;
    try {
        const dataUrl = await new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = reject;
            reader.readAsDataURL(_voiceBlob);
        });
        await api('/api/voice-control/enroll', jopts('POST', {
            account_id: scope.accountId,
            channel: scope.channel,
            mime_type: _voiceBlob.type,
            audio_b64: String(dataUrl).split(',', 2)[1] || '',
        }));
        toast(t('voice_control.enrolled'), 'success');
        await loadVoiceControl(scope.accountId);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function deleteVoiceEnrollment() {
    const scope = _voiceScope();
    if (!scope.accountId || !scope.channel || !confirm(t('voice_control.delete_confirm'))) return;
    try {
        await api(`/api/voice-control/enrollment?account_id=${scope.accountId}&channel=${encodeURIComponent(scope.channel)}`, {method: 'DELETE'});
        _voiceBlob = null;
        $('voiceControlPlayback')?.classList.add('hidden');
        toast(t('voice_control.deleted'), 'success');
        await loadVoiceControl(scope.accountId);
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function loadVoiceSuggestions() {
    const scope = _voiceScope();
    const list = $('voiceControlSuggestions');
    if (!list || !scope.accountId || !scope.channel) return;
    try {
        const data = await api(`/api/mod-feed/events?account_id=${scope.accountId}&channel=${encodeURIComponent(scope.channel)}&limit=100`);
        const items = (data.intents || []).filter(item => item.intent?.source === 'owner_voice');
        list.innerHTML = items.map(item => `<div class="p-2 form-panel flex gap-2 items-center flex-wrap">
            <span class="badge">${panelModFeedField(item, 'action')}</span>
            <span class="text-sm" style="flex:1">${panelModFeedField(item, 'text')}</span>
            <span class="text-xs text-muted">${Math.round(Number(item.intent?.confidence || 0) * 100)}%</span>
            <button class="btn btn-primary btn-sm" onclick="decideVoiceSuggestion(${Number(item.id)},'approve')">${esc(t('voice_control.approve'))}</button>
            <button class="btn btn-secondary btn-sm" onclick="decideVoiceSuggestion(${Number(item.id)},'reject')">${esc(t('voice_control.reject'))}</button>
        </div>`).join('') || `<div class="text-sm text-muted">${esc(t('voice_control.pending_empty'))}</div>`;
    } catch (e) { list.textContent = e.message; }
}

async function decideVoiceSuggestion(id, decision) {
    try {
        const result = await api(`/api/mod-feed/intents/${id}/${decision}`, {method: 'POST'});
        toast(result.ok ? t('voice_control.decision_saved') : t('toast.error_detail', {detail: result.error}), result.ok ? 'success' : 'error');
        await loadVoiceSuggestions();
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

Object.assign(LANGS.ru, {
    'voice_control.title': '🎙 Голосовое управление',
    'voice_control.hint': 'Команды берутся из локального stream audio → Whisper и исполняются только после совпадения фразы активации и голоса владельца.',
    'voice_control.channel': 'Канал', 'voice_control.channel_hint': 'Профиль и команды изолированы по выбранному боту и каналу.',
    'voice_control.phrase': 'Фраза активации', 'voice_control.phrase_hint': 'Команда без этой фразы всегда игнорируется.',
    'voice_control.threshold': 'Порог совпадения голоса', 'voice_control.threshold_hint': 'Низкая уверенность создаёт предложение модератору, но ничего не меняет сама.',
    'voice_control.enabled': 'Автоисполнение подтверждённого голоса', 'voice_control.enabled_hint': 'Необратимые TTS, Soundboard, clip и moderation не входят в голосовой whitelist.',
    'voice_control.enroll_title': 'Регистрация голоса владельца',
    'voice_control.enroll_text': 'Прочитайте вслух: «Я подтверждаю локальное голосовое управление этим каналом. Таймер старт, таймер пауза, цель плюс пять. Мой голос используется только для проверки владельца».',
    'voice_control.storage_hint': 'Запись хранится локально в data/voice-control и не отправляется AI-провайдеру. Модель проверки загружается отдельно, аудио остаётся на этом компьютере.',
    'voice_control.record': '● Записать 30–60 сек', 'voice_control.stop': '■ Остановить', 'voice_control.enroll': 'Сохранить профиль', 'voice_control.delete': 'Удалить запись',
    'voice_control.profile_ready': 'профиль готов', 'voice_control.profile_missing': 'профиль не создан', 'voice_control.verifier_missing': 'установите SpeechBrain',
    'voice_control.pending_title': 'Предложения с низкой уверенностью', 'voice_control.pending_empty': 'Предложений нет.',
    'voice_control.approve': 'Одобрить', 'voice_control.reject': 'Отклонить', 'voice_control.decision_saved': 'Решение сохранено',
    'voice_control.mic_error': 'Микрофон браузера недоступен', 'voice_control.seconds': '{count} сек', 'voice_control.enrolled': 'Голосовой профиль сохранён',
    'voice_control.deleted': 'Голосовая запись удалена', 'voice_control.delete_confirm': 'Удалить локальную голосовую запись?',
    'voice_control.hotkey_review': 'Хоткеи панели работают только при открытой вкладке. OBS не умеет вызывать API этих биндингов напрямую; его hotkeys управляют сценой/source, поэтому отдельная фиктивная интеграция не добавлена.',
});
Object.assign(LANGS.en, {
    'voice_control.title': '🎙 Voice control',
    'voice_control.hint': 'Commands come from local stream audio → Whisper and run only when both the activation phrase and owner voice match.',
    'voice_control.channel': 'Channel', 'voice_control.channel_hint': 'The profile and commands are isolated to the selected bot and channel.',
    'voice_control.phrase': 'Activation phrase', 'voice_control.phrase_hint': 'A command without this phrase is always ignored.',
    'voice_control.threshold': 'Voice match threshold', 'voice_control.threshold_hint': 'Low confidence creates a moderator suggestion and never changes state automatically.',
    'voice_control.enabled': 'Auto-run verified owner voice', 'voice_control.enabled_hint': 'Irreversible TTS, Soundboard, clip, and moderation actions are not in the voice whitelist.',
    'voice_control.enroll_title': 'Enroll owner voice',
    'voice_control.enroll_text': 'Read aloud: “I confirm local voice control for this channel. Countdown start, countdown pause, goal add five. My voice is used only to verify the owner.”',
    'voice_control.storage_hint': 'The recording stays locally in data/voice-control and is not sent to an AI provider. The verification model is downloaded separately; audio stays on this computer.',
    'voice_control.record': '● Record 30–60 sec', 'voice_control.stop': '■ Stop', 'voice_control.enroll': 'Save profile', 'voice_control.delete': 'Delete recording',
    'voice_control.profile_ready': 'profile ready', 'voice_control.profile_missing': 'profile missing', 'voice_control.verifier_missing': 'install SpeechBrain',
    'voice_control.pending_title': 'Low-confidence suggestions', 'voice_control.pending_empty': 'No suggestions.',
    'voice_control.approve': 'Approve', 'voice_control.reject': 'Reject', 'voice_control.decision_saved': 'Decision saved',
    'voice_control.mic_error': 'Browser microphone is unavailable', 'voice_control.seconds': '{count} sec', 'voice_control.enrolled': 'Voice profile saved',
    'voice_control.deleted': 'Voice recording deleted', 'voice_control.delete_confirm': 'Delete the local voice recording?',
    'voice_control.hotkey_review': 'Panel hotkeys work only while the tab is open. OBS cannot invoke these binding APIs directly; its hotkeys control scenes/sources, so no fake integration was added.',
});
Object.assign(LANGS.ua, {
    'voice_control.title': '🎙 Голосове керування',
    'voice_control.hint': 'Команди надходять із локального stream audio → Whisper і виконуються лише за збігу фрази активації та голосу власника.',
    'voice_control.channel': 'Канал', 'voice_control.channel_hint': 'Профіль і команди ізольовані для вибраного бота й каналу.',
    'voice_control.phrase': 'Фраза активації', 'voice_control.phrase_hint': 'Команда без цієї фрази завжди ігнорується.',
    'voice_control.threshold': 'Поріг збігу голосу', 'voice_control.threshold_hint': 'Низька впевненість створює пропозицію модератору й нічого не змінює автоматично.',
    'voice_control.enabled': 'Автовиконання підтвердженого голосу', 'voice_control.enabled_hint': 'Незворотні TTS, Soundboard, clip і moderation не входять до голосового whitelist.',
    'voice_control.enroll_title': 'Реєстрація голосу власника',
    'voice_control.enroll_text': 'Прочитайте вголос: «Я підтверджую локальне голосове керування цим каналом. Таймер старт, таймер пауза, ціль плюс пʼять. Мій голос використовується лише для перевірки власника».',
    'voice_control.storage_hint': 'Запис зберігається локально в data/voice-control і не надсилається AI-провайдеру. Модель перевірки завантажується окремо, аудіо лишається на цьому компʼютері.',
    'voice_control.record': '● Записати 30–60 сек', 'voice_control.stop': '■ Зупинити', 'voice_control.enroll': 'Зберегти профіль', 'voice_control.delete': 'Видалити запис',
    'voice_control.profile_ready': 'профіль готовий', 'voice_control.profile_missing': 'профіль не створено', 'voice_control.verifier_missing': 'встановіть SpeechBrain',
    'voice_control.pending_title': 'Пропозиції з низькою впевненістю', 'voice_control.pending_empty': 'Пропозицій немає.',
    'voice_control.approve': 'Схвалити', 'voice_control.reject': 'Відхилити', 'voice_control.decision_saved': 'Рішення збережено',
    'voice_control.mic_error': 'Мікрофон браузера недоступний', 'voice_control.seconds': '{count} с', 'voice_control.enrolled': 'Голосовий профіль збережено',
    'voice_control.deleted': 'Голосовий запис видалено', 'voice_control.delete_confirm': 'Видалити локальний голосовий запис?',
    'voice_control.hotkey_review': 'Хоткеї панелі працюють лише за відкритої вкладки. OBS не може напряму викликати API цих биндингів; його hotkeys керують сценами/source, тому фіктивну інтеграцію не додано.',
});

