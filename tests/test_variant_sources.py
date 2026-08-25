"""End-to-end coverage for ``[[source.variant_sources]]``.

The reader's whole job is to make ``sphinx-build`` produce the document set the
project's ``ubproject.toml`` describes for the current variant — the same set
ubCode produces from the same file. So these tests build real projects and look
at what came out, rather than at what the reader computed.

Four things are load-bearing enough to have their own sections below:

* the **fold into config values**, which is what makes a gating flip converge
  on the build where it happened, in both directions, with no invalidation
  story of its own;
* the **warning downgrade**, without which ``sphinx-build -W`` fails a build
  that has nothing wrong with it;
* the **hard refusals**, every one of which exists because report-and-drop
  fails open;
* the **variant-data read rule**, which has to give the same answer whether
  sphinx-needs is absent, present-but-not-yet-resolving, or present and
  already resolved.
"""

from __future__ import annotations

from io import StringIO
import json
from pathlib import Path
import shutil
import textwrap
from typing import Any

import pytest
from sphinx.application import Sphinx

from sphinx_mounts import warnings as mount_warnings

FILLER_COUNT = 9
"""Enough extra host pages that a parallel read genuinely engages.

``sphinx-build -j`` chunks the document list, and the ``convert_serializable``
hazard the filter's attachment point exists to avoid is invisible in a build
small enough to stay in one chunk.
"""


@pytest.fixture(autouse=True)
def _detach_filters():
    """Keep the process-global logger filters from leaking between tests.

    The emitting loggers are module-level objects shared by every ``Sphinx``
    application in the process, so a test that installs a filter and never
    builds again would change what the next test sees.
    """
    yield
    mount_warnings.remove_downgrade_filters()


# ---------------------------------------------------------------------------
# Project construction
# ---------------------------------------------------------------------------


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")


def make_project(
    root: Path,
    *,
    toml: str,
    conf_extra: str = "",
    dangling: bool = False,
    srcdir_name: str | None = None,
) -> tuple[Path, Path]:
    """Materialise a host project plus an external bundle.

    :param root: A directory to build inside.
    :param toml: The whole ``ubproject.toml`` body, with ``{bundle}``
        substituted for the bundle's absolute path.
    :param conf_extra: Extra lines appended to ``conf.py``.
    :param dangling: Add a toctree entry naming a document that never exists
        and that no rule mentions — the negative control.
    :param srcdir_name: Put the Sphinx sources in this sub-directory instead of
        beside ``conf.py``, for the layout guard.
    :return: ``(confdir, bundle)``.
    """
    confdir = root / "proj"
    srcdir = confdir if srcdir_name is None else confdir / srcdir_name
    bundle = root / "bundle"

    _write(
        bundle / "index.rst",
        """
        Bundle
        ======

        .. toctree::

           binternal
    """,
    )
    _write(
        bundle / "binternal.rst",
        """
        Bundle internal
        ---------------

        BUNDLE_INTERNAL_MARKER
    """,
    )

    entries = ["hostkeep", "hostgated", "mnt/index", "mnt/binternal"]
    entries += [f"filler{index:02d}" for index in range(FILLER_COUNT)]
    if dangling:
        entries.append("nosuchdoc")
    listed = "\n           ".join(entries)
    _write(
        srcdir / "index.rst",
        f"""
        Host
        ====

        .. toctree::

           {listed}

        .. toctree::
           :glob:

           gated/*
    """,
    )
    for name in ("hostkeep", "hostgated"):
        _write(
            srcdir / f"{name}.rst",
            f"""
            {name.title()}
            {"=" * len(name)}

            {name.upper()}_MARKER
        """,
        )
    for index in range(FILLER_COUNT):
        _write(
            srcdir / f"filler{index:02d}.rst",
            f"""
            Filler {index}
            ============

            Padding so a parallel read chunks.
        """,
        )
    for name in ("a", "b"):
        _write(
            srcdir / "gated" / f"{name}.rst",
            f"""
            Gated {name}
            =========

            GATED_{name.upper()}_MARKER
        """,
        )

    _write(
        confdir / "conf.py",
        f"""
        project = "host"
        author = "tests"
        extensions = ["sphinx_mounts"]
        exclude_patterns: list[str] = []
        master_doc = "index"
        {conf_extra}
    """,
    )
    _write(confdir / "ubproject.toml", toml.replace("{bundle}", bundle.as_posix()))
    return confdir, bundle


_BASE_TOML = """
[[source.mounts]]
dir = "{bundle}"
mount_at = "mnt"

[[source.variant_sources]]
if = "var.edition == 'pro'"
files = ["hostgated.rst", "binternal.rst", "gated/**"]

[needs.variant_data]
edition = "EDITION"
"""


