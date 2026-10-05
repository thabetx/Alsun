import copy
import json
import unittest
from unittest import mock

from helpers import FakeLlm

import modify_many_paragraphs
import quran_detect
import retranslate_original
from paragraph_format import build_paragraph_display_parts, concatenate_paragraph_segements

# When the user deletes an ayah from the translation, its segment becomes a normal one:
#   - type "normal", the text he wrote in its place (maybe empty)
#   - "original" keeps the arabic words of the ayah (so the words still match the original text)
#   - "replaced_quran" remembers which ayah it was


def normal(segment_id, text, original="عربي"):
    return {"id": segment_id, "type": "normal", "text": text, "original": original}


def replaced(segment_id, text, ayah_original="علمه شديد القوي ذو مرة فاستوي"):
    return {"id": segment_id, "type": "normal", "text": text, "original": ayah_original,
            "replaced_quran": [{"aya_name": "النجم", "aya_start": 5, "aya_end": 6, "original": ayah_original}]}


class TestParagraphWithAnEmptyPart(unittest.TestCase):
    def test_an_empty_part_adds_no_extra_space(self):
        segments = [normal("seg_1", "before"), replaced("seg_2", ""), normal("seg_3", "after")]
        self.assertEqual(concatenate_paragraph_segements(segments), "before after")

    def test_the_part_is_still_in_the_parts_list_with_its_id(self):
        segments = [normal("seg_1", "before"), replaced("seg_2", ""), normal("seg_3", "after")]
        parts = build_paragraph_display_parts(segments)
        self.assertEqual([part["id"] for part in parts], ["seg_1", "seg_2", "seg_3"])
        self.assertEqual(parts[1]["text"], "")

    def test_the_text_the_user_wrote_in_place_of_the_ayah_is_shown_without_quotes(self):
        segments = [normal("seg_1", "before"), replaced("seg_2", "my own words"), normal("seg_3", "after")]
        self.assertEqual(concatenate_paragraph_segements(segments), "before my own words after")


class TestAssistantAndReplacedAyah(unittest.TestCase):
    def reply(self, kwargs):
        sent = json.loads(kwargs["messages"][1]["content"])
        return json.dumps({"items": [{"key": i["key"], "text": "<MOD:" + i["text"] + ">"} for i in sent["items"]]})

    def run_assistant(self, paragraphs):
        fake_llm = FakeLlm(self.reply)
        with mock.patch.object(modify_many_paragraphs.client.chat.completions, "create", fake_llm):
            return modify_many_paragraphs.modify_many_paragraphs(paragraphs, "x"), fake_llm

    def test_a_segment_with_no_text_is_not_sent_to_the_llm(self):
        paragraphs = [[normal("seg_1", "before"), replaced("seg_2", ""), normal("seg_3", "   ")]]
        result, fake_llm = self.run_assistant(paragraphs)
        sent = json.loads(fake_llm.calls[0]["messages"][1]["content"])
        self.assertEqual([item["text"] for item in sent["items"]], ["before"])
        self.assertEqual(result[0][0]["text"], "<MOD:before>")
        self.assertEqual(result[0][1], paragraphs[0][1])
        self.assertEqual(result[0][2], paragraphs[0][2])

    def test_a_row_with_only_empty_text_makes_no_call(self):
        result, fake_llm = self.run_assistant([[replaced("seg_1", "")]])
        self.assertEqual(fake_llm.calls, [])
        self.assertEqual(result, [[replaced("seg_1", "")]])

    def test_the_text_the_user_wrote_instead_of_an_ayah_can_be_edited_by_the_assistant(self):
        result, fake_llm = self.run_assistant([[replaced("seg_1", "my own words")]])
        self.assertEqual(result[0][0]["text"], "<MOD:my own words>")
        self.assertEqual(result[0][0]["replaced_quran"], replaced("seg_1", "x")["replaced_quran"])


class TestRetranslateWithAReplacedAyah(unittest.TestCase):
    AYAH = "علمه شديد القوي ذو مرة فاستوي"

    def retranslate(self, old_segments, new_text):
        fake_llm = FakeLlm(lambda kwargs: "<LLM:" + kwargs["messages"][1]["content"] + ">")
        with mock.patch.object(quran_detect.client.chat.completions, "create", fake_llm):
            return retranslate_original.retranslate_edited_original(old_segments, new_text)

    def test_the_fingerprint_counts_an_ayah_the_user_replaced(self):
        fingerprint = retranslate_original.build_quran_fingerprint([normal("seg_1", "x"), replaced("seg_2", "my words")])
        self.assertEqual(fingerprint, [("النجم", 5, 6)])

    def test_an_empty_replaced_segment_counts_too(self):
        self.assertEqual(retranslate_original.build_quran_fingerprint([replaced("seg_1", "")]), [("النجم", 5, 6)])

    def test_the_same_ayah_found_again_is_not_a_change(self):
        old = [normal("seg_1", "before", "اذيا صاحبي"), replaced("seg_2", "my own words")]
        response = self.retranslate(old, f"اذيا صاحبي {self.AYAH}")
        changes = response["quran_changes"]
        self.assertEqual((changes["removed"], changes["added"], changes["damaged"]), ([], [], []))
        self.assertEqual(changes["unchanged"], 1)
        self.assertFalse(response["needs_review"])

    def test_the_ayah_removed_from_the_original_is_reported_as_removed(self):
        old = [normal("seg_1", "before", "اذيا صاحبي"), replaced("seg_2", "my own words")]
        response = self.retranslate(old, "اذيا صاحبي ورجعنا البيت")
        self.assertEqual(len(response["quran_changes"]["removed"]), 1)
        self.assertTrue(response["needs_review"])

    def test_the_old_segments_are_not_changed(self):
        old = [replaced("seg_1", "my own words")]
        before = copy.deepcopy(old)
        self.retranslate(old, "نص مختلف")
        self.assertEqual(old, before)


if __name__ == "__main__":
    unittest.main()
