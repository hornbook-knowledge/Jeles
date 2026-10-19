"""Commons vs novel knowledge — classification for intake and seed loading.

Commons (π, Newton's laws, core "way things work" domains) in the bundled
seed land at the ``human`` rung when citable sources exist, without a Nestor
seal: these are knowns, established by the people who discovered them and
kept by the reference works that record them, and the developer has ruled
that they need no seal in the base store. Credit goes to that public record,
not to whoever loaded it: ``verified_by`` names the cited publishers
(:func:`commons_credit`) and ``evidence`` (:func:`commons_evidence`) lists
them, never a ``seal_sig``, so a reader can tell it from a signature and
Nestor reconciliation can find what is still unsealed. Commons arriving
through intake stay at ``machine``.
Novel synthesis (operator research, institutional genealogy) stays ``asserted``
until a human verifies or conflict_scan corroborates.
"""

from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import urlparse

COMMONS_DOMAIN_PREFIXES = ("core-",)
COMMONS_VERIFIED_BY = "commons:bootstrap"
#: `evidence["scheme"]` for a seed commons nugget — deliberately not
#: `nestor-seal-v1`, because nothing here is signed.
COMMONS_EVIDENCE_SCHEME = "public-record-v1"
#: The scheme commons carried before credit moved to the public record.
#: `promote_commons_in_store` re-credits nuggets still carrying it.
LEGACY_COMMONS_SCHEMES = ("developer-attestation-v1",)
#: Display names for the publishers the seed cites most; any other host is
#: credited by its own name.
_PUBLISHERS = {
    "wikipedia.org": "Wikipedia",
    "britannica.com": "Encyclopaedia Britannica",
    "nasa.gov": "NASA",
    "esa.int": "ESA",
    "nih.gov": "NIH",
    "medlineplus.gov": "MedlinePlus (NIH)",
    "cdc.gov": "CDC",
    "who.int": "WHO",
    "noaa.gov": "NOAA",
    "usgs.gov": "USGS",
    "nist.gov": "NIST",
    "bipm.org": "BIPM",
    "loc.gov": "Library of Congress",
    "archives.gov": "US National Archives",
    "congress.gov": "US Congress",
    "un.org": "United Nations",
    "nationalgeographic.org": "National Geographic",
    "nationalgeographic.com": "National Geographic",
    "pewresearch.org": "Pew Research Center",
    "plato.stanford.edu": "Stanford Encyclopedia of Philosophy",
    "iep.utm.edu": "Internet Encyclopedia of Philosophy",
    "my.clevelandclinic.org": "Cleveland Clinic",
    "history.com": "History.com",
    "khanacademy.org": "Khan Academy",
    "smithsonianmag.com": "Smithsonian",
    "si.edu": "Smithsonian",
    "britishmuseum.org": "British Museum",
    "metmuseum.org": "The Met",
    "nobelprize.org": "Nobel Prize",
    "nature.com": "Nature",
}
#: The visibility tier an entry that can answer lands at. willow-mcp's
#: federation filter caps a serve/OAuth caller at "serve" (public < serve <
#: internal), so an answering entry left "internal" never reaches a served
#: session. Asserted research stays "internal": it cannot answer anyway.
SERVE_VISIBILITY = "serve"
INTAKE_VERIFIED_BY = "operator-seat"
NOVEL_VERIFIED_BY = "research-agent"

__all__ = [
    "COMMONS_DOMAIN_PREFIXES",
    "COMMONS_EVIDENCE_SCHEME",
    "COMMONS_VERIFIED_BY",
    "SERVE_VISIBILITY",
    "classification_for_pair",
    "commons_credit",
    "commons_evidence",
    "domain_is_commons",
    "file_classification",
    "has_citable_source",
    "intake_nugget_id",
    "is_commons_domain",
    "pair_classification",
    "promote_commons_in_store",
    "seed_nugget_id",
    "seed_pair_verification",
    "verification_for_intake",
    "visibility_for",
]


