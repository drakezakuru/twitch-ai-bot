// Service captions are selected only by explicit producer metadata, never by user text.
const MOD_FEED_CAPTIONS = {
    'mod-feed.caption.rule': ['Сработал словарь/правило', 'Dictionary/rule matched', 'Спрацював словник/правило'],
    'mod-feed.caption.applied': ['Таймаут/блок применён', 'Timeout/block applied', 'Таймаут/блок застосовано'],
    'mod-feed.caption.decision_required': ['Требует решения', 'Decision required', 'Потребує рішення'],
    'mod-feed.caption.moderation': ['Модерация: {category}', 'Moderation: {category}', 'Модерація: {category}'],
    'mod-feed.caption.category_severity': ['Категория: {category} · строгость {severity}', 'Category: {category} · severity {severity}', 'Категорія: {category} · суворість {severity}'],
    'mod-feed.caption.timeout_proposal': ['Предлагаю таймаут {minutes} мин ({category})', 'Proposed timeout: {minutes} min ({category})', 'Пропоную таймаут {minutes} хв ({category})'],
    'mod-feed.caption.hotkey_timeout': ['Таймаут по хоткею', 'Hotkey timeout applied', 'Таймаут за гарячою клавішею'],
    'mod-feed.caption.failed': ['Не удалось выполнить действие', 'Action failed', 'Не вдалося виконати дію'],
    'mod-feed.caption.hotkey_warn': ['Предупреждение по хоткею', 'Hotkey warning', 'Попередження за гарячою клавішею'],
    'mod-feed.caption.hotkey_clear': ['Чат очищен по хоткею', 'Chat cleared by hotkey', 'Чат очищено за гарячою клавішею'],
    'mod-feed.caption.hotkey_applied': ['{tool}: применено', '{tool}: applied', '{tool}: застосовано'],
    'mod-feed.caption.timeout': ['Таймаут {minutes} мин', 'Timeout: {minutes} min', 'Таймаут {minutes} хв'],
    'mod-feed.caption.stream_category': ['Сменить категорию на «{value}» · {result}', 'Change category to “{value}” · {result}', 'Змінити категорію на «{value}» · {result}'],
    'mod-feed.caption.stream_title': ['Сменить название на «{value}» · {result}', 'Change title to “{value}” · {result}', 'Змінити назву на «{value}» · {result}'],
    'mod-feed.caption.stream_enable': ['Включить: {tool} · {result}', 'Enable: {tool} · {result}', 'Увімкнути: {tool} · {result}'],
    'mod-feed.caption.stream_disable': ['Выключить: {tool} · {result}', 'Disable: {tool} · {result}', 'Вимкнути: {tool} · {result}'],
    'mod-feed.caption.result.pending': ['Предложение', 'Proposal', 'Пропозиція'],
    'mod-feed.caption.result.done': ['Выполнено', 'Completed', 'Виконано'],
    'mod-feed.caption.result.failed': ['Ошибка выполнения', 'Execution failed', 'Помилка виконання'],
    'mod-feed.caption.result.scope_failed': ['Недостаточно прав Twitch: проверьте OAuth scopes бота', 'Missing Twitch permissions: check the bot’s OAuth scopes', 'Бракує прав Twitch: перевірте OAuth scopes бота'],
    'mod-feed.caption.tool.timeout': ['Таймаут', 'Timeout', 'Таймаут'],
    'mod-feed.caption.tool.warn': ['Предупреждение', 'Warning', 'Попередження'],
    'mod-feed.caption.tool.clear': ['Очистка чата', 'Clear chat', 'Очищення чату'],
    'mod-feed.caption.tool.slow_on': ['Медленный чат включён', 'Slow mode enabled', 'Повільний чат увімкнено'],
    'mod-feed.caption.tool.slow_off': ['Медленный чат выключен', 'Slow mode disabled', 'Повільний чат вимкнено'],
    'mod-feed.caption.tool.emote_on': ['Только эмодзи включено', 'Emote-only mode enabled', 'Лише емодзі увімкнено'],
    'mod-feed.caption.tool.emote_off': ['Только эмодзи выключено', 'Emote-only mode disabled', 'Лише емодзі вимкнено'],
    'mod-feed.caption.tool.unique_on': ['Уникальный чат включён', 'Unique chat enabled', 'Унікальний чат увімкнено'],
    'mod-feed.caption.tool.unique_off': ['Уникальный чат выключен', 'Unique chat disabled', 'Унікальний чат вимкнено'],
    'mod-feed.caption.tool.category': ['Категория', 'Category', 'Категорія'],
    'mod-feed.caption.tool.ai_category': ['Категория по AI', 'AI category', 'Категорія за AI'],
    'mod-feed.caption.tool.title': ['Название стрима', 'Stream title', 'Назва стріму'],
    'mod-feed.caption.tool.slow': ['Медленный чат', 'Slow mode', 'Повільний чат'],
    'mod-feed.caption.tool.follower': ['Чат для фолловеров', 'Follower-only mode', 'Чат для фоловерів'],
    'mod-feed.caption.tool.emote_only': ['Только эмодзи', 'Emote-only mode', 'Лише емодзі'],
    'mod-feed.caption.tool.unique': ['Уникальный чат', 'Unique chat', 'Унікальний чат'],
    'mod-feed.caption.voice.countdown.start': ['Таймер: старт', 'Timer: start', 'Таймер: старт'],
    'mod-feed.caption.voice.countdown.pause': ['Таймер: пауза', 'Timer: pause', 'Таймер: пауза'],
    'mod-feed.caption.voice.countdown.reset': ['Таймер: сброс', 'Timer: reset', 'Таймер: скидання'],
    'mod-feed.caption.voice.countdown.add_time': ['Таймер: добавить время', 'Timer: add time', 'Таймер: додати час'],
    'mod-feed.caption.voice.sub_goal.reset': ['Цель подписок: сброс', 'Sub goal: reset', 'Ціль підписок: скидання'],
    'mod-feed.caption.voice.sub_goal.increment': ['Цель подписок: добавить', 'Sub goal: add', 'Ціль підписок: додати'],
    'mod-feed.caption.voice.sub_goal.set': ['Цель подписок: задать значение', 'Sub goal: set value', 'Ціль підписок: задати значення'],
    'mod-feed.caption.voice.now_playing.clear': ['Сейчас играет: очистить', 'Now playing: clear', 'Зараз грає: очистити'],
    'mod-feed.caption.voice.now_playing.set': ['Сейчас играет: задать текст', 'Now playing: set text', 'Зараз грає: задати текст'],
    'mod-feed.caption.voice.lower_third.show': ['Плашка: показать', 'Lower third: show', 'Плашка: показати'],
    'mod-feed.caption.voice.lower_third.hide': ['Плашка: скрыть', 'Lower third: hide', 'Плашка: сховати'],
    'mod-feed.caption.voice.goals.add_percent': ['Цель: добавить проценты', 'Goal: add percent', 'Ціль: додати відсотки'],
    'mod-feed.caption.voice.goals.reset': ['Цель: сброс', 'Goal: reset', 'Ціль: скидання'],
};
for (const [key, values] of Object.entries(MOD_FEED_CAPTIONS)) {
    ['ru', 'en', 'ua'].forEach((lang, i) => { LANGS[lang][key] = values[i]; });
}

