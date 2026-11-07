import os
import re
import uuid
import zlib
import struct
import hashlib
import sqlite3
from typing import List, Optional, AsyncIterator
from services.api.config import settings
from services.api.database import get_db
from services.api.schemas import FileItemDTO, StatsDTO
from services.api.migrations import LEGACY_SEED_TITLES, LegacyMigrationManager
from services.ingestion.extractor import (
    sanitize_filename,
    validate_file_signature,
    normalize_persian_text,
    normalize_for_fts,
)
from services.worker.lifecycle import JobState
from services.worker.queue import JobQueueRepository


class IngestionValidationError(Exception):
    def __init__(self, message: str, code: str = "VALIDATION_ERROR", status_code: int = 422):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class UploadTooLargeError(Exception):
    def __init__(self, max_bytes: int):
        msg = f"حجم فایل از سقف مجاز ({max_bytes // (1024 * 1024)} مگابایت) بیشتر است."
        super().__init__(msg)
        self.message = msg
        self.code = "UPLOAD_TOO_LARGE"
        self.status_code = 413


class DuplicateFileError(Exception):
    def __init__(self, existing_id: str, existing_title: str, sha256: str):
        msg = f"این فایل قبلاً با نام «{existing_title}» در آرشیو ثبت شده است (تطابق کامل SHA-256)."
        super().__init__(msg)
        self.message = msg
        self.existing_id = existing_id
        self.existing_title = existing_title
        self.sha256 = sha256
        self.code = "DUPLICATE_FILE"
        self.status_code = 409


class StoragePersistenceError(Exception):
    def __init__(self, message: str = "خطا در ذخیره‌سازی فیزیکی فایل در دیسک محلی."):
        super().__init__(message)
        self.message = message
        self.code = "STORAGE_ERROR"
        self.status_code = 500


class DatabasePersistenceError(Exception):
    def __init__(self, message: str = "خطا در ثبت اطلاعات فایل در پایگاه‌داده SQLite."):
        super().__init__(message)
        self.message = message
        self.code = "DATABASE_ERROR"
        self.status_code = 500


def detect_kind(mime_type: str, filename: str) -> str:
    lower_name = filename.lower()
    if mime_type.startswith("image/"):
        if "screenshot" in lower_name or "screen" in lower_name or "اسکرین" in lower_name:
            return "اسکرین‌شات"
        return "تصویر"
    return "سند"


def detect_color_scheme(kind: str, filename: str) -> str:
    lower = filename.lower()
    if kind == "اسکرین‌شات":
        return "social"
    if kind == "تصویر":
        if any(w in lower for w in ["nature", "forest", "جنگل", "طبیعت", "green"]):
            return "forest"
        return "room"
    if any(w in lower for w in ["report", "ai", "هوش", "پژوهش"]):
        return "report"
    if any(w in lower for w in ["note", "یادداشت", "جلسه"]):
        return "notes"
    return "paper"


def build_safe_fts_query(raw_query: str) -> str:
    """
    Normalizes Persian/Arabic characters and half-spaces, strips FTS5 syntax characters
    to prevent syntax errors, and constructs a safe prefix match query.
    """
    if not raw_query or not raw_query.strip():
        return ""
    norm = normalize_persian_text(raw_query)
    norm = norm.replace("\u200c", " ")
    tokens = re.findall(r"\w+", norm, flags=re.UNICODE)
    fts_reserved = {"AND", "OR", "NOT", "NEAR"}
    clean_tokens = [t for t in tokens if t.upper() not in fts_reserved]
    if not clean_tokens:
        return ""
    return " ".join(f'"{tok}"*' for tok in clean_tokens)


