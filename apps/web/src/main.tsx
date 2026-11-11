import React, { useEffect, useState, useCallback } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";
import {
  FileItem,
  StatsResponse,
  ConnectionMode,
  FileUpdatePayload,
  JobItem,
  JobStats,
  WorkerInfo,
  ResourceMode,
  OCREngineStatus,
  LegacyMigrationReport,
  LegacyMigrationResult,
} from "./types/archive";
import {
  ArchiveApiClient,
  EXPLICIT_DEMO_SAMPLES,
  LegacyBrowserDataHelper,
} from "./services/apiClient";
import { Sidebar } from "./components/Sidebar";
import { Preview } from "./components/Preview";
import { FileDetailModal } from "./components/FileDetailModal";
import { ImportDialog } from "./components/ImportDialog";
import { ProcessingQueueView } from "./components/ProcessingQueueView";
import { BatchImageAnalysisView } from "./components/BatchImageAnalysisView";

const digits = (value: number) => value.toLocaleString("fa-IR");

const DEMO_JOBS: JobItem[] = [
  {
    id: "demo-job-1",
    archive_id: "demo",
    file_id: "demo-1",
    file_title: "یادداشت‌های طراحی و معماری (نمونه نمایشی).txt",
    file_kind: "سند",
    file_status: "آماده",
    job_type: "FILE_INGESTION",
    processing_stage: "FINALIZATION",
    state: "COMPLETED",
    priority: 50,
    attempt_count: 1,
    max_retries: 3,
    progress: 100,
    progress_message: "استخراج متن و نمایه‌سازی FTS5 با موفقیت تکمیل شد (نمونه نمایشی).",
    is_retryable: true,
    processing_version: 1,
    created_at: "2026-11-06T09:00:00Z",
    started_at: "2026-11-06T09:00:01Z",
    completed_at: "2026-11-06T09:00:02Z",
  },
  {
    id: "demo-job-2",
    archive_id: "demo",
    file_id: "demo-3",
    file_title: "اسکرین‌شات نمونه در انتظار OCR (نمونه نمایشی)",
    file_kind: "اسکرین‌شات",
    file_status: "نیازمند بازبینی",
    job_type: "FILE_INGESTION",
    processing_stage: "OCR_PENDING",
    state: "COMPLETED",
    priority: 50,
    attempt_count: 1,
    max_retries: 3,
    progress: 100,
    progress_message: "اعتبارسنجی باینری تکمیل شد؛ در انتظار موتور OCR آفلاین (نمونه نمایشی).",
    is_retryable: true,
    processing_version: 1,
    created_at: "2026-11-06T11:15:00Z",
    started_at: "2026-11-06T11:15:01Z",
    completed_at: "2026-11-06T11:15:02Z",
  },
];

