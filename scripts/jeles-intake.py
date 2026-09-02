#!/usr/bin/env python3
"""Jeles corpus intake — load local Q/A JSON, probe for research gaps.

From the Jeles checkout (works with system python3 or .venv):

    python3 scripts/jeles-intake.py
    python3 scripts/jeles-intake.py --probe-only
    python3 scripts/jeles-intake.py --load-only

Or explicitly:  .venv/bin/python3 scripts/jeles-intake.py

Override intake directory: JELES_INTAKE_DIR=/path/to/intake
Override store: source ~/github/willow-memory/.willow/fleet.env
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running from the checkout without `pip install -e .`
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from jeles.intake import main

if __name__ == "__main__":
    raise SystemExit(main())
