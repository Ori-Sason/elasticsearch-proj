---
name: learning-session-notes
description: Write or update the notes file for a learning session in this project. Use this after finishing (or partway through) a session from the curriculum, whenever the user asks to save notes, summarize what was covered, or write up a session. Produces a detailed, skimmable notes file under learning-notes/ — plain language, full technical depth.
---

# Learning session notes

Write notes so that months later, reading the file brings back not just what the session was about, but the actual reasoning and mechanisms involved. This is a technical reference, not a simplified recap — simplify the language, never the content.

Before writing, read `reference/user-background.md` — it covers what the learner already knows, so explanations calibrate to the right starting depth instead of re-teaching fundamentals or, conversely, assuming context that hasn't been covered yet.

## Simplify language, never content

This is the single most important rule here. A note that reads easily but lost the substance has failed.

- Write in plain language: short sentences, everyday words, explained the way you'd explain it to a peer rather than the way a manual would.
- Do **not** cut technical depth to make a note simpler. Mechanisms (why something actually works the way it does), trade-offs, alternatives that were considered and rejected, and exact commands/config/output all belong in the note. The user has real technical depth already — see `reference/user-background.md` for what to assume as known — so don't dumb concepts down or skip the "why," just say it plainly.
- Every technical term gets used directly, with a short plain-language gloss the first time it shows up — don't avoid a term because it's technical, and don't over-explain one that's already obvious from context.
- No mid-sentence line breaks. Write each sentence, and each paragraph, as one unbroken line. Use blank lines only to separate distinct paragraphs, bullets, or sections — never inside one.
- Depth over brevity, but no padding: say everything that matters, nothing that doesn't.

## Where the file goes

- Path: `learning-notes/session-<n>-<short-topic>.md` (matches the existing files in that folder, e.g. `session-1-cluster-fundamentals.md`).
- One file per session. If the file already exists, update it — add new material to the right existing section, or add a new section, rather than restructuring what's already there unless it's wrong or the user asks you to.

## Structure

1. **Title** — `# Session <n> — <topic>`.
2. **TL;DR** — a few lines right after the title: what this session was about and what got built or done, in the fewest words that still make sense standalone. This is a quick orienting summary, not a substitute for depth — the sections below still carry full technical content regardless of what's said here.
3. **What we covered** — the key concepts. Each one gets a bold short topic name followed by real explanation: what it is, why it exists, the mechanism behind it, how it compares to things the user already knows (Postgres, MongoDB, AWS, Docker/Kubernetes, etc. — but the comparison should sharpen understanding, not replace it). Go as deep as the concept actually requires. Skip only what was purely mentioned in passing and didn't matter to the session's goal.
4. **What we did** — the actual steps/commands/config/output, in enough detail to reconstruct the reasoning later: what was run, what it returned, what that meant, and what was decided as a result (including alternatives considered and why they were or weren't used). Use real code/command blocks, not paraphrases of them. Link out to files in the repo (`docker-compose.yaml`, scripts) for their full content instead of duplicating something long, but still explain and quote the parts that matter.
5. **Questions I had** (only if relevant) — short question/answer pairs for anything the user specifically asked about and wanted remembered, answered with the same depth as the rest of the file.

Skip a section only if it has nothing worth keeping (other than the Title and TL;DR, which are always present) — an empty "Questions I had" heading is worse than no heading at all.

**Links to other files in the repo:** use project-absolute paths (starting from the repo root, e.g. `/docker-compose.yaml`, `/learning-notes/images/session1-1.png`), not relative paths like `../docker-compose.yaml` — relative paths break depending on where the note file itself is.

## What to leave out

- Don't include troubleshooting/debugging blow-by-blow unless the user asks for it, or the dead end actually changed a real decision.
- Don't duplicate full file contents that already live in the repo (a whole `docker-compose.yaml`, a whole script) — quote and explain the parts worth explaining, link to the file for the rest.
- Don't editorialize about how the session went — just the content.

## After writing

Check off the matching task boxes in `learning-notes/elasticsearch-curriculum.md` if they're done and not already checked, per the project's own convention — don't leave that for a separate step.
