import {
  FileItem,
  StatsResponse,
  HealthResponse,
  FileUpdatePayload,
} from "../types/archive";

export class ApiClientError extends Error {
  status: number;
  code: string;
  isNetworkError: boolean;
  existingFileId?: string;
  existingTitle?: string;

  constructor(options: {
    message: string;
    status?: number;
    code?: string;
    isNetworkError?: boolean;
    existingFileId?: string;
    existingTitle?: string;
  }) {
    super(options.message);
    this.name = "ApiClientError";
    this.status = options.status ?? 0;
    this.code = options.code ?? "API_ERROR";
    this.isNetworkError = options.isNetworkError ?? false;
    this.existingFileId = options.existingFileId;
    this.existingTitle = options.existingTitle;
  }
}

/**
 * Explicit Demo Mode sample records.
 * Used ONLY when the user explicitly activates Demo Mode in the UI.
 * Never used as a silent fallback when the production backend is unreachable or returns an error.
 */
export const EXPLICIT_DEMO_SAMPLES: FileItem[] = [
  {
    id: "demo-1",
    archive_id: "demo",
    title: "یادداشت‌های طراحی و معماری (نمونه نمایشی).txt",
    kind: "سند",
    topic: "طراحی",
    status: "آماده",
    mime_type: "text/plain",
    file_size: 1420,
    sha256: "نمونه نمایشی (بدون فایل باینری)",
    text: "طراحی خوب از شناخت مسئله آغاز می‌شود. در این یادداشت، اصول طراحی یک محصول ساده، خوانا و قابل استفاده را مرور می‌کنیم.",
    extraction_status: "extracted",
    extraction_method: "direct_text",
    system_note: "رکورد نمایشی برای بررسی رابط کاربری (در پایگاه‌داده ذخیره نشده است).",
    color: "paper",
    tags: ["طراحی محصول", "یادداشت"],
    page_count: 1,
    created_at: "2026-11-06T09:00:00Z",
  },
  {
    id: "demo-2",
    archive_id: "demo",
    title: "گزارش پژوهش‌های هوش مصنوعی (نمونه نمایشی).txt",
    kind: "سند",
    topic: "فناوری",
    status: "آماده",
    mime_type: "text/plain",
    file_size: 5120,
    sha256: "نمونه نمایشی (بدون فایل باینری)",
    text: "این گزارش به بررسی کاربرد مدل‌های زبانی در دسته‌بندی و بازیابی اسناد می‌پردازد.",
    extraction_status: "extracted",
    extraction_method: "direct_text",
    system_note: "رکورد نمایشی برای بررسی رابط کاربری (در پایگاه‌داده ذخیره نشده است).",
    color: "report",
    tags: ["پژوهش", "هوش مصنوعی"],
    page_count: 1,
    created_at: "2026-11-06T10:30:00Z",
  },
  {
    id: "demo-3",
    archive_id: "demo",
    title: "اسکرین‌شات نمونه در انتظار OCR (نمونه نمایشی)",
    kind: "اسکرین‌شات",
    topic: "آموزش",
    status: "نیازمند بازبینی",
    mime_type: "image/png",
    file_size: 212000,
    sha256: "نمونه نمایشی (بدون فایل باینری)",
    text: "",
    extraction_status: "pending_ocr",
    extraction_method: "none",
    system_note: "این یک نمونهٔ نمایشی از تصویر بدون متن استخراج‌شده است که در انتظار اجرای OCR قرار دارد.",
    color: "social",
    tags: ["یادگیری", "مطالعه"],
    page_count: 1,
    created_at: "2026-11-06T11:15:00Z",
  },
];

const LEGACY_LOCAL_STORAGE_KEY = "saher_offline_archive_files_v1";

export class LegacyBrowserDataHelper {
  /**
   * Checks if the user had any custom-added entries in the legacy prototype's localStorage
   * so they can export them safely without silently mixing them into production SQLite state.
   */
  static getLegacyUserEntries(): FileItem[] {
    try {
      if (typeof localStorage === "undefined") return [];
      const raw = localStorage.getItem(LEGACY_LOCAL_STORAGE_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed.filter((item) => item && typeof item.id === "string" && item.id.startsWith("local-"));
    } catch {
      return [];
    }
  }

  static clearLegacyStorage(): void {
    try {
      if (typeof localStorage !== "undefined") {
        localStorage.removeItem(LEGACY_LOCAL_STORAGE_KEY);
      }
    } catch {
      // Ignore storage access errors
    }
  }
}

function getConfiguredOrigin(): string {
  try {
    const envOrigin = (import.meta as unknown as { env?: Record<string, string> })?.env?.VITE_API_BASE_URL;
    if (envOrigin) {
      return envOrigin.replace(/\/+$/, "");
    }
  } catch {
    // Ignore if import.meta.env is undefined in Node test runner
  }
  return "";
}

export class ArchiveApiClient {
  private static defaultTimeoutMs = 15000;
  private static uploadTimeoutMs = 60000;

