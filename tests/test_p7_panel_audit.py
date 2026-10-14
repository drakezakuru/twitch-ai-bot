"""P7 PANEL_REVIEW Ф1: автотесты классов багов «виджеты / WS-контракт».

Класс подтверждён прецедентом 01.09 (PANEL_REVIEW_PLAN.md F2, коррекция Ф1):
blur-guard-v2 читал `msg.event`, а бэкенд (app/blur_guard.py::_broadcast) шлёт
`kind` — blur_on/blur_off молча дропались в дефолт-ветке switch и оверлей
реагировал только на свой 5-секундный поллинг (в v2 поллинга нет вовсе).

Тесты держат контракт с двух сторон:
- каждый kind, который бэкенд эммитит в конверте blur_guard, обрабатывается
  в routeEvent виджета blur-guard-v2 (единственный живой оверлей);
- dispatch виджета читает именно то поле, куда бэкенд кладёт событие (`kind`);
- каждый `type === 'X'` в виджетах соответствует типу, реально эммитимому
  бэкендом в /ws (broadcast_log).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIDGETS = ROOT / "widgets"
APP = ROOT / "app"

# kind, о котором бэкенд ещё не знает (контракт задел на будущее) — находка
# в отчёт Ф3, тестом не ловится (dead-подписка, не битый emit).
BLUR_KINDS_NOT_EMITTED = set()  # P8-B5: blur_config теперь эмитится (W1), clean/dirty_frame кейсы удалены из виджета


def _emit_blur_kinds() -> set[str]:
    """kind-и, отправляемые бэкендом в конверте {"type": "blur_guard", "kind": ...}."""
    kinds: set[str] = set()
    for py in APP.glob("*.py"):
        text = py.read_text(encoding="utf-8")
        kinds |= set(re.findall(r'_broadcast\(\s*"([a-z_]+)"', text))
        # инлайн-конверты broadcast_log({"type": "blur_guard", "kind": "X", ...})
        for m in re.finditer(r'"type":\s*"blur_guard"[^)]*?"kind":\s*"([a-z_]+)"', text, re.S):
            kinds.add(m.group(1))
    return kinds


def _direct_ws_types() -> set[str]:
    """Все "type": "X", отправляемые бэкендом через broadcast_log (общий /ws)."""
    text = "\n".join(py.read_text(encoding="utf-8") for py in APP.glob("*.py"))
    return set(re.findall(r'"type":\s*"([a-z_]+)"', text))


def _widget_text(name: str) -> str:
    return (WIDGETS / name / "index.html").read_text(encoding="utf-8")


def test_blur_guard_v2_handles_all_emitted_kinds():
    """Каждый emit бэка (blur_on/blur_off/...) имеет case в routeEvent виджета v2."""
    js = _widget_text("blur-guard-v2")
    m = re.search(r"function routeEvent\(kind, msg\) \{(.*?)\n  \}", js, re.S)
    assert m, "routeEvent не найден в blur-guard-v2"
    cases = set(re.findall(r'case\s+"([a-z_]+)"', m.group(1)))
    emitted = _emit_blur_kinds()
    assert emitted, "не найдено ни одного blur-emit в app/ — регрессия бэка?"
    missing = emitted - cases
    assert not missing, (
        f"бэкенд эммитит blur-события {sorted(missing)}, которых нет в "
        f"routeEvent виджета blur-guard-v2 — оверлей их молча игнорирует"
    )


def test_blur_guard_v2_dispatch_reads_kind_field():
    """Диспатч v2 читает `msg.kind` (поле бэка), а не только легаси `msg.event`."""
    js = _widget_text("blur-guard-v2")
    m = re.search(r'if \(msg\.type === "blur_guard"\) \{(.*?)\n    \}', js, re.S)
    assert m, "ветка blur_guard в handleMessage не найдена"
    body = m.group(1)
    assert re.search(r"msg\.kind\b", body), (
        "ветка blur_guard не читает msg.kind — бэкенд кладёт событие в `kind` "
        "(app/blur_guard.py::_broadcast), события снова будут дропаться"
    )


def test_widget_type_checks_match_backend_emits():
    """Каждый `type === 'X'` в виджетах — реально эммитимый бэкендом тип /ws."""
    emitted = _direct_ws_types()
    assert "chat" in emitted and "blur_guard" in emitted  # санити сбора
    bad: list[tuple[str, str]] = []
    for wdir in sorted(WIDGETS.iterdir()):
        html = wdir / "index.html"
        if not html.is_file():
            continue
        for t in re.findall(r"type\s*===\s*['\"]([a-z_]+)['\"]", html.read_text(encoding="utf-8")):
            if t not in emitted:
                bad.append((wdir.name, t))
    assert not bad, f"виджеты ждут WS-типы, которые бэкенд не шлёт: {bad}"


def test_blur_guard_v2_no_known_dead_subscriptions():
    """Задел на будущее (blur_config/clean_frame/dirty_frame) не разросся:
    новый case в routeEvent без emit в бэке = dead-подписка → в отчёт Ф3."""
    js = _widget_text("blur-guard-v2")
    m = re.search(r"function routeEvent\(kind, msg\) \{(.*?)\n  \}", js, re.S)
    cases = set(re.findall(r'case\s+"([a-z_]+)"', m.group(1)))
    dead = (cases - _emit_blur_kinds()) - BLUR_KINDS_NOT_EMITTED
    assert not dead, (
        f"новые dead-подписки в blur-guard-v2 (case без emit в бэке): {sorted(dead)} — "
        f"добавь emit в app/blur_guard*.py или задокументируй в BLUR_KINDS_NOT_EMITTED"
    )


# ══════════════ Ф1: панельные классы багов (кнопки / API / DOM / БД) ══════════════

from tests._panel_js import panel_js  # noqa: E402

# Шаблоны, НЕ являющиеся живой панелью: страница OBS-виджета со своим JS,
# архивные бэкапы шаблонов.
_EXCLUDED_TEMPLATES = {"obs_tts_widget.html", "index_v10_backup.html"}

# Идентификаторы в onclick, не обязанные быть функциями панели.
_JS_GLOBALS = {
    "if", "this", "window", "navigator", "document", "event", "location",
    "alert", "confirm", "history", "console", "localStorage", "sessionStorage",
    "setTimeout", "open",
}

# Находки Ф1 (битые API-вызовы), разрешённые до вердикта Ф4 — задокументированы.
# Ф1-1 (/api/stream-commands) закрыт в Ф4: мёртвый JS-блок §S6 удалён; если
# фича понадобится — роут и UI делаются вместе, этот allowlist не расширяется.
# P8-A1 (GET /api/accounts/{X}) закрыт: GET-роут заведён в routes.py —
# allowlist пуст; новые записи не добавлять без вердикта владельца.
_API_CALLS_WITHOUT_BACKEND: dict[str, str] = {
    # 20_director.js::_directorReviewURL(): динамическая склейка
    # /api/director/{channel}${path} — аудитор не может развернуть два плейсхолдера.
    # Роуты существуют в app/director_routes.py (/{channel}/prompts, /replay и др.).
    "POST /api/director/{X}{X}": "динамическая склейка _directorReviewURL; роуты в app/director_routes.py",
}


def _live_templates() -> str:
    """Конкатенация живых шаблонов панели (без архива и OBS-страниц)."""
    parts: list[str] = []
    for p in sorted((ROOT / "templates").rglob("*.html")):
        if p.name not in _EXCLUDED_TEMPLATES:
            parts.append(p.read_text(encoding="utf-8"))
    return "\n".join(parts)


def _js_defines(name: str, js: str) -> bool:
    pat = (rf"\bfunction\s+{re.escape(name)}\b"
           rf"|\b(?:const|let|var)\s+{re.escape(name)}\b"
           rf"|\bwindow\.{re.escape(name)}\s*=")
    return bool(re.search(pat, js))


def test_no_dead_onclick_handlers():
    """Класс «мёртвая кнопка»: каждый onclick="fn()" в живых шаблонах →
    fn определена в конкатенации панельного JS. Прецедент: дубль const
    ломал весь app.js (панель без JS)."""
    js = panel_js()
    dead: list[tuple[str, str]] = []
    for p in sorted((ROOT / "templates").rglob("*.html")):
        if p.name in _EXCLUDED_TEMPLATES:
            continue
        for onclick in re.findall(r'onclick="([^"]*)"', p.read_text(encoding="utf-8")):
            m = re.match(r"\s*([A-Za-z_$][\w$]*)", onclick)
            if not m:
                continue
            name = m.group(1)
            if name in _JS_GLOBALS:
                continue
            if not _js_defines(name, js):
                dead.append((p.name, name))
    assert not dead, f"мёртвые onclick-обработчики (нет в панельном JS): {dead}"


def _backend_api_routes() -> set[str]:
    """Реальные пути FastAPI: общий router + все include_router в server.py
    (widgets admin/public, blur-guard, beep и т.д.) — то, что видит клиент."""
    from fastapi.routing import APIRoute
    from app.server import app  # tmp_db (conftest) защищает data/bot.db
    paths: set[str] = set()
    for r in app.routes:
        if isinstance(r, APIRoute):
            paths.add(r.path)
    return paths


def _backend_route_methods() -> dict[str, set[str]]:
    """путь → {GET, POST, PUT, ...} по всем APIRoute приложения."""
    from fastapi.routing import APIRoute
    from app.server import app
    out: dict[str, set[str]] = {}
    for r in app.routes:
        if isinstance(r, APIRoute):
            out.setdefault(r.path, set()).update(m.upper() for m in r.methods)
    return out


_API_CALL_RE = re.compile(
    r"(?:api|wapi)\(\s*[\"'`](/api/[^\"'`\s]+)[\"'`]"
    r"(?:\s*,\s*(?:jopts\(\s*[\"']([A-Z]+)[\"']|{\s*method\s*:\s*[\"']([A-Z]+)[\"']|[\"']([A-Z]+)[\"']))?"
)


def _js_api_calls() -> list[tuple[str, str]]:
    """(метод, путь) из панельного JS: api()/wapi() с 2-м аргументом-методом
    (jopts('PUT',...), {method:'POST'}, 'DELETE') или без него (=GET).
    ${...} → {X}; query отрезается."""
    calls: list[tuple[str, str]] = []
    for m in _API_CALL_RE.finditer(panel_js()):
        raw = m.group(1)
        method = (m.group(2) or m.group(3) or m.group(4) or "GET").upper()
        path = raw.split("?")[0].rstrip("/")
        path = re.sub(r"\$\{[^}]*\}", "{X}", path)
        if path and path != "/api":
            calls.append((method, path))
    return calls


def _api_path_matches(js_path: str, backend_path: str) -> bool:
    a, b = js_path.split("/"), backend_path.split("/")
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if x == "{X}" or (y.startswith("{") and y.endswith("}")):
            continue
        if x != y:
            return False
    return True


def test_panel_api_calls_have_backend_routes():
    """Класс «битый API-вызов» (путь И метод): каждый api()/wapi() из
    панельного JS должен попадать в существующий маршрут с ТЕМ ЖЕ методом.
    Прецеденты: snippets-таблицы нет (ddbfb8f); 405 Method Not Allowed на
    «Мозг бота» — GET /api/accounts/{id} существовал только как PUT/DELETE."""
    route_methods = _backend_route_methods()
    bad: list[str] = []
    for method, path in _js_api_calls():
        hits = [r for r in route_methods if _api_path_matches(path, r)]
        if not hits:
            if path not in _API_CALLS_WITHOUT_BACKEND \
                    and f"{method} {path}" not in _API_CALLS_WITHOUT_BACKEND:
                bad.append(f"{method} {path} — маршрута нет")
        elif not any(method in route_methods[r] for r in hits):
            if f"{method} {path}" not in _API_CALLS_WITHOUT_BACKEND \
                    and path not in _API_CALLS_WITHOUT_BACKEND:
                bad.append(
                    f"{method} {path} — маршрут есть, но методов: "
                    f"{sorted(set().union(*(route_methods[r] for r in hits)))}"
                )
    assert not bad, (
        f"JS дергает API мимо бэкенда: {bad} — почини метод/путь, заведи роут "
        f"или задокументируй в _API_CALLS_WITHOUT_BACKEND"
    )


def test_js_referenced_dom_ids_exist():
    """Класс «DOM-разрыв»: id, запрашиваемые из панельного JS
    (getElementById / querySelector('#x') / $('#x')), должны существовать в
    живых шаблонах ИЛИ создаваться самим JS (innerHTML-строки, .id=…,
    динамические шаблоны id="prefix${…}")."""
    js = panel_js()
    refs = set()
    refs |= set(re.findall(r"getElementById\(\s*['\"]([^'\"${}]+)['\"]", js))
    refs |= set(re.findall(r"querySelector\(\s*['\"]#([A-Za-z][^'\"${}\s]*)['\"]", js))
    refs |= set(re.findall(r"\$\(\s*['\"]#([A-Za-z][^'\"${}\s]*)['\"]", js))

    tpl = _live_templates()
    have = set(re.findall(r'id="([A-Za-z][^"$]*)"', tpl))
    have |= set(re.findall(r'id="([A-Za-z][^"$]*)"', js))
    have |= set(re.findall(r"\.id\s*=\s*['\"]([A-Za-z][^'\"]*)['\"]", js))
    # id из динамических шаблонов: id="roleF_${key}" → префикс+суффикс
    dyn = set(re.findall(r'id="([^"]*\$\{[^"]*)"', tpl))
    dyn |= set(re.findall(r'id="([^"]*\$\{[^"]*)"', js))

    def dyn_match(i: str) -> bool:
        for t in dyn:
            parts = re.split(r"\$\{[^}]*\}", t)
            if (len(parts) == 2 and i.startswith(parts[0]) and i.endswith(parts[1])
                    and len(i) >= len(parts[0]) + len(parts[1])):
                return True
        return False

    missing = sorted(i for i in refs if i not in have and not dyn_match(i))
    assert not missing, (
        f"JS читает DOM-id, которых нет ни в шаблонах, ни в генерируемом JS: "
        f"{missing} — класс «DOM-разрыв» (прецедент: </section> раньше времени)"
    )


# Ленивые создатели таблиц: CREATE TABLE вне app/database.py. Прецедент-класс:
# snippets — эндпоинт жил, таблицы не было. Тест требует, чтобы каждая такая
# таблица создавалась в функции, которая реально вызывается (self-lazy или
# через импорт), — иначе она мертва до первого «случайного» запроса.
def _create_table_sites() -> list[tuple[str, Path, str]]:
    """(таблица, файл, имя функции-создателя) по всем app/**/*.py через AST."""
    import ast
    sites: list[tuple[str, Path, str]] = []
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))

        def visit(node, fn_name: str) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    visit(child, child.name)
                    continue
                if (isinstance(child, ast.Constant) and isinstance(child.value, str)
                        and "CREATE TABLE" in child.value):
                    m = re.search(r"CREATE TABLE\s+(?:IF NOT EXISTS\s+)?([a-zA-Z_]+)",
                                  child.value)
                    if m:
                        sites.append((m.group(1), path, fn_name))
                visit(child, fn_name)

        visit(tree, "<module>")
    return sites


def _creator_is_called(module: Path, func: str) -> bool:
    """func вызывается в своём модуле или в модуле, который его импортирует
    (в т.ч. с алиасом: `from app.x import ensure_schema as _x_ensure`)."""
    if re.search(rf"(?<!def )\b{re.escape(func)}\s*\(", module.read_text(encoding="utf-8")):
        return True
    stem = module.stem
    for py in APP.glob("*.py"):
        if py == module:
            continue
        t = py.read_text(encoding="utf-8")
        imp = re.search(rf"from app\.{stem} import|from \.{stem} import|import app\.{stem}\b", t)
        if not imp:
            continue
        if re.search(rf"\b{re.escape(func)}\s*\(", t):
            return True
        # алиасный импорт: ... import <func> as <alias> → зовут под алиасом
        for alias in re.findall(rf"import\s+(?:[\w.,\s]*\b)?{re.escape(func)}\s+as\s+(\w+)", t):
            if re.search(rf"\b{re.escape(alias)}\s*\(", t):
                return True
    return False


def test_all_create_table_sites_are_reachable():
    """Класс «таблицы нет»: каждая CREATE TABLE из кода — либо в app/database.py
    (путь init_db при старте), либо в вызываемом ленивом создателе."""
    seen: dict[str, tuple[Path, str]] = {}
    for table, path, func in _create_table_sites():
        seen.setdefault(table, (path, func))
    problems: list[str] = []
    for table, (path, func) in sorted(seen.items()):
        if path.name == "database.py":
            continue  # путь init_db при старте
        if func == "<module>":
            problems.append(f"{table}: CREATE TABLE на уровне модуля {path.name} — не вызывается")
        elif not _creator_is_called(path, func):
            problems.append(
                f"{table}: ленивый создатель {path.name}::{func}() нигде не вызывается"
            )
    assert not problems, (
        f"CREATE TABLE без достижимого создания: {problems} — "
        f"добавь вызов ensure-функции или перенеси CREATE TABLE в init_db "
        f"(прецедент: snippets, ddbfb8f)"
    )


def test_widget_dirs_are_served_and_readme_urls_exist():
    """Класс «виджет-сирота»: папка widgets/<name>/index.html без серверного
    маршрута никогда не загрузится в OBS; _widget_html() с несуществующей
    папкой — 500 на живом оверлее. Плюс: каждый /widget|/obs URL из
    widgets/README.md должен существовать в бэкенде."""
    dirs = {d.name for d in WIDGETS.iterdir() if d.is_dir() and (d / "index.html").exists()}
    served: set[str] = set()
    for py in APP.glob("*.py"):
        t = py.read_text(encoding="utf-8")
        served |= set(re.findall(r'_widget_html\(\s*["\']([a-z0-9\-_]+)["\']', t))
        served |= set(re.findall(r'"widgets"\s*/\s*"([a-z0-9\-_]+)"', t))
    orphans = sorted(dirs - served - {"_shared"})
    assert not orphans, f"виджеты без серверного маршрута: {orphans}"
    ghosts = sorted(served - dirs)
    assert not ghosts, f"_widget_html()/путь ссылается на несуществующие папки: {ghosts}"

    routes = _backend_api_routes()
    readme = (WIDGETS / "README.md").read_text(encoding="utf-8")
    doc_urls = set(re.findall(r"/(?:widget|obs)/[a-z0-9\-]+", readme))
    undocumented = sorted(u for u in doc_urls if u not in routes)
    assert not undocumented, f"URL из widgets/README.md не существуют в бэкенде: {undocumented}"

    from app.widget_inventory import (
        ALIAS_WIDGETS,
        LEGACY_PARAM_URLS,
        PROTECTED_WIDGET_OUTPUTS,
        RETIRED_WIDGETS,
        WIDGET_INVENTORY,
    )

    rows = re.findall(
        r"^\| `([^`]+)` \| `([^`]+)` \| `([^`]+)` \| (\d+)×(\d+) \(([^)]+)\) \|$",
        readme,
        re.M,
    )
    documented = {
        slug: (folder, route, int(width), int(height), layout)
        for slug, folder, route, width, height, layout in rows
    }
    expected = {
        item.slug: (
            f"{item.folder}/index.html",
            item.route,
            item.obs_width,
            item.obs_height,
            item.obs_layout,
        )
        for item in WIDGET_INVENTORY
    }
    assert documented == expected, "README active inventory/sizes drifted from canonical registry"

    compatibility_urls = (
        set(RETIRED_WIDGETS)
        | set(ALIAS_WIDGETS)
        | set(LEGACY_PARAM_URLS)
        | set(PROTECTED_WIDGET_OUTPUTS)
    )
    missing_compatibility = sorted(url for url in compatibility_urls if url not in readme)
    assert not missing_compatibility, f"README пропустил compatibility URL: {missing_compatibility}"


# ══════════════ Ф4: класс «cross-чанковый hoisting» (Ф2-1) ══════════════
# В монолите function-декларации поднимались на весь файл; после P5-сплита —
# только внутри своего чанка. Top-level ссылка на функцию из ПОЗДНЕГО чанка
# бросает ReferenceError и обрывает выполнение остатка чанка в браузере.
# Прецедент: loadHeatmap() в 04 (функция в 07), _botTabLoaders в 06
# (loadBrainPreview в 09) — см. находку Ф2-1.

_JS_KEYWORDS = {
    "if", "for", "while", "switch", "catch", "function", "return", "typeof",
    "new", "delete", "void", "await", "async", "case", "do", "else", "throw",
    "try", "finally", "with", "in", "of", "instanceof",
}
_JS_EVAL_GLOBALS = {
    "window", "document", "location", "navigator", "history", "console",
    "alert", "confirm", "prompt", "fetch", "setTimeout", "setInterval",
    "clearTimeout", "clearInterval", "requestAnimationFrame", "localStorage",
    "sessionStorage", "Math", "JSON", "Date", "Object", "Array", "String",
    "Number", "Boolean", "Promise", "RegExp", "Error", "TypeError",
    "encodeURIComponent", "decodeURIComponent", "parseInt", "parseFloat",
    "isNaN", "structuredClone", "URLSearchParams", "URL", "FormData",
    "Blob", "FileReader", "WebSocket", "Event", "CustomEvent", "MutationObserver",
    "IntersectionObserver", "ResizeObserver", "crypto", "performance", "getComputedStyle",
    "matchMedia", "open", "close", "alert",
}


def _strip_js_noise(code: str) -> str:
    """Убрать комментарии и строковые/шаблонные литералы (для depth-скана).
    Апострофы внутри одинарных строк ('п'ять') ломают чётность кавычек —
    такие строки выбрасываем целиком (для depth-баланса достаточно)."""
    code = re.sub(r"/\*.*?\*/", " ", code, flags=re.S)
    code = re.sub(r"`(?:[^`\\]|\\.)*`", "``", code, flags=re.S)
    out: list[str] = []
    for line in code.split("\n"):
        line = re.sub(r"//[^\n]*", " ", line)
        if line.count("'") % 2 == 1 or line.count('"') % 2 == 1:
            continue
        line = re.sub(r'"(?:[^"\\\n]|\\.)*"', '""', line)
        line = re.sub(r"'(?:[^'\\\n]|\\.)*'", "''", line)
        out.append(line)
    return "\n".join(out)


def _chunk_order() -> list[Path]:
    """Порядок чанков из <script src> в templates/base.html."""
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    srcs = re.findall(r'<script src="(/static/[^"?]+)', base)
    return [ROOT / src.lstrip("/") for src in srcs]


def _depth_scan_line(line: str, depth: int) -> int:
    for ch in line:
        if ch in "{([":
            depth += 1
        elif ch in "})]":
            depth = max(0, depth - 1)
    return depth


_CALL_RE = re.compile(r"(?<![\w$.\"'])([A-Za-z_$][\w$]*)\s*\(")
_FN_DECL_RE = re.compile(r"(?:(?:async\s+)?function\s+([A-Za-z_$][\w$]*)|window\.([A-Za-z_$][\w$]*)\s*=)")


def _top_level_refs(code: str, fn_names: set[str]) -> set[str]:
    """Идентификаторы, используемые top-level кодом чанка: вызовы name(...) и
    значения в const/let/var-инициализаторах (включая многострочные литералы;
    ключи объекта 'name:', обращения x.name и параметры стрелок отбрасываются)."""
    lines = code.split("\n")
    refs: set[str] = set()
    depth = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        d_start = depth
        d_end = _depth_scan_line(line, depth)
        top_line = d_start == 0 and d_end == 0
        # 1) complete top-level statement line
        if top_line:
            # однострочная function-декларация: вызовы в её теле исполняются
            # в момент клика/вызова, а не при загрузке чанка — не top-level
            if not re.match(r"\s*function\s+[A-Za-z_$][\w$]*\s*\([^)]*\)\s*\{.*\}\s*;?\s*$", line):
                for m in _CALL_RE.finditer(line):
                    refs.add(m.group(1))
            dm = re.match(r"\s*(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*=\s*(.+);?\s*$", line)
            if dm:
                seg = dm.group(1)
                ids = set(re.findall(r"[A-Za-z_$][\w$]*", seg))
                ids -= set(re.findall(r"([A-Za-z_$][\w$]*)\s*:", seg))
                refs |= ids
        # 2) многострочный const/let/var инициализатор
        if d_start == 0 and d_end > 0 and re.match(r"\s*(?:const|let|var)\b", line):
            j = i
            block: list[str] = []
            d = 0
            while j < len(lines):
                block.append(lines[j])
                d = _depth_scan_line(lines[j], d)
                j += 1
                if d == 0:
                    break
            seg = "\n".join(block)
            ids = set(re.findall(r"[A-Za-z_$][\w$]*", seg))
            ids -= set(re.findall(r"([A-Za-z_$][\w$]*)\s*:", seg))
            ids -= set(re.findall(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)", seg))
            # только имена, являющиеся function-декларациями где-либо
            # (параметры стрелок/промисов и локальные const не считаем)
            refs |= ids & fn_names
            i = j
            depth = 0
            continue
        depth = d_end
        i += 1
    return refs


def _declared_names(code: str) -> set[str]:
    """Имена, объявленные в чанке: function/const/let/var/class/window.X=."""
    names = set(re.findall(r"\b(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", code))
    names |= set(re.findall(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)", code))
    names |= set(re.findall(r"\bclass\s+([A-Za-z_$][\w$]*)", code))
    names |= set(re.findall(r"window\.([A-Za-z_$][\w$]*)\s*=", code))
    return names


def test_no_forward_chunk_references():
    """Класс «cross-чанковый hoisting» (Ф2-1): top-level код чанка не имеет
    права ссылаться на функции/константы, объявленные только в ПОЗДНИХ чанках —
    в браузере это ReferenceError + обрыв остатка чанка."""
    chunks = _chunk_order()
    assert len(chunks) >= 10, "не удалось прочитать порядок чанков из base.html"
    problems: list[str] = []

    decl_by_chunk = [_declared_names(_strip_js_noise(p.read_text(encoding="utf-8")))
                     for p in chunks]
    all_defined: set[str] = set().union(*decl_by_chunk)
    fn_names: set[str] = set()
    for p in chunks:
        src = _strip_js_noise(p.read_text(encoding="utf-8"))
        fn_names |= {a or b for a, b in _FN_DECL_RE.findall(src)}

    for idx, path in enumerate(chunks):
        raw = _strip_js_noise(path.read_text(encoding="utf-8"))
        refs = _top_level_refs(raw, fn_names)
        refs -= decl_by_chunk[idx]
        for name in sorted(refs):
            if name in _JS_KEYWORDS or name in _JS_EVAL_GLOBALS:
                continue
            if any(name in decl_by_chunk[k] for k in range(idx)):
                continue  # более ранний чанк: уже исполнен к этому моменту
            if name not in all_defined:
                continue  # совсем неизвестные имена — не этот класс (см. мёртвые кнопки/API-тесты)
            problems.append(f"{path.name}: '{name}' объявлен только в позднем чанке")
    assert not problems, (
        f"top-level ссылки на поздние чанки (ReferenceError + обрыв чанка в браузере): "
        f"{problems} — перенеси вызов в 16_tail.js или сделай инициализацию ленивой "
        f"(прецедент Ф2-1: loadHeatmap, _botTabLoaders)"
    )


def test_no_duplicate_top_level_function_declarations():
    """Класс «мёртвый дубликат» (27.09.2026): две функции с одним именем в разных чанках —
    браузер выполняет обе последовательно, вторая молча перекрывает первую (window.<имя>).
    Первая версия не выполняется никогда, но выглядит как живой код и путает при чтении.
    Прецедент: showBotTab (03_bots.js вперемешку с 06_roles.js) и waBindingScope
    (07_widgets.js вперемешку с 13_widgets_session.js) — обе дублирующие копии удалены;
    этот тест не даёт паре появиться снова незамеченной.
    """
    chunks = _chunk_order()
    seen: dict[str, str] = {}
    problems: list[str] = []
    for path in chunks:
        src = _strip_js_noise(path.read_text(encoding="utf-8"))
        for match in re.finditer(r"^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(", src, re.M):
            name = match.group(1)
            if name in seen and seen[name] != path.name:
                problems.append(f"{name}: {seen[name]} и {path.name}")
            else:
                seen[name] = path.name
    assert not problems, (
        f"дублирующиеся top-level function-объявления (вторая копия мёртвая, "
        f"перекрывается загрузкой позже): {problems}"
    )
