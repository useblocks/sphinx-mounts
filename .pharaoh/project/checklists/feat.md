---
name: Feature review checklist
applies_to: feat
axes:
  - clarity
  - traceability
---

# Feature review checklist

- [ ] ID matches `id_regex` (`^(FEAT|CREQ|ERR|IMPL|TEST)_[A-Z0-9_]*[0-9]{3}$`).
- [ ] Title names a single user-observable capability (not an implementation detail).
- [ ] Status is one of `open`, `in_progress`, `implemented`.
- [ ] Body describes the capability in user terms (what, when, for whom).
- [ ] `:source_doc:` names the implementing source file(s) (forward trace).
- [ ] At least one code-authored `impl` need `:links:` this feature
      (reverse trace — advisory; see traceability.rst and SN #1590).
- [ ] At least one `comp_req` `:satisfies:` this feature.
- [ ] No semantic overlap with another feature.
