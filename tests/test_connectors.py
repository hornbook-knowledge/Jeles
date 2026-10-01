"""Connectors extra: optional clients preferred over urllib twins."""

from __future__ import annotations

import subprocess
import sys
import textwrap
import types

from jeles import sources


def test_via_connector_prefers_client_when_present(monkeypatch):
    canned = [
        sources._result(
            title="from-connector",
            url="https://example.org/1",
            source="openalex",
            institution="Test U",
        )
    ]

    monkeypatch.setattr(
        sources,
        "_via_connector",
        lambda name, query, limit: canned if name == "openalex" else None,
    )

    def boom(*_a, **_k):
        raise AssertionError("urllib twin must not run when connector returns a list")

    monkeypatch.setattr(sources, "_get", boom)
    out = sources.search_openalex("q", limit=1)
    assert out == canned


def test_via_connector_empty_list_is_not_a_fallback(monkeypatch):
    monkeypatch.setattr(sources, "_via_connector", lambda *_a, **_k: [])

    def boom(*_a, **_k):
        raise AssertionError("empty connector answer must not fall through to urllib")

    monkeypatch.setattr(sources, "_get", boom)
    assert sources.search_crossref("q", limit=1) == []


def test_via_connector_none_uses_urllib_twin(monkeypatch):
    monkeypatch.setattr(sources, "_via_connector", lambda *_a, **_k: None)
    monkeypatch.setattr(
        sources,
        "_get",
        lambda *_a, **_k: {
            "results": [
                {
                    "display_name": "urllib-hit",
                    "doi": "https://doi.org/10.1/x",
                    "id": "https://openalex.org/W1",
                    "authorships": [],
                    "abstract": "",
                    "publication_year": 2024,
                }
            ]
        },
    )
    out = sources.search_openalex("q", limit=1)
    assert len(out) == 1
    assert out[0]["title"] == "urllib-hit"
    assert out[0]["source"] == "openalex"


def test_via_connector_exception_falls_back(monkeypatch):
    def raise_then_none(name, query, limit):
        # Simulate get_search present but client blowing up → helper returns None.
        return None

    monkeypatch.setattr(sources, "_via_connector", raise_then_none)
    monkeypatch.setattr(sources, "_get", lambda *_a, **_k: {"results": []})
    assert sources.search_gbif("q", limit=1) == []


def test_connector_failure_inside_helper_falls_back(monkeypatch):
    def boom(_q, _n):
        raise RuntimeError("client down")

    monkeypatch.setattr(
        "jeles.connectors.get_search",
        lambda name: boom if name == "inaturalist" else None,
    )
    monkeypatch.setattr(
        sources,
        "_get",
        lambda *_a, **_k: {
            "results": [
                {
                    "id": 1,
                    "name": "Canis lupus",
                    "preferred_common_name": "Wolf",
                    "rank": "species",
                    "observations_count": 10,
                }
            ]
        },
    )
    out = sources.search_inaturalist("wolf", limit=1)
    assert out and out[0]["source"] == "inaturalist"


def test_arxiv_empty_tokens_skips_connector_and_network(monkeypatch):
    called = []

    def track(*_a, **_k):
        called.append(True)
        return [{"title": "should-not"}]

    monkeypatch.setattr(sources, "_via_connector", track)
    monkeypatch.setattr(sources, "_fetch", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError))
    assert sources.search_arxiv("   ", limit=1) == []
    assert called == []


_SLICE0_CONNECTOR_NAMES = (
    "openalex",
    "crossref",
    "arxiv",
    "pubmed",
    "internet_archive",
    "musicbrainz",
    "gbif",
    "inaturalist",
)


def _slice0_names_missing_via_connector(text: str) -> list[str]:
    """Names whose search_* never call `_via_connector("<name>"` in sources.py."""
    return [name for name in _SLICE0_CONNECTOR_NAMES if f'_via_connector("{name}"' not in text]


def test_slice0_names_are_wired():
    """Every slice-0 source must consult `_via_connector`."""
    from pathlib import Path

    missing = _slice0_names_missing_via_connector(
        Path(sources.__file__).read_text(encoding="utf-8")
    )
    assert missing == [], f"search_* missing connector hook: {missing}"


def test_a_missing_via_connector_hook_is_caught():
    """Plant: strip one hook and prove the scan fires."""
    from pathlib import Path

    real = Path(sources.__file__).read_text(encoding="utf-8")
    planted = real.replace('_via_connector("openalex"', '_via_connector_GONE("openalex"', 1)
    assert planted != real
    assert _slice0_names_missing_via_connector(planted) == ["openalex"]


