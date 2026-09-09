"""Emit every company_site URL as Markdown, with the exact trailing slash.

APPEND_SLASH is False in this application, so Django never redirects /path to
/path/ or back. Each route accepts exactly one of the two forms, and which one
varies route by route. A wrong slash produces a 404 that reads as "this page
does not exist", which is why this list is worth having.

Ports are annotated from infra/nginx/nginx.conf: 8090 carries /adminmaster/ and
/admin/, 8080 carries everything else and refuses user management.

    docker compose exec -T company_site python dump_routes.py > ROUTES.md
"""

import os
import re

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "RAAI.settings_integration")
django.setup()

from django.urls import get_resolver  # noqa: E402

#: Paths 8080 refuses -- user management and the Django admin.
ADMIN_ONLY_EXACT = {
    "adminmaster/view_users",
    "adminmaster/add_user",
}
ADMIN_ONLY_PREFIX = ("adminmaster/edit_user/", "adminmaster/delete_user/", "admin/")


def collect():
    routes = []

    def walk(resolver, prefix=""):
        for pattern in resolver.url_patterns:
            if hasattr(pattern, "url_patterns"):
                walk(pattern, prefix + str(pattern.pattern))
            else:
                routes.append(
                    (prefix + str(pattern.pattern), getattr(pattern, "name", None) or "")
                )

    walk(get_resolver())
    return routes


def ports_for(path):
    if path in ADMIN_ONLY_EXACT or path.startswith(ADMIN_ONLY_PREFIX):
        return "8090 only"
    if path == "adminmaster/adminbase":
        return "8090 (8080 redirects here)"
    if path.startswith("adminmaster/"):
        return "8080 + 8090"
    return "8080"


def main():
    routes = collect()
    seen = set()
    groups = {"RATools": [], "AIDatabase": [], "AdminMaster": [], "Django admin": [], "Root": []}

    for path, name in sorted(set(routes)):
        if path.startswith("^"):  # static/media catch-alls
            continue
        if (path, name) in seen:
            continue
        seen.add((path, name))
        if path.startswith("ratools/"):
            group = "RATools"
        elif path.startswith("aidatabase/"):
            group = "AIDatabase"
        elif path.startswith("adminmaster/"):
            group = "AdminMaster"
        elif path.startswith("admin/"):
            group = "Django admin"
        else:
            group = "Root"
        groups[group].append((path, name))

    # Django's own admin contributes ~377 auto-generated routes that nobody
    # navigates by hand; they are counted but not listed.
    listed = {k: v for k, v in groups.items() if k != "Django admin"}
    total = sum(len(v) for v in listed.values())
    with_slash = sum(1 for v in listed.values() for p, _ in v if p.endswith("/"))

    print("# company_site — URL reference\n")
    print("Generated from the live Django URLconf, not from documentation.\n")
    print("**`APPEND_SLASH` is `False`.** Django does not redirect `/path` to `/path/`")
    print("or back, and each route accepts only one of the two forms. Copy the path")
    print("exactly as written below, slash included or omitted as shown — a wrong")
    print("slash returns a 404 that looks like the page does not exist.\n")
    print("| | |")
    print("|---|---|")
    print(f"| Routes listed | {total} |")
    print(f"| Django admin routes (auto-generated, not listed) | {len(groups['Django admin'])} |")
    print(f"| Require a trailing slash | {with_slash} |")
    print(f"| Must omit the trailing slash | {total - with_slash} |")
    print()
    print("## Ports\n")
    print("| Port | Serves |")
    print("|---|---|")
    print("| **8080** | Everything user-facing. Refuses user management and `/admin/`. |")
    print("| **8090** | The admin console: all of `/adminmaster/` plus `/admin/`. |")
    print()
    print("`/adminmaster/login/` works on both — an admin has to authenticate on the")
    print("origin they will use, because the session cookie is per-origin.\n")
    print("---\n")

    for group in ("Root", "RATools", "AIDatabase", "AdminMaster"):
        rows = groups[group]
        if not rows:
            continue
        print(f"## {group}  ({len(rows)} routes)\n")
        print("| URL | Trailing slash | Port | View name |")
        print("|---|---|---|---|")
        for path, name in rows:
            slash = "yes" if path.endswith("/") else "**no**"
            display = "/" + path
            # Django's converter syntax is clearer than the raw regex for a reader.
            display = re.sub(r"<([a-z_]+):([a-z_]+)>", r"<\2>", display)
            print(f"| `{display}` | {slash} | {ports_for(path)} | `{name}` |")
        print()


if __name__ == "__main__":
    main()