function modFeedField(event, field, translate = t) {
    const legacy = typeof event?.[field] === 'string' ? event[field] : '';
    const descriptor = event?.localization?.[field];
    if (!descriptor || typeof descriptor.key !== 'string' ||
        !Object.hasOwn(MOD_FEED_CAPTIONS, descriptor.key) || descriptor.key.startsWith('mod-feed.caption.result.')) return legacy;
    const params = descriptor.params ?? {};
    if (!params || typeof params !== 'object' || Array.isArray(params)) return legacy;
    const vars = {};
    for (const [, name] of MOD_FEED_CAPTIONS[descriptor.key][0].matchAll(/\{(\w+)\}/g)) {
        if (!Object.hasOwn(params, name)) return legacy;
        const value = params[name];
        if (['minutes', 'severity'].includes(name)) {
            if (!Number.isSafeInteger(value) || Math.abs(value) > 1000000000) return legacy;
        } else if (typeof value !== 'string' || value.length > 200) return legacy;
        if (name === 'tool' || name === 'result') {
            const key = `mod-feed.caption.${name}.${value}`;
            if (!Object.hasOwn(MOD_FEED_CAPTIONS, key)) return legacy;
            vars[name] = translate(key) || MOD_FEED_CAPTIONS[key][0];
        } else vars[name] = value;
    }
    const template = translate(descriptor.key) || MOD_FEED_CAPTIONS[descriptor.key][0];
    // One pass: user parameters containing {other_param} are literal content.
    return template.replace(/\{(\w+)\}/g, (match, name) => Object.hasOwn(vars, name) ? String(vars[name]) : match);
}

