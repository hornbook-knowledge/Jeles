# Host cards — a preloaded catalog of the sites and APIs jeles touches

*Status: **DRAFT, shape agreed** — 2026-08-04. No code. Supersedes nothing yet;
`SOURCES[*].hosts` stays authoritative until a migration lands. The five
questions this draft opened are answered in §6; two smaller ones remain in §7.*

*Companions: `jeles/sources.py` (the registry) · `tests/test_source_hosts.py` (which
checks `hosts` against the code) · willow-mcp `src/willow_mcp/web_search.py`
(`_TRUSTED_SUFFIXES`) · willow-mcp `tests/test_trusted_sources.py` (the bridge)*

---

## 1. The problem, measured

`SOURCES[*].hosts` is one field answering three different questions, and nothing
in the tree distinguishes them. Classified by AST over `jeles/sources.py` —
strings reaching a `_result(url=…)` are *emitted*, everything else in a source
function is *requested*, XML namespace URIs are neither:

| Relationship | Hosts | Example |
|---|---:|---|
| **query only** — jeles sends a request here, never emits a link to it | 47 | `api.openalex.org`, `eutils.ncbi.nlm.nih.gov`, `export.arxiv.org` |
| **citation only** — jeles emits links here, never requests it | 17 | `doi.org`, `www.imdb.com`, `patents.google.com`, `pubmed.ncbi.nlm.nih.gov` |
| **both** | 19 | `archive.org` (`/advancedsearch.php` vs `/details/{id}`) |
| **namespace** — an XML namespace URI, not a network relationship at all | 1 | `www.loc.gov` |
| | **84** | |

So **36 hosts are citation-capable and 48 are not** — 57% of the set can never
appear as a result URL, because jeles never emits one.

**What that classification can and cannot see.** It reads string *literals*, so
it is exact about the URLs jeles hardcodes and blind to the ones it builds at
runtime. `chronicling_america` emits `item.get("url")`, which is a `www.loc.gov`
URL in practice and invisible here — so the counts are a lower bound on
citation-capability, never an upper one. That is the safe direction for the
generated first pass (§5): a host wrongly marked `query`-only is a missing
verdict, which the curation step catches, and it is the same blind spot as
question 4 below rather than a new one.

That matters because willow-mcp's `test_trusted_sources.py` demands a published
citability verdict for **every one of the 84**. Today that test went red because
jeles 0.6.0 recovered two sources, and the verdict it demanded first was on
`www.omdbapi.com` — a JSON API endpoint that cannot appear in a DuckDuckGo result
under any circumstances. The tripwire fires where it does not matter.

And it is silent where it does: **46 of the 65 sources build their citation URL
out of the API response**, so where a result *points* is not knowable from the
registry at all. OpenAlex or Crossref can legitimately return a link to any
publisher on earth. The list constrains the predictable minority and abstains on
the rest.

### 1.1 The `www.w3.org` bug is still live, under a different name

willow-mcp's trusted list was reworked because it had inherited `www.w3.org` from
arXiv's Atom namespace identifier and was treating it as an institution. That
instance was fixed. **The mechanism was not**, and it is still present:

```python
# search_gallica  — Bibliothèque nationale de France
ns_srw = "http://www.loc.gov/zing/srw/"

# search_ndl      — National Diet Library, Japan
for record in root.findall(".//{http://www.loc.gov/zing/srw/}recordData"):
```

Both sources declare `www.loc.gov` in `hosts`. Neither contacts it. It is the
SRW/Zing namespace URI — a string that identifies a schema, not a server.

It is harmless *here* only because loc.gov happens to be trusted for unrelated
reasons. `tests/test_source_hosts.py` checks `hosts` against the code and passes,
because the string genuinely is in the code. A field that cannot tell a request
from a namespace cannot catch this class, and one host is one accident away from
the next `w3.org`.

---

## 2. The proposal

**jeles ships a preloaded catalog of host cards. jeles keeps the cards; consumers
keep their own policy.**

A card records *properties of a site*. It does not record whether any particular
consumer should believe it — that stays downstream, because willow-mcp is not
jeles' only consumer and a second one should not inherit willow-mcp's opinions
along with its data.

