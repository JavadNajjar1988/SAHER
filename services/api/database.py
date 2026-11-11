import sqlite3
import os
from contextlib import contextmanager
from typing import Generator
from services.api.config import settings


def get_db_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(settings.db_path), exist_ok=True)
    conn = sqlite3.connect(settings.db_path, check_same_thread=False, timeout=20.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 15000;")
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


def _record_schema_migration(conn: sqlite3.Connection, version: str, description: str) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO schema_migrations (version, description)
        VALUES (?, ?)
        """,
        (version, description),
    )


def init_db(conn: sqlite3.Connection | None = None) -> None:
    close_after = False
    if conn is None:
        conn = get_db_connection()
        close_after = True

    with conn:
        # 0. Versioned non-destructive schema migrations tracking table
        conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

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
            processing_version INTEGER NOT NULL DEFAULT 1,
            latest_job_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        _ensure_column(conn, "files", "error_code", "TEXT")
        _ensure_column(conn, "files", "is_user_modified", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "files", "processing_version", "INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "files", "latest_job_id", "TEXT")

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
            extraction_version INTEGER NOT NULL DEFAULT 1,
            system_note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        _ensure_column(conn, "documents", "extraction_status", "TEXT NOT NULL DEFAULT 'extracted'")
        _ensure_column(conn, "documents", "system_note", "TEXT")
        _ensure_column(conn, "documents", "extraction_version", "INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "documents", "updated_at", "TIMESTAMP")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_file_id ON documents(file_id);")

        # 4. Pages table (for page-level text, OCR bounding boxes, page-level errors & user overrides)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS pages (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            file_id TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            page_number INTEGER NOT NULL,
            raw_text TEXT NOT NULL DEFAULT '',
            normalized_text TEXT NOT NULL DEFAULT '',
            bboxes_json TEXT NOT NULL DEFAULT '[]',
            extraction_method TEXT NOT NULL DEFAULT 'direct_text',
            page_status TEXT NOT NULL DEFAULT 'extracted',
            error_code TEXT,
            error_message TEXT,
            ocr_confidence REAL,
            width INTEGER,
            height INTEGER,
            is_user_modified INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        _ensure_column(conn, "pages", "bboxes_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "pages", "extraction_method", "TEXT NOT NULL DEFAULT 'direct_text'")
        _ensure_column(conn, "pages", "page_status", "TEXT NOT NULL DEFAULT 'extracted'")
        _ensure_column(conn, "pages", "error_code", "TEXT")
        _ensure_column(conn, "pages", "error_message", "TEXT")
        _ensure_column(conn, "pages", "ocr_confidence", "REAL")
        _ensure_column(conn, "pages", "width", "INTEGER")
        _ensure_column(conn, "pages", "height", "INTEGER")
        _ensure_column(conn, "pages", "is_user_modified", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "pages", "updated_at", "TIMESTAMP")
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

        # 7. Full-Text Search Table (FTS5) - Document level
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

        # 7b. Milestone 3: Page-level Full-Text Search Table (FTS5) for exact page matching
        conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
            file_id UNINDEXED,
            page_number UNINDEXED,
            raw_text,
            normalized_text,
            tokenize = 'unicode61'
        );
        """)

        _record_schema_migration(conn, "001_milestone_1_5_base", "Initial archive, files, documents, pages, tags, and FTS5 schema")

        # 8. Milestone 2: Durable Jobs table
        conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            archive_id TEXT NOT NULL REFERENCES archives(id) ON DELETE CASCADE,
            file_id TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            job_type TEXT NOT NULL DEFAULT 'FILE_INGESTION',
            target_stage TEXT,
            processing_stage TEXT NOT NULL DEFAULT 'DISCOVERY',
            state TEXT NOT NULL DEFAULT 'QUEUED',
            priority INTEGER NOT NULL DEFAULT 50,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            max_retries INTEGER NOT NULL DEFAULT 3,
            progress REAL NOT NULL DEFAULT 0.0,
            progress_message TEXT,
            error_code TEXT,
            error_message TEXT,
            is_retryable INTEGER NOT NULL DEFAULT 1,
            worker_id TEXT,
            lease_expires_at TIMESTAMP,
            heartbeat_at TIMESTAMP,
            next_run_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processing_version INTEGER NOT NULL DEFAULT 1,
            checkpoint_json TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            started_at TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_claim ON jobs(state, next_run_at, priority DESC, created_at ASC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_file_id ON jobs(file_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_archive_id ON jobs(archive_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_lease ON jobs(state, lease_expires_at);")

        # 9. Milestone 2: Job Events / Execution Attempts history table
        conn.execute("""
        CREATE TABLE IF NOT EXISTS job_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            attempt_number INTEGER NOT NULL DEFAULT 0,
            from_state TEXT,
            to_state TEXT NOT NULL,
            stage TEXT NOT NULL,
            event_type TEXT NOT NULL,
            worker_id TEXT,
            message TEXT,
            error_code TEXT,
            details_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_job_events_job_id ON job_events(job_id, id ASC);")

        # 10. Milestone 2: Worker Registry table
        conn.execute("""
        CREATE TABLE IF NOT EXISTS worker_registry (
            worker_id TEXT PRIMARY KEY,
            resource_mode TEXT NOT NULL DEFAULT 'Balanced',
            concurrency INTEGER NOT NULL DEFAULT 2,
            active_jobs INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'ONLINE',
            hostname TEXT,
            pid INTEGER,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_heartbeat_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # 11. Safe Migration Audit Log table
        conn.execute("""
        CREATE TABLE IF NOT EXISTS migration_audit_log (
            id TEXT PRIMARY KEY,
            operation_type TEXT NOT NULL,
            backup_id TEXT,
            backup_path TEXT,
            affected_count INTEGER NOT NULL DEFAULT 0,
            preserved_count INTEGER NOT NULL DEFAULT 0,
            details_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        _ensure_column(conn, "files", "card_json", "TEXT NOT NULL DEFAULT '{}'")
        _record_schema_migration(conn, "004_document_card", "General document metadata")
        _record_schema_migration(conn, "002_milestone_2_durable_jobs", "Durable jobs, job_events, worker_registry, and migration_audit_log tables")
        _record_schema_migration(conn, "003_milestone_3_ocr_and_pages_fts", "Page-level OCR text, bounding boxes, page error tracking, and pages_fts virtual table")

    if close_after:
        conn.close()
