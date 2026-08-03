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


# ── The write path ──────────────────────────────────────────────────────────
#
# `_put` used INSERT OR REPLACE, which deletes the row and inserts a new one —
# so every column it did not name reverted to its schema default. Each case
# below was verified broken before the fix.


def _raw(corpus, rid, column):
    return corpus._conn(corpus.NUGGETS_COLLECTION).execute(
        f"SELECT {column} FROM records WHERE id = ?", (rid,)).fetchone()[0]


def test_a_jeles_write_preserves_willow_mcp_columns(corpus):
    """The module carries `deviation`/`action` precisely so the store stays
    usable from both sides. Every jeles write used to reset them, making it
    compatible in exactly one direction — which is not compatible."""
    rid = _seed_grove(corpus)["id"]
    corpus._conn(corpus.NUGGETS_COLLECTION).execute(
        "UPDATE records SET deviation = 0.87, action = 'escalate' WHERE id = ?", (rid,))

    corpus.put_nugget("What's the primary color in Grove?", "Updated.",
                      ["s"], "designer", nugget_id=rid)

    assert _raw(corpus, rid, "deviation") == 0.87
    assert _raw(corpus, rid, "action") == "escalate"


def test_a_re_put_does_not_resurrect_a_soft_deleted_record(corpus):
    """`deleted` was hardcoded to 0 on every write, so anyone who could write
    could undo a delete."""
    rid = _seed_grove(corpus)["id"]
    corpus._conn(corpus.NUGGETS_COLLECTION).execute(
        "UPDATE records SET deleted = 1 WHERE id = ?", (rid,))

    result = corpus.put_nugget("What's the primary color in Grove?", "Sneaky.",
                               ["s"], "designer", nugget_id=rid)

    assert _raw(corpus, rid, "deleted") == 1, "the tombstone must survive a write"
    assert corpus.get_nugget(rid).get("error"), "and the record stays invisible"
    # Not refused — refusing would let anyone who can soft-delete permanently
    # deny an id — but not reported as a create either.
    assert result["action"] == "updated_tombstoned"


def test_created_at_survives_an_update(corpus):
    rid = _seed_grove(corpus)["id"]
    created = corpus.get_nugget(rid)["_created"]
    corpus.put_nugget("What's the primary color in Grove?", "Updated.",
                      ["s"], "designer", nugget_id=rid)
    assert corpus.get_nugget(rid)["_created"] == created


