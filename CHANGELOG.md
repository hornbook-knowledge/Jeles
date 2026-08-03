# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Entries below 0.2.0 were written by hand. From 0.2.0 onward this file is
maintained by release-please, which builds each entry from the
conventional-commit prefixes on `master` — so it cannot go stale between
releases the way a hand-kept changelog can.

## [0.1.0] — 2026-08-02

First published release. The verified-corpus organ extracted from the Ask Jeles
app into its own installable package, plus the canonical Jeles persona.

### Added
- **`jeles.corpus`** — pure, stdlib-only storage and ranked lookup of verified
  nuggets over willow-mcp's SOIL `Store` SQLite schema, with gap logging.
- **`jeles.corpus_server`** — a standalone MCP server over the corpus
  (`corpus_ask`, `corpus_search`, `corpus_get`, `corpus_list`, `corpus_put`,
  `corpus_gaps`), depending on nothing from willow-mcp.
- **`jeles.willow_mcp_client`** — best-effort, non-blocking forwarding of gaps
  into willow-mcp's fleet-wide backlog, with a retry cooldown.
- **`jeles.reactions.conflict_scan`** — the prior-art reaction: search for what
  *supersedes or refutes* a claim rather than what resembles it, and promote a
  finding only when two independent registrable domains corroborate it.
- **`jeles.reactions.search_adapter`** — the web-search edge, with `searxng`,
  `brave`, `tavily` and `ddg` backends, fail-soft to `[]`.
- **The canonical Jeles persona** and a deterministic prompt compiler, so hosts
  stop hand-carrying their own prose copies.

### Build
- **Zero runtime dependencies.** The MCP SDK moved to a `[mcp]` extra so a host
  can depend on `jeles` without inheriting a version constraint — `mcp` had been
  a hard dependency pinned `<2`, which made `pip install willow-mcp jeles`
  unresolvable.
- **The version is derived from the git tag** (`hatch-vcs`); `jeles.__version__`
  reads it back from installed package metadata, resolved lazily so
  `importlib.metadata` does not pull `socket` into a package that promises not
  to import network modules.

[0.1.0]: https://pypi.org/project/jeles/0.1.0/
