"""corpus_server — the standalone MCP server over the corpus.

This module had **no tests at all** until the SDK 2.0 port, which is exactly why
its breakage was invisible: `mcp.server.fastmcp` was removed in SDK 2.0, so
`import jeles.corpus_server` raised ModuleNotFoundError under any 2.x SDK, and
nothing in CI ever imported it.

These tests are deliberately cheap. They import the module (which is the check
that caught nothing before), assert the tool surface is what the README claims,
and drive each tool against a stubbed corpus to pin the two behaviours that are
easy to get wrong and impossible to see from a signature:

  * `corpus_ask` forwards a gap on a miss, and does *not* on a hit.
  * `corpus_search` never forwards, whatever it finds.

Skipped wholesale when the SDK is absent — base `jeles` has no runtime
dependencies, and the `no-extras` CI leg installs exactly that shape.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("mcp", reason="jeles[mcp] extra not installed")

import jeles  # noqa: E402
from jeles import corpus_server  # noqa: E402

EXPECTED_TOOLS = {
    "corpus_ask",
    "corpus_search",
    "corpus_get",
    "corpus_list",
    "corpus_put",
    "corpus_gaps",
}


def _listed_tools():
    return asyncio.run(corpus_server.mcp.list_tools())


def test_exactly_the_documented_tools_are_registered():
    assert {t.name for t in _listed_tools()} == EXPECTED_TOOLS


def test_every_tool_carries_a_description():
    """The docstrings are the tool descriptions an MCP client shows a model."""
    missing = [t.name for t in _listed_tools() if not (t.description or "").strip()]
    assert not missing, f"tools with no description: {missing}"


def test_every_tool_takes_app_id():
    """Naming-convention parity with willow-mcp: `app_id` on every tool, so a
    permission gate can be added later without changing any signature."""
    # SDK 2.0 renamed Tool.inputSchema -> Tool.input_schema.
    without = [
        t.name for t in _listed_tools()
        if "app_id" not in (t.input_schema.get("properties") or {})
    ]
    assert not without, f"tools missing app_id: {without}"


def test_server_advertises_the_package_version():
    """Guards the tag-derived version reaching the wire, not just the metadata."""
    assert corpus_server.mcp.version == jeles.__version__


def test_ask_forwards_a_gap_on_a_miss(monkeypatch):
    forwarded = []
    monkeypatch.setattr(corpus_server.corpus, "ask_corpus", lambda q: {"found": False})
    monkeypatch.setattr(
        corpus_server.willow_mcp_client, "forward_gap", lambda q: forwarded.append(q)
    )

    result = corpus_server.corpus_ask("app", "what is the accent colour?")

    assert result == {"found": False}
    assert forwarded == ["what is the accent colour?"]


def test_ask_does_not_forward_on_a_hit(monkeypatch):
    forwarded = []
    monkeypatch.setattr(
        corpus_server.corpus, "ask_corpus",
        lambda q: {"found": True, "exact": True, "nugget": {"id": "n1"}},
    )
    monkeypatch.setattr(
        corpus_server.willow_mcp_client, "forward_gap", lambda q: forwarded.append(q)
    )

    result = corpus_server.corpus_ask("app", "known question")

    assert result["found"] is True
    assert forwarded == [], "a hit must not be recorded as a gap"


def test_search_never_forwards_even_when_it_finds_nothing(monkeypatch):
    """The passive/deliberate split: search is background, so a miss is not a
    gap. Only `ask` treats a miss as a question worth tracking."""
    forwarded = []
    monkeypatch.setattr(corpus_server.corpus, "search_nuggets", lambda q, limit: [])
    monkeypatch.setattr(
        corpus_server.willow_mcp_client, "forward_gap", lambda q: forwarded.append(q)
    )

    assert corpus_server.corpus_search("app", "nothing matches this") == []
    assert forwarded == []


def test_put_passes_every_field_through(monkeypatch):
    seen = {}

    def _put(question, answer, sources, verified_by, tags=None, nugget_id=None):
        seen.update(
            question=question, answer=answer, sources=sources,
            verified_by=verified_by, tags=tags, nugget_id=nugget_id,
        )
        return {"id": "n1", "action": "created"}

    monkeypatch.setattr(corpus_server.corpus, "put_nugget", _put)

    result = corpus_server.corpus_put(
        "app", "q?", "a.", ["src/one.json"], "designer",
        tags=["colour"], nugget_id="n1",
    )

    assert result == {"id": "n1", "action": "created"}
    assert seen == {
        "question": "q?", "answer": "a.", "sources": ["src/one.json"],
        "verified_by": "designer", "tags": ["colour"], "nugget_id": "n1",
    }


@pytest.mark.parametrize(
    "tool,corpus_fn,args",
    [
        ("corpus_get", "get_nugget", ("app", "n1")),
        ("corpus_list", "list_nuggets", ("app",)),
        ("corpus_gaps", "list_gaps", ("app",)),
    ],
)
def test_read_tools_delegate_to_corpus(monkeypatch, tool, corpus_fn, args):
    sentinel = {"delegated": True}
    monkeypatch.setattr(
        corpus_server.corpus, corpus_fn, lambda *a, **k: sentinel
    )
    assert getattr(corpus_server, tool)(*args) == sentinel
