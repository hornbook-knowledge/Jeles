"""corpus.py must stay pure: importing it loads no MCP and no network stack.

Design principle 2 — `corpus.py` has no MCP, no network, no side effects
beyond SQLite. This test imports it in a *fresh* subprocess and asserts that
none of the MCP/HTTP/socket machinery got dragged in as an import side
effect. Run in a subprocess so a prior import in this session's interpreter
(e.g. from corpus_server tests) can't mask a real regression.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap


def test_importing_corpus_pulls_in_no_mcp_or_network_modules():
    probe = textwrap.dedent(
        """
        import sys
        import jeles.corpus  # noqa: F401

        forbidden = {
            "mcp",
            "mcp.server",
            "mcp.server.fastmcp",
            "mcp.client",
            "anyio",
            "httpx",
            "httpcore",
            "requests",
            "aiohttp",
            "urllib.request",
            "socket",
            "ssl",
            "asyncio",
        }
        loaded = forbidden & set(sys.modules)
        if loaded:
            print(",".join(sorted(loaded)))
            sys.exit(1)
        sys.exit(0)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "jeles.corpus imported network/MCP modules at import time: "
        f"{result.stdout.strip()!r} (stderr: {result.stderr.strip()!r})"
    )
