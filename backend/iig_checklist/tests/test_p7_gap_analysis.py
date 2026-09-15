"""P7 -- the gap-analysis engine, its two surfaces, and the snapshot record.

Before P7 the only tests here covered `_normalised` and `_score` -- two helpers.
The rule itself, `analyse_execution`, had no test at all, which is how two
defects survived: `review_required` was reported as `unanswered`, and sections
were grouped by a title that is not unique.

The structure of this module follows from the fix. There is now one engine and
two callers, so the rule is tested once against `classify()`, and each surface
is tested for *being a faithful projection of it* rather than for re-deriving
the same answers. A test that asserted the same expectations twice would pass
just as happily if the two paths diverged again.
"""

from __future__ import annotations

import pytest

from iig_checklist.enums import AnswerType, DataSourceClassification
from iig_checklist.gap_analysis import (
    ALGORITHM_VERSION,
    GapStatus,
    ReasonCode,
    analyse,
    analyse_execution,
    classify,
)
from iig_checklist.tests.test_4d4_applicability_governance import _formulation, _product, _rule

pytestmark = pytest.mark.django_db

GAP_EVENT = "iig_checklist.gap_analysis.generated"


# ---------------------------------------------------------------------------
# World
# ---------------------------------------------------------------------------
def _build(tenant, tenant_definition, user, *, second_section_title=None):
    """An execution covering every classification the engine can produce.

    `second_section_title` builds a second section that deliberately shares the
    first one's *title* while carrying its own code -- the exact shape that used
    to collapse two sections into one bucket.
    """
    from iig_checklist.models import (
        ChecklistQuestion,
        ChecklistResponse,
        ChecklistSection,
        ChecklistVersion,
    )
    from iig_checklist.services import create_execution

    version = ChecklistVersion.objects.create(
        definition=tenant_definition, version_number=1, status="active", created_by=user
    )
    section = ChecklistSection.objects.create(
        checklist_version=version,
        code="SEC-B",
        title="Shared title",
        display_order=2,
        criticality="high",
    )
    rule = _rule(version, user)

    specs = [
        ("Q-YES", AnswerType.YES_NO, "critical", None),
        ("Q-NO", AnswerType.YES_NO, "critical", None),
        ("Q-BLANK", AnswerType.YES_NO, "low", None),
        ("Q-NA", AnswerType.YES_NO_NOT_APPLICABLE, "medium", None),
        ("Q-TEXT", AnswerType.SHORT_TEXT, "critical", None),
        ("Q-REVIEW", AnswerType.YES_NO, "critical", rule),
    ]
    for order, (code, answer_type, criticality, applicability_rule) in enumerate(specs, start=1):
        ChecklistQuestion.objects.create(
            section=section,
            code=code,
            question_text=f"Text for {code}",
            display_order=order,
            answer_type=answer_type,
            data_source_classification=DataSourceClassification.USER_REQUIRED,
            criticality=criticality,
            applicability_rule=applicability_rule,
        )

    if second_section_title is not None:
        # display_order 1 -- authored *before* SEC-B, so a correct grouping puts
        # it first even though its code sorts second.
        other = ChecklistSection.objects.create(
            checklist_version=version,
            code="SEC-A",
            title=second_section_title,
            display_order=1,
            criticality="low",
        )
        ChecklistQuestion.objects.create(
            section=other,
            code="Q-OTHER-NO",
            question_text="Text for Q-OTHER-NO",
            display_order=1,
            answer_type=AnswerType.YES_NO,
            data_source_classification=DataSourceClassification.USER_REQUIRED,
            criticality="low",
        )

    formulation_version = _formulation(_product(tenant, user), user)
    execution = create_execution(
        tenant=tenant,
        checklist_version_public_id=str(version.public_id),
        formulation_version_public_id=str(formulation_version.public_id),
        actor=user,
    )
    responses = {r.question.code: r for r in ChecklistResponse.objects.filter(execution=execution)}
    return execution, version, responses


def _answer(responses, code, **fields):
    """Write response state directly.

    The governed services refuse a client-written applicability, which is the
    behaviour under test elsewhere; here the row has to be *put into* the state
    the analysis then has to classify.
    """
    from iig_checklist.models import ChecklistResponse

    ChecklistResponse.objects.filter(pk=responses[code].pk).update(**fields)


