---
name: Error review checklist
applies_to: err
axes:
  - clarity
  - correctness
  - traceability
---

# Error review checklist

- [ ] ID matches `id_regex` (`^(FEAT|CREQ|ERR|IMPL|TEST)_[A-Z0-9_]*[0-9]{3}$`).
- [ ] Title names the observable failure condition (not its cause).
- [ ] Status is one of `open`, `in_progress`, `implemented`.
- [ ] Body explains the condition, when it arises, and the consequence if unguarded.
- [ ] **At least one** handling relation is set — `:tested_in:`,
      `:checked_in:`, or `:mitigated_in:` — each pointing at the feature(s)
      where the handling lives. (This OR-rule is enforced here, not via
      `required_links`, which has AND semantics.)
- [ ] Relation choice matches reality: `:checked_in:` = raises/guards at runtime;
      `:mitigated_in:` = graceful degradation by design; `:tested_in:` =
      correctness rests on tests with no runtime guard or fallback.
- [ ] `:severity:` is set (`low` / `medium` / `high`).
- [ ] `:source_doc:` names the source file(s) where the condition is handled.
- [ ] Where a test exercises the condition, a `test` need `:detects:` this
      error.
