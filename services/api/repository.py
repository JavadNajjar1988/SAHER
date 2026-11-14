import os
import re
import json
import uuid
import zlib
import struct
import hashlib
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, AsyncIterator, Any
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
    def _get_failed_pages(cls, conn: sqlite3.Connection, file_id: str) -> List[int]:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT page_number FROM pages
            WHERE file_id = ? AND page_status = 'failed'
            ORDER BY page_number ASC
            """,
            (file_id,),
        )
        return [int(r[0]) for r in cur.fetchall()]

    @classmethod
    def _find_matching_pages(
        cls,
        conn: sqlite3.Connection,
        file_id: str,
        fts_query: str,
    ) -> tuple[Optional[int], List[int], Optional[str]]:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT CAST(page_number AS INTEGER) AS pnum,
                   snippet(pages_fts, 2, '«', '»', '…', 20) AS page_snippet
            FROM pages_fts
            WHERE pages_fts MATCH ? AND file_id = ?
            ORDER BY rank, pnum ASC
            """,
            (fts_query, file_id),
        )
        rows = cur.fetchall()
        if not rows:
            return None, [], None
        matched_pages: List[int] = []
        primary_snippet: Optional[str] = None
        for r in rows:
            pnum = int(r["pnum"])
            if pnum not in matched_pages:
                matched_pages.append(pnum)
            if primary_snippet is None and r["page_snippet"]:
                primary_snippet = f"صفحهٔ {pnum}: {r['page_snippet']}"
        matched_pages.sort()
        primary_page = int(rows[0]["pnum"])
        return primary_page, matched_pages, primary_snippet

    @classmethod
    def _row_to_dto(
        cls,
        conn: sqlite3.Connection,
        r: sqlite3.Row,
        matched_snippet: Optional[str] = None,
        matched_page: Optional[int] = None,
        matched_pages: Optional[List[int]] = None,
    ) -> FileItemDTO:
        tags = cls.get_file_tags(conn, r["id"])
        failed_pages = cls._get_failed_pages(conn, r["id"])
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
            matched_page=matched_page,
            matched_pages=matched_pages or [],
            failed_pages=failed_pages,
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
                results: List[FileItemDTO] = []
                for r in rows:
                    m_page, m_pages, page_snip = cls._find_matching_pages(conn, r["id"], fts_query)
                    if m_page is None and (r["extracted_text"] or "").strip():
                        m_page = 1
                        m_pages = [1]
                    final_snip = page_snip or r["matched_snippet"] or None
                    results.append(
                        cls._row_to_dto(
                            conn,
                            r,
                            matched_snippet=final_snip,
                            matched_page=m_page,
                            matched_pages=m_pages,
                        )
                    )
                return results
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
    def get_file_pages(cls, file_id: str) -> List[Any]:
        import json as _json
        from services.api.schemas import PageItemDTO, BoundingBoxDTO

        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, file_id, page_number, raw_text, normalized_text,
                       bboxes_json, extraction_method, page_status,
                       error_code, error_message, ocr_confidence,
                       width, height, is_user_modified, updated_at
                FROM pages
                WHERE file_id = ?
                ORDER BY page_number ASC
                """,
                (file_id,),
            )
            rows = cur.fetchall()
            pages_out: List[PageItemDTO] = []
            for r in rows:
                try:
                    raw_boxes = _json.loads(r["bboxes_json"] or "[]")
                    boxes = [BoundingBoxDTO(**b) for b in raw_boxes if isinstance(b, dict)]
                except Exception:
                    boxes = []
                pages_out.append(
                    PageItemDTO(
                        id=r["id"],
                        file_id=r["file_id"],
                        page_number=int(r["page_number"]),
                        raw_text=r["raw_text"] or "",
                        normalized_text=r["normalized_text"] or "",
                        bboxes=boxes,
                        extraction_method=r["extraction_method"] or "direct_text",
                        page_status=r["page_status"] or "extracted",
                        error_code=r["error_code"],
                        error_message=r["error_message"],
                        ocr_confidence=float(r["ocr_confidence"]) if r["ocr_confidence"] is not None else None,
                        width=int(r["width"]) if r["width"] is not None else None,
                        height=int(r["height"]) if r["height"] is not None else None,
                        is_user_modified=bool(r["is_user_modified"]),
                        updated_at=str(r["updated_at"]) if r["updated_at"] else None,
                    )
                )
            return pages_out

    @classmethod
    def update_page_text(cls, file_id: str, page_number: int, raw_text: str) -> Optional[Any]:
        import json as _json
        from services.ingestion.extractor import build_synthetic_line_bboxes

        norm_text = normalize_persian_text(raw_text)
        fts_norm = normalize_for_fts(norm_text)

        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, title, topic FROM files WHERE id = ?", (file_id,))
            f_row = cur.fetchone()
            if not f_row:
                return None

            cur.execute("SELECT id FROM documents WHERE file_id = ?", (file_id,))
            d_row = cur.fetchone()
            if not d_row:
                return None
            doc_id = d_row["id"]

            cur.execute(
                "SELECT id, width, height FROM pages WHERE file_id = ? AND page_number = ?",
                (file_id, page_number),
            )
            p_row = cur.fetchone()
            w = int(p_row["width"] or 800) if p_row else 800
            h = int(p_row["height"] or 1100) if p_row else 1100
            bboxes = build_synthetic_line_bboxes(norm_text, w, h)

            if p_row:
                cur.execute(
                    """
                    UPDATE pages
                    SET raw_text = ?,
                        normalized_text = ?,
                        bboxes_json = ?,
                        page_status = 'user_modified',
                        error_code = NULL,
                        error_message = NULL,
                        is_user_modified = 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (raw_text, norm_text, _json.dumps(bboxes, ensure_ascii=False), p_row["id"]),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO pages (
                        id, document_id, file_id, page_number, raw_text, normalized_text,
                        bboxes_json, extraction_method, page_status, is_user_modified,
                        width, height, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'user_modified', 'user_modified', 1, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        str(uuid.uuid4()),
                        doc_id,
                        file_id,
                        page_number,
                        raw_text,
                        norm_text,
                        _json.dumps(bboxes, ensure_ascii=False),
                        w,
                        h,
                    ),
                )

            # Rebuild `pages_fts` and `documents.extracted_text` + `files_fts` for this file
            cur.execute(
                "SELECT page_number, raw_text, normalized_text FROM pages WHERE file_id = ? ORDER BY page_number ASC",
                (file_id,),
            )
            all_pages = cur.fetchall()
            cur.execute("DELETE FROM pages_fts WHERE file_id = ?", (file_id,))
            non_empty_texts: List[str] = []
            for pr in all_pages:
                p_norm = (pr["normalized_text"] or "").strip()
                if p_norm:
                    non_empty_texts.append(p_norm)
                p_fts = normalize_for_fts(p_norm or pr["raw_text"] or "")
                if p_fts:
                    cur.execute(
                        "INSERT INTO pages_fts (file_id, page_number, raw_text, normalized_text) VALUES (?, ?, ?, ?)",
                        (file_id, int(pr["page_number"]), normalize_persian_text(pr["raw_text"] or ""), p_fts),
                    )

            combined_text = "\n\n".join(non_empty_texts)
            cur.execute(
                "UPDATE documents SET extracted_text = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (combined_text, doc_id),
            )
            cur.execute(
                "UPDATE files SET is_user_modified = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (file_id,),
            )
            tags = cls.get_file_tags(conn, file_id)
            cls.update_fts(conn, file_id, f_row["title"], combined_text, f_row["topic"], tags)

        pages = cls.get_file_pages(file_id)
        for p in pages:
            if p.page_number == page_number:
                return p
        return None

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

    @classmethod
    def analyze_file_nature_and_topic(
        cls,
        file_id: str,
        relative_path: str = "",
        auto_update_metadata: bool = False,
        source_url: str = "",
        template_overrides: Optional[Dict[str, Any]] = None,
        ocr_engine: Optional[str] = None,
    ):
        """
        Computes a comprehensive visual + textual nature & topic analysis for a stored archive file/image.
        Optionally enriches the file's topic and tags in SQLite when `auto_update_metadata=True`.
        """
        from services.analysis.image_analyzer import analyze_image_nature_and_topic
        from services.ocr import get_ocr_engine_by_name

        file_item = cls.get_file(file_id)
        if not file_item:
            return None

        storage_info = cls.get_file_storage_path(file_id)
        storage_path = storage_info[0] if storage_info else ""
        pages = cls.get_file_pages(file_id)

        bboxes_combined = []
        confs = []
        for p in pages:
            for b in p.bboxes:
                bboxes_combined.append(b.model_dump() if hasattr(b, "model_dump") else dict(b))
            if p.ocr_confidence is not None:
                confs.append(float(p.ocr_confidence))

        avg_conf = round(sum(confs) / len(confs), 1) if confs else None
        effective_text = file_item.text or ""
        effective_engine_name = (ocr_engine or settings.ocr_engine or "paddleocr").strip().lower()

        # When PaddleOCR / Hybrid engine is requested and existing text is empty or low-confidence
        # (e.g. dark-mode screenshot or unextracted image), run PaddleOCR recognition on the image
        if (
            storage_path
            and os.path.isfile(storage_path)
            and file_item.mime_type.startswith("image/")
            and effective_engine_name in ("paddleocr", "hybrid")
            and (not effective_text.strip() or (avg_conf is not None and avg_conf < 72.0))
        ):
            try:
                engine_adapter = get_ocr_engine_by_name(effective_engine_name)
                ocr_res = engine_adapter.recognize_image(storage_path, page_number=1)
                if ocr_res.normalized_text and len(ocr_res.normalized_text) >= len(effective_text.strip()):
                    effective_text = ocr_res.normalized_text
                    bboxes_combined = [b.to_dict() for b in ocr_res.bboxes]
                    avg_conf = round(float(ocr_res.confidence), 1)
            except Exception:
                pass

        # Preserve any previously saved account identity or URL tags (from folder upload) during subsequent re-analysis / Word export
        effective_rel_path = relative_path or file_item.title
        effective_source_url = (source_url or "").strip()
        for t in file_item.tags or []:
            if t.startswith("آیدی:") and "/" not in effective_rel_path:
                saved_id = t.replace("آیدی:", "").strip()
                if saved_id:
                    effective_rel_path = f"{saved_id}/{effective_rel_path}"
            elif t.startswith("لینک:") and not effective_source_url:
                effective_source_url = t.replace("لینک:", "").strip()

        result = analyze_image_nature_and_topic(
            file_id=file_item.id,
            title=file_item.title,
            image_path=storage_path,
            mime_type=file_item.mime_type,
            file_size=file_item.file_size,
            extracted_text=effective_text,
            bboxes=bboxes_combined,
            ocr_confidence=avg_conf,
            relative_path=effective_rel_path,
            source_url=effective_source_url,
            template_overrides=template_overrides,
            ocr_engine=effective_engine_name,
        )

        if auto_update_metadata:
            if not file_item.is_user_modified:
                merged_tags = list(file_item.tags)
                for t in result.tags:
                    if t not in merged_tags:
                        merged_tags.append(t)
                if effective_source_url:
                    url_tag = f"لینک: {effective_source_url}"
                    if url_tag not in merged_tags:
                        merged_tags.append(url_tag)
                with get_db() as conn:
                    conn.execute(
                        "UPDATE files SET topic = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (result.detected_topic, file_id),
                    )
                    cls.set_file_tags(conn, file_id, merged_tags[:10])
                    cls.update_fts(
                        conn,
                        file_id,
                        file_item.title,
                        effective_text,
                        result.detected_topic,
                        merged_tags[:10],
                    )
            try:
                pid = getattr(result, "personal_identity", None) or {}
                crim = getattr(result, "criminal_assessment", None) or {}
                if pid.get("has_identity_data"):
                    cls.sync_single_analysis_to_identity_profile(file_id, pid, crim)
            except Exception:
                pass

        return result

    @classmethod
    def sync_single_analysis_to_identity_profile(
        cls,
        file_id: str,
        pid: Dict[str, Any],
        crim: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Upserts an extracted personal identity dossier into `identity_profiles`, matching
        by national_id, mobile_phone, account_handle, or source_file_id so duplicate images
        of the same subject enrich a single unified dossier.
        """
        nid = (pid.get("national_id") or "").strip()
        mob = (pid.get("mobile_phone") or "").strip()
        handle = (pid.get("account_handle") or "").strip()
        full_n = (pid.get("full_name") or "").strip()

        if not (nid or mob or handle or full_n):
            return None

        jud_notes_parts: List[str] = []
        if crim.get("criminal_charges"):
            jud_notes_parts.append("اتهامات: " + " ؛ ".join(crim["criminal_charges"]))
        if crim.get("legal_articles"):
            jud_notes_parts.append("مواد قانونی: " + " ؛ ".join(crim["legal_articles"]))
        if crim.get("recommended_action"):
            jud_notes_parts.append("اقدام: " + str(crim["recommended_action"]))
        jud_notes = " | ".join(jud_notes_parts)

        with get_db() as conn:
            cur = conn.cursor()
            existing_row = None
            if nid:
                cur.execute("SELECT * FROM identity_profiles WHERE national_id = ? LIMIT 1", (nid,))
                existing_row = cur.fetchone()
            if not existing_row and mob:
                cur.execute("SELECT * FROM identity_profiles WHERE mobile_phone = ? LIMIT 1", (mob,))
                existing_row = cur.fetchone()
            if not existing_row and handle:
                cur.execute("SELECT * FROM identity_profiles WHERE lower(account_handle) = lower(?) LIMIT 1", (handle,))
                existing_row = cur.fetchone()
            if not existing_row and file_id:
                cur.execute("SELECT * FROM identity_profiles WHERE source_file_id = ? LIMIT 1", (file_id,))
                existing_row = cur.fetchone()

            fields_map = {
                "source_file_id": file_id,
                "first_name": (pid.get("first_name") or "").strip(),
                "last_name": (pid.get("last_name") or "").strip(),
                "full_name": full_n,
                "father_name": (pid.get("father_name") or "").strip(),
                "national_id": nid,
                "birth_certificate_no": (pid.get("birth_certificate_no") or "").strip(),
                "birth_date": (pid.get("birth_date") or "").strip(),
                "birth_place": (pid.get("birth_place") or "").strip(),
                "occupation": (pid.get("occupation") or "").strip(),
                "mobile_phone": mob,
                "secondary_mobile": (pid.get("secondary_mobile") or "").strip(),
                "landline_phone": (pid.get("landline_phone") or "").strip(),
                "province": (pid.get("province") or "").strip(),
                "city": (pid.get("city") or "").strip(),
                "address": (pid.get("address") or "").strip(),
                "postal_code": (pid.get("postal_code") or "").strip(),
                "gps_coordinates": (pid.get("gps_coordinates") or "").strip(),
                "location_name": (pid.get("location_name") or "").strip(),
                "account_handle": handle,
                "numeric_id": (pid.get("numeric_id") or "").strip(),
                "profile_url": (pid.get("profile_url") or "").strip(),
                "personal_folder": (pid.get("personal_folder") or "").strip(),
                "thematic_category": (pid.get("thematic_category") or "اجتماعی").strip(),
                "risk_level": (crim.get("risk_level") or "عادی").strip(),
                "judicial_notes": jud_notes,
            }

            if existing_row:
                prof_id = existing_row["id"]
                merged: Dict[str, Any] = {}
                for k, new_v in fields_map.items():
                    old_v = existing_row[k] if k in existing_row.keys() else ""
                    if new_v and (not old_v or old_v == "موقعیت مکانی ثبت‌نشده" or len(str(new_v)) > len(str(old_v))):
                        merged[k] = new_v
                    else:
                        merged[k] = old_v or ""
                cur.execute(
                    """
                    UPDATE identity_profiles SET
                        source_file_id = ?, first_name = ?, last_name = ?, full_name = ?,
                        father_name = ?, national_id = ?, birth_certificate_no = ?, birth_date = ?,
                        birth_place = ?, occupation = ?, mobile_phone = ?, secondary_mobile = ?,
                        landline_phone = ?, province = ?, city = ?, address = ?, postal_code = ?,
                        gps_coordinates = ?, location_name = ?, account_handle = ?, numeric_id = ?,
                        profile_url = ?, personal_folder = ?, thematic_category = ?, risk_level = ?,
                        judicial_notes = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        merged["source_file_id"],
                        merged["first_name"],
                        merged["last_name"],
                        merged["full_name"],
                        merged["father_name"],
                        merged["national_id"],
                        merged["birth_certificate_no"],
                        merged["birth_date"],
                        merged["birth_place"],
                        merged["occupation"],
                        merged["mobile_phone"],
                        merged["secondary_mobile"],
                        merged["landline_phone"],
                        merged["province"],
                        merged["city"],
                        merged["address"],
                        merged["postal_code"],
                        merged["gps_coordinates"],
                        merged["location_name"],
                        merged["account_handle"],
                        merged["numeric_id"],
                        merged["profile_url"],
                        merged["personal_folder"],
                        merged["thematic_category"],
                        merged["risk_level"],
                        merged["judicial_notes"],
                        prof_id,
                    ),
                )
            else:
                prof_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO identity_profiles (
                        id, source_file_id, first_name, last_name, full_name,
                        father_name, national_id, birth_certificate_no, birth_date,
                        birth_place, occupation, mobile_phone, secondary_mobile,
                        landline_phone, province, city, address, postal_code,
                        gps_coordinates, location_name, account_handle, numeric_id,
                        profile_url, personal_folder, thematic_category, risk_level,
                        judicial_notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        prof_id,
                        fields_map["source_file_id"],
                        fields_map["first_name"],
                        fields_map["last_name"],
                        fields_map["full_name"],
                        fields_map["father_name"],
                        fields_map["national_id"],
                        fields_map["birth_certificate_no"],
                        fields_map["birth_date"],
                        fields_map["birth_place"],
                        fields_map["occupation"],
                        fields_map["mobile_phone"],
                        fields_map["secondary_mobile"],
                        fields_map["landline_phone"],
                        fields_map["province"],
                        fields_map["city"],
                        fields_map["address"],
                        fields_map["postal_code"],
                        fields_map["gps_coordinates"],
                        fields_map["location_name"],
                        fields_map["account_handle"],
                        fields_map["numeric_id"],
                        fields_map["profile_url"],
                        fields_map["personal_folder"],
                        fields_map["thematic_category"],
                        fields_map["risk_level"],
                        fields_map["judicial_notes"],
                    ),
                )
            cur.execute("SELECT * FROM identity_profiles WHERE id = ?", (prof_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    @classmethod
    def list_identity_profiles(cls, query: str = "") -> List[Dict[str, Any]]:
        with get_db() as conn:
            cur = conn.cursor()
            q = (query or "").strip()
            if q:
                like_q = f"%{q}%"
                cur.execute(
                    """
                    SELECT * FROM identity_profiles
                    WHERE full_name LIKE ? OR first_name LIKE ? OR last_name LIKE ?
                       OR father_name LIKE ? OR national_id LIKE ? OR birth_certificate_no LIKE ?
                       OR mobile_phone LIKE ? OR secondary_mobile LIKE ? OR landline_phone LIKE ?
                       OR address LIKE ? OR city LIKE ? OR province LIKE ?
                       OR account_handle LIKE ? OR numeric_id LIKE ? OR judicial_notes LIKE ?
                    ORDER BY updated_at DESC, created_at DESC
                    """,
                    (like_q,) * 15,
                )
            else:
                cur.execute("SELECT * FROM identity_profiles ORDER BY updated_at DESC, created_at DESC")
            return [dict(r) for r in cur.fetchall()]

    @classmethod
    def upsert_identity_profile(cls, data: Dict[str, Any], profile_id: Optional[str] = None) -> Dict[str, Any]:
        full_n = (data.get("full_name") or "").strip()
        fn = (data.get("first_name") or "").strip()
        ln = (data.get("last_name") or "").strip()
        if not full_n and (fn or ln):
            full_n = f"{fn} {ln}".strip()
        elif full_n and not (fn or ln):
            parts = full_n.split()
            if len(parts) >= 2:
                fn = parts[0]
                ln = " ".join(parts[1:])
            elif len(parts) == 1:
                fn = parts[0]

        with get_db() as conn:
            cur = conn.cursor()
            target_id = profile_id or str(uuid.uuid4())
            cur.execute("SELECT id FROM identity_profiles WHERE id = ?", (target_id,))
            exists = cur.fetchone() is not None

            vals = (
                data.get("source_file_id"),
                fn,
                ln,
                full_n,
                (data.get("father_name") or "").strip(),
                (data.get("national_id") or "").strip(),
                (data.get("birth_certificate_no") or "").strip(),
                (data.get("birth_date") or "").strip(),
                (data.get("birth_place") or "").strip(),
                (data.get("occupation") or "").strip(),
                (data.get("mobile_phone") or "").strip(),
                (data.get("secondary_mobile") or "").strip(),
                (data.get("landline_phone") or "").strip(),
                (data.get("province") or "").strip(),
                (data.get("city") or "").strip(),
                (data.get("address") or "").strip(),
                (data.get("postal_code") or "").strip(),
                (data.get("gps_coordinates") or "").strip(),
                (data.get("location_name") or "").strip(),
                (data.get("account_handle") or "").strip(),
                (data.get("numeric_id") or "").strip(),
                (data.get("profile_url") or "").strip(),
                (data.get("personal_folder") or "").strip(),
                (data.get("thematic_category") or "اجتماعی").strip(),
                (data.get("risk_level") or "عادی").strip(),
                (data.get("judicial_notes") or "").strip(),
            )

            if exists:
                cur.execute(
                    """
                    UPDATE identity_profiles SET
                        source_file_id = ?, first_name = ?, last_name = ?, full_name = ?,
                        father_name = ?, national_id = ?, birth_certificate_no = ?, birth_date = ?,
                        birth_place = ?, occupation = ?, mobile_phone = ?, secondary_mobile = ?,
                        landline_phone = ?, province = ?, city = ?, address = ?, postal_code = ?,
                        gps_coordinates = ?, location_name = ?, account_handle = ?, numeric_id = ?,
                        profile_url = ?, personal_folder = ?, thematic_category = ?, risk_level = ?,
                        judicial_notes = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (*vals, target_id),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO identity_profiles (
                        id, source_file_id, first_name, last_name, full_name,
                        father_name, national_id, birth_certificate_no, birth_date,
                        birth_place, occupation, mobile_phone, secondary_mobile,
                        landline_phone, province, city, address, postal_code,
                        gps_coordinates, location_name, account_handle, numeric_id,
                        profile_url, personal_folder, thematic_category, risk_level,
                        judicial_notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (target_id, *vals),
                )
            cur.execute("SELECT * FROM identity_profiles WHERE id = ?", (target_id,))
            row = cur.fetchone()
            return dict(row)

    @classmethod
    def delete_identity_profile(cls, profile_id: str) -> bool:
        with get_db() as conn:
            cur = conn.execute("DELETE FROM identity_profiles WHERE id = ?", (profile_id,))
            return cur.rowcount > 0

    @classmethod
    def sync_identity_profiles_from_archive(cls) -> List[Dict[str, Any]]:
        cls.ensure_default_user_report_seeded()
        files, _ = cls.list_files(limit=200, offset=0)
        for f in files:
            try:
                cls.analyze_file_nature_and_topic(
                    file_id=f.id,
                    relative_path=f.title,
                    auto_update_metadata=True,
                )
            except Exception:
                pass
        return cls.list_identity_profiles()

    # =========================================================================
    # 6-Tab User Activity Reports (گزارش جامع کاربر - دیتای مجازی، حقیقی، تحلیل شخصیت، عناوین اتهامی، گروه‌ها و پیام‌ها)
    # =========================================================================

    @classmethod
    def _row_to_user_report_summary(cls, row: Any) -> Dict[str, Any]:
        d = dict(row)
        return {
            "id": d["id"],
            "full_name": d.get("full_name") or "",
            "username": d.get("username") or "",
            "telegram_id": d.get("telegram_id") or "",
            "national_id": d.get("national_id") or "",
            "phone_number": d.get("phone_number") or "",
            "city": d.get("city") or "",
            "province": d.get("province") or "",
            "final_status": d.get("final_status") or "سیاه",
            "header_subtitle": d.get("header_subtitle") or "",
            "total_charges": int(d.get("total_charges") or 0),
            "total_groups": int(d.get("total_groups") or 0),
            "total_messages": int(d.get("total_messages") or 0),
            "source_filename": d.get("source_filename") or "",
            "created_at": str(d.get("created_at") or ""),
            "updated_at": str(d.get("updated_at") or ""),
        }

    @classmethod
    def _row_to_user_report_detail(cls, row: Any) -> Dict[str, Any]:
        d = dict(row)
        summary = cls._row_to_user_report_summary(d)

        def _safe_json(val: Any) -> List[Any]:
            if isinstance(val, list):
                return val
            if not val:
                return []
            try:
                parsed = json.loads(val)
                return parsed if isinstance(parsed, list) else []
            except Exception:
                return []

        return {
            **summary,
            "birth_date": d.get("birth_date") or "",
            "gender": d.get("gender") or "",
            "postal_code": d.get("postal_code") or "",
            "virtual_data": _safe_json(d.get("virtual_data_json")),
            "real_data": _safe_json(d.get("real_data_json")),
            "personality_analysis": _safe_json(d.get("personality_analysis_json")),
            "charges": _safe_json(d.get("charges_json")),
            "groups": _safe_json(d.get("groups_json")),
            "messages": _safe_json(d.get("messages_json")),
        }

    @classmethod
    def ensure_default_user_report_seeded(cls) -> None:
        """
        Automatically seeds the attached reference file `public/assets/aistudio/890046190_8b7aba55.html`
        (گزارش کاربر: علی اکبر آشوری) into `user_activity_reports` and `identity_profiles` if not yet present.
        """
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) AS cnt FROM user_activity_reports")
            row = cur.fetchone()
            if row and int(row["cnt"]) > 0:
                return

        repo_root = Path(__file__).resolve().parent.parent.parent
        html_path = repo_root / "public" / "assets" / "aistudio" / "890046190_8b7aba55.html"
        if not html_path.is_file():
            return

        try:
            from services.analysis.user_report_analyzer import parse_user_report_html

            html_content = html_path.read_text(encoding="utf-8", errors="ignore")
            parsed = parse_user_report_html(html_content)
            cls.upsert_user_report(
                parsed,
                report_id="user-report-890046190",
                source_filename="890046190_8b7aba55.html",
            )
        except Exception:
            pass

    @classmethod
    def upsert_user_report(
        cls,
        report_data: Dict[str, Any],
        report_id: Optional[str] = None,
        source_filename: str = "",
    ) -> Dict[str, Any]:
        full_name = (report_data.get("full_name") or "").strip() or "کاربر"
        username = (report_data.get("username") or "").strip()
        telegram_id = (report_data.get("telegram_id") or "").strip()
        national_id = (report_data.get("national_id") or "").strip()
        phone_number = (report_data.get("phone_number") or "").strip()
        birth_date = (report_data.get("birth_date") or "").strip()
        gender = (report_data.get("gender") or "").strip()
        postal_code = (report_data.get("postal_code") or "").strip()
        city = (report_data.get("city") or "").strip()
        province = (report_data.get("province") or "").strip()
        final_status = (report_data.get("final_status") or "سیاه").strip()
        header_subtitle = (
            report_data.get("header_subtitle")
            or f"آیدی: {username or '—'} | آیدی تلگرام: {telegram_id or '—'} | استان: {province or '—'} | وضعیت: {final_status}"
        ).strip()

        virtual_data = report_data.get("virtual_data") or []
        real_data = report_data.get("real_data") or []
        personality_analysis = report_data.get("personality_analysis") or []
        charges = report_data.get("charges") or []
        groups = report_data.get("groups") or []
        messages = report_data.get("messages") or []

        with get_db() as conn:
            cur = conn.cursor()
            target_id = report_id
            if not target_id and national_id:
                cur.execute(
                    "SELECT id FROM user_activity_reports WHERE national_id = ? LIMIT 1",
                    (national_id,),
                )
                r = cur.fetchone()
                if r:
                    target_id = r["id"]
            if not target_id and telegram_id:
                cur.execute(
                    "SELECT id FROM user_activity_reports WHERE telegram_id = ? LIMIT 1",
                    (telegram_id,),
                )
                r = cur.fetchone()
                if r:
                    target_id = r["id"]
            if not target_id:
                target_id = f"urep-{uuid.uuid4().hex[:10]}"

            cur.execute("SELECT id FROM user_activity_reports WHERE id = ?", (target_id,))
            exists = cur.fetchone() is not None

            vals = (
                full_name,
                username,
                telegram_id,
                national_id,
                phone_number,
                birth_date,
                gender,
                postal_code,
                city,
                province,
                final_status,
                header_subtitle,
                json.dumps(virtual_data, ensure_ascii=False),
                json.dumps(real_data, ensure_ascii=False),
                json.dumps(personality_analysis, ensure_ascii=False),
                json.dumps(charges, ensure_ascii=False),
                json.dumps(groups, ensure_ascii=False),
                json.dumps(messages, ensure_ascii=False),
                len(charges),
                len(groups),
                len(messages),
                source_filename,
            )

            if exists:
                cur.execute(
                    """
                    UPDATE user_activity_reports SET
                        full_name = ?, username = ?, telegram_id = ?, national_id = ?,
                        phone_number = ?, birth_date = ?, gender = ?, postal_code = ?,
                        city = ?, province = ?, final_status = ?, header_subtitle = ?,
                        virtual_data_json = ?, real_data_json = ?, personality_analysis_json = ?,
                        charges_json = ?, groups_json = ?, messages_json = ?,
                        total_charges = ?, total_groups = ?, total_messages = ?,
                        source_filename = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (*vals, target_id),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO user_activity_reports (
                        id, full_name, username, telegram_id, national_id,
                        phone_number, birth_date, gender, postal_code,
                        city, province, final_status, header_subtitle,
                        virtual_data_json, real_data_json, personality_analysis_json,
                        charges_json, groups_json, messages_json,
                        total_charges, total_groups, total_messages,
                        source_filename
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (target_id, *vals),
                )

            cur.execute("SELECT * FROM user_activity_reports WHERE id = ?", (target_id,))
            saved_row = cur.fetchone()

        # Also sync real/virtual data into identity_profiles so both pages share the dossier
        try:
            name_parts = full_name.split()
            fn = name_parts[0] if name_parts else ""
            ln = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
            charge_titles = [str(c.get("title") or "") for c in charges if c.get("title")]
            jud_summary = f"وضعیت: {final_status}"
            if charge_titles:
                jud_summary += f" | عناوین اتهامی ({len(charge_titles)}): " + " ؛ ".join(charge_titles[:6])
            cls.upsert_identity_profile(
                {
                    "first_name": fn,
                    "last_name": ln,
                    "full_name": full_name,
                    "national_id": national_id,
                    "birth_date": birth_date,
                    "mobile_phone": phone_number,
                    "province": province,
                    "city": city,
                    "postal_code": postal_code.replace(".0", ""),
                    "account_handle": f"@{username.lstrip('@')}" if username else "",
                    "numeric_id": telegram_id,
                    "personal_folder": f"پوشهٔ شخصی: {full_name} ({username or telegram_id})",
                    "thematic_category": "سیاسی" if charges else "اجتماعی",
                    "risk_level": "بحرانی (وضعیت سیاه — اقدام فوری قضایی)" if final_status == "سیاه" else final_status,
                    "judicial_notes": jud_summary,
                }
            )
        except Exception:
            pass

        return cls._row_to_user_report_detail(saved_row)

    @classmethod
    def list_user_reports(cls, query: Optional[str] = None) -> List[Dict[str, Any]]:
        cls.ensure_default_user_report_seeded()
        with get_db() as conn:
            cur = conn.cursor()
            if query and query.strip():
                q = f"%{query.strip()}%"
                cur.execute(
                    """
                    SELECT * FROM user_activity_reports
                    WHERE full_name LIKE ? OR username LIKE ? OR telegram_id LIKE ?
                       OR national_id LIKE ? OR phone_number LIKE ? OR city LIKE ?
                       OR province LIKE ?
                    ORDER BY updated_at DESC, created_at DESC
                    """,
                    (q, q, q, q, q, q, q),
                )
            else:
                cur.execute(
                    "SELECT * FROM user_activity_reports ORDER BY updated_at DESC, created_at DESC"
                )
            return [cls._row_to_user_report_summary(r) for r in cur.fetchall()]

    @classmethod
    def get_user_report(cls, report_id: str) -> Optional[Dict[str, Any]]:
        cls.ensure_default_user_report_seeded()
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM user_activity_reports WHERE id = ?", (report_id,))
            row = cur.fetchone()
            if not row:
                return None
            return cls._row_to_user_report_detail(row)

    @classmethod
    def delete_user_report(cls, report_id: str) -> bool:
        with get_db() as conn:
            cur = conn.execute("DELETE FROM user_activity_reports WHERE id = ?", (report_id,))
            return cur.rowcount > 0



