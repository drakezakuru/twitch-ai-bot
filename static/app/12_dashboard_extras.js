// [P5-split] 12_dashboard_extras.js ← static/app.js, исходные строки 7986–8195; грузится после предыдущего чанка, порядок = порядку строк


// ── PLAN §9g/§9h: Dashboard-лента всплесков чата + настройка автозаписи replay ──

async function loadClipSpikesFeed() {
    const el = $('clipSpikesFeed');
    if (!el) return;
    const bots = _allBots || [];
    if (!bots.length) return;
    const rows = await Promise.allSettled(bots.map(b => api(`/api/bot/clip-detector/moments/${b.id}`)));
    const since = Date.now() - 24 * 3600 * 1000;
    const items = [];
    rows.forEach((r, idx) => {
        if (r.status !== 'fulfilled') return;
        for (const m of (r.value.items || [])) {
            const raw = String(m.created_at || m.timestamp || '');
            if (!raw) continue;
            const ts = Date.parse(raw.includes('T') ? (raw.endsWith('Z') ? raw : raw + 'Z') : raw.replace(' ', 'T') + 'Z');
            if (!isFinite(ts) || ts < since) continue;
            items.push({ bot: bots[idx]?.nickname || '#' + bots[idx]?.id, m, ts });
        }
    });
    if (!items.length) {
        el.innerHTML = `<div class="empty-state"><div class="empty-icon">🎬</div><span>${esc(t('clips.dash_empty'))}</span></div>`;
        return;
    }
    items.sort((a, b) => b.ts - a.ts);
    el.innerHTML = items.slice(0, 6).map(({ bot, m }) => `
        <div class="flex gap-2 items-center text-sm py-1" style="border-top:1px solid var(--border-light)">
            <span>🎬</span>
            <strong>${esc(bot)}</strong>
            <span class="text-muted">#${esc(m.channel || '')}</span>
            <span class="badge">🔥 ${esc(String(m.rate ?? ''))} ${esc(t('clips.per_sec'))}</span>
            <span class="text-xs text-muted" style="flex:1">${esc(String(m.created_at || m.timestamp || '').substring(0, 19))}</span>
        </div>`).join('');
}

// Q16 F5 (DEC-OWNER-016): автозапись replay-сессий — настройка бота
// (botReplayAutoRecord в карточке «Запись сессий»); глобальная карточка и функции удалены.

// Q16 F1 (DEC-OWNER-016): глобальный мастер-выключатель провокаций убран из Настроек —
// вкл/выкл только у бота во вкладке «Характер» (conflictEnabled). Сохранённое глобальное
// значение `provocations_master_enabled` рантайм (chat_analyzer) читает как legacy-fallback.

