"""One authored dialect, three engines — the translation tables.

A rule's ``files`` patterns are written once and have to mean the same thing to
globset (the authored dialect), to Sphinx's ``exclude_patterns`` matcher, and
to the Rust ``ignore`` crate that walks a mount. This module pins the two
translations row by row, and then runs all three engines over one fixture tree
and requires them to agree — the property the translations exist to provide,
asserted rather than described.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sphinx.util.matching import get_matching_files

from sphinx_mounts.dialect import matches, refuse, to_exclude_patterns, to_gitignore
from sphinx_mounts.mounter import _build_walker

# ---------------------------------------------------------------------------
# The fence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("docs/{a,b}/**", "alternation"),
        ("docs/{a/**", "alternation"),
        ("{a,b}.rst", "alternation"),
        ("../bundle/**", "climb"),
        ("docs/../../bundle/**", "climb"),
        ("..\\bundle\\**", "climb"),
        ("/abs/path.rst", "absolute"),
        ("\\abs\\path.rst", "absolute"),
        ("C:/abs/path.rst", "absolute"),
        ("dir/a?c.rst", "?"),
        ("a?c/x.rst", "?"),
        # Accepted spellings, for the negative half of the fence.
        ("reference/pro/**/*.rst", None),
        ("internal.rst", None),
        ("a?c.rst", None),
        ("**", None),
        ("docs/[ab]/*.rst", None),
        ("docs/./a.rst", None),
        ("docs/a..b.rst", None),
    ],
    ids=lambda value: str(value),
)
def test_the_glob_dialect_fence(pattern: str, expected: str | None) -> None:
    """Four refusals, one validator, so loosening any of them is visible here.

    ``{}`` and ``..`` mirror ubCode's own fence (``refuse_glob_dialect``); the
    absolute-path and ``?``-with-separator rows are this reader's additions.
    ``?`` is the one form with no faithful gitignore spelling: globset's ``?``
    may cross a path separator and gitignore's never does.
    """
    reason = refuse(pattern)
    if expected is None:
        assert reason is None, f"{pattern!r} should be accepted, got {reason}"
        return
    assert reason is not None, f"{pattern!r} should be refused"
    assert expected in reason


def test_every_refusal_says_what_to_write_instead() -> None:
    """A refusal that only says "no" makes the whole build unfixable."""
    remedies = ("write", "drop", "gate")
    for pattern in ("a/{x,y}.rst", "../x.rst", "/x.rst", "a/b?.rst"):
        reason = refuse(pattern)
        assert reason is not None
        assert any(remedy in reason for remedy in remedies), reason


# ---------------------------------------------------------------------------
# globset -> gitignore (the mount arm)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("name.rst", "name.rst"),
        ("*.rst", "*.rst"),
        ("a?c.rst", "a?c.rst"),
        ("a[bX]c.rst", "a[bX]c.rst"),
        ("dir/name.rst", "dir/name.rst"),
        ("dir/**", "dir/**"),
        ("dir/**/*.rst", "dir/**/*.rst"),
        ("dir/*.rst", "dir/**/*.rst"),
        ("dir/*", "dir/**"),
        ("*/x.rst", "**/*/x.rst"),
        ("a/*/b/*.rst", "a/**/*/b/**/*.rst"),
    ],
    ids=lambda value: value,
)
def test_the_gitignore_translation_table(pattern: str, expected: str) -> None:
    """Every row of the measured table, including the identities.

    The identities matter as much as the translations: leaving a separator-less
    pattern alone is what makes both engines match it by basename at any depth,
    and "translating" it would silently narrow a rule to the project root.
    """
    assert to_gitignore(pattern) == expected


# ---------------------------------------------------------------------------
# globset -> Sphinx exclude_patterns (the host arm)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("internal.rst", ["internal.rst", "**/internal.rst"]),
        ("*.rst", ["*.rst", "**/*.rst"]),
        ("a[bX]c.rst", ["a[bX]c.rst", "**/a[bX]c.rst"]),
        ("dir/name.rst", ["dir/name.rst"]),
        ("dir/*.rst", ["dir/**.rst"]),
        ("dir/*", ["dir/**"]),
        ("dir/**", ["dir/**"]),
        ("dir/**/*.rst", ["dir/**/**.rst", "dir/**.rst"]),
        ("**/pro/**", ["**/pro/**", "pro/**"]),
    ],
    ids=lambda value: str(value),
)
def test_the_exclude_patterns_translation_table(
    pattern: str, expected: list[str]
) -> None:
    """Two divergences, two reasons for a translation to emit several patterns.

    A separator-less pattern needs both ``x`` and ``**/x``, because Sphinx's
    ``**/x`` is ``.*/x$`` and cannot match ``x`` at the root
    (``sphinx/util/matching.py``: ``_translate_pattern``, and
    ``Project.discover`` reaches it through ``compile_matchers``, which — unlike
    ``Matcher`` — does not expand the ``**/`` form). A leading or interior
    ``**`` needs a present and an absent form, because globset's matches zero
    directories and Sphinx's is a plain ``.*`` with the surrounding ``/`` still
    required. A single ``*`` becomes ``**`` because globset's crosses ``/``.
    """
    assert to_exclude_patterns(pattern) == expected


# ---------------------------------------------------------------------------
# The property the tables exist for: all three engines agree
# ---------------------------------------------------------------------------

TREE = (
    "internal.rst",
    "abc.rst",
    "aXc.rst",
    "index.rst",
    "a/internal.rst",
    "a/b/internal.rst",
    "docs/index.rst",
    "docs/guide/g.rst",
    "reference/pro/one.rst",
    "reference/pro/sub/two.rst",
    "reference/pro/sub/three.rst",
    "reference/basic/four.rst",
)

PARITY_PATTERNS = (
    "internal.rst",
    "*.rst",
    "a[bX]c.rst",
    "a?c.rst",
    "docs/index.rst",
    "docs/**",
    "docs/**/*.rst",
    "docs/*.rst",
    "docs/*",
    "**/pro/**",
    "reference/pro/**",
    "reference/*/two.rst",
    "**",
)


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A small tree, materialised once per test."""
    for relative in TREE:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x\n", encoding="utf-8")
    return tmp_path


