import json
import unittest
from unittest import mock

from helpers import FakeLlm

from fastapi import FastAPI
from fastapi.testclient import TestClient

import assistant_routes
import modify_fragment
import modify_many_paragraphs

# The assistant (shorten, simplify, rephrase...) must not change the approved terms of the user's glossary:
# it is told which ones to keep, and if its answer loses one it is asked once more.

HAY = {"arabic": "حي بن يقظان", "translation": "Hay bin Yaqdhan"}
SALAH = {"arabic": "الصلاة", "translation": "the prayer"}

TEXT = "The story of Hay bin Yaqdhan is long"
ORIGINAL = "قصة حي بن يقظان طويلة"


def segment(text=TEXT, original=ORIGINAL, segment_id="seg_1"):
    return {"id": segment_id, "type": "normal", "text": text, "original": original}


def replies(*answers):
    answers = iter(answers)
    return FakeLlm(lambda kwargs: next(answers))


def rows_answer(**texts):
    # {"items": [{"key": "0", "text": ...}]} for keys given as k0, k1...
    return json.dumps({"items": [{"key": key[1:], "text": text} for key, text in texts.items()]})


class TestFragment(unittest.TestCase):
    def suggest(self, fake_llm, text=TEXT, original=ORIGINAL, start=0, end=None, glossary=None):
        end = len(text) if end is None else end
        with mock.patch.object(modify_fragment.client.chat.completions, "create", fake_llm):
            return modify_fragment.suggest_fragment_replacement(
                segment(text, original), start, end, "shorten", glossary=glossary)

    def test_the_terms_in_the_selected_part_are_told_to_the_model(self):
        fake_llm = replies("Hay bin Yaqdhan, a long story")
        result = self.suggest(fake_llm, glossary=[HAY, SALAH])
        system = fake_llm.calls[0]["messages"][0]["content"]
        self.assertIn('"Hay bin Yaqdhan"', system)
        self.assertNotIn("the prayer", system)  # a term that is not in this text
        self.assertEqual(result, "Hay bin Yaqdhan, a long story")
        self.assertEqual(len(fake_llm.calls), 1)

    def test_a_term_outside_the_selected_part_is_not_protected(self):
        fake_llm = replies("a long tale")
        start = TEXT.index("is long")
        self.suggest(fake_llm, start=start, glossary=[HAY])
        self.assertNotIn("glossary", fake_llm.calls[0]["messages"][0]["content"].lower())

    def test_without_a_glossary_nothing_changes(self):
        fake_llm = replies("short")
        self.assertEqual(self.suggest(fake_llm), "short")
        self.assertEqual(len(fake_llm.calls), 1)
        self.assertNotIn("glossary", fake_llm.calls[0]["messages"][0]["content"].lower())

    def test_a_term_that_is_not_in_the_arabic_of_the_text_is_not_protected(self):
        fake_llm = replies("short")
        self.suggest(fake_llm, original="نص آخر تماما", glossary=[HAY])
        self.assertNotIn("glossary", fake_llm.calls[0]["messages"][0]["content"].lower())

    def test_a_term_the_user_already_took_out_is_not_protected(self):
        fake_llm = replies("short")
        self.suggest(fake_llm, text="The story of Hayy is long", glossary=[HAY])
        self.assertEqual(len(fake_llm.calls), 1)

    def test_an_answer_that_loses_the_term_is_asked_again(self):
        fake_llm = replies("A long story of Hayy ibn Yaqzan", "Hay bin Yaqdhan, a long story")
        result = self.suggest(fake_llm, glossary=[HAY])
        self.assertEqual(result, "Hay bin Yaqdhan, a long story")
        retry = fake_llm.calls[1]["messages"]
        self.assertEqual(retry[2], {"role": "assistant", "content": "A long story of Hayy ibn Yaqzan"})
        self.assertIn('"Hay bin Yaqdhan"', retry[3]["content"])

    def test_if_it_still_loses_the_term_the_suggestion_is_refused(self):
        fake_llm = replies("Story one", "Story two")
        with self.assertRaisesRegex(ValueError, "approved glossary term"):
            self.suggest(fake_llm, glossary=[HAY])
        self.assertEqual(len(fake_llm.calls), 2)  # never a third call


