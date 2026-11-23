"""Formulations domain API views. Tenant-scoped, UUID-only, generic 404."""

from contextlib import contextmanager

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status as http_status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from .audit_events import FormulationEvent, emit
from .models import (
    DosingRegimen,
    FormulationComponent,
    FormulationVersion,
    ProductDevelopmentRecord,
)
from .permissions import (
    PERM_CREATE,
    CanCreateFormulations,
    CanEditDraftFormulations,
    CanViewFormulations,
    has_formulation_permission,
)
from .serializers import (
    DosingRegimenSerializer,
    FormulationComponentSerializer,
    FormulationVersionCreateSerializer,
    FormulationVersionSerializer,
    ProductDevelopmentRecordCreateSerializer,
    ProductDevelopmentRecordSerializer,
    ReferenceProductSelectionSerializer,
)


class FormulationsPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


def _get_tenant(request):
    from rest_framework.exceptions import PermissionDenied

    from tenancy.context import TenantScopeMissing, current_tenant

    try:
        return current_tenant()
    except (TenantScopeMissing, Exception) as exc:
        raise PermissionDenied("No active tenant context.") from exc


def _get_product_or_404(public_id, tenant) -> ProductDevelopmentRecord:
    try:
        return ProductDevelopmentRecord.objects.for_tenant(tenant).get(public_id=public_id)
    except ProductDevelopmentRecord.DoesNotExist as exc:
        raise NotFound("Product development record not found.") from exc


def _get_version_or_404(public_id, tenant) -> FormulationVersion:
    try:
        return FormulationVersion.objects.for_tenant(tenant).get(public_id=public_id)
    except FormulationVersion.DoesNotExist as exc:
        raise NotFound("Formulation version not found.") from exc


@contextmanager
def _integrity_error_as_validation_error(message: str):
    """Backstop: a DB CheckConstraint/UniqueConstraint rejection must never
    reach the client as a raw 500 IntegrityError -- serializer-level
    validation is the primary defense (see validate_* methods in
    serializers.py), this is the last line of defense for anything a
    serializer validator doesn't independently catch."""
    try:
        with transaction.atomic():
            yield
    except IntegrityError as exc:
        raise ValidationError({"detail": message}) from exc


class ProductListView(APIView):
    pagination_class = FormulationsPagination

    def get_permissions(self):
        if self.request.method == "POST":
            return [CanCreateFormulations()]
        return [CanViewFormulations()]

    def get(self, request):
        tenant = _get_tenant(request)
        qs = ProductDevelopmentRecord.objects.for_tenant(tenant).order_by("product_code")
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        response = paginator.get_paginated_response(
            ProductDevelopmentRecordSerializer(page, many=True).data
        )
        # Display only: whether this user may create a product in this tenant,
        # so the screen does not offer a button the POST would refuse.
        response.data["can_create"] = has_formulation_permission(request.user, tenant, PERM_CREATE)
        return response

    def post(self, request):
        tenant = _get_tenant(request)
        serializer = ProductDevelopmentRecordCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with _integrity_error_as_validation_error(
            "product_code must be unique within this tenant."
        ):
            product = ProductDevelopmentRecord.objects.create(
                tenant=tenant, created_by=request.user, **serializer.validated_data
            )
            # QA-09: inside the block, so the row and its audit record commit together.
            emit(
                event_type=FormulationEvent.PRODUCT_CREATED,
                resource_id=str(product.public_id),
                tenant_id=tenant.id,
                actor_id=request.user.id,
                actor_email=request.user.email,
            )

        return Response(
            ProductDevelopmentRecordSerializer(product).data, status=http_status.HTTP_201_CREATED
        )


class ProductDetailView(APIView):
    def get_permissions(self):
        return [CanViewFormulations()]

    def get(self, request, public_id):
        tenant = _get_tenant(request)
        product = _get_product_or_404(public_id, tenant)
        return Response(ProductDevelopmentRecordSerializer(product).data)


