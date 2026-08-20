# The mount mapping contract

This document is the **normative** specification of how sphinx-mounts turns a
`ubproject.toml` mount declaration into a set of `(docname, absolute path)` pairs,
and of every rule that decides what happens when two things want the same docname.

It exists because "declarative TOML so any language can read the mapping" is only
a real promise if the mapping is written down.
Without it, a second implementation — an editor plugin, a language server,
an indexer, a build-system integration — has to infer the rules from prose
scattered across the user documentation, and will diverge on exactly the
under-specified points: suffix matching order, path resolution, pattern dialect,
tie-breaks.
Those divergences surface to a user as "the editor shows a page the build does not"
(or the reverse), which is worse than either behaviour alone.

Audience: implementers of a second reader.
End users should read [`docs/source/configuration.rst`](../docs/source/configuration.rst),
which links here for the precise rules.

Status: describes the implementation as it is, not as it might become.
When behaviour changes, this document changes in the same commit.

## 1. Where the mounts array lives

The array of tables may be declared in either of two locations:

| Location | Status |
| --- | --- |
| `[[source.mounts]]` | Recommended. `[source]` owns source discovery in the shared `ubproject.toml` vocabulary. |
| `[[mounts]]` (top level) | Original spelling. Fully supported, not deprecated. |

Rules:

1. Exactly one location may be **declared** in a file.
   Declaring both is a hard configuration error (`TomlConfigError`) naming both
   locations.
   A reader must not pick a winner or merge the two: the effective mount list
   would then depend on a precedence rule invisible to anyone reading the file.
2. "Declared" means the key is present, including when its value is an empty array.
   `mounts = []` is a statement that the project has no mounts.
3. A `[source]` table that contains no `mounts` key is not a declaration.
4. A `source` key whose value is not a table is ignored entirely
   (another tool may own that name for something else).
5. Nesting under `[source]` implies **no inheritance**.
   A mount does not read, default from, or otherwise consult any other `[source]` key.
   See §5 on why this matters for `include` / `exclude` specifically.

Both spellings are identical in every other respect covered by this document.
Where the rest of this document says "the mounts array", it means whichever one
was declared.

## 2. Config precedence: TOML versus `conf.py`

A mount list may also come from a `mounts = [...]` value in `conf.py` (the legacy path).
The rule is about *declaration*, not about file existence:

| Situation | Effective mount list |
| --- | --- |
| TOML declares a mounts array | the TOML's |
| TOML declares an empty array | empty — `conf.py` is overridden |
| TOML exists but declares no mounts key | `conf.py`'s |
| TOML file absent | `conf.py`'s |
| `mounts_from_toml = None` in `conf.py` | `conf.py`'s (TOML is never read) |

The third row is load-bearing:
a `ubproject.toml` present only to configure *other* tools must never silently
switch a project's mounts off.

`mounts_from_toml` is documented as a path relative to `confdir`.
The implementation also accepts an absolute path, and a relative path may climb
above `confdir` with `..`; neither is rejected.
A second reader may reject them, but must not assume they cannot occur.

## 3. Path anchoring and resolution

Two separate steps, in this order.

**Step 1 — anchor.** A relative `dir` or `files` entry is made absolute against:

| Declared in | Anchor |
| --- | --- |
| `ubproject.toml` (either location) | the directory containing **the TOML file** |
| `conf.py` (legacy) | `confdir` |

Anchoring to the TOML's own directory — not to `confdir` — makes the file
self-describing: moving it as a unit keeps its relative paths meaningful,
and a TOML in a subdirectory of `confdir` does not silently re-anchor.

**Step 2 — resolve.** Every `dir` and every `files` entry is then resolved:
`..` segments collapsed and **symlinks followed**.
This applies to paths that were already absolute, too.
There is no opt-out.

Consequences a second implementation must reproduce or knowingly deviate from:

- Path confinement (§6) compares resolved paths on both sides.
  This is what makes a bundle reached through a symlinked directory work rather
  than being reported as an escape — the case that matters whenever a build
  system exposes its outputs through a symlink.
- Diagnostics name the **resolved** path, not the path the user wrote.
  A mount configured through a symlink is reported by its target.
- The resolved absolute paths are what reach Sphinx as the `mounts` config value,
  so **relocating the checkout changes that value** and invalidates the build
  environment even though nothing semantic changed.
  This is the same mechanism that makes an edit to `ubproject.toml` correctly
  invalidate the cache, so it is a deliberate trade.
  Comment-only edits change nothing.

