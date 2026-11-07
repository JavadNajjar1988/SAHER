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
  color: string;
  tags: string[];
  page_count: number;
  created_at: string;
  error_message?: string | null;
}

export interface StatsResponse {
  total_files: number;
  ready_files: number;
  attention_files: number;
}

export interface HealthResponse {
  status: string;
  version: string;
  database: string;
  storage_accessible: boolean;
}

export interface FileUpdatePayload {
  topic?: string;
  status?: string;
  tags?: string[];
}
