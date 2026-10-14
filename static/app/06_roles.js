// [P5-split] 06_roles.js ← static/app.js, исходные строки 5049–5575; грузится после предыдущего чанка, порядок = порядку строк

// ── Extend showBotTab ─────────────────────────────────
// ==================== §6 PLAN_FEEDBACK_3008: роли ботов ====================

const ROLE_META = {
    chatter: { label: 'role.name.chatter', color: '#22c55e', desc: 'role.desc.chatter' },
    moderator: { label: 'role.name.moderator', color: '#e74c3c', desc: 'role.desc.moderator' },
    voice_companion: { label: 'role.name.voice_companion', color: '#9146ff', desc: 'role.desc.voice_companion' },
    lurker: { label: 'role.name.lurker', color: '#38bdf8', desc: 'role.desc.lurker' },
    director: { label: 'role.name.director', color: '#f59e0b', desc: 'role.desc.director' },
};

function _roleMetaLabel(role) { return _roleT((ROLE_META[role] || ROLE_META.chatter).label); }

// Переводы форм ролей живут локально (ru/en/ua рядом с полем), чтобы не
// раздувать общий словарь на ~50 ключей.
const ROLE_I18N = {
    'role.name.chatter': { ru: '💬 Болтун', en: '💬 Chatter', ua: '💬 Балакун' },
    'role.name.moderator': { ru: '🛡 Модератор', en: '🛡 Moderator', ua: '🛡 Модератор' },
    'role.name.voice_companion': { ru: '🎙 Собеседник в чате (озвучиваемый)', en: '🎙 Spoken chat companion', ua: '🎙 Співрозмовник у чаті (озвучуваний)' },
    'role.name.lurker': { ru: '👀 Зритель', en: '👀 Lurker', ua: '👀 Глядач' },
    'role.name.director': { ru: '🎬 Режиссёр', en: '🎬 Director', ua: '🎬 Режисер' },
    'role.desc.chatter': {
        ru: '💬 Живой зритель в чате: реагирует на стрим и зрителей, шутит, поддерживает беседу. Стиль — пресеты («Свой в доску», «Ехидный»…) или копирка чужого стиля. Настройки — во вкладках «Характер» и «AI и TTS».',
        en: '💬 A live chat member: reacts to the stream and viewers, jokes, keeps the conversation going. Style via presets (“One of the boys”, “Sarcastic”…) or by copying someone’s style. Settings in the “Character” and “AI & TTS” tabs.',
        ua: '💬 Живий глядач у чаті: реагує на стрим і глядачів, жартує, підтримує розмову. Стиль — пресети («Свій у дошку», «Значний»…) чи копіювання чужого стилю. Налаштування — у вкладках «Характер» та «AI і TTS».',
    },
    'role.desc.moderator': {
        ru: '🛡 Модерирует чат и может болтать (по умолчанию болтает). Наказания — по лестнице (предупреждение → таймаут → бан), спорные случаи показывает всплывашками в mod-feed виджете, где ты решаешь. Может предлагать стрим-инструменты (категория/название/slow).',
        en: '🛡 Moderates chat and can chat too (chats by default). Punishments follow a ladder (warning → timeout → ban), borderline cases appear as pop-ups in the mod-feed widget for you to decide. Can suggest stream tools (category/title/slow).',
        ua: '🛡 Модерує чат і може балакати (за замовчуванням балакає). Покарання — драбиною (попередження → таймаут → бан), спірні випадки — спливашками в mod-feed віджеті, де вирішуєш ти. Може пропонувати стрім-інструменти (категорія/назва/slow).',
    },
    'role.desc.voice_companion': {
        ru: '🎙 Собеседник в публичном Twitch-чате: наблюдает за стримом и чатом, пишет как обычный бот, а его отправленные сообщения дополнительно озвучиваются в стрим. Частоту озвучки задаёт существующий процент TTS во вкладке «AI и TTS».',
        en: '🎙 A companion in public Twitch chat: observes the stream and chat, posts like a regular bot, and its sent messages are also spoken on stream. The existing TTS percentage in “AI & TTS” controls how often replies are spoken.',
        ua: '🎙 Співрозмовник у публічному Twitch-чаті: спостерігає за стримом і чатом, пише як звичайний бот, а його надіслані повідомлення додатково озвучуються у стрим. Частоту озвучення задає наявний відсоток TTS у вкладці «AI і TTS».',
    },
    'role.desc.lurker': {
        ru: '👀 Non-AI наблюдатель в чате: подключается и читает чат, но сам не пишет. Может ответить только на прямое @упоминание, если это отдельно разрешено.',
        en: '👀 A non-AI chat observer: connects and reads chat but does not post on its own. It may reply only to a direct @mention when explicitly allowed.',
        ua: '👀 Non-AI спостерігач у чаті: підключається й читає чат, але сам не пише. Може відповісти лише на пряме @згадування, якщо це окремо дозволено.',
    },
    'role.desc.director': {
        ru: '🎬 Анализирует выбранный канал и создаёт проверенные планы для lurker-аккаунтов. Сам этот аккаунт в чат никогда не пишет.',
        en: '🎬 Analyzes the selected channel and creates validated plans for lurker accounts. This account never posts in chat.',
        ua: '🎬 Аналізує вибраний канал і створює перевірені плани для lurker-акаунтів. Цей акаунт ніколи не пише в чат.',
    },
    'role.director.panel_hint': {
        ru: 'После назначения аккаунта все управление Director находится в отдельной панели. Обычные настройки чат-бота к этой роли не применяются.',
        en: 'After assigning the account, all Director controls live in the dedicated panel. Regular chat-bot settings do not apply to this role.',
        ua: 'Після призначення акаунта все керування Director міститься в окремій панелі. Звичайні налаштування чат-бота до цієї ролі не застосовуються.',
    },
    'role.director.open_panel': {
        ru: 'Открыть панель Режиссёра', en: 'Open Director panel', ua: 'Відкрити панель Режисера',
    },
    'role.f.chat_activity': { ru: 'Активность в чате', en: 'Chat activity', ua: 'Активність у чаті' },
    'role.f.chat_activity.chatter': { ru: 'Болтает как обычный бот', en: 'Chats like a regular bot', ua: 'Балакає як звичайний бот' },
    'role.f.chat_activity.mod_only': { ru: 'Только модерация', en: 'Moderation only', ua: 'Лише модерація' },
    'role.f.chat_activity.silent': { ru: 'Полное молчание', en: 'Full silence', ua: 'Повна тиша' },
    'role.f.strictness': { ru: 'Строгость', en: 'Strictness', ua: 'Суворість' },
    'role.f.strictness.soft': { ru: 'Мягкая (только предупреждения)', en: 'Soft (warnings only)', ua: 'Мʼяка (лише попередження)' },
    'role.f.strictness.normal': { ru: 'Обычная (лестница наказаний)', en: 'Normal (punishment ladder)', ua: 'Звичайна (драбина покарань)' },
    'role.f.strictness.strict': { ru: 'Жёсткая (сразу таймауты)', en: 'Strict (instant timeouts)', ua: 'Сувора (одразу таймаути)' },
    'role.f.strictness.manual': { ru: 'Ручной режим (только лог для меня)', en: 'Manual (log only)', ua: 'Ручний режим (лише лог для мене)' },
    'role.f.ladder_warn': { ru: 'Нарушение № → предупреждение', en: 'Violation # → warning', ua: 'Порушення № → попередження' },
    'role.f.ladder_t1': { ru: 'Таймаут №2, мин', en: 'Timeout #2, min', ua: 'Таймаут №2, хв' },
    'role.f.ladder_t2': { ru: 'Таймаут №3, мин', en: 'Timeout #3, min', ua: 'Таймаут №3, хв' },
    'role.f.ladder_ban': { ru: 'Нарушение № → бан', en: 'Violation # → ban', ua: 'Порушення № → бан' },
    'role.f.translit': { ru: 'Ловить замаскированные (м***к) и транслит', en: 'Catch masked (m***k) and translit', ua: 'Ловити замасковані (м***к) і трансліт' },
    'role.f.ai_judge': { ru: 'AI-судья для спорных случаев', en: 'AI judge for borderline cases', ua: 'AI-суддя для спірних випадків' },
    'role.f.ai_judge_soft': { ru: 'При сомнении — предупреждение вместо таймаута', en: 'On doubt — warning instead of timeout', ua: 'При сумніві — попередження замість таймауту' },
    'role.f.warn_before': { ru: 'Писать «@user, предупреждение» перед наказанием', en: 'Post "@user, warning" before a punishment', ua: 'Писати «@user, попередження» перед покаранням' },
    'role.f.warn_text': { ru: 'Свой текст предупреждения (опц.)', en: 'Custom warning text (opt.)', ua: 'Свій текст попередження (опц.)' },
    'role.f.announce_chat': { ru: 'Анонсить свои действия в чат (по умолчанию — всплывашки)', en: 'Announce actions in chat (default: pop-ups)', ua: 'Анонсувати свої дії в чат (за замовчуванням — спливашки)' },
    'role.f.tts_announce': { ru: 'Озвучивать свои действия (TTS)', en: 'Announce actions with TTS', ua: 'Озвучувати свої дії (TTS)' },
    'role.f.confirm_mode': { ru: 'Применение наказаний', en: 'Punishment mode', ua: 'Застосування покарань' },
    'role.f.confirm_mode.auto': { ru: 'Авто (по лестнице)', en: 'Auto (by ladder)', ua: 'Авто (за драбиною)' },
    'role.f.confirm_mode.confirm': { ru: 'Только после моего одобрения', en: 'Only after my approval', ua: 'Лише після мого схвалення' },
    'role.f.category_policy': { ru: 'Политика по категориям (поверх строгости)', en: 'Category policy (overrides strictness)', ua: 'Політика за категоріями (понад суворість)' },
    'role.f.category_policy.hint': { ru: 'Задаёт действие для каждой категории нарушений независимо от лестницы. «По тяжести» — как настроено выше.', en: 'Sets the action per violation category regardless of the ladder. "By severity" keeps the ladder above.', ua: 'Задає дію для кожної категорії порушень незалежно від драбини. «За тяжкістю» — як налаштовано вище.' },
    'role.f.whitelist': { ru: 'Белый список ников (не трогать)', en: 'Nickname whitelist (never touch)', ua: 'Білий список нікнеймів (не чіпати)' },
    'role.v.companion_scope': { ru: 'Куда пишет', en: 'Where it posts', ua: 'Куди пише' },
    'role.v.companion_channel_chat': { ru: 'Публичный Twitch-чат канала', en: 'Public channel Twitch chat', ua: 'Публічний Twitch-чат каналу' },
    'role.v.on_speech': { ru: 'Учитывать речь стримера из контекста стрима', en: 'Use streamer speech from stream context', ua: 'Враховувати мовлення стримера з контексту стриму' },
    'role.v.on_questions': { ru: 'Отвечать на вопросы стримера', en: 'Answer streamer questions', ua: 'Відповідати на питання стрімера' },
    'role.v.on_silence': { ru: 'Заводить разговор на паузах тишины', en: 'Start small talk on silences', ua: 'Заводити розмову на паузах тиші' },
    'role.v.silence_sec': { ru: 'Пауза тишины, сек', en: 'Silence pause, sec', ua: 'Пауза тиші, сек' },
    'role.v.command_phrases': { ru: 'Команды-фразы («скажи привет»)', en: 'Trigger phrases ("say hi")', ua: 'Команди-фрази («скажи привіт»)' },
    'role.v.reply_delay': { ru: 'Задержка перед ответом, сек (1-4)', en: 'Reply delay, sec (1-4)', ua: 'Затримка перед відповіддю, сек (1-4)' },
    'role.v.max_reply_len': { ru: 'Макс. длина реплики, симв', en: 'Max reply length, chars', ua: 'Макс. довжина репліки, символів' },
    'role.v.interruptible': { ru: 'Можно перебить, если стример заговорил', en: 'Interruptible when the streamer speaks', ua: 'Можна перебити, якщо стрімер заговорив' },
    'role.v.excluded_topics': { ru: 'Темы-исключения (политика и т.п.)', en: 'Excluded topics (politics etc.)', ua: 'Теми-винятки (політика тощо)' },
    'role.v.ignore_swears': { ru: 'Не комментировать чужие маты', en: 'Do not comment on swearing', ua: 'Не коментувати чужі мати' },
    'role.v.whisper_conf': { ru: 'Порог уверенности распознавания речи (0-1)', en: 'Speech recognition confidence threshold (0-1)', ua: 'Поріг упевненості розпізнавання мовлення (0-1)' },
    'role.v.tts_percent_hint': { ru: '🔊 Озвучка отправленных сообщений использует «Процент ответов с TTS» во вкладке «AI и TTS».', en: '🔊 Spoken sent messages use “TTS reply percentage” from the “AI & TTS” tab.', ua: '🔊 Озвучення надісланих повідомлень використовує «Відсоток відповідей із TTS» у вкладці «AI і TTS».' },
    'role.v.min_words': { ru: 'Мин. слов во фразе стримера', en: 'Min words in a streamer phrase', ua: 'Мін. слів у фразі стрімера' },
    'role.v.max_10min': { ru: 'Макс. озвучек за 10 мин', en: 'Max voice replies per 10 min', ua: 'Макс. озвучок за 10 хв' },
    'role.v.cooldown': { ru: 'Кулдаун между репликами, сек', en: 'Cooldown between replies, sec', ua: 'Кулдаун між репліками, сек' },
    'role.l.mention_reply': { ru: 'Может ответить ТОЛЬКО на прямое @упоминание', en: 'May reply ONLY to a direct @mention', ua: 'Може відповісти ЛИШЕ на пряме @згадування' },
    'role.c.anti_assistant': { ru: 'Анти-ассистент фильтр (не быть «подсказчиком»)', en: 'Anti-assistant filter (never a "helper")', ua: 'Анти-асистент фільтр (не бути «підказувачем»)' },
    'role.c.preset': { ru: 'Пресет характера', en: 'Character preset', ua: 'Пресет характеру' },
    'role.c.preset.none': { ru: '— нет (как настроено в «Характер»)', en: '— none (as set in Character)', ua: '— немає (як у «Характер»)' },
    'role.c.preset.vdosku': { ru: 'Свой в доску (сленг, подкалы)', en: 'One of the boys (slang, banter)', ua: 'Свій в дошку (сленг, підколи)' },
    'role.c.preset.emotional': { ru: 'Эмоциональный (КАПС, эмоции)', en: 'Emotional (CAPS, emotions)', ua: 'Емоційний (КАПС, емоції)' },
    'role.c.preset.ehidny': { ru: 'Ехидный (сарказм)', en: 'Sarcastic', ua: 'Ехидний (сарказм)' },
    'role.c.preset.znatok': { ru: 'Тихий знаток (редко, по делу)', en: 'Quiet expert (rare, on point)', ua: 'Тихий знаток (рідко, по суті)' },
    'role.c.preset.memny': { ru: 'Мемный (мемы и шаблоны)', en: 'Memelord (memes and templates)', ua: 'Мемний (меми і шаблони)' },
    'role.c.preset.custom': { ru: 'Свой (чистый лист)', en: 'Custom (blank slate)', ua: 'Свій (чистий аркуш)' },
    'role.c.mode': { ru: 'Копирка «как у живого»', en: '"Human-like" mimicry', ua: 'Копірка «як у живого»' },
    'role.c.mode.off': { ru: 'выкл', en: 'off', ua: 'вимк' },
    'role.c.mode.copy': { ru: '📋 Копия сообщений', en: '📋 Message copy', ua: '📋 Копія повідомлень' },
    'role.c.mode.profile': { ru: '🎨 Стиль-профиль', en: '🎨 Style profile', ua: '🎨 Стиль-профіль' },
    'role.c.user': { ru: 'Юзер-источник стиля', en: 'Style source user', ua: 'Юзер-джерело стилю' },
    'role.c.strength': { ru: 'Сила копирования 0–100', en: 'Mimicry strength 0–100', ua: 'Сила копіювання 0–100' },
    'role.c.profile': { ru: 'Стил-профиль (текст, редактируемый)', en: 'Style profile (editable text)', ua: 'Стиль-профіль (текст, редагований)' },
    'role.c.candidates': { ru: 'Активные зрители чата', en: 'Active chat viewers', ua: 'Активні глядачі чату' },
    'role.c.nick_label': { ru: 'Ник чатера (любой)', en: 'Chatter nick (any)', ua: 'Нік чатера (будь-який)' },
    'role.c.candidates_refresh': { ru: 'Обновить список', en: 'Refresh list', ua: 'Оновити список' },
    'role.c.copy_btn': { ru: 'Скопировать сообщения', en: 'Copy messages', ua: 'Скопіювати повідомлення' },
    'role.c.profile_btn': { ru: 'Собрать профиль (AI)', en: 'Build profile (AI)', ua: 'Зібрати профіль (AI)' },
    'role.c.copy_none': { ru: 'Копия ещё не собрана: выбери зрителя и нажми «Скопировать».', en: 'No copy yet: pick a viewer and press "Copy".', ua: 'Копії ще немає: виберіть глядача і натисніть «Скопіювати».' },
    'role.c.user_required': { ru: 'Выбери юзера-источник стиля', en: 'Pick a style source user', ua: 'Виберіть юзера-джерело стилю' },
    'role.c.copied': { ru: 'Скопировано сообщений: {n} (в промпт пойдут последние 50)', en: 'Messages copied: {n} (last 50 go to the prompt)', ua: 'Скопійовано повідомлень: {n} (у промпт підуть останні 50)' },
    'role.c.building': { ru: 'Собираю стиль-профиль…', en: 'Building style profile…', ua: 'Збираю стиль-профіль…' },
    'role.c.built': { ru: 'Профиль собран — отредактируй при желании и сохрани', en: 'Profile built — edit if needed and save', ua: 'Профіль зібрано — за потреби відредагуйте та збережіть' },
    'role.c.learned': { ru: 'Выучено удачных ответов', en: 'Learned good replies', ua: 'Вивчено вдалих відповідей' },
    'role.c.learned_clear': { ru: 'Очистить выученное', en: 'Clear learned', ua: 'Очистити вивчене' },
};
function _roleT(key, vars) {
    const lang = (typeof localStorage !== 'undefined' && localStorage.getItem('lang')) || 'ru';
    const entry = ROLE_I18N[key];
    if (entry) return entry[lang] || entry.ru;
    if (hasTranslation(key)) return t(key, vars);
    return key.split('.').pop().replace(/[_-]/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}
for (const [key, entry] of Object.entries(ROLE_I18N)) {
    for (const lang of ['ru', 'en', 'ua']) LANGS[lang][key] ??= entry[lang] || entry.ru;
}

let _roleCfg = null;   // {bot_role, configs:{role:{...}}}
let _roleEditing = null;

// Q02: таблица «категория → действие» в роли модератора. Ключи опций = ровно
// ACTION_EXT_CHOICES бэкенда (app/moderation.py), лейблы — общие словари панели.
const ROLE_CATPOLICY_CATEGORIES = [
    ['insult', 'panel.mod.cat_insult'],
    ['hate', 'panel.mod.cat_hate'],
    ['threat', 'panel.mod.cat_threat'],
    ['sexual', 'panel.mod.cat_sexual'],
    ['spam', 'panel.mod.cat_spam'],
];
const ROLE_CATPOLICY_ACTIONS = [
    ['', 'panel.mod.ext_auto'], ['mask', 'panel.mod.ext_mask'], ['block', 'panel.mod.ext_block'],
    ['timeout_600', 'panel.mod.ext_timeout_600'], ['timeout_3600', 'panel.mod.ext_timeout_3600'],
    ['timeout_86400', 'panel.mod.ext_timeout_86400'], ['timeout_604800', 'panel.mod.ext_timeout_604800'],
    ['timeout_1209600', 'panel.mod.ext_timeout_1209600'], ['ban', 'panel.mod.ext_ban'],
];

const ROLE_FIELDS = {
    // [ключ, label, тип, opts]
    moderator: [
        ['chat_activity', 'role.f.chat_activity', 'select', { chatter: 'role.f.chat_activity.chatter', moderation_only: 'role.f.chat_activity.mod_only', silent: 'role.f.chat_activity.silent' }],
        ['strictness', 'role.f.strictness', 'select', { soft: 'role.f.strictness.soft', normal: 'role.f.strictness.normal', strict: 'role.f.strictness.strict', manual: 'role.f.strictness.manual' }],
        ['ladder_warn', 'role.f.ladder_warn', 'number', {}],
        ['ladder_t1_min', 'role.f.ladder_t1', 'number', {}],
        ['ladder_t2_min', 'role.f.ladder_t2', 'number', {}],
        ['ladder_ban', 'role.f.ladder_ban', 'number', {}],
        ['category_policy', 'role.f.category_policy', 'catpolicy', {}],
        ['translit', 'role.f.translit', 'toggle', {}],
        ['ai_judge', 'role.f.ai_judge', 'toggle', {}],
        ['ai_judge_soft', 'role.f.ai_judge_soft', 'toggle', {}],
        ['warn_before', 'role.f.warn_before', 'toggle', {}],
        ['warn_text', 'role.f.warn_text', 'text', {}],
        ['announce_in_chat', 'role.f.announce_chat', 'toggle', {}],
        ['tts_announce', 'role.f.tts_announce', 'toggle', {}],
        ['confirm_mode', 'role.f.confirm_mode', 'select', { auto: 'role.f.confirm_mode.auto', confirm: 'role.f.confirm_mode.confirm' }],
        ['whitelist', 'role.f.whitelist', 'tags', {}],
    ],
    voice_companion: [
        ['companion_scope', 'role.v.companion_scope', 'select', {
            channel_chat: 'role.v.companion_channel_chat',
        }],
        ['on_speech', 'role.v.on_speech', 'toggle', {}],
        ['on_questions', 'role.v.on_questions', 'toggle', {}],
        ['on_silence', 'role.v.on_silence', 'toggle', {}],
        ['silence_sec', 'role.v.silence_sec', 'number', {}],
        ['command_phrases', 'role.v.command_phrases', 'tags', {}],
        ['reply_delay_sec', 'role.v.reply_delay', 'number', {}],
        ['max_reply_len', 'role.v.max_reply_len', 'number', {}],
        ['interruptible', 'role.v.interruptible', 'toggle', {}],
        ['excluded_topics', 'role.v.excluded_topics', 'tags', {}],
        ['ignore_swears', 'role.v.ignore_swears', 'toggle', {}],
        ['whisper_confidence', 'role.v.whisper_conf', 'number', {}],
        ['min_streamer_words', 'role.v.min_words', 'number', {}],
        ['max_per_10min', 'role.v.max_10min', 'number', {}],
        ['cooldown_sec', 'role.v.cooldown', 'number', {}],
    ],
    lurker: [
        ['mention_reply', 'role.l.mention_reply', 'toggle', {}],
    ],
    chatter: [
        ['anti_assistant', 'role.c.anti_assistant', 'toggle', {}],
        ['preset_key', 'role.c.preset', 'select', {
            '': 'role.c.preset.none', svoi_vdosku: 'role.c.preset.vdosku',
            emotional: 'role.c.preset.emotional', ehidny: 'role.c.preset.ehidny',
            znatok: 'role.c.preset.znatok', memny: 'role.c.preset.memny',
            custom: 'role.c.preset.custom',
        }],
        ['mimic_mode', 'role.c.mode', 'select', {
            off: 'role.c.mode.off', copy: 'role.c.mode.copy', profile: 'role.c.mode.profile',
        }],
        ['mimic_user', 'role.c.user', 'text', {}],
        ['mimic_strength', 'role.c.strength', 'number', {}],
        ['mimic_profile', 'role.c.profile', 'text', {}],
    ],
};

async function loadBotRole(id) {
    if (!id) return;
    try {
        const config = await api(`/api/accounts/${id}/role-config`);
        if (id !== _currentBotId) return;
        _roleCfg = config;
        _roleEditing = _roleCfg.bot_role || 'chatter';
        const account = _allBots.find(bot => bot.id === id);
        if (account) account.bot_role = _roleEditing;
        renderRoleTab();
    } catch (e) { console.error('loadBotRole', e); }
    // P8-C3: отношение к стримеру живёт во вкладке «Роль»
    if (typeof loadBotAttitude === 'function') loadBotAttitude();
}

function renderRoleTab() {
    if (!_roleCfg) return;
    const role = _roleEditing;
    const meta = ROLE_META[role] || ROLE_META.chatter;
    // C1: вкладки и слот role-формы зависят от роли (вкладки «Роль» больше нет)
    if (typeof applyBotRoleVisibility === 'function') applyBotRoleVisibility(role, _roleCfg.configs[role]?.chat_activity || 'chatter');
    if (typeof relocateRoleConfig === 'function') relocateRoleConfig(role);
    const tab = $('botTab-role');
    if (tab) {
        tab.classList.remove('role-chatter', 'role-moderator', 'role-voice_companion', 'role-lurker');
        tab.classList.add('role-' + role);
    }
    const sel = $('roleSelect');
    if (sel) {
        sel.innerHTML = Object.keys(ROLE_META).map(r =>
            `<option value="${r}" ${r === role ? 'selected' : ''}>${esc(_roleT(ROLE_META[r].label))}</option>`).join('');
        // BUGFIX: селект всегда показывает роль ЭТОГО бота — раньше выбранное
        // значение предыдущего бота «переезжало» при переключении ботов.
        sel.value = role;
    }
    const nameEl = $('roleTabRoleName');
    if (nameEl) nameEl.textContent = _roleMetaLabel(role);
    const desc = $('roleDescription');
    if (desc) desc.textContent = _roleT(meta.desc);
    // бейдж роли на карточке в списке
    renderBotsList(_allBots);
    const form = $('roleConfigForm');
    if (!form) return;
    const cfg = _roleCfg.configs[role] || {};
    if (role === 'director') {
        form.innerHTML = `<div class="p-3 form-panel mb-3">
            <p class="text-sm text-muted mb-2">${esc(_roleT('role.director.panel_hint'))}</p>
            <button class="btn btn-primary btn-sm" type="button" onclick="openDirectorPanel()">🎬 ${esc(_roleT('role.director.open_panel'))}</button>
        </div>`;
        return;
    }
    if (role === 'chatter') {
        form.innerHTML = `<p class="text-sm text-muted mb-2">${esc(t('role.chatter_map'))}</p>
            <div class="flex gap-2 flex-wrap mb-3">
                <button class="btn btn-sm btn-secondary" onclick="showBotGroup('identity')">🎭 ${esc(t('tab.identity'))}</button>
                <button class="btn btn-sm btn-secondary" onclick="showBotTab('attention')">🧠 ${esc(t('tab.ai_tts'))}</button>
            </div>
            <div class="p-3 form-panel mb-3">
                <b class="text-sm">📋 ${panelI18n('role.c.mode')}</b>
                <div class="flex gap-2 flex-wrap items-end mt-2">
                    <div class="form-group" style="min-width:220px"><label class="text-xs">${esc(_roleT('role.c.candidates'))}</label>
                        <select id="mimicCandidate" class="input" style="max-width:220px" onchange="if(this.value)document.getElementById('roleF_mimic_user').value=this.value"></select></div>
                    <div class="form-group" style="min-width:200px"><label class="text-xs">${esc(_roleT('role.c.nick_label'))}</label>
                        <input type="text" id="mimicNick" class="input" style="max-width:200px" placeholder="nick" list="mimicCandidatesList"></div>
                    <datalist id="mimicCandidatesList"></datalist>
                    <button class="btn btn-secondary btn-sm" onclick="mimicLoadCandidates()" ${panelI18nAttrs('role.c.candidates_refresh')}>🔄</button>
                    <button class="btn btn-primary btn-sm" onclick="mimicBuildProfile()">🎨 ${esc(_roleT('role.c.profile_btn'))}</button>
                </div>
                <div class="text-xs text-muted mt-2" id="mimicCopyInfo"></div>
            </div>
            <div class="flex gap-2 flex-wrap items-center mb-2">
                <span class="text-xs text-muted">${esc(_roleT('role.c.learned'))}: ${(cfg.learned_pool || []).length}</span>
                <button class="btn btn-secondary btn-sm" onclick="mimicClearLearned()">🗑 ${esc(_roleT('role.c.learned_clear'))}</button>
            </div>`;
        mimicLoadCandidates(cfg.mimic_user);
        const info = $('mimicCopyInfo');
        if (info) {
            const n = (cfg.mimic_copy_msgs || []).length;
            info.innerHTML = cfg.mimic_mode === 'copy' && n
                ? `${panelI18n('dynamic.copy')}: <span data-user-content>${esc(cfg.mimic_user)}</span> · ${n} ${panelI18n('dynamic.messages')} · <span data-user-content>${esc(cfg.mimic_copy_summary || '')}</span>`
                : panelI18n('role.c.copy_none');
        }
        return;
    }
    const rows = (ROLE_FIELDS[role] || []).map(([key, labelKey, type, opts]) => {
        const val = cfg[key];
        const id = `roleF_${key}`;
        if (type === 'toggle') {
            return `<div class="flex items-center gap-2 text-sm mb-1">
                <div class="toggle ${val ? 'active' : ''}" id="${id}" role="switch" aria-checked="${!!val}" aria-labelledby="${id}-label" tabindex="0" onclick="uiToggle(this)"></div>
                <span id="${id}-label" data-i18n="${labelKey}">${esc(_roleT(labelKey))}</span></div>`;
        }
        if (type === 'catpolicy') {
            // Q02: таблица «категория → действие», 5 строк с селектом действия
            const pol = (val && typeof val === 'object') ? val : {};
            const items = ROLE_CATPOLICY_CATEGORIES.map(([cat, catKey]) => {
                const cur = String(pol[cat] ?? '');
                const opts_ = ROLE_CATPOLICY_ACTIONS.map(([v, lk]) =>
                    `<option value="${v}" ${cur === v ? 'selected' : ''}>${esc(_roleT(lk))}</option>`).join('');
                return `<div class="flex items-center gap-2 text-sm mb-1">
                    <span class="badge" style="min-width:140px" data-i18n="${catKey}">${esc(_roleT(catKey))}</span>
                    <select id="${id}_${cat}" class="input select-160" data-i18n-aria-label="${catKey}" aria-label="${esc(_roleT(catKey))}">${opts_}</select>
                </div>`;
            }).join('');
            return `<div class="form-group mb-2" style="min-width:320px;flex:1"><label class="text-xs" data-i18n="${labelKey}">${esc(_roleT(labelKey))}</label>
                ${items}<p class="text-xs text-muted mt-1" data-i18n="role.f.category_policy.hint">${esc(_roleT('role.f.category_policy.hint'))}</p></div>`;
        }
        if (type === 'select') {
            const options = Object.entries(opts).map(([v, lk]) =>
                `<option value="${v}" data-i18n="${lk}" ${String(val) === v ? 'selected' : ''}>${esc(_roleT(lk))}</option>`).join('');
            return `<div class="form-group mb-2" style="min-width:230px"><label class="text-xs" for="${id}" data-i18n="${labelKey}">${esc(_roleT(labelKey))}</label>
                <select id="${id}" class="input" ${key === 'chat_activity' ? 'onchange="applyBotRoleVisibility(\'moderator\',this.value)"' : ''}>${options}</select></div>`;
        }
        if (type === 'number') {
            return `<div class="form-group mb-2" style="min-width:160px"><label class="text-xs" for="${id}" data-i18n="${labelKey}">${esc(_roleT(labelKey))}</label>
                <input type="number" id="${id}" class="input" value="${val ?? ''}"></div>`;
        }
        if (type === 'tags') {
            const joined = Array.isArray(val) ? val.join(', ') : (val || '');
            return `<div class="form-group mb-2 flex-1" style="min-width:240px"><label class="text-xs" for="${id}" data-i18n="${labelKey}">${esc(_roleT(labelKey))}</label>
                <input type="text" id="${id}" class="input" value="${esc(joined)}" placeholder="a, b, c"></div>`;
        }
        return `<div class="form-group mb-2 flex-1" style="min-width:240px"><label class="text-xs" for="${id}" data-i18n="${labelKey}">${esc(_roleT(labelKey))}</label>
            <input type="text" id="${id}" class="input" value="${esc(val ?? '')}"></div>`;
    }).join('');
    const roleHint = role === 'voice_companion'
        ? `<p class="text-xs text-muted mt-2">${esc(_roleT('role.v.tts_percent_hint'))}</p>`
        : '';
    form.innerHTML = `<div class="flex gap-3 flex-wrap">${rows}</div>${roleHint}`;
}

async function roleChange(role) {
    if (!_roleCfg || _roleEditing === role) return;
    _roleCfg.configs[_roleEditing] = _collectRoleForm();
    _roleEditing = role;
    renderRoleTab();
    // BUGFIX: смена роли применяется СРАЗУ (PUT role-config меняет bot_role).
    // Раньше роль менялась только по «💾 Сохранить» — легко пропустить, и бот
    // «оставался» в старой роли (lurker и т.п.).
    try {
        const res = await api(`/api/accounts/${_currentBotId}/role-config`, jopts('PUT', {
            role: _roleEditing, config: _collectRoleForm(),
        }));
        _roleCfg.configs[_roleEditing] = res.config || _roleCfg.configs[_roleEditing];
        const bot = _allBots.find(b => b.id === _currentBotId);
        if (bot) bot.bot_role = res.bot_role || _roleEditing;
        if (typeof renderBotsList === 'function') renderBotsList(_allBots);
        if (typeof loadBotGeneral === 'function') loadBotGeneral();
        // люркер → другая роль снимает observation_only — обновить тумблер
        if (res.observation_only_cleared && typeof loadQuickBehavior === 'function') loadQuickBehavior();
        toast(t('msg.saved'), 'success');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

function _collectRoleForm() {
    const role = _roleEditing;
    const cfg = { ...(_roleCfg.configs[role] || {}) };
    for (const [key, , type] of (ROLE_FIELDS[role] || [])) {
        const el = $(`roleF_${key}`);
        if (!el && type !== 'catpolicy') continue;
        if (type === 'toggle') cfg[key] = toggleChecked(el.id);
        else if (type === 'number') cfg[key] = el.value === '' ? null : Number(el.value);
        else if (type === 'tags') cfg[key] = el.value.split(',').map(s => s.trim()).filter(Boolean);
        else if (type === 'catpolicy') {
            // Q02: собираем только непустые значения; '' = «по тяжести» не храним
            const pol = {};
            for (const [cat] of ROLE_CATPOLICY_CATEGORIES) {
                const sel = $(`roleF_${key}_${cat}`);
                if (sel && sel.value) pol[cat] = sel.value;
            }
            cfg[key] = pol;
        }
        else cfg[key] = el.value;
    }
    return cfg;
}

async function saveRoleConfig() {
    if (!_currentBotId || !_roleCfg) return;
    try {
        const res = await api(`/api/accounts/${_currentBotId}/role-config`, jopts('PUT', {
            role: _roleEditing, config: _collectRoleForm(),
        }));
        if (!res.ok) throw new Error(res.error || 'error');
        toast(t('msg.saved'), 'success');
        await loadBotRole(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function roleResetToDefaults() {
    if (!_currentBotId || !_roleCfg) return;
    if (!confirm(t('role.reset_confirm'))) return;
    try {
        await api(`/api/accounts/${_currentBotId}/role-config`, jopts('PUT', {
            role: _roleEditing, config: {},
        }));
        toast(t('msg.saved'), 'success');
        await loadBotRole(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

function roleExport() {
    if (!_roleCfg) return;
    const payload = { role: _roleEditing, config: _roleCfg.configs[_roleEditing] || {} };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `role-${_roleEditing}-bot${_currentBotId}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
}

async function roleImport(input) {
    if (!_currentBotId || !input?.files?.[0]) return;
    try {
        const parsed = JSON.parse(await input.files[0].text());
        const role = parsed.role, config = parsed.config;
        if (!role || typeof config !== 'object') throw new Error('bad json');
        const res = await api(`/api/accounts/${_currentBotId}/role-config`, jopts('PUT', { role, config }));
        if (!res.ok) throw new Error(res.error || 'error');
        toast(t('role.imported'), 'success');
        await loadBotRole(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
    input.value = '';
}

async function roleSandbox() {
    if (!_currentBotId || !_roleCfg) return;
    const msg = prompt(t('role.sandbox_prompt'), 'matюк в чате');
    if (msg === null) return;
    try {
        const res = await api(`/api/accounts/${_currentBotId}/role-sandbox`, jopts('POST', {
            role: _roleEditing, message: msg,
        }));
        if (!res.ok) throw new Error(res.error || 'error');
        const out = $('roleConfigForm');
        if (out) out.insertAdjacentHTML('beforeend',
            `<div class="p-3 mt-2 text-sm" style="border:1px dashed var(--border);border-radius:8px">
                <b>🧪 ${esc(t('role.sandbox_result'))}</b><pre style="white-space:pre-wrap;margin:6px 0 0">${esc(res.verdict || '')}</pre></div>`);
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

// ── §R4: копирка/самообучение болтуна (UI-обработчики) ──
async function mimicLoadCandidates(preselect) {
    const sel = $('mimicCandidate');
    if (!sel || !_currentBotId) return;
    try {
        const data = await api(`/api/accounts/${_currentBotId}/mimic/candidates`);
        sel.innerHTML = `<option value="">—</option>` +
            (data.items || []).map(u =>
                `<option value="${esc(u.username)}">${esc(u.username)} · ${u.cnt}</option>`).join('');
        const cur = preselect || $('roleF_mimic_user')?.value || '';
        if (cur && [...sel.options].some(o => o.value === cur)) sel.value = cur;
        // P8-C1: свободный ввод ника — подсказки из активных зрителей
        const dl = $('mimicCandidatesList');
        if (dl) dl.innerHTML = (data.items || []).slice(0, 30).map(u =>
            `<option value="${esc(u.username)}"></option>`).join('');
    } catch (e) { /* некритично */ }
}

async function mimicCopyNow() {
    if (!_currentBotId) return;
    const user = $('roleF_mimic_user')?.value || $('mimicCandidate')?.value || '';
    if (!user) return toast(t('role.c.user_required'), 'error');
    try {
        const res = await api(`/api/accounts/${_currentBotId}/mimic/copy`, jopts('POST', { user }));
        if (!res.ok) throw new Error(res.error || 'error');
        toast(t('role.c.copied', { n: res.saved }), 'success');
        await loadBotRole(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function mimicBuildProfile() {
    if (!_currentBotId) return;
    // P8-C1: ник можно ввести свободно (mimicNick), из селекта или поля mimic_user
    const user = ($('mimicNick')?.value || '').trim()
        || $('roleF_mimic_user')?.value || $('mimicCandidate')?.value || '';
    if (!user) return toast(t('role.c.user_required'), 'error');
    const nickField = $('roleF_mimic_user');
    if (nickField && !nickField.value) nickField.value = user;
    try {
        toast(t('role.c.building'), 'info');
        const res = await api(`/api/accounts/${_currentBotId}/mimic/profile-build`, jopts('POST', { user }));
        if (!res.ok) throw new Error(res.error || 'error');
        const ta = $('roleF_mimic_profile');
        if (ta) ta.value = res.profile;
        const mode = $('roleF_mimic_mode');
        if (mode) mode.value = 'profile';
        const info = $('mimicCopyInfo');
        if (info && (res.sources || []).length) info.innerHTML = `${panelI18n('dynamic.sources')}: <span data-user-content>${esc(res.sources.join(', '))}</span>`;
        toast(t('role.c.built'), 'success');
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function mimicClearLearned() {
    if (!_currentBotId) return;
    try {
        await api(`/api/accounts/${_currentBotId}/mimic/learn-clear`, jopts('POST', {}));
        toast(t('msg.saved'), 'success');
        await loadBotRole(_currentBotId);
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

Object.assign(LANGS.ru, {
    'role.c.building': 'Собираю стиль-профиль…',
    'role.c.built': 'Профиль собран — отредактируй при желании и сохрани',
    'role.c.copied': 'Скопировано сообщений: {n} (в промпт пойдут последние 50)',
    'role.c.user_required': 'Выбери юзера-источник стиля',
});
Object.assign(LANGS.en, {
    'role.c.building': 'Building style profile…',
    'role.c.built': 'Profile built — edit if needed and save',
    'role.c.copied': 'Messages copied: {n} (last 50 go to the prompt)',
    'role.c.user_required': 'Pick a style source user',
});
Object.assign(LANGS.ua, {
    'role.c.building': 'Збираю стиль-профіль…',
    'role.c.built': 'Профіль зібрано — за потреби відредагуйте та збережіть',
    'role.c.copied': 'Скопійовано повідомлень: {n} (у промпт підуть останні 50)',
    'role.c.user_required': 'Виберіть юзера-джерело стилю',
});

function roleBadgeHtml(bot) {
    const role = bot?.bot_role || 'chatter';
    const meta = ROLE_META[role] || ROLE_META.chatter;
    return `<span class="bot-card-badge role-badge" style="--role-color:${meta.color}"><span class="role-dot"></span>${esc(_roleMetaLabel(role))}</span>`;
}

// §6: общие подписи вкладки роли (ru/en/ua)
Object.assign(LANGS.ru, {
    'tab.role': '⚙️ Роль',
    'role.pick': 'Роль бота:',
    'role.reset': '↩ Сбросить к дефолтам',
    'role.export': '📤 Экспорт JSON',
    'role.import': 'Импорт JSON',
    'role.sandbox': '🧪 Проверить роль',
    'role.reset_confirm': 'Сбросить настройки этой роли к дефолтам?',
    'role.imported': 'Конфиг роли импортирован',
    'role.sandbox_prompt': 'Тестовое сообщение или ситуация (без реального чата):',
    'role.sandbox_result': 'Что сделает бот',
    'role.chatter_map': 'У болтуна настройки уже проработаны в общих вкладках — карта «что где настраивается»:',
    'director.open_panel': 'Панель Режиссёра',
});
Object.assign(LANGS.en, {
    'tab.role': '⚙️ Role',
    'role.pick': 'Bot role:',
    'role.reset': '↩ Reset to defaults',
    'role.export': '📤 Export JSON',
    'role.import': 'Import JSON',
    'role.sandbox': '🧪 Test the role',
    'role.reset_confirm': 'Reset this role settings to defaults?',
    'role.imported': 'Role config imported',
    'role.sandbox_prompt': 'Test message or situation (no real chat):',
    'role.sandbox_result': 'What the bot would do',
    'role.chatter_map': 'The chatter role is already deeply configured in the shared tabs — a map of what lives where:',
    'director.open_panel': 'Director panel',
});
Object.assign(LANGS.ua, {
    'tab.role': '⚙️ Роль',
    'role.pick': 'Роль бота:',
    'role.reset': '↩ Скинути до дефолтів',
    'role.export': '📤 Експорт JSON',
    'role.import': 'Імпорт JSON',
    'role.sandbox': '🧪 Перевірити роль',
    'role.reset_confirm': 'Скинути налаштування цієї ролі до дефолтів?',
    'role.imported': 'Конфіг ролі імпортовано',
    'role.sandbox_prompt': 'Тестове повідомлення або ситуація (без реального чату):',
    'role.sandbox_result': 'Що зробить бот',
    'role.chatter_map': 'У балакуна налаштування вже опрацьовані в спільних вкладках — карта «що де налаштовується»:',
    'director.open_panel': 'Панель Режисера',
});

// P7 Ф4 (Ф2-1): инициализатор ленивый — loadBotModeration/loadBrainPreview
// живут в поздних чанках (08/09), top-level const рвал весь чанк в браузере.
function _botTabLoaders() {
    return {
        general: loadBotGeneral,
        'brain-x': loadBrainPreview,
        persona: loadBotPersona,
        channels: loadBotChannels,
        triggers: loadBotTriggers,
        events: loadBotEvents,
        filters: loadBotFilters,
        moderation: loadBotModeration,
        'chat-users': loadBotChatUsers,
        memory: loadBotMemory,
        knowledge: loadKnowledge,
        snippets: loadBotSnippets,
        tts: loadBotTTS,
        'voice-clones': loadBotVoiceClones,
        attention: loadBotAttention,
        streamer: loadBotStreamer,
        logs: loadBotLogs,
        files: loadBotFiles,
        sandbox: loadBotSandbox,
    };
}

function showBotTab(name) {
    if (typeof botRoleAllowsTab === 'function' && !botRoleAllowsTab(name)) name = 'general';
    if (typeof BOT_TAB_GROUPS !== 'undefined') _currentBotGroup = Object.keys(BOT_TAB_GROUPS).find(group => BOT_TAB_GROUPS[group].includes(name)) || 'overview';
    document.querySelectorAll('.bot-tab').forEach(t => t.classList.add('hidden'));
    document.querySelectorAll('[data-bot-tab]').forEach(b => b.classList.remove('active'));
    const tab = $('botTab-' + name);
    const btn = document.querySelector(`[data-bot-tab="${name}"]`);
    if (tab) tab.classList.remove('hidden');
    if (btn) btn.classList.add('active');
    try { localStorage.setItem('panel_active_bot_tab', name); } catch (e) {}

    const loader = _botTabLoaders()[name];
    if (loader && _currentBotId) {
        loader(_currentBotId);
    }
}

