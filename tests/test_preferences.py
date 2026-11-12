import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from abyss_app.preferences import load_preferences, preferences_path, save_preferences


class PreferencesTests(unittest.TestCase):
    def test_missing_file_returns_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_preferences(Path(tmp) / "missing.json"), {})

    def test_round_trip_and_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config" / "settings.json"
            values = {"iframe_xpath": "//iframe[@title='视频']/@src", "title_xpath": "//h1", "jar": "/tmp/a jar.jar", "output": "/tmp/videos"}
            save_preferences(path, values)
            self.assertEqual(load_preferences(path), values)
            values["title_xpath"] = "//h2"
            save_preferences(path, values)
            self.assertEqual(load_preferences(path), values)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_invalid_schema_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            for raw in ['{', '[]', '{"iframe_xpath": null}', '{"output": 12}']:
                with self.subTest(raw=raw):
                    path.write_text(raw)
                    with self.assertRaises(ValueError):
                        load_preferences(path)
            path.write_text('{"title_xpath": "//h1", "unknown": 12}')
            self.assertEqual(load_preferences(path), {"title_xpath": "//h1"})

    def test_failed_replace_keeps_previous_settings_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            values = dict(iframe_xpath="", title_xpath="", jar="", output="")
            save_preferences(path, values)
            with patch("abyss_app.preferences.os.replace", side_effect=PermissionError("read only")):
                with self.assertRaises(PermissionError):
                    save_preferences(path, {**values, "title_xpath": "//h1"})
            self.assertEqual(load_preferences(path), values)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_xdg_location(self):
        with patch.dict("os.environ", {"XDG_CONFIG_HOME": "/tmp/abyss-test-config"}):
            self.assertEqual(preferences_path(), Path("/tmp/abyss-test-config/abyss-downloader/settings.json"))
        with patch.dict("os.environ", {"XDG_CONFIG_HOME": "relative"}):
            self.assertEqual(preferences_path(), Path.home() / ".config/abyss-downloader/settings.json")
