Errors
======

Each **error** (``err``) is a failure condition tied to one or more
features. The link relation records *how* the error is addressed:

- ``:checked_in:`` — a **runtime check** in the feature detects the
  condition and fails loudly (raises), so it cannot corrupt the output.
- ``:mitigated_in:`` — the feature **tolerates** the condition by design
  (e.g. emits a warning and continues) instead of failing.
- ``:tested_in:`` — correctness rests on **test coverage**; there is no
  dedicated runtime guard or graceful fallback for the condition.

An error may carry more than one relation (e.g. both runtime-checked and
tested). ``:severity:`` records the impact if the condition were hit
unguarded. Where a test exercises the condition, a ``test`` need
``:detects:`` this error (see :doc:`traceability`).

.. err:: Mounted docname collides with an existing document
   :id: ERR_COLLISION_001
   :status: implemented
   :checked_in: FEAT_DIRMOUNT_001, FEAT_FILEMOUNT_001
   :severity: high
   :source_doc: src/sphinx_mounts/mounter.py

   Two mounts — or a mount and a host document — can produce the same
   docname, which would silently shadow content. Registration detects the
   collision and raises ``ValueError`` naming both contributors, so the
   build fails loudly instead of dropping a document.

.. err:: attach_to targets a non-existent host document
   :id: ERR_DEADATTACH_001
   :status: implemented
   :mitigated_in: FEAT_TOCWIRE_001
   :severity: low
   :source_doc: src/sphinx_mounts/extension.py

   If ``attach_to`` names a docname that does not exist there is nothing to
   wire. Rather than fail the build, the consistency check emits a warning
   and continues — the misconfiguration is surfaced without blocking
   unrelated output. This is a deliberate mitigation, not a runtime guard.

.. err:: Incremental build serves a stale mounted document
   :id: ERR_STALEMOUNT_001
   :status: implemented
   :tested_in: FEAT_DIRMOUNT_001
   :severity: medium
   :source_doc: src/sphinx_mounts/mounter.py

   On an incremental rebuild a changed mounted file must be re-read, and an
   unchanged one must not trigger needless work. There is no runtime
   assertion for this property; its correctness rests on the incremental
   test cases that exercise both directions.

.. err:: toctree_index out of range for the host document
   :id: ERR_TOCIDX_001
   :status: implemented
   :checked_in: FEAT_TOCWIRE_001
   :tested_in: FEAT_TOCWIRE_001
   :severity: medium
   :source_doc: src/sphinx_mounts/extension.py

   A mount can request a ``toctree_index`` larger than the number of
   toctrees present in the host document. Rather than silently leave the
   mount unreferenced, the extension raises ``ExtensionError``. The
   behaviour is both runtime-checked and covered by a test — an example of
   an error carrying more than one handling relation.
