import sys
import types
import unittest

import helpers  # noqa: F401  (paths and the fake keys)

from fastapi.testclient import TestClient

# The pages of the site:
#   /     the home page          /app  the viewer
#   any other address that does not exist: the page of web/404.html for a browser, a short answer for everything else.

BROWSER = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}


class TestPages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # main.py imports the ocr module that needs the datalab sdk; it is not needed here
        sys.modules.setdefault("datalab_sdk", types.SimpleNamespace(ConvertOptions=object, DatalabClient=object))
        import main

        cls.client = TestClient(main.app)

    def get(self, path, headers=None, **kwargs):
        return self.client.get(path, headers=headers, follow_redirects=False, **kwargs)

    def test_the_root_is_the_home_page(self):
        response = self.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("ترجم. راجع.", response.text)  # the title of the home page
        self.assertIn('id="file-input"', response.text)  # the upload box

    def test_app_is_the_viewer(self):
        response = self.get("/app")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="block-rows"', response.text)
        self.assertIn('src="/web/app.js"', response.text)

    def test_the_old_addresses_of_the_two_pages_go_to_the_new_ones(self):
        home = self.get("/web/home.html")
        viewer = self.get("/web/index.html")
        self.assertEqual((home.status_code, home.headers["location"]), (307, "/"))
        self.assertEqual((viewer.status_code, viewer.headers["location"]), (307, "/app"))

    def test_the_pages_link_to_each_other_with_the_new_addresses(self):
        home_js = self.get("/web/home.js").text
        viewer = self.get("/app").text
        self.assertIn("/app?book=", home_js)  # the book that was uploaded
        self.assertIn("/books?name=", home_js)  # the upload
        self.assertNotIn("/web/index.html", home_js)
        self.assertIn('href="/"', viewer)
        self.assertNotIn("/web/home.html", viewer)

    def test_the_files_of_web_are_still_served(self):
        for path, kind in [("/web/app.js", "javascript"), ("/web/home.css", "css"), ("/web/logo-mark.svg", "svg")]:
            response = self.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn(kind, response.headers["content-type"], path)

    def test_every_page_has_an_icon_so_the_browser_does_not_ask_for_favicon_ico(self):
        for path in ["/", "/app", "/web/404.html"]:
            self.assertIn('rel="icon"', self.get(path).text, path)


class TestNotFound(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.modules.setdefault("datalab_sdk", types.SimpleNamespace(ConvertOptions=object, DatalabClient=object))
        import main

        cls.client = TestClient(main.app)

    def get(self, path, headers=None):
        return self.client.get(path, headers=headers, follow_redirects=False)

    def test_a_browser_that_opens_a_missing_address_gets_the_page_with_a_404_status(self):
        for path in ["/nope", "/app/extra", "/a/b/c", "/web/", "/web/missing.html", "/data/missing.pdf"]:
            response = self.get(path, BROWSER)
            self.assertEqual(response.status_code, 404, path)
            self.assertIn("text/html", response.headers["content-type"], path)
            self.assertIn("هذا الرابط غير موجود", response.text, path)

    def test_the_page_has_the_pen_the_languages_and_the_way_home(self):
        text = self.get("/nope", BROWSER).text
        self.assertIn('class="hero-visual"', text)  # the pen of the home page
        for language in ["العربية", "English", "Español", "Français", "Deutsch", "Türkçe"]:
            self.assertIn(language, text)
        self.assertIn('class="btn-home"', text)
        self.assertIn('href="/"', text)
        self.assertIn('content="noindex"', text)

    def test_the_page_uses_absolute_addresses_so_it_works_at_any_depth(self):
        text = self.get("/a/b/c", BROWSER).text
        self.assertNotIn('href="web/', text)
        self.assertNotIn('src="web/', text)
        for asset in ["/web/home.css", "/web/not-found.css", "/web/not-found.js"]:
            self.assertEqual(self.get(asset).status_code, 200, asset)

    def test_a_script_or_an_api_call_gets_the_short_answer_not_the_page(self):
        for headers in [None, {"Accept": "application/json"}, {"Accept": "text/css,*/*;q=0.1"}]:
            response = self.get("/api/nothing", headers)
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), {"detail": "Not Found"})
        self.assertEqual(self.get("/web/missing.js", {"Accept": "*/*"}).json(), {"detail": "Not Found"})

    def test_only_a_get_gets_the_page(self):
        response = self.client.post("/nothing", headers=BROWSER, json={})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Not Found"})

    def test_other_errors_are_not_changed(self):
        # a wrong method on a real address, and our own 400 messages, keep their usual answers
        wrong_method = self.client.get("/translate", headers=BROWSER)
        self.assertEqual(wrong_method.status_code, 405)
        self.assertNotIn("هذا الرابط غير موجود", wrong_method.text)
        bad_language = self.client.post("/translate", json={"text": "x", "target_lang": "Klingon"})
        self.assertEqual(bad_language.status_code, 400)
        self.assertIn("Klingon", bad_language.json()["detail"])

    def test_the_address_is_shown_with_textcontent_so_it_can_not_become_html(self):
        script = self.get("/web/not-found.js").text
        self.assertIn("textContent", script)
        self.assertNotIn("innerHTML", script)


if __name__ == "__main__":
    unittest.main()
