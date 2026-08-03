"""Verified-nugget corpus: storage, ranked ask/search, gap logging."""

from __future__ import annotations

import pytest


@pytest.fixture()
def corpus(tmp_path, monkeypatch):
    # _conn() keys its connection cache by the full resolved db path, so a
    # fresh WILLOW_STORE_ROOT per test is enough isolation without reload.
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path / "store"))
    from jeles import corpus as corpus_module

    return corpus_module


def _seed_grove(corpus):
    return corpus.put_nugget(
        question="What's the primary color in Grove?",
        answer="The primary color in Grove is #ffffff (white).",
        sources=["safe-library/themes/grove.json"],
        verified_by="designer",
        tags=["color", "grove", "primary"],
    )


def test_put_requires_core_fields(corpus):
    assert "error" in corpus.put_nugget("", "", [], "")
    assert "error" in corpus.put_nugget("Q?", "A.", [], "")


def test_put_and_get_roundtrip(corpus):
    result = _seed_grove(corpus)
    assert "id" in result
    nugget = corpus.get_nugget(result["id"])
    assert nugget["question"] == "What's the primary color in Grove?"
    assert nugget["verified_by"] == "designer"
    assert nugget["status"] == "verified"


def test_get_missing_returns_error(corpus):
    assert corpus.get_nugget("does-not-exist") == {"error": "not_found"}


def test_search_ranks_question_match_first(corpus):
    _seed_grove(corpus)
    corpus.put_nugget(
        question="What's the accent color in Nord?",
        answer="The accent color in Nord is #88c0d0 (ice blue).",
        sources=["safe-library/themes/nord.json"],
        verified_by="designer",
    )
    hits = corpus.search_nuggets("primary color Grove")
    assert hits
    assert hits[0]["question"].startswith("What's the primary color")


def test_weak_overlap_is_not_a_confident_ask(corpus):
    # "color" overlaps with the Grove nugget, so search_nuggets() (a loose
    # ranked lookup) may legitimately surface it — but that weak overlap
    # must not be enough for ask_corpus() to call it a confident answer.
    _seed_grove(corpus)
    asked = corpus.ask_corpus("What is the accent color in Tokyo Night?")
    assert asked["found"] is False


def test_ask_corpus_exact_match(corpus):
    _seed_grove(corpus)
    result = corpus.ask_corpus("What's the primary color in Grove?")
    assert result["found"] is True
    assert result["exact"] is True
    assert "white" in result["nugget"]["answer"].lower()


def test_ask_corpus_miss_logs_gap(corpus):
    result = corpus.ask_corpus("What is the accent color in Tokyo Night?")
    assert result["found"] is False
    gaps = corpus.list_gaps()
    assert len(gaps) == 1
    assert gaps[0]["question"] == "What is the accent color in Tokyo Night?"
    assert gaps[0]["asked_count"] == 1


def test_ask_corpus_repeated_miss_bumps_count_not_duplicates(corpus):
    corpus.ask_corpus("What is the accent color in Tokyo Night?")
    corpus.ask_corpus("what is the accent color in tokyo night")
    gaps = corpus.list_gaps()
    assert len(gaps) == 1
    assert gaps[0]["asked_count"] == 2


def test_search_nuggets_never_logs_a_gap(corpus):
    corpus.search_nuggets("some unmatched query")
    assert corpus.list_gaps() == []


def test_to_search_hit_shape(corpus):
    _seed_grove(corpus)
    nugget = corpus.list_nuggets()[0]
    hit = corpus.to_search_hit(nugget, 1)
    assert hit["source_id"] == "corpus"
    assert hit["confidence"] == "verified"
    assert hit["title"] == nugget["question"]
    assert hit["snippet"] == nugget["answer"]
    assert hit["url"] == "safe-library/themes/grove.json"


def test_list_nuggets_most_recent_first(corpus):
    first = _seed_grove(corpus)
    second = corpus.put_nugget(
        question="What's the accent color in Nord?",
        answer="The accent color in Nord is #88c0d0 (ice blue).",
        sources=["safe-library/themes/nord.json"],
        verified_by="designer",
    )
    nuggets = corpus.list_nuggets()
    assert nuggets[0]["_id"] == second["id"]
    assert nuggets[1]["_id"] == first["id"]


def test_control_chars_stripped_at_write_boundary(corpus):
    # B-009 (shared with the-squirrel): C0 control chars have no place in a
    # stored nugget — a NUL that truncates C-string tooling, a BEL nobody can
    # retype. Tab/newline survive.
    nid = corpus.put_nugget(
        question="What is\x00 a Vespa?",
        answer="A scooter.\x07 Made by Piaggio.\nItalian design.",
        sources=["ex\x1fample.com"],
        verified_by="ed\x08itor",
    )
    n = corpus.get_nugget(nid["id"])
    assert "\x00" not in n["question"] and n["question"] == "What is a Vespa?"
    assert "\x07" not in n["answer"] and "\x08" not in n["verified_by"]
    assert "\nItalian design." in n["answer"]     # newline preserved
    assert n["sources"] == ["example.com"]         # cleaned inside the list too


