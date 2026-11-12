"""Store editable desktop defaults separately from download queue state."""

import json
import os
import tempfile
from pathlib import Path

FIELDS = ("iframe_xpath", "title_xpath", "jar", "output")


def preferences_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(config_home) if config_home and Path(config_home).is_absolute() else Path.home() / ".config"
    return base / "abyss-downloader" / "settings.json"


def load_preferences(path: Path) -> dict[str, str]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Saved settings are not valid JSON.") from exc
    if not isinstance(data, dict):
        raise ValueError("Saved settings must be a JSON object.")
    if any(key in data and not isinstance(data[key], str) for key in FIELDS):
        raise ValueError("Saved XPath expressions and paths must be text.")
    return {key: data[key] for key in FIELDS if key in data}


def save_preferences(path: Path, values: dict[str, str]) -> None:
    data = {key: values[key] for key in FIELDS}
    if any(not isinstance(value, str) for value in data.values()):
        raise ValueError("XPath expressions and paths must be text.")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Replace atomically only after a complete write; never leave half-written JSON.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".settings-", suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
