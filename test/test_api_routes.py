import copy
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from helpers import FakeLlm

from fastapi import FastAPI
from fastapi.testclient import TestClient

import assistant_routes
import modify_fragment
import modify_many_paragraphs
import quran_detect
import refine_ocr

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

    def test_detect_ayas_marks_the_quran_without_calling_the_llm(self):
        sys.modules.setdefault("datalab_sdk", types.SimpleNamespace(ConvertOptions=object, DatalabClient=object))
        import main

        fake_llm = FakeLlm(lambda kwargs: "<LLM>")
        with mock.patch.object(quran_detect.client.chat.completions, "create", fake_llm):
            response = TestClient(main.app).post("/detect-ayas", json={
                "text": "اذيا صاحبي علمه شديد القوي ذو مرة فاستوي"})
        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual([s["type"] for s in body["segments"]], ["normal", "quran"])
        self.assertEqual(body["segments"][1]["aya_name"], "النجم")
        # the arabic is kept as it is, nothing was translated
        self.assertEqual(body["segments"][1]["text"], "علمه شديد القوي ذو مرة فاستوي")
        self.assertEqual(fake_llm.calls, [])

    def test_detect_ayas_on_text_without_quran_is_only_normal_text(self):
        sys.modules.setdefault("datalab_sdk", types.SimpleNamespace(ConvertOptions=object, DatalabClient=object))
        import main

        response = TestClient(main.app).post("/detect-ayas", json={"text": "قال|Author كان يقول"})
        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual([s["type"] for s in body["segments"]], ["normal"])


class TestRefineOcrPrompt(unittest.TestCase):
    def test_the_prompt_asks_for_a_repair_only(self):
        system_prompt = refine_ocr.SYSTEM_PROMPT
        self.assertIn("do not rephrase", system_prompt)
        self.assertIn("not a rewrite", system_prompt)
        self.assertIn("Never invent text", system_prompt)

    def test_the_prompt_explains_the_ayah_marks(self):
        system_prompt = refine_ocr.SYSTEM_PROMPT
        self.assertIn("[[", system_prompt)
        self.assertIn("]]", system_prompt)
        # an ayah can be cut in half: the words around the marks are part of it too
        self.assertIn("cuts an ayah in half", system_prompt)

    def test_the_prompt_does_not_ask_for_tashkeel(self):
        # the model gets it wrong more often than it gets it right, and it is not worth the risk
        self.assertNotIn("tashkeel", refine_ocr.SYSTEM_PROMPT.lower())


class TestMarkDetectedAyas(unittest.TestCase):
    def test_one_pair_of_marks_per_detected_ayah(self):
        matches = [{"startInText": 1, "endInText": 3}]
        self.assertEqual(
            refine_ocr.mark_detected_ayas("ذهب إلى البيت", matches),
            "ذهب [[ إلى البيت ]]",
        )

    def test_two_ayas_are_marked_separately(self):
        matches = [{"startInText": 0, "endInText": 1}, {"startInText": 2, "endInText": 4}]
        self.assertEqual(
            refine_ocr.mark_detected_ayas("أ ب ج د", matches),
            "[[ أ ]] ب [[ ج د ]]",
        )

    def test_a_text_without_quran_is_sent_unchanged(self):
        self.assertEqual(refine_ocr.mark_detected_ayas("لا آية هنا", []), "لا آية هنا")

    def test_overlapping_matches_are_not_marked_twice(self):
        matches = [{"startInText": 0, "endInText": 2}, {"startInText": 1, "endInText": 3}]
        self.assertEqual(refine_ocr.mark_detected_ayas("أ ب ج", matches), "[[ أ ب ]] ج")

    def test_the_marks_are_taken_out_of_the_answer(self):
        self.assertEqual(refine_ocr.remove_aya_marks("قبل [[ بعد ]] و[[ أخرى ]]"), "قبل بعد و أخرى")

    def test_the_text_is_kept_when_the_llm_answers_nothing(self):
        fake_llm = FakeLlm(lambda kwargs: "   ")
        with mock.patch.object(refine_ocr.client.chat.completions, "create", fake_llm):
            self.assertEqual(refine_ocr.refine_ocr_text("كان极速"), "كان极速")

    def test_the_ayas_are_marked_before_the_llm_is_called(self):
        # the quran detector marked the ayah, so the model knows where it is
        fake_llm = FakeLlm(lambda kwargs: kwargs["messages"][1]["content"])
        with mock.patch.object(refine_ocr.client.chat.completions, "create", fake_llm):
            # the fake llm echoes the marked text back, marks and all: they must not stay in the answer
            self.assertEqual(
                refine_ocr.refine_ocr_text("اذيا صاحبي علمه شديد القوي ذو مرة فاستوي"),
                "اذيا صاحبي علمه شديد القوي ذو مرة فاستوي",
            )
        self.assertEqual(
            fake_llm.calls[0]["messages"][1]["content"],
            "اذيا صاحبي [[ علمه شديد القوي ذو مرة فاستوي ]]",
        )


