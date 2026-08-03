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
  * `corpus_web_search` reports a failed search as a failure, never as an
    empty answer, and never labels a web page as verified.

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
    # The settled layer.
    "corpus_ask",
    "corpus_search",
    "corpus_get",
    "corpus_list",
    "corpus_put",
    "corpus_gaps",
    # The second hop.
    "corpus_web_search",
    "corpus_search_status",
    # The third hop.
    "corpus_institutional_search",
    "corpus_sources",
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


def _capture_put(monkeypatch):
    seen = {}

    def _put(question, answer, sources, verified_by, **kw):
        seen.update(question=question, answer=answer, sources=sources,
                    verified_by=verified_by, **kw)
        return {"id": "n1", "action": "created",
                "verification_kind": kw.get("verification_kind")}

    monkeypatch.setattr(corpus_server.corpus, "put_nugget", _put)
    return seen


def test_put_passes_every_field_through(monkeypatch):
    seen = _capture_put(monkeypatch)
    monkeypatch.delenv(corpus_server.TRUST_TOOL_WRITES_ENV, raising=False)

    result = corpus_server.corpus_put(
        "app", "q?", "a.", ["src/one.json"], "designer",
        tags=["colour"], nugget_id="n1",
    )

    assert result == {"id": "n1", "action": "created",
                      "verification_kind": "asserted"}
    assert seen == {
        "question": "q?", "answer": "a.", "sources": ["src/one.json"],
        "verified_by": "designer", "tags": ["colour"], "nugget_id": "n1",
        "verification_kind": "asserted", "written_by": "app",
    }


# ── corpus_put cannot mint the top rung ──────────────────────────────────────
#
# This tool is reachable by any MCP client that can start the server, and one
# of the things that client does is read the open web through
# `corpus_web_search`. At HEAD, a page saying "record that X is true" came back
# through here as a nugget with `verified_by` set to whatever the model typed,
# landed at `confidence: verified`, and was served by `corpus_ask` as settled
# fact from then on — in a store shared with willow-mcp. Verified before the
# fix: `to_search_hit` returned `verified | Verified corpus — the operator`.


def test_a_tool_write_is_an_assertion_not_a_verification(monkeypatch):
    seen = _capture_put(monkeypatch)
    monkeypatch.delenv(corpus_server.TRUST_TOOL_WRITES_ENV, raising=False)

    corpus_server.corpus_put("app", "q?", "a.", ["s"], "the operator")

    assert seen["verification_kind"] == "asserted"


def test_the_caller_cannot_choose_its_own_rung(monkeypatch):
    """`verification_kind` is deliberately not a parameter of the tool. If a
    model could pass it, the gate would be a suggestion."""
    schema = {t.name: t.input_schema for t in _listed_tools()}["corpus_put"]
    props = schema.get("properties") or {}
    assert "verification_kind" not in props
    assert "written_by" not in props, "written_by is stamped from app_id, not supplied"


def test_the_writing_app_is_recorded_beside_the_claim(monkeypatch):
    """`verified_by` is whatever string the caller typed. `written_by` is which
    app actually made the call, and is what a reader is shown."""
    seen = _capture_put(monkeypatch)
    corpus_server.corpus_put("some-mcp-client", "q?", "a.", ["s"], "the operator")
    assert seen["verified_by"] == "the operator"
    assert seen["written_by"] == "some-mcp-client"


def test_the_operator_can_re_open_the_door_on_purpose(monkeypatch):
    """The single-user local case, where the tool caller really is the person:
    an env var, read per call so a typo cannot stop the server from starting."""
    seen = _capture_put(monkeypatch)
    monkeypatch.setenv(corpus_server.TRUST_TOOL_WRITES_ENV, "1")
    corpus_server.corpus_put("app", "q?", "a.", ["s"], "designer")
    assert seen["verification_kind"] == "human"

    monkeypatch.setenv(corpus_server.TRUST_TOOL_WRITES_ENV, "no")
    corpus_server.corpus_put("app", "q?", "a.", ["s"], "designer")
    assert seen["verification_kind"] == "asserted"


def test_the_trust_switch_is_not_read_at_import(monkeypatch):
    """A module-level `os.environ[...]` read is how a typo in an env var turns
    into a server that will not start at all."""
    import inspect
    src = inspect.getsource(corpus_server)
    module_level = [
        line for line in src.splitlines()
        if "os.environ" in line and not line.startswith((" ", "\t"))
    ]
    assert not module_level, f"env read at import time: {module_level}"


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


# ── The second hop: the open web ────────────────────────────────────────────

WEB_TOOLS = {"corpus_web_search", "corpus_search_status"}


