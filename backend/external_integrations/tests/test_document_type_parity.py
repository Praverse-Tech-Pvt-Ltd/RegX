"""The connector import path is held to the same document-type rule as upload.

Extracting a shared `documents.ingest` is only worth doing if both callers are
held to the same rules. The pipeline below the API was already shared; the
*request validation above it* was not, and the connector's was looser.

**Django does not enforce `choices` on `objects.create()`.** `full_clean()` does,
and nothing in either write path calls it, so a value that got past request
validation would be stored and nothing downstream would notice. Request
validation is therefore the only place this can be caught, which is why it is
tested here rather than assumed from the model field.

The parity test is the one that matters long-term: it fails if either side ever
grows a type the other does not have, without anybody having to remember to
check.
"""

import json

import pytest

from documents.models import Document, DocumentType, DocumentVersion
from documents.serializers import DocumentCreateSerializer
from external_integrations.models import ConnectorExecution, ExternalObjectLink
from external_integrations.serializers import ImportDocumentPayloadSerializer
from external_integrations.tests.conftest import INTEGRATIONS_API, PDF_BYTES


def _payload(document_type):
    return {
        "external_object_id": "remote-doc-1.pdf",
        "relative_path": "inbox/remote-doc-1.pdf",
        "title": "Imported synthetic document",
        "document_type": document_type,
    }


def _choice_values(field):
    """The values a DRF `ChoiceField` accepts, whatever shape `choices` took."""
    return {str(value) for value in field.choices}


# ---------------------------------------------------------------------------
# Parity
# ---------------------------------------------------------------------------
class TestDocumentTypeParity:
    def test_both_paths_accept_exactly_the_model_enum(self):
        """One authoritative source. Neither path keeps its own list.

        If somebody adds a document type to the enum, both sides gain it. If
        somebody adds one to a hand-maintained list on either side, this fails.
        """
        upload_field = DocumentCreateSerializer().fields["document_type"]
        import_field = ImportDocumentPayloadSerializer().fields["document_type"]

        enum_values = set(DocumentType.values)
        assert _choice_values(upload_field) == enum_values
        assert _choice_values(import_field) == enum_values
        assert _choice_values(upload_field) == _choice_values(import_field)

    def test_the_connector_serializer_derives_from_the_enum_not_a_copy(self):
        """A second hand-maintained list is the thing this milestone must not
        introduce; the field's choices are the enum's, by identity of values."""
        field = ImportDocumentPayloadSerializer().fields["document_type"]
        assert _choice_values(field) == set(DocumentType.values)
        assert len(DocumentType.values) > 1, (
            "the enum must be non-trivial for this to mean anything"
        )

    @pytest.mark.parametrize("document_type", DocumentType.values)
    def test_every_type_the_upload_accepts_the_connector_accepts(self, document_type):
        upload_field = DocumentCreateSerializer().fields["document_type"]
        assert upload_field.run_validation(document_type) == document_type

        serializer = ImportDocumentPayloadSerializer(data=_payload(document_type))
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["document_type"] == document_type

    @pytest.mark.parametrize(
        "document_type",
        ["not_a_type", "OTHER", "', DROP TABLE", "a" * 64, "", "regulatory_submission"],
    )
    def test_an_invalid_type_is_refused_by_both_paths(self, document_type):
        from rest_framework.exceptions import ValidationError as DRFValidationError

        upload_field = DocumentCreateSerializer().fields["document_type"]
        with pytest.raises(DRFValidationError):
            upload_field.run_validation(document_type)

        serializer = ImportDocumentPayloadSerializer(data=_payload(document_type))
        assert not serializer.is_valid()
        assert "document_type" in serializer.errors


