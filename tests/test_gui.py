"""Opt-in real Tk window smoke: ABYSS_GUI_TEST=1 python -m unittest discover -s tests -v."""

import functools
import os
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from app import Application
from abyss_app.downloader import DownloadWorker
from abyss_app.extraction import Cancelled


class GuiExtractor:
    def __init__(self, *_):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def extract(self, url, manual_title=None):
        return "test123", manual_title if manual_title is not None else "GUI test video"


@unittest.skipUnless(os.environ.get("ABYSS_GUI_TEST") == "1", "Set ABYSS_GUI_TEST=1 with a desktop display")
class GuiTests(unittest.TestCase):
    def test_manual_id_skips_browser_and_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            jar = folder / "fake.jar"
            jar.touch()
            root = tk.Tk()
            gui = Application(root, settings_path=folder / "settings.json")
            try:
                gui.input_mode.set("single")
                gui.id_mode.set("manual")
                gui.update_input_mode()
                self.assertEqual(str(gui.url_entry["state"]), "normal")
                gui.url_entry.insert(0, "https://example.com/reference")
                self.assertEqual(gui.single_url.get(), "https://example.com/reference")
                self.assertEqual(str(gui.iframe_entry["state"]), "disabled")
                self.assertEqual(str(gui.manual_id_entry["state"]), "normal")
                gui.jar.set(str(jar))
                gui.output.set(str(folder))
                gui.manual_title.set("5")
                for invalid in ["", "-flag", "a b", "https://example.com/?v=abc"]:
                    gui.manual_id.set(invalid)
                    with patch("app.messagebox.showerror") as error:
                        gui.start_button.invoke()
                        error.assert_called_once()
                    self.assertIsNone(gui.worker_thread)
                gui.manual_id.set("  2IkDMd-H81  ")
                calls = []
                browser = unittest.mock.Mock(side_effect=AssertionError("Browser must not start"))

                def runner(settings, video_id, target, stop, log):
                    calls.append(video_id)
                    target.write_bytes(b"video")

                factory = functools.partial(DownloadWorker, extractor_factory=browser, runner=runner)
                with patch("app.DownloadWorker", factory):
                    gui.start_button.invoke()
                    self.assertEqual(str(gui.manual_id_entry["state"]), "disabled")
                    self.assertEqual(str(gui.url_entry["state"]), "disabled")
                    gui.worker_thread.join(5)
                    self.assertFalse(gui.worker_thread.is_alive())
                    gui.poll()
                browser.assert_not_called()
                self.assertEqual(str(gui.url_entry["state"]), "normal")
                self.assertEqual(gui.single_url.get(), "https://example.com/reference")
                self.assertEqual(calls, ["2IkDMd-H81"])
                self.assertTrue((folder / "E05.mp4").is_file())
                self.assertEqual(gui.tree.set(gui.rows[0], "status"), "Completed")
                gui.id_mode.set("xpath")
                gui.update_input_mode()
                self.assertEqual(str(gui.iframe_entry["state"]), "normal")
                self.assertEqual(str(gui.url_entry["state"]), "normal")
                self.assertEqual(str(gui.manual_id_entry["state"]), "disabled")
                with patch("app.messagebox.showerror") as error:
                    gui.start_button.invoke()
                    error.assert_called_once()
                gui.id_mode.set("manual")
                gui.input_mode.set("txt")
                gui.update_input_mode()
                self.assertEqual(str(gui.iframe_entry["state"]), "normal")
                self.assertEqual(str(gui.manual_id_entry["state"]), "disabled")
                self.assertTrue(all(str(radio["state"]) == "disabled" for radio in gui.id_radios))
            finally:
                gui.stop.set()
                if gui.worker_thread:
                    gui.worker_thread.join(5)
                root.destroy()

    def test_single_url_and_txt_source_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            jar = folder / "fake.jar"
            jar.touch()
            root = tk.Tk()
            gui = Application(root, settings_path=folder / "settings.json")
            try:
                self.assertEqual(str(gui.url_entry["state"]), "disabled")
                gui.input_mode.set("single")
                gui.update_input_mode()
                self.assertEqual(str(gui.url_entry["state"]), "normal")
                self.assertEqual(str(gui.txt_entry["state"]), "disabled")
                self.assertEqual(str(gui.txt_button["state"]), "disabled")
                gui.single_url.set("  https://example.com/one  ")
                gui.jar.set(str(jar))
                gui.output.set(str(folder))
                gui.iframe.set("//iframe")
                gui.title.set("")  # Single mode must not need a title XPath.
                self.assertEqual(str(gui.title_xpath_entry["state"]), "disabled")
                self.assertEqual(str(gui.manual_title_entry["state"]), "normal")
                for empty_title in ["", "   ", "..."]:
                    gui.manual_title.set(empty_title)
                    with patch("app.messagebox.showerror") as error:
                        gui.start_button.invoke()
                        error.assert_called_once()
                    self.assertIsNone(gui.worker_thread)
                gui.manual_title.set("  3  ")
                calls = []

                def runner(settings, video_id, target, stop, log):
                    calls.append(video_id)
                    target.write_bytes(b"test video")

                factory = functools.partial(DownloadWorker, extractor_factory=GuiExtractor, runner=runner)
                with patch("app.DownloadWorker", factory):
                    gui.start_button.invoke()
                    self.assertEqual(gui.urls, ["https://example.com/one"])
                    self.assertEqual(str(gui.url_entry["state"]), "disabled")
                    gui.worker_thread.join(5)
                    self.assertFalse(gui.worker_thread.is_alive())
                    gui.poll()
                self.assertEqual(len(calls), 1)
                self.assertTrue((folder / "E03.mp4").is_file())
                self.assertEqual(gui.tree.set(gui.rows[0], "title"), "3")
                self.assertEqual(str(gui.title_xpath_entry["state"]), "disabled")
                self.assertEqual(str(gui.manual_title_entry["state"]), "normal")
                self.assertEqual(gui.tree.set(gui.rows[0], "status"), "Completed")
                self.assertEqual(str(gui.url_entry["state"]), "normal")
                self.assertEqual(str(gui.txt_entry["state"]), "disabled")
                for invalid in ["", "not a link", "https://example.com/1\nhttps://example.com/2"]:
                    gui.single_url.set(invalid)
                    with patch("app.messagebox.showerror") as error:
                        gui.start_button.invoke()
                        error.assert_called_once()
                links = folder / "links.txt"
                links.write_text("https://example.com/1\nhttps://example.com/2\n")
                gui.txt.set(str(links))
                gui.input_mode.set("txt")
                gui.update_input_mode()
                self.assertEqual(str(gui.title_xpath_entry["state"]), "normal")
                self.assertEqual(str(gui.manual_title_entry["state"]), "disabled")
                with patch("app.messagebox.showerror") as error:
                    gui.start_button.invoke()
                    error.assert_called_once()
                gui.title.set("//h1")
                gui.load_links()
                self.assertEqual(len(gui.urls), 2)
                self.assertEqual(str(gui.txt_entry["state"]), "normal")
                self.assertEqual(str(gui.url_entry["state"]), "disabled")
                # Switching sources retains the text in both input fields.
                self.assertEqual(gui.txt.get(), str(links))
                gui.input_mode.set("single")
                gui.single_url.set("https://example.com/new")
                gui.update_input_mode()
                gui.load_links()
                self.assertEqual(gui.urls, ["https://example.com/new"])
                self.assertEqual(len(gui.rows), 1)
            finally:
                gui.stop.set()
                if gui.worker_thread:
                    gui.worker_thread.join(5)
                root.destroy()

    def test_progress_carriage_returns_are_displayed_as_newlines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tk.Tk()
            try:
                gui = Application(root, settings_path=Path(tmp) / "settings.json")
                # Reproduce progress updates and CRLF split across stream chunks.
                for chunk in ["Downloading 10%\r", "Downloading 20%\r", "\nDone\n", "Part", "ial\r\nNext"]:
                    gui.append_log(chunk)
                self.assertEqual(gui.log.get("1.0", "end-1c"),
                                 "Downloading 10%\nDownloading 20%\nDone\nPartial\nNext")
            finally:
                root.destroy()

    def test_settings_saved_reloaded_and_editable(self):
        from abyss_app.preferences import load_preferences, save_preferences

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            first = {"iframe_xpath": "//iframe/@src", "title_xpath": "//h1", "jar": "/old/tool.jar", "output": "/old/output"}
            save_preferences(path, first)
            root = tk.Tk()
            gui = Application(root, settings_path=path)
            try:
                root.update()
                self.assertEqual(gui.iframe.get(), first["iframe_xpath"])
                self.assertEqual(gui.title.get(), first["title_xpath"])
                self.assertEqual(gui.jar.get(), first["jar"])
                self.assertEqual(gui.output.get(), first["output"])
                gui.iframe.set("//iframe[@id='new']/@src")
                gui.title.set("//h2")
                # Edits are per-run until explicitly saved.
                self.assertEqual(load_preferences(path), first)
                gui.save_button.invoke()
                self.assertEqual(load_preferences(path)["title_xpath"], "//h2")
                self.assertIn("Settings saved", gui.settings_status.get())
                gui.set_running(True)
                self.assertEqual(str(gui.save_button["state"]), "disabled")
                gui.set_running(False)
                self.assertEqual(str(gui.save_button["state"]), "normal")
                with patch("app.save_preferences", side_effect=PermissionError("read only")), patch("app.messagebox.showerror") as error:
                    gui.save_button.invoke()
                    error.assert_called_once()
            finally:
                root.destroy()
            root = tk.Tk()
            gui = Application(root, settings_path=path)
            try:
                root.update()
                self.assertEqual(gui.iframe.get(), "//iframe[@id='new']/@src")
                self.assertEqual(gui.title.get(), "//h2")
                self.assertEqual(str(gui.editable[0]["state"]), "normal")
            finally:
                root.destroy()

    def test_corrupt_settings_does_not_prevent_opening(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text("not json")
            root = tk.Tk()
            try:
                gui = Application(root, settings_path=path)
                root.update()
                self.assertEqual(gui.iframe.get(), "")
                self.assertIn("Could not load", gui.settings_status.get())
            finally:
                root.destroy()

    def test_window_start_complete_cancel_and_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = tk.Tk()
            gui = Application(root, settings_path=Path(tmp) / "settings.json")
            try:
                folder = Path(tmp)
                links = folder / "links.txt"
                links.write_text("https://example.com/one\nhttps://example.com/two\n")
                jar = folder / "fake.jar"
                jar.touch()
                gui.txt.set(str(links))
                gui.jar.set(str(jar))
                gui.output.set(str(folder))
                gui.iframe.set("//iframe")
                gui.title.set("//h1")
                slow = threading.Event()

                def runner(settings, video_id, target, stop, log):
                    log("Fake GUI download\n")
                    if slow.is_set():
                        stop.wait(10)
                        raise Cancelled()
                    time.sleep(0.15)
                    target.write_bytes(b"test video")

                def wait_for(predicate, timeout=5):
                    deadline = time.monotonic() + timeout
                    while time.monotonic() < deadline:
                        root.update()
                        if predicate():
                            return
                        time.sleep(0.02)
                    self.fail("GUI interaction timed out")

                factory = functools.partial(DownloadWorker, extractor_factory=GuiExtractor, runner=runner)
                with patch("app.DownloadWorker", factory):
                    gui.start_button.invoke()
                    self.assertEqual(str(gui.start_button["state"]), "disabled")
                    wait_for(lambda: gui.summary.get().startswith("Finished:"))
                    self.assertIn("2 completed", gui.summary.get())
                    self.assertEqual(len(list(folder.glob("*.mp4"))), 2)
                    self.assertIn("Fake GUI download", gui.log.get("1.0", "end"))
                    slow.set()
                    gui.start_button.invoke()
                    wait_for(lambda: gui.tree.set(gui.rows[0], "status") == "Downloading")
                    gui.cancel_button.invoke()
                    wait_for(lambda: gui.summary.get().startswith("Finished:"))
                    self.assertIn("2 cancelled", gui.summary.get())
                    # Optional window-only screenshot, never the surrounding desktop.
                    screenshot = os.environ.get("ABYSS_GUI_SCREENSHOT")
                    if screenshot:
                        from PIL import ImageGrab
                        root.update()
                        x, y = root.winfo_rootx(), root.winfo_rooty()
                        ImageGrab.grab(bbox=(x, y, x + root.winfo_width(), y + root.winfo_height())).save(screenshot)
                    # Closing during an active download must stop and join the worker.
                    gui.start_button.invoke()
                    wait_for(lambda: gui.tree.set(gui.rows[0], "status") == "Downloading")
                    gui.close()
                    thread = gui.worker_thread
                    thread.join(5)
                    self.assertFalse(thread.is_alive())
            finally:
                gui.stop.set()
                if gui.worker_thread:
                    gui.worker_thread.join(5)
                try:
                    root.destroy()
                except tk.TclError:
                    pass


if __name__ == "__main__":
    unittest.main()
