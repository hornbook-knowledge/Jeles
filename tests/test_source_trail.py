"""Properties of `source_trail`, the raw-prose claim verifier.

Two things matter here: that `extract_claims` degrades to "no claims" rather
than raising when the injected model call misbehaves, and that `verify_claim`
picks the single *highest-confidence* hit rather than the first or the last
one `sources.search` happens to hand back. Everything else is bookkeeping
around those two behaviors.

Offline throughout: `sources.route_sources` and `sources.search` are
monkeypatched directly, so no test here reaches `jeles._egress` or the network
`jeles.sources` would otherwise use.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

from jeles import source_trail
from jeles.source_trail import PRESS_SOURCES, extract_claims, verify_claim, verify_text


def _stub(text):
    """An `llm_respond` that always answers with `text`."""
    return lambda system, history, user: text


def _raising(exc):
    def _fn(system, history, user):
        raise exc
    return _fn


# ── extract_claims ───────────────────────────────────────────────────────────


def test_extract_claims_splits_on_lines_and_strips_them():
    out = extract_claims("irrelevant", _stub("  claim one  \nclaim two\n\n"))
    assert out == ["claim one", "claim two"]


def test_extract_claims_caps_at_ten():
    lines = "\n".join(f"claim {i}" for i in range(15))
    out = extract_claims("irrelevant", _stub(lines))
    assert len(out) == 10
    assert out[0] == "claim 0"
    assert out[-1] == "claim 9"


def test_extract_claims_drops_blank_lines():
    out = extract_claims("irrelevant", _stub("claim one\n\n   \nclaim two"))
    assert out == ["claim one", "claim two"]


def test_extract_claims_truncates_input_to_4000_chars():
    seen = {}

    def _capture(system, history, user):
        seen["len"] = len(user)
        return "a claim"

    extract_claims("x" * 10_000, _capture)
    assert seen["len"] == 4000


def test_extract_claims_swallows_llm_errors_and_returns_empty_list():
    """A model outage degrades to 'no claims found', not an exception out of
    a pipeline that called this expecting a list."""
    out = extract_claims("irrelevant", _raising(RuntimeError("no groq key")))
    assert out == []


# ── verify_claim ─────────────────────────────────────────────────────────────


def test_verify_claim_matched_false_when_nothing_comes_back(monkeypatch):
    monkeypatch.setattr(source_trail._sources, "route_sources", lambda q: ["openalex"])
    monkeypatch.setattr(source_trail._sources, "search",
                         lambda q, s, limit: {"results": {}})
    out = verify_claim("a claim nobody indexed")
    assert out == {
        "claim": "a claim nobody indexed", "matched": False,
        "title": "", "url": "", "date": "", "source": "", "institution": "",
        "tier": "", "confidence": 0.0,
    }


def test_verify_claim_picks_the_highest_confidence_hit_not_the_first(monkeypatch):
    """`zenodo` (0.65) is listed before `pubmed` (0.90) in the fan-out here —
    if this picked the first source with a hit rather than ranking by
    confidence, the low-confidence deposit would win."""
    monkeypatch.setattr(source_trail._sources, "route_sources", lambda q: ["zenodo", "pubmed"])

    def _fake_search(query, s, limit):
        return {"results": {
            "zenodo": [{"title": "A preprint", "url": "https://zenodo.org/x",
                        "institution": "Zenodo / CERN"}],
            "pubmed": [{"title": "A peer-reviewed paper", "url": "https://pubmed/y",
                        "institution": "PubMed / NLM"}],
        }}

    monkeypatch.setattr(source_trail._sources, "search", _fake_search)
    out = verify_claim("some claim")
    assert out["matched"] is True
    assert out["source"] == "pubmed"
    assert out["confidence"] == pytest.approx(0.90)
    assert out["tier"] == "academic"


def test_verify_claim_tags_a_press_source_as_press_not_academic(monkeypatch):
    monkeypatch.setattr(source_trail._sources, "route_sources", lambda q: ["psychiatric_times"])
    monkeypatch.setattr(
        source_trail._sources, "search",
        lambda q, s, limit: {"results": {
            "psychiatric_times": [{"title": "An article", "url": "https://pt/x",
                                    "institution": "Psychiatric Times"}],
        }},
    )
    out = verify_claim("a psychiatry claim")
    assert out["tier"] == "press"
    assert out["source"] == "psychiatric_times"


def test_verify_claim_auto_routes_when_no_sources_given(monkeypatch):
    calls = []
    monkeypatch.setattr(source_trail._sources, "route_sources",
                         lambda q: calls.append(q) or ["arxiv"])
    monkeypatch.setattr(source_trail._sources, "search",
                         lambda q, s, limit: {"results": {}})
    verify_claim("route me")
    assert calls == ["route me"]


def test_verify_claim_skips_routing_when_sources_are_given_explicitly(monkeypatch):
    routed = []
    searched = []
    monkeypatch.setattr(source_trail._sources, "route_sources",
                         lambda q: routed.append(q) or ["should-not-be-used"])
    monkeypatch.setattr(source_trail._sources, "search",
                         lambda q, s, limit: searched.append(s) or {"results": {}})
    verify_claim("a claim", sources=["pubmed", "arxiv"])
    assert routed == []
    assert searched == [["pubmed", "arxiv"]]


def test_verify_claim_falls_back_to_070_confidence_for_an_unranked_source(monkeypatch):
    monkeypatch.setattr(source_trail._sources, "route_sources", lambda q: ["mystery_source"])
    monkeypatch.setattr(
        source_trail._sources, "search",
        lambda q, s, limit: {"results": {
            "mystery_source": [{"title": "t", "url": "u", "institution": "i"}],
        }},
    )
    out = verify_claim("obscure claim")
    assert out["confidence"] == pytest.approx(0.70)


def test_verify_claim_passes_limit_through_to_search(monkeypatch):
    seen = {}

    def _fake_search(query, s, limit):
        seen["limit"] = limit
        return {"results": {}}

    monkeypatch.setattr(source_trail._sources, "route_sources", lambda q: ["pubmed"])
    monkeypatch.setattr(source_trail._sources, "search", _fake_search)
    verify_claim("a claim", limit=5)
    assert seen["limit"] == 5


# ── verify_text ──────────────────────────────────────────────────────────────


def test_verify_text_short_circuits_when_no_claims_are_found():
    out = verify_text("no verifiable content here", _stub(""))
    assert out == {"claims": [], "total": 0, "matched": 0,
                    "note": "No verifiable claims found."}


def test_verify_text_verifies_each_extracted_claim_and_counts_matches(monkeypatch):
    monkeypatch.setattr(source_trail._sources, "route_sources", lambda q: ["pubmed"])

    def _fake_search(query, s, limit):
        if "first" in query:
            return {"results": {"pubmed": [{"title": "t", "url": "u", "institution": "i"}]}}
        return {"results": {}}

    monkeypatch.setattr(source_trail._sources, "search", _fake_search)
    out = verify_text("irrelevant", _stub("first claim\nsecond claim"))
    assert out["total"] == 2
    assert out["matched"] == 1
    assert [c["claim"] for c in out["claims"]] == ["first claim", "second claim"]
    assert out["claims"][0]["matched"] is True
    assert out["claims"][1]["matched"] is False


def test_verify_text_forwards_sources_and_limit_to_verify_claim(monkeypatch):
    seen = []
    monkeypatch.setattr(source_trail._sources, "route_sources",
                         lambda q: (_ for _ in ()).throw(AssertionError("should not route")))
    monkeypatch.setattr(source_trail._sources, "search",
                         lambda q, s, limit: seen.append((s, limit)) or {"results": {}})
    verify_text("irrelevant", _stub("only claim"), sources=["arxiv"], limit=7)
    assert seen == [(["arxiv"], 7)]


# ── PRESS_SOURCES ────────────────────────────────────────────────────────────


def test_press_sources_is_disjoint_from_nothing_academic_by_construction():
    """Every registered source not in PRESS_SOURCES reads as academic — this
    just pins that the set is non-empty and contains the sources the module
    docstring names."""
    assert {"psychiatric_times", "fbi_vault", "ig_nobel"} <= PRESS_SOURCES


# ── import purity ────────────────────────────────────────────────────────────


def test_importing_source_trail_pulls_in_no_third_party_or_mcp_modules():
    """`source_trail` itself never opens a socket or talks to a model, and
    imports nothing beyond the stdlib and `jeles.sources`. `jeles.sources`
    does import `urllib.request`/`socket`/`ssl` at module level — that is a
    stdlib import, not an egress, and is exactly what `jeles.sources`' own
    purity story already covers; asserting their *absence* here would just
    fail on jeles.sources' legitimate shape. What matters for this module's
    own zero-dependency promise is that nothing third-party or MCP-flavored
    rides along. Run in a subprocess so a prior import in this session's
    interpreter can't mask a real regression."""
    probe = textwrap.dedent(
        """
        import sys
        import jeles.source_trail  # noqa: F401

        forbidden = {
            "requests", "httpx", "httpcore", "aiohttp",
            "mcp", "mcp.server", "mcp.client", "anyio",
        }
        loaded = forbidden & set(sys.modules)
        if loaded:
            print(",".join(sorted(loaded)))
            sys.exit(1)
        sys.exit(0)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "jeles.source_trail imported third-party/MCP modules at import time: "
        f"{result.stdout.strip()!r} (stderr: {result.stderr.strip()!r})"
    )


def test_source_trail_declares_the_documented_public_api():
    assert source_trail.__all__ == [
        "PRESS_SOURCES", "extract_claims", "verify_claim", "verify_text",
    ]
