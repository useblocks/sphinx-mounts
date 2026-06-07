---
name: Check review checklist
applies_to: check
axes:
  - clarity
  - correctness
  - traceability
---

# Check review checklist

- [ ] ID matches `id_regex` (`^(STORY|FEAT|ERR|TEST|CHECK|REST|IMPL)_[A-Z0-9_]*[0-9]{3}$`).
- [ ] Title states what the check verifies at runtime.
- [ ] Status reflects reality (`in_progress` until the CI job is wired up).
- [ ] `:detects:` names the error(s) this check would catch.
- [ ] Body says where the check runs (CI job / tool) and what signal it
      inspects (log lines, output, needs.json …).
- [ ] The check fails the build/pipeline when the error appears — not
      advisory-only.
