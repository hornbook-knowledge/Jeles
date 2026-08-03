# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Entries below 0.2.0 were written by hand. From 0.2.0 onward this file is
maintained by release-please, which builds each entry from the
conventional-commit prefixes on `master` — so it cannot go stale between
releases the way a hand-kept changelog can.

## [0.3.0](https://github.com/rudi193-cmd/Jeles/compare/v0.2.1...v0.3.0) (2026-08-03)


### Added

* give the corpus server its second hop — the open web ([dd187e4](https://github.com/rudi193-cmd/Jeles/commit/dd187e4641a1bf5c4c2d59048e7a3122d94735df))
* give the corpus server its second hop — the open web ([79342ed](https://github.com/rudi193-cmd/Jeles/commit/79342ed0c8905431b3819f440c3be9ffefa46013))

## [0.2.1](https://github.com/rudi193-cmd/Jeles/compare/v0.2.0...v0.2.1) (2026-08-03)


### Fixed

* extras went to the wrong jobs — no-extras is pure again ([3006ed9](https://github.com/rudi193-cmd/Jeles/commit/3006ed94268fc9150c68b00667d64e2b54088595))
* make the search edge say why it found nothing ([68b103b](https://github.com/rudi193-cmd/Jeles/commit/68b103be2c62098115c1e12509c6329a6600f8b8))


### CI

* add a workflow_dispatch recovery path to release.yml ([9569d2a](https://github.com/rudi193-cmd/Jeles/commit/9569d2a0d9203b8f2f6647e7d183cba87d4ae800))
* call release.yml from release-please instead of hoping to trigger it ([ecb40d9](https://github.com/rudi193-cmd/Jeles/commit/ecb40d96f2d9b65a217af8d6a2f3f31b81bfbd6a))
* coverage floor at 80 — measured 85.8%; tests run with the SDK ([e9328c9](https://github.com/rudi193-cmd/Jeles/commit/e9328c9ca88881e273764819b9cceea77cdbc86b))

## [0.2.0](https://github.com/rudi193-cmd/Jeles/compare/v0.1.0...v0.2.0) (2026-08-03)


### Added

* port corpus_server to MCP SDK 2.0, and give it tests ([b8486a5](https://github.com/rudi193-cmd/Jeles/commit/b8486a5a9161616072531ac355a02ccbd6401e6a))


### CI

* automate releases with release-please ([0e7fa76](https://github.com/rudi193-cmd/Jeles/commit/0e7fa768e1666ee89fd5540161c709adccf57efc))
* fleet hardening — concurrency, lint cache, automerge fix ([fe6f3d2](https://github.com/rudi193-cmd/Jeles/commit/fe6f3d2cf147817efdf389d5bfd2cc9c2cdaf0b8))

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