def _populate(responses):
    from iig_checklist.applicability_runtime import review_required_marker

    _answer(responses, "Q-YES", raw_value="yes")
    _answer(responses, "Q-NO", raw_value="no")
    # Q-BLANK left untouched.
    _answer(responses, "Q-NA", is_not_applicable=True, not_applicable_reason="RULE_EXCLUDED")
    _answer(responses, "Q-TEXT", raw_value="no")
    _answer(
        responses,
        "Q-REVIEW",
        not_applicable_reason=review_required_marker("APPLICABILITY_SOURCE_UNRESOLVED"),
    )
    if "Q-OTHER-NO" in responses:
        _answer(responses, "Q-OTHER-NO", raw_value="no")


@pytest.fixture
def world(db, tenant_a, tenant_definition, user_a, doer_membership):
    execution, version, responses = _build(tenant_a, tenant_definition, user_a)
    _populate(responses)
    return {"execution": execution, "version": version, "responses": responses}


# ---------------------------------------------------------------------------
# A. The rule
# ---------------------------------------------------------------------------
class TestClassification:
    def _by_code(self, execution):
        _states, result = analyse(execution)
        return {item.question_code: item for item in result.items}

    @pytest.mark.parametrize(
        ("code", "status", "reason"),
        [
            ("Q-YES", GapStatus.NO_GAP, ReasonCode.ANSWER_YES),
            ("Q-NO", GapStatus.GAP, ReasonCode.ANSWER_NO),
            ("Q-BLANK", GapStatus.UNANSWERED, ReasonCode.ANSWER_MISSING),
            ("Q-NA", GapStatus.NOT_APPLICABLE, ReasonCode.APPLICABILITY_NOT_APPLICABLE),
            ("Q-TEXT", GapStatus.NO_GAP, ReasonCode.NOT_GAPPABLE_TYPE),
            (
                "Q-REVIEW",
                GapStatus.REVIEW_REQUIRED,
                ReasonCode.APPLICABILITY_REVIEW_REQUIRED,
            ),
        ],
    )
    def test_each_question_gets_its_status_and_reason(self, world, code, status, reason):
        item = self._by_code(world["execution"])[code]
        assert item.status == status
        assert item.reason_code == reason

    def test_review_required_is_not_unanswered(self, world):
        """D1. The governed applicability vocabulary already distinguishes
        "a person must decide whether this applies" from "nobody typed
        anything", and the analysis now does too."""
        _states, result = analyse(world["execution"])
        assert result.counts[GapStatus.REVIEW_REQUIRED] == 1
        assert result.counts[GapStatus.UNANSWERED] == 1

    def test_review_required_wins_over_an_answer(self, world):
        """An answer to a question whose applicability is unresolved is not yet
        a finding. Calling it a gap would assert the question applies."""
        _answer(world["responses"], "Q-REVIEW", raw_value="no")
        item = self._by_code(world["execution"])["Q-REVIEW"]
        assert item.status == GapStatus.REVIEW_REQUIRED

    def test_not_applicable_wins_over_review_required(self, world):
        """The order the governed `derive_applicability_outcome` already
        implies: a question that does not apply cannot also be awaiting a
        decision about whether it applies."""
        from iig_checklist.applicability_runtime import review_required_marker

        _answer(
            world["responses"],
            "Q-NA",
            is_not_applicable=True,
            not_applicable_reason=review_required_marker("APPLICABILITY_SOURCE_UNRESOLVED"),
        )
        assert self._by_code(world["execution"])["Q-NA"].status == GapStatus.NOT_APPLICABLE

    def test_a_no_on_a_non_gappable_type_is_never_a_gap(self, world):
        """D2, made visible rather than repaired. A short-text "no" cannot be a
        finding, and the reason code says so instead of letting it read as a
        pass."""
        item = self._by_code(world["execution"])["Q-TEXT"]
        assert item.status == GapStatus.NO_GAP
        assert item.reason_code == ReasonCode.NOT_GAPPABLE_TYPE

    def test_counts_add_up_to_the_question_total(self, world):
        _states, result = analyse(world["execution"])
        five = (
            result.counts[GapStatus.GAP]
            + result.counts[GapStatus.NO_GAP]
            + result.counts[GapStatus.UNANSWERED]
            + result.counts[GapStatus.REVIEW_REQUIRED]
            + result.counts[GapStatus.NOT_APPLICABLE]
        )
        assert five == result.counts["total_questions"] == 6
        assert result.counts["applicable"] == 6 - result.counts[GapStatus.NOT_APPLICABLE]

    def test_the_engine_is_pure_and_repeatable(self, world):
        """`classify` takes state and returns a result. Same state in, same
        result out -- which is what makes the input hash mean anything."""
        states, first = analyse(world["execution"])
        assert classify(states) == first
        assert classify(states) == classify(states)

    def test_the_result_carries_no_question_or_answer_text(self, world):
        """Items are what get persisted, so text must not be reachable from
        them."""
        _states, result = analyse(world["execution"])
        blob = str([vars(item) if hasattr(item, "__dict__") else item for item in result.items])
        assert "Text for" not in str(result.items)
        assert "Text for" not in blob

    def test_criticality_is_carried_through_verbatim(self, world):
        by_code = self._by_code(world["execution"])
        assert by_code["Q-NO"].criticality == "critical"
        assert by_code["Q-BLANK"].criticality == "low"
        assert by_code["Q-NA"].criticality == "medium"


