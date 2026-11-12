"""Rendered-page XPath extraction (Playwright is imported only when used)."""

import re
import time
from threading import Event
from urllib.parse import parse_qs, urljoin, urlsplit


class Cancelled(Exception):
    """The user stopped the queue."""


def check_cancel(stop: Event) -> None:
    if stop.is_set():
        raise Cancelled("Cancelled")


def validate_video_id(value: str) -> str:
    video_id = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]*", video_id):
        raise ValueError("Enter a video ID containing only letters, digits, underscores, or hyphens; it cannot start with a hyphen.")
    return video_id


def extract_id(iframe_url: str) -> str:
    parts = urlsplit(iframe_url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("The iframe must have an HTTP(S) URL.")
    values = parse_qs(parts.query, keep_blank_values=True).get("v", [])
    if len(values) != 1 or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]*", values[0]):
        raise ValueError("The iframe URL needs exactly one valid video ID in its 'v' parameter.")
    return values[0]


# XPath expressions are passed as data, never interpolated into JavaScript.
XPATH_VALUE = r"""({expression, iframe}) => {
    const result = document.evaluate(expression, document, null, XPathResult.ANY_TYPE, null);
    let value;
    if (result.resultType === XPathResult.STRING_TYPE) value = result.stringValue;
    else if (result.resultType === XPathResult.NUMBER_TYPE || result.resultType === XPathResult.BOOLEAN_TYPE)
        throw new Error('XPath must select text or an element, not a number or boolean');
    else {
        const node = result.iterateNext();
        if (!node) return '';
        if (result.iterateNext()) throw new Error('XPath matched multiple nodes; select exactly one');
        value = node.nodeType === Node.ELEMENT_NODE
            ? (iframe ? node.getAttribute('src') : node.textContent)
            : node.nodeValue;
    }
    return (value || '').trim();
}"""


class BrowserExtractor:
    def __init__(self, iframe_xpath: str, title_xpath: str, stop: Event):
        self.iframe_xpath = iframe_xpath
        self.title_xpath = title_xpath
        self.stop = stop
        self.runtime = None
        self.browser = None

    def __enter__(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Install dependencies: pip install -r requirements.txt") from exc
        try:
            self.runtime = sync_playwright().start()
            self.browser = self.runtime.chromium.launch(headless=True)
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        try:
            if self.browser:
                self.browser.close()
        finally:
            if self.runtime:
                self.runtime.stop()

    def _value(self, page, expression: str, iframe: bool) -> str:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            check_cancel(self.stop)
            value = page.evaluate(XPATH_VALUE, {"expression": expression, "iframe": iframe})
            if value:
                return value
            self.stop.wait(0.2)
        raise ValueError(f"XPath returned no nonempty value within 20 seconds: {expression}")

    def extract(self, url: str, manual_title: str | None = None) -> tuple[str, str]:
        check_cancel(self.stop)
        # A separate context prevents cookies/storage leaking between list entries.
        context = self.browser.new_context(accept_downloads=False)
        try:
            page = context.new_page()
            # Commit avoids waiting for unrelated ads/media to finish loading.
            response = page.goto(url, wait_until="commit", timeout=10000)
            if response and response.status >= 400:
                raise ValueError(f"Page returned HTTP {response.status}")
            page.wait_for_load_state("domcontentloaded", timeout=10000)
            iframe = self._value(page, self.iframe_xpath, True)
            title = manual_title if manual_title is not None else self._value(page, self.title_xpath, False)
            base_uri = page.evaluate("document.baseURI")
            check_cancel(self.stop)
            return extract_id(urljoin(base_uri, iframe)), title
        finally:
            context.close()
