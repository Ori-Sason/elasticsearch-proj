---
name: curriculum-creation
description: Design a session-by-session learning curriculum for a hands-on technical project. Use when the user wants to learn a new tool, language, or technology through a guided project, or asks for a curriculum, learning plan, syllabus, or session breakdown. Produces a markdown curriculum file structured for Claude Code to teach from directly, plus a CLAUDE.md pointer so it loads automatically every session.
---

# Curriculum creation

Design curriculums that get read and taught from, not just skimmed once and abandoned. The test: months into the project, session 4 should still make sense as a step in a coherent whole, not a disconnected exercise.

## Before writing

If any of this isn't already clear from the conversation, ask before drafting — a curriculum built on a wrong guess about scope or level wastes more time than the questions do:

- **The topic and the project it'll be taught through.** A curriculum needs a throughline project, not a list of disconnected exercises — if the user only names a topic ("I want to learn Kafka"), propose a concrete project to learn it through and confirm it, don't just start listing abstract topics.
- **Audience/skill level.** What the learner already knows that's relevant (adjacent tools, general experience level) — check `reference/user-background.md` if this project has one, the same way `learning-session-notes` does, so sessions calibrate to the right starting depth instead of re-teaching fundamentals or assuming context that hasn't been covered.
- **Environment and tools available**, so tasks are concrete and runnable, not generic.
- **Rough scope** — single lesson, short series, or full curriculum — and session count if the user has a preference; otherwise choose a number that fits the topic and say why.

## Design principles

- **One throughline project, by default — not a topic list.** Most sessions should build the same running project further, not cover an isolated concept in a vacuum, so a learner can say what they *built*, not just what they *read about*. This is a preference, not a hard rule: if a subject genuinely doesn't fit the main project, give it its own small side project rather than dropping it or forcing an awkward fit — don't sacrifice an important subject just to keep everything in one project.
- **Sessions are dependencies, not modules.** Each session's deliverable feeds the next one. If a session could be deleted or reordered without breaking anything downstream, the sequencing isn't doing its job. A side project spun off for a subject that doesn't fit the main line is the exception — it doesn't need to feed the main project's chain, but it should still say up front why it's a detour.
- **Theory → hands-on → deep dive → hands-on — but only when the topic has a deep dive in it.** Start with just enough background to know what's about to be built and why — not a full lecture. Move quickly into real hands-on work; don't over-explain before letting the learner touch it. Then, if the topic has genuinely more complicated areas underneath — mechanisms, trade-offs, edge cases, the "why" — go from the intro into those harder corners, the way a session moves from understanding a concept to its harder territory, and close with hands-on that applies it. If the topic doesn't have that further depth, skip the second theory pass for that session rather than filling the space with a repeat or a different-angle retelling relabeled as a deep dive.
- **Explicit over implicit**, in both the project's own conventions (e.g. explicit config over relying on defaults) and in the curriculum itself — spell out what a session's theory passes should actually cover, don't just say "explain the basics."
- **Verify version-specific syntax against current docs, not just trained knowledge.** When a concept or task depends on exact API/config syntax that changes across versions, use a documentation-lookup MCP (e.g. `context7`, if available) to check current syntax rather than trusting memory alone.
- **Scope stretch material out.** Advanced/production concerns (scaling, security hardening, performance tuning) belong in an optional stretch section at the end, not folded into early sessions where they'd bury the fundamentals.

## File structure

Produce a single markdown file with this shape:

1. **Title + purpose note** — what the file is and how it's meant to be used (by the learner, with Claude Code, session by session).
2. **"How to use this with Claude Code"** — an explicit instruction block telling Claude Code to teach, not just execute: follow the theory → hands-on → deep-dive theory → hands-on pattern each session, connect new material back to earlier sessions, check understanding as you go rather than lecturing straight through, and check off task boxes in this same file as work completes so progress persists across sessions.
3. **Environment** — what's available (OS, languages, tools already installed) so later tasks can assume it without re-stating it.
4. **Introduction** — what the technology actually is, the core problem it solves, where it's used in the industry, and (briefly) how it compares to something the learner already knows. This is the scene-setting the first Claude Code session should walk through before session 1 starts.
5. **One section per session**, each with:
   - **Goal** — one or two sentences, outcome-focused.
   - **Concepts to cover before the tasks** — the first, lighter theory pass: specific concepts named, not "explain the basics." Say what the concept is, why it's being introduced now, and what it should connect back to from earlier sessions. Keep this pass just deep enough to make the hands-on tasks make sense — the deeper pass comes later.
   - **Tasks** — a `- [ ]` checklist, concrete and runnable in the stated environment. This is what `learning-session-notes` (or whatever the project's notes skill is) checks off later — keep the checkbox format exact.
   - **Deep dive (only when the topic has one)** — after the hands-on tasks, move into the more complicated areas of the same subject: mechanisms, trade-offs, edge cases, the "why" behind what was just built — like going from an intro to the concept into its harder corners. If there's nothing further to go into, skip this rather than filling the space with a repeat or a different-angle retelling dressed up as depth. When it is included, note where it should lead into further hands-on (more tasks, or extending the existing ones) rather than ending on theory alone.
   - **Deliverable** — what should exist and work by the end of the session.
6. **Stretch section** (optional) — advanced topics deliberately left out of the core sequence, named but not detailed, for after the fundamentals are solid.

## Where the file goes

- Path: `learning-notes/<topic>-curriculum.md` (matches how a companion notes skill would reference it, e.g. `learning-notes/elasticsearch-curriculum.md`).
- One file for the whole curriculum, not one per session — Claude Code needs the full sequence in view to know what's next and what came before. A side project gets its own section in the same file (or its own short file, linked from the main one) rather than vanishing from the plan.

## After writing

Offer to write or update the project's `CLAUDE.md` with a short pointer to the curriculum file (what it's for, the teach-first instruction, where to resume from). `CLAUDE.md` loads automatically every Claude Code session; the curriculum file doesn't, unless something points to it. Without that pointer the learner has to ask for it to be read every time, which defeats a lot of the point.

While doing this, check whether a documentation-lookup MCP (e.g. `context7`) is installed. If not, suggest the user install it before starting the curriculum's sessions — per the design principle above, sessions use it to verify version-specific API/config syntax rather than relying on trained knowledge alone. If it is installed, add the same note to `CLAUDE.md` that this project's own file uses (a short "Tools" section pointing at it) so every session picks it up automatically.

## What to leave out

- Don't write full technical content (code samples, exact commands, Query-DSL-level detail, etc.) into the curriculum itself — that's what the session actually teaches. The curriculum names concepts and tasks; it doesn't pre-empt the teaching by dumping the answers.
- Don't front-load every interesting tangent into session 1. If a topic doesn't serve that session's deliverable, it belongs later, in the stretch section, or in its own side project.
- Don't pad sessions to hit a target count, and don't cram unrelated concepts into one session to hit a smaller one. Let the project's natural structure set the session count.
