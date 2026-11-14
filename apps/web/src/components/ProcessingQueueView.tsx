import React, { useState } from "react";
import {
  JobItem,
  JobStats,
  WorkerInfo,
  ResourceMode,
  ConnectionMode,
  OCREngineStatus,
} from "../types/archive";
import { ArchiveApiClient } from "../services/apiClient";

interface ProcessingQueueViewProps {
  jobs: JobItem[];
  jobStats: JobStats;
  workers: WorkerInfo[];
  resourceMode: ResourceMode;
  workerConcurrency: number;
  workerOnline?: boolean;
  ocrStatus?: OCREngineStatus | null;
  connectionMode: ConnectionMode;
  loading: boolean;
  stateFilter: string;
  stageFilter: string;
  onStateFilterChange: (val: string) => void;
  onStageFilterChange: (val: string) => void;
  onRefresh: () => Promise<void>;
  onOpenFileById: (fileId: string, pageNumber?: number) => Promise<void>;
  digits: (val: number) => string;
}

const STATE_LABELS: Record<string, string> = {
  QUEUED: "در صف انتظار",
  RUNNING: "در حال اجرا",
  PAUSED: "متوقف موقت",
  COMPLETED: "تکمیل‌شده",
  FAILED: "خطا در پردازش",
  CANCELLED: "لغوشده",
};

const STAGE_LABELS: Record<string, string> = {
  DISCOVERY: "۱. کشف و بررسی فایل",
  VALIDATION: "۲. اعتبارسنجی باینری (SHA-256)",
  EXTRACTION: "۳. استخراج ساختار و متن",
  OCR_PENDING: "۴. تشخیص متن آفلاین (OCR فارسی و انگلیسی)",
  ANALYSIS_PENDING: "۴. در انتظار تحلیل دیداری آفلاین",
  INDEXING: "۵. نمایه‌سازی تمام‌متن و صفحات (FTS5)",
  FINALIZATION: "۶. نهایی‌سازی و ثبت نسخه",
};

const JOB_TYPE_LABELS: Record<string, string> = {
  FILE_INGESTION: "واردسازی و استخراج اولیه",
  REANALYZE: "تحلیل و بازپردازش کامل",
  STAGE_REPROCESS: "بازپردازش مرحله‌ای",
};

const RESOURCE_MODE_LABELS: Record<ResourceMode, { title: string; desc: string }> = {
  Eco: {
    title: "کم‌مصرف",
    desc: "۱ کارگر هم‌زمان · حداقل مصرف پردازنده",
  },
  Balanced: {
    title: "متعادل",
    desc: "۲ کارگر هم‌زمان · تعادل سرعت و منابع سیستم",
  },
  Performance: {
    title: "حداکثر توان",
    desc: "۴ کارگر هم‌زمان · پردازش سریع دسته‌ای",
  },
};

