import os
import subprocess
import sys
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401  (paths and the fake keys)

from fastapi.testclient import TestClient

import quran_detect

# The quran detector takes ~6 seconds to build. It used to be built when the server started, so the browser showed an
# error until it was done. Now the server starts without it and it is built when it is needed (or earlier, when the
# page of the user chooses a book).

PROJECT = Path(__file__).resolve().parent.parent


class FakeAnnotater:
    built = 0

    def __init__(self):
        type(self).built += 1
        time.sleep(0.05)  # a slow build, so threads that ask together really overlap

    def matchAll(self, paragraph):
        return []


class TestLazyDetector(unittest.TestCase):
    def setUp(self):
        FakeAnnotater.built = 0
        # the real detector stays untouched: the module variable is put back after the test
        previous = quran_detect._annotater
        quran_detect._annotater = None
        self.addCleanup(setattr, quran_detect, "_annotater", previous)
        patcher = mock.patch.object(quran_detect.qdetect, "qMatcherAnnotater", FakeAnnotater)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_it_is_not_built_until_it_is_needed(self):
        self.assertFalse(quran_detect.detector_is_ready())
        self.assertEqual(FakeAnnotater.built, 0)
        quran_detect.quran_detector("نص")
        self.assertTrue(quran_detect.detector_is_ready())
        self.assertEqual(FakeAnnotater.built, 1)

    def test_it_is_built_once_even_if_many_requests_ask_together(self):
        threads = [threading.Thread(target=quran_detect.quran_detector, args=("نص",)) for _ in range(8)]
        [thread.start() for thread in threads]
        [thread.join() for thread in threads]
        self.assertEqual(FakeAnnotater.built, 1)

    def test_the_warm_up_builds_it_in_the_background(self):
        started = time.time()
        quran_detect.warm_up_detector_in_background()
        self.assertLess(time.time() - started, 0.04)  # it does not wait for the build
        for _ in range(100):
            if quran_detect.detector_is_ready():
                break
            time.sleep(0.02)
        self.assertTrue(quran_detect.detector_is_ready())
        self.assertEqual(FakeAnnotater.built, 1)

    def test_the_warm_up_does_nothing_if_it_is_already_built(self):
        quran_detect.load_detector()
        quran_detect.warm_up_detector_in_background()
        time.sleep(0.1)
        self.assertEqual(FakeAnnotater.built, 1)


class TestServerStart(unittest.TestCase):
    def test_importing_the_server_does_not_build_the_detector(self):
        # a fresh python, as when the server starts: the detector must not be built by the imports
        code = (
            "import sys, time; sys.path.insert(0, 'python'); t = time.time(); import main, quran_detect; "
            "print('ready=' + str(quran_detect.detector_is_ready()), 'seconds=%.1f' % (time.time() - t))"
        )
        environment = {**os.environ, "OPENAI_API_KEY": "fake-key-for-tests", "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run([sys.executable, "-c", code], cwd=PROJECT, env=environment,
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr[-500:])
        self.assertIn("ready=False", result.stdout)
        self.assertNotIn("Matcher/Annotator created", result.stdout)


class TestHealthAndWarmup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.modules.setdefault("datalab_sdk", types.SimpleNamespace(ConvertOptions=object, DatalabClient=object))
        import main

        cls.client = TestClient(main.app)

    def test_health_answers_at_once_and_says_if_the_detector_is_loaded(self):
        with mock.patch("main.detector_is_ready", return_value=False):
            self.assertEqual(self.client.get("/health").json(), {"status": "ok", "detector": "not loaded yet"})
        with mock.patch("main.detector_is_ready", return_value=True):
            self.assertEqual(self.client.get("/health").json(), {"status": "ok", "detector": "ready"})

    def test_warmup_starts_the_loading_and_does_not_wait_for_it(self):
        with mock.patch("main.warm_up_detector_in_background") as warm_up, \
                mock.patch("main.detector_is_ready", return_value=False):
            response = self.client.post("/warmup")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"detector": "loading"})
        warm_up.assert_called_once_with()

    def test_the_two_addresses_are_not_taken_for_a_missing_page(self):
        self.assertEqual(self.client.get("/health", headers={"Accept": "text/html"}).status_code, 200)

    def test_serve_bat_opens_the_browser_only_when_the_server_answers(self):
        script = (PROJECT / "serve.bat").read_text(encoding="utf-8")
        first_start = script.index("start ")
        self.assertIn("/health", script)
        # the browser is started by the waiting process, never by a plain `start http://...` line before uvicorn
        self.assertNotIn("start http://", script.replace('Start-Process http://', ''))
        self.assertLess(first_start, script.index("uvicorn"))


if __name__ == "__main__":
    unittest.main()
