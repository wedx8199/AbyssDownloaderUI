"""Validate link lists and choose safe output names."""

import re
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit


def validate_url(value: str) -> str:
    url = value.strip()
    try:
        parts = urlsplit(url)
        valid = parts.scheme in ("http", "https") and bool(parts.hostname)
        _ = parts.port
        valid = valid and not any(c.isspace() or ord(c) < 32 for c in url)
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Enter one complete HTTP(S) webpage URL, without spaces or extra lines.")
    return url


def parse_links(path: Path) -> list[str]:
    urls, errors = [], []
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        url = line.strip()
        if not url:
            continue
        try:
            urls.append(validate_url(url))
        except ValueError:
            errors.append(str(number))
    if errors:
        raise ValueError("Invalid HTTP(S) URL on line(s): " + ", ".join(errors))
    if not urls:
        raise ValueError("The TXT file contains no URLs.")
    return urls


def video_filename(title: str) -> str:
    name = "".join(c for c in title if not unicodedata.category(c).startswith("C"))
    name = re.sub(r'[<>:"/\\|?*]', "_", name).strip(" .")
    while name.lower().endswith(".mp4"):
        name = name[:-4].rstrip(" .")
    if not name:
        raise ValueError("The video title does not contain a usable filename.")
    if re.fullmatch(r"[0-9]+", name):
        number = name.lstrip("0") or "0"
        name = "E" + number.zfill(2)
    if name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        name = "_" + name
    # Leave room for extension and collision suffix on 255-byte filesystems.
    name = name.encode("utf-8")[:180].decode("utf-8", errors="ignore").rstrip(" .")
    return name + ".mp4"


def choose_output(directory: Path, title: str, reserved: set[Path]) -> Path:
    directory = directory.resolve()
    filename = video_filename(title)
    candidate = directory / filename
    counter = 2
    while candidate.exists() or candidate.is_symlink() or candidate in reserved:
        candidate = directory / f"{filename[:-4]} ({counter}).mp4"
        counter += 1
    reserved.add(candidate)
    return candidate
