"""v16 BRAIN_PLAN §8: тесты новых модулей мозга.

- Lore: suggested не попадает в prompt, approved попадает, expiry работает.
- Learning: предложение → применение → откат (style/kb).
- Shift: события меняют mood временно, восстанавливается по таймеру.
- Summarizer: чекпоинты, парсер секций отчёта, lore-suggestions.
- Memory: confirmed → prompt первым; gc_expired_facts удаляет TTL.
- Изоляция: lore/learning/shift per (account_id, channel).
"""

from __future__ import annotations

import json
import time

import pytest

from app import streamer_lore
from app import learning as learning_mod
from app import personality_shift
from app import summarizer
from app import user_memory
from app.database import init_db


async def _setup_accounts():
    await init_db()
    # accounts нужны из-за FOREIGN KEY ... ON DELETE CASCADE
    from app.database import get_db
    db = await get_db()
    try:
        for aid, nick in ((1, "bot1"), (2, "bot2")):
            await db.execute(
                "INSERT OR IGNORE INTO accounts (id, nickname, token) VALUES (?, ?, 't')",
                (aid, nick),
            )
        await db.commit()
    finally:
        await db.close()


# ==================== §5 Lore ====================


class TestLore:
    pytestmark = pytest.mark.asyncio
    async def test_suggested_not_in_prompt(self, tmp_db):
        await _setup_accounts()
        await streamer_lore.add_suggestion(1, "chan", "любит хорроры", source="summary")
        rows = await streamer_lore.list_approved(1, "chan")
        assert streamer_lore.format_lore_for_prompt(rows) == ""

    async def test_approved_in_prompt(self, tmp_db):
        await _setup_accounts()
        lid = await streamer_lore.add_suggestion(1, "chan", "любит хорроры")
        await streamer_lore.approve(lid)
        rows = await streamer_lore.list_approved(1, "chan")
        assert "любит хорроры" in streamer_lore.format_lore_for_prompt(rows)

    async def test_rejected_not_in_prompt(self, tmp_db):
        await _setup_accounts()
        lid = await streamer_lore.add_suggestion(1, "chan", "факт X")
        await streamer_lore.reject(lid)
        rows = await streamer_lore.list_approved(1, "chan")
        assert streamer_lore.format_lore_for_prompt(rows) == ""

    async def test_expired_not_in_prompt(self, tmp_db):
        await _setup_accounts()
        lid = await streamer_lore.add_suggestion(1, "chan", "устаревший факт")
        await streamer_lore.approve(lid)
        await streamer_lore.update_fact(lid, expires_at="2000-01-01T00:00:00+00:00")
        rows = await streamer_lore.list_approved(1, "chan")
        assert streamer_lore.format_lore_for_prompt(rows) == ""

    async def test_isolated_per_account_and_channel(self, tmp_db):
        await _setup_accounts()
        lid = await streamer_lore.add_suggestion(1, "chan_a", "факт A")
        await streamer_lore.approve(lid)
        rows_b = await streamer_lore.list_approved(1, "chan_b")
        assert streamer_lore.format_lore_for_prompt(rows_b) == ""
        rows_c = await streamer_lore.list_approved(2, "chan_a")
        assert streamer_lore.format_lore_for_prompt(rows_c) == ""
        rows_a = await streamer_lore.list_approved(1, "chan_a")
        assert "факт A" in streamer_lore.format_lore_for_prompt(rows_a)

    async def test_empty_channel_is_global(self, tmp_db):
        await _setup_accounts()
        lid = await streamer_lore.add_suggestion(1, "", "глобальный факт")
        await streamer_lore.approve(lid)
        rows_g = await streamer_lore.list_approved(1, "")
        assert "глобальный факт" in streamer_lore.format_lore_for_prompt(rows_g)
        rows_a = await streamer_lore.list_approved(1, "chan")
        assert streamer_lore.format_lore_for_prompt(rows_a) == ""

    async def test_importance_sorting(self, tmp_db):
        await _setup_accounts()
        l1 = await streamer_lore.add_suggestion(1, "c", "низкий", importance=10)
        l2 = await streamer_lore.add_suggestion(1, "c", "высокий", importance=90)
        await streamer_lore.approve(l1)
        await streamer_lore.approve(l2)
        rows = await streamer_lore.list_approved(1, "c")
        block = streamer_lore.format_lore_for_prompt(rows)
        assert block.index("высокий") < block.index("низкий")


