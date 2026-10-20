"""Offline and privacy guarantees, checked against the source code."""

from __future__ import annotations

import ast
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "riskascent"
NETWORK_MODULES = {"socket", "urllib.request", "http.client", "requests", "httpx", "aiohttp", "ftplib",
                   "smtplib", "telnetlib", "xmlrpc.client", "PySide6.QtNetwork", "PySide6.QtWebEngineCore"}
UNSAFE_CALLS = {"eval", "exec", "compile", "__import__"}


def _imports(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
            for a in node.names:
                yield f"{node.module}.{a.name}"


def test_no_network_or_dynamic_code():
    offenders = []
    for f in PKG.rglob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for name in _imports(tree):
            if any(name == m or name.startswith(m + ".") for m in NETWORK_MODULES):
                offenders.append(f"{f.name}: imports {name}")
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in UNSAFE_CALLS:
                offenders.append(f"{f.name}:{node.lineno} calls {node.func.id}")
    assert offenders == []


def test_user_data_stays_in_the_data_folder(game, data_home, saves):
    # The game writes only to the save manager's folders and the data folder.
    assert str(saves.slot_path(1)).startswith(str(saves.saves))
    from riskascent.paths import user_data_dir
    assert user_data_dir() == data_home
