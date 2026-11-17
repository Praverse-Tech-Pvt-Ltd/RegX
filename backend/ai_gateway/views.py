"""AI gateway endpoints: platform switch, metrics, tenant health check.

There is no AI feature here. The health check is the smallest call that proves
the whole path (tenant check, switch, configuration, breaker, provider, record)
and shows what a page gets back when AI is off or down: HTTP 200 with
`status` != "ok" and a message to display, never an error page.
"""

from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from . import service
from .config import config_problem, load_config
from .metrics import summarise
from .models import AISwitch
from .permissions import IsPlatformAdmin, IsTenantAdmin


class SwitchSerializer(serializers.Serializer):
    setting_enabled = serializers.BooleanField(read_only=True)
    switch_enabled = serializers.BooleanField()
    effective_enabled = serializers.BooleanField(read_only=True)
    provider = serializers.CharField(read_only=True)
    configuration_problem = serializers.CharField(read_only=True, allow_null=True)
    updated_at = serializers.DateTimeField(read_only=True, allow_null=True)


class AIResultSerializer(serializers.Serializer):
    status = serializers.CharField()
    message = serializers.CharField(allow_blank=True)
    reason_code = serializers.CharField(allow_blank=True)
    text = serializers.CharField(allow_null=True)
    prompt_id = serializers.CharField()
    prompt_version = serializers.IntegerField()
    call_id = serializers.CharField(allow_null=True)


def _switch_state() -> dict:
    from django.conf import settings

    row = AISwitch.objects.filter(pk=AISwitch.SINGLETON_PK).first()
    config = load_config()
    return {
        "setting_enabled": bool(settings.REGX_AI_ENABLED),
        "switch_enabled": bool(row and row.enabled),
        "effective_enabled": service.is_enabled(),
        "provider": config.provider,
        # A code such as API_KEY_MISSING, never the value of anything.
        "configuration_problem": config_problem(config),
        "updated_at": row.updated_at if row else None,
    }


class AISwitchView(APIView):
    permission_classes = [IsPlatformAdmin]

    @extend_schema(responses=SwitchSerializer)
    def get(self, request):
        return Response(SwitchSerializer(_switch_state()).data)

    @extend_schema(request=SwitchSerializer, responses=SwitchSerializer)
    def put(self, request):
        incoming = SwitchSerializer(data=request.data)
        incoming.is_valid(raise_exception=True)
        with transaction.atomic():
            AISwitch.objects.update_or_create(
                pk=AISwitch.SINGLETON_PK,
                defaults={
                    "enabled": incoming.validated_data["switch_enabled"],
                    "updated_by": request.user,
                },
            )
        return Response(SwitchSerializer(_switch_state()).data)


class AIMetricsView(APIView):
    permission_classes = [IsPlatformAdmin]

    @extend_schema(responses={200: dict})
    def get(self, request):
        try:
            days = int(request.query_params.get("days", 7))
        except ValueError:
            days = 7
        return Response(summarise(days=min(max(days, 1), 90)))


class AIHealthCheckView(APIView):
    permission_classes = [IsTenantAdmin]

    @extend_schema(request=None, responses=AIResultSerializer)
    def post(self, request):
        result = service.generate("gateway.health_check", user=request.user)
        return Response(AIResultSerializer(result).data)
