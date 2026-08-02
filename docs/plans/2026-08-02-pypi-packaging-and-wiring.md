# Plan — PyPI packaging and wiring Jeles into willow-mcp

Date: 2026-08-02
Branch: `claude/world-meltdown-investigation-pjhwe8`
Status: **proposed** — steps 1 and 2 not yet executed.

The goal: get standalone Jeles built, published, and consumed by willow-mcp as a
PyPI dependency the same way `kartikeya` already is — and then get the verified
information path actually moving.

---

## 0. Findings that shaped this plan

Measured on 2026-08-02 against a clean venv, not assumed:

| Check | Result |
|---|---|
| `python -m build` | `jeles-0.1.0.tar.gz` + `jeles-0.1.0-py3-none-any.whl` — clean |
| `twine check` | PASSED, 2 cosmetic warnings (`long_description` missing) |
| `pytest` | 53 passed in 0.68s |
| `pytest` **with `mcp` uninstalled** | 53 passed in 0.62s |
| PyPI name `jeles` | 404 — free |
| PyPI `kartikeya` / `willow-mcp` | 200 / 200 — both published |

The package half is in better shape than expected. Two blockers stand between
it and being consumable.

### Blocker A — the `mcp` pin conflict (hard)

```
jeles       mcp>=1.6.0,<2.0.0     (resolves 1.29.0)
willow-mcp  mcp>=2.0.0,<3.0.0
```

The ranges are disjoint. `pip install willow-mcp jeles` cannot resolve, so
willow-mcp cannot take jeles as a dependency today. This is a resolver error,
not a design objection.

### Blocker B — no release path

`.github/workflows/` holds `tests.yml` and `dependabot-automerge.yml` only.
Nothing tags, builds, or ships. Release metadata (`readme`, `authors`,
`keywords`, `classifiers`, `urls`) is also absent, so the PyPI landing page
would render blank.

### The shape of the fix

Only two modules need `mcp` at all:

- `corpus_server.py:29` — `from mcp.server.fastmcp import FastMCP`, top-level.
  The one hard requirement.
- `willow_mcp_client.py:103` — imports `mcp` **lazily inside a function**, and
  is fail-soft by contract. It already degrades correctly with no `mcp` present.

`corpus.py`, `persona/`, and `reactions/` (including `search_adapter`'s urllib
egress) are stdlib-only, and `tests/test_import_purity.py` already enforces it.
No test imports `mcp` — the full suite passes with it uninstalled.

So `mcp` can become an optional extra, leaving base `jeles` with **zero runtime
dependencies** and no version surface to conflict with anything. That is a
stronger package than the kart precedent, not a weaker one: `kartikeya` must be
a hard dependency of willow-mcp because it *is* the task executor. Jeles does
not have to be.

---

## 1. Step one — `mcp` becomes an optional extra

Unblocks everything else. Small, mechanical, independently valuable.

**`pyproject.toml`**

```toml
dependencies = []                       # was: ["mcp>=1.6.0,<2.0.0"]

[project.optional-dependencies]
mcp = ["mcp>=1.6.0,<2.0.0"]
dev = ["pytest>=8.0", "jeles[mcp]"]     # dev keeps mcp so the server stays exercisable
```

**`jeles/corpus_server.py`** — guard the top-level import so a missing extra
yields a sentence rather than a traceback:

```
ImportError: jeles.corpus_server needs the MCP client library.
Install it with:  pip install "jeles[mcp]"
(the corpus, persona, and reactions work without it)
```

**`tests/test_import_purity.py`** — extend from the module-level claim
(`jeles.corpus` loads no MCP or network modules) to the packaging-level one
(base `jeles` declares zero runtime dependencies). This turns "we do not
conflict with willow-mcp" from a fact into an invariant with a test behind it.

**`.github/workflows/tests.yml`** — `pip install -e . pytest` becomes
`pip install -e ".[dev]"`, plus a matrix leg that installs bare `.` to prove the
no-extra path stays green. That leg is the point of the whole change.

**`README.md`** — the Install section documents
`jeles @ git+https://github.com/rudi193-cmd/jeles@main`, which would silently
stop shipping `mcp`. This is the one genuine breaking change for existing
consumers and must be called out, not just edited.

