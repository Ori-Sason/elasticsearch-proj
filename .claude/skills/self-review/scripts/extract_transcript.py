#!/usr/bin/env python3
"""
extract_transcript.py -- turn a raw Claude Code session .jsonl transcript into
a small, filtered stream of the user's own messages, for the self-review skill.

A raw session transcript is full of tool results, thinking blocks, and other
noise that's worthless for reviewing how a person prompts and learns -- and
can be roughly 100x larger than the content that actually matters. This
script strips all of that out locally, with zero model tokens spent, so a
harvesting subagent only ever reads the small part that's actually relevant.

Usage:
  extract_transcript.py list [--project-dir DIR]
      Lists this project's session transcript files, one per line:
      <path>\t<line_count>\t<first_ts>\t<last_ts>\t<n_real_user_messages>

  extract_transcript.py pending [--project-dir DIR] [--checkpoint PATH]
      Diffs every transcript's current line count against the cursor recorded
      in the checkpoint file (a missing checkpoint file counts as empty, so
      everything is pending). Prints only what actually has new content:
      <path>\t<from_line>\t<new_cursor>
      This is a plain diff, done in code -- no need to read `list` output and
      the checkpoint file and compare them by hand.

  extract_transcript.py extract <jsonl_path> [--from-line N]
      Prints the filtered text of real user messages starting at raw line N
      (default 0 -- the whole file), each one preceded by Claude's plain-text
      reply that came right before it (verbatim, not summarized -- a short
      message like "yes" or "correct?" is often only meaningful next to what
      it's replying to). Ends with a final line:
          ===CURSOR:<total_line_count>===
      Persist that number as this file's new checkpoint cursor. Next time,
      pass it back as --from-line to pick up only what's new (including a
      session that got resumed and had more appended to the same file).

  extract_transcript.py hash <file_path>
      Prints the real sha256 hex digest of a file's content. Use this
      instead of asking a model to "record a hash" -- a model cannot
      actually compute one and will confabulate a fake-looking string.

  extract_transcript.py append-evidence <evidence_log_path>
      Reads evidence entries from stdin (one JSON object per line, an
      optional wrapping ``` fence tolerated and stripped), validates every
      line parses as real JSON, and only then appends them to the log file.
      Fails loudly with nothing written if any line is invalid.
"""
import argparse
import json
import re
import sys
from pathlib import Path

MAX_MSG_CHARS = 2000


def project_slug(project_dir: Path) -> str:
    return str(project_dir.resolve()).replace("/", "-")


def transcripts_dir(project_dir: Path) -> Path:
    return Path.home() / ".claude" / "projects" / project_slug(project_dir)


