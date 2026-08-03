"""sources — the in-package institutional collections, tested offline.

~65 source functions is too many to pin one-by-one without the suite becoming
the thing you maintain. So the bar here is deliberate:

  * **The fan-out machinery in full** — registry integrity, default vs opt-in
    selection, per-source failure isolation, the wall-clock cap, and the
    grouped response shape. That is the part every source depends on, and the
    part where a bug silently loses results rather than raising.
  * **A representative handful of parsers** — one JSON, one XML, one keyed —
    to prove the `_result` citation contract holds across response formats.

Every test stubs the network. Nothing here makes a request.
"""
from __future__ import annotations

import io
import json

import pytest

from jeles import sources


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Fail loudly if a test reaches the network by accident."""
    def explode(*a, **k):
        raise AssertionError("tests must not make real requests")
    monkeypatch.setattr(sources.urllib.request, "urlopen", explode)


def _stub_json(monkeypatch, payload, capture=None):
    def fake(req, timeout=None):
        if capture is not None:
            capture.append(req.full_url if hasattr(req, "full_url") else str(req))
        body = payload if isinstance(payload, (bytes, str)) else json.dumps(payload)
        return _Resp(body.encode() if isinstance(body, str) else body)
    monkeypatch.setattr(sources.urllib.request, "urlopen", fake)


# ── The registry ────────────────────────────────────────────────────────────


def test_the_registry_is_populated_and_well_formed():
    reg = sources._load_registry()
    assert len(reg) >= 50, "the point of this module is breadth"
    for sid, cfg in reg.items():
        assert cfg["name"], f"{sid} has no display name"
        assert isinstance(cfg["key_required"], bool)
        assert isinstance(cfg["opt_in"], bool)


def test_every_registered_source_resolves_to_a_real_function():
    """`_resolve_fn` does getattr on this module, so a typo in a registry
    entry is invisible until someone searches and silently gets nothing."""
    missing = [
        sid for sid, cfg in sources._load_registry().items()
        if not callable(sources._resolve_fn(cfg["fn_name"]))
    ]
    assert not missing, f"registry entries with no function: {missing}"


def test_wikipedia_is_not_in_the_default_set():
    """Stated policy: every default result can appear in an academic
    bibliography."""
    reg = sources._load_registry()
    if "wikipedia" in reg:
        assert reg["wikipedia"]["opt_in"] is True


def test_default_fan_out_excludes_opt_in_sources(monkeypatch):
    seen = []
    monkeypatch.setattr(sources, "_resolve_fn",
                        lambda fn: (lambda q, n: seen.append(fn) or []))
    sources.search("q")
    reg = sources._load_registry()
    opt_in_fns = {c["fn_name"] for c in reg.values() if c["opt_in"]}
    assert not (opt_in_fns & set(seen)), "opt-in sources must be asked for by name"


def test_narrowing_queries_only_the_named_sources(monkeypatch):
    called = []

    def _resolve(fn_name):
        def _fn(q, n):
            called.append(fn_name)
            return []
        return _fn

    monkeypatch.setattr(sources, "_resolve_fn", _resolve)
    out = sources.search("q", sources=["arxiv"])
    assert len(called) == 1
    assert out["sources_queried"] == ["arxiv"]


def test_an_unknown_source_id_is_skipped_not_fatal(monkeypatch):
    monkeypatch.setattr(sources, "_resolve_fn", lambda fn: (lambda q, n: []))
    out = sources.search("q", sources=["arxiv", "not-a-real-source"])
    assert out["total"] == 0  # and no exception


# ── Failure isolation: one bad source must not sink the fan-out ─────────────


def test_one_failing_source_does_not_lose_the_others(monkeypatch):
    def _resolve(fn_name):
        if fn_name == "search_arxiv":
            def _boom(q, n):
                raise RuntimeError("arxiv is down")
            return _boom
        return lambda q, n: [sources._result(
            title="t", url="https://loc.gov/1", source="loc",
            institution="Library of Congress")]

    monkeypatch.setattr(sources, "_resolve_fn", _resolve)
    out = sources.search("q", sources=["arxiv", "loc"])

    assert out["total"] == 1
    assert "arxiv" not in out["results"], "a failed source contributes nothing"
    assert "loc" in out["results"]


def test_sources_returning_nothing_are_omitted_from_results(monkeypatch):
    monkeypatch.setattr(sources, "_resolve_fn", lambda fn: (lambda q, n: []))
    out = sources.search("q", sources=["arxiv", "loc"])
    assert out["results"] == {}
    assert out["sources_queried"] == ["arxiv", "loc"], \
        "queried is what we asked, not what answered"


def test_the_response_is_grouped_by_source_id(monkeypatch):
    monkeypatch.setattr(sources, "_resolve_fn", lambda fn: (lambda q, n: [
        sources._result(title="t", url="https://e.org/1", source="s",
                        institution="Inst")]))
    out = sources.search("q", sources=["arxiv", "loc"])
    assert set(out["results"]) == {"arxiv", "loc"}
    assert out["total"] == 2
    assert out["query"] == "q"


def test_limit_per_source_is_passed_through(monkeypatch):
    seen = []
    monkeypatch.setattr(sources, "_resolve_fn",
                        lambda fn: (lambda q, n: seen.append(n) or []))
    sources.search("q", sources=["arxiv", "loc"], limit_per_source=7)
    assert seen == [7, 7]


def test_the_wall_clock_cap_drops_stragglers_rather_than_hanging(monkeypatch):
    """A slow source must cost a result, not the whole call."""
    import time

    def _resolve(fn_name):
        if fn_name == "search_arxiv":
            def _slow(q, n):
                time.sleep(5)
                return [sources._result(title="late", url="u", source="arxiv",
                                        institution="arXiv")]
            return _slow
        return lambda q, n: [sources._result(
            title="quick", url="https://loc.gov/1", source="loc",
            institution="Library of Congress")]

    monkeypatch.setattr(sources, "_resolve_fn", _resolve)
    started = time.monotonic()
    out = sources.search("q", sources=["arxiv", "loc"], wall_clock_limit=0.5)
    elapsed = time.monotonic() - started

    assert elapsed < 3, "the cap must bound the call, not just log about it"
    assert "loc" in out["results"]


def test_the_executor_is_not_created_at_import():
    """A module-level thread pool would be a side effect in every process that
    merely imports jeles."""
    import subprocess
    import sys
    probe = (
        "import jeles.sources as s\n"
        "assert s._SEARCH_EXECUTOR is None, 'pool built at import'\n"
    )
    assert subprocess.run([sys.executable, "-c", probe]).returncode == 0


def test_the_corpus_does_not_drag_in_the_collections():
    """`jeles.sources` imports urllib.request, so it pulls in socket and ssl —
    unavoidable for a module whose job is HTTP, and the same is true of
    `reactions.search_adapter`. The invariant that actually matters is that the
    *corpus* stays free of all of it, so a host doing local lookups never loads
    a network stack. That is what this guards."""
    import subprocess
    import sys
    probe = (
        "import sys, jeles.corpus\n"
        "assert 'jeles.sources' not in sys.modules, 'corpus pulled in the collections'\n"
        "assert not ({'socket', 'ssl'} & set(sys.modules)), sorted(sys.modules)\n"
    )
    assert subprocess.run([sys.executable, "-c", probe]).returncode == 0


# ── The citation contract ───────────────────────────────────────────────────

CITATION_KEYS = {"title", "url", "source", "institution", "snippet", "date", "id"}


def test_result_shape_is_the_citation_contract():
    r = sources._result(title=" T ", url="u", source="s", institution="I",
                        snippet="x" * 900, date="d", rid="7")
    assert set(r) == CITATION_KEYS
    assert r["title"] == "T", "titles are stripped"
    assert len(r["snippet"]) <= 400, "snippets are capped"
    assert r["id"] == "7"


def test_openalex_parses_json_into_the_contract(monkeypatch):
    _stub_json(monkeypatch, {"results": [{
        "display_name": "Signed policy bundles",
        "doi": "https://doi.org/10.1/x",
        "publication_year": 2026,
        "id": "https://openalex.org/W1",
        "authorships": [{"institutions": [{"display_name": "Cornell University"}]}],
    }]})
    hits = sources.search_openalex("policy", limit=1)
    assert hits and set(hits[0]) == CITATION_KEYS
    assert hits[0]["title"] == "Signed policy bundles"
    assert hits[0]["institution"] == "Cornell University"
    assert hits[0]["url"] == "https://doi.org/10.1/x", "the DOI is the citable url"


def test_an_absent_institution_is_empty_not_invented(monkeypatch):
    """OpenAlex derives the institution from authorships, which are often
    missing. Empty is the honest answer; `institutional.to_hit` falls back to
    the source id for display rather than fabricating an affiliation."""
    _stub_json(monkeypatch, {"results": [{
        "display_name": "Anonymous preprint", "id": "https://openalex.org/W2"}]})
    assert sources.search_openalex("q", limit=1)[0]["institution"] == ""


def test_arxiv_parses_xml_into_the_contract(monkeypatch):
    atom = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>http://arxiv.org/abs/2601.00001v1</id>
        <title>Deterministic policy evaluation</title>
        <summary>An abstract.</summary>
        <published>2026-01-02T00:00:00Z</published>
      </entry>
    </feed>"""
    _stub_json(monkeypatch, atom)
    hits = sources.search_arxiv("policy", limit=1)
    assert hits and set(hits[0]) == CITATION_KEYS
    assert hits[0]["title"] == "Deterministic policy evaluation"
    assert "arxiv.org" in hits[0]["url"]


