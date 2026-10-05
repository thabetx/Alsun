import json
import os
import sys
import types
import unittest
from types import SimpleNamespace
from unittest import mock

from helpers import FakeLlm

from fastapi.testclient import TestClient

import llm
import quran_detect

# When a model does not answer (an error, nothing in time, an empty answer, not json when json is asked), the question
# goes to the next model of llm.fallback_chain, and the user is told. The models here are always fakes.

MESSAGES = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
GPT5 = {"provider": "openai", "model": "gpt-5"}
COHERE_PLUS = {"provider": "cohere", "model": "command-a-plus-05-2026"}
COHERE_AYA = {"provider": "cohere", "model": "c4ai-aya-expanse-32b"}


class FakeCohere:
    def __init__(self, behavior):
        self.behavior = behavior  # a function(kwargs) -> text, it may raise
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        text = self.behavior(kwargs)
        return SimpleNamespace(message=SimpleNamespace(content=[SimpleNamespace(type="text", text=text)]))


def openai_client(behavior):
    fake = FakeLlm(behavior)
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake))), fake


def boom(kwargs):
    raise RuntimeError("the model is down")


class FallbackTestCase(unittest.TestCase):
    def setUp(self):
        llm.forget_failures()
        self.addCleanup(llm.forget_failures)
        patcher = mock.patch.dict(os.environ, {"OPENAI_API_KEY": "fake-key-for-tests", "COHERE_API_KEY": "fake-key-for-tests"})
        patcher.start()
        self.addCleanup(patcher.stop)


class TestChain(FallbackTestCase):
    def test_the_chosen_model_then_the_safe_one_of_its_provider_then_the_other_provider(self):
        self.assertEqual(llm.fallback_chain(GPT5), [GPT5, llm.DEFAULT_MODEL, COHERE_PLUS])
        self.assertEqual(llm.fallback_chain(COHERE_AYA), [COHERE_AYA, COHERE_PLUS, llm.DEFAULT_MODEL])

    def test_the_default_model_goes_to_the_other_provider_only(self):
        self.assertEqual(llm.fallback_chain(None), [llm.DEFAULT_MODEL, COHERE_PLUS])

    def test_a_provider_without_a_key_is_never_in_the_chain(self):
        with mock.patch.dict(os.environ, {"COHERE_API_KEY": ""}):
            self.assertEqual(llm.fallback_chain(GPT5), [GPT5, llm.DEFAULT_MODEL])
            self.assertEqual(llm.fallback_chain(None), [llm.DEFAULT_MODEL])


