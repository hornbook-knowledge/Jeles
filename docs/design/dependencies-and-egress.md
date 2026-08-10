# Zero dependencies, and the egress posture that follows from it

*Status: LOCAL — this document describes this package's own architecture. It
is not a pointer to an upstream doc; nothing outside this repository was found
naming this specific rationale, so it is written directly from the code and
comments cited below.*

*Companions: `pyproject.toml` (`dependencies = []`) · `jeles/_egress.py` (the
one URL-opening implementation) · `jeles/sources.py`, `jeles/institutional.py`,
`jeles/reactions/search_adapter.py` (its three call sites) ·
`tests/test_import_purity.py`, `tests/test_egress.py`,
`tests/test_no_registered_source_requests_over_plain_http` (in
`tests/test_sources.py`)*

---

## 1. `dependencies = []` — confirmed, and why it is load-bearing

`pyproject.toml`'s `[project]` table declares:

```toml
dependencies = []
```

with this comment directly above it:

> Zero runtime dependencies, on purpose. `corpus.py`, the persona, and the
> reactions (including `search_adapter`'s urllib egress) are stdlib-only, and
> `tests/test_import_purity.py` enforces it. That is what lets a host —
> willow-mcp above all — depend on `jeles` without inheriting a version
> constraint: pinning `mcp` here made `pip install willow-mcp jeles`
> unresolvable, because willow-mcp requires `mcp>=2` while this package
> required `mcp<2`.

This is not an aesthetic preference; it is a load-bearing fact about
installability. The one place this package genuinely needs a third-party
package — the MCP SDK, for `jeles.corpus_server` — is walled off behind the
`jeles[mcp]` optional-dependencies extra rather than pulled in by default. The
`README.md` states the consequence plainly: "Base `jeles` has zero runtime
dependencies... so a host can depend on this package without inheriting a
single version constraint from it." `corpus_server.py` itself raises a
deliberate, named `ImportError` — distinguishing "the MCP SDK isn't installed
at all" from "SDK 1.x is installed, and `mcp.server.mcpserver` doesn't exist
there" — rather than letting either failure surface as a bare traceback.

Two consequences fall out of "zero runtime dependencies" once it is taken
literally:

1. **No third-party HTTP client.** `requests`, `httpx`, and similar are exactly
   the kind of dependency this promise forbids, so every module that makes a
   network call in this package (`sources.py`, `institutional.py`,
   `reactions/search_adapter.py`) is built on `urllib.request` — a stdlib
   module with a genuinely awkward API for the guarantees this package needs
   (bounded reads, scheme enforcement across redirects, destination checks).
   `jeles/_egress.py` exists because that awkwardness, handled ad hoc at each
   call site, is exactly how the bugs in §2 happened.
2. **No I/O, and no network state, at import.** `tests/test_import_purity.py`
   enforces that importing `jeles` — and its submodules — costs nothing.
   `_egress.py`'s own docstring names the specific reason this matters for
   egress in particular: `ProxyHandler()` "snapshots the proxy environment when
   it is constructed," so an opener built at import time would freeze whatever
   `HTTPS_PROXY` happened to be set (or unset) at process start, rather than
   respecting an operator's environment as it exists when a request is
   actually made. `_egress.opener()` is built lazily and cached
   (`_OPENERS`), keyed on the scheme policy in effect, so this stays true no
   matter which module calls it first.

## 2. `_egress.py` — one guard, because three copies of it disagreed

`jeles/_egress.py`'s module docstring states the origin directly: three
modules do raw egress — `sources` (the institutional fan-out),
`reactions.search_adapter` (the open-web hop), and `institutional` (the
optional remote delegate) — and each had grown its own scheme check, and each
had gotten the same two things wrong, "because a rule written out three times
is a rule enforced nowhere":

- The check ran once, on the URL the caller built, but `urllib` follows 3xx
  redirects *inside* `urlopen`, so a redirect target was never inspected.
  Reproduced: a 302 to `ftp://` landed a live TCP connection with `urlopen`'s
  default handler set.
- The docstring next to each copy described a policy the code did not actually
  implement.

So the guard now lives once, in `_egress.py`, and each call site differs by
exactly one argument: which schemes it allows.

### The three lanes, and why they differ

| Lane | Module | Schemes | `allow_private` | Why |
|---|---|---|---|---|
| Institutional fan-out | `sources.py` | `HTTPS_ONLY` | never | "aimed at an address the operator chose" is not true here — it is aimed at sixty-plus hardcoded public APIs, so nothing needs plain `http`, and the stricter policy is the free one. |
| Open-web search | `reactions/search_adapter.py` | `HTTP_OR_HTTPS` | per-call, `True` only for the SearXNG backend | the sovereign, self-hosted default (`JELES_SEARXNG_URL=http://127.0.0.1:8888`) is a private address the *operator* configured, and refusing it "would break the sovereign, self-hosted case this package is built around." Brave/Tavily/DuckDuckGo — hardcoded public APIs with no such claim — go through the same function with `allow_private=False`. |
| Institutional remote delegate | `institutional.py` | `HTTP_OR_HTTPS` | `True`, for the same reason | `JELES_REMOTE_URL` is a deployment the operator points at, which may legitimately be on a private network. |

`_egress.py` names the resulting trade-off rather than hiding it: on the two
`HTTP_OR_HTTPS` lanes, "a hostile redirect can still downgrade https -> http."
The docstring's instruction is to narrow the allowed set at the call site if a
given deployment cannot afford that.

### What the destination check (`private_destination`) closes

A scheme guard says *how* a request travels, never *where*. Before
`private_destination` existed, "a redirect from a source could reach any https
address — including `169.254.169.254`, the cloud metadata endpoint, and
`127.0.0.1:8888`," per `_egress.py`'s docstring. The function resolves
hostnames rather than pattern-matching them (`evil.example` with an A record of
`127.0.0.1` is the obvious bypass of a name-only check — and it is a real hole
named in willow-mcp's own fetch guard, per the same docstring), and rejects
private, loopback, link-local, reserved, multicast, unspecified, and
non-global addresses. Two specific parsing bugs are called out and fixed in the
same module, both reproduced against a real request rather than theorized:

- **Two disagreeing parsers.** `urlsplit(url).hostname` does not
  percent-decode; `urllib.request.Request(url).host` does. A URL like
  `https://127.0.0%2e1:8888/` read as the opaque name `127.0.0%2e1` to one
  parser and the address `127.0.0.1` to the socket — eleven variants got past
  a check that trusted only one view. `_dialled_hosts` now collects both views
  and requires every one of them to be acceptable.
- **Alternate literal encodings.** `2130706433`, `0177.0.0.1`, and `127.1` are
  all read by `getaddrinfo` (and therefore the socket) as `127.0.0.1`, but
  `ipaddress.ip_address` rejects all three — so a naive check waved them
  through as unrecognized "names." `_as_address` does the same arithmetic
  `inet_aton` does, locally, closing that gap on the two paths where no DNS
  lookup happens (behind a proxy, and offline).

`SchemeGuardedRedirects` re-applies both the scheme and the destination check
on *every* redirect hop, not just the first URL — closing the "checked once,
followed silently" pattern that motivated the whole module — and additionally
strips authenticating headers (`Authorization`, `X-Jeles-Secret`,
`X-Subscription-Token`, `X-Api-Key`, …) when a redirect changes host, after a
reproduced case where a redirect from a configured `JELES_REMOTE_URL` to
`http://attacker.example` carried the shared secret along, cross-host, over
plaintext.

## 3. What this buys, concretely

- `jeles.corpus` — the pure storage/ranking core — never imports `_egress` at
  all (`_egress.py`'s own docstring states this as a rule, and
  `tests/test_import_purity.py` is what enforces it): nothing in storage needs
  network egress, so nothing in storage is allowed to import the module that
  provides it.
- A host that only wants the corpus (`pip install jeles`) gets a package with
  no third-party code running at all, importable with no network access and no
  proxy configuration required.
- A host that wants the reactions or the institutional fan-out gets one, single
  egress implementation underneath both, rather than three independently
  drifting copies of the same intended policy — which is the bug class this
  module exists to retire, stated in its own first paragraph.
