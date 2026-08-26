"""End-to-end coverage for ``if`` on a ``[[source.mounts]]`` entry.

Whole-bundle variant gating. ``[[source.variant_sources]]`` narrows a file set
by glob; this key removes a whole mount, which makes it the blunter of the two
and the one whose failure modes are larger:

* it must **fail closed** on every path — a condition that is false, one that
  cannot be validated, one that cannot be evaluated, and one this reader never
  got to look at all end with the bundle out of the build;
* it must be **silent in the right places**: a mount whose condition holds must
  produce no ``mounts.unknown_key``, and a mount that is gated off must produce
  no ``attach_to`` complaint, no dangling toctree entry and no ``-W`` failure;
* it must be **loud in the one place that matters**: a gated-off bundle is a
  large, silent absence, so the record fires whether or not anything in the
  project references it.

So these tests build real projects and look at what came out, rather than at
what the reader computed.
"""

from __future__ import annotations

import logging as stdlib_logging
from pathlib import Path
import textwrap
from typing import Any

import pytest

from sphinx_mounts import warnings as mount_warnings
from sphinx_mounts.logging import MOUNT_GATED_CODE


@pytest.fixture(autouse=True)
def _detach_filters():
    """Keep the process-global logger filters from leaking between tests.

    The emitting loggers are module-level objects shared by every ``Sphinx``
    application in the process, so a test that installs a filter and never
    builds again would change what the next test sees.
    """
    yield
    mount_warnings.remove_downgrade_filters()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")


def bundle_path(root: Path) -> str:
    """The directory bundle :func:`make_project` writes, as a ``conf.py`` literal.

    Needed by the ``conf.py`` routes, which declare their mounts before the
    project exists and so cannot be handed the path the TOML substitution
    would have given them.
    """
    return (root / "bundle").as_posix()


