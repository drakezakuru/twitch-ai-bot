/* ═══════════════════════════════════════════════════════
   v12 App.js — navigation + data loading + CRUD + WS
   Секції: dashboard, bots, chat, analytics, settings
   ═══════════════════════════════════════════════════════ */

'use strict';

const API = '';

// ── Global state ────────────────────────────────────
let _allBots = [];            // array of account dicts
let _botStatuses = {};        // {account_id: {connected, channels}}
let _botStats = {};           // {account_id: {sent, read}}
let _currentBotId = null;
let _currentBot = null;
let _personaCache = null;     // persona dict of current bot
let _channelsCache = [];      // channels of current bot
let _overridesCache = [];     // channel overrides of current bot
let _aiConfig = {};           // global AI config

// ── Helpers ─────────────────────────────────────────
function esc(s) {
    if (s === null || s === undefined) return '';
    const d = document.createElement('div');
    d.textContent = String(s);
    return d.innerHTML;
}
function $(id) { return document.getElementById(id); }
function fmtTime(ts) {
    try { return new Date(ts).toLocaleTimeString(); } catch (e) { return ''; }
}
async function api(url, opts) {
    const res = await fetch(API + url, opts);
    let payload = null;
    try { payload = await res.json(); } catch (e) {}
    if (!res.ok || payload?.ok === false) {
        const info = apiErrorInfo(payload, res.statusText);
        const err = new Error(info.message);
        err.code = info.code;
        err.params = info.params;
        err.status = res.status;
        err.payload = payload;
        throw err;
    }
    return payload;
}
function apiErrorInfo(payload, statusText = '') {
    const nested = payload?.error;
    let code = '';
    let params = {};
    let legacy = '';
    if (nested && typeof nested === 'object') {
        code = typeof nested.code === 'string' ? nested.code : '';
        params = nested.params && typeof nested.params === 'object' ? nested.params : {};
    } else {
        code = typeof payload?.code === 'string' ? payload.code : '';
        params = payload?.params && typeof payload.params === 'object' ? payload.params : {};
        legacy = typeof nested === 'string' ? nested : (typeof payload?.detail === 'string' ? payload.detail : '');
    }
    if (code) {
        const key = `api.error.${code}`;
        const translated = t(key, params);
        const safeFallback = typeof LANGS === 'object'
            ? (LANGS.ru?.['api.error.unknown'] || 'Не удалось выполнить запрос')
            : t('api.error.unknown');
        const known = typeof LANGS === 'object' && Object.values(LANGS).some(labels => Object.hasOwn(labels, key));
        return {code, params, message: known ? translated : safeFallback};
    }
    return {code: '', params: {}, message: legacy || statusText || t('api.error.unknown')};
}
function jopts(method, body) {
    return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) };
}

// ── Toast ───────────────────────────────────────────
const TOAST_TRANSLATIONS = [
    [/^Нічого не знайдено$/, 'toast.not_found'],
    [/^Помилка: (.+)$/, 'toast.error_detail'],
    [/^Ошибка: (.+)$/, 'toast.error_detail'],
    [/^Виберіть хоча б одного бота$/, 'toast.select_bot'],
    [/^Выберите хотя бы одного бота$/, 'toast.select_bot'],
    [/^Виберіть бота для генерації$/, 'toast.select_bot_generate'],
    [/^Выберите бота для генерации$/, 'toast.select_bot_generate'],
    [/^Заготовка збережена$/, 'toast.snippet_saved'],
    [/^Заготовка сохранена$/, 'toast.snippet_saved'],
    [/^Факт сохранён$/, 'toast.fact_saved'],
    [/^Факт збережено$/, 'toast.fact_saved'],
    [/^Нічого не знайдено$/, 'toast.not_found'],
    [/^Немає змін$/, 'toast.no_changes'],
    [/^Виберіть канал$/, 'toast.select_channel'],
    [/^Виберіть бота і введіть текст$/, 'toast.select_bot_text'],
    [/^Немає каналів для відправки$/, 'toast.no_channels_send'],
    [/^Користувача забанено$/, 'toast.user_banned'],
    [/^Користувача розбанено$/, 'toast.user_unbanned'],
    [/^Слово додано до фільтра$/, 'toast.word_added'],
    [/^Слово видалено$/, 'toast.word_deleted'],
    [/^Бекап відновлено$/, 'toast.backup_restored'],
    [/^Помилка відновлення$/, 'toast.restore_error'],
    [/^Перевіряю зʼєднання\.\.\.$/, 'toast.checking_connection'],
    [/^AI зʼєднання працює ✅$/, 'toast.ai_connected'],
    [/^TTS збережено$/, 'toast.tts_saved'],
    [/^Налаштування уваги збережено$/, 'toast.attention_saved'],
    [/^Поведінку збережено$/, 'toast.behavior_saved'],
    [/^Персону збережено$/, 'toast.persona_saved'],
    [/^Пресет характеру застосовано$/, 'toast.persona_preset_applied'],
    [/^Персону згенеровано AI$/, 'toast.persona_generated'],
    [/^Віджет TTS відкрито в новій вкладці$/, 'toast.tts_opened'],
    [/^Скопійовано$/, 'toast.copied'],
    [/^Логи очищено$/, 'toast.logs_cleared'],
    [/^Канал видалено$/, 'toast.channel_deleted'],
    [/^Канал #(.+) додано$/, 'toast.channel_added'],
    [/^Приєднано до #(.+)$/, 'toast.channel_joined'],
    [/^Вийшов з #(.+)$/, 'toast.channel_left'],
    [/^Бота видалено$/, 'toast.bot_deleted'],
    [/^Бота (.+) створено$/, 'toast.bot_created'],
    [/^Бота запущено$/, 'toast.bot_started'],
    [/^Бота зупинено$/, 'toast.bot_stopped'],
    [/^Основні налаштування збережено$/, 'toast.general_saved'],
    [/^AI перевизначення збережено$/, 'toast.ai_override_saved'],
    [/^Заготовка додана$/, 'toast.snippet_added'],
    [/^Заготовка видалена$/, 'toast.snippet_deleted'],
    [/^Генерую 5 заготовок\.\.\.$/, 'toast.generating_snippets'],
    [/^Введите название и текст фразы$/, 'toast.enter_snippet'],
    [/^Введіть назву та текст фрази$/, 'toast.enter_snippet'],
    [/^Выберите бота для сохранения фразы$/, 'toast.select_bot_save'],
    [/^Виберіть бота для збереження фрази$/, 'toast.select_bot_save'],
    [/^Добавлено заготовок: (\d+)$/, 'toast.snippets_added'],
    [/^Додано (\d+) заготовок$/, 'toast.snippets_added'],
    [/^Отправлено ботами: (\d+)$/, 'toast.sent_by_bots'],
    [/^Відправлено ботами: (\d+)$/, 'toast.sent_by_bots'],
    [/^Ошибка генерации: (.+)$/, 'toast.generation_error'],
    [/^Помилка генерації: (.+)$/, 'toast.generation_error'],
    [/^Ошибка восстановления$/, 'toast.restore_error'],
    [/^AI відповів з помилкою: (.+)$/, 'toast.ai_error'],
    [/^AI ответил с ошибкой: (.+)$/, 'toast.ai_error'],
    [/^Бекап відновлено$/, 'toast.backup_restored'],
    [/^Підключено до #(.+)$/, 'toast.channel_joined'],
    [/^Подключено к #(.+)$/, 'toast.channel_joined'],
];
function toast(msg, type = 'info') {
    let display = msg;
    for (const [pattern, key] of TOAST_TRANSLATIONS) {
        const match = String(msg).match(pattern);
        if (match) { display = t(key, { detail: match[1] || '' }); break; }
    }
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.textContent = display;
    $('toastContainer').appendChild(el);
    setTimeout(() => el.remove(), 3200);
}

// ── P8-C13: guard несохранённых изменений (уход со страницы/формы) ──
const _dirtyScopes = new Set();

function markDirty(scope) { _dirtyScopes.add(scope); }
function clearDirty(scope) { _dirtyScopes.delete(scope); }
function isDirty() { return _dirtyScopes.size > 0; }

// Штатная всплывашка браузера при закрытии вкладки/перезагрузке,
// если есть несохранённые изменения.
window.addEventListener('beforeunload', (e) => {
    if (isDirty()) { e.preventDefault(); e.returnValue = ''; }
});

// Внутренняя навигация (назад из карточки бота, смена секции, удаление и т.п.):
// спросить подтверждение; true = «продолжить и потерять», false = «отменить».
function confirmDirty() {
    if (!isDirty()) return true;
    const ok = confirm(t('dirty.confirm'));
    if (ok) { _dirtyScopes.clear(); }
    return ok;
}

// Привязать поля формы к скоупу: input/change → markDirty; сброс после save.
function bindDirtyWatch(scope, ids) {
    ids.forEach(id => {
        const el = $(id);
        if (!el || el.dataset.dirtyBound === scope) return;
        el.addEventListener('input', () => markDirty(scope));
        el.addEventListener('change', () => markDirty(scope));
        el.dataset.dirtyBound = scope;
    });
}

function countLabel(count, forms) {
    const lang = localStorage.getItem('lang') || 'ru';
    if (lang === 'en') return `${count} ${forms.en}`;
    if (lang === 'ua' && forms.ua) {
        const n = Math.abs(Number(count)) % 100;
        const one = n % 10 === 1 && n !== 11;
        const few = n % 10 >= 2 && n % 10 <= 4 && (n < 10 || n >= 20);
        return `${count} ${one ? forms.ua.one : few ? forms.ua.few : forms.ua.many}`;
    }
    const n = Math.abs(Number(count)) % 100;
    const one = n % 10 === 1 && n !== 11;
    const few = n % 10 >= 2 && n % 10 <= 4 && (n < 10 || n >= 20);
    const form = one ? forms.one : few ? forms.few : forms.many;
    return `${count} ${form}`;
}

// ── Language switcher (RU/EN/UA, как в v10) ─────────
const LANGS = {
    ru: {
        'nav.dashboard': 'Обзор', 'nav.bots': 'Боты', 'nav.channels': 'Каналы', 'nav.chat': 'Чат',
        'nav.analytics': 'Статистика', 'nav.settings': 'Настройки',
        'title.dashboard': 'Обзор', 'title.bots': 'Боты', 'title.chat': 'Чат',
        'bots.filter.all_roles': 'Все роли', 'bots.filter.all_channels': 'Все каналы', 'bot.memory.long_term': 'Долгосрочная память о зрителях', 'bot.memory.disabled_hint': 'Память о зрителях выключена у этого бота — включите тумблер выше, чтобы бот запоминал факты.', 'panel.summary.title': '📊 Расклад', 'panel.summary.online': 'Подключено: {online} из {total}', 'panel.summary.channel': 'Канал', 'panel.summary.bots': 'Боты', 'panel.summary.connected': 'Живые подключения',
        'bots.change_channel': 'Сменить канал', 'bots.change_channel_new': '+ Новый канал',
        'bots.change_channel_hint': 'Привяжите бота к существующему каналу другого бота (перенос), к уже своему или создайте новый канал.',
        'bots.change_channel_none': 'Нет свободных каналов у других ботов',
        'token.status.valid': 'Токен активен', 'token.status.expiring': 'Токен истекает',
        'token.status.expired': 'Токен истёк', 'token.status.not_refreshable': 'Не продлевается',
        'token.status.unknown': 'Статус токена неизвестен', 'token.refresh': '🔄 Обновить токен',
        'token.refresh_done': 'Токен обновлён', 'token.refresh_failed': 'Не удалось обновить токен',
        'token.manual_hint': 'Этот токен не будет продлеваться автоматически.',
        'token.auto_refresh': 'Автоматически продлевать токены',
        'token.auto_refresh_hint': 'Работает для ботов, вошедших через Twitch, когда Client ID и Client Secret настроены.',
        'token.warning_days': 'Показывать «истекает» заранее, дней',
        'token.warning_days_hint': 'Меняет только момент появления жёлтого статуса на карточке бота.',
        'token.save_settings': 'Сохранить продление токенов', 'token.settings_saved': 'Настройки продления сохранены',
        'check.open': 'Проверить', 'check.title': 'Проверка ботов',
        'check.hint': 'Тестовый канал используется только для этой проверки. Боты ждут сообщение из чата и отправляют по одному контрольному сообщению.',
        'check.channel': 'Тестовый канал', 'check.channel_hint': 'Выберите используемый канал или введите Twitch login без #.',
        'check.message': 'Контрольное сообщение', 'check.message_hint': 'Маркер [ник] заменяется на имя каждого бота.',
        'check.default_message': '✅ проверка связи [ник]', 'check.send_enabled': 'Отправлять контрольное сообщение (по умолчанию выкл.)', 'check.start': 'Запустить проверку',
        'check.cancel_running': 'Остановить проверку', 'check.running': 'Проверка идёт: ожидание сообщения занимает до 45 секунд…',
        'check.completed': 'Проверка завершена', 'check.cancelled': 'Проверка остановлена', 'check.failed': 'Не удалось выполнить проверку',
        'check.invalid_input': 'Укажите канал и контрольное сообщение', 'check.download_csv': 'Скачать CSV', 'check.download_text': 'Скачать текст',
        'check.col.bot': 'Бот', 'check.col.token': 'Токен', 'check.col.join': 'IRC', 'check.col.read': 'Чтение',
        'check.col.send': 'Отправка', 'check.col.result': 'Результат',
        'check.value.valid': 'активен', 'check.value.expired': 'истёк', 'check.value.unknown': 'неизвестно',
        'check.value.online': 'подключён', 'check.value.error': 'ошибка', 'check.value.confirmed': 'подтверждено',
        'check.value.no_messages': 'сообщений не было', 'check.value.sent': 'отправлено', 'check.value.not_run': 'не выполнялось',
        'check.value.success': 'успешно', 'check.value.not_confirmed': 'не подтверждено',
        'check.reason.ok': 'бот читает чат и отправил сообщение', 'check.reason.no_messages': 'сообщений в окне ожидания не было',
        'check.reason.token_expired': 'токен истёк', 'check.reason.token_unknown': 'не удалось проверить токен',
        'check.reason.join_timeout': 'истекло время подключения', 'check.reason.join_failed': 'не удалось подключиться',
        'check.reason.channel_not_connected': 'канал не подключён', 'check.reason.send_rejected': 'Twitch отклонил сообщение',
        'check.reason.bot_not_found': 'бот не найден', 'check.reason.not_run': 'не выполнялось', 'check.reason.check_failed': 'ошибка проверки',
        'check.error.invalid_account_ids': 'Выберите от 1 до 100 ботов', 'check.error.invalid_channel': 'Некорректный Twitch login канала',
        'check.error.invalid_message': 'Некорректное контрольное сообщение', 'check.error.check_failed': 'Не удалось запустить проверку',
        'channels.title': 'Каналы', 'channels.hint': 'Используемые Twitch-каналы, добавленные боты и их фактическое подключение.',
        'channels.load_failed': 'Не удалось загрузить каналы', 'channels.empty': 'Используемых каналов пока нет',
        'channels.connected_count': 'Подключено: {connected} из {total}',
        'channels.settings_btn': '⚙️ Настройки канала', 'channels.settings_tabs': 'Настройки канала',
        'channels.clone_btn': '📋 Скопировать с канала...', 'channels.clone_title': '📋 Скопировать настройки канала',
        'channels.clone_hint': 'Перенести правила модерации, запрещённые и разрешённые темы в текущий канал.',
        'channels.clone_from': 'Откуда скопировать', 'channels.clone_rules': '🛡 База правил модерации',
        'channels.clone_bans': '🚫 Запретные темы канала', 'channels.clone_allowed': '✅ Разрешённые темы канала',
        'channels.clone_submit': 'Скопировать', 'channels.clone_no_source': 'Нет других каналов для копирования',
        'channels.clone_pick_at_least_one': 'Выберите хотя бы один пункт для копирования',
        'channels.clone_ok': 'Настройки успешно скопированы из #{from} в #{to}',
        'channels.bots_tab': '🤖 Боты канала',
        'channels.bots_tab_hint': 'Боты, привязанные к этому каналу — статус подключения, переименование канала для конкретного бота, отвязка, добавление новых ботов.',
        'channels.bots_tab_empty': 'К этому каналу пока не привязан ни один бот.',
        'channels.base_rules': '🛡 База правил',
        'channels.base_rules_hint': 'Свой список правил этого канала. Наказывают по нему только боты с ролью «модератор»; правило конкретного бота с тем же словом переопределяет базу.',
        'channels.base_rules_empty': 'База канала пуста — стартуйте из пресета Twitch или добавьте правило.',
        'channels.base_rules_add': '+ Добавить в базу канала',
        'channels.base_rules_seed': '🌱 Стартовать из пресета Twitch',
        'channels.base_rules_seed_ru': '🇷🇺 Пресет РФ/СНГ',
        'channels.base_rules_seeded': 'Пресет правил: добавлено правил — {count}',
        'channels.mod_tab': '🧾 Модерация', 'channels.mod_bot': 'Бот',
        'channels.profile_tab': '👤 Профиль канала', 'channels.profile_bot': 'Бот (для lore и сводок)',
        'channels.profile_hint': 'Инфо о стримере этого канала: профиль и фото хранятся per-channel. Бот ниже понадобится для lore и live-сводок этого канала.',
        'channels.bans_title': '🚫 Запретные темы канала', 'channels.bans_inherited': 'наследует пресет Twitch',
        'channels.runs_title': '📝 Сводки: прогоны',
        'channels.bans_hint': 'Что ботам нельзя поднимать в чате этого канала. Одна запретка на строку, строки с # — комментарии. Пока своего списка нет, канал наследует базовый пресет Twitch.',
        'channels.bans_placeholder': 'Не обсуждать политику\nБез спойлеров к сериалам',
        'channels.bans_seed': '🌱 Взять пресет Twitch',
        'channels.bans_preset_title': 'Базовый пресет Twitch (наследуется каналами без своего списка)',
        'channels.allowed_title': '✅ Что ботам можно делать (разрешённые темы)', 'channels.allowed_inherited': 'наследует пресет Twitch',
        'channels.allowed_hint': 'Что ботам разрешено и поощряется делать в чате этого канала. Одно указание на строку, строки с # — комментарии. Пока своего списка нет, канал наследует базовый пресет Twitch.',
        'channels.allowed_placeholder': 'Обсуждать текущую игру\nПоддерживать стримера',
        'channels.allowed_seed': '🌱 Взять пресет Twitch',
        'channels.allowed_preset_title': 'Базовый пресет разрешённых тем (наследуется каналами без своего списка)',
        'channels.profile_lore_hint': 'Факты о стримере у выбранного бота на этом канале: добавленные вручную и предложенные сводками/чатом. В список попадают только после подтверждения ✓.',
        'channels.profile_summary_hint': 'Live-сводки «как прошёл стрим» у выбранного бота на этом канале: вкл/выкл и язык переопределяют настройки бота, другие каналы не трогают. Ручной прогон за период — в «Мозге».',
        'channels.mod_queue': '⏳ Очередь подтверждения',
        'channels.mod_queue_hint': '«Бан навсегда» защищённого зрителя не применён и ждёт вашего решения: до него сообщение не удаляется, не маскируется и таймаут не даётся.',
        'channels.mod_queue_empty': 'Очередь пуста — отложенных случаев нет.',
        'channels.mod_queue_ban': 'Забанить', 'channels.mod_queue_pardon': 'Не наказывать',
        'channels.mod_resolved_yes': 'Наказание применено.', 'channels.mod_resolved_no': 'Случай закрыт без наказания.',
        'channels.mod_journal': '📜 Журнал наказаний',
        'channels.mod_journal_empty': 'Наказаний пока не было.',
        'channels.mod_status_applied': 'применено', 'channels.mod_status_pending': 'ждёт подтверждения',
        'channels.mod_status_cancelled': 'отменено владельцем', 'channels.mod_status_expired': 'закрыто по сроку',
        'channels.mod_protected': '🛡 Защищённые от «бана навсегда»',
        'channels.mod_protected_hint': 'Модераторы, редакторы и стример защищены автоматически — вписывать их не нужно. Таймауты применяются к защищённым как настроено: защита только от вечного бана.',
        'channels.mod_protected_empty': 'Ручной список пуст.', 'channels.mod_protected_user': 'Ник зрителя',
        'channels.mod_protected_note': 'Заметка', 'channels.mod_protected_add': '+ Защитить',
        'channels.mod_protected_remove': 'Убрать из защищённых',
        'channels.mod_unban': '🔓 Разбанить', 'channels.mod_unban_btn': 'Разбанить',
        'channels.mod_unban_ok': 'Зритель разбанен.', 'channels.mod_unban_already': 'Зритель уже не забанен.',
        'channels.mod_no_bot': 'К каналу не подключён бот.', 'channels.mod_action_ban': 'бан навсегда',
        'channels.mod_action_timeout': 'таймаут',
        'channels.mod_manual_punish': '⚡ Быстрое наказание', 'channels.mod_duration': 'Длительность',
        'channels.mod_reason': 'Причина', 'channels.mod_apply_punish': 'Применить',
        'channels.mod_quick_reasons': 'Быстрые шаблоны:', 'channels.mod_quick_notes': 'Быстрые заметки:',
        'channels.mod_punish_fill_fields': 'Укажите ник зрителя и выберите бота.', 'channels.mod_punish_ok': 'Наказание применено.',
        'channels.add': '+ Добавить канал', 'channels.add_hint': 'Канал привяжется к выбранному боту; тот же канал можно добавить нескольким ботам.',
        'channels.add_bot': 'Бот', 'channels.add_no_bots': 'Сначала добавьте бота', 'channels.add_invalid': 'Укажите канал и бота',
        'channels.rename': 'Переименовать канал', 'channels.rename_prompt': 'Новое имя канала (без #)',
        'channels.rename_conflict': 'Имя занято в таблицах: {tables}. Заменить их данные?',
        'channels.delete': 'Удалить канал', 'channels.delete_hint': 'Вместе с привязкой удалятся связанные данные канала.',
        'channels.delete_no_data': 'Связанных данных нет — канал удалится безопасно.',
        'channels.delete_confirm_data': 'Внимание: будет удалено записей — {total}.',
        'channels.deps_failed': 'Не удалось получить зависимости канала', 'channels.binding_actions': 'Действия для этого бота',
        'toast.channel_renamed': 'Канал переименован в #{detail}', 'toast.channel_rename_failed': 'Не удалось переименовать канал',
        'toast.channel_add_failed': 'Не удалось добавить канал', 'toast.channel_delete_failed': 'Не удалось удалить канал',
        'bulk.title': 'Добавить и проверить', 'bulk.hint': 'Каждая новая или существующая связка бот×канал будет сразу проверена.',
        'bulk.bots': 'Боты', 'bulk.bots_hint': 'Выберите ботов, которых нужно добавить к каналу.',
        'bulk.channels': 'Каналы', 'bulk.channels_hint': 'По одному Twitch login на строку или через запятую, без #.',
        'bulk.start': 'Добавить и проверить', 'bulk.add_bots': 'Добавить ботов и проверить', 'bulk.cancel': 'Остановить операцию', 'bulk.select_all': 'Выбрать всех', 'bulk.deselect_all': 'Снять выбор',
        'bulk.invalid_input': 'Выберите ботов, каналы и укажите сообщение', 'bulk.running': 'Добавление и проверка выполняются…',
        'bulk.completed': 'Операция завершена', 'bulk.cancelled': 'Операция остановлена', 'bulk.failed': 'Операция завершилась с ошибкой',
        'bulk.col.channel': 'Канал', 'bulk.col.add': 'Добавление', 'bulk.col.check': 'Проверка',
        'bulk.value.added': 'успешно', 'bulk.value.skipped': 'пропущено', 'bulk.value.error': 'ошибка',
        'bulk.reason.added': 'связка добавлена', 'bulk.reason.already_exists': 'уже существует',
        'bulk.reason.bot_not_found': 'бот не найден', 'bulk.reason.add_failed': 'не удалось добавить', 'bulk.value.changed': 'изменено', 'bulk.reason.ok': 'связки обновлены', 'bulk.reason.binding_disabled': 'связка выключена', 'bulk.reason.change_failed': 'не удалось сменить канал', 'bulk.change_channel': 'Сменить канал', 'bulk.change_apply': 'Сменить выбранным', 'bulk.change_new': 'Новый канал (если нет в списке)', 'bulk.change_need_channel': 'Укажите канал: выберите из списка или впишите', 'bulk.change_replace': 'Снять прежние каналы у выбранных ботов', 'bulk.change_hint': 'Канал выбирается из списка или вводится именем; снятые привязки не удаляют сами каналы — только отвязывают ботов.', 'bulk.change_done': 'Готово: изменено {changed}, добавлено {added}, пропущено {skipped}, ошибок {errors}.',
        'bulk.error.invalid_direction': 'Некорректное направление операции', 'bulk.error.invalid_account_ids': 'Выберите от 1 до 100 ботов',
        'bulk.error.invalid_channels': 'Проверьте Twitch login каналов', 'bulk.error.too_many_pairs': 'За один раз можно обработать до 500 связок',
        'bulk.error.invalid_message': 'Некорректное контрольное сообщение', 'bulk.error.bulk_failed': 'Не удалось запустить операцию',
        'title.analytics': 'Статистика', 'title.settings': 'Настройки',
        'btn.start': '▶ Старт', 'btn.stop': '⏹ Стоп', 'btn.save': '💾 Сохранить',
        'btn.delete': '🗑 Удалить', 'btn.add': '+ Добавить', 'btn.cancel': 'Отмена',
        'btn.connect': '🟢 Подключить', 'btn.disconnect': '🔴 Отключить',
        'label.online': '🟢 Online', 'label.offline': '🔴 Offline', 'label.enabled': '🟡 Включён',
        'label.connected': '🟢 Подключено', 'label.disconnected': '🔴 Отключено',
        'label.no_channels': 'без каналов', 'label.search': 'Поиск...',
        'msg.saved': 'Сохранено', 'msg.deleted': 'Удалено', 'msg.error': 'Ошибка',
        'msg.started': 'Бот запущен', 'msg.stopped': 'Бот остановлен',
        'msg.connected': 'Подключено', 'msg.disconnected': 'Отключено',
        'app.title': 'Панель Twitch AI Bot', 'nav.collapse': 'Свернуть', 'nav.menu': 'Меню', 'nav.theme': 'Тема',
        'search.placeholder': 'Поиск... (Ctrl+K)', 'btn.refresh': '🔄 Обновить', 'btn.back': '← Назад',
        'btn.add_bot': '+ Добавить бота', 'btn.send': 'Отправить', 'btn.history': '📜 История',
        'dm.title': '💬 Разговор в Twitch-чате', 'dm.public_hint': 'Сообщение и ответ бота увидят все зрители выбранного канала.', 'dm.channel': 'Канал Twitch', 'dm.channel_required': 'Выберите подключённый канал', 'dm.twitch_error': 'Не удалось отправить в Twitch: {detail}', 'dm.open_btn': '💬 Разговор',
        'dm.voice': '🎤 Голос', 'dm.photo': '🖼 Картинка', 'dm.text_input': '⌨️ Текст', 'dm.speak_reply': '🔊 Озвучивать ответы',
        'dm.attach_photo': 'Прикрепить картинку', 'dm.record': 'Записать', 'dm.stop': 'Стоп', 'dm.placeholder': 'Напиши у Twitch-чат…',
        'dm.you': 'Ты', 'dm.you_bot': 'Бот', 'dm.photo_ready': 'Картинка прикреплена', 'dm.transcribing': 'Распознаю голос…',
        'dm.voice_sent': 'голосовое сообщение', 'dm.photo_sent': 'картинка', 'dm.mic_error': 'Микрофон недоступен', 'dm.empty': 'Пусто — нечего отправлять', 'dm.reset': '🗑 Очистить разговор',
        'btn.clear': 'Очистить', 'btn.generate': 'Сгенерировать', 'btn.test': '🔌 Проверить соединение',
        'label.bots_online': 'Подключено ботов', 'label.bots_enabled': 'Включено',
        'label.messages_read': 'Прочитано сообщений', 'label.bot_replies': 'Написано ботами',
        'label.live_events': 'Live-события', 'label.live_chat': 'Живой чат', 'label.loading': 'Загрузка...',
        'health.title': '🩺 Здоровье эфира', 'health.silent': 'молчит', 'health.responds': 'отвечает',
        'health.last_activity': 'последняя активность', 'health.empty': 'Нет привязанных каналов.',
        'label.waiting_events': 'Ожидание событий...', 'label.no_data': 'Данных нет', 'label.no_bots': 'Ботов нет',
        'label.all_channels': 'Все каналы', 'label.all_bots': 'Все боты', 'label.all_levels': 'Все уровни',
        'label.message_from_bot': 'Сообщение от имени бота...', 'label.no_messages': 'Сообщений пока нет',
        'label.activity': 'Активность по ботам (написано сообщений)', 'label.bot_logs': '📋 Логи ботов',
        'settings.group_ai': 'AI и провайдеры', 'settings.group_diagnostics': 'Журналы и диагностика', 'settings.group_twitch': 'Подключение Twitch', 'settings.group_security': 'Безопасность и интерфейс', 'settings.group_maintenance': 'Данные и обслуживание', 'settings.group_modsite': 'Moderator-site: администрирование',
        'settings.diagnostics': '🛠 Журналы и диагностика', 'settings.bot_logs_hint': 'Логи ботов находятся в «Статистике»: фильтруйте по боту, уровню и периоду, затем выгружайте CSV.', 'btn.open_bot_logs': 'Открыть логи ботов',
        'settings.ai_global': '🧠 AI (глобально)', 'placeholder.eleven_key_set':'ключ задан (введите новый для замены)',
        'settings.tts_map_title': '🗺 Кто что озвучивает',
        'settings.mod_tts_title': '🎙 Moderator TTS console', 'settings.mod_tts_hint': 'Голоса, правила и доступ Twitch-пользователей для точной пары бот/канал.',
        'settings.mod_media_title': 'GIF / медиа для модераторов', 'settings.mod_media_hint': 'Owner-approved библиотека и отдельный token-limited OBS Browser Source для выбранного scope.', 'settings.mod_media_upload': 'Загрузить и одобрить', 'settings.mod_media_obs': 'Новый OBS URL', 'settings.mod_media_stop': 'Stop', 'settings.mod_media_clear': 'Clear queue', 'settings.mod_media_kill': 'Kill switch', 'settings.mod_media_empty': 'Медиа пока нет.',
        'settings.mod_media_obs_url': 'OBS Browser Source URL', 'settings.mod_media_reveal': 'Показать на 30 секунд', 'settings.mod_media_preview': 'Безопасное превью moderator media', 'settings.mod_media_rotate_hint': 'Ротация сразу отключает старый OBS URL.', 'settings.mod_media_rotate_confirm': 'Создать новый URL? Старый OBS URL сразу перестанет работать.', 'settings.mod_media_revealed': 'URL показан на 30 секунд.', 'settings.mod_media_hidden': 'OBS URL настроен и скрыт.', 'settings.mod_media_rotation_required': 'Старый URL продолжает работать, но показать его нельзя. Выполните ротацию.', 'settings.mod_media_obs_missing': 'Создайте отдельный ограниченный URL для OBS.', 'settings.mod_media_reveal_error': 'Не удалось показать URL. Доступ разрешён только локальному владельцу.', 'settings.mod_media_copied': 'OBS URL скопирован.', 'settings.mod_media_copy_error': 'Не удалось скопировать OBS URL.',
        'settings.mod_sound_title': 'Звуки для модераторов', 'settings.mod_sound_hint': 'Одобренные треки играют через существующий Soundboard; добавьте exact-scoped URL ниже в OBS.', 'settings.mod_sound_empty': 'Треков пока нет.', 'settings.mod_sound_obs': 'Новый OBS URL', 'settings.mod_sound_obs_configured': 'OBS token настроен. Новый URL сразу отменит предыдущий.', 'settings.mod_sound_obs_missing': 'Создайте отдельный ограниченный URL для OBS.',
        'settings.tts_output_title': 'Единственный TTS audio output', 'settings.tts_output_hint': 'Выберите один exact-scoped Browser Source. Старые URL остаются legacy и не имеют active-source telemetry.', 'settings.tts_output_test': 'Тест output', 'settings.tts_output_test_text': 'Проверка выбранного источника озвучки',
        'settings.mod_tts_scope': 'Бот / канал', 'settings.mod_tts_source': 'Источник TTS', 'settings.mod_tts_voices': 'Разрешённые голоса',
        'settings.mod_tts_alias_ph': 'Короткий alias', 'settings.mod_tts_provider_ph': 'Provider', 'settings.mod_tts_voice_id_ph': 'Зарегистрированный voice ID',
        'settings.mod_tts_add_voice': 'Добавить голос', 'settings.mod_tts_policy': 'Правило источника', 'settings.mod_tts_enabled': 'Включено',
        'settings.mod_tts_voice_choice': 'Разрешить выбор голоса', 'settings.mod_tts_cooldown': 'Cooldown, сек', 'settings.mod_tts_rate': 'Максимум в минуту',
        'settings.mod_tts_length': 'Максимальная длина', 'settings.mod_tts_blacklist': 'Blacklist, слова через запятую', 'settings.mod_tts_save_policy': 'Сохранить правило',
        'settings.mod_tts_access': 'Доступ Twitch', 'settings.mod_tts_user_id': 'Стабильный Twitch user ID', 'settings.mod_tts_login': 'Twitch login (подпись)',
        'settings.mod_tts_save_grant': 'Сохранить доступ', 'settings.mod_tts_revoke': 'Отозвать', 'settings.mod_tts_chat_enabled': 'Команда в Twitch-чате',
        'settings.mod_tts_save_chat': 'Сохранить команду', 'settings.mod_tts_load_error': 'Не удалось загрузить настройки Moderator TTS.',
        'settings.mod_tts_no_scope': 'Нет включённых пар бот/канал.', 'settings.mod_tts_no_voices': 'Разрешённых голосов пока нет.',
        'settings.mod_tts_provider_default': 'Без выбранного alias', 'settings.mod_tts_loaded': 'Настройки загружены.',
        'settings.mod_tts_invalid_input': 'Заполните alias и параметры голоса.', 'settings.mod_tts_invalid_user': 'Нужен числовой Twitch user ID.',
        'settings.mod_tts_save_error': 'Не удалось сохранить', 'settings.mod_tts_active': 'активен', 'settings.mod_tts_revoked': 'отозван',
        'settings.mod_tts_sessions': 'сессий', 'settings.mod_tts_invite': 'Создать вход', 'settings.mod_tts_no_grants': 'Доступов пока нет.',
        'settings.mod_tts_one_time_link': 'Одноразовая ссылка, действует 15 минут',
        'settings.mod_tts_source_bot_reply': 'Ответы бота', 'settings.mod_tts_source_voice_companion_reply': 'Ответы голосового собеседника',
        'settings.mod_tts_source_moderation_announcement': 'Объявления moderator-бота', 'settings.mod_tts_source_twitch_moderator_message': 'Twitch moderator TTS',
        'settings.mod_tts_source_ordinary_chat': 'Обычный чат', 'settings.mod_tts_source_channel_points_reward': 'Channel Points reward',
        'settings.tts_map_hint': 'Только чтение: итоговая policy и голос для каждой пары бот/канал.',
        'settings.tts_map_loading': 'Загрузка карты…', 'settings.tts_map_empty': 'Нет включённых пар бот/канал.',
        'settings.tts_map_error': 'Не удалось загрузить карту TTS.',
        'settings.tts_source_bot': 'Ответы бота', 'settings.tts_source_companion': 'Ответы голосового собеседника',
        'settings.tts_source_mod_announcement': 'Объявления moderator-бота',
        'settings.tts_source_twitch_mod': 'Сообщения Twitch-модераторов',
        'settings.tts_source_chat': 'Обычный чат', 'settings.tts_source_reward': 'Channel Points reward',
        'settings.tts_col_scope': 'Бот / канал', 'settings.tts_col_source': 'Источник',
        'settings.tts_col_policy': 'Policy', 'settings.tts_col_voice': 'Голос', 'settings.tts_col_output': 'OBS output',
        'settings.tts_policy_off': 'выключено', 'settings.tts_policy_on': 'включено',
        'settings.tts_policy_channel_muted': 'выключено в этом канале',
        'settings.tts_policy_not_spoken': 'автоматически не озвучивается',
        'settings.tts_policy_percent': 'включено · {percent}% ответов',
        'settings.tts_policy_rewards': 'включено · rewards: {rewards}',
        'settings.tts_policy_any_reward': 'включено · любой reward',
        'settings.tts_policy_legacy_account': 'legacy-настройка на весь аккаунт',
        'settings.tts_voice_unassigned': 'не назначен', 'settings.tts_voice_inherited': 'наследуется от бота/глобального',
        'settings.tts_voice_unknown': 'неизвестный voice ID', 'settings.tts_voice_browser': 'проверяется браузером OBS',
        'settings.tts_output_unverified': 'Не подтверждено: сервер не видит активные Browser Sources',
        'settings.widgets': '📺 OBS-виджеты', 'settings.security': '🔐 Безопасность',
        'settings.theme_background': '🎨 Фон темы', 'settings.backup': '💾 Резервная копия',
        'settings.faq': '❓ FAQ', 'label.provider': 'Провайдер', 'label.model': 'Модель',
        'settings.database': '🗄 База данных', 'btn.db_optimize': '🧹 Оптимизировать',
        'btn.db_cleanup': '🗑 Очистить старые логи', 'prompt.cleanup_logs_days': 'Удалить логи старше скольких дней? (по умолчанию 30):',
        'msg.logs_cleaned': 'Очищено {count} старых записей логов.', 'toast.invalid_days': 'Укажите положительное число дней.',
        'label.db_size': 'Размер:', 'label.db_records': 'Записей:', 'msg.db_optimized': 'БД оптимизирована',
        'label.api_key': 'API-ключ', 'label.voice': 'Голос', 'label.speed': 'Скорость',
        'label.volume': 'Громкость', 'label.client_id': 'Client ID', 'label.client_secret': 'Client Secret',
        'provider.inherit': 'Наследовать глобальный', 'provider.custom': 'Пользовательский API',
        'theme.default': 'Серый', 'theme.midnight': '🌙 Полночь', 'theme.ocean': '🌊 Океан',
        'theme.forest': '🌲 Лес', 'theme.sunset': '🌅 Закат', 'theme.neon': '⚡ Неон',
        'theme.purple': '💜 Фиолетовый', 'theme.minimal': '◼ Минимал',
    },
    en: {
        'nav.dashboard': 'Dashboard', 'nav.bots': 'Bots', 'nav.channels': 'Channels', 'nav.chat': 'Chat',
        'nav.analytics': 'Stats', 'nav.settings': 'Settings',
        'title.dashboard': 'Dashboard', 'title.bots': 'Bots', 'title.chat': 'Chat',
        'bots.filter.all_roles': 'All roles', 'bots.filter.all_channels': 'All channels', 'bot.memory.long_term': 'Long-term viewer memory', 'bot.memory.disabled_hint': 'Viewer memory is off for this bot — turn on the toggle above to let it remember facts.', 'panel.summary.title': '📊 Layout', 'panel.summary.online': 'Connected: {online} of {total}', 'panel.summary.channel': 'Channel', 'panel.summary.bots': 'Bots', 'panel.summary.connected': 'Live connections',
        'bots.change_channel': 'Change channel', 'bots.change_channel_new': '+ New channel',
        'bots.change_channel_hint': 'Bind the bot to a channel another bot already uses (moves it), to an existing one of its own, or create a new channel.',
        'bots.change_channel_none': 'No unused channels on other bots',
        'token.status.valid': 'Token is active', 'token.status.expiring': 'Token is expiring',
        'token.status.expired': 'Token has expired', 'token.status.not_refreshable': 'Not renewable',
        'token.status.unknown': 'Token status unknown', 'token.refresh': '🔄 Refresh token',
        'token.refresh_done': 'Token refreshed', 'token.refresh_failed': 'Could not refresh token',
        'token.manual_hint': 'This token will not be renewed automatically.',
        'token.auto_refresh': 'Renew tokens automatically',
        'token.auto_refresh_hint': 'Works for bots signed in through Twitch when Client ID and Client Secret are configured.',
        'token.warning_days': 'Show “expiring” this many days ahead',
        'token.warning_days_hint': 'Only changes when the yellow status appears on a bot card.',
        'token.save_settings': 'Save token renewal', 'token.settings_saved': 'Token renewal settings saved',
        'check.open': 'Check', 'check.title': 'Bot check',
        'check.hint': 'The test channel is used only for this check. Bots wait for a chat message and send one control message each.',
        'check.channel': 'Test channel', 'check.channel_hint': 'Choose a used channel or enter a Twitch login without #.',
        'check.message': 'Control message', 'check.message_hint': 'The [ник] marker is replaced with each bot name.',
        'check.default_message': '✅ проверка связи [ник]', 'check.send_enabled': 'Send the check message (off by default)', 'check.start': 'Start check',
        'check.cancel_running': 'Stop check', 'check.running': 'Check in progress: waiting for a message takes up to 45 seconds…',
        'check.completed': 'Check completed', 'check.cancelled': 'Check stopped', 'check.failed': 'Check failed',
        'check.invalid_input': 'Enter a channel and control message', 'check.download_csv': 'Download CSV', 'check.download_text': 'Download text',
        'check.col.bot': 'Bot', 'check.col.token': 'Token', 'check.col.join': 'IRC', 'check.col.read': 'Read',
        'check.col.send': 'Send', 'check.col.result': 'Result',
        'check.value.valid': 'active', 'check.value.expired': 'expired', 'check.value.unknown': 'unknown',
        'check.value.online': 'connected', 'check.value.error': 'error', 'check.value.confirmed': 'confirmed',
        'check.value.no_messages': 'no messages', 'check.value.sent': 'sent', 'check.value.not_run': 'not run',
        'check.value.success': 'success', 'check.value.not_confirmed': 'not confirmed',
        'check.reason.ok': 'bot read chat and sent a message', 'check.reason.no_messages': 'no messages arrived during the wait window',
        'check.reason.token_expired': 'token expired', 'check.reason.token_unknown': 'token could not be checked',
        'check.reason.join_timeout': 'connection timed out', 'check.reason.join_failed': 'connection failed',
        'check.reason.channel_not_connected': 'channel is not connected', 'check.reason.send_rejected': 'Twitch rejected the message',
        'check.reason.bot_not_found': 'bot not found', 'check.reason.not_run': 'not run', 'check.reason.check_failed': 'check error',
        'check.error.invalid_account_ids': 'Select between 1 and 100 bots', 'check.error.invalid_channel': 'Invalid Twitch channel login',
        'check.error.invalid_message': 'Invalid control message', 'check.error.check_failed': 'Could not start the check',
        'channels.title': 'Channels', 'channels.hint': 'Used Twitch channels, assigned bots, and their actual connection state.',
        'channels.load_failed': 'Could not load channels', 'channels.empty': 'No channels are used yet',
        'channels.connected_count': 'Connected: {connected} of {total}',
        'channels.settings_btn': '⚙️ Channel settings', 'channels.settings_tabs': 'Channel settings',
        'channels.clone_btn': '📋 Copy from channel...', 'channels.clone_title': '📋 Copy channel settings',
        'channels.clone_hint': 'Transfer moderation rules, banned and allowed topics to the current channel.',
        'channels.clone_from': 'Source channel', 'channels.clone_rules': '🛡 Base moderation rules',
        'channels.clone_bans': '🚫 Banned topics', 'channels.clone_allowed': '✅ Allowed topics',
        'channels.clone_submit': 'Copy', 'channels.clone_no_source': 'No other channels to copy from',
        'channels.clone_pick_at_least_one': 'Select at least one item to copy',
        'channels.clone_ok': 'Settings copied from #{from} to #{to}',
        'channels.bots_tab': '🤖 Channel bots',
        'channels.bots_tab_hint': 'Bots bound to this channel — connection status, per-bot channel rename, unbinding, adding new bots.',
        'channels.bots_tab_empty': 'No bot is bound to this channel yet.',
        'channels.base_rules': '🛡 Base rules',
        'channels.base_rules_hint': 'This channel’s own rules list. Only bots with the “moderator” role punish by it; a specific bot’s rule for the same word overrides the base.',
        'channels.base_rules_empty': 'Channel base is empty — start from the Twitch preset or add a rule.',
        'channels.base_rules_add': '+ Add to channel base',
        'channels.base_rules_seed': '🌱 Start from Twitch preset',
        'channels.base_rules_seed_ru': '🇷🇺 Russian preset',
        'channels.base_rules_seeded': 'Rules preset: added rules — {count}',
        'channels.mod_tab': '🧾 Moderation', 'channels.mod_bot': 'Bot',
        'channels.profile_tab': '👤 Channel profile', 'channels.profile_bot': 'Bot (for lore and summaries)',
        'channels.profile_hint': 'This channel’s streamer info: profile and photo are stored per-channel. The bot below is used for this channel’s lore and live summaries.',
        'channels.bans_title': '🚫 Banned topics for this channel', 'channels.bans_inherited': 'inherits the Twitch preset',
        'channels.runs_title': '📝 Summaries: runs',
        'channels.bans_hint': 'What bots must not bring up in this channel’s chat. One rule per line, # lines are comments. Until the channel has its own list, it inherits the base Twitch preset.',
        'channels.bans_placeholder': 'No politics talk\nNo series spoilers',
        'channels.bans_seed': '🌱 Take the Twitch preset',
        'channels.bans_preset_title': 'Base Twitch preset (inherited by channels without their own list)',
        'channels.allowed_title': '✅ What bots are allowed to do (permitted topics)', 'channels.allowed_inherited': 'inherits the Twitch preset',
        'channels.allowed_hint': 'What bots are permitted and encouraged to do in this channel’s chat. One directive per line, # lines are comments. Until the channel has its own list, it inherits the base Twitch preset.',
        'channels.allowed_placeholder': 'Discuss the ongoing game\nCheer for the streamer',
        'channels.allowed_seed': '🌱 Take the Twitch preset',
        'channels.allowed_preset_title': 'Base preset of permitted topics (inherited by channels without their own list)',
        'channels.profile_lore_hint': 'Streamer facts for the selected bot on this channel: added manually or suggested by summaries/chat. Entries appear in the list only after approval ✓.',
        'channels.profile_summary_hint': 'Live “how the stream went” summaries for the selected bot on this channel: on/off and language override the bot’s settings without touching other channels. Manual period runs stay in the Brain.',
        'channels.mod_queue': '⏳ Confirmation queue',
        'channels.mod_queue_hint': 'A permanent ban of a protected viewer is not applied and awaits your decision: until then the message is not deleted and no timeout is given.',
        'channels.mod_queue_empty': 'Queue is empty — no deferred cases.',
        'channels.mod_queue_ban': 'Ban', 'channels.mod_queue_pardon': 'Do not punish',
        'channels.mod_resolved_yes': 'Punishment applied.', 'channels.mod_resolved_no': 'Case closed without punishment.',
        'channels.mod_journal': '📜 Punishment journal',
        'channels.mod_journal_empty': 'No punishments yet.',
        'channels.mod_status_applied': 'applied', 'channels.mod_status_pending': 'awaiting approval',
        'channels.mod_status_cancelled': 'cancelled by owner', 'channels.mod_status_expired': 'closed by timeout',
        'channels.mod_protected': '🛡 Protected from permanent ban',
        'channels.mod_protected_hint': 'Moderators, editors and the streamer are protected automatically — no need to list them. Timeouts still apply to protected viewers as configured: protection covers permanent bans only.',
        'channels.mod_protected_empty': 'Manual list is empty.', 'channels.mod_protected_user': 'Viewer nickname',
        'channels.mod_protected_note': 'Note', 'channels.mod_protected_add': '+ Protect',
        'channels.mod_protected_remove': 'Remove from protected',
        'channels.mod_unban': '🔓 Unban', 'channels.mod_unban_btn': 'Unban',
        'channels.mod_unban_ok': 'Viewer unbanned.', 'channels.mod_unban_already': 'Viewer is not banned.',
        'channels.mod_no_bot': 'No bot is connected to this channel.', 'channels.mod_action_ban': 'permanent ban',
        'channels.mod_action_timeout': 'timeout',
        'channels.mod_manual_punish': '⚡ Quick Punishment', 'channels.mod_duration': 'Duration',
        'channels.mod_reason': 'Reason', 'channels.mod_apply_punish': 'Apply',
        'channels.mod_quick_reasons': 'Quick templates:', 'channels.mod_quick_notes': 'Quick notes:',
        'channels.mod_punish_fill_fields': 'Specify viewer username and select a bot.', 'channels.mod_punish_ok': 'Punishment applied.',
        'channels.add': '+ Add channel', 'channels.add_hint': 'The channel is bound to the selected bot; the same channel can be added to several bots.',
        'channels.add_bot': 'Bot', 'channels.add_no_bots': 'Add a bot first', 'channels.add_invalid': 'Provide a channel and a bot',
        'channels.rename': 'Rename channel', 'channels.rename_prompt': 'New channel name (without #)',
        'channels.rename_conflict': 'The name is taken in: {tables}. Replace that data?',
        'channels.delete': 'Delete channel', 'channels.delete_hint': 'Related channel data will be deleted along with the binding.',
        'channels.delete_no_data': 'No related data — the channel is safe to delete.',
        'channels.delete_confirm_data': 'Warning: records to delete — {total}.',
        'channels.deps_failed': 'Could not read channel dependencies', 'channels.binding_actions': 'Actions for this bot',
        'toast.channel_renamed': 'Channel renamed to #{detail}', 'toast.channel_rename_failed': 'Could not rename the channel',
        'toast.channel_add_failed': 'Could not add the channel', 'toast.channel_delete_failed': 'Could not delete the channel',
        'bulk.title': 'Add and check', 'bulk.hint': 'Every new or existing bot×channel pair will be checked immediately.',
        'bulk.bots': 'Bots', 'bulk.bots_hint': 'Select bots to add to this channel.',
        'bulk.channels': 'Channels', 'bulk.channels_hint': 'One Twitch login per line or comma-separated, without #.',
        'bulk.start': 'Add and check', 'bulk.add_bots': 'Add bots and check', 'bulk.cancel': 'Stop operation', 'bulk.select_all': 'Select all', 'bulk.deselect_all': 'Deselect all',
        'bulk.invalid_input': 'Select bots and channels and enter a message', 'bulk.running': 'Adding and checking…',
        'bulk.completed': 'Operation completed', 'bulk.cancelled': 'Operation stopped', 'bulk.failed': 'Operation failed',
        'bulk.col.channel': 'Channel', 'bulk.col.add': 'Add', 'bulk.col.check': 'Check',
        'bulk.value.added': 'success', 'bulk.value.skipped': 'skipped', 'bulk.value.error': 'error',
        'bulk.reason.added': 'pair added', 'bulk.reason.already_exists': 'already exists',
        'bulk.reason.bot_not_found': 'bot not found', 'bulk.reason.add_failed': 'could not add', 'bulk.value.changed': 'changed', 'bulk.reason.ok': 'bindings updated', 'bulk.reason.binding_disabled': 'binding disabled', 'bulk.reason.change_failed': 'could not change channel', 'bulk.change_channel': 'Change channel', 'bulk.change_apply': 'Apply to selected', 'bulk.change_new': 'New channel (if not in the list)', 'bulk.change_need_channel': 'Pick a channel from the list or type one', 'bulk.change_replace': 'Detach previous channels from the selected bots', 'bulk.change_hint': 'Pick the channel from the list or type its name; detached bindings do not delete the channels themselves — bots are just unbound.', 'bulk.change_done': 'Done: {changed} changed, {added} added, {skipped} skipped, {errors} errors.',
        'bulk.error.invalid_direction': 'Invalid operation direction', 'bulk.error.invalid_account_ids': 'Select between 1 and 100 bots',
        'bulk.error.invalid_channels': 'Check the Twitch channel logins', 'bulk.error.too_many_pairs': 'Up to 500 pairs can be processed at once',
        'bulk.error.invalid_message': 'Invalid control message', 'bulk.error.bulk_failed': 'Could not start the operation',
        'title.analytics': 'Stats', 'title.settings': 'Settings',
        'btn.start': '▶ Start', 'btn.stop': '⏹ Stop', 'btn.save': '💾 Save',
        'btn.delete': '🗑 Delete', 'btn.add': '+ Add', 'btn.cancel': 'Cancel',
        'btn.connect': '🟢 Connect', 'btn.disconnect': '🔴 Disconnect',
        'label.online': '🟢 Online', 'label.offline': '🔴 Offline', 'label.enabled': '🟡 Enabled',
        'label.connected': '🟢 Connected', 'label.disconnected': '🔴 Disconnected',
        'label.no_channels': 'no channels', 'label.search': 'Search...',
        'msg.saved': 'Saved', 'msg.deleted': 'Deleted', 'msg.error': 'Error',
        'msg.started': 'Bot started', 'msg.stopped': 'Bot stopped',
        'msg.connected': 'Connected', 'msg.disconnected': 'Disconnected',
        'app.title': 'Twitch AI Bot Panel', 'nav.collapse': 'Collapse', 'nav.menu': 'Menu', 'nav.theme': 'Theme',
        'search.placeholder': 'Search... (Ctrl+K)', 'btn.refresh': '🔄 Refresh', 'btn.back': '← Back',
        'btn.add_bot': '+ Add bot', 'btn.send': 'Send', 'btn.history': '📜 History', 'btn.clear': 'Clear',
        'dm.title': '💬 Conversation in Twitch chat', 'dm.public_hint': 'Your message and the bot reply are public to all viewers in the selected channel.', 'dm.channel': 'Twitch channel', 'dm.channel_required': 'Select a connected channel', 'dm.twitch_error': 'Could not send to Twitch: {detail}', 'dm.open_btn': '💬 Talk',
        'dm.voice': '🎤 Voice', 'dm.photo': '🖼 Photo', 'dm.text_input': '⌨️ Text', 'dm.speak_reply': '🔊 Speak replies',
        'dm.attach_photo': 'Attach photo', 'dm.record': 'Record', 'dm.stop': 'Stop', 'dm.placeholder': 'Write to Twitch chat…',
        'dm.you': 'You', 'dm.you_bot': 'Bot', 'dm.photo_ready': 'Photo attached', 'dm.transcribing': 'Transcribing…',
        'dm.voice_sent': 'voice message', 'dm.photo_sent': 'photo', 'dm.mic_error': 'Microphone unavailable', 'dm.empty': 'Nothing to send', 'dm.reset': '🗑 Clear conversation',
        'btn.generate': 'Generate', 'btn.test': '🔌 Test connection', 'label.bots_online': 'Bots connected',
        'label.bots_enabled': 'Enabled', 'label.messages_read': 'Messages read', 'label.bot_replies': 'Bot replies',
        'label.live_events': 'Live events', 'label.live_chat': 'Live chat', 'label.loading': 'Loading...',
        'health.title': '🩺 Stream health', 'health.silent': 'silent', 'health.responds': 'responds',
        'health.last_activity': 'last activity', 'health.empty': 'No channels are bound yet.',
        'label.waiting_events': 'Waiting for events...', 'label.no_data': 'No data', 'label.no_bots': 'No bots',
        'label.all_channels': 'All channels', 'label.all_bots': 'All bots', 'label.all_levels': 'All levels',
        'label.message_from_bot': 'Message as bot...', 'label.no_messages': 'No messages yet',
        'label.activity': 'Activity by bot (messages sent)', 'label.bot_logs': '📋 Bot logs',
        'settings.group_ai': 'AI and providers', 'settings.group_diagnostics': 'Logs and diagnostics', 'settings.group_twitch': 'Twitch connection', 'settings.group_security': 'Security and interface', 'settings.group_maintenance': 'Data and maintenance', 'settings.group_modsite': 'Moderator-site: administration',
        'settings.diagnostics': '🛠 Logs and diagnostics', 'settings.bot_logs_hint': 'Bot logs are in Analytics: filter by bot, level, and period, then export CSV.', 'btn.open_bot_logs': 'Open bot logs',
        'settings.ai_global': '🧠 AI (global)', 'placeholder.eleven_key_set':'key set (enter new to replace)',
        'settings.tts_map_title': '🗺 Who voices what',
        'settings.mod_tts_title': '🎙 Moderator TTS console', 'settings.mod_tts_hint': 'Voices, rules and Twitch user access for one exact bot/channel pair.',
        'settings.mod_media_title': 'Moderator GIF / media', 'settings.mod_media_hint': 'Owner-approved library and a separate token-limited OBS Browser Source for the selected scope.', 'settings.mod_media_upload': 'Upload and approve', 'settings.mod_media_obs': 'New OBS URL', 'settings.mod_media_stop': 'Stop', 'settings.mod_media_clear': 'Clear queue', 'settings.mod_media_kill': 'Kill switch', 'settings.mod_media_empty': 'No media yet.',
        'settings.mod_media_obs_url': 'OBS Browser Source URL', 'settings.mod_media_reveal': 'Reveal for 30 seconds', 'settings.mod_media_preview': 'Safe moderator media preview', 'settings.mod_media_rotate_hint': 'Rotation immediately revokes the old OBS URL.', 'settings.mod_media_rotate_confirm': 'Create a new URL? The old OBS URL will stop working immediately.', 'settings.mod_media_revealed': 'URL revealed for 30 seconds.', 'settings.mod_media_hidden': 'OBS URL is configured and hidden.', 'settings.mod_media_rotation_required': 'The old URL still works, but cannot be revealed. Rotate it to continue.', 'settings.mod_media_obs_missing': 'Create a separate limited URL for OBS.', 'settings.mod_media_reveal_error': 'Could not reveal the URL. Access is limited to the local owner.', 'settings.mod_media_copied': 'OBS URL copied.', 'settings.mod_media_copy_error': 'Could not copy the OBS URL.',
        'settings.mod_sound_title': 'Moderator sounds', 'settings.mod_sound_hint': 'Approved tracks play through the existing Soundboard; add the exact-scoped URL below to OBS.', 'settings.mod_sound_empty': 'No tracks yet.', 'settings.mod_sound_obs': 'New OBS URL', 'settings.mod_sound_obs_configured': 'OBS token is configured. A new URL immediately revokes the previous one.', 'settings.mod_sound_obs_missing': 'Create a separate limited URL for OBS.',
        'settings.tts_output_title': 'Single TTS audio output', 'settings.tts_output_hint': 'Choose one exact-scoped Browser Source. Old URLs remain legacy and have no active-source telemetry.', 'settings.tts_output_test': 'Test output', 'settings.tts_output_test_text': 'Selected TTS output test',
        'settings.mod_tts_scope': 'Bot / channel', 'settings.mod_tts_source': 'TTS source', 'settings.mod_tts_voices': 'Approved voices',
        'settings.mod_tts_alias_ph': 'Short alias', 'settings.mod_tts_provider_ph': 'Provider', 'settings.mod_tts_voice_id_ph': 'Registered voice ID',
        'settings.mod_tts_add_voice': 'Add voice', 'settings.mod_tts_policy': 'Source policy', 'settings.mod_tts_enabled': 'Enabled',
        'settings.mod_tts_voice_choice': 'Allow voice choice', 'settings.mod_tts_cooldown': 'Cooldown, sec', 'settings.mod_tts_rate': 'Maximum per minute',
        'settings.mod_tts_length': 'Maximum length', 'settings.mod_tts_blacklist': 'Blacklist, comma-separated', 'settings.mod_tts_save_policy': 'Save policy',
        'settings.mod_tts_access': 'Twitch access', 'settings.mod_tts_user_id': 'Stable Twitch user ID', 'settings.mod_tts_login': 'Twitch login (label)',
        'settings.mod_tts_save_grant': 'Save access', 'settings.mod_tts_revoke': 'Revoke', 'settings.mod_tts_chat_enabled': 'Twitch chat command',
        'settings.mod_tts_save_chat': 'Save command', 'settings.mod_tts_load_error': 'Could not load Moderator TTS settings.',
        'settings.mod_tts_no_scope': 'No enabled bot/channel pairs.', 'settings.mod_tts_no_voices': 'No approved voices yet.',
        'settings.mod_tts_provider_default': 'No selected alias', 'settings.mod_tts_loaded': 'Settings loaded.',
        'settings.mod_tts_invalid_input': 'Enter an alias and voice parameters.', 'settings.mod_tts_invalid_user': 'A numeric Twitch user ID is required.',
        'settings.mod_tts_save_error': 'Could not save', 'settings.mod_tts_active': 'active', 'settings.mod_tts_revoked': 'revoked',
        'settings.mod_tts_sessions': 'sessions', 'settings.mod_tts_invite': 'Create login', 'settings.mod_tts_no_grants': 'No access grants yet.',
        'settings.mod_tts_one_time_link': 'One-time link, valid for 15 minutes',
        'settings.mod_tts_source_bot_reply': 'Bot replies', 'settings.mod_tts_source_voice_companion_reply': 'Voice companion replies',
        'settings.mod_tts_source_moderation_announcement': 'Moderator-bot announcements', 'settings.mod_tts_source_twitch_moderator_message': 'Twitch moderator TTS',
        'settings.mod_tts_source_ordinary_chat': 'Ordinary chat', 'settings.mod_tts_source_channel_points_reward': 'Channel Points reward',
        'settings.tts_map_hint': 'Read-only: resolved policy and voice for every bot/channel pair.',
        'settings.tts_map_loading': 'Loading routing map…', 'settings.tts_map_empty': 'No enabled bot/channel pairs.',
        'settings.tts_map_error': 'Could not load the TTS map.',
        'settings.tts_source_bot': 'Bot replies', 'settings.tts_source_companion': 'Voice companion replies',
        'settings.tts_source_mod_announcement': 'Moderator-bot announcements',
        'settings.tts_source_twitch_mod': 'Twitch moderator messages',
        'settings.tts_source_chat': 'Ordinary chat', 'settings.tts_source_reward': 'Channel Points reward',
        'settings.tts_col_scope': 'Bot / channel', 'settings.tts_col_source': 'Source',
        'settings.tts_col_policy': 'Policy', 'settings.tts_col_voice': 'Voice', 'settings.tts_col_output': 'OBS output',
        'settings.tts_policy_off': 'off', 'settings.tts_policy_on': 'on',
        'settings.tts_policy_channel_muted': 'muted in this channel',
        'settings.tts_policy_not_spoken': 'not spoken automatically',
        'settings.tts_policy_percent': 'on · {percent}% of replies',
        'settings.tts_policy_rewards': 'on · rewards: {rewards}',
        'settings.tts_policy_any_reward': 'on · any reward',
        'settings.tts_policy_legacy_account': 'legacy account-wide setting',
        'settings.tts_voice_unassigned': 'not assigned', 'settings.tts_voice_inherited': 'inherited from bot/global',
        'settings.tts_voice_unknown': 'unknown voice ID', 'settings.tts_voice_browser': 'verified by the OBS browser',
        'settings.tts_output_unverified': 'Unverified: server cannot see active Browser Sources',
        'settings.widgets': '📺 OBS widgets', 'settings.security': '🔐 Security',
        'settings.theme_background': '🎨 Theme background', 'settings.backup': '💾 Backup',
        'settings.faq': '❓ FAQ', 'label.provider': 'Provider', 'label.model': 'Model',
        'settings.database': '🗄 Database', 'btn.db_optimize': '🧹 Optimize',
        'btn.db_cleanup': '🗑 Clean old logs', 'prompt.cleanup_logs_days': 'Delete logs older than how many days? (default 30):',
        'msg.logs_cleaned': 'Cleaned up {count} old log records.', 'toast.invalid_days': 'Specify a positive number of days.',
        'label.db_size': 'Size:', 'label.db_records': 'Records:', 'msg.db_optimized': 'Database optimized',
        'label.api_key': 'API key', 'label.voice': 'Voice', 'label.speed': 'Speed', 'label.volume': 'Volume',
        'label.client_id': 'Client ID', 'label.client_secret': 'Client Secret',
        'provider.inherit': 'Inherit global', 'provider.custom': 'Custom API', 'theme.default': 'Gray',
        'theme.midnight': '🌙 Midnight', 'theme.ocean': '🌊 Ocean', 'theme.forest': '🌲 Forest',
        'theme.sunset': '🌅 Sunset', 'theme.neon': '⚡ Neon', 'theme.purple': '💜 Purple', 'theme.minimal': '◼ Minimal',
    },
    ua: {
        'nav.dashboard': 'Головна', 'nav.bots': 'Боти', 'nav.channels': 'Канали', 'nav.chat': 'Чат',
        'nav.analytics': 'Статистика', 'nav.settings': 'Налаштування',
        'title.dashboard': 'Головна', 'title.bots': 'Боти', 'title.chat': 'Чат',
        'bots.filter.all_roles': 'Усі ролі', 'bots.filter.all_channels': 'Усі канали', 'bot.memory.long_term': 'Довгострокова пам’ять про глядачів', 'bot.memory.disabled_hint': 'Пам’ять про глядачів вимкнена в цього бота — увімкніть перемикач вище, щоб бот запам’ятовував факти.', 'panel.summary.title': '📊 Розклад', 'panel.summary.online': 'Підключено: {online} з {total}', 'panel.summary.channel': 'Канал', 'panel.summary.bots': 'Боти', 'panel.summary.connected': 'Живі підключення',
        'bots.change_channel': 'Змінити канал', 'bots.change_channel_new': '+ Новий канал',
        'bots.change_channel_hint': 'Прив’яжіть бота до наявного каналу іншого бота (перенесення), до свого наявного або створіть новий канал.',
        'bots.change_channel_none': 'Немає вільних каналів у інших ботів',
        'token.status.valid': 'Токен активний', 'token.status.expiring': 'Термін токена спливає',
        'token.status.expired': 'Термін токена сплив', 'token.status.not_refreshable': 'Не подовжується',
        'token.status.unknown': 'Статус токена невідомий', 'token.refresh': '🔄 Оновити токен',
        'token.refresh_done': 'Токен оновлено', 'token.refresh_failed': 'Не вдалося оновити токен',
        'token.manual_hint': 'Цей токен не буде подовжуватися автоматично.',
        'token.auto_refresh': 'Автоматично подовжувати токени',
        'token.auto_refresh_hint': 'Працює для ботів, які увійшли через Twitch, коли Client ID і Client Secret налаштовані.',
        'token.warning_days': 'Показувати «термін спливає» заздалегідь, днів',
        'token.warning_days_hint': 'Змінює лише момент появи жовтого статусу на картці бота.',
        'token.save_settings': 'Зберегти подовження токенів', 'token.settings_saved': 'Налаштування подовження збережено',
        'check.open': 'Перевірити', 'check.title': 'Перевірка ботів',
        'check.hint': 'Тестовий канал використовується лише для цієї перевірки. Боти чекають повідомлення з чату й надсилають по одному контрольному повідомленню.',
        'check.channel': 'Тестовий канал', 'check.channel_hint': 'Виберіть використаний канал або введіть Twitch login без #.',
        'check.message': 'Контрольне повідомлення', 'check.message_hint': 'Маркер [ник] замінюється на ім’я кожного бота.',
        'check.default_message': '✅ проверка связи [ник]', 'check.send_enabled': 'Надсилати контрольне повідомлення (вимк. за замовчуванням)', 'check.start': 'Запустити перевірку',
        'check.cancel_running': 'Зупинити перевірку', 'check.running': 'Перевірка триває: очікування повідомлення займає до 45 секунд…',
        'check.completed': 'Перевірку завершено', 'check.cancelled': 'Перевірку зупинено', 'check.failed': 'Не вдалося виконати перевірку',
        'check.invalid_input': 'Вкажіть канал і контрольне повідомлення', 'check.download_csv': 'Завантажити CSV', 'check.download_text': 'Завантажити текст',
        'check.col.bot': 'Бот', 'check.col.token': 'Токен', 'check.col.join': 'IRC', 'check.col.read': 'Читання',
        'check.col.send': 'Надсилання', 'check.col.result': 'Результат',
        'check.value.valid': 'активний', 'check.value.expired': 'прострочений', 'check.value.unknown': 'невідомо',
        'check.value.online': 'підключений', 'check.value.error': 'помилка', 'check.value.confirmed': 'підтверджено',
        'check.value.no_messages': 'повідомлень не було', 'check.value.sent': 'надіслано', 'check.value.not_run': 'не виконувалось',
        'check.value.success': 'успішно', 'check.value.not_confirmed': 'не підтверджено',
        'check.reason.ok': 'бот читає чат і надіслав повідомлення', 'check.reason.no_messages': 'повідомлень у вікні очікування не було',
        'check.reason.token_expired': 'термін токена сплив', 'check.reason.token_unknown': 'не вдалося перевірити токен',
        'check.reason.join_timeout': 'час підключення вичерпано', 'check.reason.join_failed': 'не вдалося підключитися',
        'check.reason.channel_not_connected': 'канал не підключений', 'check.reason.send_rejected': 'Twitch відхилив повідомлення',
        'check.reason.bot_not_found': 'бота не знайдено', 'check.reason.not_run': 'не виконувалось', 'check.reason.check_failed': 'помилка перевірки',
        'check.error.invalid_account_ids': 'Виберіть від 1 до 100 ботів', 'check.error.invalid_channel': 'Некоректний Twitch login каналу',
        'check.error.invalid_message': 'Некоректне контрольне повідомлення', 'check.error.check_failed': 'Не вдалося запустити перевірку',
        'channels.title': 'Канали', 'channels.hint': 'Використані Twitch-канали, додані боти та їхній фактичний стан підключення.',
        'channels.load_failed': 'Не вдалося завантажити канали', 'channels.empty': 'Використаних каналів ще немає',
        'channels.connected_count': 'Підключено: {connected} з {total}',
        'channels.settings_btn': '⚙️ Налаштування каналу', 'channels.settings_tabs': 'Налаштування каналу',
        'channels.clone_btn': '📋 Скопіювати з каналу...', 'channels.clone_title': '📋 Скопіювати налаштування каналу',
        'channels.clone_hint': 'Перенести правила модерації, заборонені та дозволені теми в поточний канал.',
        'channels.clone_from': 'Звідки скопіювати', 'channels.clone_rules': '🛡 База правил модерації',
        'channels.clone_bans': '🚫 Заборонені теми каналу', 'channels.clone_allowed': '✅ Дозволені теми каналу',
        'channels.clone_submit': 'Скопіювати', 'channels.clone_no_source': 'Немає інших каналів для копіювання',
        'channels.clone_pick_at_least_one': 'Виберіть хоча б один пункт для копіювання',
        'channels.clone_ok': 'Налаштування успішно скопійовано з #{from} до #{to}',
        'channels.bots_tab': '🤖 Боти каналу',
        'channels.bots_tab_hint': 'Боти, прив’язані до цього каналу — статус підключення, перейменування каналу для конкретного бота, відв’язка, додавання нових ботів.',
        'channels.bots_tab_empty': 'До цього каналу поки не прив’язано жодного бота.',
        'channels.base_rules': '🛡 База правил',
        'channels.base_rules_hint': 'Власний список правил цього каналу. Карають за ним лише боти з роллю «модератор»; правило конкретного бота з тим самим словом перевизначає базу.',
        'channels.base_rules_empty': 'База каналу порожня — стартуйте з пресету Twitch або додайте правило.',
        'channels.base_rules_add': '+ Додати в базу каналу',
        'channels.base_rules_seed': '🌱 Стартувати з пресету Twitch',
        'channels.base_rules_seed_ru': '🇷🇺 Пресет РФ/СНД',
        'channels.base_rules_seeded': 'Пресет правил: додано правил — {count}',
        'channels.mod_tab': '🧾 Модерація', 'channels.mod_bot': 'Бот',
        'channels.profile_tab': '👤 Профіль каналу', 'channels.profile_bot': 'Бот (для lore й зведень)',
        'channels.profile_hint': 'Інфо про стрімера цього каналу: профіль і фото зберігаються per-channel. Бот нижче знадобиться для lore й live-зведень цього каналу.',
        'channels.bans_title': '🚫 Заборонені теми каналу', 'channels.bans_inherited': 'успадковує пресет Twitch',
        'channels.runs_title': '📝 Зведення: прогони',
        'channels.bans_hint': 'Чого ботам не можна піднімати в чаті цього каналу. Одна заборона на рядок, рядки з # — коментарі. Поки власного списку немає, канал успадковує базовий пресет Twitch.',
        'channels.bans_placeholder': 'Не обговорювати політику\nБез спойлерів до серіалів',
        'channels.bans_seed': '🌱 Взяти пресет Twitch',
        'channels.bans_preset_title': 'Базовий пресет Twitch (успадковується каналами без власного списку)',
        'channels.allowed_title': '✅ Що ботам можна робити (дозволені теми)', 'channels.allowed_inherited': 'успадковує пресет Twitch',
        'channels.allowed_hint': 'Що ботам дозволено та заохочується робити в чаті цього каналу. Одна настанова на рядок, рядки з # — коментарі. Поки власного списку немає, канал успадковує базовий пресет Twitch.',
        'channels.allowed_placeholder': 'Обговорювати поточну гру\nПідтримувати стрімера',
        'channels.allowed_seed': '🌱 Взяти пресет Twitch',
        'channels.allowed_preset_title': 'Базовий пресет дозволених тем (успадковується каналами без власного списку)',
        'channels.profile_lore_hint': 'Факти про стрімера в обраного бота на цьому каналі: додані вручну або запропоновані зведеннями/чатом. У список потрапляють лише після підтвердження ✓.',
        'channels.profile_summary_hint': 'Live-зведення «як минув стрім» в обраного бота на цьому каналі: увімк/вимк і мова перевизначають налаштування бота, інші канали не чіпають. Ручний прогін за період — у «Мозку».',
        'channels.mod_queue': '⏳ Черга підтвердження',
        'channels.mod_queue_hint': '«Бан назавжди» захищеного глядача не застосовано й чекає вашого рішення: до того повідомлення не видаляється, не маскується і таймаут не дається.',
        'channels.mod_queue_empty': 'Черга порожня — відкладених випадків немає.',
        'channels.mod_queue_ban': 'Забанити', 'channels.mod_queue_pardon': 'Не карати',
        'channels.mod_resolved_yes': 'Покарання застосовано.', 'channels.mod_resolved_no': 'Випадок закрито без покарання.',
        'channels.mod_journal': '📜 Журнал покарань',
        'channels.mod_journal_empty': 'Покарань ще не було.',
        'channels.mod_status_applied': 'застосовано', 'channels.mod_status_pending': 'чекає підтвердження',
        'channels.mod_status_cancelled': 'скасовано власником', 'channels.mod_status_expired': 'закрито за строком',
        'channels.mod_protected': '🛡 Захищені від «бану назавжди»',
        'channels.mod_protected_hint': 'Модератори, редактори та стрімер захищені автоматично — вписувати їх не треба. Таймаути застосовуються до захищених як налаштовано: захист лише від вічного бану.',
        'channels.mod_protected_empty': 'Ручний список порожній.', 'channels.mod_protected_user': 'Нік глядача',
        'channels.mod_protected_note': 'Нотатка', 'channels.mod_protected_add': '+ Захистити',
        'channels.mod_protected_remove': 'Прибрати із захищених',
        'channels.mod_unban': '🔓 Розбанити', 'channels.mod_unban_btn': 'Розбанити',
        'channels.mod_unban_ok': 'Глядача розбанено.', 'channels.mod_unban_already': 'Глядач уже не забанений.',
        'channels.mod_no_bot': 'До каналу не підключено бота.', 'channels.mod_action_ban': 'бан назавжди',
        'channels.mod_action_timeout': 'таймаут',
        'channels.mod_manual_punish': '⚡ Швидке покарання', 'channels.mod_duration': 'Тривалість',
        'channels.mod_reason': 'Причина', 'channels.mod_apply_punish': 'Застосувати',
        'channels.mod_quick_reasons': 'Швидкі шаблони:', 'channels.mod_quick_notes': 'Швидкі нотатки:',
        'channels.mod_punish_fill_fields': 'Вкажіть нік глядача та оберіть бота.', 'channels.mod_punish_ok': 'Покарання застосовано.',
        'channels.add': '+ Додати канал', 'channels.add_hint': 'Канал прив’яжеться до обраного бота; той самий канал можна додати кільком ботам.',
        'channels.add_bot': 'Бот', 'channels.add_no_bots': 'Спочатку додайте бота', 'channels.add_invalid': 'Вкажіть канал і бота',
        'channels.rename': 'Перейменувати канал', 'channels.rename_prompt': 'Нова назва каналу (без #)',
        'channels.rename_conflict': 'Назва зайнята в таблицях: {tables}. Замінити їхні дані?',
        'channels.delete': 'Видалити канал', 'channels.delete_hint': 'Разом із прив’язкою видаляться пов’язані дані каналу.',
        'channels.delete_no_data': 'Пов’язаних даних немає — канал видалиться безпечно.',
        'channels.delete_confirm_data': 'Увага: буде видалено записів — {total}.',
        'channels.deps_failed': 'Не вдалося отримати залежності каналу', 'channels.binding_actions': 'Дії для цього бота',
        'toast.channel_renamed': 'Канал перейменовано на #{detail}', 'toast.channel_rename_failed': 'Не вдалося перейменувати канал',
        'toast.channel_add_failed': 'Не вдалося додати канал', 'toast.channel_delete_failed': 'Не вдалося видалити канал',
        'bulk.title': 'Додати й перевірити', 'bulk.hint': 'Кожну нову або наявну пару бот×канал буде одразу перевірено.',
        'bulk.bots': 'Боти', 'bulk.bots_hint': 'Виберіть ботів, яких потрібно додати до каналу.',
        'bulk.channels': 'Канали', 'bulk.channels_hint': 'Один Twitch login на рядок або через кому, без #.',
        'bulk.start': 'Додати й перевірити', 'bulk.add_bots': 'Додати ботів і перевірити', 'bulk.cancel': 'Зупинити операцію', 'bulk.select_all': 'Вибрати всіх', 'bulk.deselect_all': 'Зняти вибір',
        'bulk.invalid_input': 'Виберіть ботів, канали та вкажіть повідомлення', 'bulk.running': 'Додавання й перевірка виконуються…',
        'bulk.completed': 'Операцію завершено', 'bulk.cancelled': 'Операцію зупинено', 'bulk.failed': 'Операція завершилася з помилкою',
        'bulk.col.channel': 'Канал', 'bulk.col.add': 'Додавання', 'bulk.col.check': 'Перевірка',
        'bulk.value.added': 'успішно', 'bulk.value.skipped': 'пропущено', 'bulk.value.error': 'помилка',
        'bulk.reason.added': 'пару додано', 'bulk.reason.already_exists': 'вже існує',
        'bulk.reason.bot_not_found': 'бота не знайдено', 'bulk.reason.add_failed': 'не вдалося додати', 'bulk.value.changed': 'змінено', 'bulk.reason.ok': 'зв’язки оновлено', 'bulk.reason.binding_disabled': 'зв’язку вимкнено', 'bulk.reason.change_failed': 'не вдалося змінити канал', 'bulk.change_channel': 'Змінити канал', 'bulk.change_apply': 'Застосувати до вибраних', 'bulk.change_new': 'Новий канал (якщо немає в списку)', 'bulk.change_need_channel': 'Вкажіть канал: виберіть зі списку або впишіть', 'bulk.change_replace': 'Зняти попередні канали в вибраних ботів', 'bulk.change_hint': 'Канал вибирається зі списку або вводиться іменем; зняті прив’язки не видаляють самі канали — лише відв’язують ботів.', 'bulk.change_done': 'Готово: змінено {changed}, додано {added}, пропущено {skipped}, помилок {errors}.',
        'bulk.error.invalid_direction': 'Некоректний напрямок операції', 'bulk.error.invalid_account_ids': 'Виберіть від 1 до 100 ботів',
        'bulk.error.invalid_channels': 'Перевірте Twitch login каналів', 'bulk.error.too_many_pairs': 'За один раз можна обробити до 500 пар',
        'bulk.error.invalid_message': 'Некоректне контрольне повідомлення', 'bulk.error.bulk_failed': 'Не вдалося запустити операцію',
        'title.analytics': 'Статистика', 'title.settings': 'Налаштування',
        'btn.start': '▶ Старт', 'btn.stop': '⏹ Стоп', 'btn.save': '💾 Зберегти',
        'btn.delete': '🗑 Видалити', 'btn.add': '+ Додати', 'btn.cancel': 'Скасувати',
        'btn.connect': '🟢 Підключити', 'btn.disconnect': '🔴 Відключити',
        'label.online': '🟢 Online', 'label.offline': '🔴 Offline', 'label.enabled': '🟡 Увімкнено',
        'label.connected': '🟢 Підключено', 'label.disconnected': '🔴 Відключено',
        'label.no_channels': 'без каналів', 'label.search': 'Пошук...',
        'msg.saved': 'Збережено', 'msg.deleted': 'Видалено', 'msg.error': 'Помилка',
        'msg.started': 'Бота запущено', 'msg.stopped': 'Бота зупинено',
        'msg.connected': 'Підключено', 'msg.disconnected': 'Відключено',
        'app.title': 'Панель Twitch AI Bot', 'nav.collapse': 'Згорнути', 'nav.menu': 'Меню', 'nav.theme': 'Тема',
        'search.placeholder': 'Пошук... (Ctrl+K)', 'btn.refresh': '🔄 Оновити', 'btn.back': '← Назад',
        'btn.add_bot': '+ Додати бота', 'btn.send': 'Відправити', 'btn.history': '📜 Історія',
        'dm.title': '💬 Розмова у Twitch-чаті', 'dm.public_hint': 'Повідомлення й відповідь бота побачать усі глядачі вибраного каналу.', 'dm.channel': 'Канал Twitch', 'dm.channel_required': 'Виберіть підключений канал', 'dm.twitch_error': 'Не вдалося надіслати у Twitch: {detail}', 'dm.open_btn': '💬 Розмова',
        'dm.voice': '🎤 Голос', 'dm.photo': '🖼 Картинка', 'dm.text_input': '⌨️ Текст', 'dm.speak_reply': '🔊 Озвучувати відповіді',
        'dm.attach_photo': 'Прикріпити картинку', 'dm.record': 'Записати', 'dm.stop': 'Стоп', 'dm.placeholder': 'Напиши у Twitch-чат…',
        'dm.you': 'Ти', 'dm.you_bot': 'Бот', 'dm.photo_ready': 'Картинку прикріплено', 'dm.transcribing': 'Розпізнаю голос…',
        'dm.voice_sent': 'голосове повідомлення', 'dm.photo_sent': 'картинка', 'dm.mic_error': 'Мікрофон недоступний', 'dm.empty': 'Порожньо — немає що надсилати', 'dm.reset': '🗑 Очистити розмову',
        'btn.clear': 'Очистити', 'btn.generate': 'Згенерувати', 'btn.test': '🔌 Тест зʼєднання',
        'label.bots_online': 'Підключено ботів', 'label.bots_enabled': 'Увімкнено',
        'label.messages_read': 'Прочитано повідомлень', 'label.bot_replies': 'Написано ботами',
        'label.live_events': 'Live-події', 'label.live_chat': 'Живий чат', 'label.loading': 'Завантаження...',
        'health.title': '🩺 Здоров’я ефіру', 'health.silent': 'мовчить', 'health.responds': 'відповідає',
        'health.last_activity': 'остання активність', 'health.empty': 'Прив’язаних каналів ще немає.',
        'label.waiting_events': 'Очікування подій...', 'label.no_data': 'Даних немає', 'label.no_bots': 'Ботів немає',
        'label.all_channels': 'Всі канали', 'label.all_bots': 'Всі боти', 'label.all_levels': 'Всі рівні',
        'label.message_from_bot': 'Повідомлення від імені бота...', 'label.no_messages': 'Повідомлень ще немає',
        'label.activity': 'Активність per-bot (написано повідомлень)', 'label.bot_logs': '📋 Логи ботів',
        'settings.group_ai': 'AI та провайдери', 'settings.group_diagnostics': 'Журнали й діагностика', 'settings.group_twitch': 'Підключення Twitch', 'settings.group_security': 'Безпека та інтерфейс', 'settings.group_maintenance': 'Дані й обслуговування', 'settings.group_modsite': 'Moderator-site: адміністрування',
        'settings.diagnostics': '🛠 Журнали й діагностика', 'settings.bot_logs_hint': 'Логи ботів є у «Статистиці»: фільтруйте за ботом, рівнем і періодом, потім вивантажуйте CSV.', 'btn.open_bot_logs': 'Відкрити логи ботів',
        'settings.ai_global': '🧠 AI (глобальний)', 'placeholder.eleven_key_set':'ключ задано (введіть новий щоб замінити)',
        'settings.tts_map_title': '🗺 Хто що озвучує',
        'settings.mod_tts_title': '🎙 Moderator TTS console', 'settings.mod_tts_hint': 'Голоси, правила та доступ Twitch-користувачів для точної пари бот/канал.',
        'settings.mod_media_title': 'GIF / медіа для модераторів', 'settings.mod_media_hint': 'Owner-approved бібліотека та окремий token-limited OBS Browser Source для вибраного scope.', 'settings.mod_media_upload': 'Завантажити та схвалити', 'settings.mod_media_obs': 'Новий OBS URL', 'settings.mod_media_stop': 'Stop', 'settings.mod_media_clear': 'Clear queue', 'settings.mod_media_kill': 'Kill switch', 'settings.mod_media_empty': 'Медіа поки немає.',
        'settings.mod_media_obs_url': 'OBS Browser Source URL', 'settings.mod_media_reveal': 'Показати на 30 секунд', 'settings.mod_media_preview': 'Безпечне прев’ю moderator media', 'settings.mod_media_rotate_hint': 'Ротація одразу вимикає старий OBS URL.', 'settings.mod_media_rotate_confirm': 'Створити новий URL? Старий OBS URL одразу перестане працювати.', 'settings.mod_media_revealed': 'URL показано на 30 секунд.', 'settings.mod_media_hidden': 'OBS URL налаштовано та приховано.', 'settings.mod_media_rotation_required': 'Старий URL продовжує працювати, але показати його неможливо. Виконайте ротацію.', 'settings.mod_media_obs_missing': 'Створіть окремий обмежений URL для OBS.', 'settings.mod_media_reveal_error': 'Не вдалося показати URL. Доступ дозволено лише локальному власнику.', 'settings.mod_media_copied': 'OBS URL скопійовано.', 'settings.mod_media_copy_error': 'Не вдалося скопіювати OBS URL.',
        'settings.mod_sound_title': 'Звуки для модераторів', 'settings.mod_sound_hint': 'Схвалені треки грають через наявний Soundboard; додайте exact-scoped URL нижче в OBS.', 'settings.mod_sound_empty': 'Треків поки немає.', 'settings.mod_sound_obs': 'Новий OBS URL', 'settings.mod_sound_obs_configured': 'OBS token налаштовано. Новий URL одразу скасує попередній.', 'settings.mod_sound_obs_missing': 'Створіть окремий обмежений URL для OBS.',
        'settings.tts_output_title': 'Єдиний TTS audio output', 'settings.tts_output_hint': 'Виберіть один exact-scoped Browser Source. Старі URL лишаються legacy та не мають active-source telemetry.', 'settings.tts_output_test': 'Тест output', 'settings.tts_output_test_text': 'Перевірка вибраного джерела озвучення',
        'settings.mod_tts_scope': 'Бот / канал', 'settings.mod_tts_source': 'Джерело TTS', 'settings.mod_tts_voices': 'Дозволені голоси',
        'settings.mod_tts_alias_ph': 'Короткий alias', 'settings.mod_tts_provider_ph': 'Provider', 'settings.mod_tts_voice_id_ph': 'Зареєстрований voice ID',
        'settings.mod_tts_add_voice': 'Додати голос', 'settings.mod_tts_policy': 'Правило джерела', 'settings.mod_tts_enabled': 'Увімкнено',
        'settings.mod_tts_voice_choice': 'Дозволити вибір голосу', 'settings.mod_tts_cooldown': 'Cooldown, сек', 'settings.mod_tts_rate': 'Максимум за хвилину',
        'settings.mod_tts_length': 'Максимальна довжина', 'settings.mod_tts_blacklist': 'Blacklist, слова через кому', 'settings.mod_tts_save_policy': 'Зберегти правило',
        'settings.mod_tts_access': 'Доступ Twitch', 'settings.mod_tts_user_id': 'Стабільний Twitch user ID', 'settings.mod_tts_login': 'Twitch login (підпис)',
        'settings.mod_tts_save_grant': 'Зберегти доступ', 'settings.mod_tts_revoke': 'Відкликати', 'settings.mod_tts_chat_enabled': 'Команда в Twitch-чаті',
        'settings.mod_tts_save_chat': 'Зберегти команду', 'settings.mod_tts_load_error': 'Не вдалося завантажити налаштування Moderator TTS.',
        'settings.mod_tts_no_scope': 'Немає увімкнених пар бот/канал.', 'settings.mod_tts_no_voices': 'Дозволених голосів поки немає.',
        'settings.mod_tts_provider_default': 'Без обраного alias', 'settings.mod_tts_loaded': 'Налаштування завантажено.',
        'settings.mod_tts_invalid_input': 'Заповніть alias і параметри голосу.', 'settings.mod_tts_invalid_user': 'Потрібен числовий Twitch user ID.',
        'settings.mod_tts_save_error': 'Не вдалося зберегти', 'settings.mod_tts_active': 'активний', 'settings.mod_tts_revoked': 'відкликаний',
        'settings.mod_tts_sessions': 'сесій', 'settings.mod_tts_invite': 'Створити вхід', 'settings.mod_tts_no_grants': 'Доступів поки немає.',
        'settings.mod_tts_one_time_link': 'Одноразове посилання, діє 15 хвилин',
        'settings.mod_tts_source_bot_reply': 'Відповіді бота', 'settings.mod_tts_source_voice_companion_reply': 'Відповіді голосового співрозмовника',
        'settings.mod_tts_source_moderation_announcement': 'Оголошення moderator-бота', 'settings.mod_tts_source_twitch_moderator_message': 'Twitch moderator TTS',
        'settings.mod_tts_source_ordinary_chat': 'Звичайний чат', 'settings.mod_tts_source_channel_points_reward': 'Channel Points reward',
        'settings.tts_map_hint': 'Лише читання: підсумкова policy і голос для кожної пари бот/канал.',
        'settings.tts_map_loading': 'Завантаження карти…', 'settings.tts_map_empty': 'Немає ввімкнених пар бот/канал.',
        'settings.tts_map_error': 'Не вдалося завантажити карту TTS.',
        'settings.tts_source_bot': 'Відповіді бота', 'settings.tts_source_companion': 'Відповіді голосового співрозмовника',
        'settings.tts_source_mod_announcement': 'Оголошення moderator-бота',
        'settings.tts_source_twitch_mod': 'Повідомлення Twitch-модераторів',
        'settings.tts_source_chat': 'Звичайний чат', 'settings.tts_source_reward': 'Channel Points reward',
        'settings.tts_col_scope': 'Бот / канал', 'settings.tts_col_source': 'Джерело',
        'settings.tts_col_policy': 'Policy', 'settings.tts_col_voice': 'Голос', 'settings.tts_col_output': 'OBS output',
        'settings.tts_policy_off': 'вимкнено', 'settings.tts_policy_on': 'ввімкнено',
        'settings.tts_policy_channel_muted': 'вимкнено в цьому каналі',
        'settings.tts_policy_not_spoken': 'автоматично не озвучується',
        'settings.tts_policy_percent': 'ввімкнено · {percent}% відповідей',
        'settings.tts_policy_rewards': 'ввімкнено · rewards: {rewards}',
        'settings.tts_policy_any_reward': 'ввімкнено · будь-який reward',
        'settings.tts_policy_legacy_account': 'legacy-налаштування на весь акаунт',
        'settings.tts_voice_unassigned': 'не призначено', 'settings.tts_voice_inherited': 'успадковано від бота/глобального',
        'settings.tts_voice_unknown': 'невідомий voice ID', 'settings.tts_voice_browser': 'перевіряється браузером OBS',
        'settings.tts_output_unverified': 'Не підтверджено: сервер не бачить активні Browser Sources',
        'settings.widgets': '📺 OBS Віджети', 'settings.security': '🔐 Безпека',
        'settings.theme_background': '🎨 Фон теми', 'settings.backup': '💾 Бекап', 'settings.faq': '❓ FAQ',
        'settings.database': '🗄 База даних', 'btn.db_optimize': '🧹 Оптимізувати',
        'btn.db_cleanup': '🗑 Очистити старі логи', 'prompt.cleanup_logs_days': 'Видалити логи старше скількох днів? (за замовчуванням 30):',
        'msg.logs_cleaned': 'Очищено {count} старих записів логів.', 'toast.invalid_days': 'Вкажіть додатне число днів.',
        'label.db_size': 'Розмір:', 'label.db_records': 'Записів:', 'msg.db_optimized': 'БД оптимізовано',
        'label.provider': 'Провайдер', 'label.model': 'Модель', 'label.api_key': 'API Ключ',
        'label.voice': 'Голос', 'label.speed': 'Швидкість', 'label.volume': 'Гучність',
        'label.client_id': 'Client ID', 'label.client_secret': 'Client Secret',
        'provider.inherit': 'Наслідувати глобальний', 'provider.custom': 'Власний API',
        'theme.default': 'Сірий', 'theme.midnight': '🌙 Опівночі', 'theme.ocean': '🌊 Океан',
        'theme.forest': '🌲 Ліс', 'theme.sunset': '🌅 Захід', 'theme.neon': '⚡ Неон',
        'theme.purple': '💜 Фіолетовий', 'theme.minimal': '◼ Мінімал',
    },
};

Object.assign(LANGS.ru, {
    'label.global_vision': 'Общая Vision-модель', 'placeholder.global_vision': 'Пусто = модель провайдера',
    'onboarding.title': '🚀 Первый запуск', 'onboarding.intro': 'Три шага до первого эфира:',
    'onboarding.step_bot': 'Добавьте Twitch-бота', 'onboarding.step_channel': 'Настройте канал', 'onboarding.step_obs': 'Подключите OBS Browser Source',
    'onboarding.dismiss': 'Не показывать больше', 'observation.title': '👁️ Что видит бот', 'widgets.connection': 'Подключение к OBS',
    'widgets.connection_hint': 'Добавьте URL виджета как Browser Source в OBS. Панель и OBS должны быть доступны на одном компьютере.',
    'widgets.wa2.example.lower_third': '👀 Например: Alekzz / играет в CS2 / @alekzz',
    'widgets.wa2.example.mascot': '👀 Например: owl · idle 120 сек; для custom — ссылка на картинку',
    'widgets.wa2.example.anime_runner': '👀 Например: угол br · скорость normal · размер M, цвета — под свой стрим',
    'panel.runner.path_points': '[[0.1,0.9],[0.9,0.85]]',
    'widgets.wa2.example.roulette': '👀 Например: Nick, Alex, Мария · спин 5 сек',
    'widgets.wa2.example.latest_event': '👀 Например: только сабы · тема glass',
    'widgets.wa2.example.session': '👀 Например: нажмите ▶ при начале эфира — uptime пойдёт в OBS',
    'widgets.wa2.example.recent': '👀 Например: follow / Nick — добавит тест-событие в ленту',
    'widgets.search': '🔎 Поиск по виджетам', 'widgets.search_ph': 'Название или slug', 'widgets.search_empty': 'Ничего не найдено.',
    'widgets.copy_url': '📋 Копировать URL', 'widgets.preview': 'Открыть превью', 'settings.twitch_app': '🟣 Twitch-приложение',
    'widgets.twitch_hint': 'Client ID и Client Secret нужны для Helix API, OAuth и получения данных каналов. Создайте приложение на dev.twitch.tv/console, укажите callback URL панели и сохраните ключи в настройках.',
    'status.no_connected_channel': 'У бота нет подключённого канала', 'status.no_fresh_observation': 'Свежего наблюдения пока нет',
    'status.ai_global_model': 'глобальная модель', 'status.online_mode': 'онлайн', 'status.offline_mode': 'оффлайн-режим',
    'status.loading': 'Загрузка...', 'status.retry': 'Повторить', 'status.no_logs': 'Логов нет',
    'status.kb_empty': 'База знаний пуста', 'status.style_empty': 'Примеров стиля нет', 'status.no_channel_bot': 'У бота нет канала',
    'toast.select_bot_export': 'Выберите бота для экспорта логов', 'toast.observation_error': 'Ошибка просмотра: {detail}',
    'toast.import_error': 'Ошибка импорта: {detail}', 'toast.voice_upload_error': 'Ошибка загрузки голоса: {detail}',
    'btn.mode': 'Режим',
    'bot.general': 'Основные настройки', 'status.offline_mode': 'Оффлайн-режим',
    'nav.widgets': 'Виджеты', 'btn.configure': '⚙️ Настроить', 'btn.observer': 'Только смотрит',
    'btn.writing': 'Писать', 'btn.observe': '👁️ Что видит', 'status.no_channel': 'У бота нет подключённого канала',
    'status.no_observation': 'Свежего наблюдения пока нет', 'status.model_global': 'глобальная модель',
    'label.custom_gender': 'Свой вариант пола', 'label.streamer': 'Стример', 'label.chat': 'Чат',
    'label.local': 'локальная', 'label.global': 'глобальная', 'label.role_viewer': 'зритель',
    'label.role_bot': 'бот', 'label.role_streamer': 'стример', 'label.widgets_connection': 'Подключение к OBS',
    'label.preview': 'Открыть превью', 'label.copy_url': '📋 Копировать URL', 'label.global_logs': '📋 Глобальные логи',
    'label.twitch_app': '🟣 Twitch-приложение', 'label.runtime_check': 'Проверка состояния...',
    'toast.enter_snippet': 'Введите название и текст фразы', 'toast.select_bot_save': 'Выберите бота для сохранения фразы',
    'toast.snippets_added': 'Добавлено заготовок: {detail}', 'toast.sent_by_bots': 'Отправлено ботами: {detail}',
    'toast.generation_error': 'Ошибка генерации: {detail}', 'toast.ai_error': 'AI ответил с ошибкой: {detail}',
    'toast.no_changes': 'Нет изменений', 'toast.select_channel': 'Выберите канал',
    'toast.select_bot_text': 'Выберите бота и введите текст', 'toast.no_channels_send': 'Нет каналов для отправки',
    'toast.user_banned': 'Пользователь заблокирован', 'toast.user_unbanned': 'Пользователь разблокирован',
    'toast.word_added': 'Слово добавлено в фильтр', 'toast.word_deleted': 'Слово удалено',
    'toast.backup_restored': 'Резервная копия восстановлена', 'toast.restore_error': 'Ошибка восстановления',
    'toast.checking_connection': 'Проверяю соединение...', 'toast.ai_connected': 'AI-соединение работает ✅',
    'toast.tts_saved': 'Настройки TTS сохранены', 'toast.attention_saved': 'Настройки внимания сохранены',
    'toast.behavior_saved': 'Поведение сохранено', 'toast.persona_saved': 'Персона сохранена',
    'toast.persona_preset_applied': 'Пресет характера применён', 'toast.persona_generated': 'Персона сгенерирована',
    'toast.tts_opened': 'Виджет TTS открыт в новой вкладке', 'toast.copied': 'Скопировано', 'toast.logs_cleared': 'Логи очищены',
    'toast.channel_deleted': 'Канал удалён', 'toast.channel_added': 'Канал #{detail} добавлен',
    'toast.channel_joined': 'Подключено к #{detail}', 'toast.channel_left': 'Выход из #{detail}',
    'toast.bot_deleted': 'Бот удалён', 'toast.bot_created': 'Бот {detail} создан', 'toast.bot_started': 'Бот запущен',
    'toast.bot_stopped': 'Бот остановлен', 'toast.general_saved': 'Основные настройки сохранены',
    'toast.ai_override_saved': 'AI-переопределение сохранено', 'toast.snippet_added': 'Заготовка добавлена',
    'toast.snippet_deleted': 'Заготовка удалена', 'toast.generating_snippets': 'Генерирую 5 заготовок...',
    'toast.not_found': 'Ничего не найдено', 'toast.error_detail': 'Ошибка: {detail}',
    'toast.select_bot': 'Выберите хотя бы одного бота', 'toast.select_bot_generate': 'Выберите бота для генерации',
     'toast.snippet_saved': 'Заготовка сохранена', 'toast.fact_saved': 'Факт сохранён', 'toast.ai_settings_saved': 'Настройки AI сохранены',
     'toast.connection_lost': 'Соединение с ботом потеряно', 'toast.override_ready': 'Пресет «{preset}» подставлен для #{channel} — нажмите «Сохранить»',
     'toast.observation_enabled': 'Режим наблюдения включён', 'toast.observation_disabled': 'Режим наблюдения выключен',
     'toast.bots_deleted': 'Удалено ботов: {detail}', 'toast.bots_started': 'Запущено {detail} ботов',
     'toast.required_nickname_token': 'Ник и токен обязательны', 'toast.nickname_required': 'Введите ник чатера',
     'toast.analyzing_style': 'Анализирую стиль сообщений...', 'toast.style_imported': 'Стиль {detail} импортирован',
     'toast.affinity_saved': 'Привязанность сохранена', 'toast.character_imported': 'Характер импортирован',
     'toast.import_failed': 'Ошибка импорта: {detail}', 'toast.preset_name_required': 'Введите название пресета',
     'toast.preset_applied': 'Пресет характера применён', 'toast.ai_generating_persona': 'AI генерирует персону...',
     'toast.override_applied': 'Пресет «{detail}» применён', 'toast.channel_added_for': 'Канал #{detail} добавлен',
     'toast.overrides_saved': 'Overrides для #{detail} сохранены', 'toast.overrides_deleted': 'Overrides удалены',
     'toast.twitch_app_saved': 'Twitch-приложение сохранено', 'toast.pattern_added': 'Pattern добавлен',
     'toast.pattern_deleted': 'Pattern удалён', 'toast.trigger_added': 'Trigger добавлен', 'toast.trigger_deleted': 'Trigger удалён',
     'toast.event_deleted': 'Event удалён', 'toast.voice_model_uploaded': 'Голосовая модель загружена',
     'toast.voice_upload_error': 'Ошибка загрузки голоса: {detail}', 'toast.snippets_deleted': 'Удалено заготовок: {detail}',
     'toast.sent_to_channel': 'Отправлено в #{detail}', 'toast.snippets_generating': 'Генерирую 5 заготовок...',
    'tab.general': 'Основное', 'tab.persona': 'Характер', 'tab.behavior': 'Поведение', 'tab.channels': 'Каналы',
    'tab.ai': 'AI', 'tab.triggers': 'Триггеры', 'tab.filters': 'Фильтры', 'tab.memory': 'Память', 'tab.snippets': 'Фразы',
    'tab.tts': 'TTS', 'tab.attention': 'Внимание', 'tab.logs': 'Логи', 'persona.generate': '🤖 Сгенерировать',
    'persona.save': '💾 Сохранить персонажа', 'attention.title': '🎯 Когда бот отвечает', 'attention.mode': 'На что реагировать',
    // AI-BUDGET AB-1: источники внимания
    'attention_sources.title': '🎯 Источники внимания (платный AI)',
    'attention_sources.hint': 'Выключенный источник = 0 запросов платной модели по нему, даже в оживлённом чате. Сырой лог чата пишется всегда, независимо от этих переключателей.',
    'attention_sources.vision': '🎥 Стрим Vision (vision-модель, дорого)',
    'attention_sources.hearing': '🔊 Стрим слух (аудио/транскрипт/beep)',
    'attention_sources.chat_ai': '💬 Чат AI-анализ (платная модель читает чат)',
    'attention_sources.future': 'Позже здесь появятся другие источники: события, донаты.',
    // PROMPT-BASE PB-3: декор исходящих сообщений
    'pb3.prefix_label': 'Эмодзи в начало сообщения',
    'pb3.suffix_label': 'Эмодзи в конец сообщения',
    'pb3.hint': 'Панель сама добавит эмодзи к готовому сообщению перед отправкой в Twitch — без участия AI. Команды (!np, !sr) не декорируются.',
    // PROMPT-BASE PB-1/PB-2: общая база запреток
    'pb.base_title': '🚫 Общая база запреток (все боты)',
    'pb.base_hint': 'Единый список запреток/правил для всех ботов — пишется один раз. Порядок сборки system prompt: база → персона/личный промпт бота → правила подсистем. При конфликте содержания личный промпт бота сильнее, но база — обязательный минимум, который бот не нарушает. Одна запретка на строку; строки с # — комментарии.',
    'pb.base_placeholder': 'Не употреблять мат\nНе обсуждать политику\nНе обещать подписки от имени стримера',
    // A3: лейблы Характера/каналов/вкладок (были захардкожены UA в JS)
    'tab.moderation': '🛡 Модерация', 'tab.voice': '🔊 Голос',
    'persona.f.humor': '😂 Юмор', 'persona.f.sarcasm': '😏 Сарказм', 'persona.f.darkness': '🌑 Чёрный юмор', 'persona.f.crudeness': '💬 Грубость', 'persona.f.adult': '🔞 Adult', 'persona.f.seriousness': '🎩 Серьёзность', 'persona.f.emotionality': '😭 Эмоциональность', 'persona.f.contact': '🤝 Привязанность к стримеру', 'persona.f.chat_affinity': '💬 Привязанность к чату',
    'persona.t.observation_only': '👀 Только наблюдает (не пишет)', 'persona.t.asterisk_emotes': '*эмоции звёздочками*', 'persona.t.auto_adjust_contact': '🤝 Авто-коррекция привязанности', 'persona.t.dynamic_humor': 'Динамический юмор', 'persona.t.dynamic_sarcasm': 'Динамический сарказм', 'persona.t.dynamic_adult': 'Динамический adult',
    'persona.preset.newbie': 'Новичок', 'persona.preset.friend': 'Друг', 'persona.preset.troll': 'Тролль', 'persona.preset.sage': 'Мудрец', 'persona.preset.toxic': 'Токсик', 'persona.preset.calm': 'Спокойный', 'persona.preset.wild': 'Дикий', 'persona.preset.spam_hahaha': 'Спам-хахаха', 'persona.preset.observer': '👀 Наблюдатель',
    'overrides.enabled': 'Включено', 'overrides.observation_only': '👀 Только наблюдает в этом канале', 'overrides.save_channel': '💾 Сохранить #{channel}',
    'gen.reason_no_json': 'AI вернул ответ без JSON-списка', 'gen.reason_empty': 'AI вернул пустой ответ', 'toast.snippets_zero': 'Заготовок не добавлено: {reason}',
    'attention.noise': 'Игнорировать шум (+1, KEKW)', 'attention.window': 'Сколько секунд собирать сообщения', 'attention.max_batch': 'Сколько сообщений собрать перед ответом',
    'attention.min_messages': 'Мин. сообщений для ответа', 'attention.cooldown': 'Кулдаун после ответа (сек)',
    'attention.max_minute': 'Макс. ответов/мин', 'tts.title': '🔊 Настройки TTS', 'tts.enabled': 'TTS включён для этого бота',
    'tts.test': '🔊 Тест', 'tts.test_text': 'Фраза для проверки голоса:', 'memory.title': '🧠 Память per-user', 'memory.description': 'Факты о пользователях, которые запоминает бот.',
    'snippets.title': '💬 Заготовки (фразы)', 'snippets.add': '+ Добавить', 'snippets.generate': '🎲 Сгенерировать 5',
    'logs.title': '📋 Логи этого бота', 'logs.load': 'Нажмите «🔄» для загрузки',
});
Object.assign(LANGS.en, {
    'label.global_vision': 'Global Vision model', 'placeholder.global_vision': 'Empty = provider model',
    'onboarding.title': '🚀 First run', 'onboarding.intro': 'Three steps to your first stream:', 'onboarding.step_bot': 'Add a Twitch bot',
    'onboarding.step_channel': 'Configure a channel', 'onboarding.step_obs': 'Connect an OBS Browser Source', 'onboarding.dismiss': 'Do not show again',
    'observation.title': '👁️ What the bot sees', 'widgets.connection': 'OBS connection', 'widgets.connection_hint': 'Add the widget URL as a Browser Source in OBS. The panel and OBS should be available on the same computer.',
    'widgets.wa2.example.lower_third': '👀 e.g. Alekzz / playing CS2 / @alekzz',
    'widgets.wa2.example.mascot': '👀 e.g. owl · idle 120 sec; custom needs an image URL',
    'widgets.wa2.example.anime_runner': '👀 e.g. corner br · speed normal · size M, colors to match your stream',
    'panel.runner.path_points': '[[0.1,0.9],[0.9,0.85]]',
    'widgets.wa2.example.roulette': '👀 e.g. Nick, Alex, Maria · spin 5 sec',
    'widgets.wa2.example.latest_event': '👀 e.g. subs only · glass theme',
    'widgets.wa2.example.session': '👀 e.g. hit ▶ when you go live — uptime shows in OBS',
    'widgets.wa2.example.recent': '👀 e.g. follow / Nick — adds a test event to the feed',
    'widgets.search': '🔎 Search widgets', 'widgets.search_ph': 'Name or slug', 'widgets.search_empty': 'Nothing found.',
    'widgets.copy_url': '📋 Copy URL', 'widgets.preview': 'Open preview', 'settings.twitch_app': '🟣 Twitch application',
    'widgets.twitch_hint': 'Client ID and Client Secret are required for Helix API, OAuth and channel data. Create an app at dev.twitch.tv/console, set the panel callback URL, and save the keys in Settings.',
    'status.no_connected_channel': 'Bot has no connected channel', 'status.no_fresh_observation': 'No fresh observation yet',
    'status.ai_global_model': 'global model', 'status.online_mode': 'online', 'status.offline_mode': 'offline mode',
    'status.loading': 'Loading...', 'status.retry': 'Retry', 'status.no_logs': 'No logs', 'status.kb_empty': 'Knowledge base is empty',
    'status.style_empty': 'No style examples', 'status.no_channel_bot': 'Bot has no channel', 'toast.select_bot_export': 'Select a bot to export logs',
    'toast.observation_error': 'Preview error: {detail}', 'toast.import_error': 'Import error: {detail}', 'toast.voice_upload_error': 'Voice upload error: {detail}',
    'btn.mode': 'Mode',
    'bot.general': 'General settings', 'status.offline_mode': 'Offline mode',
    'nav.widgets': 'Widgets', 'btn.configure': '⚙️ Configure', 'btn.observer': 'Observe only', 'btn.writing': 'Write',
    'btn.observe': '👁️ What it sees', 'status.no_channel': 'Bot has no connected channel', 'status.no_observation': 'No fresh observation yet',
    'status.model_global': 'global model', 'label.custom_gender': 'Custom gender', 'label.streamer': 'Streamer', 'label.chat': 'Chat',
    'label.local': 'local', 'label.global': 'global', 'label.role_viewer': 'viewer', 'label.role_bot': 'bot',
    'label.role_streamer': 'streamer', 'label.widgets_connection': 'OBS connection', 'label.preview': 'Open preview',
    'label.copy_url': '📋 Copy URL', 'label.global_logs': '📋 Global logs', 'label.twitch_app': '🟣 Twitch application',
    'label.runtime_check': 'Checking status...',
    'toast.enter_snippet': 'Enter a phrase name and text', 'toast.select_bot_save': 'Select a bot to save the phrase',
    'toast.snippets_added': 'Snippets added: {detail}', 'toast.sent_by_bots': 'Sent by bots: {detail}',
    'toast.generation_error': 'Generation error: {detail}', 'toast.ai_error': 'AI returned an error: {detail}',
    'toast.no_changes': 'No changes', 'toast.select_channel': 'Select a channel', 'toast.select_bot_text': 'Select a bot and enter text',
    'toast.no_channels_send': 'No channels available for sending', 'toast.user_banned': 'User blocked', 'toast.user_unbanned': 'User unblocked',
    'toast.word_added': 'Word added to filter', 'toast.word_deleted': 'Word removed', 'toast.backup_restored': 'Backup restored',
    'toast.restore_error': 'Restore error', 'toast.checking_connection': 'Checking connection...', 'toast.ai_connected': 'AI connection works ✅',
    'toast.tts_saved': 'TTS settings saved', 'toast.attention_saved': 'Attention settings saved', 'toast.behavior_saved': 'Behavior saved',
    'toast.persona_saved': 'Persona saved', 'toast.persona_preset_applied': 'Persona preset applied', 'toast.persona_generated': 'Persona generated',
    'toast.tts_opened': 'TTS widget opened in a new tab', 'toast.copied': 'Copied', 'toast.logs_cleared': 'Logs cleared',
    'toast.channel_deleted': 'Channel deleted', 'toast.channel_added': 'Channel #{detail} added', 'toast.channel_joined': 'Joined #{detail}',
    'toast.channel_left': 'Left #{detail}', 'toast.bot_deleted': 'Bot deleted', 'toast.bot_created': 'Bot {detail} created',
    'toast.bot_started': 'Bot started', 'toast.bot_stopped': 'Bot stopped', 'toast.general_saved': 'General settings saved',
    'toast.ai_override_saved': 'AI override saved', 'toast.snippet_added': 'Snippet added', 'toast.snippet_deleted': 'Snippet deleted',
    'toast.generating_snippets': 'Generating 5 snippets...',
    'toast.not_found': 'Nothing found', 'toast.error_detail': 'Error: {detail}',
    'toast.select_bot': 'Select at least one bot', 'toast.select_bot_generate': 'Select a bot for generation',
     'toast.snippet_saved': 'Snippet saved', 'toast.fact_saved': 'Fact saved', 'toast.ai_settings_saved': 'AI settings saved',
     'toast.connection_lost': 'Bot connection lost', 'toast.override_ready': 'Preset "{preset}" ready for #{channel} — click "Save"',
     'toast.observation_enabled': 'Observation mode enabled', 'toast.observation_disabled': 'Observation mode disabled',
     'toast.bots_deleted': 'Bots deleted: {detail}', 'toast.bots_started': 'Started {detail} bots',
     'toast.required_nickname_token': 'Nickname and token are required', 'toast.nickname_required': 'Enter chatter nickname',
     'toast.analyzing_style': 'Analyzing message style...', 'toast.style_imported': 'Style for {detail} imported',
     'toast.affinity_saved': 'Affinity saved', 'toast.character_imported': 'Character imported',
     'toast.import_failed': 'Import error: {detail}', 'toast.preset_name_required': 'Enter preset name',
     'toast.preset_applied': 'Character preset applied', 'toast.ai_generating_persona': 'AI is generating a persona...',
     'toast.override_applied': 'Preset "{detail}" applied', 'toast.channel_added_for': 'Channel #{detail} added',
     'toast.overrides_saved': 'Overrides for #{detail} saved', 'toast.overrides_deleted': 'Overrides deleted',
     'toast.twitch_app_saved': 'Twitch application saved', 'toast.pattern_added': 'Pattern added',
     'toast.pattern_deleted': 'Pattern deleted', 'toast.trigger_added': 'Trigger added', 'toast.trigger_deleted': 'Trigger deleted',
     'toast.event_deleted': 'Event deleted', 'toast.voice_model_uploaded': 'Voice model uploaded',
     'toast.voice_upload_error': 'Voice upload error: {detail}', 'toast.snippets_deleted': 'Snippets deleted: {detail}',
     'toast.sent_to_channel': 'Sent to #{detail}', 'toast.snippets_generating': 'Generating 5 snippets...',
    'tab.general': 'General', 'tab.persona': 'Persona', 'tab.behavior': 'Behavior', 'tab.channels': 'Channels', 'tab.ai': 'AI',
    'tab.triggers': 'Triggers', 'tab.filters': 'Filters', 'tab.memory': 'Memory', 'tab.snippets': 'Phrases', 'tab.tts': 'TTS',
    'tab.attention': 'Attention', 'tab.logs': 'Logs', 'persona.generate': '🤖 Generate', 'persona.save': '💾 Save persona',
    'tab.moderation': '🛡 Moderation', 'tab.voice': '🔊 Voice',
    'persona.f.humor': '😂 Humor', 'persona.f.sarcasm': '😏 Sarcasm', 'persona.f.darkness': '🌑 Dark humor', 'persona.f.crudeness': '💬 Crudeness', 'persona.f.adult': '🔞 Adult', 'persona.f.seriousness': '🎩 Seriousness', 'persona.f.emotionality': '😭 Emotionality', 'persona.f.contact': '🤝 Streamer attachment', 'persona.f.chat_affinity': '💬 Chat attachment',
    'persona.t.observation_only': '👀 Observe only (no messages)', 'persona.t.asterisk_emotes': '*emotes in asterisks*', 'persona.t.auto_adjust_contact': '🤝 Auto-adjust attachment', 'persona.t.dynamic_humor': 'Dynamic humor', 'persona.t.dynamic_sarcasm': 'Dynamic sarcasm', 'persona.t.dynamic_adult': 'Dynamic adult',
    'persona.preset.newbie': 'Newbie', 'persona.preset.friend': 'Friend', 'persona.preset.troll': 'Troll', 'persona.preset.sage': 'Sage', 'persona.preset.toxic': 'Toxic', 'persona.preset.calm': 'Calm', 'persona.preset.wild': 'Wild', 'persona.preset.spam_hahaha': 'Haha-spam', 'persona.preset.observer': '👀 Observer',
    'overrides.enabled': 'Enabled', 'overrides.observation_only': '👀 Observe only in this channel', 'overrides.save_channel': '💾 Save #{channel}',
    'gen.reason_no_json': 'AI reply had no JSON list', 'gen.reason_empty': 'AI returned an empty reply', 'toast.snippets_zero': 'No snippets added: {reason}',
    'attention.title': '🎯 When the bot replies', 'attention.mode': 'What to react to', 'attention.noise': 'Ignore noise (+1, KEKW)',
    // AI-BUDGET AB-1: attention sources
    'attention_sources.title': '🎯 Attention sources (paid AI)',
    'attention_sources.hint': 'A disabled source = 0 paid-model requests for it, even in a busy chat. Raw chat log is always written regardless of these switches.',
    'attention_sources.vision': '🎥 Stream Vision (vision model, expensive)',
    'attention_sources.hearing': '🔊 Stream hearing (audio/transcript/beep)',
    'attention_sources.chat_ai': '💬 Chat AI analysis (paid model reads chat)',
    'attention_sources.future': 'More sources will appear here later: events, donations.',
    // PROMPT-BASE PB-3: outgoing message decor
    'pb3.prefix_label': 'Emoji at the start of a message',
    'pb3.suffix_label': 'Emoji at the end of a message',
    'pb3.hint': 'The panel adds the emoji to the finished message before sending to Twitch — no AI involved. Commands (!np, !sr) are not decorated.',
    // PROMPT-BASE PB-1/PB-2: shared rules base
    'pb.base_title': '🚫 Shared rules base (all bots)',
    'pb.base_hint': 'One shared list of bans/rules for all bots — written once. System prompt assembly order: base → bot persona/personal prompt → subsystem rules. On conflicting content the bot’s personal prompt wins, but the base is a hard minimum the bot never breaks. One rule per line; lines starting with # are comments.',
    'pb.base_placeholder': 'No swearing\nNo politics\nDon’t promise subscriptions on behalf of the streamer',
    'attention.window': 'Seconds to collect messages', 'attention.max_batch': 'Messages to collect before replying', 'attention.min_messages': 'Min. messages to reply',
    'attention.cooldown': 'Reply cooldown (sec)', 'attention.max_minute': 'Max replies/min', 'tts.title': '🔊 TTS settings',
    'tts.enabled': 'TTS enabled for this bot', 'tts.test': '🔊 Test', 'tts.test_text': 'Voice test phrase:', 'memory.title': '🧠 Per-user memory',
    'memory.description': 'Facts remembered about users.', 'snippets.title': '💬 Snippets', 'snippets.add': '+ Add',
    'snippets.generate': '🎲 Generate 5', 'logs.title': '📋 This botʼs logs', 'logs.load': 'Press «🔄» to load',
});
Object.assign(LANGS.ua, {
    'label.global_vision': 'Загальна Vision-модель', 'placeholder.global_vision': 'Порожньо = модель провайдера',
    'onboarding.title': '🚀 Перший запуск', 'onboarding.intro': 'Три кроки до першого ефіру:', 'onboarding.step_bot': 'Додайте Twitch-бота',
    'onboarding.step_channel': 'Налаштуйте канал', 'onboarding.step_obs': 'Підключіть OBS Browser Source', 'onboarding.dismiss': 'Більше не показувати',
    'observation.title': '👁️ Що бачить бот', 'widgets.connection': 'Підключення до OBS', 'widgets.connection_hint': 'Додайте URL віджета як Browser Source в OBS. Панель і OBS мають бути доступні на одному компʼютері.',
    'widgets.wa2.example.lower_third': '👀 Наприклад: Alekzz / грає в CS2 / @alekzz',
    'widgets.wa2.example.mascot': '👀 Наприклад: owl · idle 120 сек; для custom — посилання на картинку',
    'widgets.wa2.example.anime_runner': '👀 Наприклад: кут br · швидкість normal · розмір M, кольори — під свій стрім',
    'panel.runner.path_points': '[[0.1,0.9],[0.9,0.85]]',
    'widgets.wa2.example.roulette': '👀 Наприклад: Nick, Alex, Марія · спін 5 сек',
    'widgets.wa2.example.latest_event': '👀 Наприклад: лише саби · тема glass',
    'widgets.wa2.example.session': '👀 Наприклад: натисніть ▶ на початку ефіру — uptime піде в OBS',
    'widgets.wa2.example.recent': '👀 Наприклад: follow / Nick — додасть тест-подію в стрічку',
    'widgets.search': '🔎 Пошук по віджетах', 'widgets.search_ph': 'Назва або slug', 'widgets.search_empty': 'Нічого не знайдено.',
    'widgets.copy_url': '📋 Копіювати URL', 'widgets.preview': 'Відкрити превʼю', 'settings.twitch_app': '🟣 Twitch-застосунок',
    'widgets.twitch_hint': 'Client ID і Client Secret потрібні для Helix API, OAuth і даних каналів. Створіть застосунок на dev.twitch.tv/console, вкажіть callback URL панелі та збережіть ключі в налаштуваннях.',
    'status.no_connected_channel': 'У бота немає підключеного каналу', 'status.no_fresh_observation': 'Свіжого спостереження ще немає',
    'status.ai_global_model': 'глобальна модель', 'status.online_mode': 'онлайн', 'status.offline_mode': 'офлайн-режим',
    'status.loading': 'Завантаження...', 'status.retry': 'Повторити', 'status.no_logs': 'Логів немає', 'status.kb_empty': 'База знань порожня',
    'status.style_empty': 'Прикладів стилю немає', 'status.no_channel_bot': 'У бота немає каналу', 'toast.select_bot_export': 'Виберіть бота для експорту логів',
    'toast.observation_error': 'Помилка перегляду: {detail}', 'toast.import_error': 'Помилка імпорту: {detail}', 'toast.voice_upload_error': 'Помилка завантаження голосу: {detail}',
    'btn.mode': 'Режим',
    'bot.general': 'Основні налаштування', 'status.offline_mode': 'Офлайн-режим',
    'nav.widgets': 'Віджети', 'btn.configure': '⚙️ Налаштувати', 'btn.observer': 'Тільки спостерігати', 'btn.writing': 'Писати',
    'btn.observe': '👁️ Що бачить', 'status.no_channel': 'У бота немає підключеного каналу', 'status.no_observation': 'Свіжого спостереження ще немає',
    'status.model_global': 'глобальна модель', 'label.custom_gender': 'Власний варіант статі', 'label.streamer': 'Стример', 'label.chat': 'Чат',
    'label.local': 'локальна', 'label.global': 'глобальна', 'label.role_viewer': 'глядач', 'label.role_bot': 'бот',
    'label.role_streamer': 'стример', 'label.widgets_connection': 'Підключення до OBS', 'label.preview': 'Відкрити превʼю',
    'label.copy_url': '📋 Копіювати URL', 'label.global_logs': '📋 Глобальні логи', 'label.twitch_app': '🟣 Twitch-застосунок',
    'label.runtime_check': 'Перевірка стану...',
    'toast.enter_snippet': 'Введіть назву та текст фрази', 'toast.select_bot_save': 'Виберіть бота для збереження фрази',
    'toast.snippets_added': 'Додано заготовок: {detail}', 'toast.sent_by_bots': 'Відправлено ботами: {detail}',
    'toast.generation_error': 'Помилка генерації: {detail}', 'toast.ai_error': 'AI відповів з помилкою: {detail}',
    'toast.no_changes': 'Немає змін', 'toast.select_channel': 'Виберіть канал', 'toast.select_bot_text': 'Виберіть бота та введіть текст',
    'toast.no_channels_send': 'Немає каналів для відправки', 'toast.user_banned': 'Користувача заблоковано', 'toast.user_unbanned': 'Користувача розблоковано',
    'toast.word_added': 'Слово додано до фільтра', 'toast.word_deleted': 'Слово видалено', 'toast.backup_restored': 'Бекап відновлено',
    'toast.restore_error': 'Помилка відновлення', 'toast.checking_connection': 'Перевіряю зʼєднання...', 'toast.ai_connected': 'AI-зʼєднання працює ✅',
    'toast.tts_saved': 'TTS збережено', 'toast.attention_saved': 'Налаштування уваги збережено', 'toast.behavior_saved': 'Поведінку збережено',
    'toast.persona_saved': 'Персону збережено', 'toast.persona_preset_applied': 'Пресет характеру застосовано', 'toast.persona_generated': 'Персону згенеровано',
    'toast.tts_opened': 'Віджет TTS відкрито в новій вкладці', 'toast.copied': 'Скопійовано', 'toast.logs_cleared': 'Логи очищено',
    'toast.channel_deleted': 'Канал видалено', 'toast.channel_added': 'Канал #{detail} додано', 'toast.channel_joined': 'Приєднано до #{detail}',
    'toast.channel_left': 'Вийшов з #{detail}', 'toast.bot_deleted': 'Бота видалено', 'toast.bot_created': 'Бота {detail} створено',
    'toast.bot_started': 'Бота запущено', 'toast.bot_stopped': 'Бота зупинено', 'toast.general_saved': 'Основні налаштування збережено',
    'toast.ai_override_saved': 'AI перевизначення збережено', 'toast.snippet_added': 'Заготовку додано', 'toast.snippet_deleted': 'Заготовку видалено',
    'toast.generating_snippets': 'Генерую 5 заготовок...',
    'toast.not_found': 'Нічого не знайдено', 'toast.error_detail': 'Помилка: {detail}',
    'toast.select_bot': 'Виберіть хоча б одного бота', 'toast.select_bot_generate': 'Виберіть бота для генерації',
     'toast.snippet_saved': 'Заготовку збережено', 'toast.fact_saved': 'Факт збережено', 'toast.ai_settings_saved': 'AI налаштування збережено',
     'toast.connection_lost': 'Зʼєднання з ботом втрачено', 'toast.override_ready': 'Пресет «{preset}» підставлено для #{channel} — натисніть «Зберегти»',
     'toast.observation_enabled': 'Режим спостереження увімкнено', 'toast.observation_disabled': 'Режим спостереження вимкнено',
     'toast.bots_deleted': 'Видалено ботів: {detail}', 'toast.bots_started': 'Запущено {detail} ботів',
     'toast.required_nickname_token': 'Нік та токен обовʼязкові', 'toast.nickname_required': 'Введіть нік чатера',
     'toast.analyzing_style': 'Аналізую стиль повідомлень...', 'toast.style_imported': 'Стиль {detail} імпортовано',
     'toast.affinity_saved': 'Привʼязаність збережена', 'toast.character_imported': 'Характер імпортовано',
     'toast.import_failed': 'Помилка імпорту: {detail}', 'toast.preset_name_required': 'Введіть назву пресета',
     'toast.preset_applied': 'Пресет характеру застосовано', 'toast.ai_generating_persona': 'AI генерує персону...',
     'toast.override_applied': 'Пресет «{detail}» застосовано', 'toast.channel_added_for': 'Канал #{detail} додано',
     'toast.overrides_saved': 'Overrides для #{detail} збережено', 'toast.overrides_deleted': 'Overrides видалено',
     'toast.twitch_app_saved': 'Twitch-застосунок збережено', 'toast.pattern_added': 'Pattern додано',
     'toast.pattern_deleted': 'Pattern видалено', 'toast.trigger_added': 'Trigger додано', 'toast.trigger_deleted': 'Trigger видалено',
     'toast.event_deleted': 'Event видалено', 'toast.voice_model_uploaded': 'Голосову модель завантажено',
     'toast.voice_upload_error': 'Помилка завантаження голосу: {detail}', 'toast.snippets_deleted': 'Видалено заготовок: {detail}',
     'toast.sent_to_channel': 'Відправлено в #{detail}', 'toast.snippets_generating': 'Генерую 5 заготовок...',
    'tab.general': 'Основне', 'tab.persona': 'Характер', 'tab.behavior': 'Поведінка', 'tab.channels': 'Канали', 'tab.ai': 'AI',
    'tab.triggers': 'Тригери', 'tab.filters': 'Фільтри', 'tab.memory': 'Памʼять', 'tab.snippets': 'Фрази', 'tab.tts': 'TTS',
    'tab.attention': 'Увага', 'tab.logs': 'Логи', 'persona.generate': '🤖 Згенерувати', 'persona.save': '💾 Зберегти характер',
    'tab.moderation': '🛡 Модерація', 'tab.voice': '🔊 Голос',
    'persona.f.humor': '😂 Гумор', 'persona.f.sarcasm': '😏 Сарказм', 'persona.f.darkness': '🌑 Чорний гумор', 'persona.f.crudeness': '💬 Пошлість', 'persona.f.adult': '🔞 Adult', 'persona.f.seriousness': '🎩 Серйозність', 'persona.f.emotionality': '😭 Емоційність', 'persona.f.contact': '🤝 Привʼязаність до стрімера', 'persona.f.chat_affinity': '💬 Привʼязаність до чату',
    'persona.t.observation_only': '👀 Тільки спостерігає (не пише)', 'persona.t.asterisk_emotes': '*емоції зірочками*', 'persona.t.auto_adjust_contact': '🤝 Авто-корекція привʼязаності', 'persona.t.dynamic_humor': 'Динамічний гумор', 'persona.t.dynamic_sarcasm': 'Динамічний сарказм', 'persona.t.dynamic_adult': 'Динамічний adult',
    'persona.preset.newbie': 'Новачок', 'persona.preset.friend': 'Друг', 'persona.preset.troll': 'Тролль', 'persona.preset.sage': 'Мудрець', 'persona.preset.toxic': 'Токсик', 'persona.preset.calm': 'Спокійний', 'persona.preset.wild': 'Дикий', 'persona.preset.spam_hahaha': 'Спам-хахаха', 'persona.preset.observer': '👀 Спостерігач',
    'overrides.enabled': 'Увімкнено', 'overrides.observation_only': '👀 Тільки спостерігає в цьому каналі', 'overrides.save_channel': '💾 Зберегти #{channel}',
    'gen.reason_no_json': 'AI повернув відповідь без JSON-списку', 'gen.reason_empty': 'AI повернув порожню відповідь', 'toast.snippets_zero': 'Заготовок не додано: {reason}',
    'attention.title': '🎯 Коли бот відповідає', 'attention.mode': 'На що реагувати', 'attention.noise': 'Ігнорувати шум (+1, KEKW)',
    // AI-BUDGET AB-1: джерела уваги
    'attention_sources.title': '🎯 Джерела уваги (платний AI)',
    'attention_sources.hint': 'Вимкнене джерело = 0 запитів платної моделі по ньому, навіть у жвавому чаті. Сирий лог чату пишеться завжди, незалежно від цих перемикачів.',
    'attention_sources.vision': '🎥 Стрім Vision (vision-модель, дорого)',
    'attention_sources.hearing': '🔊 Стрім слух (аудіо/транскрипт/beep)',
    'attention_sources.chat_ai': '💬 Чат AI-аналіз (платна модель читає чат)',
    'attention_sources.future': 'Пізніше тут з’являться інші джерела: події, донати.',
    // PROMPT-BASE PB-3: декор вихідних повідомлень
    'pb3.prefix_label': 'Емодзі на початку повідомлення',
    'pb3.suffix_label': 'Емодзі в кінці повідомлення',
    'pb3.hint': 'Панель сама додасть емодзі до готового повідомлення перед відправкою в Twitch — без участі AI. Команди (!np, !sr) не декоруються.',
    // PROMPT-BASE PB-1/PB-2: спільна база заборон
    'pb.base_title': '🚫 Спільна база заборон (усі боти)',
    'pb.base_hint': 'Єдиний список заборон/правил для всіх ботів — пишеться один раз. Порядок збирання system prompt: база → персона/особистий промпт бота → правила підсистем. При конфлікті змісту особистий промпт бота сильніший, але база — обов’язковий мінімум, який бот не порушує. Одна заборона на рядок; рядки з # — коментарі.',
    'pb.base_placeholder': 'Не вживати мат\nНе обговорювати політику\nНе обіцяти підписки від імені стрімера',
    'attention.window': 'Скільки секунд збирати повідомлення', 'attention.max_batch': 'Скільки повідомлень зібрати перед відповіддю', 'attention.min_messages': 'Мін. повідомлень для відповіді',
    'attention.cooldown': 'Кулдаун після відповіді (сек)', 'attention.max_minute': 'Макс. відповідей/хв', 'tts.title': '🔊 Налаштування TTS',
    'tts.enabled': 'TTS увімкнено для цього бота', 'tts.test': '🔊 Тест', 'tts.test_text': 'Фраза для перевірки голосу:', 'memory.title': '🧠 Памʼять per-user',
    'memory.description': 'Факти про користувачів, які запамʼятовує бот.', 'snippets.title': '💬 Заготовки (фрази)',
    'snippets.add': '+ Додати', 'snippets.generate': '🎲 Згенерувати 5', 'logs.title': '📋 Логи цього бота',
    'logs.load': 'Натисніть «🔄» для завантаження',
});

// Dynamic views use these keys for empty, loading, and action states. Keep
// them in each locale so a language switch never falls back to another one.
const DYNAMIC_I18N = {
    ru: {
        'label.connecting': 'Подключение', 'label.error': 'Ошибка',
        'btn.close': 'Закрыть',
        'empty.waiting_events': 'Ожидание событий...', 'empty.no_bots': 'Ботов нет. Добавьте первого в разделе «Боты»!',
        'empty.no_bots_add': 'Ботов нет. Нажмите «+ Добавить бота»', 'empty.no_triggers': 'Триггеров нет — добавьте!',
        'empty.no_events': 'Событий нет — добавьте!', 'empty.no_banned': 'Заблокированных пользователей нет',
        'empty.no_filtered_words': 'Слов в фильтре нет', 'toast.not_sent_by_bots': 'Не отправлено ботами: {detail}',
        'toast.trigger_updated': 'Триггер обновлён', 'toast.event_added': 'Событие добавлено',
        'status.runtime': 'AI: {provider}', 'status.ai_paused': ' · приостановлен: Ollama недоступна', 'status.ai_paused_short': 'Приостановлен: Ollama недоступна', 'status.fallback_enabled': ' · Ollama fallback включён',
        'status.runtime_error': 'Ошибка состояния: {detail}', 'status.bot_enabled_not_connected': 'Включён (не подключён)',
        'onboarding.next': 'Далее', 'onboarding.done': 'Готово', 'onboarding.complete': 'Первоначальная настройка завершена',
        'onboarding.ai_title': 'Подключим AI', 'onboarding.twitch_title': 'Подключим Twitch', 'onboarding.tts_title': 'Добавим озвучку',
        'onboarding.bot_title': 'Создадим первого бота', 'onboarding.channel_title': 'Выберем канал', 'onboarding.obs_title': 'Подключим OBS',
        'onboarding.ai_description': 'Выберите провайдера. Ключ можно добавить сейчас или настроить позже в разделе «Настройки».',
        'onboarding.twitch_description': 'Client ID и Secret нужны для данных канала и OAuth. Их можно пропустить, если токен бота уже готов.',
        'onboarding.tts_description': 'Настройте голос для сообщений. Web Speech работает без ключа прямо в браузере.',
        'onboarding.bot_description': 'Введите имя Twitch-аккаунта бота и OAuth-токен с правом писать в чат.',
        'onboarding.channel_description': 'Куда боту подключаться после запуска?',
        'onboarding.obs_description': 'Скопируйте URL TTS-виджета в OBS как Browser Source. Панель и OBS должны быть на одном компьютере.',
        'onboarding.label_ai_provider': 'AI провайдер', 'onboarding.label_model': 'Модель', 'onboarding.label_api_key': 'API ключ (опционально)',
        'onboarding.label_base_url': 'Base URL для Ollama/Custom', 'onboarding.label_twitch_id': 'Twitch Client ID',
        'onboarding.label_twitch_secret': 'Twitch Client Secret', 'onboarding.label_tts_provider': 'Провайдер TTS',
        'onboarding.label_voice': 'Голос (опционально)', 'onboarding.label_tts_key': 'ElevenLabs API key (опционально)',
        'onboarding.label_bot_name': 'Никнейм Twitch', 'onboarding.label_bot_token': 'OAuth токен', 'onboarding.label_channel': 'Название канала',
        'onboarding.widget_url': 'URL виджета', 'onboarding.copy_url': 'Скопировать URL', 'onboarding.preview': 'Открыть превью',
        'confirm.delete_bots': 'Удалить {count} ботов? Это действие необратимо.', 'confirm.delete_bot': 'Удалить бота {name}? Это действие необратимо.',
        'confirm.delete_item': 'Удалить этот элемент?', 'confirm.delete_named': 'Удалить {name}?', 'confirm.clear_logs': 'Очистить все логи этого бота?',
        'confirm.restore_backup': 'Восстановить из бекапа? Текущие данные будут перезаписаны.', 'confirm.delete_memory': 'Удалить всю память о {name}?',
        'prompt.phrase_name': 'Название фразы:', 'prompt.phrase_text': 'Текст фразы:', 'prompt.keyword': 'Ключевое слово',
        'prompt.fixed_response': 'Фиксированный ответ (пусто = AI)', 'prompt.edit_fact': 'Изменить факт:', 'prompt.persona': 'Опишите персонажа кратко (например: «геймер с Одессы, любит Dota 2 и сарказм»):',
        'error.bot_credentials': 'Введите никнейм и OAuth-токен', 'error.channel_and_bot': 'Введите канал и сначала создайте бота',
        'bot.preset': 'пользовательский пресет', 'bot.voice_clone': 'голосовой клон', 'confirm.delete_snippets': 'Удалить {count} заготовок?',
        'behavior.title': 'Пресеты поведения', 'behavior.description': 'Быстрый выбор того, когда и как бот отвечает. Пресет меняет поведение, а не характер.', 'behavior.custom_preset_placeholder': 'Название своего пресета', 'behavior.save_custom': '+ Сохранить текущие значения',
        'behavior.auto_chat': 'Бот может сам начинать сообщения', 'behavior.auto_chat_hint': 'Если выключить, бот продолжит читать чат и отвечать на разрешённые обращения.',
        'behavior.use_persona': 'Использовать характер бота', 'behavior.silent': 'Тихий режим', 'behavior.silent_hint': 'Бот собирает контекст, но отвечает реже и не озвучивает каждое сообщение.',
        'behavior.cooldown': 'Минимальный интервал между сообщениями (сек)', 'behavior.instructions': 'Дополнительные инструкции боту',
        'behavior.instructions_placeholder': 'Например: отвечай коротко и не перебивай стримера', 'behavior.response_length': 'Длина ответа',
        'behavior.short': 'Короткий (10–15 слов)', 'behavior.medium': 'Средний', 'behavior.long': 'Длинный', 'behavior.save': '💾 Сохранить поведение',
        'preset.quiet': 'Тихий', 'preset.friendly': 'Дружелюбный', 'preset.troll': 'Тролль', 'preset.wild': 'Дикий', 'preset.spam': 'Спам-хахаха', 'preset.observer': 'Наблюдатель',
        'preset.quiet_desc': 'Для спокойных и серьёзных стримов', 'preset.friendly_desc': 'Для обычного общения', 'preset.troll_desc': 'Для лёгких подколов без злобы',
        'preset.wild_desc': 'Для хайповых моментов', 'preset.spam_desc': 'Когда стример активно шутит', 'preset.observer_desc': 'Только наблюдает и не пишет',
        'onboarding.eyebrow': 'ПЕРВЫЙ ЗАПУСК', 'onboarding.close': 'Закрыть', 'onboarding.progress': 'Прогресс настройки', 'onboarding.back': 'Назад', 'onboarding.skip': 'Пропустить', 'onboarding.legacy': 'Открыть старую форму добавления бота',
    },
    en: {
        'label.connecting': 'Connecting', 'label.error': 'Error',
        'btn.close': 'Close',
        'empty.waiting_events': 'Waiting for events...', 'empty.no_bots': 'No bots. Add the first one in the Bots section!',
        'empty.no_bots_add': 'No bots. Click “+ Add bot”', 'empty.no_triggers': 'No triggers — add one!',
        'empty.no_events': 'No events — add one!', 'empty.no_banned': 'No blocked users',
        'empty.no_filtered_words': 'No filtered words', 'toast.not_sent_by_bots': 'Not sent by bots: {detail}',
        'toast.trigger_updated': 'Trigger updated', 'toast.event_added': 'Event added',
        'status.runtime': 'AI: {provider}', 'status.ai_paused': ' · paused: Ollama unavailable', 'status.ai_paused_short': 'Paused: Ollama unavailable', 'status.fallback_enabled': ' · Ollama fallback enabled',
        'status.runtime_error': 'Status error: {detail}', 'status.bot_enabled_not_connected': 'Enabled (not connected)',
        'onboarding.next': 'Next', 'onboarding.done': 'Done', 'onboarding.complete': 'Initial setup completed',
        'onboarding.ai_title': 'Connect AI', 'onboarding.twitch_title': 'Connect Twitch', 'onboarding.tts_title': 'Add voice output',
        'onboarding.bot_title': 'Create your first bot', 'onboarding.channel_title': 'Choose a channel', 'onboarding.obs_title': 'Connect OBS',
        'onboarding.ai_description': 'Choose a provider. Add a key now or configure it later in Settings.', 'onboarding.twitch_description': 'Client ID and Secret are needed for channel data and OAuth. Skip this if the bot token is ready.',
        'onboarding.tts_description': 'Configure the voice for messages. Web Speech works in the browser without a key.', 'onboarding.bot_description': 'Enter the bot Twitch account name and an OAuth token allowed to write in chat.',
        'onboarding.channel_description': 'Where should the bot connect after launch?', 'onboarding.obs_description': 'Copy the TTS widget URL to OBS as a Browser Source. The panel and OBS should be on the same computer.',
        'onboarding.label_ai_provider': 'AI provider', 'onboarding.label_model': 'Model', 'onboarding.label_api_key': 'API key (optional)', 'onboarding.label_base_url': 'Base URL for Ollama/Custom',
        'onboarding.label_twitch_id': 'Twitch Client ID', 'onboarding.label_twitch_secret': 'Twitch Client Secret', 'onboarding.label_tts_provider': 'TTS provider', 'onboarding.label_voice': 'Voice (optional)',
        'onboarding.label_tts_key': 'ElevenLabs API key (optional)', 'onboarding.label_bot_name': 'Twitch nickname', 'onboarding.label_bot_token': 'OAuth token', 'onboarding.label_channel': 'Channel name',
        'onboarding.widget_url': 'Widget URL', 'onboarding.copy_url': 'Copy URL', 'onboarding.preview': 'Open preview', 'confirm.delete_bots': 'Delete {count} bots? This cannot be undone.',
        'confirm.delete_bot': 'Delete bot {name}? This cannot be undone.', 'confirm.delete_item': 'Delete this item?', 'confirm.delete_named': 'Delete {name}?', 'confirm.clear_logs': 'Clear all logs for this bot?',
        'confirm.restore_backup': 'Restore from backup? Current data will be overwritten.', 'confirm.delete_memory': 'Delete all memory about {name}?', 'prompt.phrase_name': 'Phrase name:', 'prompt.phrase_text': 'Phrase text:',
        'prompt.keyword': 'Keyword', 'prompt.fixed_response': 'Fixed response (empty = AI)', 'prompt.edit_fact': 'Edit fact:', 'prompt.persona': 'Describe the persona briefly (for example: “gamer from Odesa who likes Dota 2 and sarcasm”):',
        'error.bot_credentials': 'Enter the nickname and OAuth token', 'error.channel_and_bot': 'Enter a channel and create a bot first',
        'bot.preset': 'custom preset', 'bot.voice_clone': 'voice clone', 'confirm.delete_snippets': 'Delete {count} snippets?',
        'behavior.title': 'Behavior presets', 'behavior.description': 'Quickly choose when and how the bot replies. A preset changes behavior, not personality.', 'behavior.custom_preset_placeholder': 'Custom preset name', 'behavior.save_custom': '+ Save current values',
        'behavior.auto_chat': 'Bot may start messages on its own', 'behavior.auto_chat_hint': 'When off, the bot still reads chat and replies to allowed requests.', 'behavior.use_persona': 'Use the bot personality',
        'behavior.silent': 'Quiet mode', 'behavior.silent_hint': 'The bot gathers context, replies less often, and does not speak every message.', 'behavior.cooldown': 'Minimum interval between messages (sec)',
        'behavior.instructions': 'Additional instructions for the bot', 'behavior.instructions_placeholder': 'For example: keep replies short and do not interrupt the streamer', 'behavior.response_length': 'Response length',
        'behavior.short': 'Short (10–15 words)', 'behavior.medium': 'Medium', 'behavior.long': 'Long', 'behavior.save': '💾 Save behavior', 'preset.quiet': 'Quiet', 'preset.friendly': 'Friendly',
        'preset.troll': 'Troll', 'preset.wild': 'Wild', 'preset.spam': 'Spam-laughs', 'preset.observer': 'Observer', 'preset.quiet_desc': 'For calm and serious streams', 'preset.friendly_desc': 'For everyday chat',
        'preset.troll_desc': 'For light teasing without malice', 'preset.wild_desc': 'For hype moments', 'preset.spam_desc': 'When the streamer is joking a lot', 'preset.observer_desc': 'Only observes and does not write',
        'onboarding.eyebrow': 'FIRST RUN', 'onboarding.close': 'Close', 'onboarding.progress': 'Setup progress', 'onboarding.back': 'Back', 'onboarding.skip': 'Skip', 'onboarding.legacy': 'Open the legacy bot form',
    },
    ua: {
        'label.connecting': 'Підключення', 'label.error': 'Помилка',
        'btn.close': 'Закрити',
        'empty.waiting_events': 'Очікування подій...', 'empty.no_bots': 'Ботів немає. Додайте першого в розділі «Боти»!',
        'empty.no_bots_add': 'Ботів немає. Натисніть «+ Додати бота»', 'empty.no_triggers': 'Тригерів немає — додайте!',
        'empty.no_events': 'Подій немає — додайте!', 'empty.no_banned': 'Заблокованих користувачів немає',
        'empty.no_filtered_words': 'Слів у фільтрі немає', 'toast.not_sent_by_bots': 'Не відправлено ботами: {detail}',
        'toast.trigger_updated': 'Тригер оновлено', 'toast.event_added': 'Подію додано',
        'status.runtime': 'AI: {provider}', 'status.ai_paused': ' · призупинено: Ollama недоступна', 'status.ai_paused_short': 'Призупинено: Ollama недоступна', 'status.fallback_enabled': ' · Ollama fallback увімкнено',
        'status.runtime_error': 'Помилка стану: {detail}', 'status.bot_enabled_not_connected': 'Увімкнено (не підключено)',
        'onboarding.next': 'Далі', 'onboarding.done': 'Готово', 'onboarding.complete': 'Початкове налаштування завершено',
        'onboarding.ai_title': 'Підключимо AI', 'onboarding.twitch_title': 'Підключимо Twitch', 'onboarding.tts_title': 'Додамо озвучення', 'onboarding.bot_title': 'Створимо першого бота',
        'onboarding.channel_title': 'Обираємо канал', 'onboarding.obs_title': 'Підключимо OBS', 'onboarding.ai_description': 'Оберіть провайдера. Ключ можна додати зараз або налаштувати пізніше в розділі «Налаштування».',
        'onboarding.twitch_description': 'Client ID і Secret потрібні для даних каналу та OAuth. Можна пропустити, якщо токен бота вже готовий.', 'onboarding.tts_description': 'Налаштуйте голос для повідомлень. Web Speech працює без ключа прямо в браузері.',
        'onboarding.bot_description': 'Введіть імʼя Twitch-акаунта бота та OAuth-токен із правом писати в чат.', 'onboarding.channel_description': 'До якого каналу підключити бота після запуску?',
        'onboarding.obs_description': 'Скопіюйте URL TTS-віджета в OBS як Browser Source. Панель і OBS мають бути на одному компʼютері.', 'onboarding.label_ai_provider': 'AI провайдер',
        'onboarding.label_model': 'Модель', 'onboarding.label_api_key': 'API ключ (необовʼязково)', 'onboarding.label_base_url': 'Base URL для Ollama/Custom', 'onboarding.label_twitch_id': 'Twitch Client ID',
        'onboarding.label_twitch_secret': 'Twitch Client Secret', 'onboarding.label_tts_provider': 'Провайдер TTS', 'onboarding.label_voice': 'Голос (необовʼязково)', 'onboarding.label_tts_key': 'Ключ ElevenLabs (необовʼязково)',
        'onboarding.label_bot_name': 'Нікнейм Twitch', 'onboarding.label_bot_token': 'OAuth токен', 'onboarding.label_channel': 'Назва каналу', 'onboarding.widget_url': 'URL віджета',
        'onboarding.copy_url': 'Копіювати URL', 'onboarding.preview': 'Відкрити превʼю', 'confirm.delete_bots': 'Видалити {count} ботів? Цю дію не можна скасувати.', 'confirm.delete_bot': 'Видалити бота {name}? Цю дію не можна скасувати.',
        'confirm.delete_item': 'Видалити цей елемент?', 'confirm.delete_named': 'Видалити {name}?', 'confirm.clear_logs': 'Очистити всі логи цього бота?', 'confirm.restore_backup': 'Відновити з бекапу? Поточні дані буде перезаписано.',
        'confirm.delete_memory': 'Видалити всю памʼять про {name}?', 'prompt.phrase_name': 'Назва фрази:', 'prompt.phrase_text': 'Текст фрази:', 'prompt.keyword': 'Ключове слово',
        'prompt.fixed_response': 'Фіксована відповідь (порожньо = AI)', 'prompt.edit_fact': 'Змінити факт:', 'prompt.persona': 'Опишіть персонажа коротко (наприклад: «геймер з Одеси, любить Dota 2 і сарказм»):',
        'error.bot_credentials': 'Введіть нікнейм та OAuth-токен', 'error.channel_and_bot': 'Введіть канал і спочатку створіть бота',
        'bot.preset': 'користувацький пресет', 'bot.voice_clone': 'голосовий клон', 'confirm.delete_snippets': 'Видалити {count} заготовок?',
        'behavior.title': 'Пресети поведінки', 'behavior.description': 'Швидкий вибір того, коли і як бот відповідає. Пресет змінює поведінку, а не характер.', 'behavior.custom_preset_placeholder': 'Назва власного пресета', 'behavior.save_custom': '+ Зберегти поточні значення',
        'behavior.auto_chat': 'Бот може сам починати повідомлення', 'behavior.auto_chat_hint': 'Якщо вимкнути, бот продовжить читати чат і відповідати на дозволені звернення.', 'behavior.use_persona': 'Використовувати характер бота',
        'behavior.silent': 'Тихий режим', 'behavior.silent_hint': 'Бот збирає контекст, але відповідає рідше й не озвучує кожне повідомлення.', 'behavior.cooldown': 'Мінімальний інтервал між повідомленнями (сек)',
        'behavior.instructions': 'Додаткові інструкції боту', 'behavior.instructions_placeholder': 'Наприклад: відповідай коротко й не перебивай стримера', 'behavior.response_length': 'Довжина відповіді',
        'behavior.short': 'Коротка (10–15 слів)', 'behavior.medium': 'Середня', 'behavior.long': 'Довга', 'behavior.save': '💾 Зберегти поведінку', 'preset.quiet': 'Тихий', 'preset.friendly': 'Дружній',
        'preset.troll': 'Троль', 'preset.wild': 'Дикий', 'preset.spam': 'Спам-ха-ха', 'preset.observer': 'Спостерігач', 'preset.quiet_desc': 'Для спокійних і серйозних ефірів', 'preset.friendly_desc': 'Для звичайного спілкування',
        'preset.troll_desc': 'Для легких підколів без злоби', 'preset.wild_desc': 'Для хайпових моментів', 'preset.spam_desc': 'Коли стример активно жартує', 'preset.observer_desc': 'Лише спостерігає і не пише',
        'onboarding.eyebrow': 'ПЕРШИЙ ЗАПУСК', 'onboarding.close': 'Закрити', 'onboarding.progress': 'Прогрес налаштування', 'onboarding.back': 'Назад', 'onboarding.skip': 'Пропустити', 'onboarding.legacy': 'Відкрити стару форму додавання бота',
    },
};
Object.entries(DYNAMIC_I18N).forEach(([lang, strings]) => Object.assign(LANGS[lang], strings));

// ── v12 P0: health-индикаторы, причины отправки, триггеры (§5, §10) ──
// Единый список: ключ обязан существовать во всех трёх языках сразу.
Object.entries({
    ru: {
        'health.online': 'Работает', 'health.connecting': 'Подключается...', 'health.error': 'Ошибка',
        'health.reconnects': 'Переподключений: {n}',
        'health.disabled': 'Выключен', 'health.offline': 'Остановлен',
        'health.last_error_at': 'Последняя ошибка: {time}',
        'health.no_reason': 'Причина неизвестна',
        'btn.reconnect': '↻ Переподключить',
        'toast.reconnecting': 'Переподключаю {name}...',
        'toast.bot_started_named': '{name} запускается...',
        'send.reason.bot_disabled': 'бот выключен',
        'send.reason.bot_not_found': 'бот не найден',
        'send.reason.bot_not_connected': 'бот не подключён к чату',
        'send.reason.channel_not_connected': 'бот не подключён к каналу',
        'send.reason.channel_disabled': 'канал отключён',
        'send.reason.no_channel': 'нет канала',
        'send.reason.oauth_expired': 'OAuth-токен истёк',
        'send.reason.cooldown': 'слишком часто (cooldown)',
        'send.reason.moderation_blocked': 'заблокировано модерацией',
        'send.reason.twitch_error': 'ошибка Twitch',
        'send.reason.network_error': 'ошибка сети',
        'send.reason.invalid_target': 'не указан бот или канал',
        'send.reason.empty_message': 'пустое сообщение',
        'send.reason.unknown': 'неизвестная ошибка',
        'send.sent_ok': '✅ отправлено',
        'send.failed_prefix': '❌ не отправлено — {reason}',
        'send.result_title': 'Результат отправки',
        'send.partial_success': 'Частично отправлено: {sent} из {total}',
        'triggers.channel_all': 'Все каналы',
        'triggers.channel_label': 'Канал',
        'triggers.fires': 'Срабатываний: {count}',
        'triggers.last_fired': 'Последний запуск: {time}',
        'triggers.never_fired': 'ещё не запускался',
        'triggers.test': '🧪 Тест',
        'triggers.channel_hint': 'Пусто — триггер работает во всех каналах бота',
        'triggers.test_prompt': 'Введите текст сообщения для проверки триггера:',
        'triggers.test_ok': '✅ Триггер сработал бы ({mode})',
        'triggers.test_ok_ai': 'ответ через AI',
        'triggers.test_ok_fixed': 'фиксированный ответ: {response}',
        'triggers.test_fail': '❌ Не сработал бы: {reason}',
        'triggers.reason.trigger_disabled': 'триггер выключен',
        'triggers.reason.channel_mismatch': 'триггер привязан к другому каналу',
        'triggers.reason.no_keyword_match': 'ключевое слово не найдено в тексте',
        'triggers.reason.not_found': 'триггер не найден',
        'btn.toggle_off': 'Выключить', 'btn.toggle_on': 'Включить', 'btn.edit': 'Изменить',
        'events.chance': 'Шанс: {chance}%', 'events.fixed': 'фиксированный ответ', 'events.ai': 'AI',
        'common.selected': 'Выбрано: {count}',
        'label.selected': '✓ выбран', 'btn.configure': 'Настроить',
        'empty.no_snippets': 'Заготовок нет — добавьте!',
                'widgets.design_theme':'Тема','widgets.design_accent':'Акцент','widgets.design_bg':'Фон','widgets.design_opacity':'Прозрачность','widgets.design_radius':'Скругление','widgets.design_font':'Шрифт','widgets.design_size':'Размер текста','widgets.design_scale':'Масштаб','widgets.design_position':'Позиция','widgets.design_hold':'Показ, сек.','widgets.design_maxw':'Макс. ширина','widgets.design_shadow':'Тень','widgets.design_status':'Статус','widgets.chat_runtime_title':'⭐ Избранный чат','widgets.chat_runtime_hint':'Общий список доверенных пользователей фильтрует настоящий Twitch-чат. Список можно редактировать после импорта.','widgets.chat_trusted_label':'Доверенные логины','widgets.chat_trusted_ph':'friend, moderator_name','widgets.chat_trusted_hint':'По одному логину в строке или через запятую; @ добавлять необязательно.','widgets.chat_import_account':'Аккаунт Twitch','widgets.chat_import_channel':'Канал Twitch','widgets.chat_import_mods':'Импорт модераторов','widgets.chat_import_vips':'Импорт VIP','widgets.chat_import_hint':'Импорт требует broadcaster OAuth с moderation:read или channel:read:vips; существующие логины сохраняются.','widgets.chat_imported':'Добавлено из Twitch: {count}','widgets.chat_import_error_helix_not_configured':'Сначала укажите Twitch Client ID.','widgets.chat_import_error_invalid_token_or_channel':'OAuth-токен или канал не прошёл проверку Twitch.','widgets.chat_import_error_broadcaster_token_required':'Для импорта нужен OAuth владельца выбранного канала.','widgets.chat_import_error_missing_scope':'Переподключите аккаунт с нужными правами импорта.','widgets.chat_import_error_request_failed':'Twitch временно недоступен; повторите позже.','widgets.chat_max_messages':'Сообщений','widgets.chat_lifetime':'Исчезновение, сек.','widgets.chat_font_size':'Размер текста','widgets.chat_emote_size':'Размер смайлов','widgets.chat_history_limit':'Сообщений истории','widgets.chat_history_minutes':'История, минут','widgets.chat_show_badges':'Показывать бейджи','widgets.chat_display_hint':'Ноль секунд оставляет сообщения до заполнения лимита; история ограничивается количеством и временем.','widgets.channel_scope': 'Канал виджетов','widgets.scope_demo': 'демо (без канала)','widgets.admin_title': '🎛 Управление контентом', 'soundboard.title':'🎵 Soundboard','soundboard.hint':'Загрузите аудио, затем нажмите Play или создайте хоткей-биндинг. Звук играет только в OBS Browser Source.','soundboard.upload_label':'Аудиофайлы MP3/WAV/OGG/WebM, до 10 МБ каждый','soundboard.upload':'⬆ Загрузить','soundboard.play':'Play','soundboard.bind':'Бинд','soundboard.stop':'■ Stop','soundboard.name':'Название','soundboard.volume':'Громкость','soundboard.cooldown':'Cooldown, сек','soundboard.order':'Порядок','soundboard.empty':'Треки ещё не загружены','soundboard.file_required':'Выберите аудиофайлы','soundboard.upload_result':'Загружено: {accepted}; отклонено: {rejected}','soundboard.played':'Команда Play отправлена в OBS','soundboard.stopped':'Команда Stop отправлена в OBS','soundboard.delete_confirm':'Удалить трек и его файл? Старый биндинг перестанет работать.','soundboard.bind_ready':'Выберите клавишу и добавьте бинд','soundboard.hotkey':'Хоткей','soundboard.hotkey_hint':'Хоткей (напр. 1, Numpad1, Alt+1) для быстрого запуска','soundboard.hotkey_triggered':'Хоткей сработал',  'widgets.countdown_title': '⏳ Countdown',  'widgets.admin_hint': 'Заполните виджеты контентом прямо здесь — изменения сразу видны в OBS. Рядом с каждой формой — живое превью.',
        'widgets.goal_placeholder': 'Новая цель...', 'widgets.clear_done': 'Убрать выполненные', 'widgets.preview_title': 'Превью виджета',
        'widgets.target': 'Цель', 'widgets.current': 'Сейчас', 'widgets.title_label': 'Заголовок', 'widgets.reset': 'Сброс',
        'widgets.kind': 'Тип', 'widgets.kind_music': 'Музыка', 'widgets.kind_video': 'Видео', 'widgets.kind_game': 'Игра', 'widgets.kind_movie': 'Фильм', 'widgets.kind_custom': 'Другое',
        'widgets.np_title': 'Название', 'widgets.np_sub': 'Автор / деталь',
        'widgets.sch_title': 'Тема эфира', 'widgets.sch_required': 'Укажите время и тему',
        'widgets.counter_key': 'ключ (death)', 'widgets.counter_label': 'подпись (Смерти)',
        'widgets.mode': 'Режим', 'widgets.mode_countdown': 'Обратный отсчёт', 'widgets.mode_stopwatch': 'Секундомер', 'widgets.cd_minutes': 'Минут',
        'widgets.donators': '💰 Топ донатеров', 'widgets.td_period': 'Период', 'widgets.td_alltime': 'Всё время', 'widgets.td_month': 'Месяц', 'widgets.td_day': 'День', 'widgets.don_message': 'Сообщение (необязательно)', 'widgets.don_required': 'Укажите ник и сумму',
        'widgets.songs': '🎧 Song Request', 'widgets.enabled': 'Включён', 'widgets.visible': 'Виден в OBS', 'widgets.song_title': 'Название трека / YouTube',
        'widgets.sr_skip': '⏭ Скип', 'widgets.sr_clear': 'Очистить очередь',
        'song_request.description':'Зрители командой !sr <ссылка или название> добавляют трек в логическую очередь.','song_request.playback_hint':'Song Request сам не запускает YouTube или Spotify. Отдельный Media Share Browser Source автоматически воспроизводит только поддерживаемые YouTube-ссылки; статус playing без него означает лишь текущую позицию очереди.','song_request.cooldown':'Cooldown !sr, сек.','song_request.max_per_user':'Макс. треков на пользователя','song_request.max_queue':'Макс. треков в очереди','song_request.queue_status':'В очереди: {count} · текущий: {current}','song_request.none':'нет','song_request.entitlements_title':'Channel Points и донаты','song_request.entitlements_hint':'Укажите стабильные reward ID. Название используется только как fallback, когда ID не задан. Платные события без уникального event ID отклоняются, автоматический refund недоступен.','song_request.points_create_id':'Reward ID: добавить','song_request.points_create_id_hint':'Создаёт новый запрос из пользовательского ввода reward.','song_request.points_priority_id':'Reward ID: приоритет','song_request.points_priority_id_hint':'Создаёт приоритетный запрос или повышает совпавший активный.','song_request.points_create_title':'Fallback-название: добавить','song_request.points_priority_title':'Fallback-название: приоритет','song_request.points_title_hint':'Используется только если соответствующий reward ID пуст.','song_request.donation_enabled':'Заказы за донаты','song_request.donation_threshold':'Минимальная сумма','song_request.donation_threshold_hint':'Событие принимается только от этой суммы включительно.','song_request.donation_currency':'Валюта','song_request.donation_currency_hint':'Точное совпадение кода валюты, без конвертации.','song_request.donation_action':'Действие доната','song_request.donation_action_hint':'Название трека берётся из сообщения доната.','song_request.action_create':'Добавить запрос','song_request.action_priority':'Добавить / повысить приоритет','song_request.audit_title':'Журнал запросов','song_request.audit_hint':'Accepted означает добавление или повышение приоритета, а не подтверждённое воспроизведение.','song_request.audit_empty':'Записей пока нет','song_request.accepted':'Принято','song_request.rejected':'Отклонено','song_request.reason.accepted':'добавлено','song_request.reason.priority_boosted':'приоритет повышен','song_request.reason.empty_request':'пустой запрос','song_request.reason.request_too_long':'слишком длинный запрос','song_request.reason.control_characters':'недопустимые символы','song_request.reason.unsafe_url':'опасная ссылка','song_request.reason.duplicate_request':'дубликат','song_request.reason.queue_full':'очередь заполнена','song_request.reason.user_limit':'лимит пользователя','song_request.reason.cooldown':'cooldown','song_request.reason.disabled':'очередь выключена','song_request.reason.missing_event_id':'нет event ID','song_request.reason.currency_mismatch':'другая валюта','song_request.reason.below_threshold':'сумма ниже порога','song_request.reason.internal_error':'внутренняя ошибка',
        'widgets.no_goals': 'Целей пока нет', 'widgets.no_schedule': 'Расписание пустое', 'widgets.no_counters': 'Счётчиков нет',
        'widgets.no_donations': 'Донатов пока нет', 'widgets.no_songs': 'Очередь пуста',
                'oauth.login_btn': 'Войти через Twitch', 'oauth.or_manual': 'или введите токен вручную ниже',
        'oauth.enter_code': 'Откройте ссылку и введите код:', 'oauth.waiting': 'Ожидание подтверждения...',
        'oauth.cancel': 'Отменить вход', 'oauth.done': 'Вход выполнен! Бот добавлен.',
        'actionlog.title': '🕘 Журнал действий', 'actionlog.description': 'Что происходило в панели. Кнопка «↩ Отменить» у записи откатывает действие (например, удаляет созданного бота). Записи без кнопки отката не имеют — это информация о событии.',
        'actionlog.all_actions': 'Все типы', 'actionlog.all_actors': 'Все акторы', 'actionlog.search': 'Поиск...',
        'actionlog.prev': '← Раньше', 'actionlog.next': 'Позже →', 'actionlog.empty': 'Записей нет',
        'actionlog.revert': '↩ Отменить', 'actionlog.reverted': 'Действие отменено', 'btn.search': 'Найти',
        'chat.channel_of': 'Канал', 'chat.add_channel_hint': 'У бота нет каналов — добавьте на вкладке «Каналы»', 'btn.configure_short': 'Настроить', 'chat.pick_search': 'Поиск канала или бота...', 'chat.pick_empty': 'Каналов не найдено',
        'chat.pick_manual_label': 'Или впишите канал вручную', 'chat.pick_manual_ph': 'имя канала', 'chat.pick_manual_use': 'Выбрать',
                'cp.none': 'Провайдеров пока нет — добавьте первого', 'cp.models_word': 'мод.',
        'cp.name_ph': 'Имя (myproxy)', 'cp.url_ph': 'https://api.example.com/v1', 'cp.key_ph': 'API-ключ (пусто = не менять)',
        'cp.key_set': 'ключ задан (введите новый, чтобы заменить)',
        'cp.name_required': 'Укажите имя провайдера',
        'cp.created': 'Провайдер добавлен', 'cp.updated': 'Провайдер обновлён', 'cp.deleted': 'Провайдер удалён',
        'cp.add': '+ Добавить провайдера', 'cp.update': '💾 Сохранить изменения',
        'cp.add_model': '＋ Модель', 'cp.model_name_ph': 'имя модели',
        'cp.model_type': 'Тип модели', 'cp.type_chat': 'чат', 'cp.type_vision': 'vision', 'cp.type_both': 'чат+vision',
        'cp.no_models': 'Моделей пока нет — добавьте первую',
        'cp.models_types_hint': 'Один список моделей: пометьте каждую как чат, vision или обе. Модель не добавляется дважды — не нужно вписывать её отдельно для vision.',
        'bot.model_default': 'По умолчанию (первая модель провайдера)',
        'bot.vision_default': 'По умолчанию (первая vision-модель провайдера)',
        'vision.testing': 'Проверяю vision...', 'vision.test_ok': 'Vision работает: {detail}',
                'mood.title': '🎭 Настроение стримера', 'mood.waiting': 'Появится, когда боты услышат стримера',
                'sharedfacts.title': '🌐 Общие факты (все боты)', 'sharedfacts.decay': '🧹 Затухание старых',
        'sharedfacts.description': 'Факты, которые боты узнали о зрителях, — общие для всех ботов панели. Confidence — уверенность (0–1), старые факты затухают.',
        'sharedfacts.fact_ph': 'Факт о зрителе', 'sharedfacts.empty': 'Введите ник, чтобы посмотреть факты',
        'sharedfacts.no_facts': 'Фактов о юзере пока нет', 'sharedfacts.confidence': 'Уверенность',
        'sharedfacts.required': 'Укажите ник и факт', 'sharedfacts.added': 'Факт добавлен',
        'sharedfacts.decayed': 'Удалено затуханием: {detail}',
        'feedback.saved': 'Спасибо за оценку!', 'feedback.total': 'всего оценок: {count}',
                'analytics.feedback_title': '👍 Оценки ответов', 'analytics.feedback_hint': 'Оцените ответ бота кнопками 👍/👎 во вкладке «Чат» — здесь появится сводка.',
        'nav.brain': '🧠 Мозг', 'title.brain': 'Мозг бота',
                'bot.quick_title': '⚡ Быстрые настройки',
        'mood.title': '😊 Настроение стримера', 'mood.hint': 'Оценка тона голоса стримера (из Stream Vision). Обновляется автоматически во время стрима.',
        'clips.title': '🎬 Клипы (всплески чата)', 'clips.check': 'Проверить всплеск', 'clips.create': '✂ Создать клип',
        'clips.hint': 'Когда чат резко ускоряется (хайп-момент) — бот предложит момент для клипа. «Создать клип» режет последние 30 секунд через Twitch.',
        'clips.spike_yes': 'Всплеск detected!', 'clips.spike_no': 'Всплеска сейчас нет',
        'clips.created': 'Клип создан: {detail}', 'clips.open': 'открыть', 'clips.no_moments': 'Моментов пока нет',
        'replay.title': '⏺ Запись сессий', 'replay.start': '⏺ Начать запись', 'replay.stop': '⏹ Закончить',
        'replay.hint': 'Записывает чат и ответы бота этой сессии в архив — потом можно просмотреть.',
        'replay.messages': 'сообщений', 'replay.empty': 'Записей пока нет',
        'replay.started': 'Запись начата', 'replay.ended': 'Запись закончена', 'replay.none_active': 'Активной записи нет',
        'brain.intro': 'Память стримера (Lore), обучение, сводки стрима и временные сдвиги настроения. Всё применяется только после подтверждения.',
        'brain.lore_hint': 'Lore — факты о стримере, которые бот помнит и учитывает в ответах: добавленные вручную и предложенные Summarizer/анализом чата. В список попадают только после подтверждения ✓. Скоуп: «все каналы» или конкретный канал.',
        'brain.importance': 'Важность 0–100',
        'brain.fact_source': 'Источник факта',
        'brain.src.manual': 'manual — добавил ты',
        'brain.src.summary': 'summary — из сводок',
        'brain.src.chat': 'chat — из чата',
        'brain.learning_hint': 'Предложения бота по улучшению стиля и базы знаний — из фидбека 👍/👎 и анализа чата. «Применить» меняет поведение бота, «Отменить» откатывает последнее применённое.',
        'brain.summary_hint': 'Отчёты «как прошёл стрим» по истории чата: ручной прогон за выбранный период и live-сводки каждые 30 минут (ниже — включение и per-канальные настройки). Сводки питают Lore фактами.',
        'brain.shift_hint': 'Временный сдвиг настроения бота: «мягкий» — чуть больше сарказма/энергии, «сильный» — заметная смена характера. Действует ограниченное время и сам гаснет. Настраивается на выбранный скоуп.',
        'brain.memory_hint': 'Что бот запомнил о зрителях. Подтверждённый факт (✓✓) живёт дольше и чаще используется; ✎ правит приоритет и срок. Прогонов не было — факты появятся, когда Summarizer/чат-анализ найдут что запомнить.',
        'brain.runs_empty': 'Прогонов ещё не было. Нажми ▶ «Прогнать стрим» (отчёт за выбранный период) или включи Live-сводки ниже — они пишутся сами каждые 30 минут, пока идёт стрим.',
        'brain.memory_empty': 'Память пуста. Факты появятся, когда бот накопит их из чата (Summarizer/анализатор). Хочешь быстрее — нажми 🤖 «Извлечь факты»: предложения придут в Lore, а после подтверждения ✓ — в память.',
        'brain.profile_title': '👤 Профиль стримера',
        'brain.profile_hint': 'Кто стример: возраст, био, стиль, любимые игры. Глобальный профиль работает на всех каналах; для отдельного канала можно задать свой. Редактор тот же, что в Настройках — изменения видны в обоих местах.',
                'btn.test_vision': '👁 Проверить vision',
        'settings.custom_providers': '🧩 Кастомные провайдеры',
        'settings.custom_providers_hint': 'Свои API-провайдеры (OpenAI-совместимые): дайте имя, укажите Base URL и ключ, добавьте модели кнопкой «＋ Модель». Потом выберите их в «AI Провайдер» выше и в настройках каждого бота.',
        'settings.vision_hint': 'Vision — модель, которая смотрит картинки стрима. Это общая база: её берут боты с режимом «Общая» (по умолчанию); бот с режимом «Своя» использует свою модель. Подсказки: OpenRouter → google/gemini-2.0-flash:free · Ollama (локально, бесплатно) → llava или minicpm-v (ollama pull llava) · именованный провайдер (🧩) → его модель с поддержкой картинок.',
        'toast.saved': 'Сохранено', 'toast.deleted': 'Удалено',
        'logs.empty_hint': 'Логов нет — они появятся, когда боты начнут читать чат и отвечать',
                'faq.q5': 'Как добавить бота без ручного токена?', 'faq.a5': 'В форме добавления бота нажмите «🟣 Войти через Twitch»: откройте twitch.tv/activate, введите код — бот добавится сам. Нужен Twitch API (Client ID/Secret) в настройках; без них — ручной токен.',
        'faq.q6': 'Как бот узнаёт стримера?', 'faq.a6': 'Боты → Настроить → «👤 О стримере»: профиль (био, стиль, интересы) + фото для распознавания в кадре. Автообновление — AI сам дополнит профиль из чата.',
        'faq.q7': 'Что бот видит и слышит со стрима?', 'faq.a7': 'Stream Vision: кадры стрима + Whisper-транскрипция аудио. Vision-модель задаётся в AI-настройках. Локально — Ollama: модель llava или minicpm-v как Vision-модель.',
        'faq.q8': 'Как запускать ботов на разных API/моделях?', 'faq.a8': 'Боты → Настроить → Обзор → AI Override: свой провайдер, модели и ключ. Без override — глобальные настройки.',
        'faq.q9': 'Бот включён, но не подключён — что делать?', 'faq.a9': 'Карточка бота: жёлтый «Подключается», красный «Ошибка» с причиной и временем; кнопка «↻ Переподключить». Частые причины: неверный/истёкший OAuth-токен, недоступен Twitch (проверьте прокси).',
        'faq.q10': 'Как откатить действие в панели?', 'faq.a10': 'Настройки → «🕘 Журнал действий»: у записей с «↩ Отменить» доступен откат. Нет кнопки — запись только для информации.',
        'faq.q11': 'Где смотреть логи бота?', 'faq.a11': 'Боты → Настроить → Дополнительно → Логи (фильтры, экспорт CSV). Общий поток — Статистика → «📋 Логи ботов». Логи появляются, когда боты читают чат и отвечают.',
        'faq.q12': 'Как сделать резервную копию?', 'faq.a12': 'Настройки → «💾 Резервная копия»: скачайте архив (включая .env), восстановите кнопкой «Восстановить» — текущие данные будут перезаписаны.',
        'faq.q13': 'Как работает доступ к панели?', 'faq.a13': 'На localhost пароль не нужен. Для явного доступа из LAN или сети задайте PANEL_AUTH_USER, PANEL_AUTH_PASS и TOKEN_ENCRYPTION_KEY; без полного набора панель остаётся на 127.0.0.1.',
        'faq.q14': 'Как подключить виджеты в OBS?', 'faq.a14': 'Вкладка «Виджеты» → заполните контент → скопируйте URL → Browser Source в OBS. Файлы виджетов в папке widgets/ правятся без панели (widgets/README.md).',
        'settings.twitch_api': '🟣 Twitch API',
        'settings.twitch_api_what': 'Что это даёт панели:',
        'settings.twitch_api_use1': 'Вход ботов через Twitch (кнопка «Войти через Twitch» без ручного токена)',
        'settings.twitch_api_use2': 'Информация о каналах: игра, название стрима, зрители',
        'settings.twitch_api_use3': 'Автообновление профиля стримера (вкладка «О стримере»)',
        'settings.twitch_api_use4': 'События Twitch (follow/sub/raid/cheer) через EventSub',
        'settings.twitch_api_how': 'Без ключей панель работает, но эти функции недоступны. Создайте приложение на dev.twitch.tv/console → Apps → New Application и вставьте Client ID и Client Secret сюда.',
                'btn.leave': '↪ Выйти', 'empty.no_channels': 'Каналов нет — добавьте первый',
        'channels.info_loading': 'Загружаю информацию о канале...', 'channels.info_btn': 'Информация о канале',
        'channels.info_failed': 'Не удалось получить информацию (нужен TWITCH_CLIENT_ID/SECRET в .env)',
        'channels.last_message': 'последнее сообщение', 'channels.overrides_btn': 'Per-channel overrides',
                'analytics.heatmap_title': '🔥 Активность чата (день × час)', 'analytics.heatmap_legend': 'Меньше', 'analytics.heatmap_legend_more': 'Больше',
        'analytics.trending_title': '📈 Растущие и угасающие темы', 'analytics.trend_hour': 'За час', 'analytics.trend_day': 'За день',
        'analytics.trending': 'Растут', 'analytics.cooling': 'Угасают', 'analytics.hour24_title': '💬 Сообщения за 24 часа',
        'analytics.top_chatters': '👑 Топ чатеров', 'analytics.perbot_title': '🤖 Статистика бота',
                'streamer.title': '👤 О стримере', 'streamer.description': 'Помогает боту знать, кто ведёт стрим: био, стиль, интересы. Бот использует это в ответах.',
        'streamer.auto_updated': 'Автообновление профиля через AI',
        'streamer.empty': 'Профиль стримера ещё не заполнен', 'streamer.fill_now': 'Заполнить сейчас',
        'streamer.age': 'Возраст', 'streamer.gender': 'Пол', 'streamer.location': 'Локация',
        'streamer.occupation': 'Род занятий', 'streamer.bio': 'Био стримера',
        'streamer.bio_placeholder': 'Короткое описание: кто он, чем занимается, чем известен',
        'streamer.gender_placeholder': 'мужской / женский',
        'streamer.style': 'Стиль стрима', 'streamer.style_none': 'Не указан',
        'streamer.style_edu': 'Обучающий', 'streamer.style_fun': 'Развлекательный', 'streamer.style_comp': 'Соревновательный',
        'streamer.interests': 'Интересы (через запятую)', 'streamer.games': 'Любимые игры (через запятую)',
        'streamer.likes': 'Нравится (через запятую)', 'streamer.dislikes': 'Не нравится (через запятую)',
        'streamer.save': '💾 Сохранить профиль', 'streamer.saved': 'Профиль стримера сохранён',
        'streamer.face_title': '📷 Фото стримера', 'streamer.face_desc': 'Фото помогает AI с vision узнавать стримера в кадре и не путать его со зрителями. Используется только локально и передаётся лишь настроенному AI-провайдеру.',
        'streamer.face_none': 'Нет фото', 'streamer.face_delete': '🗑 Удалить фото',
        'streamer.face_uploaded': 'Фото загружено', 'streamer.face_deleted': 'Фото удалено',
        'streamer.face_invalid': 'Файл должен быть JPEG/PNG до 2 МБ',
        'streamer.channel_hint': 'Один профиль на бота — применяется ко всем его каналам: {channels}. Для разных стримеров на разных каналах создайте отдельного бота.',
        'streamer.channel_hint_none': 'Один профиль на бота. У бота пока нет каналов — профиль будет применён к первому подключённому.',
        'empty.load_failed': 'Ошибка загрузки: {detail}',
    },
    en: {
        'health.online': 'Working', 'health.connecting': 'Connecting...', 'health.error': 'Error',
        'health.reconnects': 'Reconnects: {n}',
        'health.disabled': 'Disabled', 'health.offline': 'Stopped',
        'health.last_error_at': 'Last error: {time}',
        'health.no_reason': 'Unknown reason',
        'btn.reconnect': '↻ Reconnect',
        'toast.reconnecting': 'Reconnecting {name}...',
        'toast.bot_started_named': '{name} is starting...',
        'send.reason.bot_disabled': 'bot is disabled',
        'send.reason.bot_not_found': 'bot not found',
        'send.reason.bot_not_connected': 'bot is not connected to chat',
        'send.reason.channel_not_connected': 'bot is not connected to the channel',
        'send.reason.channel_disabled': 'channel is disabled',
        'send.reason.no_channel': 'no channel',
        'send.reason.oauth_expired': 'OAuth token expired',
        'send.reason.cooldown': 'too frequent (cooldown)',
        'send.reason.moderation_blocked': 'blocked by moderation',
        'send.reason.twitch_error': 'Twitch error',
        'send.reason.network_error': 'network error',
        'send.reason.invalid_target': 'no bot or channel specified',
        'send.reason.empty_message': 'empty message',
        'send.reason.unknown': 'unknown error',
        'send.sent_ok': '✅ sent',
        'send.failed_prefix': '❌ not sent — {reason}',
        'send.result_title': 'Send result',
        'send.partial_success': 'Partially sent: {sent} of {total}',
        'triggers.channel_all': 'All channels',
        'triggers.channel_label': 'Channel',
        'triggers.fires': 'Fires: {count}',
        'triggers.last_fired': 'Last fired: {time}',
        'triggers.never_fired': 'never fired yet',
        'triggers.test': '🧪 Test',
        'triggers.channel_hint': 'Empty — the trigger works in all bot channels',
        'triggers.test_prompt': 'Enter a chat message to test the trigger against:',
        'triggers.test_ok': '✅ Trigger would fire ({mode})',
        'triggers.test_ok_ai': 'AI reply',
        'triggers.test_ok_fixed': 'fixed reply: {response}',
        'triggers.test_fail': '❌ Would not fire: {reason}',
        'triggers.reason.trigger_disabled': 'trigger is disabled',
        'triggers.reason.channel_mismatch': 'trigger is bound to another channel',
        'triggers.reason.no_keyword_match': 'keyword not found in the text',
        'triggers.reason.not_found': 'trigger not found',
        'btn.toggle_off': 'Disable', 'btn.toggle_on': 'Enable', 'btn.edit': 'Edit',
        'events.chance': 'Chance: {chance}%', 'events.fixed': 'fixed reply', 'events.ai': 'AI',
        'common.selected': 'Selected: {count}',
        'label.selected': '✓ selected', 'btn.configure': 'Configure',
        'empty.no_snippets': 'No snippets yet — add one!',
                'widgets.design_theme':'Theme','widgets.design_accent':'Accent','widgets.design_bg':'Background','widgets.design_opacity':'Opacity','widgets.design_radius':'Corner radius','widgets.design_font':'Font','widgets.design_size':'Text size','widgets.design_scale':'Scale','widgets.design_position':'Position','widgets.design_hold':'Display, sec.','widgets.design_maxw':'Max width','widgets.design_shadow':'Shadow','widgets.design_status':'Status','widgets.chat_runtime_title':'⭐ Selected chat','widgets.chat_runtime_hint':'A shared trusted-user list filters real Twitch chat. You can edit the list after importing.','widgets.chat_trusted_label':'Trusted logins','widgets.chat_trusted_ph':'friend, moderator_name','widgets.chat_trusted_hint':'Use one login per line or separate them with commas; @ is optional.','widgets.chat_import_account':'Twitch account','widgets.chat_import_channel':'Twitch channel','widgets.chat_import_mods':'Import moderators','widgets.chat_import_vips':'Import VIPs','widgets.chat_import_hint':'Import requires broadcaster OAuth with moderation:read or channel:read:vips; existing logins are kept.','widgets.chat_imported':'Added from Twitch: {count}','widgets.chat_import_error_helix_not_configured':'Set the Twitch Client ID first.','widgets.chat_import_error_invalid_token_or_channel':'Twitch could not validate the OAuth token or channel.','widgets.chat_import_error_broadcaster_token_required':'Import requires OAuth from the selected channel owner.','widgets.chat_import_error_missing_scope':'Reconnect the account with the required import permissions.','widgets.chat_import_error_request_failed':'Twitch is temporarily unavailable; try again later.','widgets.chat_max_messages':'Messages','widgets.chat_lifetime':'Disappear after, sec.','widgets.chat_font_size':'Text size','widgets.chat_emote_size':'Emote size','widgets.chat_history_limit':'History messages','widgets.chat_history_minutes':'History, minutes','widgets.chat_show_badges':'Show badges','widgets.chat_display_hint':'Zero seconds keeps messages until the limit is reached; history is limited by count and time.','widgets.channel_scope': 'Widget channel','widgets.scope_demo': 'demo (no channel)','widgets.admin_title': '🎛 Widget content management', 'soundboard.title':'🎵 Soundboard','soundboard.hint':'Upload audio, then press Play or create a hotkey binding. Audio plays only in the OBS Browser Source.','soundboard.upload_label':'MP3/WAV/OGG/WebM audio files, up to 10 MB each','soundboard.upload':'⬆ Upload','soundboard.play':'Play','soundboard.bind':'Bind','soundboard.stop':'■ Stop','soundboard.name':'Name','soundboard.volume':'Volume','soundboard.cooldown':'Cooldown, sec','soundboard.order':'Order','soundboard.empty':'No tracks uploaded yet','soundboard.file_required':'Choose audio files','soundboard.upload_result':'Uploaded: {accepted}; rejected: {rejected}','soundboard.played':'Play command sent to OBS','soundboard.stopped':'Stop command sent to OBS','soundboard.delete_confirm':'Delete the track and its file? Its old binding will stop working.','soundboard.bind_ready':'Choose a key and add the binding','soundboard.hotkey':'Hotkey','soundboard.hotkey_hint':'Hotkey (e.g. 1, Numpad1, Alt+1) for quick trigger','soundboard.hotkey_triggered':'Hotkey triggered',  'widgets.countdown_title': '⏳ Countdown',  'widgets.admin_hint': 'Fill widget content right here — changes appear in OBS immediately. Each form has a live preview.',
        'widgets.goal_placeholder': 'New goal...', 'widgets.clear_done': 'Clear completed', 'widgets.preview_title': 'Widget preview',
        'widgets.target': 'Target', 'widgets.current': 'Current', 'widgets.title_label': 'Title', 'widgets.reset': 'Reset',
        'widgets.kind': 'Kind', 'widgets.kind_music': 'Music', 'widgets.kind_video': 'Video', 'widgets.kind_game': 'Game', 'widgets.kind_movie': 'Movie', 'widgets.kind_custom': 'Other',
        'widgets.np_title': 'Title', 'widgets.np_sub': 'Author / detail',
        'widgets.sch_title': 'Stream topic', 'widgets.sch_required': 'Specify time and topic',
        'widgets.counter_key': 'key (death)', 'widgets.counter_label': 'label (Deaths)',
        'widgets.mode': 'Mode', 'widgets.mode_countdown': 'Countdown', 'widgets.mode_stopwatch': 'Stopwatch', 'widgets.cd_minutes': 'Minutes',
        'widgets.donators': '💰 Top donators', 'widgets.td_period': 'Period', 'widgets.td_alltime': 'All time', 'widgets.td_month': 'Month', 'widgets.td_day': 'Day', 'widgets.don_message': 'Message (optional)', 'widgets.don_required': 'Specify nickname and amount',
        'widgets.songs': '🎧 Song Request', 'widgets.enabled': 'Enabled', 'widgets.visible': 'Visible in OBS', 'widgets.song_title': 'Track title / YouTube',
        'widgets.sr_skip': '⏭ Skip', 'widgets.sr_clear': 'Clear queue',
        'song_request.description':'Viewers use !sr <link or title> to add a track to the logical queue.','song_request.playback_hint':'Song Request does not start YouTube or Spotify by itself. The separate Media Share Browser Source autoplays supported YouTube links only; without it, playing is only the current queue position.','song_request.cooldown':'!sr cooldown, sec.','song_request.max_per_user':'Max tracks per user','song_request.max_queue':'Max queued tracks','song_request.queue_status':'Queued: {count} · current: {current}','song_request.none':'none','song_request.entitlements_title':'Channel Points and donations','song_request.entitlements_hint':'Use stable reward IDs. Title is a fallback only when no ID is set. Paid events without a unique event ID are rejected; automatic refunds are unavailable.','song_request.points_create_id':'Reward ID: add','song_request.points_create_id_hint':'Creates a request from the reward user input.','song_request.points_priority_id':'Reward ID: priority','song_request.points_priority_id_hint':'Creates a priority request or boosts a matching active item.','song_request.points_create_title':'Fallback title: add','song_request.points_priority_title':'Fallback title: priority','song_request.points_title_hint':'Used only when the matching reward ID is empty.','song_request.donation_enabled':'Donation requests','song_request.donation_threshold':'Minimum amount','song_request.donation_threshold_hint':'The event is accepted at or above this amount.','song_request.donation_currency':'Currency','song_request.donation_currency_hint':'Exact currency-code match; no conversion.','song_request.donation_action':'Donation action','song_request.donation_action_hint':'The track title is read from the donation message.','song_request.action_create':'Add request','song_request.action_priority':'Add / boost priority','song_request.audit_title':'Request journal','song_request.audit_hint':'Accepted means queued or boosted, not confirmed playback.','song_request.audit_empty':'No entries yet','song_request.accepted':'Accepted','song_request.rejected':'Rejected','song_request.reason.accepted':'added','song_request.reason.priority_boosted':'priority boosted','song_request.reason.empty_request':'empty request','song_request.reason.request_too_long':'request too long','song_request.reason.control_characters':'invalid characters','song_request.reason.unsafe_url':'unsafe URL','song_request.reason.duplicate_request':'duplicate','song_request.reason.queue_full':'queue full','song_request.reason.user_limit':'user limit','song_request.reason.cooldown':'cooldown','song_request.reason.disabled':'queue disabled','song_request.reason.missing_event_id':'missing event ID','song_request.reason.currency_mismatch':'currency mismatch','song_request.reason.below_threshold':'below threshold','song_request.reason.internal_error':'internal error',
        'widgets.no_goals': 'No goals yet', 'widgets.no_schedule': 'Schedule is empty', 'widgets.no_counters': 'No counters',
        'widgets.no_donations': 'No donations yet', 'widgets.no_songs': 'Queue is empty',
                'oauth.login_btn': 'Sign in with Twitch', 'oauth.or_manual': 'or enter a token manually below',
        'oauth.enter_code': 'Open the link and enter the code:', 'oauth.waiting': 'Waiting for confirmation...',
        'oauth.cancel': 'Cancel sign-in', 'oauth.done': 'Signed in! Bot added.',
        'actionlog.title': '🕘 Action log', 'actionlog.description': 'What happened in the panel. The “↩ Revert” button on an entry undoes that action (e.g. removes a created bot). Entries without the button cannot be reverted — they are informational.',
        'actionlog.all_actions': 'All types', 'actionlog.all_actors': 'All actors', 'actionlog.search': 'Search...',
        'actionlog.prev': '← Older', 'actionlog.next': 'Newer →', 'actionlog.empty': 'No entries',
        'actionlog.revert': '↩ Revert', 'actionlog.reverted': 'Action reverted', 'btn.search': 'Search',
        'chat.channel_of': 'Channel', 'btn.configure_short': 'Configure', 'chat.add_channel_hint': 'This bot has no channels — add one in the Channels tab', 'chat.pick_search': 'Search channel or bot...', 'chat.pick_empty': 'No channels found',
        'chat.pick_manual_label': 'Or type a channel manually', 'chat.pick_manual_ph': 'channel name', 'chat.pick_manual_use': 'Use',
                'cp.none': 'No providers yet — add the first one', 'cp.models_word': 'models',
        'cp.name_ph': 'Name (myproxy)', 'cp.url_ph': 'https://api.example.com/v1', 'cp.key_ph': 'API key (empty = keep)',
        'cp.key_set': 'key set (enter a new one to replace)',
        'cp.name_required': 'Specify the provider name',
        'cp.created': 'Provider added', 'cp.updated': 'Provider updated', 'cp.deleted': 'Provider deleted',
        'cp.add': '+ Add provider', 'cp.update': '💾 Save changes',
        'cp.add_model': '＋ Model', 'cp.model_name_ph': 'model name',
        'cp.model_type': 'Model type', 'cp.type_chat': 'chat', 'cp.type_vision': 'vision', 'cp.type_both': 'chat+vision',
        'cp.no_models': 'No models yet — add the first one',
        'cp.models_types_hint': 'One model list: mark each as chat, vision, or both. A model is never added twice — no separate entry for vision.',
        'bot.model_default': 'Default (first provider model)',
        'bot.vision_default': 'Default (first provider vision model)',
        'vision.testing': 'Testing vision...', 'vision.test_ok': 'Vision works: {detail}',
                'mood.title': '🎭 Streamer mood', 'mood.waiting': 'Appears when bots hear the streamer',
                'sharedfacts.title': '🌐 Shared facts (all bots)', 'sharedfacts.decay': '🧹 Decay old ones',
        'sharedfacts.description': 'Facts the bots learned about viewers — shared across all bots. Confidence (0–1); old facts decay over time.',
        'sharedfacts.fact_ph': 'Fact about the viewer', 'sharedfacts.empty': 'Enter a nickname to see facts',
        'sharedfacts.no_facts': 'No facts about this user yet', 'sharedfacts.confidence': 'Confidence',
        'sharedfacts.required': 'Specify nickname and fact', 'sharedfacts.added': 'Fact added',
        'sharedfacts.decayed': 'Removed by decay: {detail}',
        'feedback.saved': 'Thanks for the rating!', 'feedback.total': 'total ratings: {count}',
                'analytics.feedback_title': '👍 Reply ratings', 'analytics.feedback_hint': 'Rate a bot reply with 👍/👎 in the Chat tab — the summary appears here.',
        'nav.brain': '🧠 Brain', 'title.brain': 'Bot brain',
                'bot.quick_title': '⚡ Quick settings',
        'mood.title': '😊 Streamer mood', 'mood.hint': 'Stream speaker tone estimate (from Stream Vision). Updates automatically during the stream.',
        'clips.title': '🎬 Clips (chat spikes)', 'clips.check': 'Check spike', 'clips.create': '✂ Create clip',
        'clips.hint': 'When chat suddenly speeds up (hype moment) the bot flags a clip moment. “Create clip” cuts the last 30 seconds via Twitch.',
        'clips.spike_yes': 'Spike detected!', 'clips.spike_no': 'No spike right now',
        'clips.created': 'Clip created: {detail}', 'clips.open': 'open', 'clips.no_moments': 'No moments yet',
        'replay.title': '⏺ Session recording', 'replay.start': '⏺ Start recording', 'replay.stop': '⏹ Stop',
        'replay.hint': 'Records this session’s chat and bot replies into an archive you can review later.',
        'replay.messages': 'messages', 'replay.empty': 'No recordings yet',
        'replay.started': 'Recording started', 'replay.ended': 'Recording stopped', 'replay.none_active': 'No active recording',
        'brain.intro': 'Streamer memory (Lore), learning, stream summaries and temporary mood shifts. Everything is applied only after approval.',
        'brain.lore_hint': 'Lore — facts about the streamer the bot remembers and uses in replies: added manually or suggested by the Summarizer/chat analysis. They appear in the list only after approval ✓. Scope: "all channels" or a specific one.',
        'brain.importance': 'Importance 0–100',
        'brain.fact_source': 'Fact source',
        'brain.src.manual': 'manual — added by you',
        'brain.src.summary': 'summary — from stream digests',
        'brain.src.chat': 'chat — from chat',
        'brain.learning_hint': "Bot's own suggestions for style and knowledge base — from 👍/👎 feedback and chat analysis. 'Apply' changes bot behavior, 'Undo last' reverts the last applied change.",
        'brain.summary_hint': '"How the stream went" reports from chat history: a manual run over a period, plus live summaries every 30 minutes (enable and per-channel settings below). Summaries feed Lore with facts.',
        'brain.shift_hint': 'A temporary mood shift: "soft" — a bit more sarcasm/energy, "strong" — a noticeable character change. It expires on its own. Applied to the selected scope.',
        'brain.memory_hint': "What the bot remembered about viewers. A confirmed fact (✓✓) lives longer and is used more; ✎ edits priority and expiry. No runs yet — facts appear when the Summarizer/chat analysis finds something.",
        'brain.runs_empty': 'No runs yet. Hit ▶ "Run stream" (a report for a chosen period) or enable Live summaries below — they are written automatically every 30 minutes while the stream is live.',
        'brain.memory_empty': 'Memory is empty. Facts appear as the bot picks them up from chat (Summarizer/analyzer). Want them faster — press 🤖 "Extract facts": suggestions go to Lore, and after ✓ approval — into memory.',
        'brain.profile_title': '👤 Streamer profile',
        'brain.profile_hint': 'Who the streamer is: age, bio, style, favorite games. The global profile works on all channels; a specific channel can have its own. Same editor as in Settings — changes are visible in both places.',
                'btn.test_vision': '👁 Test vision',
        'settings.custom_providers': '🧩 Custom providers',
        'settings.custom_providers_hint': 'Your own OpenAI-compatible API providers: give a name, set the Base URL and key, add models with the “＋ Model” button. Then pick them in the “AI Provider” selector above and in each bot’s settings.',
        'settings.vision_hint': 'Vision — the model that looks at stream images. This is the shared base: bots in “Shared” mode (default) use it; a bot in “Own” mode uses its own model. Hints: OpenRouter → google/gemini-2.0-flash:free · Ollama (local, free) → llava or minicpm-v (ollama pull llava) · a named provider (🧩) → its image-capable model.',
        'toast.saved': 'Saved', 'toast.deleted': 'Deleted',
        'logs.empty_hint': 'No logs yet — they appear when bots start reading chat and replying',
                'faq.q5': 'How to add a bot without a manual token?', 'faq.a5': 'In the add-bot form click “🟣 Sign in with Twitch”: open twitch.tv/activate, enter the code — the bot is added automatically. Requires Twitch API (Client ID/Secret) in settings; otherwise use a manual token from twitchtokengenerator.com.',
        'faq.q6': 'How does the bot learn about the streamer?', 'faq.a6': 'Bots → Configure → “👤 About the streamer”: fill the profile (bio, style, interests) and upload a photo for on-camera recognition. Auto-update lets AI extend the profile from chat.',
        'faq.q7': 'What does the bot see and hear from the stream?', 'faq.a7': 'Stream Vision: the bot periodically looks at stream frames and listens to audio (Whisper transcription). The Vision model is set in AI settings. Locally and free — Ollama: install llava or minicpm-v and pick it as the Vision model.',
        'faq.q8': 'How to run bots on different APIs/models?', 'faq.a8': 'Bots → Configure → Overview → AI Override: pick your own provider, text/vision models and API key. Without override the bot uses global settings.',
        'faq.q9': 'Bot is enabled but not connected — what to do?', 'faq.a9': 'The bot card shows a health indicator: yellow “Connecting”, red “Error” with reason and time; press “↻ Reconnect”. Common causes: invalid or expired OAuth token, Twitch unreachable (check proxy).',
        'faq.q10': 'How to undo an action in the panel?', 'faq.a10': 'Settings → “🕘 Action log”: entries with a “↩ Revert” button can be undone (e.g. deleting a created bot). No button — undo is unavailable, the entry is informational.',
        'faq.q11': 'Where to see bot logs?', 'faq.a11': 'Bots → Configure → Advanced → Logs (filters, CSV export). The combined stream is in Analytics → “📋 Bot logs”. Logs appear when bots read chat and reply.',
        'faq.q12': 'How to make a backup?', 'faq.a12': 'Settings → “💾 Backup”: download the archive (including .env) and restore it with “Restore”. Current data will be overwritten.',
        'faq.q13': 'How does panel access work?', 'faq.a13': 'No password is needed on localhost. For explicit LAN or network access, configure PANEL_AUTH_USER, PANEL_AUTH_PASS, and TOKEN_ENCRYPTION_KEY; without all three the panel stays on 127.0.0.1.',
        'faq.q14': 'How to add widgets to OBS?', 'faq.a14': 'Widgets tab → fill the content → copy the widget URL → add a Browser Source in OBS. Background is transparent. Widget files live in the widgets/ folder and can be edited without the panel (see widgets/README.md).',
        'settings.twitch_api': '🟣 Twitch API',
        'settings.twitch_api_what': 'What it gives the panel:',
        'settings.twitch_api_use1': 'Bot sign-in via Twitch (the “Sign in with Twitch” button, no manual token)',
        'settings.twitch_api_use2': 'Channel info: game, stream title, viewers',
        'settings.twitch_api_use3': 'Auto-update of the streamer profile (About the streamer tab)',
        'settings.twitch_api_use4': 'Twitch events (follow/sub/raid/cheer) via EventSub',
        'settings.twitch_api_how': 'Without the keys the panel works, but these features are unavailable. Create an app at dev.twitch.tv/console → Apps → New Application and paste the Client ID and Client Secret here.',
                'btn.leave': '↪ Leave', 'empty.no_channels': 'No channels — add the first one',
        'channels.info_loading': 'Loading channel info...', 'channels.info_btn': 'Channel info',
        'channels.info_failed': 'Could not load channel info (TWITCH_CLIENT_ID/SECRET required in .env)',
        'channels.last_message': 'last message', 'channels.overrides_btn': 'Per-channel overrides',
                'analytics.heatmap_title': '🔥 Chat activity (day × hour)', 'analytics.heatmap_legend': 'Less', 'analytics.heatmap_legend_more': 'More',
        'analytics.trending_title': '📈 Rising and cooling topics', 'analytics.trend_hour': 'Last hour', 'analytics.trend_day': 'Last day',
        'analytics.trending': 'Rising', 'analytics.cooling': 'Cooling', 'analytics.hour24_title': '💬 Messages last 24h',
        'analytics.top_chatters': '👑 Top chatters', 'analytics.perbot_title': '🤖 Bot statistics',
                'streamer.title': '👤 About the streamer', 'streamer.description': 'Helps the bot know who runs the stream: bio, style, interests. The bot uses it in replies.',
        'streamer.auto_updated': 'Auto-update profile via AI',
        'streamer.empty': 'Streamer profile is not filled in yet', 'streamer.fill_now': 'Fill in now',
        'streamer.age': 'Age', 'streamer.gender': 'Gender', 'streamer.location': 'Location',
        'streamer.occupation': 'Occupation', 'streamer.bio': 'Bio',
        'streamer.bio_placeholder': 'Short description: who they are, what they do, what they are known for',
        'streamer.gender_placeholder': 'male / female',
        'streamer.style': 'Stream style', 'streamer.style_none': 'Not set',
        'streamer.style_edu': 'Educational', 'streamer.style_fun': 'Entertaining', 'streamer.style_comp': 'Competitive',
        'streamer.interests': 'Interests (comma separated)', 'streamer.games': 'Favorite games (comma separated)',
        'streamer.likes': 'Likes (comma separated)', 'streamer.dislikes': 'Dislikes (comma separated)',
        'streamer.save': '💾 Save profile', 'streamer.saved': 'Streamer profile saved',
        'streamer.face_title': '📷 Streamer photo', 'streamer.face_desc': 'The photo helps the vision AI recognise the streamer on camera and not confuse them with viewers. Used only locally and sent only to the configured AI provider.',
        'streamer.face_none': 'No photo', 'streamer.face_delete': '🗑 Delete photo',
        'streamer.face_uploaded': 'Photo uploaded', 'streamer.face_deleted': 'Photo deleted',
        'streamer.face_invalid': 'File must be JPEG/PNG up to 2 MB',
        'streamer.channel_hint': 'One profile per bot — applies to all of its channels: {channels}. For different streamers per channel, create a separate bot.',
        'streamer.channel_hint_none': 'One profile per bot. This bot has no channels yet — the profile will apply to the first connected one.',
        'empty.load_failed': 'Load error: {detail}',
    },
    ua: {
        'health.online': 'Працює', 'health.connecting': 'Підключається...', 'health.error': 'Помилка',
        'health.reconnects': 'Перепідключень: {n}',
        'health.disabled': 'Вимкнено', 'health.offline': 'Зупинено',
        'health.last_error_at': 'Остання помилка: {time}',
        'health.no_reason': 'Причина невідома',
        'btn.reconnect': '↻ Перепідключити',
        'toast.reconnecting': 'Перепідключаю {name}...',
        'toast.bot_started_named': '{name} запускається...',
        'send.reason.bot_disabled': 'бота вимкнено',
        'send.reason.bot_not_found': 'бота не знайдено',
        'send.reason.bot_not_connected': 'бот не підключений до чату',
        'send.reason.channel_not_connected': 'бот не підключений до каналу',
        'send.reason.channel_disabled': 'канал вимкнено',
        'send.reason.no_channel': 'немає каналу',
        'send.reason.oauth_expired': 'OAuth-токен закінчився',
        'send.reason.cooldown': 'занадто часто (cooldown)',
        'send.reason.moderation_blocked': 'заблоковано модерацією',
        'send.reason.twitch_error': 'помилка Twitch',
        'send.reason.network_error': 'помилка мережі',
        'send.reason.invalid_target': 'не вказано бота або канал',
        'send.reason.empty_message': 'порожнє повідомлення',
        'send.reason.unknown': 'невідома помилка',
        'send.sent_ok': '✅ відправлено',
        'send.failed_prefix': '❌ не відправлено — {reason}',
        'send.result_title': 'Результат відправки',
        'send.partial_success': 'Частково відправлено: {sent} з {total}',
        'triggers.channel_all': 'Усі канали',
        'triggers.channel_label': 'Канал',
        'triggers.fires': 'Спрацювань: {count}',
        'triggers.last_fired': 'Останній запуск: {time}',
        'triggers.never_fired': 'ще не запускався',
        'triggers.test': '🧪 Тест',
        'triggers.channel_hint': 'Порожньо — тригер працює в усіх каналах бота',
        'triggers.test_prompt': 'Введіть текст повідомлення для перевірки тригера:',
        'triggers.test_ok': '✅ Тригер спрацював би ({mode})',
        'triggers.test_ok_ai': 'відповідь через AI',
        'triggers.test_ok_fixed': 'фіксована відповідь: {response}',
        'triggers.test_fail': '❌ Не спрацював би: {reason}',
        'triggers.reason.trigger_disabled': 'тригер вимкнено',
        'triggers.reason.channel_mismatch': 'тригер привʼязаний до іншого каналу',
        'triggers.reason.no_keyword_match': 'ключове слово не знайдено в тексті',
        'triggers.reason.not_found': 'тригер не знайдено',
        'btn.toggle_off': 'Вимкнути', 'btn.toggle_on': 'Увімкнути', 'btn.edit': 'Змінити',
        'events.chance': 'Шанс: {chance}%', 'events.fixed': 'фіксована відповідь', 'events.ai': 'AI',
        'common.selected': 'Вибрано: {count}',
        'label.selected': '✓ вибрано', 'btn.configure': 'Налаштувати',
        'empty.no_snippets': 'Заготовок немає — додайте!',
                'widgets.design_theme':'Тема','widgets.design_accent':'Акцент','widgets.design_bg':'Тло','widgets.design_opacity':'Прозорість','widgets.design_radius':'Заокруглення','widgets.design_font':'Шрифт','widgets.design_size':'Розмір тексту','widgets.design_scale':'Масштаб','widgets.design_position':'Позиція','widgets.design_hold':'Показ, сек.','widgets.design_maxw':'Макс. ширина','widgets.design_shadow':'Тінь','widgets.design_status':'Статус','widgets.chat_runtime_title':'⭐ Обраний чат','widgets.chat_runtime_hint':'Спільний список довірених користувачів фільтрує справжній Twitch-чат. Список можна редагувати після імпорту.','widgets.chat_trusted_label':'Довірені логіни','widgets.chat_trusted_ph':'friend, moderator_name','widgets.chat_trusted_hint':'По одному логіну в рядку або через кому; @ додавати необов’язково.','widgets.chat_import_account':'Акаунт Twitch','widgets.chat_import_channel':'Канал Twitch','widgets.chat_import_mods':'Імпорт модераторів','widgets.chat_import_vips':'Імпорт VIP','widgets.chat_import_hint':'Імпорт потребує broadcaster OAuth з moderation:read або channel:read:vips; наявні логіни зберігаються.','widgets.chat_imported':'Додано з Twitch: {count}','widgets.chat_import_error_helix_not_configured':'Спочатку вкажіть Twitch Client ID.','widgets.chat_import_error_invalid_token_or_channel':'Twitch не зміг перевірити OAuth-токен або канал.','widgets.chat_import_error_broadcaster_token_required':'Для імпорту потрібен OAuth власника вибраного каналу.','widgets.chat_import_error_missing_scope':'Перепідключіть акаунт із потрібними правами імпорту.','widgets.chat_import_error_request_failed':'Twitch тимчасово недоступний; спробуйте пізніше.','widgets.chat_max_messages':'Повідомлень','widgets.chat_lifetime':'Зникнення, сек.','widgets.chat_font_size':'Розмір тексту','widgets.chat_emote_size':'Розмір смайлів','widgets.chat_history_limit':'Повідомлень історії','widgets.chat_history_minutes':'Історія, хвилин','widgets.chat_show_badges':'Показувати бейджі','widgets.chat_display_hint':'Нуль секунд залишає повідомлення до заповнення ліміту; історія обмежується кількістю й часом.','widgets.channel_scope': 'Канал віджетів','widgets.scope_demo': 'демо (без каналу)','widgets.admin_title': '🎛 Керування контентом', 'soundboard.title':'🎵 Soundboard','soundboard.hint':'Завантажте аудіо, потім натисніть Play або створіть прив’язку клавіші. Звук грає лише в OBS Browser Source.','soundboard.upload_label':'Аудіофайли MP3/WAV/OGG/WebM, до 10 МБ кожен','soundboard.upload':'⬆ Завантажити','soundboard.play':'Play','soundboard.bind':'Прив’язка','soundboard.stop':'■ Stop','soundboard.name':'Назва','soundboard.volume':'Гучність','soundboard.cooldown':'Cooldown, сек','soundboard.order':'Порядок','soundboard.empty':'Треки ще не завантажено','soundboard.file_required':'Виберіть аудіофайли','soundboard.upload_result':'Завантажено: {accepted}; відхилено: {rejected}','soundboard.played':'Команду Play надіслано в OBS','soundboard.stopped':'Команду Stop надіслано в OBS','soundboard.delete_confirm':'Видалити трек і його файл? Старий binding перестане працювати.','soundboard.bind_ready':'Виберіть клавішу й додайте прив’язку','soundboard.hotkey':'Гаряча клавіша','soundboard.hotkey_hint':'Гаряча клавіша (напр. 1, Numpad1, Alt+1) для швидкого запуску','soundboard.hotkey_triggered':'Гарячу клавішу активовано',  'widgets.countdown_title': '⏳ Countdown',  'widgets.admin_hint': 'Заповніть віджети контентом прямо тут — зміни одразу видно в OBS. Біля кожної форми — живе превʼю.',
        'widgets.goal_placeholder': 'Нова ціль...', 'widgets.clear_done': 'Прибрати виконані', 'widgets.preview_title': 'Превʼю віджета',
        'widgets.target': 'Ціль', 'widgets.current': 'Зараз', 'widgets.title_label': 'Заголовок', 'widgets.reset': 'Скидання',
        'widgets.kind': 'Тип', 'widgets.kind_music': 'Музика', 'widgets.kind_video': 'Відео', 'widgets.kind_game': 'Гра', 'widgets.kind_movie': 'Фільм', 'widgets.kind_custom': 'Інше',
        'widgets.np_title': 'Назва', 'widgets.np_sub': 'Автор / деталь',
        'widgets.sch_title': 'Тема ефіру', 'widgets.sch_required': 'Вкажіть час і тему',
        'widgets.counter_key': 'ключ (death)', 'widgets.counter_label': 'підпис (Смерті)',
        'widgets.mode': 'Режим', 'widgets.mode_countdown': 'Зворотний відлік', 'widgets.mode_stopwatch': 'Секундомір', 'widgets.cd_minutes': 'Хвилин',
        'widgets.donators': '💰 Топ донатерів', 'widgets.td_period': 'Період', 'widgets.td_alltime': 'Весь час', 'widgets.td_month': 'Місяць', 'widgets.td_day': 'День', 'widgets.don_message': 'Повідомлення (необовʼязково)', 'widgets.don_required': 'Вкажіть нік і суму',
        'widgets.songs': '🎧 Song Request', 'widgets.enabled': 'Увімкнено', 'widgets.visible': 'Видно в OBS', 'widgets.song_title': 'Назва треку / YouTube',
        'widgets.sr_skip': '⏭ Скіп', 'widgets.sr_clear': 'Очистити чергу',
        'song_request.description':'Глядачі командою !sr <посилання або назва> додають трек до логічної черги.','song_request.playback_hint':'Song Request сам не запускає YouTube або Spotify. Окремий Media Share Browser Source автоматично відтворює лише підтримувані YouTube-посилання; без нього playing означає тільки поточну позицію черги.','song_request.cooldown':'Cooldown !sr, сек.','song_request.max_per_user':'Макс. треків на користувача','song_request.max_queue':'Макс. треків у черзі','song_request.queue_status':'У черзі: {count} · поточний: {current}','song_request.none':'немає','song_request.entitlements_title':'Channel Points і донати','song_request.entitlements_hint':'Вкажіть стабільні reward ID. Назва є fallback лише коли ID не задано. Платні події без унікального event ID відхиляються; автоматичний refund недоступний.','song_request.points_create_id':'Reward ID: додати','song_request.points_create_id_hint':'Створює запит із користувацького вводу reward.','song_request.points_priority_id':'Reward ID: пріоритет','song_request.points_priority_id_hint':'Створює пріоритетний запит або підвищує збіг активного.','song_request.points_create_title':'Fallback-назва: додати','song_request.points_priority_title':'Fallback-назва: пріоритет','song_request.points_title_hint':'Використовується лише якщо відповідний reward ID порожній.','song_request.donation_enabled':'Замовлення за донати','song_request.donation_threshold':'Мінімальна сума','song_request.donation_threshold_hint':'Подія приймається від цієї суми включно.','song_request.donation_currency':'Валюта','song_request.donation_currency_hint':'Точний збіг коду валюти, без конвертації.','song_request.donation_action':'Дія донату','song_request.donation_action_hint':'Назва треку береться з повідомлення донату.','song_request.action_create':'Додати запит','song_request.action_priority':'Додати / підвищити пріоритет','song_request.audit_title':'Журнал запитів','song_request.audit_hint':'Accepted означає додавання або підвищення пріоритету, а не підтверджене відтворення.','song_request.audit_empty':'Записів ще немає','song_request.accepted':'Прийнято','song_request.rejected':'Відхилено','song_request.reason.accepted':'додано','song_request.reason.priority_boosted':'пріоритет підвищено','song_request.reason.empty_request':'порожній запит','song_request.reason.request_too_long':'запит задовгий','song_request.reason.control_characters':'неприпустимі символи','song_request.reason.unsafe_url':'небезпечне посилання','song_request.reason.duplicate_request':'дублікат','song_request.reason.queue_full':'черга заповнена','song_request.reason.user_limit':'ліміт користувача','song_request.reason.cooldown':'cooldown','song_request.reason.disabled':'черга вимкнена','song_request.reason.missing_event_id':'немає event ID','song_request.reason.currency_mismatch':'інша валюта','song_request.reason.below_threshold':'сума нижча за поріг','song_request.reason.internal_error':'внутрішня помилка',
        'widgets.no_goals': 'Цілей поки немає', 'widgets.no_schedule': 'Розклад порожній', 'widgets.no_counters': 'Лічильників немає',
        'widgets.no_donations': 'Донатів поки немає', 'widgets.no_songs': 'Черга порожня',
                'oauth.login_btn': 'Увійти через Twitch', 'oauth.or_manual': 'або введіть токен вручну нижче',
        'oauth.enter_code': 'Відкрийте посилання та введіть код:', 'oauth.waiting': 'Очікування підтвердження...',
        'oauth.cancel': 'Скасувати вхід', 'oauth.done': 'Вхід виконано! Бота додано.',
        'actionlog.title': '🕘 Журнал дій', 'actionlog.description': 'Що відбувалося в панелі. Кнопка «↩ Скасувати» у записі відкочує дію (наприклад, видаляє створеного бота). Записи без кнопки не мають відкату — це інформація про подію.',
        'actionlog.all_actions': 'Усі типи', 'actionlog.all_actors': 'Усі актори', 'actionlog.search': 'Пошук...',
        'actionlog.prev': '← Старіші', 'actionlog.next': 'Новіші →', 'actionlog.empty': 'Записів немає',
        'actionlog.revert': '↩ Скасувати', 'actionlog.reverted': 'Дію скасовано', 'btn.search': 'Знайти',
        'chat.channel_of': 'Канал', 'chat.add_channel_hint': 'У бота немає каналів — додайте на вкладці «Канали»', 'btn.configure_short': 'Налаштувати', 'chat.pick_search': 'Пошук каналу або бота...', 'chat.pick_empty': 'Каналів не знайдено',
        'chat.pick_manual_label': 'Або впишіть канал вручну', 'chat.pick_manual_ph': "ім'я каналу", 'chat.pick_manual_use': 'Вибрати',
                'cp.none': 'Провайдерів поки немає — додайте першого', 'cp.models_word': 'мод.',
        'cp.name_ph': 'Імʼя (myproxy)', 'cp.url_ph': 'https://api.example.com/v1', 'cp.key_ph': 'API-ключ (порожньо = не змінювати)',
        'cp.key_set': 'ключ задано (введіть новий, щоб замінити)',
        'cp.name_required': 'Вкажіть імʼя провайдера',
        'cp.created': 'Провайдера додано', 'cp.updated': 'Провайдера оновлено', 'cp.deleted': 'Провайдера видалено',
        'cp.add': '+ Додати провайдера', 'cp.update': '💾 Зберегти зміни',
        'cp.add_model': '＋ Модель', 'cp.model_name_ph': 'назва моделі',
        'cp.model_type': 'Тип моделі', 'cp.type_chat': 'чат', 'cp.type_vision': 'vision', 'cp.type_both': 'чат+vision',
        'cp.no_models': 'Моделей поки немає — додайте першу',
        'cp.models_types_hint': 'Один список моделей: позначте кожну як чат, vision або обидві. Модель не додається двічі — не треба вписувати її окремо для vision.',
        'bot.model_default': 'За замовчуванням (перша модель провайдера)',
        'bot.vision_default': 'За замовчуванням (перша vision-модель провайдера)',
        'vision.testing': 'Перевіряю vision...', 'vision.test_ok': 'Vision працює: {detail}',
                'mood.title': '🎭 Настрій стримера', 'mood.waiting': 'З’явиться, коли боти почують стримера',
                'sharedfacts.title': '🌐 Спільні факти (усі боти)', 'sharedfacts.decay': '🧹 Затухання старих',
        'sharedfacts.description': 'Факти, які боти дізналися про глядачів, — спільні для всіх ботів панелі. Confidence — впевненість (0–1), старі факти затухають.',
        'sharedfacts.fact_ph': 'Факт про глядача', 'sharedfacts.empty': 'Введіть нік, щоб побачити факти',
        'sharedfacts.no_facts': 'Фактів про юзера поки немає', 'sharedfacts.confidence': 'Впевненість',
        'sharedfacts.required': 'Вкажіть нік і факт', 'sharedfacts.added': 'Факт додано',
        'sharedfacts.decayed': 'Видалено затуханням: {detail}',
        'feedback.saved': 'Дякую за оцінку!', 'feedback.total': 'усього оцінок: {count}',
                'analytics.feedback_title': '👍 Оцінки відповідей', 'analytics.feedback_hint': 'Оцініть відповідь бота кнопками 👍/👎 у вкладці «Чат» — тут з’явиться зведення.',
        'nav.brain': '🧠 Мозок', 'title.brain': 'Мозок бота',
                'bot.quick_title': '⚡ Швидкі налаштування',
        'mood.title': '😊 Настрій стримера', 'mood.hint': 'Оцінка тону голосу стримера (з Stream Vision). Оновлюється автоматично під час стриму.',
        'clips.title': '🎬 Кліпи (сплески чату)', 'clips.check': 'Перевірити сплеск', 'clips.create': '✂ Створити кліп',
        'clips.hint': 'Коли чат різко прискорюється (хайп-момент) — бот позначить момент для кліпу. «Створити кліп» ріже останні 30 секунд через Twitch.',
        'clips.spike_yes': 'Сплеск виявлено!', 'clips.spike_no': 'Сплеску зараз немає',
        'clips.created': 'Кліп створено: {detail}', 'clips.open': 'відкрити', 'clips.no_moments': 'Моментів поки немає',
        'replay.title': '⏺ Запис сесій', 'replay.start': '⏺ Почати запис', 'replay.stop': '⏹ Закінчити',
        'replay.hint': 'Записує чат і відповіді бота цієї сесії в архів — потім можна переглянути.',
        'replay.messages': 'повідомлень', 'replay.empty': 'Записів поки немає',
        'replay.started': 'Запис почато', 'replay.ended': 'Запис закінчено', 'replay.none_active': 'Активного запису немає',
        'brain.intro': 'Памʼять стримера (Lore), навчання, зведення стримів і тимчасові зсуви настрою. Усе застосовується лише після підтвердження.',
        'brain.lore_hint': 'Lore — факти про стрімера, які бот памʼятає і використовує у відповідях: додані вручну та запропоновані Summarizer/аналізом чату. У список потрапляють лише після підтвердження ✓. Скоуп: «усі канали» або конкретний канал.',
        'brain.importance': 'Важливість 0–100',
        'brain.fact_source': 'Джерело факту',
        'brain.src.manual': 'manual — додав ти',
        'brain.src.summary': 'summary — зі зведень',
        'brain.src.chat': 'chat — з чату',
        'brain.learning_hint': 'Пропозиції бота щодо стилю та бази знань — з фідбеку 👍/👎 і аналізу чату. «Застосувати» змінює поведінку бота, «Скасувати» відкочує останнє застосоване.',
        'brain.summary_hint': 'Звіти «як минув стрим» з історії чату: ручний прогін за період і live-зведення кожні 30 хвилин (нижче — увімкнення та налаштування per-канал). Зведення живлять Lore фактами.',
        'brain.shift_hint': 'Тимчасовий зсув настрою бота: «мʼякий» — трохи більше сарказму/енергії, «сильний» — помітна зміна характеру. Діє обмежений час і гасне сам. Налаштовується на обраний скоуп.',
        'brain.memory_hint': 'Що бот запамʼятав про глядачів. Підтверджений факт (✓✓) живе довше і частіше використовується; ✎ править пріоритет і строк. Прогонів не було — факти зʼявляться, коли Summarizer/чат-аналіз знайде що запамʼятати.',
        'brain.runs_empty': 'Прогонів ще не було. Натисніть ▶ «Прогнати стрим» (звіт за період) або увімкніть Live-зведення нижче — вони пишуться самі кожні 30 хвилин, поки йде стрим.',
        'brain.memory_empty': 'Памʼять порожня. Факти зʼявляться, коли бот накопичить їх з чату (Summarizer/аналізатор). Хочете швидше — натисніть 🤖 «Витягти факти»: пропозиції підуть у Lore, а після підтвердження ✓ — у памʼять.',
        'brain.profile_title': '👤 Профіль стрімера',
        'brain.profile_hint': 'Хто такий стрімер: вік, біо, стиль, улюблені ігри. Глобальний профіль діє на всіх каналах; для окремого каналу можна задати свій. Редактор той самий, що в Налаштуваннях — зміни видно в обох місцях.',
                'btn.test_vision': '👁 Перевірити vision',
        'settings.custom_providers': '🧩 Кастомні провайдери',
        'settings.custom_providers_hint': 'Власні API-провайдери (OpenAI-сумісні): дайте імʼя, вкажіть Base URL і ключ, додайте моделі кнопкою «＋ Модель». Потім оберіть їх у «AI Провайдер» вище та в налаштуваннях кожного бота.',
        'settings.vision_hint': 'Vision — модель, що дивиться на картинки стриму. Це спільна база: її беруть боти в режимі «Спільна» (за замовчуванням); бот у режимі «Власна» використовує свою модель. Підказки: OpenRouter → google/gemini-2.0-flash:free · Ollama (локально, безкоштовно) → llava або minicpm-v (ollama pull llava) · іменований провайдер (🧩) → його модель з підтримкою картинок.',
        'toast.saved': 'Збережено', 'toast.deleted': 'Видалено',
        'logs.empty_hint': 'Логів немає — вони з’являться, коли боти почнуть читати чат і відповідати',
                'faq.q5': 'Як додати бота без ручного токена?', 'faq.a5': 'У формі додавання бота натисніть «🟣 Увійти через Twitch»: відкрийте twitch.tv/activate, введіть код — бота додано автоматично. Потрібен Twitch API (Client ID/Secret) у налаштуваннях; без них — ручний токен.',
        'faq.q6': 'Як бот дізнається про стримера?', 'faq.a6': 'Боти → Налаштувати → «👤 Про стримера»: профіль (біо, стиль, інтереси) + фото для розпізнавання в кадрі. Автооновлення — AI сам доповнить профіль із чату.',
        'faq.q7': 'Що бот бачить і чує зі стриму?', 'faq.a7': 'Stream Vision: кадри стриму + Whisper-транскрипція аудіо. Vision-модель задається в AI-налаштуваннях. Локально — Ollama: модель llava або minicpm-v як Vision-модель.',
        'faq.q8': 'Як запускати ботів на різних API/моделях?', 'faq.a8': 'Боти → Налаштувати → Огляд → AI Override: власний провайдер, моделі й ключ. Без override — глобальні налаштування.',
        'faq.q9': 'Бота увімкнено, але не підключено — що робити?', 'faq.a9': 'Картка бота: жовтий «Підключається», червоний «Помилка» з причиною й часом; кнопка «↻ Перепідключити». Часті причини: невірний/закінчений OAuth-токен, Twitch недоступний (перевірте проксі).',
        'faq.q10': 'Як відкотити дію в панелі?', 'faq.a10': 'Налаштування → «🕘 Журнал дій»: у записів з «↩ Скасувати» доступне скасування. Немає кнопки — запис лише для інформації.',
        'faq.q11': 'Де дивитися логи бота?', 'faq.a11': 'Боти → Налаштувати → Додатково → Логи (фільтри, експорт CSV). Загальний потік — Статистика → «📋 Логи ботів». Логи з’являються, коли боти читають чат і відповідають.',
        'faq.q12': 'Як зробити резервну копію?', 'faq.a12': 'Налаштування → «💾 Резервна копія»: завантажте архів (включно з .env), відновіть кнопкою «Відновити» — поточні дані буде перезаписано.',
        'faq.q13': 'Як працює доступ до панелі?', 'faq.a13': 'На localhost пароль не потрібен. Для явного доступу з LAN або мережі налаштуйте PANEL_AUTH_USER, PANEL_AUTH_PASS і TOKEN_ENCRYPTION_KEY; без повного набору панель залишається на 127.0.0.1.',
        'faq.q14': 'Як підключити віджети в OBS?', 'faq.a14': 'Вкладка «Віджети» → заповніть контент → скопіюйте URL → Browser Source в OBS. Файли віджетів у папці widgets/ правляться без панелі (widgets/README.md).',
        'settings.twitch_api': '🟣 Twitch API',
        'settings.twitch_api_what': 'Що це дає панелі:',
        'settings.twitch_api_use1': 'Вхід ботів через Twitch (кнопка «Увійти через Twitch» без ручного токена)',
        'settings.twitch_api_use2': 'Інформація про канали: гра, назва стриму, глядачі',
        'settings.twitch_api_use3': 'Автооновлення профілю стримера (вкладка «Про стримера»)',
        'settings.twitch_api_use4': 'Події Twitch (follow/sub/raid/cheer) через EventSub',
        'settings.twitch_api_how': 'Без ключів панель працює, але ці функції недоступні. Створіть застосунок на dev.twitch.tv/console → Apps → New Application і вставте Client ID і Client Secret сюди.',
                'btn.leave': '↪ Вийти', 'empty.no_channels': 'Каналів немає — додайте перший',
        'channels.info_loading': 'Завантажую інформацію про канал...', 'channels.info_btn': 'Інформація про канал',
        'channels.info_failed': 'Не вдалося отримати інформацію (потрібен TWITCH_CLIENT_ID/SECRET у .env)',
        'channels.last_message': 'останнє повідомлення', 'channels.overrides_btn': 'Per-channel overrides',
                'analytics.heatmap_title': '🔥 Активність чату (день × година)', 'analytics.heatmap_legend': 'Менше', 'analytics.heatmap_legend_more': 'Більше',
        'analytics.trending_title': '📈 Зростаючі та згасаючі теми', 'analytics.trend_hour': 'За годину', 'analytics.trend_day': 'За день',
        'analytics.trending': 'Зростають', 'analytics.cooling': 'Згасають', 'analytics.hour24_title': '💬 Повідомлення за 24 години',
        'analytics.top_chatters': '👑 Топ чатерів', 'analytics.perbot_title': '🤖 Статистика бота',
                'streamer.title': '👤 Про стримера', 'streamer.description': 'Допомагає боту знати, хто веде стрим: біо, стиль, інтереси. Бот використовує це у відповідях.',
        'streamer.auto_updated': 'Автооновлення профілю через AI',
        'streamer.empty': 'Профіль стримера ще не заповнено', 'streamer.fill_now': 'Заповнити зараз',
        'streamer.age': 'Вік', 'streamer.gender': 'Стать', 'streamer.location': 'Локація',
        'streamer.occupation': 'Рід занять', 'streamer.bio': 'Біо стримера',
        'streamer.bio_placeholder': 'Короткий опис: хто він, чим займається, чим відомий',
        'streamer.gender_placeholder': 'чоловіча / жіноча',
        'streamer.style': 'Стиль стриму', 'streamer.style_none': 'Не вказано',
        'streamer.style_edu': 'Навчальний', 'streamer.style_fun': 'Розважальний', 'streamer.style_comp': 'Змагальний',
        'streamer.interests': 'Інтереси (через кому)', 'streamer.games': 'Улюблені ігри (через кому)',
        'streamer.likes': 'Подобається (через кому)', 'streamer.dislikes': 'Не подобається (через кому)',
        'streamer.save': '💾 Зберегти профіль', 'streamer.saved': 'Профіль стримера збережено',
        'streamer.face_title': '📷 Фото стримера', 'streamer.face_desc': 'Фото допомагає AI з vision розпізнавати стримера в кадрі й не плутати його з глядачами. Використовується лише локально та передається лише налаштованому AI-провайдеру.',
        'streamer.face_none': 'Немає фото', 'streamer.face_delete': '🗑 Видалити фото',
        'streamer.face_uploaded': 'Фото завантажено', 'streamer.face_deleted': 'Фото видалено',
        'streamer.face_invalid': 'Файл має бути JPEG/PNG до 2 МБ',
        'streamer.channel_hint': 'Один профіль на бота — застосовується до всіх його каналів: {channels}. Для різних стримерів на різних каналах створіть окремого бота.',
        'streamer.channel_hint_none': 'Один профіль на бота. У бота поки немає каналів — профіль буде застосовано до першого підключеного.',
        'empty.load_failed': 'Помилка завантаження: {detail}',
    },
}).forEach(([lang, strings]) => Object.assign(LANGS[lang], strings));


// Strings used by the live dashboard and CRUD controls must exist in every
// supported locale because these views are rendered dynamically.
for (const [lang, strings] of Object.entries({
    ru: {
        'label.connecting': 'Подключение', 'label.error': 'Ошибка',
        'toast.not_sent_by_bots': 'Не отправлено ботами: {detail}',
        'toast.trigger_updated': 'Триггер обновлён', 'toast.event_added': 'Событие добавлено',
        'status.runtime': 'AI: {provider}', 'status.ai_paused': ' · приостановлен: Ollama недоступна', 'status.ai_paused_short': 'Приостановлен: Ollama недоступна', 'status.fallback_enabled': ' · Ollama fallback включён',
        'status.runtime_error': 'Ошибка состояния: {detail}',
    },
    en: {
        'label.connecting': 'Connecting', 'label.error': 'Error',
        'toast.not_sent_by_bots': 'Not sent by bots: {detail}',
        'toast.trigger_updated': 'Trigger updated', 'toast.event_added': 'Event added',
        'status.runtime': 'AI: {provider}', 'status.ai_paused': ' · paused: Ollama unavailable', 'status.ai_paused_short': 'Paused: Ollama unavailable', 'status.fallback_enabled': ' · Ollama fallback enabled',
        'status.runtime_error': 'Status error: {detail}',
    },
    ua: {
        'label.connecting': 'Підключення', 'label.error': 'Помилка',
        'toast.not_sent_by_bots': 'Не відправлено ботами: {detail}',
        'toast.trigger_updated': 'Тригер оновлено', 'toast.event_added': 'Подію додано',
        'status.runtime': 'AI: {provider}', 'status.ai_paused': ' · призупинено: Ollama недоступна', 'status.ai_paused_short': 'Призупинено: Ollama недоступна', 'status.fallback_enabled': ' · Ollama fallback увімкнено',
        'status.runtime_error': 'Помилка стану: {detail}',
    },
})) LANGS[lang] = {...LANGS[lang], ...strings};

const PLURAL_FORMS = {
    bots: { ru: ['бот', 'бота', 'ботов'], ua: ['бот', 'боти', 'ботів'], en: ['bot', 'bots', 'bots'] },
    messages: { ru: ['сообщение', 'сообщения', 'сообщений'], ua: ['повідомлення', 'повідомлення', 'повідомлень'], en: ['message', 'messages', 'messages'] },
    snippets: { ru: ['заготовка', 'заготовки', 'заготовок'], ua: ['заготовка', 'заготовки', 'заготовок'], en: ['snippet', 'snippets', 'snippets'] },
    replies: { ru: ['ответ', 'ответа', 'ответов'], ua: ['відповідь', 'відповіді', 'відповідей'], en: ['reply', 'replies', 'replies'] },
    events: { ru: ['событие', 'события', 'событий'], ua: ['подія', 'події', 'подій'], en: ['event', 'events', 'events'] },
    errors: { ru: ['ошибка', 'ошибки', 'ошибок'], ua: ['помилка', 'помилки', 'помилок'], en: ['error', 'errors', 'errors'] },
    minutes: { ru: ['минута', 'минуты', 'минут'], ua: ['хвилина', 'хвилини', 'хвилин'], en: ['min', 'min', 'min'] },
};
function tPlural(key, count) {
    const lang = localStorage.getItem('lang') || 'ru';
    const forms = PLURAL_FORMS[key]?.[lang] || PLURAL_FORMS[key]?.ru;
    if (!forms) return String(count);
    if (lang === 'en') return `${count} ${Number(count) === 1 ? forms[0] : forms[2]}`;
    const n = Math.abs(Number(count)) % 100;
    const one = n % 10 === 1 && n !== 11;
    const few = n % 10 >= 2 && n % 10 <= 4 && (n < 10 || n >= 20);
    return `${count} ${one ? forms[0] : few ? forms[1] : forms[2]}`;
}

Object.assign(LANGS.ru, {'tab.voice_clones':'Голосовые клоны','tts.clone_manage':'Управление голосовыми клонами','tts.upload_model':'Загрузить Piper-модель','tts.setup_guide':'Гайд по настройке','status.no_clones':'Клонов голосов нет','status.uploaded':'Голосовая модель загружена','label.emotion':'Эмоция','label.observation_only':'Только наблюдает','tab.overview':'📌 Обзор','tab.identity':'🎭 Характер','tab.ai_tts':'🧠 AI и TTS','tab.flow':'📡 Каналы и триггеры','tab.memory_knowledge':'🧠 Память и знания','tab.advanced':'⚙️ Дополнительно','tab.sandbox':'🧪 Песочница','analytics.sentiment_title':'Настроение чата','analytics.wordcloud_title':'Популярные слова','botfiles.title':'📁 Файлы бота','botfiles.hint':'Текстовые файлы (json/md/txt) до 256 КБ. Промпты и память бота можно править прямо здесь.','botfiles.empty':'Файлов пока нет','confirm.delete_file':'Удалить этот файл?',
    'widgets.grid_hint':'Откройте URL в Browser Source OBS. Все виджеты — прозрачный фон, поддерживают dark/light тему.',
    'widget.tts.title':'🔊 TTS Озвучка','widget.tts.desc':'Озвучка сообщений чата (Web Speech API)',
    'widget.goals.title':'🎯 Цели','widget.goals.desc':'Прогресс-бар целей (donate/sub/follow)',
    'widget.now_playing.title':'🎵 Сейчас играет','widget.now_playing.desc':'Текущий трек (Last.fm / Spotify)',
    'widget.sub_goal.title':'⭐ Sub-цель','widget.sub_goal.desc':'Счётчик подписок',
    'widget.schedule.title':'📅 Расписание','widget.schedule.desc':'Сейчас на стриме / скоро',
    'widget.uptime.title':'⏱ Uptime','widget.uptime.desc':'REC / длительность стрима',
    'widget.counter.title':'🔔 Counter','widget.counter.desc':'Счётчик (death/streak/custom)',
    'widget.follower_ticker.title':'🏃 Follower Ticker','widget.follower_ticker.desc':'Бегущая строка событий',
    'widget.lower_third.title':'🏷 Lower Third','widget.lower_third.desc':'Плашка имя + tagline',
    'widget.mascot.title':'🐾 Маскот','widget.mascot.desc':'Зверёк с реакциями',
    'widget.chat_highlight.title':'💬 Chat Highlight','widget.chat_highlight.desc':'Выделение сообщений чата',
    'widget.chat_roulette.title':'🎲 Chat Roulette','widget.chat_roulette.desc':'Случайное сообщение из чата',
    'widget.combo_counter.title':'🔥 Combo Counter','widget.combo_counter.desc':'Счётчик комбо одинаковых сообщений',
    'widget.animated_bg.title':'❄️ Animated BG','widget.animated_bg.desc':'Анимированный фон (снег, дождь, листья)',
    'widget.anime_runner.title':'🕺 Anime Runner','widget.anime_runner.desc':'Аниме-бегунок в углу',
    'widget.countdown.title':'🎯 Countdown','widget.countdown.desc':'Обратный отсчёт до события',
    'placeholder.client_id':'ваш client_id','placeholder.client_secret':'ваш client_secret',
    'settings.provider_status':'🩺 Состояние провайдеров','btn.test_all':'🔌 Проверить все',
    'settings.offline_mode':'🛡️ Оффлайн-режим','settings.offline_mode_desc':'Принудительно использовать Ollama для AI/Vision и Piper/Web Speech для озвучки. Ключи облачных сервисов не требуются.',
    'settings.offline_mode_toggle':'Работать без облачных API','btn.test_local_services':'Проверить локальные сервисы',
    'status.offline_enabled':'Включен','status.offline_disabled':'Выключен',
    'btn.export_csv':'📥 CSV',

    'placeholder.eleven_key_set':'ключ задан (введите новый для замены)',
    'placeholder.twitch_secret_set':'секрет задан (введите новый чтобы заменить)',
    'security.auth_panel':'Авторизация панели','security.local_no_password':'Локальный доступ без пароля','security.network_auth':'Сетевой доступ с паролем','security.token_encryption':'Шифрование токенов','security.helix_api':'Twitch Helix API','security.device_oauth':'Device OAuth',
    'security.plaintext_warning':'⚠️ Внимание: токены и API-ключи хранятся в БД без шифрования. Панель доступна только с этого компьютера. Настройте TOKEN_ENCRYPTION_KEY.',
    'settings.security_desc':'На localhost панель работает без пароля. Для доступа из сети нужны PANEL_AUTH_USER, PANEL_AUTH_PASS и TOKEN_ENCRYPTION_KEY.',
    'settings.theme_hint':'Выберите фоновый градиент для панели',
    'btn.download_backup':'📥 Скачать бэкап',
    'faq.q1':'Как добавить бота?','faq.a1':'Раздел «Боты» → «+ Добавить бота» → введите ник и OAuth-токен (twitchtokengenerator.com)',
    'faq.q2':'Как настроить разное поведение в разных каналах?','faq.a2':'Боты → Настроить → Каналы → Per-channel overrides. Выберите канал и задайте юмор/сарказм отдельно для него.',
    'faq.q3':'Как настроить TTS?','faq.a3':'Боты → Настроить → «🔊 TTS»: выберите провайдер и голос. Для OBS: скопируйте URL TTS-виджета и добавьте как Browser Source.',
    'faq.q4':'Как работает фильтр внимания?','faq.a4':'Боты → Настроить → Внимание. Бот собирает сообщения в батч в течение N секунд, фильтрует шум (+1, KEKW) и генерирует один ответ.',
    'label.status_checked_note':'Ключи и подключения проверяются без отображения секретов.',
    'status.configured':'Настроен','status.not_configured':'Не настроен',
    'toast.status_unavailable':'Состояние недоступно: {detail}',
    'toast.checking':'Проверяю...','toast.unknown_error':'ошибка',
    'toast.local_services_not_ready':'Локальные сервисы: {count} не готовы','toast.local_services_ready':'Локальные сервисы готовы',
    'toast.providers_check_done':'Проверка завершена: {count} не готовы','toast.providers_all_ready':'Все провайдеры готовы',
});
Object.assign(LANGS.en, {'tab.voice_clones':'Voice clones','tts.clone_manage':'Voice clone management','tts.upload_model':'Upload Piper model','tts.setup_guide':'Setup guide','status.no_clones':'No voice clones','status.uploaded':'Voice model uploaded','label.emotion':'Emotion','label.observation_only':'Observe only','tab.overview':'📌 Overview','tab.identity':'🎭 Identity','tab.ai_tts':'🧠 AI & TTS','tab.flow':'📡 Channels & triggers','tab.memory_knowledge':'🧠 Memory & knowledge','tab.advanced':'⚙️ Advanced','tab.sandbox':'🧪 Sandbox','analytics.sentiment_title':'Chat mood','analytics.wordcloud_title':'Popular words','botfiles.title':'📁 Bot files','botfiles.hint':'Text files (json/md/txt) up to 256 KB. Edit bot prompts and memory right here.','botfiles.empty':'No files yet','confirm.delete_file':'Delete this file?',
    'widgets.grid_hint':'Open the URL in OBS Browser Source. All widgets have a transparent background and support dark/light theme.',
    'widget.tts.title':'🔊 TTS Voice','widget.tts.desc':'Chat message voiceover (Web Speech API)',
    'widget.goals.title':'🎯 Goals','widget.goals.desc':'Goals progress bar (donate/sub/follow)',
    'widget.now_playing.title':'🎵 Now Playing','widget.now_playing.desc':'Current track (Last.fm / Spotify)',
    'widget.sub_goal.title':'⭐ Sub goal','widget.sub_goal.desc':'Subscriber counter',
    'widget.schedule.title':'📅 Schedule','widget.schedule.desc':'Live now / coming up',
    'widget.uptime.title':'⏱ Uptime','widget.uptime.desc':'REC / stream duration',
    'widget.counter.title':'🔔 Counter','widget.counter.desc':'Counter (death/streak/custom)',
    'widget.follower_ticker.title':'🏃 Follower Ticker','widget.follower_ticker.desc':'Scrolling event ticker',
    'widget.lower_third.title':'🏷 Lower Third','widget.lower_third.desc':'Name + tagline banner',
    'widget.mascot.title':'🐾 Mascot','widget.mascot.desc':'Animal with reactions',
    'widget.chat_highlight.title':'💬 Chat Highlight','widget.chat_highlight.desc':'Highlight chat messages',
    'widget.chat_roulette.title':'🎲 Chat Roulette','widget.chat_roulette.desc':'Random chat message',
    'widget.combo_counter.title':'🔥 Combo Counter','widget.combo_counter.desc':'Repeated-message combo counter',
    'widget.animated_bg.title':'❄️ Animated BG','widget.animated_bg.desc':'Animated background (snow, rain, leaves)',
    'widget.anime_runner.title':'🕺 Anime Runner','widget.anime_runner.desc':'Anime runner in the corner',
    'widget.countdown.title':'🎯 Countdown','widget.countdown.desc':'Countdown to an event',
    'placeholder.client_id':'your client_id','placeholder.client_secret':'your client_secret',
    'settings.provider_status':'🩺 Provider status','btn.test_all':'🔌 Test all',
    'settings.offline_mode':'🛡️ Offline mode','settings.offline_mode_desc':'Force Ollama for AI/Vision and Piper/Web Speech for voice. Cloud API keys are not required.',
    'settings.offline_mode_toggle':'Work without cloud APIs','btn.test_local_services':'Test local services',
    'status.offline_enabled':'Enabled','status.offline_disabled':'Disabled',
    'btn.export_csv':'📥 CSV',

    'placeholder.eleven_key_set':'key set (enter new to replace)',
    'placeholder.twitch_secret_set':'secret set (enter new to replace)',
    'security.auth_panel':'Panel authorization','security.local_no_password':'Local access without a password','security.network_auth':'Password-protected network access','security.token_encryption':'Token encryption','security.helix_api':'Twitch Helix API','security.device_oauth':'Device OAuth',
    'security.plaintext_warning':'⚠️ Warning: tokens and API keys are stored unencrypted in the database. The panel is available only from this computer. Configure TOKEN_ENCRYPTION_KEY.',
    'settings.security_desc':'The panel needs no password on localhost. Network access requires PANEL_AUTH_USER, PANEL_AUTH_PASS, and TOKEN_ENCRYPTION_KEY.',
    'settings.theme_hint':'Choose a background gradient for the panel',
    'btn.download_backup':'📥 Download backup',
    'faq.q1':'How do I add a bot?','faq.a1':'"Bots" section → "+ Add bot" → enter nickname and OAuth token (twitchtokengenerator.com)',
    'faq.q2':'How do I configure different behavior per channel?','faq.a2':'Bots → Configure → Channels → Per-channel overrides. Select a channel and set humor/sarcasm for it separately.',
    'faq.q3':'How do I configure TTS?','faq.a3':'Bots → Configure → “🔊 TTS”: choose a provider and voice. For OBS: copy the TTS widget URL and add it as a Browser Source.',
    'faq.q4':'How does the attention filter work?','faq.a4':'Bots → Configure → Attention. The bot batches messages for N seconds, filters noise (+1, KEKW), and generates one reply.',
    'label.status_checked_note':'Keys and connections are checked without exposing secrets.',
    'status.configured':'Configured','status.not_configured':'Not configured',
    'toast.status_unavailable':'Status unavailable: {detail}',
    'toast.checking':'Checking...','toast.unknown_error':'error',
    'toast.local_services_not_ready':'Local services: {count} not ready','toast.local_services_ready':'Local services ready',
    'toast.providers_check_done':'Check complete: {count} not ready','toast.providers_all_ready':'All providers ready',
});
Object.assign(LANGS.ua, {'tab.voice_clones':'Голосові клони','tts.clone_manage':'Керування голосовими клонами','tts.upload_model':'Завантажити Piper-модель','tts.setup_guide':'Гайд з налаштування','status.no_clones':'Клонів голосу немає','status.uploaded':'Голосову модель завантажено','label.emotion':'Емоція','label.observation_only':'Тільки спостерігає','tab.overview':'📌 Огляд','tab.identity':'🎭 Характер','tab.ai_tts':'🧠 AI і TTS','tab.flow':'📡 Канали й тригери','tab.memory_knowledge':'🧠 Памʼять і знання','tab.advanced':'⚙️ Додатково','tab.sandbox':'🧪 Пісочниця','analytics.sentiment_title':'Настрій чату','analytics.wordcloud_title':'Популярні слова','botfiles.title':'📁 Файли бота','botfiles.hint':'Текстові файли (json/md/txt) до 256 КБ. Промпти й памʼять бота можна редагувати тут.','botfiles.empty':'Файлів ще немає','confirm.delete_file':'Видалити цей файл?',
    'widgets.grid_hint':'Відкрийте URL у Browser Source OBS. Усі віджети — прозорий фон, підтримують dark/light тему.',
    'widget.tts.title':'🔊 TTS Озвучення','widget.tts.desc':'Озвучення повідомлень чату (Web Speech API)',
    'widget.goals.title':'🎯 Цілі','widget.goals.desc':'Прогрес-бар цілей (donate/sub/follow)',
    'widget.now_playing.title':'🎵 Зараз грає','widget.now_playing.desc':'Поточний трек (Last.fm / Spotify)',
    'widget.sub_goal.title':'⭐ Sub-ціль','widget.sub_goal.desc':'Лічильник підписок',
    'widget.schedule.title':'📅 Розклад','widget.schedule.desc':'Зараз на стримі / скоро',
    'widget.uptime.title':'⏱ Uptime','widget.uptime.desc':'REC / тривалість стриму',
    'widget.counter.title':'🔔 Counter','widget.counter.desc':'Лічильник (death/streak/custom)',
    'widget.follower_ticker.title':'🏃 Follower Ticker','widget.follower_ticker.desc':'Рядок подій, що біжить',
    'widget.lower_third.title':'🏷 Lower Third','widget.lower_third.desc':'Плашка ім\'я + tagline',
    'widget.mascot.title':'🐾 Маскот','widget.mascot.desc':'Звірок з реакціями',
    'widget.chat_highlight.title':'💬 Chat Highlight','widget.chat_highlight.desc':'Виділення повідомлень чату',
    'widget.chat_roulette.title':'🎲 Chat Roulette','widget.chat_roulette.desc':'Випадкове повідомлення з чату',
    'widget.combo_counter.title':'🔥 Combo Counter','widget.combo_counter.desc':'Лічильник комбо однакових повідомлень',
    'widget.animated_bg.title':'❄️ Animated BG','widget.animated_bg.desc':'Анімований фон (сніг, дощ, листя)',
    'widget.anime_runner.title':'🕺 Anime Runner','widget.anime_runner.desc':'Аніме-бігунок в кутку',
    'widget.countdown.title':'🎯 Countdown','widget.countdown.desc':'Зворотний відлік до події',
    'placeholder.client_id':'ваш client_id','placeholder.client_secret':'ваш client_secret',
    'settings.provider_status':'🩺 Стан провайдерів','btn.test_all':'🔌 Перевірити все',
    'settings.offline_mode':'🛡️ Офлайн-режим','settings.offline_mode_desc':'Примусово використовувати Ollama для AI/Vision і Piper/Web Speech для озвучення. Ключі хмарних сервісів не потрібні.',
    'settings.offline_mode_toggle':'Працювати без хмарних API','btn.test_local_services':'Перевірити локальні сервіси',
    'status.offline_enabled':'Увімкнено','status.offline_disabled':'Вимкнено',
    'btn.export_csv':'📥 CSV',

    'placeholder.eleven_key_set':'ключ задано (введіть новий щоб замінити)',
    'placeholder.twitch_secret_set':'секрет заданий (введіть новий щоб замінити)',
    'security.auth_panel':'Авторизація панелі','security.local_no_password':'Локальний доступ без пароля','security.network_auth':'Мережевий доступ із паролем','security.token_encryption':'Шифрування токенів','security.helix_api':'Twitch Helix API','security.device_oauth':'Device OAuth',
    'security.plaintext_warning':'⚠️ Увага: токени та API-ключі зберігаються в БД без шифрування. Панель доступна лише з цього комп’ютера. Налаштуйте TOKEN_ENCRYPTION_KEY.',
    'settings.security_desc':'На localhost панель працює без пароля. Для доступу з мережі потрібні PANEL_AUTH_USER, PANEL_AUTH_PASS і TOKEN_ENCRYPTION_KEY.',
    'settings.theme_hint':'Оберіть фоновий градієнт для панелі',
    'btn.download_backup':'📥 Скачати бекап',
    'faq.q1':'Як додати бота?','faq.a1':'Секція «Боти» → «+ Додати бота» → введіть нік та OAuth-токен (twitchtokengenerator.com)',
    'faq.q2':'Як налаштувати різну поведінку в різних каналах?','faq.a2':'Боти → Налаштувати → Канали → Per-channel overrides. Виберіть канал і задайте гумор/сарказм окремо для нього.',
    'faq.q3':'Як налаштувати TTS?','faq.a3':'Боти → Налаштувати → «🔊 TTS»: виберіть провайдера та голос. Для OBS: скопіюйте URL TTS-віджета й додайте як Browser Source.',
    'faq.q4':'Як працює фільтр уваги?','faq.a4':'Боти → Налаштувати → Увага. Бот збирає повідомлення у батч протягом N секунд, фільтрує шум (+1, KEKW) та генерує одну відповідь.',
    'label.status_checked_note':'Ключі та підключення перевіряються без відображення секретів.',
    'status.configured':'Налаштовано','status.not_configured':'Не налаштовано',
    'toast.status_unavailable':'Стан недоступний: {detail}',
    'toast.checking':'Перевіряю...','toast.unknown_error':'помилка',
    'toast.local_services_not_ready':'Локальні сервіси: {count} не готові','toast.local_services_ready':'Локальні сервіси готові',
    'toast.providers_check_done':'Перевірку завершено: {count} не готові','toast.providers_all_ready':'Усі провайдери готові',
});

// Bots.html i18n keys (added to fix residual Ukrainian text in RU/EN modes)
Object.assign(LANGS.ru, {
    'affinity.auto_update':'Автообновление ботом','affinity.title':'🔁 Привязанность','affinity.to_chat':'К чату','affinity.to_streamer':'К стримеру',
    'attention.chat_only':'💬 Только чат','attention.custom':'🎯 Выборочный','attention.everyone':'👥 Все','attention.streamer_and_chat':'👑💬 Стример + чат','attention.streamer_only':'👑 Только стример',
    'attention.window_title':'Время, в течение которого бот собирает сообщения перед одним ответом','attention.max_batch_title':'Максимальное число сообщений в одной группе',
    'behavior.analyzer_title':'⚙️ Анализатор чата','bot.ai_override_hint':'Пусто = наследовать глобальные настройки','bot.ai_override_title':'🧠 AI Мозг (переопределение)','label.vision_mode':'Vision-модель','bot.vision_shared':'Общая (по умолчанию)','bot.vision_own':'Своя','bot.vision_own_ph':'модель vision для «своя»','bot.fallback_ollama':'Резерв: локальная Ollama','bot.fallback_ollama_hint':'Если облачный провайдер упал (лимит, ошибка сервера), бот временно отвечает через локальную Ollama. По умолчанию выключен — включается отдельно для этого бота.','bot.smart_routing_title':'🧭 Smart-routing (чат-модели)','bot.smart_routing_enable':'Переключать модель по сложности промпта','bot.smart_routing_threshold':'Порог длины (символы)','bot.smart_routing_simple_p':'Простой → провайдер','bot.smart_routing_simple_m':'Простой → модель','bot.smart_routing_complex_p':'Сложный → провайдер','bot.smart_routing_complex_m':'Сложный → модель','bot.smart_routing_hint':'Короткие реплики уходят на дешёвую модель, длинные и контекстные — на сильную. Пустые поля = не менять.',
    'btn.add_channel':'+ Канал','btn.add_event':'+ Добавить event','btn.add_example':'+ Пример','btn.add_override':'+ Override','btn.add_pattern':'+ Добавить pattern','btn.add_trigger':'+ Добавить trigger',
    'btn.analyze_style':'🧬 Проанализировать стиль','btn.ban':'+ Забанить','btn.create':'Создать','btn.create_clone':'Создать клон','btn.export':'📤 Экспорт','btn.import':'📥 Импорт',
    'btn.save_affinity':'💾 Сохранить привязанность','btn.save_snippet':'+ Сохранить',
    'channels.overrides_desc':'Настройте характер бота отдельно для каждого канала: значения переопределяют персону только в этом канале.','channels.per_channel_overrides':'🎛️ Per-channel overrides','channels.title':'📺 Каналы',
    'emotion.angry':'😠 Злая','emotion.happy':'😊 Радостная','emotion.neutral':'😐 Нейтральная','emotion.sad':'😢 Грустная',
    'events.description':'Event — это событие Twitch (follow, sub, raid, cheer, points). Бот может ответить AI или шаблоном.','events.title':'🔔 Events (события Twitch)',
    'filters.banlist_desc':'Пользователи, которых бот игнорирует.','filters.banlist_title':'🚫 Banlist (чёрный список)','filters.title':'🛡️ Фильтры',
    'filters.wordfilter_desc':'Слова, которые нужно избегать или заменять.','filters.wordfilter_title':'📝 Wordfilter (фильтр слов)',
    'chat_users.title':'👥 Пользователи чата','chat_users.description':'Список пользователей, которых бот видел в чате. Отключите конкретного пользователя, чтобы бот перестал ему отвечать — без глобального Twitch-бана.',
    'chat_users.search_placeholder':'🔍 Поиск по нику...','chat_users.all_roles':'Все роли','chat_users.messages_short':'сообщ.',
    'chat_users.enabled':'Разрешён','chat_users.disabled':'Отключён','chat_users.toast_enabled':'Пользователь снова разрешён','chat_users.toast_disabled':'Пользователь отключён',
    'empty.no_chat_users':'Пользователей чата пока нет — появятся после первых сообщений',
    'label.role_mod':'модератор','label.role_vip':'VIP','label.role_subscriber':'подписчик',
    'gender.bi':'би','gender.female':'жен','gender.male':'муж','gender.other':'другое','gender.trans':'трансгендер',
    'knowledge.title':'📚 База знаний стримера','label.age':'Возраст','label.ai_provider':'AI Провайдер','label.biography_freetext':'Биография (свободный текст)',
    'label.channel_optional_add':'Канал (опционально, добавить сразу)','label.city':'Город','label.event_required':'Событие *','label.favorite_games':'Любимые игры (через запятую)',
    'label.favorite_phrases':'Любимые фразы (через запятую)','label.first_name':'Имя','label.gender':'Пол','label.keyword_required':'Ключевое слово *','label.language':'Язык',
    'label.mimic_chatter':'Копировать поведение чатера','label.name_required':'Название *','label.oauth_token_required':'OAuth токен *','label.occupation':'Занятие',
    'label.personality_traits':'Черты характера (через запятую)','label.proxy_optional':'Прокси (опционально)','label.reply_chance_percent':'Шанс ответа, %',
    'label.response_empty_for_ai':'Ответ (оставьте пустым для AI)','label.response_empty_for_ai_short':'Ответ (пусто для AI)','label.response_style':'Стиль ответа',
    'label.system_prompt_required':'System prompt *','label.text_required':'Текст *','label.twitch_nickname_required':'Никнейм Twitch *','label.use_ai':'Использовать AI',
    'mimicry.description':'Добавляйте реальные реплики стримера, чтобы бот подстраивал лексику и манеру ответа.','mimicry.title':'🎭 Mimicry стримера',
    'modal.new_bot':'🤖 Новый бот','modal.new_event':'🔔 Новое событие','modal.new_pattern':'📋 Новый pattern','modal.new_trigger':'⚡ Новый trigger',
    'option.voice_id_or_name':'ID или название',
    'persona.ai_generate':'🤖 AI-генерация','persona.character_title':'🎚️ Характер (0–100)','persona.preset_placeholder':'Пресет характера...','persona.title':'🎭 Биография',
    'settings.title':'Настройки','snippets.description':'Готовые фразы для быстрых ответов. Отправка с КД 1-2 сек между сообщениями.',
    'style.friendly':'Дружелюбный','style.silent':'Тихий','style.troll':'Тролль','style.witty':'Остроумный',
    'triggers.description':'Триггер — это ключевое слово, которое активирует ответ (AI или фиксированный).','triggers.title':'⚡ Triggers (триггеры)',
    'voiceclone.piper_note':'Piper работает локально и не отправляет записи голоса в облако. Для XTTS/Coqui/F5-TTS и ElevenLabs используйте провайдеров, настроенных в TTS.','voiceclone.upload_sample':'Загрузить sample.wav',
    'wordfilter.block':'Блокировать','wordfilter.replace':'Заменить','wordfilter.warn':'Предупреждение',
    'placeholder.bots_search':'🔍 Поиск...','placeholder.chatter_nick':'Ник чатера','placeholder.clone_name':'Название клона','placeholder.custom_gender':'Свой вариант пола',
    'placeholder.fact_or_description':'Факт или описание','placeholder.oauth_readonly':'schmoofie... (не изменять)','placeholder.snippet_name':'Название своей фразы','placeholder.snippet_text':'Текст фразы',
    'placeholder.streamer_line':'Реплика стримера','placeholder.streamer_nick_channel':'Ник стримера / канал','placeholder.tags':'Теги','placeholder.topic':'Тема',
    'placeholder.username':'ник пользователя','placeholder.vision_same_as_text':'пусто = как текстовая','placeholder.word':'слово',
});
Object.assign(LANGS.en, {
    'affinity.auto_update':'Auto-update by bot','affinity.title':'🔁 Affinity','affinity.to_chat':'To chat','affinity.to_streamer':'To streamer',
    'attention.chat_only':'💬 Chat only','attention.custom':'🎯 Custom','attention.everyone':'👥 Everyone','attention.streamer_and_chat':'👑💬 Streamer + chat','attention.streamer_only':'👑 Streamer only',
    'attention.window_title':'Time during which the bot collects messages before one reply','attention.max_batch_title':'Maximum number of messages in one group',
    'behavior.analyzer_title':'⚙️ Chat analyzer','bot.ai_override_hint':'Empty = inherit global settings','bot.ai_override_title':'🧠 AI Brain (override)','label.vision_mode':'Vision model','bot.vision_shared':'Shared (default)','bot.vision_own':'Own','bot.vision_own_ph':'vision model for “Own”','bot.fallback_ollama':'Fallback: local Ollama','bot.fallback_ollama_hint':'If the cloud provider fails (rate limit, server error), the bot temporarily replies via local Ollama. Off by default — enabled per bot.','bot.smart_routing_title':'🧭 Smart-routing (chat models)','bot.smart_routing_enable':'Switch model by prompt complexity','bot.smart_routing_threshold':'Length threshold (chars)','bot.smart_routing_simple_p':'Simple → provider','bot.smart_routing_simple_m':'Simple → model','bot.smart_routing_complex_p':'Complex → provider','bot.smart_routing_complex_m':'Complex → model','bot.smart_routing_hint':'Short replies go to a cheap model, long context-heavy ones — to a strong one. Empty fields = keep as is.',
    'btn.add_channel':'+ Channel','btn.add_event':'+ Add event','btn.add_example':'+ Example','btn.add_override':'+ Override','btn.add_pattern':'+ Add pattern','btn.add_trigger':'+ Add trigger',
    'btn.analyze_style':'🧬 Analyze style','btn.ban':'+ Ban','btn.create':'Create','btn.create_clone':'Create clone','btn.export':'📤 Export','btn.import':'📥 Import',
    'btn.save_affinity':'💾 Save affinity','btn.save_snippet':'+ Save',
    'channels.overrides_desc':'Configure the bot\u2019s persona separately for each channel: values override the persona only in that channel.','channels.per_channel_overrides':'🎛️ Per-channel overrides','channels.title':'📺 Channels',
    'emotion.angry':'😠 Angry','emotion.happy':'😊 Happy','emotion.neutral':'😐 Neutral','emotion.sad':'😢 Sad',
    'events.description':'Event — a Twitch event (follow, sub, raid, cheer, points). The bot can reply with AI or a template.','events.title':'🔔 Events (Twitch events)',
    'filters.banlist_desc':'Users the bot ignores.','filters.banlist_title':'🚫 Banlist','filters.title':'🛡️ Filters',
    'filters.wordfilter_desc':'Words to avoid or replace.','filters.wordfilter_title':'📝 Wordfilter',
    'chat_users.title':'👥 Chat Users','chat_users.description':'Users the bot has seen in chat. Disable a specific user to stop the bot replying to them — without a global Twitch ban.',
    'chat_users.search_placeholder':'🔍 Search by nickname...','chat_users.all_roles':'All roles','chat_users.messages_short':'msgs',
    'chat_users.enabled':'Allowed','chat_users.disabled':'Disabled','chat_users.toast_enabled':'User re-enabled','chat_users.toast_disabled':'User disabled',
    'empty.no_chat_users':'No chat users yet — they will appear after the first messages',
    'label.role_mod':'moderator','label.role_vip':'VIP','label.role_subscriber':'subscriber',
    'gender.bi':'bi','gender.female':'female','gender.male':'male','gender.other':'other','gender.trans':'transgender',
    'knowledge.title':'📚 Streamer knowledge base','label.age':'Age','label.ai_provider':'AI Provider','label.biography_freetext':'Biography (free text)',
    'label.channel_optional_add':'Channel (optional, add right away)','label.city':'City','label.event_required':'Event *','label.favorite_games':'Favorite games (comma-separated)',
    'label.favorite_phrases':'Favorite phrases (comma-separated)','label.first_name':'Name','label.gender':'Gender','label.keyword_required':'Keyword *','label.language':'Language',
    'label.mimic_chatter':'Copy chatter behavior','label.name_required':'Name *','label.oauth_token_required':'OAuth token *','label.occupation':'Occupation',
    'label.personality_traits':'Personality traits (comma-separated)','label.proxy_optional':'Proxy (optional)','label.reply_chance_percent':'Reply chance, %',
    'label.response_empty_for_ai':'Response (leave empty for AI)','label.response_empty_for_ai_short':'Response (empty for AI)','label.response_style':'Response style',
    'label.system_prompt_required':'System prompt *','label.text_required':'Text *','label.twitch_nickname_required':'Twitch nickname *','label.use_ai':'Use AI',
    'mimicry.description':'Add real streamer lines so the bot adapts vocabulary and tone.','mimicry.title':'🎭 Streamer mimicry',
    'modal.new_bot':'🤖 New bot','modal.new_event':'🔔 New event','modal.new_pattern':'📋 New pattern','modal.new_trigger':'⚡ New trigger',
    'option.voice_id_or_name':'ID or name',
    'persona.ai_generate':'🤖 AI generation','persona.character_title':'🎚️ Character (0–100)','persona.preset_placeholder':'Character preset...','persona.title':'🎭 Biography',
    'settings.title':'Settings','snippets.description':'Ready-made phrases for quick replies. Sent with a 1-2s cooldown between messages.',
    'style.friendly':'Friendly','style.silent':'Silent','style.troll':'Troll','style.witty':'Witty',
    'triggers.description':'A trigger is a keyword that activates a reply (AI or fixed).','triggers.title':'⚡ Triggers',
    'voiceclone.piper_note':'Piper runs locally and does not send voice recordings to the cloud. For XTTS/Coqui/F5-TTS and ElevenLabs use the providers configured in TTS.','voiceclone.upload_sample':'Upload sample.wav',
    'wordfilter.block':'Block','wordfilter.replace':'Replace','wordfilter.warn':'Warning',
    'placeholder.bots_search':'🔍 Search...','placeholder.chatter_nick':'Chatter nick','placeholder.clone_name':'Clone name','placeholder.custom_gender':'Custom gender value',
    'placeholder.fact_or_description':'Fact or description','placeholder.oauth_readonly':'schmoofie... (do not change)','placeholder.snippet_name':'Name of your phrase','placeholder.snippet_text':'Phrase text',
    'placeholder.streamer_line':'Streamer line','placeholder.streamer_nick_channel':'Streamer nick / channel','placeholder.tags':'Tags','placeholder.topic':'Topic',
    'placeholder.username':'username','placeholder.vision_same_as_text':'empty = same as text','placeholder.word':'word',
});
Object.assign(LANGS.ua, {
    'affinity.auto_update':'Автооновлення ботом','affinity.title':'🔁 Прив\u02bcязаність','affinity.to_chat':'До чату','affinity.to_streamer':'До стримера',
    'attention.chat_only':'💬 Тільки чат','attention.custom':'🎯 Вибірковий','attention.everyone':'👥 Всі','attention.streamer_and_chat':'👑💬 Стример + чат','attention.streamer_only':'👑 Тільки стример',
    'attention.window_title':'Час, протягом якого бот збирає повідомлення перед однією відповіддю','attention.max_batch_title':'Максимальна кількість повідомлень в одній групі',
    'behavior.analyzer_title':'⚙️ Аналізатор чату','bot.ai_override_hint':'Порожньо = наслідувати глобальні налаштування','bot.ai_override_title':'🧠 AI Мозок (перевизначення)','label.vision_mode':'Vision-модель','bot.vision_shared':'Спільна (за замовчуванням)','bot.vision_own':'Власна','bot.vision_own_ph':'модель vision для «Власна»','bot.fallback_ollama':'Резерв: локальна Ollama','bot.fallback_ollama_hint':'Якщо хмарний провайдер впав (ліміт, помилка сервера), бот тимчасово відповідає через локальну Ollama. За замовчуванням вимкнено — вмикається окремо для цього бота.','bot.smart_routing_title':'🧭 Smart-routing (чат-моделі)','bot.smart_routing_enable':'Перемикати модель за складністю промпта','bot.smart_routing_threshold':'Поріг довжини (символи)','bot.smart_routing_simple_p':'Простий → провайдер','bot.smart_routing_simple_m':'Простий → модель','bot.smart_routing_complex_p':'Складний → провайдер','bot.smart_routing_complex_m':'Складний → модель','bot.smart_routing_hint':'Короткі репліки йдуть на дешеву модель, довгі й контекстні — на сильну. Порожні поля = не змінювати.',
    'btn.add_channel':'+ Канал','btn.add_event':'+ Додати event','btn.add_example':'+ Приклад','btn.add_override':'+ Override','btn.add_pattern':'+ Додати pattern','btn.add_trigger':'+ Додати trigger',
    'btn.analyze_style':'🧬 Проаналізувати стиль','btn.ban':'+ Забанити','btn.create':'Створити','btn.create_clone':'Створити клон','btn.export':'📤 Експорт','btn.import':'📥 Імпорт',
    'btn.save_affinity':'💾 Зберегти привʼязаність','btn.save_snippet':'+ Зберегти',
    'channels.overrides_desc':'Налаштуйте характер бота окремо для кожного каналу: значення перевизначають персону лише в цьому каналі.','channels.per_channel_overrides':'🎛️ Per-channel overrides','channels.title':'📺 Канали',
    'emotion.angry':'😠 Зла','emotion.happy':'😊 Щаслива','emotion.neutral':'😐 Нейтральна','emotion.sad':'😢 Сумна',
    'events.description':'Event — це подія Twitch (follow, sub, raid, cheer, points). Бот може відповісти AI або шаблоном.','events.title':'🔔 Events (події Twitch)',
    'filters.banlist_desc':'Користувачі, яких бот ігнорує.','filters.banlist_title':'🚫 Banlist (чорний список)','filters.title':'🛡️ Фільтри',
    'filters.wordfilter_desc':'Слова, яких треба уникати чи замінити.','filters.wordfilter_title':'📝 Wordfilter (фільтр слів)',
    'chat_users.title':'👥 Користувачі чату','chat_users.description':'Список користувачів, яких бот бачив у чаті. Вимкніть конкретного користувача, щоб бот перестав йому відповідати — без глобального Twitch-бану.',
    'chat_users.search_placeholder':'🔍 Пошук за ніком...','chat_users.all_roles':'Всі ролі','chat_users.messages_short':'повід.',
    'chat_users.enabled':'Дозволено','chat_users.disabled':'Вимкнено','chat_users.toast_enabled':'Користувача знову дозволено','chat_users.toast_disabled':'Користувача вимкнено',
    'empty.no_chat_users':'Користувачів чату ще немає — з\u2019являться після перших повідомлень',
    'label.role_mod':'модератор','label.role_vip':'VIP','label.role_subscriber':'підписник',
    'gender.bi':'бі','gender.female':'жін','gender.male':'чол','gender.other':'інше','gender.trans':'трансгендер',
    'knowledge.title':'📚 База знань стримера','label.age':'Вік','label.ai_provider':'AI Провайдер','label.biography_freetext':'Біографія (вільний текст)',
    'label.channel_optional_add':'Канал (опційно, додати одразу)','label.city':'Місто','label.event_required':'Подія *','label.favorite_games':'Улюблені ігри (через кому)',
    'label.favorite_phrases':'Улюблені фрази (через кому)','label.first_name':'Ім\u02bcя','label.gender':'Стать','label.keyword_required':'Ключове слово *','label.language':'Мова',
    'label.mimic_chatter':'Копіювати поведінку чатера','label.name_required':'Назва *','label.oauth_token_required':'OAuth токен *','label.occupation':'Заняття',
    'label.personality_traits':'Черти характеру (через кому)','label.proxy_optional':'Проксі (опційно)','label.reply_chance_percent':'Шанс відповіді, %',
    'label.response_empty_for_ai':'Відповідь (залиште порожнім для AI)','label.response_empty_for_ai_short':'Відповідь (порожньо для AI)','label.response_style':'Стиль відповіді',
    'label.system_prompt_required':'System prompt *','label.text_required':'Текст *','label.twitch_nickname_required':'Нікнейм Twitch *','label.use_ai':'Використовувати AI',
    'mimicry.description':'Додавайте реальні репліки стримера, щоб бот підлаштовував лексику і манеру відповіді.','mimicry.title':'🎭 Mimicry стримера',
    'modal.new_bot':'🤖 Новий бот','modal.new_event':'🔔 Нова подія','modal.new_pattern':'📋 Новий pattern','modal.new_trigger':'⚡ Новий trigger',
    'option.voice_id_or_name':'ID або назва',
    'persona.ai_generate':'🤖 AI-генерація','persona.character_title':'🎚️ Характер (0–100)','persona.preset_placeholder':'Пресет характеру...','persona.title':'🎭 Біографія',
    'settings.title':'Налаштування','snippets.description':'Готові фрази для швидких відповідей. Відправка з КД 1-2 сек між повідомленнями.',
    'style.friendly':'Дружній','style.silent':'Тихий','style.troll':'Тролль','style.witty':'Дотепний',
    'triggers.description':'Тригер — це ключове слово, яке активує відповідь (AI чи фіксована).','triggers.title':'⚡ Triggers (тригери)',
    'voiceclone.piper_note':'Piper працює локально і не відправляє записи голосу в хмару. Для XTTS/Coqui/F5-TTS і ElevenLabs використовуйте провайдерів, налаштованих у TTS.','voiceclone.upload_sample':'Завантажити sample.wav',
    'wordfilter.block':'Блокувати','wordfilter.replace':'Замінити','wordfilter.warn':'Попередження',
    'placeholder.bots_search':'🔍 Пошук...','placeholder.chatter_nick':'Нік чатера','placeholder.clone_name':'Назва клону','placeholder.custom_gender':'Власний варіант статі',
    'placeholder.fact_or_description':'Факт або опис','placeholder.oauth_readonly':'schmoofie... (не змінювати)','placeholder.snippet_name':'Назва своєї фрази','placeholder.snippet_text':'Текст фрази',
    'placeholder.streamer_line':'Репліка стримера','placeholder.streamer_nick_channel':'Нік стримера / канал','placeholder.tags':'Теги','placeholder.topic':'Тема',
    'placeholder.username':'нік користувача','placeholder.vision_same_as_text':'порожньо = як текстова','placeholder.word':'слово',
});

// Active templates still contain a few legacy text nodes. Keep their source
// text in one table so dynamic re-renders and language changes stay consistent.
const LEGACY_I18N = {
    'Основні налаштування': 'bot.general', 'Нікнейм': 'bot.nickname', 'Статус': 'bot.status',
    'OAuth токен': 'bot.oauth', 'Проксі': 'bot.proxy', 'Зберегти': 'btn.save', 'Зберегти AI': 'btn.save_ai',
    'AI Провайдер': 'label.provider', 'Модель': 'label.model', 'API Ключ': 'label.api_key',
    'Vision модель (опційно)': 'label.vision_optional', 'Голос': 'label.voice', 'Емоція': 'label.emotion',
    'Гучність': 'label.volume', 'Швидкість': 'label.speed', 'Налаштування уваги': 'attention.title',
    'Налаштуй на що бот реагує та як батчити повідомлення.': 'attention.description',
    'Провайдер': 'label.provider', 'Порожньо = модель провайдера': 'placeholder.global_vision',
    'Основні налаштування': 'bot.general', 'Довжина відповіді': 'label.response_length',
    'Нова заготовка': 'snippet.new', 'Текст': 'label.text', 'Назва': 'label.name',
    'Згенерувати 5': 'snippets.generate', 'Заготовки (фрази)': 'snippets.title',
    'Факти про користувачів, які бот запам\'ятовує.': 'memory.description',
    'Бота не підключено': 'status.no_connected_channel', 'Всі рівні': 'label.all_levels',
    'Всі категорії': 'label.all_categories', 'Всі статуси': 'label.all_statuses',
    'Підключені': 'label.connected', 'Відключені': 'label.disconnected',
    'За іменем': 'sort.name', 'За статусом': 'sort.status', 'Відправити': 'btn.send',
    'Оновити': 'btn.refresh', 'Відновити': 'btn.restore', 'Скасувати': 'btn.cancel',
    'Каналів немає': 'bot.no_channels', 'Виберіть канал...': 'select.channel',
    'Немає даних': 'label.no_data', 'Завантаження...': 'label.loading', 'Логів немає': 'status.no_logs',
    'Скопійовано': 'toast.copied', 'Налаштування збережено': 'msg.saved',
    'Twitch приложение': 'settings.twitch_app', 'Безпека': 'settings.security', 'FAQ': 'settings.faq',
    'Фон теми': 'settings.theme_background', 'Бекап': 'settings.backup',
};

Object.assign(LANGS.ru, {
    'bot.nickname': 'Никнейм', 'bot.status': 'Статус', 'bot.oauth': 'OAuth-токен', 'bot.proxy': 'Прокси',
    'btn.save_ai': '💾 Сохранить AI', 'label.vision_optional': 'Vision-модель (необязательно)', 'label.emotion': 'Эмоция',
    'attention.description': 'Настройте, на что бот реагирует и как группировать сообщения.', 'label.response_length': 'Длина ответа',
    'label.text': 'Текст', 'label.name': 'Название', 'snippet.new': 'Новая заготовка', 'label.all_categories': 'Все категории',
    'label.all_statuses': 'Все статусы', 'sort.name': 'По имени', 'sort.status': 'По статусу', 'btn.restore': 'Восстановить',
    'select.channel': 'Выберите канал...', 'settings.twitch_app': '🟣 Twitch-приложение',
    'analytics.empty': 'Данных пока нет — как накопится, появится',
    'analytics.all_bots': 'Все боты',
    'mod.pack_title': '🧰 Пакет модератора',
    'mod.pack_hint': 'Всё, что нужно боту-модератору: автомодерация и стрим-инструменты — здесь; запикивание мата — вкладка «Чат»; blur-guard для OBS — карточка в «Виджетах».',
    'mod.pack_automod': 'Автомодерация — ниже',
    'mod.pack_stream_tools': 'Стрим-инструменты — ниже',
    'mod.pack_beep': 'Запикивание — ниже',
    'mod.pack_blur': 'Blur-guard — в «Виджетах»',
    'dirty.confirm': 'Есть несохранённые изменения. Уйти без сохранения?',
});
Object.assign(LANGS.en, {
    'bot.general': 'General settings', 'bot.nickname': 'Nickname', 'bot.status': 'Status', 'bot.oauth': 'OAuth token', 'bot.proxy': 'Proxy',
    'btn.save_ai': '💾 Save AI', 'label.vision_optional': 'Vision model (optional)', 'label.emotion': 'Emotion',
    'attention.description': 'Choose what the bot reacts to and how messages are grouped.', 'label.response_length': 'Response length',
    'label.text': 'Text', 'label.name': 'Name', 'snippet.new': 'New snippet', 'label.all_categories': 'All categories',
    'label.all_statuses': 'All statuses', 'sort.name': 'By name', 'sort.status': 'By status', 'btn.restore': 'Restore',
    'select.channel': 'Select a channel...', 'settings.twitch_app': '🟣 Twitch application',
    'analytics.empty': 'No data yet — it will appear as it accumulates',
    'analytics.all_bots': 'All bots',
    'mod.pack_title': '🧰 Moderator pack',
    'mod.pack_hint': 'Everything a moderator bot needs: automod and stream tools are here; profanity beeping lives in the “Chat” tab; the OBS blur-guard card is in “Widgets”.',
    'mod.pack_automod': 'Automod — below',
    'mod.pack_stream_tools': 'Stream tools — below',
    'mod.pack_beep': 'Beep pipeline — below',
    'mod.pack_blur': 'Blur-guard — in “Widgets”',
    'dirty.confirm': 'You have unsaved changes. Leave without saving?',
});
Object.assign(LANGS.ua, {
    'bot.general': 'Основні налаштування', 'bot.nickname': 'Нікнейм', 'bot.status': 'Статус', 'bot.oauth': 'OAuth токен', 'bot.proxy': 'Проксі',
    'btn.save_ai': '💾 Зберегти AI', 'label.vision_optional': 'Vision-модель (необовʼязково)', 'label.emotion': 'Емоція',
    'attention.description': 'Налаштуйте, на що бот реагує та як групувати повідомлення.', 'label.response_length': 'Довжина відповіді',
    'label.text': 'Текст', 'label.name': 'Назва', 'snippet.new': 'Нова заготовка', 'label.all_categories': 'Всі категорії',
    'label.all_statuses': 'Всі статуси', 'sort.name': 'За іменем', 'sort.status': 'За статусом', 'btn.restore': 'Відновити',
    'select.channel': 'Виберіть канал...', 'settings.twitch_app': '🟣 Twitch-застосунок',
    'analytics.empty': 'Даних поки немає — з’являться, як накопичаться',
    'analytics.all_bots': 'Усі боти',
    'mod.pack_title': '🧰 Пакет модератора',
    'mod.pack_hint': 'Усе, що потрібно боту-модератору: автомодерація та стрім-інструменти — тут; запиквання матів — вкладка «Чат»; blur-guard для OBS — картка у «Віджетах».',
    'mod.pack_automod': 'Автомодерація — нижче',
    'mod.pack_stream_tools': 'Стрім-інструменти — нижче',
    'mod.pack_beep': 'Запікування — нижче',
    'mod.pack_blur': 'Blur-guard — у «Віджетах»',
    'dirty.confirm': 'Є незбережені зміни. Піти без збереження?',
});
Object.assign(LANGS.ru, {
    'api.error.bad_request': 'Некорректный запрос',
    'api.error.unauthorized': 'Требуется авторизация',
    'api.error.forbidden': 'Недостаточно прав',
    'api.error.not_found': 'Запрошенные данные не найдены',
    'api.error.method_not_allowed': 'Это действие не поддерживается',
    'api.error.conflict': 'Действие конфликтует с текущим состоянием',
    'api.error.request_invalid': 'Проверьте заполненные данные',
    'api.error.rate_limited': 'Слишком много запросов — повторите позже',
    'api.error.request_failed': 'Не удалось выполнить запрос',
    'api.error.internal_error': 'Внутренняя ошибка — подробности сохранены в логах',
    'api.error.invalid_channel': 'Некорректный Twitch-канал: {channel}',
    'api.error.unknown_role': 'Неизвестная роль: {role}',
    'api.error.invalid_role_config': 'Некорректные настройки роли',
    'api.error.role_config_too_large': 'Настройки роли слишком большие',
    'api.error.unknown': 'Не удалось выполнить запрос',
});
Object.assign(LANGS.en, {
    'api.error.bad_request': 'Invalid request',
    'api.error.unauthorized': 'Authorization required',
    'api.error.forbidden': 'Insufficient permissions',
    'api.error.not_found': 'Requested data was not found',
    'api.error.method_not_allowed': 'This action is not supported',
    'api.error.conflict': 'The action conflicts with the current state',
    'api.error.request_invalid': 'Check the submitted data',
    'api.error.rate_limited': 'Too many requests — try again later',
    'api.error.request_failed': 'Could not complete the request',
    'api.error.internal_error': 'Internal error — details were saved to the logs',
    'api.error.invalid_channel': 'Invalid Twitch channel: {channel}',
    'api.error.unknown_role': 'Unknown role: {role}',
    'api.error.invalid_role_config': 'Invalid role settings',
    'api.error.role_config_too_large': 'Role settings are too large',
    'api.error.unknown': 'Could not complete the request',
});
Object.assign(LANGS.ua, {
    'api.error.bad_request': 'Некоректний запит',
    'api.error.unauthorized': 'Потрібна авторизація',
    'api.error.forbidden': 'Недостатньо прав',
    'api.error.not_found': 'Запитані дані не знайдено',
    'api.error.method_not_allowed': 'Ця дія не підтримується',
    'api.error.conflict': 'Дія конфліктує з поточним станом',
    'api.error.request_invalid': 'Перевірте надіслані дані',
    'api.error.rate_limited': 'Забагато запитів — повторіть пізніше',
    'api.error.request_failed': 'Не вдалося виконати запит',
    'api.error.internal_error': 'Внутрішня помилка — подробиці збережено в логах',
    'api.error.invalid_channel': 'Некоректний Twitch-канал: {channel}',
    'api.error.unknown_role': 'Невідома роль: {role}',
    'api.error.invalid_role_config': 'Некоректні налаштування ролі',
    'api.error.role_config_too_large': 'Налаштування ролі завеликі',
    'api.error.unknown': 'Не вдалося виконати запит',
});

const _legacySourceByNode = new WeakMap();
let _legacyObserver;
function localizeLegacyNodes() {
    const root = document.body;
    if (!root) return;
    _legacyObserver?.disconnect();
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(node => {
        if (!node.nodeValue?.trim()) return;
        if (node.parentElement?.closest('script,style,pre,code,textarea,[contenteditable],[data-user-content],.chat-msg')) return;
        const original = _legacySourceByNode.get(node) || node.nodeValue;
        const source = original.trim();
        const key = LEGACY_I18N[source];
        if (!key) return;
        _legacySourceByNode.set(node, original);
        const translated = t(key);
        if (node.nodeValue.trim() !== translated) {
            node.nodeValue = original.replace(source, translated);
        }
    });
    _legacyObserver = new MutationObserver(() => localizeLegacyNodes());
    _legacyObserver.observe(root, {childList: true, subtree: true});
}

function hasTranslation(key) {
    return Object.values(LANGS).some(labels => Object.hasOwn(labels, key));
}

function t(key, vars = {}) {
    const lang = localStorage.getItem('lang') || 'ru';
    let value = LANGS[lang]?.[key] || LANGS.ru[key] || LANGS.ru['ui.text_unavailable'] || 'Текст недоступен';
    Object.entries(vars).forEach(([name, replacement]) => {
        value = value.replaceAll(`{${name}}`, String(replacement));
    });
    return value;
}

function plural(count, forms) {
    const lang = localStorage.getItem('lang') || 'ru';
    if (lang === 'en') return `${count} ${forms[2]}`;
    const n = Math.abs(Number(count)) % 100;
    const one = n % 10 === 1 && n !== 11;
    const few = n % 10 >= 2 && n % 10 <= 4 && (n < 10 || n >= 20);
    return `${count} ${one ? forms[0] : few ? forms[1] : forms[2]}`;
}

function setLang(lang) {
    if (!LANGS[lang]) lang = 'ru';
    localStorage.setItem('lang', lang);
    document.documentElement.setAttribute('lang', lang === 'ua' ? 'uk' : lang);
    // Translate labels without replacing editable controls or their draft values.
    document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        if (hasTranslation(key)) el.textContent = t(key);
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
        el.setAttribute('placeholder', t(el.getAttribute('data-i18n-placeholder')));
    });
    document.querySelectorAll('[data-i18n-title]').forEach(el => {
        el.setAttribute('title', t(el.getAttribute('data-i18n-title')));
    });
    document.querySelectorAll('[data-i18n-aria-label]').forEach(el => {
        el.setAttribute('aria-label', t(el.getAttribute('data-i18n-aria-label')));
    });
    document.querySelectorAll('[data-i18n-alt]').forEach(el => {
        el.setAttribute('alt', t(el.getAttribute('data-i18n-alt')));
    });
    document.title = t('app.title');
    localizeLegacyNodes();
    // Подсветка активной кнопки языка
    document.querySelectorAll('.lang-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.lang === lang);
    });
    // Dynamic cards are rendered from API data and need a refresh after switching language.
    if (_allBots.length) {
        renderDashboardBots();
        if ($('botsList')) filterBots();
    }
    if (typeof refreshPanelAccessibility === 'function') refreshPanelAccessibility();
    if (typeof refreshModFeedCaptions === 'function') refreshModFeedCaptions();
    if (typeof brainAffinityLevels === 'function') brainAffinityLevels();
    if (typeof waRefreshWidgetLocale === 'function') waRefreshWidgetLocale();
    if (typeof renderDirectorState === 'function' && typeof _directorState !== 'undefined' && _directorState) {
        renderDirectorWorkerChoices();
        renderDirectorAccountChoices();
        renderDirectorState();
        if (typeof loadDirectorAudit === 'function') loadDirectorAudit();
    }
}

function initLang() {
    setLang(localStorage.getItem('lang') || 'ru');
}

// ── Navigation ──────────────────────────────────────
function showSection(name) {
    if (!confirmDirty()) return; // P8-C13: не даём уйти с несохранёнными изменениями
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    document.querySelectorAll('.nav-btn[data-section]').forEach(b => b.classList.remove('active'));
    const sec = $('section-' + name);
    const btn = document.querySelector(`[data-section="${name}"]`);
    if (sec) sec.classList.add('active');
    if (btn) btn.classList.add('active');
    history.replaceState(null, '', '#' + name);
    if (name === 'dashboard') loadDashboard();
    if (name === 'bots') loadBotsList();
    if (name === 'channels') {
        // Владелец 27.09: настройки канала — своя страница, не всплывашка; сбрасываем на список каналов
        $('channelSettingsPage')?.classList.add('hidden');
        $('channelsListView')?.classList.remove('hidden');
        loadChannelsSection();
    }
    if (name === 'director') { loadDirectorSection(); if (typeof loadDirectorStorage === 'function') loadDirectorStorage(); } // Q40: своя страница
    if (name === 'chat') initChat(); // Q25: beep-карточка переехала во вкладку модератора
    if (name === 'analytics') {
        // P8-A2/C14: вся секция; trending удалён по вердикту C14
        loadAnalytics();
        loadHeatmap();
        loadChat24h();
        loadFeedbackSummary();
        loadPerBotStatsSelect();
    }
    // Q19: вкладка «Мозг» удалена (initBrain больше не зовётся)
    if (name === 'settings') { loadSettings(); loadPanelLogTail(); }
    if (name === 'chatlogger') {
        loadChatLoggerSection();
        clearInterval(_chatLoggerTimer);
        _chatLoggerTimer = setInterval(() => {
            if ($('section-chatlogger')?.classList.contains('active')) loadChatLoggerSection();
            else clearInterval(_chatLoggerTimer);
        }, 15000);
    }
    if (name === 'widgets') { loadWidgetsAdmin(); loadChannelPointsTts(); loadTtsChatCard(); }
    if (name === 'calendar') loadCalendarSection();
    // на мобільному — ховаємо сайдбар після вибору
    if (window.innerWidth <= 768) {
        $('sidebar').classList.remove('open');
        document.querySelector('.sidebar-backdrop').classList.remove('active');
    }
}

function toggleSidebar() {
    const sb = $('sidebar');
    if (window.innerWidth <= 768) {
        sb.classList.toggle('open');
        document.querySelector('.sidebar-backdrop').classList.toggle('active', sb.classList.contains('open'));
    } else {
        sb.classList.toggle('collapsed');
        document.body.classList.toggle('sidebar-desktop-collapsed', sb.classList.contains('collapsed'));
    }
}

function enforcePanelDarkTheme() {
    document.documentElement.setAttribute('data-theme', 'dark');
    document.documentElement.style.colorScheme = 'dark';
    try { localStorage.setItem('theme', 'dark'); } catch (_) { /* Storage may be unavailable. */ }
}

function toggleTheme() {
    enforcePanelDarkTheme();
    initBgPreset();
}

// v12: Фон темы — пресеты фоновых кольорів/патернів
const THEME_PRESET_KEYS = ['--page-gradient', '--bg-card', '--bg-input', '--bg-active', '--accent', '--accent-hover', '--text', '--text-muted', '--border', '--border-light', '--sidebar-bg', '--shadow-card'];
const BG_PRESETS = [
    { id: 'default', labelKey: 'theme.default', vars: { dark: {}, light: {} } },
    { id: 'midnight', labelKey: 'theme.midnight', vars: { dark: {'--page-gradient':'linear-gradient(135deg,#0f0c29,#302b63 50%,#24243e)','--accent':'#a78bfa','--accent-hover':'#8b5cf6','--bg-card':'rgba(0,0,0,.68)','--sidebar-bg':'rgba(0,0,0,.78)'}, light: {'--page-gradient':'linear-gradient(135deg,#e8e7fa,#d7d5ef)','--accent':'#6d50c7','--accent-hover':'#5840aa','--bg-card':'rgba(255,255,255,.82)','--sidebar-bg':'rgba(255,255,255,.88)'} } },
    { id: 'ocean', labelKey: 'theme.ocean', vars: { dark: {'--page-gradient':'linear-gradient(135deg,#0c1445,#1a3a5c 50%,#0d2137)','--accent':'#35b8ff','--accent-hover':'#1595d1'}, light: {'--page-gradient':'linear-gradient(135deg,#dff5ff,#c8e5f4)','--accent':'#087eaa','--accent-hover':'#066887','--bg-card':'rgba(255,255,255,.84)'} } },
    { id: 'forest', labelKey: 'theme.forest', vars: { dark: {'--page-gradient':'linear-gradient(135deg,#0b1a0b,#1a3a1a 50%,#0d210d)','--accent':'#57d68d','--accent-hover':'#35b96d'}, light: {'--page-gradient':'linear-gradient(135deg,#e5f7e8,#ccebd3)','--accent':'#21834b','--accent-hover':'#176b3b','--bg-card':'rgba(255,255,255,.84)'} } },
    { id: 'sunset', labelKey: 'theme.sunset', vars: { dark: {'--page-gradient':'linear-gradient(135deg,#1a0a0a,#3a1a1a 50%,#21100d)','--accent':'#ff8a65','--accent-hover':'#e86642'}, light: {'--page-gradient':'linear-gradient(135deg,#fff0e9,#f5d8cb)','--accent':'#c95532','--accent-hover':'#a84427','--bg-card':'rgba(255,255,255,.84)'} } },
    { id: 'neon', labelKey: 'theme.neon', vars: { dark: {'--page-gradient':'linear-gradient(135deg,#0a0a1a,#1a0a2a 50%,#0a1a2a)','--accent':'#d946ef','--accent-hover':'#b629c9'}, light: {'--page-gradient':'linear-gradient(135deg,#f7eaff,#e3e2ff)','--accent':'#a21caf','--accent-hover':'#86198f','--bg-card':'rgba(255,255,255,.86)'} } },
    { id: 'purple', labelKey: 'theme.purple', vars: { dark: {'--page-gradient':'linear-gradient(135deg,#1a0a2e,#3a1a5c 50%,#2a0a3e)','--accent':'#b26cff','--accent-hover':'#914fe0'}, light: {'--page-gradient':'linear-gradient(135deg,#f2eaff,#e7d7ff)','--accent':'#7c3aed','--accent-hover':'#6425c2','--bg-card':'rgba(255,255,255,.84)'} } },
    { id: 'minimal', labelKey: 'theme.minimal', vars: { dark: {'--page-gradient':'linear-gradient(180deg,#111,#1a1a1a)','--accent':'#efeff1','--accent-hover':'#cfcfd4'}, light: {'--page-gradient':'linear-gradient(180deg,#fff,#ededf0)','--accent':'#34343a','--accent-hover':'#111116','--bg-card':'rgba(255,255,255,.9)'} } },
];

function applyBgPreset(presetId, persist = true) {
    const preset = BG_PRESETS.find(p => p.id === presetId) || BG_PRESETS[0];
    const root = document.documentElement;
    THEME_PRESET_KEYS.forEach(key => root.style.removeProperty(key));
    enforcePanelDarkTheme();
    Object.entries(preset.vars.dark).forEach(([key, value]) => root.style.setProperty(key, value));
    if (persist) { try { localStorage.setItem('bgPreset', preset.id); } catch (_) {} }
    // Оновлюємо активну кнопку в UI
    document.querySelectorAll('.bg-preset-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.bg === presetId);
    });
}

function initBgPreset() {
    let saved = 'default';
    try { saved = localStorage.getItem('bgPreset') || 'default'; } catch (_) {}
    applyBgPreset(saved, false);
}

// ── Global search (Ctrl+K) ──────────────────────────
const GLOBAL_SECTION_SEARCH_KEYS = {
    dashboard: ['nav.dashboard', 'title.dashboard'],
    bots: ['nav.bots', 'title.bots'],
    chat: ['nav.chat', 'title.chat'],
    analytics: ['nav.analytics', 'title.analytics'],
    brain: ['nav.brain', 'title.brain'],
    settings: ['nav.settings', 'title.settings'],
    widgets: ['nav.widgets'],
    chatlogger: ['nav.chatlogger'],
};

// Владелец 27.09 (вечер): «набрать TTS и не попасть на конкретный тумблер» —
// глобальный поиск теперь ищет и внутри карточек «Настроек», не только по
// названиям разделов. Каждая запись — id карточки (`templates/partials/settings.html`)
// + i18n-ключи, по которым её можно найти (заголовок + по смыслу).
const GLOBAL_SETTINGS_CARD_SEARCH_KEYS = {
    'settingsCard-ai_global': ['settings.ai_global'],
    'customProvidersCard': ['settings.custom_providers'],
    'settingsCard-provider_status': ['settings.provider_status'],
    'settingsCard-offline_mode': ['settings.offline_mode', 'settings.offline_mode_toggle'],
    'settingsCard-diagnostics': ['settings.diagnostics'],
    'settingsCard-twitch_api': ['settings.twitch_api'],
    'settingsCard-security': ['settings.security'],
    'settingsCard-theme_background': ['settings.theme_background'],
    'directorSkinCard': ['settings.panel_layout'],
    'settingsCard-backup': ['settings.backup'],
    'dbMaintenanceCard': ['settings.database'],
};

function findSectionBySearch(query) {
    return Object.entries(GLOBAL_SECTION_SEARCH_KEYS).find(([section, keys]) =>
        section.includes(query) || keys.some(key => Object.values(LANGS).some(labels =>
            (labels[key] || '').toLocaleLowerCase().includes(query)))
    )?.[0];
}

function findSettingsCardBySearch(query) {
    return Object.entries(GLOBAL_SETTINGS_CARD_SEARCH_KEYS).find(([, keys]) =>
        keys.some(key => Object.values(LANGS).some(labels =>
            (labels[key] || '').toLocaleLowerCase().includes(query)))
    )?.[0];
}

// Владелец 27.09 (вечер): «набрать TTS» на деле указывает не в «Настройки»
// (TTS убран оттуда решением DEC-OWNER-016, живёт только во вкладке бота),
// а в конкретную вкладку карточки бота. Ищем по стабильному id вкладки
// (не переводится по языкам), а не по надписи кнопки.
function findBotTabBySearch(query) {
    if (typeof BOT_TAB_GROUPS === 'undefined') return null;
    const allTabs = [...new Set(Object.values(BOT_TAB_GROUPS).flat())];
    return allTabs.find(tab => tab.replace(/-/g, ' ').includes(query)) || null;
}

function highlightSettingsCard(cardId) {
    const el = document.getElementById(cardId);
    if (!el) return;
    if (el.tagName === 'DETAILS' || el.closest) {
        const details = el.closest('details');
        if (details) details.open = true;
    }
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.classList.add('search-highlight');
    setTimeout(() => el.classList.remove('search-highlight'), 2000);
}

async function handleGlobalSearch(ev) {
    if (ev.key !== 'Enter') return;
    const q = ev.target.value.trim().toLowerCase();
    if (!q) return;
    const section = findSectionBySearch(q);
    if (section) { showSection(section); ev.target.value = ''; return; }
    const settingsCard = findSettingsCardBySearch(q);
    if (settingsCard) {
        showSection('settings');
        setTimeout(() => highlightSettingsCard(settingsCard), 150);
        ev.target.value = '';
        return;
    }
    // A dashboard-first search must also find bots before their list has been opened.
    if (!_allBots.length) {
        try {
            const accounts = await api('/api/accounts');
            _allBots = Array.isArray(accounts) ? accounts : (accounts.accounts || []);
        } catch (e) { /* The not-found feedback below remains useful when loading fails. */ }
    }
    const botTab = findBotTabBySearch(q);
    if (botTab) {
        showSection('bots');
        if (_allBots.length === 1) {
            // loadBotsList() refetches /api/accounts and reassigns _allBots — the
            // single-bot id must be captured BEFORE that overwrite, not read after.
            const soleBotId = _allBots[0].id;
            loadBotsList().then(() => { openBotSettings(soleBotId); showBotTab(botTab); });
        } else {
            loadBotsList();
            toast(t('search.pick_bot_for_tab'), 'info');
        }
        ev.target.value = '';
        return;
    }
    const bot = _allBots.find(b => (b.nickname || '').toLowerCase().includes(q));
    if (bot) {
        showSection('bots');
        loadBotsList().then(() => openBotSettings(bot.id));
        ev.target.value = '';
        return;
    }
    toast(t('toast.not_found'), 'info');
}

// ── WebSocket (live) ────────────────────────────────
let ws = null;
let wsRetry = 0;
function connectWS() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    try {
        ws = new WebSocket(`${proto}//${location.host}/ws`);
    } catch (e) { setTimeout(connectWS, 5000); return; }
    ws.onopen = () => { wsRetry = 0; };
    ws.onmessage = (e) => {
        let msg;
        try { msg = JSON.parse(e.data); } catch (err) { return; }
        handleWSMessage(msg);
    };
    ws.onclose = () => {
        wsRetry = Math.min(wsRetry + 1, 6);
        setTimeout(connectWS, 1000 * Math.pow(2, Math.min(wsRetry, 4)));
    };
}

function handleWSMessage(msg) {
    if (msg.type === 'mod_feed') {
        if (typeof handlePanelModFeedEvent === 'function') handlePanelModFeedEvent(msg);
    } else if (msg.type === 'chat') {
        appendLiveChat(msg);
        if (typeof appendDashboardMiniChat === 'function') appendDashboardMiniChat(msg);
        pushEvent('chat', `💬 ${msg.author}: ${msg.message}`, msg.account_id);
        if (_botStats[msg.account_id]) {
            if (msg.is_bot) _botStats[msg.account_id].sent++; else _botStats[msg.account_id].read++;
        }
    } else if (msg.type === 'ai_log') {
        pushEvent('ai', `🧠 ${msg.event}: ${msg.detail}`, msg.account_id);
        prependBotLogLive(msg);
    } else if (msg.type === 'tts') {
        pushEvent('tts', `🔊 TTS: ${msg.text || msg.message || ''}`, msg.account_id);
    } else if (msg.type === 'log') {
        pushEvent('system', `⚙️ ${msg.action || ''} ${msg.detail || ''}`.trim(), msg.account_id);
    } else if (msg.type === 'health_alert') {
        pushEvent('system', `${msg.status === 'connected' ? '🟢' : '🔴'} ${msg.detail || 'Bot status changed'}`, msg.account_id);
        if (msg.status === 'disconnected' && !(typeof popupsHidden === 'function' && popupsHidden())) toast(msg.detail || t('toast.connection_lost'), 'error');
    } else if (msg.type === 'health') {
        // §5.1: живое обновление health-индикатора без перезагрузки списка.
        const icon = msg.state === 'online' ? '🟢' : msg.state === 'error' ? '⚠️' : msg.state === 'connecting' ? '🟡' : '⚫';
        pushEvent('system', `${icon} ${msg.nickname || ''}: ${msg.state}${msg.error ? ` — ${msg.error}` : ''}`, msg.account_id);
        if (_botStatuses[msg.account_id]) {
            _botStatuses[msg.account_id] = { ..._botStatuses[msg.account_id], connected: msg.state === 'online', state: msg.state, last_error: msg.error || '' };
            renderBotsList(_allBots);
            renderDashboardBots();
        }
    }
}

// Live-лента подій на дашборді (макс 100)
const _eventFeed = [];
function pushEvent(kind, text, accountId) {
    const bot = accountId ? _allBots.find(b => b.id === accountId) : null;
    if (bot) text = `[${bot.nickname}] ${text}`;
    _eventFeed.unshift({ kind, text, t: new Date() });
    if (_eventFeed.length > 100) _eventFeed.pop();
    renderEventFeed();
}
function renderEventFeed() {
    const el = $('dashboardEvents');
    if (!el) return;
    if (!_eventFeed.length) {
        el.innerHTML = `<div class="empty-state"><div class="empty-icon">📡</div>${esc(t('empty.waiting_events'))}</div>`;
        return;
    }
    const icons = { chat: '💬', ai: '🧠', tts: '🔊', system: '⚙️' };
    el.innerHTML = _eventFeed.slice(0, 50).map(ev => `
        <div class="event-line ev-${esc(ev.kind)}">
            <span class="event-icon">${icons[ev.kind] || '•'}</span>
            <span class="event-text">${ev.modFeed ? panelModFeedEvent(ev.modFeed) : esc(ev.text)}</span>
            <span class="event-time">${fmtTime(ev.t)}</span>
        </div>
    `).join('');
}


// ── PLAN.md «Чат-логгер»: вкладка в сайдбаре (статус/токен/запуск/каналы/поиск/экспорт) ──
Object.assign(LANGS.ru, {
    'nav.chatlogger': 'Чат-логгер',
    'chatlog.account': '👤 Аккаунт логгера',
    'chatlog.start': 'Запустить',
    'chatlog.stop': 'Остановить',
    'chatlog.hint': 'Отдельная программа-зритель (НЕ бот): сидит в чужих чатах, пишет историю сообщений в базу. Нужна для «Собрать стиль чатера» и поиска по истории. Один аккаунт — десятки каналов; стримерам не видно. Токен нужен с правой chat:read.',
    'chatlog.token': 'OAuth-токен (chat:read)',
    'chatlog.nick': 'Ник аккаунта (опц.)',
    'chatlog.save_token': '🔑 Сохранить токен',
    'chatlog.channel': 'Канал для слежки',
    'chatlog.channels_hint': 'Добавь каналы стримеров, чаты которых логировать. Логгер должен быть запущен, чтобы подключиться к новым каналам.',
    'chatlog.export': '📥 Экспорт CSV',
    'chatlog.search_q': 'Текст (опц.)',
    'chatlog.history': '🔎 История',
    'chatlog.empty': 'Истории пока нет — запусти логгер, он начнёт писать чат.',
    'chatlog.token_saved': 'Токен сохранён — перезапусти логгер',
    'chatlog.state.valid': '🟢 Токен жив · до истечения {days} дн.',
    'chatlog.state.expiring': '🟡 Токен истекает через {days} дн. — обнови',
    'chatlog.state.expired': '🔴 Токен истёк — вставь новый',
    'chatlog.state.none': '⚪ Токен не задан',
    'chatlog.state.unknown': '⚪ Не удалось проверить (сеть?)',
    'chatlog.running': '▶ логгер работает',
    'chatlog.stopped': '⏸ логгер остановлен',
    'chatlog.now': '🩺 Что происходит',
    'chatlog.now_ok': '✅ Логгер работает, сидит в {n} из {total} чатов. Пишет историю (~{h24} сообщений за 24ч).',
    'chatlog.now_no_token': '⚪ Токен не задан — вставь oauth-токен ниже и нажми «Запустить».',
    'chatlog.now_expired': '🔴 Токен истёк — вставь новый и нажми «Запустить».',
    'chatlog.now_expiring': '🟡 Работает, но токен истекает через {days} дн. — заранее вставь новый (сохранить → перезапустить кнопкой).',
    'chatlog.now_not_running': '⏸ Логгер не запущен — чат не пишется. Нажми «Запустить».',
    'chatlog.now_no_channels': '⚪ Логгер запущен, но каналов нет — добавь хотя бы один канал ниже.',
    'chatlog.now_died': '🔴 Логгер похоже упал (pid-файл указывает на мёртвый процесс) — нажми «Запустить» заново.',
    'chatlog.now_unknown': '⚪ Не удалось проверить токен (сеть?) — если логгер запущен, скорее всего всё пишется.',
    'chatlog.restart_hint': 'Сменил токен? Нажми ⏹ затем ▶ — логгер перечитает его.',
    'chatlog.chan_ok': '🟢',
    'chatlog.chan_wait': '⚫',
    'chatlog.live_title': '💬 Чат канала',
    'chatlog.live_on': '▶ Live',
    'chatlog.live_off': '⏸ Live стоп',
    'chatlog.pick_channel': 'выбери канал выше',
    'chatlog.live_following': 'автопрокрутка включена',
    'chatlog.quick_reply': 'Быстрый ответ в ручной отправке Режиссёра',
});
Object.assign(LANGS.en, {
    'nav.chatlogger': 'Chat logger',
    'chatlog.account': '👤 Logger account',
    'chatlog.start': 'Start',
    'chatlog.stop': 'Stop',
    'chatlog.hint': 'A separate viewer program (NOT a bot): sits in other channels’ chats and records message history into a database. Used for “Collect chatter style” and history search. One account can follow dozens of channels; invisible to streamers. Token needs the chat:read scope.',
    'chatlog.token': 'OAuth token (chat:read)',
    'chatlog.nick': 'Account nick (opt.)',
    'chatlog.save_token': '🔑 Save token',
    'chatlog.channel': 'Channel to follow',
    'chatlog.channels_hint': 'Add streamer channels to log. The logger must be running to connect to new channels.',
    'chatlog.export': '📥 Export CSV',
    'chatlog.search_q': 'Text (opt.)',
    'chatlog.history': '🔎 History',
    'chatlog.empty': 'No history yet — start the logger and it will record the chat.',
    'chatlog.token_saved': 'Token saved — restart the logger',
    'chatlog.state.valid': '🟢 Token valid · {days} days left',
    'chatlog.state.expiring': '🟡 Token expires in {days} days — renew it',
    'chatlog.state.expired': '🔴 Token expired — paste a new one',
    'chatlog.state.none': '⚪ No token set',
    'chatlog.state.unknown': '⚪ Could not check (network?)',
    'chatlog.running': '▶ logger is running',
    'chatlog.stopped': '⏸ logger stopped',
    'chatlog.now': '🩺 What’s happening',
    'chatlog.now_ok': '✅ The logger is running, sitting in {n} of {total} chats. Recording history (~{h24} messages in 24h).',
    'chatlog.now_no_token': '⚪ No token — paste one below and press “Start”.',
    'chatlog.now_expired': '🔴 Token expired — paste a new one and press “Start”.',
    'chatlog.now_expiring': '🟡 Running, but the token expires in {days} days — paste a new one soon (Save → restart with the button).',
    'chatlog.now_not_running': '⏸ The logger is not running — nothing is being recorded. Press “Start”.',
    'chatlog.now_no_channels': '⚪ Running, but no channels — add at least one below.',
    'chatlog.now_died': '🔴 The logger seems dead (stale pid file) — press “Start” again.',
    'chatlog.now_unknown': '⚪ Could not verify the token (network?) — if the logger is running, it is probably fine.',
    'chatlog.restart_hint': 'Changed the token? Press ⏹ then ▶ — the logger will re-read it.',
    'chatlog.chan_ok': '🟢',
    'chatlog.chan_wait': '⚫',
    'chatlog.live_title': '💬 Channel chat',
    'chatlog.live_on': '▶ Live',
    'chatlog.live_off': '⏸ Live стоп',
    'chatlog.pick_channel': 'pick a channel above',
    'chatlog.live_following': 'autoscroll enabled',
    'chatlog.quick_reply': 'Quick reply in Director manual sending',
});
Object.assign(LANGS.ua, {
    'nav.chatlogger': 'Чат-логер',
    'chatlog.account': '👤 Акаунт логера',
    'chatlog.start': 'Запустити',
    'chatlog.stop': 'Зупинити',
    'chatlog.hint': 'Окрема програма-глядач (НЕ бот): сидить у чужих чатах і пише історію повідомлень у базу. Потрібна для «Зібрати стиль чатера» і пошуку по історії. Один акаунт — десятки каналів; стрімерам не видно. Токен потрібен із правом chat:read.',
    'chatlog.token': 'OAuth-токен (chat:read)',
    'chatlog.nick': 'Нік акаунта (опц.)',
    'chatlog.save_token': '🔑 Зберегти токен',
    'chatlog.channel': 'Канал для стеження',
    'chatlog.channels_hint': 'Додай канали стрімерів, чати яких логувати. Логер має бути запущений, щоб підключитися до нових каналів.',
    'chatlog.export': '📥 Експорт CSV',
    'chatlog.search_q': 'Текст (опц.)',
    'chatlog.history': '🔎 Історія',
    'chatlog.empty': 'Історії поки немає — запусти логер, він почне писати чат.',
    'chatlog.token_saved': 'Токен збережено — перезапусти логер',
    'chatlog.state.valid': '🟢 Токен живий · до закінчення {days} дн.',
    'chatlog.state.expiring': '🟡 Токен закінчується через {days} дн. — онови',
    'chatlog.state.expired': '🔴 Токен прострочений — встав новий',
    'chatlog.state.none': '⚪ Токен не заданий',
    'chatlog.state.unknown': '⚪ Не вдалося перевірити (мережа?)',
    'chatlog.running': '▶ логер працює',
    'chatlog.stopped': '⏸ логер зупинений',
    'chatlog.now': '🩺 Що відбувається',
    'chatlog.now_ok': '✅ Логер працює, сидить у {n} із {total} чатів. Пише історію (~{h24} повідомлень за 24ч).',
    'chatlog.now_no_token': '⚪ Токен не заданий — встав oauth-токен нижче й натисни «Запустити».',
    'chatlog.now_expired': '🔴 Токен прострочений — встав новий і натисни «Запустити».',
    'chatlog.now_expiring': '🟡 Працює, але токен закінчується через {days} дн. — завчасно встав новий (зберегти → перезапустити кнопкою).',
    'chatlog.now_not_running': '⏸ Логер не запущений — чат не пишеться. Натисни «Запустити».',
    'chatlog.now_no_channels': '⚪ Запущений, але каналів немає — додай хоча б один канал нижче.',
    'chatlog.now_died': '🔴 Логер схоже впав (pid-файл вказує на мертвий процес) — натисни «Запустити» знову.',
    'chatlog.now_unknown': '⚪ Не вдалося перевірити токен (мережа?) — якщо логер запущений, швидше за все все пишеться.',
    'chatlog.restart_hint': 'Змінив токен? Натисни ⏹ потім ▶ — логер перечитає його.',
    'chatlog.chan_ok': '🟢',
    'chatlog.chan_wait': '⚫',
    'chatlog.live_title': '💬 Чат каналу',
    'chatlog.live_on': '▶ Live',
    'chatlog.live_off': '⏸ Live стоп',
    'chatlog.pick_channel': 'обери канал вище',
    'chatlog.live_following': 'автопрокрутка ввімкнена',
    'chatlog.quick_reply': 'Швидка відповідь у ручному надсиланні Режисера',
});

let _chatLoggerRunning = false;
let _chatLoggerTimer = null;
let _chatLoggerState = {};

async function loadChatLoggerSection() {
    if (!$('section-chatlogger')) return;
    try {
        const st = await api('/api/chat-logger/status');
        _chatLoggerRunning = !!st.running;
        _chatLoggerState = st;

        // бейдж в шапке: работает/остановлен
        const badge = $('chatLogRunBadge');
        if (badge) {
            badge.textContent = _chatLoggerRunning ? t('chatlog.running') : t('chatlog.stopped');
            badge.classList.toggle('off', !_chatLoggerRunning);
        }

        // статус токена (честный, Twitch validate) — для «Что происходит»
        let tok = { state: 'none', login: '', expires_in_days: null };
        try { tok = await api('/api/chat-logger/token-status'); } catch (e) { tok.state = 'unknown'; }

        // «Что происходит» — человеческим языком
        const now = $('chatLogNow');
        if (now) {
            let key, vars = {};
            if (!st.configured || tok.state === 'none') key = 'chatlog.now_no_token';
            else if (tok.state === 'expired') key = 'chatlog.now_expired';
            else if (!_chatLoggerRunning) key = 'chatlog.now_not_running';
            else if (st.logger_status === 'died') key = 'chatlog.now_died';
            else if (!(st.channels || []).length) key = 'chatlog.now_no_channels';
            else if (tok.state === 'unknown') key = 'chatlog.now_unknown';
            else {
                key = 'chatlog.now_ok';
                vars = { n: st.channels_connected, total: (st.channels || []).length, h24: st.messages_24h };
            }
            if (key === 'chatlog.now_expiring') vars = { days: tok.expires_in_days };
            if (st.configured && tok.state === 'expiring' && _chatLoggerRunning && key === 'chatlog.now_ok') {
                now.innerHTML = esc(t(key, vars))
                    + `<div class="text-xs text-muted mt-1">${esc(t('chatlog.now_expiring', { days: tok.expires_in_days }))}</div>`;
            } else {
                now.innerHTML = esc(t(key, vars));
            }
        }
        const hint = $('chatLogNowHint');
        if (hint) hint.textContent = (st.configured && tok.state === 'expired') ? t('chatlog.restart_hint') : '';

        // статус токена в карточке аккаунта
        const tsb = $('chatLogTokenStatus');
        if (tsb) {
            let daysVal = tok.expires_in_days ?? '?';
            if (tok.state === 'expiring' && tok.expires_in_hours != null && tok.expires_in_hours < 24) {
                daysVal = `${tok.expires_in_hours} ч`;
            }
            const stateKey = { valid: 'chatlog.state.valid', expiring: 'chatlog.state.expiring',
                expired: 'chatlog.state.expired', none: 'chatlog.state.none',
                unknown: 'chatlog.state.unknown' }[tok.state] || 'chatlog.state.none';
            tsb.textContent = t(stateKey, { days: daysVal })
                + (tok.login ? ` · ${tok.login}` : '');
        }

        // каналы: 🟢/⚫ + счётчик сообщений по каналу
        const box = $('chatLoggerChannels');
        if (box) {
            const chans = st.channels || [];
            box.innerHTML = chans.map(c => `
                <div class="flex items-center gap-2 text-sm py-1" style="border-top:1px solid var(--border-light)">
                    <span>${c.connected ? '🟢' : '⚫'}</span>
                    <b><a href="#" onclick="clOpenLog('${esc(c.channel)}');return false" class="text-accent" title="${esc(t('chatlog.live_title'))}">#${esc(c.channel)}</a></b>
                    <span class="text-muted text-xs" style="flex:1">${c.msg_count ? `📨 ${c.msg_count}` : ''}${c.last_msg_ts ? ` · ${esc(String(c.last_msg_ts))}` : ''}</span>
                    <button class="btn btn-sm btn-danger" onclick="removeChatLoggerChannel('${esc(c.channel)}')">✕</button>
                </div>`).join('')
                || `<span class="text-xs text-muted">${esc(t('chatlog.empty'))}</span>`;
            const counter = $('chatLogChanCounter');
            if (counter) counter.textContent = `${st.channels_connected}/${chans.length}`;
            // селект «💬 Чат канала» — выбор канала без целения в ссылку
            const vsel = $('chatLogViewerSelect');
            if (vsel) {
                const cur = _clLiveChannel || vsel.value;
                vsel.innerHTML = `<option value="">— ${esc(t('chatlog.pick_channel'))} —</option>` +
                    chans.map(c => `<option value="${esc(c.channel)}" ${c.channel === cur ? 'selected' : ''}>${c.connected ? '🟢' : '⚫'} #${esc(c.channel)}</option>`).join('');
            }
        }

        const info = $('chatLoggerResults');
        if (info && !info.dataset.hasResults && st.messages_total) {
            info.innerHTML = `<span class="text-xs text-muted">📨 всего ${st.messages_total} · за 24ч ${st.messages_24h} · ${st.db_size_mb} МБ</span>`;
        }
        _updateChatLoggerRunBtn();
    } catch (e) { /* некритично */ }
}

function _updateChatLoggerRunBtn() {
    const btn = $('chatLogRunBtn');
    if (!btn) return;
    btn.innerHTML = _chatLoggerRunning
        ? `⏹ ${esc(t('chatlog.stop'))}`
        : `▶ ${esc(t('chatlog.start'))}`;
}

async function chatLoggerToggle() {
    try {
        const url = _chatLoggerRunning ? '/api/chat-logger/stop' : '/api/chat-logger/start';
        const res = await api(url, { method: 'POST' });
        toast(res.running ? t('chatlog.running') : t('chatlog.stopped'), 'success');
        await loadChatLoggerSection();
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function saveChatLoggerToken() {
    const token = ($('chatLogToken')?.value || '').trim();
    const nick = ($('chatLogNick')?.value || '').trim();
    if (!token) return toast(t('status.not_configured'), 'error');
    try {
        await api('/api/chat-logger/token', jopts('POST', { token, nick }));
        toast(t('chatlog.token_saved'), 'success');
        if ($('chatLogToken')) $('chatLogToken').value = '';
        await loadChatLoggerSection();
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function addChatLoggerChannel() {
    const ch = ($('chatLogNewChannel')?.value || '').trim();
    if (!ch) return;
    try {
        await api('/api/chat-logger/channels', jopts('POST', { channel: ch }));
        if ($('chatLogNewChannel')) $('chatLogNewChannel').value = '';
        await loadChatLoggerSection();
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function removeChatLoggerChannel(ch) {
    if (!confirm(t('confirm.delete_item'))) return;
    try {
        await api(`/api/chat-logger/channels/${encodeURIComponent(ch)}`, { method: 'DELETE' });
        await loadChatLoggerSection();
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function searchChatLogger() {
    const box = $('chatLoggerResults');
    if (!box) return;
    const user = ($('chatLogSearchUser')?.value || '').trim();
    const q = ($('chatLogSearchQ')?.value || '').trim();
    if (!user && !q) return;
    const params = new URLSearchParams();
    if (user) params.set('user', user.replace(/^@/, ''));
    if (q) params.set('q', q);
    params.set('limit', '50');
    try {
        const data = await api(`/api/chat-logger/search?${params}`);
        box.dataset.hasResults = '1';
        box.innerHTML = (data.items || []).map(r => `
            <div class="text-sm py-1" style="border-top:1px solid var(--border-light)">
                <span class="badge">#${esc(r.channel)}</span>
                <b>${esc(r.username)}</b>
                <span class="text-xs text-muted">${esc(String(r.ts))}</span>
                <div>${esc(r.message)}</div>
            </div>`).join('') || `<div class="text-muted text-sm">${esc(t('label.no_data'))}</div>`;
    } catch (e) { box.innerHTML = `<span class="text-error text-sm">${esc(e.message)}</span>`; }
}

function exportChatLoggerCsv() {
    window.open(`${API}/api/chat-logger/export.csv`, '_blank');
}

// ── Чат-логгер: просмотр чата стрима (хвост + Live) ──
let _clLiveTimer = null;
let _clLiveCursor = 0;
let _clLiveChannel = "";

function _clEsc(t) { return esc(String(t ?? "")); }

function _clRenderLines(items) {
    return items.map(r => `
        <div class="text-sm py-0.5" style="border-top:1px solid var(--border-light)">
            <span class="text-xs text-muted">${_clEsc(String(r.ts || '').slice(11, 19))}</span>
            <b>#${_clEsc(r.channel || '')}</b>
            <span class="text-accent">${_clEsc(r.username)}</span>:
            ${_clEsc(r.message)}
            <button type="button" class="btn btn-secondary btn-sm" style="padding:0 6px" data-channel="${_directorAttr(r.channel || '')}" data-username="${_directorAttr(r.username || '')}" title="${esc(t('chatlog.quick_reply'))}" aria-label="${esc(t('chatlog.quick_reply'))}" onclick="chatLogQuickReply(this.dataset.channel, this.dataset.username)">↩</button>
        </div>`).join("");
}

async function clOpenLog(channel) {
    _clLiveChannel = channel;
    const box = $('chatLogViewer');
    if (!box) return;
    box.innerHTML = `<div class="text-muted text-xs">…</div>`;
    try {
        const data = await api(`/api/chat-logger/log?channel=${encodeURIComponent(channel)}&limit=200`);
        _clLiveCursor = data.last_id || 0;
        box.innerHTML = _clRenderLines(data.items || []) || `<div class="text-muted text-xs">${esc(t('chatlog.empty'))}</div>`;
        box.scrollTop = box.scrollHeight;
        const sel = $('chatLogViewerChannel');
        if (sel) sel.textContent = '#' + channel;
        const btn = $('chatLogLiveBtn');
        if (btn) btn.classList.remove('hidden');
    } catch (e) { box.innerHTML = `<span class="text-error text-xs">${_clEsc(e.message)}</span>`; }
}

async function clLiveTick() {
    if (!_clLiveChannel) return;
    const box = $('chatLogViewer');
    if (!box) return;
    try {
        const data = await api(`/api/chat-logger/log?channel=${encodeURIComponent(_clLiveChannel)}&after_id=${_clLiveCursor}&limit=100`);
        if (data.items && data.items.length) {
            _clLiveCursor = data.last_id || _clLiveCursor;
            const stick = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
            box.insertAdjacentHTML("beforeend", _clRenderLines(data.items));
            while (box.children.length > 1000) box.removeChild(box.firstChild);
            if (stick) box.scrollTop = box.scrollHeight;
        }
    } catch (e) { /* сеть дрогнула — попробуем на следующем тике */ }
}

function clToggleLive() {
    const btn = $('chatLogLiveBtn');
    if (!btn) return;
    if (_clLiveTimer) {
        clearInterval(_clLiveTimer);
        _clLiveTimer = null;
        btn.innerHTML = `▶ ${esc(t('chatlog.live_on'))}`;
        return;
    }
    if (!_clLiveChannel) return;
    btn.innerHTML = `⏸ ${esc(t('chatlog.live_off'))}`;
    _clLiveTimer = setInterval(clLiveTick, 3000);
    clLiveTick();
}

function _clStopLive() {
    if (_clLiveTimer) { clearInterval(_clLiveTimer); _clLiveTimer = null; }
    const btn = $('chatLogLiveBtn');
    if (btn) btn.innerHTML = `▶ ${esc(t('chatlog.live_on'))}`;
}

// ── Владелец 27.09 (вечер): «Календарь недели» — новая вкладка ────
Object.assign(LANGS.ru, {
    'nav.calendar': 'Календарь',
    'calendar.title': 'Календарь недели', 'calendar.hint': 'Расписание каналов, пачек ботов и TTS-моментов на одной сетке, без переходов по разделам настроек.',
    'calendar.add': '+ Добавить событие', 'calendar.save': '💾 Сохранить', 'calendar.saved': 'Событие сохранено',
    'calendar.day': 'День недели', 'calendar.time': 'Время', 'calendar.kind': 'Тип',
    'calendar.kind_channel': 'Канал', 'calendar.kind_pack': 'Пачка ботов', 'calendar.kind_tts': 'TTS-момент',
    'calendar.event_title': 'Название', 'calendar.event_title_ph': 'Например: Эфир на test_channel',
    'calendar.channel': 'Канал', 'calendar.pack': 'Пачка ботов', 'calendar.note': 'Заметка',
    'calendar.empty_day': 'Пусто', 'calendar.error_title': 'Впишите название события',
    'calendar.error_generic': 'Не удалось сохранить событие', 'calendar.delete_confirm': 'Удалить это событие из календаря?',
    'calendar.mon': 'Понедельник', 'calendar.tue': 'Вторник', 'calendar.wed': 'Среда', 'calendar.thu': 'Четверг',
    'calendar.fri': 'Пятница', 'calendar.sat': 'Суббота', 'calendar.sun': 'Воскресенье',
    'abtest.title': '🧪 A/B тест промптов', 'abtest.enable': 'Включить A/B тест',
    'abtest.hint': 'Несколько вариантов системного промпта конкурируют по весу; бот подставляет случайный включённый вариант и считает лайки/дизлайки ответов на него. Выключено — бот использует обычный системный промпт из вкладки «Характер».',
    'abtest.label': 'Ярлык', 'abtest.weight': 'Вес', 'abtest.system_prompt': 'Системный промпт варианта',
    'abtest.system_prompt_ph': 'Ты — саркастичный комментатор...', 'abtest.add': '+ Добавить вариант',
    'abtest.empty': 'Вариантов ещё нет — добавьте хотя бы два, чтобы сравнивать.',
    'abtest.no_data': 'Данных пока нет — станут видны после первых ответов бота.',
    'abtest.responses': 'Ответов', 'abtest.like_ratio': 'Доля лайков', 'abtest.leader': 'Лидер',
    'abtest.rec_leader': '🏆 лидер', 'abtest.rec_drop': '⚠ стоит выключить',
    'abtest.error_prompt': 'Впишите системный промпт варианта', 'abtest.saved': 'Вариант сохранён',
    'search.pick_bot_for_tab': 'Это настройка внутри карточки бота — выберите бота из списка ниже.',
});
Object.assign(LANGS.en, {
    'nav.calendar': 'Calendar',
    'calendar.title': 'Weekly calendar', 'calendar.hint': 'Channel schedule, bot packs, and TTS moments on one grid, no jumping between settings sections.',
    'calendar.add': '+ Add event', 'calendar.save': '💾 Save', 'calendar.saved': 'Event saved',
    'calendar.day': 'Day of week', 'calendar.time': 'Time', 'calendar.kind': 'Type',
    'calendar.kind_channel': 'Channel', 'calendar.kind_pack': 'Bot pack', 'calendar.kind_tts': 'TTS moment',
    'calendar.event_title': 'Title', 'calendar.event_title_ph': 'E.g.: Stream on test_channel',
    'calendar.channel': 'Channel', 'calendar.pack': 'Bot pack', 'calendar.note': 'Note',
    'calendar.empty_day': 'Empty', 'calendar.error_title': 'Enter an event title',
    'calendar.error_generic': 'Could not save the event', 'calendar.delete_confirm': 'Delete this event from the calendar?',
    'calendar.mon': 'Monday', 'calendar.tue': 'Tuesday', 'calendar.wed': 'Wednesday', 'calendar.thu': 'Thursday',
    'calendar.fri': 'Friday', 'calendar.sat': 'Saturday', 'calendar.sun': 'Sunday',
    'abtest.title': '🧪 Prompt A/B test', 'abtest.enable': 'Enable A/B test',
    'abtest.hint': 'Several system prompt variants compete by weight; the bot picks a random enabled variant and tracks likes/dislikes on its replies. Off — the bot uses the regular system prompt from the Persona tab.',
    'abtest.label': 'Label', 'abtest.weight': 'Weight', 'abtest.system_prompt': 'Variant system prompt',
    'abtest.system_prompt_ph': 'You are a sarcastic commentator...', 'abtest.add': '+ Add variant',
    'abtest.empty': 'No variants yet — add at least two to compare.',
    'abtest.no_data': 'No data yet — will appear after the bot\'s first replies.',
    'abtest.responses': 'Responses', 'abtest.like_ratio': 'Like ratio', 'abtest.leader': 'Leader',
    'abtest.rec_leader': '🏆 leader', 'abtest.rec_drop': '⚠ consider dropping',
    'abtest.error_prompt': 'Enter the variant system prompt', 'abtest.saved': 'Variant saved',
    'search.pick_bot_for_tab': 'That setting lives inside a bot card — pick a bot from the list below.',
});
Object.assign(LANGS.ua, {
    'nav.calendar': 'Календар',
    'calendar.title': 'Календар тижня', 'calendar.hint': 'Розклад каналів, пачок ботів і TTS-моментів на одній сітці, без переходів по розділах налаштувань.',
    'calendar.add': '+ Додати подію', 'calendar.save': '💾 Зберегти', 'calendar.saved': 'Подію збережено',
    'calendar.day': 'День тижня', 'calendar.time': 'Час', 'calendar.kind': 'Тип',
    'calendar.kind_channel': 'Канал', 'calendar.kind_pack': 'Пачка ботів', 'calendar.kind_tts': 'TTS-момент',
    'calendar.event_title': 'Назва', 'calendar.event_title_ph': 'Наприклад: Ефір на test_channel',
    'calendar.channel': 'Канал', 'calendar.pack': 'Пачка ботів', 'calendar.note': 'Замітка',
    'calendar.empty_day': 'Порожньо', 'calendar.error_title': 'Впишіть назву події',
    'calendar.error_generic': 'Не вдалося зберегти подію', 'calendar.delete_confirm': 'Видалити цю подію з календаря?',
    'calendar.mon': 'Понеділок', 'calendar.tue': 'Вівторок', 'calendar.wed': 'Середа', 'calendar.thu': 'Четвер',
    'calendar.fri': 'Пʼятниця', 'calendar.sat': 'Субота', 'calendar.sun': 'Неділя',
    'abtest.title': '🧪 A/B тест промптів', 'abtest.enable': 'Увімкнути A/B тест',
    'abtest.hint': 'Кілька варіантів системного промпту конкурують за вагою; бот підставляє випадковий увімкнений варіант і рахує лайки/дизлайки відповідей на нього. Вимкнено — бот використовує звичайний системний промпт з вкладки «Характер».',
    'abtest.label': 'Ярлик', 'abtest.weight': 'Вага', 'abtest.system_prompt': 'Системний промпт варіанта',
    'abtest.system_prompt_ph': 'Ти — саркастичний коментатор...', 'abtest.add': '+ Додати варіант',
    'abtest.empty': 'Варіантів ще немає — додайте щонайменше два, щоб порівнювати.',
    'abtest.no_data': 'Даних поки немає — з’являться після перших відповідей бота.',
    'abtest.responses': 'Відповідей', 'abtest.like_ratio': 'Частка лайків', 'abtest.leader': 'Лідер',
    'abtest.rec_leader': '🏆 лідер', 'abtest.rec_drop': '⚠ варто вимкнути',
    'abtest.error_prompt': 'Впишіть системний промпт варіанта', 'abtest.saved': 'Варіант збережено',
    'search.pick_bot_for_tab': 'Це налаштування всередині картки бота — оберіть бота зі списку нижче.',
});
