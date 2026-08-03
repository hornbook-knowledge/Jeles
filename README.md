# jeles

The **verified-corpus organ**, extracted from the [Ask Jeles](https://github.com/rudi193-cmd) app into its own installable package — plus the canonical **Jeles persona**.

A *nugget* is a human-verified question/answer pair with citations:
`{question, answer, sources, verified_by, verified_at, tags}`. This package
is the settled layer of answers that sits *in front of* a host's live
search — a confident nugget match answers instantly; everything else falls
through to the host's own search path unchanged. Misses are logged as
*gaps* ("I don't know yet") so the corpus knows what it's been asked and
couldn't answer.

## What's in the organ

| Module | Role |
| --- | --- |
| `jeles.corpus` | Pure storage + ranked lookup of verified nuggets and gap logging. **Stdlib-only, no MCP, no network at import.** Reuses willow-mcp's SOIL `Store` SQLite schema at `$WILLOW_STORE_ROOT/<collection>/store.db`. |
| `jeles.corpus_server` | Standalone `MCPServer` (MCP SDK 2.x) over the corpus (`python -m jeles.corpus_server`). Mirrors willow-mcp's shape (`app_id` on every tool) **without depending on willow-mcp**. |
| `jeles.institutional` | The third hop: named institutional/academic collections via a [`jeles-remote`](https://github.com/rudi193-cmd/jeles-remote) deployment (~65 sources — arXiv, PubMed, Crossref, OpenAlex, Library of Congress, Europeana, CourtListener, the Smithsonian). **Stdlib-only, no network at import.** |
| `jeles.willow_mcp_client` | Best-effort, fire-and-forget forwarding of gaps into willow-mcp's fleet-wide backlog. Never blocks, never raises; 30s retry cooldown so a single failed connect doesn't permanently disable forwarding. |
| `jeles.load_persona()` | Loads the canonical Jeles persona JSON (this package is its canonical home). |

## Design principles

1. **The corpus sits in front of live search, it doesn't replace it.** A confident nugget match answers instantly — no search, no LLM call.
2. **`corpus.py` stays pure.** Storage and ranking have no MCP, no network, no side effects beyond SQLite. Everything MCP-shaped wraps it; it never depends on anything MCP-shaped itself. This is what keeps its tests fast and network-free.
3. **The corpus is its own standalone MCP server, on purpose.** `corpus_server.py` is a small `MCPServer` any stdio client can run directly, mirroring willow-mcp's shape without depending on it.
4. **Two kinds of "ask," two gap-logging rules.** `search_nuggets()` (passive/background) checks the corpus but never logs a gap on a miss. `ask_corpus()` (deliberate) treats a miss — or a match below `MIN_ASK_SCORE` — as a real gap worth tracking, and logs it.
5. **Local is the source of truth; the fleet backlog is additive.** `corpus.log_gap()` (synchronous, local SQLite) always runs first and makes the host fully functional offline. `willow_mcp_client.forward_gap()` is a *best-effort* copy into willow-mcp's shared backlog.

## Install

**Base `jeles` has zero runtime dependencies.** The corpus, the persona, and the
reactions are stdlib-only, so a host can depend on this package without
inheriting a single version constraint from it. Only the standalone MCP server
needs the SDK, and it lives behind an extra.

```bash
pip install jeles           # corpus + persona + reactions. No dependencies.
pip install "jeles[mcp]"    # adds the MCP SDK, for the standalone server
pip install -e ".[dev]"     # editable, with pytest and the SDK
```

Or as a host dependency, straight from git:

```
jeles @ git+https://github.com/rudi193-cmd/Jeles@main
```

`jeles[mcp]` requires **MCP SDK 2.x** (`corpus_server.py` uses
`mcp.server.mcpserver.MCPServer`; `mcp.server.fastmcp` was removed in SDK 2.0).
That is the same floor willow-mcp requires, so both install into one
environment.

### Versioning

The version comes from the git tag (`hatch-vcs`), not from a literal in
`pyproject.toml`, and `jeles.__version__` reads it back out of installed package
metadata. There is exactly one place a release number is decided, so a tag
cannot disagree with the artifact it builds.

## Usage

### As a library

```python
from jeles import corpus

corpus.put_nugget(
    question="What is the primary color in Grove?",
    answer="The primary color in Grove is #ffffff (white).",
    sources=["safe-library/themes/grove.json"],
    verified_by="designer",
    tags=["color", "grove", "primary"],
)

hit = corpus.ask_corpus("What is the primary color in Grove?")
# -> {"found": True, "exact": True, "nugget": {...}, "candidates": [...]}

miss = corpus.ask_corpus("What is the accent color in Tokyo Night?")
# -> {"found": False, ...}   and the question is logged as a gap
```

### As a standalone MCP server

```bash
python -m jeles.corpus_server      # stdio; or use the `jeles-corpus-mcp` console script
```

Tools — each takes an `app_id` for naming-convention parity with willow-mcp:

| Hop | Tools |
| --- | --- |
| The settled layer | `corpus_ask`, `corpus_search`, `corpus_get`, `corpus_list`, `corpus_put`, `corpus_gaps` |
| Open web | `corpus_web_search` |
| Special collections | `corpus_institutional_search` |
| Diagnosis | `corpus_search_status` — can either outward hop work? Asks nothing of the network. |

### The confidence ladder

All three hops return the **same hit shape**, so a host can rank them in one
list without translating any of them. What never merges is the labelling:

| `confidence` | `source_id` | Means |
| --- | --- | --- |
| `verified` | `corpus` | A human checked it. |
| `corroborated` | `corpus` | Two independent domains agreed; no human yet. |
| `institutional` | `institutional` | A named body published it — arXiv, the Library of Congress. Nobody checked it *for you*. |
| `unverified` | `web` | Someone put it on the internet. |

If any two of those ever collapse, the librarian is citing something it did not
check — so a test asserts all four stay distinct.

### The persona

```python
import jeles
persona = jeles.load_persona()   # dict; canonical Jeles persona
```

## Configuration

| Env var | Default | Effect |
| --- | --- | --- |
| `WILLOW_STORE_ROOT` | `~/.willow/store` | Root under which `<collection>/store.db` lives. |
| `JELES_CORPUS_COLLECTION` | `ask_jeles_corpus` | Nugget collection name (back-compat with Ask Jeles). |
| `JELES_CORPUS_GAPS_COLLECTION` | `ask_jeles_corpus_gaps` | Local gap-log collection name. |
| `JELES_CORPUS_APP_ID` | `ask-jeles` | `app_id` used when forwarding gaps to willow-mcp. |
| `JELES_CORPUS_TOPIC` | `ask-jeles-corpus` | Backlog topic gaps are forwarded under. |
| `WILLOW_MCP_CMD` | — | Explicit command to launch willow-mcp (else `willow-mcp` on PATH, else `python -m willow_mcp`). |
| `JELES_REMOTE_URL` | `https://jeles-remote.fly.dev` | Base URL of the `jeles-remote` deployment backing the third hop. |
| `JELES_REMOTE_SECRET` | — | Shared secret sent as `X-Jeles-Secret`. **Without it every institutional search is refused with 401**, which would otherwise look exactly like an empty shelf. |
| `JELES_REMOTE_TIMEOUT` | `30` | Seconds to wait on the institutional fan-out. |
| `JELES_SEARCH_BACKEND` | `searxng` if `JELES_SEARXNG_URL` is set, else `ddg` | Open-web backend: `searxng`, `brave`, `tavily`, `ddg`. The `ddg` fallback is zero-config and **shallow** — it returns related topics, not a result page. `corpus_search_status` says so rather than letting you infer depth from the absence of an error. |
| `ASK_JELES_USE_WILLOW_MCP` | `1` | Set to `0`/`false`/`no` to disable fleet gap-forwarding entirely. |

The Ask Jeles-flavored defaults are preserved so an existing store and its
already-forwarded fleet backlog keep resolving after the extraction.

## Tests

```bash
pytest -q
```

`corpus.py`'s tests are fast and network-free by construction; the
willow-mcp client tests never spin up a real subprocess. An import-purity
test asserts that importing `jeles.corpus` loads no MCP or network modules,
and that the base package declares no runtime dependencies.

`tests/test_corpus_server.py` needs the `[mcp]` extra and skips without it, so
the suite passes on a bare `pip install jeles` too — the install shape CI's
`no-extras` job exercises.

## License

Apache-2.0 — see [LICENSE](LICENSE).
