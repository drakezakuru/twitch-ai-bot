// [P5-split] 15_feedback_2908.js ← static/app.js, исходные строки 8815–9597; грузится после предыдущего чанка, порядок = порядку строк

// ── PLAN_FEEDBACK_2908 §2: i18n пустых состояний (были захардкожены ru/ua) ──
Object.assign(LANGS.ru, {
    'blurguard.empty': 'Нарушений за время стрима не было',
    'channels.empty': 'Нет подключённых каналов.',
    'kb.empty': 'Пока нет фактов в базе знаний',
    'kb.channel_hint': 'Запись «все каналы» видна боту везде; для отдельного канала — только там. Выбор фильтрует список.',
    'memory.empty': 'Нет памяти о пользователях',
    'mimicry.empty': 'Нет примеров реплик стримера',
    'overrides.empty': 'Overrides нет. Добавьте, чтобы изменить характер бота в отдельном канале.',
    'sharedfacts.empty': 'Пока нет фактов. Добавьте вручную или запустите Summarizer.',
    'stats.nodata': 'Данных нет',
    'voiceclones.empty': 'Нет клонов голоса',
    'wordfilter.empty': 'Правил пока нет — работают встроенные словари.',
});
Object.assign(LANGS.en, {
    'blurguard.empty': 'No violations during the stream',
    'channels.empty': 'No connected channels.',
    'kb.empty': 'No facts in the knowledge base yet',
    'kb.channel_hint': 'An "all channels" entry is visible everywhere; a per-channel one only there. The select also filters the list.',
    'memory.empty': 'No user memory yet',
    'mimicry.empty': 'No streamer line examples yet',
    'overrides.empty': 'No overrides yet. Add one to adjust the bot in a specific channel.',
    'sharedfacts.empty': 'No facts yet. Add them manually or run the Summarizer.',
    'stats.nodata': 'No data yet',
    'voiceclones.empty': 'No voice clones yet',
    'wordfilter.empty': 'No rules yet — built-in dictionaries are active.',
});
Object.assign(LANGS.ua, {
    'blurguard.empty': 'Порушень за час стріму не було',
    'channels.empty': 'Немає підключених каналів.',
    'kb.empty': 'Ще немає фактів у базі знань',
    'kb.channel_hint': 'Запис «усі канали» видно боту всюди; для окремого каналу — лише там. Вибір фільтрує список.',
    'memory.empty': 'Немає пам\u02bcяті про користувачів',
    'mimicry.empty': 'Немає прикладів реплік стрімера',
    'overrides.empty': 'Overrides немає. Додайте, щоб змінити характер бота в окремому каналі.',
    'sharedfacts.empty': 'Ще немає фактів. Додайте вручну або запустіть Summarizer.',
    'stats.nodata': 'Даних немає',
    'voiceclones.empty': 'Немає клонів голосу',
    'wordfilter.empty': 'Правил ще немає — працюють вбудовані словники.',
});

// ── PLAN_FEEDBACK_2908 §1.1: единые тумблеры .toggle вместо чекбоксов ──
function toggleChecked(id) {
    return !!document.getElementById(id)?.classList.contains('active');
}
function setToggle(id, val) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.toggle('active', !!val);
    el.setAttribute('aria-checked', String(!!val));
}
function uiToggle(el, onChange) {
    if (!el) return;
    el.classList.toggle('active');
    const on = el.classList.contains('active');
    el.setAttribute('aria-checked', String(on));
    if (typeof onChange === 'function') onChange(on);
}
document.addEventListener('keydown', e => {
    const el = e.target;
    if (el && el.classList?.contains('toggle') && el.getAttribute?.('role') === 'switch'
        && (e.key === 'Enter' || e.key === ' ')) {
        e.preventDefault();
        el.click();
    }
});

// ── PLAN_FEEDBACK_2908 §1.3: сворачиваемые карточки (клик по заголовку, чебурашка ▸/▾, localStorage) ──
function toggleCardCollapse(card, force) {
    const collapsed = force !== undefined ? force : !card.classList.contains('collapsed');
    card.classList.toggle('collapsed', collapsed);
    const chev = card.querySelector(':scope > .card-header > .card-chevron');
    if (chev) {
        chev.textContent = collapsed ? '▸' : '▾';
        chev.setAttribute('aria-expanded', String(!collapsed));
        chev.setAttribute('data-i18n-title', collapsed ? 'ui.expand_section' : 'ui.collapse_section');
        chev.title = t(collapsed ? 'ui.expand_section' : 'ui.collapse_section');
    }
    if (card.id) localStorage.setItem('card_collapsed_' + card.id, collapsed ? '1' : '0');
}

function initCollapsibleCards(root) {
    (root || document).querySelectorAll('.card').forEach(card => {
        if (card.dataset.collapsibleInit || card.tagName === 'DETAILS') return;
        const header = card.querySelector(':scope > .card-header');
        if (!header) return;
        card.dataset.collapsibleInit = '1';
        card.classList.add('collapsible');
        if (!card.id) {
            const title = header.querySelector('.card-title')?.textContent || '';
            const slug = title.trim().toLowerCase()
                .replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/gu, '')
                .replace(/[^\wа-яіїєґ]+/giu, '-').replace(/^-+|-+$/g, '').slice(0, 40);
            if (slug) card.id = 'card-' + slug;
        }
        if (card.id && localStorage.getItem('card_collapsed_' + card.id) === '1') {
            card.classList.add('collapsed');
        }
        if (!header.querySelector(':scope > .card-chevron')) {
            const chev = document.createElement('button');
            chev.type = 'button';
            chev.className = 'card-chevron btn btn-sm btn-secondary';
            const collapsed = card.classList.contains('collapsed');
            chev.textContent = collapsed ? '▸' : '▾';
            chev.setAttribute('aria-expanded', String(!collapsed));
            chev.setAttribute('data-i18n-title', collapsed ? 'ui.expand_section' : 'ui.collapse_section');
            chev.title = t(collapsed ? 'ui.expand_section' : 'ui.collapse_section');
            const title = header.querySelector('.card-title');
            if (title) chev.setAttribute('aria-labelledby', panelElementId(title, 'panel-card-title'));
            else chev.setAttribute('aria-label', chev.title);
            const contents = [...card.children].filter(child => child !== header);
            if (contents.length) chev.setAttribute('aria-controls', contents.map(child => panelElementId(child, 'panel-card-content')).join(' '));
            chev.addEventListener('click', () => toggleCardCollapse(card));
            header.appendChild(chev);
        }
        header.addEventListener('click', e => {
            if (e.target.closest('button, input, select, textarea, a, .toggle, label, [onclick]')) return;
            toggleCardCollapse(card);
        });
    });
}

let _cardInitTimer = null;
function _scheduleCardInit() {
    if (_cardInitTimer) return;
    _cardInitTimer = setTimeout(() => { _cardInitTimer = null; initCollapsibleCards(document); }, 250);
}

document.addEventListener('DOMContentLoaded', () => {
    initCollapsibleCards(document);
    new MutationObserver(_scheduleCardInit).observe(document.body, { childList: true, subtree: true });
});

// ── PLAN_FEEDBACK_2908 §1.4: пустые состояния с пояснением «откуда берутся данные» ──
Object.assign(LANGS.ru, {
    'logs.empty_hint': 'Логов пока нет — они появятся, когда боты начнут читать чат и отвечать. Проверьте, что боты запущены.',
    'logs.how': '❓ Как это работает?',
    'logs.how_text': 'Боты подключаются к чату Twitch, читают сообщения и выполняют действия. Каждое значимое событие (ответ, ошибка, старт/стоп) пишется в журнал. Пока боты отключены — журнал пуст.',
    'clips.no_moments': 'Моментов пока нет — детектор клипов ловит пики активности чата и создаёт клипы автоматически. Также можно создать клип командой в чате.',
    'kb.empty': 'Пока нет фактов в базе знаний — Summarizer собирает их из чата автоматически, или добавьте вручную.',
});
Object.assign(LANGS.en, {
    'logs.empty_hint': 'No logs yet — they will appear once bots start reading chat and replying. Make sure the bots are running.',
    'logs.how': '❓ How does it work?',
    'logs.how_text': 'Bots connect to Twitch chat, read messages and take actions. Every notable event (reply, error, start/stop) is written to the journal. While bots are offline the journal stays empty.',
    'clips.no_moments': 'No moments yet — the clip detector catches chat activity spikes and creates clips automatically. You can also create a clip with a chat command.',
    'kb.empty': 'No facts in the knowledge base yet — the Summarizer collects them from chat automatically, or add them manually.',
});
Object.assign(LANGS.ua, {
    'logs.empty_hint': 'Логів поки немає — вони з\u02bcявляться, коли боти почнуть читати чат і відповідати. Перевірте, що боти запущені.',
    'logs.how': '❓ Як це працює?',
    'logs.how_text': 'Боти підключаються до чату Twitch, читають повідомлення і виконують дії. Кожна значуща подія (відповідь, помилка, старт/стоп) пишеться в журнал. Поки боти вимкнені — журнал порожній.',
    'clips.no_moments': 'Моментів поки немає — детектор кліпів ловить піки активності чату і створює кліпи автоматично. Також кліп можна створити командою в чаті.',
    'kb.empty': 'Ще немає фактів у базі знань — Summarizer збирає їх з чату автоматично, або додайте вручну.',
});

