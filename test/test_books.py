import io
import json
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401  (paths and the fake keys)

from fastapi.testclient import TestClient
from pypdf import PdfWriter

import books
import ocr

# Any pdf can be uploaded: it is checked, kept under an id, and read by the ocr a few pages at a time.
# The upload folder is a temporary one and Datalab is a fake, so nothing real is written or paid.


def make_pdf(pages=3):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=300)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class BooksTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        patcher = mock.patch.object(books, "UPLOAD_DIR", self.folder)
        patcher.start()
        self.addCleanup(patcher.stop)


class TestSaveUpload(BooksTestCase):
    def test_a_pdf_is_kept_and_described(self):
        book = books.save_upload(make_pdf(3), "كتاب جميل.pdf")
        self.assertEqual((book.name, book.pages, book.sample), ("كتاب جميل.pdf", 3, False))
        self.assertRegex(book.book, r"^[0-9a-f]{16}$")
        self.assertTrue((self.folder / f"{book.book}.pdf").is_file())
        self.assertFalse((self.folder / "ocr_cache").exists())  # the ocr is kept by the browser, not here

    def test_the_same_file_is_the_same_book(self):
        first = books.save_upload(make_pdf(2), "first.pdf")
        second = books.save_upload(make_pdf(2), "second.pdf")
        self.assertEqual(first.book, second.book)
        self.assertEqual(second.name, "first.pdf")  # the name of the first upload stays
        self.assertEqual(len(list(self.folder.glob("*.pdf"))), 1)

    def test_another_file_is_another_book(self):
        self.assertNotEqual(books.save_upload(make_pdf(2), "a.pdf").book, books.save_upload(make_pdf(3), "b.pdf").book)

    def test_what_is_not_a_pdf_is_refused(self):
        for data, message in [
            (b"", "empty"),
            (b"hello, this is not a pdf", "not a pdf"),
            (b"%PDF-1.7 but then nothing that makes a pdf", "can not be read"),
            (b"MZ" + b"\0" * 100, "not a pdf"),
        ]:
            with self.assertRaisesRegex(ValueError, message):
                books.save_upload(data, "x.pdf")
        self.assertEqual(list(self.folder.glob("*.pdf")), [])  # nothing was kept

    def test_a_pdf_with_a_password_is_refused(self):
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.encrypt("secret")
        buffer = io.BytesIO()
        writer.write(buffer)
        with self.assertRaisesRegex(ValueError, "password"):
            books.save_upload(buffer.getvalue(), "locked.pdf")

    def test_too_many_pages_or_too_big_is_refused(self):
        with mock.patch.object(books, "MAX_PAGES", 2):
            with self.assertRaisesRegex(ValueError, "more than 2 pages"):
                books.save_upload(make_pdf(3), "long.pdf")
        with mock.patch.object(books, "MAX_UPLOAD_BYTES", 100):
            with self.assertRaisesRegex(ValueError, "bigger than"):
                books.save_upload(make_pdf(3), "big.pdf")

    def test_the_name_is_only_text_to_show(self):
        for given, shown in [
            ("../../etc/passwd", "passwd"),
            ("C:\\Users\\me\\book.pdf", "book.pdf"),
            ("bad\x00name\n.pdf", "badname.pdf"),
            ("", "book.pdf"),
            ("x" * 500 + ".pdf", ("x" * 500 + ".pdf")[:books.MAX_NAME_CHARS]),
        ]:
            self.assertEqual(books.clean_name(given), shown)


class TestFindBook(BooksTestCase):
    def test_an_uploaded_book_is_found_by_its_id(self):
        saved = books.save_upload(make_pdf(4), "mine.pdf")
        found = books.find_book(saved.book)
        self.assertEqual((found.name, found.pages), ("mine.pdf", 4))

    def test_a_sample_is_found_by_its_file_name(self):
        found = books.find_book("yaqzan.pdf")
        self.assertTrue(found.sample)

    def test_the_arabic_sample_is_the_default_book(self):
        found = books.find_book("فقه الاستدراك.pdf")
        self.assertTrue(found.sample)
        self.assertEqual((found.name, found.pages), ("فقه الاستدراك.pdf", 2))

    def test_a_book_that_does_not_exist_is_not_found(self):
        with self.assertRaises(FileNotFoundError):
            books.find_book("0123456789abcdef")
        with self.assertRaises(FileNotFoundError):
            books.find_book("not-there.pdf")

    def test_a_name_that_is_not_a_book_name_is_refused_before_any_file_is_touched(self):
        for bad in ["../.env", "..\\x.pdf", "/etc/passwd", "a/b.pdf", "yaqzan.pdf/../../.env", "ABCDEF0123456789",
                    "0123456789abcde", "0123456789abcdef0", "", ".pdf", "x.exe", "a" * 100 + ".pdf"]:
            with self.assertRaises(ValueError, msg=bad):
                books.find_book(bad)


