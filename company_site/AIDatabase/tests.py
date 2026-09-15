"""P8 -- the Form 483 search, and the absence of the legacy chatbot.

Two things are proven here, and the second is as important as the first.

The Form 483 observation search used to expand the typed query into synonyms
through a ChatGPT call before searching the database. That made an ordinary
filter submission on a logged-in page reach a paid external API, and it did not
even work: the helper returned a six-tuple of lists while the caller iterated it
as a flat list of terms, so every search built `icontains=[]` and matched
nothing. Anyone using the box got an empty result set and no error.

So these tests assert the search *works* -- which it did not before -- and, in
the same breath, that it reaches no network. A test that only checked the
results would pass equally well on a version that quietly called out to an API
first, which is precisely the state being removed.

The chatbot assertions are absence checks. Absences are the kind of requirement
that stops holding quietly, and this code was reachable-by-uncommenting for its
whole life in the repository.
"""

import re
import socket
from pathlib import Path

from django.apps import apps
from django.test import TestCase
from django.urls import NoReverseMatch, reverse

from .models import (
    Form483Master,
    Form483Observation,
    Form483ObeservationContent,
    Form483System,
)

APP_DIR = Path(__file__).resolve().parent

#: Every live Python module of this app. Comment bodies are stripped before
#: these are searched, so a mention inside dead commented code does not fail a
#: test that is about live references.
LIVE_MODULES = sorted(p for p in APP_DIR.glob("*.py") if p.name != "tests.py")

#: `observation_summary.py` is a *different*, pre-existing OpenAI integration
#: and is deliberately out of scope here: it generates Form 483 observation
#: summaries during an Excel cache refresh, has a real caller, and is already
#: off by default behind an explicit API-key check. P8 removed the accidental
#: dependency on the *search* path; it did not touch this one. Its gate is
#: pinned by `ObservationSummaryStaysGatedTests` below rather than being
#: exempted silently.
OPENAI_MODULES_OUT_OF_SCOPE = {"observation_summary.py"}

SEARCH_PATH_MODULES = [p for p in LIVE_MODULES if p.name not in OPENAI_MODULES_OUT_OF_SCOPE]


def _live_source(path: Path) -> str:
    """The file's source with whole-line comments removed.

    Crude on purpose: it is enough to tell "this name is referenced by code"
    from "this name appears in a comment", and anything cleverer would need a
    parser for a file this cleanup did not otherwise touch.
    """
    return "\n".join(
        line for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )


class NetworkBlocked(AssertionError):
    """Raised if anything tries to open a socket during a guarded block."""


class _NoNetwork:
    """Fail loudly on any outbound connection attempt.

    Patching `socket.socket.connect` rather than the OpenAI client is
    deliberate. A double for the client would only prove that *that* client was
    not used; this proves nothing reached the network at all, by any route.
    """

    def __enter__(self):
        self._real = socket.socket.connect

        def refuse(sock, address):
            raise NetworkBlocked(f"the search attempted a network connection to {address!r}")

        socket.socket.connect = refuse
        return self

    def __exit__(self, *exc_info):
        socket.socket.connect = self._real
        return False


