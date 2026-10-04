import copy
import unittest

from helpers import FakeLlm  # noqa: F401  (makes helpers set the path and the test key)

import merge_rows


def make_row(row_id, texts, page=1):
    # texts = list of ("normal" | "quran", text)
    segments = []
    for number, (segment_type, text) in enumerate(texts, start=1):
        segment = {"id": f"seg_{number}", "type": segment_type, "text": text, "original": "عربي " + text}
        if segment_type == "quran":
            segment.update({"aya_name": "النجم", "aya_start": 5, "aya_end": 5})
        segments.append(segment)
    return {"id": row_id, "segments": segments, "source_blocks": [{"id": f"block_{row_id}", "page": page}]}


def make_rows():
    return [
        make_row("r1", [("normal", "one")], page=1),
        make_row("r2", [("normal", "two a"), ("quran", "AYAH"), ("normal", "two b")], page=1),
        make_row("r3", [("normal", "three")], page=2),
        make_row("r4", [("quran", "AYAH FOUR")], page=2),
        make_row("r5", [("normal", "five")], page=2),
    ]


class TestExplainMergeProblem(unittest.TestCase):
    def setUp(self):
        self.rows = make_rows()

    def test_rows_next_to_each_other_can_be_merged(self):
        self.assertIsNone(merge_rows.explain_merge_problem(self.rows, ["r2", "r3"]))
        self.assertIsNone(merge_rows.explain_merge_problem(self.rows, ["r1", "r2", "r3", "r4", "r5"]))

    def test_the_order_of_the_clicks_does_not_matter(self):
        self.assertIsNone(merge_rows.explain_merge_problem(self.rows, ["r3", "r2"]))

    def test_rows_that_are_not_next_to_each_other_are_refused_with_a_reason(self):
        problem = merge_rows.explain_merge_problem(self.rows, ["r1", "r3"])
        self.assertIn("next to each other", problem)
        self.assertIn("next to each other", merge_rows.explain_merge_problem(self.rows, ["r1", "r2", "r4"]))

    def test_less_than_two_rows_is_refused(self):
        self.assertIsNotNone(merge_rows.explain_merge_problem(self.rows, []))
        self.assertIsNotNone(merge_rows.explain_merge_problem(self.rows, ["r1"]))

    def test_unknown_or_repeated_rows_are_refused(self):
        self.assertIn("does not exist", merge_rows.explain_merge_problem(self.rows, ["r1", "r99"]))
        self.assertIsNotNone(merge_rows.explain_merge_problem(self.rows, ["r1", "r1"]))


class TestMergeRows(unittest.TestCase):
    def setUp(self):
        self.rows = make_rows()
        self.before = copy.deepcopy(self.rows)
        self.merged_rows = merge_rows.merge_rows(self.rows, ["r2", "r3"])

    def test_the_merged_row_replaces_the_selected_rows_in_the_same_place(self):
        self.assertEqual([row["id"] for row in self.merged_rows], ["r1", "r2+r3", "r4", "r5"])

    def test_the_segments_are_joined_in_order_and_renumbered(self):
        merged = self.merged_rows[1]
        self.assertEqual([s["text"] for s in merged["segments"]], ["two a", "AYAH", "two b", "three"])
        self.assertEqual([s["id"] for s in merged["segments"]], ["seg_1", "seg_2", "seg_3", "seg_4"])

    def test_quran_is_still_quran_after_the_merge(self):
        merged = self.merged_rows[1]
        self.assertEqual([s["type"] for s in merged["segments"]], ["normal", "quran", "normal", "normal"])
        self.assertEqual(merged["segments"][1]["aya_name"], "النجم")

    def test_the_source_blocks_of_all_the_rows_are_kept(self):
        merged = self.merged_rows[1]
        self.assertEqual([b["id"] for b in merged["source_blocks"]], ["block_r2", "block_r3"])
        self.assertEqual([b["page"] for b in merged["source_blocks"]], [1, 2])  # can be on 2 pages

    def test_the_old_rows_are_not_changed(self):
        self.assertEqual(self.rows, self.before)

    def test_a_refused_merge_raises(self):
        with self.assertRaises(ValueError):
            merge_rows.merge_rows(self.rows, ["r1", "r3"])

    def test_merging_in_the_wrong_click_order_gives_the_same_result(self):
        self.assertEqual(merge_rows.merge_rows(self.rows, ["r3", "r2"]), self.merged_rows)

    def test_merging_all_the_rows(self):
        merged = merge_rows.merge_rows(self.rows, ["r1", "r2", "r3", "r4", "r5"])
        self.assertEqual(len(merged), 1)
        self.assertEqual(len(merged[0]["segments"]), 7)


