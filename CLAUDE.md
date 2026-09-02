# Project: Elasticsearch learning

This project exists to learn Elasticsearch hands-on by building a small log search and analytics stack. The full plan lives in `learning-notes/elasticsearch-curriculum.md` — read it before starting any work here.

## How to run sessions

- Follow the teaching instructions in `learning-notes/elasticsearch-curriculum.md`: explain concepts before writing code, connect new ideas back to earlier sessions, and check understanding as you go rather than lecturing straight through.
- Before explaining anything, read `.claude/skills/learning-session-notes/reference/user-background.md` to calibrate depth: simplify language, never content — don't re-teach fundamentals it says are already known, but go fully deep on anything specific to the new tool/topic.
- If this is the very first session in the project, start with the "Introduction — what is Elasticsearch, and why use it" section before session 1.
- Work through sessions in order. Each session's deliverable is a dependency for the next one — don't skip ahead even if it looks simple.
- At the start of a session, check which task checkboxes in `learning-notes/elasticsearch-curriculum.md` are already ticked to figure out where we left off, rather than asking to be told.
- As tasks are completed, check them off directly in `learning-notes/elasticsearch-curriculum.md` (`[ ]` → `[x]`), so progress persists across sessions.

## Conventions

- Mappings are explicit, never left to dynamic mapping.
- Config is explicit over defaulted — e.g. a `.env.example` documenting connection settings, not hardcoded values.