class Form483SearchTests(TestCase):
    """The visible search feature, doing plain database work."""

    @classmethod
    def setUpTestData(cls):
        cls.matching = Form483Master.objects.create(
            company_name="Synthetic Pharma A",
            city="Springfield",
            year_of_inspection="2024",
        )
        cls.other = Form483Master.objects.create(
            company_name="Synthetic Pharma B",
            city="Shelbyville",
            year_of_inspection="2024",
        )
        cls._observation(
            cls.matching,
            "Equipment used in the manufacture of drug products is not of appropriate design.",
        )
        cls._observation(
            cls.other,
            "Written procedures for cleaning and maintenance were not followed.",
        )

    @classmethod
    def _observation(cls, master, content):
        system = Form483System.objects.create(master=master, system="Quality")
        observation = Form483Observation.objects.create(system=system, observation_number=1)
        return Form483ObeservationContent.objects.create(
            observation=observation, content_category="OBS", content=content
        )

    def _search(self, term):
        from .filters import Form483Filter

        filterset = Form483Filter(
            {"search": term}, queryset=Form483Master.objects.all()
        )
        return list(filterset.qs)

    def test_a_matching_term_returns_the_record(self):
        self.assertEqual(self._search("appropriate design"), [self.matching])

    def test_the_match_is_case_insensitive(self):
        """`icontains`, not `contains`: the box is a search field, and a user
        typing lowercase means the same thing as the source text's case."""
        self.assertEqual(self._search("APPROPRIATE DESIGN"), [self.matching])

    def test_a_partial_word_matches(self):
        self.assertEqual(self._search("manufactur"), [self.matching])

    def test_unmatched_text_returns_no_rows(self):
        self.assertEqual(self._search("no observation mentions this phrase"), [])

    def test_an_empty_search_returns_everything(self):
        """An unused filter must not narrow the page."""
        self.assertCountEqual(self._search(""), [self.matching, self.other])

    def test_a_term_matching_both_returns_both_once_each(self):
        """`distinct()` matters: a master has many observations, and several can
        match one term. Without it the page would repeat rows."""
        self._observation(self.matching, "Procedures were not followed on the second line.")
        results = self._search("procedures")
        self.assertCountEqual(results, [self.matching, self.other])
        self.assertEqual(len(results), len(set(results)))

    def test_the_search_makes_no_network_call(self):
        """The whole point of the change. Any socket attempt fails the test."""
        with _NoNetwork():
            self.assertEqual(self._search("appropriate design"), [self.matching])

    def test_the_search_page_renders_without_a_network_call(self):
        """End to end through the view that owns the filter, because the filter
        being clean would not help if the view reached the API another way."""
        from AdminMaster.models import CustomUser

        CustomUser.objects.create_user(
            username="p8-tester", email="p8@example.invalid", password="SyntheticPass1234!"
        )
        self.client.login(username="p8-tester", password="SyntheticPass1234!")

        with _NoNetwork():
            response = self.client.get("/aidatabase/form483_database", {"search": "design"})
        self.assertEqual(response.status_code, 200)


