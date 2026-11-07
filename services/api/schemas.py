from typing import Optional, List
from pydantic import BaseModel, Field

class FileItemDTO(BaseModel):
    id: str
    archive_id: str = "default"
    title: str
    kind: str  # 'سند', 'تصویر', 'اسکرین‌شات'
    topic: str = "کار"
    status: str = "آماده"  # 'آماده', 'در صف', 'در حال پردازش', 'تحلیل ناقص', 'نیازمند بازبینی', 'خطا'
    mime_type: str
    file_size: int
    sha256: str
    text: str = ""
    extraction_status: str = "extracted"  # 'extracted' | 'empty' | 'pending_ocr' | 'unsupported' | 'failed'
    extraction_method: str = "direct_text"
    system_note: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    matched_snippet: Optional[str] = None
    is_user_modified: bool = False
    color: str = "paper"
    tags: List[str] = Field(default_factory=list)
    page_count: int = 1
    created_at: str
    updated_at: Optional[str] = None

class FileUpdateDTO(BaseModel):
    topic: Optional[str] = None
    status: Optional[str] = None
    tags: Optional[List[str]] = None

class TagAddDTO(BaseModel):
    tag: str = Field(..., min_length=1, max_length=64)

class StatsDTO(BaseModel):
    total_files: int
    ready_files: int
    attention_files: int
    demo_mode: bool = False

class FileListResponseDTO(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[FileItemDTO]

class HealthDTO(BaseModel):
    status: str
    version: str
    database: str
    storage_accessible: bool
    demo_mode: bool = False
    max_upload_size_bytes: int
