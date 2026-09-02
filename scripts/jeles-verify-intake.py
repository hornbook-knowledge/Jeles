#!/usr/bin/env python3
"""Promote asserted Jeles intake nuggets to human-verified (in-process only).

Human verification is deliberately not reachable via corpus_put MCP — only
operator scripts like this one may set verification_kind=human.

    source ~/github/willow-memory/.willow/fleet.env
    .venv/bin/python3 scripts/jeles-verify-intake.py paperclip-genealogy.json
    .venv/bin/python3 scripts/jeles-verify-intake.py --tag institutional-genealogy
    .venv/bin/python3 scripts/jeles-verify-intake.py paperclip-genealogy.json --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from jeles.intake import bootstrap_fleet_env, find_intake_dir, _load_json


def _find_by_question(all_nuggets: list[dict], question: str) -> dict | None:
    q = question.strip()
    for n in all_nuggets:
        if (n.get("question") or "").strip() == q:
            return n
    return None


def verify_from_file(
    intake_path: Path,
    *,
    verified_by: str,
    dry_run: bool,
) -> dict[str, int]:
    from jeles import corpus

    data = _load_json(intake_path)
    domain = data.get("domain", intake_path.stem)
    all_nuggets = corpus.list_nuggets(limit=10000)
    counts = {"promoted": 0, "skipped": 0, "missing": 0, "already": 0, "errors": 0}
    today = datetime.now(timezone.utc).date().isoformat()

    for pair in data.get("pairs", []):
        question = pair["source_text"].strip()
        answer = pair["target_text"].strip()
        sources = [str(s) for s in (pair.get("sources") or [])]
        tags = [domain, "willow-intake"]
        if pair.get("reason"):
            tags.append("has-reason")

        existing = _find_by_question(all_nuggets, question)
        if not existing:
            print(f"  missing: {question[:72]}…")
            counts["missing"] += 1
            continue

        kind = existing.get("verification_kind") or "human"
        if kind == "human":
            counts["already"] += 1
            continue

        nid = existing.get("_id", "")
        if dry_run:
            print(f"  would promote: {question[:72]}…")
            counts["promoted"] += 1
            continue

        evidence = dict(existing.get("evidence") or {})
        evidence["operator_review"] = {
            "verified_by": verified_by,
            "verified_at": today,
            "intake_file": intake_path.name,
            "method": "public-osint-operator-review",
        }

        result = corpus.put_nugget(
            question=question,
            answer=answer,
            sources=sources or list(existing.get("sources") or []),
            verified_by=verified_by,
            tags=tags,
            nugget_id=nid,
            verified_at=today,
            verification_kind="human",
            written_by=existing.get("written_by") or "jeles-intake",
            evidence=evidence,
        )
        if result.get("error"):
            print(f"  error: {question[:60]!r}: {result['error']}")
            counts["errors"] += 1
        else:
            print(f"  verified: {question[:72]}…")
            counts["promoted"] += 1

    return counts


def verify_by_tag(
    tag: str,
    *,
    verified_by: str,
    dry_run: bool,
) -> dict[str, int]:
    from jeles import corpus

    all_nuggets = corpus.list_nuggets(limit=10000)
    counts = {"promoted": 0, "skipped": 0, "missing": 0, "already": 0, "errors": 0}
    today = datetime.now(timezone.utc).date().isoformat()

    for existing in all_nuggets:
        tags = existing.get("tags") or []
        if tag not in tags:
            continue
        kind = existing.get("verification_kind") or "human"
        if kind == "human":
            counts["already"] += 1
            continue

        question = (existing.get("question") or "").strip()
        if dry_run:
            print(f"  would promote: {question[:72]}…")
            counts["promoted"] += 1
            continue

        evidence = dict(existing.get("evidence") or {})
        evidence["operator_review"] = {
            "verified_by": verified_by,
            "verified_at": today,
            "method": "public-osint-operator-review",
            "tag": tag,
        }

        result = corpus.put_nugget(
            question=question,
            answer=(existing.get("answer") or "").strip(),
            sources=list(existing.get("sources") or []),
            verified_by=verified_by,
            tags=list(tags),
            nugget_id=existing.get("_id", ""),
            verified_at=today,
            verification_kind="human",
            written_by=existing.get("written_by") or "jeles-intake",
            evidence=evidence,
        )
        if result.get("error"):
            counts["errors"] += 1
        else:
            counts["promoted"] += 1

    return counts


def main(argv: list[str] | None = None) -> int:
    bootstrap_fleet_env()
    intake_dir = find_intake_dir()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "file",
        nargs="?",
        help="Intake JSON filename in jeles-intake/ (e.g. paperclip-genealogy.json)",
    )
    parser.add_argument("--tag", help="Promote all asserted nuggets with this tag")
    parser.add_argument(
        "--verified-by",
        default="Sean Campbell",
        help="Human verifier name (default: Sean Campbell)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if not args.file and not args.tag:
        parser.error("provide intake file name or --tag")

    if args.file:
        path = Path(args.file)
        if not path.is_file():
            path = intake_dir / args.file
        if not path.is_file():
            print(f"not found: {path}", file=sys.stderr)
            return 1
        print(f"== verify {path.name} as human ({args.verified_by})")
        counts = verify_from_file(path, verified_by=args.verified_by, dry_run=args.dry_run)
    else:
        print(f"== verify tag={args.tag!r} as human ({args.verified_by})")
        counts = verify_by_tag(args.tag, verified_by=args.verified_by, dry_run=args.dry_run)

    print(
        f"  promoted={counts['promoted']} already={counts['already']} "
        f"missing={counts['missing']} errors={counts['errors']}"
    )
    return 0 if counts["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
