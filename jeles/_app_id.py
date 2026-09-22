"""Shared ``JELES_CORPUS_APP_ID`` resolution.

One env var, read by two callers: ``jeles/corpus.py``'s manifest-scoped store
gate (``_manifest_scope``) and ``jeles/willow_mcp_client.py``'s fleet gap
forwarder both need to know which seat the organ is presenting itself as, and
until now they disagreed — corpus.py resolved a locally-configured default
while willow_mcp_client.py's own module-level ``APP_ID`` still defaulted to
the unrelated back-compat value ``ask-jeles`` and never refused the retired
seat at all (Loki F2, rework of gap 3cdeb177af78 / ae23d366). This module is
the one resolver, one default, and one retirement refusal both import,
instead of two copies that can drift.

Base ``jeles`` has zero runtime dependencies, so this stays stdlib-only.
"""

from __future__ import annotations

import os
import re

#: The retired Ask Jeles specialist seat. Never a valid organ id — ae23d366
#: ("Jeles is the organ") exists specifically to end the confusion of the
#: corpus, or its forwarder, running *as* that seat.
RETIRED_APP_ID = "jeles"

#: The organ's own default seat, used only when ``JELES_CORPUS_APP_ID`` is
#: unset or blank. Distinct from `RETIRED_APP_ID` on purpose: an operator who
#: never configured an app id gets a lookup that fails closed under a name
#: that cannot be mistaken for the retired seat, not a silent fallback to it.
DEFAULT_APP_ID = "jeles-corpus"

#: Mirrors willow-mcp's own ``paths._APP_ID_RE`` shape rule exactly — kept as
#: a literal copy rather than an import (base `jeles` has zero runtime
#: dependencies on willow-mcp). Any app id resolved here is validated on the
#: SAME shape willow-mcp's own gate enforces, BEFORE it is ever compared
#: against `RETIRED_APP_ID` or joined into a filesystem path (Loki F1).
#: Without this, a bare string-equality retirement check on the raw env
#: value, later joined straight into ``_apps_root() / app_id``, admitted
#: ``./jeles``, ``jeles/``, ``jeles/.``, ``../mcp_apps/jeles``,
#: ``../outside/evil``, and an absolute path (pathlib silently drops
#: everything left of an absolute right-hand operand in a ``/`` join, so
#: ``_apps_root() / "/etc/passwd"`` is ``/etc/passwd``) — any signed-looking
#: manifest anywhere on disk could set the organ's entire reach.
_APP_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")

#: Mirrors willow-mcp's own ``paths._CONTAINER_DIR_NAMES`` reserved-name
#: guard — the per-app container directories under willow-mcp's
#: ``$WILLOW_HOME``. An app id equal to one of these would collide with a
#: container, not name an app.
RESERVED_APP_IDS = frozenset({"mcp_apps", "schema_maps", "handoffs", "sessions"})


def resolve_app_id() -> tuple[str, str]:
    """``(app_id, source)`` — ``source`` is ``"env"`` when
    ``JELES_CORPUS_APP_ID`` is set to a non-blank value (stripped), else
    ``"default"`` and ``app_id`` is `DEFAULT_APP_ID`. Never substitutes
    `RETIRED_APP_ID` as a default; an explicit ``jeles`` passes through here
    unchanged and is refused by `shape_error`/`retirement_error`, not
    silently swapped for something else.
    """
    raw = os.environ.get("JELES_CORPUS_APP_ID", "").strip()
    if raw:
        return raw, "env"
    return DEFAULT_APP_ID, "default"


def shape_error(app_id: str) -> str | None:
    """``None`` if `app_id` is shape-valid; else the refusal reason.

    Callers must check this BEFORE comparing `app_id` against
    `RETIRED_APP_ID` or joining it into a filesystem path — see the module
    comment on `_APP_ID_RE` (Loki F1).
    """
    if not _APP_ID_RE.match(app_id or ""):
        return f"invalid app_id shape: {app_id!r} (must match {_APP_ID_RE.pattern})"
    if app_id in RESERVED_APP_IDS:
        return f"invalid app_id: {app_id!r} names a container directory, not an app"
    return None


def retirement_error(app_id: str) -> str | None:
    """``None`` unless `app_id` is exactly the retired seat.

    Only meaningful to call once `app_id` has already passed `shape_error` —
    the retirement compare runs on the validated id, never the raw one.
    """
    if app_id == RETIRED_APP_ID:
        return (
            f"{RETIRED_APP_ID!r} is the retired Ask Jeles specialist seat, not "
            'an organ id — ae23d366 ("Jeles is the organ") exists to end '
            "exactly this confusion; pick a distinct app id (the organ's own "
            f"default is {DEFAULT_APP_ID!r})"
        )
    return None


def origin(app_id: str, source: str, manifest_path: object | None = None) -> str:
    """The trailer every refusal carries: which app id was resolved, whether
    it came from ``JELES_CORPUS_APP_ID`` or the default, and — when a
    filesystem path was actually looked at — that path. Shape-invalid ids
    never get a path here: they are refused before any path is built from
    them (Loki F1)."""
    text = (
        f"JELES_CORPUS_APP_ID={app_id!r}"
        if source == "env"
        else f"JELES_CORPUS_APP_ID unset, defaulted to {app_id!r}"
    )
    if manifest_path is None:
        return f" [{text}]"
    return f" [{text}; looked at {manifest_path}]"
