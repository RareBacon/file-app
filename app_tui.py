"""
FileSage — Textual TUI version
Run: python app_tui.py
Requires: pip install textual
"""
import asyncio
from textual.app import App, ComposeResult
from textual.widgets import Input, ListView, ListItem, Label, Button, Header, Footer, Static
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.screen import Screen
from textual.reactive import reactive
from textual.binding import Binding
from textual import work

import backend

# ── tag helpers ────────────────────────────────────────────────────────────
TAG_MARKUP = {
    "docx": "[bold #60a5fa][doc][/]", "doc": "[bold #60a5fa][doc][/]",
    "pdf":  "[bold #f87171][pdf][/]",
    "xlsx": "[bold #34d399][xls][/]", "xls": "[bold #34d399][xls][/]",
    "csv":  "[bold #34d399][csv][/]",
    "py":   "[bold #a78bfa][py][/]",
    "js":   "[bold #fbbf24][js][/]",  "ts":  "[bold #93c5fd][ts][/]",
    "txt":  "[bold #737373][txt][/]", "md":  "[bold #a3a3a3][md][/]",
}
DEFAULT_TAG = "[bold #525252][file][/]"

CHIP_FILTER = {
    "all":   None,
    "doc":   ["docx", "doc"],
    "pdf":   ["pdf"],
    "sheet": ["xlsx", "xls", "csv"],
    "code":  ["py", "js", "ts", "json", "html", "css"],
    "txt":   ["txt", "md"],
}


def get_ext(name):
    parts = name.rsplit(".", 1)
    return parts[1].lower() if len(parts) > 1 else ""


def file_markup(name, path, match_type="filename", query=""):
    tag = TAG_MARKUP.get(get_ext(name), DEFAULT_TAG)
    # Highlight query match in filename
    if query:
        i = name.lower().find(query.lower())
        if i >= 0:
            before = name[:i]
            match = name[i:i+len(query)]
            after = name[i+len(query):]
            name_part = f"{before}[bold #fb923c]{match}[/]{after}"
        else:
            name_part = name
    else:
        name_part = name

    content_marker = " [dim #525252][~][/]" if match_type == "content" else ""
    path_part = f"[dim #525252]{path}[/]"
    return f"{tag} {name_part}{content_marker}  {path_part}"


# ── settings screen ────────────────────────────────────────────────────────
class SettingsScreen(Screen):
    BINDINGS = [Binding("escape", "dismiss", "back")]

    DEFAULT_CSS = """
    SettingsScreen {
        background: #0a0a0a;
    }
    #settings-container {
        padding: 1 2;
    }
    .section-label {
        color: #525252;
        margin-top: 1;
        margin-bottom: 0;
    }
    .folder-item {
        color: #e5e5e5;
        height: 1;
    }
    #folder-input {
        background: #0a0a0a;
        border: none;
        border-bottom: tall #262626;
        color: #e5e5e5;
        height: 3;
        margin-top: 0;
    }
    #folder-input:focus {
        border-bottom: tall #fb923c;
    }
    .type-label {
        color: #a3a3a3;
        height: 1;
    }
    #hotkey-badge {
        color: #fb923c;
        border: round #262626;
        padding: 0 1;
    }
    """

    FOLDERS = [
        "C:\\Users\\Seth\\Documents",
        "C:\\Users\\Seth\\Desktop",
        "C:\\Users\\Seth\\Downloads",
    ]

    def compose(self) -> ComposeResult:
        yield Static("← [bold #e5e5e5]# settings[/]  [dim](esc to go back)[/]", id="settings-title")
        with ScrollableContainer(id="settings-container"):
            yield Static("[dim]# indexed folders[/]", classes="section-label")
            for f in self.FOLDERS:
                yield Static(f"  {f}", classes="folder-item")
            yield Input(placeholder="add folder path...", id="folder-input")
            yield Static(" ")
            yield Static("[dim]# file types to index[/]", classes="section-label")
            for label in ["✓ Documents", "✓ PDFs", "✓ Spreadsheets", "✓ Code files", "  Images"]:
                yield Static(f"  {label}", classes="type-label")
            yield Static(" ")
            yield Static("[dim]# global hotkey[/]", classes="section-label")
            with Horizontal():
                yield Static("  open search window   ")
                yield Static("Alt + Space", id="hotkey-badge")

    def action_dismiss(self):
        self.app.pop_screen()


