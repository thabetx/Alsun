import copy
import json
import unittest
from unittest import mock

from helpers import FakeLlm

import modify_many_paragraphs


def normal(segment_id, text):
    return {"id": segment_id, "type": "normal", "text": text, "original": "عربي"}


def quran(segment_id, text):
    return {"id": segment_id, "type": "quran", "text": text, "original": "قرآن",
            "aya_name": "النجم", "aya_start": 5, "aya_end": 5}


def make_paragraphs():
    return [
        [normal("seg_1", "hello one"), quran("seg_2", "AYAH ONE"), normal("seg_3", "bye one")],
        [normal("seg_1", "hello two"), quran("seg_2", "AYAH TWO"), normal("seg_3", "bye two")],
        [quran("seg_1", "AYAH THREE")],
        [normal("seg_1", "only normal")],
    ]


def reply_with_changed_texts(kwargs):
    # the good llm: same keys, every text changed
    sent = json.loads(kwargs["messages"][1]["content"])
    return json.dumps({"items": [{"key": item["key"], "text": "<MOD:" + item["text"] + ">"} for item in sent["items"]]})


def run(paragraphs, reply_function=reply_with_changed_texts, instructions="make it formal"):
    fake_llm = FakeLlm(reply_function)
    with mock.patch.object(modify_many_paragraphs.client.chat.completions, "create", fake_llm):
        try:
            result = modify_many_paragraphs.modify_many_paragraphs(paragraphs, instructions)
        except ValueError as error:
            result = error
    return result, fake_llm


class TestOneCallForManyParagraphs(unittest.TestCase):
    def setUp(self):
        self.paragraphs = make_paragraphs()
        self.before = copy.deepcopy(self.paragraphs)
        self.result, self.fake_llm = run(self.paragraphs)

    def test_only_one_llm_call_for_all_the_paragraphs(self):
        self.assertEqual(len(self.fake_llm.calls), 1)

    def test_only_normal_texts_are_sent_with_the_instructions(self):
        sent = json.loads(self.fake_llm.calls[0]["messages"][1]["content"])
        self.assertEqual(sent["instructions"], "make it formal")
        self.assertEqual([item["text"] for item in sent["items"]],
                         ["hello one", "bye one", "hello two", "bye two", "only normal"])

    def test_quran_is_never_sent_to_the_llm(self):
        sent = self.fake_llm.calls[0]["messages"][1]["content"]
        for ayah in ("AYAH ONE", "AYAH TWO", "AYAH THREE"):
            self.assertNotIn(ayah, sent)

    def test_the_number_of_paragraphs_and_segments_stays_the_same(self):
        self.assertEqual(len(self.result), len(self.paragraphs))
        for new_paragraph, old_paragraph in zip(self.result, self.paragraphs):
            self.assertEqual([s["id"] for s in new_paragraph], [s["id"] for s in old_paragraph])
            self.assertEqual([s["type"] for s in new_paragraph], [s["type"] for s in old_paragraph])

    def test_every_normal_text_is_changed_in_the_right_place(self):
        self.assertEqual(self.result[0][0]["text"], "<MOD:hello one>")
        self.assertEqual(self.result[0][2]["text"], "<MOD:bye one>")
        self.assertEqual(self.result[1][0]["text"], "<MOD:hello two>")
        self.assertEqual(self.result[1][2]["text"], "<MOD:bye two>")
        self.assertEqual(self.result[3][0]["text"], "<MOD:only normal>")

    def test_quran_is_exactly_the_same(self):
        self.assertEqual(self.result[0][1], self.before[0][1])
        self.assertEqual(self.result[1][1], self.before[1][1])
        self.assertEqual(self.result[2], self.before[2])

    def test_the_selected_paragraphs_are_not_changed(self):
        self.assertEqual(self.paragraphs, self.before)