def an_ocr_page():
    """A page as datalab writes it: a page block holding a header, two paragraphs
    and a footer. Only the paragraphs carry text."""
    return {
        "block_type": "Page",
        "id": "/page/0/Page/0",
        "bbox": [0.0, 0.0, 812.0, 1064.0],
        "polygon": [[0.0, 0.0], [812.0, 0.0], [812.0, 1064.0], [0.0, 1064.0]],
        "section_hierarchy": {},
        "html": "",
        "children": [
            {"id": "/page/0/PageHeader/1", "block_type": "PageHeader", "html": "",
             "bbox": [0.0, 1.0, 2.0, 3.0], "metadata": None},
            {"id": "/page/0/Text/1", "block_type": "Text", "html": "<p>اذيا صاحبي علمه</p>",
             "bbox": [0.0, 4.0, 5.0, 6.0], "markdown": None, "metadata": None,
             "inference_failed": False, "page": 0},
            {"id": "/page/0/Text/2", "block_type": "Text", "html": "<p>لا آية هنا</p>",
             "bbox": [0.0, 7.0, 8.0, 9.0], "markdown": None, "metadata": None,
             "inference_failed": False, "page": 0},
            {"id": "/page/0/PageFooter/4", "block_type": "PageFooter", "html": "",
             "bbox": [0.0, 10.0, 11.0, 12.0], "metadata": None},
        ],
    }


class TestRefineOcrPage(unittest.TestCase):
    def test_one_llm_call_per_paragraph(self):
        page = an_ocr_page()
        fake_llm = FakeLlm(lambda kwargs: "نص")
        with mock.patch.object(refine_ocr.client.chat.completions, "create", fake_llm):
            refine_ocr.refine_page(page)

        # the two paragraphs, the header and the footer have no text and are not sent
        self.assertEqual(len(fake_llm.calls), 2)
        sent = sorted(call["messages"][1]["content"] for call in fake_llm.calls)
        self.assertEqual(sent, ["اذيا صاحبي علمه", "لا آية هنا"])

    def test_the_json_keeps_its_shape_and_only_the_text_changes(self):
        page = an_ocr_page()
        fake_llm = FakeLlm(lambda kwargs: "نص")
        with mock.patch.object(refine_ocr.client.chat.completions, "create", fake_llm):
            refined = refine_ocr.refine_page(page)

        self.assertEqual(refined["id"], page["id"])
        self.assertEqual(refined["bbox"], page["bbox"])
        self.assertEqual(refined["polygon"], page["polygon"])
        self.assertEqual(refined["section_hierarchy"], page["section_hierarchy"])
        self.assertEqual(len(refined["children"]), len(page["children"]))
        for refined_block, original_block in zip(refined["children"], page["children"]):
            self.assertEqual(refined_block["id"], original_block["id"])
            self.assertEqual(refined_block["block_type"], original_block["block_type"])
            self.assertEqual(refined_block["bbox"], original_block["bbox"])
            # every field came through, and no field was added
            self.assertEqual(sorted(refined_block), sorted(original_block))
        # the paragraphs kept their "<p>" wrapper, only the words inside are new
        self.assertEqual(refined["children"][1]["html"], "<p>نص</p>")
        self.assertEqual(refined["children"][2]["html"], "<p>نص</p>")

    def test_the_page_html_is_its_paragraphs_one_after_the_other(self):
        page = an_ocr_page()
        page["html"] = "".join(block["html"] for block in page["children"])
        fake_llm = FakeLlm(lambda kwargs: "نص")
        with mock.patch.object(refine_ocr.client.chat.completions, "create", fake_llm):
            refined = refine_ocr.refine_page(page)
        self.assertEqual(refined["html"], "<p>نص</p><p>نص</p>")

    def test_the_page_it_came_in_is_not_touched(self):
        page = an_ocr_page()
        before = copy.deepcopy(page)
        fake_llm = FakeLlm(lambda kwargs: "نص")
        with mock.patch.object(refine_ocr.client.chat.completions, "create", fake_llm):
            refine_ocr.refine_page(page)
        self.assertEqual(page, before)

    def test_a_failed_call_keeps_that_paragraph_only(self):
        page = an_ocr_page()
        answers = {"اذيا صاحبي علمه": "نص جديد"}

        def answer(kwargs):
            text = kwargs["messages"][1]["content"]
            if text not in answers:
                raise RuntimeError("the api is down")
            return answers[text]

        with mock.patch.object(refine_ocr.client.chat.completions, "create", FakeLlm(answer)):
            refined = refine_ocr.refine_page(page)

        # the paragraph whose call failed is left alone, the other one is fixed
        self.assertEqual(refined["children"][1]["html"], "<p>نص جديد</p>")
        self.assertEqual(refined["children"][2]["html"], "<p>لا آية هنا</p>")

    def test_a_page_without_paragraphs_is_left_alone(self):
        page = an_ocr_page()
        page["children"] = []
        fake_llm = FakeLlm(lambda kwargs: "نص")
        with mock.patch.object(refine_ocr.client.chat.completions, "create", fake_llm):
            refined = refine_ocr.refine_page(page)
        self.assertEqual(refined["children"], [])
        self.assertEqual(fake_llm.calls, [])

    def test_footnotes_and_section_headers_are_refined_too(self):
        # the table shows a row for every block that carries text, not just for the body
        page = an_ocr_page()
        page["children"][3] = {"id": "/page/0/SectionHeader/4", "block_type": "SectionHeader",
                               "html": "<h1>الفصل الأول</h1>", "bbox": [0.0, 7.0, 8.0, 9.0]}
        page["children"][2]["block_type"] = "Footnote"

        fake_llm = FakeLlm(lambda kwargs: "نص")
        with mock.patch.object(refine_ocr.client.chat.completions, "create", fake_llm):
            refined = refine_ocr.refine_page(page)

        # the paragraph, the footnote and the section header
        self.assertEqual(len(fake_llm.calls), 3)
        self.assertIn("الفصل الأول", [call["messages"][1]["content"] for call in fake_llm.calls])
        # a header without <p> still comes back as a paragraph of text
        self.assertEqual(refined["children"][3]["html"], "<p>نص</p>")