# ── main app ───────────────────────────────────────────────────────────────
class FileSageApp(App):
    TITLE = "seth's sage — filesage"
    CSS = """
    FileSageApp {
        background: #0a0a0a;
    }
    /* Title bar */
    #titlebar {
        height: 1;
        background: #171717;
        border-bottom: tall #262626;
        padding: 0 2;
    }
    #titlebar-text {
        color: #525252;
        width: 1fr;
    }
    #settings-btn {
        background: transparent;
        border: none;
        color: #525252;
        min-width: 3;
        height: 1;
        padding: 0;
    }
    #settings-btn:hover { color: #fb923c; }

    /* Prompt row */
    #prompt-row {
        height: 1;
        padding: 0 2;
        margin-top: 1;
    }
    #prompt-user { color: #fb923c; }
    #prompt-tilde { color: #525252; }
    #prompt-dollar { color: #737373; }
    #search-input {
        background: #0a0a0a;
        border: none;
        color: #e5e5e5;
        height: 1;
        padding: 0;
        width: 1fr;
    }
    #search-input:focus { border: none; }
    #reindex-btn {
        background: transparent;
        border: none;
        color: #525252;
        min-width: 3;
        height: 1;
        padding: 0;
    }
    #reindex-btn:hover { color: #fb923c; }

    /* Filter chips */
    #chips-row {
        height: 3;
        padding: 0 2;
    }
    .chip {
        background: transparent;
        border: tall #262626;
        color: #737373;
        min-width: 6;
        height: 3;
        margin-right: 1;
    }
    .chip:hover { color: #e5e5e5; }
    .chip.active {
        border: tall #f97316;
        color: #fb923c;
    }

    /* Status */
    #status-bar {
        height: 1;
        padding: 0 2;
        color: #525252;
    }

    /* Results */
    #results-container {
        padding: 0 1;
    }
    .result-item {
        height: 1;
        background: transparent;
        padding: 0 1;
    }
    .result-item:hover { background: #1a1a1a; }
    ListView > ListItem.--highlight {
        background: #262626;
    }
    ListView {
        background: #0a0a0a;
        border: none;
        scrollbar-gutter: stable;
    }
    ListView:focus { border: none; }

    /* Section headers */
    .section-header {
        color: #525252;
        height: 1;
        padding: 0 1;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+r", "reindex", "reindex"),
        Binding("ctrl+comma", "settings", "settings"),
        Binding("escape", "clear_or_quit", "clear/quit"),
    ]

    active_chip: reactive[str] = reactive("all")
    status_text: reactive[str] = reactive("no index — click ↺ to index")

    def compose(self) -> ComposeResult:
        # Title bar
        with Horizontal(id="titlebar"):
            yield Static("● ● ●  seth's sage — filesage", id="titlebar-text")
            yield Button("⚙", id="settings-btn")

        # Search prompt
        with Horizontal(id="prompt-row"):
            yield Static("user@pc", id="prompt-user")
            yield Static(" ~ ", id="prompt-tilde")
            yield Static("$ ", id="prompt-dollar")
            yield Input(placeholder="search...", id="search-input")
            yield Button("↺", id="reindex-btn")

        # Filter chips
        with Horizontal(id="chips-row"):
            for chip_id, label in [("all","all"),("doc","doc"),("pdf","pdf"),("sheet","sheet"),("code","code"),("txt","text")]:
                btn = Button(label, id=f"chip-{chip_id}", classes=f"chip {'active' if chip_id == 'all' else ''}")
                yield btn

        # Status
        yield Static(self.status_text, id="status-bar")

        # Results / recent list
        yield ListView(id="results-list")

    def on_mount(self) -> None:
        self.query_one("#search-input", Input).focus()
        self._load_status()
        self._show_recent()

    def _load_status(self):
        status = backend.get_status()
        if status["count"] > 0:
            self.status_text = f"indexed {status['count']:,} files · {status['last_indexed_ago']}"
        else:
            self.status_text = "no index — click ↺ to index"
        self.query_one("#status-bar", Static).update(self.status_text)

    def _show_recent(self):
        lv = self.query_one("#results-list", ListView)
        lv.clear()
        recent = backend.get_recent()
        lv.append(ListItem(Static("[dim]# recently opened[/]", classes="section-header")))
        for f in recent.get("opened", []) or [{"name": "—", "path": ""}]:
            markup = file_markup(f["name"], f["path"]) if f.get("path") else "[dim]—[/]"
            item = ListItem(Static(markup, classes="result-item"))
            item.path = f.get("path", "")
            lv.append(item)
        lv.append(ListItem(Static("[dim]# recently modified[/]", classes="section-header")))
        for f in recent.get("modified", []) or [{"name": "—", "path": ""}]:
            markup = file_markup(f["name"], f["path"]) if f.get("path") else "[dim]—[/]"
            item = ListItem(Static(markup, classes="result-item"))
            item.path = f.get("path", "")
            lv.append(item)

    def watch_status_text(self, new_text: str) -> None:
        try:
            self.query_one("#status-bar", Static).update(new_text)
        except Exception:
            pass

    @work(exclusive=True, thread=True)
    def _do_search(self, query: str) -> None:
        results = backend.search(query)
        self.call_from_thread(self._update_results, results, query)

    def _update_results(self, results: list, query: str) -> None:
        chip_exts = CHIP_FILTER.get(self.active_chip)
        if chip_exts:
            results = [r for r in results if get_ext(r["name"]) in chip_exts]

        lv = self.query_one("#results-list", ListView)
        lv.clear()

        count = len(results)
        self.query_one("#status-bar", Static).update(
            f"# {count} match{'es' if count != 1 else ''}"
        )

        for r in results:
            markup = file_markup(r["name"], r["path"], r.get("match_type", "filename"), query)
            item = ListItem(Static(markup, classes="result-item"))
            item.path = r["path"]
            lv.append(item)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "search-input":
            return
        query = event.value.strip()
        if not query:
            self._load_status()
            self._show_recent()
            return
        self._do_search(query)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "reindex-btn":
            self.action_reindex()
        elif btn_id == "settings-btn":
            self.action_settings()
        elif btn_id and btn_id.startswith("chip-"):
            chip_id = btn_id[5:]
            self._set_chip(chip_id)

    def _set_chip(self, chip_id: str) -> None:
        self.active_chip = chip_id
        for cid in CHIP_FILTER:
            try:
                btn = self.query_one(f"#chip-{cid}", Button)
                btn.remove_class("active")
                if cid == chip_id:
                    btn.add_class("active")
            except Exception:
                pass
        # Re-run search with new filter
        query = self.query_one("#search-input", Input).value.strip()
        if query:
            self._do_search(query)
        else:
            self._show_recent()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        path = getattr(event.item, "path", None)
        if path:
            backend.open_file(path)

    def action_reindex(self) -> None:
        self.query_one("#status-bar", Static).update("indexing...")

        def on_done():
            self.call_from_thread(self._load_status)

        backend.reindex(on_done=on_done)

    def action_settings(self) -> None:
        self.push_screen(SettingsScreen())

    def action_clear_or_quit(self) -> None:
        inp = self.query_one("#search-input", Input)
        if inp.value:
            inp.clear()
        else:
            self.exit()


if __name__ == "__main__":
    app = FileSageApp()
    app.run()
