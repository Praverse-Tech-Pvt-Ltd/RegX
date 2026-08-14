"""Text-only extractor for the company Django route table.

Deliberately parses the urls.py/views.py files as TEXT (no imports, no
bytecode) so that running it never writes __pycache__ into the read-only
company source tree.
"""

import re
import sys
from pathlib import Path

SRC = Path(sys.argv[1])
OUT = Path(sys.argv[2])

PATH_RE = re.compile(
    r"""path\(\s*["']([^"']*)["']\s*,\s*(?:views\.)?([A-Za-z_][A-Za-z0-9_]*)""",
)

APPS = [
    ("RATools", "/ratools/"),
    ("AIDatabase", "/aidatabase/"),
    ("AdminMaster", "/adminmaster/"),
]


def view_flags(views_src: str, name: str) -> tuple[bool, str]:
    """Return (login_required, template) for a view, by text inspection."""
    m = re.search(rf"^(?:@[^\n]*\n)*def {re.escape(name)}\(", views_src, re.M)
    if not m:
        return False, ""
    decorators = views_src[m.start(): m.start() + (m.end() - m.start())]
    login = "login_required" in decorators
    # body = up to the next top-level def
    body_start = m.end()
    nxt = re.search(r"^def ", views_src[body_start:], re.M)
    body = views_src[body_start: body_start + (nxt.start() if nxt else 4000)]
    tpl = re.search(r"""render\(\s*request\s*,\s*["']([^"']+)["']""", body)
    return login, tpl.group(1) if tpl else ""


rows = []
for app, prefix in APPS:
    urls_src = (SRC / app / "urls.py").read_text(encoding="utf-8", errors="replace")
    views_src = (SRC / app / "views.py").read_text(encoding="utf-8", errors="replace")
    seen = set()
    for route, view in PATH_RE.findall(urls_src):
        full = prefix + route
        if full in seen:
            continue
        seen.add(full)
        login, tpl = view_flags(views_src, view)
        rows.append((app, full, view, "yes" if login else "no", tpl))

lines = [
    "| App | Route | View | Login required | Template |",
    "| --- | --- | --- | --- | --- |",
]
for app, full, view, login, tpl in rows:
    lines.append(f"| {app} | `{full}` | `{view}` | {login} | {tpl or '—'} |")

OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"{len(rows)} routes -> {OUT}")
by_app: dict[str, int] = {}
for app, *_ in rows:
    by_app[app] = by_app.get(app, 0) + 1
print(by_app)
print("login-required:", sum(1 for r in rows if r[3] == "yes"))