def base_toml(edition: str) -> str:
    """The standard three-arm rule set, for one variant.

    ``hostgated.rst`` and ``binternal.rst`` carry no path separator, so they
    gate by **file name** in every tree — host and mounted alike. ``gated/**``
    carries one, so it is root-anchored and reaches only the host tree.
    """
    return _BASE_TOML.replace("EDITION", edition)


def _build(
    make_app,
    confdir: Path,
    *,
    builddir: Path | None = None,
    freshenv: bool = True,
    **kwargs: Any,
):
    app = make_app(srcdir=confdir, builddir=builddir, freshenv=freshenv, **kwargs)
    app.build()
    return app


def _build_split(confdir: Path, srcdir: Path, builddir: Path):
    """Build with ``srcdir`` and ``confdir`` genuinely different.

    ``SphinxTestApp`` always sets ``confdir = srcdir``, so the layout guard —
    whose whole subject is the two directories disagreeing — has to go through
    ``Sphinx`` itself.
    """
    status, warning = StringIO(), StringIO()
    app = Sphinx(
        srcdir=str(srcdir),
        confdir=str(confdir),
        outdir=str(builddir / "html"),
        doctreedir=str(builddir / "doctrees"),
        buildername="html",
        status=status,
        warning=warning,
        freshenv=True,
    )
    app.build()
    return app


def _fails_under_dash_w(make_app, confdir: Path, builddir: Path) -> bool:
    """Whether ``sphinx-build -W`` would fail this project.

    Two supported Sphinx versions report it two ways: 7.4's
    ``WarningIsErrorFilter`` **raises** from the warning handler, while from 8.2
    plain ``-W`` only sets ``_fail_on_warnings`` and the build fails in the
    epilogue by setting a non-zero status code. Both count as a failure here.
    """
    try:
        app = _build(make_app, confdir, warningiserror=True, builddir=builddir)
    except Exception:
        return True
    return app.statuscode != 0


def _pages(app) -> set[str]:
    outdir = Path(app.outdir)
    return {
        path.relative_to(outdir).as_posix()
        for path in outdir.rglob("*.html")
        if "_static" not in path.parts
    }


# ---------------------------------------------------------------------------
# The fold: which documents exist
# ---------------------------------------------------------------------------


def test_a_false_rule_removes_host_and_mounted_files(make_app, tmp_path):
    """One rule, three arms: a host file, a mounted file, and a glob tree.

    ``binternal.rst`` has no path separator, so it gates by **file name** in
    every tree — host and mounted alike. That reach is the documented footgun,
    and it is what makes a single rule able to narrow a bundle without knowing
    where the bundle is mounted.
    """
    confdir, _ = make_project(tmp_path, toml=base_toml("basic"))
    app = _build(make_app, confdir)
    pages = _pages(app)
    assert "hostkeep.html" in pages
    assert "mnt/index.html" in pages
    assert "hostgated.html" not in pages
    assert "mnt/binternal.html" not in pages
    assert "gated/a.html" not in pages
    assert "gated/b.html" not in pages


def test_a_true_rule_changes_nothing(make_app, tmp_path):
    """Rules only ever narrow, and only when their condition is false."""
    confdir, _ = make_project(tmp_path, toml=base_toml("pro"))
    app = _build(make_app, confdir)
    pages = _pages(app)
    assert {"hostgated.html", "mnt/binternal.html", "gated/a.html"} <= pages


def test_the_verdict_is_folded_into_config_values(make_app, tmp_path):
    """The patterns land in ``exclude_patterns`` and in the mount's ``exclude``.

    Asserted directly, because it is the mechanism a gating flip converges
    through: both confvals are ``rebuild="env"``, so a changed value is a
    config change Sphinx already knows how to act on. A reader that gated
    without touching a config value leaves both byte-identical across a flip.
    """
    confdir, _ = make_project(tmp_path, toml=base_toml("basic"))
    app = _build(make_app, confdir)
    assert "hostgated.rst" in app.config.exclude_patterns
    assert "**/hostgated.rst" in app.config.exclude_patterns
    assert "binternal.rst" in app.config.mounts[0]["exclude"]


def test_a_gating_flip_converges_in_both_directions(make_app, tmp_path):
    """Three builds over one doctree cache: gated, un-gated, gated again.

    Both directions have to converge on the build where the flip happened.
    This is the test the fold exists for — and the one that goes red if the
    mount arm becomes a post-walk filter, because ``config.mounts`` would then
    be byte-identical across the flip and nothing would re-read.
    """
    confdir, _ = make_project(tmp_path, toml=base_toml("pro"))
    builddir = tmp_path / "build"

    first = _build(make_app, confdir, builddir=builddir)
    assert "mnt/binternal.html" in _pages(first)

    _flip(confdir, "pro", "basic")
    second = _build(make_app, confdir, builddir=builddir, freshenv=False)
    assert "mnt/binternal" not in second.env.found_docs
    assert "hostgated" not in second.env.found_docs

    _flip(confdir, "basic", "pro")
    third = _build(make_app, confdir, builddir=builddir, freshenv=False)
    assert "mnt/binternal" in third.env.found_docs
    assert "hostgated" in third.env.found_docs


