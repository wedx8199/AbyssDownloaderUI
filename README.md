# Abyss Player Downloader

A local **desktop app** for pasting a single webpage URL or loading URLs from a TXT file, extracting a video ID and title using XPath, and running `abyss-dl.jar` **one video at a time, in file order**.

## Platform support

Currently supported on **Linux only**. A Windows version is planned for a later release; the setup and launch instructions below are for Linux.

## Start

Python 3.10+ and Java are required. Use a normal desktop session (Tkinter needs a display).

```bash
cd /home/kai/projects/abyss
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python app.py
```

The virtual environment, Python dependencies, and Chromium have already been installed in this workspace.

### Click to launch (Linux)

Double-click **Abyss Downloader.desktop** in this project folder. Depending on your desktop/file manager, first right-click it and choose **Allow Launching** or enable **Allow executing file as program** in Properties. You can copy the launcher to your Desktop; it points to the app at `/home/kai/projects/abyss`. If you move the project, update the launcher's `Exec` path.

Alternatively, run `./run-app.sh` from a terminal. It uses the app's virtual environment automatically, so activating the environment is not necessary. File managers may offer **Run** for this script, or open it in an editor depending on their settings.

These are Linux launchers, not a Windows `.bat` file. Python dependencies must be installed before launching.

On Debian/Ubuntu, if Tkinter is missing, install `python3-tk` (and `python3-venv` if needed). If Chromium reports missing system libraries, run `.venv/bin/python -m playwright install-deps chromium` after reviewing its system-package changes. Java must be on `PATH`; the required Java version depends on your JAR.

The app defaults to the existing `abyss-dl.jar` and `vids` directory beside `app.py`. Both can be changed with Browse. The selected output folder must already exist and be writable.

## Workflow

In **Single URL** mode, choose how to supply the video ID:

- **Iframe XPath**: provide the webpage URL and iframe XPath; the app extracts the ID using Chromium.
- **Manual video ID**: enter just the ID (for example `2IkDMd-H81`) and the manual video title. The webpage URL stays editable but is optional and is not used for extraction. The iframe XPath is disabled and not required. This mode skips Chromium entirely and sends the ID directly to the downloader.

Both choices require a manual video title. Switching choices preserves your inputs. TXT mode always uses webpage URLs and XPath extraction. Manual IDs and titles are not saved as defaults.

1. Choose a **Link source**: **Single URL** lets you paste one complete HTTP(S) webpage URL without a TXT file; **TXT file** lets you browse to a UTF-8 file containing **one webpage URL per line**. Blank lines are ignored; duplicate links are preserved. Invalid inputs are reported before the queue starts. Only the selected source is used; switching sources keeps your input text.
2. Choose an output folder and the downloader JAR.
3. Enter the **iframe XPath** for your pages. In **TXT file** mode, also enter **Video title XPath (TXT)** to extract each title. In **Single URL** mode, that XPath field is disabled: you must enter **Video title (single URL)** manually instead. The title XPath is not evaluated in single mode, and its previous value is retained for TXT mode. Manual titles are per-run and are not saved as defaults. Numeric manual titles use episode filenames too (`3` → `E03.mp4`).
4. Click **Save settings** to remember both XPath expressions, the JAR path, and the output directory. Saved values are restored automatically next time. **XPath fields remain editable**: change them for a single run, or click Save settings again to replace your saved defaults. Saving does not require a TXT file and does not start a download.
5. Click **Start queue**. Each page is opened in headless Chromium, its ID/title extracted, and its download completed before the next page starts. Current field values are used, whether saved or not. Fields and Save settings are disabled only while a queue is running.
6. Use **Cancel** to stop the current process and skip all remaining items. Closing the window also requests cleanup.

Settings are stored locally at `~/.config/abyss-downloader/settings.json` (or `$XDG_CONFIG_HOME/abyss-downloader/settings.json` when an absolute XDG config directory is set). Invalid/unreadable saved settings show a notice and the app still opens with defaults. Unsaved edits are not automatically saved when closing the app.

Example TXT format (replace these with your actual pages):

```text
https://example.com/episode/1
https://example.com/episode/2
```

### XPath configuration

Examples only — use selectors matching your website:

| Field | Element XPath | Attribute/text XPath |
|---|---|---|
| Iframe | `//iframe[@id='player']` | `//iframe[@id='player']/@src` |
| Video title | `//h1[@class='video-title']` | `//h1[@class='video-title']/text()` |

Each XPath must yield one nonempty value. Multiple matches and invalid expressions are errors. Selectors run against the rendered main-page DOM, so JavaScript-created elements are supported. The app waits up to 20 seconds per value. It does not traverse into nested frames or shadow DOM, or perform player-button clicks. For lazy iframe attributes such as `data-src`, select that attribute explicitly.

For an iframe URL such as:

```text
https://api.anime3s.com/ApiOk.php?v=2IkDMd-H81&show=0
```

the video ID is `2IkDMd-H81`, taken from query parameter `v`. Relative iframe URLs are resolved against the document base URL. IDs support letters, digits, underscores, and hyphens (but cannot begin with a hyphen).

### Download behavior

The command is executed directly without a shell:

```text
java -jar /absolute/path/abyss-dl.jar 2IkDMd-H81 -o /output/.abyss-<temporary>/Video title.mp4
```

Downloads first go into a new private temporary subdirectory of your output folder. On success, the nonempty MP4 is atomically published to the final output path without replacing existing files. Temporary partial files are removed on ordinary failure/cancellation. A force-killed app or power loss may leave a `.abyss-*` folder that you can inspect/remove once no download is active.

- Numeric-only titles become episode filenames: `1` → `E01.mp4`, `2` → `E02.mp4`, `10` → `E10.mp4`, `100` → `E100.mp4`. Other titles keep their names, sanitized for safe filenames. Existing or repeated names get suffixes such as `E01 (2).mp4` or `Video title (2).mp4`.
- The existing JAR and videos are not changed or overwritten.
- A failed page/download is logged and the queue proceeds to the next item. There are no automatic retries or resume support.
- Linux cancellation terminates the Java process group, escalating after two seconds if necessary. A browser operation already in progress may take up to its timeout (typically 10 seconds) before stopping.
- Browser contexts are isolated per page. Login cookies are not imported. Sites requiring login, CAPTCHA completion, or access checks are not bypassed.
- Saved XPath/path settings persist between sessions. The selected TXT file, queue state, and logs are not saved.
- Use only a JAR you trust, URLs you trust, and videos you are authorized to download. The JAR runs with your user's permissions, not in a security sandbox.

## Tests

```bash
# Unit tests plus local Chromium integration tests:
.venv/bin/python -m unittest discover -s tests -v

# Also drive an actual Tk window (requires a working desktop display):
ABYSS_GUI_TEST=1 .venv/bin/python -m unittest discover -s tests -v
```

Tests use temporary directories, a local JavaScript fixture page, and a fake Java process. They do **not** execute the supplied JAR or download real videos. Browser tests skip if Playwright/Chromium cannot start; GUI tests are opt-in. An optional GUI-only screenshot requires Pillow and `ABYSS_GUI_SCREENSHOT=/absolute/path/screenshot.png`; Pillow is not needed by the app.

Real-site end-to-end verification requires your iframe/title XPath expressions and a usable webpage URL.
