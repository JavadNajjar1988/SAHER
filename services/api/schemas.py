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
    available_engines: List[Dict[str, Any]] = Field(default_factory=list)
    paddleocr_metadata: Optional[Dict[str, Any]] = None


class OCREngineSwitchDTO(BaseModel):
    engine_name: str = Field(..., pattern="^(paddleocr|hybrid|tesseract)$")


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


class CulturalSocialTemplateFieldsDTO(BaseModel):
    full_name: str = ""
    national_id: str = ""
    phone_number: str = ""
    guidance_date: str = ""
    numeric_id: str = ""
    account_handle: str = ""
    description: str = ""
    city_hashtag: str = "#کاشمر"
    occupation: str = ""
    violation: str = "ترویج ابتذال"
    action_request: str = "درخواست مسدودی سیم کارت"
    profile_url: str = ""
    hashtags: List[str] = Field(
        default_factory=lambda: ["#ابتذال", "#خراسان_رضوی", "#شهرستان_کاشمر"]
    )
    cultural_template_text: str = ""
    social_template_text: str = ""


class PersonalIdentityDTO(BaseModel):
    has_identity_data: bool = False
    first_name: str = ""
    last_name: str = ""
    full_name: str = ""
    father_name: str = ""
    national_id: str = ""
    birth_certificate_no: str = ""
    birth_date: str = ""
    birth_place: str = ""
    occupation: str = ""
    mobile_phone: str = ""
    secondary_mobile: str = ""
    landline_phone: str = ""
    province: str = ""
    city: str = ""
    address: str = ""
    postal_code: str = ""
    location_name: str = ""
    gps_coordinates: str = ""
    account_handle: str = ""
    account_label: str = ""
    numeric_id: str = ""
    profile_url: str = ""
    personal_folder: str = ""
    thematic_category: str = "اجتماعی"


class CriminalAssessmentDTO(BaseModel):
    has_criminal_indicator: bool = False
    risk_level: str = "عادی (فاقد مصداق مجرمانهٔ آشکار در عنوان و متن)"
    criminal_charges: List[str] = Field(default_factory=list)
    legal_articles: List[str] = Field(default_factory=list)
    evidence_quotes: List[str] = Field(default_factory=list)
    exact_text_inspection: str = ""
    judicial_summary: str = ""
    recommended_action: str = ""


class ImageAnalysisItemDTO(BaseModel):
    file_id: str
    title: str
    relative_path: str = ""
    mime_type: str = "image/png"
    file_size: int = 0
    width: int = 0
    height: int = 0
    aspect_ratio: float = 1.0
    orientation: str = "افقی"
    color_mode: str = "RGB"
    dominant_color_hex: str = "#F5F3EE"
    color_profile_label: str = "زمینهٔ روشن کاغذی"
    mean_brightness: float = 240.0
    contrast_std: float = 25.0
    paper_bg_ratio: float = 0.8
    edge_density: float = 0.05
    word_count: int = 0
    char_count: int = 0
    line_count: int = 0
    bbox_count: int = 0
    ocr_confidence: Optional[float] = None
    ocr_engine: str = "paddleocr"
    extracted_text: str = ""
    personal_folder: str = "پوشهٔ عمومی آرشیو"
    account_id: str = ""
    account_username: str = ""
    account_label: str = "بدون نام کاربری / آیدی مشخص"
    platform_source: str = "اسکرین‌شات / تصویر عمومی"
    capture_source_category: str = "اسکرین‌شات موبایل / شبکهٔ اجتماعی"
    subject_classification: str = "پست یا استوری شبکهٔ اجتماعی"
    camera_info: str = "بدون فرادادهٔ دوربین"
    location_name: str = "موقعیت مکانی ثبت‌نشده"
    gps_coordinates: str = ""
    detected_caption: str = ""
    thematic_category: str = "اجتماعی"
    image_nature: str = "سند یا برگهٔ متنی اسکن‌شده"
    detected_topic: str = "اجتماعی"
    confidence_label: str = "بالا"
    tags: List[str] = Field(default_factory=list)
    key_findings: List[str] = Field(default_factory=list)
    analysis_summary: str = ""
    personal_identity: PersonalIdentityDTO = Field(default_factory=PersonalIdentityDTO)
    criminal_assessment: CriminalAssessmentDTO = Field(default_factory=CriminalAssessmentDTO)
    template_applicable: bool = False
    template_fields: Optional[CulturalSocialTemplateFieldsDTO] = None
    formatted_template_text: str = ""


class FolderAnalysisResponseDTO(BaseModel):
    folder_name: str
    total_images: int
    ocr_engine: str = "paddleocr"
    account_breakdown: Dict[str, int] = Field(default_factory=dict)
    account_category_tree: Dict[str, Dict[str, int]] = Field(default_factory=dict)
    topic_breakdown: Dict[str, int] = Field(default_factory=dict)
    nature_breakdown: Dict[str, int] = Field(default_factory=dict)
    source_type_breakdown: Dict[str, int] = Field(default_factory=dict)
    location_breakdown: Dict[str, int] = Field(default_factory=dict)
    criminal_count: int = 0
    items: List[ImageAnalysisItemDTO] = Field(default_factory=list)