The line: **the card holds facts about the host; the consumer holds facts about
its own use.** "Can any account edit this record" is a property of the site.
"Does that disqualify it for my citations" is a property of the caller.

### 2.1 Why here

- The data flows down the dependency graph. willow-mcp depends on jeles; jeles
  depends on nothing.
- jeles is the only party that *knows* which of its hosts is an endpoint and
  which is a destination, because jeles wrote the request. willow-mcp is guessing
  from the hostname's shape — which is how `api.` prefixes became a heuristic.
- The registry is already a proto-catalog, already machine-checked against the
  code by `tests/test_source_hosts.py`. Cards are an enrichment of data jeles
  already owns and already verifies.
- 84 hosts. The table is small; carrying it costs nothing.

### 2.2 Prior art in the org, deliberately reused

`almanac-template/schema/catalog-entry.schema.json` already solves most of the
shape, and its framing is the one this needs:

> An Almanac is an **open, versioned index of public data** — a catalog, not a
> data warehouse. Each entry is a human-reviewed, machine-validated record
> pointing to an [external source].

Fields worth borrowing outright:

- **`access.method: [web|api|bulk|s3|ftp]`** — the role distinction, already
  invented. No need to design it twice.
- **`publisher`**, annotated *"reference-piece only; carries NO weight in
  recovery ranking"* — the schema already separates the fact from the judgement,
  structurally. That is exactly the separation argued for above.
- **`jurisdiction.scope`** — `national` / `regional-bloc` / `multilateral` /
  `international-ngo`.
- **`observed`** — machine facts, written by a probe rather than a curator. Here
  that probe is `willow-bot`, out of jeles' process entirely (§6.2).

Borrow the shape, not the dependency: an Almanac entry describes a *dataset*, a
host card describes a *host*. Different entities, same discipline.

### 2.3 The monitoring argument, from today

jeles 0.6.1 hand-fixed two dead endpoints:

- `chroniclingamerica.loc.gov` — retired, 308-redirects to a 404. The source had
  been returning nothing at all, in a published package, silently.
- `search.patentsview.org` — DNS-dead since 2026. Every default fan-out spent a
  full timeout on a name that does not resolve.

Both were found by reading willow-2.0's issue log, not by anything in this repo.
An `observed` block plus a probe finds them the week they break. **The catalog is
not only a trust substrate — it is the thing that tells us the sources are
broken.**

---

## 3. Card schema (draft)

One card per **host**, not per source. `doi.org` serves 9 sources and
`www.loc.gov` serves 4; per-source cards would let 9 records disagree about one
host. Sources reference cards by hostname.

JSON, not YAML: jeles is stdlib-only and `yaml` is a dependency. Shipped as
package data so it is present in the wheel.

```jsonc
{
  "host": "www.imdb.com",          // the key. exact, lowercase, no trailing dot
  "roles": ["citation"],           // query | citation | namespace  (>=1)
  "publisher": "IMDb.com, Inc.",   // who runs it. reference-piece only
  "custody": "community",          // institutional | community | commercial | aggregator
  "jurisdiction": {"scope": "national", "country": "US"},   // optional
  "status": "live",                // live | degraded | retired
  "observed": {                    // written by willow-bot, never by jeles (§6.2)
    "checked": "2026-08-04",
    "reachable": true,
    "http_status": 200,
    "note": null
  },
  "notes": "Community-editable film database."
}
```

### 3.1 `roles` — the field that does the work

| Value | Meaning | Consequence |
|---|---|---|
| `query` | jeles sends requests here | no citability verdict is owed by anyone |
| `citation` | a result URL can point here | the only role a trust policy needs to consider |
| `namespace` | an XML namespace URI | **not a network relationship**; excluded from egress reasoning and from trust reasoning alike |

`namespace` exists solely so the `w3.org`/`loc.gov` class becomes a value rather
than an accident. A host whose only role is `namespace` should arguably not be in
`hosts` at all — but recording it is honest and catches it; deleting it silently
re-opens the question the next time someone parses SRW.

### 3.2 `custody` — the trust-relevant fact

