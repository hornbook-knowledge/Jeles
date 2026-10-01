"""`_apps_root` precedence and `_store_call` ToolError wrapping (Loki F1/F2).

Shipped after Loki CLEAR-with-findings on ``4381af2``: the claim held, but no
tests pinned the apps-root ladder or that write-path tools surface through
``ToolError`` instead of MCP SDK 2's opaque ``Error executing tool``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jeles import corpus

pytest.importorskip("mcp", reason="jeles[mcp] extra not installed")

from mcp.server.mcpserver.exceptions import ToolError

from jeles import corpus_server


def test_apps_root_prefers_explicit_over_willow_home(monkeypatch, tmp_path):
    explicit = tmp_path / "explicit-apps"
    box = tmp_path / "box"
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(explicit))
    monkeypatch.setenv("WILLOW_HOME", str(box))
    assert corpus._apps_root() == Path(explicit)


def test_apps_root_uses_willow_home_mcp_apps_when_no_explicit(monkeypatch, tmp_path):
    box = tmp_path / "box"
    monkeypatch.delenv("WILLOW_MCP_APPS_ROOT", raising=False)
    monkeypatch.setenv("WILLOW_HOME", str(box))
    assert corpus._apps_root() == box / "mcp_apps"


def test_apps_root_whitespace_explicit_falls_through_to_willow_home(monkeypatch, tmp_path):
    box = tmp_path / "box"
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", "   ")
    monkeypatch.setenv("WILLOW_HOME", str(box))
    assert corpus._apps_root() == box / "mcp_apps"


def test_apps_root_whitespace_home_falls_through_to_dot_willow(monkeypatch):
    monkeypatch.delenv("WILLOW_MCP_APPS_ROOT", raising=False)
    monkeypatch.setenv("WILLOW_HOME", "  ")
    root = corpus._apps_root()
    assert root.name == "mcp_apps"
    assert root.parent.name == ".willow"


def test_apps_root_default_is_dot_willow_mcp_apps(monkeypatch):
    monkeypatch.delenv("WILLOW_MCP_APPS_ROOT", raising=False)
    monkeypatch.delenv("WILLOW_HOME", raising=False)
    root = corpus._apps_root()
    assert root.name == "mcp_apps"
    assert root.parent.name == ".willow"


def test_store_call_wraps_permission_error_as_tool_error():
    def boom():
        raise PermissionError("manifest refused store_scope")

    with pytest.raises(ToolError, match="manifest refused store_scope"):
        corpus_server._store_call(boom)


def test_store_call_wraps_value_error_as_tool_error():
    def boom():
        raise ValueError("bad collection")

    with pytest.raises(ToolError, match="bad collection"):
        corpus_server._store_call(boom)


def test_store_call_rethrows_tool_error_unchanged():
    def boom():
        raise ToolError("already typed")

    with pytest.raises(ToolError, match="already typed") as caught:
        corpus_server._store_call(boom)
    assert type(caught.value) is ToolError


def test_store_call_does_not_swallow_unexpected_errors():
    def boom():
        raise RuntimeError("not anticipated")

    with pytest.raises(RuntimeError, match="not anticipated"):
        corpus_server._store_call(boom)


def test_corpus_put_surfaces_permission_error_as_tool_error(monkeypatch):
    monkeypatch.setattr(corpus_server, "_trust_tool_writes", lambda: False)

    def refuse(*_a, **_k):
        raise PermissionError("write path BARE without wrap")

    monkeypatch.setattr(corpus_server.corpus, "put_nugget", refuse)
    with pytest.raises(ToolError, match="write path BARE"):
        corpus_server.corpus_put("app", "q?", "a.", ["s"], "operator")


def test_corpus_resolve_gap_surfaces_permission_error_as_tool_error(monkeypatch):
    def refuse(*_a, **_k):
        raise PermissionError("resolve path BARE without wrap")

    monkeypatch.setattr(corpus_server.corpus, "resolve_gap", refuse)
    with pytest.raises(ToolError, match="resolve path BARE"):
        corpus_server.corpus_resolve_gap("app", "g1")
