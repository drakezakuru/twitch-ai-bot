// [P5-split] 16_tail.js ← static/app.js, исходные строки 9598–9785; грузится после предыдущего чанка, порядок = порядку строк

// ── PLAN_FEEDBACK_2908 §7.1 §9k: категории оценки ответов ──
Object.assign(LANGS.ru, {
    'feedback.categories_title': 'Что не так с ответом?',
    'feedback.cat_too_long': '📏 Слишком длинный',
    'feedback.cat_toxic': '☠ Токсичный',
    'feedback.cat_off_style': '🎭 Не в стиле бота',
    'feedback.cat_off_topic': '🎯 Не по теме',
    'feedback.cat_other': '❓ Другое',
});
Object.assign(LANGS.en, {
    'feedback.categories_title': 'What\u02bcs wrong with the reply?',
    'feedback.cat_too_long': '📏 Too long',
    'feedback.cat_toxic': '☠ Toxic',
    'feedback.cat_off_style': '🎭 Off style',
    'feedback.cat_off_topic': '🎯 Off topic',
    'feedback.cat_other': '❓ Other',
});
Object.assign(LANGS.ua, {
    'feedback.categories_title': 'Що не так з відповіддю?',
    'feedback.cat_too_long': '📏 Задовгий',
    'feedback.cat_toxic': '☠ Токсичний',
    'feedback.cat_off_style': '🎭 Не в стилі бота',
    'feedback.cat_off_topic': '🎯 Не по темі',
    'feedback.cat_other': '❓ Інше',
});

// ── PLAN_FEEDBACK_2908 §10.6: гайд «виджеты без панели» ──
Object.assign(LANGS.ru, {
    'widgets.standalone_title': '🔧 Как менять виджеты без панели',
    'widgets.standalone_hint': 'Публичные API виджетов не требуют авторизации — ими можно управлять из OBS-хоткея, Home Assistant, Streamer.bot или curl. Админ-API требует auth-сессию панели.',
});
Object.assign(LANGS.en, {
    'widgets.standalone_title': '🔧 Managing widgets without the panel',
    'widgets.standalone_hint': 'Public widget APIs need no auth — drive them from OBS hotkeys, Home Assistant, Streamer.bot or curl. Admin APIs require the panel auth session.',
});
Object.assign(LANGS.ua, {
    'widgets.standalone_title': '🔧 Керування віджетами без панелі',
    'widgets.standalone_hint': 'Публічні API віджетів не потребують авторизації — керуйте з OBS-хоткея, Home Assistant, Streamer.bot чи curl. Адмін-API вимагає auth-сесію панелі.',
});

// ── §R5 PLAN_SESSION_ROLES: дашборд «Боты по ролям» (цвета + счётчики mod-feed) ──
async function loadRolesSummary() {
    const el = $('rolesSummary');
    if (!el) return;
    try {
        const data = await api('/api/mod-feed/roles-summary');
        const bots = data.bots || [];
        if (!bots.length) {
            el.innerHTML = `<div class="empty-state"><div class="empty-icon">🧩</div><span>${esc(t('role.dash_empty'))}</span></div>`;
            return;
        }
        el.innerHTML = bots.map(b => `
            <div class="flex gap-2 items-center text-sm" style="--role-color:${esc(b.color)}">
                <span class="role-dot"></span>
                <strong>${esc(b.nickname)}</strong>
                <span class="badge role-badge" style="--role-color:${esc(b.color)}">${esc(_roleMetaLabel(b.bot_role))}</span>
                ${b.channels ? `<span class="badge">${b.channels} 📡</span>` : `<span class="text-xs text-muted">${esc(t('label.no_channels'))}</span>`}
                ${b.bot_role === 'moderator' ? `<span class="bot-card-badge">⚠ ${b.violations}</span><span class="bot-card-badge">🛡 ${b.actions}</span>` : ''}
                ${b.enabled ? '' : `<span class="text-xs text-muted">${esc(t('label.offline'))}</span>`}
            </div>`).join('');
    } catch (e) { console.error('loadRolesSummary', e); }
}

Object.assign(LANGS.ru, { 'role.dash_empty': 'Добавьте ботов — здесь появится сводка по ролям' });
Object.assign(LANGS.en, { 'role.dash_empty': 'Add bots — the role summary will appear here' });
Object.assign(LANGS.ua, { 'role.dash_empty': 'Додайте ботів — тут з\u02bcявиться зведення за ролями' });

Object.assign(LANGS.ru, {
    'chat.select_bot': 'Сначала выберите бота',
    'chat.select_channel': 'Выберите канал для отправки',
    'send.unconfirmed_hint': 'Отправлено в Twitch, но подтверждения доставки нет — проверьте появление сообщения в чате вручную.',
});
Object.assign(LANGS.en, {
    'chat.select_bot': 'Select a bot first',
    'chat.select_channel': 'Select a channel to send to',
    'send.unconfirmed_hint': 'Sent to Twitch, but delivery is not confirmed — check the chat manually to see if it appeared.',
});
Object.assign(LANGS.ua, {
    'chat.select_bot': 'Спочатку виберіть бота',
    'chat.select_channel': 'Виберіть канал для надсилання',
    'send.unconfirmed_hint': 'Надіслано в Twitch, але підтвердження доставки немає — перевірте появу повідомлення в чаті вручну.',
});


// ── §S4 Превью виджетов ──
function waWidgetPreview(widgetId, url) {
    if (!url) return;
    window.open(url, '_blank', 'width=800,height=600,menubar=no,toolbar=no');
}

Object.assign(LANGS.ru, { 'widgets.extra_title': '🧩 Контент виджетов' });
Object.assign(LANGS.en, { 'widgets.extra_title': '🧩 Widget Content' });
Object.assign(LANGS.ua, { 'widgets.extra_title': '🧩 Контент віджетів' });