class TestSectionGrouping:
    @pytest.fixture
    def two_sections(self, db, tenant_a, tenant_definition, user_a, doer_membership):
        execution, version, responses = _build(
            tenant_a, tenant_definition, user_a, second_section_title="Shared title"
        )
        _populate(responses)
        return execution

    def test_two_sections_sharing_a_title_stay_separate(self, two_sections):
        """D3. `code` is unique per checklist version; `title` is not. Grouping
        on the title silently merged two differently-authored sections."""
        _states, result = analyse(two_sections)
        assert [s.section_code for s in result.sections] == ["SEC-A", "SEC-B"]
        assert len({s.section_title for s in result.sections}) == 1

    def test_sections_come_back_in_authored_order(self, two_sections):
        """`display_order`, not alphabetical title. SEC-A is authored first and
        sorts first even though the old code sorted by title."""
        _states, result = analyse(two_sections)
        assert [s.display_order for s in result.sections] == [1, 2]

    def test_each_section_counts_only_its_own_questions(self, two_sections):
        _states, result = analyse(two_sections)
        by_code = {s.section_code: s for s in result.sections}
        assert by_code["SEC-A"].counts[GapStatus.GAP] == 1
        assert by_code["SEC-B"].counts[GapStatus.GAP] == 1
        assert by_code["SEC-A"].counts["total_questions"] == 1