Existence is **not** part of resolution.
A path that resolves but is not on disk is not a configuration error;
it is reported later, during discovery, as `mounts.missing_path` (§7).
A build whose upstream bundle has not been produced yet still runs.

## 4. Per-key reference

One table is one mount entry.
Unknown keys are rejected (hard error).
Exactly one of `dir` / `files` must be present.

| Key | Type | Default | Meaning and constraints |
| --- | --- | --- | --- |
| `mount_at` | string \| absent | absent | Docname prefix. Must be relative: no leading `/`, no `..` component. Surrounding slashes are stripped. Absent means the bundle mounts at the project root, so a bundle file `tutorial.rst` becomes the docname `tutorial`. |
| `dir` | string | — | **Directory mode.** Root of a tree to walk. Mutually exclusive with `files`. |
| `files` | array of strings | — | **File-list mode.** Explicit files, at least one. Mutually exclusive with `dir`. |
| `include` | array of strings | `[]` | Allowlist patterns, directory mode only. See §5. |
| `exclude` | array of strings | `[]` | Denylist patterns, directory mode only. See §5. |
| `gitignore` | bool | `true` | Honour `.gitignore` / `.ignore` files **inside** the walked tree. Directory mode only. See §5. |
| `attach_to` | string \| absent | absent | Docname whose toctree receives this mount's entries. Same shape constraints as `mount_at`. May name a *mounted* docname, not just a host one (§8). |
| `toctree_index` | non-negative int | `0` | Which toctree inside `attach_to`, in document order. Booleans are rejected even though `bool` is an `int` in Python. |
| `entry_doc` | string | `"index"` | Mount-relative docname to wire. Same shape constraints as `mount_at`. |
| `attach_each` | bool | `false` | Wire *every* file instead of `entry_doc`. Requires `files` **and** `attach_to`, and is mutually exclusive with a non-default `entry_doc`. |
| `strict_mount_at` | bool | `false` | Skip the mount if the host srcdir already has a directory at `mount_at`. Requires an explicit `mount_at`. |
| `path_check` | `"error"` \| `"warn"` \| `"off"` | `"error"` | Reaction to a reference that escapes the bundle root (§6). |

## 5. Discovery: which files a mount contributes

### 5.1 Directory mode

The tree under `dir` is walked with the Rust `ignore` crate (via `ignore-python`).
The walk policy is fixed:

| Setting | Value | Why it is not configurable |
| --- | --- | --- |
| ignore files inside the tree | per-mount `gitignore` (default on) | Only takes effect when the tree is itself a git repository, per the crate's contract. |
| ignore files in **parent** directories | never consulted | A mount often lives under a path the host workspace gitignores (a build-output directory). Honouring parents would silently produce zero files. |
| global git config, `.git/info/exclude` | never consulted | Builds must not depend on a developer's machine. |
| hidden entries (dotfiles, dot-directories) | skipped | |

Only files whose name ends with a registered source suffix are kept (§5.3).

### 5.2 File-list mode

No walk. Each listed file is taken as given, and:

- a listed file that does not exist skips the **whole mount**
  (`mounts.missing_path`);
- a listed file with no registered suffix skips the **whole mount**
  (`mounts.unknown_suffix`) — the user named the file explicitly, so ignoring it
  silently would be wrong;
- a listed file whose name is *nothing but* a suffix (a file called `.rst`) has no
  docname and skips the **whole mount** (`mounts.empty_docname`).

Because there is no walker, there is no hidden-entry rule:
a listed dotfile such as `.hidden.rst` **is** mounted, as the docname tail
`.hidden`.
This is the one place the two modes disagree, and it is deliberate — file-list
mode is an explicit request for named files.
A second reader must reproduce the asymmetry:

| Mode | `.hidden.rst` in the mount | Result |
| --- | --- | --- |
| directory | present on disk | skipped (hidden) |
| file-list | listed | mounted as `<mount_at>/.hidden` |

### 5.3 Pattern dialect

`include` and `exclude` are **gitignore-style patterns**, evaluated relative to
`dir`, and fed to the `ignore` crate's override builder:
every `include` pattern is added as a positive override, then every `exclude`
pattern is added as a negated one (`!pattern`).

The crate's semantics are **last match wins**.
Because all includes are added before all excludes, that yields one rule worth
stating explicitly, since the gitignore intuition ("more specific wins") points
the other way:

> A broad `exclude` always beats a narrow `include`, regardless of the order the
> keys appear in the TOML.

So `include = ["keep.rst"]` with `exclude = ["**/*.rst"]` mounts **nothing**.

