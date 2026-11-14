export type ExtractionStatus =
  | "extracted"
  | "empty"
  | "pending_ocr"
  | "partial_ocr"
  | "unsupported"
  | "failed"
  | "queued";

export type ConnectionMode = "checking" | "connected" | "disconnected" | "demo";

export type JobState =
  | "QUEUED"
  | "RUNNING"
  | "PAUSED"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED";

export type ProcessingStage =
  | "DISCOVERY"
  | "VALIDATION"
  | "EXTRACTION"
  | "OCR_PENDING"
  | "ANALYSIS_PENDING"
  | "INDEXING"
  | "FINALIZATION";

export type ResourceMode = "Eco" | "Balanced" | "Performance";

export interface BoundingBoxItem {
  text: string;
  x: number;
  y: number;
  width: number;
  height: number;
  confidence: number;
  line_num: number;
  block_num: number;
  direction: "rtl" | "ltr" | string;
}

export interface PageItem {
  id: string;
  file_id: string;
  page_number: number;
  raw_text: string;
  normalized_text: string;
  bboxes: BoundingBoxItem[];
  extraction_method: string;
  page_status: "extracted" | "empty" | "pending_ocr" | "failed" | "user_modified" | string;
  error_code?: string | null;
  error_message?: string | null;
  ocr_confidence?: number | null;
  width?: number | null;
  height?: number | null;
  is_user_modified: boolean;
  updated_at?: string | null;
}

export type OCREngineId = "paddleocr" | "hybrid" | "tesseract" | string;

export interface OCREngineOption {
  id: OCREngineId;
  title: string;
  description: string;
  ready: boolean;
}

export interface PaddleOCRMetadata {
  repo_present: boolean;
  repo_url: string;
  repo_dir: string;
  dict_dir: string;
  has_configs: boolean;
  dictionaries_loaded: Record<string, number>;
  total_charset_size: number;
  supported_scripts: string[];
  pipeline_stages: string[];
}

export interface OCREngineStatus {
  ready: boolean;
  engine_name: OCREngineId;
  engine_version: string;
  model_dir: string;
  installed_languages: string[];
  required_languages: string[];
  missing_languages: string[];
  offline_ready: boolean;
  error_code?: string | null;
  error_message?: string | null;
  available_engines?: OCREngineOption[];
  paddleocr_metadata?: PaddleOCRMetadata | null;
}

export interface FileItem {
  id: string;
  archive_id: string;
  title: string;
  kind: string; // 'سند', 'تصویر', 'اسکرین‌شات'
  topic: string;
  status: string; // 'آماده', 'در صف', 'در حال پردازش', 'تحلیل ناقص', 'نیازمند بازبینی', 'خطا'
  mime_type: string;
  file_size: number;
  sha256: string;
  text: string;
  extraction_status: ExtractionStatus;
  extraction_method: string;
  extraction_version?: number;
  processing_version?: number;
  latest_job_id?: string | null;
  job_state?: JobState | null;
  processing_stage?: ProcessingStage | null;
  processing_progress?: number | null;
  system_note?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  matched_snippet?: string | null;
  matched_page?: number | null;
  matched_pages?: number[];
  failed_pages?: number[];
  is_user_modified?: boolean;
  color: string;
  tags: string[];
  page_count: number;
  created_at: string;
  updated_at?: string | null;
}

export interface StatsResponse {
  total_files: number;
  ready_files: number;
  attention_files: number;
  queued_jobs?: number;
  running_jobs?: number;
  failed_jobs?: number;
  demo_mode?: boolean;
}

export interface HealthResponse {
  status: string;
  version: string;
  database: string;
  storage_accessible: boolean;
  demo_mode?: boolean;
  max_upload_size_bytes?: number;
  worker_online?: boolean;
  active_workers_count?: number;
  resource_mode?: ResourceMode;
  ocr_ready?: boolean;
  ocr_engine?: string;
  ocr_languages?: string[];
}

export interface FileUpdatePayload {
  topic?: string;
  status?: string;
  tags?: string[];
}

export interface JobEventItem {
  id: number;
  job_id: string;
  attempt_number: number;
  from_state?: string | null;
  to_state: string;
  stage: string;
  event_type: string;
  worker_id?: string | null;
  message?: string | null;
  error_code?: string | null;
  created_at: string;
}

