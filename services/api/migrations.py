import os
import json
import uuid
import shutil
import hashlib
import sqlite3
from datetime import datetime, timezone
from typing import List
from services.api.config import settings
from services.api.database import get_db
from services.api.schemas import (
    LegacyCandidateDTO,
    LegacyMigrationReportDTO,
    LegacyMigrationResultDTO,
    MigrationAuditItemDTO,
)

LEGACY_SEED_TITLES = {
    "یادداشت‌های طراحی و معماری.txt",
    "رنگ، فضا و زندگی روزمره.png",
    "چطور بهتر یاد بگیریم؟.png",
    "گزارش پژوهش‌های هوش مصنوعی.txt",
    "سفر به جنگل‌های شمال.png",
    "دست‌نوشته‌های جلسهٔ محصول.txt",
}


def _compute_file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


class LegacyMigrationManager:
    """
    Safe, non-destructive migration inspector and approved backup+cleanup manager.
    Replaces automatic startup record deletion with:
    1. Read-only inspection / dry-run preview (`inspect_legacy_records`)
    2. Preservation of modified (`is_user_modified == 1`) and ambiguous/user records
    3. Verified backup creation (SQLite snapshot + physical files + SHA-256 verification)
    4. Explicit user approval requirement (`confirm_approval=True`)
    5. Full restoration capability (`restore_backup`) and audit logging (`migration_audit_log`)
    """

    @classmethod
    def inspect_legacy_records(cls, log_dry_run: bool = False) -> LegacyMigrationReportDTO:
        candidates: List[LegacyCandidateDTO] = []
        preserved: List[LegacyCandidateDTO] = []

        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, title, mime_type, storage_path, is_user_modified
                FROM files
                ORDER BY created_at ASC
                """
            )
            rows = cur.fetchall()
            if not rows:
                return LegacyMigrationReportDTO(
                    total_inspected=0,
                    candidate_count=0,
                    preserved_count=0,
                    requires_approval=True,
                    candidates=[],
                    preserved=[],
                )

            all_legacy_unmodified = (
                len(rows) <= 6
                and all(r["title"] in LEGACY_SEED_TITLES and not r["is_user_modified"] for r in rows)
            )

            for r in rows:
                file_id = r["id"]
                title = r["title"]
                mime_type = r["mime_type"]
                path = r["storage_path"]
                is_mod = bool(r["is_user_modified"])

                if is_mod:
                    preserved.append(
                        LegacyCandidateDTO(
                            file_id=file_id,
                            title=title,
                            mime_type=mime_type,
                            classification="preserved_user_modified",
                            reason="رکورد توسط کاربر ویرایش یا تأیید شده است و هرگز حذف نمی‌شود.",
                            is_user_modified=True,
                        )
                    )
                    continue

                is_fake_png = False
                if mime_type == "image/png" and path and os.path.exists(path):
                    try:
                        with open(path, "rb") as f:
                            sig = f.read(8)
                        if sig != b"\x89PNG\r\n\x1a\n":
                            is_fake_png = True
                    except OSError:
                        pass

                if is_fake_png:
                    candidates.append(
                        LegacyCandidateDTO(
                            file_id=file_id,
                            title=title,
                            mime_type=mime_type,
                            classification="candidate_fake_png",
                            reason="فایل نمونهٔ قدیمی با پسوند PNG که محتوای متنی غیرتصویری دارد و توسط کاربر ویرایش نشده است.",
                            is_user_modified=False,
                        )
                    )
                elif all_legacy_unmodified and not settings.demo_mode:
                    candidates.append(
                        LegacyCandidateDTO(
                            file_id=file_id,
                            title=title,
                            mime_type=mime_type,
                            classification="candidate_untouched_seed",
                            reason="رکورد نمونهٔ اولیهٔ دست‌نخورده از نسخهٔ آزمایشی پیشین.",
                            is_user_modified=False,
                        )
                    )
                else:
                    preserved.append(
                        LegacyCandidateDTO(
                            file_id=file_id,
                            title=title,
                            mime_type=mime_type,
                            classification="preserved_genuine_or_ambiguous",
                            reason="فایل معتبر کاربر یا رکورد دارای ابهام که برای حفاظت از داده حفظ می‌شود.",
                            is_user_modified=False,
                        )
                    )

            if log_dry_run:
                audit_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO migration_audit_log (
                        id, operation_type, affected_count, preserved_count, details_json
                    ) VALUES (?, 'DRY_RUN', ?, ?, ?)
                    """,
                    (
                        audit_id,
                        len(candidates),
                        len(preserved),
                        json.dumps(
                            {
                                "candidates": [c.model_dump() for c in candidates],
                                "preserved": [p.model_dump() for p in preserved],
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )

        return LegacyMigrationReportDTO(
            total_inspected=len(rows),
            candidate_count=len(candidates),
            preserved_count=len(preserved),
            requires_approval=True,
            candidates=candidates,
            preserved=preserved,
        )

    @classmethod
    def execute_approved_cleanup(cls, confirm_approval: bool = False) -> LegacyMigrationResultDTO:
        if not confirm_approval:
            raise PermissionError(
                "حذف رکوردهای قدیمی بدون تأیید صریح کاربر (confirm_approval=True) مجاز نیست."
            )

        report = cls.inspect_legacy_records(log_dry_run=False)
        audit_id = str(uuid.uuid4())

        if report.candidate_count == 0:
            with get_db() as conn:
                conn.execute(
                    """
                    INSERT INTO migration_audit_log (
                        id, operation_type, affected_count, preserved_count, details_json
                    ) VALUES (?, 'APPROVED_LEGACY_CLEANUP_NOOP', 0, ?, ?)
                    """,
                    (audit_id, report.preserved_count, json.dumps({"note": "No legacy candidates found"})),
                )
            return LegacyMigrationResultDTO(
                executed=True,
                removed_count=0,
                preserved_count=report.preserved_count,
                backup_id=None,
                backup_path=None,
                audit_id=audit_id,
                message="هیچ رکورد قدیمی نیازمند پاک‌سازی یافت نشد. تمام فایل‌ها حفظ شدند.",
            )

        # 1. Create a verified backup before any destructive action
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_id = f"{timestamp}_{uuid.uuid4().hex[:8]}"
        backup_dir = os.path.join(settings.backup_dir, f"migration_{backup_id}")
        files_backup_dir = os.path.join(backup_dir, "files")
        os.makedirs(files_backup_dir, exist_ok=True)

        # Backup SQLite database using SQLite's online backup API
        db_backup_path = os.path.join(backup_dir, "saher_pre_migration.db")
        with get_db() as conn:
            bck_conn = sqlite3.connect(db_backup_path)
            try:
                conn.backup(bck_conn)
            finally:
                bck_conn.close()

        if not os.path.exists(db_backup_path) or os.path.getsize(db_backup_path) == 0:
            raise RuntimeError("پشتیبان‌گیری از پایگاه‌داده پیش از مهاجرت با خطا مواجه شد؛ عملیات لغو گردید.")

        db_backup_sha256 = _compute_file_sha256(db_backup_path)

        candidate_ids = {c.file_id for c in report.candidates}
        backed_up_records = []

        with get_db() as conn:
            cur = conn.cursor()
            for file_id in candidate_ids:
                cur.execute("SELECT * FROM files WHERE id = ? AND is_user_modified = 0", (file_id,))
                f_row = cur.fetchone()
                if not f_row:
                    continue

                cur.execute("SELECT * FROM documents WHERE file_id = ?", (file_id,))
                doc_row = cur.fetchone()

                cur.execute(
                    """
                    SELECT t.name FROM tags t
                    JOIN file_tags ft ON t.id = ft.tag_id
                    WHERE ft.file_id = ?
                    """,
                    (file_id,),
                )
                tags = [r[0] for r in cur.fetchall()]

                orig_path = f_row["storage_path"]
                copied_file_name = None
                copied_sha256 = None

                if orig_path and os.path.exists(orig_path):
                    orig_sha = _compute_file_sha256(orig_path)
                    copied_file_name = os.path.basename(orig_path)
                    dest_path = os.path.join(files_backup_dir, copied_file_name)
                    shutil.copy2(orig_path, dest_path)
                    copied_sha256 = _compute_file_sha256(dest_path)
                    if copied_sha256 != orig_sha:
                        raise RuntimeError(
                            f"عدم تطابق هش فایل پشتیبان برای «{f_row['title']}»؛ عملیات حذف متوقف شد."
                        )

                backed_up_records.append(
                    {
                        "file": dict(f_row),
                        "document": dict(doc_row) if doc_row else None,
                        "tags": tags,
                        "backed_up_filename": copied_file_name,
                        "backed_up_sha256": copied_sha256,
                    }
                )

            manifest_path = os.path.join(backup_dir, "manifest.json")
            manifest_data = {
                "backup_id": backup_id,
                "created_at": timestamp,
                "db_backup_sha256": db_backup_sha256,
                "records": backed_up_records,
            }
            with open(manifest_path, "w", encoding="utf-8") as mf:
                json.dump(manifest_data, mf, ensure_ascii=False, indent=2, default=str)

            # Verify manifest is readable before deleting anything
            with open(manifest_path, "r", encoding="utf-8") as mf:
                verified_manifest = json.load(mf)
            if len(verified_manifest.get("records", [])) != len(backed_up_records):
                raise RuntimeError("تأیید صحت مانیفست پشتیبان ناموفق بود؛ عملیات حذف متوقف شد.")

            # 2. Perform approved deletion of only verified unmodified candidates
            removed_count = 0
            for rec in backed_up_records:
                f_data = rec["file"]
                fid = f_data["id"]
                path = f_data.get("storage_path")
                cur.execute("DELETE FROM files_fts WHERE file_id = ?", (fid,))
                cur.execute("DELETE FROM files WHERE id = ? AND is_user_modified = 0", (fid,))
                if cur.rowcount == 1:
                    removed_count += 1
                    if path and os.path.exists(path):
                        try:
                            os.remove(path)
                        except OSError:
                            pass

            conn.execute(
                """
                INSERT INTO migration_audit_log (
                    id, operation_type, backup_id, backup_path, affected_count, preserved_count, details_json
                ) VALUES (?, 'APPROVED_LEGACY_CLEANUP', ?, ?, ?, ?, ?)
                """,
                (
                    audit_id,
                    backup_id,
                    backup_dir,
                    removed_count,
                    report.preserved_count,
                    json.dumps(
                        {
                            "removed_ids": [r["file"]["id"] for r in backed_up_records],
                            "backup_id": backup_id,
                        },
                        ensure_ascii=False,
                    ),
                ),
            )

        return LegacyMigrationResultDTO(
            executed=True,
            removed_count=removed_count,
            preserved_count=report.preserved_count,
            backup_id=backup_id,
            backup_path=backup_dir,
            audit_id=audit_id,
            message=f"{removed_count} رکورد نمونهٔ قدیمی پس از تهیهٔ نسخهٔ پشتیبان تأییدشده ({backup_id}) پاک‌سازی شد.",
        )

    @classmethod
    def restore_backup(cls, backup_id: str) -> LegacyMigrationResultDTO:
        backup_dir = os.path.join(settings.backup_dir, f"migration_{backup_id}")
        manifest_path = os.path.join(backup_dir, "manifest.json")
        if not os.path.exists(manifest_path):
            raise FileNotFoundError(f"نسخهٔ پشتیبان مهاجرت با شناسهٔ «{backup_id}» یافت نشد.")

        with open(manifest_path, "r", encoding="utf-8") as mf:
            manifest = json.load(mf)

        records = manifest.get("records", [])
        files_backup_dir = os.path.join(backup_dir, "files")
        restored_count = 0
        audit_id = str(uuid.uuid4())

        from services.api.repository import ArchiveRepository

        with get_db() as conn:
            cur = conn.cursor()
            for rec in records:
                f_data = rec["file"]
                doc_data = rec.get("document")
                tags = rec.get("tags", [])
                backed_up_filename = rec.get("backed_up_filename")
                expected_sha = rec.get("backed_up_sha256")

                target_storage_path = f_data["storage_path"]
                if backed_up_filename:
                    src_file = os.path.join(files_backup_dir, backed_up_filename)
                    if os.path.exists(src_file):
                        actual_sha = _compute_file_sha256(src_file)
                        if expected_sha and actual_sha != expected_sha:
                            raise RuntimeError("هش فایل پشتیبان هنگام بازیابی معتبر نیست.")
                        os.makedirs(os.path.dirname(target_storage_path), exist_ok=True)
                        shutil.copy2(src_file, target_storage_path)

                cur.execute("SELECT id FROM files WHERE id = ?", (f_data["id"],))
                if cur.fetchone():
                    continue

                cur.execute(
                    """
                    INSERT INTO files (
                        id, archive_id, title, kind, topic, status, mime_type,
                        file_size, sha256, storage_path, color_scheme, error_code, error_message, is_user_modified
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f_data["id"],
                        f_data.get("archive_id", "default"),
                        f_data["title"],
                        f_data["kind"],
                        f_data.get("topic", "کار"),
                        f_data.get("status", "آماده"),
                        f_data["mime_type"],
                        f_data["file_size"],
                        f_data["sha256"],
                        target_storage_path,
                        f_data.get("color_scheme", "paper"),
                        f_data.get("error_code"),
                        f_data.get("error_message"),
                        f_data.get("is_user_modified", 0),
                    ),
                )

                if doc_data:
                    cur.execute(
                        """
                        INSERT INTO documents (
                            id, file_id, extracted_text, summary, page_count,
                            extraction_status, extraction_method, system_note
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            doc_data["id"],
                            f_data["id"],
                            doc_data.get("extracted_text", ""),
                            doc_data.get("summary"),
                            doc_data.get("page_count", 1),
                            doc_data.get("extraction_status", "extracted"),
                            doc_data.get("extraction_method", "direct_text"),
                            doc_data.get("system_note"),
                        ),
                    )

                ArchiveRepository.set_file_tags(conn, f_data["id"], tags)
                extracted_txt = doc_data.get("extracted_text", "") if doc_data else ""
                ArchiveRepository.update_fts(
                    conn,
                    f_data["id"],
                    f_data["title"],
                    extracted_txt,
                    f_data.get("topic", "کار"),
                    tags,
                )
                restored_count += 1

            conn.execute(
                """
                INSERT INTO migration_audit_log (
                    id, operation_type, backup_id, backup_path, affected_count, preserved_count, details_json
                ) VALUES (?, 'RESTORE_BACKUP', ?, ?, ?, 0, ?)
                """,
                (
                    audit_id,
                    backup_id,
                    backup_dir,
                    restored_count,
                    json.dumps({"restored_count": restored_count}, ensure_ascii=False),
                ),
            )

        return LegacyMigrationResultDTO(
            executed=True,
            removed_count=restored_count,
            preserved_count=0,
            backup_id=backup_id,
            backup_path=backup_dir,
            audit_id=audit_id,
            message=f"{restored_count} رکورد از نسخهٔ پشتیبان ({backup_id}) با موفقیت بازیابی شد.",
        )

    @classmethod
    def list_audits(cls) -> List[MigrationAuditItemDTO]:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, operation_type, backup_id, backup_path,
                       affected_count, preserved_count, created_at
                FROM migration_audit_log
                ORDER BY created_at DESC, rowid DESC
                LIMIT 50
                """
            )
            return [
                MigrationAuditItemDTO(
                    id=r["id"],
                    operation_type=r["operation_type"],
                    backup_id=r["backup_id"],
                    backup_path=r["backup_path"],
                    affected_count=r["affected_count"],
                    preserved_count=r["preserved_count"],
                    created_at=str(r["created_at"]),
                )
                for r in cur.fetchall()
            ]
