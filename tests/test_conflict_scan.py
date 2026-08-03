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
            {"title": "OPA signed bundles",
             "url": "https://openpolicyagent.org/docs/bundles",
             "snippet": "Bundles can be signed; the registry serves policy."},
        ],
        "signed policy registry vs prior art comparison": [
            {"title": "OPA vs Cedar", "url": "https://osohq.com/learn/opa-vs-cedar",
             "snippet": "Comparing signed policy distribution and registry design."},
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
            {"title": "A prior design", "url": "https://example.com/a",
             "snippet": "an earlier design of the same shape"},
        ],
        "my design alternative that supersedes": [
            {"title": "Another design", "url": "https://example.com/b",
             "snippet": "a competing design"},
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
        hit_a = {"title": "A resilient claim", "url": "https://a.org/x",
                 "snippet": "prior work on the resilient claim"}
        hit_b = {"title": "Resilient claim, revisited", "url": "https://b.org/y",
                 "snippet": "supersedes the resilient claim"}
        return [hit_a] if "existing" in query else \
               [hit_b] if "comparison" in query else []
    proposals = cs.react({"claim": "resilient claim"}, searcher=flaky)
    # a.org + b.org still corroborate despite the raised query.
    assert proposals[0]["driver"] == "put_nugget"


def test_propose_not_execute_writes_nothing_until_apply():
    searcher = _fake_searcher({
        "widget cache alternative that supersedes": [
            {"title": "Widget cache, prior art", "url": "https://one.com/a",
             "snippet": "an existing widget cache"}],
        "widget cache vs prior art comparison": [
            {"title": "Comparing widget caches", "url": "https://two.com/b",
             "snippet": "widget cache designs compared"}],
    })
    proposals = cs.react({"claim": "widget cache"}, searcher=searcher)

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


# ── A witness must be a witness ─────────────────────────────────────────────
#
# The old gate counted every returned domain. Nothing checked that a hit
# refuted, superseded, or even mentioned the claim — so any two results from
# any two sites promoted a machine-verified "prior work exists" nugget. Each
# case below was verified producing put_nugget before the fix.

_INVENTED = "a totally novel signed reaction registry nobody has built"


def _drivers(searcher, claim=_INVENTED):
    return [p["driver"] for p in cs.react({"claim": claim}, searcher=searcher)]


def test_a_search_engine_is_not_a_source_about_itself():
    """The one that mattered: DuckDuckGo's Instant-Answer endpoint — the
    zero-config default backend — returns its RelatedTopics as duckduckgo.com
    URLs. Paired with the single Wikipedia AbstractURL that cleared a two-source
    bar for any claim whatsoever."""
    ddg_shaped = lambda q: [  # noqa: E731
        {"title": "Policy", "url": "https://en.wikipedia.org/wiki/Policy",
         "snippet": "A policy is a deliberate system of principles."},
        {"title": "Registry", "url": "https://duckduckgo.com/Registry",
         "snippet": "A registry is a collection of records."},
    ]
    assert "put_nugget" not in _drivers(ddg_shaped)
    assert "log_gap" in _drivers(ddg_shaped)


def test_two_url_shorteners_are_not_two_sources():
    """Opaque, and both can point at the same page — the exact opposite of the
    independence the rule is trying to establish."""
    shortened = lambda q: [  # noqa: E731
        {"title": "Signed reaction registry", "url": "https://bit.ly/3xYz",
         "snippet": "a signed reaction registry"},
        {"title": "Signed reaction registry", "url": "https://t.co/abc",
         "snippet": "a signed reaction registry"},
    ]
    assert "put_nugget" not in _drivers(shortened)


def test_address_literals_witness_nothing():
    """`_domain` used to keep the last two labels of anything dotted, so
    93.184.216.34 and .99 read as two independent sources, while 1.2.3.4 and
    9.9.3.4 both collapsed to "3.4". Neither reading is defensible."""
    assert cs._domain("http://93.184.216.34/a") == ""
    assert cs._domain("http://1.2.3.4/x") == ""
    ips = lambda q: [  # noqa: E731
        {"title": "signed reaction registry", "url": "http://93.184.216.34/a",
         "snippet": "signed reaction registry"},
        {"title": "signed reaction registry", "url": "http://93.184.216.99/b",
         "snippet": "signed reaction registry"},
    ]
    assert "put_nugget" not in _drivers(ips)


def test_relevant_looking_domains_still_need_to_mention_the_claim():
    """Two real, distinct, reputable sites — about nothing to do with it."""
    off_topic = lambda q: [  # noqa: E731
        {"title": "Cake recipes", "url": "https://allrecipes.com/x",
         "snippet": "flour, sugar, butter"},
        {"title": "Weather", "url": "https://bbc.co.uk/weather",
         "snippet": "rain tomorrow"},
    ]
    assert "put_nugget" not in _drivers(off_topic)


def test_genuine_prior_art_still_corroborates():
    """The gate must not buy correctness with uselessness."""
    genuine = lambda q: [  # noqa: E731
        {"title": "Signed policy bundles in OPA",
         "url": "https://openpolicyagent.org/docs",
         "snippet": "a signed registry of reaction bundles"},
        {"title": "Cedar signed registry", "url": "https://cedarpolicy.com/x",
         "snippet": "a signed reaction registry design"},
    ]
    assert "put_nugget" in _drivers(genuine)


def test_a_relevant_page_sharing_no_vocabulary_is_not_counted():
    """A deliberate, documented false negative.

    A page that is genuinely about the claim but shares no content word with it
    cannot be distinguished — from title, snippet and URL alone — from a page
    about something else. So it is not counted, and the scan reports a contested
    gap instead of prior art.

    The failure directions are not symmetric: refusing a real witness costs a
    gap that asks a human to look, while accepting a false one writes a nugget
    asserting prior art that does not exist. This test exists so the cost is a
    decision on the record rather than a surprise.
    """
    oblique = lambda q: [  # noqa: E731
        {"title": "Ledger of attested handlers", "url": "https://one.example/a",
         "snippet": "an append-only ledger of attested handlers"},
        {"title": "Verified dispatch table", "url": "https://two.example/b",
         "snippet": "a verified dispatch table"},
    ]
    assert "put_nugget" not in _drivers(oblique)
    assert "log_gap" in _drivers(oblique)


def test_a_claim_with_no_content_words_cannot_corroborate():
    """Relevance is measured against the claim's content words. With none,
    nothing can be shown relevant to it, so nothing corroborates."""
    anything = lambda q: [  # noqa: E731
        {"title": "Something", "url": "https://a.org/x", "snippet": "text"},
        {"title": "Else", "url": "https://b.org/y", "snippet": "more text"},
    ]
    assert "put_nugget" not in _drivers(anything, claim="a b c")


def test_sources_are_exactly_the_witnesses():
    """A human re-verifying "the sources" must see what actually cleared the
    bar — not every URL the search returned."""
    mixed = lambda q: [  # noqa: E731
        {"title": "Signed reaction registry", "url": "https://real.org/a",
         "snippet": "a signed reaction registry"},
        {"title": "Registry", "url": "https://duckduckgo.com/Registry",
         "snippet": "a signed reaction registry"},
        {"title": "Cake", "url": "https://allrecipes.com/x", "snippet": "flour"},
        {"title": "Signed reaction registry", "url": "https://other.org/b",
         "snippet": "a signed reaction registry"},
    ]
    proposals = cs.react({"claim": _INVENTED}, searcher=mixed)
    nugget = [p for p in proposals if p["driver"] == "put_nugget"][0]["args"]
    assert sorted(nugget["sources"]) == ["https://other.org/b", "https://real.org/a"]
