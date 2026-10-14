"""Тесты универсального парсера аккаунтов, кук и токенов Twitch."""
from __future__ import annotations

from app.account_parser import parse_account_line, parse_accounts_input


def test_parse_login_pass_token():
    line = "cool_bot:secret_pass_123:a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5"
    parsed = parse_account_line(line)
    assert parsed is not None
    assert parsed.token == "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5"
    assert parsed.nickname_hint == "cool_bot"


def test_parse_login_pass_oauth_prefix():
    line = "bot_nick:my_password:oauth:a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5"
    parsed = parse_account_line(line)
    assert parsed is not None
    assert parsed.token == "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5"
    assert parsed.nickname_hint == "bot_nick"


def test_parse_login_pass_cookie_string():
    line = "streamer_fan:Pass999:auth-token=a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5; unique_id=987; persistent=yes"
    parsed = parse_account_line(line)
    assert parsed is not None
    assert parsed.token == "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5"
    assert parsed.nickname_hint == "streamer_fan"


def test_parse_pure_cookie_string():
    line = "unique_id=abc; auth-token=a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5; server_session=123"
    parsed = parse_account_line(line)
    assert parsed is not None
    assert parsed.token == "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5"


def test_parse_json_cookie_editor():
    json_text = '[{"name": "unique_id", "value": "123"}, {"name": "auth-token", "value": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5"}]'
    res = parse_accounts_input(json_text)
    assert len(res) == 1
    assert res[0].token == "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5"


def test_parse_shop_format_with_email():
    line = "bot1:pass1:bot1@mail.ru:mailpass:a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5"
    parsed = parse_account_line(line)
    assert parsed is not None
    assert parsed.token == "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5"
    assert parsed.nickname_hint == "bot1"


def test_parse_shop_format_with_proxy():
    line = "bot2:pass2:a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5:185.220.101.5:8080:puser:ppass"
    parsed = parse_account_line(line)
    assert parsed is not None
    assert parsed.token == "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5"
    assert parsed.nickname_hint == "bot2"
    assert parsed.proxy == "http://puser:ppass@185.220.101.5:8080"


def test_parse_pipe_delimiter():
    line = "bot3|pass3|a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5"
    parsed = parse_account_line(line)
    assert parsed is not None
    assert parsed.token == "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5"
    assert parsed.nickname_hint == "bot3"


def test_parse_plain_tokens():
    line = "oauth:a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5"
    assert parse_account_line(line).token == "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5"

    line2 = "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5"
    assert parse_account_line(line2).token == "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5"
