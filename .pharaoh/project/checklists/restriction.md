---
name: Restriction review checklist
applies_to: restriction
axes:
  - clarity
  - traceability
---

# Restriction review checklist

- [ ] ID matches `id_regex` (`^(STORY|FEAT|ERR|TEST|CHECK|REST|IMPL)_[A-Z0-9_]*[0-9]{3}$`).
- [ ] Title states the constraint as a single rule.
- [ ] Status is one of `open`, `in_progress`, `implemented`.
- [ ] `:avoids:` names the error(s) whose precondition the restriction removes.
- [ ] Body documents the constraint and how it is communicated or enforced
      (install docs, CI guard, environment requirement).
- [ ] The restriction removes the error's precondition rather than detecting
      it after the fact.
