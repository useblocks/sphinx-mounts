"""File-referencing directives inside a mounted bundle resolve relative to
the bundle root; the build fails when a reference escapes that root.

Covers literalinclude, include, csv-table :file:, raw :file:, image,
figure, graphviz, uml, mermaid, plus the path_check enforcement. The tests
are renderer-independent: mermaid uses 'raw' output, and graphviz/uml are
asserted via the recorded dependency rather than the rendered image, so no
mmdc/java/dot binary is required.
"""

from __future__ import annotations

from pathlib import Path
import struct
from typing import TYPE_CHECKING
import zlib

import pytest

from tests.conftest import write_ubproject_toml

if TYPE_CHECKING:
    from sphinx.testing.util import SphinxTestApp


def _build(make_app, host: Path) -> SphinxTestApp:
    """Build the host project and return the app (for env/outdir/warnings)."""
    app = make_app(srcdir=host, freshenv=True)
    app.build()
    return app


def _resolved_deps(app: SphinxTestApp, docname: str) -> list[Path]:
    """Resolve every recorded dependency of ``docname`` to an absolute path."""
    srcdir = Path(app.srcdir)
    return [(srcdir / dep).resolve() for dep in app.env.dependencies.get(docname, ())]


def _replace_index_toctree(host: Path, *docnames: str) -> None:
    """Rewrite host index.rst with a toctree referencing the given docnames."""
    body = "Host project\n============\n\n.. toctree::\n   :maxdepth: 2\n\n"
    for d in docnames:
        body += f"   {d}\n"
    (host / "index.rst").write_text(body, encoding="utf-8")


def _add_extensions(host: Path, *exts: str) -> None:
    """Append extra extensions to the host conf.py extensions list."""
    conf = host / "conf.py"
    text = conf.read_text(encoding="utf-8")
    joined = ", ".join(f'"{e}"' for e in exts)
    conf.write_text(
        text.replace(
            'extensions = ["sphinx_mounts"]',
            f'extensions = ["sphinx_mounts", {joined}]',
        ),
        encoding="utf-8",
    )


def _append_conf(host: Path, line: str) -> None:
    """Append a single config line to the host conf.py."""
    conf = host / "conf.py"
    conf.write_text(conf.read_text(encoding="utf-8") + f"\n{line}\n", encoding="utf-8")


def _tiny_png() -> bytes:
    """A minimal 1x1 red PNG built with the stdlib (no Pillow dependency)."""

    def chunk(name: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + name
            + data
            + struct.pack(">I", zlib.crc32(name + data))
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(
        b"IEND", b""
    )


# ---------- Task 3: discovery records docname -> (root, path_check) ----------


def test_doc_roots_records_bundle_root_and_path_check(
    make_app, make_host_project, tmp_path
):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "index.rst").write_text("Bundle\n======\n", encoding="utf-8")

    host = make_host_project()
    write_ubproject_toml(host, [{"dir": str(bundle), "mount_at": "_g/api"}])
    _replace_index_toctree(host, "_g/api/index")

    app = _build(make_app, host)

    roots = app.env.project._doc_roots
    assert roots["_g/api/index"] == (bundle.resolve(), "error")


def test_doc_roots_files_mode_uses_file_parent_dir(
    make_app, make_host_project, tmp_path
):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "page.rst").write_text("Page\n====\n", encoding="utf-8")

    host = make_host_project()
    write_ubproject_toml(
        host,
        [{"files": [str(pkg / "page.rst")], "mount_at": "_g/api", "path_check": "warn"}],
    )
    _replace_index_toctree(host, "_g/api/page")

    app = _build(make_app, host)

    assert app.env.project._doc_roots["_g/api/page"] == (pkg.resolve(), "warn")


# ---------- Task 4: happy path — directives resolve inside the bundle ----------


TEXT_CASES = [
    pytest.param(
        ".. literalinclude:: snippet.py\n",
        "snippet.py",
        "SNIP_MARKER = 1\n",
        "SNIP_MARKER",
        id="literalinclude",
    ),
    pytest.param(
        ".. include:: inc.txt\n",
        "inc.txt",
        "Included\n--------\n\nINC_MARKER\n",
        "INC_MARKER",
        id="include",
    ),
    pytest.param(
        ".. csv-table::\n   :file: data.csv\n",
        "data.csv",
        "h1,h2\nCSV_MARKER,2\n",
        "CSV_MARKER",
        id="csv-table-file",
    ),
    pytest.param(
        ".. raw:: html\n   :file: snippet.html\n",
        "snippet.html",
        "<p>RAW_MARKER</p>\n",
        "RAW_MARKER",
        id="raw-file",
    ),
]