# ---------------------------------------------------------------------------
# B. The legacy GET is an adapter, not a second rule
# ---------------------------------------------------------------------------
class TestLegacyProjection:
    LEGACY_KEYS = {
        "execution_id",
        "total_questions",
        "answered",
        "unanswered",
        "not_applicable",
        "gap_count",
        "score_percent",
        "completeness_percent",
        "sections",
        "gaps",
    }

    def test_every_pre_p7_key_is_still_present(self, world):
        payload = analyse_execution(world["execution"])
        assert self.LEGACY_KEYS <= set(payload)

    def test_review_required_is_added_not_substituted(self, world):
        payload = analyse_execution(world["execution"])
        assert payload["review_required"] == 1
        assert payload["unanswered"] == 1

    def test_the_percentages_are_unchanged_by_the_p7_corrections(self, world):
        """`answered`, `gap_count` and `not_applicable` are untouched by the
        review-required split, so neither legacy percentage moves. They are
        retained for compatibility only -- nothing persists or acts on them."""
        payload = analyse_execution(world["execution"])
        assert payload["answered"] == 3
        assert payload["gap_count"] == 1
        assert payload["score_percent"] == 66.67
        assert payload["completeness_percent"] == 66.67

    def test_no_score_is_reported_when_nothing_is_answered(
        self, db, tenant_a, tenant_definition, user_a, doer_membership
    ):
        execution, _version, _responses = _build(tenant_a, tenant_definition, user_a)
        payload = analyse_execution(execution)
        assert payload["score_percent"] is None

    def test_gap_rows_keep_their_original_shape(self, world):
        payload = analyse_execution(world["execution"])
        (row,) = payload["gaps"]
        assert set(row) == {"question_id", "code", "section", "question_text", "answer"}
        assert row["code"] == "Q-NO"
        assert row["question_text"] == "Text for Q-NO"
        assert row["answer"] == "no"

    def test_section_rows_gain_identity_without_losing_the_title(self, world):
        (bucket,) = analyse_execution(world["execution"])["sections"]
        assert bucket["section"] == "Shared title"
        assert bucket["section_code"] == "SEC-B"
        assert bucket["review_required"] == 1

    def test_the_projection_agrees_with_the_engine(self, world):
        """The point of the refactor: the GET reports the engine's counts, so
        the two surfaces cannot disagree about one execution."""
        _states, result = analyse(world["execution"])
        payload = analyse_execution(world["execution"])
        assert payload["gap_count"] == result.counts[GapStatus.GAP]
        assert payload["unanswered"] == result.counts[GapStatus.UNANSWERED]
        assert payload["review_required"] == result.counts[GapStatus.REVIEW_REQUIRED]
        assert payload["not_applicable"] == result.counts[GapStatus.NOT_APPLICABLE]
        assert payload["total_questions"] == result.counts["total_questions"]


# ---------------------------------------------------------------------------
# C. Snapshots
# ---------------------------------------------------------------------------
class TestSnapshotGeneration:
    def test_a_snapshot_records_the_engine_counts(self, world, tenant_a, user_a):
        from iig_checklist.gap_snapshots import generate

        analysis, created = generate(execution=world["execution"], tenant=tenant_a, actor=user_a)
        assert created is True
        assert analysis.total_questions == 6
        assert analysis.gap_count == 1
        assert analysis.review_required_count == 1
        assert analysis.unanswered_count == 1
        assert analysis.not_applicable_count == 1
        assert analysis.no_gap_count == 2
        assert analysis.applicable_count == 5

    def test_a_snapshot_binds_to_the_exact_checklist_version(self, world, tenant_a, user_a):
        from iig_checklist.gap_snapshots import generate

        analysis, _ = generate(execution=world["execution"], tenant=tenant_a, actor=user_a)
        assert analysis.checklist_version_id == world["version"].pk
        assert analysis.algorithm_version == ALGORITHM_VERSION

    def test_items_reference_questions_rather_than_copying_text(self, world, tenant_a, user_a):
        from iig_checklist.gap_snapshots import generate

        analysis, _ = generate(execution=world["execution"], tenant=tenant_a, actor=user_a)
        items = list(analysis.items.all())
        assert len(items) == 6
        for item in items:
            assert item.question_id is not None
            assert not hasattr(item, "question_text")
        by_code = {item.question.code: item for item in items}
        assert by_code["Q-REVIEW"].status == GapStatus.REVIEW_REQUIRED
        assert by_code["Q-NO"].reason_code == ReasonCode.ANSWER_NO
        assert by_code["Q-NA"].configured_criticality == "medium"

    def test_no_score_is_persisted(self, world, tenant_a, user_a):
        from iig_checklist.gap_snapshots import generate
        from iig_checklist.models import GapAnalysis

        generate(execution=world["execution"], tenant=tenant_a, actor=user_a)
        columns = {f.name for f in GapAnalysis._meta.get_fields()}
        assert "score_percent" not in columns
        assert "completeness_percent" not in columns


