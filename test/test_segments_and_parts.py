import copy
import unittest
from unittest import mock

import helpers
from helpers import FakeLlm

import quran_detect
import modify_paragraph
from paragraph_format import build_paragraph_display_parts, concatenate_paragraph_segements

MIXED_PARAGRAPH = "اذيا صاحبي متقلقش ربنا بيقول علمه شديد القوي ذو مرة فاستوي ورجعنا البيت بعد الشغل"
NORMAL_PARAGRAPH = "ورجعنا البيت بعد الشغل"


def translate(paragraph):
    fake_llm = FakeLlm(lambda kwargs: "<LLM:" + kwargs["messages"][1]["content"] + ">")
    with mock.patch.object(quran_detect.client.chat.completions, "create", fake_llm):
        return quran_detect.translate_paragraph_and_build_response(paragraph)


class TestSegmentIds(unittest.TestCase):
    def test_every_segment_has_the_keys_we_need(self):
        for segment in translate(MIXED_PARAGRAPH)["segments"]:
            for key in ("id", "type", "text", "original"):
                self.assertIn(key, segment)

    def test_ids_are_sequential_and_unique(self):
        ids = [segment["id"] for segment in translate(MIXED_PARAGRAPH)["segments"]]
        self.assertEqual(ids, ["seg_1", "seg_2", "seg_3"])

    def test_normal_paragraph_is_one_segment(self):
        segments = translate(NORMAL_PARAGRAPH)["segments"]
        self.assertEqual([segment["type"] for segment in segments], ["normal"])
        self.assertEqual(segments[0]["id"], "seg_1")

    def test_empty_paragraph_has_no_segments(self):
        response = translate("")
        self.assertEqual(response["segments"], [])
        self.assertEqual(response["parts"], [])
        self.assertEqual(response["paragraph"], "")

    def test_quran_text_comes_from_the_json_and_original_is_arabic(self):
        quran_segment = translate(MIXED_PARAGRAPH)["segments"][1]
        self.assertEqual(quran_segment["type"], "quran")
        self.assertIn("He has been taught", quran_segment["text"])
        self.assertEqual(quran_segment["original"], "علمه شديد القوي ذو مرة فاستوي")


class TestDisplayParts(unittest.TestCase):
    def setUp(self):
        self.response = translate(MIXED_PARAGRAPH)

    def test_one_part_per_segment_with_the_same_id_and_type(self):
        segments, parts = self.response["segments"], self.response["parts"]
        self.assertEqual([p["id"] for p in parts], [s["id"] for s in segments])
        self.assertEqual([p["type"] for p in parts], [s["type"] for s in segments])

    def test_quotes_are_inside_the_quran_part_only(self):
        for part in self.response["parts"]:
            if part["type"] == "quran":
                self.assertTrue(part["text"].startswith('"') and part["text"].endswith('"'))
            else:
                self.assertNotIn('"', part["text"])

    def test_segment_text_has_no_quotes_added(self):
        quran_segment = self.response["segments"][1]
        self.assertFalse(quran_segment["text"].startswith('"'))

    def test_paragraph_is_the_parts_joined_with_a_space(self):
        parts_text = " ".join(part["text"] for part in self.response["parts"])
        self.assertEqual(self.response["paragraph"], parts_text)

    def test_concatenate_gives_the_same_as_the_parts(self):
        segments = self.response["segments"]
        self.assertEqual(concatenate_paragraph_segements(segments), self.response["paragraph"])
        self.assertEqual(build_paragraph_display_parts(segments), self.response["parts"])


class TestModifyKeepsTheStructure(unittest.TestCase):
    def setUp(self):
        self.segments = translate(MIXED_PARAGRAPH)["segments"]
        self.segments_before = copy.deepcopy(self.segments)
        fake_llm = FakeLlm(helpers.echo_last_line)
        with mock.patch.object(modify_paragraph.client.chat.completions, "create", fake_llm):
            self.response = modify_paragraph.modify_paragraph_and_build_response(self.segments, "make it formal")
        self.fake_llm = fake_llm

    def test_ids_and_types_stay_the_same(self):
        self.assertEqual([s["id"] for s in self.response["segments"]], [s["id"] for s in self.segments])
        self.assertEqual([s["type"] for s in self.response["segments"]], [s["type"] for s in self.segments])

    def test_quran_is_not_changed_and_never_sent_to_the_llm(self):
        self.assertEqual(self.response["segments"][1], self.segments[1])
        sent = " ".join(call["messages"][1]["content"] for call in self.fake_llm.calls)
        self.assertNotIn("He has been taught", sent)

    def test_only_normal_segments_are_sent(self):
        self.assertEqual(len(self.fake_llm.calls), 2)

    def test_response_has_parts_and_paragraph(self):
        self.assertEqual([p["id"] for p in self.response["parts"]], ["seg_1", "seg_2", "seg_3"])
        self.assertIn('"He has been taught', self.response["paragraph"])

    def test_the_original_segments_are_not_changed(self):
        self.assertEqual(self.segments, self.segments_before)
        self.assertNotEqual(self.response["segments"][0]["text"], self.segments[0]["text"])


if __name__ == "__main__":
    unittest.main()