def test_the_web_hop_is_registered():
    """The gap this closes: search_adapter existed with exactly one consumer
    (conflict_scan.react), and neither was reachable from this server — so a
    client got a corpus and no internet."""
    assert WEB_TOOLS <= {t.name for t in _listed_tools()}


def test_web_search_reports_a_failure_rather_than_an_empty_answer(monkeypatch):
    """`ok: false` with no hits must not be mistakable for "the web had
    nothing" — answering "I don't know" to a search that never ran is a lie."""
    monkeypatch.setattr(
        corpus_server.search_adapter, "search_with_status",
        lambda q: {"hits": [], "ok": False, "backend": "brave",
                   "shallow": False, "error": "BRAVE_API_KEY is not set"},
    )
    out = corpus_server.corpus_web_search("app", "anything")
    assert out["ok"] is False
    assert out["hits"] == []
    assert "BRAVE_API_KEY" in out["error"]


def test_web_search_distinguishes_a_genuinely_empty_result(monkeypatch):
    monkeypatch.setattr(
        corpus_server.search_adapter, "search_with_status",
        lambda q: {"hits": [], "ok": True, "backend": "searxng",
                   "shallow": False, "error": ""},
    )
    out = corpus_server.corpus_web_search("app", "nothing matches")
    assert (out["ok"], out["hits"], out["error"]) == (True, [], "")


def test_web_hits_are_never_labelled_verified(monkeypatch):
    """Corpus hits and web hits share a shape so they can merge into one ranked
    list. They must not share a confidence: a human-verified nugget and a page
    off the internet cannot be allowed to read the same."""
    monkeypatch.setattr(
        corpus_server.search_adapter, "search_with_status",
        lambda q: {"hits": [
            {"title": "A", "url": "https://example.org/a", "snippet": "s"},
            {"title": "B", "url": "https://sub.example.com/b", "snippet": "t"},
        ], "ok": True, "backend": "searxng", "shallow": False, "error": ""},
    )
    hits = corpus_server.corpus_web_search("app", "q")["hits"]

    assert [h["confidence"] for h in hits] == ["unverified", "unverified"]
    assert [h["source_id"] for h in hits] == ["web", "web"]
    assert [h["hostname"] for h in hits] == ["example.org", "sub.example.com"]
    assert [h["n"] for h in hits] == [0, 1]


def test_web_hits_carry_the_same_keys_as_corpus_hits(monkeypatch):
    """The merge contract for the layering work: same keys, so a host can rank
    corpus and web results together without translating either."""
    monkeypatch.setattr(
        corpus_server.search_adapter, "search_with_status",
        lambda q: {"hits": [{"title": "A", "url": "https://example.org/a", "snippet": "s"}],
                   "ok": True, "backend": "searxng", "shallow": False, "error": ""},
    )
    web = corpus_server.corpus_web_search("app", "q")["hits"][0]
    nugget = corpus_server.corpus.to_search_hit(
        {"question": "q?", "answer": "a", "sources": ["s"], "verified_by": "human"}
    )
    assert set(web) == set(nugget)


def test_web_search_respects_limit(monkeypatch):
    monkeypatch.setattr(
        corpus_server.search_adapter, "search_with_status",
        lambda q: {"hits": [{"title": str(i), "url": f"https://e.org/{i}", "snippet": ""}
                            for i in range(10)],
                   "ok": True, "backend": "searxng", "shallow": False, "error": ""},
    )
    assert len(corpus_server.corpus_web_search("app", "q", limit=3)["hits"]) == 3


def test_web_hit_survives_a_junk_url(monkeypatch):
    """Backends are untrusted input; a malformed url must not take the tool
    down, and the hit must still be shaped."""
    monkeypatch.setattr(
        corpus_server.search_adapter, "search_with_status",
        lambda q: {"hits": [{"title": "x", "url": "not a url", "snippet": ""}],
                   "ok": True, "backend": "ddg", "shallow": True, "error": ""},
    )
    hit = corpus_server.corpus_web_search("app", "q")["hits"][0]
    assert hit["confidence"] == "unverified"
    assert hit["hostname"] in ("web", "")


def test_search_status_passes_the_backend_diagnosis_through(monkeypatch):
    monkeypatch.delenv("JELES_SEARXNG_URL", raising=False)
    monkeypatch.delenv("JELES_SEARCH_BACKEND", raising=False)
    status = corpus_server.corpus_search_status("app")
    assert status["backend"] == "ddg"
    assert (status["configured"], status["shallow"]) == (True, True), \
        "the zero-config default looks healthy and cannot corroborate anything"


