"""External integration endpoints.

TWO GATES EVERYWHERE IT MATTERS. `external_integrations.execute` says a caller
may run a connector. It says nothing about whether they may see a document or
export a package, and those are checked separately against their own apps' role
maps -- so a connector can never become a way to read content the caller could
not read directly, or to create content they could not create directly.

Cross-tenant is 404, never 403, and the target-domain permission is checked
*before* the target is resolved, so "absent", "belongs to another tenant" and
"you are not allowed" are one indistinguishable answer. That is the Milestone 8
existence-oracle lesson, and it applies with more force here: a connector
endpoint that answered 403 for a package in another tenant would let a caller
enumerate package ids across the deployment.
"""

import os

from django.db import transaction
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status as http_status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import services
from .audit_events import IntegrationEvent, emit
from .config_schema import ConfigurationError, validate_configuration
from .models import (
    Connector,
    ConnectorExecution,
    ConnectorOperation,
    ConnectorStatus,
    ExecutionStatus,
    ResourceType,
    TestStatus,
)
from .permissions import (
    CanCreateConnectors,
    CanEditConnectors,
    CanEnableConnectors,
    CanExecuteConnectors,
    CanTestConnectors,
    CanViewConnectors,
    CanViewExecutionHistory,
    may_create_documents,
    may_export_packages,
    may_view_documents,
)
from .serializers import (
    ConnectionTestSerializer,
    ConnectorCreateSerializer,
    ConnectorSerializer,
    ConnectorUpdateSerializer,
    ExecutionCreateSerializer,
    ExecutionSerializer,
)

TAGS = ["External integrations"]

#: One message for every way a connector reference can fail.
NOT_FOUND_MESSAGE = "No such connector."


class IntegrationPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


def _tenant_or_403():
    from tenancy.context import TenantScopeMissing, current_tenant

    try:
        return current_tenant()
    except TenantScopeMissing:
        raise PermissionDenied("Tenant context is required.") from None


def _get_connector_or_404(public_id, tenant):
    connector = (
        Connector.objects.filter(public_id=public_id, tenant=tenant)
        .select_related("credential_reference", "created_by")
        .first()
    )
    if connector is None:
        raise NotFound(NOT_FOUND_MESSAGE)
    return connector


def _credential_block(connector):
    """The credential's identity, resolvability and nothing else."""
    reference = getattr(connector, "credential_reference", None)
    if reference is None:
        return None
    from .secrets import environment_variable_name

    name = environment_variable_name(connector, reference)
    return {
        "public_id": str(reference.public_id),
        "credential_type": reference.credential_type,
        "environment_variable": name,
        # Presence only. The value is never read into a variable that could end
        # up anywhere: `in os.environ` answers the question without touching it.
        "is_resolvable": name in os.environ and bool(os.environ.get(name)),
    }


def _advisory_permissions(request, tenant):
    """The caller's connector permissions, computed once per request.

    These depend on the user and the tenant, never on the connector, so
    computing them inside a row loop cost two queries per row per
    permission -- a list of sixty connectors issued four hundred and
    eighty queries it did not need. Hoisting them out is the fix; the
    query-cost test is what makes it stay fixed.
    """
    from .permissions import (
        PERM_EDIT,
        PERM_ENABLE,
        PERM_EXECUTE,
        PERM_TEST,
        has_integration_permission,
    )

    return {
        "can_edit": has_integration_permission(request.user, tenant, PERM_EDIT),
        "can_enable": has_integration_permission(request.user, tenant, PERM_ENABLE),
        "can_test": has_integration_permission(request.user, tenant, PERM_TEST),
        "can_execute": has_integration_permission(request.user, tenant, PERM_EXECUTE),
    }


def _connector_payload(connector, request, tenant, permissions=None):
    return {
        "public_id": str(connector.public_id),
        "name": connector.name,
        "description": connector.description,
        "connector_type": connector.connector_type,
        "status": connector.status,
        "configuration": connector.configuration,
        "configuration_version": connector.configuration_version,
        "last_tested_at": connector.last_tested_at,
        "last_test_status": connector.last_test_status,
        "created_at": connector.created_at,
        "credential": _credential_block(connector),
        "permissions": (
            permissions if permissions is not None else _advisory_permissions(request, tenant)
        ),
    }