export function ProcessingQueueView({
  jobs,
  jobStats,
  workers,
  resourceMode,
  workerConcurrency,
  workerOnline = true,
  ocrStatus,
  connectionMode,
  loading,
  stateFilter,
  stageFilter,
  onStateFilterChange,
  onStageFilterChange,
  onRefresh,
  onOpenFileById,
  digits,
}: ProcessingQueueViewProps) {
  const [busyJobId, setBusyJobId] = useState<string | null>(null);
  const [changingMode, setChangingMode] = useState(false);
  const [actionBanner, setActionBanner] = useState<string>("");
  const [actionError, setActionError] = useState<string>("");
  const [expandedJob, setExpandedJob] = useState<JobItem | null>(null);

  const isConnected = connectionMode === "connected";
  const onlineWorkers = workers.filter((w) => w.status === "ONLINE");
  const effectiveWorkerOnline = isConnected && (workerOnline || onlineWorkers.length > 0);

  const runJobAction = async (
    jobId: string,
    actionFn: () => Promise<unknown>,
    successMsg: string,
  ) => {
    setBusyJobId(jobId);
    setActionBanner("");
    setActionError("");
    try {
      await actionFn();
      setActionBanner(successMsg);
      await onRefresh();
      if (expandedJob && expandedJob.id === jobId) {
        const fresh = await ArchiveApiClient.getJob(jobId);
        setExpandedJob(fresh);
      }
    } catch (err: any) {
      setActionError(err?.message || "خطا در اجرای دستور روی صف پردازش.");
    } finally {
      setBusyJobId(null);
    }
  };

  const handleModeSwitch = async (mode: ResourceMode) => {
    if (!isConnected || changingMode) return;
    setChangingMode(true);
    setActionBanner("");
    setActionError("");
    try {
      await ArchiveApiClient.updateWorkerConfig(mode);
      setActionBanner(`حالت منابع کارگر به «${RESOURCE_MODE_LABELS[mode].title}» تغییر یافت.`);
      await onRefresh();
    } catch (err: any) {
      setActionError(err?.message || "خطا در تغییر حالت منابع کارگر.");
    } finally {
      setChangingMode(false);
    }
  };

  const handleOcrEngineSwitch = async (engineName: string) => {
    if (!isConnected || changingMode) return;
    setChangingMode(true);
    setActionBanner("");
    setActionError("");
    try {
      const updated = await ArchiveApiClient.switchOcrEngine(engineName);
      setActionBanner(`موتور تشخیص متن آفلاین به «${updated.engine_version}» تغییر یافت.`);
      await onRefresh();
    } catch (err: any) {
      setActionError(err?.message || "خطا در تغییر موتور تشخیص متن (OCR).");
    } finally {
      setChangingMode(false);
    }
  };

  const handleToggleHistory = async (job: JobItem) => {
    if (expandedJob?.id === job.id) {
      setExpandedJob(null);
      return;
    }
    if (!isConnected) {
      setExpandedJob(job);
      return;
    }
    try {
      const detail = await ArchiveApiClient.getJob(job.id);
      setExpandedJob(detail);
    } catch {
      setExpandedJob(job);
    }
  };

  const formatTimestamp = (ts?: string | null) => {
    if (!ts) return "—";
    try {
      const d = new Date(ts.includes("T") ? ts : `${ts.replace(" ", "T")}Z`);
      if (Number.isNaN(d.getTime())) return ts;
      return d.toLocaleTimeString("fa-IR", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    } catch {
      return ts;
    }
  };

  return (
    <div className="queue-dashboard" data-testid="processing-queue-dashboard">
      {/* Queue KPI Summary Cards */}
      <section className="queue-kpi-grid" aria-label="آمار صف پردازش">
        <div className="queue-kpi-card" data-testid="kpi-queued-jobs">
          <small>در صف انتظار</small>
          <strong className="tabular-nums">{digits(jobStats.queued)}</strong>
          <span>آمادهٔ تحویل به کارگر</span>
        </div>
        <div className="queue-kpi-card" data-testid="kpi-running-jobs">
          <small>در حال اجرا</small>
          <strong className="tabular-nums">{digits(jobStats.running)}</strong>
          <span>
            کارگرهای فعال: {digits(onlineWorkers.length || (effectiveWorkerOnline ? 1 : 0))}
          </span>
        </div>
        <div className="queue-kpi-card" data-testid="kpi-completed-jobs">
          <small>تکمیل‌شده</small>
          <strong className="tabular-nums">{digits(jobStats.completed)}</strong>
          <span>ثبت‌شده در پایگاه‌داده</span>
        </div>
        <div className="queue-kpi-card" data-testid="kpi-failed-jobs">
          <small>خطا / متوقف</small>
          <strong className="tabular-nums">
            {digits(jobStats.failed + jobStats.paused)}
          </strong>
          <span>
            خطا: {digits(jobStats.failed)} · متوقف: {digits(jobStats.paused)}
          </span>
        </div>
      </section>

      {/* Worker Availability, Standalone Worker Heartbeat & Offline OCR Engine Status */}
      <section className="worker-resource-bar" aria-label="مدیریت منابع و کارگرهای پس‌زمینه">
        <div className="worker-meta">
          <strong>
            وضعیت موتور پردازش پس‌زمینه:{" "}
            {!isConnected
              ? "حالت نمایشی (غیرمتصل)"
              : effectiveWorkerOnline
                ? "فعال و متصل به SQLite"
                : "کارگر پس‌زمینه آفلاین است"}
          </strong>
          <p>
            هم‌زمانی فعلی: <span className="tabular-nums">{digits(workerConcurrency)}</span> کارگر ·
            حالت منابع: {RESOURCE_MODE_LABELS[resourceMode]?.title || resourceMode}
            {onlineWorkers[0]?.worker_id ? ` · شناسه کارگر: ${onlineWorkers[0].worker_id}` : ""}
          </p>
          {ocrStatus && (
            <p className="ocr-engine-meta" data-testid="ocr-engine-status-line">
              موتور تشخیص متن آفلاین (OCR):{" "}
              {ocrStatus.ready ? (
                <span>
                  ✓ آماده ({ocrStatus.engine_version} · مدل‌های فعال:{" "}
                  {ocrStatus.installed_languages.join("، ")})
                </span>
              ) : (
                <span className="ocr-missing-warning">
                  ⚠ خطا ({ocrStatus.error_code}): {ocrStatus.error_message}
                </span>
              )}
            </p>
          )}
          {ocrStatus?.paddleocr_metadata && (
            <p className="ocr-engine-meta" data-testid="paddleocr-repo-status-line">
              مخزن یکپارچه‌شدهٔ <strong>PaddlePaddle/PaddleOCR</strong>:{" "}
              {ocrStatus.paddleocr_metadata.repo_present ? (
                <span>
                  ✓ فعال در <code>vendor/PaddleOCR</code> · واژه‌نامه‌های بارگذاری‌شده:{" "}
                  <code>fa_dict.txt</code>، <code>ppocrv5_arabic_dict.txt</code>،{" "}
                  <code>en_dict.txt</code> ({digits(ocrStatus.paddleocr_metadata.total_charset_size)} نویسه)
                </span>
              ) : (
                <span>در انتظار بارگذاری مخزن</span>
              )}
            </p>
          )}
        </div>
        <div className="worker-controls-stack">
          <div className="resource-mode-group" role="group" aria-label="انتخاب حالت منابع پردازشی">
            {(["Eco", "Balanced", "Performance"] as ResourceMode[]).map((m) => (
              <button
                key={m}
                type="button"
                disabled={!isConnected || changingMode}
                className={resourceMode === m ? "mode-btn active" : "mode-btn"}
                onClick={() => handleModeSwitch(m)}
                title={RESOURCE_MODE_LABELS[m].desc}
              >
                {RESOURCE_MODE_LABELS[m].title}
              </button>
            ))}
          </div>
          {ocrStatus && (
            <div
              className="resource-mode-group"
              role="group"
              aria-label="انتخاب موتور تشخیص متن آفلاین (OCR)"
              data-testid="ocr-engine-switcher-group"
            >
              {[
                { id: "paddleocr", label: "PaddleOCR (PP-OCRv4/v5)" },
                { id: "hybrid", label: "ترکیبی (PaddleOCR + Tesseract)" },
                { id: "tesseract", label: "Tesseract 5 LSTM" },
              ].map((eng) => (
                <button
                  key={eng.id}
                  type="button"
                  data-testid={`switch-ocr-engine-${eng.id}`}
                  disabled={!isConnected || changingMode}
                  className={ocrStatus.engine_name === eng.id ? "mode-btn active" : "mode-btn"}
                  onClick={() => handleOcrEngineSwitch(eng.id)}
                >
                  {eng.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </section>

      {actionBanner && (
        <div className="queue-banner success" role="status">
          {actionBanner}
        </div>
      )}
      {actionError && (
        <div className="queue-banner error" role="alert">
          {actionError}
        </div>
      )}

      {/* Queue Filter Toolbar */}
      <section className="toolbar queue-toolbar">
        <div className="queue-filters">
          <label htmlFor="job-state-filter" className="sr-only">
            فیلتر وضعیت کار
          </label>
          <select
            id="job-state-filter"
            aria-label="فیلتر وضعیت کار"
            value={stateFilter}
            onChange={(e) => onStateFilterChange(e.target.value)}
          >
            <option value="ALL">همهٔ وضعیت‌های صف</option>
            <option value="QUEUED">در صف انتظار (QUEUED)</option>
            <option value="RUNNING">در حال اجرا (RUNNING)</option>
            <option value="PAUSED">متوقف موقت (PAUSED)</option>
            <option value="COMPLETED">تکمیل‌شده (COMPLETED)</option>
            <option value="FAILED">دارای خطا (FAILED)</option>
            <option value="CANCELLED">لغوشده (CANCELLED)</option>
          </select>

          <label htmlFor="job-stage-filter" className="sr-only">
            فیلتر مرحلهٔ پردازش
          </label>
          <select
            id="job-stage-filter"
            aria-label="فیلتر مرحلهٔ پردازش"
            value={stageFilter}
            onChange={(e) => onStageFilterChange(e.target.value)}
          >
            <option value="ALL">همهٔ مراحل پردازش</option>
            <option value="DISCOVERY">کشف و بررسی فایل (DISCOVERY)</option>
            <option value="VALIDATION">اعتبارسنجی باینری (VALIDATION)</option>
            <option value="EXTRACTION">استخراج متن (EXTRACTION)</option>
            <option value="OCR_PENDING">تشخیص متن آفلاین (OCR_PENDING)</option>
            <option value="ANALYSIS_PENDING">در انتظار تحلیل دیداری (ANALYSIS_PENDING)</option>
            <option value="INDEXING">نمایه‌سازی FTS5 (INDEXING)</option>
            <option value="FINALIZATION">نهایی‌سازی (FINALIZATION)</option>
          </select>
        </div>

        <button
          type="button"
          onClick={() => onRefresh()}
          disabled={loading}
          aria-label="بروزرسانی صف پردازش"
        >
          {loading ? "در حال دریافت…" : "↻ بروزرسانی صف"}
        </button>
      </section>

      <div className="sectionline">
        <h2>
          فهرست کارهای پردازشی <span>{digits(jobs.length)} کار</span>
        </h2>
        <span>
          نگهداری پایدار در جدول jobs پایگاه‌داده SQLite با قابلیت بازیابی خودکار پس از وقفه
        </span>
      </div>

      {/* Job Items Table / Cards */}
      {jobs.length > 0 ? (
        <div className="job-list" data-testid="job-list-container">
          {jobs.map((job) => {
            const isBusy = busyJobId === job.id;
            const canPause = isConnected && (job.state === "QUEUED" || job.state === "RUNNING");
            const canResume = isConnected && job.state === "PAUSED";
            const canRetry = isConnected && (job.state === "FAILED" || job.state === "CANCELLED");
            const canCancel =
              isConnected &&
              (job.state === "QUEUED" || job.state === "RUNNING" || job.state === "PAUSED");
            const canReprocess =
              isConnected &&
              (job.state === "COMPLETED" || job.state === "FAILED" || job.state === "CANCELLED");
            const isExpanded = expandedJob?.id === job.id;
            const failedPages = Array.isArray(job.checkpoint?.failed_pages)
              ? (job.checkpoint?.failed_pages as number[])
              : [];
            const ocrMs =
              typeof job.checkpoint?.ocr_processing_ms === "number"
                ? (job.checkpoint.ocr_processing_ms as number)
                : null;

            return (
              <article
                key={job.id}
                className={`job-card state-${job.state.toLowerCase()}`}
                data-testid={`job-item-${job.id}`}
              >
                <div className="job-card-main">
                  <div className="job-title-group">
                    <div className="job-meta-line">
                      <span className={`job-state-text state-${job.state.toLowerCase()}`}>
                        {STATE_LABELS[job.state] || job.state}
                      </span>
                      <span aria-hidden="true">·</span>
                      <span>{STAGE_LABELS[job.processing_stage] || job.processing_stage}</span>
                      <span aria-hidden="true">·</span>
                      <span>{JOB_TYPE_LABELS[job.job_type] || job.job_type}</span>
                      <span aria-hidden="true">·</span>
                      <span className="tabular-nums">
                        تلاش {digits(job.attempt_count)} از {digits(job.max_retries)}
                      </span>
                      {ocrMs != null && ocrMs > 0 && (
                        <>
                          <span aria-hidden="true">·</span>
                          <span className="tabular-nums">
                            زمان OCR: {digits(Math.round(ocrMs))} میلی‌ثانیه
                          </span>
                        </>
                      )}
                    </div>

                    <h3>
                      <button
                        type="button"
                        className="job-file-link"
                        onClick={() => onOpenFileById(job.file_id)}
                      >
                        {job.file_title || `فایل ${job.file_id.substring(0, 8)}`}
                      </button>
                    </h3>

                    {job.progress_message && (
                      <p className="job-progress-note">{job.progress_message}</p>
                    )}

                    {failedPages.length > 0 && (
                      <div className="job-error-box" role="alert">
                        <strong>
                          خطای خواندن در صفحهٔ {failedPages.map(digits).join("، ")}:
                        </strong>{" "}
                        سایر صفحات سالم فایل استخراج و نمایه‌سازی شدند.{" "}
                        <button
                          type="button"
                          className="inline-page-jump-btn"
                          onClick={() => onOpenFileById(job.file_id, failedPages[0])}
                        >
                          مشاهدهٔ صفحهٔ دارای خطا ←
                        </button>
                      </div>
                    )}

                    {job.error_message && (
                      <div className="job-error-box" role="alert">
                        <strong>خطا ({job.error_code || "ERROR"}):</strong> {job.error_message}
                      </div>
                    )}

                    <div className="job-timestamps tabular-nums">
                      <span>ثبت: {formatTimestamp(job.created_at)}</span>
                      <span aria-hidden="true">·</span>
                      <span>شروع: {formatTimestamp(job.started_at)}</span>
                      <span aria-hidden="true">·</span>
                      <span>پایان: {formatTimestamp(job.completed_at)}</span>
                      <span aria-hidden="true">·</span>
                      <span>نسخه پردازش: {digits(job.processing_version)}</span>
                    </div>
                  </div>

                  <div className="job-progress-column">
                    <div className="job-progress-header tabular-nums">
                      <span>پیشرفت مرحله</span>
                      <strong>{digits(Math.round(job.progress))}٪</strong>
                    </div>
                    <progress
                      className="job-progress-native"
                      value={Math.min(100, Math.max(0, Math.round(job.progress)))}
                      max={100}
                      aria-label="درصد پیشرفت کار"
                    />

                    <div className="job-actions">
                      {canPause && (
                        <button
                          type="button"
                          disabled={isBusy}
                          onClick={() =>
                            runJobAction(
                              job.id,
                              () => ArchiveApiClient.pauseJob(job.id),
                              "کار پردازشی موقتاً متوقف شد.",
                            )
                          }
                        >
                          توقف موقت
                        </button>
                      )}
                      {canResume && (
                        <button
                          type="button"
                          className="primary-sm"
                          disabled={isBusy}
                          onClick={() =>
                            runJobAction(
                              job.id,
                              () => ArchiveApiClient.resumeJob(job.id),
                              "کار پردازشی در صف ادامه قرار گرفت.",
                            )
                          }
                        >
                          ادامه
                        </button>
                      )}
                      {canRetry && (
                        <button
                          type="button"
                          className="primary-sm"
                          disabled={isBusy}
                          onClick={() =>
                            runJobAction(
                              job.id,
                              () => ArchiveApiClient.retryJob(job.id),
                              "تلاش مجدد کار در صف ثبت شد.",
                            )
                          }
                        >
                          تلاش مجدد
                        </button>
                      )}
                      {canCancel && (
                        <button
                          type="button"
                          disabled={isBusy}
                          onClick={() =>
                            runJobAction(
                              job.id,
                              () => ArchiveApiClient.cancelJob(job.id),
                              "کار پردازشی لغو شد.",
                            )
                          }
                        >
                          لغو کار
                        </button>
                      )}
                      {canReprocess && (
                        <button
                          type="button"
                          disabled={isBusy}
                          onClick={() =>
                            runJobAction(
                              job.id,
                              () => ArchiveApiClient.reanalyzeFile(job.file_id),
                              "درخواست بازپردازش فایل در صف ثبت شد.",
                            )
                          }
                        >
                          پردازش دوباره
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => handleToggleHistory(job)}
                        aria-expanded={isExpanded}
                      >
                        {isExpanded ? "بستن تاریخچه" : "تاریخچهٔ اجرا"}
                      </button>
                    </div>
                  </div>
                </div>

                {isExpanded && (
                  <div className="job-events-drawer" data-testid={`job-events-${job.id}`}>
                    <h4>تاریخچهٔ رویدادها و تلاش‌های کارگر</h4>
                    {expandedJob?.events && expandedJob.events.length > 0 ? (
                      <ul className="job-event-list">
                        {expandedJob.events.map((ev) => (
                          <li key={ev.id}>
                            <span className="tabular-nums">{formatTimestamp(ev.created_at)}</span>
                            <span aria-hidden="true">·</span>
                            <strong>{ev.event_type}</strong>
                            <span aria-hidden="true">·</span>
                            <span>مرحله: {STAGE_LABELS[ev.stage] || ev.stage}</span>
                            {ev.message && (
                              <>
                                <span aria-hidden="true">·</span>
                                <span>{ev.message}</span>
                              </>
                            )}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p>رویدادی برای این کار ثبت نشده است.</p>
                    )}
                  </div>
                )}
              </article>
            );
          })}
        </div>
      ) : (
        <div className="empty" data-testid="empty-jobs-state">
          هیچ کار پردازشی با فیلترهای انتخابی در صف وجود ندارد. با وارد کردن یک فایل جدید از کتابخانه، کار پردازشی پایدار در این صفحه ثبت و اجرا می‌شود.
        </div>
      )}
    </div>
  );
}
