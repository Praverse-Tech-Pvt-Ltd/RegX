"""Reference audit for the copied company assets.

Builds a token set of every filename-like string appearing in the company's
templates, CSS, JS and Python, then reports which asset files under static/
are referenced by at least one of them.

Deliberately conservative: a file counts as REFERENCED if its basename appears
anywhere in the corpus, even inside a comment, and URL-encoded forms are
decoded first. The aim is to avoid deleting something that is actually used,
not to produce a minimal set.
"""

import collections
import os
import re
import sys
import urllib.parse

ROOT = sys.argv[1]

ASSET_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".bmp",
    ".mp4", ".webm", ".ogg", ".mp3", ".wav",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".pdf", ".docx", ".xlsx", ".csv", ".zip",
}
TEXT_EXT = {".html", ".htm", ".css", ".js", ".py", ".json", ".txt", ".md", ".scss"}

SKIP_DIRS = {".venv", "__pycache__", "node_modules", ".git"}

# Anything that looks like a filename with one of the extensions above.
TOKEN_RE = re.compile(
    r"[A-Za-z0-9_\-.%+()\[\] ]+?\.(?:png|jpe?g|gif|svg|ico|webp|bmp|mp4|webm|ogg|mp3|wav|woff2?|ttf|eot|otf|pdf|docx|xlsx|csv|zip)",
    re.IGNORECASE,
)

tokens: set[str] = set()
corpus_files = 0

for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
    for name in filenames:
        ext = os.path.splitext(name)[1].lower()
        if ext not in TEXT_EXT:
            continue
        path = os.path.join(dirpath, name)
        # Skip the asset trees themselves as corpus EXCEPT css/js, which do
        # reference fonts and background images.
        try:
            data = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        corpus_files += 1
        for m in TOKEN_RE.findall(data):
            pass
        for m in TOKEN_RE.finditer(data):
            raw = m.group(0).strip()
            tokens.add(raw.lower())
            tokens.add(urllib.parse.unquote(raw).lower())
            tokens.add(os.path.basename(raw).lower())
            tokens.add(os.path.basename(urllib.parse.unquote(raw)).lower())

referenced: list[tuple[int, str]] = []
unreferenced: list[tuple[int, str]] = []

for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, "static")):
    dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
    for name in filenames:
        ext = os.path.splitext(name)[1].lower()
        if ext not in ASSET_EXT:
            continue
        path = os.path.join(dirpath, name)
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        key = name.lower()
        hit = key in tokens or urllib.parse.unquote(key) in tokens
        (referenced if hit else unreferenced).append((size, rel))

referenced.sort(reverse=True)
unreferenced.sort(reverse=True)

print(f"corpus files scanned: {corpus_files}, distinct filename tokens: {len(tokens)}")
print()
print(f"REFERENCED   : {len(referenced):5d} files, {sum(s for s, _ in referenced)/1048576:9.1f} MB")
print(f"UNREFERENCED : {len(unreferenced):5d} files, {sum(s for s, _ in unreferenced)/1048576:9.1f} MB")
print()
print("=== TOP 30 UNREFERENCED BY SIZE ===")
for size, rel in unreferenced[:30]:
    print(f"{size/1048576:8.1f} MB  {rel}")
print()
print("=== TOP 15 REFERENCED BY SIZE ===")
for size, rel in referenced[:15]:
    print(f"{size/1048576:8.1f} MB  {rel}")

by_dir: collections.Counter = collections.Counter()
for size, rel in unreferenced:
    by_dir[os.path.dirname(rel)] += size
print()
print("=== UNREFERENCED BY DIRECTORY ===")
for d, s in by_dir.most_common(12):
    print(f"{s/1048576:8.1f} MB  {d}")
