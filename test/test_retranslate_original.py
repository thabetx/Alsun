import copy
import unittest
from unittest import mock

from helpers import FakeLlm

import quran_detect
import retranslate_original

AYAH = "علمه شديد القوي ذو مرة فاستوي"  # An-Najm 5-6
AYAH_WITH_TYPO = "علمه شديد القوي ذو مرة فتوي"
OTHER_AYAH = "ذلك الكتاب لا ريب فيه هدى للمتقين"  # Al-Baqarah 2
OLD_TEXT = f"اذيا صاحبي متقلقش ربنا بيقول {AYAH} ورجعنا البيت بعد الشغل"


def translate(text):
    fake_llm = FakeLlm(lambda kwargs: "<LLM:" + kwargs["messages"][1]["content"] + ">")
    with mock.patch.object(quran_detect.client.chat.completions, "create", fake_llm):
        return quran_detect.translate_paragraph_segments(text)


def retranslate(old_segments, new_text):
    fake_llm = FakeLlm(lambda kwargs: "<LLM:" + kwargs["messages"][1]["content"] + ">")
    with mock.patch.object(quran_detect.client.chat.completions, "create", fake_llm):
        return retranslate_original.retranslate_edited_original(old_segments, new_text), fake_llm


class TestOnlyNormalTextChanged(unittest.TestCase):
    def setUp(self):
        self.old_segments = translate(OLD_TEXT)
        self.response, self.fake_llm = retranslate(self.old_segments, OLD_TEXT.replace("البيت", "الدار"))

    def test_quran_is_the_same_and_no_review_is_needed(self):
        changes = self.response["quran_changes"]
        self.assertEqual((changes["removed"], changes["added"], changes["damaged"]), ([], [], []))
        self.assertEqual(changes["unchanged"], 1)
        self.assertFalse(self.response["needs_review"])

    def test_the_row_is_translated_again_with_the_new_arabic(self):
        self.assertIn("الدار", self.response["segments"][2]["original"])
        self.assertIn("الدار", self.response["segments"][2]["text"])

    def test_the_old_segments_are_kept_for_the_edit_history(self):
        self.assertEqual(self.response["previous_segments"], self.old_segments)

    def test_the_response_has_paragraph_parts_and_segments(self):
        self.assertEqual([p["id"] for p in self.response["parts"]], ["seg_1", "seg_2", "seg_3"])
        self.assertIn('"He has been taught', self.response["paragraph"])


class TestAyahRemoved(unittest.TestCase):
    def test_removed_ayah_needs_review(self):
        old_segments = translate(OLD_TEXT)
        response, _ = retranslate(old_segments, "اذيا صاحبي متقلقش ربنا بيقول ورجعنا البيت بعد الشغل")
        changes = response["quran_changes"]
        self.assertEqual(len(changes["removed"]), 1)
        self.assertEqual(changes["removed"][0]["aya_start"], 5)
        self.assertEqual((changes["added"], changes["damaged"], changes["unchanged"]), ([], [], 0))
        self.assertTrue(response["needs_review"])
        self.assertTrue(all(segment["type"] == "normal" for segment in response["segments"]))

    def test_deleting_the_whole_text(self):
        response, _ = retranslate(translate(OLD_TEXT), "")
        self.assertEqual(response["segments"], [])
        self.assertEqual(len(response["quran_changes"]["removed"]), 1)
        self.assertTrue(response["needs_review"])


class TestAyahAdded(unittest.TestCase):
    def test_added_ayah_needs_review(self):
        old_segments = translate("ورجعنا البيت بعد الشغل")
        response, _ = retranslate(old_segments, f"ورجعنا البيت {OTHER_AYAH} بعد الشغل")
        changes = response["quran_changes"]
        self.assertEqual(len(changes["added"]), 1)
        self.assertEqual(changes["added"][0]["aya_start"], 2)
        self.assertEqual((changes["removed"], changes["damaged"], changes["unchanged"]), ([], [], 0))
        self.assertTrue(response["needs_review"])
        self.assertEqual([s["type"] for s in response["segments"]], ["normal", "quran", "normal"])


class TestAyahDamagedBySpellingMistake(unittest.TestCase):
    def test_a_mistake_inside_the_ayah_is_reported_as_damaged_not_removed(self):
        old_segments = translate(OLD_TEXT)
        response, _ = retranslate(old_segments, OLD_TEXT.replace(AYAH, AYAH_WITH_TYPO))
        changes = response["quran_changes"]
        self.assertEqual(len(changes["damaged"]), 1)
        self.assertEqual(changes["removed"], [])
        self.assertTrue(response["needs_review"])

    def test_the_damaged_part_is_not_translated_as_quran(self):
        old_segments = translate(OLD_TEXT)
        response, _ = retranslate(old_segments, OLD_TEXT.replace(AYAH, AYAH_WITH_TYPO))
        # the part the detector lost goes to the llm as normal text, the user is warned by needs_review
        self.assertIn("normal", [segment["type"] for segment in response["segments"]])


class TestSameAyahMoved(unittest.TestCase):
    def test_moving_the_ayah_in_the_text_is_not_a_change(self):
        old_segments = translate(f"{AYAH} ورجعنا البيت")
        response, _ = retranslate(old_segments, f"ورجعنا البيت {AYAH}")
        self.assertFalse(response["needs_review"])
        self.assertEqual(response["quran_changes"]["unchanged"], 1)


class TestHelpers(unittest.TestCase):
    def test_words_ratio_ignores_tashkeel_and_punctuation(self):
        self.assertTrue(retranslate_original.ayah_words_still_in_text("عَلَّمَهُ شَدِيدُ القُوَى", "علمه، شديد القوي!"))

    def test_an_ayah_with_no_arabic_words_is_never_damaged(self):
        self.assertFalse(retranslate_original.ayah_words_still_in_text("123 ...", "علمه شديد القوي"))

    def test_the_old_segments_are_not_changed(self):
        old_segments = translate(OLD_TEXT)
        before = copy.deepcopy(old_segments)
        retranslate(old_segments, "نص جديد")
        self.assertEqual(old_segments, before)


if __name__ == "__main__":
    unittest.main()
