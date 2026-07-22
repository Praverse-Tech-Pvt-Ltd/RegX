from django.urls import path

from . import views

urlpatterns = [
    path("roles/", views.role_list_view, name="role-list"),
    path("permissions/", views.permission_list_view, name="permission-list"),
]
