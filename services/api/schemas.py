from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class BoundingBoxDTO(BaseModel):
    text: str
    x: int
    y: int
    width: int
    height: int
    confidence: float = 100.0
    line_num: int = 1
    block_num: int = 1
    direction: str = "rtl"


class PageItemDTO(BaseModel):
    id: str
    file_id: str
    page_number: int
    raw_text: str = ""
    normalized_text: str = ""
    bboxes: List[BoundingBoxDTO] = Field(default_factory=list)
    extraction_method: str = "direct_text"
    page_status: str = "extracted"  # 'extracted' | 'empty' | 'pending_ocr' | 'failed' | 'user_modified'
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    ocr_confidence: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    is_user_modified: bool = False
    updated_at: Optional[str] = None


class PageUpdateDTO(BaseModel):
    raw_text: str = Field(..., max_length=200000)


class OCREngineStatusDTO(BaseModel):
    ready: bool
    engine_name: str
    engine_version: str
    model_dir: str
    installed_languages: List[str] = Field(default_factory=list)
    required_languages: List[str] = Field(default_factory=list)
    missing_languages: List[str] = Field(default_factory=list)
    offline_ready: bool = False
    error_code: Optional[str] = None
    error_message: Optional[str] = None


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
    extraction_status: str = "extracted"  # 'extracted' | 'empty' | 'pending_ocr' | 'partial_ocr' | 'unsupported' | 'failed' | 'queued'
    extraction_method: str = "direct_text"
    extraction_version: int = 1
    processing_version: int = 1
    latest_job_id: Optional[str] = None
    job_state: Optional[str] = None
    processing_stage: Optional[str] = None
    processing_progress: Optional[float] = None
    system_note: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    matched_snippet: Optional[str] = None
    matched_page: Optional[int] = None
    matched_pages: List[int] = Field(default_factory=list)
    failed_pages: List[int] = Field(default_factory=list)
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
    queued_jobs: int = 0
    running_jobs: int = 0
    failed_jobs: int = 0
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
    worker_online: bool = True
    active_workers_count: int = 1
    resource_mode: str = "Balanced"
    ocr_ready: bool = True
    ocr_engine: str = "tesseract"
    ocr_languages: List[str] = Field(default_factory=list)


class JobEventDTO(BaseModel):
    id: int
    job_id: str
    attempt_number: int
    from_state: Optional[str] = None
    to_state: str
    stage: str
    event_type: str
    worker_id: Optional[str] = None
    message: Optional[str] = None
    error_code: Optional[str] = None
    created_at: str


class JobItemDTO(BaseModel):
    id: str
    archive_id: str = "default"
    file_id: str
    file_title: str = ""
    file_kind: str = "سند"
    file_status: str = "در صف"
    job_type: str = "FILE_INGESTION"
    target_stage: Optional[str] = None
    processing_stage: str = "DISCOVERY"
    state: str = "QUEUED"  # QUEUED | RUNNING | PAUSED | COMPLETED | FAILED | CANCELLED
    priority: int = 50
    attempt_count: int = 0
    max_retries: int = 3
    progress: float = 0.0
    progress_message: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    is_retryable: bool = True
    worker_id: Optional[str] = None
    lease_expires_at: Optional[str] = None
    heartbeat_at: Optional[str] = None
    next_run_at: Optional[str] = None
    processing_version: int = 1
    checkpoint: Dict[str, Any] = Field(default_factory=dict)
    created_at: str
    started_at: Optional[str] = None
    updated_at: Optional[str] = None
    completed_at: Optional[str] = None
    events: List[JobEventDTO] = Field(default_factory=list)


class JobStatsDTO(BaseModel):
    queued: int = 0
    running: int = 0
    paused: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0
    total: int = 0


class WorkerInfoDTO(BaseModel):
    worker_id: str
    resource_mode: str = "Balanced"
    concurrency: int = 2
    active_jobs: int = 0
    status: str = "ONLINE"
    hostname: Optional[str] = None
    pid: Optional[int] = None
    started_at: Optional[str] = None
    last_heartbeat_at: Optional[str] = None


class JobListResponseDTO(BaseModel):
    total: int
    limit: int
    offset: int
    stats: JobStatsDTO
    workers: List[WorkerInfoDTO] = Field(default_factory=list)
    resource_mode: str = "Balanced"
    worker_concurrency: int = 2
    items: List[JobItemDTO]


class ReanalyzeRequestDTO(BaseModel):
    stage: Optional[str] = Field(
        None,
        description="Optional stage to target: DISCOVERY, VALIDATION, EXTRACTION, OCR_PENDING, ANALYSIS_PENDING, INDEXING",
    )
    priority: int = Field(60, ge=1, le=100)


class ReanalyzeResponseDTO(BaseModel):
    job: JobItemDTO
    created_new: bool
    message: str


class WorkerConfigUpdateDTO(BaseModel):
    resource_mode: str = Field(..., pattern="^(Eco|Balanced|Performance)$")
    concurrency: Optional[int] = Field(None, ge=1, le=8)


class LegacyCandidateDTO(BaseModel):
    file_id: str
    title: str
    mime_type: str
    classification: str  # 'candidate_fake_png' | 'candidate_untouched_seed' | 'preserved_user_modified' | 'preserved_genuine_or_ambiguous'
    reason: str
    is_user_modified: bool


class LegacyMigrationReportDTO(BaseModel):
    total_inspected: int
    candidate_count: int
    preserved_count: int
    requires_approval: bool = True
    candidates: List[LegacyCandidateDTO] = Field(default_factory=list)
    preserved: List[LegacyCandidateDTO] = Field(default_factory=list)


class LegacyMigrationApprovalDTO(BaseModel):
    confirm_approval: bool = False


class LegacyMigrationResultDTO(BaseModel):
    executed: bool
    removed_count: int
    preserved_count: int
    backup_id: Optional[str] = None
    backup_path: Optional[str] = None
    audit_id: str
    message: str


class MigrationAuditItemDTO(BaseModel):
    id: str
    operation_type: str
    backup_id: Optional[str] = None
    backup_path: Optional[str] = None
    affected_count: int
    preserved_count: int
    created_at: str


class SessionHandshakeDTO(BaseModel):
    session_auth_required: bool
    session_token: Optional[str] = None
    allowed_origins: List[str]