# ==================== §6 Learning ====================


class TestLearning:
    pytestmark = pytest.mark.asyncio
    async def test_add_dedup_pending(self, tmp_db):
        await _setup_accounts()
        id1 = await learning_mod.add_suggestion(1, "c", "kb_topic", {"topic": "t", "content": "x"})
        id2 = await learning_mod.add_suggestion(1, "c", "kb_topic", {"topic": "t", "content": "x"})
        assert id1 == id2

    async def test_invalid_kind_rejected(self, tmp_db):
        await _setup_accounts()
        assert await learning_mod.add_suggestion(1, "c", "hack", {}) == 0

    async def test_apply_style_example_and_revert(self, tmp_db):
        from app.ai_quality_db import add_style_example, list_style_examples
        await _setup_accounts()
        sid = await learning_mod.add_suggestion(
            1, "c", "style_example",
            {"message": "тестовая реплика стиля", "note": "n"},
            reason="test", source="manual",
        )
        assert sid > 0
        s = await learning_mod.get_suggestion(1, sid)
        assert s["status"] == "pending"
        await add_style_example(
            1, s["payload"]["message"], channel=s["channel"],
            note=s["payload"].get("note", ""),
        )
        await learning_mod.apply_suggestion(1, sid)
        s2 = await learning_mod.get_suggestion(1, sid)
        assert s2["status"] == "applied"
        examples = await list_style_examples(1, channel="c")
        assert any("тестовая реплика стиля" == e["message"] for e in examples)
        await learning_mod.mark_reverted(1, sid)
        s3 = await learning_mod.get_suggestion(1, sid)
        assert s3["status"] == "reverted"

    async def test_apply_kb_topic(self, tmp_db):
        from app.ai_quality_db import add_kb, list_kb
        await _setup_accounts()
        sid = await learning_mod.add_suggestion(
            1, "c", "kb_topic",
            {"topic": "любимая игра", "content": "стример любит Elden Ring"},
        )
        s = await learning_mod.get_suggestion(1, sid)
        await add_kb(1, s["payload"]["topic"], s["payload"]["content"])
        kb = await list_kb(1)
        assert any(e["topic"] == "любимая игра" for e in kb)

    async def test_reject(self, tmp_db):
        await _setup_accounts()
        sid = await learning_mod.add_suggestion(1, "c", "banned_topic", {"pattern": "politics"})
        assert await learning_mod.reject_suggestion(1, sid)
        s = await learning_mod.get_suggestion(1, sid)
        assert s["status"] == "rejected"

    async def test_isolated_per_account(self, tmp_db):
        await _setup_accounts()
        await learning_mod.add_suggestion(1, "c", "kb_topic", {"topic": "a"})
        items_1 = await learning_mod.list_suggestions(1, "c")
        items_2 = await learning_mod.list_suggestions(2, "c")
        assert len(items_1) == 1
        assert len(items_2) == 0

    async def test_row_operations_reject_foreign_account(self, tmp_db):
        await _setup_accounts()
        pending_id = await learning_mod.add_suggestion(
            1, "c", "kb_topic", {"topic": "owned"}
        )
        applied_id = await learning_mod.add_suggestion(
            1, "c", "style_example", {"message": "owned"}
        )
        assert await learning_mod.apply_suggestion(1, applied_id)

        assert await learning_mod.get_suggestion(2, pending_id) is None
        assert await learning_mod.apply_suggestion(2, pending_id) is False
        assert await learning_mod.reject_suggestion(2, pending_id) is False
        assert await learning_mod.mark_reverted(2, applied_id) is False
        assert (await learning_mod.get_suggestion(1, pending_id))["status"] == "pending"
        assert (await learning_mod.get_suggestion(1, applied_id))["status"] == "applied"


