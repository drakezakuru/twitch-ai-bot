"""MOD-15 gate: correlation dedup, restart ambiguity, stop scope, single dispatch path."""
from __future__ import annotations

import pytest
import pytest_asyncio

from app import moderator_site_library as lib
from app import moderator_site_sound as sound


class _Spy:
    def __init__(self): self.calls: list[tuple[str, str, dict]] = []
    async def __call__(self, channel: str, kind: str, meta: dict) -> None:
        self.calls.append((channel, kind, meta))


@pytest_asyncio.fixture
async def db(tmp_path):
    import aiosqlite
    conn = await aiosqlite.connect(tmp_path / "sound.db")
    await sound.ensure_schema(conn)
    await lib.ensure_schema(conn)
    await lib.add_item(conn, "s1", 1, "chan", "sound", "Drum roll")
    await conn.commit()
    yield conn
    await conn.close()


@pytest.mark.asyncio
async def test_same_correlation_never_double_dispatches(db):
    spy = _Spy()
    first = await sound.play(db, spy, account_id=1, channel="chan", sound_id="s1", correlation_id="corr-1")
    assert first["deduplicated"] is False
    again = await sound.play(db, spy, account_id=1, channel="chan", sound_id="s1", correlation_id="corr-1")
    assert again["deduplicated"] is True and again["correlation_id"] == "corr-1"
    assert len(spy.calls) == 1  # no double dispatch on retry


@pytest.mark.asyncio
async def test_restart_ambiguity_after_done(db):
    spy = _Spy()
    await sound.play(db, spy, account_id=1, channel="chan", sound_id="s1", correlation_id="corr-2")
    # A renderer restart re-sends the same correlation; it must not replay.
    replay = await sound.play(db, spy, account_id=1, channel="chan", sound_id="s1", correlation_id="corr-2")
    assert replay["deduplicated"] is True
    assert len(spy.calls) == 1


@pytest.mark.asyncio
async def test_sound_scope_fencing(db):
    spy = _Spy()
    with pytest.raises(ValueError, match="sound_not_in_scope"):
        await sound.play(db, spy, account_id=1, channel="chan", sound_id="foreign",
                         from_library=lib)  # чужой ID
    with pytest.raises(ValueError, match="sound_not_in_scope"):
        await sound.play(db, spy, account_id=1, channel="chan", sound_id="s1q",
                         from_library=lib)  # не из библиотеки
    assert spy.calls == []


@pytest.mark.asyncio
async def test_stop_scope_stops_all_and_dispatches_stop(db):
    spy = _Spy()
    await sound.play(db, spy, account_id=1, channel="chan", sound_id="s1", correlation_id="c1")
    await sound.play(db, spy, account_id=1, channel="other-chan", sound_id="s1", correlation_id="c2")
    stopped = await sound.stop_scope(db, spy, "chan")
    assert stopped == 1
    kinds = [call[1] for call in spy.calls]
    assert kinds.count("sound_stop") == 1
    status = await sound.safe_status(db, "c1")
    assert status["status"] == "stopped"
    other = await sound.safe_status(db, "c2")
    assert other["status"] == "dispatched"  # другой скоуп не задет
