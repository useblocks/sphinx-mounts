---
name: Test review checklist
applies_to: test
axes:
  - clarity
  - correctness
  - traceability
---

# Test review checklist

- [ ] ID matches `id_regex` (`^(STORY|FEAT|ERR|TEST|CHECK|REST|IMPL)_[A-Z0-9_]*[0-9]{3}$`).
- [ ] Title states what the test rules out ("Prevents …").
- [ ] Status is one of `open`, `in_progress`, `implemented`.
- [ ] `:prevents:` names the error(s) the test structurally rules out.
- [ ] The one-line need sits in the test file next to the test it represents
      (sphinx-codelinks local-url).
- [ ] The test actually fails if the error condition is introduced — it
      proves prevention, not just happy-path behaviour.
