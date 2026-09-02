#!/usr/bin/env python3
"""Promote asserted commons-domain nuggets to machine (re-seed without full reload).

    source ~/github/willow-memory/.willow/fleet.env
    .venv/bin/python3 scripts/jeles-commons-promote.py
    .venv/bin/python3 scripts/jeles-commons-promote.py --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from jeles.commons import promote_commons_in_store
from jeles.intake import bootstrap_fleet_env


def main(argv: list[str] | None = None) -> int:
    bootstrap_fleet_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    counts = promote_commons_in_store(dry_run=args.dry_run)
    verb = "would promote" if args.dry_run else "promoted"
    print(
        f"{verb}={counts['promoted']} skipped={counts['skipped']} "
        f"errors={counts['errors']}"
    )
    return 0 if counts["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
