Features
========

Each **feature** (``feat``) is a user-observable capability that
``:realizes:`` a user story. ``:source_doc:`` is the forward trace to the
implementing source; an ``impl`` one-line need in that source carries the
reverse trace (see :doc:`traceability`). The errors each feature can exhibit
are in :doc:`errors`.

.. feat:: Directory mounting
   :id: FEAT_DIRMOUNT_001
   :status: implemented
   :realizes: STORY_MOUNT_001
   :source_doc: src/sphinx_mounts/mounter.py

   sphinx-mounts mounts an external directory into the host Sphinx project.
   Every file under the directory whose extension matches the project's
   configured ``source_suffix`` is registered as a document at the
   ``mount_at`` prefix, with its path relative to the directory (minus the
   matched suffix) as the docname tail. Sources are read in place — never
   copied or symlinked.

.. feat:: File-list mounting
   :id: FEAT_FILEMOUNT_001
   :status: implemented
   :realizes: STORY_MOUNT_001
   :source_doc: src/sphinx_mounts/mounter.py

   sphinx-mounts mounts an explicit list of individual files. Each file's
   basename (minus the matched suffix) becomes a docname under ``mount_at``,
   forming a flat namespace; subdirectories in the file paths are ignored.

.. feat:: Declarative TOML configuration
   :id: FEAT_TOMLCONF_001
   :status: implemented
   :realizes: STORY_DECLARE_001
   :source_doc: src/sphinx_mounts/config.py

   Mount entries can be declared in ``ubproject.toml`` as a top-level
   ``[[mounts]]`` array, so non-Python tooling (ubCode, IDEs, CI gates) can
   read the configuration without evaluating ``conf.py``. The TOML list
   replaces any ``mounts`` value set in ``conf.py``.

.. feat:: Automatic toctree wiring
   :id: FEAT_TOCWIRE_001
   :status: implemented
   :realizes: STORY_MOUNT_001
   :source_doc: src/sphinx_mounts/extension.py

   A mount can request that its entry document be wired into a host
   document's toctree via ``attach_to``. sphinx-mounts appends the entry to
   the selected toctree (``toctree_index``), or creates a new toctree
   beneath the first section when the host document has none.