class TestIdempotencyAndHistory:
    def test_identical_inputs_return_the_existing_snapshot(self, world, tenant_a, user_a):
        from iig_checklist.gap_snapshots import generate
        from iig_checklist.models import GapAnalysis

        first, created_first = generate(execution=world["execution"], tenant=tenant_a, actor=user_a)
        second, created_second = generate(
            execution=world["execution"], tenant=tenant_a, actor=user_a
        )
        assert created_first is True
        assert created_second is False
        assert first.pk == second.pk
        assert GapAnalysis.objects.count() == 1

    def test_a_changed_answer_creates_a_new_snapshot(self, world, tenant_a, user_a):
        from iig_checklist.gap_snapshots import generate
        from iig_checklist.models import GapAnalysis

        first, _ = generate(execution=world["execution"], tenant=tenant_a, actor=user_a)
        _answer(world["responses"], "Q-BLANK", raw_value="no")
        second, created = generate(execution=world["execution"], tenant=tenant_a, actor=user_a)

        assert created is True
        assert second.pk != first.pk
        assert second.input_hash != first.input_hash
        assert GapAnalysis.objects.count() == 2

    def test_the_old_snapshot_does_not_move_when_answers_change(self, world, tenant_a, user_a):
        """The whole reason to persist. A snapshot keeps saying what it said."""
        from iig_checklist.gap_snapshots import generate
        from iig_checklist.models import GapAnalysis

        first, _ = generate(execution=world["execution"], tenant=tenant_a, actor=user_a)
        before = (first.gap_count, first.unanswered_count, first.input_hash)

        _answer(world["responses"], "Q-BLANK", raw_value="no")
        generate(execution=world["execution"], tenant=tenant_a, actor=user_a)

        reread = GapAnalysis.objects.get(pk=first.pk)
        assert (reread.gap_count, reread.unanswered_count, reread.input_hash) == before

    def test_a_snapshot_refuses_to_be_rewritten(self, world, tenant_a, user_a):
        from django.core.exceptions import ValidationError

        from iig_checklist.gap_snapshots import generate

        analysis, _ = generate(execution=world["execution"], tenant=tenant_a, actor=user_a)
        analysis.gap_count = 99
        with pytest.raises(ValidationError):
            analysis.save()

    def test_an_answer_that_does_not_change_the_classification_still_rehashes(
        self, world, tenant_a, user_a
    ):
        """The hash covers the answers, not only the verdict, so "nothing
        changed" means nothing changed rather than "the counts happen to
        match"."""
        from iig_checklist.gap_snapshots import generate

        first, _ = generate(execution=world["execution"], tenant=tenant_a, actor=user_a)
        # A different free-text answer: still NO_GAP/NOT_GAPPABLE_TYPE.
        _answer(world["responses"], "Q-TEXT", raw_value="something else entirely")
        second, created = generate(execution=world["execution"], tenant=tenant_a, actor=user_a)

        assert created is True
        assert second.gap_count == first.gap_count
        assert second.input_hash != first.input_hash


class TestInputHash:
    def test_the_hash_is_stable_across_recomputation(self, world):
        from iig_checklist.gap_snapshots import current_input_hash

        assert current_input_hash(world["execution"]) == current_input_hash(world["execution"])

    def test_the_hash_is_a_sha256_hex_digest(self, world):
        from iig_checklist.gap_snapshots import current_input_hash

        digest = current_input_hash(world["execution"])
        assert len(digest) == 64
        assert set(digest) <= set("0123456789abcdef")

    def test_the_algorithm_version_is_part_of_the_hash(self, world, monkeypatch):
        """A rule change must not be able to reuse an older snapshot."""
        from iig_checklist import gap_snapshots

        before = gap_snapshots.current_input_hash(world["execution"])
        states, result = gap_snapshots.analyse(world["execution"])
        bumped = type(result)(
            algorithm_version=result.algorithm_version + 1,
            items=result.items,
            sections=result.sections,
            counts=result.counts,
        )
        assert gap_snapshots.input_hash(world["execution"], states, bumped) != before

    def test_no_answer_text_enters_the_hashed_payload(self, world):
        """Answers contribute a digest, not their content, so a free-text
        answer carrying personal data never enters the structure."""
        from iig_checklist.gap_snapshots import analyse, canonical_inputs

        _answer(world["responses"], "Q-TEXT", raw_value="patient name Jane Roe")
        states, result = analyse(world["execution"])
        blob = str(canonical_inputs(world["execution"], states, result))
        assert "Jane Roe" not in blob
        assert "Text for" not in blob

    def test_the_hash_notices_an_applicability_change(self, world):
        from iig_checklist.gap_snapshots import current_input_hash

        before = current_input_hash(world["execution"])
        _answer(world["responses"], "Q-YES", is_not_applicable=True, not_applicable_reason="X")
        assert current_input_hash(world["execution"]) != before