def test_concurrent_asks_do_not_lose_gap_counts(corpus):
    """`log_gap` read the count and wrote count+1 in two separate transactions,
    so concurrent asks all read the same number: measured 14 after 50 calls.
    `list_gaps` sorts by this, so the growth queue was ordered by a number that
    undercounted exactly the questions being asked most."""
    import threading

    question = "what is the accent color in Tokyo Night?"
    threads = [threading.Thread(target=corpus.log_gap, args=(question,))
               for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    gap = [g for g in corpus.list_gaps() if "Tokyo Night" in g["question"]][0]
    assert gap["asked_count"] == 50


def test_concurrent_asks_produce_one_gap_not_fifty(corpus):
    import threading

    threads = [threading.Thread(target=corpus.log_gap, args=("one shared question",))
               for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len([g for g in corpus.list_gaps() if g["question"] == "one shared question"]) == 1


def test_the_store_is_in_wal_mode(corpus):
    """WAL lets a reader run while a writer holds the database. Without it, a
    willow-mcp reader and a jeles writer on the shared store raise
    `database is locked` out of functions documented to return dicts."""
    _seed_grove(corpus)
    mode = corpus._conn(corpus.NUGGETS_COLLECTION).execute(
        "PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_a_failed_write_rolls_back(corpus):
    """`_write` must not leave a half-applied transaction behind."""
    import pytest as _pytest

    conn = corpus._conn(corpus.NUGGETS_COLLECTION)
    before = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    with _pytest.raises(RuntimeError):
        with corpus._write(conn):
            conn.execute(
                "INSERT INTO records (id, data, created_at, updated_at, deleted) "
                "VALUES ('x', '{}', 'n', 'n', 0)")
            raise RuntimeError("boom")
    assert conn.execute("SELECT COUNT(*) FROM records").fetchone()[0] == before


# ── A write cannot claim more than it is entitled to ─────────────────────────
#
# Three rungs — human > machine > asserted — and the rung is the product. The
# threat is not another app's data; it is an agent that has just read the open
# web writing what it read into the settled layer. `corpus_put` is where that
# lands, but the invariant belongs here, because a rule enforced at one caller
# is enforced at none.


def test_an_asserted_nugget_does_not_read_as_verified(corpus):
    rid = corpus.put_nugget("Is X true?", "Yes.", ["https://evil.example/p"],
                            "the operator", verification_kind="asserted",
                            written_by="some-mcp-client")["id"]
    hit = corpus.to_search_hit(corpus.get_nugget(rid))
    assert hit["confidence"] == "unverified"
    assert hit["verification_kind"] == "asserted"
    # The line a reader actually sees must not say "Verified corpus", and must
    # name the app that wrote it rather than the name that app typed.
    assert "Verified corpus" not in hit["source"]
    assert "some-mcp-client" in hit["source"]
    assert corpus.get_nugget(rid)["status"] == "asserted"


def test_ask_corpus_does_not_answer_from_an_assertion(corpus):
    """`found: true` is the settled layer speaking. A caller that reads only
    `nugget["answer"]` — most of them — has no other way to tell."""
    corpus.put_nugget("Is X true?", "Yes.", ["s"], "the operator",
                      verification_kind="asserted")

    asked = corpus.ask_corpus("Is X true?")
    assert asked["found"] is False
    # Reachable, just not authoritative.
    assert [n["answer"] for n in asked["candidates"]] == ["Yes."]
    assert corpus.search_nuggets("Is X true?")[0]["answer"] == "Yes."
    assert corpus.ask_corpus("Is X true?", include_asserted=True)["found"] is True


def test_ask_corpus_still_answers_from_machine_corroboration(corpus):
    """Only the bottom rung is excluded — conflict_scan's findings still answer."""
    corpus.put_nugget("Is Y true?", "Yes.", ["s"], "conflict_scan",
                      verification_kind="machine")
    assert corpus.ask_corpus("Is Y true?")["found"] is True


def test_an_assertion_cannot_overwrite_a_verified_nugget(corpus):
    """Without this, every other protection is one `nugget_id=` away from being
    bypassed: the assertion lands on the verified nugget, keeping its id and its
    place in every search result. Verified before the fix — the human answer was
    replaced with "Actually it is #000000."."""
    real = _seed_grove(corpus)

    refused = corpus.put_nugget(
        "What's the primary color in Grove?", "Actually it is #000000.",
        ["https://evil.example/p"], "designer", nugget_id=real["id"],
        verification_kind="asserted")

    assert refused["error"] == "kind_downgrade_refused"
    assert refused["existing_kind"] == "human" and refused["attempted_kind"] == "asserted"
    nugget = corpus.get_nugget(real["id"])
    assert nugget["answer"].endswith("#ffffff (white).")
    assert nugget["verification_kind"] == "human"


def test_machine_cannot_overwrite_human_either(corpus):
    real = _seed_grove(corpus)
    refused = corpus.put_nugget("What's the primary color in Grove?", "#eeeeee.",
                                ["s"], "conflict_scan", nugget_id=real["id"],
                                verification_kind="machine")
    assert refused["error"] == "kind_downgrade_refused"


def test_a_person_can_still_supersede_and_promote(corpus):
    """The rule is one-directional: writing at the same rung or a higher one is
    ordinary editing, and must not be caught by the guard."""
    asserted = corpus.put_nugget("Is X true?", "Maybe.", ["s"], "client",
                                 verification_kind="asserted")
    same = corpus.put_nugget("Is X true?", "Still maybe.", ["s"], "client",
                             nugget_id=asserted["id"], verification_kind="asserted")
    assert same["action"] == "updated"

    promoted = corpus.put_nugget("Is X true?", "Yes — checked.", ["s"], "designer",
                                 nugget_id=asserted["id"])
    assert promoted["verification_kind"] == "human"
    assert corpus.to_search_hit(corpus.get_nugget(asserted["id"]))["confidence"] == "verified"


def test_a_refused_write_changes_nothing(corpus):
    """The rung check runs inside the write transaction, so a refusal is not a
    partial write — and cannot be raced past by a concurrent one."""
    real = _seed_grove(corpus)
    before = corpus.get_nugget(real["id"])["_updated"]
    corpus.put_nugget("q?", "a", ["s"], "x", nugget_id=real["id"],
                      verification_kind="asserted")
    assert corpus.get_nugget(real["id"])["_updated"] == before


def test_an_unrecognised_kind_is_refused_not_promoted(corpus):
    """It used to be `"machine" if kind == "machine" else "human"`, so every
    typo — and every unknown future rung — landed at the top."""
    result = corpus.put_nugget("q?", "a", ["s"], "x", verification_kind="verified")
    assert "error" in result and "verification_kind" in result["error"]
    assert corpus.list_nuggets() == []


def test_a_garbled_stored_kind_is_treated_as_the_highest_rung(corpus):
    """Reading is protective in the other direction: an unrecognised value on
    an existing record must not make it overwritable by anything."""
    rid = _seed_grove(corpus)["id"]
    corpus._put(corpus.NUGGETS_COLLECTION,
                {**corpus.get_nugget(rid), "verification_kind": "?"}, record_id=rid)

    assert corpus.to_search_hit(corpus.get_nugget(rid))["confidence"] == "verified"
    refused = corpus.put_nugget("q?", "a", ["s"], "x", nugget_id=rid,
                                verification_kind="asserted")
    assert refused["error"] == "kind_downgrade_refused"


def test_a_legacy_nugget_without_a_kind_is_human(corpus):
    """Nuggets written before the field existed were human-entered, and must not
    become overwritable by adding the field."""
    rid = _seed_grove(corpus)["id"]
    legacy = {k: v for k, v in corpus.get_nugget(rid).items()
              if k != "verification_kind"}
    corpus._put(corpus.NUGGETS_COLLECTION, legacy, record_id=rid)

    assert corpus.to_search_hit(corpus.get_nugget(rid))["confidence"] == "verified"
    assert corpus.put_nugget("q?", "a", ["s"], "x", nugget_id=rid,
                             verification_kind="machine")["error"] == "kind_downgrade_refused"
