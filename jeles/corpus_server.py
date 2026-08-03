"""Standalone MCP server over Jeles' verified-nugget corpus.

Mirrors willow-mcp's shape — `MCPServer`, stdio by default, every tool takes
an `app_id` — but scoped to one small corpus so it can run independently of
any particular fleet and be MCP-agnostic: any stdio MCP client (Claude
Code, Claude Desktop, Cursor, willow-mcp itself, a bare script) can point
at it with `python -m jeles.corpus_server`.

Unlike willow-mcp, this server does not implement manifest-based ACL — the
corpus is already scoped to a single app's own data, so there is nothing
for a permission gate to isolate. `app_id` is accepted on every tool for
naming-convention parity and so a future gate can be added without
changing the tool signatures. This server does not depend on willow-mcp.

Tools:
  corpus_ask     — best-match nugget for a question, or {found: false}
                   (logs a gap on miss)
  corpus_search  — ranked nugget search (no gap logging)
  corpus_get     — fetch a single nugget by id
  corpus_list    — list nuggets, most recently updated first
  corpus_put     — add or update a verified nugget
  corpus_gaps    — list logged "I don't know yet" questions

The outward hops, for what the verified layer could not answer:

  corpus_web_search           — the open web; results are always `unverified`
  corpus_institutional_search — ~65 institutional/academic collections, run
                                in-process; results are `institutional`
  corpus_sources              — which collections exist, and which need a key
  corpus_search_status        — can either outward hop work? (asks nothing of
                                the network)

Together those are the persona's mandate — local KB → open web → special
collections — with the confidence ladder intact across all three:

  verified > corroborated > institutional > unverified
"""

from __future__ import annotations

from typing import Optional

try:
    from mcp.server.mcpserver import MCPServer
except ImportError as exc:  # pragma: no cover - exercised by install shape, not tests
    # The MCP SDK is an optional extra: base `jeles` has zero runtime
    # dependencies so a host can depend on it without inheriting a version
    # constraint. Two different failures land here, and they need different
    # answers, so say which one it is rather than leaking a bare traceback.
    if exc.name == "mcp":
        raise ImportError(
            "jeles.corpus_server needs the MCP SDK, which base `jeles` does not "
            'install. Add the extra:  pip install "jeles[mcp]"\n'
            "(the corpus, the persona, and the reactions all work without it)"
        ) from exc
    raise ImportError(
        "jeles.corpus_server requires MCP SDK 2.x — `mcp.server.mcpserver` does "
        "not exist in SDK 1.x, where the equivalent was `mcp.server.fastmcp`. "
        "Upgrade:\n"
        '    pip install --upgrade "jeles[mcp]"   # pins mcp>=2.0,<3\n'
        "SDK 2.x is also what willow-mcp requires, so the two now co-install."
    ) from exc

from urllib.parse import urlparse

import jeles
from jeles import corpus, institutional, willow_mcp_client
from jeles.reactions import search_adapter

mcp = MCPServer(
    "jeles-corpus",
    version=jeles.__version__,
    instructions=(
        "Jeles' verified-nugget corpus. Ask a question to get a cited, "
        "human-verified answer if one exists, search the corpus directly, "
        "or contribute a new verified nugget. Misses are logged as gaps "
        "for someone to fill in later."
    ),
)


@mcp.tool()
def corpus_ask(app_id: str, question: str) -> dict:
    """Answer from the verified corpus if a nugget matches; returns
    {found: false} and logs a gap otherwise. The gap also gets a
    best-effort, non-blocking forward to willow-mcp's fleet-wide gap
    backlog, so it isn't just a local secret."""
    result = corpus.ask_corpus(question)
    if not result.get("found"):
        willow_mcp_client.forward_gap(question)
    return result


@mcp.tool()
def corpus_search(app_id: str, query: str, limit: int = 8) -> list:
    """Ranked nugget search across the corpus. Never logs a gap."""
    return corpus.search_nuggets(query, limit=limit)


@mcp.tool()
def corpus_get(app_id: str, nugget_id: str) -> dict:
    """Fetch a single nugget by id."""
    return corpus.get_nugget(nugget_id)


@mcp.tool()
def corpus_list(app_id: str, limit: int = 50) -> list:
    """List nuggets, most recently updated first."""
    return corpus.list_nuggets(limit=limit)


@mcp.tool()
def corpus_put(
    app_id: str,
    question: str,
    answer: str,
    sources: list[str],
    verified_by: str,
    tags: Optional[list[str]] = None,
    nugget_id: Optional[str] = None,
) -> dict:
    """Add or update a verified nugget. Requires question, answer, at least
    one source, and who verified it. Returns {id, action}."""
    return corpus.put_nugget(
        question, answer, sources, verified_by, tags=tags, nugget_id=nugget_id
    )


@mcp.tool()
def corpus_gaps(app_id: str, limit: int = 50) -> list:
    """List logged 'I don't know yet' questions, most-asked first — the
    corpus's growth queue."""
    return corpus.list_gaps(limit=limit)


# ── The second hop: the open web ────────────────────────────────────────────
#
# The persona's mandate is "local KB → open web → special collections", and
# until now this server implemented only the first. `search_adapter` existed
# but had exactly one consumer — conflict_scan.react — which was not exposed as
# a tool, so a client running this server got a corpus and no internet at all.
#
# These do not change what `corpus_ask` does. The corpus sits *in front of*
# live search rather than replacing it (design principle 1), so the second hop
# is a separate, explicit call: the caller decides to leave the settled layer,
# and can see that it did.