def _authored_removals(pattern: str) -> set[str]:
    """What the AUTHORED globset pattern selects — the reference reading."""
    return {relative for relative in TREE if matches(pattern, relative)}


def _gitignore_removals(tree: Path, pattern: str) -> set[str]:
    """What the real ``ignore``-crate walker removes with the translated pattern.

    Configured exactly as a mount's walk is, so this measures the engine the
    mount arm actually feeds rather than a model of it.
    """
    walker = _build_walker(
        tree, include=(), exclude=(to_gitignore(pattern),), gitignore=False
    )
    kept = {
        entry.path().relative_to(tree).as_posix()
        for entry in walker
        if entry.path().is_file()
    }
    return set(TREE) - kept


def _sphinx_removals(tree: Path, pattern: str) -> set[str]:
    """What Sphinx's own discovery drops with the translated patterns."""
    kept = set(get_matching_files(tree, ("**",), to_exclude_patterns(pattern)))
    return set(TREE) - kept


@pytest.mark.parametrize("pattern", PARITY_PATTERNS, ids=lambda value: value)
def test_all_three_engines_remove_the_same_files(tree: Path, pattern: str) -> None:
    """The whole point of the translations, measured end to end.

    A rule glob that removed a different set of files on the host side than on
    the mount side would be the "one rule string, two document sets" hazard the
    narrowed grammar exists to prevent, reintroduced one dialect lower down.
    """
    authored = _authored_removals(pattern)
    assert _gitignore_removals(tree, pattern) == authored, (
        f"gitignore arm diverged for {pattern!r} "
        f"(translated to {to_gitignore(pattern)!r})"
    )
    assert _sphinx_removals(tree, pattern) == authored, (
        f"exclude_patterns arm diverged for {pattern!r} "
        f"(translated to {to_exclude_patterns(pattern)!r})"
    )


def test_a_separator_less_pattern_really_does_reach_every_depth() -> None:
    """The documented footgun, stated as a test so it cannot be "fixed" quietly."""
    assert _authored_removals("internal.rst") == {
        "internal.rst",
        "a/internal.rst",
        "a/b/internal.rst",
    }


def test_a_separator_carrying_pattern_is_root_anchored() -> None:
    """The opposite of the basename intuition, and the reason it is documented."""
    assert _authored_removals("pro/**") == set()
    assert _authored_removals("reference/pro/**") == {
        "reference/pro/one.rst",
        "reference/pro/sub/two.rst",
        "reference/pro/sub/three.rst",
    }