def test_a_keyed_source_is_skipped_without_its_key(monkeypatch):
    """Missing key means the source is absent, never an exception — that is
    what lets the default fan-out run unconfigured."""
    monkeypatch.delenv("OMDB_API_KEY", raising=False)
    assert sources.search_omdb("dune", limit=1) == []


def test_a_malformed_response_yields_no_hits_rather_than_raising(monkeypatch):
    _stub_json(monkeypatch, "not json at all")
    assert sources.search_openalex("q", limit=1) == []


def test_polite_pool_identity_is_overridable(monkeypatch):
    """Crossref/OpenAlex/NCBI throttle anonymous traffic; the contact address
    is sent, and a deployment must be able to make it its own."""
    urls = []
    monkeypatch.setattr(sources, "_CONTACT_EMAIL", "ops@example.org")
    _stub_json(monkeypatch, {"results": []}, capture=urls)
    sources.search_openalex("q", limit=1)
    assert urls and "ops%40example.org" in urls[0]


# ── The egress path (added when vendoring; not inherited) ───────────────────


def test_every_source_goes_through_the_guarded_opener():
    """`_urlopen` is the single egress point. A source calling
    urllib.request.urlopen directly would skip the scheme guard and the size
    cap, so there should be none left."""
    import pathlib
    src = pathlib.Path(sources.__file__).read_text()
    direct = src.count("urllib.request.urlopen(")
    assert direct == 1, "only _urlopen itself may call urlopen directly"


