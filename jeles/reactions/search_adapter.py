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
* **Fail-soft, not silent.** Returning ``[]`` for an unset API key, an
  unreachable host, a 403 and a genuinely empty result gave one symptom —
  "nothing found" — four causes, and no way to tell which. The swallowing stays
  (corroboration depends on a failed search yielding no witness), but failures
  now log at WARNING, an unconfigured or shallow backend says so on first use,
  and :func:`search_with_status` returns the reason as data for callers that
  need to act on it. :func:`describe_backend` answers "can this even work?"
  without making a request.
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
import logging
import os
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from jeles import _egress

log = logging.getLogger("jeles.search")

Searcher = Callable[[str], list[dict[str, Any]]]

_UA = "jeles-conflict-scan/1.0 (+local-first; https://github.com/rudi193-cmd/Jeles)"
_TIMEOUT = float(os.environ.get("JELES_SEARCH_TIMEOUT", "12"))
_MAX = int(os.environ.get("JELES_SEARCH_MAX", "8"))
# Cap the response body: a misbehaving/redirected endpoint could otherwise
# stream an unbounded body into memory before parse (this component is fail-soft
# and never trusted, so a big body should fail, not OOM).
_MAX_BYTES = int(os.environ.get("JELES_SEARCH_MAX_BYTES", str(4 * 1024 * 1024)))


#: http stays allowed here, unlike `jeles.sources`, which is https-only. The
#: sovereign default this module is built around is a SearXNG instance the
#: operator runs themselves — `JELES_SEARXNG_URL=http://127.0.0.1:8888` is the
#: documented zero-config setup — and refusing plain http would break exactly
#: the self-hosted case. The cost is real and worth naming: on this lane a
#: hostile redirect can still downgrade https -> http. Set the backend to a
#: keyed API over TLS if a deployment cannot afford that.
_ALLOWED_SCHEMES = _egress.HTTP_OR_HTTPS


def _get_json(url: str, headers: dict[str, str] | None = None,
              data: bytes | None = None) -> Any:
    """Fetch and decode JSON through the shared egress guard.

    The guard was previously a one-shot `url.startswith(("https://", "http://"))`
    here, which urllib then walked straight past: it follows 3xx *inside*
    `urlopen`, so a redirect to `ftp://` was never inspected — reproduced
    against a listening socket, the connection arrived. `jeles._egress` re-checks
    the scheme on every hop and gives file:/ftp:/data: no transport at all.
    """
    # `allow_private=True` deliberately: the documented zero-config default is a
    # SearXNG instance on http://127.0.0.1:8888, so refusing private addresses
    # here would break the out-of-the-box case rather than protect it.
    raw = _egress.fetch(url, allowed=_ALLOWED_SCHEMES, timeout=_TIMEOUT,
                        max_bytes=_MAX_BYTES, data=data, allow_private=True,
                        headers={"User-Agent": _UA, **(headers or {})})
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


# Which env var makes each backend usable, and whether it can answer properly
# once it is. `ddg` is deliberately marked shallow: it needs no configuration,
# which is why it is the zero-config fallback, but the Instant-Answer endpoint
# returns related topics rather than a result page. It is a placeholder, not a
# search engine, and describe_backend() says so rather than letting a caller
# infer depth from the absence of an error.
_REQUIRES: dict[str, str | None] = {
    "searxng": "JELES_SEARXNG_URL",
    "brave": "BRAVE_API_KEY",
    "tavily": "TAVILY_API_KEY",
    "ddg": None,
}
_SHALLOW = frozenset({"ddg"})


