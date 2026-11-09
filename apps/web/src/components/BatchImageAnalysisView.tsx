import React, { useState, useRef } from "react";
import {
  ConnectionMode,
  FileItem,
  FolderAnalysisResponse,
  ImageAnalysisItem,
} from "../types/archive";
import { ArchiveApiClient } from "../services/apiClient";

interface BatchImageAnalysisViewProps {
  connectionMode: ConnectionMode;
  archiveFiles: FileItem[];
  onRefreshArchive: () => Promise<void>;
  onOpenFileById: (fileId: string, pageNumber?: number) => void;
  digits: (n: number) => string;
}

const IMAGE_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp", ".bmp"];

function isSupportedImageFile(file: File): boolean {
  const lower = file.name.toLowerCase();
  if (IMAGE_EXTENSIONS.some((ext) => lower.endsWith(ext))) {
    return true;
  }
  return file.type.startsWith("image/");
}

export function BatchImageAnalysisView({
  connectionMode,
  archiveFiles,
  onRefreshArchive,
  onOpenFileById,
  digits,
}: BatchImageAnalysisViewProps) {
  const [analysisReport, setAnalysisReport] = useState<FolderAnalysisResponse | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isExportingWord, setIsExportingWord] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string>("");
  const [errorMessage, setErrorMessage] = useState<string>("");
  const [customFolderName, setCustomFolderName] = useState<string>("");
  const [topicFilter, setTopicFilter] = useState<string>("ALL");

  const folderInputRef = useRef<HTMLInputElement | null>(null);
  const filesInputRef = useRef<HTMLInputElement | null>(null);

  const existingImageFiles = archiveFiles.filter(
    (f) => f.mime_type.startsWith("image/") || f.kind === "تصویر" || f.kind === "اسکرین‌شات",
  );

  const handleAnalyzeSelectedFiles = async (fileList: FileList | null, fromFolderPicker: boolean) => {
    if (!fileList || fileList.length === 0) return;
    if (connectionMode !== "connected") {
      setErrorMessage("تحلیل پوشهٔ عکس‌ها و تولید فایل Word نیازمند اتصال به سرویس محلی ساهر (FastAPI) است.");
      return;
    }

    const validImages: File[] = [];
    let detectedFolder = customFolderName.trim();

    for (let i = 0; i < fileList.length; i++) {
      const f = fileList[i];
      if (isSupportedImageFile(f)) {
        validImages.push(f);
        if (!detectedFolder) {
          const rel = (f as any).webkitRelativePath as string | undefined;
          if (rel && rel.includes("/")) {
            detectedFolder = rel.split("/")[0];
          }
        }
      }
    }

    if (validImages.length === 0) {
      setErrorMessage(
        "در پوشه یا فایل‌های انتخاب‌شده هیچ تصویر معتبری با فرمت‌های مجاز (PNG, JPG, WEBP, BMP) یافت نشد.",
      );
      return;
    }

    setIsAnalyzing(true);
    setErrorMessage("");
    setStatusMessage(
      `در حال واکاوی ماهیت بصری، استخراج متن آفلاین (OCR) و تشخیص موضوع برای ${digits(validImages.length)} تصویر…`,
    );

    try {
      const folderTitle =
        detectedFolder || (fromFolderPicker ? "پوشهٔ عکس‌های انتخابی" : "مجموعه تصاویر انتخابی");
      const response = await ArchiveApiClient.analyzeImageFolder(validImages, folderTitle);
      setAnalysisReport(response);
      setTopicFilter("ALL");
      setStatusMessage(
        `تحلیل مجزای ${digits(response.total_images)} عکس در «${response.folder_name}» تکمیل شد. اکنون می‌توانید گزارش کامل Word (.docx) را دریافت کنید.`,
      );
      await onRefreshArchive();
    } catch (err: any) {
      setErrorMessage(err?.message || "خطا در تحلیل پوشهٔ تصاویر در سرویس بک‌اند.");
      setStatusMessage("");
    } finally {
      setIsAnalyzing(false);
      if (folderInputRef.current) folderInputRef.current.value = "";
      if (filesInputRef.current) filesInputRef.current.value = "";
    }
  };

  const handleAnalyzeExistingArchiveImages = async () => {
    if (existingImageFiles.length === 0) {
      setErrorMessage("در حال حاضر هیچ عکس یا اسکرین‌شاتی در کتابخانه ثبت نشده است. لطفاً یک پوشهٔ عکس انتخاب کنید.");
      return;
    }
    if (connectionMode !== "connected") {
      setErrorMessage("این عملیات نیازمند اتصال به سرویس محلی FastAPI است.");
      return;
    }

    setIsAnalyzing(true);
    setErrorMessage("");
    setStatusMessage(
      `در حال تحلیل موضوع و ماهیت ${digits(existingImageFiles.length)} تصویر موجود در کتابخانه…`,
    );

    try {
      const ids = existingImageFiles.map((f) => f.id);
      const response = await ArchiveApiClient.analyzeExistingImages(
        ids,
        customFolderName.trim() || "تصاویر آرشیو کتابخانه",
      );
      setAnalysisReport(response);
      setTopicFilter("ALL");
      setStatusMessage(
        `تحلیل مجزای ${digits(response.total_images)} تصویر کتابخانه تکمیل شد و آمادهٔ خروجی Word است.`,
      );
      await onRefreshArchive();
    } catch (err: any) {
      setErrorMessage(err?.message || "خطا در تحلیل تصاویر موجود در کتابخانه.");
      setStatusMessage("");
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleDownloadFullWordReport = async () => {
    if (!analysisReport || analysisReport.items.length === 0) return;
    setIsExportingWord(true);
    setErrorMessage("");
    try {
      const fileIds = analysisReport.items.map((item) => item.file_id);
      const blob = await ArchiveApiClient.downloadImagesWordReport(
        fileIds,
        analysisReport.folder_name,
      );
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      const safeName = (analysisReport.folder_name || "images")
        .replace(/[^\u0600-\u06FFa-zA-Z0-9_-]+/g, "-")
        .replace(/^-+|-+$/g, "");
      link.download = `گزارش-تحلیل-تصاویر-${safeName || "ساهر"}.docx`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err: any) {
      setErrorMessage(err?.message || "خطا در دریافت فایل گزارش Word (.docx).");
    } finally {
      setIsExportingWord(false);
    }
  };

  const handleDownloadSingleImageWord = async (item: ImageAnalysisItem) => {
    try {
      const blob = await ArchiveApiClient.downloadImagesWordReport([item.file_id], item.title);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      const baseTitle = item.title.replace(/\.[^.]+$/, "");
      link.download = `تحلیل-تصویر-${baseTitle}.docx`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err: any) {
      setErrorMessage(err?.message || "خطا در تولید فایل Word برای این تصویر.");
    }
  };

  const displayedItems = analysisReport
    ? topicFilter === "ALL"
      ? analysisReport.items
      : analysisReport.items.filter((i) => i.detected_topic === topicFilter)
    : [];

  return (
    <section className="batch-analysis-container" data-testid="batch-image-analysis-view">
      {/* 1. Folder & Multi-Image Input Panel */}
      <div className="batch-upload-panel">
        <div className="batch-upload-header">
          <div>
            <h2>دریافت پوشهٔ عکس‌ها، تشخیص ماهیت و موضوع هر عکس و تولید گزارش Word</h2>
            <p>
              یک پوشهٔ کامل از عکس‌ها را انتخاب کنید تا سامانهٔ ساهر هر تصویر را به‌صورت جداگانه از نظر{" "}
              <strong>ماهیت بصری</strong> (سند اسکن‌شده، فاکتور مالی، قرارداد، اسکرین‌شات، نقشه یا عکس واقعی)،{" "}
              <strong>موضوع محتوایی</strong> و <strong>متن داخل تصویر (OCR)</strong> تحلیل کرده و در قالب یک فایل{" "}
              <strong>Word (.docx)</strong> مجزا و مصور تحویل دهد.
            </p>
          </div>
          <div className="batch-folder-title-input">
            <label htmlFor="batch-folder-title">عنوان گزارش در فایل Word (اختیاری):</label>
            <input
              id="batch-folder-title"
              type="text"
              placeholder="مثلاً: اسناد و تصاویر پروژهٔ آبان ۱۴۰۵"
              value={customFolderName}
              disabled={isAnalyzing}
              onChange={(e) => setCustomFolderName(e.target.value)}
            />
          </div>
        </div>

        <div className="batch-actions-grid">
          {/* Option 1: Select an entire Folder of Images */}
          <label
            className={`batch-drop-card primary-drop ${isAnalyzing ? "disabled" : ""}`}
            data-testid="select-image-folder-label"
          >
            <span className="batch-card-icon">▤</span>
            <div className="batch-card-text">
              <strong>انتخاب پوشهٔ کامل عکس‌ها (Folder)</strong>
              <small>
                تمامی عکس‌های موجود در پوشهٔ انتخابی (PNG, JPG, WEBP, BMP) به‌صورت خودکار شناسایی و تک‌به‌تک تحلیل می‌شوند
              </small>
            </div>
            <input
              ref={folderInputRef}
              type="file"
              multiple
              // @ts-expect-error webkitdirectory is standard across Chromium/Firefox/Safari for directory selection
              webkitdirectory=""
              directory=""
              disabled={isAnalyzing || connectionMode !== "connected"}
              onChange={(e) => handleAnalyzeSelectedFiles(e.target.files, true)}
            />
          </label>

          {/* Option 2: Select Multiple Image Files */}
          <label
            className={`batch-drop-card ${isAnalyzing ? "disabled" : ""}`}
            data-testid="select-multiple-images-label"
          >
            <span className="batch-card-icon">＋</span>
            <div className="batch-card-text">
              <strong>انتخاب چند عکس به‌صورت هم‌زمان</strong>
              <small>انتخاب مستقیم یک یا چند فایل تصویری از پوشه‌های مختلف دستگاه</small>
            </div>
            <input
              ref={filesInputRef}
              type="file"
              multiple
              accept=".png,.jpg,.jpeg,.webp,.bmp,image/*"
              disabled={isAnalyzing || connectionMode !== "connected"}
              onChange={(e) => handleAnalyzeSelectedFiles(e.target.files, false)}
            />
          </label>

          {/* Option 3: Analyze Existing Images in Archive */}
          <button
            type="button"
            className="batch-drop-card button-card"
            data-testid="analyze-existing-images-btn"
            disabled={isAnalyzing || connectionMode !== "connected" || existingImageFiles.length === 0}
            onClick={handleAnalyzeExistingArchiveImages}
          >
            <span className="batch-card-icon">⌕</span>
            <div className="batch-card-text">
              <strong>
                تحلیل عکس‌های موجود در کتابخانه ({digits(existingImageFiles.length)} تصویر)
              </strong>
              <small>
                اجرای تحلیل ماهیت و موضوع روی تصاویر فعلی آرشیو و دریافت خروجی یکپارچهٔ Word
              </small>
            </div>
          </button>
        </div>

        {statusMessage && (
          <div className="batch-status-banner" role="status" data-testid="batch-analysis-status">
            <span>{isAnalyzing ? "◌" : "✓"}</span>
            <span>{statusMessage}</span>
          </div>
        )}

        {errorMessage && (
          <div className="import-error-alert" role="alert" data-testid="batch-analysis-error">
            <strong>خطا:</strong> {errorMessage}
          </div>
        )}
      </div>

      {/* 2. Results & Word Export Section */}
      {analysisReport && (
        <div className="batch-results-section" data-testid="batch-analysis-results">
          <div className="batch-results-header">
            <div>
              <h3>
                نتیجهٔ تحلیل مجزای عکس‌ها: {analysisReport.folder_name} (
                <span className="tabular-nums">{digits(analysisReport.total_images)}</span> تصویر)
              </h3>
              <p className="batch-breakdown-line">
                <span>تفکیک موضوعات: </span>
                {Object.entries(analysisReport.topic_breakdown).map(([topic, cnt], idx) => (
                  <React.Fragment key={topic}>
                    {idx > 0 && <span aria-hidden="true"> · </span>}
                    <span>
                      {topic} (<strong className="tabular-nums">{digits(cnt)}</strong>)
                    </span>
                  </React.Fragment>
                ))}
              </p>
              <p className="batch-breakdown-line">
                <span>تفکیک ماهیت بصری: </span>
                {Object.entries(analysisReport.nature_breakdown).map(([nat, cnt], idx) => (
                  <React.Fragment key={nat}>
                    {idx > 0 && <span aria-hidden="true"> · </span>}
                    <span>
                      {nat} (<strong className="tabular-nums">{digits(cnt)}</strong>)
                    </span>
                  </React.Fragment>
                ))}
              </p>
            </div>

            <button
              type="button"
              className="primary export-word-cta"
              data-testid="download-full-word-report-btn"
              disabled={isExportingWord || analysisReport.items.length === 0}
              onClick={handleDownloadFullWordReport}
            >
              <span>⬇</span>
              <span>
                {isExportingWord
                  ? "در حال صفحه‌بندی و ساخت فایل Word…"
                  : `دریافت گزارش تحلیل مجزا در قالب Word (.docx)`}
              </span>
            </button>
          </div>

          {/* Interactive Topic Filter Tabs */}
          {Object.keys(analysisReport.topic_breakdown).length > 1 && (
            <div className="batch-filter-bar" role="tablist" aria-label="فیلتر بر اساس موضوع تشخیص‌داده‌شده">
              <button
                type="button"
                role="tab"
                aria-selected={topicFilter === "ALL"}
                className={topicFilter === "ALL" ? "active" : ""}
                onClick={() => setTopicFilter("ALL")}
              >
                همهٔ عکس‌ها ({digits(analysisReport.total_images)})
              </button>
              {Object.entries(analysisReport.topic_breakdown).map(([topic, count]) => (
                <button
                  key={topic}
                  type="button"
                  role="tab"
                  aria-selected={topicFilter === topic}
                  className={topicFilter === topic ? "active" : ""}
                  onClick={() => setTopicFilter(topic)}
                >
                  {topic} ({digits(count)})
                </button>
              ))}
            </div>
          )}

          {/* Per-Image Separate Analysis Cards */}
          <div className="batch-items-list">
            {displayedItems.map((item, idx) => (
              <article
                key={item.file_id}
                className="batch-item-card"
                data-testid={`analyzed-image-card-${idx + 1}`}
              >
                <div className="batch-item-preview">
                  <img
                    src={ArchiveApiClient.getPagePreviewUrl(item.file_id, 1)}
                    alt={`پیش‌نمایش تصویر ${item.title}`}
                    referrerPolicy="no-referrer"
                    loading="lazy"
                  />
                  <div className="batch-item-index tabular-nums">
                    تصویر شمارهٔ {digits(idx + 1)}
                  </div>
                </div>

                <div className="batch-item-body">
                  <div className="batch-item-toprow">
                    <div>
                      <h4>{item.title}</h4>
                      {item.relative_path && item.relative_path !== item.title && (
                        <small className="batch-rel-path">مسیر در پوشه: {item.relative_path}</small>
                      )}
                    </div>
                    <div className="batch-item-actions">
                      <button
                        type="button"
                        className="secondary-btn"
                        onClick={() => onOpenFileById(item.file_id, 1)}
                      >
                        مشاهدهٔ جزئیات در کتابخانه
                      </button>
                      <button
                        type="button"
                        className="secondary-btn"
                        data-testid={`download-single-word-btn-${idx + 1}`}
                        onClick={() => handleDownloadSingleImageWord(item)}
                      >
                        ⬇ فایل Word این عکس (.docx)
                      </button>
                    </div>
                  </div>

                  {/* Clean unboxed metadata row */}
                  <div className="batch-item-meta tabular-nums">
                    <span>
                      <strong>موضوع:</strong> {item.detected_topic}
                    </span>
                    <span aria-hidden="true">·</span>
                    <span>
                      <strong>ماهیت تصویر:</strong> {item.image_nature}
                    </span>
                    <span aria-hidden="true">·</span>
                    <span>
                      ابعاد: {digits(item.width)}×{digits(item.height)} ({item.orientation})
                    </span>
                    <span aria-hidden="true">·</span>
                    <span>{item.color_profile_label}</span>
                    <span aria-hidden="true">·</span>
                    <span>
                      کلمات استخراج‌شده: {digits(item.word_count)}
                      {item.ocr_confidence != null ? ` (دقت OCR: ${digits(Math.round(item.ocr_confidence))}٪)` : ""}
                    </span>
                  </div>

                  <p className="batch-item-summary">{item.analysis_summary}</p>

                  {item.extracted_text && (
                    <div className="batch-item-ocr-box">
                      <strong>متن خوانده‌شده از داخل این تصویر (OCR):</strong>
                      <p>{item.extracted_text}</p>
                    </div>
                  )}
                </div>
              </article>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
