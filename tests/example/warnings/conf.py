"""Minimal host project for the sphinx-mounts warning showcase.

Every mount declaration lives in ``ubproject.toml`` next to this file and
is commented out: uncomment one ``[[mounts]]`` block at a time and rebuild
to see the warning it triggers.
"""

project = "sphinx-mounts warnings"
author = "useblocks"
extensions = ["sphinx_mounts"]
# The demo bundles live inside the srcdir for self-containment; exclude
# them (and the checked-in mount-point dir) from host discovery so the
# default build — all [[mounts]] blocks commented out — is completely
# clean. Mounts read their sources directly, unaffected by these patterns.
exclude_patterns: list[str] = ["_build", "bundles", "_generated"]
master_doc = "index"
