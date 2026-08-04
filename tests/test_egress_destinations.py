"""A scheme guard says *how* a request travels. Nothing said *where*.

`_egress` re-checked the scheme on every redirect hop, which closed an
https -> http downgrade and an ftp hop. It said nothing about the destination,
so a redirect from a source could reach **any** https address — including
`169.254.169.254`, the cloud metadata endpoint, and `127.0.0.1:8888`, where
this package's own corpus server listens.

Reaching that needs a redirect from one of the ~60 upstreams: a hostile or
compromised one, an open redirect, or DNS pointing a public name at a private
address. Not all of them are hardened institutions — `gutendex.com`,
`thesportsdb.com`, `frankfurter.app` and `open-meteo.com` are third-party
conveniences.

It became worth closing when willow-mcp 2.2.0 made `jeles.institutional`
reachable as an MCP tool, on the same permission line as `willow_web_fetch` —
which blocks exactly these addresses. Two tools, one grant, and the newer one
was the weaker path.

**The split follows the one already there.** `sources` is https-only and has no
legitimate private destination. The two operator-pointed lanes — a SearXNG
instance on `http://127.0.0.1:8888`, a `JELES_REMOTE_URL` on a private network —
are aimed at an address the operator chose, and refusing private there would
break the sovereign case this package is built around. So the default is
"public only" and those two opt out, visibly.
"""
from __future__ import annotations

import io
import urllib.error
from typing import ClassVar

import pytest
from conftest import real_opener

from jeles import _egress

_PRIVATE = [
    ("cloud metadata", "https://169.254.169.254/latest/meta-data/iam/"),
    ("IPv4 loopback", "https://127.0.0.1:8888/admin"),
    ("IPv6 loopback", "https://[::1]/x"),
    ("localhost by name", "https://localhost:5432/"),
    ("RFC1918", "https://10.0.0.5/internal"),
    ("carrier-grade NAT / reserved", "https://192.0.0.1/"),
]


class _Req:
    """The minimum urllib's redirect handler touches."""
    full_url = "https://api.crossref.org/works?query=x"
    headers: ClassVar[dict] = {}
    unredirected_hdrs: ClassVar[dict] = {}
    timeout = None
    origin_req_host = "api.crossref.org"
    unverifiable = False
    data = None

    def get_full_url(self):
        return self.full_url

    def get_method(self):
        return "GET"


def _redirect(handler, url):
    return handler.redirect_request(_Req(), io.BytesIO(b""), 302, "Found", {}, url)


@pytest.mark.parametrize(("label", "url"), _PRIVATE, ids=[p[0] for p in _PRIVATE])
def test_a_source_redirect_cannot_reach_a_private_address(label, url):
    """The hole, closed. Every one of these was followed before."""
    handler = _egress.SchemeGuardedRedirects(_egress.HTTPS_ONLY)
    with pytest.raises(urllib.error.HTTPError, match="private destination"):
        _redirect(handler, url)


def test_a_source_redirect_to_a_public_address_still_works():
    """The other half. A guard that refuses everything is not a guard."""
    handler = _egress.SchemeGuardedRedirects(_egress.HTTPS_ONLY)
    assert _redirect(handler, "https://arxiv.org/abs/1234") is not None


@pytest.mark.parametrize(("label", "url"), _PRIVATE, ids=[p[0] for p in _PRIVATE])
def test_the_operator_pointed_lanes_may_still_reach_private_addresses(label, url):
    """`allow_private=True` is not a loophole, it is the point of those lanes.
    The documented zero-config default is SearXNG on `http://127.0.0.1:8888`;
    refusing it would break the out-of-the-box case rather than protect it."""
    handler = _egress.SchemeGuardedRedirects(_egress.HTTP_OR_HTTPS, allow_private=True)
    assert _redirect(handler, url) is not None


def test_the_scheme_guard_still_holds_alongside_the_destination_one():
    """Adding a second check must not displace the first — an https -> http
    downgrade on the sources lane is still refused, and for its own reason."""
    handler = _egress.SchemeGuardedRedirects(_egress.HTTPS_ONLY)
    with pytest.raises(urllib.error.HTTPError, match="scheme outside"):
        _redirect(handler, "http://arxiv.org/abs/1")


def test_a_name_that_resolves_private_is_caught(monkeypatch):
    """A name-only check is the obvious thing to write and is trivially bypassed
    by pointing a public name at 127.0.0.1. willow-mcp's own fetch guard
    inspects the literal host and stops, so it has exactly that hole."""
    monkeypatch.setattr(
        _egress.socket, "getaddrinfo",
        lambda host, port, *a, **k: [(2, 1, 6, "", ("127.0.0.1", 0))])
    reason = _egress.private_destination("https://totally-legit.example/x")
    assert reason is not None
    assert "127.0.0.1" in reason
    assert "totally-legit.example" in reason, "should say the name it resolved from"


def test_a_name_that_does_not_resolve_is_not_refused(monkeypatch):
    """The connection is about to fail on its own. Refusing here would report a
    security decision for what is really a DNS failure."""
    def boom(*a, **k):
        raise OSError("Name or service not known")

    monkeypatch.setattr(_egress.socket, "getaddrinfo", boom)
    assert _egress.private_destination("https://nx.invalid/x") is None


def test_the_opener_cache_does_not_share_across_destination_policies():
    """The cache key is (schemes, allow_private). Keyed on schemes alone, the
    first lane to build an opener would hand its redirect handler to the other —
    and a sources call could inherit the operator lane's permission to reach
    localhost."""
    # `real_opener`, not `_egress.opener`: conftest's autouse fixture swaps the
    # latter for a delegating shim, which would make both sides the same object
    # and the assertion vacuous rather than true.
    strict = real_opener(_egress.HTTP_OR_HTTPS, allow_private=False)
    loose = real_opener(_egress.HTTP_OR_HTTPS, allow_private=True)
    assert strict is not loose

    def guard_of(o):
        return next(h for h in o.handlers
                    if isinstance(h, _egress.SchemeGuardedRedirects))

    assert guard_of(strict).allow_private is False
    assert guard_of(loose).allow_private is True


def test_the_first_url_is_checked_too_not_only_redirects():
    """A redirect is the realistic vector, but a caller passing a private URL
    directly should not be the one hole left open."""
    req = _egress.urllib.request.Request("https://127.0.0.1:9/x")
    with pytest.raises(ValueError, match="private destination"):
        _egress.urlopen(req, allowed=_egress.HTTPS_ONLY, timeout=1)


def test_the_lanes_declare_their_own_posture():
    """Reading the call sites is how someone checks this, so pin what they say:
    sources takes the default, the two operator-pointed lanes opt out."""
    from pathlib import Path

    root = Path(_egress.__file__).parent
    sources = (root / "sources.py").read_text()
    assert "allow_private" not in sources, \
        "sources must take the secure default rather than restate it"

    for name in ("institutional.py", "reactions/search_adapter.py"):
        text = (root / name).read_text()
        assert "allow_private=True" in text, f"{name} must opt out visibly"
