"""Typed-warning helpers for sphinx-mounts.

Every warning this extension emits carries a ``type`` that starts with
``mounts_`` so users can identify it as coming from sphinx-mounts and
selectively suppress it via Sphinx's ``suppress_warnings`` config:

.. code-block:: python

   suppress_warnings = [
       "mounts_docname_conflict",   # one specific problem
       "mounts_mount_at_occupied",
   ]

Sphinx matches warning types exactly (``type``, ``type.*``, or
``type.subtype``), so the plain ``mounts_<topic>`` tokens used here are
suppressed by naming them verbatim. Non-suppressed warnings are counted
by Sphinx and escalate to a failed build under ``sphinx-build -W``
(``warningiserror``), which is how users turn "soft" mount problems into
hard build failures when they want to.

Config *validation* errors (malformed TOML, wrong types, unknown keys)
deliberately stay hard ``ExtensionError`` failures instead of warnings —
sphinx-mounts cannot proceed at all when the configuration is unreadable,
and such errors must not be suppressible.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from sphinx import version_info

if TYPE_CHECKING:
    from sphinx.util.logging import SphinxLoggerAdapter

#: Warning topics known to sphinx-mounts. Keep sorted — adding a new
#: topic should be a visible, reviewable diff.
WarningTopics = Literal[
    "attach_to_missing",
    "docname_conflict",
    "missing_path",
    "mount_at_occupied",
    "path_escape",
    "toctree_index",
    "unknown_suffix",
]

#: One-line description per topic; feeds the documentation.
WARNING_TOPIC_DESCRIPTIONS: dict[WarningTopics, str] = {
    "attach_to_missing": "attach_to references a docname that does not exist",
    "docname_conflict": "a mount would shadow a docname already provided by "
    "the host project or an earlier mount",
    "missing_path": "a configured dir/files path does not exist on disk",
    "mount_at_occupied": "strict_mount_at is set and the host already has a "
    "directory at the mount point",
    "path_escape": "a mounted doc references a file outside its bundle root",
    "toctree_index": "toctree_index exceeds the number of toctrees in the "
    "attach_to document",
    "unknown_suffix": "a file-list entry has no extension registered in source_suffix",
}


def log_warning(
    logger: SphinxLoggerAdapter,
    message: str,
    topic: WarningTopics,
    *,
    location: str | None = None,
) -> None:
    """Emit a typed sphinx-mounts warning.

    The full warning type is ``mounts_<topic>`` — the string users put
    into ``suppress_warnings``. Sphinx < 8 does not display warning types
    by default, so the type is appended to the message there to keep the
    console output self-explanatory on all supported versions.

    :param logger: The module logger to emit through.
    :param message: The warning text (already including the
        ``sphinx-mounts:`` prefix where appropriate).
    :param topic: One of the registered :data:`WarningTopics`.
    :param location: Optional docname (or ``docname:lineno``) the warning
        belongs to.
    """
    warning_type = f"mounts_{topic}"
    if version_info < (8,):
        message = f"{message} [{warning_type}]"
    logger.warning(message, type=warning_type, location=location)
