---
name: self-review
description: Review the person doing this learning project, not the subject matter -- their question quality, engagement, and prompt/context-window habits. Runs two ways -- a lightweight, automatic harvest of evidence at the start of every session, and a full compiled review written whenever the user actually asks for one. Use the harvest step every session, unprompted. Use the compile step when the user asks for a self-review, a review of themselves, or how they're doing as a learner.
---

# Self-review

This skill produces a review of the learner, not the material being taught. It runs in two distinct modes, and they use different amounts of effort on purpose:

- **Harvest** -- automatic, at the start of every session, cheap. Pulls a few short evidence notes out of whatever session(s) haven't been looked at yet, and stores them. No writing happens here.
- **Compile** -- on request only, when the user actually asks for a review. Reads everything harvested so far plus the project's own files, and writes the full review.

Keep these two separate. Harvesting is extraction, not judgment -- it should never produce prose, never interrupt teaching, and never show its work in the main conversation. Compiling is where the actual thinking and writing happen, once, when it's asked for.

---

## Voice and structure (compile step only)

This section defines the review's voice directly. Don't borrow tone or structure from another skill in this project -- this skill is self-contained.

- **Ambivalent, evidence-driven.** State a strength where the evidence shows one, and a weakness where it shows one, in whatever mix the actual sessions produced. Don't force a strength for every weakness or a weakness for every strength -- some topics will be entirely one or the other, and that's fine. Never blunt a stated weakness with a compliment in the same breath ("...but that came from a good instinct"). If both are true, say both, as separate, standalone statements -- not one softening the other.
- **Examples over assertions.** Every real claim needs a quoted prompt or a specific, concrete moment behind it. "Your questions were sharp" is not a finding. `"related to your point about 'term' in line 11 - this is not always true..."` is.
- **Structure, per topic:** an opening (what was looked at, and how), then the substance (whatever mix of strength and weakness the evidence actually shows), then a closing verdict for that topic. Repeat per topic. Close the whole review with a short "carrying forward" list -- concrete, not generic.
- **Plain language.** Short sentences. One idea each. A worked example for anything abstract. Write it the way you'd actually say it out loud to someone you respect, not the way a performance review template would.
- **Correctness over confidence.** Any claim about the current state of a file must come from actually reading that file in this pass -- never from an earlier snapshot, memory, or something read before this compile started. A wrong claim stated confidently is worse than no claim.

---

## Where things live

