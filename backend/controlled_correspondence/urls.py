from django.urls import path

from .views import (
    BestPracticeCategoriesView,
    BestPracticeListView,
    DraftDetailView,
    DraftListView,
)

urlpatterns = [
    path(
        "controlled-correspondence/best-practices/",
        BestPracticeListView.as_view(),
        name="cc-best-practice-list",
    ),
    path(
        "controlled-correspondence/best-practices/categories/",
        BestPracticeCategoriesView.as_view(),
        name="cc-best-practice-categories",
    ),
    path(
        "controlled-correspondence/drafts/",
        DraftListView.as_view(),
        name="cc-draft-list",
    ),
    path(
        "controlled-correspondence/drafts/<uuid:public_id>/",
        DraftDetailView.as_view(),
        name="cc-draft-detail",
    ),
]