def extract_text(content):
    """Return the plain text of a genuine human-typed message, or None."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result":
                return None  # a tool response, not something typed by a person
            if block.get("type") == "text":
                texts.append(block.get("text", ""))
        return "\n".join(texts) if texts else None
    return None


def extract_assistant_text(content):
    """Return an assistant turn's plain reply text only -- 'text' blocks,
    never 'thinking' or 'tool_use' (where nearly all the size lives) -- or
    None if the turn was pure tool calls with no reply text of its own."""
    if not isinstance(content, list):
        return None
    texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    return "\n".join(texts) if texts else None


def iter_real_messages(jsonl_path: Path, from_line: int = 0, line_count_out: list = None):
    """Yield (line_no, timestamp, kind, text, prior_reply) for genuine user
    content only. kind is 'MSG' for a typed message, 'CMD' for a slash-command
    invocation (slash commands matter here as direct evidence of session/
    context habits: /clear, /compact, /context, /model). prior_reply is the
    plain text of Claude's most recent reply before this message -- needed
    because a short message ("yes", "correct?") is often only meaningful next
    to what it's replying to -- or None for a CMD, or if nothing preceded it.

    Every line is scanned regardless of from_line, so prior_reply is correct
    even right after a resume point; only whether a user message actually
    gets yielded respects the cursor.

    If line_count_out is given (an empty list), this scans the whole file
    exactly once and appends the total line count to it once exhausted --
    avoids a second full read of the file just to count its lines."""
    last_reply = None
    total = 0
    with jsonl_path.open(encoding="utf-8", errors="replace") as f:
        for line_no, raw in enumerate(f):
            total = line_no + 1
            raw = raw.strip()
            if not raw:
                continue
            try:
                d = json.loads(raw)
            except Exception:
                continue
            if d.get("isSidechain") in (True, "True"):
                continue

            if d.get("type") == "assistant":
                msg = d.get("message")
                if isinstance(msg, dict) and msg.get("role") == "assistant":
                    text = extract_assistant_text(msg.get("content"))
                    if text:
                        last_reply = text.strip()
                continue

            if d.get("type") != "user":
                continue
            msg = d.get("message")
            if not isinstance(msg, dict) or msg.get("role") != "user":
                continue
            text = extract_text(msg.get("content"))
            if text is None:
                continue
            stripped = text.strip()
            if not stripped:
                continue
            if stripped.startswith(("<local-command-caveat>", "<system-reminder>", "<system_warning")):
                continue

            if line_no < from_line:
                continue  # prior_reply tracking above still runs either way

            ts = d.get("timestamp")
            if stripped.startswith("<command-name>"):
                m = re.search(r"<command-name>(.*?)</command-name>", stripped)
                yield line_no, ts, "CMD", (m.group(1) if m else stripped[:60]), None
                continue
            yield line_no, ts, "MSG", stripped, last_reply

    if line_count_out is not None:
        line_count_out.append(total)


def count_lines(path: Path) -> int:
    total = 0
    with path.open(encoding="utf-8", errors="replace") as f:
        for total, _ in enumerate(f, start=1):
            pass
    return total


def cmd_list(args):
    tdir = transcripts_dir(Path(args.project_dir))
    if not tdir.is_dir():
        print(f"# no transcripts directory found at {tdir}", file=sys.stderr)
        return
    for path in sorted(tdir.glob("*.jsonl")):
        first_ts = last_ts = None
        n_msgs = 0
        line_count_out = []
        for _, ts, kind, _, _ in iter_real_messages(path, line_count_out=line_count_out):
            if kind == "MSG":
                n_msgs += 1
                if first_ts is None:
                    first_ts = ts
                last_ts = ts
        print(f"{path}\t{line_count_out[0]}\t{first_ts}\t{last_ts}\t{n_msgs}")


def load_checkpoint(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def pending_files(project_dir: Path, checkpoint_path: Path):
    """Yield (path, from_line, new_cursor) for each transcript with unprocessed content."""
    tdir = transcripts_dir(project_dir)
    if not tdir.is_dir():
        return
    checkpoint = load_checkpoint(checkpoint_path)
    for path in sorted(tdir.glob("*.jsonl")):
        current = count_lines(path)
        cursor = checkpoint.get(str(path), 0)
        if current > cursor:
            yield path, cursor, current


def cmd_pending(args):
    for path, cursor, current in pending_files(Path(args.project_dir), Path(args.checkpoint)):
        print(f"{path}\t{cursor}\t{current}")


def _capped(text: str) -> str:
    if len(text) > MAX_MSG_CHARS:
        return text[:MAX_MSG_CHARS] + f"... [TRUNCATED, total {len(text)} chars]"
    return text


def cmd_extract(args):
    path = Path(args.jsonl_path)
    line_count_out = []
    for _, ts, kind, text, prior_reply in iter_real_messages(path, args.from_line, line_count_out):
        if kind == "CMD":
            print(f"[{ts}] /CMD: {text}")
        else:
            if prior_reply:
                print(f"[{ts}] CLAUDE (preceding reply): {_capped(prior_reply)}")
            print(f"[{ts}] USER: {_capped(text)}\n---")
    print(f"===CURSOR:{line_count_out[0]}===")


def cmd_hash(args):
    """Print the sha256 hex digest of a file's content. A model cannot
    actually compute a cryptographic hash by reasoning about text -- asked
    to "record a sha256 hash," it will confabulate a plausible-looking fake
    one. This gives the skill a real, portable digest to compare against,
    instead of leaning on OS-specific tools (sha256sum vs Get-FileHash)."""
    import hashlib
    digest = hashlib.sha256(Path(args.file_path).read_bytes()).hexdigest()
    print(digest)


def cmd_append_evidence(args):
    """Append evidence entries to the evidence log, guarding against the
    most common way a subagent corrupts a JSONL file: wrapping its output in
    a Markdown code fence. Strips one, if present, then validates every
    remaining non-empty line is real JSON before writing anything -- a
    malformed batch fails loudly with nothing appended, rather than silently
    writing a mix of good lines and one line that breaks every future read
    of this file."""
    raw = sys.stdin.read().strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()

    entries = []
    for i, line in enumerate(raw.split("\n"), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            json.loads(line)  # validate only -- write back the original line
        except json.JSONDecodeError as e:
            print(f"error: line {i} is not valid JSON, nothing appended: {e}\n  {line}", file=sys.stderr)
            sys.exit(1)
        entries.append(line)

    if not entries:
        print("error: no evidence entries found in input, nothing appended", file=sys.stderr)
        sys.exit(1)

    path = Path(args.evidence_log)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for line in entries:
            f.write(line + "\n")
    print(f"appended {len(entries)} entries to {path}")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="list this project's session transcripts")
    p_list.add_argument("--project-dir", default=".")
    p_list.set_defaults(func=cmd_list)

    p_pending = sub.add_parser("pending", help="list transcripts with unprocessed content vs. a checkpoint file")
    p_pending.add_argument("--project-dir", default=".")
    p_pending.add_argument("--checkpoint", default="learning-notes/self-review/checkpoint.json")
    p_pending.set_defaults(func=cmd_pending)

    p_extract = sub.add_parser("extract", help="extract filtered text from one transcript")
    p_extract.add_argument("jsonl_path")
    p_extract.add_argument("--from-line", type=int, default=0)
    p_extract.set_defaults(func=cmd_extract)

    p_hash = sub.add_parser("hash", help="print the sha256 hex digest of a file")
    p_hash.add_argument("file_path")
    p_hash.set_defaults(func=cmd_hash)

    p_append = sub.add_parser(
        "append-evidence",
        help="validate and append JSONL evidence entries (read from stdin) to a log file",
    )
    p_append.add_argument("evidence_log")
    p_append.set_defaults(func=cmd_append_evidence)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
