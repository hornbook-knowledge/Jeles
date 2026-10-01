"""Maintained-client façades for the first connectors adoption slice.

Each ``search_*`` returns the same citation dict shape as ``jeles.sources``
(``title``, ``url``, ``source``, ``institution``, ``snippet``, ``date``, ``id``).
Imports of third-party clients are lazy so this module loads without the
``[connectors]`` extra; a missing client raises ``ImportError`` and the caller
falls back to the urllib twin in ``sources``.

Slice 0 (store ``jeles-adoption-map-2026-09-30``): openalex, crossref, arxiv,
pubmed, internet_archive, musicbrainz, gbif, inaturalist.
"""

from __future__ import annotations

import re

from jeles.sources import _CONTACT_EMAIL, _NCBI_TOOL, _result, _text


def search_openalex(query: str, limit: int = 5) -> list[dict]:
    from pyalex import Works

    Works.email = _CONTACT_EMAIL
    works = Works().search(query).get(per_page=limit)
    results = []
    for item in (works or [])[:limit]:
        doi = item.get("doi") or ""
        results.append(
            _result(
                title=item.get("display_name", ""),
                url=doi if doi else item.get("id", ""),
                source="openalex",
                institution=", ".join(
                    i.get("display_name", "")
                    for a in (item.get("authorships") or [])[:2]
                    for i in (a.get("institutions") or [])[:1]
                ),
                snippet=item.get("abstract", "") or "",
                date=str(item.get("publication_year", "")),
                rid=item.get("id", "").split("/")[-1],
            )
        )
    return results


def search_crossref(query: str, limit: int = 5) -> list[dict]:
    from habanero import Crossref

    cr = Crossref(mailto=_CONTACT_EMAIL)
    data = cr.works(query=query, limit=limit)
    items = ((data or {}).get("message") or {}).get("items") or []
    results = []
    for item in items[:limit]:
        doi = item.get("DOI", "")
        titles = item.get("title") or [""]
        date_parts = (
            (item.get("published") or item.get("issued") or {}).get("date-parts") or [[]]
        )[0]
        date = "-".join(str(p) for p in date_parts) if date_parts else ""
        results.append(
            _result(
                title=titles[0] if titles else "",
                url=f"https://doi.org/{doi}" if doi else "",
                source="crossref",
                institution=item.get("publisher", ""),
                snippet=(item.get("abstract") or "")[:400],
                date=date,
                rid=doi,
            )
        )
    return results


def search_arxiv(query: str, limit: int = 5) -> list[dict]:
    import arxiv

    client = arxiv.Client()
    search = arxiv.Search(
        query=query,
        max_results=limit,
        sort_by=arxiv.SortCriterion.Relevance,
    )
    results = []
    for paper in client.results(search):
        arxiv_id = paper.get_short_id()
        # Match the urllib twin: institution string, full Atom-style published
        # stamp, and let ``_result`` cap the snippet (Loki F2).
        if paper.published is not None:
            published = paper.published
            if published.tzinfo is not None:
                date = published.isoformat().replace("+00:00", "Z")
            else:
                date = published.strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            date = ""
        results.append(
            _result(
                title=(paper.title or "").strip(),
                url=paper.entry_id or "",
                source="arxiv",
                institution="arXiv / Cornell University",
                snippet=(paper.summary or "").strip(),
                date=date,
                rid=arxiv_id,
            )
        )
        if len(results) >= limit:
            break
    return results


def search_pubmed(query: str, limit: int = 5) -> list[dict]:
    from Bio import Entrez

    Entrez.email = _CONTACT_EMAIL
    Entrez.tool = _NCBI_TOOL
    with Entrez.esearch(db="pubmed", term=query, retmax=limit) as handle:
        search = Entrez.read(handle)
    ids = list(search.get("IdList") or [])
    if not ids:
        return []
    with Entrez.esummary(db="pubmed", id=",".join(ids)) as handle:
        summary = Entrez.read(handle)
    results = []
    # Bio.Entrez.esummary may return a list of dicts or a dict keyed by id.
    docs: list[dict] = []
    if isinstance(summary, list):
        docs = [d for d in summary if isinstance(d, dict)]
    elif isinstance(summary, dict):
        for pmid in ids:
            doc = summary.get(pmid)
            if isinstance(doc, dict):
                docs.append(doc)
    for doc in docs[:limit]:
        pmid = str(doc.get("Id") or doc.get("uid") or "")
        if not pmid:
            continue
        authors = doc.get("Authors") or doc.get("authors") or []
        if authors and isinstance(authors[0], dict):
            author_snip = ", ".join(a.get("name", "") for a in authors[:3])
        else:
            author_snip = ", ".join(str(a) for a in authors[:3])
        results.append(
            _result(
                title=doc.get("Title") or doc.get("title") or "",
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                source="pubmed",
                institution="PubMed / National Library of Medicine",
                snippet=author_snip,
                date=doc.get("PubDate") or doc.get("pubdate") or "",
                rid=pmid,
            )
        )
    return results