def test_the_opener_refuses_a_non_http_scheme():
    """URLs are built from queries and API responses, so 'it is always https'
    is worth enforcing rather than assuming."""
    req = sources.urllib.request.Request("file:///etc/passwd")
    with pytest.raises(ValueError, match="refusing non-HTTP"):
        sources._urlopen(req)


def test_bodies_are_capped(monkeypatch):
    monkeypatch.setattr(sources, "_MAX_BYTES", 8)
    with pytest.raises(ValueError, match="refusing"):
        sources._read_capped(io.BytesIO(b"x" * 64))


def test_a_body_at_the_cap_is_still_read(monkeypatch):
    monkeypatch.setattr(sources, "_MAX_BYTES", 8)
    assert sources._read_capped(io.BytesIO(b"x" * 8)) == b"x" * 8


def test_the_module_never_reaches_for_requests():
    """A zero-dependency package must not behave differently because something
    unrelated installed `requests`. The vendored original tried it first and
    fell back to urllib, which also meant a failed request was issued twice."""
    import pathlib
    assert "import requests" not in pathlib.Path(sources.__file__).read_text()


# ── Unreachable is not empty ────────────────────────────────────────────────


def test_search_records_which_sources_failed(monkeypatch):
    def _resolve(fn_name):
        if fn_name == "search_arxiv":
            def _boom(q, n):
                raise RuntimeError("arxiv is down")
            return _boom
        return lambda q, n: [sources._result(
            title="t", url="https://loc.gov/1", source="loc", institution="LoC")]

    monkeypatch.setattr(sources, "_resolve_fn", _resolve)
    out = sources.search("q", sources=["arxiv", "loc"])
    assert set(out["failed"]) == {"arxiv"}
    assert "arxiv is down" in out["failed"]["arxiv"]


def test_a_source_that_swallows_its_own_error_is_still_recorded(monkeypatch):
    """Most sources catch and return [] so one outage cannot sink the fan-out.
    Without the breadcrumb in `_urlopen`, that makes an unreachable source look
    identical to an empty one — which is how a fully blocked egress reported
    ok=true, total=0."""
    def _swallowing_source(q, n):
        try:
            with sources._urlopen(
                    sources.urllib.request.Request("https://example.org")):
                pass
        except Exception:
            return []
        return []

    monkeypatch.setattr(sources, "_resolve_fn", lambda fn: _swallowing_source)

    def refuse(req, timeout=None):
        raise OSError("Tunnel connection failed: 403 Forbidden")
    monkeypatch.setattr(sources.urllib.request, "urlopen", refuse)

    out = sources.search("q", sources=["arxiv"])
    assert "arxiv" in out["failed"], "a swallowed transport error must still surface"
    assert "403" in out["failed"]["arxiv"]


def test_an_empty_but_reachable_source_is_not_marked_failed(monkeypatch):
    monkeypatch.setattr(sources, "_resolve_fn", lambda fn: (lambda q, n: []))
    out = sources.search("q", sources=["arxiv"])
    assert out["failed"] == {}, "reached it, it had nothing — that is not a failure"
