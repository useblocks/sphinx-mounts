Features & component requirements
=================================

Each **feature** (``feat``) is a user-observable capability. Each
**component requirement** (``comp_req``) decomposes a feature into a
testable obligation and ``:satisfies:`` it. The ``:source_doc:`` field is
the forward trace to the implementing source file; each requirement is
verified by one or more ``test`` needs authored in the suite (see
:doc:`traceability`).

Directory mounting
------------------

.. feat:: Directory mounting
   :id: FEAT_DIRMOUNT_001
   :status: implemented
   :source_doc: src/sphinx_mounts/mounter.py

   sphinx-mounts mounts an external directory into the host Sphinx project.
   Every file under the directory whose extension matches the project's
   configured ``source_suffix`` is registered as a document at the
   ``mount_at`` prefix, with its path relative to the directory (minus the
   matched suffix) as the docname tail. Sources are read in place — never
   copied or symlinked.

.. comp_req:: Suffix-matching files under a mounted directory are discovered
   :id: CREQ_DIRMOUNT_001
   :status: implemented
   :satisfies: FEAT_DIRMOUNT_001
   :source_doc: src/sphinx_mounts/mounter.py

   In directory mode, discovery shall register, for every file under
   ``mount.dir`` whose name ends with one of ``project.source_suffix``, a
   docname formed by joining ``mount_at`` with the file's path relative to
   ``dir`` minus the matched suffix. Discovery order shall be deterministic
   (paths sorted) regardless of filesystem walk order.

File-list mounting
------------------

.. feat:: File-list mounting
   :id: FEAT_FILEMOUNT_001
   :status: implemented
   :source_doc: src/sphinx_mounts/mounter.py

   sphinx-mounts mounts an explicit list of individual files. Each file's
   basename (minus the matched suffix) becomes a docname under ``mount_at``,
   forming a flat namespace; subdirectories in the file paths are ignored.

.. comp_req:: File-list entries become flat-namespace docnames
   :id: CREQ_FILEMOUNT_001
   :status: implemented
   :satisfies: FEAT_FILEMOUNT_001
   :source_doc: src/sphinx_mounts/mounter.py

   In file-list mode, the extension shall register, for each path in
   ``mount.files``, a docname formed by joining ``mount_at`` with the file's
   basename minus the matched ``source_suffix``. A file whose suffix is not
   a registered source suffix shall be rejected with a clear error.

Declarative TOML configuration
------------------------------

.. feat:: Declarative TOML configuration
   :id: FEAT_TOMLCONF_001
   :status: implemented
   :source_doc: src/sphinx_mounts/config.py

   Mount entries can be declared in ``ubproject.toml`` as a top-level
   ``[[mounts]]`` array, so non-Python tooling (ubCode, IDEs, CI gates) can
   read the configuration without evaluating ``conf.py``. The TOML list
   replaces any ``mounts`` value set in ``conf.py``.

.. comp_req:: TOML paths are anchored to the TOML file's directory
   :id: CREQ_TOMLCONF_001
   :status: implemented
   :satisfies: FEAT_TOMLCONF_001
   :source_doc: src/sphinx_mounts/config.py

   Relative ``dir`` and ``files`` paths declared in the TOML file shall be
   anchored to the directory containing that TOML file (not to ``confdir``);
   absolute paths shall be left unchanged.

Automatic toctree wiring
------------------------

.. feat:: Automatic toctree wiring
   :id: FEAT_TOCWIRE_001
   :status: implemented
   :source_doc: src/sphinx_mounts/extension.py

   A mount can request that its entry document be wired into a host
   document's toctree via ``attach_to``. sphinx-mounts appends the entry to
   the selected toctree (``toctree_index``), or creates a new toctree
   beneath the first section when the host document has none.

.. comp_req:: attach_to wires the entry doc into the host toctree
   :id: CREQ_TOCWIRE_001
   :status: implemented
   :satisfies: FEAT_TOCWIRE_001
   :source_doc: src/sphinx_mounts/extension.py

   When a mount sets ``attach_to`` to an existing host docname, the
   extension shall append ``{mount_at}/{entry_doc}`` to the toctree at
   ``toctree_index`` in that document — creating a toctree if none exists —
   and shall be idempotent when the entry is already referenced.
