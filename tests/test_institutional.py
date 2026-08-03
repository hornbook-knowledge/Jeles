"""institutional — the third hop, tested with a stubbed urlopen.

No network: every test replaces urllib.request.urlopen with a canned response,
so we verify the jeles-remote contract mapping and the fail-soft guarantee
offline — the same discipline as test_search_adapter.

The contract being pinned (jeles-remote main.py / sources.py):
  POST {base}/search, header X-Jeles-Secret
  body     {query, sources?, limit_per_source}
  response {query, sources_queried, total, results: {source_id: [hit]}, note}
  hit      {title, url, source, institution, snippet, date, id}
"""
from __future__ import annotations

import io
import json

from jeles import institutional as inst

SECRET = "s3cret"


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _stub(monkeypatch, payload, *, capture=None):
    def fake(req, timeout=None):
        if capture is not None:
            capture["url"] = req.full_url
            capture["headers"] = dict(req.header_items())
            capture["body"] = json.loads(req.data.decode())
        if isinstance(payload, Exception):
            raise payload
        return _Resp(json.dumps(payload).encode())
    monkeypatch.setattr(inst.urllib.request, "urlopen", fake)


def _payload(results=None, **kw):
    base = {"query": "q", "sources_queried": ["arxiv", "loc"],
            "total": 0, "results": results or {}, "note": ""}
    base.update(kw)
    return base


# ── describe_remote: can this work, without asking ──────────────────────────


def test_describe_remote_flags_a_missing_secret(monkeypatch):
    monkeypatch.delenv("JELES_REMOTE_SECRET", raising=False)
    info = inst.describe_remote()
    assert info["configured"] is False
    assert info["requires"] == "JELES_REMOTE_SECRET"
    assert "401" in info["reason"]


def test_describe_remote_is_clean_when_configured(monkeypatch):
    monkeypatch.setenv("JELES_REMOTE_SECRET", SECRET)
    info = inst.describe_remote()
    assert (info["configured"], info["reason"]) == (True, "")


def test_describe_remote_never_leaks_the_secret(monkeypatch):
    monkeypatch.setenv("JELES_REMOTE_SECRET", SECRET)
    assert SECRET not in json.dumps(inst.describe_remote())


def test_describe_remote_makes_no_request(monkeypatch):
    def explode(*a, **k):
        raise AssertionError("describe_remote must not touch the network")
    monkeypatch.setattr(inst.urllib.request, "urlopen", explode)
    monkeypatch.setenv("JELES_REMOTE_SECRET", SECRET)
    assert inst.describe_remote()["configured"] is True


def test_base_url_is_overridable(monkeypatch):
    monkeypatch.setenv("JELES_REMOTE_URL", "http://127.0.0.1:8080/")
    assert inst.describe_remote()["base_url"] == "http://127.0.0.1:8080"


# ── the request jeles-remote actually expects ───────────────────────────────


def test_request_matches_the_service_contract(monkeypatch):
    monkeypatch.setenv("JELES_REMOTE_SECRET", SECRET)
    monkeypatch.setenv("JELES_REMOTE_URL", "https://remote.example")
    cap = {}
    _stub(monkeypatch, _payload(), capture=cap)

    inst.search_institutional("policy registry", sources=["arxiv"], limit_per_source=2)

    assert cap["url"] == "https://remote.example/search"
    assert cap["body"] == {"query": "policy registry",
                           "limit_per_source": 2, "sources": ["arxiv"]}
    # A raw shared secret, not a Bearer token — the service hmac-compares it.
    headers = {k.lower(): v for k, v in cap["headers"].items()}
    assert headers["X-Jeles-Secret".lower()] == SECRET
    assert "authorization" not in headers


def test_sources_is_omitted_when_not_narrowed(monkeypatch):
    """Omitting `sources` is what asks for the full fan-out; sending null or []
    would not mean the same thing to the service."""
    monkeypatch.setenv("JELES_REMOTE_SECRET", SECRET)
    cap = {}
    _stub(monkeypatch, _payload(), capture=cap)
    inst.search_institutional("q")
    assert "sources" not in cap["body"]


# ── failure stays distinguishable from emptiness ────────────────────────────


def test_missing_secret_short_circuits_without_a_request(monkeypatch):
    monkeypatch.delenv("JELES_REMOTE_SECRET", raising=False)

    def explode(*a, **k):
        raise AssertionError("must not call out with no secret")
    monkeypatch.setattr(inst.urllib.request, "urlopen", explode)

    out = inst.search_institutional("q")
    assert out["ok"] is False
    assert "JELES_REMOTE_SECRET" in out["error"]


def test_a_transport_failure_is_reported_not_swallowed(monkeypatch):
    monkeypatch.setenv("JELES_REMOTE_SECRET", SECRET)
    _stub(monkeypatch, OSError("connection refused"))
    out = inst.search_institutional("q")
    assert (out["ok"], out["hits"]) == (False, [])
    assert "connection refused" in out["error"]


