import {
  FileItem,
  StatsResponse,
  HealthResponse,
  FileUpdatePayload,
  JobItem,
  JobListResponse,
  ReanalyzeResponse,
  ResourceMode,
  LegacyMigrationReport,
  LegacyMigrationResult,
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
    extraction_version: 1,
    processing_version: 1,
    job_state: "COMPLETED",
    processing_stage: "FINALIZATION",
    processing_progress: 100,
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
    extraction_version: 1,
    processing_version: 1,
    job_state: "COMPLETED",
    processing_stage: "FINALIZATION",
    processing_progress: 100,
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
    extraction_version: 1,
    processing_version: 1,
    job_state: "COMPLETED",
    processing_stage: "OCR_PENDING",
    processing_progress: 100,
    system_note: "این یک نمونهٔ نمایشی از تصویر بدون متن استخراج‌شده است که در انتظار اجرای OCR قرار دارد.",
    color: "social",
    tags: ["یادگیری", "مطالعه"],
    page_count: 1,
    created_at: "2026-11-06T11:15:00Z",
  },
];

const LEGACY_LOCAL_STORAGE_KEY = "saher_offline_archive_files_v1";

export class LegacyBrowserDataHelper {
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
  private static sessionToken: string | null = null;

  static setSessionToken(token: string | null): void {
    this.sessionToken = token;
  }

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
    if (this.sessionToken) {
      headers.set("X-Saher-Session-Token", this.sessionToken);
    }
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

  static async getFilePages(fileId: string): Promise<import("../types/archive").PageItem[]> {
    return this.requestJson<import("../types/archive").PageItem[]>(
      `/api/v1/files/${encodeURIComponent(fileId)}/pages`,
      { method: "GET" },
    );
  }

