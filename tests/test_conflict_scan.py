"""conflict_scan reaction — network-free by construction (injected searcher).

Covers the three disciplines: conflict-biased framing, the two-independent-
source corroboration gate (both sides), and propose-not-execute.
"""
from jeles.reactions import conflict_scan as cs


def _fake_searcher(by_query):
    """Return a searcher that yields canned results per query (dict lookup),
    defaulting to [] for anything not listed. No network, ever."""
    def search(query):
        return by_query.get(query, [])
    return search


def test_frame_queries_is_conflict_biased():
    qs = cs.frame_queries("signed reaction registry")
    assert qs, "a non-empty claim must produce queries"
    # Exactly one mirror/baseline query; the rest hunt conflict.
    mirror = [q for q in qs if "existing implementation" in q]
    conflict = [q for q in qs if any(w in q for w in ("supersedes", "vs ", "criticism"))]
    assert len(mirror) == 1
    assert len(conflict) >= len(mirror), "queries must lean toward conflict, not similarity"
    assert cs.frame_queries("") == []


def test_domain_independence_dedupes_same_site():
    # github.com twice + github.io is two independent domains, not three.
    assert cs._domain("https://github.com/evilmartians/lefthook") == "github.com"
    assert cs._domain("https://www.github.com/aitemr/awesome-git-hooks") == "github.com"
    assert cs._domain("https://foo.github.io/page") == "github.io"
    assert cs._domain("not a url") == ""


def test_two_independent_sources_corroborate_to_a_nugget():
    # Two distinct domains across the query fan-out -> corroborated.
    searcher = _fake_searcher({
        "signed policy registry alternative that supersedes": [
            {"title": "OPA signed bundles", "url": "https://openpolicyagent.org/docs/bundles"},
        ],
        "signed policy registry vs prior art comparison": [
            {"title": "OPA vs Cedar", "url": "https://osohq.com/learn/opa-vs-cedar"},
        ],
    })
    proposals = cs.react({"claim": "signed policy registry", "kind": "post_edit"},
                         searcher=searcher)
    kinds = [p["driver"] for p in proposals]
    assert kinds[0] == "put_nugget", "corroborated conflict is proposed first"
    assert kinds[-1] == "frank_append", "every firing leaves one legible line"
    assert "log_gap" not in kinds
    nugget = proposals[0]["args"]
    assert nugget["verified_by"] == cs.WITNESS
    assert len(nugget["sources"]) == 2
    assert "conflict-scan" in nugget["tags"]


def test_single_source_stays_a_contested_gap():
    # Two hits, one domain -> one witness -> not corroborated -> gap.
    searcher = _fake_searcher({
        "my design existing implementation library": [
            {"title": "a", "url": "https://example.com/a"},
        ],
        "my design alternative that supersedes": [
            {"title": "b", "url": "https://example.com/b"},
        ],
    })
    proposals = cs.react({"claim": "my design"}, searcher=searcher)
    kinds = [p["driver"] for p in proposals]
    assert "put_nugget" not in kinds
    assert kinds[0] == "log_gap"
    assert "1 independent source" in proposals[0]["reason"]


def test_empty_claim_reacts_to_nothing():
    assert cs.react({"claim": "   "}, searcher=_fake_searcher({})) == []


def test_a_failing_query_does_not_sink_the_scan():
    def flaky(query):
        if "supersedes" in query:
            raise RuntimeError("network hiccup")
        return [{"title": "ok", "url": "https://a.org/x"}] if "existing" in query else \
               [{"title": "ok2", "url": "https://b.org/y"}] if "comparison" in query else []
    proposals = cs.react({"claim": "resilient claim"}, searcher=flaky)
    # a.org + b.org still corroborate despite the raised query.
    assert proposals[0]["driver"] == "put_nugget"


def test_propose_not_execute_writes_nothing_until_apply():
    searcher = _fake_searcher({
        "x alternative that supersedes": [{"title": "t", "url": "https://one.com/a"}],
        "x vs prior art comparison": [{"title": "t2", "url": "https://two.com/b"}],
    })
    proposals = cs.react({"claim": "x"}, searcher=searcher)

    calls = {"nuggets": [], "gaps": [], "frank": []}
    receipts = cs.apply(
        proposals,
        put_nugget=lambda **kw: calls["nuggets"].append(kw) or {"id": "n1", "action": "created"},
        log_gap=lambda **kw: calls["gaps"].append(kw) or {"id": "g1"},
        frank=lambda entry: calls["frank"].append(entry) or {"appended": True},
    )
    assert len(calls["nuggets"]) == 1          # corroborated -> one nugget
    assert len(calls["gaps"]) == 0
    assert len(calls["frank"]) == 1            # one legible line
    assert receipts[0]["result"]["action"] == "created"


def test_apply_records_unwired_frank_as_skipped_not_dropped():
    proposals = [{"driver": "frank_append", "args": {"kind": "conflict_scan"}}]
    receipts = cs.apply(proposals, put_nugget=lambda **k: None, log_gap=lambda **k: None)
    assert receipts[0]["result"] == {"skipped": "no frank driver wired"}