function logsEmptyHtml() {
    return `<div class="empty-state text-muted text-sm">${esc(t('logs.empty_hint'))} `
        + `<button class="btn btn-sm btn-secondary" onclick="toast(t('logs.how_text'), 'info')">${esc(t('logs.how'))}</button></div>`;
}

// ── PLAN_FEEDBACK_2908 §1.5: список виджетов — что видит зритель + куда вставить в OBS ──
Object.assign(LANGS.ru, {
    'widgets.guide.tts.viewer': 'Зритель слышит голос бота, читающего сообщения чата, а на экране — субтитры: «Imagine Dragons — Bones? База!»',
    'widgets.guide.tts.obs': 'OBS → Источники → + → Браузер. Размер 400×600; субтитры — под голосом.',
    'widgets.guide.goals.viewer': 'Чек-лист с прогресс-барами: «Донат-цель 5000₽ из 10000₽ — бар наполовину заполнен». Заполняется по мере достижения.',
    'widgets.guide.goals.obs': 'OBS → Источники → + → Браузер. Размер 400×300; сбоку экрана.',
    'widgets.guide.nowplaying.viewer': 'Плашка с треком: 🎵 Imagine Dragons — Bones + обложка. Обновляется сама.',
    'widgets.guide.nowplaying.obs': 'OBS → Источники → + → Браузер. Размер 500×90; низ экрана.',
    'widgets.guide.subgoal.viewer': 'Прогресс подписок к цели: «45 / 100 сабов». Анимация при каждом новом сабе.',
    'widgets.guide.subgoal.obs': 'OBS → Источники → + → Браузер. Размер 400×120; угол экрана.',
    'widgets.guide.uptime.viewer': 'Таймер стрима: «02:34:15» — сколько вы уже в эфире.',
    'widgets.guide.uptime.obs': 'OBS → Источники → + → Браузер. Размер 220×60; рядом с другими виджетами.',
    'widgets.guide.highlight.viewer': 'Сообщение зрителя крупным текстом поверх экрана: «@bot, скажи привет маме».',
    'widgets.guide.highlight.obs': 'OBS → Источники → + → Браузер. Размер 800×120; по центру внизу.',
});
Object.assign(LANGS.en, {
    'widgets.guide.tts.viewer': 'Viewers hear the bot reading chat messages aloud, with subtitles on screen: "Imagine Dragons — Bones? Classic!"',
    'widgets.guide.tts.obs': 'OBS → Sources → + → Browser. Size 400×600; subtitles under the voice.',
    'widgets.guide.goals.viewer': 'Checklist with progress bars: "Donation goal $50 of $100 — bar half full". Fills up as goals progress.',
    'widgets.guide.goals.obs': 'OBS → Sources → + → Browser. Size 400×300; side of the screen.',
    'widgets.guide.nowplaying.viewer': 'A plate with the track: 🎵 Imagine Dragons — Bones + cover art. Updates itself.',
    'widgets.guide.nowplaying.obs': 'OBS → Sources → + → Browser. Size 500×90; bottom of the screen.',
    'widgets.guide.subgoal.viewer': 'Sub progress toward the goal: "45 / 100 subs". Animation on every new sub.',
    'widgets.guide.subgoal.obs': 'OBS → Sources → + → Browser. Size 400×120; corner of the screen.',
    'widgets.guide.uptime.viewer': 'Stream timer: "02:34:15" — how long you have been live.',
    'widgets.guide.uptime.obs': 'OBS → Sources → + → Browser. Size 220×60; next to other widgets.',
    'widgets.guide.highlight.viewer': 'A viewer message in large text over the screen: "@bot, say hi to my mom".',
    'widgets.guide.highlight.obs': 'OBS → Sources → + → Browser. Size 800×120; centered at the bottom.',
});
Object.assign(LANGS.ua, {
    'widgets.guide.tts.viewer': 'Глядач чує голос бота, що читає повідомлення чату, а на екрані — субтитри: «Imagine Dragons — Bones? База!»',
    'widgets.guide.tts.obs': 'OBS → Джерела → + → Браузер. Розмір 400×600; субтитри — під голосом.',
    'widgets.guide.goals.viewer': 'Чек-лист із прогрес-барами: «Донат-ціль 5000₽ із 10000₽ — бар наполовину заповнений». Заповнюється в міру досягнення.',
    'widgets.guide.goals.obs': 'OBS → Джерела → + → Браузер. Розмір 400×300; збоку екрана.',
    'widgets.guide.nowplaying.viewer': 'Платівка з треком: 🎵 Imagine Dragons — Bones + обкладинка. Оновлюється сама.',
    'widgets.guide.nowplaying.obs': 'OBS → Джерела → + → Браузер. Розмір 500×90; низ екрана.',
    'widgets.guide.subgoal.viewer': 'Прогрес підписок до цілі: «45 / 100 сабів». Анімація при кожному новому сабі.',
    'widgets.guide.subgoal.obs': 'OBS → Джерела → + → Браузер. Розмір 400×120; кут екрана.',
    'widgets.guide.uptime.viewer': 'Таймер стріму: «02:34:15» — скільки ви вже в ефірі.',
    'widgets.guide.uptime.obs': 'OBS → Джерела → + → Браузер. Розмір 220×60; поруч з іншими віджетами.',
    'widgets.guide.highlight.viewer': 'Повідомлення глядача великим текстом поверх екрана: «@bot, привітай маму».',
    'widgets.guide.highlight.obs': 'OBS → Джерела → + → Браузер. Розмір 800×120; по центру внизу.',
});

// ── PLAN_FEEDBACK_2908 §1.8: пояснения простым языком ──
Object.assign(LANGS.ru, {
    'widgets.twitch_hint': 'Приложение регистрируется ОДНО на всю панель — на аккаунт владельца; боты входят через него, а их токены хранятся отдельно у каждого бота. Client ID — это НЕ токен стримера и НЕ токен бота: это идентификатор приложения для Helix API и OAuth. Создайте приложение на dev.twitch.tv/console, укажите callback URL панели и сохраните ключи здесь.',
    'settings.replay_auto_hint': 'При старте бота открывается сессия записи: пишутся сообщения чата, ответы бота, vision-описания кадров и сработавшие триггеры. Хранится в базе панели; список сессий — /api/replay/sessions. Место: зависит от активности чата, обычный стрим — единицы МБ.',
    'behavior.length_hint': 'Короткий — 1 короткая фраза («Ага, момент топ!»). Средний — 2–3 предложения. Длинный — развёрнутый ответ с историей.',
    'widgets.goalsync_hint': 'Каждый новый донат из подключённых платформ (DonatePay, DonateX, DonationAlerts) в сборе автоматически двигает активный челлендж (дельта; локальные донаты не затираются).',
});
Object.assign(LANGS.en, {
    'widgets.twitch_hint': 'The app is registered ONCE for the whole panel — on the owner\u02bcs account; bots sign in through it, and their tokens are stored separately per bot. Client ID is NOT the streamer\u02bcs token and NOT the bot\u02bcs token: it identifies the app for Helix API and OAuth. Create the app at dev.twitch.tv/console, set the panel callback URL and save the keys here.',
    'settings.replay_auto_hint': 'A recording session opens when the bot starts: chat messages, bot replies, vision frame descriptions and fired triggers are stored. Kept in the panel database; session list at /api/replay/sessions. Space: depends on chat activity, a typical stream is a few MB.',
    'behavior.length_hint': 'Short — one short phrase ("Yeah, that moment was great!"). Medium — 2–3 sentences. Long — a detailed reply with a story.',
    'widgets.goalsync_hint': 'Every new donation from connected platforms (DonatePay, DonateX, DonationAlerts) to the fund automatically moves the active challenge (delta; local donations are not overwritten).',
});
Object.assign(LANGS.ua, {
    'widgets.twitch_hint': 'Застосунок реєструється ОДИН на всю панель — на акаунт власника; боти входять через нього, а їхні токени зберігаються окремо в кожного бота. Client ID — це НЕ токен стрімера і НЕ токен бота: це ідентифікатор застосунку для Helix API та OAuth. Створіть застосунок на dev.twitch.tv/console, вкажіть callback URL панелі та збережіть ключі тут.',
    'settings.replay_auto_hint': 'Під час старту бота відкривається сесія запису: пишуться повідомлення чату, відповіді бота, vision-описи кадрів і спрацьовані тригери. Зберігається в базі панелі; список сесій — /api/replay/sessions. Місце: залежить від активності чату, звичайний стрім — одиниці МБ.',
    'behavior.length_hint': 'Короткий — 1 коротка фраза («Ага, момент топ!»). Середній — 2–3 речення. Довгий — розгорнута відповідь з історією.',
    'widgets.goalsync_hint': 'Кожен новий донат із підключених платформ (DonatePay, DonateX, DonationAlerts) у зборі автоматично рухає активний челендж (дельта; локальні донати не затираються).',
});