  static async updatePageText(
    fileId: string,
    pageNumber: number,
    rawText: string,
  ): Promise<import("../types/archive").PageItem> {
    return this.requestJson<import("../types/archive").PageItem>(
      `/api/v1/files/${encodeURIComponent(fileId)}/pages/${pageNumber}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ raw_text: rawText }),
      },
    );
  }

  static getPagePreviewUrl(fileId: string, pageNumber: number): string {
    return this.buildUrl(`/api/v1/files/${encodeURIComponent(fileId)}/pages/${pageNumber}/preview`);
  }

  static async getOcrStatus(): Promise<import("../types/archive").OCREngineStatus> {
    return this.requestJson<import("../types/archive").OCREngineStatus>(
      `/api/v1/ocr/status`,
      { method: "GET" },
    );
  }

  static async switchOcrEngine(
    engineName: "paddleocr" | "hybrid" | "tesseract" | string,
  ): Promise<import("../types/archive").OCREngineStatus> {
    return this.requestJson<import("../types/archive").OCREngineStatus>(
      `/api/v1/ocr/engine`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ engine_name: engineName }),
      },
    );
  }

  static async importFile(
    file: File,
    topic?: string,
    options?: { asyncMode?: boolean },
  ): Promise<FileItem> {
    const formData = new FormData();
    formData.append("file", file);
    if (topic) formData.append("topic", topic);
    const asyncMode = options?.asyncMode ?? true;
    formData.append("async_mode", asyncMode ? "true" : "false");

    return this.requestJson<FileItem>(
      `/api/v1/files/import?async_mode=${asyncMode ? "true" : "false"}`,
      {
        method: "POST",
        headers: asyncMode ? { "X-Saher-Async": "true" } : undefined,
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

  // Milestone 2: Job Management & Reprocessing APIs
  static async listJobs(params?: {
    state?: string;
    stage?: string;
    fileId?: string;
    limit?: number;
    offset?: number;
  }): Promise<JobListResponse> {
    const qs = new URLSearchParams();
    if (params?.state && params.state !== "ALL") qs.set("state", params.state);
    if (params?.stage && params.stage !== "ALL") qs.set("stage", params.stage);
    if (params?.fileId) qs.set("file_id", params.fileId);
    qs.set("limit", String(params?.limit ?? 50));
    qs.set("offset", String(params?.offset ?? 0));

    return this.requestJson<JobListResponse>(`/api/v1/jobs?${qs.toString()}`, {
      method: "GET",
    });
  }

  static async getJob(jobId: string): Promise<JobItem> {
    return this.requestJson<JobItem>(`/api/v1/jobs/${encodeURIComponent(jobId)}`, {
      method: "GET",
    });
  }

  static async pauseJob(jobId: string): Promise<JobItem> {
    return this.requestJson<JobItem>(`/api/v1/jobs/${encodeURIComponent(jobId)}/pause`, {
      method: "POST",
    });
  }

  static async resumeJob(jobId: string): Promise<JobItem> {
    return this.requestJson<JobItem>(`/api/v1/jobs/${encodeURIComponent(jobId)}/resume`, {
      method: "POST",
    });
  }

  static async cancelJob(jobId: string): Promise<JobItem> {
    return this.requestJson<JobItem>(`/api/v1/jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: "POST",
    });
  }

  static async retryJob(jobId: string): Promise<JobItem> {
    return this.requestJson<JobItem>(`/api/v1/jobs/${encodeURIComponent(jobId)}/retry`, {
      method: "POST",
    });
  }

  static async reanalyzeFile(
    fileId: string,
    stage?: string,
    priority: number = 60,
  ): Promise<ReanalyzeResponse> {
    return this.requestJson<ReanalyzeResponse>(
      `/api/v1/files/${encodeURIComponent(fileId)}/reanalyze`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stage: stage || null, priority }),
      },
    );
  }

  static async updateWorkerConfig(
    resourceMode: ResourceMode,
    concurrency?: number,
  ): Promise<{
    resource_mode: ResourceMode;
    concurrency: number;
    worker_online: boolean;
  }> {
    return this.requestJson(`/api/v1/workers/config`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ resource_mode: resourceMode, concurrency }),
    });
  }

  // Safe Legacy Migration Preview, Approval & Restoration APIs
  static async previewLegacyMigration(): Promise<LegacyMigrationReport> {
    return this.requestJson<LegacyMigrationReport>(`/api/v1/migrations/legacy-preview`, {
      method: "GET",
    });
  }

  static async executeLegacyCleanup(confirmApproval: boolean): Promise<LegacyMigrationResult> {
    return this.requestJson<LegacyMigrationResult>(`/api/v1/migrations/legacy-cleanup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm_approval: confirmApproval }),
    });
  }

  static async restoreMigrationBackup(backupId: string): Promise<LegacyMigrationResult> {
    return this.requestJson<LegacyMigrationResult>(
      `/api/v1/migrations/restore/${encodeURIComponent(backupId)}`,
      {
        method: "POST",
      },
    );
  }

  // Batch Folder Image Analysis (Topic & Nature) & Word (.docx) Report Export
  static async analyzeImageFolder(
    files: File[],
    folderName?: string,
    sourceUrl?: string,
    ocrEngine: string = "paddleocr",
  ): Promise<import("../types/archive").FolderAnalysisResponse> {
    const formData = new FormData();
    const relPaths: string[] = [];
    for (const f of files) {
      formData.append("files", f);
      const webkitRel = (f as any).webkitRelativePath;
      relPaths.push(webkitRel && typeof webkitRel === "string" ? webkitRel : f.name);
    }
    if (folderName) {
      formData.append("folder_name", folderName);
    }
    if (sourceUrl && sourceUrl.trim()) {
      formData.append("source_url", sourceUrl.trim());
    }
    if (ocrEngine) {
      formData.append("ocr_engine", ocrEngine);
    }
    formData.append("relative_paths", JSON.stringify(relPaths));

    return this.requestJson<import("../types/archive").FolderAnalysisResponse>(
      `/api/v1/images/analyze-folder`,
      {
        method: "POST",
        body: formData,
      },
      120000,
    );
  }

  static async analyzeExistingImages(
    fileIds: string[],
    folderName?: string,
    sourceUrl?: string,
    ocrEngine: string = "paddleocr",
  ): Promise<import("../types/archive").FolderAnalysisResponse> {
    return this.requestJson<import("../types/archive").FolderAnalysisResponse>(
      `/api/v1/images/analyze-existing`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          file_ids: fileIds,
          folder_name: folderName || "تصاویر منتخب کتابخانه",
          source_url: sourceUrl?.trim() || null,
          ocr_engine: ocrEngine || "paddleocr",
        }),
      },
      90000,
    );
  }

  static async downloadImagesWordReport(
    fileIds: string[],
    folderName?: string,
    options?: {
      sourceUrl?: string;
      templateOverridesByFile?: Record<string, Record<string, unknown>>;
    },
  ): Promise<Blob> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      "X-Saher-Client": "web-ui/0.3.0",
    };
    if (this.sessionToken) {
      headers["X-Saher-Session-Token"] = this.sessionToken;
    }

    const response = await fetch(this.buildUrl(`/api/v1/images/export-word`), {
      method: "POST",
      headers,
      body: JSON.stringify({
        file_ids: fileIds,
        folder_name: folderName || "پوشهٔ تصاویر انتخابی",
        source_url: options?.sourceUrl?.trim() || null,
        template_overrides_by_file: options?.templateOverridesByFile || null,
      }),
    });

    if (!response.ok) {
      let detail = "خطا در تولید گزارش Word (.docx)";
      try {
        const errJson = await response.json();
        if (errJson?.detail) detail = String(errJson.detail);
      } catch {
        // Ignore JSON parse error
      }
      throw new ApiClientError({
        message: detail,
        status: response.status,
        code: "WORD_EXPORT_FAILED",
        isNetworkError: false,
      });
    }

    return await response.blob();
  }

  static getSingleFileWordUrl(fileId: string): string {
    return this.buildUrl(`/api/v1/files/${encodeURIComponent(fileId)}/export-word`);
  }

  // Personal & Civil Identity Dossiers (مشخصات انفرادی و شناسنامه‌ای)
  static async listIdentityProfiles(
    query?: string,
  ): Promise<import("../types/archive").IdentityProfileListResponse> {
    const qs = query?.trim() ? `?q=${encodeURIComponent(query.trim())}` : "";
    return this.requestJson<import("../types/archive").IdentityProfileListResponse>(
      `/api/v1/profiles${qs}`,
      { method: "GET" },
    );
  }

  static async createIdentityProfile(
    payload: Partial<import("../types/archive").IdentityProfileItem>,
  ): Promise<import("../types/archive").IdentityProfileItem> {
    return this.requestJson<import("../types/archive").IdentityProfileItem>(
      `/api/v1/profiles`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    );
  }

  static async updateIdentityProfile(
    profileId: string,
    payload: Partial<import("../types/archive").IdentityProfileItem>,
  ): Promise<import("../types/archive").IdentityProfileItem> {
    return this.requestJson<import("../types/archive").IdentityProfileItem>(
      `/api/v1/profiles/${encodeURIComponent(profileId)}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    );
  }

  static async deleteIdentityProfile(profileId: string): Promise<{ deleted: boolean; id: string }> {
    return this.requestJson<{ deleted: boolean; id: string }>(
      `/api/v1/profiles/${encodeURIComponent(profileId)}`,
      { method: "DELETE" },
    );
  }

  static async syncIdentityProfilesFromArchive(): Promise<import("../types/archive").IdentityProfileListResponse> {
    return this.requestJson<import("../types/archive").IdentityProfileListResponse>(
      `/api/v1/profiles/sync-from-archive`,
      { method: "POST" },
      90000,
    );
  }

  static async downloadIdentityProfilesWordReport(
    profileIds?: string[],
    reportTitle?: string,
  ): Promise<Blob> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      "X-Saher-Client": "web-ui/0.3.0",
    };
    if (this.sessionToken) {
      headers["X-Saher-Session-Token"] = this.sessionToken;
    }

    const response = await fetch(this.buildUrl(`/api/v1/profiles/export-word`), {
      method: "POST",
      headers,
      body: JSON.stringify({
        profile_ids: profileIds && profileIds.length > 0 ? profileIds : null,
        report_title:
          reportTitle || "گزارش جامع مشخصات انفرادی، شناسنامه‌ای، شماره موبایل و آدرس",
      }),
    });

    if (!response.ok) {
      throw new ApiClientError({
        message: "خطا در تولید سند Word مشخصات انفرادی (.docx)",
        status: response.status,
        code: "PROFILE_WORD_EXPORT_FAILED",
        isNetworkError: false,
      });
    }

    return await response.blob();
  }
}

