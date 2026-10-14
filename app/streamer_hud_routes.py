"""v10.5 — OBS Streamer HUD / Суфлёр для стримера.

Интерактивный виджет для OBS Browser Source и OBS Custom Browser Docks:
- 💬 Детектор вопросов зрителей из чата (с кнопкой быстрого списания «✓»)
- 💡 Подсказки тем и темники для разговора (Cue Cards / Prompts)
- ⏱️ Индикатор затишья эфира (Dead-Air Alert)
- 📝 Заметки стримера
- ⚡ Быстрые действия прямо из дока (Хайп, Оживить, Пауза 2м)
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.widgets import _widget_html
from app.database import get_db

router = APIRouter()

# In-memory storage for HUD state
_DISMISSED_IDS: set[str] = set()
_CUSTOM_NOTES: dict[str, list[dict[str, Any]]] = {}  # channel -> list of notes
_CUSTOM_TOPICS_ROTATION: dict[str, int] = {}

BUILTIN_TOPICS = [
    {
        "title": "Тактика и билд",
        "hint": "Расскажи зрителям, почему выбрал текущую стратегию и какие плюсы/минусы видишь.",
    },
    {
        "title": "Опрос чата",
        "hint": "Спроси чат, кто уже играл в эту версию и какие эмоции оставила игра.",
    },
    {
        "title": "Планы на стрим",
        "hint": "Поделись ближайшей целью на стриме (босс, ранг, челлендж) и спроси совета.",
    },
    {
        "title": "Впечатления от обновления",
        "hint": "Обсуди последние патч-ноуты: что разработчики сделали круто, а что спорно.",
    },
    {
        "title": "Интерактив со зрителями",
        "hint": "Предложи зрителям выбрать следующее действие или челлендж через чат.",
    },
]

_QUESTION_PATTERNS = re.compile(
    r"\?|(?:^|\s)(?:кто|что|где|когда|зачем|почему|как|куда|откуда|сколько|какой|какая|какие|каком|будет|будешь|смотришь|играл|подруб|will|what|when|where|why|how|who|is|are|can|could|did)(?:\s|$)",
    re.IGNORECASE,
)


def _format_time_ago(ts: float, now: float) -> str:
    diff = max(0, int(now - ts))
    if diff < 60:
        return f"{diff}с назад"
    mins = diff // 60
    if mins < 60:
        return f"{mins}м назад"
    return f"{mins // 60}ч назад"


@router.get("/widget/streamer-hud", response_class=HTMLResponse)
async def widget_streamer_hud():
    """OBS Browser Source & Custom Dock page for Streamer HUD."""
    return HTMLResponse(_widget_html("streamer-hud"))


@router.get("/api/widgets/streamer-hud/state")
async def get_streamer_hud_state(
    request: Request,
    channel: str = "",
    preview: bool = False,
) -> dict:
    from app.server import bot_manager, chat_analyzer

    now = time.time()
    ch_clean = (channel or "").lstrip("#").lower()

    if not ch_clean:
        # Автоматически берём первый активный канал
        statuses = bot_manager.get_all_statuses()
        for aid, st in statuses.items():
            if st.get("connected") and st.get("channels"):
                ch_clean = st["channels"][0].lstrip("#").lower()
                break

    # 1. PREVIEW MODE
    if preview:
        return {
            "ok": True,
            "channel": ch_clean or "streamer",
            "silence_sec": 18,
            "silence_alert": False,
            "chat_speed_cpm": 32,
            "questions": [
                {
                    "id": "prev_q1",
                    "author": "ViewerAlex",
                    "text": "Какой билд сейчас качаешь? Через криты или урон?",
                    "time_ago": "25с назад",
                },
                {
                    "id": "prev_q2",
                    "author": "CyberFox",
                    "text": "Во сколько завтра стрим по турниру?",
                    "time_ago": "1м назад",
                },
            ],
            "topics": [
                {
                    "id": "prev_t1",
                    "title": "Обсудить новый патч",
                    "hint": "Спроси чат, кто уже затестил последние изменения в игре.",
                },
                {
                    "id": "prev_t2",
                    "title": "Тактика на босса",
                    "hint": "Расскажи, почему выбрал ветку огня вместо льда.",
                },
            ],
            "notes": [
                {
                    "id": "prev_n1",
                    "text": "Розыгрыш ключа в 21:00",
                    "created_at": "5м назад",
                }
            ],
            "quick_pause_active": False,
            "quick_pause_sec": 0,
        }

    # 2. LIVE DATA
    # Silence detection
    last_act = 0.0
    for (aid, ch), act_ts in chat_analyzer._channel_last_activity.items():
        if ch == ch_clean and act_ts > last_act:
            last_act = act_ts

    if last_act > 0:
        silence_sec = max(0, int(now - last_act))
    else:
        silence_sec = 0

    silence_alert = silence_sec >= 90  # 1.5 мин без сообщений

    # Questions detection from chat buffer & chat_log
    questions = []
    seen_texts = set()

    # Сначала проверяем свежий in-memory буфер чата
    for (aid, ch), act_ts in chat_analyzer._channel_last_activity.items():
        if ch == ch_clean:
            buf_key = chat_analyzer._buffer_key(aid, ch_clean)
            recent = chat_analyzer._chat_buffer.get(buf_key, [])
            for m in reversed(recent[-25:]):
                txt = (m.get("text") or "").strip()
                author = (m.get("author") or "").strip()
                if not txt or txt.startswith("!") or len(txt) < 5 or txt in seen_texts:
                    continue
                q_id = f"q_{abs(hash(txt + author))}"
                if q_id in _DISMISSED_IDS:
                    continue
                if _QUESTION_PATTERNS.search(txt):
                    seen_texts.add(txt)
                    questions.append({
                        "id": q_id,
                        "author": author,
                        "text": txt,
                        "time_ago": _format_time_ago(m.get("time", now), now),
                    })
                if len(questions) >= 5:
                    break
        if len(questions) >= 5:
            break

    # Если буфер пуст, читаем из chat_log
    if not questions and ch_clean:
        try:
            db = await get_db()
            try:
                cur = await db.execute(
                    "SELECT id, author, message, timestamp FROM chat_log "
                    "WHERE channel=? AND is_bot=0 ORDER BY id DESC LIMIT 20",
                    (ch_clean,)
                )
                rows = await cur.fetchall()
                for row in rows:
                    m_id, author, msg, ts_str = row
                    txt = (msg or "").strip()
                    if not txt or txt.startswith("!") or len(txt) < 5 or txt in seen_texts:
                        continue
                    q_id = f"q_db_{m_id}"
                    if q_id in _DISMISSED_IDS:
                        continue
                    if _QUESTION_PATTERNS.search(txt):
                        seen_texts.add(txt)
                        questions.append({
                            "id": q_id,
                            "author": author,
                            "text": txt,
                            "time_ago": "недавно",
                        })
                    if len(questions) >= 5:
                        break
            finally:
                await db.close()
        except Exception:
            pass

    # Chat speed estimate
    chat_speed_cpm = max(len(seen_texts) * 3, 0)

    # Topics rotation
    rot_idx = _CUSTOM_TOPICS_ROTATION.get(ch_clean, 0)
    topics = []
    for i in range(2):
        t_obj = BUILTIN_TOPICS[(rot_idx + i) % len(BUILTIN_TOPICS)]
        t_id = f"t_{rot_idx + i}"
        if t_id not in _DISMISSED_IDS:
            topics.append({
                "id": t_id,
                "title": t_obj["title"],
                "hint": t_obj["hint"],
            })

    # Notes
    notes = [
        n for n in _CUSTOM_NOTES.get(ch_clean, [])
        if n["id"] not in _DISMISSED_IDS
    ]

    paused, remaining = chat_analyzer.is_paused()
    from app.tts_mute_state import is_tts_muted
    tts_muted, tts_remaining = is_tts_muted(ch_clean)

    return {
        "ok": True,
        "channel": ch_clean,
        "silence_sec": silence_sec,
        "silence_alert": silence_alert,
        "chat_speed_cpm": chat_speed_cpm,
        "questions": questions[:5],
        "topics": topics,
        "notes": notes,
        "quick_pause_active": paused,
        "quick_pause_sec": remaining,
        "tts_mute_active": tts_muted,
        "tts_mute_sec": tts_remaining,
    }


@router.post("/api/widgets/streamer-hud/dismiss")
async def dismiss_streamer_hud_item(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception:
        data = {}
    item_id = str(data.get("id") or "").strip()
    if item_id:
        _DISMISSED_IDS.add(item_id)
        return {"ok": True, "dismissed": item_id}
    return {"ok": False, "error": "id_required"}


@router.post("/api/widgets/streamer-hud/note")
async def add_streamer_hud_note(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception:
        data = {}
    text = (data.get("text") or "").strip()
    channel = (data.get("channel") or "").strip().lstrip("#").lower()
    if not text:
        return {"ok": False, "error": "text_required"}

    note_id = f"n_{int(time.time() * 1000)}"
    note = {
        "id": note_id,
        "text": text[:200],
        "created_at": "только что",
    }
    if channel not in _CUSTOM_NOTES:
        _CUSTOM_NOTES[channel] = []
    _CUSTOM_NOTES[channel].insert(0, note)
    _CUSTOM_NOTES[channel] = _CUSTOM_NOTES[channel][:10]
    return {"ok": True, "note": note}


@router.post("/api/widgets/streamer-hud/topic/new")
async def next_streamer_hud_topic(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception:
        data = {}
    channel = (data.get("channel") or "").strip().lstrip("#").lower()
    curr = _CUSTOM_TOPICS_ROTATION.get(channel, 0)
    _CUSTOM_TOPICS_ROTATION[channel] = (curr + 1) % len(BUILTIN_TOPICS)
    return {"ok": True, "index": _CUSTOM_TOPICS_ROTATION[channel]}


@router.post("/api/widgets/streamer-hud/action")
async def streamer_hud_action(request: Request) -> dict:
    """Trigger quick-actions directly from Streamer HUD / OBS Dock."""
    from app.director_routes import director_quick_action
    return await director_quick_action(request)
