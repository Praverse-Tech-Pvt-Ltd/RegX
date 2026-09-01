"""Query-cost shape for the dossier and section endpoints.

Asserts INVARIANCE, not an absolute number: an absolute would encode today's
fixed overhead (authentication, tenant resolution, one membership lookup per
module permission) and break on unrelated changes. What must never change is
that cost stays flat as rows are added -- that is what an N+1 destroys.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from submission_dossiers import services
from submission_dossiers.tests.conftest import make_section

DOSS = "/api/regx/v1/submission-dossiers"
SECT = "/api/regx/v1/dossier-sections"


def _measure(client, url):
    client.get(url)  # warm lazily-built caches
    with CaptureQueriesContext(connection) as ctx:
        client.get(url)
    return len(ctx.captured_queries)


@pytest.mark.django_db
class TestQueryCost:
    def test_dossier_detail_is_flat_in_section_count(self, client_doer_a, case_a, tenant_a, doer_a):
        """1, 10 and 100 sections must cost the same. The tree is serialised
        flat and assembled by the client for exactly this reason."""
        counts = {}
        for n in (1, 10, 100):
            dossier = services.create_dossier(
                case=case_a, tenant=tenant_a, actor=doer_a, title=f"D{n}"
            )
            for i in range(n):
                make_section(dossier, tenant_a, doer_a, f"s{i}")
            counts[n] = _measure(client_doer_a, f"{DOSS}/{dossier.public_id}/")

        print(f"  dossier detail queries by section count: {counts}")
        assert counts[1] == counts[10] == counts[100], f"query count grows: {counts}"

    def test_section_detail_is_flat_in_link_count(self, client_doer_a, dossier_a, tenant_a, doer_a):
        from documents.models import Document

        counts = {}
        for n in (1, 5, 20):
            section = make_section(dossier_a, tenant_a, doer_a, f"sec-{n}")
            for i in range(n):
                doc = Document.objects.create(
                    tenant=tenant_a, title=f"doc-{n}-{i}", document_type="other"
                )
                services.link_target(
                    kind="document",
                    section=section,
                    target_public_id=doc.public_id,
                    actor=doer_a,
                    tenant=tenant_a,
                )
            counts[n] = _measure(client_doer_a, f"{SECT}/{section.public_id}/")

        print(f"  section detail queries by link count: {counts}")
        assert counts[1] == counts[5] == counts[20], f"query count grows: {counts}"

    def test_readiness_recalculation_is_flat_in_section_count(self, case_a, tenant_a, doer_a):
        """The bottom-up recalculation loads the tree once and groups children
        in memory; a per-node query would show up here immediately."""
        counts = {}
        for n in (5, 50):
            dossier = services.create_dossier(
                case=case_a, tenant=tenant_a, actor=doer_a, title=f"R{n}"
            )
            parent = None
            for i in range(n):
                parent = (
                    make_section(dossier, tenant_a, doer_a, f"r{i}", parent=parent)
                    if i < 5
                    else make_section(dossier, tenant_a, doer_a, f"r{i}")
                )
            with CaptureQueriesContext(connection) as ctx:
                services.recalculate_dossier(dossier)
            counts[n] = len(ctx.captured_queries)

        print(f"  recalculate queries by section count: {counts}")
        # Bulk-update batching can add a query, so allow a small constant
        # difference -- what matters is that it is not proportional to n.
        assert abs(counts[50] - counts[5]) <= 2, f"recalculation scales with sections: {counts}"