class TestParagraphsWithoutNormalText(unittest.TestCase):
    def test_no_paragraphs_means_no_call(self):
        result, fake_llm = run([])
        self.assertEqual(result, [])
        self.assertEqual(fake_llm.calls, [])

    def test_only_quran_means_no_call_and_no_change(self):
        paragraphs = [[quran("seg_1", "AYAH")], [quran("seg_1", "AYAH TWO")]]
        result, fake_llm = run(paragraphs)
        self.assertEqual(result, paragraphs)
        self.assertEqual(fake_llm.calls, [])

    def test_response_tells_which_rows_are_quran_only(self):
        fake_llm = FakeLlm(reply_with_changed_texts)
        with mock.patch.object(modify_many_paragraphs.client.chat.completions, "create", fake_llm):
            response = modify_many_paragraphs.modify_many_paragraphs_and_build_response(make_paragraphs(), "x")
        self.assertEqual(response["quran_only_rows"], [2])
        self.assertEqual(len(response["rows"]), 4)
        for row in response["rows"]:
            self.assertEqual(sorted(row), ["paragraph", "parts", "segments"])
        self.assertIn('"AYAH ONE"', response["rows"][0]["paragraph"])
        self.assertEqual([p["id"] for p in response["rows"][0]["parts"]], ["seg_1", "seg_2", "seg_3"])


class TestEmptyParagraph(unittest.TestCase):
    def test_a_paragraph_with_no_segments_is_not_called_quran_only(self):
        fake_llm = FakeLlm(reply_with_changed_texts)
        paragraphs = [[], [normal("seg_1", "hello")], [quran("seg_1", "AYAH")]]
        with mock.patch.object(modify_many_paragraphs.client.chat.completions, "create", fake_llm):
            response = modify_many_paragraphs.modify_many_paragraphs_and_build_response(paragraphs, "x")
        self.assertEqual(response["quran_only_rows"], [2])
        self.assertEqual(response["rows"][0]["segments"], [])


class TestBadLlmAnswers(unittest.TestCase):
    def assert_refused_and_nothing_changed(self, reply_function):
        paragraphs = make_paragraphs()
        before = copy.deepcopy(paragraphs)
        result, _ = run(paragraphs, reply_function)
        self.assertIsInstance(result, ValueError)
        self.assertEqual(paragraphs, before)

    def test_not_json(self):
        self.assert_refused_and_nothing_changed(lambda kwargs: "here you go: formal text")

    def test_json_without_items(self):
        self.assert_refused_and_nothing_changed(lambda kwargs: json.dumps({"result": []}))

    def test_one_text_missing(self):
        def reply(kwargs):
            sent = json.loads(kwargs["messages"][1]["content"])
            return json.dumps({"items": [{"key": i["key"], "text": "x"} for i in sent["items"][:-1]]})
        self.assert_refused_and_nothing_changed(reply)

    def test_extra_text(self):
        def reply(kwargs):
            sent = json.loads(kwargs["messages"][1]["content"])
            items = [{"key": i["key"], "text": "x"} for i in sent["items"]] + [{"key": "99", "text": "extra"}]
            return json.dumps({"items": items})
        self.assert_refused_and_nothing_changed(reply)

    def test_wrong_key(self):
        def reply(kwargs):
            sent = json.loads(kwargs["messages"][1]["content"])
            return json.dumps({"items": [{"key": "k" + i["key"], "text": "x"} for i in sent["items"]]})
        self.assert_refused_and_nothing_changed(reply)

    def test_empty_text_would_delete_the_translation(self):
        def reply(kwargs):
            sent = json.loads(kwargs["messages"][1]["content"])
            return json.dumps({"items": [{"key": i["key"], "text": "  "} for i in sent["items"]]})
        self.assert_refused_and_nothing_changed(reply)

    def test_text_that_is_not_a_string(self):
        def reply(kwargs):
            sent = json.loads(kwargs["messages"][1]["content"])
            return json.dumps({"items": [{"key": i["key"], "text": 5} for i in sent["items"]]})
        self.assert_refused_and_nothing_changed(reply)

    def test_answer_in_a_different_order_is_still_placed_correctly(self):
        def reply(kwargs):
            sent = json.loads(kwargs["messages"][1]["content"])
            items = [{"key": i["key"], "text": "<MOD:" + i["text"] + ">"} for i in sent["items"]]
            return json.dumps({"items": items[::-1]})
        result, _ = run(make_paragraphs(), reply)
        self.assertEqual(result[0][0]["text"], "<MOD:hello one>")
        self.assertEqual(result[3][0]["text"], "<MOD:only normal>")


if __name__ == "__main__":
    unittest.main()
