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

import ipaddress
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from typing import Any

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


#: Hostnames that name the local machine without being IP literals.
_LOCAL_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})


def private_destination(url: str) -> str | None:
    """Why this URL points somewhere only the host itself can reach, or None.

    A scheme guard says *how* a request travels, never *where*. Nothing here
    used to say where, so a redirect from a source could reach any https
    address — including `169.254.169.254`, the cloud metadata endpoint, and
    `127.0.0.1`, where this package's own corpus server listens. The initial
    URLs are hardcoded public APIs, so reaching those needs a hostile or
    compromised upstream, an open redirect, or DNS pointing a public name at a
    private address. Several sources are third-party conveniences rather than
    hardened institutions, which is enough to make that worth closing.

    Hostnames are resolved, not just pattern-matched: `evil.example` with an A
    record of `127.0.0.1` is the obvious way past a name-only check, and
    willow-mcp's own fetch guard — which inspects the literal host and stops —
    has exactly that hole.

    **Residual, stated rather than papered over:** resolving here and connecting
    afterwards is two lookups, so a name that answers public now and private a
    moment later still gets through. Closing that needs the connection pinned to
    the address that was checked, which urllib does not expose. This raises the
    cost from "set a DNS record" to "win a race", and no further.

    A name that does not resolve is allowed through — the connection is about to
    fail on its own, and refusing here would report the wrong reason.
    """
    host = (urllib.parse.urlsplit(url).hostname or "").strip("[]").lower()
    if not host:
        return None
    if host in _LOCAL_NAMES:
        return f"{host!r} names the local machine"

    candidates: list[str] = [host]
    try:
        ipaddress.ip_address(host)
    except ValueError:
        try:
            candidates = [info[4][0] for info in socket.getaddrinfo(host, None)]
        except OSError:
            return None

    for raw in candidates:
        try:
            addr = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_reserved or addr.is_multicast or addr.is_unspecified):
            via = "" if raw == host else f" (resolved from {host!r})"
            return f"{raw} is not a public address{via}"
    return None


class SchemeGuardedRedirects(urllib.request.HTTPRedirectHandler):
    """Re-applies the scheme *and* destination checks on every redirect hop.

    stdlib's own filter lives in `http_error_302` and permits http, https *and
    ftp*; `file:` and `data:` it already rejects. So ftp is the hop it lets
    through, and — for an https-only caller — so is a silent https -> http
    downgrade. Both are closed here.

    The destination check is the one that was missing entirely. A first URL is
    chosen by this package; a redirect target is chosen by whatever answered.
    """

    def __init__(self, allowed: frozenset[str], allow_private: bool = False) -> None:
        super().__init__()
        self.allowed = allowed
        self.allow_private = allow_private

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # `newurl` is resolved against the request URL upstream, so a relative
        # Location arrives here absolute and carries its scheme.
        if not scheme_ok(newurl, self.allowed):
            raise urllib.error.HTTPError(
                newurl, code,
                f"refusing redirect to a scheme outside "
                f"{sorted(self.allowed)}: {newurl[:60]!r}",
                headers, fp)
        if not self.allow_private:
            reason = private_destination(newurl)
            if reason is not None:
                raise urllib.error.HTTPError(
                    newurl, code,
                    f"refusing redirect to a private destination — {reason}: "
                    f"{newurl[:60]!r}",
                    headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENERS: dict[tuple[frozenset[str], bool], urllib.request.OpenerDirector] = {}
_OPENER_LOCK = threading.Lock()


def opener(allowed: frozenset[str], *, allow_private: bool = False
           ) -> urllib.request.OpenerDirector:
    """The shared opener for one scheme policy, built on first use.

    Assembled by hand rather than with `build_opener`, which installs handlers
    for file:, ftp: and data:. With no handler for a scheme, a URL that somehow
    got past both checks has nothing able to open it — `UnknownHandler` raises
    `unknown url type: ...`. `HTTPHandler` is included only when plain http is
    allowed, so an https-only caller gets that structural backstop too.
    (Verified that omitting it leaves https-through-a-proxy unchanged: that
    path tunnels via `HTTPSHandler` and `ProxyHandler`.)
    """
    # The destination policy is part of the cache key, not just the scheme set.
    # Sharing one opener between a lane that may reach localhost and one that
    # may not would hand the stricter lane the looser lane's redirect handler.
    key = (allowed, allow_private)
    with _OPENER_LOCK:
        if key not in _OPENERS:
            handlers: list[Any] = [urllib.request.ProxyHandler()]  # honors HTTPS_PROXY
            if "http" in allowed:
                handlers.append(urllib.request.HTTPHandler())
            handlers += [
                urllib.request.HTTPSHandler(),
                SchemeGuardedRedirects(allowed, allow_private),
                urllib.request.HTTPDefaultErrorHandler(),
                urllib.request.HTTPErrorProcessor(),
                urllib.request.UnknownHandler(),
            ]
            o = urllib.request.OpenerDirector()
            for h in handlers:
                o.add_handler(h)
            _OPENERS[key] = o
        return _OPENERS[key]


def urlopen(req: urllib.request.Request, *, allowed: frozenset[str],
            timeout: float, allow_private: bool = False):
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
    if not allow_private:
        reason = private_destination(url)
        if reason is not None:
            raise ValueError(
                f"refusing a private destination — {reason}: {url[:60]!r}")
    return opener(allowed, allow_private=allow_private).open(req, timeout=timeout)


def read_capped(resp: Any, max_bytes: int) -> bytes:
    """Read a bounded body. Every response is untrusted input, and an endpoint
    that starts streaming without end should fail, not exhaust memory."""
    raw = resp.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError(f"response exceeds {max_bytes} bytes — refusing")
    return raw


def fetch(url: str, *, allowed: frozenset[str], timeout: float, max_bytes: int,
          headers: dict | None = None, data: bytes | None = None,
          allow_private: bool = False) -> bytes:
    """Open and read in one call, so no caller ever holds a response it could
    read unbounded. This is the only shape that makes the cap structural rather
    than remembered — six of eight egress sites in `sources` had skipped it."""
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urlopen(req, allowed=allowed, timeout=timeout,
                 allow_private=allow_private) as resp:
        return read_capped(resp, max_bytes)
