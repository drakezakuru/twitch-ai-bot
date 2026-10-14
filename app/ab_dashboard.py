"""A/B real-time engagement dashboard.

Агрегирует данные из существующих таблиц:
  - prompt_variants (id, label, system_prompt, weight, count, likes, dislikes)
  - bot_engagement (chat_log_id, support, mentions, replies, breakthrough)
  - bot_response_feedback (chat_log_id, prompt_variant_id, feedback)
  - chat_log (id, account_id, channel, timestamp, ai_prompt_variant_id?)

Метрики per-variant (за окно `hours`):
  - n_responses      — кол-во ответов
  - likes, dislikes  — фидбек
  - like_ratio       — likes / (likes + dislikes + 1)
  - avg_support      — средний support из engagement
  - avg_mentions     — среднее mentions
  - avg_replies      — среднее replies
  - breakthroughs    — кол-во breakthrough=1
  - score            — общий score (используется для ранжирования)
  - score_per_response — нормализованный

Pure-функции — компоновка score и нормализация. Async-функции — выборка из БД.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict, field
from typing import Iterable

try:
    from app.database import get_db
except Exception:  # pragma: no cover
    get_db = None  # type: ignore


# --- pure helpers ----------------------------------------------------------


def safe_div(a, b, default: float = 0.0) -> float:
    try:
        b = float(b)
        return float(a) / b if b else default
    except Exception:
        return default


def variant_score(
    *,
    likes: int,
    dislikes: int,
    avg_support: float,
    avg_mentions: float,
    avg_replies: float,
    breakthroughs: int,
    n_responses: int,
) -> float:
    """Композитный score варианта.

    Вес:
      - likes - dislikes: +1 / -1 каждый
      - support: +0.6 за единицу avg_support
      - mentions: +0.4 (показатель что юзеры повторно упоминают)
      - replies: +0.5 (другие юзеры отвечают)
      - breakthroughs: +1.5 (большой реакционный момент)
    Нормализуется на sqrt(n_responses+1) — чтобы редко используемые варианты
    с малым sample не выскакивали наверх.
    """
    raw = (
        float(likes) - float(dislikes)
        + 0.6 * float(avg_support)
        + 0.4 * float(avg_mentions)
        + 0.5 * float(avg_replies)
        + 1.5 * float(breakthroughs)
    )
    return round(raw / math.sqrt(max(0, int(n_responses)) + 1), 3)


def like_ratio(likes: int, dislikes: int) -> float:
    total = (likes or 0) + (dislikes or 0)
    if total <= 0:
        return 0.0
    return round(safe_div(likes, total), 3)


def rank_variants(variants: list[dict]) -> list[dict]:
    """Сортирует variants по `score` DESC. Добавляет `rank` и `recommendation`."""
    sorted_v = sorted(variants, key=lambda v: float(v.get("score") or 0), reverse=True)
    for i, v in enumerate(sorted_v):
        v["rank"] = i + 1
        if i == 0 and v.get("score", 0) > 0:
            v["recommendation"] = "leader"
        elif v.get("score", 0) <= -1.0:
            v["recommendation"] = "drop"
        else:
            v["recommendation"] = "keep"
    return sorted_v


def total_responses(variants: Iterable[dict]) -> int:
    return sum(int(v.get("n_responses") or 0) for v in variants)


def summary_metrics(variants: Iterable[dict]) -> dict:
    """Свод для верхней панели dashboard."""
    vs = list(variants)
    total = total_responses(vs)
    likes = sum(int(v.get("likes") or 0) for v in vs)
    dislikes = sum(int(v.get("dislikes") or 0) for v in vs)
    bt = sum(int(v.get("breakthroughs") or 0) for v in vs)
    return {
        "n_variants": len(vs),
        "n_responses": total,
        "likes": likes,
        "dislikes": dislikes,
        "like_ratio": like_ratio(likes, dislikes),
        "breakthroughs": bt,
        "leader": (vs[0]["label"] if vs and vs[0].get("rank") == 1 else ""),
    }


# --- async DB API ----------------------------------------------------------


async def get_variant_metrics(
    *,
    pattern_id: int | None = None,
    account_id: int | None = None,
    hours: int = 168,  # неделя
) -> list[dict]:
    """Считает per-variant метрики за последние N часов.

    pattern_id is retained only for call compatibility and is ignored.
    If account_id is set, return variants for that account.
    Возвращает ranked list.
    """
    if get_db is None:
        return []
    db = await get_db()
    try:
        params: list = []
        where_parts: list[str] = []
        if account_id is not None:
            where_parts.append("v.account_id = ?")
            params.append(int(account_id))
        where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
        sql = (
            "SELECT v.id, v.account_id, v.label, v.weight, v.count, v.likes, v.dislikes, v.enabled "
            "FROM prompt_variants v "
            f"{where_sql} "
            "ORDER BY v.account_id, v.id"
        )
        cursor = await db.execute(sql, params)
        variants = [dict(r) for r in await cursor.fetchall()]
        if not variants:
            return []

        # Тянем engagement для каждого варианта через bot_response_feedback → chat_log_id → bot_engagement
        # Не у всех есть колонка prompt_variant_id в chat_log напрямую — используем bot_response_feedback.
        # Берём окно по timestamp в bot_engagement.computed_at
        var_ids = [int(v["id"]) for v in variants]
        placeholders = ",".join("?" for _ in var_ids)
        sql_eng = (
            "SELECT brf.prompt_variant_id AS vid, "
            "  AVG(be.support) AS avg_support, "
            "  AVG(be.mentions) AS avg_mentions, "
            "  AVG(be.replies) AS avg_replies, "
            "  SUM(CASE WHEN be.breakthrough = 1 THEN 1 ELSE 0 END) AS breakthroughs, "
            "  COUNT(*) AS n_responses "
            "FROM bot_response_feedback brf "
            "JOIN bot_engagement be ON be.chat_log_id = brf.chat_log_id "
            "WHERE brf.prompt_variant_id IN (" + placeholders + ") "
            "  AND be.computed_at >= datetime('now', ?) "
            "GROUP BY brf.prompt_variant_id"
        )
        eng_cursor = await db.execute(sql_eng, [*var_ids, f"-{int(hours)} hours"])
        eng_rows = {int(r["vid"]): dict(r) for r in await eng_cursor.fetchall()}

        # Сборка финального ответа
        out: list[dict] = []
        for v in variants:
            vid = int(v["id"])
            eng = eng_rows.get(vid, {})
            n = int(eng.get("n_responses") or 0)
            likes = int(v.get("likes") or 0)
            dislikes = int(v.get("dislikes") or 0)
            avg_s = float(eng.get("avg_support") or 0)
            avg_m = float(eng.get("avg_mentions") or 0)
            avg_r = float(eng.get("avg_replies") or 0)
            bt = int(eng.get("breakthroughs") or 0)
            score = variant_score(
                likes=likes,
                dislikes=dislikes,
                avg_support=avg_s,
                avg_mentions=avg_m,
                avg_replies=avg_r,
                breakthroughs=bt,
                n_responses=n,
            )
            out.append({
                "id": vid,
                "account_id": int(v.get("account_id") or 0),
                "label": v.get("label") or "?",
                "weight": int(v.get("weight") or 0),
                "enabled": bool(v.get("enabled") or 0),
                "n_responses": n,
                "likes": likes,
                "dislikes": dislikes,
                "like_ratio": like_ratio(likes, dislikes),
                "avg_support": round(avg_s, 3),
                "avg_mentions": round(avg_m, 3),
                "avg_replies": round(avg_r, 3),
                "breakthroughs": bt,
                "score": score,
                "score_per_response": round(safe_div(score, max(n, 1)), 3),
            })
        return rank_variants(out)
    finally:
        await db.close()


async def get_dashboard_payload(
    *,
    account_id: int | None = None,
    hours: int = 168,
) -> dict:
    """Один вызов для UI: metrics + summary."""
    variants = await get_variant_metrics(account_id=account_id, hours=hours)
    return {
        "hours": int(hours),
        "summary": summary_metrics(variants),
        "variants": variants,
    }
