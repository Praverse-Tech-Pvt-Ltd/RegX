from django.urls import path

from .views import AIHealthCheckView, AIMetricsView, AISwitchView

urlpatterns = [
    path("ai/switch/", AISwitchView.as_view(), name="ai-switch"),
    path("ai/metrics/", AIMetricsView.as_view(), name="ai-metrics"),
    path("ai/health-check/", AIHealthCheckView.as_view(), name="ai-health-check"),
]
