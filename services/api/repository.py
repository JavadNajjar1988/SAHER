import os
import hashlib
import uuid
import mimetypes
from typing import List, Optional
import sqlite3
from services.api.config import settings
from services.api.database import get_db
from services.api.schemas import FileItemDTO, StatsDTO
from services.ingestion.extractor import extract_text_from_file

def calculate_sha256(file_path: str) -> str:
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            sha.update(chunk)
    return sha.hexdigest()

def detect_kind(mime_type: str, filename: str) -> str:
    lower_name = filename.lower()
    if mime_type.startswith("image/"):
        if "screenshot" in lower_name or "اسکرین" in lower_name:
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

class ArchiveRepository:
    @staticmethod
    def get_file_tags(conn: sqlite3.Connection, file_id: str) -> List[str]:
        cur = conn.cursor()
        cur.execute("""
            SELECT t.name FROM tags t
            JOIN file_tags ft ON t.id = ft.tag_id
            WHERE ft.file_id = ?
            ORDER BY t.name ASC
        """, (file_id,))
        return [row[0] for row in cur.fetchall()]

    @staticmethod
    def set_file_tags(conn: sqlite3.Connection, file_id: str, tag_names: List[str]) -> None:
        cur = conn.cursor()
        # Remove existing associations
        cur.execute("DELETE FROM file_tags WHERE file_id = ?", (file_id,))
        
        for name in tag_names:
            clean_name = name.strip()
            if not clean_name:
                continue
            cur.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (clean_name,))
            cur.execute("SELECT id FROM tags WHERE name = ?", (clean_name,))
            tag_id = cur.fetchone()[0]
            cur.execute("INSERT OR IGNORE INTO file_tags (file_id, tag_id) VALUES (?, ?)", (file_id, tag_id))

    @staticmethod
    def update_fts(conn: sqlite3.Connection, file_id: str, title: str, text: str, topic: str, tags: List[str]) -> None:
        cur = conn.cursor()
        cur.execute("DELETE FROM files_fts WHERE file_id = ?", (file_id,))
        cur.execute("""
            INSERT INTO files_fts (file_id, title, extracted_text, topic, tags)
            VALUES (?, ?, ?, ?, ?)
        """, (file_id, title, text, topic, " ".join(tags)))

    @classmethod
    def list_files(
        cls,
        kind: Optional[str] = None,
        query: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100
    ) -> List[FileItemDTO]:
        with get_db() as conn:
            cur = conn.cursor()
            
            # If query provided, use FTS5 for search
            if query and query.strip():
                clean_q = query.strip().replace('"', '""')
                fts_query = f'"{clean_q}"*'
                cur.execute("""
                    SELECT f.id, f.archive_id, f.title, f.kind, f.topic, f.status,
                           f.mime_type, f.file_size, f.sha256, d.extracted_text, f.color_scheme,
                           d.page_count, f.created_at, f.error_message
                    FROM files_fts s
                    JOIN files f ON s.file_id = f.id
                    LEFT JOIN documents d ON f.id = d.file_id
                    WHERE files_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                """, (fts_query, limit))
                rows = cur.fetchall()
            else:
                sql = """
                    SELECT f.id, f.archive_id, f.title, f.kind, f.topic, f.status,
                           f.mime_type, f.file_size, f.sha256, d.extracted_text, f.color_scheme,
                           d.page_count, f.created_at, f.error_message
                    FROM files f
                    LEFT JOIN documents d ON f.id = d.file_id
                    WHERE 1=1
                """
                params = []
                if kind and kind != "همهٔ فایل‌ها":
                    sql += " AND f.kind = ?"
                    params.append(kind)
                if status:
                    sql += " AND f.status = ?"
                    params.append(status)
                sql += " ORDER BY f.created_at DESC LIMIT ?"
                params.append(limit)
                
                cur.execute(sql, params)
                rows = cur.fetchall()

            items = []
            for r in rows:
                tags = cls.get_file_tags(conn, r["id"])
                items.append(FileItemDTO(
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
                    color=r["color_scheme"] or "paper",
                    tags=tags,
                    page_count=r["page_count"] or 1,
                    created_at=str(r["created_at"]),
                    error_message=r["error_message"]
                ))
            return items

    @classmethod
    def get_file(cls, file_id: str) -> Optional[FileItemDTO]:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT f.id, f.archive_id, f.title, f.kind, f.topic, f.status,
                       f.mime_type, f.file_size, f.sha256, d.extracted_text, f.color_scheme,
                       d.page_count, f.created_at, f.error_message
                FROM files f
                LEFT JOIN documents d ON f.id = d.file_id
                WHERE f.id = ?
            """, (file_id,))
            r = cur.fetchone()
            if not r:
                return None
            tags = cls.get_file_tags(conn, file_id)
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
                color=r["color_scheme"] or "paper",
                tags=tags,
                page_count=r["page_count"] or 1,
                created_at=str(r["created_at"]),
                error_message=r["error_message"]
            )

    @classmethod
    def save_imported_file(
        cls,
        filename: str,
        content: bytes,
        archive_id: str = "default",
        custom_topic: Optional[str] = None
    ) -> FileItemDTO:
        file_id = str(uuid.uuid4())
        mime_type, _ = mimetypes.guess_type(filename)
        mime_type = mime_type or "application/octet-stream"
        kind = detect_kind(mime_type, filename)
        color = detect_color_scheme(kind, filename)
        topic = custom_topic or ("طراحی" if "طراحی" in filename else "کار")

        # Create physical storage path
        ext = os.path.splitext(filename)[1]
        stored_filename = f"{file_id}{ext}"
        storage_path = os.path.join(settings.storage_dir, stored_filename)

        with open(storage_path, "wb") as f:
            f.write(content)

        file_size = len(content)
        sha256_hash = calculate_sha256(storage_path)

        # Check for duplicate
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM files WHERE sha256 = ?", (sha256_hash,))
            duplicate = cur.fetchone()
            default_tags = []
            if duplicate:
                status = "نیازمند بازبینی"
                default_tags.append("فایل تکراری")
            else:
                status = "آماده"

            # Extract available text
            extracted_text, page_count, extraction_method = extract_text_from_file(storage_path, mime_type)
            if extraction_method == "pdf_needs_ocr" or extraction_method == "image_pending_ocr":
                status = "نیازمند بازبینی"
            elif extraction_method == "error":
                status = "تحلیل ناقص"

            # Auto-tagging based on content and file characteristics
            if "هوش مصنوعی" in filename or "هوش مصنوعی" in extracted_text:
                default_tags.append("هوش مصنوعی")
            if "طراحی" in filename or "معماری" in filename:
                default_tags.append("طراحی محصول")

            # Persist File Record
            cur.execute("""
                INSERT INTO files (
                    id, archive_id, title, kind, topic, status, mime_type,
                    file_size, sha256, storage_path, color_scheme
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                file_id, archive_id, filename, kind, topic, status,
                mime_type, file_size, sha256_hash, storage_path, color
            ))

            # Persist Document Record
            doc_id = str(uuid.uuid4())
            cur.execute("""
                INSERT INTO documents (
                    id, file_id, extracted_text, page_count, extraction_method
                ) VALUES (?, ?, ?, ?, ?)
            """, (doc_id, file_id, extracted_text, page_count, extraction_method))

            # Persist Tags
            cls.set_file_tags(conn, file_id, default_tags)

            # Update FTS
            cls.update_fts(conn, file_id, filename, extracted_text, topic, default_tags)

        return cls.get_file(file_id)

    @classmethod
    def update_file(
        cls,
        file_id: str,
        topic: Optional[str] = None,
        status: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> Optional[FileItemDTO]:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT title, topic, status FROM files WHERE id = ?", (file_id,))
            file_row = cur.fetchone()
            if not file_row:
                return None
            
            new_topic = topic if topic is not None else file_row["topic"]
            new_status = status if status is not None else file_row["status"]

            cur.execute("""
                UPDATE files
                SET topic = ?, status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (new_topic, new_status, file_id))

            if tags is not None:
                cls.set_file_tags(conn, file_id, tags)

            cur.execute("SELECT extracted_text FROM documents WHERE file_id = ?", (file_id,))
            doc_row = cur.fetchone()
            text = doc_row["extracted_text"] if doc_row else ""
            current_tags = cls.get_file_tags(conn, file_id)

            cls.update_fts(conn, file_id, file_row["title"], text, new_topic, current_tags)

        return cls.get_file(file_id)

    @classmethod
    def get_stats(cls) -> StatsDTO:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM files")
            total = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM files WHERE status = 'آماده'")
            ready = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM files WHERE status != 'آماده'")
            attention = cur.fetchone()[0]

            return StatsDTO(
                total_files=total,
                ready_files=ready,
                attention_files=attention
            )
            
    @classmethod
    def seed_initial_records_if_empty(cls) -> None:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM files")
            count = cur.fetchone()[0]
            if count > 0:
                return

        initial_seeds = [
            {
                "title": "یادداشت‌های طراحی و معماری.txt",
                "content": "طراحی خوب از شناخت مسئله آغاز می‌شود. در این یادداشت، اصول طراحی یک محصول ساده، خوانا و قابل استفاده را مرور می‌کنیم.\nساهر بر اصل حریم خصوصی محلی و سادگی کاربری تمرکز دارد.",
                "topic": "طراحی",
                "kind": "سند",
                "tags": ["طراحی محصول", "یادداشت"],
                "color": "paper"
            },
            {
                "title": "رنگ، فضا و زندگی روزمره.png",
                "content": "تصویری از یک فضای آرام با نور طبیعی، دیوارهای روشن و جزئیات سبز. این توصیف، برداشت اولیهٔ مدل است.",
                "topic": "معماری",
                "kind": "تصویر",
                "tags": ["فضای داخلی", "الهام"],
                "color": "room"
            },
            {
                "title": "چطور بهتر یاد بگیریم؟.png",
                "content": "یادگیری عمیق با تمرین‌های کوتاه و پیوسته شکل می‌گیرد. بین مطالعه‌ها فاصله بگذارید و آنچه آموخته‌اید را با زبان خودتان بازگو کنید.",
                "topic": "آموزش",
                "kind": "اسکرین‌شات",
                "tags": ["یادگیری", "مطالعه"],
                "color": "social"
            },
            {
                "title": "گزارش پژوهش‌های هوش مصنوعی.txt",
                "content": "این گزارش به بررسی کاربرد مدل‌های زبانی در دسته‌بندی و بازیابی اسناد می‌پردازد.\nبازیابی ترکیبی هیبریدی شامل FTS5 و بردارها به جستجوی بهینه کمک می‌کند.",
                "topic": "فناوری",
                "kind": "سند",
                "tags": ["پژوهش", "هوش مصنوعی"],
                "color": "report"
            },
            {
                "title": "سفر به جنگل‌های شمال.png",
                "content": "جنگلی مه‌آلود با درختان بلند و مسیر باریک میان پوشش سبز.",
                "topic": "زندگی",
                "kind": "تصویر",
                "tags": ["طبیعت", "سفر"],
                "color": "forest"
            },
            {
                "title": "دست‌نوشته‌های جلسهٔ محصول.txt",
                "content": "موضوع جلسه، ساده‌سازی ورود فایل و نمایش روشن وضعیت پردازش بود. بخشی از نوشته در نمونه خوانا نیست و نیاز به بازبینی دارد.",
                "topic": "کار",
                "kind": "سند",
                "tags": ["جلسه", "محصول"],
                "color": "notes"
            }
        ]

        for s in initial_seeds:
            cls.save_imported_file(
                filename=s["title"],
                content=s["content"].encode("utf-8"),
                custom_topic=s["topic"]
            )