class SelectReferenceProductView(APIView):
    """Explicit reference-product selection -- never auto-picked, even
    when only one candidate exists. Snapshots the exact identifiers so a
    later FDA data refresh cannot retroactively change what was selected."""

    def get_permissions(self):
        return [CanEditDraftFormulations()]

    def post(self, request, public_id):
        tenant = _get_tenant(request)
        product = _get_product_or_404(public_id, tenant)
        serializer = ReferenceProductSelectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        # QA-09: the change and its audit record commit together or not at all.
        with transaction.atomic():
            product.selected_ob_application_number = data["application_number"]
            product.selected_ob_product_number = data["product_number"]
            product.selected_ob_product_public_id = data["product_public_id"]
            product.selected_ob_release_public_id = data["release_public_id"]
            product.selection_timestamp = timezone.now()
            product.selecting_user = request.user
            product.selection_justification = data.get("justification", "")
            product.save(
                update_fields=[
                    "selected_ob_application_number",
                    "selected_ob_product_number",
                    "selected_ob_product_public_id",
                    "selected_ob_release_public_id",
                    "selection_timestamp",
                    "selecting_user",
                    "selection_justification",
                    "updated_at",
                ]
            )
            emit(
                event_type=FormulationEvent.REFERENCE_PRODUCT_SELECTED,
                resource_id=str(product.public_id),
                tenant_id=tenant.id,
                payload={
                    "product_public_id": str(data["product_public_id"]),
                    "release_public_id": str(data["release_public_id"]),
                },
                actor_id=request.user.id,
                actor_email=request.user.email,
            )
        return Response(ProductDevelopmentRecordSerializer(product).data)


class FormulationVersionListCreateView(APIView):
    pagination_class = FormulationsPagination

    def get_permissions(self):
        if self.request.method == "POST":
            return [CanCreateFormulations()]
        return [CanViewFormulations()]

    def get(self, request, public_id):
        tenant = _get_tenant(request)
        product = _get_product_or_404(public_id, tenant)
        qs = FormulationVersion.objects.filter(product=product).order_by("-version_number")
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(FormulationVersionSerializer(page, many=True).data)

    def post(self, request, public_id):
        tenant = _get_tenant(request)
        product = _get_product_or_404(public_id, tenant)
        serializer = FormulationVersionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        last = (
            FormulationVersion.objects.filter(product=product).order_by("-version_number").first()
        )
        with _integrity_error_as_validation_error(
            "Formulation version could not be created with the given values."
        ):
            version = FormulationVersion.objects.create(
                product=product,
                version_number=(last.version_number + 1) if last else 1,
                created_by=request.user,
                **serializer.validated_data,
            )
            # QA-09: inside the block, so the row and its audit record commit together.
            emit(
                event_type=FormulationEvent.FORMULATION_VERSION_CREATED,
                resource_id=str(version.public_id),
                tenant_id=tenant.id,
                actor_id=request.user.id,
                actor_email=request.user.email,
            )

        return Response(
            FormulationVersionSerializer(version).data, status=http_status.HTTP_201_CREATED
        )


def _version_payload(version, user, tenant) -> dict:
    """The version, what this user may do with it now, and its history."""
    from .approval import available_actions, history

    data = dict(FormulationVersionSerializer(version).data)
    data["available_actions"] = available_actions(version, user, tenant)
    data["history"] = history(version)
    return data


def _require_draft(version) -> None:
    """Components and dosing regimens change only while the version is a draft
    (the database refuses it too, migration 0004)."""
    from .models import FormulationStatus

    if version.status != FormulationStatus.DRAFT:
        raise ValidationError(
            {
                "error_code": "version_not_draft",
                "detail": (
                    f"This version is {version.get_status_display().lower()}, so it cannot be "
                    "changed. A version can be changed only while it is a draft (a reviewer can "
                    "return it to draft); an approved version never changes: create a new version."
                ),
            }
        )