class TestRows(unittest.TestCase):
    PARAGRAPHS = [
        [segment(TEXT, ORIGINAL, "seg_1")],
        [segment("Prayer is a pillar", "الصلاة عمود", "seg_1")],
        [segment("Plain text", "نص عادي", "seg_1")],
    ]

    def modify(self, fake_llm, glossary=None, paragraphs=None):
        with mock.patch.object(modify_many_paragraphs.client.chat.completions, "create", fake_llm):
            return modify_many_paragraphs.modify_many_paragraphs_and_build_response(
                paragraphs or self.PARAGRAPHS, "shorten", glossary=glossary)

    def sent_items(self, fake_llm, call=0):
        return json.loads(fake_llm.calls[call]["messages"][1]["content"])["items"]

    def test_the_items_with_terms_carry_a_keep_list(self):
        good = rows_answer(k0="Hay bin Yaqdhan: long", k1="the prayer is a pillar", k2="Plain")
        fake_llm = replies(good)
        self.modify(fake_llm, glossary=[HAY, SALAH])
        items = self.sent_items(fake_llm)
        self.assertEqual(items[0]["keep"], ["Hay bin Yaqdhan"])
        self.assertNotIn("keep", items[2])  # nothing to keep in this one
        self.assertIn('"keep"', fake_llm.calls[0]["messages"][0]["content"])

    def test_when_every_term_is_kept_there_is_one_call(self):
        fake_llm = replies(rows_answer(k0="Hay bin Yaqdhan: long", k1="x", k2="y"))
        answer = self.modify(fake_llm, glossary=[HAY])
        self.assertEqual(len(fake_llm.calls), 1)
        self.assertEqual(answer["glossary_blocked_rows"], [])
        self.assertEqual(answer["rows"][0]["segments"][0]["text"], "Hay bin Yaqdhan: long")

    def test_a_lost_term_is_fixed_by_asking_again(self):
        fake_llm = replies(
            rows_answer(k0="Hayy: long", k1="the prayer: pillar", k2="Plain"),
            rows_answer(k0="Hay bin Yaqdhan: long", k1="IGNORED", k2="IGNORED"),
        )
        answer = self.modify(fake_llm, glossary=[HAY, SALAH])
        texts = [row["segments"][0]["text"] for row in answer["rows"]]
        # the fixed row comes from the second answer, the others stay as the first answer made them
        self.assertEqual(texts, ["Hay bin Yaqdhan: long", "the prayer: pillar", "Plain"])
        self.assertEqual(answer["glossary_blocked_rows"], [])
        self.assertEqual(len(fake_llm.calls), 2)

    def test_a_row_that_still_loses_its_term_is_left_as_it_was(self):
        fake_llm = replies(
            rows_answer(k0="Hayy: long", k1="the prayer: pillar", k2="Plain"),
            rows_answer(k0="Hayy again", k1="IGNORED", k2="IGNORED"),
        )
        answer = self.modify(fake_llm, glossary=[HAY, SALAH])
        texts = [row["segments"][0]["text"] for row in answer["rows"]]
        self.assertEqual(texts, [TEXT, "the prayer: pillar", "Plain"])
        self.assertEqual(answer["glossary_blocked_rows"], [0])
        self.assertEqual(len(fake_llm.calls), 2)

    def test_a_second_answer_that_cannot_be_read_leaves_the_row_as_it_was(self):
        fake_llm = replies(rows_answer(k0="Hayy: long", k1="x", k2="y"), "this is not json")
        answer = self.modify(fake_llm, glossary=[HAY])
        self.assertEqual(answer["rows"][0]["segments"][0]["text"], TEXT)
        self.assertEqual(answer["rows"][1]["segments"][0]["text"], "x")
        self.assertEqual(answer["glossary_blocked_rows"], [0])

    def test_without_a_glossary_it_is_the_same_as_before(self):
        fake_llm = replies(rows_answer(k0="a", k1="b", k2="c"))
        answer = self.modify(fake_llm)
        self.assertEqual(len(fake_llm.calls), 1)
        self.assertTrue(all("keep" not in item for item in self.sent_items(fake_llm)))
        self.assertNotIn('"keep"', fake_llm.calls[0]["messages"][0]["content"])
        self.assertEqual(answer["glossary_blocked_rows"], [])


class TestEndpoints(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(assistant_routes.router)
        self.client = TestClient(app)

    def test_modify_rows_and_fragment_take_the_glossary(self):
        fake_llm = replies(rows_answer(k0="Hay bin Yaqdhan: long"), "Hay bin Yaqdhan, long")
        with mock.patch.object(modify_many_paragraphs.client.chat.completions, "create", fake_llm):
            rows = self.client.post("/assistant/modify-rows", json={
                "paragraphs": [[segment()]], "instructions": "shorten", "glossary": [HAY]})
            fragment = self.client.post("/assistant/suggest-fragment", json={
                "segment": segment(), "fragment_start": 0, "fragment_end": len(TEXT),
                "instructions": "shorten", "glossary": [HAY]})
        self.assertEqual(rows.status_code, 200)
        self.assertEqual(rows.json()["glossary_blocked_rows"], [])
        self.assertEqual(fragment.json()["replacement"], "Hay bin Yaqdhan, long")
        self.assertIn("Hay bin Yaqdhan", fake_llm.calls[0]["messages"][0]["content"] + fake_llm.calls[0]["messages"][1]["content"])

    def test_a_bad_glossary_is_refused_before_any_call(self):
        fake_llm = replies("x")
        bad = [{"arabic": "prayer", "translation": "x"}]
        with mock.patch.object(modify_many_paragraphs.client.chat.completions, "create", fake_llm):
            rows = self.client.post("/assistant/modify-rows", json={
                "paragraphs": [[segment()]], "instructions": "shorten", "glossary": bad})
            fragment = self.client.post("/assistant/suggest-fragment", json={
                "segment": segment(), "fragment_start": 0, "fragment_end": 5, "instructions": "x", "glossary": bad})
        self.assertEqual(rows.status_code, 400)
        self.assertEqual(fragment.status_code, 400)
        self.assertEqual(fake_llm.calls, [])

    def test_a_suggestion_that_loses_a_term_gives_a_message_for_the_user(self):
        fake_llm = replies("One", "Two")
        with mock.patch.object(modify_fragment.client.chat.completions, "create", fake_llm):
            response = self.client.post("/assistant/suggest-fragment", json={
                "segment": segment(), "fragment_start": 0, "fragment_end": len(TEXT),
                "instructions": "shorten", "glossary": [HAY]})
        self.assertEqual(response.status_code, 400)
        self.assertIn("approved glossary term", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
