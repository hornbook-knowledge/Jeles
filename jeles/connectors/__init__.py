"""Optional maintained-client backends for ``jeles.sources``.

Install with ``pip install "jeles[connectors]"``. Base ``jeles`` stays
stdlib-only; these imports are never taken at package import time. Each
``search_*`` in ``jeles.sources`` asks here first and falls back to the
urllib implementation when this extra is absent or a client raises.

**Egress trade (Loki F3, accepted):** when a connector client runs, HTTP goes
through that library's own stack (often ``requests``), **not**
``jeles._egress`` / ``sources._urlopen``. Redirect refusal, HTTPS-only, and
byte caps therefore apply only on the urllib twin path. That is inherent to
adopting maintained clients; twins keep the hardened guard. Do not assume a
connector hit was bounded the same way as a twin hit.

See store ``jeles-adopt-clients-2026-09-30`` / adoption map.
"""

from __future__ import annotations

from collections.abc import Callable


def available() -> bool:
    """True when the connectors extra's core scholarly clients import."""
    try:
        import habanero  # noqa: F401
        import pyalex  # noqa: F401
    except ImportError:
        return False
    return True


def get_search(name: str) -> Callable[..., list] | None:
    """Return ``scholarly.search_<name>`` if that client path is importable."""
    try:
        from jeles.connectors import scholarly
    except ImportError:
        return None
    return getattr(scholarly, f"search_{name}", None)