export interface JobItem {
  id: string;
  archive_id: string;
  file_id: string;
  file_title: string;
  file_kind: string;
  file_status: string;
  job_type: string;
  target_stage?: string | null;
  processing_stage: ProcessingStage;
  state: JobState;
  priority: number;
  attempt_count: number;
  max_retries: number;
  progress: number;
  progress_message?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  is_retryable: boolean;
  worker_id?: string | null;
  lease_expires_at?: string | null;
  heartbeat_at?: string | null;
  next_run_at?: string | null;
  processing_version: number;
  checkpoint?: Record<string, unknown>;
  created_at: string;
  started_at?: string | null;
  updated_at?: string | null;
  completed_at?: string | null;
  events?: JobEventItem[];
}

export interface JobStats {
  queued: number;
  running: number;
  paused: number;
  completed: number;
  failed: number;
  cancelled: number;
  total: number;
}

export interface WorkerInfo {
  worker_id: string;
  resource_mode: ResourceMode;
  concurrency: number;
  active_jobs: number;
  status: string;
  hostname?: string | null;
  pid?: number | null;
  started_at?: string | null;
  last_heartbeat_at?: string | null;
}

export interface JobListResponse {
  total: number;
  limit: number;
  offset: number;
  stats: JobStats;
  workers: WorkerInfo[];
  resource_mode: ResourceMode;
  worker_concurrency: number;
  items: JobItem[];
}

export interface ReanalyzeResponse {
  job: JobItem;
  created_new: boolean;
  message: string;
}

export interface LegacyCandidateItem {
  file_id: string;
  title: string;
  mime_type: string;
  classification: string;
  reason: string;
  is_user_modified: boolean;
}

export interface LegacyMigrationReport {
  total_inspected: number;
  candidate_count: number;
  preserved_count: number;
  requires_approval: boolean;
  candidates: LegacyCandidateItem[];
  preserved: LegacyCandidateItem[];
}

export interface LegacyMigrationResult {
  executed: boolean;
  removed_count: number;
  preserved_count: number;
  backup_id?: string | null;
  backup_path?: string | null;
  audit_id: string;
  message: string;
}

export const THEMATIC_CATEGORIES_12: readonly string[] = [
  "اجتماعی",
  "اقتصادی",
  "امنیتی",
  "جاسوسی",
  "دفاعی (نظامی، کویر و مرز)",
  "دین و روحانیت",
  "رزمایش",
  "سایبری",
  "سیاسی",
  "علم و فناوری",
  "فرهنگی",
  "هواگرد (پهپاد، ریزپرنده، جنگنده و ...)",
];

export interface CulturalSocialTemplateFields {
  full_name: string;
  national_id: string;
  phone_number: string;
  guidance_date?: string;
  numeric_id?: string;
  account_handle?: string;
  description?: string;
  city_hashtag?: string;
  occupation: string;
  violation: string;
  action_request: string;
  profile_url: string;
  hashtags: string[];
  cultural_template_text?: string;
  social_template_text?: string;
}

export interface PersonalIdentityFields {
  has_identity_data?: boolean;
  first_name?: string;
  last_name?: string;
  full_name?: string;
  father_name?: string;
  national_id?: string;
  birth_certificate_no?: string;
  birth_date?: string;
  birth_place?: string;
  occupation?: string;
  mobile_phone?: string;
  secondary_mobile?: string;
  landline_phone?: string;
  province?: string;
  city?: string;
  address?: string;
  postal_code?: string;
  location_name?: string;
  gps_coordinates?: string;
  account_handle?: string;
  account_label?: string;
  numeric_id?: string;
  profile_url?: string;
  personal_folder?: string;
  thematic_category?: string;
}

export interface CriminalAssessment {
  has_criminal_indicator: boolean;
  risk_level: string;
  criminal_charges: string[];
  legal_articles: string[];
  evidence_quotes: string[];
  exact_text_inspection: string;
  judicial_summary: string;
  recommended_action: string;
}