# ==================== §7 Personality Shift ====================


class TestPersonalityShift:
    def setup_method(self):
        personality_shift.shift_manager = personality_shift.PersonalityShiftManager()

    def test_disabled_no_trigger(self):
        assert personality_shift.shift_manager.trigger(1, "c", "raid", mood_delta=0.3) is None

    def test_enabled_trigger_and_expire(self):
        m = personality_shift.shift_manager
        m.set_enabled(1, "c", True)
        m.set_intensity(1, "c", 1)
        st = m.trigger(1, "c", "raid", duration_sec=60, mood_delta=0.3, emotionality_delta=0.1)
        assert st is not None
        active = m.get_active(1, "c")
        assert active is not None and active.kind == "raid"
        hint = m.get_hint(1, "c")
        assert "raid" in hint or "рейда" in hint
        st.expires_at = time.time() - 1
        assert m.get_active(1, "c") is None
        assert m.get_hint(1, "c") == ""

    def test_intensity_scales_deltas(self):
        m = personality_shift.shift_manager
        m.set_enabled(1, "c", True)
        m.set_intensity(1, "c", 1)
        st1 = m.trigger(1, "c", "raid", duration_sec=60, mood_delta=0.3)
        m2 = personality_shift.PersonalityShiftManager()
        m2.set_enabled(1, "c", True)
        m2.set_intensity(1, "c", 2)
        st2 = m2.trigger(1, "c", "raid", duration_sec=60, mood_delta=0.3)
        assert st2.mood_delta > st1.mood_delta

    def test_disabled_after_set_off(self):
        m = personality_shift.shift_manager
        m.set_enabled(1, "c", True)
        m.set_intensity(1, "c", 2)
        m.set_enabled(1, "c", False)
        assert m.trigger(1, "c", "raid", duration_sec=60, mood_delta=0.3) is None

    def test_invalid_kind(self):
        m = personality_shift.shift_manager
        m.set_enabled(1, "c", True)
        m.set_intensity(1, "c", 1)
        assert m.trigger(1, "c", "nuclear_war", duration_sec=60) is None

    def test_isolated_per_channel(self):
        m = personality_shift.shift_manager
        m.set_enabled(1, "a", True)
        m.set_intensity(1, "a", 1)
        assert m.trigger(1, "a", "raid", duration_sec=60) is not None
        assert m.trigger(1, "b", "raid", duration_sec=60) is None


# ==================== §4 Summarizer ====================


class FakeAI:
    def __init__(self, response: str = "digest"):
        self.response = response
        self.calls: list[str] = []

    async def generate_text(self, prompt, system="", account_id=0, channel="",
                            temperature=None):
        self.calls.append(prompt[:100])
        return self.response