class TestConcurrency:
    def test_two_generations_of_identical_inputs_make_one_snapshot(
        self, world, tenant_a, user_a, monkeypatch
    ):
        """The unique constraint is the arbiter, not a check-then-insert.

        The race is forced by blinding the pre-check, so both callers believe
        they are the first and both attempt the insert -- which is exactly what
        two simultaneous requests do.
        """
        from iig_checklist import gap_snapshots
        from iig_checklist.models import GapAnalysis

        first, created_first = gap_snapshots.generate(
            execution=world["execution"], tenant=tenant_a, actor=user_a
        )
        assert created_first is True

        real_filter = GapAnalysis.objects.filter
        calls = {"n": 0}

        def blind_once(*args, **kwargs):
            # Only the pre-check inside `generate` is blinded, and only once.
            if calls["n"] == 0 and "input_hash" in kwargs:
                calls["n"] += 1
                return real_filter(pk=-1)
            return real_filter(*args, **kwargs)

        monkeypatch.setattr(GapAnalysis.objects, "filter", blind_once)
        second, created_second = gap_snapshots.generate(
            execution=world["execution"], tenant=tenant_a, actor=user_a
        )

        assert created_second is False
        assert second.pk == first.pk
        assert GapAnalysis.objects.count() == 1

    def test_the_uniqueness_rule_exists_in_the_database(self, world, tenant_a, user_a):
        from django.db import IntegrityError, transaction

        from iig_checklist.gap_snapshots import generate
        from iig_checklist.models import GapAnalysis

        analysis, _ = generate(execution=world["execution"], tenant=tenant_a, actor=user_a)
        with pytest.raises(IntegrityError), transaction.atomic():
            GapAnalysis.objects.create(
                tenant=tenant_a,
                execution=world["execution"],
                checklist_version=world["version"],
                input_hash=analysis.input_hash,
                algorithm_version=analysis.algorithm_version,
                generated_at=analysis.generated_at,
                total_questions=0,
                applicable_count=0,
                gap_count=0,
                no_gap_count=0,
                unanswered_count=0,
                review_required_count=0,
                not_applicable_count=0,
            )


# ---------------------------------------------------------------------------
# D. Audit
# ---------------------------------------------------------------------------
class TestAudit:
    def _events(self):
        from audit.models import AuditEvent

        return AuditEvent.objects.filter(event_type=GAP_EVENT)

    def test_generation_is_audited_once(self, world, tenant_a, user_a):
        from iig_checklist.gap_snapshots import generate

        analysis, _ = generate(execution=world["execution"], tenant=tenant_a, actor=user_a)
        event = self._events().get()
        assert event.tenant_id == tenant_a.pk
        assert event.actor_id == user_a.pk
        assert event.resource_id == str(analysis.public_id)

    def test_an_idempotent_regeneration_is_not_an_event(self, world, tenant_a, user_a):
        """Nothing was written, so nothing happened. Auditing it would fill the
        trail with rows that record a question, not a change."""
        from iig_checklist.gap_snapshots import generate

        generate(execution=world["execution"], tenant=tenant_a, actor=user_a)
        generate(execution=world["execution"], tenant=tenant_a, actor=user_a)
        generate(execution=world["execution"], tenant=tenant_a, actor=user_a)
        assert self._events().count() == 1

    def test_the_payload_carries_no_question_or_answer_content(self, world, tenant_a, user_a):
        from iig_checklist.gap_snapshots import generate

        _answer(world["responses"], "Q-TEXT", raw_value="patient name Jane Roe")
        generate(execution=world["execution"], tenant=tenant_a, actor=user_a)

        blob = str(self._events().get().payload)
        assert "Jane Roe" not in blob
        assert "Text for" not in blob
        assert "Q-NO" not in blob

    def test_the_payload_is_ids_counts_and_a_hash(self, world, tenant_a, user_a):
        from iig_checklist.gap_snapshots import generate

        analysis, _ = generate(execution=world["execution"], tenant=tenant_a, actor=user_a)
        payload = self._events().get().payload
        assert set(payload) == {
            "analysis_public_id",
            "execution_public_id",
            "checklist_version_public_id",
            "input_hash",
            "algorithm_version",
            "total_questions",
            "applicable",
            "gap",
            "no_gap",
            "unanswered",
            "review_required",
            "not_applicable",
        }
        assert payload["input_hash"] == analysis.input_hash

    def test_a_failed_generation_audits_nothing(self, world, tenant_a, user_a, monkeypatch):
        """The emit shares the write's transaction, so a failure rolls both
        back. An audit row for a snapshot that does not exist would be a false
        record."""
        from iig_checklist import gap_snapshots
        from iig_checklist.models import GapAnalysis, GapAnalysisItem

        def explode(*args, **kwargs):
            raise RuntimeError("item write failed")

        monkeypatch.setattr(GapAnalysisItem.objects, "bulk_create", explode)
        with pytest.raises(RuntimeError):
            gap_snapshots.generate(execution=world["execution"], tenant=tenant_a, actor=user_a)

        assert GapAnalysis.objects.count() == 0
        assert self._events().count() == 0

    def test_the_event_name_matches_the_declared_vocabulary(self):
        from iig_checklist.audit import IigChecklistEvent

        assert IigChecklistEvent.GAP_ANALYSIS_GENERATED == GAP_EVENT