def test_logged_gap_is_sanitized(corpus):
    corpus.log_gap("who is\x00 nobody?")
    g = corpus.list_gaps()[0]
    assert "\x00" not in g["question"]


# ── Answering wrongly is worse than not answering ───────────────────────────
#
# The old score was `matched / len(query_tokens)` — recall only. Two questions
# differing by the one word that changes the answer share every other word, so
# the distinguishing token was worth 1/N of the decision and `MIN_ASK_SCORE`
# (half overlap) waved them through. Each case below was verified returning
# `found: True` with the wrong nugget before the fix.


def _seed(corpus, question, answer, **kw):
    return corpus.put_nugget(question=question, answer=answer,
                             sources=["s"], verified_by="human", **kw)


def test_a_different_environment_is_a_different_question(corpus):
    """The one that would page someone: staging credentials answering a
    production question. Old score 0.95, found=True."""
    _seed(corpus, "How do I rotate the staging database password?",
          "Run `ops rotate --env staging`.", tags=["production", "rotate"])

    asked = corpus.ask_corpus("How do I rotate the production database password?")

    assert asked["found"] is False
    assert asked["nugget"] is None
    # Still surfaced as a near-miss — "I don't know, but this is close" is
    # useful; "here is your answer" is not.
    assert asked["candidates"], "a close nugget should still come back as a candidate"


def test_a_different_subject_is_a_different_question(corpus):
    """Old score 0.90, found=True — answered a covid question with flu advice."""
    _seed(corpus, "Is the flu vaccine safe during pregnancy?",
          "Yes - the inactivated flu vaccine is recommended.")
    assert corpus.ask_corpus("Is the covid vaccine safe during pregnancy?")["found"] is False


def test_a_tag_cannot_carry_a_wrong_nugget_over_the_threshold(corpus):
    """Old score 0.60, found=True. Half the overlap was the generic word
    'policy'; the +0.1 that pushed it over came from a tag matching the very
    word that made the questions different."""
    _seed(corpus, "What is the privacy policy?",
          "We keep logs for 90 days.", tags=["policy", "refund"])
    assert corpus.ask_corpus("What is the refund policy?")["found"] is False


def test_a_query_far_broader_than_the_nugget_is_not_confident(corpus):
    """Rule 1 alone would pass this: every query token *is* in the nugget. The
    symmetric measure is what refuses it — one word does not ask a specific
    question, and answering it invents the rest."""
    _seed(corpus, "Is the flu vaccine safe during pregnancy?", "Yes.")
    assert corpus.ask_corpus("vaccine")["found"] is False


@pytest.mark.parametrize("question", [
    "What's the primary color in Grove?",          # exact
    "primary color in Grove",                      # same tokens, no filler
    "What is the primary color in Grove???",       # punctuation only
])
def test_the_questions_it_should_answer_still_answer(corpus, question):
    """The fix must not buy correctness with uselessness."""
    _seed_grove(corpus)
    assert corpus.ask_corpus(question)["found"] is True


def test_a_more_general_question_still_reaches_a_specific_nugget(corpus):
    """Deliberate: the asker used no word the nugget lacks, and the overlap is
    strong, so the specific nugget answers. Documented because it is a genuine
    judgement call — the corpus knows only about staging and says so in the
    answer text."""
    _seed(corpus, "How do I rotate the staging database password?",
          "Run `ops rotate --env staging`.")
    assert corpus.ask_corpus("how do I rotate the database password?")["found"] is True


def test_ranking_and_answering_are_separate_decisions(corpus):
    """`search_nuggets` stays a loose ranked lookup — it should still surface a
    near-miss that `ask_corpus` refuses to answer with."""
    _seed(corpus, "What is the privacy policy?", "We keep logs for 90 days.",
          tags=["policy", "refund"])

    assert corpus.search_nuggets("refund policy"), "search should still find it"
    assert corpus.ask_corpus("What is the refund policy?")["found"] is False


def test_a_lower_ranked_but_confident_nugget_is_not_lost(corpus):
    """Confidence is checked across candidates, not only the top-ranked one, so
    a near-miss that ranks higher cannot hide a nugget that actually answers."""
    _seed(corpus, "What is the refund policy?", "Refunds within 30 days.")
    _seed(corpus, "What is the privacy policy?", "We keep logs for 90 days.",
          tags=["refund", "refund", "refund"])

    asked = corpus.ask_corpus("What is the refund policy?")
    assert asked["found"] is True
    assert asked["nugget"]["answer"] == "Refunds within 30 days."