def _flip(confdir: Path, before: str, after: str) -> None:
    toml = confdir / "ubproject.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8").replace(
            f'edition = "{before}"', f'edition = "{after}"'
        ),
        encoding="utf-8",
    )


MOUNT_ONLY_TOML = """
[[source.mounts]]
dir = "{bundle}"
mount_at = "mnt"

[[source.variant_sources]]
if = "var.edition == 'pro'"
files = ["binternal.rst"]

[needs.variant_data]
edition = "EDITION"
"""


def test_a_mount_only_flip_converges(make_app, tmp_path):
    """``config.mounts`` alone is enough to invalidate the environment.

    Isolated from the host arm on purpose: with no ``exclude_patterns`` entry
    changing, the only thing that differs across the flip is the mounts config
    value. If the mount arm stopped folding into that value — a post-walk
    filter, or a fold that mutates a copy and never reassigns — the value would
    be byte-identical across the flip, nothing would invalidate, and the second
    build would still hold the gated document.
    """
    confdir, _ = make_project(tmp_path, toml=MOUNT_ONLY_TOML.replace("EDITION", "pro"))
    builddir = tmp_path / "build"
    first = _build(make_app, confdir, builddir=builddir)
    assert "mnt/binternal" in first.env.found_docs

    _flip(confdir, "pro", "basic")
    second = _build(make_app, confdir, builddir=builddir, freshenv=False)
    assert "mnt/binternal" not in second.env.found_docs
    assert "mnt/index" in second.env.found_docs

    _flip(confdir, "basic", "pro")
    third = _build(make_app, confdir, builddir=builddir, freshenv=False)
    assert "mnt/binternal" in third.env.found_docs


def test_the_stale_output_caveat_is_real(make_app, tmp_path):
    """The gated page stays on disk after a flip, live and URL-reachable.

    Upstream behaviour — Sphinx does not delete output for removed documents —
    but it is the single most important operational consequence of this
    feature, so it is pinned here rather than only described in the docs. A
    per-variant CI publishing ``_build/html`` from a warm build directory ships
    the gated page.
    """
    confdir, _ = make_project(tmp_path, toml=base_toml("pro"))
    builddir = tmp_path / "build"
    _build(make_app, confdir, builddir=builddir)
    _flip(confdir, "pro", "basic")
    second = _build(make_app, confdir, builddir=builddir, freshenv=False)

    assert "hostgated" not in second.env.found_docs
    assert (Path(second.outdir) / "hostgated.html").exists(), (
        "Sphinx does not delete output for removed documents; build each "
        "variant into its own -d and output directory, or use -E with a clean "
        "outdir."
    )


@pytest.mark.parametrize(
    "pattern",
    ["binternal.rst", "bundle/binternal.rst", "bundle/**", "*/binternal.rst"],
    ids=["basename", "path", "tree", "wildcard-dir"],
)
def test_a_file_list_mount_is_not_gated_by_any_rule_spelling(
    make_app, tmp_path, pattern: str
):
    """Parity: neither reader gates a file-list mount, under any spelling.

    ubCode cannot gate one — a ``files`` mount's entries are pushed straight
    into its result with no include or exclude consulted, and a variant rule
    reaches its discovery only through ``extend_exclude``
    (``rust/ubc_config/src/resolved.rs``). This reader used to gate one by
    basename, which put a file in ubCode's build and not in Sphinx's from one
    rule string — a divergence in the removes-more-here direction, and exactly
    what this key must never do.

    So the arm is gone rather than completed, and this test is what keeps it
    gone. Every spelling is exercised because "not gated" has to hold for the
    path forms too, not only the basename one that used to fire.
    """
    toml = f"""
    [[source.mounts]]
    files = ["{{bundle}}/index.rst", "{{bundle}}/binternal.rst"]
    mount_at = "mnt"

    [[source.variant_sources]]
    if = "var.edition == 'pro'"
    files = ["{pattern}"]

    [needs.variant_data]
    edition = "basic"
    """
    confdir, _ = make_project(tmp_path, toml=toml)
    app = _build(make_app, confdir)
    pages = _pages(app)
    assert "mnt/index.html" in pages
    assert "mnt/binternal.html" in pages, (
        "a file-list mount must survive every rule spelling, because ubCode's "
        "cannot be gated at all"
    )


