import os
from typing import List, Optional, AsyncIterator
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Request, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, Response
from services.api.config import settings
from services.api.database import init_db, get_db
from services.api.migrations import LegacyMigrationManager
from services.api.repository import (
    ArchiveRepository,
    IngestionValidationError,
    UploadTooLargeError,
    DuplicateFileError,
    StoragePersistenceError,
    DatabasePersistenceError,
)
from services.api.schemas import (
    FileItemDTO,
    FileUpdateDTO,
    TagAddDTO,
    StatsDTO,
    HealthDTO,
    PageItemDTO,
    PageUpdateDTO,
    OCREngineStatusDTO,
    JobItemDTO,
    JobListResponseDTO,
    ReanalyzeRequestDTO,
    ReanalyzeResponseDTO,
    WorkerConfigUpdateDTO,
    LegacyMigrationReportDTO,
    LegacyMigrationApprovalDTO,
    LegacyMigrationResultDTO,
    MigrationAuditItemDTO,
    SessionHandshakeDTO,
)
from services.ingestion.extractor import render_page_preview_png
from services.ocr import get_ocr_engine
from services.worker.queue import (
    JobQueueRepository,
    JobNotFoundError,
    JobStateTransitionError,
)
from services.worker.runner import default_worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    init_db()
    # Recover any interrupted jobs whose lease expired (non-destructive)
    try:
        JobQueueRepository.recover_expired_leases()
    except Exception:
        pass
    # Start independent background worker thread if enabled
    if settings.enable_background_worker:
        default_worker.start()
    try:
        yield
    finally:
        if default_worker.is_running:
            default_worker.stop()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="سرویس محلی و آفلاین ساهر برای بایگانی هوشمند، موتور پردازش پایدار کارها و جست‌وجوی FTS5",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Content-Type",
        "Accept",
        "X-Saher-Client",
        "X-Saher-Session-Token",
        "X-Saher-Async",
        "Authorization",
    ],
)


def _is_allowed_origin(origin: str) -> bool:
    normalized = origin.strip().rstrip("/")
    allowed = {o.strip().rstrip("/") for o in settings.cors_origins if o}
    return normalized in allowed


@app.middleware("http")
async def security_and_origin_middleware(request: Request, call_next):
    # 1. Validate Origin against explicit allowlist on state-changing requests
    if request.method in ("POST", "PATCH", "PUT", "DELETE"):
        origin = request.headers.get("origin")
        if origin and not _is_allowed_origin(origin):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "مبدأ درخواست (Origin) در فهرست مجاز سرویس محلی ساهر قرار ندارد.",
                    "code": "FORBIDDEN_ORIGIN",
                },
            )

        # 2. Validate local session token if session authentication is enabled or header is explicitly supplied
        supplied_token = request.headers.get("x-saher-session-token")
        auth_header = request.headers.get("authorization", "")
        if not supplied_token and auth_header.lower().startswith("bearer "):
            supplied_token = auth_header[7:].strip()

        if settings.session_auth_required:
            if not supplied_token or supplied_token != settings.session_token:
                return JSONResponse(
                    status_code=401,
                    content={
                        "detail": "توکن نشست محلی (Session Token) معتبر نیست یا ارسال نشده است.",
                        "code": "UNAUTHORIZED_SESSION",
                    },
                )
        elif supplied_token is not None and supplied_token != settings.session_token:
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "توکن نشست ارسالی نامعتبر است.",
                    "code": "UNAUTHORIZED_SESSION",
                },
            )

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response


@app.exception_handler(IngestionValidationError)
async def handle_validation_error(request: Request, exc: IngestionValidationError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message, "code": exc.code},
    )


@app.exception_handler(UploadTooLargeError)
async def handle_upload_too_large(request: Request, exc: UploadTooLargeError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message, "code": exc.code},
    )


@app.exception_handler(DuplicateFileError)
async def handle_duplicate_error(request: Request, exc: DuplicateFileError):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.message,
            "code": exc.code,
            "existing_file_id": exc.existing_id,
            "existing_title": exc.existing_title,
        },
    )


@app.exception_handler(StoragePersistenceError)
async def handle_storage_error(request: Request, exc: StoragePersistenceError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message, "code": exc.code},
    )


@app.exception_handler(DatabasePersistenceError)
async def handle_db_error(request: Request, exc: DatabasePersistenceError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message, "code": exc.code},
    )


@app.exception_handler(JobNotFoundError)
async def handle_job_not_found(request: Request, exc: JobNotFoundError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message, "code": exc.code},
    )


@app.exception_handler(JobStateTransitionError)
async def handle_job_transition_error(request: Request, exc: JobStateTransitionError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message, "code": exc.code},
    )