class TestSummarizerPure:
    def test_parse_report_sections_ru(self):
        md = (
            "## Главное\n- Пункт 1\n- Пункт 2\n\n"
            "## Смешные моменты\n- Смешной момент\n\n"
            "## Неудачи / Конфликты\n- Фейл\n\n"
            "## Реакция чата\nЧат был в восторге.\n\n"
            "## Игровые / Стрим-события\n- Босс убит\n\n"
            "## Lore-предложения\n- Стример любит кофе\n- Стример из Киева\n"
        )
        events, funny, chat, lore = summarizer._parse_report_sections(md, lang="ru")
        assert "Пункт 1" in events and "Босс убит" in events and "Фейл" in events
        assert funny == ["Смешной момент"]
        assert chat == ["Чат был в восторге."]
        assert len(lore) == 2
        assert lore[0]["fact"] == "Стример любит кофе"
        assert 0.0 < lore[0]["confidence"] <= 1.0

    def test_parse_report_sections_en(self):
        md = (
            "## Highlights\n- H1\n\n## Funny moments\n- F1\n\n"
            "## Chat reaction\nChill vibe.\n\n"
            "## Suggested 'lore' facts about the streamer (0-3, single sentence each, in third person)\n- Loves coffee\n"
        )
        events, funny, chat, lore = summarizer._parse_report_sections(md, lang="en")
        assert "H1" in events
        assert funny == ["F1"]
        assert chat == ["Chill vibe."]
        assert lore and lore[0]["fact"] == "Loves coffee"

    def test_parse_empty(self):
        assert summarizer._parse_report_sections("") == ([], [], [], [])
        assert summarizer._parse_report_sections("no sections here") == ([], [], [], [])

    def test_digest_prompt_contains_messages(self):
        msgs = [
            {"author": "a", "message": "привет", "is_bot": False, "ts": ""},
            {"author": "bot", "message": "ответ", "is_bot": True, "ts": ""},
        ]
        p = summarizer._build_digest_prompt(msgs, lang="ru")
        assert "привет" in p and "bot" in p

    def test_write_run_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(summarizer, "SUMMARY_ROOT", tmp_path / "sum")
        paths = summarizer._write_run_files(
            account_id=1, channel="chan", run_date="2026-08-28",
            summary_md="# Отчёт", events=["e1"], funny=["f1"],
            chat_analysis=["c1"], lore_suggestions=[{"fact": "l1"}],
            digests=[],
        )
        assert (tmp_path / "sum" / "chan" / "2026-08-28" / "summary.md").exists()
        for key in ("events.json", "funny-moments.json", "chat-analysis.json", "lore-suggestions.json"):
            assert key in paths
        data = json.loads((tmp_path / "sum" / "chan" / "2026-08-28" / "lore-suggestions.json").read_text())
        assert data == [{"fact": "l1"}]


class TestSummarizer:
    pytestmark = pytest.mark.asyncio

    async def test_run_lifecycle_with_checkpoints(self, tmp_db, tmp_path, monkeypatch):
        await _setup_accounts()
        from datetime import datetime, timezone
        monkeypatch.setattr(summarizer, "SUMMARY_ROOT", tmp_path / "sum")
        pstart = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
        pend = datetime(2026, 8, 28, 13, 30, tzinfo=timezone.utc)  # 3 окна по 30 мин
        run = await summarizer.create_run(1, "chan", pstart, pend, lang="ru")
        assert run is not None
        ai = FakeAI(
            "## Главное\n- ок\n\n## Смешные моменты\n- ха\n\n## Неудачи / Конфликты\n\n"
            "## Реакция чата\nтихо\n\n## Игровые / Стрим-события\n- босс\n\n"
            "## Lore-предложения\n- любит кофе"
        )
        assert await summarizer.execute_run(run["id"], ai, window_minutes=30) is True
        done = await summarizer.get_run(run["id"])
        assert done["status"] == "done"
        cps = await summarizer.get_checkpoints(run["id"])
        assert len(cps) == 3
        # resumable: повторный прогон не пересоздаёт чекпоинты
        assert await summarizer.execute_run(run["id"], ai, window_minutes=30) is True
        cps2 = await summarizer.get_checkpoints(run["id"])
        assert len(cps2) == 3
        lore = json.loads(done["lore_json"])
        assert lore and lore[0]["fact"] == "любит кофе"

    async def test_chat_window_fetch(self, tmp_db):
        await _setup_accounts()
        from datetime import datetime, timezone
        from app.database import get_db
        db = await get_db()
        try:
            await db.execute(
                "INSERT INTO chat_log (account_id, channel, author, message, is_bot, timestamp) "
                "VALUES (1, 'chan', 'u1', 'привет', 0, '2026-08-28 12:10:00')"
            )
            await db.commit()
        finally:
            await db.close()
        msgs = await summarizer._fetch_chat_window(
            1, "chan",
            datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc),
            datetime(2026, 8, 28, 13, 0, tzinfo=timezone.utc),
        )
        assert len(msgs) == 1
        assert msgs[0]["author"] == "u1"