// ── PLAN §6/§9g/§9h: i18n ключи карточек страницы бота, Dashboard и настроек ──
Object.assign(LANGS.ru, {
    'clips.config': '⚙️ Чувствительность детектора', 'clips.threshold': 'Порог (× среднего)',
    'clips.window': 'Окно, сек', 'clips.cooldown': 'Пауза, сек', 'clips.per_sec': 'сообщ/сек',
    'clips.dash_title': '🔥 Всплески чата (клип-моменты)', 'clips.dash_empty': 'Всплесков за последние 24 часа не было',
    'replay.auto_hint': 'При старте бота запись включается автоматически, если включён тумблер «Автозапись при старте», — закончить можно кнопкой «Закончить».', 'replay.auto_record': 'Автозапись при старте бота',
    'replay.view': 'Просмотр событий', 'replay.play': 'Воспроизвести', 'replay.delete': 'Удалить сессию',
    'confirm.delete_replay': 'Удалить эту replay-сессию?',
    'replay.kind_chat_in': 'чат', 'replay.kind_bot_out': 'ответ бота', 'replay.kind_vision_frame': 'кадр',
    'replay.kind_whisper_seg': 'речь', 'replay.kind_trigger': 'триггер', 'replay.kind_setting': 'настройка',
    'replay.kind_mood': 'настроение', 'replay.kind_thread': 'тред',
    'influences.title': '🎛 Влияния на этого бота', 'influences.hint': 'Выключенное влияние просто не попадает в промпт — код и данные остаются.',
    'influences.mimicry': 'Копирка / стиль чатера', 'influences.observations': 'Vision-наблюдения стрима',
    'influences.lore': 'Знания о стримере (lore)', 'influences.learning': 'Обучение по стриму',
    'btn.import_history': 'Из файла (txt/json)', 'btn.describe_from_history': '🧬 Описать характер по истории',
    'history.import_hint': 'TXT — строки «автор: текст», JSON — [{author,text}]. Файл используется для стиля/характера, в чат ничего не отправляется.',
    'history.parse_error': 'Не удалось разобрать файл: нет пар «автор: текст»', 'history.loaded': 'Загружено сообщений: {detail}',
    'history.too_short': 'Слишком мало сообщений для анализа (нужно хотя бы ~10)', 'history.proposal_done': 'Характер предложен по {detail} сообщениям — проверь и сохрани',
});
Object.assign(LANGS.en, {
    'clips.config': '⚙️ Detector sensitivity', 'clips.threshold': 'Threshold (× average)',
    'clips.window': 'Window, sec', 'clips.cooldown': 'Pause, sec', 'clips.per_sec': 'msg/sec',
    'clips.dash_title': '🔥 Chat spikes (clip moments)', 'clips.dash_empty': 'No spikes in the last 24 hours',
    'replay.auto_hint': 'Recording starts automatically when the bot starts if “Auto-record on start” is on — stop it with the “Stop” button.', 'replay.auto_record': 'Auto-record on bot start',
    'replay.view': 'View events', 'replay.play': 'Play back', 'replay.delete': 'Delete session',
    'confirm.delete_replay': 'Delete this replay session?',
    'replay.kind_chat_in': 'chat', 'replay.kind_bot_out': 'bot reply', 'replay.kind_vision_frame': 'frame',
    'replay.kind_whisper_seg': 'speech', 'replay.kind_trigger': 'trigger', 'replay.kind_setting': 'setting',
    'replay.kind_mood': 'mood', 'replay.kind_thread': 'thread',
    'settings.replay_auto': '⏺ Auto-record replay sessions on bot start',
    'settings.replay_auto_hint': 'Records chat, bot replies and frames into the database (a few MB per stream). Toggle it off here.',
    'influences.title': '🎛 Influences on this bot', 'influences.hint': 'A disabled influence is simply omitted from the prompt — code and data stay.',
    'influences.mimicry': 'Mimicry / chatter style', 'influences.observations': 'Vision stream observations',
    'influences.lore': 'Streamer lore facts', 'influences.learning': 'Learning from stream',
    'btn.import_history': 'From file (txt/json)', 'btn.describe_from_history': '🧬 Describe character from history',
    'history.import_hint': 'TXT — lines "author: text", JSON — [{author,text}]. The file is used for style/character only, nothing is sent to chat.',
    'history.parse_error': 'Could not parse file: no "author: text" pairs', 'history.loaded': 'Loaded messages: {detail}',
    'history.too_short': 'Too few messages to analyze (need at least ~10)', 'history.proposal_done': 'Character proposed from {detail} messages — review and save',
});
Object.assign(LANGS.ua, {
    'clips.config': '⚙️ Чутливість детектора', 'clips.threshold': 'Поріг (× середнього)',
    'clips.window': 'Вікно, сек', 'clips.cooldown': 'Пауза, сек', 'clips.per_sec': 'повід/сек',
    'clips.dash_title': '🔥 Сплески чату (кліп-моменти)', 'clips.dash_empty': 'Сплесків за останні 24 години не було',
    'replay.auto_hint': 'При старті бота запис вмикається автоматично, якщо увімкнено тумблер «Автозапис при старті», — завершити можна кнопкою «Закінчити».', 'replay.auto_record': 'Автозапис при старті бота',
    'replay.view': 'Перегляд подій', 'replay.play': 'Відтворити', 'replay.delete': 'Видалити сесію',
    'confirm.delete_replay': 'Видалити цю replay-сесію?',
    'replay.kind_chat_in': 'чат', 'replay.kind_bot_out': 'відповідь бота', 'replay.kind_vision_frame': 'кадр',
    'replay.kind_whisper_seg': 'мова', 'replay.kind_trigger': 'тригер', 'replay.kind_setting': 'налаштування',
    'replay.kind_mood': 'настрій', 'replay.kind_thread': 'тред',
    'settings.replay_auto': '⏺ Автозапис replay-сесій при старті бота',
    'settings.replay_auto_hint': 'Пише чат, відповіді бота й кадри в базу (одиниці МБ за стрім). Вимикається тут.',
    'influences.title': '🎛 Впливи на цього бота', 'influences.hint': 'Вимкнений вплив просто не потрапляє в промпт — код і дані лишаються.',
    'influences.mimicry': 'Копіювання / стиль чатера', 'influences.observations': 'Vision-спостереження стріму',
    'influences.lore': 'Знання про стрімера (lore)', 'influences.learning': 'Навчання зі стріму',
    'btn.import_history': 'З файлу (txt/json)', 'btn.describe_from_history': '🧬 Описати характер за історією',
    'history.import_hint': 'TXT — рядки «автор: текст», JSON — [{author,text}]. Файл використовується для стилю/характеру, у чат нічого не надсилається.',
    'history.parse_error': 'Не вдалося розібрати файл: немає пар «автор: текст»', 'history.loaded': 'Завантажено повідомлень: {detail}',
    'history.too_short': 'Занадто мало повідомлень для аналізу (потрібно хоча б ~10)', 'history.proposal_done': 'Характер запропоновано за {detail} повідомленнями — перевір і збережи',
});