**These keys are not the same dialect as a same-named key elsewhere in the file.**
`[source].include` / `[source].exclude`, as used by ubCode, are globset globs with
their own default sets, and ubCode additionally path-expands them.
A mount's `include` / `exclude` are gitignore-style override patterns scoped to
that mount's `dir`, with no defaults and no expansion.
Nesting the mounts array under `[source]` (§1) puts two same-named keys with
different dialects one level apart; it changes nothing about either.
A second implementation must not share a pattern compiler between the two without
first making them the same dialect deliberately.

## 6. Docname derivation

A docname is `mount_at` joined to a *tail* with a single `/`
(or the bare tail when `mount_at` is absent).

The tail is the file's path with **one** matched source suffix removed:

| Mode | Tail |
| --- | --- |
| directory | the file's path relative to `dir` (POSIX separators), suffix removed — directory structure preserved |
| file-list | the file's **basename**, suffix removed — directories discarded, flat namespace |

The suffix removed is the **first** entry of Sphinx's `source_suffix` that the
filename ends with, iterating in registration order.
It is **not** the longest match.

This is exactly what Sphinx core does for files in the host source directory,
so mounted and host files derive docnames identically — but it means overlapping
suffixes are order-sensitive:

| `source_suffix` order | file | docname tail |
| --- | --- | --- |
| `.rst`, `.txt`, `.rst.txt` | `a.rst.txt` | `a.rst` (`.txt` matched first) |
| `.rst`, `.rst.txt`, `.txt` | `a.rst.txt` | `a` |

A second implementation must iterate the *host project's registered order*,
not a sorted or longest-first order.
Where it cannot observe that order, it must say so rather than guess.

Enumeration order of a mount's entries is deterministic and is part of the
contract, because it decides which entry is reported first in a conflict and the
order `attach_each` wires files:

- directory mode: sorted by the file's absolute POSIX path;
- file-list mode: the order of the `files` array.

## 7. Tie-breaks and failure modes

The whole-mount skip is the single reaction to every mount-level problem.
When a mount is skipped, **none** of its files are registered — not just the
offending one.
This is deliberate: a partially mounted bundle leaves its siblings dangling and
can wire broken toctrees, i.e. it modifies the host project despite the problem.

Collision rules, in the order they are evaluated for each candidate docname:

1. **Host wins.** A docname the host source directory already provides is not
   taken over. The mount is skipped (`mounts.docname_conflict`).
2. **First mount wins.** A docname an *earlier* mount in the array already
   provides is not taken over. The later mount is skipped
   (`mounts.docname_conflict`).
3. **Intra-mount collisions are an error, not a last-one-wins.** Two files of the
   same mount that map to one docname skip the mount
   (`mounts.docname_conflict`, naming both contributing paths).
   This happens in both modes: two listed files sharing a basename (file-list mode
   is flat), or two files differing only in registered suffix such as `index.rst`
   beside `index.md`.
   A second implementation must not resolve this by order.

"Earlier" and "later" in rule 2 mean position in the mounts array.
Declaration order therefore matters for conflicts, and only for conflicts —
toctree wiring does not depend on it (§8).

Other whole-mount skips: `mounts.missing_path`, `mounts.unknown_suffix`,
`mounts.empty_docname`, `mounts.mount_at_occupied`.

### 7.1 Warning subtypes are a stable contract

Every diagnostic carries the Sphinx warning type `mounts` with a per-problem
subtype, so it can be suppressed at either granularity and mapped onto another
tool's diagnostic codes.
**This list is stable.** Subtypes may be added; existing ones will not be renamed
or repurposed without a breaking release.

| Subtype | Condition | Effect |
| --- | --- | --- |
| `mounts.attach_to_missing` | `attach_to` names a docname that does not exist | nothing wired |
| `mounts.docname_conflict` | collision per rules 1-3 above | whole mount skipped |
| `mounts.empty_docname` | a listed file's name is only a suffix | whole mount skipped |
| `mounts.missing_path` | `dir` or a listed file is not on disk | whole mount skipped |
| `mounts.mount_at_occupied` | `strict_mount_at` set, host has a directory at `mount_at` | whole mount skipped |
| `mounts.path_escape` | a reference leaves the bundle root, `path_check = "warn"` | reported only |
| `mounts.toctree_index` | `toctree_index` exceeds the toctrees present | mount left unwired, its docs marked orphan |
| `mounts.unknown_suffix` | a listed file has no registered suffix | whole mount skipped |

Configuration problems — malformed TOML, wrong types, unknown keys, contradictory
options, both mount locations declared — are **not** in this list.
They are hard errors and are deliberately not suppressible.

## 8. Toctree wiring (`attach_to`)

