"""institutional — the third hop, local-first, tested offline.

`jeles.sources` does the fan-out and is tested in test_sources.py. What this
file pins is the layer above it:

  * which lane a search takes, and that the local one needs no configuration
  * that a failure never reads as an empty shelf
  * the hit shape, and that `institutional` stays its own rung on the
    confidence ladder

Nothing here makes a request: the local lane is driven with a stubbed
`sources.search`, and the remote lane with a stubbed `urlopen`.
"""
from __future__ import annotations

import io
import json

import pytest

from jeles import institutional as inst

SECRET = "s3cret"


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("JELES_REMOTE_URL", raising=False)
    monkeypatch.delenv("JELES_REMOTE_SECRET", raising=False)


def _stub_local(monkeypatch, results=None, **kw):
    payload = {"query": "q", "sources_queried": ["arxiv", "loc"],
               "total": sum(len(v) for v in (results or {}).values()),
               "results": results or {}}
    payload.update(kw)
    calls = []

    def fake(query, sources=None, limit_per_source=3, **_):
        calls.append({"query": query, "sources": sources,
                      "limit_per_source": limit_per_source})
        if isinstance(payload, Exception):
            raise payload
        return payload

    monkeypatch.setattr(inst.sources, "search", fake)
    return calls


def _stub_remote(monkeypatch, payload, capture=None):
    def fake(req, timeout=None):
        if capture is not None:
            capture["url"] = req.full_url
            capture["headers"] = dict(req.header_items())
            capture["body"] = json.loads(req.data.decode())
        if isinstance(payload, Exception):
            raise payload
        return _Resp(json.dumps(payload).encode())
    monkeypatch.setattr(inst.urllib.request, "urlopen", fake)


# ── Which lane, and can it work ─────────────────────────────────────────────


def test_the_local_lane_needs_no_configuration():
    """The whole point of moving the collections in-package: out of the box,
    with nothing set, the third hop works."""
    info = inst.describe_remote()
    assert info["lane"] == "local"
    assert info["configured"] is True
    assert info["reason"] == ""
    assert len(info["sources"]) >= 50


def test_a_remote_url_with_a_secret_selects_the_remote_lane(monkeypatch):
    monkeypatch.setenv("JELES_REMOTE_URL", "https://remote.example/")
    monkeypatch.setenv("JELES_REMOTE_SECRET", SECRET)
    info = inst.describe_remote()
    assert (info["lane"], info["configured"]) == ("remote", True)
    assert info["base_url"] == "https://remote.example", "trailing slash trimmed"


def test_a_remote_url_without_a_secret_is_a_misconfiguration(monkeypatch):
    """Not "fall back quietly to local" — the operator asked for the remote,
    and a 401 from it would read exactly like an empty shelf."""
    monkeypatch.setenv("JELES_REMOTE_URL", "https://remote.example")
    info = inst.describe_remote()
    assert (info["lane"], info["configured"]) == ("remote", False)
    assert "JELES_REMOTE_SECRET" in info["reason"]
    assert "Unset JELES_REMOTE_URL" in info["reason"], "say how to get back to local"


def test_describe_remote_never_leaks_the_secret(monkeypatch):
    monkeypatch.setenv("JELES_REMOTE_URL", "https://remote.example")
    monkeypatch.setenv("JELES_REMOTE_SECRET", SECRET)
    assert SECRET not in json.dumps(inst.describe_remote())


def test_describe_remote_makes_no_request(monkeypatch):
    def explode(*a, **k):
        raise AssertionError("describe_remote must not touch the network")
    monkeypatch.setattr(inst.urllib.request, "urlopen", explode)
    assert inst.describe_remote()["lane"] == "local"


def test_list_sources_is_local_knowledge(monkeypatch):
    def explode(*a, **k):
        raise AssertionError("listing sources must not touch the network")
    monkeypatch.setattr(inst.urllib.request, "urlopen", explode)

    listed = inst.list_sources()
    assert len(listed) >= 50
    assert set(listed[0]) == {"id", "name", "key_required", "opt_in"}
    assert any(s["key_required"] for s in listed), "some sources need keys"


# ── The local lane ──────────────────────────────────────────────────────────