class TestParagraphText(unittest.TestCase):
    """Datalab writes html inside the paragraph. None of it may reach the reader: it used
    to be escaped back into the text, so the rows showed a literal "<br/>"."""

    def test_the_line_breaks_of_the_printed_page_are_gone(self):
        html = "<p>كان من خيري،<br/>والله ما اجتمعت</p>"
        self.assertEqual(refine_ocr.paragraph_text(html), "كان من خيري، والله ما اجتمعت")

    def test_a_tag_becomes_a_space_so_the_words_stay_apart(self):
        # "end of a line<br/>start of the next": without the space the words would be glued
        self.assertEqual(refine_ocr.paragraph_text("<p>نهاية<br/>بداية</p>"), "نهاية بداية")

    def test_the_other_tags_datalab_writes_are_gone_too(self):
        html = "<p>لا إله إلا الله<sup>1</sup> وهو العلي<sup>2</sup></p>"
        self.assertEqual(refine_ocr.paragraph_text(html), "لا إله إلا الله 1 وهو العلي 2")

    def test_the_entities_are_read_as_the_characters_they_mean(self):
        self.assertEqual(refine_ocr.paragraph_text("<p>عبد &amp; غيره</p>"), "عبد & غيره")

    def test_a_tag_that_is_only_written_out_stays_text(self):
        # an escaped "&lt;br/&gt;" is not a tag: the author printed the characters
        self.assertEqual(refine_ocr.paragraph_text("<p>&lt;br/&gt;</p>"), "<br/>")

    def test_two_paragraphs_are_not_melted_into_one(self):
        # a greedy match would capture "الأول</p><p>الثاني" and write it back as text
        html = "<p>الأول</p><p>الثاني</p>"
        self.assertEqual(refine_ocr.paragraph_text(html), "الأول")
        self.assertEqual(refine_ocr.with_paragraph_text(html, "مصلح"), "<p>مصلح</p><p>الثاني</p>")

    def test_the_fixed_text_is_escaped_so_markup_cannot_come_back(self):
        self.assertEqual(
            refine_ocr.with_paragraph_text("<p>قديم</p>", "جديد & <br/>"),
            "<p>جديد &amp; &lt;br/&gt;</p>",
        )

    def test_the_line_breaks_are_not_asked_about_by_the_llm(self):
        page = an_ocr_page()
        page["children"][1]["html"] = "<p>اذيا صاحبي،<br/>علمه</p>"
        fake_llm = FakeLlm(lambda kwargs: "نص")
        with mock.patch.object(refine_ocr.client.chat.completions, "create", fake_llm):
            refine_ocr.refine_page(page)
        self.assertEqual(fake_llm.calls[0]["messages"][1]["content"], "اذيا صاحبي، علمه")