function App() {
  const [items, setItems] = useState<FileItem[]>([]);
  const [stats, setStats] = useState<StatsResponse>({
    total_files: 0,
    ready_files: 0,
    attention_files: 0,
    queued_jobs: 0,
    running_jobs: 0,
    failed_jobs: 0,
  });
  const [jobs, setJobs] = useState<JobItem[]>([]);
  const [jobStats, setJobStats] = useState<JobStats>({
    queued: 0,
    running: 0,
    paused: 0,
    completed: 0,
    failed: 0,
    cancelled: 0,
    total: 0,
  });
  const [workers, setWorkers] = useState<WorkerInfo[]>([]);
  const [workerOnline, setWorkerOnline] = useState<boolean>(true);
  const [ocrStatus, setOcrStatus] = useState<OCREngineStatus | null>(null);
  const [resourceMode, setResourceMode] = useState<ResourceMode>("Balanced");
  const [workerConcurrency, setWorkerConcurrency] = useState<number>(2);
  const [jobStateFilter, setJobStateFilter] = useState<string>("ALL");
  const [jobStageFilter, setJobStageFilter] = useState<string>("ALL");

  const [connectionMode, setConnectionMode] = useState<ConnectionMode>("checking");
  const [backendVersion, setBackendVersion] = useState<string | undefined>(undefined);
  const [maxUploadBytes, setMaxUploadBytes] = useState<number>(25 * 1024 * 1024);
  const [apiErrorBanner, setApiErrorBanner] = useState<string>("");

  const [demoItems, setDemoItems] = useState<FileItem[]>(EXPLICIT_DEMO_SAMPLES);
  const [page, setPage] = useState("کتابخانه");
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("همهٔ فایل‌ها");
  const [view, setView] = useState("grid");
  const [selected, setSelected] = useState<FileItem | null>(null);
  const [selectedInitialPage, setSelectedInitialPage] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const [loading, setLoading] = useState(false);

  // Safe migration preview & execution state
  const [migrationReport, setMigrationReport] = useState<LegacyMigrationReport | null>(null);
  const [migrationResult, setMigrationResult] = useState<LegacyMigrationResult | null>(null);
  const [migrationBusy, setMigrationBusy] = useState(false);

  const loadFromBackend = useCallback(async () => {
    setLoading(true);
    try {
      const health = await ArchiveApiClient.checkHealth();
      if (health.status === "starting") {
        setConnectionMode("checking");
        setApiErrorBanner("");
        return;
      }
      setBackendVersion(health.version);
      if (health.max_upload_size_bytes) {
        setMaxUploadBytes(health.max_upload_size_bytes);
      }
      if (health.resource_mode) {
        setResourceMode(health.resource_mode);
      }
      setWorkerOnline(health.worker_online ?? true);

      const statusFilter = page === "بازبینی" ? "نیازمند بازبینی" : undefined;
      const [fetchedFiles, fetchedStats, fetchedJobs, fetchedOcr] = await Promise.all([
        ArchiveApiClient.listFiles(kind, query, statusFilter),
        ArchiveApiClient.getStats(),
        ArchiveApiClient.listJobs({
          state: jobStateFilter,
          stage: jobStageFilter,
          limit: 100,
        }),
        ArchiveApiClient.getOcrStatus().catch(() => null),
      ]);
      setItems(fetchedFiles);
      setStats(fetchedStats);
      setJobs(fetchedJobs.items);
      setJobStats(fetchedJobs.stats);
      setWorkers(fetchedJobs.workers);
      setResourceMode(fetchedJobs.resource_mode);
      setWorkerConcurrency(fetchedJobs.worker_concurrency);
      if (fetchedOcr) {
        setOcrStatus(fetchedOcr);
      }
      setApiErrorBanner("");
      setConnectionMode("connected");
    } catch (err: any) {
      if (err?.code === "BACKEND_STARTING" || err?.status === 425) {
        setConnectionMode("checking");
        setApiErrorBanner("");
      } else {
        setConnectionMode("disconnected");
        setApiErrorBanner(
          err?.message ||
            "ارتباط با سرویس محلی ساهر (FastAPI) برقرار نشد. عملیات آرشیو تا زمان اتصال مجدد غیرفعال است.",
        );
      }
    } finally {
      setLoading(false);
    }
  }, [kind, query, page, jobStateFilter, jobStageFilter]);

  const loadDemoData = useCallback(() => {
    let filtered = [...demoItems];
    if (kind && kind !== "همهٔ فایل‌ها") {
      filtered = filtered.filter((f) => f.kind === kind);
    }
    if (page === "بازبینی") {
      filtered = filtered.filter((f) => f.status === "نیازمند بازبینی");
    }
    if (query.trim()) {
      const q = query.trim().toLowerCase();
      filtered = filtered.filter(
        (f) =>
          f.title.toLowerCase().includes(q) ||
          f.text.toLowerCase().includes(q) ||
          f.tags.some((t) => t.toLowerCase().includes(q)),
      );
    }
    setItems(filtered);
    setStats({
      total_files: demoItems.length,
      ready_files: demoItems.filter((i) => i.status === "آماده").length,
      attention_files: demoItems.filter((i) => i.status !== "آماده").length,
      queued_jobs: 0,
      running_jobs: 0,
      failed_jobs: 0,
      demo_mode: true,
    });
    setJobs(DEMO_JOBS);
    setJobStats({
      queued: 0,
      running: 0,
      paused: 0,
      completed: DEMO_JOBS.length,
      failed: 0,
      cancelled: 0,
      total: DEMO_JOBS.length,
    });
  }, [demoItems, kind, query, page]);

  useEffect(() => {
    if (connectionMode === "demo") {
      loadDemoData();
    } else {
      loadFromBackend();
    }
  }, [connectionMode, loadFromBackend, loadDemoData]);

  // Automatically retry connection while backend is warming up ("checking") or temporarily unreachable ("disconnected")
  useEffect(() => {
    if (connectionMode !== "checking" && connectionMode !== "disconnected") return;
    const retryMs = connectionMode === "checking" ? 1200 : 2500;
    const timer = setInterval(() => {
      loadFromBackend();
    }, retryMs);
    return () => clearInterval(timer);
  }, [connectionMode, loadFromBackend]);

  // Poll automatically when jobs are active (QUEUED or RUNNING) or user is viewing the processing dashboard
  const hasActiveJobs = jobStats.queued + jobStats.running > 0;
  useEffect(() => {
    if (connectionMode !== "connected") return;
    if (!hasActiveJobs && page !== "صف پردازش" && page !== "منابع") return;

    const intervalMs = hasActiveJobs ? 900 : 3000;
    const timer = setInterval(() => {
      loadFromBackend();
    }, intervalMs);
    return () => clearInterval(timer);
  }, [connectionMode, hasActiveJobs, page, loadFromBackend]);

  // Modal accessibility & focus management
  const modalOpen = selected !== null || adding;
  useEffect(() => {
    if (!modalOpen) return;
    const previousFocus = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]');
    const focusable = () =>
      Array.from(
        dialog?.querySelectorAll<HTMLElement>(
          "button:not([disabled]), input:not([disabled]), select:not([disabled]), [href]",
        ) ?? [],
      );
    focusable()[0]?.focus();
    function handleKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setSelected(null);
        setAdding(false);
      }
      if (event.key === "Tab") {
        const controls = focusable();
        const first = controls[0];
        const last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    }
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("keydown", handleKey);
      document.body.style.overflow = previousOverflow;
      previousFocus?.focus();
    };
  }, [modalOpen]);

  const handleUpdateFile = async (fileId: string, payload: FileUpdatePayload) => {
    if (connectionMode === "demo") {
      setDemoItems((prev) =>
        prev.map((item) => {
          if (item.id !== fileId) return item;
          const updated: FileItem = {
            ...item,
            topic: payload.topic ?? item.topic,
            status: payload.status ?? item.status,
            tags: payload.tags ?? item.tags,
            is_user_modified: true,
          };
          setSelected(updated);
          return updated;
        }),
      );
      return;
    }

    const updated = await ArchiveApiClient.updateFile(fileId, payload);
    setSelected(updated);
    await loadFromBackend();
  };

  const handleAddTag = async (fileId: string, tag: string) => {
    if (connectionMode === "demo") {
      const target = demoItems.find((i) => i.id === fileId);
      if (!target) return;
      await handleUpdateFile(fileId, {
        tags: Array.from(new Set([...target.tags, tag])),
      });
      return;
    }

    const updated = await ArchiveApiClient.addTag(fileId, tag);
    setSelected(updated);
    await loadFromBackend();
  };

  const handleRemoveTag = async (fileId: string, tag: string) => {
    if (connectionMode === "demo") {
      const target = demoItems.find((i) => i.id === fileId);
      if (!target) return;
      await handleUpdateFile(fileId, {
        tags: target.tags.filter((t) => t !== tag),
      });
      return;
    }

    const updated = await ArchiveApiClient.removeTag(fileId, tag);
    setSelected(updated);
    await loadFromBackend();
  };

  const handleReanalyzeFile = async (fileId: string, stage?: string): Promise<string> => {
    const resp = await ArchiveApiClient.reanalyzeFile(fileId, stage);
    const freshFile = await ArchiveApiClient.getFile(fileId);
    setSelected(freshFile);
    await loadFromBackend();
    return resp.message;
  };

  const handleOpenFileById = async (fileId: string, pageNumber?: number) => {
    if (connectionMode === "demo") {
      const found = demoItems.find((d) => d.id === fileId);
      if (found) {
        setSelectedInitialPage(pageNumber || 1);
        setSelected(found);
      }
      return;
    }
    try {
      const f = await ArchiveApiClient.getFile(fileId);
      setSelectedInitialPage(pageNumber || f.matched_page || 1);
      setSelected(f);
    } catch {
      // Ignore if file was removed
    }
  };

  const handleImportFiles = async (files: FileList, topic?: string) => {
    if (connectionMode === "demo") {
      throw new Error(
        "در حالت نمایشی امکان ذخیره‌سازی واقعی فایل وجود ندارد. لطفاً ابتدا به حالت آرشیو اصلی (متصل به بک‌اند) بازگردید.",
      );
    }
    for (let i = 0; i < files.length; i++) {
      await ArchiveApiClient.importFile(files[i], topic, { asyncMode: true });
    }
    await loadFromBackend();
  };

  const handleInspectMigration = async () => {
    setMigrationBusy(true);
    try {
      const rep = await ArchiveApiClient.previewLegacyMigration();
      setMigrationReport(rep);
    } finally {
      setMigrationBusy(false);
    }
  };

  const handleApproveMigrationCleanup = async () => {
    setMigrationBusy(true);
    try {
      const res = await ArchiveApiClient.executeLegacyCleanup(true);
      setMigrationResult(res);
      const rep = await ArchiveApiClient.previewLegacyMigration();
      setMigrationReport(rep);
      await loadFromBackend();
    } finally {
      setMigrationBusy(false);
    }
  };

  const handleRestoreMigrationBackup = async (backupId: string) => {
    setMigrationBusy(true);
    try {
      const res = await ArchiveApiClient.restoreMigrationBackup(backupId);
      setMigrationResult(res);
      const rep = await ArchiveApiClient.previewLegacyMigration();
      setMigrationReport(rep);
      await loadFromBackend();
    } finally {
      setMigrationBusy(false);
    }
  };

  const legacyBrowserEntries = LegacyBrowserDataHelper.getLegacyUserEntries();

  return (
    <div className="shell">
      <Sidebar
        page={page}
        setPage={setPage}
        setQuery={setQuery}
        attentionCount={stats.attention_files}
        activeJobCount={jobStats.queued + jobStats.running}
        digits={digits}
        connectionMode={connectionMode}
        backendVersion={backendVersion}
      />
      <main>
        <header>
          <span>
            {connectionMode === "demo" ? "فضای نمایشی آزمایشی" : "فضای شخصی"}{" "}
            <span className="crumb">/</span> {page}
          </span>
          <div className="headerleft">
            {connectionMode === "demo" && (
              <button
                className="return-main-btn"
                onClick={() => setConnectionMode("checking")}
              >
                بازگشت به آرشیو اصلی (SQLite)
              </button>
            )}
            <span className="privacy">◈ حریم خصوصی، پیش‌فرض ماست</span>
            <span className="avatar small">م</span>
          </div>
        </header>
        <div className="content">
          {connectionMode === "disconnected" && (
            <div
              role="alert"
              data-testid="backend-disconnected-banner"
              className="disconnected-banner"
            >
              <div>
                <strong>خطا در ارتباط با سرویس محلی ساهر (FastAPI):</strong>{" "}
                {apiErrorBanner}
              </div>
              <div className="banner-actions">
                <button
                  className="retry-conn-btn"
                  onClick={() => loadFromBackend()}
                >
                  تلاش مجدد برای اتصال
                </button>
                <button
                  className="enter-demo-btn"
                  onClick={() => setConnectionMode("demo")}
                >
                  ورود به حالت نمایشی مجزا
                </button>
              </div>
            </div>
          )}

          {connectionMode === "demo" && (
            <div
              role="status"
              data-testid="demo-mode-banner"
              className="demo-banner"
            >
              <span>
                <strong>حالت نمایشی فعال است:</strong> رکوردهای این نما صرفاً نمونهٔ رابط کاربری هستند و در پایگاه‌داده SQLite ذخیره نمی‌شوند.
              </span>
              <button
                className="connect-real-btn"
                onClick={() => setConnectionMode("checking")}
              >
                اتصال به آرشیو واقعی
              </button>
            </div>
          )}

          <section className="heading">
            <div>
              <div className="eyebrow">هر چیزی، در جای خودش</div>
              <h1>{page === "کتابخانه" ? "کتابخانهٔ من" : page}</h1>
              <p>
                {page === "صف پردازش" || page === "منابع"
                  ? "پایش زندهٔ کارهای پردازشی پایدار، مراحل استخراج متن، وضعیت کارگرهای پس‌زمینه و مدیریت منابع"
                  : page === "تحلیل پوشهٔ عکس‌ها"
                    ? "تحلیل خودکار موضوع و ماهیت هر تصویر در پوشه به همراه استخراج متن آفلاین (OCR) و تولید گزارش Word (.docx)"
                    : "اینجا جایی برای نگه‌داشتن، پیدا کردن و دوباره کشف کردن است."}
              </p>
            </div>
            <div className="heading-actions">
              {page !== "تحلیل پوشهٔ عکس‌ها" && (
                <button
                  type="button"
                  className="secondary-header-btn"
                  data-testid="open-folder-analyzer-btn"
                  disabled={connectionMode !== "connected"}
                  onClick={() => setPage("تحلیل پوشهٔ عکس‌ها")}
                >
                  <span>▤</span> تحلیل پوشهٔ عکس‌ها (Word)
                </button>
              )}
              <button
                className="primary"
                disabled={connectionMode !== "connected"}
                title={
                  connectionMode !== "connected"
                    ? "واردسازی فایل فقط در حالت متصل به سرویس محلی FastAPI امکان‌پذیر است"
                    : "افزودن فایل جدید به آرشیو محلی"
                }
                onClick={() => setAdding(true)}
              >
                <span>＋</span> افزودن فایل
              </button>
            </div>
          </section>

          {page === "تحلیل پوشهٔ عکس‌ها" ? (
            <BatchImageAnalysisView
              connectionMode={connectionMode}
              archiveFiles={items}
              onRefreshArchive={loadFromBackend}
              onOpenFileById={handleOpenFileById}
              digits={digits}
            />
          ) : page === "صف پردازش" || page === "منابع" ? (
            <ProcessingQueueView
              jobs={jobs}
              jobStats={jobStats}
              workers={workers}
              resourceMode={resourceMode}
              workerConcurrency={workerConcurrency}
              workerOnline={workerOnline}
              ocrStatus={ocrStatus}
              connectionMode={connectionMode}
              loading={loading}
              stateFilter={jobStateFilter}
              stageFilter={jobStageFilter}
              onStateFilterChange={setJobStateFilter}
              onStageFilterChange={setJobStageFilter}
              onRefresh={loadFromBackend}
              onOpenFileById={handleOpenFileById}
              digits={digits}
            />
          ) : (
            <>
              <section className="stats">
                <div>
                  <span className="statIcon">▤</span>
                  <div>
                    <small>تمام فایل‌ها</small>
                    <strong className="tabular-nums">
                      {digits(stats.total_files)}
                      <em>فایل در کتابخانه</em>
                    </strong>
                  </div>
                </div>
                <div>
                  <span className="statIcon green">✓</span>
                  <div>
                    <small>آمادهٔ جست‌وجو</small>
                    <strong className="tabular-nums">
                      {digits(stats.ready_files)}
                      <em>پردازش کامل شده</em>
                    </strong>
                  </div>
                </div>
                <div>
                  <span className="statIcon amber">◌</span>
                  <div>
                    <small>نیازمند توجه شما</small>
                    <strong className="tabular-nums">
                      {digits(stats.attention_files)}
                      <em>بازبینی و در صف</em>
                    </strong>
                  </div>
                </div>
              </section>

              {["کتابخانه", "جست‌وجو", "بازبینی"].includes(page) ? (
                <>
                  <section className="toolbar">
                    <div className="search">
                      <span>⌕</span>
                      <input
                        aria-label="جست‌وجو در کتابخانه"
                        placeholder="در میان فایل‌ها، متن‌ها و برچسب‌ها بگردید…"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                      />
                      {query && (
                        <button
                          aria-label="پاک کردن جست‌وجو"
                          onClick={() => setQuery("")}
                        >
                          ×
                        </button>
                      )}
                    </div>
                    <select
                      aria-label="نوع فایل"
                      value={kind}
                      onChange={(e) => setKind(e.target.value)}
                    >
                      {["همهٔ فایل‌ها", "سند", "تصویر", "اسکرین‌شات"].map((k) => (
                        <option key={k} value={k}>
                          {k}
                        </option>
                      ))}
                    </select>
                    <div className="viewtoggle">
                      <button
                        aria-label="نمای کارتی"
                        className={view === "grid" ? "chosen" : ""}
                        onClick={() => setView("grid")}
                      >
                        ▦
                      </button>
                      <button
                        aria-label="نمای فهرستی"
                        className={view === "list" ? "chosen" : ""}
                        onClick={() => setView("list")}
                      >
                        ☰
                      </button>
                    </div>
                  </section>
                  <div className="sectionline">
                    <h2>
                      {query ? "نتیجهٔ جست‌وجو" : "فایل‌های آرشیو"}{" "}
                      <span>{digits(items.length)} فایل</span>
                    </h2>
                    <span>
                      {loading
                        ? "در حال دریافت از سرویس محلی…"
                        : connectionMode === "demo"
                          ? "نمایش داده‌های نمونه (مجزا از آرشیو اصلی)"
                          : "پایگاه‌داده پایدار SQLite + FTS5 · کارگر پس‌زمینه فعال"}
                    </span>
                  </div>
                  <section className={`files ${view}`}>
                    {items.map((item) => (
                      <button
                        className="filecard"
                        key={item.id}
                        data-testid={`file-card-${item.id}`}
                        onClick={() => {
                          setSelectedInitialPage(item.matched_page || 1);
                          setSelected(item);
                        }}
                      >
                        <div className={`preview ${item.color}`}>
                          <Preview item={item} />
                          <span className="filekind">{item.kind}</span>
                        </div>
                        <div className="cardbody">
                          <div className="card-badges-row">
                            <span
                              className={`status ${item.status === "آماده" ? "ready" : "attention"}`}
                            >
                              {item.status === "آماده" ? "●" : "◌"} {item.status}
                            </span>
                            {item.matched_page != null && (
                              <span
                                className="matched-page-badge tabular-nums"
                                data-testid={`matched-page-badge-${item.id}`}
                              >
                                ⌕ صفحهٔ {digits(item.matched_page)}
                                {item.matched_pages && item.matched_pages.length > 1
                                  ? ` (صفحات ${item.matched_pages.map(digits).join("، ")})`
                                  : ""}
                              </span>
                            )}
                            {item.failed_pages && item.failed_pages.length > 0 && (
                              <span
                                className="failed-page-badge tabular-nums"
                                title="خطای خواندن در برخی صفحات"
                              >
                                ⚠ خطا در صفحهٔ {item.failed_pages.map(digits).join("، ")}
                              </span>
                            )}
                          </div>
                          <h3>{item.title}</h3>
                          {item.matched_snippet && (
                            <p className="matched-snippet">
                              {item.matched_snippet}
                            </p>
                          )}
                          <div className="cardmeta">
                            <span>
                              {item.topic} · {digits(item.page_count || 1)} صفحه
                            </span>
                            <span>
                              {item.created_at
                                ? new Date(item.created_at).toLocaleDateString("fa-IR")
                                : "امروز"}
                            </span>
                          </div>
                        </div>
                      </button>
                    ))}
                  </section>
                  {!items.length && !loading && (
                    <div className="empty" data-testid="empty-archive-state">
                      {query || kind !== "همهٔ فایل‌ها" || page === "بازبینی" ? (
                        <>
                          فایلی با این مشخصات در آرشیو پیدا نشد.
                          <button
                            onClick={() => {
                              setQuery("");
                              setKind("همهٔ فایل‌ها");
                              if (page === "بازبینی") setPage("کتابخانه");
                            }}
                          >
                            پاک کردن فیلترها
                          </button>
                        </>
                      ) : connectionMode === "connected" ? (
                        <>
                          آرشیو شخصی شما در حال حاضر خالی است. نخستین سند یا تصویر خود را وارد کنید یا برای مشاهدهٔ نمونه‌ها وارد حالت نمایشی شوید.
                          <div className="empty-actions">
                            <button onClick={() => setAdding(true)}>
                              ＋ افزودن نخستین فایل
                            </button>
                            <button onClick={() => setConnectionMode("demo")}>
                              مشاهدهٔ حالت نمایشی آزمایشی
                            </button>
                          </div>
                        </>
                      ) : (
                        <>ارتباط با سرویس بک‌اند برقرار نیست.</>
                      )}
                    </div>
                  )}
                </>
              ) : (
                <section className="placeholder">
                  <span>◇</span>
                  <h2>{page}</h2>
                  <p>
                    {page === "تنظیمات" || page === "پشتیبان‌گیری"
                      ? "مدیریت حالت عملیاتی آرشیو محلی، بررسی ایمن مهاجرت رکوردهای قدیمی و پشتیبان‌گیری تأییدشده."
                      : "این بخش در مایلستون‌های بعدی فعال می‌شود. هم‌اکنون می‌توانید کتابخانه و صف پردازش پایدار را مدیریت کنید."}
                  </p>
                  {(page === "تنظیمات" || page === "پشتیبان‌گیری") && (
                    <div className="settings-panel">
                      <div className="settings-actions">
                        <button
                          onClick={() =>
                            setConnectionMode(connectionMode === "demo" ? "checking" : "demo")
                          }
                        >
                          {connectionMode === "demo"
                            ? "بازگشت به حالت آرشیو اصلی (SQLite)"
                            : "تغییر به حالت نمایشی آزمایشی"}
                        </button>
                        {connectionMode === "connected" && (
                          <button
                            disabled={migrationBusy}
                            onClick={handleInspectMigration}
                            data-testid="inspect-legacy-migration-btn"
                          >
                            بررسی ایمن رکوردهای قدیمی (Dry-Run)
                          </button>
                        )}
                        {legacyBrowserEntries.length > 0 && (
                          <button
                            onClick={() => {
                              const blob = new Blob(
                                [JSON.stringify(legacyBrowserEntries, null, 2)],
                                { type: "application/json" },
                              );
                              const url = URL.createObjectURL(blob);
                              const a = document.createElement("a");
                              a.href = url;
                              a.download = "saher-legacy-localstorage-export.json";
                              a.click();
                              URL.revokeObjectURL(url);
                            }}
                          >
                            برون‌ریزی داده‌های قدیمی مرورگر ({digits(legacyBrowserEntries.length)} مورد)
                          </button>
                        )}
                      </div>

                      {migrationReport && (
                        <div className="migration-report-box" data-testid="migration-report-box">
                          <h4>گزارش پیش‌نمایش مهاجرت غیرمخرب</h4>
                          <p>
                            تعداد کل بررسی‌شده: {digits(migrationReport.total_inspected)} ·{" "}
                            نامزد پاک‌سازی: {digits(migrationReport.candidate_count)} ·{" "}
                            محافظت‌شده (حفظ‌شده): {digits(migrationReport.preserved_count)}
                          </p>
                          {migrationReport.candidate_count > 0 && (
                            <button
                              className="primary"
                              disabled={migrationBusy}
                              onClick={handleApproveMigrationCleanup}
                            >
                              تأیید صریح: تهیهٔ پشتیبان و پاک‌سازی رکوردهای نمونهٔ قدیمی
                            </button>
                          )}
                        </div>
                      )}

                      {migrationResult && (
                        <div className="migration-report-box" role="status">
                          <p>{migrationResult.message}</p>
                          {migrationResult.backup_id && (
                            <button
                              disabled={migrationBusy}
                              onClick={() =>
                                handleRestoreMigrationBackup(migrationResult.backup_id!)
                              }
                            >
                              بازیابی از نسخهٔ پشتیبان ({migrationResult.backup_id})
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                  <button
                    className="back-to-lib-btn"
                    onClick={() => setPage("کتابخانه")}
                  >
                    رفتن به کتابخانه
                  </button>
                </section>
              )}
            </>
          )}
          <footer>
            <span>◈ محتوای شما، روی دستگاه شما</span>
            <span>
              {connectionMode === "demo"
                ? "حالت نمایشی مجزا · بدون ذخیره‌سازی دیسک"
                : "بایگانی محلی آفلاین ساهر · پایگاه‌داده پایدار SQLite FTS5 و موتور کارگر پس‌زمینه"}
            </span>
          </footer>
        </div>
      </main>
      {selected && (
        <FileDetailModal
          selected={selected}
          initialPage={selectedInitialPage}
          onClose={() => {
            setSelected(null);
            setSelectedInitialPage(null);
          }}
          onUpdate={handleUpdateFile}
          onAddTag={handleAddTag}
          onRemoveTag={handleRemoveTag}
          onReanalyze={handleReanalyzeFile}
          onPageUpdated={async (fileId) => {
            const fresh = await ArchiveApiClient.getFile(fileId);
            setSelected(fresh);
            await loadFromBackend();
          }}
          isDemoMode={connectionMode === "demo"}
        />
      )}
      {adding && (
        <ImportDialog
          onClose={() => setAdding(false)}
          onImport={handleImportFiles}
          maxUploadBytes={maxUploadBytes}
        />
      )}
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