def test_a_directory_mount_beside_a_file_list_mount_is_still_gated(make_app, tmp_path):
    """The limitation is per mount MODE, not per project.

    Dropping the file-list arm must not quietly stop gating the directory
    mounts in the same project — which is what a coarser "skip mounts when any
    is a file list" fix would have done.
    """
    toml = """
    [[source.mounts]]
    files = ["{bundle}/index.rst"]
    mount_at = "flat"

    [[source.mounts]]
    dir = "{bundle}"
    mount_at = "mnt"

    [[source.variant_sources]]
    if = "var.edition == 'pro'"
    files = ["binternal.rst"]

    [needs.variant_data]
    edition = "basic"
    """
    confdir, _ = make_project(tmp_path, toml=toml)
    app = _build(make_app, confdir)
    pages = _pages(app)
    assert "flat/index.html" in pages
    assert "mnt/index.html" in pages
    assert "mnt/binternal.html" not in pages


def test_a_conf_py_mount_is_gated_too(make_app, tmp_path):
    """The legacy ``conf.py`` mount list gets the same fold.

    A variant rule must not mean one thing in TOML and another in ``conf.py``.
    """
    toml = """
    [[source.variant_sources]]
    if = "var.edition == 'pro'"
    files = ["binternal.rst"]

    [needs.variant_data]
    edition = "basic"
    """
    confdir, bundle = make_project(tmp_path, toml=toml)
    conf = confdir / "conf.py"
    conf.write_text(
        conf.read_text(encoding="utf-8")
        + f"\nmounts = [{{'dir': r'{bundle}', 'mount_at': 'mnt'}}]\n",
        encoding="utf-8",
    )
    app = _build(make_app, confdir)
    assert "mnt/index.html" in _pages(app)
    assert "mnt/binternal.html" not in _pages(app)


def test_a_conf_py_mountconfig_instance_is_gated_too(make_app, tmp_path):
    """The `conf.py` dataclass path, which no test used to reach.

    ``parse_mounts`` documents ``mounts`` as "a sequence of mappings **or**
    ``MountConfig`` instances", and the fold has a dedicated branch for the
    second shape that a plain dict never exercises. Both mount modes are
    asserted: a directory mount gated, a file-list mount NOT gated — the same
    parity the TOML path keeps.
    """
    toml = """
    [[source.variant_sources]]
    if = "var.edition == 'pro'"
    files = ["binternal.rst"]

    [needs.variant_data]
    edition = "basic"
    """
    confdir, bundle = make_project(tmp_path, toml=toml)
    conf = confdir / "conf.py"
    conf.write_text(
        conf.read_text(encoding="utf-8")
        + "\nfrom pathlib import Path\n"
        + "from sphinx_mounts.config import MountConfig\n"
        + f"mounts = [MountConfig(dir=Path(r'{bundle}'), mount_at='mnt'),\n"
        + f"          MountConfig(files=(Path(r'{bundle}/binternal.rst'),),"
        + " mount_at='flat')]\n",
        encoding="utf-8",
    )
    app = _build(make_app, confdir)
    pages = _pages(app)
    assert "mnt/index.html" in pages
    assert "mnt/binternal.html" not in pages, "the directory mount is gated"
    assert "flat/binternal.html" in pages, "the file-list mount is not"


# ---------------------------------------------------------------------------
# The downgrade
# ---------------------------------------------------------------------------


def test_a_gated_project_builds_clean_under_dash_w(make_app, tmp_path):
    """``-W`` on a correctly configured variant build exits 0.

    Three warnings would otherwise fire, one per arm: ``toc.excluded`` for the
    host file, ``toc.not_readable`` for the mounted one, and the type-less
    "glob matched nothing" for the ``:glob:`` tree. All three are attributable
    to a rule, so all three are reclassified rather than counted.
    """
    confdir, _ = make_project(tmp_path, toml=base_toml("basic"))
    app = _build(make_app, confdir, warningiserror=True)
    assert "WARNING" not in app._warning.getvalue()
    assert app.statuscode == 0


def test_a_gated_project_builds_clean_under_dash_w_parallel(make_app, tmp_path):
    """The same, under a parallel read.

    This is the cell a handler-level filter fails: the worker serialises its
    buffered records with ``convert_serializable``, which does ``r.args = ()``,
    so any attribution that reads ``record.args[0]`` in the parent silently
    stops matching. Attaching to the emitting child logger runs the filter in
    whatever process emits, before that call.
    """
    confdir, _ = make_project(tmp_path, toml=base_toml("basic"))
    app = _build(make_app, confdir, warningiserror=True, parallel=2)
    assert "WARNING" not in app._warning.getvalue()
    assert app.statuscode == 0


def test_a_gated_project_builds_clean_under_exception_on_warning(make_app, tmp_path):
    """``--exception-on-warning`` raises from a *handler* filter.

    A logger filter is upstream of every handler filter, so the record is
    already an INFO by the time ``_RaiseOnWarningFilter`` could look at it.
    """
    confdir, _ = make_project(tmp_path, toml=base_toml("basic"))
    app = _build(make_app, confdir, warningiserror=True, exception_on_warning=True)
    assert "WARNING" not in app._warning.getvalue()
    assert app.statuscode == 0