export interface ImageAnalysisItem {
  file_id: string;
  title: string;
  relative_path: string;
  mime_type: string;
  file_size: number;
  width: number;
  height: number;
  aspect_ratio: number;
  orientation: string;
  color_mode: string;
  dominant_color_hex: string;
  color_profile_label: string;
  mean_brightness: number;
  contrast_std: number;
  paper_bg_ratio: number;
  edge_density: number;
  word_count: number;
  char_count: number;
  line_count: number;
  bbox_count: number;
  ocr_confidence?: number | null;
  ocr_engine?: string;
  extracted_text: string;
  personal_folder?: string;
  account_id?: string;
  account_username?: string;
  account_label?: string;
  platform_source?: string;
  capture_source_category?: string;
  subject_classification?: string;
  camera_info?: string;
  location_name?: string;
  gps_coordinates?: string;
  detected_caption?: string;
  thematic_category?: string;
  image_nature: string;
  detected_topic: string;
  confidence_label: string;
  tags: string[];
  key_findings: string[];
  analysis_summary: string;
  personal_identity?: PersonalIdentityFields | null;
  criminal_assessment?: CriminalAssessment | null;
  template_applicable?: boolean;
  template_fields?: CulturalSocialTemplateFields | null;
  formatted_template_text?: string;
}

export interface FolderAnalysisResponse {
  folder_name: string;
  total_images: number;
  ocr_engine?: string;
  account_breakdown?: Record<string, number>;
  account_category_tree?: Record<string, Record<string, number>>;
  topic_breakdown: Record<string, number>;
  nature_breakdown: Record<string, number>;
  source_type_breakdown?: Record<string, number>;
  location_breakdown?: Record<string, number>;
  criminal_count?: number;
  items: ImageAnalysisItem[];
}

export interface IdentityProfileItem {
  id: string;
  source_file_id?: string | null;
  first_name: string;
  last_name: string;
  full_name: string;
  father_name: string;
  national_id: string;
  birth_certificate_no: string;
  birth_date: string;
  birth_place: string;
  occupation: string;
  mobile_phone: string;
  secondary_mobile: string;
  landline_phone: string;
  province: string;
  city: string;
  address: string;
  postal_code: string;
  gps_coordinates: string;
  location_name: string;
  account_handle: string;
  numeric_id: string;
  profile_url: string;
  personal_folder: string;
  thematic_category: string;
  risk_level: string;
  judicial_notes: string;
  created_at?: string;
  updated_at?: string;
}

export interface IdentityProfileListResponse {
  total: number;
  items: IdentityProfileItem[];
}

export interface UserReportKeyValue {
  label: string;
  value: string;
}

export interface UserReportAnalysisSection {
  title: string;
  content: string;
}

export interface UserReportEvidence {
  meta: string;
  doc_id: string;
  offset: string;
  date: string;
  source: string;
  content: string;
}

export interface UserReportCharge {
  title: string;
  count: number;
  evidences: UserReportEvidence[];
}

export interface UserReportGroup {
  name: string;
  message_count: number;
  count_label: string;
}

export interface UserReportMessage {
  meta: string;
  date: string;
  source: string;
  doc_id: string;
  content: string;
}

export interface UserReportSummary {
  id: string;
  full_name: string;
  username: string;
  telegram_id: string;
  national_id: string;
  phone_number: string;
  city: string;
  province: string;
  final_status: string;
  header_subtitle: string;
  total_charges: number;
  total_groups: number;
  total_messages: number;
  source_filename: string;
  created_at?: string;
  updated_at?: string;
}

export interface UserReportDetail extends UserReportSummary {
  birth_date: string;
  gender: string;
  postal_code: string;
  virtual_data: UserReportKeyValue[];
  real_data: UserReportKeyValue[];
  personality_analysis: UserReportAnalysisSection[];
  charges: UserReportCharge[];
  groups: UserReportGroup[];
  messages: UserReportMessage[];
}

export interface UserReportCreatePayload {
  full_name?: string;
  username?: string;
  telegram_id?: string;
  national_id?: string;
  phone_number?: string;
  birth_date?: string;
  gender?: string;
  postal_code?: string;
  city?: string;
  province?: string;
  final_status?: string;
  activity_type?: string;
  behavior_desc?: string;
  network_desc?: string;
  interests_desc?: string;
  key_points?: string;
  final_reason?: string;
  default_group?: string;
  raw_messages_text?: string;
}

export interface UserReportListResponse {
  total: number;
  items: UserReportSummary[];
}