class ImageWordExportRequestDTO(BaseModel):
    file_ids: List[str] = Field(..., min_length=1, max_length=200)
    folder_name: Optional[str] = Field(default="پوشهٔ تصاویر انتخابی", max_length=200)
    source_url: Optional[str] = Field(default=None, max_length=500)
    ocr_engine: Optional[str] = Field(default=None, max_length=64)
    template_overrides_by_file: Optional[Dict[str, Dict[str, Any]]] = None


class IdentityProfileItemDTO(BaseModel):
    id: str
    source_file_id: Optional[str] = None
    first_name: str = ""
    last_name: str = ""
    full_name: str = ""
    father_name: str = ""
    national_id: str = ""
    birth_certificate_no: str = ""
    birth_date: str = ""
    birth_place: str = ""
    occupation: str = ""
    mobile_phone: str = ""
    secondary_mobile: str = ""
    landline_phone: str = ""
    province: str = ""
    city: str = ""
    address: str = ""
    postal_code: str = ""
    gps_coordinates: str = ""
    location_name: str = ""
    account_handle: str = ""
    numeric_id: str = ""
    profile_url: str = ""
    personal_folder: str = ""
    thematic_category: str = "اجتماعی"
    risk_level: str = "عادی"
    judicial_notes: str = ""
    created_at: str = ""
    updated_at: str = ""


class IdentityProfileUpsertDTO(BaseModel):
    source_file_id: Optional[str] = None
    first_name: str = ""
    last_name: str = ""
    full_name: str = ""
    father_name: str = ""
    national_id: str = ""
    birth_certificate_no: str = ""
    birth_date: str = ""
    birth_place: str = ""
    occupation: str = ""
    mobile_phone: str = ""
    secondary_mobile: str = ""
    landline_phone: str = ""
    province: str = ""
    city: str = ""
    address: str = ""
    postal_code: str = ""
    gps_coordinates: str = ""
    location_name: str = ""
    account_handle: str = ""
    numeric_id: str = ""
    profile_url: str = ""
    personal_folder: str = ""
    thematic_category: str = "اجتماعی"
    risk_level: str = "عادی"
    judicial_notes: str = ""


class IdentityProfileListResponseDTO(BaseModel):
    total: int
    items: List[IdentityProfileItemDTO] = Field(default_factory=list)


class IdentityProfileWordExportRequestDTO(BaseModel):
    profile_ids: Optional[List[str]] = None
    report_title: Optional[str] = "گزارش جامع مشخصات انفرادی، شناسنامه‌ای، شماره موبایل و آدرس"


class UserReportKeyValueDTO(BaseModel):
    label: str
    value: str


class UserReportAnalysisSectionDTO(BaseModel):
    title: str
    content: str


class UserReportEvidenceDTO(BaseModel):
    meta: str = ""
    doc_id: str = ""
    offset: str = ""
    date: str = ""
    source: str = ""
    content: str = ""


class UserReportChargeDTO(BaseModel):
    title: str
    count: int = 0
    evidences: List[UserReportEvidenceDTO] = Field(default_factory=list)


class UserReportGroupDTO(BaseModel):
    name: str
    message_count: int = 0
    count_label: str = ""


class UserReportMessageDTO(BaseModel):
    meta: str = ""
    date: str = ""
    source: str = ""
    doc_id: str = ""
    content: str = ""


class UserReportSummaryDTO(BaseModel):
    id: str
    full_name: str = ""
    username: str = ""
    telegram_id: str = ""
    national_id: str = ""
    phone_number: str = ""
    city: str = ""
    province: str = ""
    final_status: str = "سیاه"
    header_subtitle: str = ""
    total_charges: int = 0
    total_groups: int = 0
    total_messages: int = 0
    source_filename: str = ""
    created_at: str = ""
    updated_at: str = ""


class UserReportDetailDTO(UserReportSummaryDTO):
    birth_date: str = ""
    gender: str = ""
    postal_code: str = ""
    virtual_data: List[UserReportKeyValueDTO] = Field(default_factory=list)
    real_data: List[UserReportKeyValueDTO] = Field(default_factory=list)
    personality_analysis: List[UserReportAnalysisSectionDTO] = Field(default_factory=list)
    charges: List[UserReportChargeDTO] = Field(default_factory=list)
    groups: List[UserReportGroupDTO] = Field(default_factory=list)
    messages: List[UserReportMessageDTO] = Field(default_factory=list)


class UserReportCreateDTO(BaseModel):
    full_name: str = ""
    username: str = ""
    telegram_id: str = ""
    national_id: str = ""
    phone_number: str = ""
    birth_date: str = ""
    gender: str = "مرد"
    postal_code: str = ""
    city: str = "کاشمر"
    province: str = "خراسان رضوی"
    final_status: str = "سیاه"
    activity_type: str = ""
    behavior_desc: str = ""
    network_desc: str = ""
    interests_desc: str = ""
    key_points: str = ""
    final_reason: str = ""
    default_group: str = "گروه رصد فضای مجازی"
    raw_messages_text: str = ""
    virtual_data: Optional[List[Dict[str, str]]] = None
    real_data: Optional[List[Dict[str, str]]] = None
    personality_analysis: Optional[List[Dict[str, str]]] = None
    charges: Optional[List[Dict[str, Any]]] = None
    groups: Optional[List[Dict[str, Any]]] = None
    messages: Optional[List[Dict[str, Any]]] = None


class UserReportListResponseDTO(BaseModel):
    total: int
    items: List[UserReportSummaryDTO] = Field(default_factory=list)



