---
name: Test review checklist
applies_to: test
axes:
  - clarity
  - correctness
  - traceability
---

# Test review checklist

- [ ] ID matches `id_regex` (`^(FEAT|CREQ|ERR|IMPL|TEST)_[A-Z0-9_]*[0-9]{3}$`).
- [ ] Title states what the test checks ("Verifies …" / "Detects …").
- [ ] Status is one of `open`, `in_progress`, `implemented`.
- [ ] **At least one** of `:verifies:` (→ comp_req) or `:detects:` (→ err) is
      non-empty. (OR-rule — enforced here, not via `required_links`.)
- [ ] `:verifies:` targets are component requirements; `:detects:` targets are
      errors — no cross-type mistakes.
- [ ] The one-line need sits in the test file next to the test it represents,
      so its source location *is* the test (sphinx-codelinks local-url).
- [ ] An error-only test writes `[]` for the mandatory `verifies` field and the
      error id for `detects`.
