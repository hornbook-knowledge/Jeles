"""Manifest-scoped collections (sealed `ae23d366`, "Jeles is the organ").

`jeles.corpus._validate_collection` refuses any collection outside the
organ's own manifest `store_scope` (read) / `store_write` (write) — declared
at `$WILLOW_MCP_APPS_ROOT/<JELES_CORPUS_APP_ID>/manifest.json` — and refuses
to serve any store-backed call at all when there is no `JELES_CORPUS_APP_ID`
or no readable manifest, fail closed rather than falling back to "everything."

The autouse `_jeles_corpus_manifest` fixture in `conftest.py` gives every
other test a wide-open manifest so this suite is the only place the gate
itself is exercised; tests here override `JELES_CORPUS_APP_ID` /
`WILLOW_MCP_APPS_ROOT` / the manifest contents directly.
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture()
def corpus(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path / "store"))
    from jeles import corpus as corpus_module

    return corpus_module


def _write_manifest(apps_root, app_id, store_scope=None, store_write=None, sign=True):
    app_dir = apps_root / app_id
    app_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict = {}
    if store_scope is not None:
        manifest["store_scope"] = store_scope
    if store_write is not None:
        manifest["store_write"] = store_write
    (app_dir / "manifest.json").write_text(json.dumps(manifest))
    if sign:
        # Shape only — corpus.py holds no PGP keyring and checks nothing about
        # these bytes (see `_manifest_scope`'s docstring, Loki J3).
        (app_dir / "manifest.json.sig").write_text("test-fixture-not-a-real-signature")


# ── Fail closed: no declared reach at all ───────────────────────────────────


def test_refuses_every_collection_with_no_app_id(corpus, monkeypatch):
    monkeypatch.delenv("JELES_CORPUS_APP_ID", raising=False)
    with pytest.raises(PermissionError, match="JELES_CORPUS_APP_ID"):
        corpus.put_nugget("q?", "a.", ["https://x/"], "rita")


def test_refuses_every_collection_with_no_manifest_on_disk(corpus, monkeypatch, tmp_path):
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps_root))
    monkeypatch.setenv("JELES_CORPUS_APP_ID", "jeles-corpus")
    with pytest.raises(PermissionError, match="no manifest signature"):
        corpus.log_gap("does it work?")


def test_refuses_a_manifest_missing_only_because_its_sig_is_present_but_it_is_not(
    corpus, monkeypatch, tmp_path
):
    """The rarer half of the same shape check: a `.sig` on disk with no
    `manifest.json` beside it still reads as "no readable manifest", not as
    a signed-and-trusted empty scope."""
    apps_root = tmp_path / "apps"
    app_dir = apps_root / "jeles-corpus"
    app_dir.mkdir(parents=True)
    (app_dir / "manifest.json.sig").write_text("test-fixture-not-a-real-signature")
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps_root))
    monkeypatch.setenv("JELES_CORPUS_APP_ID", "jeles-corpus")
    with pytest.raises(PermissionError, match="no readable manifest"):
        corpus.log_gap("does it work?")


def test_refuses_an_unsigned_manifest_even_when_store_scope_is_wide_open(
    corpus, monkeypatch, tmp_path
):
    """J3: a manifest.json with no sibling .sig is refused on shape, even
    when its store_scope/store_write would otherwise allow everything —
    presence of a signature file is checked before the scope is ever read."""
    apps_root = tmp_path / "apps"
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps_root))
    monkeypatch.setenv("JELES_CORPUS_APP_ID", "jeles-corpus")
    _write_manifest(apps_root, "jeles-corpus", store_scope=["*"], store_write=["*"], sign=False)
    with pytest.raises(PermissionError, match="no manifest signature"):
        corpus.list_nuggets()


def test_refuses_when_store_scope_is_malformed(corpus, monkeypatch, tmp_path):
    apps_root = tmp_path / "apps"
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps_root))
    monkeypatch.setenv("JELES_CORPUS_APP_ID", "jeles-corpus")
    # store_scope is a string here, not a list.
    _write_manifest(apps_root, "jeles-corpus", store_scope="ask_jeles_corpus_*")
    with pytest.raises(PermissionError, match="not a list"):
        corpus.list_nuggets()


# ── A declared, narrower scope ──────────────────────────────────────────────


def test_refuses_an_undeclared_collection(corpus, monkeypatch, tmp_path):
    apps_root = tmp_path / "apps"
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps_root))
    monkeypatch.setenv("JELES_CORPUS_APP_ID", "jeles-corpus")
    _write_manifest(apps_root, "jeles-corpus", store_scope=["ask_jeles_corpus"])
    with pytest.raises(PermissionError, match="collection_denied"):
        corpus._conn("some_other_collection")


def test_admits_a_declared_collection(corpus, monkeypatch, tmp_path):
    apps_root = tmp_path / "apps"
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps_root))
    monkeypatch.setenv("JELES_CORPUS_APP_ID", "jeles-corpus")
    _write_manifest(apps_root, "jeles-corpus", store_scope=["ask_jeles_corpus"])
    corpus._conn("ask_jeles_corpus")  # does not raise


def test_a_trailing_wildcard_matches_a_prefix(corpus, monkeypatch, tmp_path):
    apps_root = tmp_path / "apps"
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps_root))
    monkeypatch.setenv("JELES_CORPUS_APP_ID", "jeles-corpus")
    _write_manifest(apps_root, "jeles-corpus", store_scope=["ask_jeles_corpus*"])
    corpus._conn("ask_jeles_corpus")  # does not raise
    corpus._conn("ask_jeles_corpus_gaps")  # does not raise
    with pytest.raises(PermissionError, match="collection_denied"):
        corpus._conn("shared_soil")


# ── Read vs write are separate lists ─────────────────────────────────────────


def test_write_is_refused_outside_store_write_even_when_readable(corpus, monkeypatch, tmp_path):
    """A collection may be readable without being writable — `store_scope`
    and `store_write` are separate declarations, and a manifest that grants
    only the read half must not silently also grant the write half."""
    apps_root = tmp_path / "apps"
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps_root))
    monkeypatch.setenv("JELES_CORPUS_APP_ID", "jeles-corpus")
    _write_manifest(
        apps_root,
        "jeles-corpus",
        store_scope=["ask_jeles_corpus", "ask_jeles_corpus_gaps"],
        store_write=["ask_jeles_corpus_gaps"],
    )
    with pytest.raises(PermissionError, match="collection_denied"):
        corpus.put_nugget("q?", "a.", ["https://x/"], "rita")  # writes NUGGETS_COLLECTION

    result = corpus.log_gap("does it work?")  # writes GAPS_COLLECTION — declared
    assert "id" in result


def test_store_write_alone_does_not_grant_read(corpus, monkeypatch, tmp_path):
    apps_root = tmp_path / "apps"
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps_root))
    monkeypatch.setenv("JELES_CORPUS_APP_ID", "jeles-corpus")
    _write_manifest(
        apps_root, "jeles-corpus", store_scope=[], store_write=["ask_jeles_corpus_gaps"]
    )
    corpus.log_gap("a question")  # write path — allowed
    with pytest.raises(PermissionError, match="collection_denied"):
        corpus.list_gaps()  # read path — not declared in store_scope
