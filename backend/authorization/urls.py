from django.urls import path

from . import views

urlpatterns = [
    path("roles/", views.role_list_view, name="role-list"),
    path("permissions/", views.permission_list_view, name="permission-list"),
    path("effective/", views.effective_permissions_view, name="permissions-effective"),
    path("mine/", views.my_roles_view, name="roles-mine"),
    path("mfa-status/", views.mfa_status_view, name="mfa-status"),
]
