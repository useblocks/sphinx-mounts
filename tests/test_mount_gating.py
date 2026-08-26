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
) -> tuple[Path, Path]:
    """Materialise a host project plus two external bundles.

    The host index toctrees only what ``host_entries`` names, so a mount is
    reachable through its own ``attach_to`` wiring and through nothing else.
    That is what makes "the mount contributed nothing" observable without a
    dangling reference confusing the picture — a reference INTO a gated bundle
    is its own scenario, and the tests that want one ask for it.

    ``{bundle}``, ``{loose}``, ``{alpha}`` and ``{beta}`` are substituted into
    ``toml`` with absolute paths.

    :return: ``(confdir, bundle)``.
    """
    confdir = root / "proj"
    srcdir = confdir if srcdir_name is None else confdir / srcdir_name
    bundle = root / "bundle"
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
    for name in ("alpha", "beta"):
        _write(
            loose / f"{name}.rst",
            f"""
            {name.title()}
            {"=" * len(name)}

            {name.upper()}_MARKER
        """,
        )

    listed = "\n           ".join(host_entries) if host_entries else ""
    _write(
        srcdir / "index.rst",
        f"""
        Host
        ====

        HOST_MARKER

        .. toctree::

           {listed}
    """,
    )
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
    **kwargs: Any,
):
    app = make_app(srcdir=confdir, builddir=builddir, freshenv=freshenv, **kwargs)
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
