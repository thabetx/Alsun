import json
import os
import sys
import types
import unittest
from types import SimpleNamespace
from unittest import mock

from helpers import FakeLlm

from fastapi import FastAPI
from fastapi.testclient import TestClient

import assistant_routes
import llm
import modify_fragment
import modify_many_paragraphs
import quran_detect
import settings_routes

# The settings of the user: the model (OpenAI or Cohere, the same prompts for both) and the quran translation.
# The models are always faked here: no cost, no internet, no real key.

COHERE = {"provider": "cohere", "model": "command-a-plus-05-2026"}
AYAH_TEXT = "اذيا صاحبي علمه شديد القوي ذو مرة فاستوي"  # normal text + An-Najm 53:5-6


def cohere_answer(*parts):
    # what the cohere sdk gives: message.content is a list of parts; a thinking part has no .text
    return SimpleNamespace(message=SimpleNamespace(content=list(parts)))


def text_part(text):
    return SimpleNamespace(type="text", text=text)


class FakeCohere:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return self.answer


class TestChatText(unittest.TestCase):
    MESSAGES = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]

    def test_without_a_model_it_is_the_default_openai_one(self):
        fake_llm = FakeLlm(lambda kwargs: "answer")
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_llm)))
        self.assertEqual(llm.chat_text(client, self.MESSAGES), "answer")
        self.assertEqual(fake_llm.calls[0]["model"], "gpt-4o-mini")
        self.assertEqual(fake_llm.calls[0]["messages"], self.MESSAGES)
        self.assertNotIn("response_format", fake_llm.calls[0])

    def test_openai_with_another_model_and_json(self):
        fake_llm = FakeLlm(lambda kwargs: "{}")
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_llm)))
        llm.chat_text(client, self.MESSAGES, {"provider": "openai", "model": "some-model"}, json_output=True)
        self.assertEqual(fake_llm.calls[0]["timeout"], 60)
        self.assertEqual(fake_llm.calls[0]["model"], "some-model")
        self.assertEqual(fake_llm.calls[0]["response_format"], {"type": "json_object"})

    def test_cohere_gets_the_same_messages_and_gives_the_text(self):
        cohere = FakeCohere(cohere_answer(text_part("the translation")))
        with mock.patch.object(llm, "get_cohere_client", return_value=cohere):
            text = llm.chat_text(None, self.MESSAGES, COHERE)
        self.assertEqual(text, "the translation")
        self.assertEqual(len(cohere.calls), 1)
        self.assertEqual(cohere.calls[0]["model"], "command-a-plus-05-2026")
        self.assertEqual(cohere.calls[0]["messages"], self.MESSAGES)
        self.assertEqual(cohere.calls[0]["request_options"], {"timeout_in_millis": 60000})

    def test_cohere_json(self):
        cohere = FakeCohere(cohere_answer(text_part("{}")))
        with mock.patch.object(llm, "get_cohere_client", return_value=cohere):
            llm.chat_text(None, self.MESSAGES, COHERE, json_output=True)
        self.assertEqual(cohere.calls[0]["response_format"], {"type": "json_object"})

    def test_cohere_thoughts_are_not_the_answer(self):
        thinking = SimpleNamespace(type="thinking", thinking="let me think")  # no .text
        cohere = FakeCohere(cohere_answer(thinking, text_part("the translation")))
        with mock.patch.object(llm, "get_cohere_client", return_value=cohere):
            self.assertEqual(llm.chat_text(None, self.MESSAGES, COHERE), "the translation")

    def test_cohere_with_an_empty_answer_is_an_error(self):
        cohere = FakeCohere(cohere_answer())
        with mock.patch.object(llm, "get_cohere_client", return_value=cohere):
            with self.assertRaisesRegex(ValueError, "empty"):
                llm.chat_text(None, self.MESSAGES, COHERE)

    def test_cohere_without_a_key_says_where_to_put_it(self):
        with mock.patch.dict(os.environ, {"COHERE_API_KEY": ""}), mock.patch.object(llm, "_cohere_client", None):
            with self.assertRaisesRegex(ValueError, "COHERE_API_KEY"):
                llm.get_cohere_client()


