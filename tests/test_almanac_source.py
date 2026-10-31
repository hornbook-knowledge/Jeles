"""`search_almanac` reads the Almanac's published catalogs and matches locally.

There is no search API on the other side — each vertical is a git repository
that publishes a generated `catalog.json` — so the behaviour worth pinning is
all on this side: which entries match, where a hit points, what is left out,
and that one unreachable vertical narrows the search instead of sinking it.
"""

from __future__ import annotations

import pytest

from jeles import sources


def _entry(eid, title, *, topics=(), publisher="Agency", description="", status="live"):
    return {
        "id": eid,
        "title": title,
        "topics": list(topics),
        "publisher": publisher,
        "description": description,
        "status": status,
        "license": "CC-BY-4.0",
        "source": {"canonical_url": f"https://publisher.example/{eid}"},
        "observed": {"checked": "2026-10-31"},
    }


_CATALOGS = {
    "education-almanac": [
        _entry(
            "peru-minedu-escale",
            "ESCALE — Peru Ministry of Education Statistics",
            topics=["education-census", "school-registry", "peru"],
            publisher="Ministerio de Educación del Perú (MINEDU)",
            description="The annual Censo Educativo databases and school registry.",
        ),
        _entry(
            "gone-dataset",
            "Peru school enrollment archive",
            topics=["peru", "enrollment"],
            status="dark",
        ),
    ],
    "energy-almanac": [
        _entry(
            "eia-open-data",
            "EIA Open Data",
            topics=["electricity", "petroleum"],
            publisher="U.S. Energy Information Administration (EIA)",
            description="Programmatic access to published energy statistics.",
        ),
    ],
}


@pytest.fixture
def catalogs(monkeypatch):
    """Serve `_CATALOGS` in place of the network and count every fetch."""
    calls: list[str] = []

    def fake_get(url, headers=None, timeout=None):
        calls.append(url)
        for vertical, entries in _CATALOGS.items():
            if f"/almanac-data/{vertical}/main/catalog.json" in url:
                return {"name": vertical, "count": len(entries), "entries": entries}
        return None  # every other vertical is unreachable

    monkeypatch.setattr(sources, "_get", fake_get)
    monkeypatch.setattr(sources, "_ALMANAC_CACHE", {})
    return calls


def test_a_hit_points_at_the_publisher_and_names_it(catalogs):
    [hit] = sources.search_almanac("Peru school census")
    assert hit["url"] == "https://publisher.example/peru-minedu-escale"
    assert hit["institution"] == "Ministerio de Educación del Perú (MINEDU)"
    assert hit["source"] == "almanac"
    assert hit["id"] == "education-almanac/peru-minedu-escale"
    assert hit["snippet"].startswith("education-almanac · live · CC-BY-4.0 — ")
    assert hit["date"] == "2026-10-31"


def test_dark_entries_are_not_cited(catalogs):
    ids = [h["id"] for h in sources.search_almanac("Peru enrollment")]
    assert "education-almanac/gone-dataset" not in ids


def test_matching_is_on_whole_words_not_substrings(catalogs):
    # "lect" is inside "electricity"; a substring match would return EIA.
    assert sources.search_almanac("lect") == []


def test_stopwords_alone_match_nothing(catalogs):
    assert sources.search_almanac("open data statistics") == []
    assert catalogs == []  # nothing to match, so nothing was fetched


def test_an_unreachable_vertical_narrows_the_search_instead_of_failing_it(catalogs):
    [hit] = sources.search_almanac("electricity petroleum")
    assert hit["id"] == "energy-almanac/eia-open-data"


def test_catalogs_are_fetched_once_per_ttl(catalogs):
    sources.search_almanac("electricity")
    first = len(catalogs)
    sources.search_almanac("petroleum")
    # The two reachable verticals are cached; the nine failures are retried.
    assert len(catalogs) - first == len(sources.ALMANAC_VERTICALS) - len(_CATALOGS)


def test_every_vertical_is_requested_over_https_from_the_declared_host(catalogs):
    sources.search_almanac("electricity")
    assert sorted(catalogs) == sorted(
        f"https://raw.githubusercontent.com/almanac-data/{v}/main/catalog.json"
        for v in sources.ALMANAC_VERTICALS
    )
    assert sources.SOURCES["almanac"]["hosts"] == ["raw.githubusercontent.com"]


def test_when_no_catalog_loads_the_fan_out_sees_a_failure_not_an_empty_shelf(monkeypatch):
    monkeypatch.setattr(sources, "_ALMANAC_CACHE", {})

    def refuse(req, timeout=None):
        raise OSError("Tunnel connection failed: 403 Forbidden")

    monkeypatch.setattr(sources.urllib.request, "urlopen", refuse)
    out = sources.search("electricity", sources=["almanac"])
    assert "almanac" in out["failed"]
    assert "almanac" not in out["results"]