def make_project(
    root: Path,
    *,
    toml: str,
    conf_extra: str = "",
    srcdir_name: str | None = None,
    host_entries: tuple[str, ...] = (),
    host_glob: str | None = None,
    host_files: dict[str, str] | None = None,
) -> tuple[Path, Path]:
    """Materialise a host project plus two external bundles.

    The host index toctrees only what ``host_entries`` names, so a mount is
    reachable through its own ``attach_to`` wiring and through nothing else.
    That is what makes "the mount contributed nothing" observable without a
    dangling reference confusing the picture — a reference INTO a gated bundle
    is its own scenario, and the tests that want one ask for it.

    ``{bundle}``, ``{rival}``, ``{loose}``, ``{alpha}`` and ``{beta}`` are
    substituted into ``toml`` with absolute paths. ``rival`` exists so that two
    mounts can contest one ``mount_at``, which is the natural shape for this
    key and the shape the attribution's ordering has to survive.

    :return: ``(confdir, bundle)``.
    """
    confdir = root / "proj"
    srcdir = confdir if srcdir_name is None else confdir / srcdir_name
    bundle = root / "bundle"
    rival = root / "rival"
    loose = root / "loose"

    _write(
        bundle / "index.rst",
        """
        Bundle
        ======

        BUNDLE_INDEX_MARKER

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
    _write(
        rival / "index.rst",
        """
        Rival
        =====

        RIVAL_INDEX_MARKER
    """,
    )
    for name in ("alpha", "beta"):
        _write(
            loose / f"{name}.rst",
            f"""
            {name.title()}
            {"=" * len(name)}

            {name.upper()}_MARKER
        """,
        )
    for name, body in (host_files or {}).items():
        _write(srcdir / name, body)

    # Assembled line by line rather than through a dedented template, for the
    # reason the conf.py below spells out: an interpolated multi-line block
    # would leave `textwrap.dedent` nothing in common to strip, and the whole
    # document would keep its template indentation.
    lines = ["Host", "====", "", "HOST_MARKER", "", ".. toctree::", ""]
    lines += [f"   {entry}" for entry in host_entries]
    lines.append("")
    if host_glob:
        lines += [".. toctree::", "   :glob:", "", f"   {host_glob}", ""]
    srcdir.mkdir(parents=True, exist_ok=True)
    (srcdir / "index.rst").write_text("\n".join(lines), encoding="utf-8")
    # Written line by line rather than through a dedented template: a
    # multi-line ``conf_extra`` interpolated into one would leave its
    # continuation lines un-indented, which makes `textwrap.dedent` a no-op and
    # the whole file a syntax error.
    confdir.mkdir(parents=True, exist_ok=True)
    (confdir / "conf.py").write_text(
        "\n".join(
            [
                'project = "host"',
                'author = "tests"',
                'extensions = ["sphinx_mounts"]',
                "exclude_patterns: list[str] = []",
                'master_doc = "index"',
                conf_extra,
                "",
            ]
        ),
        encoding="utf-8",
    )
    _write(
        confdir / "ubproject.toml",
        toml.replace("{bundle}", bundle.as_posix())
        .replace("{rival}", rival.as_posix())
        .replace("{loose}", loose.as_posix())
        .replace("{alpha}", (loose / "alpha.rst").as_posix())
        .replace("{beta}", (loose / "beta.rst").as_posix()),
    )
    return confdir, bundle


def _build(
    make_app,
    confdir: Path,
    *,
    builddir: Path | None = None,
    freshenv: bool = True,
    attribution: dict[str, str] | None = None,
    **kwargs: Any,
):
    """Build the project, optionally snapshotting the downgrade attribution.

    The downgrade filter lives on process-global loggers and is detached at
    ``build-finished``, so a caller that looks at it after ``app.build()``
    returns always sees an empty map — correctly, since a finished build no
    longer owns those loggers. Passing ``attribution`` connects a listener at
    priority 1, ahead of the extension's own detach at the default 500, and
    fills the given dict with what the filter was holding.
    """
    app = make_app(srcdir=confdir, builddir=builddir, freshenv=freshenv, **kwargs)
    if attribution is not None:
        app.connect(
            "build-finished",
            lambda *_: attribution.update(_attribution()),
            priority=1,
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

    # Only ever used to assert that a build DOES fail. Constructing a second
    # `SphinxTestApp` in one process re-registers the `sphinx.addnodes` node
    # classes and emits an `app.add_node` warning for each, which under `-W`
    # is enough to fail any second build — so "it passed -W" has to be
    # asserted on a test's FIRST and only application, never through here.


def _attribution() -> dict[str, str]:
    """The docname -> gate/rule map the installed downgrade filter is holding.

    Read off the emitting loggers rather than off the app, because that is
    where the attribution actually lives and what the filter actually consults.
    An empty map means no filter is installed, which is the correct state for a
    build that excluded nothing.
    """
    for name in mount_warnings.FALLBACK_LOGGER_NAMES:
        for installed in stdlib_logging.getLogger(name).filters:
            if isinstance(installed, mount_warnings.DowngradeFilter):
                return dict(installed._excluded)
    return {}


DIR_MOUNT_TOML = """
[[source.mounts]]
dir = "{bundle}"
mount_at = "mnt"
attach_to = "index"
if = "var.edition == 'pro'"

[needs.variant_data]
edition = "EDITION"
"""

FILE_MOUNT_TOML = """
[[source.mounts]]
files = ["{alpha}", "{beta}"]
mount_at = "loose"
attach_to = "index"
attach_each = true
if = "var.edition == 'pro'"

[needs.variant_data]
edition = "EDITION"
"""


# ---------------------------------------------------------------------------
# The gate itself, in both mount modes
# ---------------------------------------------------------------------------


def test_a_false_condition_gates_the_whole_mount_off(make_app, tmp_path):
    """The bundle is out of the build entirely — not merely unwired."""
    confdir, _ = make_project(tmp_path, toml=DIR_MOUNT_TOML.replace("EDITION", "basic"))
    app = _build(make_app, confdir)
    assert "mnt/index" not in app.env.found_docs
    assert "mnt/binternal" not in app.env.found_docs
    assert not (Path(app.outdir) / "mnt" / "index.html").exists()


def test_a_true_condition_leaves_the_mount_mounted(make_app, tmp_path):
    """The control. Same file, same key, the other variant."""
    confdir, _ = make_project(tmp_path, toml=DIR_MOUNT_TOML.replace("EDITION", "pro"))
    app = _build(make_app, confdir)
    assert "mnt/index" in app.env.found_docs
    assert "mnt/binternal" in app.env.found_docs


def test_a_gated_on_mount_reports_no_unknown_key(make_app, tmp_path):
    """The key must be STRIPPED from a surviving table, not merely read.

    ``if`` is a Python keyword, so ``MountConfig`` can never model it as a
    field and ``from_dict`` would report ``mounts.unknown_key`` for it. That is
    a *warning*, so the trap is not cosmetic: it fails ``sphinx-build -W`` on a
    project whose only sin is using the key exactly as documented.
    """
    confdir, _ = make_project(tmp_path, toml=DIR_MOUNT_TOML.replace("EDITION", "pro"))
    app = _build(make_app, confdir)
    warning = app._warning.getvalue()
    assert "mounts.unknown_key" not in warning
    assert warning.strip() == ""


@pytest.mark.parametrize("edition", ["pro", "basic"])
def test_neither_arm_fails_under_dash_w(make_app, tmp_path, edition):
    """Both verdicts have to be clean under ``-W``, for opposite reasons.

    Gated ON, the risk is the unstripped key. Gated OFF, the risk is every
    diagnostic about a mount that is not in the build: the ``attach_to`` host
    that was never extended, the bundle root that no longer matters.
    """
    confdir, _ = make_project(tmp_path, toml=DIR_MOUNT_TOML.replace("EDITION", edition))
    assert not _fails_under_dash_w(make_app, confdir, tmp_path / "build")


@pytest.mark.parametrize("edition", ["pro", "basic"])
def test_a_file_list_mount_is_gated_uniformly(make_app, tmp_path, edition):
    """A whole-mount ``if`` gates a ``files`` mount exactly as it gates a ``dir``.

    This is a different question from the one ``[[source.variant_sources]]``
    answers, and it has the opposite answer. A rule cannot narrow a file-list
    mount in either reader — a ``files`` mount's entries bypass pattern
    matching entirely — but dropping a whole bundle touches neither ``include``
    nor ``exclude``, so it is mode-blind by construction here and in ubCode.
    Reading "file-list mounts are now gateable" as "rules reach them now" is
    the confusion this test exists to keep separate.
    """
    confdir, _ = make_project(
        tmp_path, toml=FILE_MOUNT_TOML.replace("EDITION", edition)
    )
    app = _build(make_app, confdir)
    present = {"loose/alpha", "loose/beta"} <= app.env.found_docs
    assert present is (edition == "pro")


def test_a_gated_off_mount_wires_nothing_into_the_host_toctree(make_app, tmp_path):
    """``attach_to`` is a no-op for a bundle that produced no documents.

    Silent because the mount produced nothing, not because anything
    special-cases it: ``_wired_entries`` already gates on what ``discover()``
    returned, and a gated mount returns an empty list.
    """
    confdir, _ = make_project(tmp_path, toml=DIR_MOUNT_TOML.replace("EDITION", "basic"))
    app = _build(make_app, confdir)
    assert app.env.toctree_includes.get("index", []) == []
    assert app._warning.getvalue().strip() == ""


def test_a_gated_off_mount_does_not_report_a_missing_attach_to(make_app, tmp_path):
    """A typo in ``attach_to`` is not this variant's problem.

    The mount wires nothing here, so ``mounts.attach_to_missing`` would be a
    warning about work that was never attempted — and ``-W`` would fail a
    correctly gated build over it. The same typo is still reported in every
    variant where the mount is live, which the second half asserts.
    """
    toml = DIR_MOUNT_TOML.replace('attach_to = "index"', 'attach_to = "nosuchdoc"')
    confdir, _ = make_project(tmp_path, toml=toml.replace("EDITION", "basic"))
    app = _build(make_app, confdir)
    assert "attach_to_missing" not in app._warning.getvalue()

    confdir_live, _ = make_project(
        tmp_path / "live", toml=toml.replace("EDITION", "pro")
    )
    app_live = _build(make_app, confdir_live)
    assert "attach_to_missing" in app_live._warning.getvalue()


# ---------------------------------------------------------------------------
# The record: a gated bundle is a large, silent absence without it
# ---------------------------------------------------------------------------


def test_a_gated_off_mount_is_recorded_even_when_nothing_references_it(
    make_app, tmp_path
):
    """The whole mitigation for this key's nastiest failure shape.

    Nothing in the host project mentions the bundle, so no toctree warning,
    no downgrade and no missing-page symptom can point at it. Without this
    record, "where did my 400 pages go" is answerable only by re-reading
    ``ubproject.toml``.
    """
    confdir, _ = make_project(tmp_path, toml=DIR_MOUNT_TOML.replace("EDITION", "basic"))
    app = _build(make_app, confdir)
    status = app._status.getvalue()
    assert MOUNT_GATED_CODE in status
    assert "var.edition == 'pro'" in status
    assert "[[source.mounts]][0]" in status


def test_the_record_is_info_rather_than_a_warning(make_app, tmp_path):
    """Gating is what the author asked for, so it must not fail ``-W``."""
    confdir, _ = make_project(tmp_path, toml=DIR_MOUNT_TOML.replace("EDITION", "basic"))
    app = _build(make_app, confdir)
    assert MOUNT_GATED_CODE not in app._warning.getvalue()


def test_a_live_mount_is_not_recorded_as_gated(make_app, tmp_path):
    confdir, _ = make_project(tmp_path, toml=DIR_MOUNT_TOML.replace("EDITION", "pro"))
    app = _build(make_app, confdir)
    assert MOUNT_GATED_CODE not in app._status.getvalue()


# ---------------------------------------------------------------------------
# A project that gates mounts and declares no rules
# ---------------------------------------------------------------------------


def test_a_mounts_only_project_reaches_the_fold(make_app, tmp_path):
    """No ``[[source.variant_sources]]`` anywhere, and the gate still fires.

    The reader used to short-circuit on five separate rules-only premises
    before it reached any fold. Every one of them is a project that gates
    mounts and declares no rules, which is the ordinary shape for a host
    project that consumes bundles it does not own.
    """
    confdir, _ = make_project(tmp_path, toml=DIR_MOUNT_TOML.replace("EDITION", "basic"))
    assert "variant_sources" not in (confdir / "ubproject.toml").read_text()
    app = _build(make_app, confdir)
    assert "mnt/index" not in app.env.found_docs


def test_a_mounts_only_project_is_not_refused_by_the_layout_guard(make_app, tmp_path):
    """A mount ``if`` anchors no glob, so no layout can be wrong for it.

    The layout guard exists because a rule GLOB has to be re-expressible as an
    ``exclude_patterns`` entry anchored at ``srcdir``. Applying it to a project
    that only gates mounts refuses a configuration with nothing wrong with
    it — and the layout it would refuse (``ubproject.toml`` beside ``conf.py``,
    sources one directory down) is entirely ordinary.
    """
    toml = DIR_MOUNT_TOML.replace("EDITION", "basic")
    confdir, _ = make_project(tmp_path, toml=f"[source]\ndir = 'source'\n{toml}")
    # `[source] dir` names a directory that is not Sphinx's srcdir, which is
    # exactly the shape the guard refuses when rules are declared.
    app = _build(make_app, confdir)
    assert "mnt/index" not in app.env.found_docs
    assert app._warning.getvalue().strip() == ""


def test_the_layout_guard_still_fires_for_a_rule_declaring_project(make_app, tmp_path):
    """The other direction, so the scoping is a scoping and not a removal."""
    toml = """
    [source]
    dir = "nowhere"

    [[source.mounts]]
    dir = "{bundle}"
    mount_at = "mnt"
    if = "var.edition == 'pro'"

    [[source.variant_sources]]
    if = "var.edition == 'pro'"
    files = ["gated/**"]

    [needs.variant_data]
    edition = "basic"
    """
    confdir, _ = make_project(tmp_path, toml=toml)
    with pytest.raises(Exception, match="mounts.variant_layout"):
        _build(make_app, confdir)


# ---------------------------------------------------------------------------
# Failure postures: fail closed on every path
# ---------------------------------------------------------------------------


def test_an_ungrammatical_mount_condition_refuses_the_configuration(make_app, tmp_path):
    """One grammar, one validator — so one posture, the rule key's.

    A bare field is refused for a rule; it has to be refused for a mount too,
    or ``if`` would mean two different things in one file.
    """
    toml = DIR_MOUNT_TOML.replace("\"var.edition == 'pro'\"", '"var.debug"')
    confdir, _ = make_project(tmp_path, toml=toml.replace("EDITION", "basic"))
    with pytest.raises(Exception, match="outside the condition grammar"):
        _build(make_app, confdir)


def test_one_hard_error_lists_offenders_from_both_keys(make_app, tmp_path):
    """Fixing one refused condition only to meet the next is what this avoids.

    Two error paths for one grammar could also disagree about what the grammar
    is, which is why the two keys go through the validator in a single call.
    """
    toml = """
    [[source.mounts]]
    dir = "{bundle}"
    mount_at = "mnt"
    if = "var.debug"

    [[source.variant_sources]]
    if = "edition == 'pro'"
    files = ["gated/**"]

    [needs.variant_data]
    edition = "basic"
    """
    confdir, _ = make_project(tmp_path, toml=toml)
    with pytest.raises(Exception) as excinfo:
        _build(make_app, confdir)
    message = str(excinfo.value)
    assert "2 variant condition(s)" in message
    assert "[[source.mounts]][0]" in message
    assert "[[source.variant_sources]][0]" in message


def test_a_non_string_condition_is_refused(make_app, tmp_path):
    """A rule's loader already rejects one; a mount table can still carry it."""
    toml = DIR_MOUNT_TOML.replace("if = \"var.edition == 'pro'\"", "if = 3")
    confdir, _ = make_project(tmp_path, toml=toml.replace("EDITION", "basic"))
    with pytest.raises(Exception, match="condition must be a string"):
        _build(make_app, confdir)


def test_an_unevaluable_mount_condition_gates_off_and_warns(make_app, tmp_path):
    """Data-dependent, so warn-and-gate rather than refuse.

    The same posture the ``.. if::`` directive already has, and the safe
    direction for a key whose purpose is keeping content out of the build.
    """
    toml = DIR_MOUNT_TOML.replace(
        "if = \"var.edition == 'pro'\"", "if = \"var.nosuchkey == 'pro'\""
    )
    confdir, _ = make_project(tmp_path, toml=toml.replace("EDITION", "basic"))
    app = _build(make_app, confdir)
    assert "mnt/index" not in app.env.found_docs
    assert "mounts.variant_rule_unevaluable" in app._warning.getvalue()


def test_a_condition_this_reader_never_evaluates_still_gates_off(make_app, tmp_path):
    """``sources_from_toml = None`` switches off everything read from TOML.

    The mounts then come from ``conf.py``, so a condition on one of them
    reaches no evaluator at all. Publishing the bundle would be the one outcome
    a gating key must not have, so it is gated off — and reported, because a
    silent disappearance is exactly what the record exists to prevent.
    """
    confdir, bundle = make_project(
        tmp_path,
        toml="",
        conf_extra=(
            "sources_from_toml = None\n"
            f'mounts = [{{"dir": "{bundle_path(tmp_path)}", "mount_at": "mnt", '
            '"if": "var.edition == \'pro\'"}]'
        ),
    )
    app = _build(make_app, confdir)
    assert "mnt/index" not in app.env.found_docs
    assert "mount_gate_unevaluable" in app._warning.getvalue()


# ---------------------------------------------------------------------------
# The conf.py routes
# ---------------------------------------------------------------------------


def test_a_conf_py_mapping_carries_a_condition(make_app, tmp_path):
    """The limitation is the dataclass's, not the route's.

    A ``conf.py``-declared mount written as a plain mapping is read by the same
    reader as a TOML table, so its ``if`` is evaluated. Only a ``MountConfig``
    *instance* cannot carry one — ``if`` is a Python keyword, so no dataclass
    field can be named for it.
    """
    confdir, _ = make_project(
        tmp_path,
        toml="[needs.variant_data]\nedition = 'basic'\n",
        conf_extra=(
            f'mounts = [{{"dir": "{bundle_path(tmp_path)}", "mount_at": "mnt", '
            '"if": "var.edition == \'pro\'"}]'
        ),
    )
    app = _build(make_app, confdir)
    assert "mnt/index" not in app.env.found_docs


def test_a_conf_py_mountconfig_instance_is_unaffected(make_app, tmp_path):
    """The documented limitation, pinned from the other side.

    An instance cannot carry a condition, so it is never gated — and the TOML
    route in the same project keeps working, which is what makes the
    limitation survivable rather than a hole.
    """
    confdir, _ = make_project(
        tmp_path,
        toml="[needs.variant_data]\nedition = 'basic'\n",
        conf_extra=(
            "from pathlib import Path\n"
            "from sphinx_mounts.config import MountConfig\n"
            f'mounts = [MountConfig(dir=Path("{bundle_path(tmp_path)}"), '
            'mount_at="mnt")]'
        ),
    )
    app = _build(make_app, confdir)
    assert "mnt/index" in app.env.found_docs


# ---------------------------------------------------------------------------
# Convergence: a gating flip is a config change Sphinx already knows
# ---------------------------------------------------------------------------


def test_a_gating_flip_converges_in_both_directions(make_app, tmp_path):
    """Three builds in one output directory, on and off and on again.

    The gate lives in the ``mounts`` config VALUE — the key survives on a
    gated-off table and is stripped from a live one — and that confval is
    ``rebuild="env"``, so Sphinx re-reads every document on the build where
    the flip happened. A reader that gated without touching a config value
    would leave both values byte-identical across the flip and would need an
    invalidation story of its own.
    """
    confdir, _ = make_project(tmp_path, toml=DIR_MOUNT_TOML.replace("EDITION", "pro"))
    builddir = tmp_path / "build"
    toml_path = confdir / "ubproject.toml"

    app = _build(make_app, confdir, builddir=builddir)
    assert "mnt/index" in app.env.found_docs

    toml_path.write_text(
        toml_path.read_text().replace('edition = "pro"', 'edition = "basic"'),
        encoding="utf-8",
    )
    app = _build(make_app, confdir, builddir=builddir, freshenv=False)
    assert "mnt/index" not in app.env.found_docs

    toml_path.write_text(
        toml_path.read_text().replace('edition = "basic"', 'edition = "pro"'),
        encoding="utf-8",
    )
    app = _build(make_app, confdir, builddir=builddir, freshenv=False)
    assert "mnt/index" in app.env.found_docs


# ---------------------------------------------------------------------------
# Attribution: which references into a gated bundle are downgraded, and why
# the docnames come from the real pipeline rather than a second walk
# ---------------------------------------------------------------------------


def test_a_toctree_entry_into_a_gated_bundle_is_downgraded(make_app, tmp_path):
    """A host index that lists every variant's pages is the normal 150% shape.

    Sphinx is right that the document is missing; what is wrong is calling it a
    problem. The record is reworded to name the gate, downgraded to INFO, and
    ``-W`` passes.
    """
    confdir, _ = make_project(
        tmp_path,
        toml=DIR_MOUNT_TOML.replace("EDITION", "basic"),
        host_entries=("mnt/index",),
    )
    app = _build(make_app, confdir, warningiserror=True)
    status = app._status.getvalue()
    assert mount_warnings.VARIANT_EXCLUDED_CODE in status
    assert "[[source.mounts]][0] (if = \"var.edition == 'pro'\")" in status
    assert "WARNING" not in app._warning.getvalue()
    assert app.statuscode == 0


def test_the_attribution_covers_every_page_of_the_gated_bundle(make_app, tmp_path):
    """Not just the entry doc: the whole bundle left, so all of it is attributed."""
    confdir, _ = make_project(tmp_path, toml=DIR_MOUNT_TOML.replace("EDITION", "basic"))
    attributed: dict[str, str] = {}
    _build(make_app, confdir, attribution=attributed)
    assert set(attributed) == {"mnt/index", "mnt/binternal"}


def test_a_genuine_typo_still_warns_beside_a_gated_mount(make_app, tmp_path):
    """The negative control, and the reason the downgrade must be exact.

    A reference no gate and no rule explains still warns and still fails
    ``-W``, so a typo cannot hide behind a variant.
    """
    confdir, _ = make_project(
        tmp_path,
        toml=DIR_MOUNT_TOML.replace("EDITION", "basic"),
        host_entries=("mnt/index", "nosuchdoc"),
    )
    app = _build(make_app, confdir)
    warning = app._warning.getvalue()
    assert "nosuchdoc" in warning
    assert "mnt/index" not in warning
    assert _fails_under_dash_w(make_app, confdir, tmp_path / "build")


def test_a_glob_entry_matching_only_gated_pages_is_downgraded(make_app, tmp_path):
    """The ``:glob:`` arm reaches a gated bundle the same way it reaches a rule."""
    confdir, _ = make_project(
        tmp_path,
        toml=DIR_MOUNT_TOML.replace("EDITION", "basic"),
        host_glob="mnt/*",
    )
    app = _build(make_app, confdir, warningiserror=True)
    assert mount_warnings.VARIANT_EXCLUDED_CODE in app._status.getvalue()
    assert "WARNING" not in app._warning.getvalue()
    assert app.statuscode == 0


def test_a_file_list_mount_gate_attributes_its_docnames(make_app, tmp_path):
    """File-list mode has no walk to reproduce, and still goes through it."""
    confdir, _ = make_project(
        tmp_path,
        toml=FILE_MOUNT_TOML.replace("EDITION", "basic"),
        host_entries=("loose/alpha",),
    )
    attributed: dict[str, str] = {}
    app = _build(make_app, confdir, attribution=attributed, warningiserror=True)
    assert set(attributed) == {"loose/alpha", "loose/beta"}
    assert mount_warnings.VARIANT_EXCLUDED_CODE in app._status.getvalue()
    assert "WARNING" not in app._warning.getvalue()
    assert app.statuscode == 0


# ---------------------------------------------------------------------------
# The phantom hazard: an attributed docname that IS still walkable would
# silently disable a genuine `-W` failure
# ---------------------------------------------------------------------------


TWO_MOUNTS_TOML = """
[[source.mounts]]
dir = "{bundle}"
mount_at = "mnt"
if = "var.edition == 'pro'"

[[source.mounts]]
dir = "{rival}"
mount_at = "mnt"
if = "var.edition == 'basic'"

[needs.variant_data]
edition = "basic"
"""


def test_a_docname_a_live_mount_still_supplies_is_not_attributed(make_app, tmp_path):
    """Two mounts, one ``mount_at``, mutually exclusive conditions.

    This is the shape the key is *for* — the pro bundle and the basic bundle
    both live at ``guides`` and exactly one of them is built. ``mnt/index``
    exists in this variant, supplied by the mount that is live, so a reference
    to it is an ordinary resolved reference and must not be downgraded.

    Attributing it would be a phantom, and a phantom is not merely a wrong
    message: the filter downgrades every toctree record naming an attributed
    docname, so a **genuine** warning about that name would be silenced and
    ``-W`` would stop failing. The gated pass runs after every live mount has
    registered precisely so that this cannot happen.
    """
    confdir, _ = make_project(
        tmp_path, toml=TWO_MOUNTS_TOML, host_entries=("mnt/index",)
    )
    attributed: dict[str, str] = {}
    app = _build(make_app, confdir, attribution=attributed, warningiserror=True)
    assert "mnt/index" in app.env.found_docs
    assert "mnt/index" not in attributed
    assert "WARNING" not in app._warning.getvalue()
    assert app.statuscode == 0
    # And the gated mount attributes NOTHING, not merely "not `mnt/index`".
    # The contested docname triggers the same whole-mount skip the live path
    # applies, so the reduction reaches its sibling `mnt/binternal` too. That
    # is deliberate: whether the gated mount would have supplied that page in
    # the variant where it is live depends on which mounts are live THERE,
    # which this build cannot know. Under-attributing costs a genuine warning
    # on a reference nobody writes; over-attributing costs a phantom, and a
    # phantom silences a real one.
    assert attributed == {}


def test_a_docname_the_host_supplies_is_not_attributed(make_app, tmp_path):
    """Host precedence is one of the reductions ``discover`` applies.

    The host's own ``mnt/index.rst`` wins over any mount, so the docname is
    alive in both variants and a reference to it is never variant-excluded.
    """
    confdir, _ = make_project(
        tmp_path,
        toml=DIR_MOUNT_TOML.replace("EDITION", "basic"),
        host_entries=("mnt/index",),
        host_files={
            "mnt/index.rst": "Host mnt\n========\n\nHOST_MNT_MARKER\n",
        },
    )
    attributed: dict[str, str] = {}
    app = _build(make_app, confdir, attribution=attributed, warningiserror=True)
    assert "mnt/index" in app.env.found_docs
    assert "mnt/index" not in attributed
    assert "WARNING" not in app._warning.getvalue()
    assert app.statuscode == 0


def test_a_gated_mount_with_an_absent_root_attributes_nothing_and_says_nothing(
    make_app, tmp_path
):
    """An absent bundle root is not a problem for a mount that is gated off.

    ``mounts.missing_path`` is a warning, so reporting it would fail ``-W`` on
    a project that gated a bundle its CI has not checked out — which is one of
    the reasons to gate a bundle in the first place. The whole-mount skip still
    happens, so nothing is attributed either.
    """
    toml = DIR_MOUNT_TOML.replace('dir = "{bundle}"', 'dir = "{bundle}-gone"')
    confdir, _ = make_project(tmp_path, toml=toml.replace("EDITION", "basic"))
    attributed: dict[str, str] = {}
    app = _build(make_app, confdir, attribution=attributed)
    assert "missing_path" not in app._warning.getvalue()
    assert attributed == {}


def test_gated_docnames_never_reach_the_wiring_dictionary(make_app, tmp_path):
    """The separate dictionary is load-bearing, not tidiness.

    ``_wired_entries`` reads ``_mount_entry_docnames`` as "what this mount
    produced" and wires ``attach_to`` from it. Publishing a gated mount's
    docnames there would wire a toctree entry no document backs — an
    un-suppressible ``toc.not_readable``, i.e. the mount modifying the host
    project while not being in the build at all.
    """
    confdir, _ = make_project(tmp_path, toml=DIR_MOUNT_TOML.replace("EDITION", "basic"))
    app = _build(make_app, confdir)
    project = app.env.project
    assert project._mount_entry_docnames == {0: []}
    assert project._gated_entry_docnames == {0: ["mnt/binternal", "mnt/index"]}


def test_the_gated_docnames_stay_out_of_the_pickled_environment(make_app, tmp_path):
    """``__getstate__`` clears the new field like the three beside it.

    Nothing reads it back — ``discover()`` rebuilds it every build — so
    pickling it would be cache weight plus a version coupling, and the mount
    state this extension deliberately keeps out of every user's ``.doctrees``
    would be back.
    """
    confdir, _ = make_project(tmp_path, toml=DIR_MOUNT_TOML.replace("EDITION", "basic"))
    app = _build(make_app, confdir)
    assert app.env.project.__getstate__()["_gated_entry_docnames"] == {}


@pytest.mark.parametrize("edition", ["pro", "basic"])
@pytest.mark.parametrize("jobs", [1, 2])
def test_dash_w_passes_in_both_variants_serially_and_in_parallel(
    make_app, tmp_path, edition, jobs
):
    """The four-cell matrix a variant CI actually runs.

    The downgrade is installed on process-global loggers at
    ``env-before-read-docs``; ``sphinx-build -j`` reads documents in worker
    processes and sends their records back, which is a different path through
    the same filter. Both verdicts have to be clean in both.
    """
    confdir, _ = make_project(
        tmp_path,
        toml=DIR_MOUNT_TOML.replace("EDITION", edition),
        host_entries=("mnt/index",),
    )
    assert not _fails_under_dash_w_parallel(make_app, confdir, tmp_path / "build", jobs)


def _fails_under_dash_w_parallel(make_app, confdir: Path, builddir: Path, jobs: int):
    try:
        app = _build(
            make_app,
            confdir,
            warningiserror=True,
            builddir=builddir,
            parallel=jobs,
        )
    except Exception:
        return True
    return app.statuscode != 0


def test_the_attribution_is_recomputed_for_a_second_build_of_one_application(
    make_app, tmp_path
):
    """Per BUILD, not per construction.

    ``Sphinx.build()`` may be called more than once on one application, and the
    filter comes off at ``build-finished``. A second build that ran unfiltered
    would emit the variant-excluded record un-downgraded and fail ``-W`` on a
    correctly gated project.
    """
    confdir, _ = make_project(
        tmp_path,
        toml=DIR_MOUNT_TOML.replace("EDITION", "basic"),
        host_entries=("mnt/index",),
    )
    first: dict[str, str] = {}
    second: dict[str, str] = {}
    app = _build(make_app, confdir, attribution=first)
    assert set(first) == {"mnt/index", "mnt/binternal"}
    app.connect("build-finished", lambda *_: second.update(_attribution()), priority=1)
    app.build()
    assert set(second) == {"mnt/index", "mnt/binternal"}
