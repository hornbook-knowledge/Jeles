"""_egress — the one definition of "how this package opens a URL".

Three modules do raw egress: `sources` (the institutional fan-out),
`reactions.search_adapter` (the open-web hop) and `institutional` (the remote
delegate). Each grew its own scheme check, and each got the same two things
wrong, because a rule written out three times is a rule enforced nowhere:

* The check ran once, on the URL the caller built. urllib follows 3xx *inside*
  `urlopen`, so a redirect was never inspected. Reproduced against a listening
  socket with `build_opener`'s default handler set: a 302 to `ftp://` landed a
  TCP connection on the target.
* The docstring beside it described a policy the code did not implement.

So the guard lives here, once, and the difference between call sites is one
argument: which schemes that site allows. Everything else — the redirect hop,
the handler set, the body cap — is identical by construction.

**Stdlib only, and no state at import.** Openers are built on first use, because
`ProxyHandler()` snapshots the proxy environment when it is constructed and
this package promises nothing happens at load. `jeles.corpus` must never import
this (see `tests/test_import_purity.py`); nothing here is needed for storage.
"""
from __future__ import annotations

import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable, Optional

#: What `sources` allows: TLS or nothing.
HTTPS_ONLY = frozenset({"https"})
#: What the two operator-pointed lanes allow. Plain http stays reachable there
#: because both are aimed at an address the operator chose — a SearXNG instance
#: on `http://127.0.0.1:8888` is the documented zero-config default, and a
#: `JELES_REMOTE_URL` on a private network is a legitimate deployment. Refusing
#: it would break the sovereign, self-hosted case this package is built around.
#: It is a real trade: on those two lanes a hostile redirect can still downgrade
#: https -> http. Narrow the set at the call site if a deployment can afford to.
HTTP_OR_HTTPS = frozenset({"http", "https"})


def scheme_ok(url: str, allowed: Iterable[str]) -> bool:
    return urllib.parse.urlsplit(url).scheme.lower() in set(allowed)


class SchemeGuardedRedirects(urllib.request.HTTPRedirectHandler):
    """Re-applies the scheme check on every redirect hop.

    stdlib's own filter lives in `http_error_302` and permits http, https *and
    ftp*; `file:` and `data:` it already rejects. So ftp is the hop it lets
    through, and — for an https-only caller — so is a silent https -> http
    downgrade. Both are closed here.
    """

    def __init__(self, allowed: frozenset[str]) -> None:
        super().__init__()
        self.allowed = allowed

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # `newurl` is resolved against the request URL upstream, so a relative
        # Location arrives here absolute and carries its scheme.
        if not scheme_ok(newurl, self.allowed):
            raise urllib.error.HTTPError(
                newurl, code,
                f"refusing redirect to a scheme outside "
                f"{sorted(self.allowed)}: {newurl[:60]!r}",
                headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENERS: dict[frozenset[str], urllib.request.OpenerDirector] = {}
_OPENER_LOCK = threading.Lock()


def opener(allowed: frozenset[str]) -> urllib.request.OpenerDirector:
    """The shared opener for one scheme policy, built on first use.

    Assembled by hand rather than with `build_opener`, which installs handlers
    for file:, ftp: and data:. With no handler for a scheme, a URL that somehow
    got past both checks has nothing able to open it — `UnknownHandler` raises
    `unknown url type: ...`. `HTTPHandler` is included only when plain http is
    allowed, so an https-only caller gets that structural backstop too.
    (Verified that omitting it leaves https-through-a-proxy unchanged: that
    path tunnels via `HTTPSHandler` and `ProxyHandler`.)
    """
    with _OPENER_LOCK:
        if allowed not in _OPENERS:
            handlers: list[Any] = [urllib.request.ProxyHandler()]  # honors HTTPS_PROXY
            if "http" in allowed:
                handlers.append(urllib.request.HTTPHandler())
            handlers += [
                urllib.request.HTTPSHandler(),
                SchemeGuardedRedirects(allowed),
                urllib.request.HTTPDefaultErrorHandler(),
                urllib.request.HTTPErrorProcessor(),
                urllib.request.UnknownHandler(),
            ]
            o = urllib.request.OpenerDirector()
            for h in handlers:
                o.add_handler(h)
            _OPENERS[allowed] = o
        return _OPENERS[allowed]


def urlopen(req: urllib.request.Request, *, allowed: frozenset[str],
            timeout: float):
    """Open a request, refusing a disallowed scheme on the first URL and on
    every redirect hop.

    Known gap, not fixed: stdlib drains the *redirect* response with an
    uncapped `fp.read()` before following it, so a body cap bounds the final
    response only. A 3xx with an endless body is still an endless body.
    """
    url = req.full_url if isinstance(req, urllib.request.Request) else str(req)
    if not scheme_ok(url, allowed):
        raise ValueError(
            f"refusing URL scheme outside {sorted(allowed)}: {url[:60]!r}")
    return opener(allowed).open(req, timeout=timeout)


def read_capped(resp: Any, max_bytes: int) -> bytes:
    """Read a bounded body. Every response is untrusted input, and an endpoint
    that starts streaming without end should fail, not exhaust memory."""
    raw = resp.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError(f"response exceeds {max_bytes} bytes — refusing")
    return raw


def fetch(url: str, *, allowed: frozenset[str], timeout: float, max_bytes: int,
          headers: Optional[dict] = None, data: Optional[bytes] = None) -> bytes:
    """Open and read in one call, so no caller ever holds a response it could
    read unbounded. This is the only shape that makes the cap structural rather
    than remembered — six of eight egress sites in `sources` had skipped it."""
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urlopen(req, allowed=allowed, timeout=timeout) as resp:
        return read_capped(resp, max_bytes)
