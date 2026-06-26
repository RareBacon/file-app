"""
FileSage — PyQt6 version
Run: python app_qt.py
Requires: pip install PyQt6
"""
import sys
import threading

from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QSize, QPoint
)
from PyQt6.QtGui import (
    QColor, QFont, QPainter, QFontDatabase, QKeySequence, QCursor
)
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QLabel, QPushButton, QListWidget, QListWidgetItem,
    QStyledItemDelegate, QStyleOptionViewItem, QAbstractItemView,
    QCheckBox, QScrollArea, QFrame, QSizePolicy, QStyle
)

import backend

# ── color palette (matches JSX Terminal skin) ──────────────────────────────
BG        = "#0a0a0a"
BG_TITLE  = "#171717"
BG_SEL    = "#262626"
FG        = "#e5e5e5"
FG_DIM    = "#525252"
FG_MUTED  = "#737373"
ORANGE    = "#fb923c"
BORDER    = "#262626"

TAG_COLORS = {
    "docx": "#60a5fa", "doc": "#60a5fa",
    "pdf":  "#f87171",
    "xlsx": "#34d399", "xls": "#34d399", "csv": "#34d399",
    "py":   "#a78bfa",
    "js":   "#fbbf24", "ts":  "#93c5fd",
    "txt":  "#737373", "md":  "#a3a3a3",
}
DEFAULT_TAG_COLOR = "#737373"

CHIP_FILTER = {
    "all":   None,
    "doc":   ["docx", "doc"],
    "pdf":   ["pdf"],
    "sheet": ["xlsx", "xls", "csv"],
    "code":  ["py", "js", "ts", "json", "html", "css"],
    "txt":   ["txt", "md"],
}


def ext(name):
    parts = name.rsplit(".", 1)
    return parts[1].lower() if len(parts) > 1 else ""


def tag_color(name):
    return TAG_COLORS.get(ext(name), DEFAULT_TAG_COLOR)


def tag_label(name):
    e = ext(name)
    labels = {"docx": "doc", "doc": "doc", "xlsx": "xls", "xls": "xls", "csv": "xls"}
    return labels.get(e, e) if e else "file"


# ── background search thread ───────────────────────────────────────────────
class SearchWorker(QThread):
    results_ready = pyqtSignal(list)

    def __init__(self, query):
        super().__init__()
        self.query = query

    def run(self):
        results = backend.search(self.query)
        self.results_ready.emit(results)


# ── custom delegate for result rows ───────────────────────────────────────
class ResultDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._mono = QFont("JetBrains Mono")
        if not QFontDatabase.families().__contains__("JetBrains Mono"):
            self._mono = QFont("Consolas")
        self._mono.setPointSize(10)

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 36)

    def paint(self, painter, option, index):
        painter.save()
        data = index.data(Qt.ItemDataRole.UserRole)
        if not data:
            painter.restore()
            return

        is_sel = bool(option.state & QStyle.StateFlag.State_Selected)
        bg = QColor(BG_SEL if is_sel else BG)
        painter.fillRect(option.rect, bg)

        x = option.rect.x() + 8
        y = option.rect.y()
        h = option.rect.height()
        painter.setFont(self._mono)

        # Arrow
        arrow_color = QColor(ORANGE)
        painter.setPen(arrow_color)
        arrow = ">" if is_sel else " "
        painter.drawText(x, y, 14, h, Qt.AlignmentFlag.AlignVCenter, arrow)
        x += 16

        # Tag
        tc = QColor(tag_color(data["name"]))
        painter.setPen(tc)
        tag_text = f"[{tag_label(data['name'])}]"
        tag_w = painter.fontMetrics().horizontalAdvance(tag_text) + 2
        painter.drawText(x, y, tag_w, h, Qt.AlignmentFlag.AlignVCenter, tag_text)
        x += tag_w + 6

        # Filename
        painter.setPen(QColor(FG))
        max_name_w = option.rect.width() - x - 20
        fm = painter.fontMetrics()
        name_text = fm.elidedText(data["name"], Qt.TextElideMode.ElideRight, max_name_w - 60)
        painter.drawText(x, y, max_name_w - 60, h, Qt.AlignmentFlag.AlignVCenter, name_text)
        name_w = fm.horizontalAdvance(name_text)

        # Content match marker
        if data.get("match_type") == "content":
            cx = x + name_w + 6
            painter.setPen(QColor(FG_DIM))
            painter.drawText(cx, y, 24, h, Qt.AlignmentFlag.AlignVCenter, "[~]")

        painter.restore()