def test_the_downgraded_records_are_still_reported(make_app, tmp_path):
    """Downgraded, never dropped — asserted by PRESENCE, not by absence.

    The reference is the only place left where a rule that removed more than
    the author meant is still visible: the file itself is gone from search,
    ``objects.inv``, cross-references and the page tree. A filter returning
    ``False`` would make an over-broad rule completely silent.
    """
    confdir, _ = make_project(tmp_path, toml=base_toml("basic"))
    app = _build(make_app, confdir)
    status = app._status.getvalue()
    assert status.count(mount_warnings.VARIANT_EXCLUDED_CODE) >= 3
    assert "'hostgated'" in status
    assert "'mnt/binternal'" in status
    assert "'gated/*'" in status
    assert "var.edition == 'pro'" in status, "the rule that removed it is named"


def test_an_unattributed_missing_document_still_warns(make_app, tmp_path):
    """The negative control: a genuinely broken reference is untouched.

    A downgrade that fired on any missing document would be a way to hide
    typos, which is exactly what makes ``suppress_warnings`` the wrong tool
    here. ``nosuchdoc`` is in no rule's file set, so it stays a warning and
    still fails ``-W``.
    """
    confdir, _ = make_project(tmp_path, toml=base_toml("basic"), dangling=True)
    app = _build(make_app, confdir)
    warning = app._warning.getvalue()
    assert "nosuchdoc" in warning
    assert "WARNING" in warning

    assert _fails_under_dash_w(make_app, confdir, tmp_path / "b2")


def test_the_filter_loggers_resolve_from_sphinx_itself(make_app, tmp_path):
    """The seam is derived from Sphinx's own modules, not hard-coded.

    The names are a function of Sphinx's module layout, so a module move
    upstream would un-hook the filter in silence. Resolving them from the
    modules' own logger objects makes such a move a loud fallback instead —
    and this test is what notices if the fallback is ever the *only* path.
    """
    names, degraded = mount_warnings.resolve_toctree_logger_names()
    assert degraded == (), f"fell back to hard-coded names: {degraded}"
    assert names == mount_warnings.FALLBACK_LOGGER_NAMES


# ---------------------------------------------------------------------------
# The hard refusals
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "match"),
    [
        ("docs/{a,b}/**", "alternation"),
        ("../outside/**", "climb"),
        ("/abs.rst", "absolute"),
        ("a?c/x.rst", r"`\?`"),
    ],
    ids=["braces", "climb", "absolute", "question-mark"],
)
def test_a_refused_glob_refuses_the_configuration(
    make_app, tmp_path, pattern: str, match: str
):
    """Not a warning that skips the rule — the whole configuration is refused.

    Skipping the rule would leave every file it names in the build, including
    the files its *other*, perfectly valid patterns name, behind a diagnostic
    the project could suppress. For a key whose only purpose is keeping content
    out of a build, failing open is the one outcome that must not be possible.
    """
    toml = f"""
    [[source.variant_sources]]
    if = "var.edition == 'pro'"
    files = ["hostgated.rst", "{pattern}"]

    [needs.variant_data]
    edition = "pro"
    """
    confdir, _ = make_project(tmp_path, toml=toml)
    with pytest.raises(Exception, match=match):
        _build(make_app, confdir)


def test_every_refused_glob_is_listed_at_once(make_app, tmp_path):
    """Fixing one refusal only to meet the next on the following build is the
    experience this avoids, and it is cheap to avoid: the check is a pure
    function of the pattern text."""
    toml = """
    [[source.variant_sources]]
    if = "var.edition == 'pro'"
    files = ["{a,b}.rst", "../up.rst", "/abs.rst"]

    [needs.variant_data]
    edition = "pro"
    """
    confdir, _ = make_project(tmp_path, toml=toml)
    with pytest.raises(Exception) as excinfo:
        _build(make_app, confdir)
    message = str(excinfo.value)
    assert "3 `variant_sources` glob(s)" in message
    assert "{a,b}.rst" in message
    assert "../up.rst" in message
    assert "/abs.rst" in message


def test_an_out_of_grammar_condition_refuses_the_configuration(make_app, tmp_path):
    """A condition outside the grammar is statically knowable, so it is a
    configuration error rather than something to evaluate."""
    toml = """
    [[source.variant_sources]]
    if = "var.debug"
    files = ["hostgated.rst"]

    [needs.variant_data]
    debug = false
    """
    confdir, _ = make_project(tmp_path, toml=toml)
    with pytest.raises(Exception, match="outside the rule grammar"):
        _build(make_app, confdir)


