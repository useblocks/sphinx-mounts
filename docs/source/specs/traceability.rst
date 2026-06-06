Traceability
============

The needs in this section form a small, closed traceability loop. Every edge
is an *outgoing* link (so it is schema-validatable), and the nodes are
authored in three places: RST (``feat``, ``comp_req``, ``err``), the package
source (``impl``), and the test suite (``test``).

Need & link structure
----------------------

.. mermaid::

   flowchart LR
       test["test (TEST_)"]
       creq["comp_req (CREQ_)"]
       feat["feat (FEAT_)"]
       err["err (ERR_)"]
       impl["impl (IMPL_)"]

       test -->|verifies| creq
       test -.->|detects| err
       creq -->|satisfies| feat
       impl -->|links| feat
       err -->|tested_in| feat
       err -->|checked_in| feat
       err -->|mitigated_in| feat

Solid edges are always present for that need type; the dotted ``detects`` edge
is optional — only tests that exercise an error carry it. ``feat`` is the hub:
``comp_req``, ``impl``, and ``err`` all point at it, and ``test`` points at
``comp_req`` / ``err``.

Forward trace — need → code
---------------------------

Every ``feat``, ``comp_req``, and ``err`` carries a ``:source_doc:`` field
naming the source file that realises it. This direction is part of each
need's own data, so it is **schema-validatable**: a project can require, via
sphinx-needs schema validation, that (say) every ``comp_req`` set a
non-empty ``source_doc``.

.. needtable:: Features and the source that implements them
   :types: feat
   :columns: id, title, source_doc, status
   :style: table

.. needtable:: Errors, how they are handled, and where
   :types: err
   :columns: id, title, severity, tested_in, checked_in, mitigated_in
   :style: table

Reverse trace — code → needs
----------------------------

Both ``impl`` and ``test`` needs are authored as `sphinx-codelinks`_
**one-line needs** in comments next to the code, and discovered at build time
(configured under the ``[codelinks]`` table in ``ubproject.toml``, which
ubCode reads as well). One ``src-trace`` directive per project renders them.

Implementation needs (``src/``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Each ``impl`` need ``:links:`` the feature it implements:

.. src-trace::
   :project: sphinx_mounts

- ``src/sphinx_mounts/mounter.py`` → :need:`IMPL_DIRMOUNT_001`,
  :need:`IMPL_FILEMOUNT_001`
- ``src/sphinx_mounts/config.py`` → :need:`IMPL_TOMLCONF_001`
- ``src/sphinx_mounts/extension.py`` → :need:`IMPL_TOCWIRE_001`

.. needtable:: Implementation needs and the feature each links to
   :types: impl
   :columns: id, title, links, status
   :style: table

Test needs (``tests/``)
~~~~~~~~~~~~~~~~~~~~~~~~~

Each ``test`` need ``:verifies:`` the component requirement(s) it covers and,
where it exercises a failure condition, ``:detects:`` the error (ISO 26262-8
Part 8 fault detection):

.. src-trace::
   :project: sphinx_mounts_tests

.. needtable:: Test needs, the requirements they verify, and errors they detect
   :types: test
   :columns: id, title, verifies, detects, status
   :style: table

A successful build logs ``Oneline needs extracted: N`` (N ≥ 1) for each of the
two projects, confirming the source and test trees define needs linked into
the catalogue.

.. note:: Backlink coverage is not yet schema-validatable (sphinx-needs #1590)

   Every edge above is an *outgoing* link (``impl → feat``, ``test →
   comp_req``/``err``), which IS schema-validatable. What we cannot yet express
   is the *inverse*, incoming rule — e.g. "every ``feat`` must have at least
   one ``impl`` linking to it" or "every ``comp_req`` must be verified by at
   least one ``test``." sphinx-needs schema validation currently constrains a
   need's own fields and its **outgoing** links only; it cannot assert anything
   about a need's **incoming** links / backlinks.

   Enforcing that via schema validation would be the canonical, declarative
   approach — far better than an advisory check. It is tracked upstream at
   `sphinx-needs#1590 <https://github.com/useblocks/sphinx-needs/issues/1590>`__.
