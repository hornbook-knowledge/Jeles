"""Shared test seam for the egress guard.

Every network-touching test in this suite stubs `urllib.request.urlopen`. Since
the scheme guard moved onto a shared `OpenerDirector` — which is what lets it
run on redirect hops, not just the first URL — those stubs are no longer on the
path: `opener.open()` dispatches to its own handler chain and never calls
`urlopen`. Without this fixture the stubs would be silently bypassed and the
tests would reach the real network.

So: point `_egress.opener` at a delegate that forwards to whatever `urlopen`
currently is. Autouse, because "this test stubs urlopen" is true of most of the
file and forgetting it fails as a live request rather than as an assertion.

`_egress.real_opener` is captured here before anything can patch it, for the
handful of tests that need to introspect the genuine handler chain.
"""

from __future__ import annotations

import json

import pytest

from jeles import _egress

#: The unpatched builder, for tests that assert on the real handler chain.
real_opener = _egress.opener


@pytest.fixture(autouse=True)
def _jeles_corpus_manifest(tmp_path_factory, monkeypatch):
    """Manifest-scoped collections (sealed `ae23d366`) are fail-closed by
    default: `jeles.corpus._validate_collection` refuses every store-backed
    call unless `JELES_CORPUS_APP_ID` names a manifest with a `store_scope`/
    `store_write` that covers the collection being touched. Almost every test
    in this suite predates that and has no reason to know about it — it wants
    'ask_jeles_corpus', 'shared_soil', or whatever it names, to just work.

    So: every test gets a wide-open manifest (`store_scope`/`store_write` =
    `["*"]`) plus a sibling `manifest.json.sig` — `_manifest_scope` refuses on
    shape when that file is absent (Jeles#87, Loki J3) — under a fresh,
    isolated `WILLOW_MCP_APPS_ROOT` by default. `tests/test_manifest_scope.py`
    overrides `JELES_CORPUS_APP_ID` / `WILLOW_MCP_APPS_ROOT` / the manifest
    contents directly to exercise the gate itself, including the sig-absent
    case.
    """
    apps_root = tmp_path_factory.mktemp("mcp_apps")
    app_dir = apps_root / "test-jeles-corpus"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "manifest.json").write_text(json.dumps({"store_scope": ["*"], "store_write": ["*"]}))
    # Not a real PGP signature — corpus.py only checks the ASCII-armor shape
    # (non-empty, bracketed by the standard markers), never validity; see
    # `_manifest_scope`'s docstring on why.
    (app_dir / "manifest.json.sig").write_text(
        "-----BEGIN PGP SIGNATURE-----\n\ntest-fixture-not-a-real-signature\n"
        "-----END PGP SIGNATURE-----\n"
    )
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps_root))
    monkeypatch.setenv("JELES_CORPUS_APP_ID", "test-jeles-corpus")


@pytest.fixture(autouse=True)
def _egress_opener_delegates_to_urlopen(monkeypatch):
    import urllib.request

    class _Delegating:
        @staticmethod
        def open(req, timeout=None):
            return urllib.request.urlopen(req, timeout=timeout)

    # Accepts `allow_private` because the real `opener` takes it — a shim with
    # a narrower signature turns a real call into a TypeError that the caller
    # swallows, and every hit disappears with only a warning to say why.
    monkeypatch.setattr(_egress, "opener", lambda allowed, *, allow_private=False: _Delegating)