# ── main window ─────────────────────────────────────────────────────────────
class FileSageWindow(QWidget):
    # Emitted from the indexer's background thread; the connected slot runs on
    # the GUI thread so it's safe to touch widgets there.
    index_done = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("filesage")
        self.setMinimumSize(480, 400)
        self.resize(680, 520)
        self._results = []
        self._active_chip = "all"
        self._search_worker = None
        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._run_search)
        self._showing_settings = False
        self._auto_index_attempted = False
        self.index_done.connect(self._on_index_done)

        self._apply_palette()
        self._build_ui()
        self._load_status()
        self._load_recent()

    def _apply_palette(self):
        self.setStyleSheet(f"""
            QWidget {{
                background: {BG};
                color: {FG};
                font-family: 'JetBrains Mono', Consolas, monospace;
                font-size: 12px;
            }}
            QLineEdit {{
                background: transparent;
                border: none;
                color: {FG};
                selection-background-color: {BG_SEL};
                font-size: 13px;
            }}
            QListWidget {{
                background: {BG};
                border: none;
                outline: none;
            }}
            QListWidget::item {{
                border: none;
            }}
            QListWidget::item:selected {{
                background: {BG_SEL};
            }}
            QScrollBar:vertical {{
                background: {BG};
                width: 4px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: #404040;
                border-radius: 2px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QPushButton {{
                background: transparent;
                border: 1px solid {BORDER};
                border-radius: 4px;
                color: {FG_MUTED};
                padding: 2px 8px;
                font-size: 11px;
            }}
            QPushButton:hover {{ color: {FG}; }}
            QPushButton[active=true] {{
                border-color: {ORANGE};
                color: {ORANGE};
            }}
            QCheckBox {{ color: {FG_MUTED}; spacing: 6px; font-size: 11px; }}
            QCheckBox::indicator {{
                width: 12px; height: 12px;
                border: 1px solid {BORDER};
                border-radius: 2px;
                background: {BG};
            }}
            QCheckBox::indicator:checked {{ background: {ORANGE}; border-color: {ORANGE}; }}
            QFrame[frameShape="4"] {{ color: {BORDER}; }}
        """)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Title bar
        self._title_bar = self._make_title_bar()
        root.addWidget(self._title_bar)

        # Main stack: search panel + settings panel
        self._main_panel = self._make_main_panel()
        self._settings_panel = self._make_settings_panel()
        self._settings_panel.hide()

        root.addWidget(self._main_panel, 1)
        root.addWidget(self._settings_panel, 1)

    def _make_title_bar(self):
        bar = QWidget()
        bar.setFixedHeight(36)
        bar.setStyleSheet(f"background: {BG_TITLE}; border-bottom: 1px solid {BORDER};")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(6)

        for color in ("#ef4444", "#eab308", "#22c55e"):
            dot = QLabel()
            dot.setFixedSize(12, 12)
            dot.setStyleSheet(f"background: {color}; border-radius: 6px;")
            lay.addWidget(dot)

        lay.addSpacing(8)
        title = QLabel("seth's sage — filesage")
        title.setStyleSheet(f"color: {FG_DIM}; font-size: 11px;")
        lay.addWidget(title)
        lay.addStretch()

        self._settings_btn = QPushButton("⚙")
        self._settings_btn.setFixedSize(24, 24)
        self._settings_btn.setStyleSheet(
            f"border: none; color: {FG_DIM}; font-size: 14px; padding: 0;"
            f"background: transparent;"
        )
        self._settings_btn.clicked.connect(self._toggle_settings)
        lay.addWidget(self._settings_btn)
        return bar

    def _make_main_panel(self):
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(0)

        # Prompt + input
        prompt_row = QHBoxLayout()
        prompt_row.setSpacing(6)
        for text, color in [("user@pc", ORANGE), ("~", FG_DIM), ("$", FG_MUTED)]:
            lbl = QLabel(text)
            lbl.setStyleSheet(f"color: {color}; font-size: 13px;")
            prompt_row.addWidget(lbl)

        self._input = QLineEdit()
        self._input.setPlaceholderText("search...")
        self._input.textChanged.connect(self._on_text_changed)
        self._input.installEventFilter(self)
        prompt_row.addWidget(self._input, 1)

        self._reindex_btn = QPushButton("↺")
        self._reindex_btn.setFixedSize(24, 24)
        self._reindex_btn.setStyleSheet(
            f"border: none; color: {FG_DIM}; font-size: 16px; padding: 0; background: transparent;"
        )
        self._reindex_btn.clicked.connect(self._do_reindex)
        prompt_row.addWidget(self._reindex_btn)
        lay.addLayout(prompt_row)
        lay.addSpacing(10)

        # Filter chips
        chips_row = QHBoxLayout()
        chips_row.setSpacing(4)
        chips_row.setContentsMargins(0, 0, 0, 0)
        self._chips = {}
        for chip_id, label in [("all","all"),("doc","doc"),("pdf","pdf"),("sheet","sheet"),("code","code"),("txt","text")]:
            btn = QPushButton(label)
            btn.setProperty("active", chip_id == "all")
            btn.clicked.connect(lambda checked, cid=chip_id: self._set_chip(cid))
            chips_row.addWidget(btn)
            self._chips[chip_id] = btn
        chips_row.addStretch()
        lay.addLayout(chips_row)
        lay.addSpacing(8)

        # Status
        self._status_lbl = QLabel("no index — click ↺ to index")
        self._status_lbl.setStyleSheet(f"color: {FG_DIM}; font-size: 11px;")
        lay.addWidget(self._status_lbl)
        lay.addSpacing(4)

        # Results / recent list
        self._list = QListWidget()
        self._list.setItemDelegate(ResultDelegate(self._list))
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._list.itemActivated.connect(self._open_selected)
        lay.addWidget(self._list, 1)

        self._first_run = False
        return panel

    def _make_settings_panel(self):
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)

        # Back button + heading
        top_row = QHBoxLayout()
        back_btn = QPushButton("←")
        back_btn.setFixedSize(24, 24)
        back_btn.setStyleSheet(f"border: none; color: {FG_DIM}; font-size: 14px; background: transparent;")
        back_btn.clicked.connect(self._toggle_settings)
        top_row.addWidget(back_btn)
        heading = QLabel("# settings")
        heading.setStyleSheet(f"color: {FG}; font-size: 13px;")
        top_row.addWidget(heading)
        top_row.addStretch()
        lay.addLayout(top_row)

        # Folders section
        folders_lbl = QLabel("# indexed folders")
        folders_lbl.setStyleSheet(f"color: {FG_DIM}; font-size: 11px; margin-top: 8px;")
        lay.addWidget(folders_lbl)

        self._folders_layout = QVBoxLayout()
        self._folders_layout.setSpacing(2)
        lay.addLayout(self._folders_layout)
        self._folders = [
            "C:\\Users\\Seth\\Documents",
            "C:\\Users\\Seth\\Desktop",
            "C:\\Users\\Seth\\Downloads",
        ]
        self._refresh_folders_ui()

        # Add folder row
        add_row = QHBoxLayout()
        plus = QLabel("+")
        plus.setStyleSheet(f"color: {FG_DIM};")
        add_row.addWidget(plus)
        self._folder_input = QLineEdit()
        self._folder_input.setPlaceholderText("add folder path...")
        self._folder_input.setStyleSheet(
            f"background: transparent; border: none; border-bottom: 1px solid {BORDER};"
            f"color: {FG}; font-size: 11px; padding: 2px 0;"
        )
        self._folder_input.returnPressed.connect(self._add_folder)
        add_row.addWidget(self._folder_input, 1)
        add_btn = QPushButton("+")
        add_btn.setFixedSize(20, 20)
        add_btn.setStyleSheet(f"border: none; color: {ORANGE}; font-size: 14px; background: transparent;")
        add_btn.clicked.connect(self._add_folder)
        add_row.addWidget(add_btn)
        lay.addLayout(add_row)

        # File types
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {BORDER};")
        lay.addWidget(sep)

        types_lbl = QLabel("# file types to index")
        types_lbl.setStyleSheet(f"color: {FG_DIM}; font-size: 11px;")
        lay.addWidget(types_lbl)

        self._type_checks = {}
        for key, label in [("docs","Documents"),("pdfs","PDFs"),("sheets","Spreadsheets"),("code","Code files"),("images","Images")]:
            cb = QCheckBox(label)
            cb.setChecked(key != "images")
            self._type_checks[key] = cb
            lay.addWidget(cb)

        # Hotkey
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {BORDER};")
        lay.addWidget(sep2)

        hotkey_lbl = QLabel("# global hotkey")
        hotkey_lbl.setStyleSheet(f"color: {FG_DIM}; font-size: 11px;")
        lay.addWidget(hotkey_lbl)

        hk_row = QHBoxLayout()
        hk_row.addWidget(QLabel("open search window"))
        hk_badge = QLabel("Alt + Space")
        hk_badge.setStyleSheet(
            f"color: {ORANGE}; border: 1px solid {BORDER}; border-radius: 3px;"
            f"padding: 2px 8px; font-size: 11px;"
        )
        hk_row.addWidget(hk_badge)
        hk_row.addStretch()
        lay.addLayout(hk_row)

        lay.addStretch()
        return panel

    def _refresh_folders_ui(self):
        # Clear and rebuild folder list widgets
        while self._folders_layout.count():
            item = self._folders_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, folder in enumerate(self._folders):
            row = QHBoxLayout()
            lbl = QLabel(folder)
            lbl.setStyleSheet(f"color: {FG}; font-size: 11px;")
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            row.addWidget(lbl, 1)
            rm = QPushButton("✕")
            rm.setFixedSize(16, 16)
            rm.setStyleSheet(f"border: none; color: {FG_DIM}; font-size: 10px; background: transparent;")
            rm.clicked.connect(lambda checked, idx=i: self._remove_folder(idx))
            row.addWidget(rm)
            w = QWidget()
            w.setLayout(row)
            self._folders_layout.addWidget(w)

    def _add_folder(self):
        v = self._folder_input.text().strip()
        if v:
            self._folders.append(v)
            self._folder_input.clear()
            self._refresh_folders_ui()

    def _remove_folder(self, idx):
        if 0 <= idx < len(self._folders):
            self._folders.pop(idx)
            self._refresh_folders_ui()

    # ── search ──────────────────────────────────────────────────────────────
    def _on_text_changed(self, text):
        self._debounce.stop()
        if not text.strip():
            self._results = []
            self._refresh_list()
            return
        self._debounce.start(150)

    def _run_search(self):
        query = self._input.text().strip()
        if not query:
            return
        if self._search_worker and self._search_worker.isRunning():
            self._search_worker.quit()
        self._search_worker = SearchWorker(query)
        self._search_worker.results_ready.connect(self._on_results)
        self._search_worker.start()

    def _on_results(self, results):
        self._results = results
        self._refresh_list()

    def _set_chip(self, chip_id):
        self._active_chip = chip_id
        for cid, btn in self._chips.items():
            btn.setProperty("active", cid == chip_id)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self._refresh_list()

    def _visible_results(self):
        exts = CHIP_FILTER.get(self._active_chip)
        if exts is None:
            return self._results
        return [r for r in self._results if ext(r["name"]) in exts]

    def _refresh_list(self):
        self._list.clear()
        query = self._input.text().strip()
        if query:
            visible = self._visible_results()
            self._status_lbl.setText(f"# {len(visible)} match{'es' if len(visible) != 1 else ''}")
            for r in visible:
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, r)
                self._list.addItem(item)
            if self._list.count() > 0:
                self._list.setCurrentRow(0)
        else:
            self._status_lbl.setText(
                f"indexed {self._status_count:,} files · {self._status_ago}"
                if hasattr(self, "_status_count") else "no index — click ↺ to index"
            )
            recent = backend.get_recent()
            self._add_recent_section("# recently opened", recent.get("opened", []))
            self._add_recent_section("# recently modified", recent.get("modified", []))

    def _add_recent_section(self, header, files):
        header_item = QListWidgetItem(header)
        header_item.setForeground(QColor(FG_DIM))
        header_item.setFlags(Qt.ItemFlag.NoItemFlags)
        self._list.addItem(header_item)
        for f in files:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, f)
            self._list.addItem(item)

    def _load_recent(self):
        self._refresh_list()

    def _load_status(self):
        status = backend.get_status()
        self._status_count = status.get("count", 0)
        self._status_ago = status.get("last_indexed_ago", "never")
        if self._status_count == 0 and not status.get("indexing") and not self._auto_index_attempted:
            self._auto_index_attempted = True
            self._first_run = True
            self._do_reindex()
        elif not self._input.text().strip():
            self._refresh_list()

    def _do_reindex(self):
        msg = (
            "indexing your files for the first time — this may take a few minutes"
            if self._first_run else "indexing..."
        )
        self._status_lbl.setText(msg)
        self._reindex_btn.setEnabled(False)
        # on_done fires on the indexer's background thread, so just emit a
        # signal — the actual widget updates happen in _on_index_done on the
        # GUI thread.
        backend.reindex(on_done=self.index_done.emit)

    def _on_index_done(self):
        self._first_run = False
        self._reindex_btn.setEnabled(True)
        self._load_status()

    def _toggle_settings(self):
        self._showing_settings = not self._showing_settings
        self._main_panel.setVisible(not self._showing_settings)
        self._settings_panel.setVisible(self._showing_settings)
        self._settings_btn.setStyleSheet(
            f"border: none; color: {ORANGE if self._showing_settings else FG_DIM}; "
            f"font-size: 14px; padding: 0; background: transparent;"
        )

    def _open_selected(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        if data and isinstance(data, dict):
            backend.open_file(data["path"])

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if obj is self._input and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Down:
                cur = self._list.currentRow()
                self._list.setCurrentRow(min(cur + 1, self._list.count() - 1))
                return True
            elif key == Qt.Key.Key_Up:
                cur = self._list.currentRow()
                self._list.setCurrentRow(max(cur - 1, 0))
                return True
            elif key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
                item = self._list.currentItem()
                if item:
                    self._open_selected(item)
                return True
        return super().eventFilter(obj, event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("FileSage")
    win = FileSageWindow()
    win.show()
    sys.exit(app.exec())