// ── PLAN §9l: i18n ключей карточки «Провокации в спорах» ──
Object.assign(LANGS.ru, {
    'conflict.title': '🔥 Провокации в спорах',
    'conflict.hint': 'Бот может задать ехидный вопрос-подначку конфликтному чатеру, а после его ответа — остроумно «добить» спор. Интенсивность задаёт ехидность и шанс срабатывания; тон ограничен персоной, насмешка идёт над аргументом, а не над человеком. Пока выключено — фича не работает.',
    'conflict.enable': 'Разрешить подначки в спорах',
    'conflict.intensity': 'Интенсивность',
});
Object.assign(LANGS.en, {
    'conflict.title': '🔥 Conflict banter',
    'conflict.hint': 'The bot may tease a heated chatter with a cheeky bait question, and after they reply — close the argument with a witty comeback. Intensity controls the sharpness and trigger chance; tone is bounded by the persona, targeting arguments rather than people. While off, the feature does nothing.',
    'conflict.enable': 'Allow banter in arguments',
    'conflict.intensity': 'Intensity',
});
Object.assign(LANGS.ua, {
    'conflict.title': '🔥 Провокації в спорах',
    'conflict.hint': 'Бот може поставити їдке запитання-підкол конфліктному чатеру, а після його відповіді — дотепно «добити» суперечку. Інтенсивність задає їдкість і шанс спрацювання; тон обмежений персоною, кпина йде над аргументом, а не над людиною. Поки вимкнено — фіча не працює.',
    'conflict.enable': 'Дозволити підколи в спорах',
    'conflict.intensity': 'Інтенсивність',
});

// ── PLAN §6: i18n подсказки «Характер vs Поведение» ──
Object.assign(LANGS.ru, {
    'persona.character_hint': 'Характер — это личность бота: стиль, юмор и эмоции. Когда и как бот отвечает — настраивается во вкладке «Поведение».',
});
Object.assign(LANGS.en, {
    'persona.character_hint': 'Identity is who the bot is: style, humor and emotions. When and how the bot replies is configured in the “Behavior” tab.',
});
Object.assign(LANGS.ua, {
    'persona.character_hint': 'Характер — це особистість бота: стиль, гумор та емоції. Коли і як бот відповідає — налаштовується у вкладці «Поведіння».',
});

