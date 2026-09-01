"""Two defects found reviewing the pushed code, and the tests that hold them shut.

1. **The import claimed to stream and did not.** The response went to a
   temporary file and was then read back with `handle.read()` into a
   `SimpleUploadedFile`, so a worker held the whole import in memory -- the
   exact thing the temporary file existed to avoid, and a worker-stability risk
   the moment two large imports overlap.

2. **`declared_mime` was accepted and dropped.** The serializer took it, the
   view did not put it in the request summary, and the worker therefore always
   fell back to guessing from the filename. The document platform compares the
   declared type against the detected one, so the comparison had quietly become
   detected-versus-our-own-guess -- which can never disagree in the way the
   check exists to catch.
"""

import io
import zipfile

import pytest

from documents.models import DocumentVersion
from external_integrations.models import ConnectorExecution, ExecutionStatus
from external_integrations.tests.conftest import INTEGRATIONS_API, PDF_BYTES


def _queue(post, connector, **overrides):
    """Queue an import and let the on-commit dispatch actually run.

    `post` is the `run_queued` fixture. The execution task is dispatched with
    `transaction.on_commit`, so in a non-transactional test nothing would run
    without it and every assertion below would be about an execution that never
    started.
    """
    payload = {
        "external_object_id": "remote-doc-1.pdf",
        "relative_path": "inbox/remote-doc-1.pdf",
        "title": "Imported synthetic document",
        "document_type": "pdf",
    }
    payload.update(overrides)
    return post(
        f"{INTEGRATIONS_API}/{connector.public_id}/executions/",
        {"operation": "import_document", "payload": payload},
    )


# ---------------------------------------------------------------------------
# 1. Streamed end to end
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestImportIsStreamed:
    def test_ingest_receives_a_real_file_not_an_in_memory_copy(
        self, queue_post, active_connector, connector_secret, fake_remote, monkeypatch
    ):
        """`fileno()` is the discriminator, and it is not a stylistic one.

        A file object backed by an operating-system file has a descriptor. One
        backed by `BytesIO` -- which is what `SimpleUploadedFile` wraps -- raises
        `UnsupportedOperation`. So this asserts the bytes are on disk rather than
        in the worker's heap, which is the property under review.
        """
        from documents import ingest as ingest_module

        seen = {}
        real = ingest_module.ingest_new_document

        def spy(**kwargs):
            file_obj = kwargs["file_obj"]
            seen["type"] = type(file_obj).__name__
            try:
                seen["fileno"] = file_obj.fileno()
            except (OSError, io.UnsupportedOperation, AttributeError):
                seen["fileno"] = None
            return real(**kwargs)

        monkeypatch.setattr(ingest_module, "ingest_new_document", spy)

        fake_remote.body = PDF_BYTES
        response = _queue(queue_post, active_connector)
        assert response.status_code == 201

        assert seen, "ingest was never called"
        assert seen["fileno"] is not None, (
            f"ingest received {seen['type']}, which holds its content in memory; "
            "the import is not streamed"
        )

    def test_the_whole_body_is_never_read_in_one_call(
        self, queue_post, active_connector, connector_secret, fake_remote, monkeypatch
    ):
        """No unbounded `read()` on the temporary file, at any point.

        Watched at the handle itself rather than inside `ingest`, because the
        defect read the body *before* handing it on -- a watcher installed
        downstream would have seen nothing and passed. Everything legitimate
        here asks for a bounded chunk: the validators, the checksum, and the
        storage backend all read in fixed sizes.
        """
        import tempfile as tempfile_module

        unbounded = []
        real_factory = tempfile_module.NamedTemporaryFile

        def watched_factory(*args, **kwargs):
            handle = real_factory(*args, **kwargs)
            original_read = handle.read

            def watched_read(size=-1):
                if size is None or size < 0:
                    unbounded.append(True)
                return original_read(size)

            handle.read = watched_read
            return handle

        monkeypatch.setattr(
            "external_integrations.operations.tempfile.NamedTemporaryFile", watched_factory
        )

        fake_remote.body = PDF_BYTES * 200
        response = _queue(queue_post, active_connector)
        assert response.status_code == 201
        assert unbounded == [], (
            "the whole import was read in one call; it is being materialised in memory"
        )

    def test_a_large_import_still_succeeds_and_stores_every_byte(
        self, queue_post, active_connector, connector_secret, fake_remote
    ):
        """Streaming must not mean truncating. The stored size and checksum are
        checked against the bytes that actually arrived."""
        import hashlib

        body = PDF_BYTES + b"\n" + (b"A" * 3_000_000)
        fake_remote.body = body

        response = _queue(queue_post, active_connector)
        assert response.status_code == 201

        version = DocumentVersion.objects.latest("id")
        assert version.size_bytes == len(body)
        assert version.sha256_checksum == hashlib.sha256(body).hexdigest()

    def test_the_import_ceiling_follows_the_document_platform_limit(self):
        """Two numbers that must agree are not written down twice."""
        from django.conf import settings

        from external_integrations.operations import max_import_bytes

        assert max_import_bytes() == settings.DOCUMENT_MAX_UPLOAD_BYTES


