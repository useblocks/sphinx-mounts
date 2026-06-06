.. _specs:

Specifications & traceability
=============================

This section is a lightweight, agile traceability model for sphinx-mounts,
authored with `Sphinx-Needs`_. It captures the extension's user-observable
**features**, the **component requirements** that decompose them, and the
**errors** (failure conditions) each feature guards against — together with
how every error is addressed (tested, runtime-checked, or mitigated) and how
each need traces to the source code that realises it.

The model is intentionally small. It follows the same agile shape useblocks
uses elsewhere (feature → component requirement) rather than a heavyweight
V-model, and adds an ``err`` type for failure conditions.

.. toctree::
   :maxdepth: 2

   features
   errors
   traceability
