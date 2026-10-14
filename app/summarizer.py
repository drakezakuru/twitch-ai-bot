"""§14 BRAIN_PLAN: Stream Summarizer.

Три режима:
  1) Live summary — каждые N минут (настраивается, дефолт 30) считаем
     краткую сводку последних сообщений чата + vision-описаний и
     складываем в summarizer_live + bot_logs.
  2) Run («прогнать стрим») — большая фоновая задача: разбивает период
     стрима на 30-мин окна, для каждого делает digest, кладёт в
     summarizer_checkpoints (resumable). По завершении — финальный отчёт
     (summary_md, events, funny, chat, lore-suggestions) → summarizer_runs.
  3) Lore — по итогам прогона рождаем suggestions в streamer_lore
     (status='suggested'), владелец подтверждает вручную.

Изоляция: per (account_id, channel) — channel='' = глобально по аккаунту.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from app.database import get_db

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUMMARY_ROOT = PROJECT_ROOT / "data" / "bots" / "summarizer"


# ---------------- helpers ----------------


def _normalize_channel(channel: str) -> str:
    return (channel or "").strip().lower().lstrip("#")


def _run_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _safe_dt(s: Any) -> Optional[datetime]:
    if not s:
        return None
    try:
        if isinstance(s, datetime):
            dt = s
        else:
            dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


# ---------------- ensure tables ----------------


async def ensure_tables() -> None:
    db = await get_db()
    try:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS summarizer_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                run_date TEXT NOT NULL,
                period_start TIMESTAMP NOT NULL,
                period_end   TIMESTAMP NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'running', 'done', 'failed', 'cancelled')),
                lang TEXT NOT NULL DEFAULT 'ru',
                summary_md TEXT NOT NULL DEFAULT '',
                events_json TEXT NOT NULL DEFAULT '[]',
                funny_json  TEXT NOT NULL DEFAULT '[]',
                chat_json   TEXT NOT NULL DEFAULT '[]',
                lore_json   TEXT NOT NULL DEFAULT '[]',
                progress_sec INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                finished_at TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
                UNIQUE(account_id, channel, run_date)
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_sumr_scope ON summarizer_runs(account_id, channel, run_date)"
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS summarizer_checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                window_start TIMESTAMP NOT NULL,
                window_end   TIMESTAMP NOT NULL,
                digest TEXT NOT NULL DEFAULT '',
                n_messages INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (run_id) REFERENCES summarizer_runs(id) ON DELETE CASCADE
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_sumcp_run ON summarizer_checkpoints(run_id, window_start)"
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS summarizer_live (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                window_start TIMESTAMP NOT NULL,
                window_end   TIMESTAMP NOT NULL,
                digest TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_sumlive_scope ON summarizer_live(account_id, channel, window_start)"
        )
        await db.commit()
    finally:
        await db.close()


# ---------------- live summary ----------------


async def _fetch_chat_window(
    account_id: int, channel: str, start: datetime, end: datetime, limit: int = 200
) -> list[dict]:
    """Возвращает список {author, message, ts, is_bot} за [start, end)."""
    try:
        db = await get_db()
        try:
            cursor = await db.execute(
                """SELECT author, message, is_bot, timestamp
                   FROM chat_log
                   WHERE account_id = ? AND channel = ?
                     AND timestamp >= ? AND timestamp < ?
                   ORDER BY timestamp ASC LIMIT ?""",
                (account_id, _normalize_channel(channel),
                 start.strftime("%Y-%m-%d %H:%M:%S"),
                 end.strftime("%Y-%m-%d %H:%M:%S"),
                 limit),
            )
            rows = await cursor.fetchall()
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("_fetch_chat_window error: %s", exc)
        return []
    out = []
    for r in rows:
        out.append({
            "author": r["author"],
            "message": r["message"],
            "is_bot": bool(r["is_bot"]),
            "ts": str(r["timestamp"]) if r["timestamp"] else "",
        })
    return out


def _build_digest_prompt(messages: list[dict], lang: str = "ru") -> str:
    """Готовит промпт для AI-саммари окна."""
    if not messages:
        return ""
    lines = []
    for m in messages[-100:]:  # cap на размер
        prefix = "[bot]" if m.get("is_bot") else ""
        lines.append(f"- {prefix}{m.get('author','')}: {m.get('message','')[:200]}")
    body = "\n".join(lines)
    if lang == "en":
        instr = ("You are an editor summarising a Twitch chat window. "
                 "Write 1-2 sentences (≤50 words) capturing the main topic and vibe. "
                 "If nothing useful — write 'no topic'.")
    else:
        instr = ("Ты редактор, делаешь краткую сводку окна Twitch-чата. "
                 "Напиши 1-2 предложения (до 50 слов) о главной теме и настроении. "
                 "Если темы нет — напиши «тема не определена».")
    return f"{instr}\n\nСообщения:\n{body}"


async def write_live_summary(
    account_id: int,
    channel: str,
    start: datetime,
    end: datetime,
    digest: str,
) -> int:
    """Сохраняет live-сводку и возвращает её id."""
    await ensure_tables()
    channel = _normalize_channel(channel)
    try:
        db = await get_db()
        try:
            cursor = await db.execute(
                """INSERT INTO summarizer_live
                   (account_id, channel, window_start, window_end, digest)
                   VALUES (?, ?, ?, ?, ?)""",
                (account_id, channel,
                 start.strftime("%Y-%m-%d %H:%M:%S"),
                 end.strftime("%Y-%m-%d %H:%M:%S"),
                 (digest or "")[:2000]),
            )
            await db.commit()
            return int(cursor.lastrowid or 0)
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("write_live_summary error: %s", exc)
        return 0


async def get_live_digest(
    account_id: int, channel: str, *, since: Optional[datetime] = None
) -> str:
    """Возвращает последнюю live-сводку (или накопление последних N) для prompt."""
    await ensure_tables()
    channel = _normalize_channel(channel)
    params: list[Any] = [account_id, channel]
    where_extra = ""
    if since:
        where_extra = " AND window_start >= ?"
        params.append(since.strftime("%Y-%m-%d %H:%M:%S"))
    params.append(5)
    try:
        db = await get_db()
        try:
            cursor = await db.execute(
                f"""SELECT digest, window_start, window_end FROM summarizer_live
                    WHERE account_id = ? AND channel = ?{where_extra}
                    ORDER BY window_start DESC LIMIT ?""",
                tuple(params),
            )
            rows = await cursor.fetchall()
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("get_live_digest error: %s", exc)
        return ""
    if not rows:
        return ""
    rows = list(reversed(rows))  # chronological
    parts = ["Live-сводки стрима (по убыванию свежести, последние сверху):"]
    for r in rows[-5:]:
        ts = str(r["window_start"] or "")
        d = (r["digest"] or "").strip()
        if d:
            parts.append(f"  [{ts}] {d}")
    return "\n".join(parts)


# ---------------- runs ----------------


async def create_run(
    account_id: int,
    channel: str,
    period_start: datetime,
    period_end: datetime,
    *,
    lang: str = "ru",
) -> dict | None:
    """Создаёт (или возвращает существующий) прогон."""
    await ensure_tables()
    channel = _normalize_channel(channel)
    if period_end <= period_start:
        return None
    run_date = _run_date(period_start)
    try:
        db = await get_db()
        try:
            cursor = await db.execute(
                """SELECT * FROM summarizer_runs
                   WHERE account_id = ? AND channel = ? AND run_date = ?""",
                (account_id, channel, run_date),
            )
            row = await cursor.fetchone()
            if row:
                return dict(row)
            cursor = await db.execute(
                """INSERT INTO summarizer_runs
                   (account_id, channel, run_date, period_start, period_end, status, lang)
                   VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
                (account_id, channel, run_date,
                 period_start.strftime("%Y-%m-%d %H:%M:%S"),
                 period_end.strftime("%Y-%m-%d %H:%M:%S"),
                 lang or "ru"),
            )
            await db.commit()
            run_id = int(cursor.lastrowid or 0)
            cursor = await db.execute(
                "SELECT * FROM summarizer_runs WHERE id = ?", (run_id,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("create_run error: %s", exc)
        return None


async def update_run(run_id: int, **fields: Any) -> bool:
    if not fields:
        return False
    allowed = {
        "status", "summary_md", "events_json", "funny_json",
        "chat_json", "lore_json", "progress_sec", "error",
        "finished_at",
    }
    sets = []
    params: list[Any] = []
    for k, v in fields.items():
        if k not in allowed:
            continue
        sets.append(f"{k} = ?")
        params.append(v)
    if not sets:
        return False
    params.append(run_id)
    try:
        db = await get_db()
        try:
            await db.execute(
                f"UPDATE summarizer_runs SET {', '.join(sets)} WHERE id = ?",
                tuple(params),
            )
            await db.commit()
            return True
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("update_run error: %s", exc)
        return False


async def list_runs(
    account_id: int, channel: str = "", *, limit: int = 50
) -> list[dict]:
    """channel='*' — прогоны всех каналов (PLAN_FEEDBACK_3008 §2.1)."""
    await ensure_tables()
    channel = _normalize_channel(channel)
    all_scopes = channel == "*"
    try:
        db = await get_db()
        try:
            ch_cond = "" if all_scopes else "AND channel = ?"
            cursor = await db.execute(
                f"""SELECT * FROM summarizer_runs
                   WHERE account_id = ? {ch_cond}
                   ORDER BY run_date DESC, id DESC LIMIT ?""",
                (account_id, *([] if all_scopes else [channel]), limit),
            )
            rows = await cursor.fetchall()
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("list_runs error: %s", exc)
        return []
    return [dict(r) for r in rows]


async def get_run(run_id: int) -> dict | None:
    await ensure_tables()
    try:
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT * FROM summarizer_runs WHERE id = ?", (run_id,)
            )
            row = await cursor.fetchone()
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("get_run error: %s", exc)
        return None
    return dict(row) if row else None


async def delete_run(run_id: int) -> bool:
    await ensure_tables()
    try:
        db = await get_db()
        try:
            await db.execute("DELETE FROM summarizer_runs WHERE id = ?", (run_id,))
            await db.commit()
            return True
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("delete_run error: %s", exc)
        return False


# ---------------- checkpoints ----------------


async def add_checkpoint(
    run_id: int, window_start: datetime, window_end: datetime,
    digest: str, n_messages: int = 0,
) -> int:
    await ensure_tables()
    try:
        db = await get_db()
        try:
            cursor = await db.execute(
                """INSERT INTO summarizer_checkpoints
                   (run_id, window_start, window_end, digest, n_messages)
                   VALUES (?, ?, ?, ?, ?)""",
                (run_id,
                 window_start.strftime("%Y-%m-%d %H:%M:%S"),
                 window_end.strftime("%Y-%m-%d %H:%M:%S"),
                 (digest or "")[:4000],
                 int(n_messages or 0)),
            )
            await db.commit()
            return int(cursor.lastrowid or 0)
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("add_checkpoint error: %s", exc)
        return 0


async def get_checkpoints(run_id: int) -> list[dict]:
    await ensure_tables()
    try:
        db = await get_db()
        try:
            cursor = await db.execute(
                """SELECT * FROM summarizer_checkpoints
                   WHERE run_id = ? ORDER BY window_start ASC""",
                (run_id,),
            )
            rows = await cursor.fetchall()
        finally:
            await db.close()
    except Exception as exc:
        logger.warning("get_checkpoints error: %s", exc)
        return []
    return [dict(r) for r in rows]


# ---------------- run pipeline ----------------


async def execute_run(
    run_id: int,
    ai_service: Any,
    *,
    window_minutes: int = 30,
    language: str = "ru",
    lore_suggester: Any | None = None,
) -> bool:
    """Главная фоновая задача: разбивает период на окна, делает digests,
    генерирует финальный отчёт.

    ``ai_service``  — объект AIService (или совместимый с .generate_text()).
    ``lore_suggester`` — async fn(run_id, lore_json) для отправки suggestions.

    Возвращает True при успехе.
    """
    await ensure_tables()
    run = await get_run(run_id)
    if not run:
        return False
    if run.get("status") == "done":
        return True
    pstart = _safe_dt(run.get("period_start"))
    pend = _safe_dt(run.get("period_end"))
    if not pstart or not pend:
        await update_run(run_id, status="failed", error="invalid_period")
        return False
    account_id = int(run["account_id"])
    channel = run["channel"]
    lang = (run.get("lang") or language or "ru").lower()

    await update_run(run_id, status="running", error="")
    try:
        # --- Phase 1: checkpoints (resumable) ---
        existing_cp = await get_checkpoints(run_id)
        cp_map = {str(c.get("window_start") or ""): c for c in existing_cp}
        total_sec = int((pend - pstart).total_seconds())
        window_sec = max(300, int(window_minutes) * 60)  # min 5 min
        cur = pstart
        progress = 0
        while cur < pend:
            nxt = min(cur + timedelta(seconds=window_sec), pend)
            key = cur.strftime("%Y-%m-%d %H:%M:%S")
            if key in cp_map:
                cp = cp_map[key]
                digest = cp.get("digest") or ""
                n_msgs = int(cp.get("n_messages") or 0)
            else:
                messages = await _fetch_chat_window(account_id, channel, cur, nxt)
                n_msgs = len(messages)
                digest = ""
                if messages and ai_service is not None:
                    prompt = _build_digest_prompt(messages, lang=lang)
                    if prompt:
                        try:
                            digest = await ai_service.generate_text(
                                prompt=prompt,
                                system="Краткая сводка окна чата.",
                                account_id=account_id,
                                channel=channel,
                                temperature=0.2,
                            )
                        except Exception as exc:
                            logger.warning("digest ai error: %s", exc)
                            digest = ""
                digest = (digest or "").strip()
                await add_checkpoint(run_id, cur, nxt, digest, n_messages=n_msgs)
            progress = int((nxt - pstart).total_seconds())
            if progress % (window_sec * 4) < window_sec:
                await update_run(run_id, progress_sec=progress)
            cur = nxt
        if total_sec > 0:
            await update_run(run_id, progress_sec=total_sec)

        # --- Phase 2: финальный отчёт ---
        cps = await get_checkpoints(run_id)
        cps_sorted = sorted(cps, key=lambda c: str(c.get("window_start") or ""))
        if not cps_sorted:
            await update_run(run_id, status="done", error="no_data",
                             finished_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
            return True

        digest_blobs = []
        for c in cps_sorted:
            ws = str(c.get("window_start") or "")
            d = (c.get("digest") or "").strip()
            n = int(c.get("n_messages") or 0)
            if d:
                digest_blobs.append(f"[{ws} | {n} сообщений]\n{d}")
        joined = "\n\n".join(digest_blobs)[:20000]

        if lang == "en":
            final_prompt = (
                "You are an editor writing a post-stream report.\n"
                "Given the chronological digests of 30-min chat windows below, "
                "produce a structured report in Markdown with sections:\n"
                "## Highlights (3-5 bullets)\n"
                "## Funny moments (2-4 bullets)\n"
                "## Fails / Conflicts (0-3 bullets)\n"
                "## Chat reaction (1-2 sentences)\n"
                "## Game / Stream events (1-3 bullets)\n"
                "## Suggested 'lore' facts about the streamer (0-3, single sentence each, in third person)\n\n"
                f"DATA:\n{joined}"
            )
            lore_block_instr = ""
        else:
            final_prompt = (
                "Ты редактор отчёта по стриму. Ниже — хронологические digest'ы "
                "30-мин окон чата.\n"
                "Сделай структурированный отчёт в Markdown с секциями:\n"
                "## Главное (3-5 пунктов)\n"
                "## Смешные моменты (2-4 пункта)\n"
                "## Неудачи / Конфликты (0-3 пункта)\n"
                "## Реакция чата (1-2 предложения)\n"
                "## Игровые / Стрим-события (1-3 пункта)\n"
                "## Lore-предложения о стримере (0-3, по одному предложению, от третьего лица)\n\n"
                f"ДАННЫЕ:\n{joined}"
            )

        summary_md = ""
        if ai_service is not None:
            try:
                summary_md = await ai_service.generate_text(
                    prompt=final_prompt,
                    system="Пиши только готовый отчёт, без преамбул.",
                    account_id=account_id,
                    channel=channel,
                    temperature=0.4,
                )
            except Exception as exc:
                logger.warning("final summary error: %s", exc)
                summary_md = ""

        # Парсим секции
        events, funny, chat_analysis, lore_suggestions = _parse_report_sections(summary_md, lang=lang)

        # P8-C8.3: в сводках подпись провайдера — владелец видит, кто писал отчёт
        provider_label = ""
        try:
            prov, model, _v, _k = ai_service._resolve(account_id)
            if prov:
                provider_label = f"{prov}/{model}" if model else prov
        except Exception:
            provider_label = ""
        if summary_md and provider_label:
            summary_md = (summary_md.rstrip() + f"\n\n---\n_Сводка сгенерирована провайдером: {provider_label}_")

        # Записываем файлы
        files = _write_run_files(
            account_id=account_id,
            channel=channel,
            run_date=str(run.get("run_date") or _run_date(pstart)),
            summary_md=summary_md,
            events=events,
            funny=funny,
            chat_analysis=chat_analysis,
            lore_suggestions=lore_suggestions,
            digests=cps_sorted,
        )

        await update_run(
            run_id,
            status="done",
            summary_md=(summary_md or "")[:60000],
            events_json=json.dumps(events, ensure_ascii=False)[:20000],
            funny_json=json.dumps(funny, ensure_ascii=False)[:20000],
            chat_json=json.dumps(chat_analysis, ensure_ascii=False)[:20000],
            lore_json=json.dumps(lore_suggestions, ensure_ascii=False)[:20000],
            finished_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        )

        # Lore suggestions → отдельная таблица
        if lore_suggestions and lore_suggester is not None:
            try:
                await lore_suggester(run_id, lore_suggestions)
            except Exception as exc:
                logger.warning("lore_suggester error: %s", exc)

        return True
    except Exception as exc:
        logger.exception("execute_run error: %s", exc)
        await update_run(
            run_id,
            status="failed",
            error=str(exc)[:500],
            finished_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        )
        return False


_SECTION_PATTERNS_RU = [
    ("highlights", re.compile(r"##\s*Главное[^\n]*(.*?)(?=^##\s|\Z)", re.MULTILINE | re.IGNORECASE | re.DOTALL)),
    ("funny", re.compile(r"##\s*Смешные\s*моменты[^\n]*(.*?)(?=^##\s|\Z)", re.MULTILINE | re.IGNORECASE | re.DOTALL)),
    ("fails", re.compile(r"##\s*Неудачи\s*/?\s*Конфликты[^\n]*(.*?)(?=^##\s|\Z)", re.MULTILINE | re.IGNORECASE | re.DOTALL)),
    ("chat", re.compile(r"##\s*Реакция\s*чата[^\n]*(.*?)(?=^##\s|\Z)", re.MULTILINE | re.IGNORECASE | re.DOTALL)),
    ("events", re.compile(r"##\s*Игровые\s*/?\s*Стрим-события[^\n]*(.*?)(?=^##\s|\Z)", re.MULTILINE | re.IGNORECASE | re.DOTALL)),
    ("lore", re.compile(r"##\s*Lore[-\s]*предложения[^\n]*(.*?)(?=^##\s|\Z)", re.MULTILINE | re.IGNORECASE | re.DOTALL)),
]
_SECTION_PATTERNS_EN = [
    ("highlights", re.compile(r"##\s*Highlights[^\n]*(.*?)(?=^##\s|\Z)", re.MULTILINE | re.IGNORECASE | re.DOTALL)),
    ("funny", re.compile(r"##\s*Funny\s*moments[^\n]*(.*?)(?=^##\s|\Z)", re.MULTILINE | re.IGNORECASE | re.DOTALL)),
    ("fails", re.compile(r"##\s*Fails\s*/?\s*Conflicts[^\n]*(.*?)(?=^##\s|\Z)", re.MULTILINE | re.IGNORECASE | re.DOTALL)),
    ("chat", re.compile(r"##\s*Chat\s*reaction[^\n]*(.*?)(?=^##\s|\Z)", re.MULTILINE | re.IGNORECASE | re.DOTALL)),
    ("events", re.compile(r"##\s*Game\s*/?\s*Stream\s*events[^\n]*(.*?)(?=^##\s|\Z)", re.MULTILINE | re.IGNORECASE | re.DOTALL)),
    ("lore", re.compile(r"##\s*(?:Suggested\s*)?['\"]?Lore['\"]?\s*facts[^\n]*(.*?)(?=^##\s|\Z)", re.MULTILINE | re.IGNORECASE | re.DOTALL)),
]


def _section_bullets(text: str) -> list[str]:
    if not text:
        return []
    items: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith(("-", "*", "•")):
            s = s.lstrip("-*•").strip()
        if 2 <= len(s) < 500:
            items.append(s)
    return items


def _section_text(text: str) -> str:
    if not text:
        return ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return " ".join(lines).strip()


def _parse_report_sections(md: str, *, lang: str = "ru") -> tuple[list, list, list, list]:
    if not md:
        return [], [], [], []
    patterns = _SECTION_PATTERNS_RU if lang == "ru" else _SECTION_PATTERNS_EN
    sections = {}
    for name, rgx in patterns:
        m = rgx.search(md)
        sections[name] = m.group(1).strip() if m else ""
    events = _section_bullets(sections.get("events") or "")
    funny = _section_bullets(sections.get("funny") or "")
    chat_text = _section_text(sections.get("chat") or "")
    chat_analysis = [chat_text] if chat_text else []
    # highlights → events, fails → events (для удобства)
    highlights = _section_bullets(sections.get("highlights") or "")
    fails = _section_bullets(sections.get("fails") or [])
    all_events = list(dict.fromkeys(highlights + events + fails))[:20]
    lore_raw = _section_bullets(sections.get("lore") or "")
    lore = [{"fact": s, "confidence": 0.6, "importance": 50} for s in lore_raw[:5] if s]
    return all_events, funny, chat_analysis, lore


def _write_run_files(
    *, account_id: int, channel: str, run_date: str,
    summary_md: str, events: list, funny: list,
    chat_analysis: list, lore_suggestions: list,
    digests: list[dict],
) -> dict[str, str]:
    """Сохраняет файлы в data/bots/summarizer/<channel>/<date>/."""
    target_dir = SUMMARY_ROOT / channel / run_date
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.warning("mkdir summary dir failed: %s", exc)
        return {}
    paths: dict[str, str] = {}
    try:
        p = target_dir / "summary.md"
        p.write_text(summary_md or "", encoding="utf-8")
        paths["summary_md"] = str(p)
    except Exception as exc:
        logger.warning("write summary.md: %s", exc)
    for name, payload in (
        ("events.json", events),
        ("funny-moments.json", funny),
        ("chat-analysis.json", chat_analysis),
        ("lore-suggestions.json", lore_suggestions),
    ):
        try:
            p = target_dir / name
            p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            paths[name] = str(p)
        except Exception as exc:
            logger.warning("write %s: %s", name, exc)
    try:
        p = target_dir / "digests.json"
        p.write_text(json.dumps(digests, ensure_ascii=False, indent=2), encoding="utf-8")
        paths["digests.json"] = str(p)
    except Exception as exc:
        logger.warning("write digests.json: %s", exc)
    return paths