def file_classification(data: dict[str, Any]) -> str:
    """File-level default: ``commons`` or ``novel`` (default ``novel``)."""
    raw = (data.get("classification") or "novel").strip().lower()
    return raw if raw in ("commons", "novel") else "novel"


def pair_classification(pair: dict[str, Any], default: str) -> str:
    raw = (pair.get("classification") or default).strip().lower()
    return raw if raw in ("commons", "novel") else default


def is_commons_domain(domain: str) -> bool:
    d = (domain or "").strip().lower()
    return any(d.startswith(prefix) for prefix in COMMONS_DOMAIN_PREFIXES)


def domain_is_commons(domain: str, data: dict[str, Any] | None = None) -> bool:
    if data is not None and file_classification(data) == "commons":
        return True
    return is_commons_domain(domain)


def has_citable_source(sources: list[str]) -> bool:
    if not sources:
        return False
    for s in sources:
        text = str(s).strip()
        if not text:
            continue
        if text.startswith(("http://", "https://")):
            return True
        if text.startswith("jeles-intake/"):
            continue
        return True
    return False


def classification_for_pair(
    *,
    domain: str,
    pair: dict[str, Any],
    data: dict[str, Any] | None,
    sources: list[str],
) -> str:
    pair_cls = (pair.get("classification") or "").strip().lower()
    file_cls = file_classification(data or {})
    if pair_cls == "novel":
        return "novel"
    if pair_cls == "commons":
        return "commons" if has_citable_source(sources) else "novel"
    if file_cls == "novel" and not is_commons_domain(domain):
        return "novel"
    if not has_citable_source(sources):
        return "novel"
    if is_commons_domain(domain) or file_cls == "commons":
        return "commons"
    return "novel"


def seed_pair_verification(
    *,
    domain: str,
    pair: dict[str, Any],
    data: dict[str, Any],
    sources: list[str],
    seal_sig: str,
) -> tuple[str, str]:
    """Return (verification_kind, verified_by) for a seed pair."""
    if seal_sig:
        claimant = (pair.get("verified_by") or data.get("verified_by") or "").strip()
        return "human", claimant or NOVEL_VERIFIED_BY
    bucket = classification_for_pair(
        domain=domain,
        pair=pair,
        data=data,
        sources=sources,
    )
    # `classification_for_pair` already demands a citation, and a commons
    # domain or file unless the pair itself is classified commons.
    if bucket == "commons":
        return "human", commons_credit(sources)
    return "asserted", pair.get("verified_by") or NOVEL_VERIFIED_BY


def visibility_for(kind: str) -> str:
    """``"serve"`` for an entry that can answer (``human`` or ``machine``),
    ``"internal"`` for an ``asserted`` one."""
    return SERVE_VISIBILITY if kind in ("human", "machine") else "internal"


def _publisher(source: str) -> str:
    host = urlparse(str(source).strip()).netloc.lower().split("@")[-1].split(":")[0]
    host = host.removeprefix("www.")
    if not host:
        return ""
    for suffix, name in _PUBLISHERS.items():
        if host == suffix or host.endswith("." + suffix):
            return name
    return host


def _publishers(sources: list[str]) -> list[str]:
    names: list[str] = []
    for source in sources:
        name = _publisher(source)
        if name and name not in names:
            names.append(name)
    return names


def commons_credit(sources: list[str]) -> str:
    """`verified_by` for a seed commons nugget: the public record it rests on,
    named by its cited publishers — not whoever loaded the seed."""
    names = _publishers(sources)
    return f"public record: {', '.join(names)}" if names else "public record"


def commons_evidence(domain: str, sources: list[str]) -> dict[str, Any]:
    """The evidence a seed commons nugget carries at the `human` rung: the
    publishers credited for it, unsealed, with Nestor reconciliation to come."""
    return {
        "scheme": COMMONS_EVIDENCE_SCHEME,
        "basis": "commons",
        "credited_to": _publishers(sources),
        "domain": domain,
        "sealed": False,
    }