class FormulationVersionDetailView(APIView):
    def get_permissions(self):
        return [CanViewFormulations()]

    def get(self, request, public_id):
        tenant = _get_tenant(request)
        version = _get_version_or_404(public_id, tenant)
        return Response(_version_payload(version, request.user, tenant))


class FormulationVersionTransitionView(APIView):
    """POST submit-review / return / reject / approve (formulations.approval).

    Permission, status, reasons and separation of duties are all checked in
    the service, which raises ApprovalRefused with the HTTP status to use."""

    action: str = ""

    def get_permissions(self):
        return [CanViewFormulations()]

    def post(self, request, public_id):
        from .approval import ApprovalRefused, approve, reject, return_to_draft, submit
        from .serializers import VersionTransitionSerializer

        tenant = _get_tenant(request)
        version = _get_version_or_404(public_id, tenant)
        text = {}
        if self.action != "submit":
            # QA-11: a note or reason that is not text is a 400 with a field
            # error, never a 500 from .strip() in the service.
            serializer = VersionTransitionSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            text = serializer.validated_data
        try:
            if self.action == "submit":
                version = submit(version, request.user, tenant)
            elif self.action == "return":
                version = return_to_draft(version, request.user, tenant, text.get("reason", ""))
            elif self.action == "reject":
                version = reject(version, request.user, tenant, text.get("reason", ""))
            else:
                version = approve(version, request.user, tenant, text.get("note", ""))
        except ApprovalRefused as exc:
            return Response({"error_code": exc.code, "detail": exc.message}, status=exc.status)
        return Response(_version_payload(version, request.user, tenant))


class FormulationComponentListView(APIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [CanCreateFormulations()]
        return [CanViewFormulations()]

    def get(self, request, public_id):
        tenant = _get_tenant(request)
        version = _get_version_or_404(public_id, tenant)
        qs = FormulationComponent.objects.filter(formulation_version=version).order_by(
            "display_order"
        )
        return Response(FormulationComponentSerializer(qs, many=True).data)

    def post(self, request, public_id):
        tenant = _get_tenant(request)
        version = _get_version_or_404(public_id, tenant)
        _require_draft(version)
        # The version gives the product's dosage form, for the per-volume rule.
        serializer = FormulationComponentSerializer(
            data=request.data, context={"formulation_version": version}
        )
        serializer.is_valid(raise_exception=True)
        with _integrity_error_as_validation_error(
            "Formulation component could not be created with the given values."
        ):
            component = FormulationComponent.objects.create(
                formulation_version=version, **serializer.validated_data
            )
            # QA-09: inside the block, so the row and its audit record commit together.
            emit(
                event_type=FormulationEvent.COMPONENT_ADDED,
                resource_id=str(component.public_id),
                tenant_id=tenant.id,
                actor_id=request.user.id,
                actor_email=request.user.email,
            )

        return Response(
            FormulationComponentSerializer(component).data, status=http_status.HTTP_201_CREATED
        )


class DosingRegimenListView(APIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [CanCreateFormulations()]
        return [CanViewFormulations()]

    def get(self, request, public_id):
        tenant = _get_tenant(request)
        version = _get_version_or_404(public_id, tenant)
        qs = DosingRegimen.objects.filter(formulation_version=version).order_by("-created_at")
        return Response(DosingRegimenSerializer(qs, many=True).data)

    def post(self, request, public_id):
        tenant = _get_tenant(request)
        version = _get_version_or_404(public_id, tenant)
        _require_draft(version)
        serializer = DosingRegimenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with _integrity_error_as_validation_error(
            "Dosing regimen could not be created with the given values."
        ):
            regimen = DosingRegimen.objects.create(
                formulation_version=version, **serializer.validated_data
            )
            # QA-09: inside the block, so the row and its audit record commit together.
            emit(
                event_type=FormulationEvent.DOSING_REGIMEN_CHANGED,
                resource_id=str(regimen.public_id),
                tenant_id=tenant.id,
                actor_id=request.user.id,
                actor_email=request.user.email,
            )

        return Response(DosingRegimenSerializer(regimen).data, status=http_status.HTTP_201_CREATED)
