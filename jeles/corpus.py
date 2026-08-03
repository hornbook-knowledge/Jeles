"""Jeles' verified-nugget corpus — storage and ranked lookup.

A nugget is a human-verified question/answer pair with citations:
{question, answer, sources, verified_by, verified_at, tags}.

Storage reuses the same SQLite shape as willow-mcp's SOIL `Store` (a
`records` table under `<collection>/store.db`, keyed by WILLOW_STORE_ROOT),
so nuggets written here are already visible to a Willow-style soil scan
with no extra wiring, and the corpus stays readable by anything else that
understands a Willow-style SOIL collection.

This module has no MCP dependency and does no network I/O — see
corpus_server.py for the MCPServer wrapper that exposes it as a standalone,
MCP-agnostic server. It imports only the standard library, on purpose:
that is what keeps its tests fast and network-free, and lets it be reused
as a plain library by any host.

The default collection names (`ask_jeles_corpus` / `ask_jeles_corpus_gaps`)
are preserved from Ask Jeles for back-compat so existing stores keep
resolving; they can be overridden via env for a differently-scoped host.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

NUGGETS_COLLECTION = os.environ.get("JELES_CORPUS_COLLECTION", "ask_jeles_corpus")
GAPS_COLLECTION = os.environ.get("JELES_CORPUS_GAPS_COLLECTION", "ask_jeles_corpus_gaps")

# A collection name becomes a path component (<root>/<collection>/store.db), so
# an unvalidated one (e.g. from an env var a launcher forwards) could traverse
# out of WILLOW_STORE_ROOT. Mirror willow-mcp's SOIL Store guard — the sibling
# this schema is copied from already validates; this copy hadn't.
_COLLECTION_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def _validate_collection(collection: str) -> None:
    if not _COLLECTION_RE.match(collection or ""):
        raise ValueError(f"invalid collection name (must match "
                         f"{_COLLECTION_RE.pattern}): {collection!r}")

# The `deviation`/`action` columns are willow-mcp's (SOIL Store, db.py). jeles
# never reads them, but a jeles-created collection missing them makes a
# willow-mcp writer pointed at the same store fail `no such column: deviation`
# (box audit A3 — the two independently-drifted "shared" schemas). Carry them so
# the store stays mutually usable; _migrate_records() backfills older stores.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id         TEXT PRIMARY KEY,
    data       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deviation  REAL NOT NULL DEFAULT 0.0,
    action     TEXT NOT NULL DEFAULT 'work_quiet',
    deleted    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_deleted ON records(deleted);
"""


def _migrate_records(conn: sqlite3.Connection) -> None:
    """Add willow-mcp's SOIL columns to a pre-existing jeles store that predates
    this change, so a shared collection stays compatible either direction."""
    have = {row[1] for row in conn.execute("PRAGMA table_info(records)")}
    if "deviation" not in have:
        conn.execute("ALTER TABLE records ADD COLUMN deviation REAL NOT NULL DEFAULT 0.0")
    if "action" not in have:
        conn.execute("ALTER TABLE records ADD COLUMN action TEXT NOT NULL DEFAULT 'work_quiet'")

_lock = threading.RLock()
_conns: dict[str, sqlite3.Connection] = {}


def _store_root() -> Path:
    default = str(Path.home() / ".willow" / "store")
    return Path(os.environ.get("WILLOW_STORE_ROOT", default)).expanduser()


def _conn(collection: str) -> sqlite3.Connection:
    _validate_collection(collection)
    db_path = _store_root() / collection / "store.db"
    key = str(db_path)
    with _lock:
        if key not in _conns:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            # isolation_level=None turns off the driver's implicit transaction
            # handling so `_write` can take a real BEGIN IMMEDIATE. Without it,
            # a read-modify-write is only as atomic as the in-process lock —
            # which is nothing at all to a second process, and this store is
            # explicitly designed to be shared with willow-mcp.
            conn = sqlite3.connect(str(db_path), check_same_thread=False,
                                   isolation_level=None)
            # WAL lets readers run while a writer holds the database, and
            # busy_timeout makes a contended write wait rather than raising
            # `database is locked` out of put_nugget/ask_corpus — which no
            # caller expects, since both are documented as returning dicts.
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.executescript(_SCHEMA)
            _migrate_records(conn)
            _conns[key] = conn
        return _conns[key]


