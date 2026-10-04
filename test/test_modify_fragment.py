import unittest
from unittest import mock

from helpers import FakeLlm

import modify_fragment

NORMAL_SEGMENT = {"id": "seg_1", "type": "normal", "text": "Hey my friend, don't worry, our Lord says", "original": "عربي"}
QURAN_SEGMENT = {"id": "seg_2", "type": "quran", "text": "He has been taught by one mighty in power", "original": "علمه شديد القوي",
                 "aya_name": "النجم", "aya_start": 5, "aya_end": 5}


def suggest(segment, start, end, instructions="make it formal", reply="Dear friend"):
    fake_llm = FakeLlm(lambda kwargs: f"  {reply}\n")
    with mock.patch.object(modify_fragment.client.chat.completions, "create", fake_llm):
        try:
            return modify_fragment.suggest_fragment_replacement(segment, start, end, instructions), fake_llm
        except ValueError as error:
            return error, fake_llm


class TestSuggestFragmentReplacement(unittest.TestCase):
    def test_returns_the_llm_reply_without_extra_spaces(self):
        replacement, _ = suggest(NORMAL_SEGMENT, 0, 13)
        self.assertEqual(replacement, "Dear friend")

    def test_sends_the_selected_part_the_context_and_the_instructions(self):
        _, fake_llm = suggest(NORMAL_SEGMENT, 0, 13, instructions="make it formal")
        sent = fake_llm.calls[0]["messages"][1]["content"]
        self.assertIn("make it formal", sent)
        self.assertIn("Selected part: Hey my friend", sent)
        self.assertIn("Full text (context only): " + NORMAL_SEGMENT["text"], sent)

    def test_it_does_not_change_the_segment(self):
        before = dict(NORMAL_SEGMENT)
        suggest(NORMAL_SEGMENT, 0, 13)
        self.assertEqual(NORMAL_SEGMENT, before)

    def test_quran_is_refused_and_the_llm_is_not_called(self):
        error, fake_llm = suggest(QURAN_SEGMENT, 0, 10)
        self.assertIsInstance(error, ValueError)
        self.assertEqual(fake_llm.calls, [])

    def test_bad_ranges_are_refused(self):
        length = len(NORMAL_SEGMENT["text"])
        for start, end in [(-1, 5), (5, 5), (8, 3), (0, length + 1), (length, length)]:
            error, fake_llm = suggest(NORMAL_SEGMENT, start, end)
            self.assertIsInstance(error, ValueError, (start, end))
            self.assertEqual(fake_llm.calls, [])

    def test_the_whole_text_can_be_selected(self):
        replacement, _ = suggest(NORMAL_SEGMENT, 0, len(NORMAL_SEGMENT["text"]))
        self.assertEqual(replacement, "Dear friend")


class TestApplyFragmentReplacement(unittest.TestCase):
    def apply(self, segment, start, end, expected, replacement):
        return modify_fragment.apply_fragment_replacement(segment, start, end, expected, replacement)

    def test_only_the_selected_part_changes(self):
        new_segment = self.apply(NORMAL_SEGMENT, 0, 13, "Hey my friend", "Dear friend")
        self.assertEqual(new_segment["text"], "Dear friend, don't worry, our Lord says")

    def test_a_part_in_the_middle_and_at_the_end(self):
        middle = self.apply(NORMAL_SEGMENT, 15, 28, "don't worry, ", "do not worry, ")
        self.assertEqual(middle["text"], "Hey my friend, do not worry, our Lord says")
        end = self.apply(NORMAL_SEGMENT, 28, 41, "our Lord says", "our Lord states")
        self.assertTrue(end["text"].endswith("our Lord states"))

    def test_the_whole_text_can_be_replaced(self):
        new_segment = self.apply(NORMAL_SEGMENT, 0, len(NORMAL_SEGMENT["text"]), NORMAL_SEGMENT["text"], "New text")
        self.assertEqual(new_segment["text"], "New text")

    def test_all_other_keys_stay_the_same(self):
        new_segment = self.apply(NORMAL_SEGMENT, 0, 13, "Hey my friend", "Dear friend")
        for key in ("id", "type", "original"):
            self.assertEqual(new_segment[key], NORMAL_SEGMENT[key])

    def test_the_old_segment_is_not_changed(self):
        before = dict(NORMAL_SEGMENT)
        self.apply(NORMAL_SEGMENT, 0, 13, "Hey my friend", "Dear friend")
        self.assertEqual(NORMAL_SEGMENT, before)

    def test_spaces_around_the_selected_part_are_kept(self):
        segment = {**NORMAL_SEGMENT, "text": "one two three"}
        new_segment = self.apply(segment, 3, 8, " two ", "2")
        self.assertEqual(new_segment["text"], "one 2 three")

    def test_a_changed_text_is_refused(self):
        changed = {**NORMAL_SEGMENT, "text": "Hello my friend, don't worry, our Lord says"}
        with self.assertRaises(ValueError):
            self.apply(changed, 0, 13, "Hey my friend", "Dear friend")

    def test_quran_is_refused(self):
        with self.assertRaises(ValueError):
            self.apply(QURAN_SEGMENT, 0, 10, QURAN_SEGMENT["text"][:10], "x")

    def test_bad_ranges_are_refused(self):
        with self.assertRaises(ValueError):
            self.apply(NORMAL_SEGMENT, 5, 5, "", "x")
        with self.assertRaises(ValueError):
            self.apply(NORMAL_SEGMENT, 0, 500, "x", "x")


if __name__ == "__main__":
    unittest.main()