def verification_for_intake(
    *,
    domain: str,
    pair: dict[str, Any],
    data: dict[str, Any],
    sources: list[str],
) -> tuple[str, str, list[str]]:
    """Return (verification_kind, verified_by, extra_tags)."""
    bucket = classification_for_pair(
        domain=domain,
        pair=pair,
        data=data,
        sources=sources,
    )
    tags: list[str] = []
    if bucket == "commons":
        tags.append("commons")
        return "machine", COMMONS_VERIFIED_BY, tags
    tags.append("novel")
    return "asserted", INTAKE_VERIFIED_BY, tags


def seed_nugget_id(domain: str, question: str) -> str:
    digest = hashlib.sha256(f"jeles-seed\0{domain}\0{question}".encode()).hexdigest()
    return f"s{digest[:10]}"


def intake_nugget_id(domain: str, question: str) -> str:
    digest = hashlib.sha256(f"jeles-intake\0{domain}\0{question}".encode()).hexdigest()
    return f"i{digest[:10]}"


def promote_commons_in_store(
    *,
    dry_run: bool = False,
    commons_domains: set[str] | None = None,
    commons_ids: set[str] | None = None,
) -> dict[str, int]:
    """Upgrade asserted or machine nuggets in commons domains to the `human`
    rung when sourced, credited to the public record — and re-credit commons
    still carrying a legacy scheme that named the developer instead.

    A domain is commons by its ``core-`` prefix or by a file-level
    ``"classification": "commons"`` in the bundled seed; a single nugget is
    commons when its seed pair is classified ``"commons"``. The nugget keeps
    neither flag, only its domain (as its first tag) and its seed id, so both
    are read from the seed itself unless ``commons_domains`` / ``commons_ids``
    are given.
    """
    from jeles import corpus

    if commons_domains is None:
        from jeles.seed_loader import seed_commons_domains

        commons_domains = seed_commons_domains()
    if commons_ids is None:
        from jeles.seed_loader import seed_commons_nugget_ids

        commons_ids = seed_commons_nugget_ids()
    counts = {"promoted": 0, "skipped": 0, "errors": 0}
    for nugget in corpus.list_nuggets(limit=20000):
        kind = nugget.get("verification_kind") or "human"
        scheme = (nugget.get("evidence") or {}).get("scheme")
        legacy = scheme in LEGACY_COMMONS_SCHEMES
        # A commons nugget already at `human` but loaded before it was given a
        # serving tier: re-tier it in place.
        unserved = (
            scheme == COMMONS_EVIDENCE_SCHEME and nugget.get("visibility") != SERVE_VISIBILITY
        )
        if kind not in ("asserted", "machine") and not legacy and not unserved:
            counts["skipped"] += 1
            continue
        tags = list(nugget.get("tags") or [])
        domain = tags[0] if tags else ""
        if (
            not is_commons_domain(domain)
            and domain not in commons_domains
            and nugget.get("_id") not in commons_ids
        ):
            counts["skipped"] += 1
            continue
        sources = [str(s) for s in (nugget.get("sources") or [])]
        if not has_citable_source(sources):
            counts["skipped"] += 1
            continue
        question = (nugget.get("question") or "").strip()
        answer = (nugget.get("answer") or "").strip()
        if not question or not answer:
            counts["skipped"] += 1
            continue
        if dry_run:
            counts["promoted"] += 1
            continue
        if "commons" not in tags:
            tags.append("commons")
        result = corpus.put_nugget(
            question=question,
            answer=answer,
            sources=sources,
            verified_by=commons_credit(sources),
            tags=tags,
            nugget_id=nugget.get("_id", ""),
            verification_kind="human",
            visibility=SERVE_VISIBILITY,
            written_by=nugget.get("written_by") or "jeles-seed",
            evidence={
                **dict(nugget.get("evidence") or {}),
                **commons_evidence(domain, sources),
                "commons_promote": {"method": "promote_commons_in_store"},
            },
        )
        if result.get("error"):
            counts["errors"] += 1
        else:
            counts["promoted"] += 1
    return counts
