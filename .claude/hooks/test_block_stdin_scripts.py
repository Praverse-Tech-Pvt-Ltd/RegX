"""Checks for block_stdin_scripts.py (the PreToolUse hook). Run: python -I .claude/hooks/test_block_stdin_scripts.py

Feeds the hook the JSON Claude Code sends for a Bash call and checks the exit code:
2 = blocked (with a message on stderr), 0 = allowed.
"""
import json
import pathlib
import subprocess
import sys

HOOK = pathlib.Path(__file__).with_name("block_stdin_scripts.py")

BLOCKED = [
    "cat > x.py <<'EOF'\nprint(1)\nEOF",
    "python - <<'X'\nX",
    "python3 <<EOF\nprint(1)\nEOF",
    "git commit -F - <<EOF\nmsg\nEOF",
    "python -",
    "python -I -",
    "python -I - < script.py",
    "python3 - arg1",
    "cd tools && python -",
    "echo 'print(1)' | python -",
    "echo 'print(1)' | python -I -",
    "py -",
    "python.exe -",
    "/usr/bin/python3.12 -I -",
]
ALLOWED = [
    "python -I path/to/script.py",
    "python path/to/script.py",
    "python -I D:/Praverse/session-work/tools/build.py arg -x",
    "python -m pytest -q",
    "python --version",
    "python -c \"print(1)\"",
    "git log --oneline -5",
    "ls -la",
    "echo a < input.txt",
    "npm run lint -- --fix",
]


def run(command, tool="Bash"):
    payload = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {"command": command}}
    p = subprocess.run([sys.executable, "-I", str(HOOK)], input=json.dumps(payload), capture_output=True, text=True)
    return p.returncode, p.stderr


failures = []
for c in BLOCKED:
    code, err = run(c)
    if code != 2 or "script file" not in err:
        failures.append(f"should block (exit 2 + message): {c!r} -> exit {code}, stderr {err[:80]!r}")
for c in ALLOWED:
    code, err = run(c)
    if code != 0:
        failures.append(f"should allow: {c!r} -> exit {code}, stderr {err[:80]!r}")
code, _ = run("python - <<'X'", tool="Read")
if code != 0:
    failures.append(f"other tools are not checked -> exit {code}")
for f in failures:
    print("FAIL", f)
print(f"{len(BLOCKED)} blocked cases, {len(ALLOWED)} allowed cases, {len(failures)} failures")
sys.exit(1 if failures else 0)
