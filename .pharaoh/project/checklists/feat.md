---
name: Feature review checklist
applies_to: feat
axes:
  - clarity
  - traceability
---

# Feature review checklist

- [ ] ID matches `id_regex` (`^(STORY|FEAT|ERR|TEST|CHECK|REST|IMPL)_[A-Z0-9_]*[0-9]{3}$`).
- [ ] Title names a single user-observable capability (not an implementation detail).
- [ ] Status is one of `open`, `in_progress`, `implemented`.
- [ ] Body describes the capability in user terms (what, when, for whom).
- [ ] `:realizes:` points at the user story this feature delivers.
- [ ] `:source_doc:` names the implementing source file(s) (forward trace).
- [ ] At least one code-authored `impl` need `:links:` this feature
      (reverse trace — advisory; see traceability.rst and SN #1590).
- [ ] At least one `test` `:verifies:` this feature.
- [ ] The errors this feature can exhibit are captured as `err` needs that
      `:affects:` it, each with a treatment.
- [ ] No semantic overlap with another feature.