// ── P3 §1.4 PLAN_PANEL_REWORK: «чья память» (скоуп shared-фактов) ──
Object.assign(LANGS.ru, {
    'behavior.memory_scope': 'Общая память с другими ботами (факты о зрителях)',
    'behavior.memory_min_conf': 'Мин. уверенность факта (0–1)',
    'behavior.memory_max_facts': 'Макс. фактов в промпт',
    'behavior.memory_scope_hint': 'Выкл = бот помнит только то, что сам узнал о зрителях. Вкл = бот также видит факты о зрителе, записанные другими ботами панели. Смена видна в «Мозге бота» (счётчик общих фактов).',
});
Object.assign(LANGS.en, {
    'behavior.memory_scope': 'Shared memory with other bots (viewer facts)',
    'behavior.memory_min_conf': 'Min. fact confidence (0–1)',
    'behavior.memory_max_facts': 'Max facts into prompt',
    'behavior.memory_scope_hint': 'Off = the bot only remembers what it learned about viewers itself. On = the bot also sees viewer facts recorded by other bots of the panel. The change is visible in “Bot Brain” (shared facts counter).',
});
Object.assign(LANGS.ua, {
    'behavior.memory_scope': 'Спільна памʼять з іншими ботами (факти про глядачів)',
    'behavior.memory_min_conf': 'Мін. впевненість факту (0–1)',
    'behavior.memory_max_facts': 'Макс. фактів у промпт',
    'behavior.memory_scope_hint': 'Вимк = бот памʼятає лише те, що сам дізнався про глядачів. Ввімк = бот також бачить факти про глядача, записані іншими ботами панелі. Зміну видно в «Мозку бота» (лічильник спільних фактів).',
});

// ── PLAN_FEEDBACK_2908 §1.7: подписи к mini-preview («как это выглядит») ──
Object.assign(LANGS.ru, {
    'widgets.example.goals': 'Цель: 5000₽ из 10000₽ — прогресс-бар наполовину заполнен.',
    'widgets.example.subgoal': 'Прогресс к цели подписок: 45 из 100 — с каждым сабом бар подрастает.',
    'widgets.example.nowplaying': 'Плашка с названием трека и обложкой — зрители видят, что сейчас звучит.',
    'widgets.example.schedule': 'Баннер «что идёт сейчас / что дальше по расписанию».',
    'widgets.example.counter': 'Счётчик смертей/побед/любого события — крутится чат-командой или биндингом.',
    'widgets.example.countdown': 'Таймер обратного отсчёта — до конца стрима, розыгрыша или челленджа.',
    'widgets.example.topdonator': 'Топ донатеров за всё время / месяц / день — обновляется из донат-интеграций.',
    'widgets.example.songrequest': 'Очередь заказов через !sr: трек + кто заказал.',
    'widgets.example.blurguard': 'Маска включается на выбранную длительность; при 100% зритель не видит пиксели сцены под ней.',
    'widgets.example.cp_tts': 'Зритель покупает награду «Озвучить сообщение» за 100 баллов и пишет текст — в OBS его текст произносится голосом бота.',
    'widgets.example.tts_chat': '@nick (за 100 баллов): привет стример! — строка висит 30 сек и исчезает.',
    'widgets.example.poll': '«Кто победит?» / «CS2, Dota» — бары растут по голосам зрителей в реальном времени.',
    'widgets.example.subathon': 'Старт 01:00:00 · саб +60 сек · донат 100₽ +30 сек — таймер тикает вверх в OBS.',
});
Object.assign(LANGS.en, {
    'widgets.example.goals': 'Goal: $50 of $100 — progress bar half full.',
    'widgets.example.subgoal': 'Sub-goal progress: 45 of 100 — the bar grows with every sub.',
    'widgets.example.nowplaying': 'A plate with the track name and cover — viewers see what is playing.',
    'widgets.example.schedule': 'A banner showing "on air now / what comes next".',
    'widgets.example.counter': 'A death/wins/any-event counter — driven by a chat command or binding.',
    'widgets.example.countdown': 'A countdown timer — until stream end, giveaway or challenge.',
    'widgets.example.topdonator': 'Top donators for all time / month / day — fed by donation integrations.',
    'widgets.example.songrequest': 'The !sr queue: track + who requested it.',
    'widgets.example.blurguard': 'The mask activates for the chosen duration; at 100%, viewers cannot see the scene pixels beneath it.',
    'widgets.example.cp_tts': 'A viewer buys the “Read my message” reward for 100 points and types text — the bot voice reads it in OBS.',
    'widgets.example.tts_chat': '@nick (for 100 points): hi streamer! — the line stays 30s and fades.',
    'widgets.example.poll': '“Who wins?” / “CS2, Dota” — bars grow with viewer votes in real time.',
    'widgets.example.subathon': 'Start 01:00:00 · sub +60 sec · 100₽ donation +30 sec — the timer ticks up in OBS.',
});
Object.assign(LANGS.ua, {
    'widgets.example.goals': 'Ціль: 5000₽ із 10000₽ — прогрес-бар наполовину заповнений.',
    'widgets.example.subgoal': 'Прогрес до цілі підписок: 45 із 100 — з кожним сабом бар підростає.',
    'widgets.example.nowplaying': 'Платівка з назвою треку та обкладинкою — глядачі бачать, що зараз грає.',
    'widgets.example.schedule': 'Банер «що йде зараз / що далі за розкладом».',
    'widgets.example.counter': 'Лічильник смертей/перемог/будь-якої події — крутиться чат-командою чи біндингом.',
    'widgets.example.countdown': 'Таймер зворотного відліку — до кінця стріму, розіграшу чи челенджу.',
    'widgets.example.topdonator': 'Топ донатерів за весь час / місяць / день — оновлюється з донат-інтеграцій.',
    'widgets.example.songrequest': 'Черга замовлень через !sr: трек + хто замовив.',
    'widgets.example.blurguard': 'Маска вмикається на обрану тривалість; при 100% глядач не бачить пікселі сцени під нею.',
    'widgets.example.cp_tts': 'Глядач купує нагороду «Озвучити повідомлення» за 100 балів і пише текст — в OBS його текст озвучує голос бота.',
    'widgets.example.tts_chat': '@nick (за 100 балів): привіт стрімеру! — рядок висить 30 сек і зникає.',
    'widgets.example.poll': '«Хто переможе?» / «CS2, Dota» — бари ростуть за голосами глядачів у реальному часі.',
    'widgets.example.subathon': 'Старт 01:00:00 · саб +60 сек · донат 100₽ +30 сек — таймер тікає вгору в OBS.',
});