def _execution_payload(execution):
    return {
        "public_id": str(execution.public_id),
        "connector_public_id": str(execution.connector.public_id),
        "operation": execution.operation,
        "status": execution.status,
        "resource_type": execution.resource_type,
        "resource_public_id": execution.resource_public_id,
        "snapshot_public_id": execution.snapshot_public_id,
        "manifest_checksum": execution.manifest_checksum,
        "requested_at": execution.requested_at,
        "started_at": execution.started_at,
        "finished_at": execution.finished_at,
        "attempt_count": execution.attempt_count,
        "connector_configuration_version": execution.connector_configuration_version,
        "error_code": execution.error_code,
        "external_reference": execution.external_reference,
        "correlation_id": execution.correlation_id,
        "request_summary": execution.request_summary,
        "response_summary": execution.response_summary,
    }


class ConnectorListCreateView(APIView):
    pagination_class = IntegrationPagination

    def get_permissions(self):
        if self.request.method == "POST":
            return [CanCreateConnectors()]
        return [CanViewConnectors()]

    @extend_schema(tags=TAGS, responses=ConnectorSerializer(many=True))
    def get(self, request):
        tenant = _tenant_or_403()
        # `select_related` on the credential reference keeps the per-row
        # credential block from costing a query each -- the list is measured for
        # invariance across sizes, not for an absolute number.
        queryset = (
            Connector.objects.for_tenant(tenant)
            .exclude(status=ConnectorStatus.ARCHIVED)
            .select_related("credential_reference", "created_by")
        )
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        # Once for the request, not once per row.
        permissions = _advisory_permissions(request, tenant)
        payload = [_connector_payload(c, request, tenant, permissions) for c in page]
        return paginator.get_paginated_response(ConnectorSerializer(payload, many=True).data)

    @extend_schema(tags=TAGS, request=ConnectorCreateSerializer, responses=ConnectorSerializer)
    def post(self, request):
        tenant = _tenant_or_403()
        serializer = ConnectorCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            connector = services.create_connector(
                tenant=tenant,
                actor=request.user,
                name=serializer.validated_data["name"],
                description=serializer.validated_data.get("description", ""),
                connector_type=serializer.validated_data["connector_type"],
                configuration=serializer.validated_data["configuration"],
                credential=serializer.validated_data.get("credential"),
            )
        except ConfigurationError as exc:
            # The enumerated code, and the safe sentence that goes with it.
            # Never the offending value: a rejected `base_url` echoed back is a
            # reflection point, and a rejected header name confirms the list.
            raise ValidationError({"code": exc.code, "detail": str(exc)}) from None

        connector = _get_connector_or_404(connector.public_id, tenant)
        return Response(
            ConnectorSerializer(_connector_payload(connector, request, tenant)).data,
            status=http_status.HTTP_201_CREATED,
        )


class ConnectorDetailView(APIView):
    def get_permissions(self):
        if self.request.method == "PATCH":
            return [CanEditConnectors()]
        return [CanViewConnectors()]

    @extend_schema(tags=TAGS, responses=ConnectorSerializer)
    def get(self, request, public_id):
        tenant = _tenant_or_403()
        connector = _get_connector_or_404(public_id, tenant)
        return Response(ConnectorSerializer(_connector_payload(connector, request, tenant)).data)

    @extend_schema(tags=TAGS, request=ConnectorUpdateSerializer, responses=ConnectorSerializer)
    def patch(self, request, public_id):
        tenant = _tenant_or_403()
        connector = _get_connector_or_404(public_id, tenant)
        serializer = ConnectorUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        try:
            services.update_connector(
                connector=connector,
                tenant=tenant,
                actor=request.user,
                **serializer.validated_data,
            )
        except ConfigurationError as exc:
            raise ValidationError({"code": exc.code, "detail": str(exc)}) from None
        except services.ConnectorNotExecutable as exc:
            return Response({"detail": str(exc)}, status=http_status.HTTP_409_CONFLICT)

        connector = _get_connector_or_404(public_id, tenant)
        return Response(ConnectorSerializer(_connector_payload(connector, request, tenant)).data)


