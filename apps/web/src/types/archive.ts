export type ExtractionStatus =
  | "extracted"
  | "empty"
  | "pending_ocr"
  | "unsupported"
  | "failed";

export type ConnectionMode = "checking" | "connected" | "disconnected" | "demo";

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
  demo_mode?: boolean;
}

export interface HealthResponse {
  status: string;
  version: string;
  database: string;
  storage_accessible: boolean;
  demo_mode?: boolean;
  max_upload_size_bytes?: number;
}

export interface FileUpdatePayload {
  topic?: string;
  status?: string;
  tags?: string[];
}