def test_connectors_extra_declared():
    try:
        import tomllib
    except ModuleNotFoundError:  # py310
        import tomli as tomllib  # type: ignore

    from pathlib import Path

    data = tomllib.loads(Path(sources.__file__).parents[1].joinpath("pyproject.toml").read_text())
    extras = data["project"]["optional-dependencies"]
    assert "connectors" in extras
    joined = " ".join(extras["connectors"]).lower()
    for pkg in (
        "pyalex",
        "habanero",
        "arxiv",
        "biopython",
        "internetarchive",
        "musicbrainzngs",
        "pygbif",
        "pyinaturalist",
    ):
        assert pkg in joined


def test_importing_sources_does_not_load_third_party_clients():
    """Base seat must stay stdlib: connectors clients stay out of import graph."""
    probe = textwrap.dedent(
        """
        import sys
        import jeles.sources  # noqa: F401

        forbidden = {
            "pyalex",
            "habanero",
            "arxiv",
            "Bio",
            "internetarchive",
            "musicbrainzngs",
            "pygbif",
            "pyinaturalist",
            "requests",
            "httpx",
        }
        loaded = forbidden & set(sys.modules)
        # connectors package itself must not load either — sources only
        # reaches for it inside `_via_connector` on a call.
        if "jeles.connectors" in sys.modules or "jeles.connectors.scholarly" in sys.modules:
            loaded = loaded | {"jeles.connectors"}
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
        "jeles.sources imported connector clients at import time: "
        f"{result.stdout.strip()!r} (stderr: {result.stderr.strip()!r})"
    )


def test_get_search_returns_callable_for_slice0():
    from jeles.connectors import get_search

    for name in (
        "openalex",
        "crossref",
        "arxiv",
        "pubmed",
        "internet_archive",
        "musicbrainz",
        "gbif",
        "inaturalist",
    ):
        assert callable(get_search(name)), name
    assert get_search("not_a_source") is None


def test_scholarly_openalex_maps_pyalex_shape(monkeypatch):
    from jeles.connectors import scholarly

    class _Works:
        email = None

        def search(self, _q):
            return self

        def get(self, per_page=5):
            return [
                {
                    "display_name": "Paper",
                    "doi": "https://doi.org/10.1/y",
                    "id": "https://openalex.org/W99",
                    "authorships": [
                        {"institutions": [{"display_name": "MIT"}]},
                    ],
                    "abstract": "abs",
                    "publication_year": 2020,
                }
            ][:per_page]

    fake = types.ModuleType("pyalex")
    fake.Works = _Works
    monkeypatch.setitem(sys.modules, "pyalex", fake)
    out = scholarly.search_openalex("q", limit=1)
    assert out[0]["title"] == "Paper"
    assert out[0]["source"] == "openalex"
    assert "MIT" in out[0]["institution"]
    assert out[0]["id"] == "W99"


def test_scholarly_arxiv_matches_urllib_twin_fields(monkeypatch):
    from datetime import datetime, timezone

    from jeles.connectors import scholarly

    class _Paper:
        title = "Twin Fields"
        entry_id = "http://arxiv.org/abs/1234.5678"
        summary = "x" * 500
        published = datetime(2014, 11, 17, 0, 0, 0, tzinfo=timezone.utc)

        def get_short_id(self):
            return "1234.5678"

    class _Client:
        def results(self, _search):
            yield _Paper()

    class _Search:
        def __init__(self, **_k):
            pass

    class _Sort:
        Relevance = "relevance"

    fake = types.ModuleType("arxiv")
    fake.Client = _Client
    fake.Search = _Search
    fake.SortCriterion = _Sort
    monkeypatch.setitem(sys.modules, "arxiv", fake)
    out = scholarly.search_arxiv("machine learning", limit=1)
    assert out[0]["institution"] == "arXiv / Cornell University"
    assert out[0]["date"] == "2014-11-17T00:00:00Z"
    assert len(out[0]["snippet"]) == 400  # _result caps; full summary was passed in


def test_scholarly_musicbrainz_recording_carries_release_date(monkeypatch):
    from jeles.connectors import scholarly

    def search_recordings(**_k):
        return {
            "recording-list": [
                {
                    "id": "rec-1",
                    "title": "Song",
                    "artist-credit-phrase": "Band",
                    "release-list": [{"title": "Album", "date": "1999-05-01"}],
                }
            ]
        }

    fake = types.ModuleType("musicbrainzngs")
    fake.set_useragent = lambda *_a, **_k: None
    fake.search_recordings = search_recordings
    monkeypatch.setitem(sys.modules, "musicbrainzngs", fake)
    out = scholarly.search_musicbrainz("Song by Band", limit=1)
    assert out[0]["date"] == "1999-05-01"
    assert out[0]["source"] == "musicbrainz"


def test_connectors_module_documents_egress_bypass():
    import jeles.connectors as cx

    assert "_egress" in (cx.__doc__ or "")
    assert "bypass" in (cx.__doc__ or "").lower() or "not" in (cx.__doc__ or "").lower()