@app.get("/health", response_model=HealthDTO)
def health_check():
    db_ok = False
    try:
        with get_db() as conn:
            conn.execute("SELECT 1").fetchone()
            db_ok = True
    except Exception:
        db_ok = False

    storage_ok = os.path.exists(settings.storage_dir) and os.access(settings.storage_dir, os.W_OK)
    overall_status = "healthy" if (db_ok and storage_ok) else "degraded"

    worker_online = default_worker.is_running
    active_workers_count = 1 if default_worker.is_running else 0
    eff_mode = default_worker.profile.mode
    if db_ok:
        try:
            worker_online, active_workers_count, eff_mode, _ = JobQueueRepository.get_online_worker_summary(
                in_process_running=default_worker.is_running,
                in_process_mode=default_worker.profile.mode,
                in_process_concurrency=default_worker.profile.concurrency,
            )
        except Exception:
            pass

    ocr_status = get_ocr_engine().inspect_status()

    return HealthDTO(
        status=overall_status,
        version=settings.app_version,
        database="sqlite3_fts5" if db_ok else "unavailable",
        storage_accessible=storage_ok,
        demo_mode=settings.demo_mode,
        max_upload_size_bytes=settings.max_upload_size_bytes,
        worker_online=worker_online,
        active_workers_count=active_workers_count,
        resource_mode=eff_mode,
        ocr_ready=ocr_status.ready,
        ocr_engine=ocr_status.engine_name,
        ocr_languages=ocr_status.installed_languages,
    )


@app.get(f"{settings.api_prefix}/ocr/status", response_model=OCREngineStatusDTO)
def get_ocr_status():
    st = get_ocr_engine().inspect_status()
    return OCREngineStatusDTO(
        ready=st.ready,
        engine_name=st.engine_name,
        engine_version=st.engine_version,
        model_dir=st.model_dir,
        installed_languages=st.installed_languages,
        required_languages=st.required_languages,
        missing_languages=st.missing_languages,
        offline_ready=st.offline_ready,
        error_code=st.error_code,
        error_message=st.error_message,
    )


@app.get(f"{settings.api_prefix}/auth/session", response_model=SessionHandshakeDTO)
def get_session_handshake(request: Request):
    origin = request.headers.get("origin")
    if origin and not _is_allowed_origin(origin):
        raise HTTPException(status_code=403, detail="Origin not allowed")
    return SessionHandshakeDTO(
        session_auth_required=settings.session_auth_required,
        session_token=settings.session_token if settings.session_auth_required else None,
        allowed_origins=settings.cors_origins,
    )


@app.get(f"{settings.api_prefix}/stats", response_model=StatsDTO)
def get_stats():
    return ArchiveRepository.get_stats()


