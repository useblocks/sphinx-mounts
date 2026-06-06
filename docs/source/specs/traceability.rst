Traceability
============

The needs form a closed loop of *outgoing* links (each schema-validatable),
authored in three places: RST (``story``, ``feat``, ``err``, ``check``,
``restriction``), the package source (``impl``), and the test suite
(``test``). See :doc:`approach` for what each link means.

Need & link structure
----------------------

.. mermaid::

   flowchart LR
       test["test (TEST_)"]
       check["check (CHECK_)"]
       rest["restriction (REST_)"]
       err["err (ERR_)"]
       feat["feat (FEAT_)"]
       story["story (STORY_)"]
       impl["impl (IMPL_)"]

       test -->|prevents| err
       check -->|detects| err
       rest -->|avoids| err
       err -->|affects| feat
       feat -->|realizes| story
       impl -->|links| feat

Reading right to left: a **story** is realized by **features**; each feature
is implemented by **impl** code and can exhibit **errors**; each error is
treated by a **test** (prevention), a **check** (runtime detection), or a
**restriction** (usage constraint).

Agile spine
-----------

.. needtable:: Features and the story each realizes
   :types: feat
   :columns: id, title, realizes, source_doc
   :style: table

Errors and their treatment
--------------------------

.. needtable:: Errors and the feature they affect
   :types: err
   :columns: id, title, severity, affects
   :style: table

.. needtable:: Treatments — prevention (test) and mitigation (check / restriction)
   :types: test, check, restriction
   :columns: id, type, title, prevents, detects, avoids, status
   :style: table

Code & test traceability (sphinx-codelinks)
-------------------------------------------

``impl`` and ``test`` needs are authored as one-line `sphinx-codelinks`_ needs
in comments next to the code, discovered at build time (configured under the
``[codelinks]`` table in ``ubproject.toml``, which ubCode reads too). One
``src-trace`` directive per project renders them.

Implementation needs (``src/``) — each ``:links:`` the feature it implements:

.. src-trace::
   :project: sphinx_mounts

.. needtable:: Implementation needs and the feature each links to
   :types: impl
   :columns: id, title, links, status
   :style: table

Test needs (``tests/``) — each ``:prevents:`` the error it structurally rules
out:

.. src-trace::
   :project: sphinx_mounts_tests

.. needtable:: Test needs and the error each prevents
   :types: test
   :columns: id, title, prevents, status
   :style: table

.. note:: Backlink coverage is not yet schema-validatable (sphinx-needs #1590)

   Every edge above is an *outgoing* link, which IS schema-validatable. What
   we cannot yet express is the *incoming* rule — e.g. "every ``feat`` must
   have at least one ``impl`` linking to it" or "every ``err`` must have at
   least one treatment (``test`` / ``check`` / ``restriction``)." sphinx-needs
   schema validation currently constrains a need's own fields and its
   **outgoing** links only, not its **incoming** links / backlinks.

   Enforcing that via schema validation would be the canonical, declarative
   approach. It is tracked upstream at
   `sphinx-needs#1590 <https://github.com/useblocks/sphinx-needs/issues/1590>`__.
