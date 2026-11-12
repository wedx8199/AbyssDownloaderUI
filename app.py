"""Launch with: python app.py"""

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from abyss_app.downloader import DownloadWorker, Settings, validate_settings
from abyss_app.files import parse_links, validate_url
from abyss_app.extraction import validate_video_id
from abyss_app.preferences import load_preferences, preferences_path, save_preferences

ROOT = Path(__file__).resolve().parent


class Application:
    def __init__(self, root: tk.Tk, settings_path: Path | None = None):
        self.root = root
        self.settings_path = settings_path if settings_path is not None else preferences_path()
        root.title("Abyss Player Downloader")
        root.geometry("1100x720")
        root.minsize(760, 540)
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.worker_thread = None
        self.closing = False
        self.urls = []
        self.rows = []
        self.editable = []
        self.log_ended_with_cr = False
        self.txt = tk.StringVar()
        self.input_mode = tk.StringVar(value="txt")
        self.single_url = tk.StringVar()
        self.manual_title = tk.StringVar()
        self.id_mode = tk.StringVar(value="xpath")
        self.manual_id = tk.StringVar()
        self.running = False
        self.jar = tk.StringVar(value=str(ROOT / "abyss-dl.jar"))
        self.output = tk.StringVar(value=str(ROOT / "vids"))
        self.iframe = tk.StringVar()
        self.title = tk.StringVar()
        self.summary = tk.StringVar(value="Select a TXT file with one webpage URL per line.")
        self.preference_fields = {
            "iframe_xpath": self.iframe, "title_xpath": self.title,
            "jar": self.jar, "output": self.output,
        }
        self.settings_status = tk.StringVar(value="XPath fields are editable. Save settings to reuse them next time.")
        try:
            saved = load_preferences(self.settings_path)
            for key, value in saved.items():
                self.preference_fields[key].set(value)
            if saved:
                self.settings_status.set("Saved settings loaded. Edit XPath fields anytime; Save settings updates your defaults.")
        except (OSError, UnicodeError, ValueError) as exc:
            self.settings_status.set(f"Could not load saved settings; using defaults: {exc}")

        frame = ttk.Frame(root, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        source = ttk.Frame(frame)
        source.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
        ttk.Label(source, text="Link source:").pack(side="left", padx=(0, 12))
        for label, mode in [("TXT file", "txt"), ("Single URL", "single")]:
            radio = ttk.Radiobutton(source, text=label, value=mode,
                                    variable=self.input_mode, command=self.update_input_mode)
            radio.pack(side="left", padx=(0, 12))
            self.editable.append(radio)
        id_source = ttk.Frame(frame)
        id_source.grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 6))
        ttk.Label(id_source, text="Single URL video ID:").pack(side="left", padx=(0, 12))
        self.id_radios = []
        for label, mode in [("Iframe XPath", "xpath"), ("Manual video ID", "manual")]:
            radio = ttk.Radiobutton(id_source, text=label, value=mode,
                                    variable=self.id_mode, command=self.update_input_mode)
            radio.pack(side="left", padx=(0, 12))
            self.id_radios.append(radio)
            self.editable.append(radio)
        for row, (label, variable, action) in enumerate([
            ("Links TXT", self.txt, self.pick_txt),
            ("Single webpage URL", self.single_url, None),
            ("Manual video ID", self.manual_id, None),
            ("Downloader JAR", self.jar, self.pick_jar),
            ("Output directory", self.output, self.pick_output),
            ("Iframe XPath", self.iframe, None),
            ("Video title XPath (TXT)", self.title, None),
            ("Video title (single URL)", self.manual_title, None),
        ], start=2):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=4)
            entry = ttk.Entry(frame, textvariable=variable)
            entry.grid(row=row, column=1, sticky="ew", pady=4)
            self.editable.append(entry)
            if variable is self.txt:
                self.txt_entry = entry
            elif variable is self.single_url:
                self.url_entry = entry
            elif variable is self.manual_id:
                self.manual_id_entry = entry
            elif variable is self.iframe:
                self.iframe_entry = entry
            elif variable is self.title:
                self.title_xpath_entry = entry
            elif variable is self.manual_title:
                self.manual_title_entry = entry
            if action:
                button = ttk.Button(frame, text="Browse…", command=action)
                button.grid(row=row, column=2, padx=(8, 0))
                self.editable.append(button)
                if variable is self.txt:
                    self.txt_button = button
        ttk.Label(frame, text="XPath examples only: //iframe[@id='player']   and   //h1   (or append /@src and /text())",
                  wraplength=720).grid(row=10, column=0, columnspan=3, sticky="w", pady=(4, 10))
        controls = ttk.Frame(frame)
        controls.grid(row=11, column=0, columnspan=3, sticky="ew")
        self.start_button = ttk.Button(controls, text="Start queue", command=self.start)
        self.start_button.pack(side="left")
        self.cancel_button = ttk.Button(controls, text="Cancel", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="left", padx=8)
        self.save_button = ttk.Button(controls, text="Save settings", command=self.save_settings)
        self.save_button.pack(side="left", padx=(8, 0))
        self.editable.append(self.save_button)
        ttk.Label(controls, textvariable=self.settings_status, wraplength=590).pack(side="left", padx=12)
        ttk.Label(frame, textvariable=self.summary, wraplength=950).grid(row=12, column=0, columnspan=3, sticky="w", pady=10)

        table = ttk.Frame(frame)
        table.grid(row=13, column=0, columnspan=3, sticky="nsew")
        frame.rowconfigure(13, weight=3)
        self.tree = ttk.Treeview(table, columns=("url", "status", "title", "id", "detail"), show="headings")
        for col, label, width in [("url", "Webpage URL", 240), ("status", "Status", 100), ("title", "Video title", 180), ("id", "Video ID", 110), ("detail", "Output / error", 280)]:
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, minwidth=70)
        yscroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        ttk.Label(frame, text="Downloader log").grid(row=14, column=0, sticky="w", pady=(10, 4))
        self.log = ScrolledText(frame, height=9, state="disabled", wrap="word")
        self.log.grid(row=15, column=0, columnspan=3, sticky="nsew")
        frame.rowconfigure(15, weight=1)
        self.update_input_mode()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.poll)

    def update_input_mode(self):
        single = self.input_mode.get() == "single"
        manual = single and self.id_mode.get() == "manual"
        for radio in self.id_radios:
            radio.configure(state="normal" if single and not self.running else "disabled")
        self.manual_id_entry.configure(state="normal" if manual and not self.running else "disabled")
        self.iframe_entry.configure(state="disabled" if self.running or manual else "normal")
        self.txt_entry.configure(state="disabled" if self.running or single else "normal")
        self.txt_button.configure(state="disabled" if self.running or single else "normal")
        self.url_entry.configure(state="normal" if single and not self.running else "disabled")
        self.title_xpath_entry.configure(state="disabled" if self.running or single else "normal")
        self.manual_title_entry.configure(state="normal" if single and not self.running else "disabled")
        if not self.running:
            if manual:
                self.summary.set("Enter the video ID and title. A webpage URL and XPath are not needed.")
            else:
                self.summary.set("Paste one webpage URL and enter its video title, then click Start queue." if single
                                 else "Select a TXT file with one webpage URL per line.")

    def save_settings(self):
        # Save current drafts without requiring valid selectors, Java, or a link list.
        # Queue startup still validates everything before using these values.
        try:
            save_preferences(self.settings_path, {
                key: variable.get() for key, variable in self.preference_fields.items()
            })
        except (OSError, UnicodeError, ValueError) as exc:
            messagebox.showerror("Cannot save settings", str(exc))
            return
        self.settings_status.set("Settings saved. You can edit the XPath fields and save new defaults anytime.")

    def pick_txt(self):
        path = filedialog.askopenfilename(filetypes=[("Text files", "*.txt"), ("All files", "*")])
        if path:
            self.txt.set(path)
            try:
                self.load_links()
            except (OSError, UnicodeError, ValueError) as exc:
                messagebox.showerror("Invalid link list", str(exc))

    def pick_jar(self):
        path = filedialog.askopenfilename(filetypes=[("Java archives", "*.jar"), ("All files", "*")])
        if path:
            self.jar.set(path)

    def pick_output(self):
        path = filedialog.askdirectory()
        if path:
            self.output.set(path)

    def load_links(self):
        if self.input_mode.get() == "single":
            if self.id_mode.get() == "manual":
                urls = ["Video ID: " + validate_video_id(self.manual_id.get())]
            else:
                urls = [validate_url(self.single_url.get())]
        else:
            urls = parse_links(Path(self.txt.get()).expanduser())
        self.urls = urls
        self.tree.delete(*self.tree.get_children())
        self.rows = [self.tree.insert("", "end", values=(url, "Pending", "", "", "")) for url in urls]
        self.summary.set(f"{len(urls)} links loaded in file order.")

    def start(self):
        if self.worker_thread and self.worker_thread.is_alive():
            return
        try:
            settings = validate_settings(Settings(
                Path(self.jar.get()), Path(self.output.get()), self.iframe.get(), self.title.get(),
                manual_title=self.manual_title.get() if self.input_mode.get() == "single" else None,
                manual_video_id=self.manual_id.get() if self.input_mode.get() == "single" and self.id_mode.get() == "manual" else None,
            ))
            self.load_links()
        except (OSError, UnicodeError, ValueError) as exc:
            messagebox.showerror("Cannot start", str(exc))
            return
        self.stop.clear()
        self.set_running(True)
        self.append_log("\nStarting sequential queue. Temporary partial files are removed on failure/cancel.\n")
        worker = DownloadWorker(settings, self.urls.copy(), self.events, self.stop)
        self.worker_thread = threading.Thread(target=worker.run, daemon=False)
        self.worker_thread.start()

    def set_running(self, running):
        self.running = running
        for widget in [*self.editable, self.start_button]:
            widget.configure(state="disabled" if running else "normal")
        self.cancel_button.configure(state="normal" if running else "disabled")
        self.update_input_mode()

    def cancel(self):
        self.stop.set()
        self.cancel_button.configure(state="disabled")
        self.summary.set("Cancelling… waiting for browser/process cleanup.")

    def append_log(self, text):
        if not text:
            return
        # Progress output uses carriage returns to redraw terminal lines. Show
        # these as separate log lines, without doubling CRLF at chunk boundaries.
        ended_with_cr = text.endswith("\r")
        if self.log_ended_with_cr and text.startswith("\n"):
            text = text[1:]
        self.log_ended_with_cr = ended_with_cr
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        self.log.configure(state="normal")
        self.log.insert("end", text)
        # Bound retained text, including output with no newline characters.
        size = int(self.log.count("1.0", "end", "chars")[0])
        if size > 100000:
            self.log.delete("1.0", f"1.0+{size - 100000}c")
        self.log.see("end")
        self.log.configure(state="disabled")

    def poll(self):
        for _ in range(200):
            try:
                kind, values = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "item":
                row = self.rows[values["index"]]
                for key in ("status", "title", "detail"):
                    if key in values:
                        self.tree.set(row, key, values[key])
                if "video_id" in values:
                    self.tree.set(row, "id", values["video_id"])
            elif kind == "log":
                self.append_log(values["text"])
            elif kind == "error":
                self.append_log("\nQueue error: " + values["text"] + "\n")
                if not self.closing:
                    messagebox.showerror("Queue error", values["text"])
            elif kind == "done":
                self.set_running(False)
                statuses = [self.tree.set(row, "status") for row in self.rows]
                self.summary.set(f"Finished: {statuses.count('Completed')} completed, {statuses.count('Failed')} failed, {statuses.count('Cancelled')} cancelled.")
        if self.closing and not (self.worker_thread and self.worker_thread.is_alive()):
            self.root.destroy()
            return
        self.root.after(100, self.poll)

    def close(self):
        self.closing = True
        if self.worker_thread and self.worker_thread.is_alive():
            self.cancel()
            self.set_running(True)
            self.cancel_button.configure(state="disabled")
        else:
            self.root.destroy()


def main():
    root = tk.Tk()
    Application(root)
    root.mainloop()


if __name__ == "__main__":
    main()