def test_a_rule_that_would_remove_the_root_document_is_refused(make_app, tmp_path):
    """Sphinx's own abort blames the source directory for an exclusion.

    *"Sphinx is unable to load the master document … The master document must
    be within the source directory or a subdirectory of it"* is actively
    misleading for this cause: the document is inside the source directory,
    and excluded. That message must never be reachable through a variant rule.

    Variant-*dependent*, unlike the glob refusal: the same rule with a true
    condition is a perfectly legal "this whole tree, this variant only".
    """
    toml = """
    [[source.variant_sources]]
    if = "var.edition == 'pro'"
    files = ["index.rst"]

    [needs.variant_data]
    edition = "basic"
    """
    confdir, _ = make_project(tmp_path, toml=toml)
    with pytest.raises(Exception) as excinfo:
        _build(make_app, confdir)
    message = str(excinfo.value)
    assert "root document" in message
    assert "unable to load the master document" not in message


def test_the_same_root_document_rule_is_fine_while_its_condition_holds(
    make_app, tmp_path
):
    """The variant-dependence of the root-doc guard, from the other side."""
    toml = """
    [[source.variant_sources]]
    if = "var.edition == 'pro'"
    files = ["index.rst"]

    [needs.variant_data]
    edition = "pro"
    """
    confdir, _ = make_project(tmp_path, toml=toml)
    app = _build(make_app, confdir)
    assert "index.html" in _pages(app)


def test_a_non_identity_layout_is_refused(tmp_path):
    """A rule glob and an ``exclude_patterns`` entry must share a base.

    When they do not, a prefix-shifted rewrite is mechanically possible for a
    path-naming pattern and has no correct form at all for a basename-matching
    one — and gating only the root that happens to coincide is the failure the
    whole feature exists to prevent. The message names both directories and the
    one-line fix.
    """
    toml = """
    [[source.variant_sources]]
    if = "var.edition == 'pro'"
    files = ["hostgated.rst"]

    [needs.variant_data]
    edition = "basic"
    """
    confdir, _ = make_project(tmp_path, toml=toml, srcdir_name="source")
    with pytest.raises(Exception) as excinfo:
        _build_split(confdir, confdir / "source", tmp_path / "build")
    message = str(excinfo.value)
    assert "source directory" in message
    assert "[source] dir = ['source']" in message


def test_a_declared_source_dir_makes_a_split_layout_identity(tmp_path):
    """The escape hatch the refusal points at, exercised.

    ``[source] dir`` is the same key ubCode reads for the same purpose, so a
    project that declares it is describing its layout once for both tools.
    """
    toml = """
    [source]
    dir = ["source"]

    [[source.variant_sources]]
    if = "var.edition == 'pro'"
    files = ["hostgated.rst"]

    [needs.variant_data]
    edition = "basic"
    """
    confdir, _ = make_project(tmp_path, toml=toml, srcdir_name="source")
    app = _build_split(confdir, confdir / "source", tmp_path / "build")
    assert "hostgated.html" not in _pages(app)
    assert "hostkeep.html" in _pages(app)


# ---------------------------------------------------------------------------
# Warn-and-exclude, and the safe drop
# ---------------------------------------------------------------------------


def test_an_unevaluable_condition_warns_and_excludes(make_app, tmp_path):
    """An unknown ``var.*`` key is data-dependent, so it is not a grammar error.

    Both engines fail to evaluate it the same way and both then exclude —
    warn-and-exclude, the contract the ``.. if::`` directive already has, and
    the safe direction for a rule whose purpose is keeping content out.
    """
    toml = """
    [[source.variant_sources]]
    if = "var.missing == 'pro'"
    files = ["hostgated.rst"]

    [needs.variant_data]
    edition = "pro"
    """
    confdir, _ = make_project(tmp_path, toml=toml)
    app = _build(make_app, confdir)
    assert "mounts.variant_rule_unevaluable" in app._warning.getvalue()
    assert "hostgated.html" not in _pages(app)


def test_a_rule_naming_no_files_is_dropped(make_app, tmp_path):
    """The one safe drop: a rule that named nothing has nothing to leak."""
    toml = """
    [[source.variant_sources]]
    if = "var.edition == 'pro'"
    files = []

    [needs.variant_data]
    edition = "basic"
    """
    confdir, _ = make_project(tmp_path, toml=toml)
    app = _build(make_app, confdir)
    assert "mounts.variant_rule_dropped" in app._warning.getvalue()
    assert "hostgated.html" in _pages(app)


def test_an_unknown_rule_key_is_reported_and_ignored(make_app, tmp_path):
    """Forward compatibility with a reader that models more keys than this one.

    The same posture mount entries take, and ubCode's
    ``config.variant_source_unknown_key``.
    """
    toml = """
    [[source.variant_sources]]
    if = "var.edition == 'pro'"
    files = ["hostgated.rst"]
    wehn = "typo"

    [needs.variant_data]
    edition = "pro"
    """
    confdir, _ = make_project(tmp_path, toml=toml)
    app = _build(make_app, confdir)
    warning = app._warning.getvalue()
    assert "mounts.unknown_key" in warning
    assert "wehn" in warning
    assert "hostgated.html" in _pages(app)


