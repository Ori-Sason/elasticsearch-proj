#!/usr/bin/env python3
"""
SessionStart hook for the self-review skill.

Runs the same backlog check as `extract_transcript.py pending` and, if
anything is unprocessed, prints a SessionStart hookSpecificOutput JSON
object so it's injected as context Claude sees at session start. Prints
nothing when there's nothing pending -- no output means no effect, per
Claude Code hook convention.

Resolves the project root from this file's own location, not from the
invoking shell's cwd, so it works regardless of where a session starts.

Everything below runs inside a broad try/except that fails silently. This
is a hook, not a command someone is watching: an environment problem (a
broken Python install, a permissions error, a corrupt checkpoint file)
must never surface as a crash or hang at session start. Worst case of
failing silently is that harvesting is skipped this session -- harmless,
and the next session's hook run will just pick up the same backlog. Worst
case of *not* failing silently is a scary, unexplained error every time a
session starts, for a feature the user never directly invoked.
"""
import sys


def main():
    import json
    from pathlib import Path

    scripts_dir = Path(__file__).resolve().parent
    project_root = scripts_dir.parents[3]  # scripts -> self-review -> skills -> .claude -> project root

    sys.path.insert(0, str(scripts_dir))
    from extract_transcript import pending_files

    checkpoint = project_root / "learning-notes" / "self-review" / "checkpoint.json"

    lines = [
        f"{path}\t{cursor}\t{current}"
        for path, cursor, current in pending_files(project_root, checkpoint)
    ]

    if lines:
        context = (
            "self-review: unprocessed session transcripts (path\\tfrom_line\\tnew_cursor). "
            "See .claude/skills/self-review/SKILL.md's harvesting section.\n" + "\n".join(lines)
        )
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        }))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # fail silently -- see module docstring
    sys.exit(0)
