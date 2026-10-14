"""Canonical inventory and panel preview contracts for public OBS widgets.

Routes remain implemented by their owning modules; this registry is the single
source for discoverability and preview rendering in the Widgets panel. Tests
fail whenever a public overlay route or on-disk widget is missing here.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WidgetPreviewContract:
    slug: str
    title: str
    description: str
    route: str
    folder: str
    preview_url: str
    preview_mode: str = "live-dark"
    requires_channel: bool = True

    @property
    def verdict(self) -> str:
        return WIDGET_CATALOG_DETAILS[self.slug][0]

    @property
    def example(self) -> str:
        return WIDGET_CATALOG_DETAILS[self.slug][1]

    @property
    def catalog_note(self) -> str:
        return WIDGET_CATALOG_DETAILS[self.slug][2]

    @property
    def binding_slug(self) -> str:
        return WIDGET_BINDING_SLUGS.get(self.slug, "")

    @property
    def obs_width(self) -> int:
        return WIDGET_OBS_SIZES[self.slug][0]

    @property
    def obs_height(self) -> int:
        return WIDGET_OBS_SIZES[self.slug][1]

    @property
    def obs_layout(self) -> str:
        return WIDGET_OBS_SIZES[self.slug][2]


# P2 verdicts are intentionally product decisions, not promises of integrations.
# MERGE candidates remain separate public URLs until a browser/OBS acceptance pass.
WIDGET_CATALOG_DETAILS: dict[str, tuple[str, str, str]] = {
    "tts": ("MERGE ✅", "Сообщение DemoViewer попадает в очередь выбранного голоса.", "Wave 5: общий transport/очередь с TTS-семьёй, свой режим сырого чата и URL."),
    "animated-bg": ("KEEP", "Фон stars с тёмной подложкой для игровой сцены.", "Сохраняем собственные типы частиц и мягкий цикл."),
    "goals": ("BORROW", "Цель 50% показывает прогресс; на 100% появляется завершение.", "Крупные цифры и progress, данные и управление наши."),
    "now-playing": ("BORROW", "Длинное название трека сокращается рядом с обложкой.", "Берём читаемую компоновку; Last.fm/MPRIS/!np наши."),
    "sub-goal": ("BORROW", "25 из 50 подписок отображаются как половина шкалы.", "Milestone и progress без замены нашего API."),
    "schedule": ("BORROW", "Пустое расписание честно показывает отсутствие ближайших блоков.", "Карточки «сейчас/далее», расписание остаётся нашим."),
    "uptime": ("KEEP", "Оффлайн показывает нулевую/неактивную сессию без ложного таймера.", "Сохраняем session API и моноширинный таймер."),
    "follower-ticker": ("BORROW", "Новая подписка появляется в тёмной бегущей ленте.", "Скорость и пауза ленты, события канала наши."),
    "lower-third": ("BORROW", "Alekzz · играет в CS2 · @alekzz помещается в safe area.", "Enter/exit и безопасные поля; set binding наш."),
    "mascot": ("MERGE ✅", "Маскот переходит из idle в реакцию на событие.", "Wave 6: общий runtime с anime-runner, SVG-реакции и URL свои."),
    "anime-runner": ("MERGE ✅", "Персонаж бесшовно повторяет проход по нижнему краю.", "Wave 6: общий runtime с mascot, canvas-раннер и URL свои."),
    "chat-highlight": ("BORROW", "На пустом чате карточка ждёт первое выделенное сообщение.", "Переносы и enter/exit, источник чата наш."),
    "chat-roulette": ("BORROW", "Nick, Alex и Мария участвуют в пятисекундном спине.", "Wheel easing и честное empty state на наших зрителях."),
    "song-request": ("BORROW", "Без заказов видна пустая очередь, а не фиктивный трек.", "Очередь и empty state поверх нашего API."),
    "top-donator": ("MERGE ✅", "Один виджет показывает лидера за выбранный период (всё время / месяц / день).", "Wave 3 исполнена: общая реализация, три исторических URL сохранены."),
    "countdown": ("KEEP", "Таймер запускается, ставится на паузу и сбрасывается.", "Сохраняем собственные состояния и биндинги."),
    "donation-challenge": ("BORROW", "Факт 500 из цели 1000 заполняет половину шкалы.", "Progress/milestone, донаты нескольких провайдеров наши."),
    "clip-moments": ("KEEP", "Без API-прав показана понятная ошибка создания клипа.", "Не изображаем успешный клип без разрешения Twitch."),
    "latest-event-card": ("MERGE ✅", "Последний follow/sub/donate получает подходящий тип карточки.", "Wave 4: общая event-модель с recent-events, карточка и URL свои."),
    "tts-bot": ("MERGE ✅", "Golden Voice ждёт сообщение в очереди и показывает статус.", "Wave 5: общий transport/очередь, Golden Voice и URL свои."),
    "tts-chat-overlay": ("KEEP", "DemoBot и зритель исчезают после заданного времени.", "Фильтры all/rewards/bot и fade-out остаются нашими."),
    "hype-meter": ("BORROW", "Пустой чат держит шкалу у нуля без выдуманной активности.", "Анимированная шкала на нашем анализе чата."),
    "subathon-timer": ("KEEP", "Событие подписки добавляет настроенное время к таймеру.", "Сохраняем наши тарифы и milestone pulse."),
    "emoji-leaderboard": ("MERGE ✅", "Без эмодзи показана пустая таблица лидеров.", "Wave 7: общее ядро распознавания с emoji-chat, рейтинг и URL свои."),
    "blur-guard-v2": ("KEEP", "Preview показывает зоны и текущее blur_config без камеры.", "Единственный Blur Guard: reactive blur + зоны + live-конфигурация."),
    "chat-reader": ("MERGE ✅", "Без сообщений очередь озвучки остаётся пустой.", "Wave 5: общий transport/очередь, режим «пузырь с репликой» и URL свои."),
    "emoji-chat": ("MERGE ✅", "Стрим без эмодзи показывает спокойное empty state.", "Wave 7: общее ядро распознавания с emoji-leaderboard, лента и URL свои."),
    "selected-chat": ("KEEP", "В отдельной ленте видны только сообщения выбранных модераторов и друзей.", "Общий ручной allow-list, история и Twitch/7TV-смайлы; AI-бот для показа не требуется."),
    "media-share": ("BORROW", "Битая ссылка получает error state и не начинает воспроизведение.", "Очередь/ошибка поверх нашей модерации и лимитов."),
    "mod-feed": ("KEEP", "Пустой фид ждёт первое решение модерации.", "Компактный action feed на наших решениях."),
    "soundboard": ("BORROW", "Play запускает выбранный трек; без трека видна ошибка.", "Плитки/очередь/volume, upload/play/bind остаются нашими."),
    "recent-events": ("MERGE ✅", "DemoViewer отображается как follow в ленте до пяти событий.", "Wave 4: общая event-модель с latest-event-card, лента и URL свои."),
    "streamer-hud": ("KEEP", "Интерактивный суфлёр для стримера: подсказки тем, вопросы зрителей и детектор затишья.", "Карточки подсказок, вопросы чата и таймер затишья для стримера."),
}


# Recommended Browser Source canvas; it does not resize or crop the widget itself.
WIDGET_OBS_SIZES: dict[str, tuple[int, int, str]] = {
    "tts": (1000, 180, "overlay"),
    "animated-bg": (1920, 1080, "fullscreen"),
    "goals": (500, 500, "overlay"),
    "now-playing": (560, 120, "overlay"),
    "sub-goal": (520, 420, "overlay"),
    "schedule": (560, 500, "overlay"),
    "uptime": (360, 70, "overlay"),
    "follower-ticker": (1920, 80, "strip"),
    "lower-third": (520, 180, "overlay"),
    "mascot": (240, 240, "overlay"),
    "anime-runner": (1920, 1080, "fullscreen"),
    "chat-highlight": (640, 220, "overlay"),
    "chat-roulette": (420, 460, "overlay"),
    "song-request": (440, 320, "overlay"),
    "top-donator": (420, 240, "overlay"),
    "countdown": (700, 300, "overlay"),
    "donation-challenge": (560, 220, "overlay"),
    "clip-moments": (460, 360, "overlay"),
    "latest-event-card": (440, 280, "overlay"),
    "tts-bot": (900, 260, "overlay"),
    "tts-chat-overlay": (800, 240, "overlay"),
    "hype-meter": (340, 120, "overlay"),
    "subathon-timer": (360, 150, "overlay"),
    "emoji-leaderboard": (320, 360, "overlay"),
    "blur-guard-v2": (1920, 1080, "fullscreen"),
    "chat-reader": (800, 220, "overlay"),
    "emoji-chat": (480, 420, "overlay"),
    "selected-chat": (560, 600, "overlay"),
    "media-share": (1920, 1080, "fullscreen"),
    "mod-feed": (560, 500, "overlay"),
    "soundboard": (360, 60, "overlay"),
    "recent-events": (480, 420, "overlay"),
    "streamer-hud": (480, 560, "overlay"),
}

# Q7 (owner survey B6): вердикт — биндинги остаются в карточке своего виджета.
# Здесь перечислены только контракты со смысловыми действиями над самим
# виджетом; slug обязан совпадать с ALLOWED_ACTIONS в app/widget_bindings.py
# (гейт — test_w7_preview_contracts). Soundboard биндится своей кнопкой
# «⌨ Биндинг» у конкретного трека (play_track:<id>), moderation — не виджет,
# поэтому оба живут в общей секции, а не в карточке.
WIDGET_BINDING_SLUGS = {
    "goals": "goals", "sub-goal": "sub_goal",
    "countdown": "countdown", "now-playing": "now_playing", "lower-third": "lower_third",
    # Q27a (DEC-OWNER-017 п.4): контракт v2 — осмысленные действия.
    "mascot": "mascot", "uptime": "uptime", "subathon-timer": "subathon_timer",
    "donation-challenge": "donation_challenge", "song-request": "song_request",
    "chat-highlight": "chat_highlight", "chat-roulette": "chat_roulette",
    "recent-events": "recent_events", "blur-guard-v2": "blur_guard_v2",
}


# Keep route/folder aliases explicit: several stable public URLs intentionally
# differ from their implementation folder (uptime/stream-session).
WIDGET_INVENTORY: tuple[WidgetPreviewContract, ...] = (
    WidgetPreviewContract("tts", "🔊 TTS", "Озвучка сообщений чата", "/obs/tts", "tts-raw", "/obs/tts?channel=demo&preview=1"),
    WidgetPreviewContract("animated-bg", "✨ Анимированный фон", "Частицы и фон сцены", "/widget/animated-bg", "animated-bg", "/widget/animated-bg?type=stars&bg=%230f0f1a&preview=1", requires_channel=False),
    WidgetPreviewContract("goals", "🎯 Цели", "Прогресс целей стрима", "/widget/goals", "goals", "/widget/goals?preview=1"),
    WidgetPreviewContract("now-playing", "🎵 Сейчас играет", "Текущий трек", "/widget/now-playing", "now-playing", "/widget/now-playing?preview=1"),
    WidgetPreviewContract("sub-goal", "⭐ Sub goal", "Счётчик подписок", "/widget/sub-goal", "sub-goal", "/widget/sub-goal?preview=1"),
    WidgetPreviewContract("schedule", "📅 Расписание", "Ближайшие блоки эфира", "/widget/schedule", "schedule", "/widget/schedule?preview=1"),
    WidgetPreviewContract("uptime", "⏱ Uptime", "Продолжительность стрима", "/widget/uptime", "stream-session", "/widget/uptime?preview=1"),
    WidgetPreviewContract("follower-ticker", "🏃 Follower ticker", "Лента событий канала", "/widget/follower-ticker", "follower-ticker", "/widget/follower-ticker?preview=1"),
    WidgetPreviewContract("lower-third", "📛 Lower third", "Плашка стримера", "/widget/lower-third", "lower-third", "/widget/lower-third?preview=1"),
    WidgetPreviewContract("mascot", "🦉 Маскот", "Реактивный персонаж", "/widget/mascot", "mascot", "/widget/mascot?preview=1"),
    WidgetPreviewContract("anime-runner", "🏃 Anime runner", "Анимированный персонаж", "/widget/anime-runner", "anime-runner", "/widget/anime-runner?preview=1", requires_channel=False),
    WidgetPreviewContract("chat-highlight", "💬 Chat highlight", "Выделение сообщений", "/widget/chat-highlight", "chat-highlight", "/widget/chat-highlight?preview=1"),
    WidgetPreviewContract("chat-roulette", "🎲 Chat roulette", "Рулетка зрителей", "/widget/chat-roulette", "chat-roulette", "/widget/chat-roulette?preview=1"),
    WidgetPreviewContract("song-request", "🎧 Song request", "Очередь заказанных треков", "/widget/song-request", "song-request", "/widget/song-request?preview=1"),
    WidgetPreviewContract("top-donator", "💰 Топ донатеров", "Лидер за период: всё время / месяц / день", "/widget/top-donator", "top-donator", "/widget/top-donator?period=alltime&preview=1"),
    WidgetPreviewContract("countdown", "⏳ Countdown", "Таймер и секундомер", "/widget/countdown", "countdown", "/widget/countdown?preview=1"),
    WidgetPreviewContract("donation-challenge", "🎯 Donation challenge", "Прогресс донат-сбора", "/widget/donation-challenge", "donation-challenge", "/widget/donation-challenge?preview=1"),
    WidgetPreviewContract("clip-moments", "🎬 Clip moments", "Моменты для клипов", "/widget/clip-moments", "clip-moments", "/widget/clip-moments?preview=1"),
    WidgetPreviewContract("latest-event-card", "⚡ Latest event", "Последнее событие канала", "/widget/latest-event-card", "latest-event-card", "/widget/latest-event-card?preview=1"),
    WidgetPreviewContract("tts-bot", "🎙 TTS bot", "Golden Voice overlay", "/widget/tts-bot", "tts-bot", "/widget/tts-bot?preview=1"),
    WidgetPreviewContract("tts-chat-overlay", "💬 TTS chat", "Реплики бота и наград", "/widget/tts-chat-overlay", "tts-chat-overlay", "/widget/tts-chat-overlay?preview=1", "representative-dark"),
    WidgetPreviewContract("hype-meter", "📈 Hype meter", "Шкала активности чата", "/widget/hype-meter", "hype-meter", "/widget/hype-meter?preview=1"),
    WidgetPreviewContract("subathon-timer", "🦾 Subathon", "Продлеваемый таймер", "/widget/subathon-timer", "subathon-timer", "/widget/subathon-timer?preview=1"),
    WidgetPreviewContract("emoji-leaderboard", "🏆 Emoji leaderboard", "Лидеры по эмодзи", "/widget/emoji-leaderboard", "emoji-leaderboard", "/widget/emoji-leaderboard?preview=1"),
    WidgetPreviewContract("blur-guard-v2", "🛡 Blur guard", "Зоны размытия и reactive blur в OBS", "/obs/blur-guard-v2", "blur-guard-v2", "/obs/blur-guard-v2?preview=1", requires_channel=False),
    WidgetPreviewContract("chat-reader", "🔊 Chat reader", "Озвучка чата", "/widget/chat-reader", "chat-reader", "/widget/chat-reader?preview=1"),
    WidgetPreviewContract("emoji-chat", "🦾 Emoji chat", "Чат из эмодзи", "/widget/emoji-chat", "emoji-chat", "/widget/emoji-chat?preview=1"),
    WidgetPreviewContract("selected-chat", "⭐ Избранный чат", "Сообщения выбранных людей", "/widget/selected-chat", "selected-chat", "/widget/selected-chat?preview=1"),
    WidgetPreviewContract("media-share", "📺 Media share", "Медиа от зрителей", "/widget/media-share", "media-share", "/widget/media-share?preview=1"),
    WidgetPreviewContract("mod-feed", "🛡 Mod feed", "Решения модерации", "/widget/mod-feed", "mod-feed", "/widget/mod-feed?preview=1"),
    WidgetPreviewContract("soundboard", "🎵 Soundboard", "Аудио по биндингам", "/widget/soundboard", "soundboard", "/widget/soundboard?preview=1"),
    WidgetPreviewContract("recent-events", "📡 Recent events", "Лента событий", "/widget/recent-events", "recent-events", "/widget/recent-events?preview=1", "representative-dark"),
    WidgetPreviewContract("streamer-hud", "🎙 Streamer HUD", "Суфлёр и подсказки для стримера", "/widget/streamer-hud", "streamer-hud", "/widget/streamer-hud?preview=1", requires_channel=False),
)

WIDGET_BY_ROUTE = {item.route: item for item in WIDGET_INVENTORY}


# Protected outputs are generated from an owner-only control surface and cannot
# have a reusable panel preview URL because each URL carries a rotated scope token.
PROTECTED_WIDGET_OUTPUTS: dict[str, str] = {
    "/widget/moderator-media": "exact account + channel + rotated OBS token",
}


# ── Выведенные из эксплуатации виджеты (owner survey 03.09) ─────────
#
# Карточка и реализация удалены, но публичный URL остаётся жить: у владельца
# уже настроены OBS Browser Source на эти адреса, и молчаливый 404 в сцене
# выглядит как поломка. Роут отдаёт тёмную заглушку с причиной и заменой
# (см. widgets._retired_widget_html). Удаление самих URL — отдельное решение.
RETIRED_WIDGETS: dict[str, tuple[str, str, str]] = {
    "/widget/voice-changer": (
        "Изменение голоса",
        "Виджет выведен из эксплуатации: voice-pipeline не используется.",
        "",
    ),
    "/widget/counter": (
        "Счётчик",
        "Виджет-оверлей выведен из эксплуатации (owner survey Q12). "
        "API счётчиков и чат-команды продолжают работать.",
        "",
    ),
    "/widget/combo-counter": (
        "Счётчик комбо",
        "Виджет выведен из эксплуатации (owner survey Q14): "
        "серии одинаковых сообщений больше не отслеживаются.",
        "",
    ),
    "/widget/typing-indicator": (
        "Индикатор сообщений",
        "Виджет выведен из эксплуатации (owner survey Q26): "
        "событие «мод/VIP только что написал» больше не рассылается.",
        "",
    ),
    "/widget/poll-overlay": (
        "Оверлей опросов",
        "Оверлей и свой !vote-опрос выведены из эксплуатации (owner survey Q28). "
        "Нативные Twitch Polls создаются из панели и показываются самим Twitch.",
        "",
    ),
}


RETIRED_WIDGET_TRANSLATIONS: dict[str, dict[str, tuple[str, str]]] = {
    "en": {
        "/widget/voice-changer": (
            "Voice changer",
            "This widget has been retired: the voice pipeline is no longer used.",
        ),
        "/widget/counter": (
            "Counter",
            "The overlay has been retired (owner survey Q12). "
            "The counter API and chat commands still work.",
        ),
        "/widget/combo-counter": (
            "Combo counter",
            "This widget has been retired (owner survey Q14): "
            "runs of identical messages are no longer tracked.",
        ),
        "/widget/typing-indicator": (
            "Typing indicator",
            "This widget has been retired (owner survey Q26): "
            "the ‘mod/VIP just posted’ event is no longer broadcast.",
        ),
        "/widget/poll-overlay": (
            "Poll overlay",
            "The overlay and custom !vote poll have been retired (owner survey Q28). "
            "Native Twitch Polls are created in the panel and displayed by Twitch.",
        ),
    },
    "ua": {
        "/widget/voice-changer": (
            "Зміна голосу",
            "Віджет виведено з експлуатації: голосовий конвеєр більше не використовується.",
        ),
        "/widget/counter": (
            "Лічильник",
            "Віджет-оверлей виведено з експлуатації (опитування власника Q12). "
            "API лічильників і команди чату продовжують працювати.",
        ),
        "/widget/combo-counter": (
            "Лічильник комбо",
            "Віджет виведено з експлуатації (опитування власника Q14): "
            "серії однакових повідомлень більше не відстежуються.",
        ),
        "/widget/typing-indicator": (
            "Індикатор повідомлень",
            "Віджет виведено з експлуатації (опитування власника Q26): "
            "подія «модератор/VIP щойно написав» більше не розсилається.",
        ),
        "/widget/poll-overlay": (
            "Оверлей опитувань",
            "Оверлей і власне !vote-опитування виведено з експлуатації (опитування власника Q28). "
            "Нативні Twitch Polls створюються з панелі та показуються самим Twitch.",
        ),
    },
}


# The historical owner-authorized chat output is not a reusable public widget.
LEGACY_WIDGET_OUTPUTS: dict[str, str] = {
    "/obs-widget": "owner-authorized chat projection via /ws; user text is preserved",
}


# ── Alias-URL: старый адрес продолжает отдавать актуальный виджет ───
#
# Отличие от RETIRED_WIDGETS: здесь замена умеет всё, что умел старый виджет,
# поэтому сцена в OBS работает как раньше, а не показывает заглушку.
ALIAS_WIDGETS: dict[str, str] = {
    # owner survey Q36: старый Blur Guard удалён, v2 покрывает его функции.
    "/obs/blur-guard": "/obs/blur-guard-v2",
}


# ── Исторические URL объединённых виджетов ─────────────────────────
#
# Wave 3 (owner survey Q15-17): три top-donator стали одной реализацией с
# параметром period. Эти адреса уже стоят в OBS-сценах владельца, поэтому
# продолжают работать и отдают тот же виджет с зафиксированным периодом.
LEGACY_PARAM_URLS: dict[str, str] = {
    "/widget/top-donator-alltime": "/widget/top-donator?period=alltime",
    "/widget/top-donator-month": "/widget/top-donator?period=month",
    "/widget/top-donator-day": "/widget/top-donator?period=day",
}
