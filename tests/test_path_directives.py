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
