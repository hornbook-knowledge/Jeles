"""`jeles-seed --init-local` — a standalone corpus for someone with no
willow-mcp fleet, signed with their own GPG key and never by this package."""

from __future__ import annotations

import json
import subprocess

from jeles import corpus, seed_loader


def _fake_gpg(monkeypatch, *, succeeds=True):
    """Stand in for the operator's gpg: record the call and, when it
    'succeeds', write an armored signature file where gpg was told to."""
    calls = []
    monkeypatch.setattr(seed_loader.shutil, "which", lambda name: "/usr/bin/gpg")

    def run(cmd, check=False):
        calls.append(cmd)
        if succeeds:
            out = cmd[cmd.index("--output") + 1]
            with open(out, "w", encoding="utf-8") as fh:
                fh.write("-----BEGIN PGP SIGNATURE-----\n\nop\n-----END PGP SIGNATURE-----\n")
        return subprocess.CompletedProcess(cmd, 0 if succeeds else 2)

    monkeypatch.setattr(seed_loader.subprocess, "run", run)
    return calls


def test_init_local_writes_a_scoped_manifest_and_signs_with_the_operators_key(
    tmp_path, monkeypatch
):
    calls = _fake_gpg(monkeypatch)
    done = seed_loader.init_local(tmp_path / "jeles")

    manifest = json.loads((tmp_path / "jeles/mcp_apps/jeles-corpus/manifest.json").read_text())
    own = [corpus.NUGGETS_COLLECTION, corpus.GAPS_COLLECTION]
    # Only the corpus's own collections — never "*".
    assert manifest == {"store_scope": own, "store_write": own}
    assert (tmp_path / "jeles/store").is_dir()
    # Signed by gpg (the operator's default key), not by anything this package wrote.
    assert calls and calls[0][:3] == ["/usr/bin/gpg", "--armor", "--detach-sign"]
    assert done["signed"] is True
    assert done["next"] == ["jeles-seed"]
    assert done["env"]["WILLOW_STORE_ROOT"] == str(tmp_path / "jeles/store")


def test_without_gpg_the_manifest_is_left_unsigned_and_the_step_is_named(tmp_path, monkeypatch):
    monkeypatch.setattr(seed_loader.shutil, "which", lambda name: None)
    done = seed_loader.init_local(tmp_path / "jeles")
    sig = tmp_path / "jeles/mcp_apps/jeles-corpus/manifest.json.sig"
    assert done["signed"] is False
    assert not sig.exists()
    assert done["next"][0].startswith("gpg --armor --detach-sign")


def test_init_local_never_overwrites_an_existing_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(seed_loader.shutil, "which", lambda name: None)
    seed_loader.init_local(tmp_path / "jeles")
    try:
        seed_loader.init_local(tmp_path / "jeles")
    except FileExistsError:
        pass
    else:
        raise AssertionError("a second init_local overwrote the manifest")


def test_a_signed_local_setup_loads_and_answers(tmp_path, monkeypatch):
    _fake_gpg(monkeypatch)
    done = seed_loader.init_local(tmp_path / "jeles")
    for key, value in done["env"].items():
        monkeypatch.setenv(key, value)
    core = [p for p in seed_loader.seed_files() if p.name == "core_reference-shelf.json"]
    totals = seed_loader.load_all(core)
    assert totals["human"] == 15
    assert corpus.ask_corpus("What is the periodic table?")["found"] is True


def test_an_unsigned_store_stops_the_load_once_instead_of_per_pair(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(seed_loader.shutil, "which", lambda name: None)
    done = seed_loader.init_local(tmp_path / "jeles")
    for key, value in done["env"].items():
        monkeypatch.setenv(key, value)
    assert seed_loader.main([]) == 1
    err = capsys.readouterr().err
    assert err.count("refused to open") == 1
    assert "WARN" not in err
    assert "jeles-seed --init-local" in err