# ==================== §1 Memory: confirmed + GC ====================


class TestMemoryConfirmed:
    pytestmark = pytest.mark.asyncio
    async def test_confirmed_first_in_prompt(self, tmp_db):
        await _setup_accounts()
        await user_memory.add_fact(1, "user1", "обычный факт", priority=30)
        await user_memory.add_fact(1, "user1", "важный факт", priority=10, confirmed=True)
        mem = await user_memory.get_user_memory(1, "user1", structured=True)
        text = user_memory.format_memory_for_prompt(mem)
        assert text.index("важный факт") < text.index("обычный факт")

    async def test_confirmed_persisted(self, tmp_db):
        await _setup_accounts()
        await user_memory.add_fact(1, "u", "факт")
        assert await user_memory.set_fact_confirmed(1, "u", "факт", True)
        mem = await user_memory.get_user_memory(1, "u", structured=True)
        f = next(f for f in mem["facts_structured"] if f["fact"] == "факт")
        assert f["confirmed"] is True
        await user_memory.set_fact_confirmed(1, "u", "факт", False)
        mem2 = await user_memory.get_user_memory(1, "u", structured=True)
        f2 = next(f for f in mem2["facts_structured"] if f["fact"] == "факт")
        assert f2["confirmed"] is False

    async def test_gc_expired(self, tmp_db):
        await _setup_accounts()
        await user_memory.add_fact(1, "u", "живой факт", priority=50)
        await user_memory.add_fact(1, "u", "мёртвый факт", priority=50,
                                   expires_at="2000-01-01T00:00:00+00:00")
        removed = await user_memory.gc_expired_facts(1)
        assert removed == 1
        mem = await user_memory.get_user_memory(1, "u", structured=True)
        facts = [f["fact"] for f in mem["facts_structured"]]
        assert "живой факт" in facts
        assert "мёртвый факт" not in facts

    async def test_add_fact_source_auto(self, tmp_db):
        await _setup_accounts()
        await user_memory.add_fact(1, "u", "авто факт", source="auto")
        mem = await user_memory.get_user_memory(1, "u", structured=True)
        f = next(f for f in mem["facts_structured"] if f["fact"] == "авто факт")
        assert f["source"] == "auto"
        assert f["confirmed"] is False


# ==================== §2 реплики стримера ====================


class TestStreamerLines:
    def test_add_and_get_recent(self):
        from app.stream_vision import StreamVisionManager
        m = StreamVisionManager(ai_service=None)
        m.add_streamer_line(1, "c", "всем привет")
        m.add_streamer_line(1, "c", "сегодня играем в хоррор")
        lines = m.get_recent_streamer_lines(1, "c", limit=5)
        assert len(lines) == 2
        assert lines[0]["text"] == "всем привет"
        assert lines[1]["text"] == "сегодня играем в хоррор"

    def test_age_filter(self):
        from app.stream_vision import StreamVisionManager
        m = StreamVisionManager(ai_service=None)
        m.add_streamer_line(1, "c", "старая реплика")
        dq = m._streamer_lines[(1, "c")]
        dq[0]["at"] = time.time() - 700
        assert m.get_recent_streamer_lines(1, "c", max_age_sec=600) == []

    def test_isolated_per_channel(self):
        from app.stream_vision import StreamVisionManager
        m = StreamVisionManager(ai_service=None)
        m.add_streamer_line(1, "a", "реплика A")
        assert m.get_recent_streamer_lines(1, "b") == []
        assert m.get_recent_streamer_lines(2, "a") == []

    def test_empty_text_ignored(self):
        from app.stream_vision import StreamVisionManager
        m = StreamVisionManager(ai_service=None)
        m.add_streamer_line(1, "c", "   ")
        assert m.get_recent_streamer_lines(1, "c") == []

    def test_module_level_helpers_no_manager(self):
        from app import stream_vision as sv
        sv._manager_ref = None
        sv.add_streamer_line(1, "c", "x")  # не падает
        assert sv.get_recent_streamer_lines(1, "c") == []


