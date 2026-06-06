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
- [ ] Title names what the test exercises.
- [ ] Status is one of `open`, `in_progress`, `implemented`.
- [ ] `:verifies:` names the feature the test exercises (every test verifies a
      feature).
- [ ] `:prevents:` (optional) names the error(s) the test structurally rules
      out.
- [ ] The one-line need sits in the test file next to the test it represents
      (sphinx-codelinks local-url).
- [ ] If it claims `:prevents:`, the test actually fails when the error
      condition is introduced — it proves prevention, not just happy-path
      behaviour.
