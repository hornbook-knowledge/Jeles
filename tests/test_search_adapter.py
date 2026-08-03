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


# ── Legibility: telling "found nothing" apart from "could not look" ──────────
#
# Every failure used to return [] with no logging, so an unset key, an
# unreachable host, a 403 and a genuinely empty result were one symptom with
# four causes. These pin the difference.


def test_describe_backend_flags_an_unconfigured_backend(monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    info = sa.describe_backend("brave")
    assert info["configured"] is False
    assert info["requires"] == "BRAVE_API_KEY"
    assert "BRAVE_API_KEY" in info["reason"]


def test_describe_backend_flags_ddg_as_shallow_even_though_it_works(monkeypatch):
    """The trap: ddg needs no configuration, so it looks healthy. It is the
    zero-config fallback and it cannot corroborate anything."""
    info = sa.describe_backend("ddg")
    assert info["configured"] is True
    assert info["shallow"] is True
    assert "shallow" in info["reason"] or "related topics" in info["reason"]


def test_describe_backend_is_clean_when_properly_configured(monkeypatch):
    monkeypatch.setenv("JELES_SEARXNG_URL", "http://127.0.0.1:8888")
    info = sa.describe_backend("searxng")
    assert (info["configured"], info["shallow"], info["reason"]) == (True, False, "")


def test_describe_backend_makes_no_request(monkeypatch):
    """It answers "can this even work?" — asking must not cost a round trip."""
    def explode(*a, **k):
        raise AssertionError("describe_backend must not touch the network")
    monkeypatch.setattr(sa.urllib.request, "urlopen", explode)
    monkeypatch.setenv("JELES_SEARXNG_URL", "http://127.0.0.1:8888")
    assert sa.describe_backend("searxng")["configured"] is True


def test_describe_backend_names_an_unknown_backend(monkeypatch):
    info = sa.describe_backend("altavista")
    assert info["configured"] is False and "altavista" in info["reason"]


def test_search_with_status_separates_failure_from_emptiness(monkeypatch):
    monkeypatch.setenv("JELES_SEARXNG_URL", "http://127.0.0.1:8888")

    _stub_urlopen(monkeypatch, {"results": []})
    empty = sa.search_with_status("q", "searxng")
    assert (empty["ok"], empty["hits"], empty["error"]) == (True, [], "")

    _stub_urlopen(monkeypatch, OSError("connection refused"))
    broken = sa.search_with_status("q", "searxng")
    assert broken["ok"] is False
    assert broken["hits"] == []
    assert "connection refused" in broken["error"]


def test_search_with_status_explains_a_missing_key_rather_than_raising(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    out = sa.search_with_status("q", "tavily")
    assert out["ok"] is False
    assert "TAVILY_API_KEY" in out["error"]


def test_make_searcher_still_swallows_but_now_logs(monkeypatch, caplog):
    """Corroboration depends on a failed search yielding no witness, so [] stays.
    Silence does not."""
    monkeypatch.setenv("JELES_SEARXNG_URL", "http://127.0.0.1:8888")
    _stub_urlopen(monkeypatch, OSError("boom"))
    with caplog.at_level("WARNING", logger="jeles.search"):
        assert sa.make_searcher("searxng")("q") == []
    assert "boom" in caplog.text
    assert "q" in caplog.text, "the failing query should be identifiable"


def test_make_searcher_warns_once_about_an_unconfigured_backend(monkeypatch, caplog):
    """The configuration warning is per-searcher, not per-query — otherwise a
    misconfigured backend floods the log and the signal is lost in itself."""
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    search = sa.make_searcher("brave")
    with caplog.at_level("WARNING", logger="jeles.search"):
        search("one")
        search("two")

    config_warnings = [r for r in caplog.records if "search backend" in r.getMessage()]
    assert len(config_warnings) == 1
    assert "BRAVE_API_KEY" in config_warnings[0].getMessage()

    # Each individual failure is still reported, so a per-query problem is not
    # hidden by the once-only configuration notice.
    failures = [r for r in caplog.records if "failed for" in r.getMessage()]
    assert len(failures) == 2