# ==================== §8: live digest изоляция ====================


class TestLiveDigestIsolation:
    pytestmark = pytest.mark.asyncio

    async def test_isolated_per_account_and_channel(self, tmp_db):
        await _setup_accounts()
        from datetime import datetime, timezone
        s = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
        e = datetime(2026, 8, 28, 12, 30, tzinfo=timezone.utc)
        await summarizer.write_live_summary(1, "chan_a", s, e, "дайджест A")
        await summarizer.write_live_summary(2, "chan_a", s, e, "дайджест B")
        await summarizer.write_live_summary(1, "chan_b", s, e, "дайджест C")
        assert "дайджест A" in await summarizer.get_live_digest(1, "chan_a")
        assert "дайджест B" not in await summarizer.get_live_digest(1, "chan_a")
        assert "дайджест C" not in await summarizer.get_live_digest(1, "chan_a")
        assert "дайджест B" in await summarizer.get_live_digest(2, "chan_a")
        assert "дайджест C" in await summarizer.get_live_digest(1, "chan_b")


# ==================== §3: KB enabled + import/export ====================


class TestKbEnabledAndBulk:
    pytestmark = pytest.mark.asyncio

    async def test_disabled_kb_not_in_prompt(self, tmp_db):
        await _setup_accounts()
        from app.ai_quality_db import add_kb, retrieve_kb_for_query, update_kb
        kid = await add_kb(1, "любимая игра", "стример любит Elden Ring")
        hits = await retrieve_kb_for_query(1, "во что играет стример")
        assert any(h["topic"] == "любимая игра" for h in hits)
        await update_kb(1, kid, enabled=0)
        hits2 = await retrieve_kb_for_query(1, "во что играет стример")
        assert not any(h["topic"] == "любимая игра" for h in hits2)

    async def test_kb_export_import_roundtrip(self, tmp_db):
        await _setup_accounts()
        from app.ai_quality_db import add_kb, list_kb
        from app.brain_routes import kb_export, kb_import
        await add_kb(1, "тема1", "контент1", tags="tag", priority=7)
        await add_kb(1, "тема2", "контент2")
        exported = await kb_export(1)
        assert exported["ok"] and len(exported["entries"]) == 2
        # импорт в аккаунт 2 (merge)
        res = await kb_import(2, {"entries": exported["entries"], "mode": "merge"})
        assert res["ok"] and res["added"] == 2 and res["skipped"] == 0
        kb2 = await list_kb(2)
        assert any(e["topic"] == "тема1" and e["priority"] == 7 for e in kb2)
        # повторный merge — дубликаты пропускаются
        res2 = await kb_import(2, {"entries": exported["entries"], "mode": "merge"})
        assert res2["added"] == 0 and res2["skipped"] == 2
        # replace — сначала чистит
        await kb_import(2, {"entries": [{"topic": "новая", "content": "x"}], "mode": "replace"})
        kb2b = await list_kb(2)
        assert [e["topic"] for e in kb2b] == ["новая"]

    async def test_kb_import_bad_entries(self, tmp_db):
        await _setup_accounts()
        from app.brain_routes import kb_import
        assert (await kb_import(1, {"entries": "nope"}))["ok"] is False
        res = await kb_import(1, {"entries": [{"topic": "", "content": "x"}, "junk", {"topic": "ok", "content": "y"}]})
        assert res["added"] == 1 and res["skipped"] == 2


# ==================== §4: summarizer settings (язык панели) ====================