function panelModFeedField(event, field) {
    const content = {text: event.text, action: event.action, localization: event.localization};
    const data = esc(JSON.stringify(content)).replace(/"/g, '&quot;');
    return `<span data-mod-feed-field="${esc(field)}" data-mod-feed-event="${data}" data-user-content>${esc(modFeedField(content, field))}</span>`;
}

function panelModFeedEvent(event) {
    const bot = _allBots.find(item => item.id === event.account_id);
    const who = [bot?.nickname, event.user].filter(Boolean).join(' · ');
    return `${who ? `<span data-user-content>${esc(who)}: </span>` : ''}${panelModFeedField(event, 'text')} <span class="text-muted">${panelModFeedField(event, 'action')}</span>`;
}

function handlePanelModFeedEvent(event) {
    _eventFeed.unshift({kind: 'system', text: '', modFeed: event, t: new Date()});
    if (_eventFeed.length > 100) _eventFeed.pop();
    renderEventFeed();
}

function refreshModFeedCaptions() {
    document.querySelectorAll('[data-mod-feed-field]').forEach(el => {
        try { el.textContent = modFeedField(JSON.parse(el.dataset.modFeedEvent), el.dataset.modFeedField); } catch (_) { /* Keep legacy content. */ }
    });
}

// Labels stay on leaf nodes so language changes preserve draft controls and user content.
function panelI18n(key) {
    return `<span data-i18n="${esc(key)}">${esc(t(key))}</span>`;
}
function panelI18nAttrs(key) {
    return `data-i18n-title="${esc(key)}" data-i18n-aria-label="${esc(key)}" title="${esc(t(key))}" aria-label="${esc(t(key))}"`;
}

function panelEnumI18n(prefix, value) {
    const key = prefix + value;
    return hasTranslation(key) ? panelI18n(key) : `<span data-user-content>${esc(value ?? '')}</span>`;
}

Object.assign(LANGS.ru, {
    'dynamic.kb_exported': 'Экспортировано записей: {count}', 'dynamic.kb_empty': 'В файле нет записей',
    'dynamic.kb_replace': 'Заменить ВСЮ существующую базу знаний?',
    'dynamic.kb_imported': 'Импорт: добавлено {added}, пропущено {skipped}',
    'dynamic.kb_import_failed': 'Не удалось импортировать базу знаний. Проверьте JSON-файл и соединение.',
    'dynamic.revert_confirm': 'Откатить последнее применённое изменение обучения (стиль/база знаний)?',
    'dynamic.reverted': 'Отменено: {kind}', 'dynamic.nothing_to_revert': 'Нечего откатывать',
    'dynamic.affinity_close': 'близкий', 'dynamic.affinity_regular': 'постоянный', 'dynamic.affinity_familiar': 'знакомый',
    'dynamic.affinity_viewer': 'зритель', 'dynamic.affinity_stranger': 'незнакомец',
    'dynamic.extracting': 'Извлекаю факты из истории чата…', 'dynamic.extracted': 'Найдено фактов-предложений: {count} (см. Lore)',
    'dynamic.no_new_facts': 'Новых фактов не найдено', 'dynamic.clip_rate': '{rate}/сек (ср. {average}/сек)',
    'dynamic.bot_number': 'Бот #{id}',
    'dynamic.mod.contains_link': 'Содержит ссылку', 'dynamic.mod.window_seconds': 'Окно, сек', 'dynamic.mod.similarity': 'Сходство',
    'panel.mod.cat_links': 'Ссылки', 'panel.mod.cat_caps': 'Капс', 'panel.mod.cat_repeat': 'Повтор', 'panel.mod.cat_emote': 'Эмоуты', 'panel.mod.cat_copypasta': 'Копипаста',
    'panel.mod.action_log': 'Записать в журнал', 'panel.mod.action_spam_log': 'Записать спам в журнал', 'panel.mod.action_spam_timeout_recommend': 'Рекомендовать таймаут за спам',
    'dynamic.source.bot_out': 'Ответ бота', 'dynamic.source.api_send': 'Отправка из панели', 'dynamic.source.antispam': 'Антиспам', 'dynamic.source.timeout_recommend': 'Рекомендация таймаута',
    'dynamic.ai_value': 'AI решает значение',
    'dynamic.new_fact': 'Новый факт', 'dynamic.fact': 'Факт',
    'dynamic.messages': 'Сообщений', 'dynamic.last_seen': 'Последнее появление',
    'dynamic.channel_scope': 'Видно только на этом канале', 'dynamic.all_scope': 'Видно на всех каналах',
    'dynamic.panel_log_empty': 'Файл panel.log пуст или не найден',
    'dynamic.mod.inherit': 'Как общий', 'dynamic.mod.global': 'Общий режим',
    'dynamic.mod.channel_saved': 'Режим канала обновлён', 'dynamic.mod.saved': 'Настройки модерации сохранены',
    'dynamic.mod.rule_added': 'Правило добавлено', 'dynamic.mod.imported': 'Импортировано: {count}',
    'dynamic.mod.day': 'За 24 часа', 'dynamic.mod.week': 'За 7 дней', 'dynamic.mod.top': 'Частые нарушители',
    'dynamic.mod.empty': 'Нарушений не зафиксировано.', 'dynamic.mod.clear_confirm': 'Очистить журнал нарушений этого бота?',
    'dynamic.mod.cleared': 'Журнал очищен', 'dynamic.mod.severity': 'Тяжесть', 'dynamic.mod.match': 'Совпадение',
    'dynamic.mod.verdict': 'Вердикт', 'dynamic.mod.clean': 'Чисто: нарушений не найдено.',
    'dynamic.status.approved': 'Подтверждено', 'dynamic.status.rejected': 'Отклонено', 'dynamic.status.suggested': 'Предложено',
    'dynamic.status.applied': 'Применено', 'dynamic.status.reverted': 'Отменено', 'dynamic.status.pending': 'Ожидает',
    'dynamic.status.done': 'Готово', 'dynamic.status.failed': 'Ошибка', 'dynamic.status.running': 'Выполняется',
    'dynamic.approve': 'Подтвердить', 'dynamic.reject': 'Отклонить', 'dynamic.apply': 'Применить', 'dynamic.revert': 'Отменить изменение',
    'dynamic.learning_empty': 'Предложений нет. Они появляются из отзывов, реакций зрителей и чата.',
    'dynamic.source': 'Источник', 'dynamic.importance': 'Важность', 'dynamic.priority': 'Приоритет',
    'dynamic.pick_bot': 'Выберите бота', 'dynamic.enter_fact': 'Введите факт', 'dynamic.fact_added': 'Факт добавлен',
    'dynamic.run_channel': 'Для прогона выберите конкретный канал рядом с ботом', 'dynamic.run_period': 'Задайте период', 'dynamic.run_started': 'Прогон запущен',
    'dynamic.export_md': 'Экспорт Markdown', 'dynamic.export_json': 'Экспорт JSON', 'dynamic.empty': '(пусто)',
    'dynamic.unconfirm': 'Снять подтверждение', 'dynamic.confirm_fact': 'Подтвердить: хранится дольше и используется первым',
    'dynamic.edit_fact': 'Редактировать приоритет и срок хранения', 'dynamic.expires': 'До',
    'dynamic.ttl': 'Срок хранения, дней (0 = бессрочно)', 'dynamic.has_expiry': 'Сейчас со сроком', 'dynamic.no_expiry': 'Сейчас бессрочно',
    'dynamic.fact_updated': 'Факт обновлён', 'dynamic.scope_override': 'Переопределено для', 'dynamic.scope_inherited': 'Наследуется от настроек бота',
    'dynamic.live_saved': 'Настройки live-сводок сохранены', 'dynamic.channel_saved': 'Сохранено для #{channel}',
    'dynamic.yes': 'Да', 'dynamic.no': 'Нет',
    'dynamic.timeout_saved': 'Политика таймаутов сохранена', 'dynamic.timeout_asks': 'Ещё спрашивает',
    'dynamic.timeout_question': 'Применить таймаут?', 'dynamic.timeout_duration': '600 сек',
    'dynamic.timeout_approved': 'Таймаут применён (если есть права модератора)', 'dynamic.timeout_rejected': 'Отклонено: бот запомнил',
    'dynamic.copy': 'Копия', 'dynamic.sources': 'Источники', 'dynamic.style_failed': 'Не удалось проанализировать стиль',
    'dynamic.persona_import_failed': 'Не удалось импортировать характер',
});
Object.assign(LANGS.en, {
    'dynamic.kb_exported': 'Entries exported: {count}', 'dynamic.kb_empty': 'The file contains no entries',
    'dynamic.kb_replace': 'Replace the ENTIRE existing knowledge base?',
    'dynamic.kb_imported': 'Import: {added} added, {skipped} skipped',
    'dynamic.kb_import_failed': 'Could not import the knowledge base. Check the JSON file and connection.',
    'dynamic.revert_confirm': 'Revert the last applied learning change (style/knowledge base)?',
    'dynamic.reverted': 'Reverted: {kind}', 'dynamic.nothing_to_revert': 'Nothing to revert',
    'dynamic.affinity_close': 'close', 'dynamic.affinity_regular': 'regular', 'dynamic.affinity_familiar': 'familiar',
    'dynamic.affinity_viewer': 'viewer', 'dynamic.affinity_stranger': 'stranger',
    'dynamic.extracting': 'Extracting facts from chat history…', 'dynamic.extracted': 'Suggested facts found: {count} (see Lore)',
    'dynamic.no_new_facts': 'No new facts found', 'dynamic.clip_rate': '{rate}/sec (avg. {average}/sec)',
    'dynamic.bot_number': 'Bot #{id}',
    'dynamic.mod.contains_link': 'Contains a link', 'dynamic.mod.window_seconds': 'Window, sec', 'dynamic.mod.similarity': 'Similarity',
    'panel.mod.cat_links': 'Links', 'panel.mod.cat_caps': 'All caps', 'panel.mod.cat_repeat': 'Repetition', 'panel.mod.cat_emote': 'Emotes', 'panel.mod.cat_copypasta': 'Copypasta',
    'panel.mod.action_log': 'Log', 'panel.mod.action_spam_log': 'Log spam', 'panel.mod.action_spam_timeout_recommend': 'Recommend spam timeout',
    'dynamic.source.bot_out': 'Bot reply', 'dynamic.source.api_send': 'Sent from panel', 'dynamic.source.antispam': 'Anti-spam', 'dynamic.source.timeout_recommend': 'Timeout recommendation',
    'dynamic.ai_value': 'AI chooses the value',
    'dynamic.new_fact': 'New fact', 'dynamic.fact': 'Fact',
    'dynamic.messages': 'Messages', 'dynamic.last_seen': 'Last seen',
    'dynamic.channel_scope': 'Visible only on this channel', 'dynamic.all_scope': 'Visible on all channels',
    'dynamic.panel_log_empty': 'The panel.log file is empty or missing',
    'dynamic.mod.inherit': 'Use global mode', 'dynamic.mod.global': 'Global mode',
    'dynamic.mod.channel_saved': 'Channel mode updated', 'dynamic.mod.saved': 'Moderation settings saved',
    'dynamic.mod.rule_added': 'Rule added', 'dynamic.mod.imported': 'Imported: {count}',
    'dynamic.mod.day': 'Last 24 hours', 'dynamic.mod.week': 'Last 7 days', 'dynamic.mod.top': 'Top offenders',
    'dynamic.mod.empty': 'No violations recorded.', 'dynamic.mod.clear_confirm': 'Clear this bot’s violation log?',
    'dynamic.mod.cleared': 'Log cleared', 'dynamic.mod.severity': 'Severity', 'dynamic.mod.match': 'Match',
    'dynamic.mod.verdict': 'Verdict', 'dynamic.mod.clean': 'Clean: no violations found.',
    'dynamic.status.approved': 'Approved', 'dynamic.status.rejected': 'Rejected', 'dynamic.status.suggested': 'Suggested',
    'dynamic.status.applied': 'Applied', 'dynamic.status.reverted': 'Reverted', 'dynamic.status.pending': 'Pending',
    'dynamic.status.done': 'Done', 'dynamic.status.failed': 'Failed', 'dynamic.status.running': 'Running',
    'dynamic.approve': 'Approve', 'dynamic.reject': 'Reject', 'dynamic.apply': 'Apply', 'dynamic.revert': 'Revert change',
    'dynamic.learning_empty': 'No suggestions. They come from feedback, viewer engagement and chat.',
    'dynamic.source': 'Source', 'dynamic.importance': 'Importance', 'dynamic.priority': 'Priority',
    'dynamic.pick_bot': 'Select a bot', 'dynamic.enter_fact': 'Enter a fact', 'dynamic.fact_added': 'Fact added',
    'dynamic.run_channel': 'Select a specific channel beside the bot to start a run', 'dynamic.run_period': 'Set a time period', 'dynamic.run_started': 'Run started',
    'dynamic.export_md': 'Export Markdown', 'dynamic.export_json': 'Export JSON', 'dynamic.empty': '(empty)',
    'dynamic.unconfirm': 'Remove confirmation', 'dynamic.confirm_fact': 'Confirm: kept longer and used first',
    'dynamic.edit_fact': 'Edit priority and retention', 'dynamic.expires': 'Until',
    'dynamic.ttl': 'Retention, days (0 = forever)', 'dynamic.has_expiry': 'Currently expires', 'dynamic.no_expiry': 'Currently permanent',
    'dynamic.fact_updated': 'Fact updated', 'dynamic.scope_override': 'Overridden for', 'dynamic.scope_inherited': 'Inherited from bot settings',
    'dynamic.live_saved': 'Live summary settings saved', 'dynamic.channel_saved': 'Saved for #{channel}',
    'dynamic.yes': 'Yes', 'dynamic.no': 'No',
    'dynamic.timeout_saved': 'Timeout policy saved', 'dynamic.timeout_asks': 'Still asks',
    'dynamic.timeout_question': 'Apply timeout?', 'dynamic.timeout_duration': '600 sec',
    'dynamic.timeout_approved': 'Timeout applied (if moderator permissions allow)', 'dynamic.timeout_rejected': 'Rejected: the bot remembered',
    'dynamic.copy': 'Copy', 'dynamic.sources': 'Sources', 'dynamic.style_failed': 'Could not analyze style',
    'dynamic.persona_import_failed': 'Could not import personality',
});
Object.assign(LANGS.ua, {
    'dynamic.kb_exported': 'Експортовано записів: {count}', 'dynamic.kb_empty': 'У файлі немає записів',
    'dynamic.kb_replace': 'Замінити ВСЮ наявну базу знань?',
    'dynamic.kb_imported': 'Імпорт: додано {added}, пропущено {skipped}',
    'dynamic.kb_import_failed': 'Не вдалося імпортувати базу знань. Перевірте JSON-файл і з’єднання.',
    'dynamic.revert_confirm': 'Відкотити останню застосовану зміну навчання (стиль/база знань)?',
    'dynamic.reverted': 'Скасовано: {kind}', 'dynamic.nothing_to_revert': 'Нічого відкочувати',
    'dynamic.affinity_close': 'близький', 'dynamic.affinity_regular': 'постійний', 'dynamic.affinity_familiar': 'знайомий',
    'dynamic.affinity_viewer': 'глядач', 'dynamic.affinity_stranger': 'незнайомець',
    'dynamic.extracting': 'Видобуваю факти з історії чату…', 'dynamic.extracted': 'Знайдено фактів-пропозицій: {count} (див. Lore)',
    'dynamic.no_new_facts': 'Нових фактів не знайдено', 'dynamic.clip_rate': '{rate}/сек (сер. {average}/сек)',
    'dynamic.bot_number': 'Бот №{id}',
    'dynamic.mod.contains_link': 'Містить посилання', 'dynamic.mod.window_seconds': 'Вікно, сек', 'dynamic.mod.similarity': 'Схожість',
    'panel.mod.cat_links': 'Посилання', 'panel.mod.cat_caps': 'Капс', 'panel.mod.cat_repeat': 'Повтор', 'panel.mod.cat_emote': 'Емоути', 'panel.mod.cat_copypasta': 'Копіпаста',
    'panel.mod.action_log': 'Записати в журнал', 'panel.mod.action_spam_log': 'Записати спам у журнал', 'panel.mod.action_spam_timeout_recommend': 'Рекомендувати таймаут за спам',
    'dynamic.source.bot_out': 'Відповідь бота', 'dynamic.source.api_send': 'Надіслано з панелі', 'dynamic.source.antispam': 'Антиспам', 'dynamic.source.timeout_recommend': 'Рекомендація таймауту',
    'dynamic.ai_value': 'AI визначає значення',
    'dynamic.new_fact': 'Новий факт', 'dynamic.fact': 'Факт',
    'dynamic.messages': 'Повідомлень', 'dynamic.last_seen': 'Остання поява',
    'dynamic.channel_scope': 'Видно лише на цьому каналі', 'dynamic.all_scope': 'Видно на всіх каналах',
    'dynamic.panel_log_empty': 'Файл panel.log порожній або відсутній',
    'dynamic.mod.inherit': 'Як загальний', 'dynamic.mod.global': 'Загальний режим',
    'dynamic.mod.channel_saved': 'Режим каналу оновлено', 'dynamic.mod.saved': 'Налаштування модерації збережено',
    'dynamic.mod.rule_added': 'Правило додано', 'dynamic.mod.imported': 'Імпортовано: {count}',
    'dynamic.mod.day': 'За 24 години', 'dynamic.mod.week': 'За 7 днів', 'dynamic.mod.top': 'Часті порушники',
    'dynamic.mod.empty': 'Порушень не зафіксовано.', 'dynamic.mod.clear_confirm': 'Очистити журнал порушень цього бота?',
    'dynamic.mod.cleared': 'Журнал очищено', 'dynamic.mod.severity': 'Тяжкість', 'dynamic.mod.match': 'Збіг',
    'dynamic.mod.verdict': 'Вердикт', 'dynamic.mod.clean': 'Чисто: порушень не знайдено.',
    'dynamic.status.approved': 'Підтверджено', 'dynamic.status.rejected': 'Відхилено', 'dynamic.status.suggested': 'Запропоновано',
    'dynamic.status.applied': 'Застосовано', 'dynamic.status.reverted': 'Скасовано', 'dynamic.status.pending': 'Очікує',
    'dynamic.status.done': 'Готово', 'dynamic.status.failed': 'Помилка', 'dynamic.status.running': 'Виконується',
    'dynamic.approve': 'Підтвердити', 'dynamic.reject': 'Відхилити', 'dynamic.apply': 'Застосувати', 'dynamic.revert': 'Скасувати зміну',
    'dynamic.learning_empty': 'Пропозицій немає. Вони з’являються з відгуків, реакцій глядачів і чату.',
    'dynamic.source': 'Джерело', 'dynamic.importance': 'Важливість', 'dynamic.priority': 'Пріоритет',
    'dynamic.pick_bot': 'Виберіть бота', 'dynamic.enter_fact': 'Введіть факт', 'dynamic.fact_added': 'Факт додано',
    'dynamic.run_channel': 'Для прогону виберіть конкретний канал поруч із ботом', 'dynamic.run_period': 'Задайте період', 'dynamic.run_started': 'Прогін запущено',
    'dynamic.export_md': 'Експорт Markdown', 'dynamic.export_json': 'Експорт JSON', 'dynamic.empty': '(порожньо)',
    'dynamic.unconfirm': 'Зняти підтвердження', 'dynamic.confirm_fact': 'Підтвердити: зберігається довше та використовується першим',
    'dynamic.edit_fact': 'Редагувати пріоритет і строк зберігання', 'dynamic.expires': 'До',
    'dynamic.ttl': 'Строк зберігання, днів (0 = безстроково)', 'dynamic.has_expiry': 'Зараз зі строком', 'dynamic.no_expiry': 'Зараз безстроково',
    'dynamic.fact_updated': 'Факт оновлено', 'dynamic.scope_override': 'Перевизначено для', 'dynamic.scope_inherited': 'Успадковано з налаштувань бота',
    'dynamic.live_saved': 'Налаштування live-зведень збережено', 'dynamic.channel_saved': 'Збережено для #{channel}',
    'dynamic.yes': 'Так', 'dynamic.no': 'Ні',
    'dynamic.timeout_saved': 'Політику таймаутів збережено', 'dynamic.timeout_asks': 'Ще запитує',
    'dynamic.timeout_question': 'Застосувати таймаут?', 'dynamic.timeout_duration': '600 сек',
    'dynamic.timeout_approved': 'Таймаут застосовано (за наявності прав модератора)', 'dynamic.timeout_rejected': 'Відхилено: бот запам’ятав',
    'dynamic.copy': 'Копія', 'dynamic.sources': 'Джерела', 'dynamic.style_failed': 'Не вдалося проаналізувати стиль',
    'dynamic.persona_import_failed': 'Не вдалося імпортувати характер',
});
