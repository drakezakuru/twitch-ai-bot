"""Track 6.2 acceptance for the offline qa_chatbot conversation paths."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


pytestmark = pytest.mark.asyncio


class _FakeAI:
    def __init__(self, reply: str):
        self.reply = reply
        self.calls: list[dict] = []

    async def generate_text(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        return self.reply


class _FakeAuthor:
    name = "trusted_viewer"
    is_mod = False
    is_vip = False
    is_subscriber = True
    is_broadcaster = False


class _FakeMessage:
    def __init__(self, content: str):
        self.channel = SimpleNamespace(name="qa_chat_channel")
        self.author = _FakeAuthor()
        self.content = content


class _FakeInstance:
    account_id = 103
    nickname = "qa_chatbot"
    token = ""


class _TwitchStub:
    def __init__(self):
        self.sent: list[tuple[int, str, str]] = []

    async def send_message_detailed(self, account_id, channel, text):
        self.sent.append((account_id, channel, text))
        return {"ok": True}


async def test_qa_chatbot_runtime_and_panel_conversation_use_fakes_only(tmp_path, monkeypatch):
    """Exercise both real runtime paths against the seeded offline profile."""
    from app import qa_profile
    from app.bot_manager import TwitchBotManager
    from app.chat_analyzer import ChatAnalyzer
    from app.dm_chat import _DM_HISTORY, router as dm_router

    profile_base = tmp_path / "qa-profiles"
    await qa_profile.reset_profile("local", base_root=profile_base)
    await qa_profile.seed_profile("local", base_root=profile_base)
    profile_root = qa_profile.profile_root("local", base_root=profile_base)

    async def forbidden_external(*_args, **_kwargs):
        raise AssertionError("the QA acceptance path must not make an external call")

    monkeypatch.setattr("app.chat_analyzer.get_channel_info", forbidden_external)
    monkeypatch.setattr(TwitchBotManager, "send_message_detailed", forbidden_external)

    async with qa_profile._configured_runtime(profile_root):
        runtime_ai = _FakeAI("Offline QA runtime reply")
        runtime_outgoing: list[tuple[int, str, str]] = []

        async def outgoing_stub(account_id, channel, text):
            runtime_outgoing.append((account_id, channel, text))
            return True

        analyzer = ChatAnalyzer(ai=runtime_ai, send_fn=outgoing_stub)
        analyzer.update_settings(103, {
            "enabled": True,
            "use_long_term_memory": True,
            "use_conversation_memory": True,
            "context_source_stream": False,
            "context_source_streamer": False,
            "use_channel_context": False,
        })
        incoming = "qa_chatbot, what does the offline QA viewer remember?"
        await analyzer.on_message(_FakeInstance(), _FakeMessage(incoming))

        assert runtime_outgoing == [(103, "qa_chat_channel", "Offline QA runtime reply")]
        assert len(runtime_ai.calls) == 1
        runtime_call = runtime_ai.calls[0]
        assert incoming in runtime_call["prompt"]
        assert runtime_call["account_id"] == 103
        assert runtime_call["channel"] == "qa_chat_channel"
        assert "offline QA companion" in runtime_call["system"]
        assert "QA conversational bot with deterministic replies." in runtime_call["system"]
        assert "QA viewer remembers the offline constellation" in runtime_call["system"]
        assert "Привет! Это офлайн-ответ." in runtime_call["system"]

        conversation_ai = _FakeAI("Offline QA panel reply")
        twitch_stub = _TwitchStub()
        monkeypatch.setitem(
            sys.modules,
            "app.server",
            SimpleNamespace(ai_service=conversation_ai, bot_manager=twitch_stub, chat_analyzer=analyzer),
        )
        _DM_HISTORY.clear()
        app = FastAPI()
        app.include_router(dm_router)
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post("/api/accounts/103/dm", json={
                    "channel": "qa_chat_channel",
                    "text": "Owner asks the offline QA bot a panel question.",
                })
                history = await client.get("/api/accounts/103/dm/history")
        finally:
            _DM_HISTORY.clear()

        assert response.status_code == 200
        result = response.json()
        assert result == {
            "ok": True,
            "reply": "Offline QA panel reply",
            "channel": "qa_chat_channel",
            "spoken": False,
        }
        assert twitch_stub.sent == [
            (103, "qa_chat_channel", "Owner asks the offline QA bot a panel question."),
            (103, "qa_chat_channel", "Offline QA panel reply"),
        ]
        assert [item["role"] for item in history.json()["messages"]] == ["user", "bot"]
        assert len(conversation_ai.calls) == 1
        assert "offline QA companion" in conversation_ai.calls[0]["system"]
        assert "QA conversational bot with deterministic replies." in conversation_ai.calls[0]["system"]
