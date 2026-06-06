Approach
========

sphinx-mounts pairs **agile terminology** with the tool-error reasoning of
**ISO 26262-8 §11** ("Confidence in the use of software tools"). The agile
spine captures intent; the tool-error layer captures how the tool is kept
trustworthy.

Agile spine
-----------

- A **story** (``story``) is a user-facing demand — *"As a … I want … so
  that …"*.
- A **feature** (``feat``) ``:realizes:`` a story: a capability the extension
  provides.

Tool-error layer
----------------

Every feature can fail in specific ways. Each such failure is a **potential
tool error** (``err``) that ``:affects:`` the feature. In ISO 26262-8 §11
terms an error contributes to the tool's *impact*; the open question is
whether there is enough confidence that it will not silently corrupt the
output.

That confidence comes from **treating** every error in one of two ways:

**Prevention — the error cannot occur.**
   A **test** (``test``) ``:prevents:`` the error: it proves, structurally,
   that the condition is ruled out (e.g. a guard raises and a test asserts
   it). A prevented error cannot reach the output.

**Mitigation — the error can occur, but is contained.**
   For errors that cannot be ruled out structurally, one of:

   - a **check** (``check``) ``:detects:`` the error at runtime — typically a
     CI step that inspects the build log or output with another tool and
     fails if the error appears; or
   - a **restriction** (``restriction``) ``:avoids:`` the error by
     constraining how the tool may be used — e.g. *if long mount paths are
     required, enable long-path support or do not run on Windows*.

Mapping to ISO 26262-8 §11
--------------------------

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Concept
     - ISO 26262-8 §11 role
   * - ``err``
     - Potential tool error (input to Tool Impact, TI)
   * - ``test``
     - Prevention measure — the error is eliminated structurally
   * - ``check``
     - Tool-error **detection** measure (TD), at runtime / in CI
   * - ``restriction``
     - Constraint of use that removes the error's preconditions

A feature whose every error is prevented or mitigated carries a defensible
tool-confidence argument. :doc:`traceability` renders the full node/link
graph and the per-error treatment tables.

Code traceability
-----------------

Orthogonal to the error layer, an **impl** (``impl``) ``:links:`` the feature
it implements. Both ``impl`` and ``test`` are authored as one-line
`sphinx-codelinks`_ needs in the source and test trees, so each need lives
next to the code it represents.
