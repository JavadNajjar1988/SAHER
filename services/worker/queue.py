import os
import json
import uuid
import socket
import sqlite3
from typing import Optional, List, Dict, Any, Tuple
from services.api.config import settings
from services.api.database import get_db_connection, get_db
from services.api.schemas import (
    JobItemDTO,
    JobEventDTO,
    JobStatsDTO,
    WorkerInfoDTO,
)
from services.worker.lifecycle import (
    JobState,
    ProcessingStage,
    JobType,
    compute_retry_backoff_seconds,
    JobInterruptedException,
)


class JobStateTransitionError(Exception):
    def __init__(self, message: str, code: str = "INVALID_JOB_STATE", status_code: int = 409):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class JobNotFoundError(Exception):
    def __init__(self, job_id: str):
        msg = f"کار پردازشی با شناسهٔ «{job_id}» یافت نشد."
        super().__init__(msg)
        self.message = msg
        self.code = "JOB_NOT_FOUND"
        self.status_code = 404


class JobQueueRepository:
    """
    Transactional SQLite-backed durable job queue with atomic worker lease claiming,
    heartbeat management, exponential retry backoff, and execution history events.
    """

    @staticmethod
    def _log_event(
        conn: sqlite3.Connection,
        job_id: str,
        attempt_number: int,
        from_state: Optional[str],
        to_state: str,
        stage: str,
        event_type: str,
        worker_id: Optional[str] = None,
        message: Optional[str] = None,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO job_events (
                job_id, attempt_number, from_state, to_state, stage,
                event_type, worker_id, message, error_code, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                attempt_number,
                from_state,
                to_state,
                stage,
                event_type,
                worker_id,
                message,
                error_code,
                json.dumps(details or {}, ensure_ascii=False),
            ),
        )

    @classmethod
    def _row_to_dto(
        cls,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        include_events: bool = False,
    ) -> JobItemDTO:
        keys = row.keys()
        checkpoint: Dict[str, Any] = {}
        raw_cp = row["checkpoint_json"] if "checkpoint_json" in keys else "{}"
        if raw_cp:
            try:
                checkpoint = json.loads(raw_cp)
            except Exception:
                checkpoint = {}

        events: List[JobEventDTO] = []
        if include_events:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, job_id, attempt_number, from_state, to_state, stage,
                       event_type, worker_id, message, error_code, created_at
                FROM job_events
                WHERE job_id = ?
                ORDER BY id ASC
                """,
                (row["id"],),
            )
            events = [
                JobEventDTO(
                    id=er["id"],
                    job_id=er["job_id"],
                    attempt_number=er["attempt_number"],
                    from_state=er["from_state"],
                    to_state=er["to_state"],
                    stage=er["stage"],
                    event_type=er["event_type"],
                    worker_id=er["worker_id"],
                    message=er["message"],
                    error_code=er["error_code"],
                    created_at=str(er["created_at"]),
                )
                for er in cur.fetchall()
            ]

        return JobItemDTO(
            id=row["id"],
            archive_id=row["archive_id"],
            file_id=row["file_id"],
            file_title=row["file_title"] if "file_title" in keys and row["file_title"] else "",
            file_kind=row["file_kind"] if "file_kind" in keys and row["file_kind"] else "سند",
            file_status=row["file_status"] if "file_status" in keys and row["file_status"] else "در صف",
            job_type=row["job_type"],
            target_stage=row["target_stage"] if "target_stage" in keys else None,
            processing_stage=row["processing_stage"],
            state=row["state"],
            priority=row["priority"],
            attempt_count=row["attempt_count"],
            max_retries=row["max_retries"],
            progress=float(row["progress"] or 0.0),
            progress_message=row["progress_message"] if "progress_message" in keys else None,
            error_code=row["error_code"],
            error_message=row["error_message"],
            is_retryable=bool(row["is_retryable"]) if "is_retryable" in keys else True,
            worker_id=row["worker_id"],
            lease_expires_at=str(row["lease_expires_at"]) if row["lease_expires_at"] else None,
            heartbeat_at=str(row["heartbeat_at"]) if row["heartbeat_at"] else None,
            next_run_at=str(row["next_run_at"]) if row["next_run_at"] else None,
            processing_version=row["processing_version"] or 1,
            checkpoint=checkpoint,
            created_at=str(row["created_at"]),
            started_at=str(row["started_at"]) if row["started_at"] else None,
            updated_at=str(row["updated_at"]) if row["updated_at"] else None,
            completed_at=str(row["completed_at"]) if row["completed_at"] else None,
            events=events,
        )

    @classmethod
    def create_job_in_transaction(
        cls,
        conn: sqlite3.Connection,
        file_id: str,
        archive_id: str = "default",
        job_type: str = JobType.FILE_INGESTION.value,
        target_stage: Optional[str] = None,
        initial_stage: str = ProcessingStage.DISCOVERY.value,
        priority: int = 50,
        max_retries: Optional[int] = None,
        processing_version: int = 1,
        progress_message: str = "ثبت در صف پردازش پایدار",
    ) -> str:
        """
        Inserts a durable job record inside an existing database transaction (e.g. during file ingestion)
        and links `files.latest_job_id = job_id`.
        """
        job_id = str(uuid.uuid4())
        retries = max_retries if max_retries is not None else settings.job_max_retries
        initial_checkpoint = {
            "completed_stages": [],
            "target_stage": target_stage,
            "processing_version": processing_version,
        }

        conn.execute(
            """
            INSERT INTO jobs (
                id, archive_id, file_id, job_type, target_stage, processing_stage,
                state, priority, attempt_count, max_retries, progress, progress_message,
                processing_version, checkpoint_json, next_run_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'QUEUED', ?, 0, ?, 0.0, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                job_id,
                archive_id,
                file_id,
                job_type,
                target_stage,
                initial_stage,
                priority,
                retries,
                progress_message,
                processing_version,
                json.dumps(initial_checkpoint, ensure_ascii=False),
            ),
        )
        conn.execute(
            "UPDATE files SET latest_job_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (job_id, file_id),
        )
        cls._log_event(
            conn=conn,
            job_id=job_id,
            attempt_number=0,
            from_state=None,
            to_state=JobState.QUEUED.value,
            stage=initial_stage,
            event_type="CREATED",
            message=progress_message,
        )
        return job_id

    @classmethod
    def enqueue_reanalysis(
        cls,
        file_id: str,
        stage: Optional[str] = None,
        priority: int = 60,
    ) -> Tuple[JobItemDTO, bool]:
        """
        Enqueues a controlled reanalysis job for `file_id`.
        Prevents unintended duplicate jobs: if an active job (QUEUED, RUNNING, PAUSED)
        already exists for `file_id`, returns `(existing_job, False)`.
        """
        valid_stages = {s.value for s in ProcessingStage}
        if stage and stage not in valid_stages:
            raise JobStateTransitionError(
                f"مرحلهٔ پردازشی «{stage}» معتبر نیست.",
                code="INVALID_STAGE",
                status_code=422,
            )

        conn = get_db_connection()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            cur = conn.cursor()

            cur.execute(
                "SELECT id, archive_id, processing_version FROM files WHERE id = ?",
                (file_id,),
            )
            file_row = cur.fetchone()
            if not file_row:
                conn.rollback()
                raise JobNotFoundError(file_id)

            # Check for existing active job to guarantee idempotency
            cur.execute(
                """
                SELECT j.*, f.title AS file_title, f.kind AS file_kind, f.status AS file_status
                FROM jobs j
                JOIN files f ON j.file_id = f.id
                WHERE j.file_id = ?
                  AND j.state IN ('QUEUED', 'RUNNING', 'PAUSED')
                ORDER BY j.created_at DESC
                LIMIT 1
                """,
                (file_id,),
            )
            existing = cur.fetchone()
            if existing:
                dto = cls._row_to_dto(conn, existing, include_events=True)
                conn.commit()
                return dto, False

            next_version = int(file_row["processing_version"] or 1) + 1
            start_stage = stage if stage in (
                ProcessingStage.DISCOVERY.value,
                ProcessingStage.VALIDATION.value,
                ProcessingStage.EXTRACTION.value,
            ) else ProcessingStage.DISCOVERY.value

            job_id = cls.create_job_in_transaction(
                conn=conn,
                file_id=file_id,
                archive_id=file_row["archive_id"],
                job_type=JobType.STAGE_REPROCESS.value if stage else JobType.REANALYZE.value,
                target_stage=stage,
                initial_stage=start_stage,
                priority=priority,
                processing_version=next_version,
                progress_message=(
                    f"درخواست بازپردازش کنترل‌شده (مرحله هدف: {stage})"
                    if stage
                    else "درخواست تحلیل و استخراج مجدد سند"
                ),
            )
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()

        job_dto = cls.get_job(job_id, include_events=True)
        if not job_dto:
            raise JobNotFoundError(job_id)
        return job_dto, True

    @classmethod
    def claim_next_job(
        cls,
        worker_id: str,
        lease_seconds: Optional[int] = None,
        specific_job_id: Optional[str] = None,
    ) -> Optional[JobItemDTO]:
        """
        Atomically claims the highest-priority eligible QUEUED job using SQLite `BEGIN IMMEDIATE`
        so two concurrent workers can never claim the same job simultaneously.
        """
        lease_sec = max(5, lease_seconds if lease_seconds is not None else settings.job_lease_seconds)
        conn = get_db_connection()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            cur = conn.cursor()

            if specific_job_id:
                cur.execute(
                    """
                    SELECT id, attempt_count, processing_stage
                    FROM jobs
                    WHERE id = ? AND state = 'QUEUED'
                    LIMIT 1
                    """,
                    (specific_job_id,),
                )
            else:
                cur.execute(
                    """
                    SELECT id, attempt_count, processing_stage
                    FROM jobs
                    WHERE state = 'QUEUED'
                      AND datetime(COALESCE(next_run_at, CURRENT_TIMESTAMP)) <= datetime('now')
                    ORDER BY priority DESC, created_at ASC, id ASC
                    LIMIT 1
                    """
                )

            candidate = cur.fetchone()
            if not candidate:
                conn.commit()
                return None

            job_id = candidate["id"]
            new_attempt = int(candidate["attempt_count"] or 0) + 1
            stage = candidate["processing_stage"]

            cur.execute(
                """
                UPDATE jobs
                SET state = 'RUNNING',
                    worker_id = ?,
                    attempt_count = ?,
                    lease_expires_at = datetime('now', '+' || ? || ' seconds'),
                    heartbeat_at = CURRENT_TIMESTAMP,
                    started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND state = 'QUEUED'
                """,
                (worker_id, new_attempt, lease_sec, job_id),
            )
            if cur.rowcount != 1:
                conn.rollback()
                return None

            cls._log_event(
                conn=conn,
                job_id=job_id,
                attempt_number=new_attempt,
                from_state=JobState.QUEUED.value,
                to_state=JobState.RUNNING.value,
                stage=stage,
                event_type="CLAIMED",
                worker_id=worker_id,
                message=f"کار توسط کارگر «{worker_id}» (تلاش شماره {new_attempt}) دریافت شد.",
            )

            cur.execute(
                """
                SELECT j.*, f.title AS file_title, f.kind AS file_kind, f.status AS file_status
                FROM jobs j
                JOIN files f ON j.file_id = f.id
                WHERE j.id = ?
                """,
                (job_id,),
            )
            claimed_row = cur.fetchone()
            dto = cls._row_to_dto(conn, claimed_row, include_events=False)
            conn.commit()
            return dto
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()

    @classmethod
    def update_stage_and_heartbeat(
        cls,
        job_id: str,
        worker_id: str,
        stage: str,
        progress: float,
        progress_message: str,
        lease_seconds: Optional[int] = None,
        checkpoint_updates: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Updates job processing stage, progress, checkpoint, and extends lease expiration.
        Raises `JobInterruptedException` if the job was paused, cancelled, or reassigned.
        """
        lease_sec = max(5, lease_seconds if lease_seconds is not None else settings.job_lease_seconds)
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT state, worker_id, attempt_count, processing_stage, checkpoint_json FROM jobs WHERE id = ?",
                (job_id,),
            )
            row = cur.fetchone()
            if not row:
                raise JobInterruptedException(JobState.CANCELLED.value, "رکورد کار یافت نشد.")

            current_state = row["state"]
            if current_state != JobState.RUNNING.value or row["worker_id"] != worker_id:
                raise JobInterruptedException(
                    current_state,
                    f"وضعیت کار به «{current_state}» تغییر یافته است.",
                )

            cp = {}
            if row["checkpoint_json"]:
                try:
                    cp = json.loads(row["checkpoint_json"])
                except Exception:
                    cp = {}
            if checkpoint_updates:
                cp.update(checkpoint_updates)

            prev_stage = row["processing_stage"]
            cur.execute(
                """
                UPDATE jobs
                SET processing_stage = ?,
                    progress = ?,
                    progress_message = ?,
                    checkpoint_json = ?,
                    heartbeat_at = CURRENT_TIMESTAMP,
                    lease_expires_at = datetime('now', '+' || ? || ' seconds'),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND state = 'RUNNING' AND worker_id = ?
                """,
                (
                    stage,
                    round(float(progress), 1),
                    progress_message,
                    json.dumps(cp, ensure_ascii=False),
                    lease_sec,
                    job_id,
                    worker_id,
                ),
            )
            if prev_stage != stage:
                cls._log_event(
                    conn=conn,
                    job_id=job_id,
                    attempt_number=row["attempt_count"],
                    from_state=JobState.RUNNING.value,
                    to_state=JobState.RUNNING.value,
                    stage=stage,
                    event_type="STAGE_TRANSITION",
                    worker_id=worker_id,
                    message=progress_message,
                )

    @classmethod
    def mark_job_completed(
        cls,
        job_id: str,
        worker_id: str,
        final_stage: str,
        progress_message: str,
        checkpoint_updates: Optional[Dict[str, Any]] = None,
    ) -> Optional[JobItemDTO]:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT state, worker_id, attempt_count, checkpoint_json FROM jobs WHERE id = ?",
                (job_id,),
            )
            row = cur.fetchone()
            if not row or row["state"] != JobState.RUNNING.value or row["worker_id"] != worker_id:
                return None

            cp = {}
            if row["checkpoint_json"]:
                try:
                    cp = json.loads(row["checkpoint_json"])
                except Exception:
                    cp = {}
            if checkpoint_updates:
                cp.update(checkpoint_updates)

            cur.execute(
                """
                UPDATE jobs
                SET state = 'COMPLETED',
                    processing_stage = ?,
                    progress = 100.0,
                    progress_message = ?,
                    error_code = NULL,
                    error_message = NULL,
                    lease_expires_at = NULL,
                    heartbeat_at = CURRENT_TIMESTAMP,
                    completed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP,
                    checkpoint_json = ?
                WHERE id = ? AND state = 'RUNNING' AND worker_id = ?
                """,
                (
                    final_stage,
                    progress_message,
                    json.dumps(cp, ensure_ascii=False),
                    job_id,
                    worker_id,
                ),
            )
            cls._log_event(
                conn=conn,
                job_id=job_id,
                attempt_number=row["attempt_count"],
                from_state=JobState.RUNNING.value,
                to_state=JobState.COMPLETED.value,
                stage=final_stage,
                event_type="COMPLETED",
                worker_id=worker_id,
                message=progress_message,
            )

        return cls.get_job(job_id, include_events=True)

    @classmethod
    def mark_job_failed_or_retry(
        cls,
        job_id: str,
        worker_id: str,
        error_code: str,
        error_message: str,
        retryable: bool = True,
        base_backoff_seconds: float = 1.0,
    ) -> Optional[JobItemDTO]:
        """
        Records a job failure. If `retryable` is True and `attempt_count < max_retries`,
        transitions the job back to `QUEUED` with exponential backoff (`next_run_at`).
        Otherwise marks the job `FAILED` and updates file status only if the file has no valid extracted text.
        """
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, file_id, state, worker_id, attempt_count, max_retries, processing_stage
                FROM jobs WHERE id = ?
                """,
                (job_id,),
            )
            row = cur.fetchone()
            if not row:
                return None

            # If job was already paused or cancelled externally, respect user action
            if row["state"] in (JobState.PAUSED.value, JobState.CANCELLED.value):
                return cls.get_job(job_id, include_events=True)

            attempt = int(row["attempt_count"] or 1)
            max_retries = int(row["max_retries"] or settings.job_max_retries)
            stage = row["processing_stage"]
            file_id = row["file_id"]

            can_retry = retryable and (attempt < max_retries)
            if can_retry:
                backoff_sec = compute_retry_backoff_seconds(attempt, base_delay=base_backoff_seconds)
                cur.execute(
                    """
                    UPDATE jobs
                    SET state = 'QUEUED',
                        worker_id = NULL,
                        lease_expires_at = NULL,
                        error_code = ?,
                        error_message = ?,
                        is_retryable = 1,
                        progress_message = ?,
                        next_run_at = datetime('now', '+' || ? || ' seconds'),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        error_code,
                        error_message,
                        f"خطای موقت؛ زمان‌بندی تلاش مجدد ({attempt}/{max_retries}) پس از {backoff_sec:.1f} ثانیه",
                        backoff_sec,
                        job_id,
                    ),
                )
                cls._log_event(
                    conn=conn,
                    job_id=job_id,
                    attempt_number=attempt,
                    from_state=row["state"],
                    to_state=JobState.QUEUED.value,
                    stage=stage,
                    event_type="RETRY_SCHEDULED",
                    worker_id=worker_id,
                    message=error_message,
                    error_code=error_code,
                    details={"backoff_seconds": backoff_sec, "attempt": attempt, "max_retries": max_retries},
                )
            else:
                cur.execute(
                    """
                    UPDATE jobs
                    SET state = 'FAILED',
                        worker_id = NULL,
                        lease_expires_at = NULL,
                        error_code = ?,
                        error_message = ?,
                        is_retryable = ?,
                        progress_message = 'پردازش کار با خطا متوقف شد.',
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        error_code,
                        error_message,
                        1 if retryable else 0,
                        job_id,
                    ),
                )
                cls._log_event(
                    conn=conn,
                    job_id=job_id,
                    attempt_number=attempt,
                    from_state=row["state"],
                    to_state=JobState.FAILED.value,
                    stage=stage,
                    event_type="FAILED",
                    worker_id=worker_id,
                    message=error_message,
                    error_code=error_code,
                )

                # Only mark file as 'خطا' if it does not already have valid extracted text or user modification
                cur.execute(
                    """
                    SELECT f.is_user_modified, d.extraction_status, d.extracted_text
                    FROM files f
                    LEFT JOIN documents d ON f.id = d.file_id
                    WHERE f.id = ?
                    """,
                    (file_id,),
                )
                f_info = cur.fetchone()
                has_valid_extraction = bool(
                    f_info
                    and f_info["extraction_status"] == "extracted"
                    and (f_info["extracted_text"] or "").strip() != ""
                )
                if not has_valid_extraction:
                    cur.execute(
                        """
                        UPDATE files
                        SET status = CASE WHEN is_user_modified = 1 THEN status ELSE 'خطا' END,
                            error_code = ?,
                            error_message = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (error_code, error_message, file_id),
                    )
                    if not (f_info and f_info["extraction_status"] in ("extracted", "pending_ocr", "empty")):
                        cur.execute(
                            """
                            UPDATE documents
                            SET extraction_status = 'failed',
                                updated_at = CURRENT_TIMESTAMP
                            WHERE file_id = ?
                            """,
                            (file_id,),
                        )

        return cls.get_job(job_id, include_events=True)

    @classmethod
    def recover_expired_leases(cls, force_all_running: bool = False) -> int:
        """
        Recovers jobs left in RUNNING state due to worker crash or expired lease.
        Preserves checkpoint metadata so recovery does not cause duplicate side effects.
        """
        recovered = 0
        conn = get_db_connection()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            cur = conn.cursor()
            if force_all_running:
                cur.execute(
                    """
                    SELECT id, file_id, attempt_count, max_retries, processing_stage, worker_id
                    FROM jobs
                    WHERE state = 'RUNNING'
                    """
                )
            else:
                cur.execute(
                    """
                    SELECT id, file_id, attempt_count, max_retries, processing_stage, worker_id
                    FROM jobs
                    WHERE state = 'RUNNING'
                      AND lease_expires_at IS NOT NULL
                      AND datetime(lease_expires_at) < datetime('now')
                    """
                )
            rows = cur.fetchall()
            for r in rows:
                job_id = r["id"]
                attempt = int(r["attempt_count"] or 1)
                max_retries = int(r["max_retries"] or settings.job_max_retries)
                stage = r["processing_stage"]
                old_worker = r["worker_id"]

                if attempt < max_retries:
                    cur.execute(
                        """
                        UPDATE jobs
                        SET state = 'QUEUED',
                            worker_id = NULL,
                            lease_expires_at = NULL,
                            error_code = 'WORKER_LEASE_EXPIRED',
                            error_message = 'مهلت کارگر منقضی شد؛ کار برای ادامهٔ ایمن به صف بازگردانده شد.',
                            progress_message = 'بازیابی خودکار پس از وقفهٔ کارگر',
                            next_run_at = CURRENT_TIMESTAMP,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ? AND state = 'RUNNING'
                        """,
                        (job_id,),
                    )
                    cls._log_event(
                        conn=conn,
                        job_id=job_id,
                        attempt_number=attempt,
                        from_state=JobState.RUNNING.value,
                        to_state=JobState.QUEUED.value,
                        stage=stage,
                        event_type="RECOVERED_LEASE",
                        worker_id=old_worker,
                        message="کار ناتمام پس از انقضای Lease کارگر به صف بازگردانده شد.",
                        error_code="WORKER_LEASE_EXPIRED",
                    )
                else:
                    cur.execute(
                        """
                        UPDATE jobs
                        SET state = 'FAILED',
                            worker_id = NULL,
                            lease_expires_at = NULL,
                            error_code = 'WORKER_CRASH_MAX_RETRIES',
                            error_message = 'تعداد دفعات مجاز تلاش پس از وقفهٔ کارگر به پایان رسید.',
                            progress_message = 'متوقف‌شده پس از اتمام سقف تلاش مجدد',
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ? AND state = 'RUNNING'
                        """,
                        (job_id,),
                    )
                    cls._log_event(
                        conn=conn,
                        job_id=job_id,
                        attempt_number=attempt,
                        from_state=JobState.RUNNING.value,
                        to_state=JobState.FAILED.value,
                        stage=stage,
                        event_type="FAILED",
                        worker_id=old_worker,
                        message="سقف تلاش مجدد پس از انقضای Lease کارگر به پایان رسید.",
                        error_code="WORKER_CRASH_MAX_RETRIES",
                    )
                recovered += 1

            conn.commit()
            return recovered
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()

    @classmethod
    def pause_job(cls, job_id: str) -> JobItemDTO:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT state, attempt_count, processing_stage FROM jobs WHERE id = ?", (job_id,))
            row = cur.fetchone()
            if not row:
                raise JobNotFoundError(job_id)

            state = row["state"]
            if state not in (JobState.QUEUED.value, JobState.RUNNING.value):
                raise JobStateTransitionError(
                    f"توقف موقت (Pause) برای کار در وضعیت «{state}» مجاز نیست.",
                    code="INVALID_PAUSE_STATE",
                )

            cur.execute(
                """
                UPDATE jobs
                SET state = 'PAUSED',
                    worker_id = NULL,
                    lease_expires_at = NULL,
                    progress_message = 'موقتاً توسط کاربر متوقف شد.',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (job_id,),
            )
            cls._log_event(
                conn=conn,
                job_id=job_id,
                attempt_number=row["attempt_count"],
                from_state=state,
                to_state=JobState.PAUSED.value,
                stage=row["processing_stage"],
                event_type="PAUSED",
                message="کار توسط کاربر متوقف (Paused) شد.",
            )

        res = cls.get_job(job_id, include_events=True)
        if not res:
            raise JobNotFoundError(job_id)
        return res

    @classmethod
    def resume_job(cls, job_id: str) -> JobItemDTO:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT state, attempt_count, processing_stage FROM jobs WHERE id = ?", (job_id,))
            row = cur.fetchone()
            if not row:
                raise JobNotFoundError(job_id)

            state = row["state"]
            if state != JobState.PAUSED.value:
                raise JobStateTransitionError(
                    f"ادامهٔ کار (Resume) فقط برای کارهای متوقف‌شده (PAUSED) مجاز است (وضعیت فعلی: {state}).",
                    code="INVALID_RESUME_STATE",
                )

            cur.execute(
                """
                UPDATE jobs
                SET state = 'QUEUED',
                    next_run_at = CURRENT_TIMESTAMP,
                    progress_message = 'ادامهٔ پردازش در صف قرار گرفت.',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (job_id,),
            )
            cls._log_event(
                conn=conn,
                job_id=job_id,
                attempt_number=row["attempt_count"],
                from_state=state,
                to_state=JobState.QUEUED.value,
                stage=row["processing_stage"],
                event_type="RESUMED",
                message="کار توسط کاربر از سر گرفته شد.",
            )

        res = cls.get_job(job_id, include_events=True)
        if not res:
            raise JobNotFoundError(job_id)
        return res

    @classmethod
    def cancel_job(cls, job_id: str) -> JobItemDTO:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT file_id, state, attempt_count, processing_stage FROM jobs WHERE id = ?", (job_id,))
            row = cur.fetchone()
            if not row:
                raise JobNotFoundError(job_id)

            state = row["state"]
            if state in (JobState.COMPLETED.value, JobState.CANCELLED.value):
                raise JobStateTransitionError(
                    f"لغو کار در وضعیت «{state}» امکان‌پذیر نیست.",
                    code="INVALID_CANCEL_STATE",
                )

            cur.execute(
                """
                UPDATE jobs
                SET state = 'CANCELLED',
                    worker_id = NULL,
                    lease_expires_at = NULL,
                    progress_message = 'لغو شده توسط کاربر.',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (job_id,),
            )
            cls._log_event(
                conn=conn,
                job_id=job_id,
                attempt_number=row["attempt_count"],
                from_state=state,
                to_state=JobState.CANCELLED.value,
                stage=row["processing_stage"],
                event_type="CANCELLED",
                message="کار توسط کاربر لغو شد.",
            )

            # Update file status if it was waiting in queue and not user modified
            cur.execute(
                """
                UPDATE files
                SET status = CASE
                    WHEN is_user_modified = 1 THEN status
                    WHEN status IN ('در صف', 'در حال پردازش') THEN 'نیازمند بازبینی'
                    ELSE status
                END,
                updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (row["file_id"],),
            )

        res = cls.get_job(job_id, include_events=True)
        if not res:
            raise JobNotFoundError(job_id)
        return res

    @classmethod
    def retry_job(cls, job_id: str) -> JobItemDTO:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT file_id, state, attempt_count, max_retries, processing_stage
                FROM jobs WHERE id = ?
                """,
                (job_id,),
            )
            row = cur.fetchone()
            if not row:
                raise JobNotFoundError(job_id)

            state = row["state"]
            if state not in (JobState.FAILED.value, JobState.CANCELLED.value):
                raise JobStateTransitionError(
                    f"تلاش مجدد (Retry) فقط برای کارهای خطادار یا لغوشده مجاز است (وضعیت فعلی: {state}).",
                    code="INVALID_RETRY_STATE",
                )

            attempt = int(row["attempt_count"] or 0)
            max_retries = max(int(row["max_retries"] or 3), attempt + 1)

            cur.execute(
                """
                UPDATE jobs
                SET state = 'QUEUED',
                    max_retries = ?,
                    worker_id = NULL,
                    lease_expires_at = NULL,
                    error_code = NULL,
                    error_message = NULL,
                    next_run_at = CURRENT_TIMESTAMP,
                    progress_message = 'تلاش مجدد به درخواست کاربر در صف قرار گرفت.',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (max_retries, job_id),
            )
            cls._log_event(
                conn=conn,
                job_id=job_id,
                attempt_number=attempt,
                from_state=state,
                to_state=JobState.QUEUED.value,
                stage=row["processing_stage"],
                event_type="RETRY_SCHEDULED",
                message="تلاش مجدد دستی توسط کاربر فعال شد.",
            )

        res = cls.get_job(job_id, include_events=True)
        if not res:
            raise JobNotFoundError(job_id)
        return res

    @classmethod
    def get_job(cls, job_id: str, include_events: bool = True) -> Optional[JobItemDTO]:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT j.*, f.title AS file_title, f.kind AS file_kind, f.status AS file_status
                FROM jobs j
                LEFT JOIN files f ON j.file_id = f.id
                WHERE j.id = ?
                """,
                (job_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return cls._row_to_dto(conn, row, include_events=include_events)

    @classmethod
    def get_job_stats(cls, archive_id: str = "default") -> JobStatsDTO:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT state, COUNT(*) AS cnt
                FROM jobs
                WHERE archive_id = ?
                GROUP BY state
                """,
                (archive_id,),
            )
            counts = {r["state"]: int(r["cnt"]) for r in cur.fetchall()}
            queued = counts.get(JobState.QUEUED.value, 0)
            running = counts.get(JobState.RUNNING.value, 0)
            paused = counts.get(JobState.PAUSED.value, 0)
            completed = counts.get(JobState.COMPLETED.value, 0)
            failed = counts.get(JobState.FAILED.value, 0)
            cancelled = counts.get(JobState.CANCELLED.value, 0)
            total = queued + running + paused + completed + failed + cancelled
            return JobStatsDTO(
                queued=queued,
                running=running,
                paused=paused,
                completed=completed,
                failed=failed,
                cancelled=cancelled,
                total=total,
            )

    @classmethod
    def list_jobs(
        cls,
        state: Optional[str] = None,
        stage: Optional[str] = None,
        file_id: Optional[str] = None,
        archive_id: str = "default",
        limit: int = 50,
        offset: int = 0,
        include_events: bool = False,
    ) -> Tuple[List[JobItemDTO], int]:
        with get_db() as conn:
            cur = conn.cursor()
            where_clauses = ["j.archive_id = ?"]
            params: list = [archive_id]

            if state and state != "ALL":
                where_clauses.append("j.state = ?")
                params.append(state)
            if stage and stage != "ALL":
                where_clauses.append("j.processing_stage = ?")
                params.append(stage)
            if file_id:
                where_clauses.append("j.file_id = ?")
                params.append(file_id)

            where_sql = " AND ".join(where_clauses)
            cur.execute(f"SELECT COUNT(*) FROM jobs j WHERE {where_sql}", params)
            total = int(cur.fetchone()[0])

            sql = f"""
                SELECT j.*, f.title AS file_title, f.kind AS file_kind, f.status AS file_status
                FROM jobs j
                LEFT JOIN files f ON j.file_id = f.id
                WHERE {where_sql}
                ORDER BY
                    CASE j.state
                        WHEN 'RUNNING' THEN 1
                        WHEN 'QUEUED' THEN 2
                        WHEN 'PAUSED' THEN 3
                        WHEN 'FAILED' THEN 4
                        WHEN 'CANCELLED' THEN 5
                        ELSE 6
                    END ASC,
                    j.priority DESC,
                    j.created_at DESC,
                    j.id DESC
                LIMIT ? OFFSET ?
            """
            cur.execute(sql, [*params, limit, offset])
            rows = cur.fetchall()
            items = [cls._row_to_dto(conn, r, include_events=include_events) for r in rows]
            return items, total

    @classmethod
    def upsert_worker_heartbeat(
        cls,
        worker_id: str,
        resource_mode: str,
        concurrency: int,
        active_jobs: int,
        status: str = "ONLINE",
    ) -> None:
        hostname = socket.gethostname()
        pid = os.getpid()
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO worker_registry (
                    worker_id, resource_mode, concurrency, active_jobs, status,
                    hostname, pid, started_at, last_heartbeat_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(worker_id) DO UPDATE SET
                    resource_mode = excluded.resource_mode,
                    concurrency = excluded.concurrency,
                    active_jobs = excluded.active_jobs,
                    status = excluded.status,
                    last_heartbeat_at = CURRENT_TIMESTAMP
                """,
                (worker_id, resource_mode, concurrency, active_jobs, status, hostname, pid),
            )

    @classmethod
    def log_stage_event(
        cls,
        job_id: str,
        stage: str,
        event_type: str,
        message: str,
        worker_id: Optional[str] = None,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT state, attempt_count FROM jobs WHERE id = ?", (job_id,))
            row = cur.fetchone()
            if not row:
                return
            cls._log_event(
                conn=conn,
                job_id=job_id,
                attempt_number=int(row["attempt_count"] or 1),
                from_state=row["state"],
                to_state=row["state"],
                stage=stage,
                event_type=event_type,
                worker_id=worker_id,
                message=message,
                error_code=error_code,
                details=details,
            )

    @classmethod
    def list_workers(cls, ttl_seconds: Optional[int] = None) -> List[WorkerInfoDTO]:
        ttl = max(5, int(ttl_seconds if ttl_seconds is not None else settings.worker_heartbeat_ttl_seconds))
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT worker_id, resource_mode, concurrency, active_jobs,
                       status, hostname, pid, started_at, last_heartbeat_at,
                       CASE
                           WHEN status = 'ONLINE'
                            AND datetime(last_heartbeat_at) >= datetime('now', '-{ttl} seconds')
                           THEN 'ONLINE'
                           ELSE 'OFFLINE'
                       END AS effective_status
                FROM worker_registry
                ORDER BY last_heartbeat_at DESC
                """
            )
            return [
                WorkerInfoDTO(
                    worker_id=r["worker_id"],
                    resource_mode=r["resource_mode"],
                    concurrency=r["concurrency"],
                    active_jobs=r["active_jobs"],
                    status=r["effective_status"],
                    hostname=r["hostname"],
                    pid=r["pid"],
                    started_at=str(r["started_at"]) if r["started_at"] else None,
                    last_heartbeat_at=str(r["last_heartbeat_at"]) if r["last_heartbeat_at"] else None,
                )
                for r in cur.fetchall()
            ]

    @classmethod
    def get_online_worker_summary(
        cls,
        in_process_running: bool = False,
        in_process_mode: str = "Balanced",
        in_process_concurrency: int = 2,
        ttl_seconds: Optional[int] = None,
    ) -> Tuple[bool, int, str, int]:
        """
        Determines real worker availability across both the in-process worker and any
        standalone worker processes (`python -m services.worker.runner` / Docker worker container)
        via SQLite `worker_registry` heartbeats.
        Returns: (worker_online, active_workers_count, resource_mode, concurrency)
        """
        workers = cls.list_workers(ttl_seconds=ttl_seconds)
        online_workers = [w for w in workers if w.status == "ONLINE"]
        if online_workers:
            primary = online_workers[0]
            return True, len(online_workers), primary.resource_mode, primary.concurrency
        if in_process_running:
            return True, 1, in_process_mode, in_process_concurrency
        return False, 0, in_process_mode, in_process_concurrency

