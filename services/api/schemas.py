from typing import Optional, List
from pydantic import BaseModel, Field

class FileItemDTO(BaseModel):
    id: str
    archive_id: str = "default"
    title: str
    kind: str # 'سند', 'تصویر', 'اسکرین‌شات'
    topic: str = "کار"
    status: str = "آماده" # 'آماده', 'در صف', 'در حال پردازش', 'تحلیل ناقص', 'نیازمند بازبینی', 'خطا'
    mime_type: str
    file_size: int
    sha256: str
    text: str = ""
    color: str = "paper"
    tags: List[str] = Field(default_factory=list)
    page_count: int = 1
    created_at: str
    error_message: Optional[str] = None

class FileUpdateDTO(BaseModel):
    topic: Optional[str] = None
    status: Optional[str] = None
    tags: Optional[List[str]] = None

class TagAddDTO(BaseModel):
    tag: str

class StatsDTO(BaseModel):
    total_files: int
    ready_files: int
    attention_files: int

class SearchResponseDTO(BaseModel):
    query: str
    total: int
    items: List[FileItemDTO]

class HealthDTO(BaseModel):
    status: str
    version: str
    database: str
    storage_accessible: bool