def create_minimal_valid_png(rgb: tuple[int, int, int] = (235, 240, 238)) -> bytes:
    """Creates a genuine, spec-compliant 1x1 PNG binary for explicit demo/test fixtures."""
    width, height = 1, 1
    raw_data = b"\x00" + bytes(rgb)

    def make_chunk(chunk_type: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(raw_data)
    return (
        b"\x89PNG\r\n\x1a\n"
        + make_chunk(b"IHDR", ihdr)
        + make_chunk(b"IDAT", idat)
        + make_chunk(b"IEND", b"")
    )


class ArchiveRepository:
    @staticmethod
    def get_file_tags(conn: sqlite3.Connection, file_id: str) -> List[str]:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT t.name FROM tags t
            JOIN file_tags ft ON t.id = ft.tag_id
            WHERE ft.file_id = ?
            ORDER BY t.name ASC
            """,
            (file_id,),
        )
        return [row[0] for row in cur.fetchall()]

    @staticmethod
    def set_file_tags(conn: sqlite3.Connection, file_id: str, tag_names: List[str]) -> None:
        cur = conn.cursor()
        cur.execute("DELETE FROM file_tags WHERE file_id = ?", (file_id,))
        seen = set()
        for name in tag_names:
            clean_name = normalize_persian_text(name)
            if not clean_name or clean_name in seen:
                continue
            seen.add(clean_name)
            cur.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (clean_name,))
            cur.execute("SELECT id FROM tags WHERE name = ?", (clean_name,))
            tag_id = cur.fetchone()[0]
            cur.execute(
                "INSERT OR IGNORE INTO file_tags (file_id, tag_id) VALUES (?, ?)",
                (file_id, tag_id),
            )

    @staticmethod
    def update_fts(
        conn: sqlite3.Connection,
        file_id: str,
        title: str,
        extracted_text: str,
        topic: str,
        tags: List[str],
    ) -> None:
        """
        Indexes normalized title, genuine extracted text, topic, and tags in FTS5.
        System notes and error messages are never passed here.
        """
        cur = conn.cursor()
        cur.execute("DELETE FROM files_fts WHERE file_id = ?", (file_id,))
        cur.execute(
            """
            INSERT INTO files_fts (file_id, title, extracted_text, topic, tags)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                file_id,
                normalize_for_fts(title),
                normalize_for_fts(extracted_text),
                normalize_for_fts(topic),
                normalize_for_fts(" ".join(tags)),
            ),
        )

    @classmethod
    def _row_to_dto(
        cls,
        conn: sqlite3.Connection,
        r: sqlite3.Row,
        matched_snippet: Optional[str] = None,
    ) -> FileItemDTO:
        tags = cls.get_file_tags(conn, r["id"])
        keys = r.keys()
        return FileItemDTO(
            id=r["id"],
            archive_id=r["archive_id"],
            title=r["title"],
            kind=r["kind"],
            topic=r["topic"],
            status=r["status"],
            mime_type=r["mime_type"],
            file_size=r["file_size"],
            sha256=r["sha256"],
            text=r["extracted_text"] or "",
            extraction_status=(
                r["extraction_status"]
                if "extraction_status" in keys and r["extraction_status"]
                else "extracted"
            ),
            extraction_method=(
                r["extraction_method"]
                if "extraction_method" in keys and r["extraction_method"]
                else "direct_text"
            ),
            extraction_version=(
                int(r["extraction_version"])
                if "extraction_version" in keys and r["extraction_version"] is not None
                else 1
            ),
            processing_version=(
                int(r["processing_version"])
                if "processing_version" in keys and r["processing_version"] is not None
                else 1
            ),
            latest_job_id=(r["latest_job_id"] if "latest_job_id" in keys else None),
            job_state=(r["job_state"] if "job_state" in keys else None),
            processing_stage=(r["processing_stage"] if "processing_stage" in keys else None),
            processing_progress=(
                float(r["processing_progress"])
                if "processing_progress" in keys and r["processing_progress"] is not None
                else None
            ),
            system_note=(r["system_note"] if "system_note" in keys else None),
            error_code=(r["error_code"] if "error_code" in keys else None),
            error_message=r["error_message"],
            matched_snippet=matched_snippet,
            is_user_modified=bool(r["is_user_modified"]) if "is_user_modified" in keys else False,
            color=r["color_scheme"] or "paper",
            tags=tags,
            page_count=r["page_count"] or 1,
            created_at=str(r["created_at"]),
            updated_at=str(r["updated_at"]) if "updated_at" in keys and r["updated_at"] else None,
        )

    @classmethod
    def list_files(
        cls,
        kind: Optional[str] = None,
        query: Optional[str] = None,
        status: Optional[str] = None,
        archive_id: str = "default",
        limit: int = 100,
        offset: int = 0,
    ) -> List[FileItemDTO]:
        with get_db() as conn:
            cur = conn.cursor()

            if query is not None and query.strip() != "":
                fts_query = build_safe_fts_query(query)
                if not fts_query:
                    return []

                sql = """
                    SELECT f.id, f.archive_id, f.title, f.kind, f.topic, f.status,
                           f.mime_type, f.file_size, f.sha256, f.color_scheme,
                           f.error_code, f.error_message, f.is_user_modified,
                           f.processing_version, f.latest_job_id,
                           f.created_at, f.updated_at,
                           d.extracted_text, d.page_count, d.extraction_status,
                           d.extraction_method, d.extraction_version, d.system_note,
                           j.state AS job_state, j.processing_stage, j.progress AS processing_progress,
                           snippet(files_fts, 1, '«', '»', '…', 20) AS matched_snippet
                    FROM files_fts
                    JOIN files f ON files_fts.file_id = f.id
                    LEFT JOIN documents d ON f.id = d.file_id
                    LEFT JOIN jobs j ON f.latest_job_id = j.id
                    WHERE files_fts MATCH ?
                      AND f.archive_id = ?
                """
                params: list = [fts_query, archive_id]
                if kind and kind != "همهٔ فایل‌ها":
                    sql += " AND f.kind = ?"
                    params.append(kind)
                if status:
                    sql += " AND f.status = ?"
                    params.append(status)

                sql += " ORDER BY rank, f.created_at DESC, f.id ASC LIMIT ? OFFSET ?"
                params.extend([limit, offset])

                cur.execute(sql, params)
                rows = cur.fetchall()
                return [
                    cls._row_to_dto(conn, r, matched_snippet=r["matched_snippet"] or None)
                    for r in rows
                ]
            else:
                sql = """
                    SELECT f.id, f.archive_id, f.title, f.kind, f.topic, f.status,
                           f.mime_type, f.file_size, f.sha256, f.color_scheme,
                           f.error_code, f.error_message, f.is_user_modified,
                           f.processing_version, f.latest_job_id,
                           f.created_at, f.updated_at,
                           d.extracted_text, d.page_count, d.extraction_status,
                           d.extraction_method, d.extraction_version, d.system_note,
                           j.state AS job_state, j.processing_stage, j.progress AS processing_progress
                    FROM files f
                    LEFT JOIN documents d ON f.id = d.file_id
                    LEFT JOIN jobs j ON f.latest_job_id = j.id
                    WHERE f.archive_id = ?
                """
                params = [archive_id]
                if kind and kind != "همهٔ فایل‌ها":
                    sql += " AND f.kind = ?"
                    params.append(kind)
                if status:
                    sql += " AND f.status = ?"
                    params.append(status)

                sql += " ORDER BY f.created_at DESC, f.id ASC LIMIT ? OFFSET ?"
                params.extend([limit, offset])

                cur.execute(sql, params)
                rows = cur.fetchall()
                return [cls._row_to_dto(conn, r) for r in rows]

    @classmethod
    def get_file(cls, file_id: str) -> Optional[FileItemDTO]:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT f.id, f.archive_id, f.title, f.kind, f.topic, f.status,
                       f.mime_type, f.file_size, f.sha256, f.color_scheme,
                       f.error_code, f.error_message, f.is_user_modified,
                       f.processing_version, f.latest_job_id,
                       f.created_at, f.updated_at,
                       d.extracted_text, d.page_count, d.extraction_status,
                       d.extraction_method, d.extraction_version, d.system_note,
                       j.state AS job_state, j.processing_stage, j.progress AS processing_progress
                FROM files f
                LEFT JOIN documents d ON f.id = d.file_id
                LEFT JOIN jobs j ON f.latest_job_id = j.id
                WHERE f.id = ?
                """,
                (file_id,),
            )
            r = cur.fetchone()
            if not r:
                return None
            return cls._row_to_dto(conn, r)

    @classmethod
    def get_file_storage_path(cls, file_id: str) -> Optional[tuple[str, str, str]]:
        """Returns (storage_path, mime_type, title) if file exists on disk."""
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT storage_path, mime_type, title FROM files WHERE id = ?",
                (file_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            path = row["storage_path"]
            if not path or not os.path.exists(path):
                return None
            return path, row["mime_type"], row["title"]

    @classmethod
    def _cleanup_failed_sync_ingest(cls, file_id: str, storage_path: str) -> None:
        if storage_path and os.path.exists(storage_path):
            try:
                os.remove(storage_path)
            except OSError:
                pass
        try:
            with get_db() as conn:
                conn.execute("DELETE FROM files_fts WHERE file_id = ?", (file_id,))
                conn.execute("DELETE FROM files WHERE id = ?", (file_id,))
        except Exception:
            pass

    @classmethod
    def _ingest_temp_file(
        cls,
        temp_path: str,
        raw_filename: str,
        file_size: int,
        sha256_hash: str,
        archive_id: str = "default",
        custom_topic: Optional[str] = None,
        async_mode: bool = False,
    ) -> FileItemDTO:
        """
        1. Validates upload extension and binary signature.
        2. Checks duplicate SHA-256.
        3. Moves file to permanent storage.
        4. Registers file metadata and creates a durable processing job in SQLite atomically.
        5. If `async_mode=True`, notifies the independent background worker and returns immediately (`status='در صف'`).
           If `async_mode=False` (backward-compatible synchronous mode), executes the durable job via the worker runner.
        """
        safe_title = sanitize_filename(raw_filename)
        ext = os.path.splitext(safe_title)[1].lower()

        if ext not in settings.allowed_extensions:
            raise IngestionValidationError(
                f"پسوند فایل «{ext or 'بدون پسوند'}» پشتیبانی نمی‌شود. فرمت‌های مجاز: {', '.join(settings.allowed_extensions)}",
                code="UNSUPPORTED_EXTENSION",
                status_code=415,
            )

        is_valid, detected_mime, sig_error = validate_file_signature(temp_path, safe_title)
        if not is_valid:
            raise IngestionValidationError(
                sig_error or "ساختار باینری فایل نامعتبر است.",
                code="INVALID_FILE_SIGNATURE",
                status_code=422,
            )

        # Check duplicate SHA-256 before moving file or allocating duplicate storage
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, title FROM files WHERE sha256 = ? AND archive_id = ?",
                (sha256_hash, archive_id),
            )
            dup = cur.fetchone()
            if dup and settings.duplicate_policy == "reject":
                raise DuplicateFileError(
                    existing_id=dup["id"],
                    existing_title=dup["title"],
                    sha256=sha256_hash,
                )

        file_id = str(uuid.uuid4())
        kind = detect_kind(detected_mime, safe_title)
        color = detect_color_scheme(kind, safe_title)
        topic = normalize_persian_text(custom_topic) if custom_topic else (
            "طراحی" if "طراحی" in safe_title else "کار"
        )

        default_tags: List[str] = []
        if "هوش مصنوعی" in safe_title:
            default_tags.append("هوش مصنوعی")
        if "طراحی" in safe_title or "معماری" in safe_title:
            default_tags.append("طراحی محصول")

        stored_filename = f"{file_id}{ext}"
        final_storage_path = os.path.join(settings.storage_dir, stored_filename)

        try:
            os.makedirs(settings.storage_dir, exist_ok=True)
            os.replace(temp_path, final_storage_path)
        except OSError as exc:
            raise StoragePersistenceError("امکان انتقال فایل به مخزن دائمی روی دیسک وجود ندارد.") from exc

        # Register file, initial document placeholder, tags, and durable job in one atomic transaction
        job_id: str = ""
        try:
            with get_db() as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO files (
                        id, archive_id, title, kind, topic, status, mime_type,
                        file_size, sha256, storage_path, color_scheme, processing_version
                    ) VALUES (?, ?, ?, ?, ?, 'در صف', ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        file_id,
                        archive_id,
                        safe_title,
                        kind,
                        topic,
                        detected_mime,
                        file_size,
                        sha256_hash,
                        final_storage_path,
                        color,
                    ),
                )

                doc_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO documents (
                        id, file_id, extracted_text, page_count,
                        extraction_status, extraction_method, extraction_version, system_note
                    ) VALUES (?, ?, '', 1, 'queued', 'none', 0, 'در صف پردازش کارگر پس‌زمینه')
                    """,
                    (doc_id, file_id),
                )

                cls.set_file_tags(conn, file_id, default_tags)
                cls.update_fts(conn, file_id, safe_title, "", topic, default_tags)

                job_id = JobQueueRepository.create_job_in_transaction(
                    conn=conn,
                    file_id=file_id,
                    archive_id=archive_id,
                    processing_version=1,
                    progress_message="فایل دریافت و در صف پردازش پایدار ثبت شد.",
                )
        except Exception as exc:
            cls._cleanup_failed_sync_ingest(file_id, final_storage_path)
            raise DatabasePersistenceError() from exc

        if async_mode:
            from services.worker.runner import default_worker

            if default_worker.is_running:
                default_worker.notify()
            res = cls.get_file(file_id)
            if not res:
                raise DatabasePersistenceError()
            return res

        # Backward-compatible synchronous mode: execute the durable job immediately via WorkerRunner
        from services.worker.runner import default_worker

        job_result = default_worker.process_one(specific_job_id=job_id)
        if job_result and job_result.state == JobState.FAILED.value:
            err_code = job_result.error_code or "EXTRACTION_FAILED"
            err_msg = job_result.error_message or "خطا در استخراج محتوای فایل."
            cls._cleanup_failed_sync_ingest(file_id, final_storage_path)
            if err_code in ("DATABASE_LOCKED", "WORKER_EXECUTION_ERROR"):
                raise DatabasePersistenceError()
            raise IngestionValidationError(err_msg, code=err_code, status_code=422)

        # If a transient retry was scheduled because of a simulated DB failure in synchronous mode, roll back cleanly
        if job_result and job_result.state == JobState.QUEUED.value and job_result.attempt_count >= 1:
            cls._cleanup_failed_sync_ingest(file_id, final_storage_path)
            raise DatabasePersistenceError()

        res = cls.get_file(file_id)
        if not res:
            raise DatabasePersistenceError()
        return res

    @classmethod
    async def save_uploaded_stream(
        cls,
        filename: str,
        chunk_iterator: AsyncIterator[bytes],
        archive_id: str = "default",
        custom_topic: Optional[str] = None,
        async_mode: bool = False,
    ) -> FileItemDTO:
        """
        Streams an incoming upload to disk with bounded memory, computing SHA-256 on the fly
        and enforcing max_upload_size_bytes. Cleans up incomplete writes on any failure.
        """
        try:
            os.makedirs(settings.storage_dir, exist_ok=True)
        except OSError as exc:
            raise StoragePersistenceError() from exc

        temp_name = f".tmp_upload_{uuid.uuid4().hex}"
        temp_path = os.path.join(settings.storage_dir, temp_name)
        sha = hashlib.sha256()
        total_bytes = 0

        try:
            with open(temp_path, "wb") as f:
                async for chunk in chunk_iterator:
                    if not chunk:
                        continue
                    total_bytes += len(chunk)
                    if total_bytes > settings.max_upload_size_bytes:
                        raise UploadTooLargeError(settings.max_upload_size_bytes)
                    sha.update(chunk)
                    f.write(chunk)

            if total_bytes == 0:
                raise IngestionValidationError(
                    "فایل ارسال‌شده خالی است.",
                    code="EMPTY_FILE",
                    status_code=400,
                )

            return cls._ingest_temp_file(
                temp_path=temp_path,
                raw_filename=filename,
                file_size=total_bytes,
                sha256_hash=sha.hexdigest(),
                archive_id=archive_id,
                custom_topic=custom_topic,
                async_mode=async_mode,
            )
        except (
            IngestionValidationError,
            UploadTooLargeError,
            DuplicateFileError,
            StoragePersistenceError,
            DatabasePersistenceError,
        ):
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            raise
        except OSError as exc:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            raise StoragePersistenceError() from exc
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    @classmethod
    def save_imported_file(
        cls,
        filename: str,
        content: bytes,
        archive_id: str = "default",
        custom_topic: Optional[str] = None,
        async_mode: bool = False,
    ) -> FileItemDTO:
        """Synchronous helper for importing in-memory bytes (used by tests and CLI tools)."""
        if len(content) == 0:
            raise IngestionValidationError("فایل ارسال‌شده خالی است.", code="EMPTY_FILE", status_code=400)
        if len(content) > settings.max_upload_size_bytes:
            raise UploadTooLargeError(settings.max_upload_size_bytes)

        try:
            os.makedirs(settings.storage_dir, exist_ok=True)
        except OSError as exc:
            raise StoragePersistenceError() from exc

        temp_name = f".tmp_sync_{uuid.uuid4().hex}"
        temp_path = os.path.join(settings.storage_dir, temp_name)
        sha256_hash = hashlib.sha256(content).hexdigest()

        try:
            with open(temp_path, "wb") as f:
                f.write(content)
            return cls._ingest_temp_file(
                temp_path=temp_path,
                raw_filename=filename,
                file_size=len(content),
                sha256_hash=sha256_hash,
                archive_id=archive_id,
                custom_topic=custom_topic,
                async_mode=async_mode,
            )
        except OSError as exc:
            raise StoragePersistenceError() from exc
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    @classmethod
    def update_file(
        cls,
        file_id: str,
        topic: Optional[str] = None,
        status: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Optional[FileItemDTO]:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT title, topic, status FROM files WHERE id = ?", (file_id,))
            file_row = cur.fetchone()
            if not file_row:
                return None

            new_topic = normalize_persian_text(topic) if topic is not None else file_row["topic"]
            new_status = status if status is not None else file_row["status"]

            cur.execute(
                """
                UPDATE files
                SET topic = ?, status = ?, is_user_modified = 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (new_topic, new_status, file_id),
            )

            if tags is not None:
                cls.set_file_tags(conn, file_id, tags)

            cur.execute(
                "SELECT extracted_text, extraction_status FROM documents WHERE file_id = ?",
                (file_id,),
            )
            doc_row = cur.fetchone()
            text = doc_row["extracted_text"] if (doc_row and doc_row["extraction_status"] != "failed") else ""
            current_tags = cls.get_file_tags(conn, file_id)

            cls.update_fts(conn, file_id, file_row["title"], text, new_topic, current_tags)

        return cls.get_file(file_id)

    @classmethod
    def get_stats(cls, archive_id: str = "default") -> StatsDTO:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM files WHERE archive_id = ?", (archive_id,))
            total = cur.fetchone()[0]

            cur.execute(
                "SELECT COUNT(*) FROM files WHERE archive_id = ? AND status = 'آماده'",
                (archive_id,),
            )
            ready = cur.fetchone()[0]

            cur.execute(
                "SELECT COUNT(*) FROM files WHERE archive_id = ? AND status != 'آماده'",
                (archive_id,),
            )
            attention = cur.fetchone()[0]

            cur.execute(
                "SELECT COUNT(*) FROM jobs WHERE archive_id = ? AND state = 'QUEUED'",
                (archive_id,),
            )
            queued_jobs = cur.fetchone()[0]

            cur.execute(
                "SELECT COUNT(*) FROM jobs WHERE archive_id = ? AND state = 'RUNNING'",
                (archive_id,),
            )
            running_jobs = cur.fetchone()[0]

            cur.execute(
                "SELECT COUNT(*) FROM jobs WHERE archive_id = ? AND state = 'FAILED'",
                (archive_id,),
            )
            failed_jobs = cur.fetchone()[0]

            return StatsDTO(
                total_files=total,
                ready_files=ready,
                attention_files=attention,
                queued_jobs=queued_jobs,
                running_jobs=running_jobs,
                failed_jobs=failed_jobs,
                demo_mode=settings.demo_mode,
            )

    @classmethod
    def purge_legacy_fake_seed_records(cls, confirm_approval: bool = False) -> int:
        """
        Safe migration wrapper: NEVER deletes files unless `confirm_approval=True` is explicitly provided.
        When approved, delegates to `LegacyMigrationManager.execute_approved_cleanup` which creates
        a verified backup and audit record before removing only unmodified legacy seed records.
        """
        if not confirm_approval:
            return 0
        res = LegacyMigrationManager.execute_approved_cleanup(confirm_approval=True)
        return res.removed_count