# ---------------------------------------------------------------------------
# The variant-data read rule
# ---------------------------------------------------------------------------


NEEDS_STUB = """
def setup(app):
    app.add_config_value("needs_variant_data", {inline}, "env")
    app.add_config_value("needs_variant_data_file", {file_ref}, "env")
    return {{"parallel_read_safe": True, "parallel_write_safe": True}}
"""


def _stub_conf(confdir: Path, module: str, inline: str, file_ref: str) -> None:
    """Register the two sphinx-needs confvals without sphinx-needs.

    Simulating the confvals directly is what makes all three cells of the
    matrix reachable deterministically: which cell a real sphinx-needs puts a
    project in depends on which release is installed, and the whole point of
    the unconditional re-merge is that the reader does not have to know.

    ``module`` must be unique per test. ``sys.modules`` is process-global and
    survives a ``SphinxTestApp``'s ``sys.path`` restore, so two tests sharing a
    stub name would silently share the first one's confval defaults — and the
    second test would then pass or fail for the wrong reason.
    """
    _write(
        confdir / f"{module}.py", NEEDS_STUB.format(inline=inline, file_ref=file_ref)
    )
    conf = confdir / "conf.py"
    conf.write_text(
        conf.read_text(encoding="utf-8").replace(
            'extensions = ["sphinx_mounts"]',
            "import os, sys; sys.path.insert(0, os.path.dirname(__file__))\n"
            f'extensions = ["{module}", "sphinx_mounts"]',
        ),
        encoding="utf-8",
    )


FILE_TOML = """
[[source.variant_sources]]
if = "var.edition == 'pro' and var.build.debug == True"
files = ["hostgated.rst"]

[needs]
variant_data_file = "variants.json"

[needs.variant_data]
edition = "pro"
"""


def test_the_file_side_is_read_when_sphinx_needs_is_absent(make_app, tmp_path):
    """Cell 1 of the matrix: nothing else computes the map, so this does."""
    confdir, _ = make_project(tmp_path, toml=FILE_TOML)
    (confdir / "variants.json").write_text(
        json.dumps({"edition": "basic", "build": {"debug": True}}), encoding="utf-8"
    )
    app = _build(make_app, confdir)
    # Inline `edition = "pro"` wins over the file's "basic"; the file supplies
    # `build.debug`, which the inline table does not have. Rule holds.
    assert "hostgated.html" in _pages(app)


def test_the_file_side_survives_an_unmerged_inline_map(make_app, tmp_path):
    """Cell 2: sphinx-needs present, resolution not yet performed.

    Every release up to and including 8.3.1 resolves the variant map at
    ``env-before-read-docs``, long after ``config-inited``, so at this seam
    ``needs_variant_data`` holds the **inline half only**. Without the
    unconditional re-merge the file-side keys are simply missing, every
    reference to one is an unknown key, and every rule excludes.
    """
    confdir, _ = make_project(tmp_path, toml=FILE_TOML)
    (confdir / "variants.json").write_text(
        json.dumps({"edition": "basic", "build": {"debug": True}}), encoding="utf-8"
    )
    _stub_conf(
        confdir,
        "needs_stub_unmerged",
        inline='{"edition": "pro"}',
        file_ref='"variants.json"',
    )
    app = _build(make_app, confdir)
    assert "mounts.variant_rule_unevaluable" not in app._warning.getvalue()
    assert "hostgated.html" in _pages(app)


def test_the_merge_is_a_no_op_on_an_already_merged_map(make_app, tmp_path):
    """Cell 3: sphinx-needs present and already resolved.

    ``deep_merge(file, already_merged) == already_merged``, so the re-merge
    changes nothing and the two tools cannot disagree about which documents
    exist. The output has to be identical to cell 2's.
    """
    confdir, _ = make_project(tmp_path, toml=FILE_TOML)
    (confdir / "variants.json").write_text(
        json.dumps({"edition": "basic", "build": {"debug": True}}), encoding="utf-8"
    )
    _stub_conf(
        confdir,
        "needs_stub_merged",
        inline='{"edition": "pro", "build": {"debug": True}}',
        file_ref='"variants.json"',
    )
    app = _build(make_app, confdir)
    assert "hostgated.html" in _pages(app)


