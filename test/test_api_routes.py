import json
import sys
import types
import unittest
from unittest import mock

from helpers import FakeLlm

from fastapi import FastAPI
from fastapi.testclient import TestClient

import assistant_routes
import modify_fragment
import modify_many_paragraphs
import quran_detect

app = FastAPI()
app.include_router(assistant_routes.router)
client = TestClient(app)


def normal(segment_id, text):
    return {"id": segment_id, "type": "normal", "text": text, "original": "عربي"}


def quran(segment_id, text):
    return {"id": segment_id, "type": "quran", "text": text, "original": "قرآن",
            "aya_name": "النجم", "aya_start": 5, "aya_end": 5}


def make_row(row_id, segments):
    return {"id": row_id, "segments": segments, "source_blocks": [{"id": f"block_{row_id}", "page": 1}]}


class TestFragmentEndpoints(unittest.TestCase):
    segment = normal("seg_1", "Hey my friend, don't worry")

    def test_suggest_returns_the_replacement(self):
        fake_llm = FakeLlm(lambda kwargs: "Dear friend")
        with mock.patch.object(modify_fragment.client.chat.completions, "create", fake_llm):
            response = client.post("/assistant/suggest-fragment", json={
                "segment": self.segment, "fragment_start": 0, "fragment_end": 13, "instructions": "formal"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"replacement": "Dear friend"})

    def test_suggest_on_quran_is_a_400_with_the_reason(self):
        response = client.post("/assistant/suggest-fragment", json={
            "segment": quran("seg_2", "AYAH"), "fragment_start": 0, "fragment_end": 2, "instructions": "x"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("quran", response.json()["detail"])

    def test_apply_returns_the_new_segment(self):
        response = client.post("/assistant/apply-fragment", json={
            "segment": self.segment, "fragment_start": 0, "fragment_end": 13,
            "expected_text": "Hey my friend", "replacement": "Dear friend"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["segment"]["text"], "Dear friend, don't worry")

    def test_apply_on_a_changed_text_is_a_400(self):
        response = client.post("/assistant/apply-fragment", json={
            "segment": self.segment, "fragment_start": 0, "fragment_end": 13,
            "expected_text": "Hello my friend", "replacement": "x"})
        self.assertEqual(response.status_code, 400)


class TestModifyRowsEndpoint(unittest.TestCase):
    def test_modifies_the_normal_text_and_reports_quran_only_rows(self):
        def reply(kwargs):
            sent = json.loads(kwargs["messages"][1]["content"])
            return json.dumps({"items": [{"key": i["key"], "text": "<MOD:" + i["text"] + ">"} for i in sent["items"]]})
        fake_llm = FakeLlm(reply)
        paragraphs = [[normal("seg_1", "one"), quran("seg_2", "AYAH")], [quran("seg_1", "AYAH TWO")]]
        with mock.patch.object(modify_many_paragraphs.client.chat.completions, "create", fake_llm):
            response = client.post("/assistant/modify-rows", json={"paragraphs": paragraphs, "instructions": "x"})
        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["quran_only_rows"], [1])
        self.assertEqual(body["rows"][0]["segments"][0]["text"], "<MOD:one>")
        self.assertEqual(body["rows"][0]["paragraph"], '<MOD:one> "AYAH"')
        self.assertEqual(len(fake_llm.calls), 1)

    def test_a_bad_llm_answer_is_a_400_and_not_a_crash(self):
        fake_llm = FakeLlm(lambda kwargs: "not json")
        with mock.patch.object(modify_many_paragraphs.client.chat.completions, "create", fake_llm):
            response = client.post("/assistant/modify-rows", json={"paragraphs": [[normal("seg_1", "one")]], "instructions": "x"})
        self.assertEqual(response.status_code, 400)


class TestRetranslateEndpoint(unittest.TestCase):
    def test_returns_the_new_segments_and_the_quran_changes(self):
        fake_llm = FakeLlm(lambda kwargs: "<LLM:" + kwargs["messages"][1]["content"] + ">")
        old_segments = [normal("seg_1", "old")]
        with mock.patch.object(quran_detect.client.chat.completions, "create", fake_llm):
            response = client.post("/retranslate", json={
                "old_segments": old_segments,
                "new_original_text": "ورجعنا البيت علمه شديد القوي ذو مرة فاستوي"})
        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual([s["type"] for s in body["segments"]], ["normal", "quran"])
        self.assertEqual(len(body["quran_changes"]["added"]), 1)
        self.assertTrue(body["needs_review"])
        self.assertEqual(body["previous_segments"], old_segments)


class TestMergeEndpoints(unittest.TestCase):
    def rows(self):
        return [
            make_row("r1", [normal("seg_1", "one")]),
            make_row("r2", [normal("seg_1", "two a"), quran("seg_2", "AYAH")]),
            make_row("r3", [normal("seg_1", "three")]),
        ]

    def test_merge_problem_is_null_when_the_rows_are_next_to_each_other(self):
        response = client.post("/rows/merge-problem", json={"rows": self.rows(), "selected_row_ids": ["r1", "r2"]})
        self.assertEqual(response.json(), {"problem": None})

    def test_merge_problem_gives_the_reason_when_they_are_not(self):
        response = client.post("/rows/merge-problem", json={"rows": self.rows(), "selected_row_ids": ["r1", "r3"]})
        self.assertIn("next to each other", response.json()["problem"])

    def test_merge_returns_the_merged_row_and_its_view(self):
        response = client.post("/rows/merge", json={"rows": self.rows(), "selected_row_ids": ["r2", "r1"]})
        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["row"]["id"], "r1+r2")
        self.assertEqual(body["view"]["paragraph"], 'one two a "AYAH"')
        self.assertTrue(body["view"]["is_merged"])
        self.assertEqual([b["id"] for b in body["row"]["source_blocks"]], ["block_r1", "block_r2"])

    def test_a_refused_merge_is_a_400(self):
        response = client.post("/rows/merge", json={"rows": self.rows(), "selected_row_ids": ["r1", "r3"]})
        self.assertEqual(response.status_code, 400)

    def test_unmerge_brings_the_rows_back(self):
        rows = self.rows()
        merged = client.post("/rows/merge", json={"rows": rows, "selected_row_ids": ["r1", "r2"]}).json()["row"]
        response = client.post("/rows/unmerge", json={"rows": [merged, rows[2]], "merged_row_id": "r1+r2"})
        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["rows"], rows[:2])
        self.assertEqual([v["id"] for v in body["views"]], ["r1", "r2"])

    def test_unmerge_of_a_normal_row_is_a_400(self):
        response = client.post("/rows/unmerge", json={"rows": self.rows(), "merged_row_id": "r1"})
        self.assertEqual(response.status_code, 400)


class TestTranslateEndpointInMain(unittest.TestCase):
    def test_translate_returns_translation_parts_and_segments(self):
        # main.py imports the ocr module that needs the datalab sdk; it is not needed for this test
        sys.modules.setdefault("datalab_sdk", types.SimpleNamespace(ConvertOptions=object, DatalabClient=object))
        import main

        fake_llm = FakeLlm(lambda kwargs: "<LLM:" + kwargs["messages"][1]["content"] + ">")
        with mock.patch.object(quran_detect.client.chat.completions, "create", fake_llm):
            response = TestClient(main.app).post("/translate", json={
                "text": "اذيا صاحبي علمه شديد القوي ذو مرة فاستوي", "target_lang": "English"})
        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual([p["id"] for p in body["parts"]], ["seg_1", "seg_2"])
        self.assertEqual(body["parts"][1]["type"], "quran")
        self.assertIn('"He has been taught', body["translation"])
        self.assertEqual([s["id"] for s in body["segments"]], ["seg_1", "seg_2"])


if __name__ == "__main__":
    unittest.main()