// ── Track 6.10: native Twitch Poll controls ──
Object.assign(LANGS.ru, {
    'widgets.poll.title': '🗳 Twitch-голосование', 'widgets.poll.hint': 'Создаёт нативное голосование Twitch — его показывает сам Twitch зрителям, OBS-оверлей не нужен. Требуется scope channel:manage:polls у приложения бота.',
    'widgets.poll.title_placeholder': 'Вопрос голосования', 'widgets.poll.choice_placeholder': 'Вариант', 'widgets.poll.duration_title': 'Длительность, сек', 'widgets.poll.remove': 'Удалить вариант',
    'widgets.poll.add_choice': '+ Добавить вариант', 'widgets.poll.choice_count': '{count} из 5 вариантов', 'widgets.poll.create': 'Twitch Poll — создать', 'widgets.poll.end': '⏹ Завершить',
    'widgets.poll.minimum_choices': '⛔ В голосовании должно остаться минимум 2 варианта', 'widgets.poll.invalid_choices': '⛔ Заполни от 2 до 5 отдельных вариантов',
    'widgets.poll.choose_channel': '⛔ Выбери бота и канал сверху панели', 'widgets.poll.created': '✅ Twitch Poll создан', 'widgets.poll.ended': '✅ Завершено',
});
Object.assign(LANGS.en, {
    'widgets.poll.title': '🗳 Twitch Poll', 'widgets.poll.hint': 'Creates a native Twitch poll that viewers see in Twitch; no OBS overlay is needed. The bot app needs the channel:manage:polls scope.',
    'widgets.poll.title_placeholder': 'Poll question', 'widgets.poll.choice_placeholder': 'Choice', 'widgets.poll.duration_title': 'Duration, seconds', 'widgets.poll.remove': 'Remove choice',
    'widgets.poll.add_choice': '+ Add choice', 'widgets.poll.choice_count': '{count} of 5 choices', 'widgets.poll.create': 'Create Twitch Poll', 'widgets.poll.end': '⏹ End',
    'widgets.poll.minimum_choices': '⛔ A poll must keep at least 2 choices', 'widgets.poll.invalid_choices': '⛔ Fill in 2 to 5 separate choices',
    'widgets.poll.choose_channel': '⛔ Select a bot and channel above', 'widgets.poll.created': '✅ Twitch Poll created', 'widgets.poll.ended': '✅ Ended',
});
Object.assign(LANGS.ua, {
    'widgets.poll.title': '🗳 Twitch-голосування', 'widgets.poll.hint': 'Створює нативне голосування Twitch, яке глядачі бачать у Twitch; OBS-оверлей не потрібен. Застосунку бота потрібен scope channel:manage:polls.',
    'widgets.poll.title_placeholder': 'Питання голосування', 'widgets.poll.choice_placeholder': 'Варіант', 'widgets.poll.duration_title': 'Тривалість, сек', 'widgets.poll.remove': 'Видалити варіант',
    'widgets.poll.add_choice': '+ Додати варіант', 'widgets.poll.choice_count': '{count} з 5 варіантів', 'widgets.poll.create': 'Створити Twitch Poll', 'widgets.poll.end': '⏹ Завершити',
    'widgets.poll.minimum_choices': '⛔ У голосуванні мають лишитися щонайменше 2 варіанти', 'widgets.poll.invalid_choices': '⛔ Заповни від 2 до 5 окремих варіантів',
    'widgets.poll.choose_channel': '⛔ Вибери бота й канал вище', 'widgets.poll.created': '✅ Twitch Poll створено', 'widgets.poll.ended': '✅ Завершено',
});
if (typeof waPollSyncChoices === 'function') waPollSyncChoices();

// ── Track 6.10: native Twitch Prediction controls ──
Object.assign(LANGS.ru, {
    'widgets.prediction.title': '🔮 Twitch Predictions', 'widgets.prediction.hint': 'Создаёт нативный прогноз Twitch: зрители ставят Channel Points на исход. OBS-оверлей не нужен; у приложения бота нужен scope channel:manage:predictions.',
    'widgets.example.prediction': '«Пройдёт ли стример босса?» — зрители ставят баллы на «Да» или «Нет» до закрытия приёма ставок.',
    'widgets.prediction.title_placeholder': 'Вопрос прогноза', 'widgets.prediction.window_title': 'Окно ставок', 'widgets.prediction.window_unit_title': 'Единица времени',
    'widgets.prediction.seconds': 'секунды', 'widgets.prediction.minutes': 'минуты', 'widgets.prediction.window_hint': 'Окно приёма ставок: от 30 секунд до 30 минут (1800 секунд).',
    'widgets.prediction.outcome_placeholder': 'Исход', 'widgets.prediction.remove': 'Удалить исход', 'widgets.prediction.add_outcome': '+ Добавить исход',
    'widgets.prediction.outcome_count': '{count} из 10 исходов', 'widgets.prediction.create': 'Создать Prediction',
    'widgets.prediction.minimum_outcomes': '⛔ В прогнозе должны остаться минимум 2 исхода', 'widgets.prediction.invalid_title': '⛔ Введи вопрос прогноза',
    'widgets.prediction.invalid_outcomes': '⛔ Заполни от 2 до 10 исходов', 'widgets.prediction.invalid_window': '⛔ Окно ставок должно быть от 30 до 1800 секунд',
    'widgets.prediction.choose_channel': '⛔ Выбери бота и канал сверху панели', 'widgets.prediction.created': '✅ Twitch Prediction создан', 'widgets.prediction.request_failed': '⛔ Не удалось создать Twitch Prediction',
    'widgets.prediction.refresh': 'Обновить статус', 'widgets.prediction.no_active': 'Активных Predictions нет', 'widgets.prediction.lock': '🔒 Закрыть ставки', 'widgets.prediction.resolve': '✅ Подтвердить победителя', 'widgets.prediction.cancel': 'Отменить Prediction', 'widgets.prediction.choose_winner': 'Выберите победивший исход', 'widgets.prediction.cancel_confirm': 'Отменить этот Prediction? Ставки будут возвращены.', 'widgets.prediction.updated': '✅ Prediction обновлён',
});
Object.assign(LANGS.en, {
    'widgets.prediction.title': '🔮 Twitch Predictions', 'widgets.prediction.hint': 'Creates a native Twitch prediction: viewers use Channel Points on an outcome. No OBS overlay is needed; the bot app needs the channel:manage:predictions scope.',
    'widgets.example.prediction': '“Will the streamer beat the boss?” — viewers stake points on “Yes” or “No” until betting closes.',
    'widgets.prediction.title_placeholder': 'Prediction question', 'widgets.prediction.window_title': 'Betting window', 'widgets.prediction.window_unit_title': 'Time unit',
    'widgets.prediction.seconds': 'seconds', 'widgets.prediction.minutes': 'minutes', 'widgets.prediction.window_hint': 'Betting window: 30 seconds to 30 minutes (1800 seconds).',
    'widgets.prediction.outcome_placeholder': 'Outcome', 'widgets.prediction.remove': 'Remove outcome', 'widgets.prediction.add_outcome': '+ Add outcome',
    'widgets.prediction.outcome_count': '{count} of 10 outcomes', 'widgets.prediction.create': 'Create Prediction',
    'widgets.prediction.minimum_outcomes': '⛔ A prediction must keep at least 2 outcomes', 'widgets.prediction.invalid_title': '⛔ Enter a prediction question',
    'widgets.prediction.invalid_outcomes': '⛔ Fill in 2 to 10 outcomes', 'widgets.prediction.invalid_window': '⛔ The betting window must be from 30 to 1800 seconds',
    'widgets.prediction.choose_channel': '⛔ Select a bot and channel above', 'widgets.prediction.created': '✅ Twitch Prediction created', 'widgets.prediction.request_failed': '⛔ Could not create Twitch Prediction',
    'widgets.prediction.refresh': 'Refresh status', 'widgets.prediction.no_active': 'No active Predictions', 'widgets.prediction.lock': '🔒 Lock betting', 'widgets.prediction.resolve': '✅ Confirm winner', 'widgets.prediction.cancel': 'Cancel Prediction', 'widgets.prediction.choose_winner': 'Choose the winning outcome', 'widgets.prediction.cancel_confirm': 'Cancel this Prediction? All stakes will be returned.', 'widgets.prediction.updated': '✅ Prediction updated',
});
Object.assign(LANGS.ua, {
    'widgets.prediction.title': '🔮 Twitch Predictions', 'widgets.prediction.hint': 'Створює нативний прогноз Twitch: глядачі ставлять Channel Points на результат. OBS-оверлей не потрібен; застосунку бота потрібен scope channel:manage:predictions.',
    'widgets.example.prediction': '«Чи пройде стрімер боса?» — глядачі ставлять бали на «Так» або «Ні» до закриття прийому ставок.',
    'widgets.prediction.title_placeholder': 'Питання прогнозу', 'widgets.prediction.window_title': 'Вікно ставок', 'widgets.prediction.window_unit_title': 'Одиниця часу',
    'widgets.prediction.seconds': 'секунди', 'widgets.prediction.minutes': 'хвилини', 'widgets.prediction.window_hint': 'Вікно прийому ставок: від 30 секунд до 30 хвилин (1800 секунд).',
    'widgets.prediction.outcome_placeholder': 'Результат', 'widgets.prediction.remove': 'Видалити результат', 'widgets.prediction.add_outcome': '+ Додати результат',
    'widgets.prediction.outcome_count': '{count} з 10 результатів', 'widgets.prediction.create': 'Створити Prediction',
    'widgets.prediction.minimum_outcomes': '⛔ У прогнозі мають лишитися щонайменше 2 результати', 'widgets.prediction.invalid_title': '⛔ Введи питання прогнозу',
    'widgets.prediction.invalid_outcomes': '⛔ Заповни від 2 до 10 результатів', 'widgets.prediction.invalid_window': '⛔ Вікно ставок має бути від 30 до 1800 секунд',
    'widgets.prediction.choose_channel': '⛔ Вибери бота й канал вище', 'widgets.prediction.created': '✅ Twitch Prediction створено', 'widgets.prediction.request_failed': '⛔ Не вдалося створити Twitch Prediction',
    'widgets.prediction.refresh': 'Оновити статус', 'widgets.prediction.no_active': 'Немає активних Predictions', 'widgets.prediction.lock': '🔒 Закрити ставки', 'widgets.prediction.resolve': '✅ Підтвердити переможця', 'widgets.prediction.cancel': 'Скасувати Prediction', 'widgets.prediction.choose_winner': 'Оберіть переможний результат', 'widgets.prediction.cancel_confirm': 'Скасувати цей Prediction? Усі ставки буде повернено.', 'widgets.prediction.updated': '✅ Prediction оновлено',
});
if (typeof waPredictionSyncOutcomes === 'function') waPredictionSyncOutcomes();

