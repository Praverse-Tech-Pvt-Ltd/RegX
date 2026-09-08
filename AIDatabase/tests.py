from unittest import mock

from django.test import TestCase

from AIDatabase import filters
from AIDatabase.filters import Form483Filter, get_synonyms_from_chatgpt
from AIDatabase.models import (
    Form483Master,
    Form483ObeservationContent,
    Form483Observation,
    Form483System,
)


def _make_observation(company_name, content):
    master = Form483Master.objects.create(company_name=company_name)
    system = Form483System.objects.create(master=master, system="Quality")
    observation = Form483Observation.objects.create(system=system, observation_number=1)
    Form483ObeservationContent.objects.create(
        observation=observation, content_category="OBS", content=content
    )
    return master


class GetSynonymsFromChatgptTests(TestCase):
    """The synonym helper must always hand back six lists, never raise."""

    def test_returns_six_empty_lists_when_no_api_key_is_configured(self):
        with mock.patch.object(filters, "_get_openai_client", return_value=None):
            result = get_synonyms_from_chatgpt("sterility failure")

        self.assertEqual(result, ([], [], [], [], [], []))

    def test_returns_six_empty_lists_when_the_api_call_raises(self):
        client = mock.Mock()
        client.chat.completions.create.side_effect = RuntimeError("boom")

        with mock.patch.object(filters, "_get_openai_client", return_value=client):
            result = get_synonyms_from_chatgpt("sterility failure")

        self.assertEqual(result, ([], [], [], [], [], []))

    def test_parses_keywords_synonyms_and_related_terms_into_the_first_list(self):
        payload = (
            '{"keywords": ["sterility"], "synonyms": ["aseptic"], '
            '"related_terms": ["contamination"], "dosage": [], "cmc": [], '
            '"deficiency": [], "category": [], "type_of_dosage": []}'
        )
        client = mock.Mock()
        client.chat.completions.create.return_value = mock.Mock(
            choices=[mock.Mock(message=mock.Mock(content=payload))]
        )

        with mock.patch.object(filters, "_get_openai_client", return_value=client):
            search_terms, *rest = get_synonyms_from_chatgpt("sterility")

        self.assertCountEqual(search_terms, ["sterility", "aseptic", "contamination"])
        self.assertEqual(rest, [[], [], [], [], []])


class FilterObservationContentTests(TestCase):
    """
    Regression tests for the observation search filter.

    It previously assigned the whole six-tuple to `search_terms` and iterated
    it, building Q(content__icontains=<list>) instead of one Q per term.
    """

    def setUp(self):
        self.sterility = _make_observation("Acme Pharma", "Sterility test failure observed.")
        self.cleaning = _make_observation("Beta Labs", "Cleaning validation was inadequate.")

    def _filter(self, value, synonyms):
        with mock.patch.object(filters, "get_synonyms_from_chatgpt", return_value=synonyms):
            return list(
                Form483Filter().filter_observation_content(
                    Form483Master.objects.all(), "search", value
                )
            )

    def test_blank_value_leaves_the_queryset_untouched(self):
        self.assertCountEqual(self._filter("", None), [self.sterility, self.cleaning])

    def test_matches_on_the_literal_query(self):
        empty = ([], [], [], [], [], [])
        self.assertEqual(self._filter("Sterility", empty), [self.sterility])

    def test_expansion_failure_falls_back_to_the_literal_query_not_everything(self):
        empty = ([], [], [], [], [], [])
        self.assertEqual(self._filter("Cleaning", empty), [self.cleaning])

    def test_synonyms_widen_the_match_beyond_the_literal_query(self):
        synonyms = (["Cleaning"], [], [], [], [], [])
        self.assertCountEqual(
            self._filter("Sterility", synonyms), [self.sterility, self.cleaning]
        )

    def test_only_the_first_list_is_used_for_content_matching(self):
        # "Cleaning" sits in the dosage list, which does not apply to content.
        synonyms = ([], ["Cleaning"], [], [], [], [])
        self.assertEqual(self._filter("Sterility", synonyms), [self.sterility])
