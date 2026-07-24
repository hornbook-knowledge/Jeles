"""The canonical Jeles persona ships in-package and loads via load_persona()."""

from __future__ import annotations

import json

import jeles


def test_persona_path_points_into_package():
    p = jeles.persona_path()
    assert p.exists()
    assert p.name == "jeles_persona.json"
    assert p.parent.name == "persona"


def test_load_persona_returns_the_jeles_identity():
    persona = jeles.load_persona()
    assert isinstance(persona, dict)
    assert persona["identity"]["name"] == "Jeles"
    # A few load-bearing sections the persona is defined by.
    for section in ("identity", "voice", "boundaries", "non_negotiable"):
        assert section in persona


def test_load_persona_matches_the_shipped_file():
    persona = jeles.load_persona()
    raw = json.loads(jeles.persona_path().read_text(encoding="utf-8"))
    assert persona == raw


def test_load_persona_is_cached():
    assert jeles.load_persona() is jeles.load_persona()
