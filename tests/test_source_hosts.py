"""`SOURCES[...]["hosts"]` must keep matching the code it describes.

The registry gained a `hosts` field so a consumer can ask "which hostnames does
this fleet actually query?" as *data* rather than by re-deriving it. A declared
list that nothing checks is just a second copy waiting to drift — and drift here
is silent in the direction that matters: a source repointed at a new API host
keeps working, while every consumer's idea of what jeles talks to quietly goes
stale.

So this reads the module's own AST and compares both directions. It is a
superset rule rather than a call-site trace: any http(s) literal in a source's
body must be declared, whether or not this file can prove a request is made
from it. Tracing exactly which literals reach `_get`/`_fetch` breaks on
ordinary control flow — `search_thesportsdb` builds its endpoints in a
list-of-tuples and unpacks them in a `for`, which a naive tracer misses
entirely — and a rule that silently under-reports is worse than one that asks
for an explicit exemption.

The one exemption is `NAMESPACE_URI_HOSTS`: XML/RDF namespace identifiers look
like URLs and are never contacted. willow-mcp's trusted-domain list had picked
up `www.w3.org` from arXiv's Atom namespace and treated it as an institution.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from urllib.parse import urlparse

from jeles import sources

_SRC = Path(sources.__file__).read_text()
_TREE = ast.parse(_SRC)
_URL_RE = re.compile(r"https?://[^\s\"'<>{}\\]+")
_FUNCS = {n.name: n for n in ast.walk(_TREE) if isinstance(n, ast.FunctionDef)}


def _literal_hosts(fn: ast.FunctionDef) -> set[str]:
    """Hosts in every http(s) literal in this function, f-string prefixes included."""
    hosts: set[str] = set()
    for sub in ast.walk(fn):
        text = ""
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            text = sub.value
        elif isinstance(sub, ast.JoinedStr):
            for value in sub.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    text += value.value
                else:
                    break          # stop at the first interpolation
        for match in _URL_RE.findall(text):
            host = (urlparse(match).netloc or "").lower()
            if host and "{" not in host and "%" not in host:
                hosts.add(host)
    return hosts


def test_every_source_declares_the_hosts_its_code_mentions():
    """Undeclared host -> a consumer's picture of jeles' egress is incomplete."""
    undeclared = {}
    for sid, cfg in sources.SOURCES.items():
        declared = set(cfg.get("hosts", ()))
        found = _literal_hosts(_FUNCS[f"search_{sid}"]) - sources.NAMESPACE_URI_HOSTS
        missing = found - declared
        if missing:
            undeclared[sid] = sorted(missing)
    assert not undeclared, (
        f"these sources contact hosts they do not declare: {undeclared}. Add "
        f"them to SOURCES[...]['hosts'], or to NAMESPACE_URI_HOSTS if the URL "
        f"is a namespace identifier that is never fetched."
    )


def test_no_source_declares_a_host_its_code_never_mentions():
    """The other direction. A phantom entry is how a list starts lying — it
    survives the source being repointed or removed, and reads as evidence."""
    phantom = {}
    for sid, cfg in sources.SOURCES.items():
        declared = set(cfg.get("hosts", ()))
        extra = declared - _literal_hosts(_FUNCS[f"search_{sid}"])
        if extra:
            phantom[sid] = sorted(extra)
    assert not phantom, f"declared but absent from the code: {phantom}"


def test_every_registered_source_declares_at_least_one_host():
    """A source that contacts nothing is either dead or not a source."""
    empty = [sid for sid, cfg in sources.SOURCES.items() if not cfg.get("hosts")]
    assert empty == [], empty


def test_registered_hosts_is_the_union_and_respects_opt_in():
    every = sources.registered_hosts()
    assert every == {h for cfg in sources.SOURCES.values() for h in cfg.get("hosts", ())}

    # wikipedia is the opt-in source; excluding it must drop its host and
    # nothing else. Pinned because the default fan-out is the set that a
    # consumer asking "what does jeles reach by default?" actually means.
    default_only = sources.registered_hosts(include_opt_in=False)
    assert default_only <= every
    assert "en.wikipedia.org" in every
    assert "en.wikipedia.org" not in default_only


def test_namespace_hosts_are_not_presented_as_sources():
    """`www.w3.org` reached willow-mcp's institutional trust list this way."""
    assert "www.w3.org" not in sources.registered_hosts()
    assert "purl.org" not in sources.registered_hosts()
    # ...and they really are still in the code, so the exemption is load-bearing
    # rather than a leftover.
    everything = set()
    for sid in sources.SOURCES:
        everything |= _literal_hosts(_FUNCS[f"search_{sid}"])
    assert everything >= sources.NAMESPACE_URI_HOSTS, (
        "NAMESPACE_URI_HOSTS names a host no source mentions any more — drop it "
        "rather than carrying an exemption for nothing"
    )


def test_list_sources_exposes_hosts():
    """The registry's public read surface has to carry it, or a consumer is
    back to importing SOURCES directly."""
    listed = {entry["id"]: entry for entry in sources.list_sources()}
    assert listed["arxiv"]["hosts"] == sources.SOURCES["arxiv"]["hosts"]
    assert all(isinstance(entry["hosts"], list) for entry in listed.values())
