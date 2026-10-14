"""Integration tests for v10.4.7 Wave 4."""

import pytest


def test_chat_analyzer_has_wave4_defaults():
    from app.server import chat_analyzer as ca

    s = ca.get_settings(account_id=999)
    # Wave 4 settings present and default-off
    keys_off = [
        "threads_enabled",
        "proactive_questions_enabled",
        "local_fallback_enabled",
        "notify_enabled",
        "live_mimicry_enabled",
        "replay_recording_enabled",
    ]
    for k in keys_off:
        assert k in s, f"missing setting {k}"
        assert s[k] is False, f"{k} should default False"
    # Defaults
    assert s["proactive_cooldown_sec"] == 180.0
    assert s["notify_min_severity"] == "info"
    assert s["local_fallback_provider"] == "ollama"


def test_chat_analyzer_lazy_init_helpers():
    from app.server import chat_analyzer as ca

    tt = ca._get_thread_tracker(1, "ch")
    pt = ca._get_proactive_tracker(1, "ch")
    lp = ca._get_live_profile(1, "ch")
    nt = ca._get_notifier(1)
    assert tt is not None
    assert pt is not None
    assert lp is not None
    assert nt is not None
    # повторный вызов — тот же объект
    assert ca._get_thread_tracker(1, "ch") is tt


def _collect_route_paths(routes) -> set:
    """Recursively collect route paths, handling FastAPI's _IncludedRouter
    wrapper (introduced in newer FastAPI versions) which nests the real
    routes under `.original_router.routes` instead of exposing `.path`
    directly on the top-level app.routes entries."""
    paths: set = set()
    for r in routes:
        path = getattr(r, "path", None)
        if path is not None:
            paths.add(path)
        nested_router = getattr(r, "original_router", None)
        if nested_router is not None:
            paths |= _collect_route_paths(nested_router.routes)
        nested_routes = getattr(r, "routes", None)
        if nested_routes is not None and nested_router is None:
            paths |= _collect_route_paths(nested_routes)
    return paths


def test_routes_expose_wave4_endpoints():
    from app.server import app

    paths = _collect_route_paths(app.routes)
    expected = [
        "/api/threads/{account_id}",
        "/api/proactive/{account_id}",
        "/api/fallback/router",
        "/api/streamer-notes",
        "/api/streamer-notes/test",
        "/api/live-mimicry/{account_id}",
        "/api/replay/sessions",
        "/api/replay/sessions/start",
    ]
    for p in expected:
        assert p in paths, f"missing endpoint {p}"


def test_all_wave4_modules_import():
    import importlib

    for mod in [
        "app.conversation_threads",
        "app.proactive_questions",
        "app.local_fallback",
        "app.streamer_notify",
        "app.live_mimicry",
        "app.replay_debug",
    ]:
        importlib.import_module(mod)


def test_invalidate_notifier_resets():
    from app.server import chat_analyzer as ca

    n1 = ca._get_notifier(31339)
    ca.invalidate_notifier(31339)
    n2 = ca._get_notifier(31339)
    assert n1 is not n2  # пересоздался


@pytest.mark.asyncio
async def test_record_replay_event_disabled_noop(tmp_path, monkeypatch):
    import app.database as db_mod
    db_path = tmp_path / "wave4.db"
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    monkeypatch.setattr(db_mod, "_shared_db", None)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    from app.server import chat_analyzer as ca

    # replay disabled by default → no exception, no recording
    await ca.record_replay_event(31340, "ch", "chat_in", {"x": 1})
