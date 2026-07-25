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
| `jeles.corpus_server` | Standalone FastMCP server over the corpus (`python -m jeles.corpus_server`). Mirrors willow-mcp's shape (`app_id` on every tool) **without depending on willow-mcp**. |
| `jeles.willow_mcp_client` | Best-effort, fire-and-forget forwarding of gaps into willow-mcp's fleet-wide backlog. Never blocks, never raises; 30s retry cooldown so a single failed connect doesn't permanently disable forwarding. |
| `jeles.load_persona()` | Loads the canonical Jeles persona JSON (this package is its canonical home). |

## Design principles

1. **The corpus sits in front of live search, it doesn't replace it.** A confident nugget match answers instantly — no search, no LLM call.
2. **`corpus.py` stays pure.** Storage and ranking have no MCP, no network, no side effects beyond SQLite. Everything MCP-shaped wraps it; it never depends on anything MCP-shaped itself. This is what keeps its tests fast and network-free.
3. **The corpus is its own standalone MCP server, on purpose.** `corpus_server.py` is a small FastMCP server any stdio client can run directly, mirroring willow-mcp's shape without depending on it.
4. **Two kinds of "ask," two gap-logging rules.** `search_nuggets()` (passive/background) checks the corpus but never logs a gap on a miss. `ask_corpus()` (deliberate) treats a miss — or a match below `MIN_ASK_SCORE` — as a real gap worth tracking, and logs it.
5. **Local is the source of truth; the fleet backlog is additive.** `corpus.log_gap()` (synchronous, local SQLite) always runs first and makes the host fully functional offline. `willow_mcp_client.forward_gap()` is a *best-effort* copy into willow-mcp's shared backlog.

## Install

```bash
pip install -e .          # editable, from a checkout
pip install -e ".[dev]"   # with pytest for the test suite
```

Or as a host dependency, straight from git:

```
jeles @ git+https://github.com/rudi193-cmd/jeles@main
```

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

Tools: `corpus_ask`, `corpus_search`, `corpus_get`, `corpus_list`, `corpus_put`, `corpus_gaps` — each takes an `app_id` for naming-convention parity with willow-mcp.

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
| `ASK_JELES_USE_WILLOW_MCP` | `1` | Set to `0`/`false`/`no` to disable fleet gap-forwarding entirely. |

The Ask Jeles-flavored defaults are preserved so an existing store and its
already-forwarded fleet backlog keep resolving after the extraction.

## Tests

```bash
pytest -q
```

`corpus.py`'s tests are fast and network-free by construction; the
willow-mcp client tests never spin up a real subprocess. An import-purity
test asserts that importing `jeles.corpus` loads no MCP or network modules.

## License

Apache-2.0 — see [LICENSE](LICENSE).
