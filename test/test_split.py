import os
import unittest
from types import SimpleNamespace
from unittest import mock

from helpers import FakeLlm

import llm
import quran_detect
from arabic_text import split_into_chunks

# command-a-translate reads 8000 tokens in all, so a long paragraph is cut at the end of sentences and the pieces
# are translated one by one. Other models get the paragraph whole. The models here are always fakes.

TRANSLATE_MODEL = {"provider": "cohere", "model": "command-a-translate-08-2025"}
PLUS = {"provider": "cohere", "model": "command-a-plus-05-2026"}
SENTENCE = "هذه جملة عربية قصيرة نكررها لنصنع نصا طويلا."


def long_text(sentences):
    return " ".join(f"{SENTENCE[:-1]} رقم {number}." for number in range(sentences))


class TestSplit(unittest.TestCase):
    def assert_same_words(self, text, chunks):
        self.assertEqual(" ".join(chunks).split(), text.split())

    def test_a_short_text_is_one_piece(self):
        self.assertEqual(split_into_chunks(SENTENCE, 1500), [SENTENCE])

    def test_an_empty_text_has_no_pieces(self):
        self.assertEqual(split_into_chunks("   ", 100), [])

    def test_a_long_text_is_cut_at_the_end_of_sentences(self):
        text = long_text(60)
        chunks = split_into_chunks(text, 300)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 300 for chunk in chunks))
        self.assertTrue(all(chunk.endswith(".") for chunk in chunks))  # never in the middle of a sentence
        self.assert_same_words(text, chunks)

    def test_the_pieces_are_as_big_as_they_can_be(self):
        chunks = split_into_chunks(long_text(60), 300)
        # a piece is closed only when the next sentence does not fit, so all but the last are nearly full
        self.assertTrue(all(len(chunk) > 300 - len(SENTENCE) - 10 for chunk in chunks[:-1]))

    def test_the_arabic_question_mark_and_semicolon_end_a_sentence(self):
        text = "هل هذا صحيح؟ " * 20 + "نعم؛ " * 20
        chunks = split_into_chunks(text, 80)
        self.assertTrue(all(len(chunk) <= 80 for chunk in chunks))
        self.assertTrue(all(chunk.endswith(("؟", "؛")) for chunk in chunks))
        self.assert_same_words(text, chunks)

    def test_a_sentence_too_long_is_cut_at_commas(self):
        text = "، ".join(f"كلمة{number} وكلمة أخرى" for number in range(40)) + "."
        chunks = split_into_chunks(text, 120)
        self.assertTrue(all(len(chunk) <= 120 for chunk in chunks))
        self.assertTrue(all(chunk.endswith("،") for chunk in chunks[:-1]))
        self.assert_same_words(text, chunks)

    def test_a_text_without_any_punctuation_is_cut_between_words(self):
        text = " ".join(f"كلمة{number}" for number in range(300))
        chunks = split_into_chunks(text, 100)
        self.assertTrue(all(len(chunk) <= 100 for chunk in chunks))
        self.assert_same_words(text, chunks)

    def test_a_word_longer_than_the_limit_is_cut(self):
        chunks = split_into_chunks("ا" * 250 + " كلمة", 100)
        self.assertTrue(all(len(chunk) <= 100 for chunk in chunks))
        self.assertEqual("".join(chunks).replace(" ", ""), "ا" * 250 + "كلمة")


class TestTranslateLongParagraph(unittest.TestCase):
    def setUp(self):
        llm.forget_failures()
        patcher = mock.patch.dict(os.environ, {"COHERE_API_KEY": "fake-key-for-tests"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def cohere(self, behavior):
        calls = []

        def chat(**kwargs):
            calls.append(kwargs)
            text = behavior(kwargs)
            return SimpleNamespace(message=SimpleNamespace(content=[SimpleNamespace(type="text", text=text)]))

        client = SimpleNamespace(chat=chat)
        return client, calls

    def translate(self, text, model, behavior, glossary=None):
        client, calls = self.cohere(behavior)
        with mock.patch.object(llm, "get_cohere_client", return_value=client):
            result = quran_detect.translate_normal_paragraph_with_report(text, "English", glossary, model)
        return result, calls

    def test_the_limit_is_only_for_the_translation_model(self):
        self.assertEqual(llm.max_input_chars(TRANSLATE_MODEL), 1500)
        self.assertIsNone(llm.max_input_chars(PLUS))
        self.assertIsNone(llm.max_input_chars(None))

    def test_a_long_paragraph_is_translated_piece_by_piece_in_order(self):
        text = long_text(100)  # about 4000 characters
        result, calls = self.translate(text, TRANSLATE_MODEL, lambda kwargs: "T[" + kwargs["messages"][1]["content"][-12:] + "]")
        pieces = split_into_chunks(text, 1500)
        self.assertGreater(len(pieces), 1)
        self.assertEqual(len(calls), len(pieces))
        self.assertTrue(all(len(call["messages"][1]["content"]) <= 1500 for call in calls))
        self.assertEqual([call["messages"][1]["content"] for call in calls], pieces)  # exactly the pieces, in order
        self.assertEqual(result["text"], " ".join("T[" + piece[-12:] + "]" for piece in pieces))

    def test_a_short_paragraph_is_one_question_even_for_the_translation_model(self):
        result, calls = self.translate(SENTENCE, TRANSLATE_MODEL, lambda kwargs: "Short")
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["text"], "Short")

    def test_other_models_get_the_long_paragraph_whole(self):
        result, calls = self.translate(long_text(100), PLUS, lambda kwargs: "Whole")
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["text"], "Whole")

    def test_the_glossary_is_told_only_to_the_piece_that_has_the_term(self):
        hay = {"arabic": "حي بن يقظان", "translation": "Hay bin Yaqdhan"}
        text = long_text(60) + " وذكر حي بن يقظان في آخر النص."
        result, calls = self.translate(
            text, TRANSLATE_MODEL,
            lambda kwargs: "Hay bin Yaqdhan" if "حي بن يقظان" in kwargs["messages"][1]["content"] else "Plain",
            glossary=[hay])
        with_term = [call for call in calls if "Hay bin Yaqdhan" in call["messages"][0]["content"]]
        self.assertEqual(len(with_term), 1)
        self.assertEqual(result["glossary"], [{**hay, "used": True}])
        self.assertEqual(len(calls), len(split_into_chunks(text, 1500)))  # no extra question: the term was used

    def test_a_term_not_used_in_one_piece_is_reported_not_used(self):
        hay = {"arabic": "حي بن يقظان", "translation": "Hay bin Yaqdhan"}
        text = (long_text(40) + " ") + "حي بن يقظان في الوسط. " + (long_text(40) + " ") + "ثم حي بن يقظان في الآخر."
        # the first piece with the term uses it, the second one never does (not even when asked again)

        def behavior(kwargs):
            asked = kwargs["messages"][1]["content"]
            if "في الآخر" in asked:
                return "Plain"
            return "Hay bin Yaqdhan" if "حي بن يقظان" in asked else "Plain"
        result, calls = self.translate(text, TRANSLATE_MODEL, behavior, glossary=[hay])
        self.assertEqual(result["glossary"], [{**hay, "used": False}])


if __name__ == "__main__":
    unittest.main()