def search_internet_archive(query: str, limit: int = 5) -> list[dict]:
    import internetarchive as ia

    search = ia.search_items(
        query,
        fields=["identifier", "title", "description", "date", "creator"],
        params={"rows": limit},
    )
    results = []
    for doc in search:
        if len(results) >= limit:
            break
        if not isinstance(doc, dict):
            continue
        identifier = doc.get("identifier", "")
        results.append(
            _result(
                title=_text(doc.get("title", "")),
                url=f"https://archive.org/details/{identifier}" if identifier else "",
                source="internet_archive",
                institution="Internet Archive",
                snippet=_text(doc.get("description", "")),
                date=str(doc.get("date", "")),
                rid=identifier,
            )
        )
    return results


def search_musicbrainz(query: str, limit: int = 5) -> list[dict]:
    import musicbrainzngs

    musicbrainzngs.set_useragent("Jeles", "1.0", _CONTACT_EMAIL)
    q_lower = query.lower()
    use_releases = any(
        w in q_lower for w in ["album", "release", "discography", "ep", "lp", "record"]
    )
    if use_releases:
        artist_name = re.sub(
            r"\b(albums?|discography|ep|lp|records?|singles?|releases?)\b",
            "",
            query,
            flags=re.IGNORECASE,
        ).strip()
        kwargs: dict = {"limit": limit}
        if artist_name:
            kwargs["artist"] = artist_name
        else:
            kwargs["releasegroup"] = query
        if any(w in q_lower for w in ["album", "discography", "lp"]):
            kwargs["primarytype"] = "Album"
        data = musicbrainzngs.search_release_groups(**kwargs)
        results = []
        for item in (data.get("release-group-list") or [])[:limit]:
            artist = ", ".join(
                c.get("artist", {}).get("name", "")
                for c in (item.get("artist-credit") or [])
                if isinstance(c, dict)
            )
            # musicbrainzngs may flatten artist-credit to a string
            if not artist and isinstance(item.get("artist-credit-phrase"), str):
                artist = item["artist-credit-phrase"]
            mbid = item.get("id", "")
            rtype = item.get("type", "") or item.get("primary-type", "")
            results.append(
                _result(
                    title=item.get("title", ""),
                    url=f"https://musicbrainz.org/release-group/{mbid}" if mbid else "",
                    source="musicbrainz",
                    institution="MusicBrainz",
                    snippet=f"{artist} — {rtype}".strip(" —") if (artist or rtype) else "",
                    date=(item.get("first-release-date") or "")[:10],
                    rid=mbid,
                )
            )
        if results:
            return results

    data = musicbrainzngs.search_recordings(query=query, limit=limit)
    results = []
    for item in (data.get("recording-list") or [])[:limit]:
        artist = ", ".join(
            c.get("artist", {}).get("name", "")
            for c in (item.get("artist-credit") or [])
            if isinstance(c, dict)
        )
        if not artist and isinstance(item.get("artist-credit-phrase"), str):
            artist = item["artist-credit-phrase"]
        releases = item.get("release-list") or []
        release_title = releases[0].get("title", "") if releases else ""
        # Match urllib twin: first release date, else recording first-release-date.
        date = (releases[0].get("date", "") if releases else "") or item.get(
            "first-release-date", ""
        )
        mbid = item.get("id", "")
        results.append(
            _result(
                title=item.get("title", ""),
                url=f"https://musicbrainz.org/recording/{mbid}" if mbid else "",
                source="musicbrainz",
                institution="MusicBrainz",
                snippet=f"{artist} — {release_title}".strip(" —")
                if (artist or release_title)
                else "",
                date=date[:10] if date else "",
                rid=mbid,
            )
        )
    return results


def search_gbif(query: str, limit: int = 5) -> list[dict]:
    from pygbif import species

    data = species.name_lookup(q=query, limit=limit) or {}
    results = []
    for item in (data.get("results") or [])[:limit]:
        key = item.get("key") or item.get("nubKey", "")
        sci_name = item.get("scientificName", "")
        canonical = item.get("canonicalName", "")
        rank = item.get("rank", "")
        kingdom = item.get("kingdom", "")
        snippet = f"{rank} — Kingdom: {kingdom}".strip(" —") if (rank or kingdom) else ""
        results.append(
            _result(
                title=sci_name or canonical,
                url=f"https://www.gbif.org/species/{key}" if key else "",
                source="gbif",
                institution="GBIF",
                snippet=snippet,
                date="",
                rid=str(key),
            )
        )
    return results


def search_inaturalist(query: str, limit: int = 5) -> list[dict]:
    from pyinaturalist import get_taxa

    data = get_taxa(q=query, per_page=limit, order_by="observations_count") or {}
    results = []
    for item in (data.get("results") or [])[:limit]:
        taxon_id = item.get("id", "")
        name = item.get("name", "")
        preferred = item.get("preferred_common_name", "")
        rank = item.get("rank", "")
        obs_count = item.get("observations_count", 0)
        title = f"{preferred} ({name})" if preferred else name
        snippet = f"{rank.capitalize()} — {obs_count:,} observations" if rank else ""
        results.append(
            _result(
                title=title,
                url=f"https://www.inaturalist.org/taxa/{taxon_id}" if taxon_id else "",
                source="inaturalist",
                institution="iNaturalist",
                snippet=snippet,
                date="",
                rid=str(taxon_id),
            )
        )
    return results
