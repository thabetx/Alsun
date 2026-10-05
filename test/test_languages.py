import json
import sys
import types
import unittest
from unittest import mock

from helpers import FakeLlm

from fastapi import FastAPI
from fastapi.testclient import TestClient

import assistant_routes
import quran_detect

# The language chosen by the user picks two things: the quran translation file (ayahs never go to the llm)
# and the language the llm is asked to translate the normal text into.

AYAH_TEXT = "اذيا صاحبي علمه شديد القوي ذو مرة فاستوي"  # normal text + An-Najm 53:5-6
LANGUAGES = ["English", "French", "German", "Turkish", "Spanish", "Indonesian"]


def echo(kwargs):
    return "<LLM:" + kwargs["messages"][1]["content"] + ">"


class TestQuranFiles(unittest.TestCase):
    def test_every_language_has_a_complete_file(self):
        for language in LANGUAGES:
            with self.subTest(language=language):
                quran = json.loads(quran_detect.find_quran_file(language).read_text(encoding="utf-8"))
                self.assertEqual(len(quran), 114)
                self.assertEqual(sum(len(surah["ayahs"]) for surah in quran.values()), 6236)
                self.assertTrue(all(text.strip() for surah in quran.values() for text in surah["ayahs"].values()))

    def test_a_language_without_a_quran_translation_is_refused(self):
        with self.assertRaises(ValueError):
            quran_detect.find_quran_file("Klingon")


class TestTranslateInAnotherLanguage(unittest.TestCase):
    def translate(self, language):
        fake_llm = FakeLlm(echo)
        with mock.patch.object(quran_detect.client.chat.completions, "create", fake_llm):
            segments = quran_detect.translate_paragraph_segments(AYAH_TEXT, target_lang=language)
        return segments, fake_llm

    def test_the_ayah_comes_from_the_file_of_the_language(self):
        for language in LANGUAGES:
            with self.subTest(language=language):
                segments, _ = self.translate(language)
                quran = json.loads(quran_detect.find_quran_file(language).read_text(encoding="utf-8"))
                expected = " ".join(quran["53"]["ayahs"][str(n)] for n in (5, 6))
                self.assertEqual(segments[1]["type"], "quran")
                self.assertEqual(segments[1]["text"], expected)

    def test_the_llm_is_asked_for_the_language_and_never_sees_the_ayah(self):
        segments, fake_llm = self.translate("German")
        self.assertEqual(len(fake_llm.calls), 1)
        self.assertIn("German", fake_llm.calls[0]["messages"][0]["content"])
        self.assertNotIn("علمه", fake_llm.calls[0]["messages"][1]["content"])

    def test_without_a_language_it_is_english_like_before(self):
        fake_llm = FakeLlm(echo)
        with mock.patch.object(quran_detect.client.chat.completions, "create", fake_llm):
            segments = quran_detect.translate_paragraph_segments(AYAH_TEXT)
        self.assertIn("English", fake_llm.calls[0]["messages"][0]["content"])
        self.assertTrue(segments[1]["text"].startswith("He has been taught"))


class TestLanguageInTheEndpoints(unittest.TestCase):
    def test_retranslate_uses_the_language(self):
        app = FastAPI()
        app.include_router(assistant_routes.router)
        fake_llm = FakeLlm(echo)
        with mock.patch.object(quran_detect.client.chat.completions, "create", fake_llm):
            response = TestClient(app).post("/retranslate", json={
                "old_segments": [], "new_original_text": AYAH_TEXT, "target_lang": "French"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("French", fake_llm.calls[0]["messages"][0]["content"])
        french = json.loads(quran_detect.find_quran_file("French").read_text(encoding="utf-8"))
        self.assertIn(french["53"]["ayahs"]["5"], response.json()["segments"][1]["text"])

    def test_translate_and_retranslate_refuse_an_unknown_language(self):
        sys.modules.setdefault("datalab_sdk", types.SimpleNamespace(ConvertOptions=object, DatalabClient=object))
        import main

        app = FastAPI()
        app.include_router(assistant_routes.router)
        fake_llm = FakeLlm(echo)
        with mock.patch.object(quran_detect.client.chat.completions, "create", fake_llm):
            translate = TestClient(main.app).post("/translate", json={"text": AYAH_TEXT, "target_lang": "Klingon"})
            retranslate = TestClient(app).post("/retranslate", json={
                "old_segments": [], "new_original_text": AYAH_TEXT, "target_lang": "Klingon"})
        self.assertEqual(translate.status_code, 400)
        self.assertEqual(retranslate.status_code, 400)
        self.assertEqual(fake_llm.calls, [])


if __name__ == "__main__":
    unittest.main()