# ---------------------------------------------------------------------------
# Through the API
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestInvalidTypeIsRefusedBeforeIngest:
    URL_SUFFIX = "executions/"

    def _post(self, client, connector, document_type):
        return client.post(
            f"{INTEGRATIONS_API}/{connector.public_id}/{self.URL_SUFFIX}",
            {"operation": "import_document", "payload": _payload(document_type)},
            format="json",
        )

    def test_an_invalid_type_is_refused_by_the_api(
        self, client_admin_a, active_connector, connector_secret, fake_remote
    ):
        response = self._post(client_admin_a, active_connector, "definitely_not_a_type")
        assert response.status_code == 400

    def test_the_ingest_pipeline_is_never_reached(
        self, client_admin_a, active_connector, connector_secret, fake_remote, monkeypatch
    ):
        """Refused above the pipeline, so the pipeline never has to defend
        itself against a value it cannot check."""
        calls = []

        def spy(**kwargs):  # pragma: no cover - must not be called
            calls.append(kwargs)
            raise AssertionError("ingest was reached with an invalid document type")

        monkeypatch.setattr("documents.ingest.ingest_new_document", spy)

        response = self._post(client_admin_a, active_connector, "definitely_not_a_type")
        assert response.status_code == 400
        assert calls == []

    def test_no_remote_request_is_made(
        self, client_admin_a, active_connector, connector_secret, fake_remote
    ):
        self._post(client_admin_a, active_connector, "definitely_not_a_type")
        assert fake_remote.calls == []

    def test_no_execution_document_version_or_link_is_created(
        self, client_admin_a, active_connector, connector_secret, fake_remote
    ):
        self._post(client_admin_a, active_connector, "definitely_not_a_type")
        assert ConnectorExecution.objects.count() == 0
        assert Document.objects.count() == 0
        assert DocumentVersion.objects.count() == 0
        assert ExternalObjectLink.objects.count() == 0

    def test_no_success_audit_is_emitted(
        self, client_admin_a, active_connector, connector_secret, fake_remote
    ):
        from audit.models import AuditEvent

        before = set(
            AuditEvent.objects.filter(resource_type="external_integration").values_list(
                "event_type", flat=True
            )
        )
        self._post(client_admin_a, active_connector, "definitely_not_a_type")
        after = set(
            AuditEvent.objects.filter(resource_type="external_integration").values_list(
                "event_type", flat=True
            )
        )
        assert after == before
        for banned in (
            "external_execution.created",
            "external_execution.started",
            "external_execution.succeeded",
            "external_object.linked",
        ):
            assert banned not in after

    @pytest.mark.parametrize("document_type", DocumentType.values)
    def test_a_valid_type_still_imports_end_to_end(
        self, client_admin_a, active_connector, connector_secret, fake_remote, document_type
    ):
        """Control. A validator that refused everything would pass every test
        above while making the operation useless."""
        fake_remote.body = PDF_BYTES
        response = self._post(client_admin_a, active_connector, document_type)
        assert response.status_code == 201, json.dumps(response.data, default=str)

        execution = ConnectorExecution.objects.get(public_id=response.data["public_id"])
        assert execution.request_summary["document_type"] == document_type

    def test_an_omitted_type_is_refused_exactly_as_the_upload_refuses_one(
        self, client_admin_a, active_connector, connector_secret, fake_remote
    ):
        """Parity includes requiredness.

        The upload endpoint requires `document_type` and offers no default, so
        the connector does too. The previous default was `"other"`, which is not
        a `DocumentType` at all -- there is no honest value to guess, because a
        remote object's type is something the caller knows and this app does
        not.
        """
        response = client_admin_a.post(
            f"{INTEGRATIONS_API}/{active_connector.public_id}/executions/",
            {
                "operation": "import_document",
                "payload": {
                    "external_object_id": "remote-doc-1.pdf",
                    "relative_path": "inbox/remote-doc-1.pdf",
                    "title": "Imported synthetic document",
                },
            },
            format="json",
        )
        assert response.status_code == 400
        assert ConnectorExecution.objects.count() == 0
        assert Document.objects.count() == 0

    def test_other_is_not_a_document_type_and_is_refused(
        self, client_admin_a, active_connector, connector_secret, fake_remote
    ):
        """The specific value this milestone was storing before the parity fix.

        `objects.create()` accepted it because Django does not enforce `choices`
        there, so every import wrote a type the enum does not contain and
        nothing complained. Named explicitly so a regression is unambiguous.
        """
        assert "other" not in DocumentType.values
        response = self._post(client_admin_a, active_connector, "other")
        assert response.status_code == 400
        assert Document.objects.count() == 0


