import os
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from services.api.config import settings
from services.api.database import init_db
from services.api.repository import ArchiveRepository
from services.api.schemas import (
    FileItemDTO,
    FileUpdateDTO,
    TagAddDTO,
    StatsDTO,
    HealthDTO
)

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    ArchiveRepository.seed_initial_records_if_empty()
    yield

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="سرویس محلی و آفلاین ساهر برای بایگانی هوشمند، استخراج اسناد و جست‌وجو",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health", response_model=HealthDTO)
def health_check():
    db_ok = os.path.exists(settings.db_path)
    storage_ok = os.path.exists(settings.storage_dir) and os.access(settings.storage_dir, os.W_OK)
    return HealthDTO(
        status="healthy",
        version=settings.app_version,
        database="sqlite3_fts5",
        storage_accessible=storage_ok
    )

@app.get(f"{settings.api_prefix}/stats", response_model=StatsDTO)
def get_stats():
    return ArchiveRepository.get_stats()

@app.get(f"{settings.api_prefix}/files", response_model=List[FileItemDTO])
def list_files(
    kind: Optional[str] = Query(None),
    query: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500)
):
    return ArchiveRepository.list_files(kind=kind, query=query, status=status, limit=limit)

@app.get(f"{settings.api_prefix}/files/{{file_id}}", response_model=FileItemDTO)
def get_file_detail(file_id: str):
    file_item = ArchiveRepository.get_file(file_id)
    if not file_item:
        raise HTTPException(status_code=404, detail="فایل مورد نظر در آرشیو یافت نشد.")
    return file_item

@app.post(f"{settings.api_prefix}/files/import", response_model=FileItemDTO)
async def import_file(
    file: UploadFile = File(...),
    topic: Optional[str] = Form(None)
):
    try:
        content = await file.read()
        filename = file.filename or "unknown_file"
        item = ArchiveRepository.save_imported_file(
            filename=filename,
            content=content,
            custom_topic=topic
        )
        return item
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطا در واردسازی و ذخیرهٔ فایل: {str(e)}")

@app.patch(f"{settings.api_prefix}/files/{{file_id}}", response_model=FileItemDTO)
def update_file(file_id: str, payload: FileUpdateDTO):
    updated = ArchiveRepository.update_file(
        file_id=file_id,
        topic=payload.topic,
        status=payload.status,
        tags=payload.tags
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
    if tag and tag not in item.tags:
        new_tags = list(item.tags) + [tag]
        updated = ArchiveRepository.update_file(file_id=file_id, tags=new_tags)
        return updated
    return item

@app.delete(f"{settings.api_prefix}/files/{{file_id}}/tags/{{tag_name}}", response_model=FileItemDTO)
def remove_tag(file_id: str, tag_name: str):
    item = ArchiveRepository.get_file(file_id)
    if not item:
        raise HTTPException(status_code=404, detail="فایل یافت نشد.")
    new_tags = [t for t in item.tags if t != tag_name]
    updated = ArchiveRepository.update_file(file_id=file_id, tags=new_tags)
    return updated
