---
name: Component requirement review checklist
applies_to: comp_req
axes:
  - clarity
  - correctness
  - traceability
---

# Component requirement review checklist

- [ ] ID matches `id_regex` (`^(FEAT|CREQ|ERR|IMPL|TEST)_[A-Z0-9_]*[0-9]{3}$`).
- [ ] Title states a single, testable obligation.
- [ ] Body is a "shall" clause — unambiguous, verifiable, free of "and/or" fusion.
- [ ] Status is one of `open`, `in_progress`, `implemented`.
- [ ] `:satisfies:` points at exactly the feature(s) this requirement decomposes.
- [ ] `:source_doc:` names the implementing source file(s) (forward trace).
- [ ] Verified by at least one `test` need (`test :verifies: <this id>`),
      authored in the test suite as a one-line need.