def test_a_toml_declared_data_file_anchors_at_the_toml_directory(make_app, tmp_path):
    """The first of the two anchors, with the two directories kept distinct.

    A relative ``variant_data_file`` declared in the TOML resolves against the
    **TOML's own directory**; one declared in ``conf.py`` or with ``-D``
    resolves against ``confdir``. Reading only one anchor means reading the
    wrong file for one of the two routes — and here that would mean reading no
    file at all.
    """
    toml = """
    [[source.variant_sources]]
    if = "var.edition == 'pro'"
    files = ["hostgated.rst"]

    [needs]
    variant_data_file = "variants.json"

    [source]
    dir = [".."]
    """
    confdir, _ = make_project(tmp_path, toml=toml)
    # Move the TOML into a sub-directory, with its data file beside it. A
    # confdir anchor would look for `<confdir>/variants.json`, which is absent.
    # `[source] dir = [".."]` keeps the rules anchored at the Sphinx source
    # directory, which is what the layout guard requires — and it is a separate
    # anchor from the data file's, which is the point of the test.
    configs = confdir / "configs"
    configs.mkdir()
    shutil.move(str(confdir / "ubproject.toml"), str(configs / "ubproject.toml"))
    (configs / "variants.json").write_text(
        json.dumps({"edition": "pro"}), encoding="utf-8"
    )
    conf = confdir / "conf.py"
    conf.write_text(
        conf.read_text(encoding="utf-8")
        + '\nsources_from_toml = "configs/ubproject.toml"\n',
        encoding="utf-8",
    )
    app = _build(make_app, confdir)
    assert "mounts.variant_rule_unevaluable" not in app._warning.getvalue()
    assert "hostgated.html" in _pages(app)


def test_unreadable_variant_data_is_a_hard_error_without_sphinx_needs(
    make_app, tmp_path
):
    """With no variant map there is no defensible answer to "which files".

    Hard only when sphinx-needs is absent: when it is present it raises its own
    ``NeedsConfigException`` for the same file, and reporting here as well
    would be two messages for one problem.
    """
    toml = """
    [[source.variant_sources]]
    if = "var.edition == 'pro'"
    files = ["hostgated.rst"]

    [needs]
    variant_data_file = "variants.json"
    """
    confdir, _ = make_project(tmp_path, toml=toml)
    (confdir / "variants.json").write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(Exception, match="variant_data_unreadable"):
        _build(make_app, confdir)


# ---------------------------------------------------------------------------
# The confvals
# ---------------------------------------------------------------------------


def test_the_deprecated_confval_is_honoured_and_reported(make_app, tmp_path):
    confdir, _ = make_project(tmp_path, toml=base_toml("basic"))
    shutil.move(str(confdir / "ubproject.toml"), str(confdir / "custom.toml"))
    conf = confdir / "conf.py"
    conf.write_text(
        conf.read_text(encoding="utf-8") + '\nmounts_from_toml = "custom.toml"\n',
        encoding="utf-8",
    )
    app = _build(make_app, confdir)
    assert "mounts.deprecated_confval" in app._warning.getvalue()
    assert "hostgated.html" not in _pages(app)


def test_setting_both_confvals_differently_is_a_hard_error(make_app, tmp_path):
    """Not a precedence puzzle: which file is read must be readable off conf.py."""
    confdir, _ = make_project(tmp_path, toml=base_toml("basic"))
    conf = confdir / "conf.py"
    conf.write_text(
        conf.read_text(encoding="utf-8")
        + '\nmounts_from_toml = "a.toml"\nsources_from_toml = "b.toml"\n',
        encoding="utf-8",
    )
    with pytest.raises(Exception, match="Keep exactly one"):
        _build(make_app, confdir)


def test_sources_from_toml_none_disables_the_variant_reader_too(make_app, tmp_path):
    """The coupling, named rather than discovered.

    ``sources_from_toml = None`` means "never read that file", and variant
    rules live in it, so they stop being read as well. That is a **fail-open**
    coupling — content the rules gate gets published — which is exactly why the
    documentation states it by name.
    """
    confdir, _ = make_project(tmp_path, toml=base_toml("basic"))
    conf = confdir / "conf.py"
    conf.write_text(
        conf.read_text(encoding="utf-8") + "\nsources_from_toml = None\n",
        encoding="utf-8",
    )
    app = _build(make_app, confdir)
    assert "hostgated.html" in _pages(app)


def test_a_project_with_no_mounts_can_use_variant_rules(make_app, tmp_path):
    """The whole justification for homing the reader here, from a user's view.

    A project with no mounts at all can install sphinx-mounts purely to have
    ``sphinx-build`` narrow its document set per variant, exactly as ubCode
    does.
    """
    toml = """
    [[source.variant_sources]]
    if = "var.edition == 'pro'"
    files = ["hostgated.rst"]

    [needs.variant_data]
    edition = "basic"
    """
    confdir, _ = make_project(tmp_path, toml=toml)
    app = _build(make_app, confdir)
    assert app.config.mounts == []
    assert "hostgated.html" not in _pages(app)
    assert "hostkeep.html" in _pages(app)
