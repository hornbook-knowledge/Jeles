"""Jeles' verified-nugget corpus — storage and ranked lookup.

A nugget is a human-verified question/answer pair with citations:
{question, answer, sources, verified_by, verified_at, tags}.

Storage reuses the same SQLite shape as willow-mcp's SOIL `Store` (a
`records` table under `<collection>/store.db`, keyed by WILLOW_STORE_ROOT),
so nuggets written here are already visible to a Willow-style soil scan
with no extra wiring, and the corpus stays readable by anything else that
understands a Willow-style SOIL collection.

This module has no MCP dependency and does no network I/O — see
corpus_server.py for the FastMCP wrapper that exposes it as a standalone,
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
        raise ValueError(f"invalid collection name (must match {_COLLECTION_RE.pattern}): {collection!r}")

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
    return Path(os.environ.get("WILLOW_STORE_ROOT", str(Path.home() / ".willow" / "store"))).expanduser()


def _conn(collection: str) -> sqlite3.Connection:
    _validate_collection(collection)
    db_path = _store_root() / collection / "store.db"
    key = str(db_path)
    with _lock:
        if key not in _conns:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(db_path), check_same_thread=False)
            conn.executescript(_SCHEMA)
            _migrate_records(conn)
            conn.commit()
            _conns[key] = conn
        return _conns[key]


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


def _put(collection: str, record: dict[str, Any], record_id: str | None = None) -> str:
    rid = record_id or uuid.uuid4().hex[:8]
    now = _now()
    record = _clean(record)   # one chokepoint — covers nuggets and gaps alike
    with _lock:
        conn = _conn(collection)
        existing = conn.execute("SELECT created_at FROM records WHERE id = ?", (rid,)).fetchone()
        created = existing[0] if existing else now
        conn.execute(
            "INSERT OR REPLACE INTO records (id, data, created_at, updated_at, deleted) "
            "VALUES (?, ?, ?, ?, 0)",
            (rid, json.dumps(record), created, now),
        )
        conn.commit()
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


def put_nugget(
    question: str,
    answer: str,
    sources: list[str],
    verified_by: str,
    tags: list[str] | None = None,
    nugget_id: str | None = None,
    verified_at: str | None = None,
    verification_kind: str = "human",
) -> dict[str, Any]:
    """Add or update a verified nugget. Returns {id, action} or {error}.

    ``verification_kind`` distinguishes a human check (``"human"``, the default)
    from machine corroboration (``"machine"`` — e.g. the conflict-scan reaction's
    two-independent-source finding). It is meant to be set by the *driver*, not
    passed through from untrusted caller data, so a machine finding can't render
    as human-verified on read (see :func:`to_search_hit`).
    """
    question = (question or "").strip()
    answer = (answer or "").strip()
    verified_by = (verified_by or "").strip()
    if not question or not answer or not verified_by:
        return {"error": "question, answer, and verified_by are required"}
    kind = "machine" if str(verification_kind).lower() == "machine" else "human"
    record = {
        "question": question,
        "answer": answer,
        "sources": [str(s) for s in (sources or [])],
        "verified_by": verified_by,
        "verified_at": verified_at or datetime.now(timezone.utc).date().isoformat(),
        "tags": [str(t) for t in (tags or [])],
        "status": "verified",
        "verification_kind": kind,
    }
    action = "updated" if (nugget_id and _get(NUGGETS_COLLECTION, nugget_id)) else "created"
    rid = _put(NUGGETS_COLLECTION, record, record_id=nugget_id)
    return {"id": rid, "action": action}


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


MIN_ASK_SCORE = 0.5  # below this, a "match" is too weak to answer with — treat as a gap


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


def ask_corpus(question: str) -> dict[str, Any]:
    """The spec's interaction flow: exact match, else best partial match,
    else 'I don't know yet' — which logs the gap for later triage.

    Unlike search_nuggets(), this is the deliberate "ask the corpus"
    entrypoint (used by corpus_server's corpus_ask tool and Jeles'
    synthesize step), so a miss — or a match too weak to trust — is
    assumed to be a real gap worth tracking, not background search noise.
    """
    ranked = _ranked(question, 5)
    if not ranked or ranked[0][1] < MIN_ASK_SCORE:
        log_gap(question)
        return {"found": False, "nugget": None, "candidates": [n for n, _ in ranked]}
    tokens = set(_tokens(question))
    top, _top_score = ranked[0]
    top_tokens = set(_tokens(top.get("question") or ""))
    exact = bool(tokens) and tokens == top_tokens
    return {"found": True, "exact": exact, "nugget": top, "candidates": [n for n, _ in ranked[1:]]}


def to_search_hit(nugget: dict[str, Any], idx: int = 0) -> dict[str, Any]:
    """Shape a nugget as a search hit compatible with a host search
    pipeline's flatten_results()/rank_hit() (source_id="corpus")."""
    sources = nugget.get("sources") or []
    # A machine-corroborated nugget must not read as human-verified: surface the
    # kind, and downgrade its confidence label so the two are distinguishable on
    # read (absent kind => legacy human nugget).
    kind = nugget.get("verification_kind") or "human"
    return {
        "title": nugget.get("question") or "Verified nugget",
        "url": sources[0] if sources else "",
        "snippet": nugget.get("answer") or "",
        "source": f"Verified corpus — {nugget.get('verified_by') or 'unknown'}",
        "date": nugget.get("verified_at") or "",
        "source_id": "corpus",
        "hostname": "corpus.local",
        "confidence": "verified" if kind == "human" else "corroborated",
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
    existing = _get(GAPS_COLLECTION, gap_id)
    record = {
        "question": question,
        "status": "unverified",
        "asked_count": (existing or {}).get("asked_count", 0) + 1,
        "first_asked_at": (existing or {}).get("first_asked_at") or _now(),
        "last_asked_at": _now(),
    }
    rid = _put(GAPS_COLLECTION, record, record_id=gap_id)
    return {"id": rid, "asked_count": record["asked_count"]}


def list_gaps(limit: int = 50) -> list[dict[str, Any]]:
    gaps = _all(GAPS_COLLECTION)
    gaps.sort(key=lambda g: g.get("asked_count", 0), reverse=True)
    return gaps[: max(0, limit)]
