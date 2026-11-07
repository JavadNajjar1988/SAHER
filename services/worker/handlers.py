import os
import time
import uuid
import hashlib
import logging
import sqlite3
from typing import Optional, List
from services.api.database import get_db
from services.api.schemas import JobItemDTO
from services.ingestion.extractor import (
    validate_file_signature,
    extract_document_content,
    normalize_for_fts,
)
from services.worker.lifecycle import (
    ProcessingStage,
    RetryableJobError,
    PermanentJobError,
    JobInterruptedException,
)
from services.worker.queue import JobQueueRepository

logger = logging.getLogger("saher.worker")


def _compute_sha256_on_disk(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def execute_job_pipeline(
    job: JobItemDTO,
    worker_id: str,
    stage_throttle_seconds: float = 0.0,
    lease_seconds: int = 30,
) -> Optional[JobItemDTO]:
    """
    Executes a claimed durable job through SAHER's Milestone 2 processing stages:
    DISCOVERY -> VALIDATION -> EXTRACTION -> (OCR_PENDING | ANALYSIS_PENDING | INDEXING -> FINALIZATION)

    Key guarantees:
    - Never fabricates OCR or Vision output; images and scanned PDFs remain at `OCR_PENDING` / `ANALYSIS_PENDING`
      with file-level `extraction_status = 'pending_ocr'`.
    - Preserves user modifications (`is_user_modified = 1`) on topic, tags, and status during reanalysis.
    - Preserves previously extracted valid text if a reanalysis attempt fails mid-flight.
    - Updates FTS5 (`files_fts`) idempotently without duplicating records.
    """
    from services.api.repository import ArchiveRepository

    job_id = job.id
    file_id = job.file_id
    completed_stages: List[str] = list(job.checkpoint.get("completed_stages", []))

    try:
        # 1. Stage: DISCOVERY
        JobQueueRepository.update_stage_and_heartbeat(
            job_id=job_id,
            worker_id=worker_id,
            stage=ProcessingStage.DISCOVERY.value,
            progress=10.0,
            progress_message="بررسی متادیتا و موقعیت فیزیکی فایل در مخزن محلی…",
            lease_seconds=lease_seconds,
        )
        if stage_throttle_seconds > 0:
            time.sleep(stage_throttle_seconds)

        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT f.id, f.title, f.kind, f.topic, f.status, f.mime_type,
                       f.file_size, f.sha256, f.storage_path, f.is_user_modified,
                       f.processing_version
                FROM files f
                WHERE f.id = ?
                """,
                (file_id,),
            )
            file_row = cur.fetchone()
            if not file_row:
                raise PermanentJobError("FILE_RECORD_MISSING", "رکورد فایل در پایگاه‌داده یافت نشد.")

            # Mark file as currently processing ONLY if it does not already have 'آماده' or user modification
            if not file_row["is_user_modified"] and file_row["status"] == "در صف":
                cur.execute(
                    "UPDATE files SET status = 'در حال پردازش', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (file_id,),
                )

        storage_path = file_row["storage_path"]
        title = file_row["title"]
        expected_sha256 = file_row["sha256"]

        if not storage_path or not os.path.exists(storage_path):
            raise RetryableJobError(
                "STORAGE_FILE_UNAVAILABLE",
                "فایل فیزیکی در مسیر مخزن در دسترس نیست.",
            )

        if ProcessingStage.DISCOVERY.value not in completed_stages:
            completed_stages.append(ProcessingStage.DISCOVERY.value)

        # 2. Stage: VALIDATION
        JobQueueRepository.update_stage_and_heartbeat(
            job_id=job_id,
            worker_id=worker_id,
            stage=ProcessingStage.VALIDATION.value,
            progress=25.0,
            progress_message="اعتبارسنجی امضای باینری و یکپارچگی هش SHA-256…",
            lease_seconds=lease_seconds,
            checkpoint_updates={"completed_stages": completed_stages},
        )
        if stage_throttle_seconds > 0:
            time.sleep(stage_throttle_seconds)

        try:
            disk_sha256 = _compute_sha256_on_disk(storage_path)
        except OSError as exc:
            raise RetryableJobError(
                "STORAGE_READ_ERROR",
                "خطای موقت در خواندن فایل از دیسک محلی.",
            ) from exc

        if expected_sha256 and disk_sha256 != expected_sha256:
            raise PermanentJobError(
                "SHA256_INTEGRITY_MISMATCH",
                "عدم تطابق هش SHA-256 فایل روی دیسک با هش ثبت‌شده در آرشیو.",
            )

        is_valid, detected_mime, sig_error = validate_file_signature(storage_path, title)
        if not is_valid:
            raise PermanentJobError(
                "INVALID_FILE_SIGNATURE",
                sig_error or "امضای باینری فایل نامعتبر است.",
            )

        if ProcessingStage.VALIDATION.value not in completed_stages:
            completed_stages.append(ProcessingStage.VALIDATION.value)

        # 3. Stage: EXTRACTION
        JobQueueRepository.update_stage_and_heartbeat(
            job_id=job_id,
            worker_id=worker_id,
            stage=ProcessingStage.EXTRACTION.value,
            progress=55.0,
            progress_message="استخراج متن و ساختار صفحات سند…",
            lease_seconds=lease_seconds,
            checkpoint_updates={"completed_stages": completed_stages, "detected_mime": detected_mime},
        )
        if stage_throttle_seconds > 0:
            time.sleep(stage_throttle_seconds)

        extraction = extract_document_content(storage_path, detected_mime, filename=title)
        if extraction.extraction_status == "failed":
            raise PermanentJobError(
                extraction.error_code or "EXTRACTION_FAILED",
                extraction.error_message or "خطا در استخراج محتوای فایل.",
            )
        if extraction.extraction_status == "unsupported":
            raise PermanentJobError(
                extraction.error_code or "UNSUPPORTED_FORMAT",
                extraction.error_message or "فرمت فایل برای استخراج متن پشتیبانی نمی‌شود.",
            )

        if ProcessingStage.EXTRACTION.value not in completed_stages:
            completed_stages.append(ProcessingStage.EXTRACTION.value)

        # 4. Handle Pending OCR / Vision Analysis vs Extracted Text Indexing
        is_pending_ocr = extraction.extraction_status == "pending_ocr"
        if is_pending_ocr:
            pending_stage = (
                ProcessingStage.ANALYSIS_PENDING.value
                if job.target_stage == ProcessingStage.ANALYSIS_PENDING.value
                else ProcessingStage.OCR_PENDING.value
            )
            JobQueueRepository.update_stage_and_heartbeat(
                job_id=job_id,
                worker_id=worker_id,
                stage=pending_stage,
                progress=85.0,
                progress_message="ثبت وضعیت انتظار OCR / تحلیل دیداری آفلاین و بروزرسانی نمایهٔ عنوان…",
                lease_seconds=lease_seconds,
                checkpoint_updates={
                    "completed_stages": completed_stages,
                    "extraction_status": "pending_ocr",
                },
            )

            with get_db() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT title, topic, status, is_user_modified FROM files WHERE id = ?",
                    (file_id,),
                )
                fresh_file = cur.fetchone()
                is_mod = bool(fresh_file["is_user_modified"])
                final_topic = fresh_file["topic"]
                final_status = fresh_file["status"] if is_mod else extraction.recommended_file_status

                cur.execute("SELECT id, extracted_text, extraction_version FROM documents WHERE file_id = ?", (file_id,))
                doc_row = cur.fetchone()
                if doc_row:
                    # Preserve any previously extracted text if present, otherwise empty
                    preserved_text = doc_row["extracted_text"] or ""
                    new_ext_ver = int(doc_row["extraction_version"] or 1) + 1
                    cur.execute(
                        """
                        UPDATE documents
                        SET page_count = ?,
                            extraction_status = 'pending_ocr',
                            extraction_method = ?,
                            extraction_version = ?,
                            system_note = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE file_id = ?
                        """,
                        (
                            extraction.page_count,
                            extraction.extraction_method,
                            new_ext_ver,
                            extraction.system_note,
                            file_id,
                        ),
                    )
                else:
                    preserved_text = ""
                    doc_id = str(uuid.uuid4())
                    cur.execute(
                        """
                        INSERT INTO documents (
                            id, file_id, extracted_text, page_count,
                            extraction_status, extraction_method, extraction_version, system_note
                        ) VALUES (?, ?, '', ?, 'pending_ocr', ?, 1, ?)
                        """,
                        (
                            doc_id,
                            file_id,
                            extraction.page_count,
                            extraction.extraction_method,
                            extraction.system_note,
                        ),
                    )

                cur.execute(
                    """
                    UPDATE files
                    SET status = ?,
                        error_code = NULL,
                        error_message = NULL,
                        processing_version = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (final_status, job.processing_version, file_id),
                )

                current_tags = ArchiveRepository.get_file_tags(conn, file_id)
                ArchiveRepository.update_fts(
                    conn,
                    file_id,
                    fresh_file["title"],
                    preserved_text,
                    final_topic,
                    current_tags,
                )

            completed_stages.append(pending_stage)
            return JobQueueRepository.mark_job_completed(
                job_id=job_id,
                worker_id=worker_id,
                final_stage=pending_stage,
                progress_message="اعتبارسنجی باینری تکمیل شد؛ در انتظار موتور OCR / تحلیل دیداری آفلاین.",
                checkpoint_updates={"completed_stages": completed_stages},
            )

        # 5. Stage: INDEXING (for documents with extracted or empty text)
        JobQueueRepository.update_stage_and_heartbeat(
            job_id=job_id,
            worker_id=worker_id,
            stage=ProcessingStage.INDEXING.value,
            progress=80.0,
            progress_message="نمایه‌سازی متن فارسی در پایگاه‌داده و موتور جست‌وجوی FTS5…",
            lease_seconds=lease_seconds,
            checkpoint_updates={"completed_stages": completed_stages},
        )
        if stage_throttle_seconds > 0:
            time.sleep(stage_throttle_seconds)

        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT title, topic, status, is_user_modified FROM files WHERE id = ?",
                (file_id,),
            )
            fresh_file = cur.fetchone()
            if not fresh_file:
                raise PermanentJobError("FILE_RECORD_MISSING", "رکورد فایل هنگام نمایه‌سازی یافت نشد.")

            is_mod = bool(fresh_file["is_user_modified"])
            final_topic = fresh_file["topic"]
            final_status = (
                fresh_file["status"]
                if (is_mod and fresh_file["status"] in ("آماده", "نیازمند بازبینی"))
                else extraction.recommended_file_status
            )

            cur.execute("SELECT id, extraction_version FROM documents WHERE file_id = ?", (file_id,))
            doc_row = cur.fetchone()
            if doc_row:
                doc_id = doc_row["id"]
                base_ver = int(doc_row["extraction_version"]) if doc_row["extraction_version"] is not None else 0
                new_ext_ver = base_ver + 1
                cur.execute(
                    """
                    UPDATE documents
                    SET extracted_text = ?,
                        page_count = ?,
                        extraction_status = ?,
                        extraction_method = ?,
                        extraction_version = ?,
                        system_note = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        extraction.extracted_text,
                        extraction.page_count,
                        extraction.extraction_status,
                        extraction.extraction_method,
                        new_ext_ver,
                        extraction.system_note,
                        doc_id,
                    ),
                )
            else:
                doc_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO documents (
                        id, file_id, extracted_text, page_count,
                        extraction_status, extraction_method, extraction_version, system_note
                    ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                    """,
                    (
                        doc_id,
                        file_id,
                        extraction.extracted_text,
                        extraction.page_count,
                        extraction.extraction_status,
                        extraction.extraction_method,
                        extraction.system_note,
                    ),
                )

            # Idempotently replace page records for this file
            cur.execute("DELETE FROM pages WHERE file_id = ?", (file_id,))
            for idx, page_text in enumerate(extraction.pages, start=1):
                cur.execute(
                    """
                    INSERT INTO pages (
                        id, document_id, file_id, page_number, raw_text, normalized_text
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        doc_id,
                        file_id,
                        idx,
                        page_text,
                        normalize_for_fts(page_text),
                    ),
                )

            # Preserve user tags if modified; otherwise add auto-detected tags without wiping existing ones
            current_tags = ArchiveRepository.get_file_tags(conn, file_id)
            if not is_mod:
                merged_tags = list(current_tags)
                if ("هوش مصنوعی" in fresh_file["title"] or "هوش مصنوعی" in extraction.extracted_text) and "هوش مصنوعی" not in merged_tags:
                    merged_tags.append("هوش مصنوعی")
                if ("طراحی" in fresh_file["title"] or "معماری" in fresh_file["title"]) and "طراحی محصول" not in merged_tags:
                    merged_tags.append("طراحی محصول")
                if merged_tags != current_tags:
                    ArchiveRepository.set_file_tags(conn, file_id, merged_tags)
                    current_tags = merged_tags

            cur.execute(
                """
                UPDATE files
                SET status = ?,
                    error_code = NULL,
                    error_message = NULL,
                    processing_version = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (final_status, job.processing_version, file_id),
            )

            ArchiveRepository.update_fts(
                conn,
                file_id,
                fresh_file["title"],
                extraction.extracted_text,
                final_topic,
                current_tags,
            )

        if ProcessingStage.INDEXING.value not in completed_stages:
            completed_stages.append(ProcessingStage.INDEXING.value)

        # 6. Stage: FINALIZATION
        JobQueueRepository.update_stage_and_heartbeat(
            job_id=job_id,
            worker_id=worker_id,
            stage=ProcessingStage.FINALIZATION.value,
            progress=95.0,
            progress_message="نهایی‌سازی متادیتا و ثبت نسخهٔ پردازش…",
            lease_seconds=lease_seconds,
            checkpoint_updates={"completed_stages": completed_stages},
        )
        completed_stages.append(ProcessingStage.FINALIZATION.value)

        return JobQueueRepository.mark_job_completed(
            job_id=job_id,
            worker_id=worker_id,
            final_stage=ProcessingStage.FINALIZATION.value,
            progress_message="استخراج متن و نمایه‌سازی FTS5 با موفقیت تکمیل شد.",
            checkpoint_updates={"completed_stages": completed_stages},
        )

    except JobInterruptedException as interrupted:
        logger.info(
            "Job %s interrupted on worker %s (new state=%s)",
            job_id,
            worker_id,
            interrupted.new_state,
        )
        return JobQueueRepository.get_job(job_id, include_events=True)

    except PermanentJobError as perm_err:
        logger.warning(
            "Permanent failure on job %s (file %s): [%s] %s",
            job_id,
            file_id,
            perm_err.code,
            perm_err.message,
        )
        return JobQueueRepository.mark_job_failed_or_retry(
            job_id=job_id,
            worker_id=worker_id,
            error_code=perm_err.code,
            error_message=perm_err.message,
            retryable=False,
        )

    except RetryableJobError as retry_err:
        logger.warning(
            "Retryable failure on job %s (file %s): [%s] %s",
            job_id,
            file_id,
            retry_err.code,
            retry_err.message,
        )
        return JobQueueRepository.mark_job_failed_or_retry(
            job_id=job_id,
            worker_id=worker_id,
            error_code=retry_err.code,
            error_message=retry_err.message,
            retryable=True,
        )

    except sqlite3.OperationalError as db_err:
        logger.error("SQLite contention on job %s: %s", job_id, db_err)
        return JobQueueRepository.mark_job_failed_or_retry(
            job_id=job_id,
            worker_id=worker_id,
            error_code="DATABASE_LOCKED",
            error_message="رقابت قفل پایگاه‌داده SQLite؛ کار مجدداً تلاش می‌شود.",
            retryable=True,
        )

    except Exception as unexpected_exc:
        logger.exception("Unexpected error executing job %s", job_id)
        return JobQueueRepository.mark_job_failed_or_retry(
            job_id=job_id,
            worker_id=worker_id,
            error_code="WORKER_EXECUTION_ERROR",
            error_message="خطای غیرمنتظره در اجرای کارگر پردازش سند.",
            retryable=True,
        )
