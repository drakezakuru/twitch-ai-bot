from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_panel_conversation_ui_is_text_channel_and_tts_only():
    html = (ROOT / "templates/partials/bots.html").read_text(encoding="utf-8")
    modal = html.split('id="dmChatModal"', 1)[1].split('id="addBotModal"', 1)[0]
    assert 'id="dmChannel"' in modal
    assert 'id="dmInput"' in modal
    assert 'id="dmSpeakReply"' in modal
    assert 'dmVoice' not in modal and 'dmPhoto' not in modal and 'dmRecBtn' not in modal


def test_panel_conversation_requires_twitch_and_posts_both_messages():
    src = (ROOT / "app/dm_chat.py").read_text(encoding="utf-8")
    assert 'send_message_detailed(account_id, channel, text)' in src
    assert 'send_message_detailed(account_id, channel, reply)' in src
    assert '"channel_required"' in src
    assert '"bot_not_connected"' not in src  # reason is relayed from the manager


def test_companion_uses_existing_tts_probability():
    src = (ROOT / "app/dm_chat.py").read_text(encoding="utf-8")
    assert 'chat_analyzer._tts_should_speak(account_id, channel)' in src
    role_src = (ROOT / "app/chat_analyzer.py").read_text(encoding="utf-8")
    assert 'if role == "voice_companion":\n            return True' in role_src
