"""institutional — the third hop: named institutional and academic collections.

The persona's mandate is "local KB → open web → special collections". The
corpus is the first hop and `reactions.search_adapter` is the second; this is
the third, and it is a genuinely different tier rather than more web.

**It runs locally by default.** :mod:`jeles.sources` holds the ~65 source
functions — arXiv, PubMed, Crossref, OpenAlex, Library of Congress, Europeana,
CourtListener, the Smithsonian — and this module is the thin layer that fans a
query across them and shapes the results like every other hit in the package.
No secret, no deployment, no second service to be up.

A hosted `jeles-remote` deployment stays available as an **opt-in delegate**:
set ``JELES_REMOTE_URL`` and ``JELES_REMOTE_SECRET`` and the fan-out happens
there instead. That is worth having when a caller would rather not make ~65
outbound connections from its own process — a CI runner, a phone, a sandbox
with a narrow egress allowlist. It is a convenience, never a prerequisite.

Design, matching the rest of the package:

* **Stdlib only**, and no socket at import. The thread pool behind the local
  fan-out is built on first use.
* **Legible failure**, like `search_adapter`. `search_institutional` returns
  ``{hits, ok, ...}`` so "the collections had nothing" and "we never reached
  them" stay distinguishable. `describe_remote` answers "which lane is this
  going to take, and can it work?" without making a request.
* **The perimeter is the operator's choice.** Both lanes do raw egress (through
  ``HTTPS_PROXY`` if set), exactly as `search_adapter` does. In a gated
  deployment, route through willow-mcp's `JelesAdapter` instead.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any
from urllib.parse import urlparse

from jeles import sources

log = logging.getLogger("jeles.institutional")

_TIMEOUT = float(os.environ.get("JELES_REMOTE_TIMEOUT", "30"))
# The remote lane returns a fan-out across dozens of sources and can legitimately
# be large; cap it anyway, since it is untrusted input like any other response.
_MAX_BYTES = int(os.environ.get("JELES_REMOTE_MAX_BYTES", str(8 * 1024 * 1024)))
_UA = "jeles/institutional (+https://github.com/rudi193-cmd/Jeles)"


def _remote_base() -> str:
    return os.environ.get("JELES_REMOTE_URL", "").strip().rstrip("/")


def _remote_secret() -> str:
    return os.environ.get("JELES_REMOTE_SECRET", "").strip()


def describe_remote() -> dict[str, Any]:
    """Report which lane a search will take, without asking the network.

    Returns ``{lane, base_url, configured, requires, reason, sources}``.

    ``lane`` is ``"local"`` unless a remote is configured. ``configured`` is
    about the *chosen* lane: the local lane is always configured — that is the
    point of moving the collections in-package — so an unset remote is not a
    problem to report, just a lane not taken. A remote URL set *without* a
    secret is a real misconfiguration, though, because the service answers 401
    and a 401 reads exactly like an empty shelf.

    The secret is never included, only whether one was found.
    """
    base, secret = _remote_base(), _remote_secret()
    local_sources = sorted(sources.SOURCES)

    if not base:
        return {"lane": "local", "base_url": "", "configured": True,
                "requires": None, "reason": "", "sources": local_sources}

    if not secret:
        return {
            "lane": "remote", "base_url": base, "configured": False,
            "requires": "JELES_REMOTE_SECRET",
            "reason": ("JELES_REMOTE_URL is set but JELES_REMOTE_SECRET is not, "
                       "so the remote refuses every search with 401 — which is "
                       "indistinguishable from the collections having nothing. "
                       "Unset JELES_REMOTE_URL to use the in-package sources."),
            "sources": local_sources,
        }

    return {"lane": "remote", "base_url": base, "configured": True,
            "requires": "JELES_REMOTE_SECRET", "reason": "",
            "sources": local_sources}


def to_hit(raw: dict[str, Any], idx: int = 0) -> dict[str, Any]:
    """Shape one source result like `corpus.to_search_hit` shapes a nugget, so
    all three hops merge into one ranked list without translation.

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


def _flatten(grouped: dict[str, list]) -> list[dict[str, Any]]:
    """jeles-remote and `sources.search` both return results grouped by source
    id. Flatten, keeping the grouping as each hit's tag so a caller can still
    see which collection answered."""
    flat: list[dict[str, Any]] = []
    for source_id, items in (grouped or {}).items():
        for raw in items or []:
            raw = dict(raw)
            raw.setdefault("source", source_id)
            flat.append(raw)
    return flat