def describe_backend(backend: str | None = None) -> dict[str, Any]:
    """Report which backend is selected and whether it can actually answer.

    The blind spot this exists for: ``make_searcher`` returns ``[]`` for an
    unset API key, an unreachable host, a 403 and a genuinely empty result
    alike. Downstream that is one symptom — "nothing found" — with four causes,
    three of which are configuration. Ask this before believing a silence.

    Returns ``{backend, configured, shallow, requires, reason}``. ``reason`` is
    empty when the backend is configured and capable.
    """
    name = (backend or _default_backend_name()).lower()
    if name not in _BACKENDS:
        return {
            "backend": name, "configured": False, "shallow": False,
            "requires": None,
            "reason": f"unknown backend {name!r}; choose one of {sorted(_BACKENDS)}",
        }

    needs = _REQUIRES[name]
    configured = bool(os.environ.get(needs)) if needs else True
    shallow = name in _SHALLOW

    if not configured:
        reason = (f"{needs} is not set, so every search returns no results — "
                  f"which is indistinguishable from finding nothing")
    elif shallow:
        reason = ("the DuckDuckGo Instant-Answer endpoint returns related "
                  "topics, not a result page. Zero-config, but too shallow to "
                  "corroborate a claim; set JELES_SEARXNG_URL (or a "
                  "BRAVE_API_KEY / TAVILY_API_KEY) for real depth")
    else:
        reason = ""

    return {"backend": name, "configured": configured, "shallow": shallow,
            "requires": needs, "reason": reason}


def search_with_status(query: str, backend: str | None = None) -> dict[str, Any]:
    """``search()`` that reports *why* it returned what it did.

    Same network call as the searcher, but the outcome is legible:
    ``{hits, ok, backend, shallow, error}``. ``ok`` false with an ``error``
    means the search failed; ``ok`` true with no hits means the web genuinely
    had nothing. Those are different facts and a caller should be able to tell
    them apart — the whole point of this module's second pass.
    """
    info = describe_backend(backend)
    name = info["backend"]
    fn = _BACKENDS.get(name)
    if fn is None:
        return {"hits": [], "ok": False, "backend": name,
                "shallow": False, "error": info["reason"]}
    try:
        hits = fn(query)
    except Exception as exc:
        # Include the configuration reason when there is one: "BRAVE_API_KEY is
        # not set" is a far more useful error than the KeyError it produces.
        detail = f"{type(exc).__name__}: {exc}"
        return {"hits": [], "ok": False, "backend": name,
                "shallow": info["shallow"],
                "error": f"{info['reason']} ({detail})" if info["reason"] else detail}
    return {"hits": hits, "ok": True, "backend": name,
            "shallow": info["shallow"], "error": ""}


def make_searcher(backend: str | None = None) -> Searcher:
    """Return a fail-soft ``(query) -> [hits]`` ready to hand to
    ``conflict_scan.react(..., searcher=make_searcher())``.

    ``backend`` overrides ``JELES_SEARCH_BACKEND``. Any error inside the backend
    (unset key, network failure, unparseable response) is swallowed to ``[]`` —
    a failed search yields no witnesses, never a false one.

    The swallowing stays, because conflict_scan's corroboration rule depends on
    it: a failed search must not be able to forge a witness. What changes is
    that it is no longer *silent* — failures log at WARNING, and an unconfigured
    or shallow backend logs once at first use. Use :func:`search_with_status`
    when the caller needs the reason as data rather than as a log line.
    """
    name = (backend or _default_backend_name()).lower()
    fn = _BACKENDS.get(name)
    if fn is None:
        raise ValueError(f"unknown search backend {name!r}; "
                         f"choose one of {sorted(_BACKENDS)}")

    info = describe_backend(name)
    warned = False

    def search(query: str) -> list[dict[str, Any]]:
        nonlocal warned
        if info["reason"] and not warned:
            warned = True
            log.warning("jeles search backend %r: %s", name, info["reason"])
        try:
            return fn(query)
        except Exception as exc:
            # fail-soft: conflict_scan reads [] as "no witness". Say so anyway —
            # an empty result that is really a broken backend is the failure
            # mode this module was hardest to debug for.
            log.warning("jeles search via %r failed for %r: %s: %s",
                        name, query, type(exc).__name__, exc)
            return []

    return search
