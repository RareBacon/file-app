import os
import sqlite3
from pathlib import Path

DB_PATH = "file_index.db"

# Edit this list to the folders you want indexed.
# Add more paths to scan other drives, e.g. r"D:\\"
ROOT_DIRS = [str(Path.home())]

# Folders to skip entirely (junk / slow to index)
SKIP_DIRS = {"node_modules", ".git", "$RECYCLE.BIN", "System Volume Information", "__pycache__"}

# Plain-text-like extensions read directly, no library needed
TEXT_EXTENSIONS = {".txt", ".py", ".md", ".js", ".html", ".css", ".json", ".csv"}

# Skip content extraction on huge files (slow, rarely useful to search)
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


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


def create_db():
    conn = sqlite3.connect(DB_PATH)
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
    conn.execute("CREATE INDEX idx_name ON files(name)")
    # FTS5 virtual table for fast full-text search over file contents
    conn.execute("CREATE VIRTUAL TABLE content_index USING fts5(path, content, tokenize='porter')")
    conn.commit()
    return conn


def walk_and_index(conn):
    file_rows = []
    content_rows = []
    for root_dir in ROOT_DIRS:
        for dirpath, dirnames, filenames in os.walk(root_dir):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fname in filenames:
                full_path = os.path.join(dirpath, fname)
                try:
                    stat = os.stat(full_path)
                except (OSError, PermissionError):
                    continue
                ext = os.path.splitext(fname)[1].lower()
                file_rows.append((full_path, fname, ext, stat.st_size, stat.st_mtime))

                text = extract_text(full_path, ext, stat.st_size)
                if text:
                    content_rows.append((full_path, text))

                if len(file_rows) >= 1000:
                    conn.executemany("INSERT INTO files VALUES (?, ?, ?, ?, ?)", file_rows)
                    conn.commit()
                    file_rows = []
                if len(content_rows) >= 200:
                    conn.executemany("INSERT INTO content_index (path, content) VALUES (?, ?)", content_rows)
                    conn.commit()
                    content_rows = []
    if file_rows:
        conn.executemany("INSERT INTO files VALUES (?, ?, ?, ?, ?)", file_rows)
        conn.commit()
    if content_rows:
        conn.executemany("INSERT INTO content_index (path, content) VALUES (?, ?)", content_rows)
        conn.commit()


def build_index():
    conn = create_db()
    walk_and_index(conn)
    file_count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    content_count = conn.execute("SELECT COUNT(*) FROM content_index").fetchone()[0]
    conn.close()
    print(f"Indexed {file_count} files, extracted searchable text from {content_count} of them.")


if __name__ == "__main__":
    build_index()
