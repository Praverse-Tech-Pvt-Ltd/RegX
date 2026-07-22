from django.urls import path

from . import views

urlpatterns = [
    path("setup/", views.mfa_setup_view, name="mfa-setup"),
    path("verify/", views.mfa_verify_view, name="mfa-verify"),
    path("recovery/", views.mfa_recovery_view, name="mfa-recovery"),
]