  private static buildUrl(path: string): string {
    const origin = getConfiguredOrigin();
    return `${origin}${path}`;
  }

  private static async requestJson<T>(
    path: string,
    init: RequestInit = {},
    timeoutMs: number = this.defaultTimeoutMs,
  ): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);

    const headers = new Headers(init.headers || {});
    headers.set("X-Saher-Client", "web-ui");
    if (!headers.has("Accept")) {
      headers.set("Accept", "application/json");
    }

    try {
      const response = await fetch(this.buildUrl(path), {
        ...init,
        headers,
        signal: controller.signal,
      });

      let payload: any = null;
      const contentType = response.headers.get("content-type") || "";
      if (contentType.includes("application/json")) {
        try {
          payload = await response.json();
        } catch {
          payload = null;
        }
      }

      if (!response.ok) {
        const detail =
          (payload && typeof payload.detail === "string" && payload.detail) ||
          `خطای سرور (${response.status})`;
        const code = (payload && typeof payload.code === "string" && payload.code) || `HTTP_${response.status}`;
        throw new ApiClientError({
          message: detail,
          status: response.status,
          code,
          isNetworkError: false,
          existingFileId: payload?.existing_file_id,
          existingTitle: payload?.existing_title,
        });
      }

      if (payload === null) {
        throw new ApiClientError({
          message: "پاسخ دریافتی از سرویس بک‌اند معتبر نیست (JSON نامعتبر).",
          status: response.status,
          code: "INVALID_JSON_RESPONSE",
          isNetworkError: false,
        });
      }

      return payload as T;
    } catch (err: any) {
      if (err instanceof ApiClientError) {
        throw err;
      }
      if (err?.name === "AbortError") {
        throw new ApiClientError({
          message: "مهلت زمانی درخواست به سرویس محلی ساهر به پایان رسید (Timeout).",
          status: 0,
          code: "REQUEST_TIMEOUT",
          isNetworkError: true,
        });
      }
      throw new ApiClientError({
        message: "ارتباط با سرویس محلی ساهر (FastAPI) برقرار نشد. لطفاً وضعیت اجرای سرویس بک‌اند را بررسی کنید.",
        status: 0,
        code: "NETWORK_UNREACHABLE",
        isNetworkError: true,
      });
    } finally {
      clearTimeout(timer);
    }
  }

  static async checkHealth(): Promise<HealthResponse> {
    return this.requestJson<HealthResponse>("/health", { method: "GET" }, 6000);
  }

  static async getStats(): Promise<StatsResponse> {
    return this.requestJson<StatsResponse>("/api/v1/stats", { method: "GET" });
  }

  static async listFiles(
    kind?: string,
    query?: string,
    status?: string,
    limit: number = 100,
    offset: number = 0,
  ): Promise<FileItem[]> {
    const params = new URLSearchParams();
    if (kind && kind !== "همهٔ فایل‌ها") params.set("kind", kind);
    if (query && query.trim()) params.set("query", query.trim());
    if (status) params.set("status", status);
    params.set("limit", String(limit));
    params.set("offset", String(offset));

    const qs = params.toString();
    return this.requestJson<FileItem[]>(`/api/v1/files${qs ? `?${qs}` : ""}`, {
      method: "GET",
    });
  }

  static async getFile(fileId: string): Promise<FileItem> {
    return this.requestJson<FileItem>(`/api/v1/files/${encodeURIComponent(fileId)}`, {
      method: "GET",
    });
  }

  static getFileContentUrl(fileId: string): string {
    return this.buildUrl(`/api/v1/files/${encodeURIComponent(fileId)}/content`);
  }

  static async importFile(file: File, topic?: string): Promise<FileItem> {
    const formData = new FormData();
    formData.append("file", file);
    if (topic) formData.append("topic", topic);

    return this.requestJson<FileItem>(
      "/api/v1/files/import",
      {
        method: "POST",
        body: formData,
      },
      this.uploadTimeoutMs,
    );
  }

  static async updateFile(fileId: string, payload: FileUpdatePayload): Promise<FileItem> {
    return this.requestJson<FileItem>(`/api/v1/files/${encodeURIComponent(fileId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  static async addTag(fileId: string, tag: string): Promise<FileItem> {
    return this.requestJson<FileItem>(`/api/v1/files/${encodeURIComponent(fileId)}/tags`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tag }),
    });
  }

  static async removeTag(fileId: string, tag: string): Promise<FileItem> {
    return this.requestJson<FileItem>(
      `/api/v1/files/${encodeURIComponent(fileId)}/tags/${encodeURIComponent(tag)}`,
      {
        method: "DELETE",
      },
    );
  }
}
