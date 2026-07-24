"""Jeles — the verified-corpus organ and its canonical persona.

A small, dependency-light package extracted from the Ask Jeles app so the
verified-nugget corpus, its standalone MCP server, the best-effort fleet
gap-forwarder, and the canonical Jeles persona can be consumed by any host.

Public surface:
    corpus              — pure storage/ranking of verified nuggets + gaps
    corpus_server       — standalone FastMCP server over the corpus
    willow_mcp_client   — best-effort gap forwarding to willow-mcp
    load_persona()      — load the canonical Jeles persona JSON
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

__version__ = "0.1.0"

_PERSONA_PATH = Path(__file__).resolve().parent / "persona" / "jeles_persona.json"


def persona_path() -> Path:
    """Absolute path to the canonical Jeles persona JSON shipped in this
    package. This package is the persona's canonical home."""
    return _PERSONA_PATH


@lru_cache(maxsize=1)
def load_persona() -> dict[str, Any]:
    """Load and return the canonical Jeles persona as a dict.

    Stdlib-only, no I/O beyond a single file read. Cached after the first
    call. Mutating the returned dict mutates the cached copy — treat it as
    read-only, or copy it if you need to edit.
    """
    return json.loads(_PERSONA_PATH.read_text(encoding="utf-8"))


__all__ = ["load_persona", "persona_path", "__version__"]