def test_local_search_runs_in_process(monkeypatch):
    calls = _stub_local(monkeypatch, results={"arxiv": [
        {"title": "Signed policy bundles", "url": "https://arxiv.org/abs/1",
         "source": "arxiv", "institution": "arXiv / Cornell University",
         "snippet": "abstract", "date": "2026-01-01", "id": "1"}]})

    out = inst.search_institutional("policy", sources_filter=["arxiv"],
                                    limit_per_source=2)

    assert out["lane"] == "local"
    assert out["ok"] is True
    assert calls == [{"query": "policy", "sources": ["arxiv"],
                      "limit_per_source": 2}]
    assert out["hits"][0]["source"] == "arXiv / Cornell University"


def test_local_failure_is_reported_not_swallowed(monkeypatch):
    monkeypatch.setattr(inst.sources, "search",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    out = inst.search_institutional("q")
    assert (out["ok"], out["hits"], out["lane"]) == (False, [], "local")
    assert "boom" in out["error"]


def test_an_empty_shelf_is_not_a_failure(monkeypatch):
    _stub_local(monkeypatch, results={})
    out = inst.search_institutional("q")
    assert (out["ok"], out["hits"], out["error"]) == (True, [], "")


def test_grouped_results_are_flattened_with_the_group_kept_as_a_tag(monkeypatch):
    _stub_local(monkeypatch, results={
        "arxiv": [{"title": "A", "url": "https://arxiv.org/abs/1",
                   "institution": "arXiv"}],
        "loc": [{"title": "B", "url": "https://loc.gov/item/2",
                 "institution": "Library of Congress"}],
    })
    out = inst.search_institutional("q")

    assert len(out["hits"]) == 2
    assert out["sources_queried"] == ["arxiv", "loc"]
    by_host = {h["hostname"]: h for h in out["hits"]}
    assert by_host["arxiv.org"]["tags"] == ["arxiv"]
    assert by_host["loc.gov"]["source"] == "Library of Congress"
    assert [h["n"] for h in out["hits"]] == [0, 1]


# ── The remote lane, when opted into ────────────────────────────────────────


def test_remote_request_matches_the_service_contract(monkeypatch):
    monkeypatch.setenv("JELES_REMOTE_URL", "https://remote.example")
    monkeypatch.setenv("JELES_REMOTE_SECRET", SECRET)
    monkeypatch.setattr(inst.sources, "search",
                        lambda *a, **k: pytest.fail("must not fan out locally"))
    cap = {}
    _stub_remote(monkeypatch, {"sources_queried": [], "total": 0, "results": {}},
                 capture=cap)

    inst.search_institutional("q", sources_filter=["arxiv"], limit_per_source=2)

    assert cap["url"] == "https://remote.example/search"
    assert cap["body"] == {"query": "q", "limit_per_source": 2,
                           "sources": ["arxiv"]}
    headers = {k.lower(): v for k, v in cap["headers"].items()}
    # A raw shared secret, not a Bearer token — the service hmac-compares it.
    assert headers["x-jeles-secret"] == SECRET
    assert "authorization" not in headers


def test_remote_omits_sources_when_not_narrowed(monkeypatch):
    monkeypatch.setenv("JELES_REMOTE_URL", "https://remote.example")
    monkeypatch.setenv("JELES_REMOTE_SECRET", SECRET)
    cap = {}
    _stub_remote(monkeypatch, {"results": {}}, capture=cap)
    inst.search_institutional("q")
    assert "sources" not in cap["body"], "omitting it is what asks for everything"


def test_a_misconfigured_remote_never_calls_out(monkeypatch):
    monkeypatch.setenv("JELES_REMOTE_URL", "https://remote.example")

    def explode(*a, **k):
        raise AssertionError("must not call a remote with no secret")
    monkeypatch.setattr(inst.urllib.request, "urlopen", explode)

    out = inst.search_institutional("q")
    assert out["ok"] is False
    assert "JELES_REMOTE_SECRET" in out["error"]


def test_remote_transport_failure_is_reported(monkeypatch):
    monkeypatch.setenv("JELES_REMOTE_URL", "https://remote.example")
    monkeypatch.setenv("JELES_REMOTE_SECRET", SECRET)
    _stub_remote(monkeypatch, OSError("connection refused"))
    out = inst.search_institutional("q")
    assert (out["ok"], out["lane"]) == (False, "remote")
    assert "connection refused" in out["error"]


def test_remote_oversized_response_is_refused(monkeypatch):
    monkeypatch.setenv("JELES_REMOTE_URL", "https://remote.example")
    monkeypatch.setenv("JELES_REMOTE_SECRET", SECRET)
    monkeypatch.setattr(inst, "_MAX_BYTES", 10)
    _stub_remote(monkeypatch, {"results": {"x": [{"title": "a long title"}]}})
    out = inst.search_institutional("q")
    assert out["ok"] is False and "refusing" in out["error"]


def test_non_http_remote_url_is_refused(monkeypatch):
    monkeypatch.setenv("JELES_REMOTE_URL", "file:///etc")
    monkeypatch.setenv("JELES_REMOTE_SECRET", SECRET)
    out = inst.search_institutional("q")
    assert out["ok"] is False
    assert "refusing" in out["error"].lower()


# ── The hit shape ───────────────────────────────────────────────────────────


def test_institutional_hits_get_their_own_confidence_rung():
    """Not `verified` (nobody checked it) and not `unverified` (a named body
    published it). Collapsing it either way discards the point of the hop."""
    hit = inst.to_hit({"title": "t", "url": "https://arxiv.org/abs/1",
                       "institution": "arXiv / Cornell University"})
    assert hit["confidence"] == "institutional"
    assert hit["source_id"] == "institutional"
    assert hit["verification_kind"] == "institutional"
    assert hit["nugget_id"] == "" and hit["verified_by"] == ""


def test_institutional_hits_carry_the_same_keys_as_corpus_hits():
    """The merge contract across all three hops."""
    from jeles import corpus
    hit = inst.to_hit({"title": "t", "url": "https://arxiv.org/abs/1",
                       "institution": "arXiv"})
    nugget = corpus.to_search_hit(
        {"question": "q?", "answer": "a", "sources": ["s"], "verified_by": "human"})
    assert set(hit) == set(nugget)


def test_a_hit_missing_institution_falls_back_to_the_source_id():
    """OpenAlex often has no affiliation. Showing the source id is honest;
    inventing an institution would not be."""
    hit = inst.to_hit({"title": "t", "url": "https://gbif.org/x", "source": "gbif"})
    assert hit["source"] == "gbif"
    assert hit["tags"] == ["gbif"]


def test_a_junk_url_does_not_break_shaping():
    hit = inst.to_hit({"title": "t", "url": "not a url"})
    assert hit["confidence"] == "institutional"


# ── Unreachable is not empty ────────────────────────────────────────────────


def test_all_sources_failing_is_reported_as_a_failure(monkeypatch):
    """Found live: a sandbox blocking egress returned ok=true, total=0 — the
    same lie the web hop used to tell, one level down. If everything we asked
    failed, we did not look."""
    _stub_local(monkeypatch, results={},
                sources_queried=["arxiv", "crossref"],
                failed={"arxiv": "URLError: tunnel 403",
                        "crossref": "URLError: tunnel 403"})
    out = inst.search_institutional("q")

    assert out["ok"] is False
    assert out["failed"] == ["arxiv", "crossref"]
    assert "every source failed (2/2)" in out["error"]
    assert "not an empty result" in out["error"]


def test_a_partial_outage_still_succeeds(monkeypatch):
    """One dead source must not turn a real answer into a failure."""
    _stub_local(monkeypatch,
                results={"loc": [{"title": "t", "url": "https://loc.gov/1",
                                  "institution": "Library of Congress"}]},
                sources_queried=["arxiv", "loc"],
                failed={"arxiv": "URLError: tunnel 403"})
    out = inst.search_institutional("q")

    assert out["ok"] is True
    assert out["failed"] == ["arxiv"], "still reported, so the gap is visible"
    assert len(out["hits"]) == 1
    assert out["error"] == ""


def test_a_genuinely_empty_result_is_not_a_failure(monkeypatch):
    _stub_local(monkeypatch, results={}, sources_queried=["arxiv"], failed={})
    out = inst.search_institutional("q")
    assert (out["ok"], out["failed"], out["error"]) == (True, [], "")