class _StatusChangeView(APIView):
    permission_classes = [CanEnableConnectors]
    target_status = ConnectorStatus.ACTIVE

    @extend_schema(tags=TAGS, request=None, responses=ConnectorSerializer)
    def post(self, request, public_id):
        tenant = _tenant_or_403()
        connector = _get_connector_or_404(public_id, tenant)
        try:
            services.set_connector_status(
                connector=connector, tenant=tenant, actor=request.user, status=self.target_status
            )
        except services.ConnectorNotExecutable as exc:
            return Response({"detail": str(exc)}, status=http_status.HTTP_409_CONFLICT)
        connector = _get_connector_or_404(public_id, tenant)
        return Response(ConnectorSerializer(_connector_payload(connector, request, tenant)).data)


class ConnectorEnableView(_StatusChangeView):
    target_status = ConnectorStatus.ACTIVE


class ConnectorDisableView(_StatusChangeView):
    target_status = ConnectorStatus.DISABLED


class ConnectorArchiveView(_StatusChangeView):
    """Retire a connector. There is no delete.

    Executions reference the connector and are evidence of what was transferred;
    deleting the row would strand that history, so a connector is archived and
    the `PROTECT` foreign key makes the alternative impossible anyway.
    """

    target_status = ConnectorStatus.ARCHIVED


class ConnectorTestView(APIView):
    """A minimal, non-destructive reachability check.

    `GET` against the configured health path, or the prefix itself. Never a
    write: a connection test that created something remote would be a transfer
    nobody asked for, performed by a button labelled "test".

    Synchronous because it is tightly bounded -- one request, connector
    timeouts, a discarded body.
    """

    permission_classes = [CanTestConnectors]

    @extend_schema(tags=TAGS, request=None, responses=ConnectionTestSerializer)
    def post(self, request, public_id):
        from .netpolicy import DestinationRefused, build_url
        from .secrets import SecretUnavailable, auth_headers
        from .transport import TransportError, TransportErrorCode, perform_request

        tenant = _tenant_or_403()
        connector = _get_connector_or_404(public_id, tenant)

        try:
            config = validate_configuration(connector.connector_type, connector.configuration)
        except ConfigurationError as exc:
            return self._result(
                connector, tenant, request, TestStatus.UNREACHABLE, error_code=exc.code
            )

        try:
            url = build_url(
                base_url=config["base_url"],
                allowed_path_prefix=config["allowed_path_prefix"],
                relative_path=config.get("health_path") or "",
            )
        except DestinationRefused as exc:
            return self._result(
                connector, tenant, request, TestStatus.UNREACHABLE, error_code=exc.code
            )

        headers = {}
        reference = getattr(connector, "credential_reference", None)
        if reference is not None:
            try:
                headers = auth_headers(connector, reference)
            except SecretUnavailable:
                return self._result(
                    connector,
                    tenant,
                    request,
                    TestStatus.UNAUTHORISED,
                    error_code=TransportErrorCode.CREDENTIAL_UNAVAILABLE,
                )

        try:
            response = perform_request(
                connector=connector,
                configuration=config,
                method="GET",
                url=url,
                headers=headers,
                # A health check reads a token's worth of body and no more.
                max_response_bytes=4096,
            )
        except TransportError as exc:
            state = (
                TestStatus.UNAUTHORISED
                if exc.code == TransportErrorCode.AUTH_FAILED
                else TestStatus.UNREACHABLE
            )
            return self._result(connector, tenant, request, state, error_code=exc.code)

        return self._result(
            connector,
            tenant,
            request,
            TestStatus.REACHABLE,
            latency_ms=response.latency_ms,
            authenticated=bool(headers),
        )

    def _result(
        self,
        connector,
        tenant,
        request,
        state,
        *,
        latency_ms=None,
        error_code="",
        authenticated=False,
    ):
        services.record_test_result(
            connector=connector,
            tenant=tenant,
            actor=request.user,
            test_status=state,
            latency_ms=latency_ms,
            error_code=error_code,
        )
        return Response(
            ConnectionTestSerializer(
                {
                    "reachable": state == TestStatus.REACHABLE,
                    "authenticated": authenticated and state == TestStatus.REACHABLE,
                    "status": state,
                    "latency_ms": latency_ms,
                    "error_code": error_code,
                }
            ).data
        )


