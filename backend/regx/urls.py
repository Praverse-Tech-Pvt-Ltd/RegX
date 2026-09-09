"""REGX root URL configuration."""

from csp.decorators import csp_update
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("api/regx/v1/", include("regx.api_v1_urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    # Swagger UI's template carries an inline <script> and inline <style>, which
    # the global `script-src 'self'` / `style-src 'self'` policy blocks. Relaxed
    # for this one view rather than globally: the docs page renders no
    # user-supplied content, so inline execution here cannot carry a payload the
    # way it could on an application page.
    path(
        "api/docs/",
        csp_update(SCRIPT_SRC=["'unsafe-inline'"], STYLE_SRC=["'unsafe-inline'"])(
            SpectacularSwaggerView.as_view(url_name="schema")
        ),
        name="swagger-ui",
    ),
]
