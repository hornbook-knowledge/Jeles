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


def test_core_domain_with_evidence_lands_as_attested_human(store, tmp_path):
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
    assert out["human"] == 1
    assert out["asserted"] == 0
    nugget = store.search_nuggets("feather bowling ball", limit=1)[0]
    assert nugget["verification_kind"] == "human"
    assert nugget["status"] == "verified"
    # Credited to the record it rests on, not to whoever loaded the seed —
    # and never a fabricated seal.
    assert nugget["verified_by"] == "public record: Wikipedia"
    assert nugget["evidence"]["scheme"] == commons.COMMONS_EVIDENCE_SCHEME
    assert nugget["evidence"]["credited_to"] == ["Wikipedia"]
    assert nugget["evidence"]["sealed"] is False
    assert "seal_sig" not in nugget["evidence"]
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


def test_seed_file_classified_commons_lands_as_attested_human(store, tmp_path):
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
    assert out["human"] == 1
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
    assert nugget["verification_kind"] == "human"
    assert nugget["evidence"]["scheme"] == commons.COMMONS_EVIDENCE_SCHEME


def test_promote_upgrades_machine_commons_to_attested_human(store):
    store.put_nugget(
        question="Why does a feather fall slower than a bowling ball?",
        answer="Air resistance.",
        sources=["https://en.wikipedia.org/wiki/Terminal_velocity"],
        verified_by=commons.COMMONS_VERIFIED_BY,
        tags=["core-forces-motion", "jeles-seed", "commons"],
        verification_kind="machine",
        written_by="jeles-seed",
    )
    counts = commons.promote_commons_in_store(commons_domains=set())
    assert counts["promoted"] == 1
    nugget = store.search_nuggets("feather bowling ball", limit=1)[0]
    assert nugget["verification_kind"] == "human"


def test_bundled_reference_seed_is_commons():
    domains = seed_loader.seed_commons_domains()
    assert "people-historical-scientists" in domains
    assert "modern-world-energy" in domains
    # Synthesis and adversarial rounds are argument, not knowns.
    assert not any(d.startswith(("crossdomain-", "adversarial-")) for d in domains)


def test_pair_classified_commons_in_novel_file_lands_as_attested_human(store, tmp_path):
    """An agreed fact inside an otherwise novel file — a fact-check verdict —
    is verified on its own, with its citation carried on the pair."""
    p = _write(
        tmp_path,
        "factcheck.json",
        {
            "domain": "adversarial-factcheck-tech",
            "pairs": [
                {
                    "source_text": "FACTCHECK REFUTED: Holmes was sentenced in January 2023",
                    "target_text": "Holmes was sentenced on November 18, 2022.",
                    "classification": "commons",
                    "evidence_urls": ["https://www.justice.gov/usao-ndca/pr/holmes"],
                },
                {
                    "source_text": "Steelman: Holmes was punished for Silicon Valley culture",
                    "target_text": "An argument, not a fact.",
                    "evidence_urls": ["https://example.org/op-ed"],
                },
            ],
        },
    )
    out = seed_loader.load_file(p)
    assert out["human"] == 1
    assert out["asserted"] == 1
    hit = store.search_nuggets("Holmes sentenced January 2023", limit=1)[0]
    assert hit["verification_kind"] == "human"
    assert hit["sources"] == ["https://www.justice.gov/usao-ndca/pr/holmes"]

    ids = seed_loader.seed_commons_nugget_ids(tmp_path)
    assert ids == {
        commons.seed_nugget_id(
            "adversarial-factcheck-tech",
            "FACTCHECK REFUTED: Holmes was sentenced in January 2023",
        )
    }


def test_promote_upgrades_single_commons_pair_by_seed_id(store):
    question = "FACTCHECK CONFIRMED: Murthy v. Missouri was decided 6-3"
    nid = commons.seed_nugget_id("adversarial-factcheck-modern", question)
    store.put_nugget(
        question=question,
        answer="Confirmed. The Court ruled 6-3 on June 26, 2024.",
        sources=["https://www.supremecourt.gov/opinions/23pdf/23-411_3dq3.pdf"],
        verified_by=commons.NOVEL_VERIFIED_BY,
        tags=["adversarial-factcheck-modern", "jeles-seed"],
        nugget_id=nid,
        verification_kind="asserted",
        written_by="jeles-seed",
    )
    counts = commons.promote_commons_in_store(commons_domains=set(), commons_ids={nid})
    assert counts["promoted"] == 1
    assert store.search_nuggets("Murthy Missouri", limit=1)[0]["verification_kind"] == "human"


def test_commons_credit_names_publishers_not_the_loader():
    sources = [
        "https://science.nasa.gov/universe/black-holes/",
        "https://www.britannica.com/science/black-hole",
        "https://en.wikipedia.org/wiki/Black_hole",
        "https://www.britannica.com/summary/black-hole",
        "https://www.jstor.org/stable/123",
    ]
    assert commons.commons_credit(sources) == (
        "public record: NASA, Encyclopaedia Britannica, Wikipedia, jstor.org"
    )
    assert commons.commons_credit([]) == "public record"


def test_promote_recredits_commons_that_named_the_developer(store):
    """Commons loaded before credit moved to the public record carried the
    developer's name. Promotion rewrites them at the same rung."""
    store.put_nugget(
        question="What is a black hole?",
        answer="A region of space where gravity is so strong light cannot escape.",
        sources=["https://science.nasa.gov/universe/black-holes/"],
        verified_by="Sean Campbell",
        tags=["core-space-astronomy", "jeles-seed", "commons"],
        verification_kind="human",
        written_by="jeles-seed",
        evidence={"scheme": "developer-attestation-v1", "attested_by": "Sean Campbell"},
    )
    counts = commons.promote_commons_in_store(commons_domains=set(), commons_ids=set())
    assert counts["promoted"] == 1
    nugget = store.search_nuggets("black hole", limit=1)[0]
    assert nugget["verification_kind"] == "human"
    assert nugget["verified_by"] == "public record: NASA"
    assert nugget["evidence"]["scheme"] == commons.COMMONS_EVIDENCE_SCHEME
