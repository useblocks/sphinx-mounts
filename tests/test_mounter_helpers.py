"""Unit tests for small private helpers in sphinx_mounts.mounter."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sphinx.project import Project

from sphinx_mounts.config import MountConfig
from sphinx_mounts.mounter import (
    _files_bundle_root,
    _is_within,
    _join_mount,
    install_mount_aware_project,
)


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


class TestInstallMountAwareProject:
    """The swap-in copy-constructor over a class this extension does not own."""

    @staticmethod
    def _stock(tmp_path: Path) -> Project:
        project = Project(tmp_path, (".rst",))
        project.docnames.add("index")
        project._docname_to_path["index"] = Path("index.rst")
        project._path_to_docname[Path("index.rst")] = "index"
        return project

    def test_known_state_travels(self, tmp_path: Path) -> None:
        stock = self._stock(tmp_path)
        new = install_mount_aware_project(stock, ())
        assert new.docnames == {"index"}
        assert new._docname_to_path == {"index": Path("index.rst")}
        assert new._path_to_docname == {Path("index.rst"): "index"}
        assert new.source_suffix == (".rst",)

    def test_unknown_attributes_travel_too(self, tmp_path: Path) -> None:
        """A field a future Sphinx adds to ``Project`` must not be dropped.

        This is a hand-rolled copy-constructor over an upstream class, so
        enumerating fields by name means a new one disappears silently — the
        worst failure mode available, because the resulting project looks
        complete and is simply missing something. Copying wholesale makes
        unknown state travel by default.
        """
        stock = self._stock(tmp_path)
        stock.a_field_from_a_future_sphinx = "carry me"  # type: ignore[attr-defined]
        new = install_mount_aware_project(stock, ())
        assert new.a_field_from_a_future_sphinx == "carry me"

    def test_docname_containers_are_not_shared_with_the_old_project(
        self, tmp_path: Path
    ) -> None:
        """The copy must not alias the old project's mutable containers.

        ``discover()`` clears and repopulates all three on the new project;
        aliasing would reach back into the object being replaced.
        """
        stock = self._stock(tmp_path)
        new = install_mount_aware_project(stock, ())
        new.docnames.add("extra")
        new._docname_to_path["extra"] = Path("extra.rst")
        new._path_to_docname[Path("extra.rst")] = "extra"
        assert stock.docnames == {"index"}
        assert "extra" not in stock._docname_to_path
        assert Path("extra.rst") not in stock._path_to_docname

    def test_mount_state_is_not_taken_from_the_old_project(
        self, tmp_path: Path
    ) -> None:
        """Fields this subclass owns come from the constructor, never from the
        project being replaced — even if that project happens to carry
        same-named attributes (a second ``builder-inited``, say)."""
        stock = self._stock(tmp_path)
        stock._mounts = ("stale",)  # type: ignore[attr-defined]
        stock._doc_roots = {"stale": "stale"}  # type: ignore[attr-defined]
        stock._mount_entry_docnames = {0: ["stale"]}  # type: ignore[attr-defined]

        mount = MountConfig(dir=tmp_path, mount_at="_g/m")
        new = install_mount_aware_project(stock, (mount,))

        assert new._mounts == (mount,)
        assert new._doc_roots == {}
        assert new._mount_entry_docnames == {}
