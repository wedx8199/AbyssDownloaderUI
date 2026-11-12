import os
import queue
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from abyss_app.downloader import DownloadWorker, Settings, run_download, validate_settings
from abyss_app.extraction import Cancelled, extract_id, validate_video_id
from abyss_app.files import choose_output, parse_links, validate_url, video_filename


class FileTests(unittest.TestCase):
    def test_manual_video_id_validation(self):
        self.assertEqual(validate_video_id(" 2IkDMd-H81 "), "2IkDMd-H81")
        for value in ["", "   ", "-o", "a/b", "a b", "a\nother", "abc;cmd"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_video_id(value)

    def test_single_url_validation(self):
        self.assertEqual(validate_url("  https://example.com/video?v=1  "), "https://example.com/video?v=1")
        for value in ["", "example.com", "file:///tmp/video", "https://example.com:bad", "https://example.com/a b", "https://one.com\nhttps://two.com"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_url(value)

    def test_links_bom_order_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "links.txt"
            path.write_bytes(b"\xef\xbb\xbfhttps://example.com/a\r\n\r\nhttps://example.com/a\r\nhttp://example.org\n")
            self.assertEqual(parse_links(path), ["https://example.com/a", "https://example.com/a", "http://example.org"])
            path.write_text("file:///etc/passwd\nhttps://example.com:bad\nhttps://example.com/a b")
            with self.assertRaisesRegex(ValueError, "1, 2, 3"):
                parse_links(path)
            path.write_text("\n")
            with self.assertRaisesRegex(ValueError, "no URLs"):
                parse_links(path)

    def test_safe_names(self):
        for title in ["../../video", "a/b\\c:*?", "clip\x00\n", "CON", "é" * 500]:
            name = video_filename(title)
            self.assertNotIn("/", name)
            self.assertNotIn("\\", name)
            self.assertLess(len(name.encode()), 240)
            self.assertTrue(name.endswith(".mp4"))
        self.assertEqual(video_filename("Example.mp4.mp4"), "Example.mp4")
        with self.assertRaises(ValueError):
            video_filename(" . \x00")

    def test_numeric_titles_use_episode_filenames(self):
        for title, expected in [("1", "E01.mp4"), ("2", "E02.mp4"),
                                ("9", "E09.mp4"), ("10", "E10.mp4"),
                                ("100", "E100.mp4"), (" 003 ", "E03.mp4"),
                                ("4.mp4", "E04.mp4"), ("0", "E00.mp4"),
                                ("Episode 1", "Episode 1.mp4"), ("E01", "E01.mp4")]:
            with self.subTest(title=title):
                self.assertEqual(video_filename(title), expected)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "E01.mp4").write_text("existing")
            self.assertEqual(choose_output(folder, "1", set()).name, "E01 (2).mp4")

    def test_collisions_and_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "video.mp4").write_text("existing")
            (folder / "video (2).mp4").symlink_to(folder / "missing")
            reserved = set()
            self.assertEqual(choose_output(folder, "video", reserved).name, "video (3).mp4")
            self.assertEqual(choose_output(folder, "video", reserved).name, "video (4).mp4")
            self.assertEqual((folder / "video.mp4").read_text(), "existing")

    def test_video_id(self):
        self.assertEqual(extract_id("https://api.anime3s.com/ApiOk.php?v=2IkDMd-H81&show=0"), "2IkDMd-H81")
        self.assertEqual(extract_id("https://example.com/?v=%41_b-2"), "A_b-2")
        for query in ["", "v=", "v=a&v=b", "v=-flag", "v=a%20b", "v=a%00", "v=a/b"]:
            with self.subTest(query=query), self.assertRaises(ValueError):
                extract_id("https://example.com/?" + query)
        with self.assertRaises(ValueError):
            extract_id("javascript:alert(1)")


class FakeExtractor:
    def __init__(self, iframe, title, stop):
        self.stop = stop

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def extract(self, url):
        if url == "bad":
            raise ValueError("missing iframe")
        return url, "same title"


