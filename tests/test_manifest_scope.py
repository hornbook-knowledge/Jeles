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


#: Shape only — corpus.py holds no PGP keyring and checks nothing about these
#: bytes beyond the ASCII-armor markers (see `_manifest_scope`'s docstring,
#: Loki J3/R1).
_FAKE_SIG = (
    "-----BEGIN PGP SIGNATURE-----\n\ntest-fixture-not-a-real-signature\n"
    "-----END PGP SIGNATURE-----\n"
)


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
        (app_dir / "manifest.json.sig").write_text(_FAKE_SIG)


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
    with pytest.raises(PermissionError, match="missing, empty, or not an ASCII-armored"):
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
    (app_dir / "manifest.json.sig").write_text(_FAKE_SIG)
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
    with pytest.raises(PermissionError, match="missing, empty, or not an ASCII-armored"):
        corpus.list_nuggets()


def test_refuses_an_empty_sig_file(corpus, monkeypatch, tmp_path):
    """Loki R1: `.sig` present but zero-byte must refuse the same as absent —
    `is_file()` alone let this through."""
    apps_root = tmp_path / "apps"
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps_root))
    monkeypatch.setenv("JELES_CORPUS_APP_ID", "jeles-corpus")
    app_dir = apps_root / "jeles-corpus"
    app_dir.mkdir(parents=True)
    (app_dir / "manifest.json").write_text(json.dumps({"store_scope": ["*"], "store_write": ["*"]}))
    (app_dir / "manifest.json.sig").write_text("")
    with pytest.raises(PermissionError, match="missing, empty, or not an ASCII-armored"):
        corpus.list_nuggets()


def test_refuses_a_garbage_sig_file(corpus, monkeypatch, tmp_path):
    """Loki R1: `.sig` present and non-empty but not an ASCII-armored PGP
    signature block must still refuse — a non-empty file is not the same as
    a signed one."""
    apps_root = tmp_path / "apps"
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps_root))
    monkeypatch.setenv("JELES_CORPUS_APP_ID", "jeles-corpus")
    app_dir = apps_root / "jeles-corpus"
    app_dir.mkdir(parents=True)
    (app_dir / "manifest.json").write_text(json.dumps({"store_scope": ["*"], "store_write": ["*"]}))
    (app_dir / "manifest.json.sig").write_text("not a signature, just some bytes")
    with pytest.raises(PermissionError, match="missing, empty, or not an ASCII-armored"):
        corpus.list_nuggets()


def test_admits_a_well_shaped_sig_file(corpus, monkeypatch, tmp_path):
    """The positive case: a `.sig` that brackets the standard ASCII-armor
    markers is admitted on shape — still not cryptographically verified."""
    apps_root = tmp_path / "apps"
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps_root))
    monkeypatch.setenv("JELES_CORPUS_APP_ID", "jeles-corpus")
    _write_manifest(apps_root, "jeles-corpus", store_scope=["*"], store_write=["*"])
    corpus.list_nuggets()  # does not raise


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


# ── Default app id (gap 3cdeb177af78) ────────────────────────────────────────


def test_default_app_id_is_jeles_corpus_not_the_retired_seat(corpus, monkeypatch, tmp_path):
    """`JELES_CORPUS_APP_ID` unset resolves to the organ's own default,
    `jeles-corpus` — never the retired Ask Jeles specialist seat `jeles`."""
    monkeypatch.delenv("JELES_CORPUS_APP_ID", raising=False)
    apps_root = tmp_path / "apps"
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps_root))
    _write_manifest(apps_root, "jeles-corpus", store_scope=["*"], store_write=["*"])
    corpus.list_nuggets()  # does not raise: the default resolved to jeles-corpus


def test_explicit_jeles_app_id_is_refused(corpus, monkeypatch, tmp_path):
    """An explicit `JELES_CORPUS_APP_ID=jeles` is refused outright, citing the
    retirement — a retired seat name cannot be an organ id (ae23d366)."""
    apps_root = tmp_path / "apps"
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps_root))
    monkeypatch.setenv("JELES_CORPUS_APP_ID", "jeles")
    # Even a wide-open, validly-signed manifest at "jeles" must not be reached.
    _write_manifest(apps_root, "jeles", store_scope=["*"], store_write=["*"])
    with pytest.raises(PermissionError, match="retired"):
        corpus.list_nuggets()


def test_refusal_names_app_id_source_and_manifest_path_default(corpus, monkeypatch, tmp_path):
    monkeypatch.delenv("JELES_CORPUS_APP_ID", raising=False)
    apps_root = tmp_path / "apps"
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps_root))
    with pytest.raises(PermissionError) as excinfo:
        corpus.list_nuggets()
    message = str(excinfo.value)
    assert "jeles-corpus" in message
    assert "default" in message
    assert str(apps_root / "jeles-corpus" / "manifest.json") in message


def test_refusal_names_app_id_source_and_manifest_path_env(corpus, monkeypatch, tmp_path):
    apps_root = tmp_path / "apps"
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps_root))
    monkeypatch.setenv("JELES_CORPUS_APP_ID", "some-other-corpus")
    with pytest.raises(PermissionError) as excinfo:
        corpus.list_nuggets()
    message = str(excinfo.value)
    assert "some-other-corpus" in message
    assert "JELES_CORPUS_APP_ID='some-other-corpus'" in message or "JELES_CORPUS_APP_ID=" in message
    assert str(apps_root / "some-other-corpus" / "manifest.json") in message


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
