"""
FileSage — pywebview version
Run: python app_webview.py
Requires: pip install pywebview
"""
import os
import sys
from pathlib import Path

import backend


class Api:
    """Exposed to JavaScript via window.pywebview.api.*"""

    def search(self, query):
        return backend.search(query)

    def open_file(self, path):
        backend.open_file(path)
        return {"ok": True}

    def get_recent(self):
        return backend.get_recent()

    def get_status(self):
        return backend.get_status()

    def reindex(self):
        backend.reindex()
        return {"ok": True}


if __name__ == "__main__":
    try:
        import webview
    except ImportError:
        print("pywebview not installed. Run: pip install pywebview")
        sys.exit(1)

    html_path = Path(__file__).parent / "ui" / "index.html"
    if not html_path.exists():
        print(f"UI file not found: {html_path}")
        sys.exit(1)

    api = Api()
    window = webview.create_window(
        title="filesage",
        url=str(html_path),
        js_api=api,
        width=680,
        height=540,
        min_size=(480, 400),
        frameless=False,
        easy_drag=False,
    )
    webview.start(debug=False)
