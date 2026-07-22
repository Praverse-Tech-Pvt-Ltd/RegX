from django.urls import path

from . import views

urlpatterns = [
    path("", views.tenant_list_view, name="tenant-list"),
    path("<uuid:public_id>/", views.tenant_detail_view, name="tenant-detail"),
    path("<uuid:public_id>/members/", views.tenant_members_view, name="tenant-members"),
]