class TestSummarizerSettings:
    pytestmark = pytest.mark.asyncio

    async def test_get_and_set_live_lang(self, tmp_db):
        await _setup_accounts()
        from app.brain_routes import summarizer_settings_get, summarizer_settings_set
        res = await summarizer_settings_get(1)
        assert res["ok"] and res["live_lang"] == "ru"
        set_res = await summarizer_settings_set(1, {"live_enabled": True, "live_lang": "en"})
        assert set_res["ok"] and set_res["live_enabled"] is True and set_res["live_lang"] == "en"
        res2 = await summarizer_settings_get(1)
        assert res2["live_enabled"] is True and res2["live_lang"] == "en"

    async def test_panel_ua_maps_to_ru(self, tmp_db):
        await _setup_accounts()
        from app.brain_routes import summarizer_settings_set
        res = await summarizer_settings_set(1, {"live_lang": "ua"})
        assert res["ok"] and res["live_lang"] == "ru"

    async def test_empty_update_rejected(self, tmp_db):
        await _setup_accounts()
        from app.brain_routes import summarizer_settings_set
        res = await summarizer_settings_set(1, {})
        assert res["ok"] is False


# ==================== §3: Mimicry top-K по косинусной близости ====================


class TestMimicryTopK:
    pytestmark = pytest.mark.asyncio

    async def test_query_ranks_relevant_first(self, tmp_db):
        await _setup_accounts()
        from app.ai_quality_db import add_style_example, pick_style_examples
        for msg in (
            "обожаю Elden Ring, пройдём босса",
            "привет, добро пожаловать на стрим",
            " Elden Ring билд лучший ",
            "сегодня без каток, просто болтаем",
        ):
            await add_style_example(1, msg, channel="c")
        picked = await pick_style_examples(1, channel="c", count=2, query="elden ring босс билд")
        assert len(picked) == 2
        msgs = [p["message"] for p in picked]
        assert "обожаю Elden Ring, пройдём босса" in msgs
        assert "сегодня без каток, просто болтаем" not in msgs

    async def test_no_query_behaves_as_before(self, tmp_db):
        await _setup_accounts()
        from app.ai_quality_db import add_style_example, pick_style_examples
        await add_style_example(1, "пример один", channel="c")
        picked = await pick_style_examples(1, channel="c", count=4)
        assert [p["message"] for p in picked] == ["пример один"]


# ==================== §6: откат последнего обучения ====================


class TestRevertLast:
    pytestmark = pytest.mark.asyncio

    async def test_revert_style_example(self, tmp_db):
        await _setup_accounts()
        from app.ai_quality_db import add_style_example, delete_style_example, list_style_examples
        from app import learning as learning_mod
        from app.brain_routes import learning_revert_last
        sid = await learning_mod.add_suggestion(
            1, "c", "style_example", {"message": "реплика на откат"}, source="manual"
        )
        ex_id = await add_style_example(1, "реплика на откат", channel="c")
        await learning_mod.apply_suggestion(1, sid)
        assert any(e["message"] == "реплика на откат" for e in await list_style_examples(1, channel="c"))
        res = await learning_revert_last(1, {})
        assert res["ok"] and res["kind"] == "style_example" and res["undone"] == "style_example_deleted"
        assert not any(e["message"] == "реплика на откат" for e in await list_style_examples(1, channel="c"))
        s = await learning_mod.get_suggestion(1, sid)
        assert s["status"] == "reverted"
        # повторный откат — нечего
        res2 = await learning_revert_last(1, {})
        assert res2["ok"] is False and res2["error"] == "nothing_applied"
        await delete_style_example(1, ex_id)  # noop-безопасность

    async def test_revert_kb_topic(self, tmp_db):
        await _setup_accounts()
        from app.ai_quality_db import add_kb, list_kb
        from app import learning as learning_mod
        from app.brain_routes import learning_revert_last
        sid = await learning_mod.add_suggestion(1, "c", "kb_topic", {"topic": "тема R"})
        await add_kb(1, "тема R", "контент R")
        await learning_mod.apply_suggestion(1, sid)
        res = await learning_revert_last(1, {"kind": "kb_topic"})
        assert res["ok"] and res["undone"] == "kb_deleted"
        assert not any(k["topic"] == "тема R" for k in await list_kb(1))


