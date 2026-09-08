from decouple import config


def base_url(request):
    """
    Absolute site origin for templates, e.g. "https://example.com".

    BASE_URL is shipped blank in .env.example, and decouple returns "" rather
    than the default for a present-but-blank key -- so fall back to the
    request-derived origin whenever the configured value is blank.
    """
    configured = (config("BASE_URL", default="") or "").strip().rstrip("/")
    return {"base_url": configured or request.build_absolute_uri("/").rstrip("/")}
