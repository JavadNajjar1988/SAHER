export type ExtractionStatus =
  | "extracted"
  | "empty"
  | "pending_ocr"
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
  resource_mode?: ResourceMode;
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