`attach_to` names a docname whose toctree receives this mount's entries.

- The entries wired are `<mount_at>/<entry_doc>` — or every docname the mount
  produced, in enumeration order, when `attach_each` is set.
- Entries are **gated on what the mount actually produced**. A skipped or absent
  mount wires nothing, so it cannot leave a dangling reference behind.
- `toctree_index` selects which toctree, in document order. If the target document
  has no toctree at all, one is created at the **end of its first top-level
  section** — after everything the author wrote. If the index exceeds the number of
  toctrees present, nothing is wired (`mounts.toctree_index`) and the mount's docs
  are marked as orphans so the single warning is not joined by one per file.
- Wiring is **idempotent**: an entry the author already listed by hand is not
  added twice.
- `attach_to` may name a **mounted** docname, so one mount can be wired into
  another mount's toctree. Declaration order does not matter for this, because the
  injection happens while each document is read, not while the config is parsed.
- Wiring **tracks appearance and disappearance across incremental builds**.
  The set of entries each mount would wire is compared against a signature
  persisted on the build environment, and the `attach_to` document is re-read when
  they differ. Both directions converge on the build where the change happened,
  without a full rebuild.

## 9. Path confinement (`path_check`)

Each mount has a **root set**, shared by every document it provides:

| Mode | Root set |
| --- | --- |
| directory | exactly one root: the resolved `dir` |
| file-list | one root per entry in `files`: that entry's resolved parent directory (duplicates collapsed, `files` order preserved) |

A dependency is inside the bundle iff it is under — or equal to — **at least
one** root of its document's mount.
There is one check per mount, not one per document.

**The bound is normative, and it is bounded on both sides.**
Two other rules were implemented and are both wrong; a second reader must
implement neither.

- *One root per document* (each listed file confined to its own parent) makes
  the verdict depend on how deep a file happens to sit.
  With `rn/index.rst` and `rn/notes/2026-q1.rst` listed, the reference *down*
  from `index.rst` into `notes/` passes while the mirror-image reference *up*
  from `notes/2026-q1.rst` to `../shared.txt` is rejected — same mount, same
  tree, opposite verdicts.
- *The common ancestor of the listed parents* fixes that asymmetry but is
  unbounded in the other direction, because the `files` list itself drives the
  root.
  Two entries in sibling subtrees promote their shared parent to the root; two
  entries on unrelated filesystem branches promote `/`, at which point the
  check permits every file on the machine and emits nothing — including at the
  default `path_check = "error"`.

The union of the listed parents is a strict superset of the first rule (so the
asymmetry stays fixed) and a strict subset of the second (so no directory the
user did not name is ever admitted).
Listing files from unrelated trees widens the bundle by exactly those trees'
directories, and by nothing else.
There is no failure case to report: a set of one or more parents always exists,
so no diagnostic accompanies root computation.

Every file the document is recorded as depending on must resolve into that root
set.
The comparison is per path component, on both sides passed through the platform's
case normalisation, because resolving a path does not fold case and both macOS and
Windows are case-insensitive but case-preserving.
A second implementation on those platforms must fold too, or it will reject
legitimate references.

Three shapes escape:

1. a leading `/`, which means "absolute from the source root" and for a mounted
   document is the **host** source directory, not the bundle;
2. a `..` climb that lands outside every root in the set;
3. a symlink inside the bundle whose target is outside it — the written path looks
   local, and only its resolved form reveals the escape.

Two limits are inherent to running this check after the read phase, and any
second implementation should state its own position rather than inherit these
silently:

- **It detects; it does not prevent.** The offending document has already been
  read and parsed, and its parsed form persisted, before the check runs. What
  `"error"` prevents is the *output*: no escaped asset is copied and no page is
  written.
- **It is not evaluated on a build that reads no document.** Sphinx runs its
  consistency checks only when at least one document was read, so an unchanged
  re-run skips them. `path_check` is a gate on builds that do work, not a standing
  invariant.

`path_check` says nothing about collisions *inside* the output: two bundles that
both ship `diagram.png` get one unsuffixed and one numbered asset name, and which
is which depends on document read order, hence on docnames. Adding or renaming a
mount can therefore change an unrelated page's asset URL. That naming is Sphinx's,
not this extension's.

## 10. What this contract does not cover

- The rendering of documents. sphinx-mounts does not parse anything; it only
  decides which docnames exist and where their bytes live.
- Anything about `[source]` other than a nested `mounts` array (§1).
- A machine-readable schema. The key table in §4 is currently the only
  specification of types and defaults besides the implementation's own validator.
