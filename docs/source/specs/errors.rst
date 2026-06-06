Errors
======

Each **error** (``err``) is a potential tool error that ``:affects:`` one or
more features. Every error is *treated* by **prevention** (a ``test`` that
proves it cannot occur) or **mitigation** (a ``check`` that detects it, or a
``restriction`` that avoids it) — see :doc:`approach`. ``:severity:`` records
the impact if the error were hit unguarded.

Prevented by a test
-------------------

.. err:: Mounted docname collides with an existing document
   :id: ERR_COLLISION_001
   :status: implemented
   :affects: FEAT_DIRMOUNT_001, FEAT_FILEMOUNT_001
   :severity: high
   :source_doc: src/sphinx_mounts/mounter.py

   Two mounts — or a mount and a host document — can produce the same
   docname, which would silently shadow content. Registration raises
   ``ValueError`` naming both contributors. Prevented structurally by
   ``TEST_COLLISION_001``.

.. err:: File-list entry has an unregistered suffix
   :id: ERR_BADSUFFIX_001
   :status: implemented
   :affects: FEAT_FILEMOUNT_001
   :severity: medium
   :source_doc: src/sphinx_mounts/mounter.py

   In file-list mode a file whose suffix is not one of the project's
   ``source_suffix`` values cannot become a docname. The extension raises
   ``ValueError`` rather than mounting it silently. Prevented structurally by
   ``TEST_BADSUFFIX_001``.

.. err:: toctree_index out of range for the host document
   :id: ERR_TOCIDX_001
   :status: implemented
   :affects: FEAT_TOCWIRE_001
   :severity: medium
   :source_doc: src/sphinx_mounts/extension.py

   A mount can request a ``toctree_index`` larger than the number of toctrees
   present in the host document. The extension raises ``ExtensionError``
   rather than leaving the mount unreferenced. Prevented structurally by
   ``TEST_TOCIDX_001``.

Mitigated by a check
--------------------

.. err:: A configured mount contributes zero documents
   :id: ERR_EMPTYMOUNT_001
   :status: implemented
   :affects: FEAT_DIRMOUNT_001
   :severity: medium
   :source_doc: src/sphinx_mounts/mounter.py

   A mount can resolve to nothing — a mistyped ``dir``, or a parent
   ``.gitignore`` that hides every file — and the build still succeeds, just
   without the expected pages. This cannot be ruled out structurally (an
   empty directory is legal), so it is detected at runtime by
   ``CHECK_MOUNTCOUNT_001``.

Avoided by a restriction
------------------------

.. err:: Mounted path exceeds the Windows MAX_PATH limit
   :id: ERR_LONGPATH_001
   :status: implemented
   :affects: FEAT_DIRMOUNT_001
   :severity: medium
   :source_doc: src/sphinx_mounts/mounter.py

   A deep mounted tree can produce absolute paths longer than the Windows
   ``MAX_PATH`` (260-character) limit, which fails the read. The condition is
   environmental, not structural, so it is avoided by ``REST_WINPATH_001``
   rather than prevented in code.
