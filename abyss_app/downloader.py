"""A single ordered worker and cancellable subprocess runner."""

import codecs
from contextlib import nullcontext
import os
import queue
import shutil
import signal
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .extraction import BrowserExtractor, Cancelled, check_cancel, validate_video_id
from .files import choose_output, video_filename


@dataclass(frozen=True)
class Settings:
    jar: Path
    output: Path
    iframe_xpath: str
    title_xpath: str
    java: str = "java"
    manual_title: str | None = None
    manual_video_id: str | None = None


def validate_settings(settings: Settings) -> Settings:
    jar = settings.jar.expanduser().resolve()
    output = settings.output.expanduser().resolve()
    if not jar.is_file():
        raise ValueError("Choose an existing abyss-dl.jar file.")
    java = shutil.which(settings.java)
    if not java:
        raise ValueError("Java was not found. Install Java and add it to PATH.")
    manual_video_id = settings.manual_video_id
    if manual_video_id is not None:
        manual_video_id = validate_video_id(manual_video_id)
        if settings.manual_title is None:
            raise ValueError("A manual video ID requires a manual video title.")
    elif not settings.iframe_xpath.strip():
        raise ValueError("Enter the iframe XPath.")
    manual_title = settings.manual_title
    if manual_title is not None:
        manual_title = manual_title.strip()
        if not manual_title:
            raise ValueError("Enter a video title for the single URL.")
        video_filename(manual_title)
    elif not settings.title_xpath.strip():
        raise ValueError("Enter the video title XPath for the TXT file.")
    if not output.is_dir():
        raise ValueError("Choose an existing output directory.")
    # Test real writability rather than relying on permission bits.
    with tempfile.TemporaryFile(dir=output):
        pass
    return Settings(jar, output, settings.iframe_xpath.strip(), settings.title_xpath.strip(), java, manual_title, manual_video_id)


def terminate_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait()
    except ProcessLookupError:
        pass


def run_download(settings: Settings, video_id: str, target: Path,
                 stop: threading.Event, log: Callable[[str], None]) -> None:
    check_cancel(stop)
    argv = [settings.java, "-jar", str(settings.jar), video_id, "-o", str(target)]
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               start_new_session=(os.name == "posix"), cwd=target.parent)

    def read_output():
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        try:
            while chunk := os.read(process.stdout.fileno(), 1024):
                log(decoder.decode(chunk))
            remainder = decoder.decode(b"", final=True)
            if remainder:
                log(remainder)
        except (OSError, ValueError):
            pass

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    try:
        while process.poll() is None:
            if stop.wait(0.1):
                raise Cancelled("Cancelled")
        check_cancel(stop)
        if process.returncode:
            raise RuntimeError(f"Java exited with code {process.returncode}")
        if target.is_symlink() or not target.is_file() or target.stat().st_size == 0:
            raise RuntimeError("Java exited successfully but produced no nonempty video file.")
    finally:
        terminate_process(process)
        reader.join(timeout=2)
        process.stdout.close()


class DownloadWorker:
    def __init__(self, settings: Settings, urls: list[str], events: queue.Queue,
                 stop: threading.Event, extractor_factory=BrowserExtractor,
                 runner=run_download):
        self.settings, self.urls = settings, urls
        self.events, self.stop = events, stop
        self.extractor_factory, self.runner = extractor_factory, runner

    def emit(self, kind: str, **values):
        self.events.put((kind, values))

    def log(self, text: str):
        # Bound pending logs even when the UI cannot keep up; state events are never dropped.
        if self.events.qsize() < 500:
            self.emit("log", text=text)

    def run(self):
        reserved: set[Path] = set()
        finished: set[int] = set()
        try:
            check_cancel(self.stop)
            context = (nullcontext(None) if self.settings.manual_video_id is not None else
                       self.extractor_factory(self.settings.iframe_xpath, self.settings.title_xpath, self.stop))
            with context as extractor:
                for index, url in enumerate(self.urls):
                    check_cancel(self.stop)
                    self.emit("item", index=index, status="Preparing" if self.settings.manual_video_id is not None else "Extracting")
                    try:
                        if self.settings.manual_video_id is not None:
                            video_id = validate_video_id(self.settings.manual_video_id)
                            title = self.settings.manual_title
                        elif self.settings.manual_title is not None:
                            video_id, title = extractor.extract(url, manual_title=self.settings.manual_title)
                        else:
                            video_id, title = extractor.extract(url)
                        check_cancel(self.stop)
                        target = choose_output(self.settings.output, title, reserved)
                        self.emit("item", index=index, status="Downloading", title=title, video_id=video_id, detail=str(target))
                        # Write into a private directory first. Atomic, no-clobber publication
                        # protects existing files even if another app creates the same name.
                        with tempfile.TemporaryDirectory(prefix=".abyss-", dir=self.settings.output) as staging:
                            staged = Path(staging) / target.name
                            self.runner(self.settings, video_id, staged, self.stop, self.log)
                            check_cancel(self.stop)
                            while True:
                                try:
                                    os.link(staged, target)
                                    break
                                except FileExistsError:
                                    target = choose_output(self.settings.output, title, reserved)
                        self.emit("item", index=index, status="Completed", detail=str(target))
                        finished.add(index)
                    except Cancelled:
                        raise
                    except Exception as exc:
                        self.emit("item", index=index, status="Failed", detail=str(exc))
                        self.log(f"\nItem {index + 1} failed: {exc}\n")
                        finished.add(index)
        except Cancelled:
            pass
        except Exception as exc:
            self.emit("error", text=str(exc))
        finally:
            for index in range(len(self.urls)):
                if index not in finished:
                    self.emit("item", index=index, status="Cancelled" if self.stop.is_set() else "Failed")
            self.emit("done")