class WorkerTests(unittest.TestCase):
    def settings(self, tmp):
        return Settings(Path(tmp) / "tool.jar", Path(tmp), "//iframe", "//h1")

    def test_order_failure_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.settings(tmp)
            (Path(tmp) / "same title.mp4").write_bytes(b"keep")
            calls = []

            def runner(settings, video_id, target, stop, log):
                calls.append(video_id)
                target.write_bytes(video_id.encode())

            events = queue.Queue()
            DownloadWorker(settings, ["one", "bad", "two"], events, threading.Event(), FakeExtractor, runner).run()
            self.assertEqual(calls, ["one", "two"])
            self.assertEqual((Path(tmp) / "same title.mp4").read_bytes(), b"keep")
            self.assertEqual((Path(tmp) / "same title (2).mp4").read_bytes(), b"one")
            self.assertEqual((Path(tmp) / "same title (3).mp4").read_bytes(), b"two")
            self.assertFalse(list(Path(tmp).glob(".abyss-*")))
            statuses = [values["status"] for kind, values in list(events.queue) if kind == "item"]
            self.assertEqual(statuses, ["Extracting", "Downloading", "Completed", "Extracting", "Failed", "Extracting", "Downloading", "Completed"])

    def test_cancel_cleans_partial_and_never_starts_next(self):
        with tempfile.TemporaryDirectory() as tmp:
            stop = threading.Event()
            calls = []

            def runner(settings, video_id, target, stop, log):
                calls.append(video_id)
                target.write_bytes(b"partial")
                stop.set()
                raise Cancelled()

            events = queue.Queue()
            DownloadWorker(self.settings(tmp), ["one", "two"], events, stop, FakeExtractor, runner).run()
            self.assertEqual(calls, ["one"])
            self.assertEqual(list(Path(tmp).iterdir()), [])
            self.assertEqual(sum(v.get("status") == "Cancelled" for _, v in list(events.queue)), 2)

    def test_publication_collision_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            def runner(settings, video_id, target, stop, log):
                target.write_bytes(b"new")
                (Path(tmp) / "same title.mp4").write_bytes(b"raced")

            DownloadWorker(self.settings(tmp), ["one"], queue.Queue(), threading.Event(), FakeExtractor, runner).run()
            self.assertEqual((Path(tmp) / "same title.mp4").read_bytes(), b"raced")
            self.assertEqual((Path(tmp) / "same title (2).mp4").read_bytes(), b"new")

    def test_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = self.settings(tmp)
            with self.assertRaisesRegex(ValueError, "existing"):
                validate_settings(settings)
            settings.jar.touch()
            with patch("abyss_app.downloader.shutil.which", return_value=None):
                with self.assertRaisesRegex(ValueError, "Java"):
                    validate_settings(settings)


class ProcessTests(unittest.TestCase):
    # Fake Java is a separate script in a new temp directory. No supplied JAR is executed.
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.script = self.folder / "fake_java.py"
        self.script.write_text("""import pathlib, sys, time
video_id = sys.argv[3]
if video_id == 'fail':
    print('intentional failure', flush=True)
    sys.exit(7)
if video_id == 'wait':
    print('waiting', flush=True)
    time.sleep(60)
if video_id != 'empty':
    pathlib.Path(sys.argv[5]).write_bytes(b'video')
print('finished', flush=True)
""")
        self.settings = Settings(self.folder / "tool ; with spaces.jar", self.folder, "//iframe", "//h1", "java")
        self.target = self.folder / "clip ; $not_shell.mp4"
        import subprocess
        self.real_popen = subprocess.Popen
        self.argv = None
        self.process = None

    def tearDown(self):
        self.temp.cleanup()

    def fake_popen(self, argv, **kwargs):
        self.argv = argv
        self.process = self.real_popen([sys.executable, "-I", str(self.script), *argv[1:]], **kwargs)
        return self.process

    def test_exact_argv_and_output(self):
        logs = []
        with patch("abyss_app.downloader.subprocess.Popen", side_effect=self.fake_popen):
            run_download(self.settings, "abc-123", self.target, threading.Event(), logs.append)
        self.assertEqual(self.argv, ["java", "-jar", str(self.settings.jar), "abc-123", "-o", str(self.target)])
        self.assertEqual(self.target.read_bytes(), b"video")
        self.assertIn("finished", "".join(logs))

    def test_failure_and_empty_output(self):
        for video_id, error in [("fail", "code 7"), ("empty", "no nonempty")]:
            with self.subTest(video_id=video_id), patch("abyss_app.downloader.subprocess.Popen", side_effect=self.fake_popen):
                with self.assertRaisesRegex(RuntimeError, error):
                    run_download(self.settings, video_id, self.target, threading.Event(), lambda _: None)

    def test_cancel_terminates_and_reaps(self):
        stop = threading.Event()
        started = threading.Event()
        errors = []

        def run():
            try:
                run_download(self.settings, "wait", self.target, stop, lambda text: started.set())
            except Exception as exc:
                errors.append(exc)

        with patch("abyss_app.downloader.subprocess.Popen", side_effect=self.fake_popen):
            thread = threading.Thread(target=run)
            thread.start()
            try:
                self.assertTrue(started.wait(5))
            finally:
                stop.set()
                thread.join(5)
            self.assertFalse(thread.is_alive())
        self.assertIsInstance(errors[0], Cancelled)
        self.assertIsNotNone(self.process.poll())


if __name__ == "__main__":
    unittest.main()
