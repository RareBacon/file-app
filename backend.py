import sqlite3
import threading
import time
from pathlib import Path

import indexer

DB_PATH = indexer.DB_PATH

_indexing = False
_index_lock = threading.Lock()


def _ensure_recent_opens_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS recent_opens (
            path TEXT,
            name TEXT,
            opened_at REAL,
            PRIMARY KEY (path)
        )
    """)
    conn.commit()


def search(query: str) -> list:
    """Search filename and content. Returns list of {name, path, match_type}."""
    if not query or not query.strip():
        return []
    try:
        conn = sqlite3.connect(DB_PATH)
        name_rows = conn.execute(
            "SELECT path, name FROM files WHERE name LIKE ? ORDER BY name LIMIT 100",
            (f"%{query}%",),
        ).fetchall()

        content_rows = []
        try:
            content_rows = conn.execute(
                "SELECT files.path, files.name FROM content_index "
                "JOIN files ON files.path = content_index.path "
                "WHERE content_index MATCH ? LIMIT 100",
                (query,),
            ).fetchall()
        except sqlite3.OperationalError:
            pass  # bad FTS5 query syntax — skip content matches

        conn.close()
    except sqlite3.OperationalError:
        return []

    name_path_set = {p for p, _ in name_rows}
    results = [{"name": n, "path": p, "match_type": "filename"} for p, n in name_rows]
    for path, name in content_rows:
        if path not in name_path_set:
            results.append({"name": name, "path": path, "match_type": "content"})
            name_path_set.add(path)

    return results


def open_file(path: str) -> None:
    """Open a file with the OS default handler and record it in recent opens."""
    import os
    try:
        os.startfile(path)
    except AttributeError:
        # Non-Windows fallback (for dev/testing)
        import subprocess
        subprocess.Popen(["xdg-open", path])
    except Exception:
        pass

    name = Path(path).name
    try:
        conn = sqlite3.connect(DB_PATH)
        _ensure_recent_opens_table(conn)
        conn.execute(
            "INSERT OR REPLACE INTO recent_opens (path, name, opened_at) VALUES (?, ?, ?)",
            (path, name, time.time()),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_recent() -> dict:
    """Return recently opened and recently modified files."""
    opened = []
    modified = []
    try:
        conn = sqlite3.connect(DB_PATH)
        _ensure_recent_opens_table(conn)
        opened = [
            {"name": r[0], "path": r[1]}
            for r in conn.execute(
                "SELECT name, path FROM recent_opens ORDER BY opened_at DESC LIMIT 5"
            ).fetchall()
        ]
        modified = [
            {"name": r[0], "path": r[1]}
            for r in conn.execute(
                "SELECT name, path FROM files ORDER BY modified DESC LIMIT 5"
            ).fetchall()
        ]
        conn.close()
    except sqlite3.OperationalError:
        pass
    return {"opened": opened, "modified": modified}


def get_status() -> dict:
    """Return index stats."""
    global _indexing
    count = 0
    last_indexed_ago = "never"
    try:
        conn = sqlite3.connect(DB_PATH)
        count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        # Use the most recent modified time of the DB file as a proxy for last index time
        conn.close()
        db_mtime = Path(DB_PATH).stat().st_mtime
        elapsed = time.time() - db_mtime
        if elapsed < 60:
            last_indexed_ago = "just now"
        elif elapsed < 3600:
            last_indexed_ago = f"{int(elapsed // 60)}m ago"
        elif elapsed < 86400:
            last_indexed_ago = f"{int(elapsed // 3600)}h ago"
        else:
            last_indexed_ago = f"{int(elapsed // 86400)}d ago"
    except (sqlite3.OperationalError, FileNotFoundError):
        pass
    return {"count": count, "indexing": _indexing, "last_indexed_ago": last_indexed_ago}


def reindex(on_done=None) -> None:
    """Run build_index() in a background daemon thread."""
    global _indexing
    with _index_lock:
        if _indexing:
            return
        _indexing = True

    def _run():
        global _indexing
        try:
            indexer.build_index()
        finally:
            _indexing = False
            if on_done:
                on_done()

    threading.Thread(target=_run, daemon=True).start()