class TestResolveModel(unittest.TestCase):
    def setUp(self):
        llm._models_cache.clear()
        patcher = mock.patch.dict(os.environ, {"COHERE_API_KEY": "fake-key-for-tests", "OPENAI_API_KEY": "fake-key-for-tests"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_nothing_chosen_means_the_default(self):
        self.assertIsNone(llm.resolve_model(None))

    def test_a_known_model_needs_no_call_to_the_provider(self):
        with mock.patch.object(llm, "_fetch_models", side_effect=AssertionError("no call expected")):
            self.assertEqual(llm.resolve_model(COHERE), COHERE)
            self.assertEqual(llm.resolve_model({"provider": "cohere", "model": "command-a-translate-08-2025"})["model"],
                             "command-a-translate-08-2025")

    def test_a_model_the_provider_lists_is_accepted_exactly_as_written(self):
        with mock.patch.object(llm, "_fetch_models", return_value=["gpt-6-luna", "gpt-4o"]):
            self.assertEqual(llm.resolve_model({"provider": "openai", "model": "gpt-6-luna"})["model"], "gpt-6-luna")

    def test_a_model_the_provider_does_not_list_is_refused(self):
        with mock.patch.object(llm, "_fetch_models", return_value=["gpt-4o"]):
            with self.assertRaisesRegex(ValueError, "not available"):
                llm.resolve_model({"provider": "openai", "model": "gpt-9-imaginary"})

    def test_if_the_list_cannot_be_read_only_the_known_models_work(self):
        with mock.patch.object(llm, "_fetch_models", side_effect=RuntimeError("no internet")):
            with self.assertRaisesRegex(ValueError, "not available"):
                llm.resolve_model({"provider": "openai", "model": "gpt-6-luna"})
            self.assertEqual(llm.resolve_model(COHERE), COHERE)

    def test_unknown_provider_and_bad_names_are_refused(self):
        with self.assertRaisesRegex(ValueError, "provider"):
            llm.resolve_model({"provider": "other", "model": "x"})
        for bad in ["", "a b", "x;rm", "../x", "m" * 101]:
            with self.assertRaisesRegex(ValueError, "not valid"):
                llm.resolve_model({"provider": "cohere", "model": bad})

    def test_a_provider_without_a_key_is_refused(self):
        with mock.patch.dict(os.environ, {"COHERE_API_KEY": ""}):
            with self.assertRaisesRegex(ValueError, "COHERE_API_KEY"):
                llm.resolve_model(COHERE)


class TestModelList(unittest.TestCase):
    def setUp(self):
        llm._models_cache.clear()
        patcher = mock.patch.dict(os.environ, {"COHERE_API_KEY": "fake-key-for-tests", "OPENAI_API_KEY": "fake-key-for-tests"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_known_models_come_first_then_the_provider_ones(self):
        with mock.patch.object(llm, "_fetch_models", return_value=["z-model", "command-a-plus-05-2026", "a-model"]):
            self.assertEqual(llm.list_models("cohere"), llm.KNOWN_MODELS["cohere"] + ["a-model", "z-model"])
            self.assertEqual(llm.list_models("cohere")[:2], ["command-a-plus-05-2026", "command-a-translate-08-2025"])

    def test_the_list_is_kept_for_a_while(self):
        with mock.patch.object(llm, "_fetch_models", return_value=["a"]) as fetch:
            llm.list_models("cohere")
            llm.list_models("cohere")
        self.assertEqual(fetch.call_count, 1)

    def test_options_say_which_providers_have_a_key(self):
        with mock.patch.dict(os.environ, {"COHERE_API_KEY": ""}), \
                mock.patch.object(llm, "_fetch_models", return_value=["gpt-4o-mini", "gpt-x", "gpt-5"]):
            options = {option["provider"]: option for option in llm.model_options()}
        self.assertTrue(options["openai"]["has_key"])
        # only the recommended models the provider has: "gpt-x" is not offered, "gpt-4.1" is not there
        self.assertEqual([item["id"] for item in options["openai"]["models"]], ["gpt-4o-mini", "gpt-5"])
        self.assertTrue(all(item["note"] for item in options["openai"]["models"]))
        self.assertFalse(options["cohere"]["has_key"])
        self.assertEqual(options["cohere"]["models"], [])

    def test_if_the_list_fails_the_known_models_are_offered(self):
        with mock.patch.object(llm, "_fetch_models", side_effect=RuntimeError("down")):
            options = {option["provider"]: option for option in llm.model_options()}
        self.assertTrue(options["cohere"]["list_failed"])
        self.assertEqual([item["id"] for item in options["cohere"]["models"]], llm.KNOWN_MODELS["cohere"])


class TestQuranSources(unittest.TestCase):
    def test_the_first_source_of_a_language_is_the_default(self):
        self.assertEqual(quran_detect.find_quran_source("English")["id"], "hilali_khan")
        self.assertEqual(quran_detect.find_quran_file("English").name, "quran_en_hilali_khan.json")

    def test_a_source_can_be_chosen_by_its_id(self):
        self.assertEqual(quran_detect.find_quran_file("English", "saheeh").name, "quran_en_saheeh.json")

    def test_an_unknown_source_is_refused(self):
        with self.assertRaisesRegex(ValueError, "No quran translation"):
            quran_detect.find_quran_file("English", "nope")
        with self.assertRaisesRegex(ValueError, "No quran translation"):
            quran_detect.find_quran_file("French", "saheeh")  # a source of another language

    def test_the_options_list_every_language_and_mark_the_default(self):
        options = quran_detect.quran_source_options()
        self.assertEqual([item["id"] for item in options["English"]], ["hilali_khan", "saheeh"])
        self.assertEqual([item["default"] for item in options["English"]], [True, False])
        self.assertEqual(len(options["French"]), 1)

    def test_every_source_file_exists(self):
        for language, sources in quran_detect.QURAN_SOURCES.items():
            for source in sources:
                self.assertTrue((quran_detect.DATA_DIR / source["file"]).exists(), source["file"])


def echo(kwargs):
    return "<LLM>"


class TestChoicesReachTheModels(unittest.TestCase):
    def test_translate_uses_the_chosen_quran_source_and_marks_the_ayah(self):
        fake_llm = FakeLlm(echo)
        with mock.patch.object(quran_detect.client.chat.completions, "create", fake_llm):
            segments = quran_detect.translate_paragraph_segments(AYAH_TEXT, quran_source="saheeh")
        quran = json.loads(quran_detect.find_quran_file("English", "saheeh").read_text(encoding="utf-8"))
        self.assertEqual(segments[1]["text"], " ".join(quran["53"]["ayahs"][str(n)] for n in (5, 6)))
        self.assertEqual(segments[1]["quran_source"], "saheeh")
        self.assertNotIn("quran_source", segments[0])

    def test_translate_with_cohere_does_not_call_openai(self):
        cohere = FakeCohere(cohere_answer(text_part("Cohere translation")))
        fake_llm = FakeLlm(echo)
        with mock.patch.object(quran_detect.client.chat.completions, "create", fake_llm), \
                mock.patch.object(llm, "get_cohere_client", return_value=cohere):
            segments = quran_detect.translate_paragraph_segments(AYAH_TEXT, model=COHERE)
        self.assertEqual(segments[0]["text"], "Cohere translation")
        self.assertEqual(fake_llm.calls, [])
        self.assertEqual(cohere.calls[0]["model"], "command-a-plus-05-2026")
        self.assertIn("English", cohere.calls[0]["messages"][0]["content"])  # the same prompt

    def test_the_assistant_uses_the_chosen_model(self):
        cohere = FakeCohere(cohere_answer(text_part("short")))
        with mock.patch.object(llm, "get_cohere_client", return_value=cohere):
            replacement = modify_fragment.suggest_fragment_replacement(
                {"type": "normal", "text": "a long text"}, 0, 6, "shorten", COHERE)
        self.assertEqual(replacement, "short")

        cohere = FakeCohere(cohere_answer(text_part(json.dumps({"items": [{"key": "0", "text": "changed"}]}))))
        paragraphs = [[{"id": "seg_1", "type": "normal", "text": "text", "original": "ن"}]]
        with mock.patch.object(llm, "get_cohere_client", return_value=cohere):
            result = modify_many_paragraphs.modify_many_paragraphs(paragraphs, "change", COHERE)
        self.assertEqual(result[0][0]["text"], "changed")
        self.assertEqual(cohere.calls[0]["response_format"], {"type": "json_object"})


class TestSettingsEndpoints(unittest.TestCase):
    def setUp(self):
        sys.modules.setdefault("datalab_sdk", types.SimpleNamespace(ConvertOptions=object, DatalabClient=object))
        import main

        self.client = TestClient(main.app)
        llm._models_cache.clear()
        patcher = mock.patch.dict(os.environ, {"COHERE_API_KEY": "fake-key-for-tests"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_options_have_the_models_and_the_quran_sources(self):
        with mock.patch.object(llm, "_fetch_models", return_value=["gpt-x"]):
            body = self.client.get("/settings/options").json()
        self.assertEqual([option["provider"] for option in body["models"]], ["openai", "cohere"])
        self.assertIn("English", body["quran_sources"])

    def test_translate_with_a_model_and_a_quran_source(self):
        cohere = FakeCohere(cohere_answer(text_part("Cohere translation")))
        with mock.patch.object(llm, "get_cohere_client", return_value=cohere):
            response = self.client.post("/translate", json={
                "text": AYAH_TEXT, "target_lang": "English", "quran_source": "saheeh",
                "model": COHERE})
        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["segments"][0]["text"], "Cohere translation")
        self.assertEqual(body["segments"][1]["quran_source"], "saheeh")

    def test_a_bad_model_or_source_is_refused_before_any_call(self):
        fake_llm = FakeLlm(echo)
        with mock.patch.object(quran_detect.client.chat.completions, "create", fake_llm), \
                mock.patch.object(llm, "_fetch_models", return_value=[]):
            bad_model = self.client.post("/translate", json={
                "text": AYAH_TEXT, "target_lang": "English", "model": {"provider": "openai", "model": "gpt-imaginary"}})
            bad_source = self.client.post("/translate", json={
                "text": AYAH_TEXT, "target_lang": "English", "quran_source": "nope"})
        self.assertEqual(bad_model.status_code, 400)
        self.assertEqual(bad_source.status_code, 400)
        self.assertEqual(fake_llm.calls, [])

    def test_retranslate_and_the_assistant_take_the_model(self):
        app = FastAPI()
        app.include_router(assistant_routes.router)
        routes_client = TestClient(app)
        cohere = FakeCohere(cohere_answer(text_part("Cohere translation")))
        with mock.patch.object(llm, "get_cohere_client", return_value=cohere):
            retranslate = routes_client.post("/retranslate", json={
                "old_segments": [], "new_original_text": "نص", "model": COHERE})
            fragment = routes_client.post("/assistant/suggest-fragment", json={
                "segment": {"type": "normal", "text": "a long text"}, "fragment_start": 0, "fragment_end": 6,
                "instructions": "shorten", "model": COHERE})
        self.assertEqual(retranslate.status_code, 200)
        self.assertEqual(fragment.json()["replacement"], "Cohere translation")

    def test_swap_source_writes_the_ayahs_again_and_touches_nothing_else(self):
        fake_llm = FakeLlm(echo)
        with mock.patch.object(quran_detect.client.chat.completions, "create", fake_llm):
            first = quran_detect.translate_paragraph_segments(AYAH_TEXT)
            swapped = self.client.post("/quran/swap-source", json={
                "target_lang": "English", "quran_source": "saheeh",
                "rows": [{"id": "row_1", "segments": first}]}).json()
        segments = swapped["rows"][0]["segments"]
        saheeh = json.loads(quran_detect.find_quran_file("English", "saheeh").read_text(encoding="utf-8"))
        self.assertEqual(swapped["rows"][0]["id"], "row_1")
        self.assertEqual(segments[0], first[0])  # the normal text is the same
        self.assertEqual(segments[1]["text"], " ".join(saheeh["53"]["ayahs"][str(n)] for n in (5, 6)))
        self.assertEqual(segments[1]["quran_source"], "saheeh")
        self.assertEqual(len(fake_llm.calls), 1)  # only the first translation used the model

    def test_swap_source_refuses_an_unknown_source(self):
        response = self.client.post("/quran/swap-source", json={
            "target_lang": "English", "quran_source": "nope", "rows": []})
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
