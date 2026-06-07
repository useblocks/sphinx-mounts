---
name: Error review checklist
applies_to: err
axes:
  - clarity
  - correctness
  - traceability
---

# Error review checklist

- [ ] ID matches `id_regex` (`^(STORY|FEAT|ERR|TEST|CHECK|REST|IMPL)_[A-Z0-9_]*[0-9]{3}$`).
- [ ] Title names the observable failure condition (not its cause).
- [ ] Status is one of `open`, `in_progress`, `implemented`.
- [ ] Body explains the condition, when it arises, and the consequence if unguarded.
- [ ] `:affects:` names the feature(s) in which this error can occur.
- [ ] `:severity:` is set (`low` / `medium` / `high`).
- [ ] `:source_doc:` names the source file(s) where the condition arises.
- [ ] **Treated** by at least one of: a `test` that `:prevents:` it
      (structural), a `check` that `:detects:` it (runtime/CI), or a
      `restriction` that `:avoids:` it (usage constraint). Incoming rule —
      reviewed here, not schema-enforced (SN #1590).
- [ ] Treatment choice matches reality: prevention only when the error is
      structurally impossible once the test passes; otherwise mitigation.