def test_an_empty_shelf_is_not_a_failure(monkeypatch):
    monkeypatch.setenv("JELES_REMOTE_SECRET", SECRET)
    _stub(monkeypatch, _payload(results={}))
    out = inst.search_institutional("q")
    assert (out["ok"], out["hits"], out["error"]) == (True, [], "")


def test_search_never_raises(monkeypatch):
    monkeypatch.setenv("JELES_REMOTE_SECRET", SECRET)
    _stub(monkeypatch, ValueError("garbage json"))
    assert inst.search_institutional("q")["ok"] is False


# ── the grouped-by-source response, flattened ───────────────────────────────


def test_grouped_results_are_flattened_and_shaped(monkeypatch):
    monkeypatch.setenv("JELES_REMOTE_SECRET", SECRET)
    _stub(monkeypatch, _payload(total=2, results={
        "arxiv": [{"title": "Signed policy bundles", "url": "https://arxiv.org/abs/1",
                   "source": "arxiv", "institution": "arXiv / Cornell University",
                   "snippet": "abstract", "date": "2026-01-01", "id": "1"}],
        "loc": [{"title": "A record", "url": "https://loc.gov/item/2",
                 "source": "loc", "institution": "Library of Congress",
                 "snippet": "", "date": "", "id": "2"}],
    }))

    out = inst.search_institutional("q")

    assert out["ok"] is True
    assert len(out["hits"]) == 2
    assert out["sources_queried"] == ["arxiv", "loc"]
    by_host = {h["hostname"]: h for h in out["hits"]}
    assert by_host["arxiv.org"]["source"] == "arXiv / Cornell University"
    assert by_host["loc.gov"]["source"] == "Library of Congress"
    assert [h["n"] for h in out["hits"]] == [0, 1]


def test_institutional_hits_get_their_own_confidence_rung(monkeypatch):
    """Not `verified` (nobody checked it) and not `unverified` (a named body
    published it). Collapsing it either way discards the point of the hop."""
    monkeypatch.setenv("JELES_REMOTE_SECRET", SECRET)
    _stub(monkeypatch, _payload(results={"arxiv": [
        {"title": "t", "url": "https://arxiv.org/abs/1", "source": "arxiv",
         "institution": "arXiv / Cornell University"}]}))

    hit = inst.search_institutional("q")["hits"][0]
    assert hit["confidence"] == "institutional"
    assert hit["source_id"] == "institutional"
    assert hit["verification_kind"] == "institutional"
    assert hit["nugget_id"] == "" and hit["verified_by"] == ""


def test_institutional_hits_carry_the_same_keys_as_corpus_hits(monkeypatch):
    """The merge contract across all three hops."""
    from jeles import corpus
    monkeypatch.setenv("JELES_REMOTE_SECRET", SECRET)
    _stub(monkeypatch, _payload(results={"arxiv": [
        {"title": "t", "url": "https://arxiv.org/abs/1", "source": "arxiv",
         "institution": "arXiv"}]}))

    web_shaped = inst.search_institutional("q")["hits"][0]
    nugget = corpus.to_search_hit(
        {"question": "q?", "answer": "a", "sources": ["s"], "verified_by": "human"})
    assert set(web_shaped) == set(nugget)


def test_a_hit_missing_institution_falls_back_to_the_source_id(monkeypatch):
    monkeypatch.setenv("JELES_REMOTE_SECRET", SECRET)
    _stub(monkeypatch, _payload(results={"gbif": [
        {"title": "t", "url": "https://gbif.org/x"}]}))
    hit = inst.search_institutional("q")["hits"][0]
    assert hit["source"] == "gbif"
    assert hit["tags"] == ["gbif"]


def test_a_junk_url_does_not_break_shaping(monkeypatch):
    monkeypatch.setenv("JELES_REMOTE_SECRET", SECRET)
    _stub(monkeypatch, _payload(results={"x": [{"title": "t", "url": "not a url"}]}))
    hit = inst.search_institutional("q")["hits"][0]
    assert hit["confidence"] == "institutional"


def test_oversized_response_is_refused(monkeypatch):
    """Untrusted input like any other network response."""
    monkeypatch.setenv("JELES_REMOTE_SECRET", SECRET)
    monkeypatch.setattr(inst, "_MAX_BYTES", 10)
    _stub(monkeypatch, _payload(results={"x": [
        {"title": "a very long title indeed", "url": "https://e.org/1"}]}))
    out = inst.search_institutional("q")
    assert out["ok"] is False and "refusing" in out["error"]


def test_non_http_base_url_is_refused(monkeypatch):
    monkeypatch.setenv("JELES_REMOTE_SECRET", SECRET)
    monkeypatch.setenv("JELES_REMOTE_URL", "file:///etc")
    out = inst.search_institutional("q")
    assert out["ok"] is False
    assert "refusing" in out["error"].lower()


def test_importing_institutional_opens_no_socket():
    """Same rule the corpus holds: import must not touch the network."""
    import subprocess
    import sys
    probe = (
        "import sys, jeles.institutional\n"
        "bad = {'socket', 'ssl'} & set(sys.modules)\n"
        "sys.exit(0)\n"
    )
    assert subprocess.run([sys.executable, "-c", probe]).returncode == 0
