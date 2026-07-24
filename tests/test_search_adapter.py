"""search_adapter — the real web-search edge, tested with a stubbed urlopen.

No network: every test replaces urllib.request.urlopen with a canned response,
so we verify the JSON→contract mapping and the fail-soft guarantee offline.
"""
import io
import json

import pytest

from jeles.reactions import search_adapter as sa


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _stub_urlopen(monkeypatch, payload, *, capture=None):
    """Make urlopen return `payload` (dict→json bytes, or an Exception to raise)."""
    def fake(req, timeout=None):
        if capture is not None:
            capture["url"] = req.full_url
            capture["headers"] = dict(req.header_items())
            capture["data"] = req.data
        if isinstance(payload, Exception):
            raise payload
        return _Resp(json.dumps(payload).encode())
    monkeypatch.setattr(sa.urllib.request, "urlopen", fake)


def test_searxng_maps_results(monkeypatch):
    monkeypatch.setenv("JELES_SEARXNG_URL", "http://127.0.0.1:8888")
    cap = {}
    _stub_urlopen(monkeypatch, {"results": [
        {"title": "OPA bundles", "url": "https://openpolicyagent.org/x", "content": "signed"},
        {"title": "Cedar", "url": "https://cedarpolicy.com/y", "content": "deterministic"},
    ]}, capture=cap)
    hits = sa.make_searcher("searxng")("signed policy registry")
    assert [h["url"] for h in hits] == ["https://openpolicyagent.org/x", "https://cedarpolicy.com/y"]
    assert hits[0]["snippet"] == "signed"          # content -> snippet
    assert "format=json" in cap["url"] and "127.0.0.1:8888" in cap["url"]


def test_brave_maps_nested_results_and_sends_key(monkeypatch):
    monkeypatch.setenv("BRAVE_API_KEY", "secret-key")
    cap = {}
    _stub_urlopen(monkeypatch, {"web": {"results": [
        {"title": "t", "url": "https://a.org/1", "description": "d"},
    ]}}, capture=cap)
    hits = sa.make_searcher("brave")("q")
    assert hits == [{"title": "t", "url": "https://a.org/1", "snippet": "d"}]
    # The key rides in a header, not the URL (urllib title-cases header names,
    # so match case-insensitively — HTTP headers are case-insensitive anyway).
    lc = {k.lower(): v for k, v in cap["headers"].items()}
    assert lc.get("x-subscription-token") == "secret-key"
    assert "secret-key" not in cap["url"]


def test_tavily_posts_body(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tv-key")
    cap = {}
    _stub_urlopen(monkeypatch, {"results": [
        {"title": "t", "url": "https://b.org/2", "content": "c"},
    ]}, capture=cap)
    hits = sa.make_searcher("tavily")("q")
    assert hits[0]["url"] == "https://b.org/2"
    assert json.loads(cap["data"])["query"] == "q"     # POSTed, not in querystring


def test_backend_that_fails_is_soft_empty(monkeypatch):
    monkeypatch.setenv("JELES_SEARXNG_URL", "http://127.0.0.1:8888")
    _stub_urlopen(monkeypatch, OSError("connection refused"))
    assert sa.make_searcher("searxng")("q") == []      # never raises


def test_missing_key_is_soft_empty(monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    # No urlopen stub needed: the backend raises before any network call.
    assert sa.make_searcher("brave")("q") == []


def test_default_backend_prefers_searxng_when_url_set(monkeypatch):
    monkeypatch.delenv("JELES_SEARCH_BACKEND", raising=False)
    monkeypatch.setenv("JELES_SEARXNG_URL", "http://127.0.0.1:8888")
    assert sa._default_backend_name() == "searxng"
    monkeypatch.delenv("JELES_SEARXNG_URL", raising=False)
    assert sa._default_backend_name() == "ddg"          # keyless fallback


def test_unknown_backend_raises_at_construction(monkeypatch):
    with pytest.raises(ValueError):
        sa.make_searcher("altavista")


def test_end_to_end_react_with_stubbed_adapter(monkeypatch):
    """The adapter feeds react() exactly like the real thing — two independent
    domains from a stubbed SearXNG corroborate into a proposed nugget."""
    from jeles.reactions import conflict_scan as cs
    monkeypatch.setenv("JELES_SEARXNG_URL", "http://127.0.0.1:8888")
    _stub_urlopen(monkeypatch, {"results": [
        {"title": "OPA", "url": "https://openpolicyagent.org/a", "content": "x"},
        {"title": "Oso", "url": "https://osohq.com/b", "content": "y"},
    ]})
    proposals = cs.react({"claim": "signed reaction registry"},
                         searcher=sa.make_searcher("searxng"))
    assert proposals[0]["driver"] == "put_nugget"
    assert proposals[0]["args"]["verified_by"] == cs.WITNESS
