"""P5-сплит routes.py: вынос секции [start, end) в app/routes_<name>.py.

Использование:
  python3 scripts/p5_split_routes.py <name> <start_prefix> <end_prefix|EOF> [routes_names...] [--extra "import x"]

- Модуль декорирует ОБЩИЙ router из app.routes и импортируется одной строкой
  внизу routes.py (после создания router).
- AST-аудит внешних имён: всё, что не покрыто (stdlib/fastapi/typing/routes_names/
  --extra), вызывает АБОРТ без записи.
"""
import ast
import builtins
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILTIN = set(dir(builtins)) | {"self", "cls"}
STDLIB = {"json", "time", "asyncio", "os", "re", "math", "random", "datetime",
          "base64", "hashlib", "uuid", "io", "csv", "textwrap", "statistics",
          "collections", "itertools", "functools", "traceback", "urllib",
          "tempfile", "shutil", "glob", "string", "secrets", "copy", "queue",
          "threading", "sqlite3", "logging", "signal", "socket", "subprocess",
          "sys", "warnings", "zipfile", "xml", "html", "difflib",
          "unicodedata", "contextlib", "dataclasses", "enum", "abc", "inspect",
          "platform"}
FASTAPI = {"HTTPException", "Request", "Depends", "BackgroundTasks", "File",
           "UploadFile", "Query", "Body", "Header", "Cookie", "Form",
           "Response", "JSONResponse", "StreamingResponse", "WebSocket",
           "WebSocketDisconnect", "status", "APIRouter"}
TYPING = {"Any", "Dict", "List", "Optional", "Tuple", "Union", "Set"}


def _names_in_target(tgt):
    return {nn.id for nn in ast.walk(tgt) if isinstance(nn, ast.Name)}


def local_names(bt):
    local = set()
    for node in ast.walk(bt):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            local.add(node.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                local.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                local.add(a.asname or a.name)
        elif isinstance(node, ast.Assign):
            for tg in node.targets:
                local |= _names_in_target(tg)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            local.add(node.target.id)
        elif isinstance(node, ast.arg):
            local.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            local.add(node.name)
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            local |= _names_in_target(node.target)
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            local |= _names_in_target(node.optional_vars)
        elif isinstance(node, ast.NamedExpr):
            local.add(node.target.id)
    return local


def module_avail(bt):
    avail = set()
    for node in bt.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            avail.add(node.name)
        elif isinstance(node, ast.Assign):
            for tg in node.targets:
                avail |= _names_in_target(tg)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            avail.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                avail.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, ast.If):
            for sub in ast.walk(node):
                if isinstance(sub, (ast.Import, ast.ImportFrom)):
                    for a in sub.names:
                        avail.add((a.asname or a.name).split(".")[0])
    return avail


def routes_top(src):
    top = set()
    for node in ast.parse(src).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            top.add(node.name)
        elif isinstance(node, ast.Assign):
            for tg in node.targets:
                top |= _names_in_target(tg)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            top.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                top.add((a.asname or a.name).split(".")[0])
    return top


def main():
    args = sys.argv[1:]
    name, start, end = args[0], args[1], args[2]
    rest = args[3:]
    extras = []
    given = []
    i = 0
    while i < len(rest):
        if rest[i] == "--extra":
            extras.append(rest[i + 1])
            i += 2
        else:
            given.append(rest[i])
            i += 1

    rp = ROOT / "app/routes.py"
    src = rp.read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)
    si = next((i for i, l in enumerate(lines) if l.startswith(start)), None)
    if si is None:
        sys.exit(f"ABORT: start-баннер не найден: {start}")
    if end == "EOF":
        ei = len(lines)
    else:
        ei = next((i for i, l in enumerate(lines) if i > si and l.startswith(end)), None)
        if ei is None:
            sys.exit(f"ABORT: end-баннер не найден: {end}")
    body = "".join(lines[si:ei])
    # если резали до EOF — отбросить хвостовые late-import строки routes.py, попавшие в срез
    tail_imports = []
    bl = body.splitlines(keepends=True)
    while bl and (bl[-1].startswith("from app import routes_")
                  or bl[-1].startswith("from app.routes")
                  or bl[-1].startswith("# P5-сплит")
                  or bl[-1].strip() == ""):
        tail_imports.insert(0, bl.pop())
    body = "".join(bl)
    bt = ast.parse(body)
    local = local_names(bt)
    avail = module_avail(bt)
    used = {n.id for n in ast.walk(bt) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    ext = (used - local - BUILTIN) - avail
    top = routes_top(src)
    given_set = set(given)
    leftover = sorted(ext - STDLIB - FASTAPI - TYPING - top - given_set)
    if leftover:
        sys.exit(f"ABORT: тело тянет внешние имена (передай их аргументами): {leftover}")
    std = sorted(n for n in ext if n in STDLIB)
    fapi = sorted(n for n in ext if n in FASTAPI)
    typ = sorted(n for n in ext if n in TYPING)
    from_routes = sorted((ext & (top | given_set)) - STDLIB - FASTAPI - TYPING)

    hdr = (f'"""{name} — вынесено из app/routes.py (P5-сплит, PLAN.md). Декорирует ОБЩИЙ\n'
           f'router из app.routes; импортируется ВНИЗУ routes.py (после создания router).\n"""\n')
    if typ:
        hdr += "from typing import " + ", ".join(typ) + "\n"
    if std:
        hdr += "import " + ", ".join(std) + "\n"
    if fapi:
        hdr += "from fastapi import " + ", ".join(fapi) + "\n"
    for e in extras:
        hdr += e.rstrip("\n") + "\n"
    from_routes = [n for n in from_routes if n != "router"]
    hdr += "from app.routes import " + ", ".join(["router"] + from_routes) + "  # noqa: E402\n\n\n"
    module = hdr + body.rstrip("\n") + "\n"
    (ROOT / f"app/routes_{name}.py").write_text(module, encoding="utf-8")
    new = "".join(lines[:si] + lines[ei:]).rstrip("\n")
    new += f"\nfrom app import routes_{name}  # noqa: E402\n"
    rp.write_text(new, encoding="utf-8")
    ast.parse(rp.read_text(encoding="utf-8"))
    ast.parse(module)
    print(f"OK routes_{name}.py: {len(module.splitlines())} строк; routes.py → {len(new.splitlines())}")


main()
