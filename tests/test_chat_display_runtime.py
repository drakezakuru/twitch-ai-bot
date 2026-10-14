"""Focused runtime contracts for Track 6.6 chat and TTS overlays."""
import json
from pathlib import Path
import subprocess

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parents[1]


def _widget(slug: str) -> str:
    return (ROOT / "widgets" / slug / "index.html").read_text(encoding="utf-8")


def _render_chat_message_in_dom(message: dict) -> dict:
    """Run the production renderer in a minimal DOM that rejects HTML sinks."""
    script = r'''
const fs = require('fs');
const vm = require('vm');
class Node {
  constructor(name, text) {
    this.name = name;
    this.children = [];
    this.className = '';
    this.style = {};
    this._text = text || '';
    this.classList = { add: () => {} };
  }
  appendChild(child) { this.children.push(child); return child; }
  get firstElementChild() { return this.children.find(child => child.name !== '#text') || null; }
  get textContent() { return this.name === '#text' ? this._text : this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this.children = [new Node('#text', String(value))]; }
  set innerHTML(value) { throw new Error('HTML sink invoked: ' + value); }
}
const document = {
  createElement: name => new Node(name),
  createTextNode: text => new Node('#text', String(text)),
};
const context = { document, URLSearchParams, location: { search: '', host: 'test', protocol: 'http:' }, setTimeout: () => 0, window: {} };
context.window = context;
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
const container = new Node('div');
context.ChatMessageCore.createList({
  container,
  settings: { max_messages: 8, lifetime_sec: 0, font_size: 24, emote_size: 32, show_badges: 1 },
}).add(JSON.parse(process.argv[2]));
function snapshot(node) { return { name: node.name, text: node.textContent, children: node.children.map(snapshot) }; }
process.stdout.write(JSON.stringify({ tree: snapshot(container), pwned: context.pwned === true }));
'''
    result = subprocess.run(
        ["node", "-e", script, str(ROOT / "widgets/_shared/chat-message-core.js"), json.dumps(message)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _render_legacy_obs_message(html: str, message: dict) -> dict:
    script = r'''
const vm = require('vm');
class Node {
  constructor(name, text = '') { this.name = name; this.children = []; this.className = ''; this.style = {}; this._text = text; }
  appendChild(child) { this.children.push(child); return child; }
  removeChild(child) { this.children.splice(this.children.indexOf(child), 1); }
  get firstChild() { return this.children[0] || null; }
  get textContent() { return this.name === '#text' ? this._text : this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this.children = [new Node('#text', String(value))]; }
  set innerHTML(value) { throw new Error('HTML sink invoked: ' + value); }
}
const chat = new Node('div');
const document = {
  createElement: name => new Node(name),
  createTextNode: text => new Node('#text', String(text)),
  getElementById: id => id === 'chat' ? chat : null,
};
const context = { document, location: { protocol: 'http:', host: 'test' } };
context.WebSocket = class { constructor() { context.socket = this; } };
vm.createContext(context);
vm.runInContext(process.argv[1], context);
context.socket.onmessage({ data: process.argv[2] });
function snapshot(node) { return { name: node.name, text: node.textContent, className: node.className, children: node.children.map(snapshot) }; }
process.stdout.write(JSON.stringify({ tree: snapshot(chat), pwned: context.pwned === true }));
'''
    production_script = html.rsplit("<script>", 1)[1].split("</script>", 1)[0]
    result = subprocess.run(
        ["node", "-e", script, production_script, json.dumps(message)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_selected_chat_demonstrates_badges_emotes_history_and_states():
    html = _widget("selected-chat")
    for marker in ("badges:['MOD']", "Kappa", "selected-history",
                   "selected-chat.empty"):
        assert marker in html
    # RU-фолбэки живут в WidgetI18n (в виджете и _shared/i18n.js)
    assert "Нет выбранных сообщений" in html
    assert "'common.disconnected'" in html
    assert "Нет связи с панелью" in (ROOT / "widgets" / "_shared" / "i18n.js").read_text(encoding="utf-8")
    assert "socket.onclose" in html and "setTimeout(connect,3000)" in html


def test_emoji_chat_filters_content_bots_and_has_reconnect_states():
    html = _widget("emoji-chat")
    assert "hasEmojiContent(message)" in html
    assert "!SHOW_BOTS && isBot" in html
    assert "API.replace" in html
    assert "Нет сообщений с эмодзи" in html  # emoji-chat.empty (WidgetI18n)
    assert "'common.disconnected'" in html and "Нет связи с панелью" in (
        ROOT / "widgets" / "_shared" / "i18n.js").read_text(encoding="utf-8")
    assert "Promise.all([loadEmojiCore(), loadEmotes()]).finally(connect)" in html


@pytest.mark.asyncio
async def test_seeded_selected_chat_history_renders_xss_payload_as_text(tmp_db, disable_auth):
    """Track 6.2: persisted trusted history must never become executable markup."""
    from app.chat_overlay_routes import admin_router, public_router
    from app.database import get_db, init_db

    payload = '<img src=x onerror="globalThis.pwned=true"><script>globalThis.pwned=true</script>'
    await init_db()
    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(public_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.put("/api/widgets/chat/trusted-users", json={"users": ["trusted_viewer"]})
        db = await get_db()
        try:
            await db.execute(
                "INSERT INTO chat_log (account_id, channel, author, message) VALUES (?, ?, ?, ?)",
                (101, "local", "trusted_viewer", payload),
            )
            await db.commit()
        finally:
            await db.close()
        response = await client.get(
            "/api/widgets/public/chat/selected-history",
            params={"account_id": 101, "channel": "local", "limit": 8, "minutes": 30},
        )

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert [message["message"] for message in messages] == [payload]
    rendered = _render_chat_message_in_dom(messages[0])
    row = rendered["tree"]["children"][0]
    assert rendered["pwned"] is False
    assert row["text"] == f"trusted_viewer:{payload}"
    assert [child["name"] for child in row["children"]] == ["span", "span"]
    body_nodes = row["children"][1]["children"]
    assert all(node["name"] == "#text" for node in body_nodes)
    assert "".join(node["text"] for node in body_nodes) == payload


@pytest.mark.asyncio
async def test_legacy_obs_widget_renders_author_and_message_as_text(disable_auth):
    from app.routes import obs_widget

    author = '</span><img src=x onerror="globalThis.pwned=true">'
    message = '<script>globalThis.pwned=true</script>'
    rendered = _render_legacy_obs_message(
        await obs_widget(),
        {"type": "chat", "author": author, "message": message},
    )

    assert rendered["pwned"] is False
    row = rendered["tree"]["children"][0]
    assert row["className"] == "msg"
    assert row["text"] == f"{author}:{message}"
    assert [child["name"] for child in row["children"]] == ["span", "#text"]


def test_tts_widgets_declare_audio_and_display_contracts():
    reader = _widget("chat-reader")
    bot = _widget("tts-bot")
    overlay = _widget("tts-chat-overlay")
    raw = _widget("tts-raw")
    assert "TtsCore.queue" in reader and "types: ['tts']" in reader
    assert "msg.speaker || msg.channel" in bot and "msg.display_text || msg.text" in bot
    # i18n: disconnected — общий ключ WidgetI18n, waiting — локальный словарь виджета
    assert "'common.disconnected'" in bot and "Ожидание озвучки" in bot
    assert "TtsCore.queue" not in overlay and "TTS_FILTER" in overlay
    assert "types: ['chat']" in raw and "TtsCore.queue" in raw


@pytest.mark.asyncio
async def test_tts_chat_filter_is_bounded_and_reaches_runtime(tmp_db, disable_auth):
    from app.database import init_db
    from app.widgets import public_router

    await init_db()
    app = FastAPI()
    app.include_router(public_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        rewards = await client.get("/widget/tts-chat-overlay", params={"filter": "rewards"})
        invalid = await client.get("/widget/tts-chat-overlay", params={"filter": "invalid"})
    assert 'const TTS_FILTER = "rewards"' in rewards.text
    assert 'const TTS_FILTER = "all"' in invalid.text


@pytest.mark.asyncio
async def test_bot_manager_forwards_twitch_badges():
    from app.bot_manager import TwitchBotManager

    received = {}

    async def callback(account_id, channel, author, message, is_bot, *,
                       badges=None, message_id="", channel_id=""):
        received.update(account_id=account_id, channel=channel, badges=badges,
                        message_id=message_id, channel_id=channel_id)

    manager = TwitchBotManager()
    manager.set_log_callback(callback)
    await manager._log(7, "Demo", "viewer", "hello", badges=["moderator"])
    assert received == {"account_id": 7, "channel": "Demo", "badges": ["moderator"],
                        "message_id": "", "channel_id": ""}