# ---------------------------------------------------------------------------
# E. API, permissions, tenant isolation
# ---------------------------------------------------------------------------
def _list_url(execution):
    from django.urls import reverse

    return reverse(
        "iig_checklist:execution-gap-analyses", kwargs={"public_id": execution.public_id}
    )


def _detail_url(execution, analysis):
    from django.urls import reverse

    return reverse(
        "iig_checklist:execution-gap-analysis-detail",
        kwargs={"public_id": execution.public_id, "analysis_public_id": analysis.public_id},
    )


class TestApi:
    def test_post_creates_and_returns_201(self, world, api_client_doer):
        response = api_client_doer.post(_list_url(world["execution"]), {}, format="json")
        assert response.status_code == 201
        assert response.data["counts"]["review_required"] == 1
        assert len(response.data["items"]) == 6

    def test_a_second_post_returns_200_and_the_same_snapshot(self, world, api_client_doer):
        first = api_client_doer.post(_list_url(world["execution"]), {}, format="json")
        second = api_client_doer.post(_list_url(world["execution"]), {}, format="json")
        assert second.status_code == 200
        assert second.data["public_id"] == first.data["public_id"]

    def test_the_list_reports_whether_the_latest_is_current(self, world, api_client_doer):
        api_client_doer.post(_list_url(world["execution"]), {}, format="json")
        listed = api_client_doer.get(_list_url(world["execution"]))
        assert listed.status_code == 200
        assert listed.data["latest_is_current"] is True

        _answer(world["responses"], "Q-BLANK", raw_value="no")
        listed = api_client_doer.get(_list_url(world["execution"]))
        assert listed.data["latest_is_current"] is False

    def test_an_empty_history_is_not_an_error(self, world, api_client_doer):
        listed = api_client_doer.get(_list_url(world["execution"]))
        assert listed.status_code == 200
        assert listed.data["results"] == []
        assert listed.data["latest_is_current"] is False

    def test_the_detail_view_serves_items_with_their_question_text(self, world, api_client_doer):
        from iig_checklist.models import GapAnalysis

        api_client_doer.post(_list_url(world["execution"]), {}, format="json")
        analysis = GapAnalysis.objects.get()
        response = api_client_doer.get(_detail_url(world["execution"], analysis))
        assert response.status_code == 200
        codes = {item["question_code"] for item in response.data["items"]}
        assert codes == {"Q-YES", "Q-NO", "Q-BLANK", "Q-NA", "Q-TEXT", "Q-REVIEW"}
        assert all(item["question_text"] for item in response.data["items"])

    def test_the_snapshot_response_reports_no_score(self, world, api_client_doer):
        response = api_client_doer.post(_list_url(world["execution"]), {}, format="json")
        assert "score_percent" not in response.data
        assert "score_percent" not in response.data["counts"]

    def test_the_legacy_route_still_answers(self, world, api_client_doer):
        from django.urls import reverse

        url = reverse(
            "iig_checklist:execution-gap-analysis",
            kwargs={"public_id": world["execution"].public_id},
        )
        response = api_client_doer.get(url)
        assert response.status_code == 200
        assert response.data["review_required"] == 1
        assert "score_percent" in response.data


