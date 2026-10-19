"""Commons classification — intake and seed loader."""

from __future__ import annotations

import json

import pytest

from jeles import commons, seed_loader


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path / "store"))
    from jeles import corpus as corpus_module

    return corpus_module


def _write(tmp_path, name, payload):
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_core_domain_with_evidence_lands_as_machine(store, tmp_path):
    p = _write(
        tmp_path,
        "core.json",
        {
            "domain": "core-forces-motion",
            "pairs": [
                {
                    "source_text": "Why does a feather fall slower than a bowling ball?",
                    "target_text": "Air resistance.",
                }
            ],
            "evidence": [
                {
                    "pair_source": "Why does a feather fall slower than a bowling ball?",
                    "locator": "https://en.wikipedia.org/wiki/Terminal_velocity",
                }
            ],
        },
    )
    out = seed_loader.load_file(p)
    assert out["machine"] == 1
    assert out["asserted"] == 0
    nugget = store.search_nuggets("feather bowling ball", limit=1)[0]
    assert nugget["verification_kind"] == "machine"
    assert nugget["verified_by"] == commons.COMMONS_VERIFIED_BY
    assert store.ask_corpus("Why does a feather fall slower than a bowling ball?")["found"] is True


def test_non_core_domain_stays_asserted(store, tmp_path):
    p = _write(
        tmp_path,
        "novel.json",
        {
            "domain": "institutional-genealogy",
            "pairs": [
                {
                    "source_text": "What is Operation Paperclip?",
                    "target_text": "A postwar US program.",
                    "sources": ["https://en.wikipedia.org/wiki/Operation_Paperclip"],
                }
            ],
        },
    )
    out = seed_loader.load_file(p)
    assert out["asserted"] == 1
    assert out["machine"] == 0


def test_intake_commons_file_lands_as_machine(store, tmp_path, monkeypatch):
    intake_dir = tmp_path / "intake"
    intake_dir.mkdir()
    (intake_dir / "probe-questions.json").write_text(
        json.dumps({"topics": []}),
        encoding="utf-8",
    )
    (intake_dir / "commons-facts.json").write_text(
        json.dumps(
            {
                "domain": "math-reference",
                "classification": "commons",
                "pairs": [
                    {
                        "source_text": "What is pi approximately?",
                        "target_text": "About 3.14.",
                        "sources": ["https://en.wikipedia.org/wiki/Pi"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("JELES_INTAKE_DIR", str(intake_dir))
    from jeles import intake

    counts = intake.load_file(
        intake_dir / "commons-facts.json",
        dry_run=False,
        intake_dir=intake_dir,
    )
    assert counts["commons"] == 1
    nugget = store.search_nuggets("pi approximately", limit=1)[0]
    assert nugget["verification_kind"] == "machine"


def test_intake_novel_default_stays_asserted(store, tmp_path, monkeypatch):
    intake_dir = tmp_path / "intake"
    intake_dir.mkdir()
    (intake_dir / "probe-questions.json").write_text(
        json.dumps({"topics": []}),
        encoding="utf-8",
    )
    (intake_dir / "operator.json").write_text(
        json.dumps(
            {
                "domain": "willow-operator",
                "pairs": [
                    {
                        "source_text": "What is the federation rule?",
                        "target_text": "Use willow-mcp federation.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("JELES_INTAKE_DIR", str(intake_dir))
    from jeles import intake

    intake.load_file(
        intake_dir / "operator.json",
        dry_run=False,
        intake_dir=intake_dir,
    )
    assert store.ask_corpus("What is the federation rule?")["found"] is False


def test_seed_file_classified_commons_lands_as_machine(store, tmp_path):
    p = _write(
        tmp_path,
        "hist.json",
        {
            "domain": "people-historical-scientists",
            "classification": "commons",
            "pairs": [
                {
                    "source_text": "Isaac Newton and the Principia",
                    "target_text": "Newton published the Principia in 1687.",
                }
            ],
            "evidence": [
                {
                    "pair_source": "Isaac Newton and the Principia",
                    "locator": "https://en.wikipedia.org/wiki/Philosophi%C3%A6_Naturalis_Principia_Mathematica",
                }
            ],
        },
    )
    out = seed_loader.load_file(p)
    assert out["machine"] == 1
    assert out["asserted"] == 0
    assert store.ask_corpus("Isaac Newton and the Principia")["found"] is True


def test_promote_upgrades_asserted_nugget_in_seed_commons_domain(store, tmp_path):
    store.put_nugget(
        question="Isaac Newton and the Principia",
        answer="Newton published the Principia in 1687.",
        sources=["https://en.wikipedia.org/wiki/Isaac_Newton"],
        verified_by=commons.NOVEL_VERIFIED_BY,
        tags=["people-historical-scientists", "jeles-seed"],
        verification_kind="asserted",
        written_by="jeles-seed",
    )
    seed_dir = tmp_path / "seed"
    seed_dir.mkdir()
    _write(
        seed_dir,
        "hist.json",
        {"domain": "people-historical-scientists", "classification": "commons", "pairs": []},
    )
    domains = seed_loader.seed_commons_domains(seed_dir)
    assert domains == {"people-historical-scientists"}

    counts = commons.promote_commons_in_store(commons_domains=domains)
    assert counts["promoted"] == 1
    nugget = store.search_nuggets("Newton Principia", limit=1)[0]
    assert nugget["verification_kind"] == "machine"


def test_bundled_reference_seed_is_commons():
    domains = seed_loader.seed_commons_domains()
    assert "people-historical-scientists" in domains
    assert "modern-world-energy" in domains
    # Synthesis and adversarial rounds are argument, not knowns.
    assert not any(d.startswith(("crossdomain-", "adversarial-")) for d in domains)