class TestUnmergeRow(unittest.TestCase):
    def test_unmerge_gives_the_same_rows_back(self):
        rows = make_rows()
        merged = merge_rows.merge_rows(rows, ["r2", "r3", "r4"])
        self.assertEqual(merge_rows.unmerge_row(merged, "r2+r3+r4"), rows)

    def test_edits_made_after_the_merge_are_kept(self):
        rows = make_rows()
        merged = merge_rows.merge_rows(rows, ["r2", "r3"])
        merged[1]["segments"][3]["text"] = "three, edited by the user"
        restored = merge_rows.unmerge_row(merged, "r2+r3")
        self.assertEqual(restored[2]["id"], "r3")
        self.assertEqual(restored[2]["segments"][0]["text"], "three, edited by the user")
        self.assertEqual(restored[2]["segments"][0]["id"], "seg_1")

    def test_a_merge_of_a_merged_row_is_undone_one_step_at_a_time(self):
        rows = make_rows()
        first = merge_rows.merge_rows(rows, ["r1", "r2"])
        second = merge_rows.merge_rows(first, ["r1+r2", "r3"])
        self.assertEqual(merge_rows.unmerge_row(second, "r1+r2+r3"), first)
        self.assertEqual(merge_rows.unmerge_row(merge_rows.unmerge_row(second, "r1+r2+r3"), "r1+r2"), rows)

    def test_a_row_that_was_not_merged_is_refused(self):
        with self.assertRaises(ValueError):
            merge_rows.unmerge_row(make_rows(), "r1")
        with self.assertRaises(ValueError):
            merge_rows.unmerge_row(make_rows(), "r99")

    def test_a_merged_row_whose_segments_changed_cannot_be_unmerged(self):
        merged = merge_rows.merge_rows(make_rows(), ["r1", "r2"])
        merged[0]["segments"][0].pop("merge_trail")
        with self.assertRaises(ValueError):
            merge_rows.unmerge_row(merged, "r1+r2")

    def test_the_merged_rows_are_not_changed_by_unmerge(self):
        merged = merge_rows.merge_rows(make_rows(), ["r1", "r2"])
        before = copy.deepcopy(merged)
        merge_rows.unmerge_row(merged, "r1+r2")
        self.assertEqual(merged, before)


class TestBuildRowsResponse(unittest.TestCase):
    def test_each_row_has_paragraph_parts_segments_and_blocks(self):
        merged = merge_rows.merge_rows(make_rows(), ["r2", "r3"])
        response = merge_rows.build_rows_response(merged)
        self.assertEqual([row["id"] for row in response["rows"]], ["r1", "r2+r3", "r4", "r5"])
        merged_row = response["rows"][1]
        self.assertTrue(merged_row["is_merged"])
        self.assertFalse(response["rows"][0]["is_merged"])
        self.assertEqual(merged_row["paragraph"], 'two a "AYAH" two b three')
        self.assertEqual([p["id"] for p in merged_row["parts"]], ["seg_1", "seg_2", "seg_3", "seg_4"])


if __name__ == "__main__":
    unittest.main()