class TestPermissions:
    def test_generating_is_not_implied_by_viewing(
        self, world, api_client_tenant_admin, tenant_admin_user, tenant_a
    ):
        """Tenant Admin holds view_execution and not generate_gap_analysis, so
        it can read history but not write a record."""
        from iig_checklist.permissions import (
            PERM_GENERATE_GAP_ANALYSIS,
            PERM_VIEW_EXECUTION,
            has_iig_checklist_permission,
        )

        assert has_iig_checklist_permission(tenant_admin_user, tenant_a, PERM_VIEW_EXECUTION)
        assert not has_iig_checklist_permission(
            tenant_admin_user, tenant_a, PERM_GENERATE_GAP_ANALYSIS
        )
        assert api_client_tenant_admin.get(_list_url(world["execution"])).status_code == 200
        assert (
            api_client_tenant_admin.post(
                _list_url(world["execution"]), {}, format="json"
            ).status_code
            == 403
        )

    def test_a_reviewer_may_generate(self, world, api_client_reviewer):
        assert (
            api_client_reviewer.post(_list_url(world["execution"]), {}, format="json").status_code
            == 201
        )

    def test_platform_support_holds_neither(self, world, api_client_platform_support):
        assert api_client_platform_support.get(_list_url(world["execution"])).status_code == 403


class TestTenantIsolation:
    def test_another_tenant_cannot_read_the_history(
        self, world, tenant_a, user_a, tenant_b, api_client_doer
    ):
        from iig_checklist.gap_snapshots import generate

        generate(execution=world["execution"], tenant=tenant_a, actor=user_a)
        # Same authenticated client, pointed at a tenant that does not own the
        # execution: the execution lookup is tenant-scoped, so it is simply not
        # there.
        api_client_doer.credentials(HTTP_X_TENANT_SLUG=tenant_b.slug)
        assert api_client_doer.get(_list_url(world["execution"])).status_code in {403, 404}

    def test_a_snapshot_is_scoped_to_its_own_tenant(self, world, tenant_a, tenant_b, user_a):
        from iig_checklist.gap_snapshots import analyses_for, generate

        generate(execution=world["execution"], tenant=tenant_a, actor=user_a)
        assert analyses_for(world["execution"], tenant_a).count() == 1
        assert analyses_for(world["execution"], tenant_b).count() == 0

    def test_a_detail_lookup_cannot_cross_tenant(self, world, tenant_a, tenant_b, user_a):
        from iig_checklist.gap_snapshots import generate
        from iig_checklist.models import GapAnalysis

        analysis, _ = generate(execution=world["execution"], tenant=tenant_a, actor=user_a)
        assert not GapAnalysis.objects.filter(
            public_id=analysis.public_id, tenant=tenant_b
        ).exists()


# ---------------------------------------------------------------------------
# F. Wording
# ---------------------------------------------------------------------------
class TestNoRegulatoryOverclaim:
    FORBIDDEN = (
        "fda compliant",
        "fda ready",
        "submission ready",
        "submission acceptable",
        "agency ready",
        "agency approved",
        "compliant",
        "non-compliant",
        "noncompliant",
        "certified",
    )

    def test_no_status_or_reason_code_claims_a_regulatory_conclusion(self):
        from iig_checklist.gap_analysis import GapStatus, ReasonCode

        vocabulary = [
            value
            for holder in (GapStatus, ReasonCode)
            for name, value in vars(holder).items()
            if not name.startswith("_") and isinstance(value, str)
        ]
        for term in vocabulary:
            assert term.lower() not in self.FORBIDDEN

    def test_the_api_payload_uses_no_overclaiming_language(self, world, api_client_doer):
        response = api_client_doer.post(_list_url(world["execution"]), {}, format="json")
        blob = str(response.data).lower()
        for forbidden in self.FORBIDDEN:
            assert forbidden not in blob