// ── PLAN_FEEDBACK_2908 §3.3: карточка сбора — нейтральное название + честная заметка ──
Object.assign(LANGS.ru, {
    'widgets.goalsync_title': '🎯 Сбор → челлендж',
    'widgets.goalsync_note': 'Источник прогресса сбора — goal-API DonateX (единственная платформа с goal-API). Челлендж при этом двигают донаты со всех подключённых платформ и webhook.',
});
Object.assign(LANGS.en, {
    'widgets.goalsync_title': '🎯 Fundraiser → challenge',
    'widgets.goalsync_note': 'The fundraiser progress source is the DonateX goal API (the only platform with a goal API). The challenge itself is moved by donations from all connected platforms and the webhook.',
});
Object.assign(LANGS.ua, {
    'widgets.goalsync_title': '🎯 Збір → челендж',
    'widgets.goalsync_note': 'Джерело прогресу збору — goal-API DonateX (єдина платформа з goal-API). Челендж при цьому рухають донати з усіх підключених платформ і webhook.',
});

// ── PLAN_FEEDBACK_2908 §3.1: hotkey-биндинги (работает, пока панель открыта) ──
Object.assign(LANGS.ru, {
    'bindings.capture': '⌨ Клавиша',
    'bindings.pressing': 'Нажмите клавишу...',
    'bindings.executed': 'Выполнено биндингов: {n}',
    'bindings.not_found': 'Для «{combo}» активных hotkey-биндингов нет',
    'bindings.hint': '⌨ Hotkey-биндинг работает, пока панель открыта и вкладка в фокусе. OBS hotkeys управляют сценами/source и не вызывают binding API; для внешней клавиши используйте Streamer.bot/public API или чат-команду.',
    'bindings.action_increment': '+1 / указанное значение', 'bindings.action_set': 'Установить значение',
    'bindings.action_reset': 'Сбросить', 'bindings.action_add_percent': 'Изменить прогресс, %',
    'bindings.action_start': 'Запустить', 'bindings.action_pause': 'Поставить на паузу',
    'bindings.action_add_time': 'Добавить время', 'bindings.action_clear': 'Очистить',
    'bindings.action_show': 'Показать', 'bindings.action_hide': 'Скрыть',
    'bindings.action_timeout_last': 'Тайм-аут последнему нарушителю', 'bindings.action_warn_last': 'Предупредить последнего',
    'bindings.action_slow_on': 'Включить slow mode', 'bindings.action_slow_off': 'Выключить slow mode',
    'bindings.action_play_track': 'Проиграть трек',
    'bindings.action_stop': 'Остановить', 'bindings.action_extend': 'Продлить на N сек',
    'bindings.action_add_funds': 'Добавить к сбору', 'bindings.action_skip': 'Пропустить трек',
    'bindings.action_spin': 'Крутить рулетку', 'bindings.action_highlight': 'Показать подсветку',
    'bindings.action_preset': 'Сменить пресет', 'bindings.action_blur_on': 'Размытие включить',
    'bindings.action_blur_off': 'Размытие выключить',
});
Object.assign(LANGS.en, {
    'bindings.capture': '⌨ Key',
    'bindings.pressing': 'Press a key...',
    'bindings.executed': 'Bindings executed: {n}',
    'bindings.not_found': 'No active hotkey bindings for "{combo}"',
    'bindings.hint': '⌨ A hotkey binding works while the panel is open and focused. OBS hotkeys control scenes/sources and do not call the binding API; for an external key, use Streamer.bot/public API or a chat command.',
    'bindings.action_increment': '+1 / specified value', 'bindings.action_set': 'Set value',
    'bindings.action_reset': 'Reset', 'bindings.action_add_percent': 'Change progress, %',
    'bindings.action_start': 'Start', 'bindings.action_pause': 'Pause',
    'bindings.action_add_time': 'Add time', 'bindings.action_clear': 'Clear',
    'bindings.action_show': 'Show', 'bindings.action_hide': 'Hide',
    'bindings.action_timeout_last': 'Timeout last offender', 'bindings.action_warn_last': 'Warn last offender',
    'bindings.action_slow_on': 'Enable slow mode', 'bindings.action_slow_off': 'Disable slow mode',
    'bindings.action_play_track': 'Play track',
    'bindings.action_stop': 'Stop', 'bindings.action_extend': 'Extend by N sec',
    'bindings.action_add_funds': 'Add to challenge', 'bindings.action_skip': 'Skip track',
    'bindings.action_spin': 'Spin the roulette', 'bindings.action_highlight': 'Show highlight',
    'bindings.action_preset': 'Change preset', 'bindings.action_blur_on': 'Blur on',
    'bindings.action_blur_off': 'Blur off',
});
Object.assign(LANGS.ua, {
    'bindings.capture': '⌨ Клавіша',
    'bindings.pressing': 'Натисніть клавішу...',
    'bindings.executed': 'Виконано біндингів: {n}',
    'bindings.not_found': 'Для «{combo}» активних hotkey-біндингів немає',
    'bindings.hint': '⌨ Hotkey-біндинг працює, доки панель відкрита й вкладка у фокусі. OBS hotkeys керують сценами/source і не викликають binding API; для зовнішньої клавіші використовуйте Streamer.bot/public API або чат-команду.',
    'bindings.action_increment': '+1 / вказане значення', 'bindings.action_set': 'Встановити значення',
    'bindings.action_reset': 'Скинути', 'bindings.action_add_percent': 'Змінити прогрес, %',
    'bindings.action_start': 'Запустити', 'bindings.action_pause': 'Призупинити',
    'bindings.action_add_time': 'Додати час', 'bindings.action_clear': 'Очистити',
    'bindings.action_show': 'Показати', 'bindings.action_hide': 'Сховати',
    'bindings.action_timeout_last': 'Тайм-аут останньому порушнику', 'bindings.action_warn_last': 'Попередити останнього',
    'bindings.action_slow_on': 'Увімкнути slow mode', 'bindings.action_slow_off': 'Вимкнути slow mode',
    'bindings.action_play_track': 'Відтворити трек',
    'bindings.action_stop': 'Зупинити', 'bindings.action_extend': 'Продовжити на N сек',
    'bindings.action_add_funds': 'Додати до збору', 'bindings.action_skip': 'Пропустити трек',
    'bindings.action_spin': 'Крутити рулетку', 'bindings.action_highlight': 'Показати підсвітку',
    'bindings.action_preset': 'Змінити пресет', 'bindings.action_blur_on': 'Розмиття увімкнути',
    'bindings.action_blur_off': 'Розмиття вимкнути',
});

function waHotkeyComboFromEvent(e) {
    if (!e || ['Control', 'Alt', 'Shift', 'Meta'].includes(e.key)) return '';
    if (e.ctrlKey && (e.key === 'Tab' || e.key === 'W' || e.key === 'T' || e.key === 'N')) return '';
    const parts = [];
    if (e.ctrlKey) parts.push('ctrl');
    if (e.altKey) parts.push('alt');
    if (e.shiftKey) parts.push('shift');
    if (e.metaKey) parts.push('meta');
    let k = (e.key || '').toLowerCase();
    if (k === ' ') k = 'space';
    if (!k) return '';
    parts.push(k);
    return parts.join('+');
}

