"""Make a trailing slash optional on every URL.

`APPEND_SLASH` is False in this application and each route accepts exactly one
form: 188 routes require a trailing slash, 154 refuse one, and which is which
varies route by route with no pattern a user could learn. Getting it wrong
returns a 404 that reads as "this page does not exist" rather than "you typed a
slash", so a copied or hand-edited URL fails for a reason nobody can see.

This middleware makes both forms work. On a 404 it tries the other form, and if
that one resolves it redirects there. Nothing else changes: the URLconf, the
templates and every existing link are untouched, and a path that genuinely does
not exist still 404s.

Why this rather than rewriting the URLs to drop the slash: that would mean
editing 188 route definitions and 128 template links in a codebase with no test
coverage, where a single missed link becomes exactly the 404 this is meant to
remove. This cannot introduce one -- it only ever turns a 404 into a working
page.

Only GET and HEAD are redirected. A redirected POST would either lose its body
or silently replay it, and neither is acceptable for a form submission.
"""

from django.http import HttpResponsePermanentRedirect
from django.urls import Resolver404, resolve

SAFE_METHODS = frozenset({"GET", "HEAD"})


class SlashToleranceMiddleware:
    """Redirect to the other trailing-slash form when that is the one that exists."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if response.status_code != 404 or request.method not in SAFE_METHODS:
            return response

        path = request.path_info
        if path in ("", "/"):
            return response

        alternate = path[:-1] if path.endswith("/") else path + "/"
        if not alternate:
            return response

        try:
            resolve(alternate)
        except Resolver404:
            return response

        # 301: the alternate form is the canonical one for this route, and it
        # will not change, so a browser is free to remember it.
        query = request.META.get("QUERY_STRING", "")
        return HttpResponsePermanentRedirect(alternate + ("?" + query if query else ""))
