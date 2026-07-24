"""conflict_scan — the prior-art / conflict reaction (v1).

The behavior this scripts is the one hand-run in the 2026-07-24 design session:
given a design *claim*, search the web not for what's *similar* (the mirror —
you always find a match and feel original) but for what *supersedes or refutes*
it, and hand back what you found. This is the reaction ``orchestrator.md`` was
prose about and never enforced; here it is a script that ends in a proposed
FRANK line.

Three disciplines, all deterministic, all testable network-free:

1. **Conflict-biased query framing.** ``frame_queries`` weights the queries
   toward supersession/rivalry/refutation, not similarity. The mirror query is
   kept (one baseline) but outnumbered.

2. **Two independent sources.** A finding is *corroborated* only when at least
   ``min_sources`` **distinct registrable domains** back it. Two hits from the
   same site do not corroborate — the independent-*source* rule (a cheap prior-
   art heuristic, deliberately weaker than, and named apart from, the
   constitution's Independent Witness, which requires failure-mode divergence).
   Corroborated → propose a nugget; single-source → propose a *gap* (contested;
   the corpus records that it looked and couldn't yet verify).

3. **Propose, don't execute.** :func:`react` is pure routing: it calls an
   *injected* ``searcher`` and returns a list of proposed actions. It writes
   nothing — not the corpus, not FRANK. :func:`apply` executes proposals
   through injected drivers (defaulting to :mod:`jeles.corpus`). Reaction
   proposes; driver enforces — the model-proposes / gateway-enforces pattern,
   one layer down.

The network lives *only* behind the injected ``searcher`` — there is no network
import at module load — so importing this module, and running :func:`react`
with a fake searcher, is fast and offline. That is the same purity seam
:mod:`jeles.corpus` holds.
"""
from __future__ import annotations

from typing import Any, Callable
from urllib.parse import urlparse

# A searcher is any ``(query) -> [ {title, url, snippet}, ... ]``. The host wires
# one (e.g. an adapter over a web-search tool); the reaction never imports one.
Searcher = Callable[[str], list[dict[str, Any]]]

# The independent-SOURCE rule: a conflict is corroborated only by >= this many
# *distinct registrable domains*. Two pages on one site are one source, not two.
#
# Note the name: this is a weaker bar than the constitution's *Independent
# Witness* (CONSTITUTION.md §), which requires demonstrated failure-mode
# divergence — two distinct domains can still be one actor who bought both. This
# is a cheap prior-art heuristic, not the witness standard; kept deliberately
# distinct so the reaction doesn't borrow authority it hasn't earned.
DEFAULT_MIN_SOURCES = 2

# Two-label public suffixes: without these, foo.co.uk and bar.co.uk both reduce
# to "co.uk" and read as one source. Small, common set — not a full PSL.
_TWO_LABEL_SUFFIXES = frozenset({
    "co.uk", "org.uk", "ac.uk", "gov.uk", "co.jp", "or.jp", "ne.jp",
    "com.au", "net.au", "org.au", "co.nz", "com.br", "co.in", "co.za",
})

# The scan's machine witness. A corroborated finding is not a human-signed
# nugget; this tag says exactly what verified it — two independent sources —
# so a person can re-verify before it is trusted as settled.
WITNESS = "jeles:conflict-scan/2-independent-sources"


def frame_queries(claim: str, *, extra: list[str] | None = None) -> list[str]:
    """Turn a claim into a conflict-biased query set.

    One mirror query (baseline "does this exist"), then three that hunt the
    superseding / rival / refuting work. The bias is the point: a "find things
    like this" search validates; a "find what beats this" search carves the
    design down to the part nobody has already built.
    """
    claim = (claim or "").strip()
    if not claim:
        return []
    queries = [
        f"{claim} existing implementation library",   # mirror (baseline)
        f"{claim} alternative that supersedes",        # supersession
        f"{claim} vs prior art comparison",            # rivalry
        f"{claim} limitations criticism why not",      # refutation
    ]
    for q in (extra or []):
        q = (q or "").strip()
        if q and q not in queries:
            queries.append(q)
    return queries


def _domain(url: str) -> str:
    """Registrable-ish domain of a URL, for the independence test.

    Coarse on purpose: strip scheme, ``www.``, and path; keep the last two
    labels (``foo.github.io`` -> ``github.io``). Good enough to tell "two
    different sites" from "two pages on one site," which is all the two-source
    rule needs. It never raises — an unparseable URL yields ``""``.
    """
    try:
        host = urlparse(url if "://" in url else f"//{url}", scheme="https").netloc.lower()
    except Exception:
        return ""
    host = host.split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    labels = [x for x in host.split(".") if x]
    # A usable source has a dotted domain; a dotless/garbage host is no source.
    if len(labels) < 2:
        return ""
    last2 = ".".join(labels[-2:])
    # Keep three labels when the last two are a known two-label public suffix,
    # so foo.co.uk and bar.co.uk stay distinct sources.
    if last2 in _TWO_LABEL_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return last2