def _post_remote(base: str, payload: dict, secret: str) -> Any:
    url = f"{base}/search"
    if not url.startswith(("https://", "http://")):
        raise ValueError(f"refusing non-HTTP(S) URL scheme: {url!r}")
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={
            "User-Agent": _UA,
            "Content-Type": "application/json",
            # A raw shared secret, not a Bearer token — jeles-remote
            # hmac-compares it (its main.py `_verify_secret`).
            "X-Jeles-Secret": secret,
        },
    )
    # Scheme is guarded above (fail-closed); urlopen honors HTTPS_PROXY.
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # nosec B310
        raw = resp.read(_MAX_BYTES + 1)
        if len(raw) > _MAX_BYTES:
            raise ValueError(f"response exceeds {_MAX_BYTES} bytes — refusing")
        return json.loads(raw.decode("utf-8", "replace"))


def list_sources() -> list[dict[str, Any]]:
    """The registered collections: ``[{id, name, key_required, opt_in}, ...]``.

    Local knowledge — no request, and true regardless of which lane a search
    would take. `key_required` sources are skipped silently when their key is
    absent, so this is how a caller finds out what it is *not* reaching.
    """
    return [
        {"id": sid, "name": cfg.get("name", sid),
         "key_required": bool(cfg.get("key_required", False)),
         "opt_in": bool(cfg.get("opt_in", False))}
        for sid, cfg in sorted(sources.SOURCES.items())
    ]


def search_institutional(
    query: str,
    *,
    sources_filter: list[str] | None = None,
    limit_per_source: int = 3,
) -> dict[str, Any]:
    """Search the institutional collections.

    Runs the in-package fan-out unless ``JELES_REMOTE_URL`` is set, in which
    case it delegates to that deployment. Returns
    ``{hits, ok, lane, sources_queried, total, error}``.

    Read `ok` before reading `hits`: ``ok`` true with no hits means the
    collections had nothing, ``ok`` false means they were never reached —
    including the case where every individual source failed, which a per-source
    fan-out would otherwise report as a successful empty result. `failed` lists
    the source ids that could not be reached even when others answered.
    ``sources_filter`` narrows the fan-out to specific registered ids; omit it
    for every non-opt-in source.

    Never raises. A failed hop yields no hits and an explanation, never a
    forged result.
    """
    info = describe_remote()
    lane = info["lane"]

    if lane == "remote" and not info["configured"]:
        return {"hits": [], "ok": False, "lane": lane, "sources_queried": [],
                "failed": [], "total": 0, "error": info["reason"]}

    try:
        if lane == "remote":
            payload: dict[str, Any] = {"query": query,
                                       "limit_per_source": limit_per_source}
            if sources_filter:
                payload["sources"] = sources_filter
            data = _post_remote(info["base_url"], payload, _remote_secret())
        else:
            data = sources.search(query, sources=sources_filter,
                                  limit_per_source=limit_per_source)
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        log.warning("institutional search (%s lane) failed for %r: %s",
                    lane, query, detail)
        return {"hits": [], "ok": False, "lane": lane, "sources_queried": [],
                "failed": [], "total": 0, "error": detail}

    flat = _flatten(data.get("results") or {})
    hits = [to_hit(raw, i) for i, raw in enumerate(flat)]
    queried = data.get("sources_queried") or []
    failed = data.get("failed") or {}

    # `ok` means "we were able to look", not "we found something". If every
    # source we asked failed, we did not look — and reporting that as an empty
    # shelf is the same lie the web hop used to tell. Found live: a sandbox
    # whose egress blocked every source returned ok=true, total=0.
    unreachable = bool(queried) and len(failed) >= len(queried)
    error = ""
    if unreachable:
        sample = "; ".join(f"{sid}: {msg}" for sid, msg in list(failed.items())[:3])
        error = (f"every source failed ({len(failed)}/{len(queried)}) — "
                 f"this is an outage or a blocked egress, not an empty result. "
                 f"{sample}")

    return {
        "hits": hits,
        "ok": not unreachable,
        "lane": lane,
        "sources_queried": queried,
        "failed": sorted(failed),
        "total": data.get("total", len(hits)),
        "error": error,
    }
