"""institutional — the third hop: named institutional and academic sources.

The persona's mandate is "local KB → open web → special collections". The
corpus is the first hop and `reactions.search_adapter` is the second; this is
the third, and it is a genuinely different tier rather than more web.

A `jeles-remote` deployment (FastAPI on Fly.io, `rudi193-cmd/jeles-remote`)
fans one query out across ~65 registered sources — arXiv, PubMed, Crossref,
OpenAlex, Library of Congress, Europeana, CourtListener, the Smithsonian — and
returns citable results. Every hit names the body that published it, which is
the whole point: an arXiv paper is not "a page on the internet", and the
librarian's no-unsourced-output rule needs that distinction to survive into the
data.

Design, matching the rest of the package:

* **Stdlib only.** urllib.request and json. Importing this module opens no
  socket; the network happens only when a function is called.
* **Legible failure, like `search_adapter`.** `search_institutional` returns
  ``{hits, ok, ...}`` so "the collections had nothing" and "we never reached
  them" stay distinguishable. `describe_remote` answers "can this work?"
  without making a request.
* **The perimeter is the operator's choice.** This does raw egress (through
  ``HTTPS_PROXY`` if set), exactly as `search_adapter` does. In a gated
  deployment, route through willow-mcp's `JelesAdapter` instead — the same
  service, reached through the three-key egress gate. That adapter already
  exists; this module is the ungated lane and says so.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any
from urllib.parse import urlparse

log = logging.getLogger("jeles.institutional")

DEFAULT_BASE_URL = "https://jeles-remote.fly.dev"
_TIMEOUT = float(os.environ.get("JELES_REMOTE_TIMEOUT", "30"))
# jeles-remote fans out to dozens of sources concurrently and can legitimately
# return a large body; cap it anyway, since this is untrusted input like any
# other network response.
_MAX_BYTES = int(os.environ.get("JELES_REMOTE_MAX_BYTES", str(8 * 1024 * 1024)))
_UA = "jeles/institutional (+https://github.com/rudi193-cmd/Jeles)"


def _base_url() -> str:
    return os.environ.get("JELES_REMOTE_URL", DEFAULT_BASE_URL).rstrip("/")


def describe_remote() -> dict[str, Any]:
    """Report whether the institutional hop can work, without asking the network.

    Returns ``{base_url, configured, requires, reason}``. ``reason`` is empty
    when a secret is present. The secret is never included — only whether one
    was found.
    """
    base = _base_url()
    secret = os.environ.get("JELES_REMOTE_SECRET", "").strip()
    if not secret:
        return {
            "base_url": base, "configured": False,
            "requires": "JELES_REMOTE_SECRET",
            "reason": ("JELES_REMOTE_SECRET is not set, so every institutional "
                       "search is refused with 401 — which is indistinguishable "
                       "from the collections having nothing"),
        }
    return {"base_url": base, "configured": True,
            "requires": "JELES_REMOTE_SECRET", "reason": ""}


def _post(url: str, payload: dict, secret: str) -> Any:
    if not url.startswith(("https://", "http://")):
        raise ValueError(f"refusing non-HTTP(S) URL scheme: {url!r}")
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={
            "User-Agent": _UA,
            "Content-Type": "application/json",
            # A raw shared secret, not a Bearer token — jeles-remote
            # hmac-compares it (main.py `_verify_secret`).
            "X-Jeles-Secret": secret,
        },
    )
    # Scheme is guarded above (fail-closed); urlopen honors HTTPS_PROXY.
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # nosec B310
        raw = resp.read(_MAX_BYTES + 1)
        if len(raw) > _MAX_BYTES:
            raise ValueError(f"response exceeds {_MAX_BYTES} bytes — refusing")
        return json.loads(raw.decode("utf-8", "replace"))


def to_hit(raw: dict[str, Any], idx: int = 0) -> dict[str, Any]:
    """Shape one jeles-remote result like `corpus.to_search_hit` shapes a
    nugget, so all three hops merge into one ranked list without translation.

    `confidence` is ``"institutional"`` — deliberately its own rung between a
    corpus nugget's ``"verified"``/``"corroborated"`` and the open web's
    ``"unverified"``. A Library of Congress record is not a human-checked
    nugget and is not a random page; flattening it into either would throw away
    the only thing this hop is for.
    """
    url = str(raw.get("url") or "")
    try:
        host = urlparse(url).netloc or "institutional"
    except ValueError:
        host = "institutional"
    institution = str(raw.get("institution") or raw.get("source") or "").strip()
    return {
        "title": raw.get("title") or "",
        "url": url,
        "snippet": raw.get("snippet") or "",
        "source": institution or "Institutional source",
        "date": raw.get("date") or "",
        "source_id": "institutional",
        "hostname": host,
        "confidence": "institutional",
        "verification_kind": "institutional",
        "nugget_id": "",
        "verified_by": "",
        "verified_at": "",
        "extra_sources": [],
        "tags": [t for t in [raw.get("source")] if t],
        "n": idx,
    }


def search_institutional(
    query: str,
    *,
    sources: list[str] | None = None,
    limit_per_source: int = 3,
) -> dict[str, Any]:
    """Search the institutional collections through jeles-remote.

    Returns ``{hits, ok, base_url, sources_queried, total, error}``. Read `ok`
    before reading `hits`: ``ok`` true with no hits means the collections had
    nothing, ``ok`` false means they were never reached. `sources` narrows the
    fan-out to specific registered ids; omit it for every non-opt-in source.

    Never raises. A failed hop yields no hits and an explanation, never a
    forged result.
    """
    info = describe_remote()
    base = info["base_url"]
    if not info["configured"]:
        return {"hits": [], "ok": False, "base_url": base,
                "sources_queried": [], "total": 0, "error": info["reason"]}

    payload: dict[str, Any] = {"query": query, "limit_per_source": limit_per_source}
    if sources:
        payload["sources"] = sources

    try:
        data = _post(f"{base}/search", payload,
                     os.environ["JELES_REMOTE_SECRET"].strip())
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        log.warning("jeles institutional search failed for %r: %s", query, detail)
        return {"hits": [], "ok": False, "base_url": base,
                "sources_queried": [], "total": 0, "error": detail}

    # jeles-remote returns results grouped by source id; flatten, keeping the
    # grouping only as a tag so a caller can still see which collection
    # answered.
    grouped = data.get("results") or {}
    flat: list[dict[str, Any]] = []
    for source_id, items in grouped.items():
        for raw in items or []:
            raw = dict(raw)
            raw.setdefault("source", source_id)
            flat.append(raw)

    hits = [to_hit(raw, i) for i, raw in enumerate(flat)]
    return {
        "hits": hits,
        "ok": True,
        "base_url": base,
        "sources_queried": data.get("sources_queried") or [],
        "total": data.get("total", len(hits)),
        "error": "",
    }
