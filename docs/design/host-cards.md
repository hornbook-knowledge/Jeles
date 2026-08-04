# Host cards — a preloaded catalog of the sites and APIs jeles touches

*Status: **DRAFT** — 2026-08-04. No code. Supersedes nothing yet; `SOURCES[*].hosts`
stays authoritative until a migration lands.*

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
- **`observed`** — machine facts, curator sets `checked`, a probe fills the rest.

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
  "observed": {                    // curator sets `checked`; a probe fills the rest
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

## 6. Open questions

1. **Does this make jeles a catalog *and* a client?** Fleet-versioning Rule 2
   says jeles' public surface is its importable API. A card schema joins that
   surface, and a breaking card change becomes a jeles major. That is acceptable
   but it should be a decision, not a discovery.

2. **Who probes?** `observed.reachable` needs something to fill it. jeles is
   stdlib-only and its egress is guarded — a probe script under `tools/` run in
   CI on a schedule is the cheap answer, but a CI job that makes 84 outbound
   requests on a cron is a posture change worth stating out loud.

3. **Is `custody` four values or three?** `commercial` and `aggregator` differ in
   provenance but usually land on the same side of any policy. Splitting them is
   cheap now and expensive later; merging them is the reverse.

4. **What about hosts jeles does not touch?** 46 of 65 sources emit URLs built
   from API responses, pointing anywhere. Cards do not solve that, and should not
   pretend to. The durable answer is that jeles results already carry `source`
   and `institution`, so a consumer never needs the hostname heuristic for
   them — `trusted_only` stays a heuristic for the genuinely open web, labelled
   as one. That is a separate change and it is the larger half of the problem.

5. **`doi.org` is `aggregator` but resolves to publishers.** A DOI link is a
   redirect to wherever the publisher put it. Does the card describe the resolver
   or the destination? Proposed: the resolver, with `notes` saying so — because
   the destination is unknowable, which is question 4 again.