Everything this skill produces lives in `learning-notes/self-review/`, git-ignored (confirm this on first use in a new project -- if the folder or its `.gitignore` entry doesn't exist yet, create both before writing anything into it):

- `checkpoint.json` -- one entry per session transcript file, recording how far harvesting has processed it. Shape:
  ```json
  {
    "/home/user/.claude/projects/-slug-/abc123.jsonl": 594
  }
  ```
  The value is a line number (from this skill's extraction script), not a boolean. A session that gets resumed can have more appended to the same transcript file later -- a cursor handles that correctly; a done/not-done flag would silently miss the new tail.
- `evidence-log.jsonl` -- one short structured entry per harvested observation, appended over time, never rewritten by the harvest step. Shape:
  ```json
  {"session": "abc123", "ts": "2026-09-04T19:17:49Z", "category": "engagement", "note": "predicted an approximate aggregation error count before running the query, landed within 3%"}
  ```
  Keep entries terse -- a fact and a quote fragment, not a paragraph. The prose write-up happens once, at compile time, not here.
- `background-summary.md` -- a short (5-10 line) distillation of the project's `user-background.md`, maintained by this skill for harvest-time use. Not the full CV -- just enough for a harvesting pass to judge whether something is expected-for-this-person or genuinely new territory (e.g. "deep in DB internals and networking; new to Elasticsearch and TypeScript specifically"). Create it the first time this skill harvests in a project. Its header records when it was generated and a content hash of `user-background.md` at that time, e.g.:
  ```
  <!-- Generated 2026-09-06 from user-background.md (sha256:3f9a...) -->
  ```
  Regenerate it whenever `user-background.md`'s current content hash doesn't match the one recorded here -- not by comparing file modification times. `user-background.md` can be edited at any point during the project (this isn't a one-time setup file), and mtimes don't survive a `git clone`/checkout onto a new machine or a VM rebuild, which this project has already been through once -- a content hash is the only signal that's actually reliable across that. Get the hash by running `extract_transcript.py hash user-background.md` -- never state or compare a hash from memory or reasoning. A model cannot actually compute a cryptographic hash by thinking about text; asked to produce one directly, it will confabulate a plausible-looking fake string instead of a real one.
- `self-review.md` -- the compiled, human-facing review. Overwritten each time compile runs.

## Setup (once per project)

The automatic harvest step depends on a `SessionStart` hook. Check `.claude/settings.json` for a `SessionStart` hook whose command runs `self-review/scripts/session_start_hook.py`. If it's already there, skip this section -- nothing to do.

If it's missing, ask the user once, at the start of a session: do they want this project reviewed as a learner (question quality, engagement, prompt/context habits) going forward, via this skill? If yes:

1. Use the `update-config` skill to add a `SessionStart` hook that runs `python3 <absolute-project-root>/.claude/skills/self-review/scripts/session_start_hook.py` -- an absolute path, since the hook can't rely on the shell's cwd being the project root.
2. Tell the user plainly that the hook is installed but not active yet this session -- Claude Code's settings watcher wasn't watching `.claude/` before this file existed, so it needs a `/hooks` reload or a session restart before it actually fires.

If the user says no, create nothing, and don't ask again this session. Without the hook, harvesting still works when compile is triggered on demand (see below) -- it just doesn't run automatically at the start of every session.

## Harvesting (every session, before anything else, automatic)

A `SessionStart` hook already runs `extract_transcript.py pending --checkpoint learning-notes/self-review/checkpoint.json` at the start of every session and surfaces the result if it's non-empty -- so the backlog check itself doesn't depend on remembering to do it. Each surfaced line is `<path>\t<from_line>\t<new_cursor>`.

If compiling a review mid-session (see below), there's no hook output waiting -- run `extract_transcript.py pending --checkpoint learning-notes/self-review/checkpoint.json` directly instead.

1. For each pending line, run `extract_transcript.py extract <path> --from-line <from_line>`. If the output (excluding the final `===CURSOR:...===` line) is trivially small -- a handful of lines, e.g. a lone `/clear` -- skip spawning anything for it, just record `<new_cursor>` for that path in `checkpoint.json` and move on. No model call needed to know there's nothing there.
2. Otherwise, spawn a fresh subagent (a small/fast model -- this is extraction, not synthesis) and give it: the filtered text from step 1, and `background-summary.md`. The filtered text includes Claude's own preceding reply next to each user message, verbatim -- so a short reply like "yes" or "correct?" can be read next to what it's actually responding to, instead of judged in isolation. Task: pull out a handful of short, concrete evidence entries (sharp questions, corrections, predictions, context-management moments -- slash commands, session-boundary reasoning), each in the shape shown above, and write them to `evidence-log.jsonl` by piping them into `extract_transcript.py append-evidence learning-notes/self-review/evidence-log.jsonl` -- never append to the file directly. That command strips an accidental Markdown code fence if the subagent wrapped its output in one, validates every line is real JSON, and writes nothing at all if any line fails, instead of silently corrupting a file every later harvest and compile depends on. Then record `<new_cursor>` for that path in `checkpoint.json`.
3. The main session sees none of this reasoning -- only a short confirmation that harvesting ran, or nothing at all if there was nothing pending.

This does not depend on any other skill firing, and it does not wait for a session to end cleanly -- a session that never gets a graceful close still gets swept up the next time any session starts, since the hook runs unconditionally.

## Compiling a review (on request, any time)

Triggered whenever the user asks to be reviewed, how they're doing, or for a self-review -- at the start of a session, in the middle of one, whenever.

1. Harvest the current session first, through the exact mechanism above (run `pending` directly, then steps 1-2, scoped to just this session's transcript) -- there is no special case for "the session asking for the review is still open." It's just one more transcript to sweep.
2. Read the full `evidence-log.jsonl`, the project's curriculum file, every skill file in `.claude/skills/`, and the full `user-background.md` (not the harvest-time summary -- the whole file, so claims can be checked against the actual evidence in it, not assumed from it).
3. Write `self-review.md` in the voice and structure defined above. Use the full model for this step, not the harvesting subagent -- this is the one place real synthesis and writing quality matter.
4. If something in the background file or the project's own files turns out to contradict a draft finding, re-read the live file before asserting anything -- never rely on a snapshot from earlier in the conversation or from memory.
