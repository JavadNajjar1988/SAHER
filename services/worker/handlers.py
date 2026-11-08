import os
import json
import time
import uuid
import hashlib
import logging
import sqlite3
from dataclasses import asdict
from typing import Optional, List, Dict, Any
from services.api.config import settings
from services.api.database import get_db
from services.api.schemas import JobItemDTO
from services.ingestion.extractor import (
    PageExtractionDetail,
    validate_file_signature,
    extract_document_content,
    render_pdf_page_to_pil,
    normalize_persian_text,
    normalize_for_fts,
)
from services.ocr import (
    get_ocr_engine,
    OCRModelMissingError,
    OCRPageReadError,
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


def _detail_from_checkpoint_dict(d: Dict[str, Any]) -> PageExtractionDetail:
    return PageExtractionDetail(
        page_number=int(d.get("page_number", 1)),
        raw_text=str(d.get("raw_text", "")),
        normalized_text=str(d.get("normalized_text", "")),
        bboxes=list(d.get("bboxes", [])),
        extraction_method=str(d.get("extraction_method", "ocr_image")),
        page_status=str(d.get("page_status", "extracted")),
        ocr_confidence=d.get("ocr_confidence"),
        width=int(d.get("width") or 800),
        height=int(d.get("height") or 1100),
        error_code=d.get("error_code"),
        error_message=d.get("error_message"),
        processing_ms=float(d.get("processing_ms") or 0.0),
    )


def execute_job_pipeline(
    job: JobItemDTO,
    worker_id: str,
    stage_throttle_seconds: float = 0.0,
    lease_seconds: int = 30,
) -> Optional[JobItemDTO]:
    """
    Executes a claimed durable job through SAHER's Milestone 2 & Milestone 3 processing stages:
    DISCOVERY -> VALIDATION -> EXTRACTION -> (OCR_PENDING) -> INDEXING -> FINALIZATION

    Key guarantees:
    - Pluggable offline Persian + English OCR (`get_ocr_engine()`) processes images, scanned PDFs,
      and only the scanned pages of hybrid PDFs while reading digital PDF pages directly.
    - Reports missing OCR model bundles explicitly (`OCR_MODEL_MISSING`).
    - Isolates page-level read/OCR errors with the exact page number while preserving healthy pages.
    - Preserves user modifications (`files.is_user_modified = 1` and `pages.is_user_modified = 1`)
      and previously valid page text during reanalysis or recovery.
    - Updates `pages`, `pages_fts`, and `files_fts` atomically and idempotently so pause/resume,
      worker crash recovery, and reanalysis never create duplicate records or search hits.
    """
    from services.api.repository import ArchiveRepository

    job_id = job.id
    file_id = job.file_id
    completed_stages: List[str] = list(job.checkpoint.get("completed_stages", []))
    checkpoint_ocr_pages: Dict[str, Dict[str, Any]] = dict(
        job.checkpoint.get("ocr_completed_pages", {})
    )

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

            if not file_row["is_user_modified"] and file_row["status"] == "در صف":
                cur.execute(
                    "UPDATE files SET status = 'در حال پردازش', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (file_id,),
                )

            # Load existing pages for this file to preserve user edits and prior valid text on reanalysis
            cur.execute(
                """
                SELECT page_number, raw_text, normalized_text, bboxes_json,
                       extraction_method, page_status, ocr_confidence, width, height,
                       is_user_modified
                FROM pages
                WHERE file_id = ?
                ORDER BY page_number ASC
                """,
                (file_id,),
            )
            existing_pages_map: Dict[int, sqlite3.Row] = {
                int(r["page_number"]): r for r in cur.fetchall()
            }

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
            progress=45.0,
            progress_message="بررسی ساختار صفحات و استخراج لایهٔ متنی مستقیم…",
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

        # 4. Handle Tiny/Blank Pending OCR Fixtures (no OCR pages to run)
        if extraction.extraction_status == "pending_ocr" and not extraction.needs_ocr_pages:
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

                cur.execute(
                    "SELECT id, extracted_text, extraction_version FROM documents WHERE file_id = ?",
                    (file_id,),
                )
                doc_row = cur.fetchone()
                if doc_row:
                    preserved_text = doc_row["extracted_text"] or ""
                    base_ver = int(doc_row["extraction_version"]) if doc_row["extraction_version"] is not None else 0
                    new_ext_ver = base_ver + 1
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

        # 5. Stage: OCR_PENDING (Milestone 3 Active Offline OCR for Images, Scanned PDFs & Hybrid PDFs)
        page_details_by_num: Dict[int, PageExtractionDetail] = {
            d.page_number: d for d in extraction.page_details
        }
        for p_idx in range(1, extraction.page_count + 1):
            if p_idx not in page_details_by_num:
                txt = extraction.pages[p_idx - 1] if p_idx - 1 < len(extraction.pages) else ""
                page_details_by_num[p_idx] = PageExtractionDetail(
                    page_number=p_idx,
                    raw_text=txt,
                    normalized_text=normalize_persian_text(txt),
                    extraction_method=extraction.extraction_method,
                    page_status="extracted" if txt else "empty",
                )

        ocr_timing_ms_total = 0.0
        page_error_notes: List[str] = []
        preserved_page_notes: List[str] = []

        if extraction.needs_ocr_pages:
            total_ocr_pages = len(extraction.needs_ocr_pages)
            JobQueueRepository.update_stage_and_heartbeat(
                job_id=job_id,
                worker_id=worker_id,
                stage=ProcessingStage.OCR_PENDING.value,
                progress=55.0,
                progress_message=f"آماده‌سازی موتور تشخیص متن آفلاین (OCR) برای {total_ocr_pages} صفحه…",
                lease_seconds=lease_seconds,
                checkpoint_updates={
                    "completed_stages": completed_stages,
                    "ocr_completed_pages": checkpoint_ocr_pages,
                },
            )

            ocr_engine = get_ocr_engine()
            try:
                ocr_engine.ensure_ready()
            except OCRModelMissingError as model_err:
                # If this is a hybrid PDF that already has extracted digital pages, index the healthy digital pages
                # before recording the missing OCR model error so digital text is not lost!
                has_digital_pages = any(
                    d.page_status == "extracted" and d.normalized_text
                    for p, d in page_details_by_num.items()
                    if p not in extraction.needs_ocr_pages
                )
                if has_digital_pages:
                    for p_num in extraction.needs_ocr_pages:
                        page_details_by_num[p_num] = PageExtractionDetail(
                            page_number=p_num,
                            raw_text="",
                            normalized_text="",
                            bboxes=[],
                            extraction_method="ocr_pdf_page",
                            page_status="failed",
                            error_code=model_err.code,
                            error_message=model_err.message,
                        )
                    _persist_document_and_pages_in_db(
                        file_id=file_id,
                        job=job,
                        extraction=extraction,
                        page_details_by_num=page_details_by_num,
                        existing_pages_map=existing_pages_map,
                        page_error_notes=[model_err.message],
                        preserved_page_notes=[],
                        override_error_code=model_err.code,
                        override_error_message=model_err.message,
                    )
                raise PermanentJobError(model_err.code, model_err.message) from model_err

            is_pdf = detected_mime == "application/pdf" or storage_path.lower().endswith(".pdf")

            for idx_in_ocr, page_num in enumerate(extraction.needs_ocr_pages, start=1):
                # 5a. If user manually edited this page previously, preserve user override
                prev_row = existing_pages_map.get(page_num)
                if prev_row and bool(prev_row["is_user_modified"]):
                    try:
                        prev_bboxes = json.loads(prev_row["bboxes_json"] or "[]")
                    except Exception:
                        prev_bboxes = []
                    page_details_by_num[page_num] = PageExtractionDetail(
                        page_number=page_num,
                        raw_text=prev_row["raw_text"] or "",
                        normalized_text=prev_row["normalized_text"] or "",
                        bboxes=prev_bboxes,
                        extraction_method=prev_row["extraction_method"] or "user_modified",
                        page_status="user_modified",
                        ocr_confidence=prev_row["ocr_confidence"],
                        width=int(prev_row["width"] or 800),
                        height=int(prev_row["height"] or 1100),
                    )
                    preserved_page_notes.append(f"صفحهٔ {page_num} (اصلاح دستی کاربر حفظ شد)")
                    continue

                # 5b. If page was already completed in an earlier checkpoint before pause/crash, reuse it
                if str(page_num) in checkpoint_ocr_pages:
                    restored_detail = _detail_from_checkpoint_dict(checkpoint_ocr_pages[str(page_num)])
                    page_details_by_num[page_num] = restored_detail
                    ocr_timing_ms_total += restored_detail.processing_ms
                    if restored_detail.page_status == "failed" and restored_detail.error_message:
                        page_error_notes.append(restored_detail.error_message)
                    continue

                step_progress = round(55.0 + (idx_in_ocr / max(1, total_ocr_pages)) * 25.0, 1)
                JobQueueRepository.update_stage_and_heartbeat(
                    job_id=job_id,
                    worker_id=worker_id,
                    stage=ProcessingStage.OCR_PENDING.value,
                    progress=step_progress,
                    progress_message=f"در حال تشخیص متن آفلاین (OCR) صفحهٔ {page_num} از {extraction.page_count}…",
                    lease_seconds=lease_seconds,
                    checkpoint_updates={
                        "completed_stages": completed_stages,
                        "ocr_completed_pages": checkpoint_ocr_pages,
                    },
                )
                if stage_throttle_seconds > 0:
                    time.sleep(stage_throttle_seconds)

                try:
                    if is_pdf:
                        pil_img = render_pdf_page_to_pil(
                            storage_path,
                            page_number=page_num,
                            scale=settings.ocr_render_scale,
                        )
                        ocr_res = ocr_engine.recognize_image(
                            pil_img,
                            page_number=page_num,
                            extraction_method="ocr_pdf_page",
                        )
                    else:
                        ocr_res = ocr_engine.recognize_image(
                            storage_path,
                            page_number=page_num,
                            extraction_method="ocr_image",
                        )

                    ocr_timing_ms_total += ocr_res.processing_ms
                    detail = PageExtractionDetail(
                        page_number=page_num,
                        raw_text=ocr_res.raw_text,
                        normalized_text=ocr_res.normalized_text,
                        bboxes=[b.to_dict() for b in ocr_res.bboxes],
                        extraction_method=ocr_res.extraction_method,
                        page_status=ocr_res.status,
                        ocr_confidence=ocr_res.confidence,
                        width=ocr_res.width,
                        height=ocr_res.height,
                        processing_ms=ocr_res.processing_ms,
                    )
                    page_details_by_num[page_num] = detail
                    checkpoint_ocr_pages[str(page_num)] = asdict(detail)

                except OCRModelMissingError as model_err:
                    raise PermanentJobError(model_err.code, model_err.message) from model_err

                except Exception as page_exc:
                    err_code = getattr(page_exc, "code", "OCR_PAGE_READ_ERROR")
                    reason = getattr(page_exc, "reason", str(page_exc))
                    page_err_msg = f"خطا در خواندن متن صفحهٔ {page_num}: {reason}"
                    logger.warning(
                        "Page-level OCR error on job %s file %s page %d: [%s] %s",
                        job_id,
                        file_id,
                        page_num,
                        err_code,
                        page_err_msg,
                    )
                    JobQueueRepository.log_stage_event(
                        job_id=job_id,
                        stage=ProcessingStage.OCR_PENDING.value,
                        event_type="PAGE_OCR_ERROR",
                        worker_id=worker_id,
                        error_code=err_code,
                        message=page_err_msg,
                        details={"page_number": page_num, "error_code": err_code},
                    )

                    # If valid text existed for this page from a prior extraction, preserve it!
                    if prev_row and (prev_row["normalized_text"] or "").strip():
                        try:
                            prev_bboxes = json.loads(prev_row["bboxes_json"] or "[]")
                        except Exception:
                            prev_bboxes = []
                        detail = PageExtractionDetail(
                            page_number=page_num,
                            raw_text=prev_row["raw_text"] or "",
                            normalized_text=prev_row["normalized_text"] or "",
                            bboxes=prev_bboxes,
                            extraction_method=prev_row["extraction_method"] or "ocr_pdf_page",
                            page_status="extracted",
                            ocr_confidence=prev_row["ocr_confidence"],
                            width=int(prev_row["width"] or 800),
                            height=int(prev_row["height"] or 1100),
                            error_code=err_code,
                            error_message=f"{page_err_msg} (متن معتبر قبلی این صفحه حفظ شد)",
                        )
                        preserved_page_notes.append(f"صفحهٔ {page_num} (حفظ متن معتبر قبلی پس از خطای بازخوانی)")
                    else:
                        detail = PageExtractionDetail(
                            page_number=page_num,
                            raw_text="",
                            normalized_text="",
                            bboxes=[],
                            extraction_method="ocr_pdf_page" if is_pdf else "ocr_image",
                            page_status="failed",
                            error_code=err_code,
                            error_message=page_err_msg,
                        )
                    page_error_notes.append(page_err_msg)
                    page_details_by_num[page_num] = detail
                    checkpoint_ocr_pages[str(page_num)] = asdict(detail)

                # Save page checkpoint so pause/resume or worker crash resumes from next page
                JobQueueRepository.update_stage_and_heartbeat(
                    job_id=job_id,
                    worker_id=worker_id,
                    stage=ProcessingStage.OCR_PENDING.value,
                    progress=step_progress,
                    progress_message=f"صفحهٔ {page_num} از {extraction.page_count} پردازش شد.",
                    lease_seconds=lease_seconds,
                    checkpoint_updates={
                        "completed_stages": completed_stages,
                        "ocr_completed_pages": checkpoint_ocr_pages,
                        "ocr_processing_ms": round(ocr_timing_ms_total, 2),
                    },
                )

            if ProcessingStage.OCR_PENDING.value not in completed_stages:
                completed_stages.append(ProcessingStage.OCR_PENDING.value)

        # Also preserve user modifications on non-OCR pages (e.g. digital pages edited by user)
        for p_num, detail in list(page_details_by_num.items()):
            prev_row = existing_pages_map.get(p_num)
            if prev_row and bool(prev_row["is_user_modified"]):
                try:
                    prev_bboxes = json.loads(prev_row["bboxes_json"] or "[]")
                except Exception:
                    prev_bboxes = []
                page_details_by_num[p_num] = PageExtractionDetail(
                    page_number=p_num,
                    raw_text=prev_row["raw_text"] or "",
                    normalized_text=prev_row["normalized_text"] or "",
                    bboxes=prev_bboxes,
                    extraction_method=prev_row["extraction_method"] or detail.extraction_method,
                    page_status="user_modified",
                    ocr_confidence=prev_row["ocr_confidence"],
                    width=int(prev_row["width"] or detail.width or 800),
                    height=int(prev_row["height"] or detail.height or 1100),
                )

        # If every single page in the document failed and no valid text exists at all, fail the job
        all_details_ordered = [
            page_details_by_num[p] for p in sorted(page_details_by_num.keys())
        ]
        failed_page_nums = [d.page_number for d in all_details_ordered if d.page_status == "failed"]
        has_any_valid_text = any(bool(d.normalized_text.strip()) for d in all_details_ordered)

        if failed_page_nums and not has_any_valid_text and len(failed_page_nums) == len(all_details_ordered):
            first_failed = all_details_ordered[0]
            _persist_document_and_pages_in_db(
                file_id=file_id,
                job=job,
                extraction=extraction,
                page_details_by_num=page_details_by_num,
                existing_pages_map=existing_pages_map,
                page_error_notes=page_error_notes,
                preserved_page_notes=preserved_page_notes,
                override_error_code=first_failed.error_code or "OCR_ALL_PAGES_FAILED",
                override_error_message="; ".join(page_error_notes),
            )
            raise PermanentJobError(
                first_failed.error_code or "OCR_ALL_PAGES_FAILED",
                "; ".join(page_error_notes) or "خطا در خواندن تمامی صفحات فایل.",
            )

        # 6. Stage: INDEXING (Persist pages, bounding boxes, document text, and FTS5 indices)
        JobQueueRepository.update_stage_and_heartbeat(
            job_id=job_id,
            worker_id=worker_id,
            stage=ProcessingStage.INDEXING.value,
            progress=85.0,
            progress_message="نمایه‌سازی متن صفحات و مختصات در پایگاه‌داده و موتور جست‌وجوی FTS5…",
            lease_seconds=lease_seconds,
            checkpoint_updates={
                "completed_stages": completed_stages,
                "ocr_completed_pages": checkpoint_ocr_pages,
                "ocr_processing_ms": round(ocr_timing_ms_total, 2),
                "failed_pages": failed_page_nums,
            },
        )
        if stage_throttle_seconds > 0:
            time.sleep(stage_throttle_seconds)

        _persist_document_and_pages_in_db(
            file_id=file_id,
            job=job,
            extraction=extraction,
            page_details_by_num=page_details_by_num,
            existing_pages_map=existing_pages_map,
            page_error_notes=page_error_notes,
            preserved_page_notes=preserved_page_notes,
        )

        if ProcessingStage.INDEXING.value not in completed_stages:
            completed_stages.append(ProcessingStage.INDEXING.value)

        # 7. Stage: FINALIZATION
        JobQueueRepository.update_stage_and_heartbeat(
            job_id=job_id,
            worker_id=worker_id,
            stage=ProcessingStage.FINALIZATION.value,
            progress=95.0,
            progress_message="نهایی‌سازی متادیتا و ثبت نسخهٔ پردازش…",
            lease_seconds=lease_seconds,
            checkpoint_updates={
                "completed_stages": completed_stages,
                "ocr_completed_pages": checkpoint_ocr_pages,
                "ocr_processing_ms": round(ocr_timing_ms_total, 2),
                "failed_pages": failed_page_nums,
            },
        )
        if ProcessingStage.FINALIZATION.value not in completed_stages:
            completed_stages.append(ProcessingStage.FINALIZATION.value)

        completion_msg = (
            f"پردازش با هشدار در صفحهٔ {', '.join(str(p) for p in failed_page_nums)} تکمیل شد؛ سایر صفحات سالم نمایه‌سازی شدند."
            if failed_page_nums
            else "استخراج متن، مختصات صفحات و نمایه‌سازی FTS5 با موفقیت تکمیل شد."
        )

        return JobQueueRepository.mark_job_completed(
            job_id=job_id,
            worker_id=worker_id,
            final_stage=ProcessingStage.FINALIZATION.value,
            progress_message=completion_msg,
            checkpoint_updates={
                "completed_stages": completed_stages,
                "ocr_completed_pages": checkpoint_ocr_pages,
                "ocr_processing_ms": round(ocr_timing_ms_total, 2),
                "failed_pages": failed_page_nums,
            },
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


def _persist_document_and_pages_in_db(
    file_id: str,
    job: JobItemDTO,
    extraction: Any,
    page_details_by_num: Dict[int, PageExtractionDetail],
    existing_pages_map: Dict[int, sqlite3.Row],
    page_error_notes: List[str],
    preserved_page_notes: List[str],
    override_error_code: Optional[str] = None,
    override_error_message: Optional[str] = None,
) -> None:
    from services.api.repository import ArchiveRepository

    ordered_details = [
        page_details_by_num[p] for p in sorted(page_details_by_num.keys())
    ]
    non_empty_texts = [
        d.normalized_text.strip()
        for d in ordered_details
        if d.normalized_text and d.normalized_text.strip()
    ]
    combined_extracted_text = "\n\n".join(non_empty_texts)
    failed_pages = [d.page_number for d in ordered_details if d.page_status == "failed"]

    # Determine overall extraction status and method
    methods_used = {d.extraction_method for d in ordered_details}
    if "pdf_text" in methods_used and "ocr_pdf_page" in methods_used:
        doc_method = "hybrid_pdf_ocr"
    elif "ocr_pdf_page" in methods_used:
        doc_method = "ocr_pdf"
    elif "ocr_image" in methods_used:
        doc_method = "ocr_image"
    else:
        doc_method = extraction.extraction_method

    if failed_pages and combined_extracted_text:
        doc_ext_status = "partial_ocr"
        rec_file_status = "نیازمند بازبینی"
    elif failed_pages and not combined_extracted_text:
        doc_ext_status = "failed"
        rec_file_status = "خطا"
    elif combined_extracted_text:
        doc_ext_status = "extracted"
        rec_file_status = "آماده"
    else:
        doc_ext_status = "empty"
        rec_file_status = "نیازمند بازبینی"

    notes: List[str] = []
    if failed_pages:
        notes.append(
            f"خطا در خواندن صفحهٔ {', '.join(str(p) for p in failed_pages)} ثبت شد؛ متن سایر صفحات سالم حفظ و نمایه‌سازی گردید."
        )
        notes.extend(page_error_notes)
    if preserved_page_notes:
        notes.append(" · ".join(preserved_page_notes))
    if not combined_extracted_text and not failed_pages and extraction.system_note:
        notes.append(extraction.system_note)
    final_system_note = " | ".join(notes) if notes else None

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
            if (is_mod and fresh_file["status"] in ("آماده", "نیازمند بازبینی") and not override_error_code)
            else rec_file_status
        )

        cur.execute("SELECT id, extracted_text, extraction_version FROM documents WHERE file_id = ?", (file_id,))
        doc_row = cur.fetchone()
        if doc_row:
            doc_id = doc_row["id"]
            # If the new run produced empty text because all pages failed, preserve previous document text if any
            if not combined_extracted_text and (doc_row["extracted_text"] or "").strip():
                combined_extracted_text = doc_row["extracted_text"]
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
                    combined_extracted_text,
                    len(ordered_details),
                    doc_ext_status,
                    doc_method,
                    new_ext_ver,
                    final_system_note,
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
                    combined_extracted_text,
                    len(ordered_details),
                    doc_ext_status,
                    doc_method,
                    final_system_note,
                ),
            )

        # Idempotently replace `pages` and `pages_fts` for this file inside the same atomic transaction
        cur.execute("DELETE FROM pages WHERE file_id = ?", (file_id,))
        cur.execute("DELETE FROM pages_fts WHERE file_id = ?", (file_id,))

        for d in ordered_details:
            prev_row = existing_pages_map.get(d.page_number)
            is_page_user_mod = 1 if (prev_row and bool(prev_row["is_user_modified"])) or d.page_status == "user_modified" else 0
            fts_norm = normalize_for_fts(d.normalized_text or d.raw_text)
            cur.execute(
                """
                INSERT INTO pages (
                    id, document_id, file_id, page_number, raw_text, normalized_text,
                    bboxes_json, extraction_method, page_status, error_code, error_message,
                    ocr_confidence, width, height, is_user_modified, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    str(uuid.uuid4()),
                    doc_id,
                    file_id,
                    d.page_number,
                    d.raw_text,
                    d.normalized_text,
                    json.dumps(d.bboxes, ensure_ascii=False),
                    d.extraction_method,
                    d.page_status,
                    d.error_code,
                    d.error_message,
                    d.ocr_confidence,
                    d.width,
                    d.height,
                    is_page_user_mod,
                ),
            )
            if fts_norm:
                cur.execute(
                    """
                    INSERT INTO pages_fts (file_id, page_number, raw_text, normalized_text)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        file_id,
                        d.page_number,
                        normalize_persian_text(d.raw_text),
                        fts_norm,
                    ),
                )

        # Preserve user tags if modified; otherwise add auto-detected tags without wiping existing ones
        current_tags = ArchiveRepository.get_file_tags(conn, file_id)
        if not is_mod:
            merged_tags = list(current_tags)
            if ("هوش مصنوعی" in fresh_file["title"] or "هوش مصنوعی" in combined_extracted_text) and "هوش مصنوعی" not in merged_tags:
                merged_tags.append("هوش مصنوعی")
            if ("طراحی" in fresh_file["title"] or "معماری" in fresh_file["title"]) and "طراحی محصول" not in merged_tags:
                merged_tags.append("طراحی محصول")
            if merged_tags != current_tags:
                ArchiveRepository.set_file_tags(conn, file_id, merged_tags)
                current_tags = merged_tags

        file_err_code = override_error_code or ("PAGE_OCR_PARTIAL_ERROR" if failed_pages else None)
        file_err_msg = override_error_message or ("; ".join(page_error_notes) if failed_pages else None)

        cur.execute(
            """
            UPDATE files
            SET status = ?,
                error_code = ?,
                error_message = ?,
                processing_version = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (final_status, file_err_code, file_err_msg, job.processing_version, file_id),
        )

        ArchiveRepository.update_fts(
            conn,
            file_id,
            fresh_file["title"],
            combined_extracted_text,
            final_topic,
            current_tags,
        )
