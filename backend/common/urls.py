from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health_view, name="health"),
    path("readiness/", views.readiness_view, name="readiness"),
    path("version/", views.version_view, name="version"),
]
