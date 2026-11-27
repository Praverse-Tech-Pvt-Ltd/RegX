"""PreToolUse hook for Bash: refuse heredocs ("<<") and Python reading its program from stdin ("python -",
with or without flags such as -I). Both have hung this project's sessions at an interactive prompt or hidden
what was run; scripts must be files that can be read, kept and re-run.

Exit 2 blocks the call and shows the message to Claude; exit 0 allows it.
"""
import json
import re
import sys

# python, python3, python3.12, py, python.exe (optionally with a path), then any flags, then a lone "-".
STDIN_PYTHON = re.compile(
    r"(?:^|[\s;&|(/\\])(?:python(?:\d+(?:\.\d+)?)?|py)(?:\.exe)?(?:\s+-[A-Za-z]+)*\s+-(?=\s|$|[;&|)<])"
)

MESSAGE = (
    "Blocked by .claude/hooks/block_stdin_scripts.py: {why}. "
    "Write the code to a script file under D:/Praverse/session-work/<date>/ and run it with "
    "\"python -I path/to/script.py\" (a file can be read, kept and re-run; stdin scripts and heredocs cannot)."
)


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if data.get("tool_name") != "Bash":
        return 0
    command = (data.get("tool_input") or {}).get("command") or ""
    if "<<" in command:
        why = "the command contains a heredoc (\"<<\")"
    elif STDIN_PYTHON.search(command):
        why = "the command runs Python from stdin (\"python -\")"
    else:
        return 0
    print(MESSAGE.format(why=why), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