class TestRefinedPageCache(unittest.TestCase):
    def setUp(self):
        sys.modules.setdefault("datalab_sdk", types.SimpleNamespace(ConvertOptions=object, DatalabClient=object))
        import ocr
        self.ocr = ocr

    def test_the_refined_page_is_written_next_to_the_raw_one_and_read_back_after(self):
        page = an_ocr_page()
        with tempfile.TemporaryDirectory() as book:
            book = Path(book)
            fake_llm = FakeLlm(lambda kwargs: "نص")
            with mock.patch.object(refine_ocr.client.chat.completions, "create", fake_llm):
                refined = self.ocr.load_or_build_refined_page(book, 0, page)
            self.assertEqual(refined["children"][1]["html"], "<p>نص</p>")
            # 0.json is what datalab returned and stays untouched, 0_refined.json is ours
            written = json.loads((book / "0_refined.json").read_text(encoding="utf-8"))
            self.assertEqual(written["children"][1]["html"], "<p>نص</p>")
            self.assertFalse((book / "0.json").exists())

            # the second time the file on disk is used, and the llm is not called again
            fake_llm = FakeLlm(lambda kwargs: "شيء آخر")
            with mock.patch.object(refine_ocr.client.chat.completions, "create", fake_llm):
                again = self.ocr.load_or_build_refined_page(book, 0, page)
            self.assertEqual(again, refined)
            self.assertEqual(fake_llm.calls, [])

    def test_a_damaged_refined_file_is_built_again(self):
        page = an_ocr_page()
        with tempfile.TemporaryDirectory() as book:
            book = Path(book)
            (book / "0_refined.json").write_text("{ not json", encoding="utf-8")
            fake_llm = FakeLlm(lambda kwargs: "نص")
            with mock.patch.object(refine_ocr.client.chat.completions, "create", fake_llm):
                refined = self.ocr.load_or_build_refined_page(book, 0, page)
            self.assertEqual(refined["children"][1]["html"], "<p>نص</p>")
            self.assertEqual(len(fake_llm.calls), 2)

    def test_a_refined_file_older_than_its_raw_page_is_built_again(self):
        # datalab writes the raw page again when the pdf changed: the refined text that
        # came from the old one is stale and must not be served
        page = an_ocr_page()
        with tempfile.TemporaryDirectory() as book:
            book = Path(book)
            raw_file = book / "0.json"
            raw_file.write_text(json.dumps(page, ensure_ascii=False), encoding="utf-8")
            (book / "0_refined.json").write_text(
                json.dumps({"block_type": "Page", "children": [{"block_type": "Text"}], "old": True}),
                encoding="utf-8")
            # the refined file was written before the raw page was fetched again
            os.utime(book / "0_refined.json", ns=(1_000_000, 1_000_000))
            os.utime(raw_file, ns=(2_000_000, 2_000_000))

            fake_llm = FakeLlm(lambda kwargs: "نص جديد")
            with mock.patch.object(refine_ocr.client.chat.completions, "create", fake_llm):
                refined = self.ocr.load_or_build_refined_page(book, 0, page)
            self.assertEqual(refined["children"][1]["html"], "<p>نص جديد</p>")
            self.assertNotIn("old", refined)

    def test_a_refined_file_newer_than_its_raw_page_is_kept(self):
        page = an_ocr_page()
        with tempfile.TemporaryDirectory() as book:
            book = Path(book)
            raw_file = book / "0.json"
            raw_file.write_text(json.dumps(page, ensure_ascii=False), encoding="utf-8")
            (book / "0_refined.json").write_text(
                json.dumps({"block_type": "Page", "children": [], "marker": "cached"}), encoding="utf-8")
            os.utime(raw_file, ns=(1_000_000, 1_000_000))
            os.utime(book / "0_refined.json", ns=(2_000_000, 2_000_000))

            fake_llm = FakeLlm(lambda kwargs: "نص")
            with mock.patch.object(refine_ocr.client.chat.completions, "create", fake_llm):
                refined = self.ocr.load_or_build_refined_page(book, 0, page)
            self.assertEqual(refined["marker"], "cached")
            self.assertEqual(fake_llm.calls, [])


if __name__ == "__main__":
    unittest.main()
