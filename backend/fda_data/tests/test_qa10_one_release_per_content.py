"""QA-10: the same content is registered once per dataset type, even under concurrency.

The duplicate check (`find_imported_duplicate`) runs before the release is
written. Two imports of the same content that overlap both passed the check
and both registered. The database now refuses a second ordinary release with
the same content fingerprint (partial unique constraint), and the loser gets
the existing "duplicate refused" answer: exit code 3 from the command, 409
`duplicate_release` from the API.

Real PostgreSQL. The concurrency test uses two real connections (threads).
"""

from __future__ import annotations

import pathlib
import threading

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, connection, transaction

from fda_data import importer
from fda_data.management.commands.import_fda_release import DUPLICATE_EXIT_CODE
from fda_data.models import FDADataSourceRelease

SAMPLE = pathlib.Path(__file__).parent / "fixtures" / "iid" / "iir_ocomm_sample.csv"
RELEASES_URL = "/api/regx/v1/fda-data/releases/"


def _lf_and_crlf(tmp_path):
    lf = tmp_path / "IIR_LF.csv"
    crlf = tmp_path / "IIR_CRLF.csv"
    text = SAMPLE.read_bytes().decode("latin-1").replace("\r\n", "\n")
    lf.write_bytes(text.encode("latin-1"))
    crlf.write_bytes(text.replace("\n", "\r\n").encode("latin-1"))
    return lf, crlf


def _import(path, actor):
    call_command(
        "import_fda_release",
        str(path),
        "--dataset-type",
        "fda_iid",
        "--actor",
        actor.email,
        "--source-reference",
        f"QA-10 ({path.name})",
    )


def _ordinary_releases():
    return FDADataSourceRelease.objects.filter(dataset_type="fda_iid", reimport_of__isnull=True)


@pytest.mark.django_db(transaction=True)
def test_qa10_overlapping_imports_of_the_same_content_register_once(
    tmp_path, user_a, doer_membership
):
    """From #154's investigation, xfail removed. The first import holds its
    transaction open; the second (same content, CRLF line endings) runs
    meanwhile on its own connection. Exactly one release registers, and the
    second import is refused with the duplicate exit code."""
    lf, crlf = _lf_and_crlf(tmp_path)
    a_done, b_done, outcome = threading.Event(), threading.Event(), {}

    def first():
        try:
            with transaction.atomic():
                _import(lf, user_a)
                a_done.set()
                # Hold the commit while the second import runs (it blocks on
                # the unique index once fixed, so do not wait for it forever).
                b_done.wait(5)
            outcome["first"] = "registered"
        except Exception as exc:
            outcome["first"] = repr(exc)[:200]
            a_done.set()
        finally:
            connection.close()

    def second():
        try:
            a_done.wait(30)
            _import(crlf, user_a)
            outcome["second"] = "registered"
        except CommandError as exc:
            outcome["second"] = ("refused", exc.returncode, str(exc)[:160])
        except Exception as exc:
            outcome["second"] = repr(exc)[:200]
        finally:
            b_done.set()
            connection.close()

    t1, t2 = threading.Thread(target=first), threading.Thread(target=second)
    t1.start()
    t2.start()
    t1.join(90)
    t2.join(90)

    prints = list(_ordinary_releases().values_list("content_fingerprint_sha256", flat=True))
    assert len(prints) == 1, (outcome, prints)
    assert outcome["first"] == "registered", outcome
    assert outcome["second"][:2] == ("refused", DUPLICATE_EXIT_CODE), outcome
    assert "Refused" in outcome["second"][2], outcome


@pytest.mark.django_db
def test_the_database_refuses_a_second_release_with_the_same_content(
    tmp_path, user_a, doer_membership
):
    lf, _ = _lf_and_crlf(tmp_path)
    _import(lf, user_a)
    first = _ordinary_releases().get()
    with pytest.raises(IntegrityError), transaction.atomic():
        FDADataSourceRelease.objects.create(
            dataset_type=first.dataset_type,
            source_name="other",
            official_source_reference="QA-10 raw insert",
            original_filename="other.csv",
            storage_key="qa10/other",
            source_checksum_sha256="0" * 64,  # different bytes, same content
            content_fingerprint_sha256=first.content_fingerprint_sha256,
        )


@pytest.mark.django_db
def test_a_deliberate_reimport_of_the_same_content_is_still_allowed(
    tmp_path, user_a, doer_membership
):
    lf, crlf = _lf_and_crlf(tmp_path)
    _import(lf, user_a)
    call_command(
        "import_fda_release",
        str(crlf),
        "--dataset-type",
        "fda_iid",
        "--actor",
        user_a.email,
        "--source-reference",
        "QA-10 deliberate",
        "--deliberate-reimport",
        "--reason",
        "QA-10: a deliberate re-import is outside the constraint",
    )
    releases = FDADataSourceRelease.objects.filter(dataset_type="fda_iid")
    assert releases.count() == 2
    assert releases.filter(reimport_of__isnull=False).count() == 1


@pytest.mark.django_db
def test_the_api_answers_409_when_it_loses_the_race(api_client_doer, monkeypatch):
    """The API path has the same check-then-write window. Reproduced
    deterministically: the duplicate check is made to miss (as it does when the
    other import has not committed yet). The loser gets 409, not a 500."""
    payload = {
        "dataset_type": "fda_iid",
        "source_name": "iid",
        "official_source_reference": "test",
        "rows": [
            {
                "INGREDIENT_NAME": "ACACIA",
                "ROUTE": "ORAL",
                "DOSAGE_FORM": "TABLET, FILM COATED",
                "UNII": "5C5403N26O",
                "POTENCY_AMOUNT": "0.14",
                "POTENCY_UNIT": "mg",
            },
            {
                "INGREDIENT_NAME": "LACTOSE",
                "ROUTE": "ORAL",
                "DOSAGE_FORM": "TABLET",
                "UNII": "J2B2A4N98G",
                "POTENCY_AMOUNT": "100",
                "POTENCY_UNIT": "mg",
            },
        ],
    }
    first = api_client_doer.post(RELEASES_URL, payload, format="json")
    assert first.status_code == 201
    monkeypatch.setattr(importer, "find_imported_duplicate", lambda *a, **k: None)
    # Same rows in the other order: different bytes, same content fingerprint.
    payload["rows"] = list(reversed(payload["rows"]))
    payload["source_name"] = "iid-again"
    second = api_client_doer.post(RELEASES_URL, payload, format="json")
    assert second.status_code == 409, second.content
    assert second.data["error_code"] == "duplicate_release"
    assert _ordinary_releases().count() == 1
