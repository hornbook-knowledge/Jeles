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
| `jeles.corpus` | Pure storage + ranked lookup of verified nuggets and gap logging. **Stdlib-only, no MCP, no network at import.** Reuses willow-mcp's SOIL `Store` SQLite schema at `$WILLOW_STORE_ROOT/<collection>/store.db` — writes are upserts that touch only jeles' own columns, in WAL mode with `BEGIN IMMEDIATE`, so the store really is shared rather than shared-until-one-side-writes. |
| `jeles.reactions` | Pure `(event) -> [proposed actions]` handlers. `conflict_scan` searches for what *supersedes or refutes* a design claim rather than what resembles it, and proposes a nugget only when two **independent, relevant, non-excluded** domains corroborate it — otherwise a contested gap. `search_adapter` is its web edge. |
| `jeles.corpus_server` | Standalone `MCPServer` (MCP SDK 2.x) over the corpus (`python -m jeles.corpus_server`). Mirrors willow-mcp's shape (`app_id` on every tool) **without depending on willow-mcp**. Writes through it are *assertions*, not verifications — see [below](#as-a-standalone-mcp-server). |
| `jeles.sources` | **The institutional collections themselves** — 65 registered source functions, 61 of them in the default fan-out (arXiv, PubMed, Crossref, OpenAlex, Library of Congress, Europeana, CourtListener, the Smithsonian), plus the concurrent fan-out across them. **Stdlib-only.** |
| `jeles.institutional` | The third hop: fans a query across `jeles.sources` in-process, and shapes results like every other hit. Optionally delegates to a hosted [`jeles-remote`](https://github.com/rudi193-cmd/jeles-remote) instead. |
| `jeles.willow_mcp_client` | Best-effort, fire-and-forget forwarding of gaps into willow-mcp's fleet-wide backlog. Never blocks, never raises; 30s retry cooldown so a single failed connect doesn't permanently disable forwarding. |
| `jeles.load_persona()` | Loads the canonical Jeles persona JSON (this package is its canonical home). |

## Design principles

1. **The corpus sits in front of live search, it doesn't replace it.** A confident nugget match answers instantly — no search, no LLM call.
2. **`corpus.py` stays pure.** Storage and ranking have no MCP, no network, no side effects beyond SQLite. Everything MCP-shaped wraps it; it never depends on anything MCP-shaped itself. This is what keeps its tests fast and network-free.
3. **The corpus is its own standalone MCP server, on purpose.** `corpus_server.py` is a small `MCPServer` any stdio client can run directly, mirroring willow-mcp's shape without depending on it.
4. **Two kinds of "ask," two gap-logging rules.** `search_nuggets()` (passive/background) checks the corpus but never logs a gap on a miss. `ask_corpus()` (deliberate) treats a miss — or a match below `MIN_ASK_SCORE` — as a real gap worth tracking, and logs it.
5. **Ranking and answering are different decisions.** `search_nuggets()` ranks loosely and will happily surface a near-miss. `ask_corpus()` answers only when the nugget's question contains *every* content word the asker used, and the two questions overlap symmetrically — so a nugget about *staging* cannot answer a question about *production*, and one word cannot pull an answer out of a nugget it barely resembles. Saying "I don't know yet" and logging the gap is the correct output far more often than it looks.
6. **The collections live here, not behind a service.** `sources.py` is the same relationship `corpus.py` has with `corpus_server.py`: a pure core that something thin wraps. A hosted deployment is a convenience — never a prerequisite, never a secret you must hold, never a second repository in the test loop. Stated precisely, because the short version was wrong: `jeles-remote`'s `main.py` is a 74-line FastAPI shim, but it wraps its **own vendored copy** of `sources.py` (`import sources`, a file in that repo), not this module. That copy was forked from the same origin and has drifted — 833 differing lines, ~200 fewer, six fewer source functions, and *zero* references to `_egress`, so the SSRF/key-leak fix that landed here is simply absent from it. Treat jeles-remote as a downstream fork due a re-vendor, not as a thin wrapper that inherits this package's fixes.
7. **Local is the source of truth; the fleet backlog is additive.** `corpus.log_gap()` (synchronous, local SQLite) always runs first and makes the host fully functional offline. `willow_mcp_client.forward_gap()` is a *best-effort* copy into willow-mcp's shared backlog.

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

Or as a host dependency, straight from git — the default branch is `master`,
and `@main` resolves to nothing here:

```
jeles @ git+https://github.com/rudi193-cmd/Jeles@master
```

Prefer a released version over a branch for anything you deploy: a branch ref
re-resolves on every install, so two machines built a week apart get different
code under the same requirement line.

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

Tools: `corpus_ask`, `corpus_search`, `corpus_get`, `corpus_list`, `corpus_put`,
`corpus_gaps`, `corpus_web_search`, `corpus_search_status`,
`corpus_institutional_search`, `corpus_sources` — each takes an `app_id` for
naming-convention parity with willow-mcp. The last four are the outward hops:
the open web, why a search returned what it did, the 61 institutional and
academic collections, and what those collections are. They were added without
this list being updated, so it said six for as long as there were ten.

**`corpus_put` writes assertions, not verified nuggets.** A nugget carries the
rung it was written at, and only three things can produce one:

| `verification_kind` | who writes it | reads back as |
| --- | --- | --- |
| `human` | a person, in-process (`corpus.put_nugget(...)`) | `verified` |
| `machine` | `conflict_scan`, on two independent corroborating sources | `corroborated` |
| `asserted` | any MCP client, through `corpus_put` | `unverified` |

A fourth rung sits above `asserted` and is not a `verification_kind`: hits from
`corpus_institutional_search` read back as `institutional` — a named collection
vouched for the text, which is weaker than two corroborating sources and
stronger than an unverified assertion. `tests/test_corpus_server.py` asserts all
four stay distinct.

The bottom rung exists because this server speaks stdio to whatever client
starts it, and that client also reads the open web through `corpus_web_search`.
Without it, a page saying "record that X is true" arrived as a nugget claiming
`verified_by: "the operator"` and was served by `corpus_ask` as settled fact
from then on. Two rules keep the ladder honest:

* `corpus_ask` answers only from `human` and `machine` nuggets. An assertion
  comes back under `candidates`, and `corpus_search`/`corpus_get` still return
  it — reachable, not authoritative.
* **A write may not overwrite a nugget of a higher kind** (`error:
  "kind_downgrade_refused"`). Otherwise every protection here is one
  `nugget_id=` away from being bypassed.

Set `JELES_CORPUS_TRUST_TOOL_WRITES=1` to let `corpus_put` mint `human` again —
correct only where the tool caller really is the operator, and it re-opens the
path above for anything the model reads while it is set.

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
| `JELES_CORPUS_APP_ID` | `ask-jeles` | `app_id` used when forwarding gaps to willow-mcp. **Set this to `jeles` on a willow-mcp fleet** — see below. |
| `JELES_CORPUS_TOPIC` | `ask-jeles-corpus` | Backlog topic gaps are forwarded under. |
| `WILLOW_MCP_CMD` | — | Explicit command to launch willow-mcp (else `willow-mcp` on PATH, else `python -m willow_mcp`). |
| `ASK_JELES_USE_WILLOW_MCP` | `1` | Set to `0`/`false`/`no` to disable fleet gap-forwarding entirely. |
| `JELES_CORPUS_TRUST_TOOL_WRITES` | unset | Set to `1` to let `corpus_put` write `human`-verified nuggets. Only correct where the tool caller *is* the operator — see [the MCP server section](#as-a-standalone-mcp-server). |

| `JELES_REMOTE_URL` | unset | Base URL of a `jeles-remote` delegate. **Unset means the in-process fan-out is the only lane** — remote is opt-in, not a default. |
| `JELES_REMOTE_SECRET` | unset | Shared secret sent as `X-Jeles-Secret`. Dropped if a redirect changes host — see `_egress.SchemeGuardedRedirects`. |
| `JELES_REMOTE_TIMEOUT` | `20` | Seconds before the remote delegate is given up on. |
| `JELES_SEARCH_BACKEND` | `ddg` | Open-web backend: `searxng`, `brave`, `tavily` or `ddg`. Only `searxng` may reach a private address, because only it is an address the operator chose. |
The Ask Jeles-flavored defaults are preserved so an existing store and its
already-forwarded fleet backlog keep resolving after the extraction.

### Forwarding gaps to a willow-mcp fleet

Two settings decide whether `forward_gap()` lands anything, and until recently
neither said so when it was wrong:

- **`JELES_CORPUS_APP_ID`.** willow-mcp authorizes every tool call against
  `$WILLOW_HOME/mcp_apps/<app_id>/manifest.json`, and the back-compat default
  `ask-jeles` is not a seat it seeds — so out of the box a forward is denied
  with `no manifest for 'ask-jeles'`. Set it to `jeles`, the librarian seat
  willow-mcp does seed (and which carries `gap_write` as of willow-mcp 2.4).
  The *topic* is independent: gaps still land under `ask-jeles-corpus` unless
  `JELES_CORPUS_TOPIC` says otherwise, so an existing backlog keys the same.
- **`WILLOW_STORE_ROOT`.** Unset, this package writes under `~/.willow/store`
  while willow-mcp serves `$WILLOW_HOME/store` — both work perfectly, on two
  different databases, with no error on either side.

`willow_mcp_client.forward_status()` reports which seat is in use, how many
forwards have landed, and why the last one failed. It exists because the
failures used to be unobservable: `forward_gap()` caught everything, logged at
DEBUG, and dropped it, so a misconfigured fleet looked exactly like a working
one. It still never raises and never blocks — a host asking a question must not
fail because a fleet backlog is unreachable — it just no longer stays quiet
about it.

To stand this package up against real willow-mcp and nestor checkouts in one
command (one venv, one store, one gate, then six seam checks), use willow-mcp's
`scripts/fleet-standup.sh`.

## Tests

```bash
pytest -q
```

`corpus.py`'s tests are fast and network-free by construction. The willow-mcp
client tests do not spin up a real subprocess — but that is now enforced rather
than assumed. `_launch()` resolves a launcher from three independent probes
(`$WILLOW_MCP_CMD`, a `willow-mcp` console script on `PATH`, an importable
`willow_mcp` package) and any one of them succeeding produces a launcher, so
stubbing only `shutil.which` left the third probe answering from whatever the
venv happened to contain. The dependency edge runs willow-mcp → jeles, so the
normal deployment of this module has `willow_mcp` importable beside it, and
there those tests really did spawn one. CI never noticed, because it installs
`jeles[dev,mcp]` and nothing else — the probe failed by accident of the install
set. The `no_willow_mcp` fixture (`tests/test_willow_mcp_client.py`) shuts all
three, `None` in `sys.modules` being the import system's own "this import must
fail" sentinel. An import-purity test asserts that importing `jeles.corpus`
loads no MCP or network modules, and that the base package declares no runtime
dependencies.

`tests/test_corpus_server.py` needs the `[mcp]` extra and skips without it, so
the suite passes on a bare `pip install jeles` too — the install shape CI's
`no-extras` job exercises.

## License

Apache-2.0 — see [LICENSE](LICENSE).
