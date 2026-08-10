# The corpus rungs — a confidence ladder earned, not declared

*Status: LOCAL — this document describes what this repository implements. It is
not a copy of anything; see §5 for where the upstream product-level design doc
actually lives.*

*Companions: `jeles/corpus.py` (the ladder's mechanics — `_KIND_RANK`,
`_KIND_STATUS`, `put_nugget`'s downgrade guard) · `jeles/corpus_server.py` (the
four-rung statement, verbatim, in its module docstring) · `jeles/verify.py` (a
related but distinct two-source bar — see §4) · `jeles/reactions/conflict_scan.py`
(the one reaction that currently produces a `corroborated` write) ·
`jeles/_independence.py` (the shared two-source rule both `verify` and
`conflict_scan` apply) · `tests/test_corpus.py`, `tests/test_hardening.py`*

---

## 1. The ladder

`jeles/corpus_server.py`'s module docstring states it directly — the persona's
three hops (local KB → open web → special collections) each answer at a
different, fixed confidence:

```
verified > corroborated > institutional > unverified
```

Every hit this package produces — a nugget, a web result, an institutional
record — carries a `confidence` field drawn from this ladder
(`corpus.to_search_hit`, `corpus_server._web_hit`,
`institutional.search_institutional`'s hits). A caller merging results from
more than one hop is meant to be able to sort or filter on this field without
inspecting where each hit came from.

## 2. What may produce each rung

**`verified`** — a person wrote it, in-process. `corpus.put_nugget`'s
`verification_kind` defaults to `"human"`, and `_KIND_STATUS` maps `human` to
`status: "verified"`. Nothing reachable over a tool call can mint this rung
directly: `corpus_server.corpus_put` pins its writes to `"asserted"` unless the
operator has explicitly set `JELES_CORPUS_TRUST_TOOL_WRITES=1` for a session
where *they* are the one typing (see `corpus_put`'s docstring). Promotion to
`verified` is, in the module's own words, "deliberately not reachable from any
tool."

**`corroborated`** — independent sources agreed, and a machine said so.
`verification_kind: "machine"` maps to `status: "corroborated"`.
`jeles.reactions.conflict_scan` is the one shipped producer: `react()` searches
for what *supersedes or refutes* a design claim, counts the distinct
registrable domains among the hits that actually mention the claim
(`_witnesses`), and proposes a `put_nugget` write only when that count clears
`MIN_INDEPENDENT_SOURCES` (2, from `jeles._independence`). The rung is pinned by
the *driver*, not carried in the proposal — `_vet` in `conflict_scan.py`
refuses any proposal that tries to set a different `verification_kind`, because
a proposal is "assembled from web-search results, so what one carries is a
claim, and a claim must not be able to name its own place on the ladder."

**`institutional`** — the third hop's own rung, sitting (per
`corpus_institutional_search`'s docstring) "between a corpus nugget's
`verified`/`corroborated` and the open web's `unverified`." Anything returned
by `jeles.institutional.search_institutional` — the in-process fan-out across
`jeles.sources`'s ~65 registered institutional and academic collections
(arXiv, PubMed, Crossref, OpenAlex, Library of Congress, Europeana,
CourtListener, the Smithsonian, …) — is labelled `confidence: "institutional"`.
It is neither a human-checked nugget nor a random web page, and collapsing it
into either rung "would discard the only thing this hop is for."

**`unverified`** — everything else. Two distinct producers land here:

- `corpus_server.corpus_web_search` results (`_web_hit` hardcodes
  `confidence: "unverified"` on every hit) — the open web, the second hop,
  where "the librarian's no-unsourced-output rule [is] expressed as data rather
  than as a warning in prose."
- Nuggets written with `verification_kind: "asserted"` — a claim that arrived
  over a tool call and that nobody has checked. `corpus.py`'s own comment on
  `_KIND_RANK` explains why this rung exists at all: `corpus_put` is reachable
  by any MCP client, "and an agent that has just read the open web is one of
  them. Without a rung below `machine`, a page saying 'record that X is true'
  laundered straight into the top rung and `corpus_ask` served it as verified
  from then on — persistently, and on a store shared with willow-mcp."

An asserted nugget still shows up in `search_nuggets`/`get_nugget`/`corpus_get`,
and among `ask_corpus`'s `candidates` — it is reachable, just not authoritative.
`ask_corpus` will not answer *from* one unless the caller opts in with
`include_asserted=True`, because `found: true` from that function "is the
settled layer speaking, and a caller that reads only `nugget["answer"]`... would
have no way to tell otherwise."

## 3. A rung is earned, not declared

Two mechanisms enforce that a write cannot simply assert its way up the ladder:

1. **`put_nugget` refuses a downgrade.** "A write may not overwrite a nugget of
   a higher kind" — `_KIND_RANK` orders `asserted (1) < machine (2) < human
   (3)`, and any write whose kind ranks below the existing nugget's is refused
   with `error: "kind_downgrade_refused"`. Without this, "every protection here
   is one `nugget_id=` away from being bypassed."
2. **The driver, never the caller, sets the rung.** `corpus_server.corpus_put`
   computes `kind` itself (`"human"` only under the trust-writes env var, else
   `"asserted"`) rather than accepting it as a parameter. `conflict_scan.apply`
   does the same in reverse: `_vet` pins `verification_kind` to `"machine"` and
   rejects a proposal that asks for anything else, rather than trusting
   whatever a proposal — built from search-engine output — happened to name.

## 4. A related but distinct ladder: `jeles.verify`

`jeles/verify.py` also produces a three-way verdict — `corroborated` /
`single_source` / `unsupported` — and it is easy to conflate with the corpus
rungs above. They are not the same question. `verify.verify_claims` runs
*after* an answer already exists, decomposes it into atomic claims, and asks
"does every claim in this answer have `min_institutions` distinct institutions
behind its citations" — evidence already retrieved by someone else.
`conflict_scan.react` runs *before* anything is written, and asks "does a fresh
web search for this claim turn up independent corroboration" — evidence it goes
and gets itself. Per `verify.py`'s own docstring: "Same bar, opposite ends of
the pipeline, different evidence; neither subsumes the other." What the two
share — the two-source bar and the domain-identity rule behind "distinct" — is
factored into `jeles._independence` precisely so it is defined once rather than
drifting between them.

## 5. Where the fuller design lives

The narrative version of this — written for the Ask Jeles product rather than
for this package's own API surface — is `apps/ask-jeles/docs/design/verified-corpus.md`
in the `safe-app-store` repository. This document is not a summary of that one;
it is the corpus rungs as this package actually implements them, sourced from
the docstrings above. If the two ever disagree, this repository's code is the
one that runs.