function waHotkeyCapture() {
    const btn = document.getElementById('waBindHotkeyBtn');
    const src = document.getElementById('waBindSource');
    const match = document.getElementById('waBindMatch');
    if (!btn || !src || !match) return;
    src.value = 'hotkey';
    window._hotkeyCapturing = true;
    btn.textContent = t('bindings.pressing');
    const done = (e) => {
        e.preventDefault();
        e.stopPropagation();
        document.removeEventListener('keydown', done, true);
        window._hotkeyCapturing = false;
        const combo = waHotkeyComboFromEvent(e);
        if (combo) {
            match.value = combo;
            btn.textContent = t('bindings.capture');
        } else {
            btn.textContent = t('bindings.capture');
        }
    };
    document.addEventListener('keydown', done, true);
}

document.addEventListener('keydown', async e => {
    if (window._hotkeyCapturing) return;
    const combos = window._hotkeyCombos || [];
    if (!combos.length) return;
    const el = e.target;
    const tag = (el?.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select' || el?.isContentEditable) return;
    const combo = waHotkeyComboFromEvent(e);
    if (!combo || !combos.includes(combo)) return;
    e.preventDefault();
    try {
        const scope = typeof waBindingScope === 'function' ? waBindingScope() : {};
        if (!scope.account_id || !scope.channel) return;
        const res = await wapi('/api/widgets/bindings/hotkey', 'POST', { combo, ...scope });
        const n = (res.executed || []).length;
        if (n) toast(t('bindings.executed', { n }), 'success');
        else toast(t('bindings.not_found', { combo }), 'error');
    } catch (err) { /* сеть дёрнулась */ }
});

// ── PLAN_FEEDBACK_2908 §4.1: свой пресет характера (сохранить/применить/удалить в карточке «Характер») ──
Object.assign(LANGS.ru, {
    'persona.save_as_preset': '💾 Сохранить как пресет',
    'persona.custom_preset_placeholder': 'Свои пресеты...',
    'prompt.preset_name': 'Название пресета характера:',
    'toast.preset_saved': 'Пресет «{name}» сохранён',
});
Object.assign(LANGS.en, {
    'persona.save_as_preset': '💾 Save as preset',
    'persona.custom_preset_placeholder': 'Custom presets...',
    'prompt.preset_name': 'Character preset name:',
    'toast.preset_saved': 'Preset "{name}" saved',
});
Object.assign(LANGS.ua, {
    'persona.save_as_preset': '💾 Зберегти як пресет',
    'persona.custom_preset_placeholder': 'Власні пресети...',
    'prompt.preset_name': 'Назва пресету характеру:',
    'toast.preset_saved': 'Пресет «{name}» збережено',
});

async function refreshPersonaCustomPresets() {
    const sel = $('personaCustomPreset');
    if (!sel || !_currentBotId) return;
    try {
        const data = await api(`/api/accounts/${_currentBotId}/behavior-presets`);
        const current = sel.value;
        sel.innerHTML = `<option value="">${esc(t('persona.custom_preset_placeholder'))}</option>` +
            (data.presets || []).map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join('');
        if (current && (data.presets || []).some(p => String(p.id) === current)) sel.value = current;
    } catch (e) { /* список пресетов не критичен */ }
}

async function savePersonaAsPreset() {
    if (!_currentBotId) return;
    const name = (prompt(t('prompt.preset_name')) || '').trim();
    if (!name) return;
    try {
        await api(`/api/accounts/${_currentBotId}/behavior-presets`, jopts('POST', { name, values: collectPersona() }));
        await refreshPersonaCustomPresets();
        loadCustomPresets();
        toast(t('toast.preset_saved', { name }), 'success');
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function applyCustomPresetToPersona(id) {
    if (!id) return;
    await applyCustomPreset(Number(id));
    toast(t('toast.persona_preset_applied'), 'success');
}

async function deleteSelectedCustomPreset() {
    const sel = $('personaCustomPreset');
    if (!sel || !sel.value) return;
    await deleteCustomPreset(Number(sel.value));
    sel.value = '';
    await refreshPersonaCustomPresets();
}

// ── PLAN_FEEDBACK_2908 §4.2/§4.3: подсказки пресетов + custom-провайдеры ──
Object.assign(LANGS.ru, {
    'behavior.vs_character': 'Поведение — когда и как бот отвечает (cooldown, источники контекста, шанс ответа). Характер — кто он: юмор, сарказм, эмоции (вкладка «Память», карточка «Характер»; свои пресеты сохраняются там же).',
    'behavior.dup_note': 'auto_chat, «Тихий режим» и cooldown здесь — те же настройки, что в Быстрых настройках общей карточки бота.',
    'provider.custom_hint': 'Свои провайдеры (навсегда) добавляются в Настройках → AI-провайдеры и появляются в списке выше.',
});
Object.assign(LANGS.en, {
    'behavior.vs_character': 'Behavior — when and how the bot replies (cooldown, context sources, reply chance). Character — who it is: humor, sarcasm, emotions (Memory tab, "Character" card; custom presets are saved there too).',
    'behavior.dup_note': 'auto_chat, "Silent mode" and cooldown here are the same settings as in the Quick settings of the bot card.',
    'provider.custom_hint': 'Permanent custom providers are added in Settings → AI providers and appear in the list above.',
});
Object.assign(LANGS.ua, {
    'behavior.vs_character': 'Поведінка — коли і як бот відповідає (cooldown, джерела контексту, шанс відповіді). Характер — хто він: гумор, сарказм, емоції (вкладка «Пам\u02bcять», картка «Характер»; власні пресети зберігаються там же).',
    'behavior.dup_note': 'auto_chat, «Тихий режим» і cooldown тут — ті самі налаштування, що у Швидких налаштуваннях спільної картки бота.',
    'provider.custom_hint': 'Свої провайдери (назавжди) додаються в Налаштуваннях → AI-провайдери і з\u02bcявляються в списку вище.',
});

// ── PLAN_FEEDBACK_2908 §5: глобальный профиль стримера (Настройки) ──
Object.assign(LANGS.ru, {
    'streamer.global_title': '👤 О стримере (глобально)',
    'streamer.global_hint': 'Общий профиль для всех ботов: «Глобальный» используется на всех каналах, где нет своего; для отдельного канала можно задать свой вариант (селект слева).',
    'streamer.settings_link': '↪ Редактор профиля живёт в разделе «Мозг бота» → «Профиль стримера» (там же скоуп: глобальный / отдельный канал).',
    'streamer.open_in_brain': '✏️ Открыть профиль в Мозге',
    'streamer.global_scope': '🌐 Глобальный профиль (все каналы)',
    'streamer.global_delete': '🗑 Удалить профиль',
    'streamer.scope_global': '🌐 глобальный профиль',
    'streamer.scope_channel': 'канал {channel}',
});
Object.assign(LANGS.en, {
    'streamer.global_title': '👤 About the streamer (global)',
    'streamer.global_hint': 'A profile shared by all bots: "Global" is used on every channel without its own; a specific channel can have its own variant (select on the left).',
    'streamer.settings_link': '↪ The profile editor lives in "Bot Brain" → "Streamer profile" (with global/per-channel scope).',
    'streamer.open_in_brain': '✏️ Open the profile in Brain',
    'streamer.global_scope': '🌐 Global profile (all channels)',
    'streamer.global_delete': '🗑 Delete profile',
    'streamer.scope_global': '🌐 global profile',
    'streamer.scope_channel': 'channel {channel}',
});
Object.assign(LANGS.ua, {
    'streamer.global_title': '👤 Про стрімера (глобально)',
    'streamer.global_hint': 'Спільний профіль для всіх ботів: «Глобальний» використовується на всіх каналах, де немає свого; для окремого каналу можна задати свій варіант (селект ліворуч).',
    'streamer.settings_link': '↪ Редактор профілю живе в розділі «Мозг бота» → «Профіль стрімера» (там же скоуп: глобальний / окремий канал).',
    'streamer.open_in_brain': '✏️ Відкрити профіль у Моззі',
    'streamer.global_scope': '🌐 Глобальний профіль (усі канали)',
    'streamer.global_delete': '🗑 Видалити профіль',
    'streamer.scope_global': '🌐 глобальний профіль',
    'streamer.scope_channel': 'канал {channel}',
});

// §2.5 PLAN_FEEDBACK_3008: функции параметризованы префиксом id-полей,
// чтобы одна и та же форма жила и в Настройках (gsp), и в Мозге (bsp).
async function loadGlobalStreamerChannels(prefix = 'gsp') {
    const sel = $(`${prefix}Channel`);
    if (!sel) return;
    try {
        const data = await api('/api/streamer-channels');
        const current = sel.value;
        sel.innerHTML = (data.channels || []).map(c => `<option value="#${esc(c)}">#${esc(c)}</option>`).join('');
        if (current && (data.channels || []).some(c => '#' + c === current)) sel.value = current;
    } catch (e) { /* некритично */ }
}

async function loadGlobalStreamerProfile(prefix = 'gsp') {
    const sel = $(`${prefix}Channel`);
    if (!sel) return;
    const channel = sel.value || '';
    if (!channel) return;
    try {
        const [res, face] = await Promise.all([
            api(`/api/streamer-profile?channel=${encodeURIComponent(channel)}`),
            api(`/api/streamer-face?channel=${encodeURIComponent(channel)}`),
        ]);
        const p = res.profile || {};
        const set = (id, v) => { const el = $(prefix + id); if (el) el.value = v ?? ''; };
        set('Age', p.age || '');
        set('Gender', p.gender);
        set('Location', p.location);
        set('Occupation', p.occupation);
        set('Bio', p.bio);
        set('Style', p.streaming_style);
        const toList = v => Array.isArray(v) ? v.join(', ')
            : (typeof v === 'string' && v.trim().startsWith('[') ? (() => { try { return JSON.parse(v).join(', '); } catch (e) { return v; } })() : v || '');
        set('Interests', toList(p.interests));
        set('Games', toList(p.favorite_games));
        const badge = $(`${prefix}ScopeBadge`);
        if (badge) badge.textContent = res.scope === 'global' ? t('streamer.scope_global') : t('streamer.scope_channel', { channel: res.scope.replace('канал ', '#').replace('channel ', '#') });
        const preview = $(`${prefix}FacePreview`);
        if (preview) {
            preview.innerHTML = (face && face.has_face && face.face_image_base64)
                ? `<img src="data:${face.mime_type || 'image/jpeg'};base64,${face.face_image_base64}" alt="streamer" style="max-width:60px;max-height:60px;border-radius:8px">`
                : esc(t('streamer.face_none'));
        }
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function saveGlobalStreamerProfile(prefix = 'gsp') {
    const channel = $(`${prefix}Channel`)?.value || '';
    if (!channel) { toast(t('streamer.channel_required'), 'error'); return; }
    const facts = {
        age: parseInt($(prefix + 'Age')?.value, 10) || 0,
        gender: $(prefix + 'Gender')?.value.trim() || '',
        location: $(prefix + 'Location')?.value.trim() || '',
        occupation: $(prefix + 'Occupation')?.value.trim() || '',
        bio: $(prefix + 'Bio')?.value.trim() || '',
        streaming_style: $(prefix + 'Style')?.value || '',
    };
    facts.interests = splitList($(prefix + 'Interests')?.value || '');
    facts.favorite_games = splitList($(prefix + 'Games')?.value || '');
    try {
        await api(`/api/streamer-profile?channel=${encodeURIComponent(channel)}`, jopts('PUT', facts));
        toast(t('streamer.saved'), 'success');
        await loadGlobalStreamerProfile(prefix);
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function deleteGlobalStreamerProfile(prefix = 'gsp') {
    const channel = $(`${prefix}Channel`)?.value || '';
    if (!channel) { toast(t('streamer.channel_required'), 'error'); return; }
    try {
        await api(`/api/streamer-profile?channel=${encodeURIComponent(channel)}`, { method: 'DELETE' });
        toast(t('streamer.saved'), 'success');
        await loadGlobalStreamerProfile(prefix);
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function uploadGlobalStreamerFace(input, prefix = 'gsp') {
    if (!input?.files?.[0]) return;
    const file = input.files[0];
    if (!['image/jpeg', 'image/png'].includes(file.type) || file.size > 2 * 1024 * 1024) {
        toast(t('streamer.face_invalid'), 'error');
        input.value = '';
        return;
    }
    const channel = $(`${prefix}Channel`)?.value || '';
    const form = new FormData();
    form.append('file', file);
    try {
        const res = await fetch(`${API}/api/streamer-face?channel=${encodeURIComponent(channel)}`, { method: 'POST', body: form });
        if (!res.ok) throw new Error(res.statusText);
        toast(t('streamer.face_uploaded'), 'success');
        await loadGlobalStreamerProfile(prefix);
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
    input.value = '';
}

// §2.5: профиль стримера в Мозге — тот же редактор с префиксом bsp
async function loadBrainProfile() {
    await loadGlobalStreamerChannels('bsp');
    await loadGlobalStreamerProfile('bsp');
}

// ── PLAN_FEEDBACK_2908 §6: per-bot TTS — голоса провайдера + подсказка ──
Object.assign(LANGS.ru, {
    'option.voice_default': 'Голос по умолчанию',
    'option.voice_manual': 'Другой голос (вручную)',
    'tts.per_bot_hint': 'Эти настройки сильнее глобальных TTS из Настроек: если провайдер задан — бот озвучивает только им. Пустой провайдер = наследовать глобальные настройки.',
});
Object.assign(LANGS.en, {
    'option.voice_default': 'Default voice',
    'option.voice_manual': 'Custom voice (manual)',
    'tts.per_bot_hint': 'These settings override the global TTS in Settings: if a provider is set, the bot speaks only with it. Empty provider = inherit global settings.',
});
Object.assign(LANGS.ua, {
    'option.voice_default': 'Голос за замовчуванням',
    'option.voice_manual': 'Інший голос (вручну)',
    'tts.per_bot_hint': 'Ці налаштування сильніші за глобальні TTS з Налаштувань: якщо провайдер заданий — бот озвучує лише ним. Порожній провайдер = наслідувати глобальні налаштування.',
});

// ── PLAN_FEEDBACK_2908 §7.1 §12.1: TTS test голосом бота + статус синтеза ──
Object.assign(LANGS.ru, {
    'tts.test_bot_voice': 'Озвучить голосом бота (через OBS TTS-оверлей)',
    'tts.sent_to_obs': 'Озвучка отправлена в OBS TTS-оверлей',
    'tts.last_none': 'Синтеза ещё не было — озвучка появится, когда бот начнёт отвечать с включённым TTS.',
    'tts.last_status': 'Последний синтез [{time}]: {msg}',
});
Object.assign(LANGS.en, {
    'tts.test_bot_voice': 'Speak with this bot\u02bcs voice (via OBS TTS overlay)',
    'tts.sent_to_obs': 'Speech sent to the OBS TTS overlay',
    'tts.last_none': 'No synthesis yet — speech appears once the bot replies with TTS enabled.',
    'tts.last_status': 'Last synthesis [{time}]: {msg}',
});
Object.assign(LANGS.ua, {
    'tts.test_bot_voice': 'Озвучити голосом цього бота (через OBS TTS-оверлей)',
    'tts.sent_to_obs': 'Озвучку надіслано в OBS TTS-оверлей',
    'tts.last_none': 'Синтезу ще не було — озвучка з\u02bcявиться, коли бот відповідатиме з увімкненим TTS.',
    'tts.last_status': 'Останній синтез [{time}]: {msg}',
});

// ── PLAN_FEEDBACK_2908 §7.1 §9: настройки «Когда бот отвечает» ──
Object.assign(LANGS.ru, {
    'attention.reply_mentions': 'Отвечать на @упоминания',
    'attention.interrupt_guard': 'Не перебивать стримера (сек, 0 = выкл)',
    'attention.tts_percent': 'Озвучивать ответы, % (0 = только текст)',
    'attention.reply_keywords': 'Отвечать на ключевые слова',
    'attention.keywords': 'Ключевые слова (через запятую)',
    'attention.delay_hint': 'Почему не сразу: бот ждёт указанное количество секунд, собирает сообщения в один батч и отвечает одним ответом на всё сразу — так меньше спама и осмысленнее ответы.',
});
Object.assign(LANGS.en, {
    'attention.reply_mentions': 'Reply to @mentions',
    'attention.interrupt_guard': "Don't interrupt the streamer (sec, 0 = off)",
    'attention.tts_percent': 'Speak replies, % (0 = text only)',
    'attention.reply_keywords': 'Reply to keywords',
    'attention.keywords': 'Keywords (comma-separated)',
    'attention.delay_hint': 'Why not instantly: the bot waits the given number of seconds, collects messages into one batch and replies once for all of them — less spam, more sensible replies.',
});
Object.assign(LANGS.ua, {
    'attention.reply_mentions': 'Відповідати на @згадки',
    'attention.interrupt_guard': 'Не перебивати стрімера (сек, 0 = вимк)',
    'attention.tts_percent': 'Озвучувати відповіді, % (0 = лише текст)',
    'attention.reply_keywords': 'Відповідати на ключові слова',
    'attention.keywords': 'Ключові слова (через кому)',
    'attention.delay_hint': 'Чому не одразу: бот чекає вказану кількість секунд, збирає повідомлення в один батч і відповідає одним ответом на все одразу — так менше спаму і осмисленіші відповіді.',
});

// ── PLAN_FEEDBACK_2908 §24: админ-формы оставшихся виджетов ──
async function wa2LoadAll() {
    if (!$('wa2LtName')) return;
    try {
        const lt = await wstateapi('/api/widgets/lower-third');
        $('wa2LtName').value = lt.name || '';
        $('wa2LtTagline').value = lt.tagline || '';
        $('wa2LtSocial').value = lt.social || '';
        $('wa2LtAvatar').value = lt.avatar_url || '';
        $('wa2LtTheme').value = lt.theme || 'minimal';
        setToggle('wa2LtVisible', !!lt.visible);
    } catch (e) {}
    try {
        const m = await wstateapi('/api/widgets/mascot');
        $('wa2MascotPreset').value = m.preset || 'blob';
        $('wa2MascotUrl').value = m.custom_url || '';
        $('wa2MascotIdle').value = m.idle_timeout_sec ?? 300;
    } catch (e) {}
    try {
        const ar = await wapi('/api/widgets/anime-runner');
        $('wa2ArHair').value = ar.hair_color || '#f5f5f5';
        $('wa2ArOutfit').value = ar.outfit_color || '#3a4';
        $('wa2ArAccent').value = ar.accent_color || '#ffaa44';
        $('wa2ArEye').value = ar.eye_color || '#3a8fff';
        $('wa2ArCorner').value = ar.corner || 'br';
        $('wa2ArSpeed').value = ar.speed || 'normal';
        $('wa2ArSize').value = ar.size || 'M';
        // Q14: восстановленные настройки v10.4.9 (были только в старом редакторе).
        setToggle('wa2ArEarsEnabled', ar.ears_enabled === undefined ? true : !!ar.ears_enabled);
        $('wa2ArEarsColor').value = ar.ears_color || '#222';
        $('wa2ArEarsInner').value = ar.ears_inner_color || '#ff7eb9';
        setToggle('wa2ArGlovesEnabled', !!ar.gloves_enabled);
        $('wa2ArGlovesColor').value = ar.gloves_color || '#ffffff';
        $('wa2ArShoes').value = ar.shoes_color || '#ffffff';
        $('wa2ArShirtPattern').value = ar.shirt_pattern || 'palm';
        $('wa2ArShorts').value = ar.shorts_color || '';
        $('wa2ArPathMode').value = ar.path_mode || 'lane';
        $('wa2ArPathPoints').value = ar.path_points || '[]';
        $('wa2ArPause').value = ar.pause_chance ?? 0.15;
        $('wa2ArIdle').value = ar.idle_timeout_sec ?? 300;
        $('wa2ArRandomPeriod').value = ar.random_period_sec ?? 90;
    } catch (e) {}
    try {
        const rl = await wstateapi('/api/widgets/chat-roulette');
        $('wa2RlParticipants').value = (rl.participants || []).join(', ');
        $('wa2RlSpin').value = rl.spin_duration_sec ?? 5;
        $('wa2RlAuto').value = rl.auto_interval_min ?? 0;
        $('wa2RlWinner').value = rl.winner || '';
        setToggle('wa2RlVisible', !!rl.visible);
    } catch (e) {}
    try {
        const le = await wapi('/api/widgets/latest-event-card');
        $('wa2LeTheme').value = le.theme || 'neon';
        $('wa2LeFilter').value = le.filter_kind || '';
    } catch (e) {}
    try {
        const ss = await wapi('/api/widgets/stream-session');
        $('wa2SsStatus').textContent = ss.is_live
            ? `🔴 В эфире с ${ss.start_time || '?'}`
            : '⚪ Не в эфире';
    } catch (e) {}
}

async function wa2LtSave() {
    try {
        await wstateapi('/api/widgets/lower-third', 'PUT', {
            name: $('wa2LtName').value, tagline: $('wa2LtTagline').value,
            social: $('wa2LtSocial').value, avatar_url: $('wa2LtAvatar').value,
            theme: $('wa2LtTheme').value, visible: toggleChecked('wa2LtVisible'),
        });
        toast(t('msg.saved'), 'success');
    } catch (e) { _waHint(e); }
}
async function wa2MascotSave() {
    try {
        await wstateapi('/api/widgets/mascot', 'PUT', {
            preset: $('wa2MascotPreset').value, custom_url: $('wa2MascotUrl').value,
            idle_timeout_sec: parseInt($('wa2MascotIdle').value, 10) || 300,
        });
        waRefreshScopedWidgetPreviews();
        toast(t('msg.saved'), 'success');
    } catch (e) { _waHint(e); }
}
async function wa2AnimeSave() {
    try {
        await wapi('/api/widgets/anime-runner', 'PUT', {
            hair_color: $('wa2ArHair').value, outfit_color: $('wa2ArOutfit').value,
            accent_color: $('wa2ArAccent').value, eye_color: $('wa2ArEye').value,
            corner: $('wa2ArCorner').value, speed: $('wa2ArSpeed').value,
            size: $('wa2ArSize').value,
            // Q14: восстановленные настройки v10.4.9 (ушки/перчатки/кроссовки/шорты,
            // узор футболки, маршрут и тайминги).
            ears_enabled: toggleChecked('wa2ArEarsEnabled'),
            ears_color: $('wa2ArEarsColor').value,
            ears_inner_color: $('wa2ArEarsInner').value,
            gloves_enabled: toggleChecked('wa2ArGlovesEnabled'),
            gloves_color: $('wa2ArGlovesColor').value,
            shoes_color: $('wa2ArShoes').value,
            shirt_pattern: $('wa2ArShirtPattern').value,
            shorts_color: $('wa2ArShorts').value,
            path_mode: $('wa2ArPathMode').value,
            path_points: ($('wa2ArPathPoints').value || '').trim() || '[]',
            pause_chance: parseFloat($('wa2ArPause').value),
            idle_timeout_sec: parseInt($('wa2ArIdle').value, 10) || 300,
            random_period_sec: parseInt($('wa2ArRandomPeriod').value, 10) || 90,
        });
        waRefreshScopedWidgetPreviews();
        toast(t('msg.saved'), 'success');
    } catch (e) { _waHint(e); }
}
async function wa2RouletteSave() {
    try {
        await wstateapi('/api/widgets/chat-roulette', 'PUT', {
            participants: $('wa2RlParticipants').value.split(',').map(s => s.trim()).filter(Boolean),
            spin_duration_sec: parseInt($('wa2RlSpin').value, 10) || 5,
            auto_interval_min: parseInt($('wa2RlAuto').value, 10) || 0,
            winner: $('wa2RlWinner').value,
            visible: toggleChecked('wa2RlVisible'),
        });
        waRefreshScopedWidgetPreviews();
        toast(t('msg.saved'), 'success');
    } catch (e) { _waHint(e); }
}
async function wa2RouletteSpin() {
    try {
        await wstateapi('/api/widgets/chat-roulette/spin', 'POST', {});
        await wa2LoadAll();
        toast('🎲', 'success');
    }
    catch (e) { _waHint(e); }
}
async function wa2LatestSave() {
    try {
        await wapi('/api/widgets/latest-event-card', 'PUT', {
            theme: $('wa2LeTheme').value, filter_kind: $('wa2LeFilter').value,
        });
        toast(t('msg.saved'), 'success');
    } catch (e) { _waHint(e); }
}
async function wa2SessionStart() {
    try { await wapi('/api/widgets/stream-session/start', 'POST', {}); wa2LoadAll(); toast('🔴', 'success'); }
    catch (e) { _waHint(e); }
}
async function wa2SessionStop() {
    try { await wapi('/api/widgets/stream-session/stop', 'POST', {}); wa2LoadAll(); toast('⚪', 'info'); }
    catch (e) { _waHint(e); }
}
async function wa2RecentAdd() {
    try {
        await wapi('/api/widgets/recent-events', 'POST', {
            kind: $('wa2ReKind').value, username: $('wa2ReUser').value,
            amount: parseInt($('wa2ReAmount').value, 10) || 0,
        });
        toast(t('msg.saved'), 'success');
    } catch (e) { _waHint(e); }
}
async function wa2RecentClear() {
    try { await wapi('/api/widgets/recent-events', 'DELETE'); toast('🗑', 'info'); }
    catch (e) { _waHint(e); }
}
const _prevWa2Load = loadWidgetsAdmin;
loadWidgetsAdmin = async function() { await _prevWa2Load(); wa2LoadAll(); };