class TestPageRange(unittest.TestCase):
    def test_good_ranges(self):
        for given in ["0", "0-4", "0,2-4", "3-3", "0-9"]:
            self.assertEqual(books.check_page_range(given, 100), given)

    def test_bad_ranges(self):
        for given in ["", "a", "1-", "-1", "5-2", "0-10", "0-4,6-12", "0;1", "0 - 4", "1e3", "99999"]:
            with self.assertRaises(ValueError, msg=given):
                books.check_page_range(given, 200)

    def test_a_range_outside_the_book_is_refused(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            books.check_page_range("0-5", 5)
        self.assertEqual(books.check_page_range("0-4", 5), "0-4")


class FakeDatalab:
    # stands in for DatalabClient: gives one block per asked page, and remembers what was asked
    calls = []

    def __init__(self, api_key):
        FakeDatalab.api_key = api_key

    def convert(self, path, options):
        FakeDatalab.calls.append((path, options.page_range))
        pages = ocr.decompress_range(options.page_range)
        children = [
            {"id": f"/page/{n}/Page/0", "block_type": "Page", "bbox": [0, 0, 100, 100],
             "children": [{"id": f"/page/{n}/Text/1", "block_type": "Text", "html": f"<p>صفحة {n}</p>", "polygon": []}]}
            for n in pages
        ]
        return types.SimpleNamespace(json={"children": children, "metadata": {}})


class TestEndpoints(BooksTestCase):
    @classmethod
    def setUpClass(cls):
        sys.modules.setdefault("datalab_sdk", types.SimpleNamespace(ConvertOptions=object, DatalabClient=object))
        import main

        cls.main = main
        cls.client = TestClient(main.app)

    def setUp(self):
        super().setUp()
        FakeDatalab.calls = []
        for patcher in [
            mock.patch.object(ocr, "DatalabClient", FakeDatalab),
            mock.patch.object(ocr, "ConvertOptions", lambda **kwargs: types.SimpleNamespace(**kwargs)),
            # the llm step of the ocr is not what is tested here: the page comes back as it is
            mock.patch.object(ocr, "refine_page", lambda page: page),
        ]:
            patcher.start()
            self.addCleanup(patcher.stop)

    def upload(self, data, name="كتاب.pdf"):
        return self.client.post("/books", params={"name": name}, content=data, headers={"Content-Type": "application/pdf"})

    def test_upload_gives_the_book(self):
        response = self.upload(make_pdf(3))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual((body["name"], body["pages"], body["sample"]), ("كتاب.pdf", 3, False))
        self.assertEqual(self.client.get(f"/books/{body['id']}").json(), body)

    def test_the_uploaded_pdf_is_served_back(self):
        book_id = self.upload(make_pdf(2)).json()["id"]
        response = self.client.get(f"/books/{book_id}/pdf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF-"))

    def test_the_uploads_are_not_in_the_folder_the_server_shows_to_everyone(self):
        book_id = self.upload(make_pdf(1)).json()["id"]
        self.assertEqual(self.client.get(f"/data/uploads/{book_id}.pdf").status_code, 404)
        self.assertEqual(self.client.get(f"/data/{book_id}.pdf").status_code, 404)

    def test_what_is_not_a_pdf_gets_a_message(self):
        response = self.upload(b"just some text")
        self.assertEqual(response.status_code, 400)
        self.assertIn("not a pdf", response.json()["detail"])

    def test_a_file_that_is_too_big_is_refused_while_it_arrives(self):
        with mock.patch.object(self.main, "MAX_UPLOAD_BYTES", 500):
            response = self.upload(make_pdf(3))
        self.assertEqual(response.status_code, 413)
        self.assertIn("bigger than", response.json()["detail"])
        self.assertEqual(list(self.folder.glob("*.pdf")), [])

    def test_an_unknown_book_is_a_404_and_a_bad_name_is_a_400(self):
        self.assertEqual(self.client.get("/books/0123456789abcdef").status_code, 404)
        self.assertEqual(self.client.get("/books/0123456789abcdef/pdf").status_code, 404)
        self.assertIn(self.client.get("/books/..%2F.env").status_code, (400, 404))  # a path is never followed
        self.assertEqual(self.client.get("/books/not-a-book").status_code, 400)
        self.assertEqual(self.client.get("/ocr", params={"book": "../.env", "page_range": "0"}).status_code, 400)

    def test_the_samples_are_books_too(self):
        body = self.client.get("/books/yaqzan.pdf").json()
        self.assertEqual((body["id"], body["sample"]), ("yaqzan.pdf", True))
        self.assertGreater(body["pages"], 0)
        self.assertEqual(self.client.get("/books/yaqzan.pdf/pdf").status_code, 200)

    def test_ocr_reads_the_asked_pages_of_an_uploaded_book(self):
        # nothing is kept between two requests: the browser keeps the ocr of a book in
        # localStorage (web/ocr-store.js), so a second ask for a page is a new run of datalab
        book_id = self.upload(make_pdf(8)).json()["id"]
        first = self.client.get("/ocr", params={"book": book_id, "page_range": "0-2"})
        self.assertEqual(first.status_code, 200)
        self.assertEqual([page["id"] for page in first.json()["children"]],
                         ["/page/0/Page/0", "/page/1/Page/0", "/page/2/Page/0"])
        self.assertEqual([call[1] for call in FakeDatalab.calls], ["0-2"])

        # asking again, and asking for more, is a new run of datalab for exactly what is asked
        again = self.client.get("/ocr", params={"book": book_id, "page_range": "1-4"})
        self.assertEqual([page["id"] for page in again.json()["children"]],
                         [f"/page/{n}/Page/0" for n in range(1, 5)])
        self.assertEqual([call[1] for call in FakeDatalab.calls], ["0-2", "1-4"])
        self.assertFalse((self.folder / "ocr_cache").exists())

    def test_ocr_asks_datalab_with_the_key_of_the_env(self):
        book_id = self.upload(make_pdf(1)).json()["id"]
        with mock.patch.dict("os.environ", {"DATALAB_API_KEY": "a-key-from-the-env-file"}):
            self.client.get("/ocr", params={"book": book_id, "page_range": "0"})
        self.assertEqual(FakeDatalab.api_key, "a-key-from-the-env-file")

    def test_a_missing_datalab_key_is_a_clear_error(self):
        with mock.patch.dict("os.environ", {"DATALAB_API_KEY": ""}):
            with self.assertRaisesRegex(ValueError, "DATALAB_API_KEY"):
                ocr.datalab_api_key()

    def test_ocr_refuses_a_bad_range_before_paying_for_anything(self):
        book_id = self.upload(make_pdf(30)).json()["id"]
        for page_range in ["0-10", "x", "5-2", "0-40"]:
            self.assertEqual(self.client.get("/ocr", params={"book": book_id, "page_range": page_range}).status_code, 400, page_range)
        # a long book can not be asked whole
        self.assertEqual(self.client.get("/ocr", params={"book": book_id}).status_code, 400)
        self.assertEqual(FakeDatalab.calls, [])

    def test_a_short_book_can_be_asked_without_a_range_and_the_old_parameter_still_works(self):
        book_id = self.upload(make_pdf(2)).json()["id"]
        self.assertEqual(len(self.client.get("/ocr", params={"book": book_id}).json()["children"]), 2)
        self.assertEqual(self.client.get("/ocr", params={"filename": book_id}).status_code, 200)

    def test_when_the_ocr_fails_the_user_gets_a_502(self):
        book_id = self.upload(make_pdf(1)).json()["id"]

        class Broken(FakeDatalab):
            def convert(self, path, options):
                raise RuntimeError("datalab is down")

        with mock.patch.object(ocr, "DatalabClient", Broken):
            response = self.client.get("/ocr", params={"book": book_id, "page_range": "0"})
        self.assertEqual(response.status_code, 502)
        self.assertIn("the ocr failed", response.json()["detail"])
        self.assertNotIn("datalab is down", response.text)  # the inside of the error is not shown


if __name__ == "__main__":
    unittest.main()