# ---------------------------------------------------------------------------
# The web upload path is unchanged
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestWebUploadRegression:
    def test_the_upload_serializer_still_refuses_an_invalid_type(self):
        serializer = DocumentCreateSerializer(
            data={"title": "T", "document_type": "not_a_type", "file": None}
        )
        assert not serializer.is_valid()
        assert "document_type" in serializer.errors

    @pytest.mark.parametrize("document_type", DocumentType.values)
    def test_the_upload_serializer_still_accepts_every_enum_value(self, document_type):
        field = DocumentCreateSerializer().fields["document_type"]
        assert field.run_validation(document_type) == document_type

    def test_both_paths_require_the_field(self):
        """Requiredness is part of parity: neither side invents a type."""
        upload = DocumentCreateSerializer().fields["document_type"]
        connector = ImportDocumentPayloadSerializer().fields["document_type"]
        assert upload.required is True
        assert connector.required is True


@pytest.mark.django_db
class TestTheOperationChecksAgain:
    """The worker does not trust the summary it was handed.

    Same reasoning as re-validating the configuration before a request: a stored
    summary is still a stored value, and `run_import_document` is reachable from
    a task, a retry, and any future caller that did not pass through the
    serializer. A `KeyError` there would surface as `INTERNAL_ERROR`, which tells
    an operator nothing.
    """

    def _execution(self, tenant, admin, connector, summary):
        from external_integrations import services

        return services.create_execution(
            connector=connector,
            tenant=tenant,
            actor=admin,
            operation="import_document",
            idempotency_parts=[str(summary)],
            request_summary=summary,
        )

    @pytest.mark.parametrize("bad", [None, "other", "not_a_type", ""])
    def test_an_invalid_type_in_a_stored_summary_is_an_enumerated_refusal(
        self, tenant_a, admin_a, active_connector, connector_secret, fake_remote, bad
    ):
        from external_integrations.operations import OperationError, run_import_document

        summary = {
            "external_object_id": "a.pdf",
            "relative_path": "inbox/a.pdf",
            "title": "A",
        }
        if bad is not None:
            summary["document_type"] = bad

        execution = self._execution(tenant_a, admin_a, active_connector, summary)
        with pytest.raises(OperationError) as excinfo:
            run_import_document(
                execution=execution,
                connector=active_connector,
                config=active_connector.configuration,
                credential_reference=active_connector.credential_reference,
                actor=admin_a,
                tenant=tenant_a,
            )
        assert excinfo.value.code == "PAYLOAD_INVALID"
        assert Document.objects.count() == 0
        # Refused before the network, not after.
        assert fake_remote.calls == []

    def test_a_valid_type_in_a_stored_summary_proceeds(
        self, tenant_a, admin_a, active_connector, connector_secret, fake_remote
    ):
        """Control, so the check above is not simply refusing everything."""
        from external_integrations.operations import run_import_document

        fake_remote.body = PDF_BYTES
        execution = self._execution(
            tenant_a,
            admin_a,
            active_connector,
            {
                "external_object_id": "a.pdf",
                "relative_path": "inbox/a.pdf",
                "title": "A",
                "document_type": "pdf",
            },
        )
        summary = run_import_document(
            execution=execution,
            connector=active_connector,
            config=active_connector.configuration,
            credential_reference=active_connector.credential_reference,
            actor=admin_a,
            tenant=tenant_a,
        )
        assert summary["document_version_public_id"]
        assert Document.objects.get().document_type == "pdf"