# ---------------------------------------------------------------------------
# 2. The declared type reaches the worker
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDeclaredMimeIsCarried:
    def test_a_declared_type_survives_into_the_request_summary(
        self, queue_post, active_connector, connector_secret, fake_remote
    ):
        fake_remote.body = PDF_BYTES
        response = _queue(queue_post, active_connector, declared_mime="application/pdf")
        assert response.status_code == 201

        execution = ConnectorExecution.objects.get(public_id=response.data["public_id"])
        assert execution.request_summary["declared_mime"] == "application/pdf"

    def test_the_declared_type_is_what_the_document_records(
        self, queue_post, active_connector, connector_secret, fake_remote
    ):
        fake_remote.body = PDF_BYTES
        _queue(queue_post, active_connector, declared_mime="application/pdf")

        version = DocumentVersion.objects.latest("id")
        assert version.declared_mime_type == "application/pdf"

    def test_a_declared_type_that_contradicts_the_bytes_is_refused(
        self, queue_post, active_connector, connector_secret, fake_remote
    ):
        """THE contract test.

        The document platform's whole reason for storing both a declared and a
        detected type is to compare them. While the declared value was being
        dropped, the comparison was against a guess derived from the same
        filename the detection ran on -- so it could not disagree, and a remote
        system lying about its content type would have gone unnoticed.

        Here the caller declares a spreadsheet and sends a PDF. It must be
        refused, and it can only be refused if the declaration arrived.
        """
        fake_remote.body = PDF_BYTES
        response = _queue(
            queue_post,
            active_connector,
            declared_mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        assert response.status_code == 201

        execution = ConnectorExecution.objects.get(public_id=response.data["public_id"])
        assert execution.status == ExecutionStatus.FAILED
        assert execution.error_code == "DOCUMENT_REJECTED"
        assert not DocumentVersion.objects.exists()

    def test_an_omitted_declared_type_still_falls_back_to_the_filename(
        self, queue_post, active_connector, connector_secret, fake_remote
    ):
        """Control. The fallback is legitimate when the caller says nothing --
        a browser derives the type from the file too -- so removing it would
        refuse every import that omitted an optional field."""
        fake_remote.body = PDF_BYTES
        response = _queue(queue_post, active_connector)
        assert response.status_code == 201

        version = DocumentVersion.objects.latest("id")
        assert version.declared_mime_type == "application/pdf"

    def test_a_declared_type_is_not_trusted_over_the_bytes(
        self, queue_post, active_connector, connector_secret, fake_remote
    ):
        """Declaring the right thing does not make the wrong content acceptable:
        detection still runs against the actual bytes."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("word/vbaProject.bin", b"\x00macro")
        fake_remote.body = buffer.getvalue()

        response = _queue(
            queue_post,
            active_connector,
            external_object_id="thing.pdf",
            declared_mime="application/pdf",
        )
        execution = ConnectorExecution.objects.get(public_id=response.data["public_id"])
        assert execution.status == ExecutionStatus.FAILED
        assert not DocumentVersion.objects.exists()