class ConnectorExecutionListCreateView(APIView):
    """Queue a transfer, or list this connector's history.

    Creation is throttled by scope. Not a quota and not billing -- just a
    ceiling on how fast one account can queue remote work, so a loop in a client
    costs a rate-limit response instead of a thousand outbound requests.
    """

    pagination_class = IntegrationPagination
    throttle_scope = "external_execution_create"

    def get_permissions(self):
        if self.request.method == "POST":
            return [CanExecuteConnectors()]
        return [CanViewExecutionHistory()]

    def get_throttles(self):
        if self.request.method == "POST":
            return [ScopedRateThrottle()]
        return []

    @extend_schema(tags=TAGS, responses=ExecutionSerializer(many=True))
    def get(self, request, public_id):
        tenant = _tenant_or_403()
        connector = _get_connector_or_404(public_id, tenant)
        queryset = services.executions_for(connector, tenant)
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        payload = [_execution_payload(e) for e in page]
        return paginator.get_paginated_response(ExecutionSerializer(payload, many=True).data)

    @extend_schema(
        tags=TAGS,
        request=ExecutionCreateSerializer,
        description=(
            "Queue one transfer.\n\n"
            "`payload` is validated by the schema belonging to the named "
            "operation, so its shape depends on `operation`. It is typed as "
            "an object here because the choice is made at runtime; the "
            "fields are:\n\n"
            "**`import_document`** - `external_object_id`, `relative_path` "
            "(relative to the connector prefix), `title`, `document_type` "
            "(**required**, one of the document platform types -- the same "
            "constraint the upload endpoint applies) and an optional "
            "`declared_mime`.\n\n"
            "**`push_frozen_package`** - `package_public_id` (must name a "
            "FROZEN package) and an optional `relative_path`.\n\n"
            "Unknown fields are rejected, and `relative_path` may only "
            "extend the connector prefix -- it can never name another host."
        ),
        responses={
            201: ExecutionSerializer,
            200: OpenApiResponse(
                response=ExecutionSerializer,
                description=(
                    "This exact transfer was already requested; the existing execution is "
                    "returned rather than a second one being started."
                ),
            ),
            403: OpenApiResponse(
                description=(
                    "The caller may run connectors but lacks the permission the operation's "
                    "target domain requires -- document view and package export for a package "
                    "transfer, document creation for an import."
                )
            ),
        },
    )
    def post(self, request, public_id):
        tenant = _tenant_or_403()
        connector = _get_connector_or_404(public_id, tenant)

        serializer = ExecutionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        operation = serializer.validated_data["operation"]
        payload = serializer.validated_data["payload"]

        if operation == ConnectorOperation.PUSH_FROZEN_PACKAGE:
            return self._queue_package_push(request, tenant, connector, payload)
        return self._queue_document_import(request, tenant, connector, payload)

    # -- operations ---------------------------------------------------------
    def _queue_document_import(self, request, tenant, connector, payload):
        # Second gate: importing creates a document, so the caller must be
        # allowed to create documents. Checked before anything else happens.
        if not may_create_documents(request.user, tenant):
            raise PermissionDenied("Importing a document requires permission to create documents.")

        summary = {
            "operation": ConnectorOperation.IMPORT_DOCUMENT,
            "external_object_id": payload["external_object_id"],
            "relative_path": payload["relative_path"],
            "title": payload["title"],
            "document_type": payload["document_type"],
            # Carried through, not dropped. The document platform compares
            # the declared type against the detected one, so discarding what
            # the caller declared would silently turn that comparison into
            # detected-versus-a-guess-from-the-filename.
            "declared_mime": payload.get("declared_mime", ""),
        }
        return self._create(
            request,
            tenant,
            connector,
            operation=ConnectorOperation.IMPORT_DOCUMENT,
            idempotency_parts=[payload["external_object_id"], payload["relative_path"]],
            request_summary=summary,
        )

    def _queue_package_push(self, request, tenant, connector, payload):
        from submission_packages.models import PackageStatus, SubmissionPackage

        # Both target-domain gates, checked BEFORE the package is resolved, so
        # a caller without them cannot learn whether a package id exists.
        if not may_export_packages(request.user, tenant):
            raise PermissionDenied(
                "Transferring a package requires permission to export submission packages."
            )
        if not may_view_documents(request.user, tenant):
            raise PermissionDenied(
                "Transferring a package requires permission to view its documents."
            )

        package = (
            SubmissionPackage.objects.filter(public_id=payload["package_public_id"], tenant=tenant)
            .select_related("snapshot")
            .first()
        )
        if package is None:
            raise NotFound("No such submission package.")
        if package.status != PackageStatus.FROZEN:
            return Response(
                {"detail": "Only a frozen package can be transferred."},
                status=http_status.HTTP_409_CONFLICT,
            )
        snapshot = getattr(package, "snapshot", None)
        if snapshot is None:
            return Response(
                {"detail": "This package has no frozen manifest."},
                status=http_status.HTTP_409_CONFLICT,
            )

        summary = {
            "operation": ConnectorOperation.PUSH_FROZEN_PACKAGE,
            "resource_type": ResourceType.SUBMISSION_PACKAGE,
            "resource_public_id": str(package.public_id),
            "snapshot_public_id": str(snapshot.public_id),
            "manifest_checksum": snapshot.manifest_checksum,
            "entry_count": snapshot.entry_count,
            "relative_path": payload.get("relative_path", "") or "",
        }
        return self._create(
            request,
            tenant,
            connector,
            operation=ConnectorOperation.PUSH_FROZEN_PACKAGE,
            resource_type=ResourceType.SUBMISSION_PACKAGE,
            resource_public_id=str(package.public_id),
            snapshot_public_id=str(snapshot.public_id),
            manifest_checksum=snapshot.manifest_checksum,
            # The manifest checksum, never the package name: a name is editable
            # and a key built from one would let the same transfer run twice.
            idempotency_parts=[str(snapshot.public_id), snapshot.manifest_checksum],
            request_summary=summary,
        )

    def _create(self, request, tenant, connector, **kwargs):
        from .tasks import run_connector_execution

        try:
            execution = services.create_execution(
                connector=connector, tenant=tenant, actor=request.user, **kwargs
            )
        except services.DuplicateExecution as exc:
            # 200, not 201 and not an error: the caller asked for a transfer
            # that already exists, and the useful answer is the one that exists.
            return Response(
                ExecutionSerializer(_execution_payload(exc.execution)).data,
                status=http_status.HTTP_200_OK,
            )
        except services.ConnectorNotExecutable as exc:
            return Response({"detail": str(exc)}, status=http_status.HTTP_409_CONFLICT)

        # On commit. `create_execution` closes its own transaction, so this is
        # ordinarily immediate; it matters if this view is ever called inside
        # one, and a worker that claimed an uncommitted execution would find
        # nothing and silently do nothing.
        transaction.on_commit(lambda: run_connector_execution.delay(execution.pk, tenant.pk))
        execution.refresh_from_db()
        return Response(
            ExecutionSerializer(_execution_payload(execution)).data,
            status=http_status.HTTP_201_CREATED,
        )