# ==================== §7: affinity rules + уровни ====================


class TestAffinityRulesPure:
    def test_compute_deltas(self):
        from app.affinity_rules import compute_affinity_delta
        assert compute_affinity_delta("ахахах это смешно 😂")[0] > 1
        assert compute_affinity_delta("спасибо, лучший стример")[0] >= 2
        assert compute_affinity_delta("ты тупой иди на")[0] < 0
        assert compute_affinity_delta("обычное сообщение про игру")[0] == 1
        assert compute_affinity_delta("")[1] == "default"

    def test_conflict_beats_support(self):
        from app.affinity_rules import compute_affinity_delta
        d, reason = compute_affinity_delta("спасибо дебил")
        assert d < 0 and reason == "conflict"

    def test_affinity_level_thresholds(self):
        from app.affinity_rules import affinity_level
        assert affinity_level(0) == "незнакомец"
        assert affinity_level(19) == "незнакомец"
        assert affinity_level(20) == "зритель"
        assert affinity_level(45) == "знакомый"
        assert affinity_level(60) == "постоянный"
        assert affinity_level(95) == "близкий"


class TestAffinityRulesDB:
    pytestmark = pytest.mark.asyncio

    async def _seed_affinity(self, auto=1, lock=0, chat=50):
        from app.database import get_db
        db = await get_db()
        try:
            await db.execute(
                "INSERT OR IGNORE INTO bot_affinity (account_id, channel, username, contact_level, chat_affinity, auto_adjust, manual_lock) "
                "VALUES (1, 'chan', 'user1', 50, ?, ?, ?)",
                (chat, auto, lock),
            )
            await db.commit()
        finally:
            await db.close()

    async def test_apply_updates_and_writes_history(self, tmp_db):
        await _setup_accounts()
        from app.affinity_rules import apply_message_affinity
        from app.database import get_db
        await self._seed_affinity()
        delta, reason = await apply_message_affinity(1, "chan", "user1", "ахах 😂")
        assert reason == "humor" and delta >= 2
        db = await get_db()
        try:
            cur = await db.execute(
                "SELECT chat_affinity FROM bot_affinity WHERE account_id=1 AND channel='chan' AND username='user1'")
            row = await cur.fetchone()
            assert row["chat_affinity"] > 50
            cur = await db.execute(
                "SELECT source FROM bot_affinity_history WHERE account_id=1 AND username='user1'")
            hist = await cur.fetchall()
            assert any("humor" in h["source"] for h in hist)
        finally:
            await db.close()

    async def test_lock_and_auto_respected(self, tmp_db):
        await _setup_accounts()
        from app.affinity_rules import apply_message_affinity
        from app.database import get_db
        await self._seed_affinity(lock=1)
        await apply_message_affinity(1, "chan", "user1", "ахах 😂")
        await self._seed_affinity(auto=0)
        await apply_message_affinity(1, "chan", "user1", "ахах 😂")
        db = await get_db()
        try:
            cur = await db.execute("SELECT chat_affinity FROM bot_affinity WHERE username='user1'")
            assert (await cur.fetchone())["chat_affinity"] == 50
        finally:
            await db.close()

    async def test_isolated_per_channel_and_account(self, tmp_db):
        await _setup_accounts()
        from app.affinity_rules import apply_message_affinity
        await self._seed_affinity()
        await apply_message_affinity(1, "другой", "user1", "ахах 😂")
        await apply_message_affinity(2, "chan", "user1", "ахах 😂")
        from app.database import get_db
        db = await get_db()
        try:
            cur = await db.execute("SELECT chat_affinity FROM bot_affinity WHERE username='user1'")
            assert (await cur.fetchone())["chat_affinity"] == 50
        finally:
            await db.close()
