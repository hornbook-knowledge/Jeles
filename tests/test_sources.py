"""sources — the in-package institutional collections, tested offline.

Sixty-odd source functions is too many to pin one-by-one without the suite
becoming the thing you maintain. So the bar here is deliberate:

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

# Captured before any test can monkeypatch it — `test_the_opener_is_assembled`
# needs the real builder, and every other test replaces `sources._opener`.
_REAL_OPENER = sources._opener


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


@pytest.fixture(autouse=True)
def _opener_delegates_to_urlopen(monkeypatch):
    """`_urlopen` goes through a shared OpenerDirector so the scheme guard can
    run on redirect hops too. Every stub in this file replaces
    `urllib.request.urlopen`, which the opener does not consult — without this
    the stubs would be silently bypassed and the tests would hit the network.
    """
    class _Delegating:
        @staticmethod
        def open(req, timeout=None):
            return sources.urllib.request.urlopen(req, timeout=timeout)

    monkeypatch.setattr(sources, "_opener", lambda: _Delegating)


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


def test_no_source_function_opens_or_reads_a_response_itself():
    """The size cap was a rule each source had to remember, and six of the
    eight sites that opened a socket did not — including all three XML
    sources. Now the only way to a body is `_fetch`, which opens and reads in
    one call, and this is what stops the seventh from being added.
    """
    import ast
    import pathlib

    egress = {"_fetch", "_get", "_get_html", "_read_capped", "_urlopen"}
    tree = ast.parse(pathlib.Path(sources.__file__).read_text())
    offenders = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef) or fn.name in egress:
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if isinstance(f, ast.Name) and f.id in {"_urlopen", "urlopen"}:
                offenders.append(f"{fn.name} opens its own response")
            elif isinstance(f, ast.Attribute) and f.attr in {"read", "urlopen"}:
                offenders.append(f"{fn.name} calls .{f.attr}() directly")
    assert not offenders, offenders


def test_the_opener_refuses_a_non_http_scheme():
    """URLs are built from queries and API responses, so the scheme is
    enforced rather than assumed."""
    req = sources.urllib.request.Request("file:///etc/passwd")
    with pytest.raises(ValueError, match="refusing non-https"):
        sources._urlopen(req)


@pytest.mark.parametrize("url, allowed", [
    ("https://example.org/x", True),
    # Plain http is refused. The only two functions that request over it —
    # search_omdb, search_isfdb — are not in SOURCES and never dispatched; the
    # `http://` strings in the registered XML sources are namespace URIs, which
    # are identifiers, not addresses.
    ("http://example.org/x", False),
    ("HTTPS://example.org/x", True),
    ("ftp://example.org/x", False),
    ("file:///etc/passwd", False),
    ("data:text/plain,hello", False),
    ("gopher://example.org/x", False),
])
def test_the_allowed_schemes_are_what_the_docstring_says(url, allowed):
    """An allowed scheme reaches the network stub — which the no-network
    fixture turns into an AssertionError, so getting that far is the proof it
    passed the guard."""
    req = sources.urllib.request.Request(url)
    if allowed:
        with pytest.raises(AssertionError, match="must not make real requests"):
            sources._urlopen(req)
    else:
        with pytest.raises(ValueError, match="refusing non-https"):
            sources._urlopen(req)


@pytest.mark.parametrize("newurl, allowed", [
    ("https://example.org/b", True),
    # A 302 downgrading https -> http is a real attack shape, not a typo.
    ("http://example.org/b", False),
    # stdlib's own filter permits http, https *and* ftp — this is the hop it
    # let through, verified against 3.11 by watching the connection arrive.
    ("ftp://evil.example/x", False),
    ("file:///etc/passwd", False),
])
def test_a_redirect_to_a_disallowed_scheme_is_refused(newurl, allowed):
    """The guard in `_urlopen` sees only the URL a source built; urllib
    follows 3xx internally. Before this handler a 302 to ftp:// was followed
    without the guard ever seeing it."""
    handler = sources._SchemeGuardedRedirects()
    req = sources.urllib.request.Request("https://example.org/a")
    args = (req, io.BytesIO(b""), 302, "Found", {}, newurl)
    if allowed:
        assert handler.redirect_request(*args).full_url == newurl
    else:
        with pytest.raises(sources.urllib.error.HTTPError,
                           match="refusing redirect to a non-https"):
            handler.redirect_request(*args)


def test_the_opener_is_assembled_with_the_guard_and_without_local_schemes():
    names = {type(h).__name__ for h in _REAL_OPENER().handlers}
    assert "_SchemeGuardedRedirects" in names
    assert "HTTPRedirectHandler" not in names, "the unguarded default must not also be in"
    assert not (names & {"FileHandler", "FTPHandler", "DataHandler"}), \
        "a scheme past both checks should have nothing able to open it"


def test_the_opener_is_not_built_at_import():
    """Same promise as the thread pool: importing jeles builds no state."""
    import subprocess
    import sys
    probe = (
        "import jeles.sources as s\n"
        "assert s._OPENER is None, 'opener built at import'\n"
    )
    assert subprocess.run([sys.executable, "-c", probe]).returncode == 0


# One oversized-but-otherwise-valid body per egress site. Each parses into
# exactly one hit when it fits under the cap, so "returns []" means refused
# rather than merely unparseable.
_PAD = "z" * 4096

_OVERSIZED = [
    ("search_arxiv",
     '<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
     '<id>http://arxiv.org/abs/2601.1</id><title>T</title>'
     f'</entry><!--{_PAD}--></feed>'),
    ("search_gallica",
     '<r xmlns:srw="http://www.loc.gov/zing/srw/" '
     'xmlns:dc="http://purl.org/dc/elements/1.1/"><srw:recordData>'
     '<dc:title>T</dc:title><dc:identifier>https://gallica.bnf.fr/ark:/1</dc:identifier>'
     f'</srw:recordData><!--{_PAD}--></r>'),
    ("search_ndl",
     '<r xmlns:srw="http://www.loc.gov/zing/srw/" '
     'xmlns:dc="http://purl.org/dc/elements/1.1/"><srw:recordData>'
     '<dc:title>T</dc:title><dc:identifier>https://iss.ndl.go.jp/books/1</dc:identifier>'
     f'</srw:recordData><!--{_PAD}--></r>'),
    ("search_sep",
     '<html><a href="?entry=/entries/kant/"><b>Kant</b></a>'
     f'<!--{_PAD}--></html>'),
    ("search_nominatim",
     json.dumps([{"display_name": "Paris", "osm_id": 1, "osm_type": "node",
                  "pad": _PAD}])),
    ("search_uk_legislation",
     json.dumps({"items": [{"title": "An Act", "href": "/ukpga/1", "year": 2020}],
                 "pad": _PAD})),
    # Control: this already went through the capped helpers. (`search_isfdb`
    # used to serve as the `_get_html` control; it requests over plain http, is
    # not registered, and is now refused by the scheme guard — `search_sep`
    # above covers the same helper.)
    ("search_openalex",
     json.dumps({"results": [{"display_name": "W", "id": "https://openalex.org/W1"}],
                 "pad": _PAD})),
]


@pytest.mark.parametrize("fn_name, body", _OVERSIZED, ids=[n for n, _ in _OVERSIZED])
def test_an_oversized_response_is_refused_at_every_egress_site(
        monkeypatch, fn_name, body):
    """A source that streams without end must fail, not exhaust memory — at
    every site, not only the two that remembered to call `_read_capped`."""
    served = []

    class _Counting(_Resp):
        def read(self, amt=-1):
            out = super().read(amt)
            served.append(len(out))
            return out

    monkeypatch.setattr(sources.urllib.request, "urlopen",
                        lambda req, timeout=None: _Counting(body.encode()))
    fn = getattr(sources, fn_name)

    monkeypatch.setattr(sources, "_MAX_BYTES", 10_000_000)
    assert len(fn("q", limit=1)) == 1, "the fixture body must parse when it fits"

    served.clear()
    monkeypatch.setattr(sources, "_MAX_BYTES", 512)
    assert fn("q", limit=1) == []
    assert sum(served) <= 513, \
        f"{fn_name} pulled {sum(served)} bytes past a 512-byte cap"


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


def test_no_registered_source_requests_over_plain_http():
    """The scheme guard is https-only, so a registered source pointing at
    `http://` would fail at runtime rather than at review.

    Two functions here do use plain http — `search_omdb` and `search_isfdb` —
    and both are absent from SOURCES, vendored as dead code and never
    dispatched. That is the only reason https-only is free. If either is ever
    registered, this fails: confirm the host serves TLS and switch the URL,
    rather than widening `_ALLOWED_SCHEMES` back.

    The `http://` strings inside `search_arxiv`, `search_gallica` and
    `search_ndl` are XML namespace URIs — identifiers, never fetched — which is
    why matching on request URLs and not on the literal is the point.
    """
    import inspect
    import re as _re

    registered = {cfg.get("fn_name") or f"search_{sid}"
                  for sid, cfg in sources.SOURCES.items()}
    # A plain-http string that is *assigned to a url* or passed to a fetch
    # helper, as opposed to bound as a namespace constant.
    requesting = _re.compile(r'(?:url\s*=\s*|_get\w*\(|_fetch\()\s*\(?\s*f?["\']http://')

    offenders = sorted(
        name for name in registered
        if (fn := getattr(sources, name, None))
        and requesting.search(inspect.getsource(fn))
    )
    assert not offenders, (
        f"registered source(s) request over plain http: {offenders} — the "
        "guard refuses these at runtime")


def test_the_two_plain_http_functions_are_still_unregistered():
    """Pins the premise the test above depends on, from the other side."""
    registered = {cfg.get("fn_name") or f"search_{sid}"
                  for sid, cfg in sources.SOURCES.items()}
    assert "search_omdb" not in registered
    assert "search_isfdb" not in registered
