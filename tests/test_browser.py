"""Local-only rendered browser integration tests; skip if Chromium is unavailable."""

import functools
import http.server
import tempfile
import threading
import unittest
from pathlib import Path

from abyss_app.extraction import BrowserExtractor, Cancelled


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        Path(cls.temp.name, "index.html").write_text("""<!doctype html><meta charset='utf-8'>
<script>setTimeout(() => {
    document.body.innerHTML = '<h1>Example video</h1><iframe id="player" src="/embed?v=2IkDMd-H81&show=0"></iframe>';
}, 300);</script><body></body>""")
        handler = functools.partial(QuietHandler, directory=cls.temp.name)
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.addClassCleanup(cls.server.server_close)
        cls.addClassCleanup(cls.server.shutdown)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/index.html"
        cls.stop = threading.Event()
        cls.extractor = BrowserExtractor("//iframe[@id='player']", "//h1", cls.stop)
        try:
            cls.extractor.__enter__()
        except Exception as exc:
            raise unittest.SkipTest(f"Browser unavailable: {exc}")
        cls.addClassCleanup(cls.extractor.__exit__, None, None, None)

    def setUp(self):
        self.stop.clear()
        self.extractor.iframe_xpath = "//iframe[@id='player']"
        self.extractor.title_xpath = "//h1"

    def test_dynamic_element_xpath(self):
        self.assertEqual(self.extractor.extract(self.url), ("2IkDMd-H81", "Example video"))

    def test_attribute_and_text_xpath(self):
        self.extractor.iframe_xpath += "/@src"
        self.extractor.title_xpath += "/text()"
        self.assertEqual(self.extractor.extract(self.url), ("2IkDMd-H81", "Example video"))

    def test_manual_title_skips_title_xpath(self):
        self.extractor.title_xpath = "//*["  # Would fail if evaluated.
        self.assertEqual(self.extractor.extract(self.url, manual_title="My episode"),
                         ("2IkDMd-H81", "My episode"))

    def test_invalid_xpath(self):
        self.extractor.iframe_xpath = "//*["
        with self.assertRaises(Exception) as error:
            self.extractor.extract(self.url)
        self.assertIn("XPath", str(error.exception))

    def test_ambiguous_xpath(self):
        self.extractor.title_xpath = "//*"
        with self.assertRaisesRegex(Exception, "multiple nodes"):
            self.extractor.extract(self.url)

    def test_cancel_before_navigation(self):
        self.stop.set()
        with self.assertRaises(Cancelled):
            self.extractor.extract(self.url)


if __name__ == "__main__":
    unittest.main()
