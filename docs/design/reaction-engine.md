# Reactions — `(event) -> [proposed actions]`

*Status: LOCAL — this document describes `jeles.reactions` as implemented in
this repository: the Jeles-resident half of a fleet-wide pattern. It is not a
copy of the fleet-level design; see §5 for where that lives.*

*Companions: `jeles/reactions/__init__.py` (the shape, stated once) ·
`jeles/reactions/conflict_scan.py` (the one shipped reaction) ·
`jeles/reactions/search_adapter.py` (its injected network edge) ·
`jeles/_independence.py` (the shared two-source rule) ·
`tests/test_conflict_scan.py`, `tests/test_search_adapter.py`*

---

## 1. The shape, and why it is enforced rather than prose

`jeles/reactions/__init__.py` states the pattern directly:

> A *reaction* is the enforced form of what used to be prose: instead of a
> skill telling an agent "you should go look at prior art," a reaction is a
> deterministic script that *does* it, on an event, and hands back proposed
> actions for a driver to execute.

Concretely, a reaction is a pure function of the form
`react(event, *, <injected dependencies>) -> list[proposal]`, where each
proposal is `{"driver": str, "reason": str, "args": dict}`. `react` never
executes anything itself — it only proposes. A separate function, `apply`,
takes the proposal list and a set of *injected drivers* and actually calls
them, returning one receipt per proposal.

This is the model-proposes / gateway-enforces pattern applied one layer down
from where a fleet usually applies it: the reaction is the "model" here (a
deterministic script rather than an LLM, but the same separation of concerns),
and `apply` is the gateway that decides what a proposal is actually allowed to
do.

## 2. `conflict_scan` — the one shipped reaction

`jeles.reactions.conflict_scan` is, per its own docstring, "the behavior this
scripts is the one hand-run in the 2026-07-24 design session: given a design
*claim*, search the web not for what's *similar* ... but for what *supersedes
or refutes* it, and hand back what you found." Three disciplines, all
deterministic and testable without a network:

1. **Conflict-biased query framing.** `frame_queries(claim)` builds four
   queries: one mirror/baseline ("existing implementation library") and three
   that hunt supersession, rivalry, and refutation specifically. The bias is
   deliberate — "a 'find things like this' search validates; a 'find what
   beats this' search carves the design down to the part nobody has already
   built."
2. **Two independent sources.** `_witnesses` filters the raw search hits down
   to ones that (a) resolve to a real, non-address domain, (b) are not a known
   non-witness (search engines, URL shorteners — see `_NON_WITNESS`, added
   after a reproduced case where DuckDuckGo's own related-topics endpoint
   satisfied a two-source bar about a claim invented on the spot), and (c)
   actually share a content word with the claim being scanned. Corroboration
   requires `>= min_sources` (`DEFAULT_MIN_SOURCES`, from
   `jeles._independence.MIN_INDEPENDENT_SOURCES`) *distinct registrable
   domains* among the survivors — not merely `>= min_sources` hits, since "two
   hits from the same site do not corroborate."
3. **Propose, don't execute.** `react()` is pure routing over an *injected*
   `searcher: (query) -> [{title, url, snippet}]`. It writes nothing. The
   network only exists behind that injection — "there is no network import at
   module load — so importing this module, and running `react()` with a fake
   searcher, is fast and offline. That is the same purity seam `jeles.corpus`
   holds."

### Proposal shapes

`react()` returns, most-actionable first:

- **`put_nugget`** — only when corroborated. Its `args` include
  `verification_kind: "machine"`, so the corpus rung it targets is
  `corroborated` (see `docs/design/corpus-rungs.md`).
- **`log_gap`** — when the finding is contested (0–1 independent sources): the
  corpus remembers it looked and could not yet verify.
- **`frank_append`** — emitted unconditionally, always last, "so every firing
  leaves one legible line regardless of outcome."

### The allowlist, and the exploit it closes

`apply()` does not simply splat a proposal's `args` into its driver. `_vet`
checks each proposal's `args` against a per-driver allowlist
(`_ALLOWED_ARGS`) before calling anything. The reason, recorded directly above
`_ALLOWED_ARGS` in `conflict_scan.py`, is a reproduced exploit: before the
allowlist existed, a hand-built proposal carrying `verification_kind: "human"`
plus an existing human-verified nugget's `nugget_id` would land on top of that
nugget and overwrite its answer — because `put_nugget`'s own downgrade guard
only refuses a *lower* rung overwriting a higher one, and `"human"` over
`"human"` is not lower. `apply`'s allowlist closes both holes: `nugget_id` is
not reachable from a proposal at all ("a reaction may add a nugget, never
replace one by id"), and `verification_kind` is pinned to `"machine"`
(`PROPOSAL_VERIFICATION_KIND`) rather than trusted from the proposal, "because
a proposal claiming... is already stopped there — but 'human' over 'human'...
sailed through."

A rejected proposal produces an error receipt rather than raising, "because
`apply` processes a *list*: one bad proposal must not take the good ones with
it."

## 3. `search_adapter` — the injected impurity, made concrete

`conflict_scan.react` never imports a search backend. `search_adapter.py` is
the default implementation of the `Searcher` it expects, kept in a separate
module specifically so the reaction's routing stays pure and offline-testable.
It is backend-pluggable (`JELES_SEARCH_BACKEND`: `searxng`, `brave`, `tavily`,
or `ddg`) and fail-soft — any network or parse error yields `[]`, which
`conflict_scan` already reads as "no witness → contested gap," never as
forged corroboration.

Its own docstring names a specific perimeter tradeoff worth restating here,
since it bears on how a reaction is meant to be deployed: this module does
*raw* egress (through `HTTPS_PROXY` if set), and "in a gated deployment, don't
use it — inject a searcher that routes through willow-mcp's three-key egress
instead. The whole point of the injected-searcher seam is that swapping this
out requires no change to the reaction." The module names this directly as
"the 'correct code, wrong perimeter' trap" from a 2026-07-24 red-team, rather
than leaving it implicit.

## 4. What is *not* yet here

This repository ships exactly one reaction. Nothing in this codebase currently
implements a general reaction *registry*, a dispatcher that routes arbitrary
event types to matching reactions, or reactions beyond `conflict_scan` — that
broader machinery, if it exists, is part of the fleet-level design named below,
not something this document can describe from code that isn't here.

## 5. Where the fuller design lives

The pattern this module implements one corner of — the reaction engine as a
fleet-wide concept, not just this package's corner of it — is
`willow/design/reaction-engine.md` in the `willow` charter repository, and
`jeles/reactions/__init__.py` names it explicitly as the design this code is
"the Jeles-resident half of." This document does not attempt to restate that
design; it describes only what `jeles.reactions` actually implements, sourced
from the code above. If the two disagree on anything outside this package's own
API, the fleet-level document is the one to trust.