| Value | Test | Examples |
|---|---|---|
| `institutional` | a named institution holds editorial responsibility for the record | `www.loc.gov`, `www.ebi.ac.uk`, `www.who.int` |
| `community` | anyone with an account can revise the record | `en.wikipedia.org`, `www.imdb.com`, `www.isfdb.org`, `www.openstreetmap.org` |
| `commercial` | a company's own service, no custodial claim over the record | `www.omdbapi.com`, `api.frankfurter.app` |
| `aggregator` | indexes others' records; custody stays upstream | `doi.org`, `api.crossref.org`, `api.openalex.org` |

This is a judgement, and it belongs in the card anyway, because it is a judgement
about *the site* and it does not vary by consumer. Whether `community` is
disqualifying is the consumer's call, and stays downstream.

Four values, decided — `commercial` and `aggregator` are not merged even though
they usually land on the same side of a policy. See §6.3.

---

## 4. What changes downstream

willow-mcp's `_TRUSTED_SUFFIXES` today is ~50 hand-typed registrable domains plus
an 8-entry `_NOT_TRUST_EVIDENCE` dict with prose reasons. With cards it becomes a
policy over fields, roughly:

> citable if `citation` in `roles` and `custody` in `{institutional}`, plus a
> named override list.

- The 48 non-citation hosts stop generating obligations entirely.
- IMDb and ISFDB answer themselves as `custody: community`. No paragraph needed.
- `www.w3.org` becomes structurally impossible: it was never a card, and if it
  were one it would be `roles: [namespace]`.
- The override list stays, and stays short — that is where a genuinely contested
  call lives, visibly, instead of being spread across a 50-entry tuple.

**willow-mcp does not lose authority.** It gains a substrate and keeps the
verdict. The bridge test survives, narrowed: *every card with `citation` in its
roles must be decided here.*

---

## 5. Migration

1. Generate a first pass of all 84 cards from the AST classification in §1 —
   `roles` is derivable mechanically, and that is the field that carries the
   measurable win.
2. `publisher` / `custody` / `jurisdiction` are curated, not generated. 84 rows
   is an afternoon.
3. `SOURCES[*].hosts` becomes a *view* over the cards, so
   `tests/test_source_hosts.py` keeps working unchanged and nothing downstream
   breaks on the day cards land.
4. Only then narrow willow-mcp's bridge test to `citation` hosts.

Steps 1–3 are additive and shippable as a minor. Step 4 is a separate willow-mcp
change, gated on a jeles floor bump.

---

## 6. Decisions