class TestSwitching(FallbackTestCase):
    def test_a_model_that_answers_is_the_only_one_asked(self):
        client, fake = openai_client(lambda kwargs: "fine")
        with llm.track_fallbacks() as fallbacks:
            self.assertEqual(llm.chat_text(client, MESSAGES, GPT5), "fine")
        self.assertEqual(fallbacks, [])
        self.assertEqual([call["model"] for call in fake.calls], ["gpt-5"])

    def test_an_error_goes_to_the_safe_model_of_the_same_provider(self):
        def behavior(kwargs):
            if kwargs["model"] == "gpt-5":
                raise RuntimeError("the model does not exist")
            return "from the safe model"

        client, fake = openai_client(behavior)
        with llm.track_fallbacks() as fallbacks:
            text = llm.chat_text(client, MESSAGES, GPT5)
        self.assertEqual(text, "from the safe model")
        self.assertEqual([call["model"] for call in fake.calls], ["gpt-5", "gpt-4o-mini"])
        self.assertEqual(len(fallbacks), 1)
        self.assertEqual((fallbacks[0]["from"], fallbacks[0]["to"]), ("gpt-5", "gpt-4o-mini"))
        self.assertIn("does not exist", fallbacks[0]["reason"])

    def test_an_empty_answer_counts_as_a_failure(self):
        answers = iter(["   ", "a real answer"])
        client, fake = openai_client(lambda kwargs: next(answers))
        self.assertEqual(llm.chat_text(client, MESSAGES, GPT5), "a real answer")

    def test_an_answer_that_is_not_json_counts_as_a_failure_when_json_is_asked(self):
        answers = iter(["not json at all", '{"items": []}'])
        client, fake = openai_client(lambda kwargs: next(answers))
        self.assertEqual(llm.chat_text(client, MESSAGES, GPT5, json_output=True), '{"items": []}')
        self.assertEqual(len(fake.calls), 2)

    def test_if_both_models_of_a_provider_fail_the_other_provider_answers(self):
        client, openai_fake = openai_client(boom)
        cohere = FakeCohere(lambda kwargs: "Cohere answer")
        with mock.patch.object(llm, "get_cohere_client", return_value=cohere), llm.track_fallbacks() as fallbacks:
            text = llm.chat_text(client, MESSAGES, GPT5)
        self.assertEqual(text, "Cohere answer")
        self.assertEqual([call["model"] for call in openai_fake.calls], ["gpt-5", "gpt-4o-mini"])
        self.assertEqual(cohere.calls[0]["model"], "command-a-plus-05-2026")
        self.assertEqual([(f["from"], f["to"]) for f in fallbacks],
                         [("gpt-5", "gpt-4o-mini"), ("gpt-4o-mini", "command-a-plus-05-2026")])

    def test_a_cohere_model_that_fails_goes_to_openai(self):
        client, openai_fake = openai_client(lambda kwargs: "OpenAI answer")
        cohere = FakeCohere(boom)
        with mock.patch.object(llm, "get_cohere_client", return_value=cohere):
            text = llm.chat_text(client, MESSAGES, COHERE_AYA)
        self.assertEqual(text, "OpenAI answer")
        self.assertEqual([call["model"] for call in cohere.calls], ["c4ai-aya-expanse-32b", "command-a-plus-05-2026"])

    def test_when_every_model_fails_there_is_one_error_with_a_message(self):
        client, fake = openai_client(boom)
        cohere = FakeCohere(boom)
        with mock.patch.object(llm, "get_cohere_client", return_value=cohere):
            with self.assertRaisesRegex(ValueError, "the models are not answering"):
                llm.chat_text(client, MESSAGES, GPT5)
        self.assertEqual(len(fake.calls) + len(cohere.calls), llm.MAX_ATTEMPTS)  # never more

    def test_without_a_second_model_the_error_is_a_message_too(self):
        client, fake = openai_client(boom)
        with mock.patch.dict(os.environ, {"COHERE_API_KEY": ""}):
            with self.assertRaisesRegex(ValueError, "the models are not answering"):
                llm.chat_text(client, MESSAGES, None)
        self.assertEqual(len(fake.calls), 1)

    def test_a_model_that_just_failed_is_skipped_by_the_next_questions(self):
        def behavior(kwargs):
            if kwargs["model"] == "gpt-5":
                raise RuntimeError("down")
            return "safe"

        client, fake = openai_client(behavior)
        llm.chat_text(client, MESSAGES, GPT5)
        with llm.track_fallbacks() as fallbacks:
            llm.chat_text(client, MESSAGES, GPT5)
        self.assertEqual([call["model"] for call in fake.calls], ["gpt-5", "gpt-4o-mini", "gpt-4o-mini"])  # not asked again
        self.assertIn("a moment ago", fallbacks[0]["reason"])

    def test_the_failure_is_forgotten_after_a_minute(self):
        client, fake = openai_client(lambda kwargs: "fine")
        llm._recent_failures[("openai", "gpt-5")] = llm.time.time() - llm.FAILURE_MEMORY_SECONDS - 1
        llm.chat_text(client, MESSAGES, GPT5)
        self.assertEqual(fake.calls[0]["model"], "gpt-5")

    def test_without_tracking_nothing_breaks(self):
        client, fake = openai_client(lambda kwargs: "fine")
        self.assertEqual(llm.chat_text(client, MESSAGES, None), "fine")


class TestFallbackInTheApp(FallbackTestCase):
    def setUp(self):
        super().setUp()
        sys.modules.setdefault("datalab_sdk", types.SimpleNamespace(ConvertOptions=object, DatalabClient=object))
        import main

        self.client = TestClient(main.app)
        llm._models_cache.clear()
        patcher = mock.patch.object(llm, "_fetch_models", return_value=["gpt-5"])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_translate_tells_the_front_when_the_model_was_changed(self):
        def behavior(kwargs):
            if kwargs["model"] == "gpt-5":
                raise RuntimeError("overloaded")
            return "Translation from the safe model"

        fake_llm = FakeLlm(behavior)
        with mock.patch.object(quran_detect.client.chat.completions, "create", fake_llm):
            response = self.client.post("/translate", json={
                "text": "نص", "target_lang": "English", "model": GPT5})
        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["segments"][0]["text"], "Translation from the safe model")
        self.assertEqual([(f["from"], f["to"]) for f in body["fallbacks"]][:1], [("gpt-5", "gpt-4o-mini")])

    def test_no_switch_means_no_fallbacks_key(self):
        fake_llm = FakeLlm(lambda kwargs: "fine")
        with mock.patch.object(quran_detect.client.chat.completions, "create", fake_llm):
            body = self.client.post("/translate", json={"text": "نص", "target_lang": "English"}).json()
        self.assertNotIn("fallbacks", body)

    def test_when_no_model_answers_the_user_gets_a_message(self):
        fake_llm = FakeLlm(boom)
        cohere = FakeCohere(boom)
        with mock.patch.object(quran_detect.client.chat.completions, "create", fake_llm), \
                mock.patch.object(llm, "get_cohere_client", return_value=cohere):
            response = self.client.post("/translate", json={"text": "نص", "target_lang": "English"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("the models are not answering", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
