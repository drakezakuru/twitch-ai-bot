import pytest
import pytest_asyncio
import httpx
from app.server import app
from app import database
from app.database import set_setting, get_setting, get_db
from app.channel_bans import channel_key as bans_key
from app.channel_allowed import channel_allowed_key as allowed_key

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _fresh_db(tmp_db, disable_auth):
    await database.init_db()
    yield


async def test_channel_clone_settings():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Валидация ошибок
        r1 = await client.post("/api/channels/clone-settings", json={"from_channel": "", "to_channel": "b"})
        assert r1.status_code == 200 and not r1.json()["ok"]

        r2 = await client.post("/api/channels/clone-settings", json={"from_channel": "a", "to_channel": "a"})
        assert r2.status_code == 200 and not r2.json()["ok"]

        # Подготовка данных исходного канала
        chan_a = "sourcechan"
        chan_b = "targetchan"

        db = await get_db()
        try:
            await db.execute(
                "INSERT INTO moderation_channel_rules (channel, pattern, category, action, severity, action_ext, enabled) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (chan_a, "запретное_слово_тест", "hate", "block", 5, "ban", 1)
            )
            await db.commit()
        finally:
            await db.close()

        await set_setting(bans_key(chan_a), "Не говорить о спойлерах\nНе обсуждать политику")
        await set_setting(allowed_key(chan_a), "Хвалить стримера\nОбсуждать игру")

        # Клонируем
        resp = await client.post("/api/channels/clone-settings", json={
            "from_channel": chan_a,
            "to_channel": chan_b,
            "copy_rules": True,
            "copy_bans": True,
            "copy_allowed": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["rules_copied"] >= 1
        assert data["bans_copied"] is True
        assert data["allowed_copied"] is True

        # Проверяем целевой канал
        db = await get_db()
        try:
            cur = await db.execute("SELECT pattern FROM moderation_channel_rules WHERE channel = ?", (chan_b,))
            rows = await cur.fetchall()
            patterns = [r["pattern"] for r in rows]
            assert "запретное_слово_тест" in patterns
        finally:
            await db.close()

        target_bans = await get_setting(bans_key(chan_b), "")
        assert "Не говорить о спойлерах" in target_bans

        target_allowed = await get_setting(allowed_key(chan_b), "")
        assert "Хвалить стримера" in target_allowed