Five questions were left open in the first draft. All five were answered by the
repository owner on commit `6a08553`
([commitcomment-194973774](https://github.com/rudi193-cmd/Jeles/commit/6a08553d7ed8f9619aa77b896bef5fc581cd5f52#commitcomment-194973774),
2026-08-04). Recorded here with what each one settles, so the reasoning is not
re-derived.

### 6.1 The card schema is part of jeles' public surface — **yes**

Fleet-versioning Rule 2 gives each package a public surface whose breakage forces
a major, and jeles' is its importable API. **The card schema joins it.** A
breaking card change — removing a field, narrowing an enum, changing what a
`role` means — is a jeles major, on the same line as deleting a function.

Consequences worth stating rather than discovering:

- Adding a field or an enum value is a minor; removing or redefining one is not.
- `roles` and `custody` are enums a consumer branches on, so they carry the
  strongest compatibility promise in the file.
- willow-mcp's `docs/design/fleet-versioning.md` Rule 2 table names jeles'
  surface as "importable API". That row needs the card schema added to it, in
  willow-mcp, when cards land. **Follow-up, not done here.**

### 6.2 The probe is willow-bot's, not jeles' — **out of process entirely**

`observed.reachable` is filled out of process, by `willow-bot`. jeles **reads**
`observed` and never writes it: the cards ship with whatever the last curated
pass recorded and are refreshed out of band. That keeps a scheduled 84-request
outbound job out of a package whose egress is otherwise guarded and whose CI
makes no network calls at all — which is the right call regardless of what
follows.

**Corrected after reading the repo.** An earlier revision of this section said
willow-bot "already does this class of work". It does not. `rudi193-cmd/willow-bot`
at `26acee3` is a 65-line FastAPI **webhook receiver** for a GitHub App, plus
`loki/` (a watcher over local disk, git and Postgres), `losc/` (a fork-event
heuristic), and `integrations/fleet_bridge.py` (routes webhooks to local files).
Measured against what a card probe needs:

| Needed | Present |
|---|---|
| periodic execution | **No.** Event-driven. One systemd unit, `uvicorn bot:app`. `loki.watcher` has 15/30-min intervals but is a hand-run `python3 -m loki.watcher` loop over local disk and Postgres, not a unit and not network-facing. |
| outbound HTTP to arbitrary hosts | **No.** Every URL literal in the repo: `api.github.com` ×11, `github.com` ×3, `raw.githubusercontent.com`, `api.groq.com`, `api.cerebras.ai`, localhost. `losc/checker.py` uses `requests`, only against GitHub. |
| writing results back to a repo | **No.** Its sole GitHub write is `github_app.post_comment` — issue and PR comments. No commit, no push, no contents API. |
| reachability semantics (status, etag, hash) | **No.** Nothing of the kind. |

So the *seat* is right and the *machinery* is absent. What willow-bot does bring
is the two hard parts of the substrate: a real GitHub App identity with
installation tokens (`github_app.py`), which is what writing cards back would
authenticate as; and the `fleet_bridge` pattern of "the bot notices, a different
service acts" — it drops a `gitsync/trigger-<owner>-<repo>.flag` rather than
doing the work itself, which maps cleanly onto *probe, then open a PR against
jeles*.

Three pieces have to be built, and none of them is in this repo's scope:

1. A scheduled arm — a systemd timer, or a network arm on `loki.watcher`.
2. A prober that requests 84 arbitrary hosts. **This is the posture question,
   not a detail:** it puts general outbound egress inside a process that holds
   the GitHub App private key and is reachable from public ingress. Moving the
   job out of jeles did not dissolve that concern, it relocated it — and it
   lands somewhere with more to lose.
3. A write-back path, extending beyond `post_comment` to a PR against jeles.

Until those exist, `observed` stays as jeles ships it: present and empty.

### 6.3 `custody` keeps four values — **`commercial` and `aggregator` stay apart**

They usually land on the same side of any policy today, which is exactly why
merging them is tempting and wrong: the distinction is about *provenance*, and
provenance is the thing a future policy will want. `doi.org` indexing someone
else's record and `api.frankfurter.app` publishing its own rate are not the same
claim, and a consumer that only cares about "not institutional" can collapse them
in one line. The reverse — recovering a distinction thrown away in the schema —
costs a major (§6.1).

### 6.4 Provenance replaces the hostname heuristic — **agreed**

46 of the 65 sources build their citation URL out of the API response, so where a
result points is unknowable from the registry. Cards do not fix that and must not
pretend to.

The agreed direction: **jeles results already carry `source` and `institution`,
so a consumer never needs to infer trust from their hostname.** A Crossref hit is
citable because Crossref returned it, not because of what its URL looks like.
`trusted_only` stays a heuristic for the *genuinely* open web — a DuckDuckGo
result with no provenance attached — and is labelled as one.

This is the larger half of the problem and a separate change from cards. Cards
make the small half exact; this makes the big half unnecessary.

### 6.5 A `doi.org` card describes the resolver — **not the destination**

A DOI link is a redirect to wherever the publisher put it. The card describes the
resolver, `custody: aggregator`, with `notes` saying so. The destination is
unknowable, which is §6.4 again — and §6.4 is why that is acceptable rather than
a gap: a DOI arrives attached to the source that emitted it.

---

## 7. Still open

Nothing blocking. Two things this draft does not decide:

- **Card file layout.** One JSON file with 84 entries, or one file per host like
  `almanac-template`'s `catalog/<id>.yaml`? Per-file is friendlier to review
  diffs and to willow-bot writing single cards back; one file is simpler to load
  and cheaper in a wheel. Leaning per-file *because* of §6.2 — a bot writing one
  card should not rewrite a file holding 83 others.
- **Whether `namespace`-only hosts stay in `hosts` at all.** §3.1 keeps them and
  records the role. The alternative is dropping them, which is cleaner and
  silently re-opens the question the next time someone parses SRW.
