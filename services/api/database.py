import sqlite3
import os
from contextlib import contextmanager
from typing import Generator
from services.api.config import settings

def get_db_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(settings.db_path), exist_ok=True)
    conn = sqlite3.connect(settings.db_path, check_same_thread=False, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn

@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = get_db_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def _ensure_column(conn: sqlite3.Connection, table: str, column: str, col_def: str) -> None:
    cur = conn.execute(f"PRAGMA table_info({table});")
    existing = {row[1] for row in cur.fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def};")

def init_db(conn: sqlite3.Connection | None = None) -> None:
    close_after = False
    if conn is None:
        conn = get_db_connection()
        close_after = True

    with conn:
        # 1. Archives table
        conn.execute("""
        CREATE TABLE IF NOT EXISTS archives (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            policy TEXT NOT NULL DEFAULT 'copy',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        conn.execute("""
        INSERT OR IGNORE INTO archives (id, name, description, policy)
        VALUES ('default', 'فضای شخصی من', 'آرشیو اصلی محلی', 'copy');
        """)

        # 2. Files table
        conn.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id TEXT PRIMARY KEY,
            archive_id TEXT NOT NULL REFERENCES archives(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            kind TEXT NOT NULL,
            topic TEXT NOT NULL DEFAULT 'کار',
            status TEXT NOT NULL DEFAULT 'در صف',
            mime_type TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            storage_path TEXT NOT NULL,
            color_scheme TEXT NOT NULL DEFAULT 'paper',
            error_code TEXT,
            error_message TEXT,
            is_user_modified INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        _ensure_column(conn, "files", "error_code", "TEXT")
        _ensure_column(conn, "files", "is_user_modified", "INTEGER NOT NULL DEFAULT 0")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_files_sha256 ON files(sha256);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_files_kind ON files(kind);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_files_archive ON files(archive_id);")

        # 3. Documents / Extracted Text table
        conn.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            file_id TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            extracted_text TEXT NOT NULL DEFAULT '',
            summary TEXT,
            page_count INTEGER NOT NULL DEFAULT 1,
            extraction_status TEXT NOT NULL DEFAULT 'extracted',
            extraction_method TEXT NOT NULL DEFAULT 'direct_text',
            system_note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        _ensure_column(conn, "documents", "extraction_status", "TEXT NOT NULL DEFAULT 'extracted'")
        _ensure_column(conn, "documents", "system_note", "TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_file_id ON documents(file_id);")

        # 4. Pages table (for page-level text & future OCR bounding boxes)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS pages (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            file_id TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            page_number INTEGER NOT NULL,
            raw_text TEXT NOT NULL DEFAULT '',
            normalized_text TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pages_file_id ON pages(file_id, page_number);")

        # 5. Tags
        conn.execute("""
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        );
        """)

        # 6. File Tags (Many-to-Many)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS file_tags (
            file_id TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
            PRIMARY KEY (file_id, tag_id)
        );
        """)

        # 7. Full-Text Search Table (FTS5)
        conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
            file_id UNINDEXED,
            title,
            extracted_text,
            topic,
            tags,
            tokenize = 'unicode61'
        );
        """)

    if close_after:
        conn.close()
