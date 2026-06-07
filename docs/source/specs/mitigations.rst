Mitigations
===========

For errors that cannot be ruled out structurally by a test, a **check**
detects them at runtime or a **restriction** avoids them by constraining how
the tool is used. (Prevention via tests lives next to the tests — see
:doc:`traceability`.)

Checks
------

A **check** (``check``) ``:detects:`` an error: an external, runtime
verification — usually a CI step — that fails if the error appears.

.. check:: CI asserts every mount contributed documents
   :id: CHECK_MOUNTCOUNT_001
   :status: in_progress
   :detects: ERR_EMPTYMOUNT_001

   A CI step parses the build's ``needs.json`` / output and fails if any
   configured mount contributed zero documents, catching a mount that
   silently resolved to nothing (wrong path, parent ``.gitignore``).

Restrictions
------------

A **restriction** (``restriction``) ``:avoids:`` an error by removing its
precondition — a documented constraint on how the tool may be used.

.. restriction:: Enable long-path support, or avoid Windows, for deep mounts
   :id: REST_WINPATH_001
   :status: implemented
   :avoids: ERR_LONGPATH_001

   When mounted document paths can exceed the Windows ``MAX_PATH``
   (260-character) limit, the project must either enable long-path support
   (``LongPathsEnabled``) or run the build on a platform without the limit.
   This removes the precondition for the error instead of detecting it after
   the fact.