def _web_hit(hit: dict, idx: int) -> dict:
    """Shape a raw searcher result like `corpus.to_search_hit` shapes a nugget,
    so corpus and web results merge into one ranked list without translation.

    The fields that must never collapse are `source_id` and `confidence`: a
    human-verified nugget and a page someone found on the internet can sit in
    the same list, but they cannot be allowed to *read* the same. Everything
    here is `unverified` — the librarian's no-unsourced-output rule expressed
    as data rather than as a warning in prose.
    """
    url = str(hit.get("url") or "")
    try:
        host = urlparse(url).netloc or "web"
    except ValueError:
        host = "web"
    return {
        "title": hit.get("title") or "",
        "url": url,
        "snippet": hit.get("snippet") or "",
        "source": f"Open web — {host}",
        "date": "",
        "source_id": "web",
        "hostname": host,
        "confidence": "unverified",
        "verification_kind": "none",
        "nugget_id": "",
        "verified_by": "",
        "verified_at": "",
        "extra_sources": [],
        "tags": [],
        "n": idx,
    }


@mcp.tool()
def corpus_web_search(app_id: str, query: str, limit: int = 8) -> dict:
    """Search the open web — the corpus's second hop, for questions the
    verified layer could not answer.

    Returns ``{hits, ok, backend, shallow, error}``. Read `ok` before reading
    `hits`: an empty list with ``ok: true`` means the web had nothing, and an
    empty list with ``ok: false`` means the search never happened (unset key,
    unreachable host, wrong backend). Those are different facts and answering
    "I don't know" on the second is a lie.

    ``shallow: true`` means the backend is the zero-config DuckDuckGo
    Instant-Answer endpoint, which returns related topics rather than a result
    page — treat thin results as a configuration problem, not as evidence of
    absence. Call ``corpus_search_status`` for the details.

    Every hit is ``confidence: "unverified"``. Promote one to the corpus with
    ``corpus_put`` only once a human has actually checked it.
    """
    out = search_adapter.search_with_status(query)
    hits = [_web_hit(h, i) for i, h in enumerate(out["hits"][:limit])]
    return {
        "hits": hits,
        "ok": out["ok"],
        "backend": out["backend"],
        "shallow": out["shallow"],
        "error": out["error"],
    }


@mcp.tool()
def corpus_search_status(app_id: str) -> dict:
    """Report whether the outward hops can work at all, without searching.

    Top-level keys describe the open web —
    ``{backend, configured, shallow, requires, reason}`` — and
    ``institutional`` carries the same question for the third hop, including
    which lane it will take (`local` in-process, or a configured `remote`).

    Worth calling before concluding that anything "found nothing": the
    zero-config web default is `ddg`, which is `configured` because it needs no
    configuration and `shallow` because it cannot corroborate anything. Both
    look like silence from the outside.
    """
    status = dict(search_adapter.describe_backend())
    # Additive: the web keys stay at the top level so anything reading this
    # tool before the third hop existed keeps working unchanged.
    status["institutional"] = institutional.describe_remote()
    return status


# ── The third hop: special collections ──────────────────────────────────────


@mcp.tool()
def corpus_institutional_search(
    app_id: str,
    query: str,
    limit: int = 12,
    sources: Optional[list[str]] = None,
    limit_per_source: int = 3,
) -> dict:
    """Search named institutional and academic collections — the persona's
    third hop, and the one that produces citable answers.

    One query fans out across ~65 registered sources (arXiv, PubMed, Crossref,
    OpenAlex, Library of Congress, Europeana, CourtListener, the Smithsonian,
    ...), **in this process** — no service to deploy and no secret to hold.
    ``sources`` narrows the fan-out to specific registered ids; omit it for
    every non-opt-in source, and call ``corpus_sources`` to see what those are.

    Returns ``{hits, ok, lane, sources_queried, total, error}``. Read `ok`
    before reading `hits`: ``ok: false`` means the collections were never
    reached. ``lane`` is ``local`` unless a remote deployment is configured.

    Every hit is ``confidence: "institutional"`` — its own rung between a
    corpus nugget's ``verified``/``corroborated`` and the open web's
    ``unverified``. A Library of Congress record is neither a human-checked
    nugget nor a random page, and collapsing it into either would discard the
    only thing this hop is for. `source` names the publishing body.
    """
    out = institutional.search_institutional(
        query, sources_filter=sources, limit_per_source=limit_per_source
    )
    return {**out, "hits": out["hits"][:limit]}


@mcp.tool()
def corpus_sources(app_id: str) -> dict:
    """List the registered institutional collections, without searching.

    ``{sources: [{id, name, key_required, opt_in}], total, default_count}``.
    A `key_required` source is skipped silently when its key is absent, so this
    is how a caller learns what it is *not* reaching; `opt_in` sources sit out
    of the default fan-out and must be named explicitly in
    ``corpus_institutional_search(sources=[...])``.
    """
    listed = institutional.list_sources()
    return {
        "sources": listed,
        "total": len(listed),
        "default_count": sum(1 for s in listed if not s["opt_in"]),
    }


def main() -> None:
    # Explicit transport: SDK 2.0 moved host/port off the constructor onto
    # run(transport=, host=, port=), making "where this instance listens" a
    # property of the run rather than of the server. stdio is the default and
    # the only mode this server offers — it is a local organ, not a service.
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