@contextmanager
def _write(conn: sqlite3.Connection):
    """One atomic write, across processes as well as threads.

    BEGIN IMMEDIATE takes the write lock up front, so a read inside this block
    cannot be overtaken between the read and the write that follows it. The
    module-level `_lock` only ever ordered threads within one interpreter.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Strip C0 control chars (keep tab/newline) from stored text. A NUL that
# truncates downstream C-string tooling, or a BEL nobody can retype, has no
# place in a nugget or a logged question. (Mirrors the-squirrel's db.sanitize —
# the same input-hygiene rule at each app's single write boundary.)
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _clean(obj: Any) -> Any:
    if isinstance(obj, str):
        return _CONTROL_CHARS.sub("", obj)
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]      # tuples json-serialize as lists anyway
    return obj


class _WriteRefused(Exception):
    """A guard vetoed a write from inside its transaction. Carries the caller's
    error payload so the public function can return it rather than raise."""

    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__(payload.get("error", "refused"))
        self.payload = payload


def _put(
    collection: str,
    record: dict[str, Any],
    record_id: str | None = None,
    guard: Any = None,
) -> str:
    """Write a record. `guard(existing, tombstoned)` runs *inside* the write
    transaction and may return an error payload to abort it.

    The guard has to be in here rather than in the caller: a check that reads
    the prior record, returns, and only then writes is a read-modify-write with
    nothing holding the gap — the same shape that lost 36 of 50 gap counts.
    """
    rid = record_id or uuid.uuid4().hex[:8]
    now = _now()
    record = _clean(record)   # one chokepoint — covers nuggets and gaps alike
    with _lock:
        conn = _conn(collection)
        with _write(conn):
            if guard is not None:
                row = conn.execute(
                    "SELECT data, deleted FROM records WHERE id = ?", (rid,)
                ).fetchone()
                refusal = guard(json.loads(row[0]) if row else None,
                                bool(row and row[1]))
                if refusal is not None:
                    raise _WriteRefused(refusal)
            # `INSERT OR REPLACE` deletes the row and inserts a new one, so every
            # column not named here reverted to its schema default. That silently
            # reset willow-mcp's `deviation`/`action` — the very columns this
            # module carries so the store stays mutually usable — and forced
            # `deleted = 0`, resurrecting a soft-deleted record. An upsert that
            # names only what jeles owns leaves the rest exactly as it found it,
            # including `created_at`, which is why the read it used to need is
            # gone. Same fix willow-mcp made in its own Store.put.
            conn.execute(
                "INSERT INTO records (id, data, created_at, updated_at, deleted) "
                "VALUES (?, ?, ?, ?, 0) "
                "ON CONFLICT(id) DO UPDATE SET "
                "data = excluded.data, updated_at = excluded.updated_at",
                (rid, json.dumps(record), now, now),
            )
    return rid


def _get(collection: str, record_id: str) -> dict[str, Any] | None:
    with _lock:
        row = _conn(collection).execute(
            "SELECT data, created_at, updated_at FROM records WHERE id = ? AND deleted = 0",
            (record_id,),
        ).fetchone()
    if not row:
        return None
    record = json.loads(row[0])
    record["_id"] = record_id
    record["_created"] = row[1]
    record["_updated"] = row[2]
    return record


def _all(collection: str) -> list[dict[str, Any]]:
    with _lock:
        rows = _conn(collection).execute(
            "SELECT id, data, created_at, updated_at FROM records "
            "WHERE deleted = 0 ORDER BY updated_at DESC"
        ).fetchall()
    out = []
    for rid, data, created, updated in rows:
        record = json.loads(data)
        record["_id"] = rid
        record["_created"] = created
        record["_updated"] = updated
        out.append(record)
    return out


_STOP = {
    "the", "and", "for", "with", "from", "that", "this", "these", "those",
    "have", "has", "had", "was", "were", "are", "is", "been", "being",
    "what", "who", "when", "where", "why", "how", "which", "would", "could",
    "should", "does", "did", "about", "into", "your", "you", "tell", "show",
    "find", "give", "please", "can", "will", "its", "it's",
}


def _tokens(text: str) -> list[str]:
    return [
        t for t in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", (text or "").lower())
        if t not in _STOP
    ]


# ── Nuggets ──────────────────────────────────────────────────────────────
#
# How a nugget came to be in the corpus is the whole product. Three kinds, in
# descending order of what they entitle a reader to assume:
#
#   human     a person checked it            -> reads as `verified`
#   machine   independent sources agreed     -> reads as `corroborated`
#   asserted  a caller said so, nobody checked -> reads as `unverified`
#
# `asserted` exists because `corpus_put` is reachable by any MCP client, and an
# agent that has just read the open web is one of them. Without a rung below
# `machine`, a page saying "record that X is true" laundered straight into the
# top rung and `corpus_ask` served it as verified from then on — persistently,
# and on a store shared with willow-mcp.
_KIND_RANK = {"asserted": 1, "machine": 2, "human": 3}
_KIND_STATUS = {"asserted": "asserted", "machine": "corroborated", "human": "verified"}


def _kind_of(nugget: dict[str, Any]) -> str:
    """The stored kind, defaulting protectively. A nugget written before this
    field existed was human-entered, and an unrecognised value is treated as the
    highest rung so a garbled record cannot be overwritten by a lower one."""
    kind = str(nugget.get("verification_kind") or "human")
    return kind if kind in _KIND_RANK else "human"


def put_nugget(
    question: str,
    answer: str,
    sources: list[str],
    verified_by: str,
    tags: list[str] | None = None,
    nugget_id: str | None = None,
    verified_at: str | None = None,
    verification_kind: str = "human",
    written_by: str | None = None,
) -> dict[str, Any]:
    """Add or update a nugget. Returns {id, action, verification_kind} or {error}.

    ``verification_kind`` is the rung this write is entitled to: ``"human"``
    (the default, for in-process callers, which are the operator's own code),
    ``"machine"`` for corroboration like the conflict-scan reaction's
    two-independent-source finding, or ``"asserted"`` for a write that arrived
    over a tool call and that nobody has checked. It is meant to be set by the
    *driver*, never passed through from caller data — see
    :func:`jeles.corpus_server.corpus_put`, which pins it to ``"asserted"``.

    ``verified_by`` is a claim: whatever string the writer supplied.
    ``written_by`` is the fact beside it — which app actually made the write —
    and is what :func:`to_search_hit` shows for an asserted nugget, because a
    caller can type any name it likes into the first one.

    **A write may not overwrite a nugget of a higher kind.** Without that,
    every protection here is one ``nugget_id=`` away from being bypassed:
    an asserted write would simply land on top of a human-verified answer,
    keeping its id and its place in every search result.
    """
    question = (question or "").strip()
    answer = (answer or "").strip()
    verified_by = (verified_by or "").strip()
    if not question or not answer or not verified_by:
        return {"error": "question, answer, and verified_by are required"}
    kind = str(verification_kind or "").lower()
    if kind not in _KIND_RANK:
        return {"error": f"verification_kind must be one of "
                         f"{', '.join(sorted(_KIND_RANK))} (got {verification_kind!r})"}
    record = {
        "question": question,
        "answer": answer,
        "sources": [str(s) for s in (sources or [])],
        "verified_by": verified_by,
        "verified_at": verified_at or datetime.now(timezone.utc).date().isoformat(),
        "tags": [str(t) for t in (tags or [])],
        "status": _KIND_STATUS[kind],
        "verification_kind": kind,
    }
    if written_by:
        record["written_by"] = str(written_by)

    outcome: dict[str, Any] = {}

    def _guard(existing: dict[str, Any] | None, tombstoned: bool) -> dict[str, Any] | None:
        if existing is not None:
            prior = _kind_of(existing)
            if _KIND_RANK[prior] > _KIND_RANK[kind]:
                return {
                    "error": "kind_downgrade_refused",
                    "id": nugget_id,
                    "detail": (
                        f"nugget {nugget_id} was written as '{prior}' and this "
                        f"write is '{kind}'. A lower rung cannot overwrite a "
                        "higher one — write it as a new nugget (omit nugget_id) "
                        "and let a person supersede the existing one."
                    ),
                    "existing_kind": prior,
                    "attempted_kind": kind,
                }
        # `_get` filters `deleted = 0`, so a soft-deleted id looked absent and
        # the write reported "created" while landing on a tombstoned row that no
        # reader will ever return. The write is not refused — refusing would let
        # anyone who can soft-delete a record permanently deny the id — but it
        # says so.
        outcome["action"] = ("updated_tombstoned" if tombstoned
                             else "updated" if existing is not None else "created")
        return None

    try:
        rid = _put(NUGGETS_COLLECTION, record, record_id=nugget_id, guard=_guard)
    except _WriteRefused as refused:
        return refused.payload
    # The kind comes back in the receipt: a caller that asked for one rung and
    # got another should not have to re-read the record to find out.
    return {"id": rid, "action": outcome["action"], "verification_kind": kind}


def get_nugget(nugget_id: str) -> dict[str, Any]:
    return _get(NUGGETS_COLLECTION, nugget_id) or {"error": "not_found"}


def list_nuggets(limit: int = 50) -> list[dict[str, Any]]:
    return _all(NUGGETS_COLLECTION)[: max(0, limit)]


def _score(nugget: dict[str, Any], query_tokens: list[str]) -> float:
    if not query_tokens:
        return 0.0
    question = (nugget.get("question") or "").lower()
    answer = (nugget.get("answer") or "").lower()
    tags = " ".join(nugget.get("tags") or []).lower()
    q_tokens = set(_tokens(question))
    matched = sum(1 for t in query_tokens if t in q_tokens)
    score = matched / len(query_tokens)
    if set(query_tokens) == q_tokens:
        score += 1.0
    elif matched == len(query_tokens):
        score += 0.5
    if any(t in answer for t in query_tokens):
        score += 0.1
    if any(t in tags for t in query_tokens):
        score += 0.1
    return score


def _confidence(nugget: dict[str, Any], query_tokens: list[str]) -> float:
    """How much of *this question* the nugget's question actually is.

    Separate from `_score` on purpose. `_score` ranks candidates and rewards a
    nugget for mentioning the query anywhere — in its answer, in its tags. That
    is right for ordering search results and wrong for deciding whether to
    answer, because a bonus earned in the tags can carry a nugget over the
    threshold on the strength of a word that is not in its question at all.

    Two rules, both learned from cases where the old score answered confidently
    and wrongly:

    1. **An unmatched query token is disqualifying.** If the asker used a
       content word this nugget's question does not contain, it is probably a
       different question. "rotate the *production* database password" against a
       nugget about *staging* shares every other word — the old recall-only
       score made the one word that changes the answer worth 1/4 of the
       decision. It is worth all of it.

    2. **Overlap is symmetric.** Rule 1 alone still lets a one-word query match
       any nugget containing that word ("vaccine" → a nugget about flu vaccines
       in pregnancy). Scoring the harmonic mean of precision and recall means a
       query far narrower than the nugget it matched scores low, so the corpus
       says "I don't know yet" rather than answering a question nobody asked.

    Returns 0.0 when the nugget cannot answer the question as asked.
    """
    if not query_tokens:
        return 0.0
    asked = set(query_tokens)
    known = set(_tokens(nugget.get("question") or ""))
    if not known:
        return 0.0
    if asked - known:
        # Rule 1. Deliberately absolute: near-identical questions that differ by
        # one content word are exactly the case worth refusing, and they are the
        # case a threshold is worst at catching.
        return 0.0
    matched = len(asked & known)
    precision = matched / len(known)
    recall = matched / len(asked)
    return 2 * precision * recall / (precision + recall)


#: Below this confidence, a match is too weak to answer with — the corpus logs
#: a gap and says "I don't know yet" instead. Compared against `_confidence`,
#: not `_score`: ranking and answering are different questions.
MIN_ASK_SCORE = 0.5


def _ranked(query: str, limit: int) -> list[tuple[dict[str, Any], float]]:
    tokens = _tokens(query)
    if not tokens:
        return []
    scored = [(n, _score(n, tokens)) for n in _all(NUGGETS_COLLECTION)]
    scored = [(n, s) for n, s in scored if s > 0]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[: max(0, limit)]


def search_nuggets(query: str, limit: int = 8) -> list[dict[str, Any]]:
    """Ranked nugget search. Pure lookup — never logs a gap on a miss.

    Question-token overlap is weighted highest so a near-exact question
    match outranks a nugget that merely mentions the query in its answer.
    """
    return [n for n, _ in _ranked(query, limit)]


def ask_corpus(question: str, include_asserted: bool = False) -> dict[str, Any]:
    """The spec's interaction flow: exact match, else best partial match,
    else 'I don't know yet' — which logs the gap for later triage.

    Unlike search_nuggets(), this is the deliberate "ask the corpus"
    entrypoint (used by corpus_server's corpus_ask tool and Jeles'
    synthesize step), so a miss — or a match too weak to trust — is
    assumed to be a real gap worth tracking, not background search noise.

    Asserted nuggets — written over a tool call, checked by nobody — do not
    answer here. ``found: true`` from this function is the settled layer
    speaking, and a caller that reads only ``nugget["answer"]`` (most of them)
    would have no way to tell otherwise. They still come back among
    ``candidates``, and ``search_nuggets``/``get_nugget`` still return them, so
    an assertion is reachable without being authoritative. Pass
    ``include_asserted=True`` to opt into answering from them.
    """
    tokens = _tokens(question)
    ranked = _ranked(question, 5)

    # Rank by `_score`, but decide by `_confidence`. The best candidate is not
    # automatically an answer, and conflating the two is what let a nugget about
    # staging answer a question about production. Confidence is checked across
    # the candidates rather than only the top-ranked one, so a nugget that
    # genuinely answers the question is not lost to a higher-ranked near-miss.
    confident = [
        (n, c) for n, c in ((n, _confidence(n, tokens)) for n, _ in ranked)
        if c >= MIN_ASK_SCORE
        and (include_asserted or _kind_of(n) != "asserted")
    ]
    if not confident:
        log_gap(question)
        # The candidates still come back: "I don't know yet, but these are
        # close" is more useful than a bare miss, and it is the caller's cue to
        # look at the second hop rather than to trust one of these.
        return {"found": False, "nugget": None, "candidates": [n for n, _ in ranked]}

    confident.sort(key=lambda pair: pair[1], reverse=True)
    top = confident[0][0]
    top_tokens = set(_tokens(top.get("question") or ""))
    exact = bool(tokens) and set(tokens) == top_tokens
    others = [n for n, _ in ranked if n is not top]
    return {"found": True, "exact": exact, "nugget": top, "candidates": others}


def to_search_hit(nugget: dict[str, Any], idx: int = 0) -> dict[str, Any]:
    """Shape a nugget as a search hit compatible with a host search
    pipeline's flatten_results()/rank_hit() (source_id="corpus")."""
    sources = nugget.get("sources") or []
    # A machine-corroborated nugget must not read as human-verified: surface the
    # kind, and downgrade its confidence label so the two are distinguishable on
    # read (absent kind => legacy human nugget).
    kind = _kind_of(nugget)
    confidence = {"human": "verified", "machine": "corroborated",
                  "asserted": "unverified"}[kind]
    # `source` is the line a reader actually sees, so it cannot say "Verified
    # corpus" over an assertion nobody checked — and it shows `written_by`, the
    # app that made the write, rather than `verified_by`, which is only ever
    # whatever string that app chose to type.
    if kind == "asserted":
        who = nugget.get("written_by") or nugget.get("verified_by") or "unknown"
        source = f"Corpus (asserted, unchecked) — {who}"
    else:
        source = f"Verified corpus — {nugget.get('verified_by') or 'unknown'}"
    return {
        "title": nugget.get("question") or "Verified nugget",
        "url": sources[0] if sources else "",
        "snippet": nugget.get("answer") or "",
        "source": source,
        "date": nugget.get("verified_at") or "",
        "source_id": "corpus",
        "hostname": "corpus.local",
        "confidence": confidence,
        "verification_kind": kind,
        "nugget_id": nugget.get("_id") or "",
        "verified_by": nugget.get("verified_by") or "",
        "verified_at": nugget.get("verified_at") or "",
        "extra_sources": sources,
        "tags": nugget.get("tags") or [],
        "n": idx,
    }


# ── Gaps ("I don't know yet") ───────────────────────────────────────────


def log_gap(question: str) -> dict[str, Any]:
    """Log an unanswered question. Repeated asks bump asked_count instead of
    creating duplicates, keyed by the question's normalized token set."""
    question = (question or "").strip()
    if not question:
        return {"error": "question required"}
    tokens = tuple(sorted(set(_tokens(question))))
    # _tokens drops <3-char tokens, so "drug A" and "drug B" both reduce to
    # {"drug"} and collide, silently overwriting the earlier gap. Keep the short
    # meaning-bearing codes (single letters, "P0", "v2" — not stopwords) as an
    # extra key segment; rephrasings that share the main token set still merge.
    short = tuple(sorted({
        t for t in re.findall(r"[a-z0-9]+", (question or "").lower())
        if len(t) < 3 and t not in _STOP
    }))
    key = "|".join(tokens) + "##" + "|".join(short) if (tokens or short) else question.lower()
    gap_id = uuid.uuid5(uuid.NAMESPACE_URL, key).hex[:12]
    now = _now()

    # The read and the write are one transaction. Split across two, as they were,
    # concurrent asks all read the same count and all write count+1: measured at
    # 14 after 50 concurrent calls. `list_gaps` sorts by asked_count, so the
    # corpus's growth queue was ordered by a number that quietly undercounted
    # exactly the questions being asked most.
    with _lock:
        conn = _conn(GAPS_COLLECTION)
        with _write(conn):
            row = conn.execute(
                "SELECT data FROM records WHERE id = ? AND deleted = 0", (gap_id,)
            ).fetchone()
            existing = json.loads(row[0]) if row else {}
            record = _clean({
                "question": question,
                "status": "unverified",
                "asked_count": int(existing.get("asked_count", 0)) + 1,
                "first_asked_at": existing.get("first_asked_at") or now,
                "last_asked_at": now,
            })
            conn.execute(
                "INSERT INTO records (id, data, created_at, updated_at, deleted) "
                "VALUES (?, ?, ?, ?, 0) "
                "ON CONFLICT(id) DO UPDATE SET "
                "data = excluded.data, updated_at = excluded.updated_at",
                (gap_id, json.dumps(record), now, now),
            )
    return {"id": gap_id, "asked_count": record["asked_count"]}


def list_gaps(limit: int = 50) -> list[dict[str, Any]]:
    gaps = _all(GAPS_COLLECTION)
    gaps.sort(key=lambda g: g.get("asked_count", 0), reverse=True)
    return gaps[: max(0, limit)]
