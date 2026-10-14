"""Тесты для теневого режима модерации (AI Shadow-Mod).

В режиме 'shadow':
1. _apply_mode_policy возвращает 'shadow'.
2. check_message формирует вердикты с action='shadow' и is_shadow=True.
3. journal_shadow записывает вердикт со статусом 'cancelled' и префиксом '[SHADOW]'.
4. ChatAnalyzer в режиме shadow логирует теневой вердикт, не банит в Twitch и отправляет событие в modfeed.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch
import pytest
import pytest_asyncio

from app import moderation as M
from app import moderation_journal as MJ
from app import database
from app.chat_analyzer import ChatAnalyzer

pytestmark = pytest.mark.asyncio


class _FakeAI:
    async def get_response(self, *a, **kw):
        return "ok"


class _FakeAuthor:
    def __init__(self, name, is_mod=False, is_vip=False, is_subscriber=False, is_broadcaster=False):
        self.name = name
        self.is_mod = is_mod
        self.is_vip = is_vip
        self.is_subscriber = is_subscriber
        self.is_broadcaster = is_broadcaster


class _FakeChannel:
    def __init__(self, name):
        self.name = name


class _FakeMessage:
    def __init__(self, channel, author, content):
        self.channel = _FakeChannel(channel)
        self.author = author
        self.content = content


class _FakeInstance:
    def __init__(self, account_id, nickname="mybot", token=""):
        self.account_id = account_id
        self.nickname = nickname
        self.token = token


@pytest_asyncio.fixture(autouse=True)
async def _reset_moderation(tmp_db, disable_auth):
    M.invalidate_cache()
    await database.init_db()
    yield
    M.invalidate_cache()


async def _make_account(nickname: str = "shadow_mod_bot", **cols) -> int:
    db = await database.get_db()
    try:
        cur = await db.execute("INSERT INTO accounts (nickname, token) VALUES (?, ?)", (nickname, "oauth:tok"))
        await db.commit()
        aid = cur.lastrowid
        if cols:
            sets = ", ".join(f"{k} = ?" for k in cols)
            await db.execute(f"UPDATE accounts SET {sets} WHERE id = ?", (*cols.values(), aid))
            await db.commit()
    finally:
        await db.close()
    M.invalidate_cache(aid)
    return aid


async def test_shadow_mode_policy():
    """Проверка, что 'shadow' в MODES и _apply_mode_policy переводит действие в 'shadow'."""
    assert "shadow" in M.MODES
    assert M._apply_mode_policy("block", mode="shadow", can_timeout=True) == "shadow"
    assert M._apply_mode_policy("timeout", mode="shadow", can_timeout=True) == "shadow"
    assert M._apply_mode_policy("ban", mode="shadow", can_timeout=True) == "shadow"
    assert M._apply_mode_policy("replace", mode="shadow", can_timeout=True) == "shadow"


async def test_shadow_mode_check_message():
    """Проверка check_message в режиме shadow: вердикт получает action='shadow' и is_shadow=True."""
    aid = await _make_account(nickname="bot_shadow", moderation_mode="shadow")

    # 'уебище' есть во встроенном словаре ru.txt
    verdicts = await M.check_message(aid, "chan", "u1", "он уебище")
    assert verdicts, "Ожидался вердикт"
    v = verdicts[0]
    assert v.action == "shadow"
    assert v.is_shadow is True


async def test_journal_shadow_logging():
    """Проверка, что journal_shadow сохраняет запись с префиксом [SHADOW]."""
    aid = await _make_account(nickname="bot_journal_test")

    row_id = await MJ.journal_shadow(
        account_id=aid,
        channel="my_channel",
        username="crypto_bot",
        category="spam",
        severity=2,
        rule_name="test_spam_rule",
        action="timeout",
        message_excerpt="buy_followers here",
        detail="[SHADOW] Теневой вердикт (timeout) — без наказания в Twitch",
    )
    assert row_id is not None

    entries = await MJ.list_journal(channel="my_channel", limit=5)
    assert len(entries) >= 1
    assert entries[0]["username"] == "crypto_bot"
    assert "[SHADOW]" in entries[0]["detail"]


async def test_chat_analyzer_shadow_mode_does_not_timeout_or_ban():
    """Проверка, что ChatAnalyzer в режиме shadow логирует теневой вердикт и НЕ банит."""
    aid = await _make_account(nickname="analyzer_shadow_bot", moderation_mode="shadow", moderation_can_timeout=1)

    sent = []
    async def capture_send(account_id, channel, text, **kw):
        sent.append(text)
        return True

    analyzer = ChatAnalyzer(ai=_FakeAI(), send_fn=capture_send)
    analyzer.update_settings(aid, {"enabled": True})
    instance = _FakeInstance(account_id=aid)

    mock_punish = AsyncMock()
    with patch("app.moderation.maybe_punish", mock_punish):
        with patch.object(MJ, "journal_shadow", wraps=MJ.journal_shadow) as mock_journal:
            # 'он уебище' триггерит builtin словарь
            msg = _FakeMessage("chan", _FakeAuthor("bad_guy"), "он уебище")
            await analyzer.on_message(instance, msg)

            # Проверяем, что в Twitch Helix наказание (maybe_punish) не вызывалось
            mock_punish.assert_not_called()

            # Проверяем, что journal_shadow был вызван
            assert mock_journal.called
