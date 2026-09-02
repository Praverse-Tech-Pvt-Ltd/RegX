"""Async work is dispatched after the rows it needs are committed.

MEASURED BEFORE THE FIX, with a caller holding a transaction:

    dispatched before commit: 1
    dispatched after commit:  0

A worker picking that message up can look up a `DocumentVersion` that does not
exist yet. It then logs "not found" and returns, so the version is never
scanned and never processed -- and nothing anywhere reports a failure.

This was latent rather than live: no caller wrapped `ingest_new_document` in a
transaction, and with `ATOMIC_REQUESTS` off the ordinary request path committed
before dispatching. It is worth fixing anyway, because `ingest_new_document`
became a shared public entry point in Milestone 14, wrapping a service call in a
transaction is an ordinary thing for a caller to do, and the resulting failure
is silent.

`on_commit` is correct either way: with no enclosing transaction Django runs the
callback immediately, so the ordinary path is unchanged.
"""

import io

import pytest
from django.db import transaction

from documents.ingest import ingest_new_document

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def _ingest(tenant, actor, name="a.pdf"):
    return ingest_new_document(
        tenant=tenant,
        actor=actor,
        file_obj=io.BytesIO(PDF),
        filename=name,
        declared_mime="application/pdf",
        title="Synthetic",
        document_type="pdf",
    )


@pytest.mark.django_db(transaction=True)
class TestScanDispatchWaitsForCommit:
    def test_dispatch_is_deferred_when_a_caller_holds_a_transaction(
        self, tenant_a, user_a, monkeypatch
    ):
        """THE regression test.

        Nothing may be queued while the caller's transaction is still open,
        because the row the worker needs is not visible to any other connection
        until that transaction commits.
        """
        from documents import ingest as ingest_module

        fired = []

        class FakeTask:
            @staticmethod
            def delay(version_pk, tenant_id):
                fired.append(version_pk)

        monkeypatch.setattr(ingest_module, "scan_document_version", FakeTask)

        with transaction.atomic():
            _ingest(tenant_a, user_a)
            assert fired == [], "the scan was dispatched before the caller committed"

        assert len(fired) == 1, "the scan was never dispatched after commit"

    def test_a_rolled_back_ingest_dispatches_nothing(self, tenant_a, user_a, monkeypatch):
        """The other half of the same property.

        If the caller rolls back, the version does not exist and no worker
        should ever be told to scan it. Dispatching inline would have queued
        work for a row that was then discarded.
        """
        from documents import ingest as ingest_module

        fired = []

        class FakeTask:
            @staticmethod
            def delay(version_pk, tenant_id):
                fired.append(version_pk)

        monkeypatch.setattr(ingest_module, "scan_document_version", FakeTask)

        class Rollback(Exception):
            pass

        with pytest.raises(Rollback), transaction.atomic():
            _ingest(tenant_a, user_a)
            raise Rollback

        assert fired == [], "work was queued for a version that was rolled back"

    def test_the_ordinary_path_still_dispatches(self, tenant_a, user_a, monkeypatch):
        """Control. `on_commit` with no enclosing transaction runs immediately,
        so the normal upload must be unchanged -- a fix that stopped dispatching
        would pass both tests above."""
        from documents import ingest as ingest_module

        fired = []

        class FakeTask:
            @staticmethod
            def delay(version_pk, tenant_id):
                fired.append(version_pk)

        monkeypatch.setattr(ingest_module, "scan_document_version", FakeTask)

        _document, version = _ingest(tenant_a, user_a)
        assert fired == [version.pk]

    def test_the_version_is_visible_to_another_connection_when_the_task_fires(
        self, tenant_a, user_a, monkeypatch
    ):
        """What the deferral is actually for.

        A worker runs on its own connection. This asserts the row is readable
        from a *fresh* connection at the moment the task is dispatched, which is
        the property that makes the lookup succeed -- not merely that the
        callback ran late.
        """
        from django.db import connections

        from documents import ingest as ingest_module
        from documents.models import DocumentVersion

        visible = []

        class FakeTask:
            @staticmethod
            def delay(version_pk, tenant_id):
                connections["default"].close()
                visible.append(DocumentVersion.objects.filter(pk=version_pk).exists())

        monkeypatch.setattr(ingest_module, "scan_document_version", FakeTask)

        with transaction.atomic():
            _ingest(tenant_a, user_a)

        assert visible == [True], "the version was not readable when the task was dispatched"


@pytest.mark.django_db
class TestVersionUploadDispatchWaitsForCommit:
    """The second upload path, which does not go through `ingest`.

    `DocumentVersionListCreateView.post` builds its own version inside an
    explicit `transaction.atomic()` block and dispatches afterwards. It needs
    the same protection for the same reason, and a mutation removing it turned
    nothing red until this existed.

    Asserted with `django_capture_on_commit_callbacks`: a deferred dispatch
    registers a callback, an inline one does not.
    """

    def test_the_scan_is_not_dispatched_before_the_response_commits(
        self,
        user_a,
        tenant_a,
        doer_membership,
        local_storage,
        valid_pdf_bytes,
        valid_docx_bytes,
        django_capture_on_commit_callbacks,
        monkeypatch,
    ):
        """Asserted on *this* dispatch, not on "some callback was registered".

        An earlier version of this test counted captured callbacks and passed
        under the mutation: Celery is eager here, so an inline `delay()` runs
        the scan task, which registers its own `on_commit` for processing. The
        count was satisfied by a callback belonging to something else entirely.

        Recording the specific task instead makes the assertion unambiguous --
        while the transaction is open, this dispatch must not have happened.
        """
        from documents import views as views_module
        from documents.tests.test_api import BASE_URL, _client_for, _docx_upload, _post_doc

        fired = []

        class FakeTask:
            @staticmethod
            def delay(version_pk, tenant_id):
                fired.append(version_pk)

        monkeypatch.setattr(views_module, "scan_document_version", FakeTask)

        client = _client_for(user_a, tenant_a)
        created = _post_doc(client, valid_pdf_bytes, "Version dispatch doc")
        assert created.status_code == 201
        public_id = created.json()["public_id"]
        fired.clear()

        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            response = client.post(
                f"{BASE_URL}{public_id}/versions/",
                data={"file": _docx_upload(valid_docx_bytes)},
                format="multipart",
            )
            assert response.status_code == 201, response.json()
            assert fired == [], (
                "the version upload dispatched its scan before the transaction committed"
            )

        for callback in callbacks:
            callback()
        assert len(fired) == 1, "the scan was never dispatched after commit"
