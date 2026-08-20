"""Unit tests for small private helpers in sphinx_mounts.mounter."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sphinx_mounts.config import MountConfig
from sphinx_mounts.mounter import _files_bundle_root, _is_within, _join_mount


class TestJoinMount:
    def test_with_prefix(self) -> None:
        assert _join_mount("_generated/api", "intro") == "_generated/api/intro"

    def test_with_nested_prefix(self) -> None:
        assert _join_mount("a/b/c", "sub/page") == "a/b/c/sub/page"

    def test_with_none_prefix_returns_tail(self) -> None:
        assert _join_mount(None, "tutorial") == "tutorial"

    def test_with_none_prefix_and_nested_tail(self) -> None:
        assert _join_mount(None, "guides/intro") == "guides/intro"


class TestIsWithin:
    """``_is_within`` backs the whole ``path_check`` feature, so it is tested
    directly rather than only through a build."""

    def test_direct_child_is_within(self) -> None:
        assert _is_within(Path("/bundle"), Path("/bundle/page.rst"))

    def test_nested_descendant_is_within(self) -> None:
        assert _is_within(Path("/bundle"), Path("/bundle/a/b/c.txt"))

    def test_the_root_itself_is_within(self) -> None:
        # A dependency recorded as the bundle root itself must not be an
        # escape; the previous implementation special-cased this and the
        # replacement has to keep it.
        assert _is_within(Path("/bundle"), Path("/bundle"))

    def test_sibling_is_not_within(self) -> None:
        assert not _is_within(Path("/bundle"), Path("/other/page.rst"))

    def test_parent_is_not_within(self) -> None:
        assert not _is_within(Path("/bundle"), Path("/page.rst"))

    def test_name_prefix_is_not_within(self) -> None:
        # A pure string ``startswith`` would wrongly accept this: the
        # comparison has to be per path component.
        assert not _is_within(Path("/bundle"), Path("/bundle-extra/page.rst"))

    def test_case_fold_is_applied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The containment comparison must go through ``os.path.normcase``.

        On a case-insensitive but case-preserving filesystem (APFS/HFS+,
        Windows) a bundle configured as ``/x/Bundle`` whose real directory is
        ``bundle`` produces two paths that differ only in case, and
        ``Path.resolve()`` does not fold case. Rejecting that as an escape
        would be a false positive on every macOS and Windows run — the
        platforms CI covers but no test exercised.

        ``normcase`` is the identity function on POSIX, so this monkeypatches
        it to a case-folding stand-in. Without that the assertion is
        untestable on Linux, and a regression would only ever surface on
        another platform.
        """
        monkeypatch.setattr(os.path, "normcase", str.lower)
        assert _is_within(Path("/x/Bundle"), Path("/x/bundle/page.rst"))
        assert _is_within(Path("/x/bundle"), Path("/x/Bundle/SUB/page.rst"))
        # The fold must not make unrelated paths match.
        assert not _is_within(Path("/x/Bundle"), Path("/x/other/page.rst"))

    def test_case_difference_without_a_fold_is_an_escape(self) -> None:
        """On a case-sensitive filesystem (the Linux default) two paths that
        differ in case really are different directories, so the honest answer
        is "not within" — the fold must come from ``normcase``, not from an
        unconditional lowercase."""
        if os.path.normcase("A") != "A":  # pragma: no cover - non-POSIX runner
            pytest.skip("filesystem paths are case-folded on this platform")
        assert not _is_within(Path("/x/Bundle"), Path("/x/bundle/page.rst"))


class TestFilesBundleRoot:
    """The single confinement root of a file-list mount."""

    @staticmethod
    def _mount(*files: str) -> MountConfig:
        return MountConfig(files=tuple(Path(f) for f in files), mount_at="_g/m")

    def test_single_file_root_is_its_parent(self) -> None:
        files = [Path("/rn/index.rst")]
        assert _files_bundle_root(files, self._mount("/rn/index.rst"), 0) == Path("/rn")

    def test_common_ancestor_of_files_at_different_depths(self) -> None:
        files = [Path("/rn/index.rst"), Path("/rn/notes/2026-q1.rst")]
        mount = self._mount("/rn/index.rst", "/rn/notes/2026-q1.rst")
        assert _files_bundle_root(files, mount, 0) == Path("/rn")

    def test_common_ancestor_of_sibling_directories(self) -> None:
        files = [Path("/pkg/a/one.rst"), Path("/pkg/b/two.rst")]
        mount = self._mount("/pkg/a/one.rst", "/pkg/b/two.rst")
        assert _files_bundle_root(files, mount, 0) == Path("/pkg")

    def test_identical_parents_collapse_to_that_parent(self) -> None:
        files = [Path("/pkg/one.rst"), Path("/pkg/two.rst")]
        mount = self._mount("/pkg/one.rst", "/pkg/two.rst")
        assert _files_bundle_root(files, mount, 0) == Path("/pkg")

    def test_no_common_ancestor_returns_none(self) -> None:
        """Files that share no filesystem root (different Windows drives, or a
        UNC path beside a drive letter) have no meaningful single root.
        ``os.path.commonpath`` raises ``ValueError``; the helper must report it
        and hand back ``None`` so the caller can fall back to per-file parents
        rather than crashing the build.

        A relative path beside an absolute one triggers the same
        ``ValueError`` on every platform, which is what makes this testable on
        POSIX at all.
        """
        files = [Path("/abs/one.rst"), Path("rel/two.rst")]
        mount = self._mount("/abs/one.rst", "rel/two.rst")
        assert _files_bundle_root(files, mount, 0) is None