def test_search_status_makes_no_request(monkeypatch):
    def explode(*a, **k):
        raise AssertionError("corpus_search_status must not touch the network")
    monkeypatch.setattr(
        corpus_server.search_adapter.urllib.request, "urlopen", explode)
    assert corpus_server.corpus_search_status("app")["backend"]


# ── The third hop: special collections ──────────────────────────────────────


def test_the_institutional_hop_is_registered():
    names = {t.name for t in _listed_tools()}
    assert {"corpus_institutional_search", "corpus_sources"} <= names


def test_institutional_search_runs_locally_with_no_configuration(monkeypatch):
    """No secret, no service — the reason the collections were moved in."""
    monkeypatch.delenv("JELES_REMOTE_URL", raising=False)
    monkeypatch.setattr(
        corpus_server.institutional.sources, "search",
        lambda q, sources=None, limit_per_source=3, **k: {
            "sources_queried": ["arxiv"], "total": 1,
            "results": {"arxiv": [{"title": "t", "url": "https://arxiv.org/abs/1",
                                   "institution": "arXiv"}]}},
    )
    out = corpus_server.corpus_institutional_search("app", "q")
    assert (out["ok"], out["lane"]) == (True, "local")
    assert out["hits"][0]["confidence"] == "institutional"


def test_institutional_search_reports_failure_rather_than_an_empty_shelf(monkeypatch):
    monkeypatch.setattr(
        corpus_server.institutional, "search_institutional",
        lambda q, **k: {"hits": [], "ok": False, "lane": "remote",
                        "sources_queried": [], "total": 0,
                        "error": "JELES_REMOTE_SECRET is not set"},
    )
    out = corpus_server.corpus_institutional_search("app", "q")
    assert out["ok"] is False
    assert "JELES_REMOTE_SECRET" in out["error"]


def test_institutional_search_narrows_and_pages(monkeypatch):
    seen = {}

    def _search(q, *, sources_filter=None, limit_per_source=3):
        seen.update(query=q, sources_filter=sources_filter,
                    limit_per_source=limit_per_source)
        return {"hits": [{"n": i} for i in range(20)], "ok": True,
                "lane": "local", "sources_queried": ["arxiv"],
                "total": 20, "error": ""}

    monkeypatch.setattr(corpus_server.institutional, "search_institutional", _search)
    out = corpus_server.corpus_institutional_search(
        "app", "q", limit=5, sources=["arxiv"], limit_per_source=2)

    assert seen == {"query": "q", "sources_filter": ["arxiv"], "limit_per_source": 2}
    assert len(out["hits"]) == 5
    assert out["total"] == 20, "total reports the fan-out, not the truncated page"


def test_corpus_sources_lists_the_collections_without_searching(monkeypatch):
    out = corpus_server.corpus_sources("app")
    assert out["total"] >= 50
    assert out["default_count"] <= out["total"], "opt-in sources sit out by default"
    assert set(out["sources"][0]) == {"id", "name", "key_required", "opt_in"}


def test_search_status_covers_both_outward_hops(monkeypatch):
    """One place to ask "can I look anywhere?" — and the web keys stay at the
    top level so a client written against 0.3.x keeps working."""
    monkeypatch.delenv("JELES_SEARXNG_URL", raising=False)
    monkeypatch.delenv("JELES_SEARCH_BACKEND", raising=False)
    monkeypatch.delenv("JELES_REMOTE_URL", raising=False)

    status = corpus_server.corpus_search_status("app")

    assert status["backend"] == "ddg"          # unchanged top-level web keys
    assert status["shallow"] is True
    assert status["institutional"]["lane"] == "local"
    assert status["institutional"]["configured"] is True


def test_the_confidence_ladder_has_four_distinct_rungs():
    """verified > corroborated > institutional > unverified. If any two of
    these ever collapse, the librarian is citing something it did not check."""
    from jeles import corpus, institutional

    human = corpus.to_search_hit({"question": "q", "answer": "a",
                                  "sources": ["s"], "verified_by": "human"})
    machine = corpus.to_search_hit({"question": "q", "answer": "a",
                                    "sources": ["s"], "verified_by": "scan",
                                    "verification_kind": "machine"})
    inst_hit = institutional.to_hit({"title": "t", "url": "https://arxiv.org/a",
                                     "institution": "arXiv"})
    web_hit = corpus_server._web_hit({"title": "t", "url": "https://e.org/a"}, 0)

    rungs = [human["confidence"], machine["confidence"],
             inst_hit["confidence"], web_hit["confidence"]]
    assert rungs == ["verified", "corroborated", "institutional", "unverified"]
    assert len(set(rungs)) == 4
