import os
from typing import List, Optional, AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from services.api.config import settings
from services.api.database import init_db, get_db
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
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    init_db()
    ArchiveRepository.purge_legacy_fake_seed_records()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="سرویس محلی و آفلاین ساهر برای بایگانی هوشمند، استخراج اسناد و جست‌وجو",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Accept", "X-Saher-Client"],
)


def _is_allowed_origin(origin: str) -> bool:
    if origin in settings.cors_origins:
        return True
    try:
        parsed = urlparse(origin)
        if parsed.scheme in ("http", "https") and parsed.hostname in ("localhost", "127.0.0.1", "0.0.0.0"):
            return True
        if parsed.hostname and parsed.hostname.endswith(".run.app"):
            return True
    except Exception:
        pass
    return False


@app.middleware("http")
async def security_and_origin_middleware(request: Request, call_next):
    # Validate Origin on state-changing requests to prevent cross-origin local CSRF
    if request.method in ("POST", "PATCH", "PUT", "DELETE"):
        origin = request.headers.get("origin")
        if origin and not _is_allowed_origin(origin):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "مبدأ درخواست (Origin) برای دسترسی به سرویس محلی مجاز نیست.",
                    "code": "FORBIDDEN_ORIGIN",
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
    return HealthDTO(
        status=overall_status,
        version=settings.app_version,
        database="sqlite3_fts5" if db_ok else "unavailable",
        storage_accessible=storage_ok,
        demo_mode=settings.demo_mode,
        max_upload_size_bytes=settings.max_upload_size_bytes,
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


@app.post(f"{settings.api_prefix}/files/import", response_model=FileItemDTO)
async def import_file(
    file: UploadFile = File(...),
    topic: Optional[str] = Form(None),
):
    filename = file.filename or "unnamed_file"

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
        )
    finally:
        await file.close()


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
