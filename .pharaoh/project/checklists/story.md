---
name: Story review checklist
applies_to: story
axes:
  - clarity
  - traceability
---

# Story review checklist

- [ ] ID matches `id_regex` (`^(STORY|FEAT|ERR|TEST|CHECK|REST|IMPL)_[A-Z0-9_]*[0-9]{3}$`).
- [ ] Title is a short, capability-level name.
- [ ] Body follows "As a <role>, I want <goal>, so that <benefit>".
- [ ] Status is one of `open`, `in_progress`, `implemented`.
- [ ] At least one `feat` `:realizes:` this story.
- [ ] The story expresses user-facing demand, not an implementation detail.