class ChatbotIsGoneTests(TestCase):
    """The legacy chatbot left no live code behind."""

    CHATBOT_ROUTE_NAMES = [
        "chat_ui",
        "chat_with_bot",
        "clear_chat",
        "new_chat",
        "get_all_chat_histories",
        "get_all_chat_by_specific_id",
        "delete_chat_by_id",
    ]

    def test_no_chatbot_url_resolves(self):
        for name in self.CHATBOT_ROUTE_NAMES:
            with self.subTest(name=name):
                with self.assertRaises(NoReverseMatch):
                    reverse(name)

    def test_no_chat_path_is_served(self):
        for path in (
            "/aidatabase/chat_ui_view/",
            "/aidatabase/chat_with_bot/",
            "/aidatabase/clear_chat/",
            "/aidatabase/new_chat/",
            "/aidatabase/get_all_chat_histories/",
            "/aidatabase/delete_chat_by_id/1/",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_the_chat_models_are_gone(self):
        for model_name in ("ChatMessage", "ChatHistory"):
            with self.subTest(model=model_name):
                with self.assertRaises(LookupError):
                    apps.get_model("AIDatabase", model_name)

    def test_no_live_module_references_the_chat_models(self):
        for path in LIVE_MODULES:
            with self.subTest(module=path.name):
                source = _live_source(path)
                self.assertNotIn("ChatMessage", source)
                self.assertNotIn("ChatHistory", source)

    def test_the_serializer_module_is_gone(self):
        self.assertFalse((APP_DIR / "serializers.py").exists())
        with self.assertRaises(ImportError):
            __import__("AIDatabase.serializers", fromlist=["ChatMessageSerializer"])

    def test_the_chatbot_template_is_gone(self):
        templates = APP_DIR.parent / "templates" / "AIDatabase" / "Chatbot"
        self.assertFalse(templates.exists())

    def test_admin_and_views_still_import(self):
        """The serializer and model deletions could have broken either module;
        both are imported at startup, so a mistake would take the site down."""
        import importlib

        for module in ("AIDatabase.views", "AIDatabase.admin", "AIDatabase.filters"):
            with self.subTest(module=module):
                self.assertIsNotNone(importlib.import_module(module))

    def test_the_admin_registry_holds_no_chat_model(self):
        from django.contrib import admin

        registered = {model.__name__ for model in admin.site._registry}
        self.assertNotIn("ChatMessage", registered)
        self.assertNotIn("ChatHistory", registered)


class NoOpenAiInThisAppTests(TestCase):
    """The accidental live dependency, and its absence now."""

    def test_no_search_path_module_imports_openai(self):
        for path in SEARCH_PATH_MODULES:
            with self.subTest(module=path.name):
                source = _live_source(path)
                self.assertNotRegex(source, r"^\s*import openai\b")
                self.assertNotRegex(source, r"^\s*from openai\b")

    def test_no_search_path_module_calls_chat_completion(self):
        for path in SEARCH_PATH_MODULES:
            with self.subTest(module=path.name):
                source = _live_source(path)
                self.assertNotIn("ChatCompletion", source)
                self.assertNotIn("chat.completions", source)

    def test_the_synonym_helper_is_gone(self):
        from . import filters

        self.assertFalse(hasattr(filters, "get_synonyms_from_chatgpt"))

    def test_no_live_module_calls_the_synonym_helper(self):
        """Commented references remain further down `filters.py`; those are
        dead, and uncommenting one now raises NameError rather than silently
        restoring a billed call. Only live code is checked here."""
        for path in LIVE_MODULES:
            with self.subTest(module=path.name):
                self.assertNotIn("get_synonyms_from_chatgpt", _live_source(path))

    def test_no_api_key_literal_is_committed_in_this_app(self):
        """A key-shaped literal would be a secret in the repository whatever it
        was for."""
        for path in LIVE_MODULES:
            with self.subTest(module=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIsNone(re.search(r"sk-[A-Za-z0-9_\-]{20,}", text))


class ObservationSummaryStaysGatedTests(TestCase):
    """The one OpenAI integration P8 deliberately leaves in place.

    `observation_summary.generate_summary` produces Form 483 observation
    summaries during an Excel cache refresh. It is not the search path and was
    not the accidental dependency: it has a real caller and a real gate.

    It is pinned here rather than exempted quietly, because "we left it alone"
    and "we left it switched off" are different claims and only the second one
    is worth anything. The gate is an explicit API-key check, so unlike the
    helper P8 removed, no dependency or SDK version change can switch it on.
    """

    def setUp(self):
        from . import observation_summary

        # The client is memoised at module level; reset it so each test sees a
        # first call rather than a cached decision from another test.
        observation_summary._openai_client = None
        observation_summary._openai_client_initialized = False

    def test_no_client_is_built_without_an_api_key(self):
        from . import observation_summary

        with self.settings(OPENAI_API_KEY=None):
            observation_summary.openai.api_key = None
            self.assertIsNone(observation_summary._get_openai_client())

    def test_generate_summary_returns_none_and_makes_no_call_without_a_key(self):
        from . import observation_summary

        with self.settings(OPENAI_API_KEY=None):
            observation_summary.openai.api_key = None
            with _NoNetwork():
                self.assertIsNone(observation_summary.generate_summary("Some observation text."))

    def test_the_gate_is_an_api_key_check_not_an_sdk_version_check(self):
        """What made the removed search helper dangerous was that its only
        real guard was an SDK incompatibility -- restore an older `openai` and
        set a key, and billed calls resume on a page render. This gate reads
        the key itself, so it cannot be opened by a dependency bump."""
        import inspect

        from . import observation_summary

        source = inspect.getsource(observation_summary._get_openai_client)
        self.assertIn("api_key", source)
        self.assertIn("if not api_key", source)
