import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DB_PATH = "file_index.db"

# Edit this list to the folders you want indexed.
# Add more paths to scan other drives, e.g. r"D:\\"
ROOT_DIRS = [str(Path.home())]

# Folders to skip entirely (junk / slow to index)
SKIP_DIRS = {"node_modules", ".git", "$RECYCLE.BIN", "System Volume Information", "__pycache__"}

# Plain-text-like extensions read directly, no library needed
TEXT_EXTENSIONS = {".txt", ".py", ".md", ".js", ".html", ".css", ".json", ".csv"}

# Extensions that need a parser library to extract text
DOC_EXTENSIONS = {".pdf", ".docx"}

# Skip content extraction on huge files (slow, rarely useful to search)
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB

# How many files to buffer before flushing to SQLite. Larger = fewer commits.
FILE_BATCH = 5000
CONTENT_BATCH = 200
# Files per parallel-extraction chunk (bounds peak memory).
EXTRACT_CHUNK = 500


def extract_text(path, ext, size):
    """Pull plain text out of a file for full-text search. Returns None if unsupported or it fails."""
    if size > MAX_FILE_SIZE:
        return None
    try:
        if ext in TEXT_EXTENSIONS:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        elif ext == ".pdf":
            import pdfplumber  # pip install pdfplumber
            chunks = []
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        chunks.append(text)
            return "\n".join(chunks)
        elif ext == ".docx":
            import docx  # pip install python-docx
            doc = docx.Document(path)
            return "\n".join(p.text for p in doc.paragraphs)
    except Exception:
        return None
    return None


def _content_eligible(ext, size):
    """True if this file is worth trying to extract text from."""
    if size > MAX_FILE_SIZE:
        return False
    return ext in TEXT_EXTENSIONS or ext in DOC_EXTENSIONS


def _connect():
    conn = sqlite3.connect(DB_PATH)
    # Bulk-load pragmas: these are the single biggest indexing speedup.
    # WAL also lets the UI keep searching while a reindex is running.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA cache_size = -65536")  # ~64 MB page cache
    return conn


def create_db():
    conn = _connect()
    conn.execute("DROP TABLE IF EXISTS files")
    conn.execute("DROP TABLE IF EXISTS content_index")
    conn.execute("""
        CREATE TABLE files (
            path TEXT,
            name TEXT,
            ext TEXT,
            size INTEGER,
            modified REAL
        )
    """)
    # FTS5 virtual table for fast full-text search over file contents
    conn.execute("CREATE VIRTUAL TABLE content_index USING fts5(path, content, tokenize='porter')")
    conn.commit()
    return conn


def _iter_files(root_dir):
    """Yield os.DirEntry objects for every file under root_dir.

    Uses os.scandir (not os.walk) so that DirEntry.stat() can reuse the
    metadata Windows already returned with the directory listing — one fewer
    syscall per file than calling os.stat() separately.
    """
    stack = [root_dir]
    while stack:
        current = stack.pop()
        try:
            scan = os.scandir(current)
        except (OSError, PermissionError):
            continue
        with scan:
            for entry in scan:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name not in SKIP_DIRS:
                            stack.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        yield entry
                except OSError:
                    continue


def walk_and_index_metadata(conn):
    """Walk the tree, insert filename/metadata rows, and return the list of
    files that are candidates for content extraction: [(path, ext, size), ...]."""
    eligible = []
    file_rows = []
    for root_dir in ROOT_DIRS:
        for entry in _iter_files(root_dir):
            try:
                stat = entry.stat()  # cached on Windows, no extra syscall
            except OSError:
                continue
            name = entry.name
            path = entry.path
            ext = os.path.splitext(name)[1].lower()
            file_rows.append((path, name, ext, stat.st_size, stat.st_mtime))
            if _content_eligible(ext, stat.st_size):
                eligible.append((path, ext, stat.st_size))

            if len(file_rows) >= FILE_BATCH:
                conn.executemany("INSERT INTO files VALUES (?, ?, ?, ?, ?)", file_rows)
                conn.commit()
                file_rows = []
    if file_rows:
        conn.executemany("INSERT INTO files VALUES (?, ?, ?, ?, ?)", file_rows)
        conn.commit()
    return eligible


def _extract_one(args):
    path, ext, size = args
    return path, extract_text(path, ext, size)


def extract_and_index_content(conn, eligible):
    """Extract text from eligible files in parallel and write it to FTS5.

    Extraction runs in a thread pool (text reads are I/O-bound, and python-docx
    parses via lxml which releases the GIL), while all SQLite writes stay on the
    calling thread — sqlite3 connections aren't safe to share across threads.
    """
    if not eligible:
        return
    workers = min(8, (os.cpu_count() or 2) * 2)
    content_rows = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        # Process in chunks so peak memory is bounded by EXTRACT_CHUNK, not the
        # whole corpus, even on very large file trees.
        for start in range(0, len(eligible), EXTRACT_CHUNK):
            chunk = eligible[start:start + EXTRACT_CHUNK]
            for path, text in pool.map(_extract_one, chunk):
                if text:
                    content_rows.append((path, text))
                if len(content_rows) >= CONTENT_BATCH:
                    conn.executemany(
                        "INSERT INTO content_index (path, content) VALUES (?, ?)", content_rows
                    )
                    conn.commit()
                    content_rows = []
    if content_rows:
        conn.executemany("INSERT INTO content_index (path, content) VALUES (?, ?)", content_rows)
        conn.commit()


def build_index():
    conn = create_db()
    eligible = walk_and_index_metadata(conn)
    # Build the name index AFTER the bulk insert — far cheaper than maintaining
    # it on every row.
    conn.execute("CREATE INDEX idx_name ON files(name)")
    conn.commit()
    extract_and_index_content(conn, eligible)
    file_count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    content_count = conn.execute("SELECT COUNT(*) FROM content_index").fetchone()[0]
    conn.close()
    print(f"Indexed {file_count} files, extracted searchable text from {content_count} of them.")


if __name__ == "__main__":
    build_index()