@app.get(f"{settings.api_prefix}/files", response_model=List[FileItemDTO])
def list_files(
    kind: Optional[str] = Query(None),
    query: Optional[str] = Query(None, max_length=256),
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    return ArchiveRepository.list_files(
        kind=kind,
        query=query,
        status=status,
        limit=limit,
        offset=offset,
    )


@app.get(f"{settings.api_prefix}/files/{{file_id}}", response_model=FileItemDTO)
def get_file_detail(file_id: str):
    file_item = ArchiveRepository.get_file(file_id)
    if not file_item:
        raise HTTPException(status_code=404, detail="فایل مورد نظر در آرشیو یافت نشد.")
    return file_item


@app.get(f"{settings.api_prefix}/files/{{file_id}}/content")
def get_file_content(file_id: str):
    info = ArchiveRepository.get_file_storage_path(file_id)
    if not info:
        raise HTTPException(status_code=404, detail="فایل فیزیکی در مخزن یافت نشد.")
    storage_path, mime_type, title = info
    headers = {
        "Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox",
        "X-Content-Type-Options": "nosniff",
    }
    return FileResponse(
        path=storage_path,
        media_type=mime_type,
        filename=title,
        content_disposition_type="inline" if mime_type.startswith(("image/", "application/pdf", "text/")) else "attachment",
        headers=headers,
    )


@app.get(f"{settings.api_prefix}/files/{{file_id}}/pages", response_model=List[PageItemDTO])
def list_file_pages(file_id: str):
    file_item = ArchiveRepository.get_file(file_id)
    if not file_item:
        raise HTTPException(status_code=404, detail="فایل مورد نظر در آرشیو یافت نشد.")
    return ArchiveRepository.get_file_pages(file_id)


@app.patch(f"{settings.api_prefix}/files/{{file_id}}/pages/{{page_number}}", response_model=PageItemDTO)
def update_file_page_text(file_id: str, page_number: int, payload: PageUpdateDTO):
    updated_page = ArchiveRepository.update_page_text(
        file_id=file_id,
        page_number=page_number,
        raw_text=payload.raw_text,
    )
    if not updated_page:
        raise HTTPException(status_code=404, detail="صفحه یا فایل مورد نظر یافت نشد.")
    return updated_page


@app.get(f"{settings.api_prefix}/files/{{file_id}}/pages/{{page_number}}/preview")
def get_file_page_preview(file_id: str, page_number: int):
    info = ArchiveRepository.get_file_storage_path(file_id)
    if not info:
        raise HTTPException(status_code=404, detail="فایل فیزیکی در مخزن یافت نشد.")
    storage_path, mime_type, title = info
    pages = ArchiveRepository.get_file_pages(file_id)
    fallback_text = ""
    for p in pages:
        if p.page_number == page_number:
            fallback_text = p.normalized_text or p.raw_text or p.error_message or ""
            break
    try:
        png_bytes = render_page_preview_png(
            file_path=storage_path,
            mime_type=mime_type,
            page_number=max(1, page_number),
            fallback_text=fallback_text,
            title=title,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"خطا در تولید پیش‌نمایش صفحهٔ {page_number}: {exc}") from exc

    headers = {
        "Content-Security-Policy": "default-src 'none'; img-src 'self' data:; sandbox",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-cache",
    }
    return Response(content=png_bytes, media_type="image/png", headers=headers)


@app.post(f"{settings.api_prefix}/files/import", response_model=FileItemDTO)
async def import_file(
    request: Request,
    file: UploadFile = File(...),
    topic: Optional[str] = Form(None),
    async_mode: Optional[bool] = Form(None),
    async_query: Optional[bool] = Query(None, alias="async_mode"),
):
    filename = file.filename or "unnamed_file"
    header_async = request.headers.get("x-saher-async", "").lower() in ("1", "true", "yes")
    use_async = bool(async_mode) or bool(async_query) or header_async

    async def chunk_reader() -> AsyncIterator[bytes]:
        while True:
            chunk = await file.read(settings.upload_chunk_size)
            if not chunk:
                break
            yield chunk

    try:
        return await ArchiveRepository.save_uploaded_stream(
            filename=filename,
            chunk_iterator=chunk_reader(),
            custom_topic=topic,
            async_mode=use_async,
        )
    finally:
        await file.close()


@app.post(f"{settings.api_prefix}/files/{{file_id}}/reanalyze", response_model=ReanalyzeResponseDTO)
def reanalyze_file(
    file_id: str,
    payload: Optional[ReanalyzeRequestDTO] = Body(default=None),
):
    req = payload or ReanalyzeRequestDTO()
    file_item = ArchiveRepository.get_file(file_id)
    if not file_item:
        raise HTTPException(status_code=404, detail="فایل مورد نظر در آرشیو یافت نشد.")

    job_dto, created_new = JobQueueRepository.enqueue_reanalysis(
        file_id=file_id,
        stage=req.stage,
        priority=req.priority,
    )
    if created_new and default_worker.is_running:
        default_worker.notify()

    msg = (
        "کار بازپردازش جدید در صف قرار گرفت."
        if created_new
        else "یک کار فعال برای این فایل از قبل در صف وجود دارد (جلوگیری از کار تکراری)."
    )
    return ReanalyzeResponseDTO(
        job=job_dto,
        created_new=created_new,
        message=msg,
    )


@app.patch(f"{settings.api_prefix}/files/{{file_id}}", response_model=FileItemDTO)
def update_file(file_id: str, payload: FileUpdateDTO):
    updated = ArchiveRepository.update_file(
        file_id=file_id,
        topic=payload.topic,
        status=payload.status,
        tags=payload.tags,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="فایل یافت نشد.")
    return updated


@app.post(f"{settings.api_prefix}/files/{{file_id}}/tags", response_model=FileItemDTO)
def add_tag(file_id: str, payload: TagAddDTO):
    item = ArchiveRepository.get_file(file_id)
    if not item:
        raise HTTPException(status_code=404, detail="فایل یافت نشد.")
    tag = payload.tag.strip()
    if not tag:
        raise HTTPException(status_code=400, detail="عنوان برچسب نمی‌تواند خالی باشد.")
    if tag not in item.tags:
        new_tags = list(item.tags) + [tag]
        updated = ArchiveRepository.update_file(file_id=file_id, tags=new_tags)
        if not updated:
            raise HTTPException(status_code=404, detail="فایل یافت نشد.")
        return updated
    return item


@app.delete(f"{settings.api_prefix}/files/{{file_id}}/tags/{{tag_name}}", response_model=FileItemDTO)
def remove_tag(file_id: str, tag_name: str):
    item = ArchiveRepository.get_file(file_id)
    if not item:
        raise HTTPException(status_code=404, detail="فایل یافت نشد.")
    new_tags = [t for t in item.tags if t != tag_name]
    updated = ArchiveRepository.update_file(file_id=file_id, tags=new_tags)
    if not updated:
        raise HTTPException(status_code=404, detail="فایل یافت نشد.")
    return updated


# ============================================================================
# Milestone 2: Job Management & Worker Resource APIs
# ============================================================================


@app.get(f"{settings.api_prefix}/jobs", response_model=JobListResponseDTO)
def list_jobs(
    state: Optional[str] = Query(None),
    stage: Optional[str] = Query(None),
    file_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    items, total = JobQueueRepository.list_jobs(
        state=state,
        stage=stage,
        file_id=file_id,
        limit=limit,
        offset=offset,
        include_events=False,
    )
    stats = JobQueueRepository.get_job_stats()
    workers = JobQueueRepository.list_workers()
    _, _, eff_mode, eff_conc = JobQueueRepository.get_online_worker_summary(
        in_process_running=default_worker.is_running,
        in_process_mode=default_worker.profile.mode,
        in_process_concurrency=default_worker.profile.concurrency,
    )
    return JobListResponseDTO(
        total=total,
        limit=limit,
        offset=offset,
        stats=stats,
        workers=workers,
        resource_mode=eff_mode,
        worker_concurrency=eff_conc,
        items=items,
    )


@app.get(f"{settings.api_prefix}/jobs/{{job_id}}", response_model=JobItemDTO)
def get_job_detail(job_id: str):
    job = JobQueueRepository.get_job(job_id, include_events=True)
    if not job:
        raise JobNotFoundError(job_id)
    return job


@app.post(f"{settings.api_prefix}/jobs/{{job_id}}/pause", response_model=JobItemDTO)
def pause_job(job_id: str):
    return JobQueueRepository.pause_job(job_id)


@app.post(f"{settings.api_prefix}/jobs/{{job_id}}/resume", response_model=JobItemDTO)
def resume_job(job_id: str):
    job = JobQueueRepository.resume_job(job_id)
    if default_worker.is_running:
        default_worker.notify()
    return job


@app.post(f"{settings.api_prefix}/jobs/{{job_id}}/cancel", response_model=JobItemDTO)
def cancel_job(job_id: str):
    return JobQueueRepository.cancel_job(job_id)


@app.post(f"{settings.api_prefix}/jobs/{{job_id}}/retry", response_model=JobItemDTO)
def retry_job(job_id: str):
    job = JobQueueRepository.retry_job(job_id)
    if default_worker.is_running:
        default_worker.notify()
    return job


@app.post(f"{settings.api_prefix}/workers/config")
def update_worker_config(payload: WorkerConfigUpdateDTO):
    prof = default_worker.configure_resources(
        resource_mode=payload.resource_mode,
        concurrency=payload.concurrency,
    )
    return {
        "resource_mode": prof.mode,
        "concurrency": prof.concurrency,
        "poll_interval_seconds": prof.poll_interval_seconds,
        "lease_seconds": prof.lease_seconds,
        "worker_online": default_worker.is_running,
    }


# ============================================================================
# Safe Migration Preview, Backup Approval & Restoration APIs
# ============================================================================


@app.get(f"{settings.api_prefix}/migrations/legacy-preview", response_model=LegacyMigrationReportDTO)
def preview_legacy_migration():
    return LegacyMigrationManager.inspect_legacy_records(log_dry_run=True)


@app.post(f"{settings.api_prefix}/migrations/legacy-cleanup", response_model=LegacyMigrationResultDTO)
def execute_legacy_migration(payload: LegacyMigrationApprovalDTO):
    if not payload.confirm_approval:
        raise IngestionValidationError(
            "حذف رکوردهای نمونهٔ قدیمی بدون تأیید صریح کاربر مجاز نیست.",
            code="APPROVAL_REQUIRED",
            status_code=400,
        )
    return LegacyMigrationManager.execute_approved_cleanup(confirm_approval=True)


@app.post(f"{settings.api_prefix}/migrations/restore/{{backup_id}}", response_model=LegacyMigrationResultDTO)
def restore_legacy_migration_backup(backup_id: str):
    try:
        return LegacyMigrationManager.restore_backup(backup_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get(f"{settings.api_prefix}/migrations/audits", response_model=List[MigrationAuditItemDTO])
def list_migration_audits():
    return LegacyMigrationManager.list_audits()
