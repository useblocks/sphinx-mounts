User stories
============

The agile demand side: what users want from sphinx-mounts. Each feature
``:realizes:`` one of these stories.

.. story:: Mount external sources in place
   :id: STORY_MOUNT_001
   :status: implemented

   As a documentation author, I want to include external source trees in my
   Sphinx build without copying or symlinking them, so that generated or
   sibling documentation renders in the same site and stays in sync with its
   source.

.. story:: Declare mounts once for the whole toolchain
   :id: STORY_DECLARE_001
   :status: implemented

   As a user of the useblocks documentation stack, I want mounts declared in
   ``ubproject.toml``, so that ubCode, IDEs, and CI read the same mount
   configuration without executing ``conf.py``.
