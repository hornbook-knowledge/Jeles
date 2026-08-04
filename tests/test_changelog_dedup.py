"""`tools/changelog_dedup.py` must reproduce the correction 0.5.0 needed by hand.

**Ported from willow-mcp, but the cases are this repo's own.** The tool is
byte-identical there; these tests are not, and deliberately so — a ported test
asserting another project's commit hashes proves the file was copied and nothing
else. Every hash below is from this repository's history.

The failure, from merging with merge commits rather than squashing (GitHub puts
the PR title in the merge commit body, where release-please reads it):

    0.5.0  the same change twice — `bbc8258` (the merge of #27) and `455be56`
           (the commit it merged). Corrected by hand in #29.

willow-mcp saw the same mechanism do worse: release-please collapses entries
sharing a scope, so a merge commit there displaced a real one and a shipped fix
went undocumented. That has not happened here yet, which is the point of adding
the guard now rather than after.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "tools"))

changelog_dedup = pytest.importorskip("changelog_dedup")

_BASE = "https://github.com/rudi193-cmd/Jeles"
_DESC = "**sources:** declare the hosts each source contacts"
_MERGE = "bbc8258e9620c1e39630f47357fbd82379ea3479"   # merge of #27
_REAL = "455be56673f62c42d097ca3bcf5819c64268bfe9"    # the commit it merged


def _bullet(sha: str) -> str:
    """release-please's bullet format. Built rather than pasted — jeles lints at
    100 columns and a real entry is longer than that."""
    return f"* {_DESC} ([{sha[:7]}]({_BASE}/commit/{sha}))"


def _section(*shas: str) -> str:
    """A 0.5.0 section containing exactly these entries, followed by 0.4.1's
    header so `rebuild` has a boundary to stop at."""
    return "\n".join([
        f"## [0.5.0]({_BASE}/compare/v0.4.1...v0.5.0) (2026-08-04)",
        "", "", "### Added", "",
        *[_bullet(s) for s in shas],
        "",
        f"## [0.4.1]({_BASE}/compare/v0.4.0...v0.4.1) (2026-08-03)",
        "",
    ])


def _has(*revs: str) -> bool:
    """Are these objects present? CI may use a shallow clone."""
    return all(
        subprocess.run(["git", "-C", str(_REPO), "rev-parse", "--verify", f"{r}^{{commit}}"],
                       capture_output=True).returncode == 0
        for r in revs
    )


needs_history = pytest.mark.skipif(
    not _has("v0.4.1", "455be56"),
    reason="needs full history and tags (shallow clone)",
)


@needs_history
def test_it_drops_the_duplicate_release_please_emitted_for_0_5_0():
    """The exact text release-please produced, and the single entry it should
    have been. `455be56` is the real commit; `bbc8258` is the merge that carried
    its title."""
    broken = _section(_MERGE, _REAL)

    fixed, summary = changelog_dedup.rebuild(broken)
    section = fixed.split("## [0.4.1]")[0]
    bullets = [ln for ln in section.splitlines() if ln.startswith("* ")]

    assert len(bullets) == 1, bullets
    assert "455be56" in bullets[0], "kept the wrong one — 455be56 is the real commit"
    assert "bbc8258" not in section, "the merge commit survived"
    assert summary


@needs_history
def test_the_hidden_types_in_that_range_stay_out():
    """v0.4.1..v0.5.0 also contains `ci:` and `test:` commits. They are hidden in
    release-please-config.json and must not be resurrected by a rebuild that
    reads git directly — the tool takes its type set from the config, not from
    what happens to be in the range."""
    broken = _section(_REAL)

    fixed, summary = changelog_dedup.rebuild(broken)
    assert summary == "", f"already correct, but the tool wanted to change it: {summary}"
    assert "stop a PR title from cutting a release" not in fixed, "a ci: commit leaked in"
    assert "make the release chain check itself" not in fixed, "a test: commit leaked in"


def test_the_repo_changelog_is_already_correct():
    """Idempotence against the real file. A failure means either the changelog
    drifted or a release landed without the workflow step running."""
    text = (_REPO / "CHANGELOG.md").read_text()
    try:
        _, summary = changelog_dedup.rebuild(text)
    except changelog_dedup.Bail as exc:
        pytest.skip(f"cannot verify in this checkout: {exc}")
    assert summary == "", f"CHANGELOG.md disagrees with the commits: {summary}"


def test_it_refuses_a_section_it_cannot_regenerate():
    """A breaking change renders as '⚠ BREAKING CHANGES', which this tool does
    not model. Rewriting a release note it had misread is worse than the bug it
    fixes, so it stops.

    This matters more here than in willow-mcp: jeles is below 1.0 with
    `bump-minor-pre-major`, so a breaking change is an ordinary minor bump rather
    than a rare major one."""
    text = f"""## [0.6.0]({_BASE}/compare/v0.5.0...v0.6.0) (2026-08-04)


### ⚠ BREAKING CHANGES

* the thing changed


### Added

* **x:** y ([abc1234]({_BASE}/commit/abc1234))
"""
    with pytest.raises(changelog_dedup.Bail, match="BREAKING CHANGES"):
        changelog_dedup.rebuild(text)


def test_prose_about_breaking_changes_is_not_a_breaking_change():
    """The bug this inherited a fix for. `"BREAKING CHANGE" in body` flagged
    willow-mcp's own commit introducing the tool, because its message described
    breaking-change handling. Anchored to a real footer now."""
    R = changelog_dedup.BREAKING_FOOTER_RE
    assert not R.search('renders as "⚠ BREAKING CHANGES" and bails')
    assert not R.search("   BREAKING CHANGE: indented, inside a code block")
    assert R.search("body\n\nBREAKING CHANGE: the API moved")
    assert R.search("body\n\nBREAKING-CHANGE: gone")


def test_hidden_types_come_from_this_repo_s_config():
    """The port must follow jeles' config, not willow-mcp's. Same visible set
    today, but the tool reads it rather than restating it."""
    visible, order = changelog_dedup.sections_from_config()
    for hidden in ("docs", "test", "ci", "chore"):
        assert hidden not in visible, hidden
    assert visible["feat"] == "Added" and visible["fix"] == "Fixed"
    assert order.index("Added") < order.index("Fixed")


def test_print_section_emits_exactly_what_a_release_body_should_be():
    """`--print-section` feeds the GitHub Release body, which release-please
    generates from its own parse rather than from CHANGELOG.md — so correcting
    the file leaves the release *page* wrong. This repo's live v0.5.0 page still
    carried the `bbc8258` duplicate after #29 fixed the file.

    The shape matters: release-please's body starts with the `## [x.y.z](…)`
    header, so the extracted section must include it."""
    text = (_REPO / "CHANGELOG.md").read_text()
    section = changelog_dedup.section_for(text, "0.5.0")
    assert section is not None
    assert section.splitlines()[0].startswith("## [0.5.0]("), section.splitlines()[0]
    assert "### Added" in section
    assert "455be56" in section
    assert "bbc8258" not in section, "the merge commit is back in the changelog"
    assert "## [0.4.1]" not in section, "swallowed the next release"
    assert not section.endswith("\n"), "trailing whitespace stripped for comparison"


def test_print_section_is_none_for_an_unknown_version():
    """The workflow warns and leaves the release alone rather than blanking it."""
    text = (_REPO / "CHANGELOG.md").read_text()
    assert changelog_dedup.section_for(text, "99.99.99") is None