### Acceptance

1. Clean venv, `pip install .` → 53 tests pass; `python -m jeles.corpus_server`
   gives the friendly ImportError.
2. Clean venv, `pip install ".[mcp]"` → server starts.
3. Resolve `jeles` against the local `willow-mcp` checkout and confirm the two
   co-install. **This is the real acceptance test for the task.**

---

## 2. Step two — release metadata and a publish workflow

**`pyproject.toml`** gains `readme = "README.md"` (clears both twine warnings and
the blank landing page), `authors`, `keywords`, `classifiers`, and
`[project.urls]` — mirroring willow-mcp's block, adjusted for
`requires-python = ">=3.10"`.

**`.github/workflows/publish.yml`** — tag-triggered, `needs: test`, OIDC trusted
publishing, no long-lived token in repository secrets.

### Two steps that require a human

1. **Trusted publishing needs a pending publisher created on pypi.org**, tying
   the project name to this repo and workflow filename. The workflow can be
   written now; without that one-time click the first tag push fails at upload.
2. **`kartikeya`'s publish workflow was not consulted** — the kart repo is not
   in this workspace. This plan writes to the standard pattern rather than
   matching the fleet's. Add the repo if they should be identical.

**Nothing is published by this plan.** Build and twine-check only; the tag stays
unpushed. Claiming an unused name on PyPI is a one-way door and belongs to the
operator, not to a commit log.

---

## 3. Step three — the layering decision (the actual work)

Steps 1 and 2 do not make the verified-information path move. They make it
*possible* to move. This step is the one that matters.

The librarian currently exists three times:

| Implementation | What it is | Wired into willow-mcp? |
|---|---|---|
| `rudi193-cmd/Jeles` | local verified corpus, SQLite, stdlib | **no** |
| `jeles-remote` (Fly.io) | ~65 institutional/academic sources, stateless | **yes** — `integrations.JelesAdapter`, `X-Jeles-Secret` |
| `willow_mcp/web_search.py` | DDG HTML scrape + ~60-entry `_TRUSTED_SUFFIXES` | yes |

willow-mcp already has a jeles lane — the remote one. Adding the package gives
it two, so this is a layering decision, not a dependency line.

This repository's README already specifies the answer: *"The corpus sits in
front of live search, it doesn't replace it."*

```
question
   ↓
local verified corpus       confident nugget hit → answer instantly, no network, no LLM
   ↓ miss
jeles-remote fan-out        ~65 institutional/academic sources, citable
   ↓ still nothing
gap log                     the corpus records what it was asked and could not answer
```

Two consequences worth naming:

- **This closes the open egress question.** Routing the searcher through
  `JelesAdapter` means egress passes willow-mcp's three-key gate instead of
  `search_adapter`'s raw urllib. The gated searcher that `search_adapter`'s
  docstring tells operators to inject already exists — it simply is not
  connected.
- **It also fixes the silent-failure pairing.** Today a lapsed egress lease and
  a fail-soft `[]` compose into empty results that look like "nothing found."
  A miss that reaches the gap log is a recorded edge, not a silent no-op.

---

## Register

Carried from the session that produced this plan. Items 0a and 0b are context,
not work items.

- **0a.** The state of the human world. Named, not filed.
- **0b.** Reach — Apache-2.0 is a bet that someone outside this workspace picks
  the software up. Licensing is done; the adoption path is the open part.
- **1.** Jeles' web edge is unreachable from its own MCP server.
- **2.** Zero-config search default is DDG Instant Answer — shallow, fails soft,
  looks alive.
- **3.** Three-key egress friction in local (manifest `web_net` + standing
  `consent.internet` + a 30-minute CLI-minted lease + optional strict trust
  root).
- **4.** Jeles' egress posture undecided: raw urllib vs. gated.
- **5.** No `docs/` in this repo. *(This document opens it.)*
- **6.** Trusted-source registry split between `willow_mcp/web_search.py` and
  `core/jeles_sources.py`, which standalone Jeles does not own.
- **7.** The `mcp` pin conflict. **→ step 1**
- **8.** Release metadata and publish workflow. **→ step 2**
- **9.** Reconcile the three Jeles implementations. **→ step 3**