def _gather(queries: list[str], searcher: Searcher, max_results: int) -> list[dict[str, Any]]:
    """Run every query through the injected searcher; normalize + dedupe by URL."""
    seen: set[str] = set()
    hits: list[dict[str, Any]] = []
    for q in queries:
        try:
            results = searcher(q) or []
        except Exception:
            # A single query failing must not sink the scan — it just yields
            # fewer witnesses, which the corroboration gate already handles.
            results = []
        for r in results[: max(0, max_results)]:
            url = str(r.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            hits.append({
                "title": str(r.get("title") or "").strip(),
                "url": url,
                "snippet": str(r.get("snippet") or "").strip(),
                "domain": _domain(url),
                "query": q,
            })
    return hits


def react(
    event: dict[str, Any],
    *,
    searcher: Searcher,
    max_results: int = 6,
    min_sources: int = DEFAULT_MIN_SOURCES,
) -> list[dict[str, Any]]:
    """The reaction. ``event`` needs a ``claim``; ``kind``/``surface``/``tags``
    are optional context. Returns proposed actions — writes nothing.

    Proposals (most-actionable first, the conflict bias carried into ordering):

    * ``put_nugget`` — emitted only when the conflict is corroborated by
      ``>= min_sources`` independent domains. Records the *fact of corroborated
      prior art*, with the URLs as sources for a human to verify.
    * ``log_gap`` — emitted when the finding is contested (0–1 sources): the
      corpus remembers it looked and couldn't yet verify.
    * ``frank_append`` — always emitted last, so every firing leaves one legible
      line regardless of outcome (the reaction-engine legibility rule).
    """
    claim = str(event.get("claim") or "").strip()
    if not claim:
        return []

    queries = frame_queries(claim, extra=event.get("queries"))
    hits = _gather(queries, searcher, max_results)
    domains = sorted({h["domain"] for h in hits if h["domain"]})
    corroborated = len(domains) >= min_sources

    # Only URLs from a real (dotted) domain are sources — drop unparseable-URL
    # hits so a human re-verifying "the sources" sees exactly what cleared the
    # independent-domain bar, not query noise.
    domain_set = set(domains)
    sources = [h["url"] for h in hits if h["domain"] in domain_set]

    tags = ["conflict-scan", "prior-art"] + [str(t) for t in (event.get("tags") or [])]
    proposals: list[dict[str, Any]] = []

    if corroborated:
        top = domains[:4]
        answer = (
            f"Corroborated by {len(domains)} independent sources "
            f"({', '.join(top)}{'…' if len(domains) > len(top) else ''}). "
            f"Superseding / prior work exists — treat the design's overlap here "
            f"as bought, not novel. Human-verify the sources before sealing."
        )
        proposals.append({
            "driver": "put_nugget",
            "reason": f"{len(domains)} independent domains corroborate prior art",
            "args": {
                "question": f"Prior-art / conflict scan: {claim}",
                "answer": answer,
                "sources": sources,
                "verified_by": WITNESS,
                # Machine corroboration, not a human check — the driver stamps
                # this so the nugget can't render as human-verified (corpus B6).
                "verification_kind": "machine",
                "tags": tags,
            },
        })
    else:
        proposals.append({
            "driver": "log_gap",
            "reason": (
                f"contested — {len(domains)} independent source(s), "
                f"below the {min_sources}-source bar"
            ),
            "args": {"question": f"Prior-art / conflict scan: {claim}"},
        })

    proposals.append({
        "driver": "frank_append",
        "reason": "legibility — every reaction leaves one line",
        "args": {
            "kind": "conflict_scan",
            "claim": claim,
            "event_kind": str(event.get("kind") or ""),
            "surface": str(event.get("surface") or ""),
            "corroborated": corroborated,
            "sources": sources,
            "domains": domains,
        },
    })
    return proposals


def apply(
    proposals: list[dict[str, Any]],
    *,
    put_nugget: Callable[..., Any] | None = None,
    log_gap: Callable[..., Any] | None = None,
    frank: Callable[[dict[str, Any]], Any] | None = None,
) -> list[dict[str, Any]]:
    """Execute proposals through injected drivers. Defaults bind to
    :mod:`jeles.corpus` for the two corpus drivers; ``frank`` has no default
    (the host wires FRANK) and an un-wired ``frank_append`` is recorded as
    skipped, not silently dropped.
    """
    if put_nugget is None or log_gap is None:
        from .. import corpus
        put_nugget = put_nugget or corpus.put_nugget
        log_gap = log_gap or corpus.log_gap

    receipts: list[dict[str, Any]] = []
    for p in proposals:
        driver = p.get("driver")
        args = p.get("args") or {}
        if driver == "put_nugget":
            receipts.append({"driver": driver, "result": put_nugget(**args)})
        elif driver == "log_gap":
            receipts.append({"driver": driver, "result": log_gap(**args)})
        elif driver == "frank_append":
            result = frank(args) if frank else {"skipped": "no frank driver wired"}
            receipts.append({"driver": driver, "result": result})
        else:
            receipts.append({"driver": driver, "result": {"error": "unknown driver"}})
    return receipts
