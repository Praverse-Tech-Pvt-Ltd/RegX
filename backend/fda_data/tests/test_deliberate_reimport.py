"""Owner decision 2026-11-18 (PROJECT_OVERVIEW §12 item 11): the same IID data
is refused by default, compared by NORMALISED CONTENT; a deliberate re-import
is allowed only through `import_fda_release --deliberate-reimport --reason`,
as a new release linked to the earlier one, through the whole lifecycle.

Before: the duplicate check compared raw bytes only, so a copy of the file
re-saved with CRLF line endings (as in the 2026-11-18 browser test) was
imported a second time; and there was no supported way to re-import on purpose.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from audit.models import AuditEvent
from fda_data import lifecycle
from fda_data.models import FDADataSourceRelease, FDAReleaseStatus
from fda_data.tests._loader import loader_email

IID = (Path(__file__).parent / "fixtures" / "iid" / "iir_ocomm_sample.csv").read_bytes()
REASON = "Route and dosage-form mappings approved after the 2026-07 release was reviewed."
pytestmark = pytest.mark.django_db


def _crlf(data: bytes) -> bytes:
    """The same file with its line endings switched (LF <-> CRLF)."""
    if b"\r\n" in data:
        return data.replace(b"\r\n", b"\n")
    return data.replace(b"\n", b"\r\n")


def _run(tmp_path, data: bytes, name="IIR_OCOMM.csv", **extra) -> str:
    path = tmp_path / name
    path.write_bytes(data)
    out = io.StringIO()
    call_command(
        "import_fda_release",
        str(path),
        dataset_type="fda_iid",
        source_reference="Test fixture: real FDA IID rows",
        actor=loader_email(),
        stdout=out,
        **extra,
    )
    return out.getvalue()


def _refused(tmp_path, data, name="IIR_OCOMM.csv", **extra):
    with pytest.raises(CommandError) as exc:
        _run(tmp_path, data, name, **extra)
    return exc.value


def _activate(release, vp):
    loader = release.imported_by
    return lifecycle.activate(
        lifecycle.approve(lifecycle.submit_for_review(release, loader), vp), vp
    )


@pytest.fixture
def first(tmp_path):
    _run(tmp_path, IID)
    return FDADataSourceRelease.objects.get(dataset_type="fda_iid")


class TestTheSameDataIsRefused:
    def test_the_same_file_is_refused(self, tmp_path, first):
        err = _refused(tmp_path, IID, "again.csv")
        assert err.returncode == 3
        assert str(first.public_id) in str(err)
        assert FDADataSourceRelease.objects.filter(dataset_type="fda_iid").count() == 1

    def test_a_crlf_copy_is_refused(self, tmp_path, first):
        copy = _crlf(IID)
        assert copy != IID  # really different bytes
        err = _refused(tmp_path, copy, "IIR_OCOMM_crlf.csv")
        assert err.returncode == 3
        assert "--deliberate-reimport" in str(err)
        assert FDADataSourceRelease.objects.filter(dataset_type="fda_iid").count() == 1

    def test_a_copy_with_trailing_spaces_is_refused(self, tmp_path, first):
        lines = IID.decode("utf-8").splitlines()
        spaced = ("\n".join(line + "   " for line in lines) + "\n").encode("utf-8")
        assert _refused(tmp_path, spaced, "spaced.csv").returncode == 3

    def test_changed_content_is_still_a_new_release(self, tmp_path, first):
        lines = IID.decode("utf-8").splitlines()
        _run(tmp_path, ("\n".join(lines[:-1]) + "\n").encode("utf-8"), "fewer_rows.csv")
        assert FDADataSourceRelease.objects.filter(dataset_type="fda_iid").count() == 2


class TestDeliberateReimport:
    def test_without_a_reason_it_is_refused(self, tmp_path, first):
        err = _refused(tmp_path, IID, deliberate_reimport=True)
        assert "needs --reason" in str(err)
        err = _refused(tmp_path, IID, deliberate_reimport=True, reason="   ")
        assert "needs --reason" in str(err)
        assert FDADataSourceRelease.objects.filter(dataset_type="fda_iid").count() == 1

    def test_a_reason_without_the_flag_is_refused(self, tmp_path, first):
        assert "only used with --deliberate-reimport" in str(_refused(tmp_path, IID, reason=REASON))

    def test_nothing_to_reimport_is_refused(self, tmp_path):
        err = _refused(tmp_path, IID, deliberate_reimport=True, reason=REASON)
        assert "not imported yet" in str(err)
        assert not FDADataSourceRelease.objects.exists()

    def test_only_for_the_iid(self, tmp_path):
        path = tmp_path / "x.txt"
        path.write_bytes(b"x")
        with pytest.raises(CommandError, match="FDA IID only"):
            call_command(
                "import_fda_release",
                str(path),
                dataset_type="orange_book_products",
                source_reference="t",
                actor=loader_email(),
                deliberate_reimport=True,
                reason=REASON,
            )

    def test_accepted_linked_and_audited(self, tmp_path, first):
        out = _run(
            tmp_path, _crlf(IID), "IIR_OCOMM_crlf.csv", deliberate_reimport=True, reason=REASON
        )
        new = FDADataSourceRelease.objects.exclude(pk=first.pk).get()
        assert new.status == FDAReleaseStatus.REGISTERED  # the whole lifecycle still to come
        assert (new.reimport_of_id, new.reimport_reason) == (first.pk, REASON)
        assert new.content_fingerprint_sha256 == first.content_fingerprint_sha256
        assert str(first.public_id) in out
        event = AuditEvent.objects.get(
            event_type="fda_data.release.reimport_registered", resource_id=str(new.public_id)
        )
        assert event.payload["reimport_of"] == str(first.public_id)
        assert event.payload["reason"] == REASON
        assert event.actor_email == loader_email()

    def test_the_same_bytes_can_be_reimported_on_purpose(self, tmp_path, first):
        _run(tmp_path, IID, "again.csv", deliberate_reimport=True, reason=REASON)
        new = FDADataSourceRelease.objects.exclude(pk=first.pk).get()
        assert new.source_checksum_sha256 == first.source_checksum_sha256
        assert new.reimport_of_id == first.pk


class TestTheEarlierReleaseStaysAsHistory:
    def test_on_activation_the_earlier_release_is_superseded_and_still_readable(
        self, tmp_path, first, vp_user, api_client_vp
    ):
        first = _activate(first, vp_user)
        _run(tmp_path, IID, "again.csv", deliberate_reimport=True, reason=REASON)
        new = FDADataSourceRelease.objects.exclude(pk=first.pk).get()
        assert FDADataSourceRelease.objects.get(pk=first.pk).status == FDAReleaseStatus.ACTIVE
        new = _activate(new, vp_user)  # approved and activated by someone other than the loader
        old = FDADataSourceRelease.objects.get(pk=first.pk)
        assert (old.status, old.superseded_by_release_id) == (FDAReleaseStatus.SUPERSEDED, new.pk)
        resp = api_client_vp.get(f"/api/regx/v1/fda-data/releases/{old.public_id}/")
        assert resp.status_code == 200
        assert resp.json()["status"] == FDAReleaseStatus.SUPERSEDED
        from fda_data.models import IIDPrecedentRecord

        old_rows = IIDPrecedentRecord.objects.filter(release=old).count()
        assert old_rows == IIDPrecedentRecord.objects.filter(release=new).count() > 0

    def test_the_loader_cannot_approve_the_reimport(self, tmp_path, first):
        _run(tmp_path, IID, "again.csv", deliberate_reimport=True, reason=REASON)
        new = FDADataSourceRelease.objects.exclude(pk=first.pk).get()
        new = lifecycle.submit_for_review(new, new.imported_by)
        with pytest.raises(Exception):  # noqa: B017 - the lifecycle's own refusal type
            lifecycle.approve(new, new.imported_by)


class TestTheDatabaseAgrees:
    def test_a_reimport_without_a_reason_cannot_be_stored(self, first):
        from django.db import IntegrityError, transaction

        with pytest.raises(IntegrityError), transaction.atomic():
            FDADataSourceRelease.objects.create(
                dataset_type="fda_iid",
                source_name="x",
                official_source_reference="x",
                original_filename="x",
                source_checksum_sha256="e" * 64,
                reimport_of=first,
            )

    def test_the_same_bytes_without_reimport_cannot_be_stored(self, first):
        from django.db import IntegrityError, transaction

        with pytest.raises(IntegrityError), transaction.atomic():
            FDADataSourceRelease.objects.create(
                dataset_type="fda_iid",
                source_name="x",
                official_source_reference="x",
                original_filename="x",
                source_checksum_sha256=first.source_checksum_sha256,
            )


class TestApiPath:
    def test_the_api_refuses_the_same_rows_reordered(self, api_client_doer):
        rows = [
            {
                "INGREDIENT_NAME": "A",
                "ROUTE": "ORAL",
                "DOSAGE_FORM": "TABLET",
                "POTENCY_AMOUNT": "1",
                "POTENCY_UNIT": "mg",
            },
            {
                "INGREDIENT_NAME": "B",
                "ROUTE": "ORAL",
                "DOSAGE_FORM": "TABLET",
                "POTENCY_AMOUNT": "2",
                "POTENCY_UNIT": "mg",
            },
        ]
        body = {"dataset_type": "fda_iid", "source_name": "t", "official_source_reference": "t"}
        assert (
            api_client_doer.post(
                "/api/regx/v1/fda-data/releases/", {**body, "rows": rows}, format="json"
            ).status_code
            == 201
        )
        resp = api_client_doer.post(
            "/api/regx/v1/fda-data/releases/",
            {**body, "rows": [rows[1], {**rows[0], "ROUTE": "ORAL  "}]},
            format="json",
        )
        assert resp.status_code == 409