class ExecutionDetailView(APIView):
    permission_classes = [CanViewExecutionHistory]

    @extend_schema(tags=TAGS, responses=ExecutionSerializer)
    def get(self, request, public_id):
        tenant = _tenant_or_403()
        execution = (
            ConnectorExecution.objects.for_tenant(tenant)
            .filter(public_id=public_id)
            .select_related("connector")
            .first()
        )
        if execution is None:
            raise NotFound("No such execution.")
        return Response(ExecutionSerializer(_execution_payload(execution)).data)


class ExecutionCancelView(APIView):
    """Cancel a queued execution before it runs.

    Only from QUEUED. A RUNNING execution may already have sent bytes, and
    marking it cancelled would make the record say something that is not true.
    """

    permission_classes = [CanExecuteConnectors]

    @extend_schema(tags=TAGS, request=None, responses=ExecutionSerializer)
    def post(self, request, public_id):
        tenant = _tenant_or_403()
        execution = (
            ConnectorExecution.objects.for_tenant(tenant)
            .filter(public_id=public_id)
            .select_related("connector")
            .first()
        )
        if execution is None:
            raise NotFound("No such execution.")
        if execution.status != ExecutionStatus.QUEUED:
            return Response(
                {"detail": "Only a queued execution can be cancelled."},
                status=http_status.HTTP_409_CONFLICT,
            )

        services.finish_execution(
            execution=execution, status=ExecutionStatus.CANCELLED, error_code="CANCELLED_BY_USER"
        )
        execution.refresh_from_db()
        emit(
            event_type=IntegrationEvent.EXECUTION_CANCELLED,
            resource_id=execution.public_id,
            actor=request.user,
            tenant_id=tenant.pk,
            payload={
                "action": "cancelled",
                "execution_public_id": str(execution.public_id),
                "connector_public_id": str(execution.connector.public_id),
            },
        )
        return Response(ExecutionSerializer(_execution_payload(execution)).data)