// ── PLAN §2.1: i18n секции «Активность и контекст» в overrides канала ──
Object.assign(LANGS.ru, {
    'overrides.activity_title': 'Активность и контекст этого канала',
    'overrides.auto_chat': 'Может начинать сам', 'overrides.silent': 'Тихий режим',
    'overrides.tts_mute': 'Без озвучки (TTS)', 'overrides.cooldown': 'Интервал между сообщениями, сек',
    'overrides.ctx_chat': '💬 чат', 'overrides.ctx_stream': '🎥 стрим', 'overrides.ctx_streamer': '👤 стример',
});
Object.assign(LANGS.en, {
    'overrides.activity_title': 'Activity & context for this channel',
    'overrides.auto_chat': 'Can start messages', 'overrides.silent': 'Quiet mode',
    'overrides.tts_mute': 'No TTS voice', 'overrides.cooldown': 'Interval between messages, sec',
    'overrides.ctx_chat': '💬 chat', 'overrides.ctx_stream': '🎥 stream', 'overrides.ctx_streamer': '👤 streamer',
});
Object.assign(LANGS.ua, {
    'overrides.activity_title': 'Активність і контекст цього каналу',
    'overrides.auto_chat': 'Може починати сам', 'overrides.silent': 'Тихий режим',
    'overrides.tts_mute': 'Без озвучки (TTS)', 'overrides.cooldown': 'Інтервал між повідомленнями, сек',
    'overrides.ctx_chat': '💬 чат', 'overrides.ctx_stream': '🎥 стрім', 'overrides.ctx_streamer': '👤 стрімер',
});

// ── PLAN §9e: i18n истории настроения ──
Object.assign(LANGS.ru, { 'mood.history': 'История настроения' });
Object.assign(LANGS.en, { 'mood.history': 'Mood history' });
Object.assign(LANGS.ua, { 'mood.history': 'Історія настрою' });

// ── PLAN §2.1: i18n фильтра слов по каналам ──
Object.assign(LANGS.ru, { 'wordfilter.all_channels': 'Все каналы' });
Object.assign(LANGS.en, { 'wordfilter.all_channels': 'All channels' });
Object.assign(LANGS.ua, { 'wordfilter.all_channels': 'Усі канали' });
// ── Widgets session: §11.2 now-playing источник автозаполнения ──
async function waNpSourceLoad() {
    if (!$('waNpSource')) return;
    try {
        const s = await wapi('/api/widgets/now-playing/source');
        $('waNpSource').value = s.source || 'manual';
        $('waNpLastfmUser').value = s.lastfm_user || '';
        $('waNpLastfmKey').value = '';
        if (s.has_lastfm_api_key) $('waNpLastfmKey').placeholder = t('placeholder.eleven_key_set');
        $('waNpMprisPlayer').value = s.mpris_player || '';
    } catch (e) { _waHint(e); }
}
async function waNpSourceSave() {
    try {
        const s = await wapi('/api/widgets/now-playing/source', 'PUT', {
            source: $('waNpSource').value,
            lastfm_user: $('waNpLastfmUser').value,
            lastfm_api_key: $('waNpLastfmKey').value,
            mpris_player: $('waNpMprisPlayer').value,
        });
        $('waNpLastfmKey').value = '';
        if (s.has_lastfm_api_key) $('waNpLastfmKey').placeholder = t('placeholder.eleven_key_set');
    } catch (e) { _waHint(e); }
}
// подгрузка в общий refresh панели виджетов
const _loadWidgetsAdminPrev = loadWidgetsAdmin;
loadWidgetsAdmin = async function() {
    await _loadWidgetsAdminPrev();
    waNpSourceLoad();
};

// ── Q24: тумблер «Не показывать всплывашки» ──
// Осознанное глобальное UI-предпочтение владельца (исключение 1 из DEC-OWNER-002):
// состояние в localStorage, по умолчанию всплывашки показываются. Подавляет только
// плавающие карточки решений (moderation pending) и тосты live-событий; inline-списки
// в Обзоре, журнале канала и настройках бота остаются.
const _POPUPS_HIDDEN_KEY = 'panelPopupsHidden';
function popupsHidden() {
    try { return localStorage.getItem(_POPUPS_HIDDEN_KEY) === '1'; } catch (e) { return false; }
}
function setPopupsHidden(hidden) {
    try { localStorage.setItem(_POPUPS_HIDDEN_KEY, hidden ? '1' : '0'); } catch (e) { /* private mode */ }
    applyPopupsHidden();
}
function applyPopupsHidden() {
    const chk = $('panelPopupsToggle');
    if (chk) chk.checked = popupsHidden();
    if (popupsHidden()) {
        const box = document.getElementById('modAskPopup');
        if (box) box.remove();
    }
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', applyPopupsHidden);
else applyPopupsHidden();