@pytest.mark.parametrize("directive_rst, target_name, target_content, marker", TEXT_CASES)
def test_text_directive_reads_file_from_bundle(
    make_app,
    make_host_project,
    tmp_path,
    directive_rst,
    target_name,
    target_content,
    marker,
):
    """A relative file reference resolves to the file inside the bundle, and
    the recorded dependency points there (not into the host srcdir).

    ``inc.txt`` / ``snippet.html`` / ``data.csv`` / ``snippet.py`` all have
    extensions outside ``source_suffix``, so they are not discovered as docs
    of their own — only referenced by the directive.
    """
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / target_name).write_text(target_content, encoding="utf-8")
    (bundle / "index.rst").write_text(
        f"Bundle\n======\n\n{directive_rst}", encoding="utf-8"
    )

    host = make_host_project()
    write_ubproject_toml(host, [{"dir": str(bundle), "mount_at": "_g/api"}])
    _replace_index_toctree(host, "_g/api/index")

    app = _build(make_app, host)

    html = (Path(app.outdir) / "_g" / "api" / "index.html").read_text(encoding="utf-8")
    assert marker in html
    assert (bundle / target_name).resolve() in _resolved_deps(app, "_g/api/index")


def test_literalinclude_prefers_bundle_over_host_decoy(
    make_app, make_host_project, tmp_path
):
    """With a same-named decoy in the host srcdir, the bundle's file wins —
    proving resolution is relative to the bundle, not the host srcdir."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "snippet.py").write_text("BUNDLE_REAL = 1\n", encoding="utf-8")
    (bundle / "index.rst").write_text(
        "Bundle\n======\n\n.. literalinclude:: snippet.py\n", encoding="utf-8"
    )

    host = make_host_project()
    # Decoy at the same relative name; .py is not a source suffix, so it is
    # not picked up as a doc.
    (host / "snippet.py").write_text("HOST_DECOY = 0\n", encoding="utf-8")
    write_ubproject_toml(host, [{"dir": str(bundle), "mount_at": "_g/api"}])
    _replace_index_toctree(host, "_g/api/index")

    app = _build(make_app, host)

    html = (Path(app.outdir) / "_g" / "api" / "index.html").read_text(encoding="utf-8")
    assert "BUNDLE_REAL" in html
    assert "HOST_DECOY" not in html


def test_image_and_figure_resolve_within_bundle(
    make_app, make_host_project, tmp_path
):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "pic.png").write_bytes(_tiny_png())
    (bundle / "index.rst").write_text(
        "Bundle\n======\n\n"
        ".. image:: pic.png\n\n"
        ".. figure:: pic.png\n\n"
        "   A caption.\n",
        encoding="utf-8",
    )

    host = make_host_project()
    write_ubproject_toml(host, [{"dir": str(bundle), "mount_at": "_g/api"}])
    _replace_index_toctree(host, "_g/api/index")

    app = _build(make_app, host)

    assert (bundle / "pic.png").resolve() in _resolved_deps(app, "_g/api/index")
    assert (Path(app.outdir) / "_images").is_dir()


def test_graphviz_file_resolves_within_bundle(make_app, make_host_project, tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "g.dot").write_text("digraph { A -> B }\n", encoding="utf-8")
    (bundle / "index.rst").write_text(
        "Bundle\n======\n\n.. graphviz:: g.dot\n", encoding="utf-8"
    )

    host = make_host_project()
    _add_extensions(host, "sphinx.ext.graphviz")
    write_ubproject_toml(host, [{"dir": str(bundle), "mount_at": "_g/api"}])
    _replace_index_toctree(host, "_g/api/index")

    app = _build(make_app, host)

    assert (bundle / "g.dot").resolve() in _resolved_deps(app, "_g/api/index")
    assert "not found" not in app._warning.getvalue()


def test_uml_file_resolves_within_bundle(make_app, make_host_project, tmp_path):
    pytest.importorskip("sphinxcontrib.plantuml")
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "d.puml").write_text("@startuml\nA -> B\n@enduml\n", encoding="utf-8")
    (bundle / "index.rst").write_text(
        "Bundle\n======\n\n.. uml:: d.puml\n", encoding="utf-8"
    )

    host = make_host_project()
    _add_extensions(host, "sphinxcontrib.plantuml")
    write_ubproject_toml(host, [{"dir": str(bundle), "mount_at": "_g/api"}])
    _replace_index_toctree(host, "_g/api/index")

    app = _build(make_app, host)

    assert (bundle / "d.puml").resolve() in _resolved_deps(app, "_g/api/index")
    assert "not found" not in app._warning.getvalue()


def test_mermaid_file_resolves_within_bundle(make_app, make_host_project, tmp_path):
    pytest.importorskip("sphinxcontrib.mermaid")
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "f.mmd").write_text("graph TD\n  A[MERMAID_MARKER]\n", encoding="utf-8"
    )
    (bundle / "index.rst").write_text(
        "Bundle\n======\n\n.. mermaid:: f.mmd\n", encoding="utf-8"
    )

    host = make_host_project()
    _add_extensions(host, "sphinxcontrib.mermaid")
    _append_conf(host, "mermaid_output_format = 'raw'")
    write_ubproject_toml(host, [{"dir": str(bundle), "mount_at": "_g/api"}])
    _replace_index_toctree(host, "_g/api/index")

    app = _build(make_app, host)

    assert (bundle / "f.mmd").resolve() in _resolved_deps(app, "_g/api/index")
    assert "not found" not in app._warning.getvalue()
    html = (Path(app.outdir) / "_g" / "api" / "index.html").read_text(encoding="utf-8")
    assert "MERMAID_MARKER" in html
