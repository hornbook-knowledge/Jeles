"""search_adapter — the real web-search edge for conflict_scan (v1).

conflict_scan.react() never imports a search backend; it takes an injected
``searcher: (query) -> [{title, url, snippet}]``. This module is the default
implementation of that edge — the one impure, network-touching piece — kept
deliberately separate so the reaction's routing stays pure and offline-testable.

Design choices, all in the box's grain:

* **Stdlib only.** urllib.request, json, no third-party HTTP client — the
  dependency-less goal. (Importing this module opens no socket; the network
  happens only when the returned searcher is *called*.)
* **Backend-pluggable, fail-soft.** ``JELES_SEARCH_BACKEND`` selects
  ``searxng`` (sovereign, self-hosted JSON — the preferred default when a URL
  is set), ``brave`` or ``tavily`` (keyed APIs), or ``ddg`` (keyless,
  best-effort HTML). Any network/parse error yields ``[]``, which conflict_scan
  already treats as "no witness → contested gap" — a failed search never forges
  corroboration.
* **The perimeter is the operator's choice.** This default does *raw* egress
  (through ``HTTPS_PROXY`` if the environment sets one). In a gated deployment,
  don't use it — inject a searcher that routes through willow-mcp's three-key
  egress instead. The whole point of the injected-searcher seam is that swapping
  this out requires no change to the reaction. (See the 2026-07-24 red-team:
  raw egress from inside a reaction is exactly the "correct code, wrong
  perimeter" trap; this module names it rather than hiding it.)
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any, Callable

Searcher = Callable[[str], list[dict[str, Any]]]

_UA = "jeles-conflict-scan/1.0 (+local-first; https://github.com/rudi193-cmd/Jeles)"
_TIMEOUT = float(os.environ.get("JELES_SEARCH_TIMEOUT", "12"))
_MAX = int(os.environ.get("JELES_SEARCH_MAX", "8"))
# Cap the response body: a misbehaving/redirected endpoint could otherwise
# stream an unbounded body into memory before parse (this component is fail-soft
# and never trusted, so a big body should fail, not OOM).
_MAX_BYTES = int(os.environ.get("JELES_SEARCH_MAX_BYTES", str(4 * 1024 * 1024)))


def _get_json(url: str, headers: dict[str, str] | None = None,
              data: bytes | None = None) -> Any:
    if not url.startswith(("https://", "http://")):
        raise ValueError(f"refusing non-HTTP(S) URL scheme: {url!r}")
    req = urllib.request.Request(url, data=data, headers={"User-Agent": _UA, **(headers or {})})
    # Scheme is guarded above (fail-closed); urlopen honors HTTPS_PROXY env.
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # nosec B310
        raw = resp.read(_MAX_BYTES + 1)
        if len(raw) > _MAX_BYTES:
            raise ValueError(f"search response exceeds {_MAX_BYTES} bytes — refusing")
        return json.loads(raw.decode("utf-8", "replace"))


def _hit(title: Any, url: Any, snippet: Any) -> dict[str, Any]:
    return {
        "title": str(title or "").strip(),
        "url": str(url or "").strip(),
        "snippet": str(snippet or "").strip(),
    }


# ── Backends: each is (query) -> [ {title,url,snippet}, ... ], raising on failure
#    (the make_searcher wrapper turns any raise into a fail-soft []). ──────────


def _searxng(query: str) -> list[dict[str, Any]]:
    """A self-hosted SearXNG instance's JSON API — the sovereign default.
    Set JELES_SEARXNG_URL (e.g. http://127.0.0.1:8888)."""
    base = os.environ.get("JELES_SEARXNG_URL", "").rstrip("/")
    if not base:
        raise RuntimeError("JELES_SEARXNG_URL not set")
    qs = urllib.parse.urlencode({"q": query, "format": "json", "safesearch": "0"})
    data = _get_json(f"{base}/search?{qs}")
    return [_hit(r.get("title"), r.get("url"), r.get("content"))
            for r in (data.get("results") or [])[:_MAX]]


def _brave(query: str) -> list[dict[str, Any]]:
    """Brave Search API. Set BRAVE_API_KEY."""
    key = os.environ.get("BRAVE_API_KEY", "")
    if not key:
        raise RuntimeError("BRAVE_API_KEY not set")
    qs = urllib.parse.urlencode({"q": query, "count": _MAX})
    data = _get_json(
        f"https://api.search.brave.com/res/v1/web/search?{qs}",
        headers={"X-Subscription-Token": key, "Accept": "application/json"},
    )
    results = ((data.get("web") or {}).get("results")) or []
    return [_hit(r.get("title"), r.get("url"), r.get("description")) for r in results[:_MAX]]


def _tavily(query: str) -> list[dict[str, Any]]:
    """Tavily search API. Set TAVILY_API_KEY."""
    key = os.environ.get("TAVILY_API_KEY", "")
    if not key:
        raise RuntimeError("TAVILY_API_KEY not set")
    body = json.dumps({"api_key": key, "query": query, "max_results": _MAX}).encode()
    data = _get_json("https://api.tavily.com/search",
                     headers={"Content-Type": "application/json"}, data=body)
    return [_hit(r.get("title"), r.get("url"), r.get("content"))
            for r in (data.get("results") or [])[:_MAX]]


def _ddg(query: str) -> list[dict[str, Any]]:
    """DuckDuckGo Instant-Answer JSON — keyless, zero-config, but shallow
    (it returns related topics, not a full SERP). Best-effort fallback so the
    adapter does *something* with no setup; upgrade to searxng/brave for depth."""
    qs = urllib.parse.urlencode({"q": query, "format": "json", "no_html": "1"})
    data = _get_json(f"https://api.duckduckgo.com/?{qs}")
    out: list[dict[str, Any]] = []
    for topic in (data.get("RelatedTopics") or []):
        # RelatedTopics is a mix of {Text,FirstURL} and {Topics:[...]} groups.
        items = topic.get("Topics") if "Topics" in topic else [topic]
        for it in items or []:
            if it.get("FirstURL"):
                out.append(_hit(it.get("Text"), it.get("FirstURL"), it.get("Text")))
    if data.get("AbstractURL"):
        out.insert(0, _hit(data.get("Heading"), data.get("AbstractURL"), data.get("AbstractText")))
    return out[:_MAX]


_BACKENDS: dict[str, Searcher] = {
    "searxng": _searxng, "brave": _brave, "tavily": _tavily, "ddg": _ddg,
}


def _default_backend_name() -> str:
    name = os.environ.get("JELES_SEARCH_BACKEND", "").strip().lower()
    if name:
        return name
    # Zero config: prefer a configured SearXNG, else fall back to keyless DDG.
    return "searxng" if os.environ.get("JELES_SEARXNG_URL") else "ddg"


def make_searcher(backend: str | None = None) -> Searcher:
    """Return a fail-soft ``(query) -> [hits]`` ready to hand to
    ``conflict_scan.react(..., searcher=make_searcher())``.

    ``backend`` overrides ``JELES_SEARCH_BACKEND``. Any error inside the backend
    (unset key, network failure, unparseable response) is swallowed to ``[]`` —
    a failed search yields no witnesses, never a false one.
    """
    name = (backend or _default_backend_name()).lower()
    fn = _BACKENDS.get(name)
    if fn is None:
        raise ValueError(f"unknown search backend {name!r}; "
                         f"choose one of {sorted(_BACKENDS)}")

    def search(query: str) -> list[dict[str, Any]]:
        try:
            return fn(query)
        except Exception:
            return []  # fail-soft: conflict_scan reads [] as "no witness"

    return search
