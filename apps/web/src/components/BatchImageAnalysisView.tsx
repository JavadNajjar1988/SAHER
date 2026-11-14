import React, { useState, useRef } from "react";
import {
  ConnectionMode,
  CulturalSocialTemplateFields,
  FileItem,
  FolderAnalysisResponse,
  ImageAnalysisItem,
  THEMATIC_CATEGORIES_12,
} from "../types/archive";
import { ArchiveApiClient } from "../services/apiClient";

interface BatchImageAnalysisViewProps {
  connectionMode: ConnectionMode;
  archiveFiles: FileItem[];
  onRefreshArchive: () => Promise<void>;
  onOpenFileById: (fileId: string, pageNumber?: number) => void;
  onOpenIdentityProfiles?: () => void;
  digits: (n: number | string) => string;
}

const IMAGE_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp", ".bmp"];

function isSupportedImageFile(file: File): boolean {
  const lower = file.name.toLowerCase();
  if (IMAGE_EXTENSIONS.some((ext) => lower.endsWith(ext))) {
    return true;
  }
  return file.type.startsWith("image/");
}

export function formatCulturalTemplateClient(fields: CulturalSocialTemplateFields): string {
  const fullName = (fields.full_name || "").trim();
  const nationalId = (fields.national_id || "").trim();
  const phoneNumber = (fields.phone_number || "").trim();
  const occupation = (fields.occupation || "").trim();
  const violation = (fields.violation || "ترویج ابتذال").trim() || "ترویج ابتذال";
  const actionRequest = (fields.action_request || "درخواست مسدودی سیم کارت").trim() || "درخواست مسدودی سیم کارت";
  const profileUrl = (fields.profile_url || "").trim();
  const hashtags =
    fields.hashtags && fields.hashtags.length > 0
      ? fields.hashtags
      : ["#ابتذال", "#خراسان_رضوی", "#شهرستان_کاشمر"];

  const lines: string[] = [
    `نام و نام خانوادگی: ${fullName}`,
    `کدملی: ${nationalId}`,
    `شماره تماس: ${phoneNumber}`,
    `شغل: ${occupation}`,
    `تخلف: ${violation}`,
    actionRequest,
  ];
  if (profileUrl) {
    lines.push(profileUrl);
  }
  lines.push("");
  for (const tag of hashtags) {
    const clean = tag.trim();
    if (!clean) continue;
    lines.push(clean.startsWith("#") ? clean : `#${clean}`);
  }
  return lines.join("\n");
}

export function formatSocialBlockingTemplateClient(fields: CulturalSocialTemplateFields): string {
  const fullName = (fields.full_name || "").trim();
  const nationalId = (fields.national_id || "").trim();
  const phoneNumber = (fields.phone_number || "").trim();
  const guidanceDate = (fields.guidance_date || "").trim();
  const numericId = (fields.numeric_id || "").trim();
  const profileUrl = (fields.profile_url || "").trim();

  let rawHandle = (fields.account_handle || "").trim().replace(/^@/, "");
  if (!rawHandle && profileUrl) {
    const m = profileUrl.match(/(?:instagram\.com|instagr\.am|t\.me)\/([A-Za-z0-9_.]{3,40})/i);
    if (m && m[1]) {
      rawHandle = m[1].replace(/[._/]+$/, "");
    }
  }
  const handleLine = rawHandle ? `@${rawHandle}` : "@";
  const description = (fields.description || "").trim();
  let cityHashtag = (fields.city_hashtag || "#کاشمر").trim() || "#کاشمر";
  if (!cityHashtag.startsWith("#")) {
    cityHashtag = `#${cityHashtag}`;
  }

  const lines: string[] = [
    "〰️〰️〰️〰️〰️〰️〰️〰️〰️",
    "#مسدودسازی",
    "#اینستاگرام",
    "",
    `✅نام و نام خانوادگی: ${fullName}`,
    `✅کدملی: ${nationalId}`,
    `✅ شماره تماس/حساب: ${phoneNumber}`,
    `✅ تاریخ ارشاد: ${guidanceDate}`,
    `✅ آیدی عددی: ${numericId}`,
    profileUrl ? `✅ آدرس اینترنتی: ${profileUrl}` : "✅ آدرس اینترنتی:",
    handleLine,
    `توضیحات: ${description}`,
    "",
    cityHashtag,
    "〰️〰️〰️〰️〰️〰️〰️〰️〰️",
  ];
  return lines.join("\n");
}

export function formatCulturalSocialTemplateClient(
  fields: CulturalSocialTemplateFields,
  thematicCategory = "",
): string {
  const culturalTxt = formatCulturalTemplateClient(fields);
  const socialTxt = formatSocialBlockingTemplateClient(fields);
  if (thematicCategory === "اجتماعی") {
    return `${socialTxt}\n\n${culturalTxt}`;
  }
  return `${culturalTxt}\n\n${socialTxt}`;
}

export function BatchImageAnalysisView({
  connectionMode,
  archiveFiles,
  onRefreshArchive,
  onOpenFileById,
  onOpenIdentityProfiles,
  digits,
}: BatchImageAnalysisViewProps) {
  const [analysisReport, setAnalysisReport] = useState<FolderAnalysisResponse | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isExportingWord, setIsExportingWord] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string>("");
  const [errorMessage, setErrorMessage] = useState<string>("");
  const [customFolderName, setCustomFolderName] = useState<string>("");
  const [instagramSourceUrl, setInstagramSourceUrl] = useState<string>("");
  const [selectedOcrEngine, setSelectedOcrEngine] = useState<string>("paddleocr");
  const [accountFilter, setAccountFilter] = useState<string>("ALL");
  const [topicFilter, setTopicFilter] = useState<string>("ALL");
  const [sourceTypeFilter, setSourceTypeFilter] = useState<string>("ALL");
  const [templateOverrides, setTemplateOverrides] = useState<Record<string, CulturalSocialTemplateFields>>({});
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  const folderInputRef = useRef<HTMLInputElement | null>(null);
  const filesInputRef = useRef<HTMLInputElement | null>(null);

  const existingImageFiles = archiveFiles.filter(
    (f) => f.mime_type.startsWith("image/") || f.kind === "تصویر" || f.kind === "اسکرین‌شات",
  );

  const getEffectiveTemplateFields = (item: ImageAnalysisItem): CulturalSocialTemplateFields => {
    const over = templateOverrides[item.file_id];
    if (over) return over;
    if (item.template_fields) return item.template_fields;
    const rawHandle = (item.account_id || "").replace(/^@/, "").trim();
    const fallbackUrl =
      instagramSourceUrl.trim() ||
      (rawHandle && rawHandle !== "نامشخص" ? `https://www.instagram.com/${rawHandle}` : "");
    return {
      full_name: "",
      national_id: "",
      phone_number: "",
      guidance_date: "",
      numeric_id: "",
      account_handle: rawHandle && rawHandle !== "نامشخص" ? `@${rawHandle}` : "@",
      description: "",
      city_hashtag: "#کاشمر",
      occupation: "",
      violation: "ترویج ابتذال",
      action_request: "درخواست مسدودی سیم کارت",
      profile_url: fallbackUrl,
      hashtags: ["#ابتذال", "#خراسان_رضوی", "#شهرستان_کاشمر"],
    };
  };

  const updateTemplateField = (
    item: ImageAnalysisItem,
    key: keyof CulturalSocialTemplateFields,
    value: string | string[],
  ) => {
    const current = getEffectiveTemplateFields(item);
    const updated: CulturalSocialTemplateFields = {
      ...current,
      [key]: value,
    };
    setTemplateOverrides((prev) => ({
      ...prev,
      [item.file_id]: updated,
    }));
  };

  const handleCopyTemplate = async (copyId: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedKey(copyId);
      setTimeout(() => {
        setCopiedKey((prev) => (prev === copyId ? null : prev));
      }, 2200);
    } catch {
      // Clipboard fallback
    }
  };

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

    const engineFaLabel =
      selectedOcrEngine === "paddleocr"
        ? "موتور بومی پدل (PaddleOCR)"
        : selectedOcrEngine === "hybrid"
          ? "موتور ترکیبی هوشمند (پدل + تسراکت)"
          : "موتور تسراکت ۵";

    setIsAnalyzing(true);
    setErrorMessage("");
    setStatusMessage(
      `در حال تفکیک نوع عکس (اسکرین‌شات/دوربین/سوژه)، پوشه‌بندی شخصی و شناسه آی‌دی، تحلیل ۱۲ سرفصل موضوعی، استخراج مشخصات انفرادی و بررسی موارد مجرمانه با ${engineFaLabel} برای ${digits(validImages.length)} تصویر…`,
    );

    try {
      const folderTitle =
        detectedFolder || (fromFolderPicker ? "پوشهٔ اسکرین‌شات‌ها و تصاویر انتخابی" : "مجموعه تصاویر انتخابی");
      const response = await ArchiveApiClient.analyzeImageFolder(
        validImages,
        folderTitle,
        instagramSourceUrl.trim() || undefined,
        selectedOcrEngine,
      );
      setAnalysisReport(response);
      setTemplateOverrides({});
      setAccountFilter("ALL");
      setTopicFilter("ALL");
      setSourceTypeFilter("ALL");
      setStatusMessage(
        `تحلیل چندبعدی ${digits(response.total_images)} تصویر در «${response.folder_name}» (نوع عکس، پوشهٔ شخصی، ۱۲ سرفصل موضوعی، مشخصات انفرادی و بررسی حقوقی و قضایی) با موفقیت تکمیل شد.`,
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
      setErrorMessage("این عملیات نیازمند اتصال به سرویس محلی ساهر است.");
      return;
    }

    setIsAnalyzing(true);
    setErrorMessage("");
    setStatusMessage(
      `در حال دسته‌بندی چندبعدی (نوع عکس، پوشهٔ شخصی و آیدی، ۱۲ سرفصل موضوعی، مشخصات انفرادی و بررسی حقوقی و قضایی) روی ${digits(existingImageFiles.length)} تصویر موجود در کتابخانه…`,
    );

    try {
      const ids = existingImageFiles.map((f) => f.id);
      const response = await ArchiveApiClient.analyzeExistingImages(
        ids,
        customFolderName.trim() || "تصاویر و اسکرین‌شات‌های آرشیو کتابخانه",
        instagramSourceUrl.trim() || undefined,
        selectedOcrEngine,
      );
      setAnalysisReport(response);
      setTemplateOverrides({});
      setAccountFilter("ALL");
      setTopicFilter("ALL");
      setSourceTypeFilter("ALL");
      setStatusMessage(
        `دسته‌بندی مجزای ${digits(response.total_images)} تصویر کتابخانه تکمیل شد و آمادهٔ دریافت خروجی فارسی Word (.docx) است.`,
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
      const fileIds = displayedItems.map((item) => item.file_id);
      const overridesPayload: Record<string, Record<string, unknown>> = {};
      for (const item of displayedItems) {
        const cat = item.thematic_category || item.detected_topic;
        if (item.template_applicable || cat === "فرهنگی" || cat === "اجتماعی") {
          overridesPayload[item.file_id] = { ...getEffectiveTemplateFields(item) };
        }
      }
      const blob = await ArchiveApiClient.downloadImagesWordReport(
        fileIds,
        analysisReport.folder_name,
        {
          sourceUrl: instagramSourceUrl.trim() || undefined,
          templateOverridesByFile: overridesPayload,
        },
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
      const cat = item.thematic_category || item.detected_topic;
      const overridesPayload: Record<string, Record<string, unknown>> = {};
      if (item.template_applicable || cat === "فرهنگی" || cat === "اجتماعی") {
        overridesPayload[item.file_id] = { ...getEffectiveTemplateFields(item) };
      }
      const blob = await ArchiveApiClient.downloadImagesWordReport([item.file_id], item.title, {
        sourceUrl: instagramSourceUrl.trim() || undefined,
        templateOverridesByFile: overridesPayload,
      });
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
    ? analysisReport.items.filter((i) => {
        const itemAcc = i.account_label || "بدون نام کاربری / آیدی مشخص";
        const itemCat = i.thematic_category || i.detected_topic;
        const itemSrc = i.capture_source_category || "اسکرین‌شات موبایل / شبکهٔ اجتماعی";
        const passAccount = accountFilter === "ALL" || itemAcc === accountFilter;
        const passTopic = topicFilter === "ALL" || itemCat === topicFilter;
        const passSource = sourceTypeFilter === "ALL" || itemSrc === sourceTypeFilter;
        return passAccount && passTopic && passSource;
      })
    : [];

  const accountBreakdown = analysisReport?.account_breakdown || {};
  const accountCategoryTree = analysisReport?.account_category_tree || {};
  const sourceTypeBreakdown = analysisReport?.source_type_breakdown || {};
  const locationBreakdown = analysisReport?.location_breakdown || {};

  return (
    <section className="batch-analysis-container" data-testid="batch-image-analysis-view">
      {/* 1. Folder & Multi-Image Input Panel */}
      <div className="batch-upload-panel">
        <div className="batch-upload-header">
          <div>
            <h2>
              تحلیل هوشمند عکس‌ها و اسکرین‌شات‌ها (تفکیک نوع عکس، پوشهٔ شخصی و آیدی، ۱۲ سرفصل موضوعی، مشخصات انفرادی و بررسی حقوقی و قضایی)
            </h2>
            <p>
              پوشهٔ عکس‌ها یا اسکرین‌شات‌های خود را انتخاب کنید تا سامانهٔ ساهر هر تصویر را از نظر{" "}
              <strong>نوع عکس (اسکرین‌شات، عکس با دوربین، عکس سوژه، سند و نقشه)</strong>،{" "}
              <strong>پوشهٔ شخصی و شناسه آی‌دی روی عکس</strong>،{" "}
              <strong>موقعیت مکانی و مختصات جغرافیایی (GPS)</strong>،{" "}
              <strong>۱۲ دسته‌بندی موضوعی</strong>،{" "}
              <strong>بررسی موارد مجرمانه بر اساس داده‌های حقوقی و قضایی</strong> و{" "}
              <strong>مشخصات انفرادی و شناسنامه‌ای</strong> تحلیل کرده و خروجی دقیق فارسی{" "}
              <strong>Word (.docx)</strong> تولید نماید:
            </p>
            <div className="taxonomy-reference-line" data-testid="thematic-categories-12-list">
              <strong>۱۲ سرفصل موضوعی پس از پوشه‌بندی شخصی: </strong>
              {THEMATIC_CATEGORIES_12.map((cat, idx) => (
                <React.Fragment key={cat}>
                  {idx > 0 && <span aria-hidden="true"> · </span>}
                  <span>{cat}</span>
                </React.Fragment>
              ))}
            </div>
          </div>
          <div className="batch-header-inputs">
            <div className="batch-folder-title-input">
              <label htmlFor="batch-folder-title">عنوان گزارش در سند Word (اختیاری):</label>
              <input
                id="batch-folder-title"
                type="text"
                placeholder="مثلاً: پروندهٔ تصاویر و اسکرین‌شات‌های رصد آبان ۱۴۰۵"
                value={customFolderName}
                disabled={isAnalyzing}
                onChange={(e) => setCustomFolderName(e.target.value)}
              />
            </div>
            <div className="batch-folder-title-input">
              <label htmlFor="batch-instagram-url">
                لینک اینستاگرام / آدرس اینترنتی صفحه (جهت تکمیل قوارهٔ فرهنگی و اجتماعی):
              </label>
              <input
                id="batch-instagram-url"
                data-testid="batch-instagram-url-input"
                type="url"
                dir="ltr"
                placeholder="https://www.instagram.com/mira_rjbpr?stkn=YzM4MWNpN3Y2a3Vy"
                value={instagramSourceUrl}
                disabled={isAnalyzing}
                onChange={(e) => setInstagramSourceUrl(e.target.value)}
              />
            </div>
            <div className="batch-folder-title-input">
              <label htmlFor="batch-ocr-engine-select">
                موتور تشخیص متن فارسی روی تصویر (OCR):
              </label>
              <select
                id="batch-ocr-engine-select"
                data-testid="batch-ocr-engine-select"
                value={selectedOcrEngine}
                disabled={isAnalyzing}
                onChange={(e) => setSelectedOcrEngine(e.target.value)}
              >
                <option value="paddleocr">
                  موتور بومی پدل (PaddleOCR · واژه‌نامهٔ فارسی و تشخیص حالت تیره)
                </option>
                <option value="hybrid">
                  موتور ترکیبی هوشمند (پدل + تسراکت ۵ · بالاترین دقت فارسی و انگلیسی)
                </option>
                <option value="tesseract">
                  موتور تسراکت ۵ (Tesseract LSTM · فارسی و انگلیسی)
                </option>
              </select>
            </div>
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
              <strong>انتخاب پوشهٔ کامل عکس‌ها و اسکرین‌شات‌ها (Folder)</strong>
              <small>
                دریافت خودکار تمام تصاویر پوشه، استخراج نام کاربری/آیدی، دسته‌بندی ۱۲گانه و تکمیل قوارهٔ فرهنگی/اجتماعی
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
              <strong>انتخاب چند اسکرین‌شات یا عکس به‌صورت هم‌زمان</strong>
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
                اجرای دسته‌بندی دومرحله‌ای (نام کاربری/آیدی ← ۱۲ سرفصل موضوعی) و دریافت خروجی Word
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

      {/* 2. Results & Two-Level Classification Section */}
      {analysisReport && (
        <div className="batch-results-section" data-testid="batch-analysis-results">
          <div className="batch-results-header">
            <div>
              <h3>
                نتیجهٔ دسته‌بندی چندبعدی: {analysisReport.folder_name} (
                <span className="tabular-nums">{digits(analysisReport.total_images)}</span> تصویر)
              </h3>
              {Object.keys(sourceTypeBreakdown).length > 0 && (
                <p className="batch-breakdown-line">
                  <strong>۱. تفکیک نوع عکس (اسکرین‌شات / عکس با دوربین / عکس سوژه / سند): </strong>
                  {Object.entries(sourceTypeBreakdown).map(([srcType, cnt], idx) => (
                    <React.Fragment key={srcType}>
                      {idx > 0 && <span aria-hidden="true"> · </span>}
                      <span>
                        {srcType} (<strong className="tabular-nums">{digits(cnt)}</strong>)
                      </span>
                    </React.Fragment>
                  ))}
                </p>
              )}
              {Object.keys(accountBreakdown).length > 0 && (
                <p className="batch-breakdown-line">
                  <strong>۲. پوشه‌بندی شخصی و شناسه آی‌دی روی عکس (اولویت اول): </strong>
                  {Object.entries(accountBreakdown).map(([acc, cnt], idx) => (
                    <React.Fragment key={acc}>
                      {idx > 0 && <span aria-hidden="true"> · </span>}
                      <span>
                        {acc} (<strong className="tabular-nums">{digits(cnt)}</strong>)
                      </span>
                    </React.Fragment>
                  ))}
                </p>
              )}
              <p className="batch-breakdown-line">
                <strong>۳. دسته‌بندی در ۱۲ سرفصل موضوعی پس از پوشه‌بندی شخصی (اولویت دوم): </strong>
                {Object.entries(analysisReport.topic_breakdown).map(([topic, cnt], idx) => (
                  <React.Fragment key={topic}>
                    {idx > 0 && <span aria-hidden="true"> · </span>}
                    <span>
                      {topic} (<strong className="tabular-nums">{digits(cnt)}</strong>)
                    </span>
                  </React.Fragment>
                ))}
              </p>
              {Object.keys(locationBreakdown).length > 0 && (
                <p className="batch-breakdown-line">
                  <strong>۴. تفکیک موقعیت مکانی و مختصات: </strong>
                  {Object.entries(locationBreakdown).map(([loc, cnt], idx) => (
                    <React.Fragment key={loc}>
                      {idx > 0 && <span aria-hidden="true"> · </span>}
                      <span>
                        {loc} (<strong className="tabular-nums">{digits(cnt)}</strong>)
                      </span>
                    </React.Fragment>
                  ))}
                </p>
              )}
            </div>

            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              {onOpenIdentityProfiles && (
                <button
                  type="button"
                  className="ghost"
                  onClick={onOpenIdentityProfiles}
                  data-testid="goto-identity-profiles-btn"
                >
                  🪪 صفحهٔ مشخصات انفرادی و شناسنامه‌ای
                </button>
              )}
              <button
                type="button"
                className="primary export-word-cta"
                data-testid="download-full-word-report-btn"
                disabled={isExportingWord || displayedItems.length === 0}
                onClick={handleDownloadFullWordReport}
              >
                <span>⬇</span>
                <span>
                  {isExportingWord
                    ? "در حال صفحه‌بندی و ساخت سند فارسی Word…"
                    : `دریافت گزارش تحلیل کامل در قالب Word (.docx)`}
                </span>
              </button>
            </div>
          </div>

          {/* Hierarchical Priority-1 (Personal Folder / Account ID) -> Priority-2 (12 Categories) Tree Panel */}
          {Object.keys(accountCategoryTree).length > 0 && (
            <div className="hierarchy-tree-panel" data-testid="account-category-hierarchy-panel">
              <h4>
                ساختار درختی دسته‌بندی (سطح اول: پوشه‌بندی شخصی و شناسه آی‌دی ← سطح دوم: ۱۲ سرفصل موضوعی)
              </h4>
              <div className="hierarchy-account-grid">
                {Object.entries(accountCategoryTree).map(([accLabel, subCats]) => {
                  const totalForAcc = accountBreakdown[accLabel] || 0;
                  const isSelectedAcc = accountFilter === accLabel;
                  return (
                    <div
                      key={accLabel}
                      className={`hierarchy-account-card ${isSelectedAcc ? "selected" : ""}`}
                    >
                      <div className="hierarchy-account-header">
                        <button
                          type="button"
                          className="hierarchy-account-btn"
                          onClick={() => {
                            setAccountFilter(isSelectedAcc ? "ALL" : accLabel);
                            setTopicFilter("ALL");
                          }}
                        >
                          <strong dir="auto">{accLabel}</strong>
                          <span className="tabular-nums">{digits(totalForAcc)} تصویر</span>
                        </button>
                      </div>
                      <div className="hierarchy-subcats">
                        {Object.entries(subCats).map(([catName, cnt]) => {
                          const isSelectedBoth =
                            accountFilter === accLabel && topicFilter === catName;
                          return (
                            <button
                              key={catName}
                              type="button"
                              className={`hierarchy-subcat-btn ${isSelectedBoth ? "active" : ""}`}
                              onClick={() => {
                                setAccountFilter(accLabel);
                                setTopicFilter(isSelectedBoth ? "ALL" : catName);
                              }}
                            >
                              <span>{catName}</span>
                              <strong className="tabular-nums">({digits(cnt)})</strong>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Capture Source Type Filter Tabs (اسکرین‌شات / عکس با دوربین / عکس سوژه / سند) */}
          {Object.keys(sourceTypeBreakdown).length > 0 && (
            <div
              className="batch-filter-bar"
              role="tablist"
              aria-label="فیلتر بر اساس نوع عکس (اسکرین‌شات، عکس با دوربین، عکس سوژه)"
            >
              <span className="filter-bar-label">نوع عکس (اسکرین‌شات / دوربین / سوژه):</span>
              <button
                type="button"
                role="tab"
                aria-selected={sourceTypeFilter === "ALL"}
                className={sourceTypeFilter === "ALL" ? "active" : ""}
                onClick={() => setSourceTypeFilter("ALL")}
              >
                همهٔ انواع عکس ({digits(analysisReport.total_images)})
              </button>
              {Object.entries(sourceTypeBreakdown).map(([srcType, count]) => (
                <button
                  key={srcType}
                  type="button"
                  role="tab"
                  aria-selected={sourceTypeFilter === srcType}
                  className={sourceTypeFilter === srcType ? "active" : ""}
                  onClick={() => setSourceTypeFilter(srcType)}
                >
                  {srcType} ({digits(count)})
                </button>
              ))}
            </div>
          )}

          {/* Priority 1 Filter Tabs: Username & ID */}
          {Object.keys(accountBreakdown).length > 1 && (
            <div
              className="batch-filter-bar"
              role="tablist"
              aria-label="فیلتر اولویت اول بر اساس پوشهٔ شخصی و شناسه آیدی"
            >
              <span className="filter-bar-label">پوشهٔ شخصی / شناسه آی‌دی:</span>
              <button
                type="button"
                role="tab"
                aria-selected={accountFilter === "ALL"}
                className={accountFilter === "ALL" ? "active" : ""}
                onClick={() => setAccountFilter("ALL")}
              >
                همهٔ اکانت‌ها ({digits(analysisReport.total_images)})
              </button>
              {Object.entries(accountBreakdown).map(([acc, count]) => (
                <button
                  key={acc}
                  type="button"
                  role="tab"
                  aria-selected={accountFilter === acc}
                  className={accountFilter === acc ? "active" : ""}
                  onClick={() => setAccountFilter(acc)}
                >
                  {acc} ({digits(count)})
                </button>
              ))}
            </div>
          )}

          {/* Priority 2 Filter Tabs: 12 Thematic Categories */}
          <div
            className="batch-filter-bar"
            role="tablist"
            aria-label="فیلتر اولویت دوم بر اساس ۱۲ سرفصل موضوعی"
          >
            <span className="filter-bar-label">سرفصل موضوعی ۱۲گانه:</span>
            <button
              type="button"
              role="tab"
              aria-selected={topicFilter === "ALL"}
              className={topicFilter === "ALL" ? "active" : ""}
              onClick={() => setTopicFilter("ALL")}
            >
              همهٔ موضوعات ({digits(analysisReport.total_images)})
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

          {/* Per-Image Separate Analysis Cards */}
          <div className="batch-items-list">
            {displayedItems.map((item, idx) => {
              const accLabel = item.account_label || "بدون نام کاربری / آیدی مشخص";
              const catLabel = item.thematic_category || item.detected_topic;
              const isCulturalOrSocial =
                item.template_applicable === true ||
                catLabel === "فرهنگی" ||
                catLabel === "اجتماعی";
              const tplFields = getEffectiveTemplateFields(item);
              const culturalTemplateText = formatCulturalTemplateClient(tplFields);
              const socialTemplateText = formatSocialBlockingTemplateClient(tplFields);
              const formattedTemplate = formatCulturalSocialTemplateClient(tplFields, catLabel);

              return (
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

                    {/* Multi-Axis Classification Row: Personal Folder, ID, 12 Category, Source Type, Subject, Location & GPS */}
                    <div className="batch-item-meta tabular-nums">
                      <span data-testid={`item-account-${idx + 1}`}>
                        <strong>پوشهٔ شخصی / آیدی (سطح ۱):</strong>{" "}
                        <bdi>{item.personal_folder || accLabel}</bdi>
                      </span>
                      <span aria-hidden="true">·</span>
                      <span data-testid={`item-category-${idx + 1}`}>
                        <strong>سرفصل موضوعی ۱۲گانه (سطح ۲):</strong> {catLabel}
                      </span>
                      <span aria-hidden="true">·</span>
                      <span>
                        <strong>نوع عکس:</strong>{" "}
                        {item.capture_source_category || "اسکرین‌شات موبایل / شبکهٔ اجتماعی"}
                      </span>
                      <span aria-hidden="true">·</span>
                      <span>
                        <strong>نوع سوژه:</strong>{" "}
                        {item.subject_classification || item.image_nature}
                      </span>
                      <span aria-hidden="true">·</span>
                      <span>
                        <strong>موقعیت مکانی:</strong>{" "}
                        {item.location_name || "موقعیت مکانی ثبت‌نشده"}
                        {item.gps_coordinates ? ` (مختصات: ${item.gps_coordinates})` : ""}
                      </span>
                      <span aria-hidden="true">·</span>
                      <span>
                        ابعاد: {digits(item.width)}×{digits(item.height)} ({item.orientation})
                      </span>
                      <span aria-hidden="true">·</span>
                      <span>
                        کلمات استخراج‌شده: {digits(item.word_count)}
                        {item.ocr_confidence != null
                          ? ` (دقت تشخیص متن: ${digits(Math.round(item.ocr_confidence))}٪)`
                          : ""}
                      </span>
                    </div>

                    <p className="batch-item-summary">{item.analysis_summary}</p>

                    {/* Legal & Judicial Criminal Assessment Box */}
                    {item.criminal_assessment && (
                      <div
                        className="batch-item-ocr-box"
                        style={{
                          borderRight: item.criminal_assessment.has_criminal_indicator
                            ? "4px solid #b42318"
                            : "4px solid var(--accent)",
                          marginBottom: "10px",
                        }}
                        data-testid={`criminal-assessment-box-${idx + 1}`}
                      >
                        <div
                          style={{
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "center",
                            flexWrap: "wrap",
                            gap: "8px",
                            marginBottom: "6px",
                          }}
                        >
                          <strong>
                            ⚖ تحلیل دقیق عنوان و نوشتهٔ عکس و بررسی موارد مجرمانه (حقوقی و قضایی):
                          </strong>
                          <span
                            className="tag"
                            style={{
                              background: item.criminal_assessment.has_criminal_indicator
                                ? "#fef3f2"
                                : "var(--bg)",
                              color: item.criminal_assessment.has_criminal_indicator
                                ? "#b42318"
                                : "var(--text)",
                              fontWeight: 700,
                            }}
                          >
                            سطح ریسک: {item.criminal_assessment.risk_level}
                          </span>
                        </div>
                        <p style={{ margin: "4px 0", fontSize: "0.9rem" }}>
                          {item.criminal_assessment.judicial_summary}
                        </p>
                        {item.criminal_assessment.criminal_charges &&
                          item.criminal_assessment.criminal_charges.length > 0 && (
                            <p style={{ margin: "4px 0", fontSize: "0.88rem" }}>
                              <strong>عناوین اتهامی و مجرمانه: </strong>
                              {item.criminal_assessment.criminal_charges.join(" ؛ ")}
                            </p>
                          )}
                        {item.criminal_assessment.legal_articles &&
                          item.criminal_assessment.legal_articles.length > 0 && (
                            <p style={{ margin: "4px 0", fontSize: "0.88rem" }}>
                              <strong>مواد قانونی منطبق: </strong>
                              {item.criminal_assessment.legal_articles.join(" ؛ ")}
                            </p>
                          )}
                        {item.criminal_assessment.recommended_action && (
                          <p style={{ margin: "4px 0", fontSize: "0.88rem" }}>
                            <strong>اقدام پیشنهادی قضایی و ضابطین: </strong>
                            {item.criminal_assessment.recommended_action}
                          </p>
                        )}
                      </div>
                    )}

                    {/* Personal & Civil Identity Specifications Box */}
                    {item.personal_identity && item.personal_identity.has_identity_data && (
                      <div
                        className="batch-item-ocr-box"
                        style={{ marginBottom: "10px" }}
                        data-testid={`personal-identity-box-${idx + 1}`}
                      >
                        <div
                          style={{
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "center",
                            flexWrap: "wrap",
                            gap: "8px",
                            marginBottom: "6px",
                          }}
                        >
                          <strong>
                            🪪 مشخصات انفرادی، شناسنامه‌ای، شماره موبایل و آدرس مستخرج از تصویر:
                          </strong>
                          {onOpenIdentityProfiles && (
                            <button
                              type="button"
                              className="secondary-btn"
                              onClick={onOpenIdentityProfiles}
                            >
                              مشاهده در صفحهٔ مشخصات انفرادی ←
                            </button>
                          )}
                        </div>
                        <div
                          style={{
                            display: "grid",
                            gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))",
                            gap: "6px 14px",
                            fontSize: "0.88rem",
                          }}
                        >
                          <div>
                            <strong>نام و نام خانوادگی: </strong>
                            {item.personal_identity.full_name || "ثبت‌نشده"}
                          </div>
                          <div>
                            <strong>نام پدر: </strong>
                            {item.personal_identity.father_name || "ثبت‌نشده"}
                          </div>
                          <div>
                            <strong>کد ملی: </strong>
                            {item.personal_identity.national_id
                              ? digits(item.personal_identity.national_id)
                              : "ثبت‌نشده"}
                          </div>
                          <div>
                            <strong>شماره شناسنامه: </strong>
                            {item.personal_identity.birth_certificate_no
                              ? digits(item.personal_identity.birth_certificate_no)
                              : "ثبت‌نشده"}
                          </div>
                          <div>
                            <strong>شماره موبایل / تلفن همراه: </strong>
                            {item.personal_identity.mobile_phone
                              ? digits(item.personal_identity.mobile_phone)
                              : "ثبت‌نشده"}
                          </div>
                          <div>
                            <strong>تلفن ثابت: </strong>
                            {item.personal_identity.landline_phone
                              ? digits(item.personal_identity.landline_phone)
                              : "ثبت‌نشده"}
                          </div>
                          <div>
                            <strong>شهر و آدرس: </strong>
                            {[
                              item.personal_identity.province,
                              item.personal_identity.city,
                              item.personal_identity.address,
                            ]
                              .filter(Boolean)
                              .join(" ، ") || "ثبت‌نشده"}
                          </div>
                          <div>
                            <strong>آیدی فضای مجازی: </strong>
                            <span dir="ltr">
                              {item.personal_identity.account_handle || "—"}
                            </span>
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Cultural & Social Structured Template Box — Strictly ONLY for «فرهنگی» and «اجتماعی» */}
                    {isCulturalOrSocial && (
                      <div
                        className="cultural-social-template-box"
                        data-testid={`cultural-social-template-${idx + 1}`}
                      >
                        <div className="cultural-social-template-header">
                          <strong>
                            قواره‌های تکمیل‌شده ویژهٔ دسته‌بندی «{catLabel}» (تکمیل خودکار از اسکرین‌شات‌ها و لینک اینستاگرام):
                          </strong>
                          <div className="template-copy-actions">
                            <button
                              type="button"
                              className="secondary-btn copy-template-btn"
                              data-testid={`copy-social-template-btn-${idx + 1}`}
                              onClick={() =>
                                handleCopyTemplate(`${item.file_id}-social`, socialTemplateText)
                              }
                            >
                              {copiedKey === `${item.file_id}-social`
                                ? "کپی شد ✓"
                                : "⧉ کپی قوارهٔ اجتماعی (#مسدودسازی)"}
                            </button>
                            <button
                              type="button"
                              className="secondary-btn copy-template-btn"
                              data-testid={`copy-cultural-template-btn-${idx + 1}`}
                              onClick={() =>
                                handleCopyTemplate(`${item.file_id}-cultural`, culturalTemplateText)
                              }
                            >
                              {copiedKey === `${item.file_id}-cultural`
                                ? "کپی شد ✓"
                                : "⧉ کپی قوارهٔ فرهنگی (#ابتذال)"}
                            </button>
                            <button
                              type="button"
                              className="secondary-btn copy-template-btn"
                              data-testid={`copy-template-btn-${idx + 1}`}
                              onClick={() =>
                                handleCopyTemplate(item.file_id, formattedTemplate)
                              }
                            >
                              {copiedKey === item.file_id ? "کپی شد ✓" : "⧉ کپی هر دو قواره"}
                            </button>
                          </div>
                        </div>

                        <div className="cultural-social-fields-grid">
                          <label>
                            <span>نام و نام خانوادگی:</span>
                            <input
                              type="text"
                              value={tplFields.full_name}
                              placeholder="استخراج از اسکرین‌شات یا ورود دستی"
                              onChange={(e) =>
                                updateTemplateField(item, "full_name", e.target.value)
                              }
                            />
                          </label>
                          <label>
                            <span>کدملی:</span>
                            <input
                              type="text"
                              dir="ltr"
                              value={tplFields.national_id}
                              placeholder="کدملی ۱۰ رقمی"
                              onChange={(e) =>
                                updateTemplateField(item, "national_id", e.target.value)
                              }
                            />
                          </label>
                          <label>
                            <span>شماره تماس / حساب:</span>
                            <input
                              type="text"
                              dir="ltr"
                              value={tplFields.phone_number}
                              placeholder="09..."
                              onChange={(e) =>
                                updateTemplateField(item, "phone_number", e.target.value)
                              }
                            />
                          </label>
                          <label>
                            <span>تاریخ ارشاد:</span>
                            <input
                              type="text"
                              dir="ltr"
                              value={tplFields.guidance_date || ""}
                              placeholder="1405/08/..."
                              onChange={(e) =>
                                updateTemplateField(item, "guidance_date", e.target.value)
                              }
                            />
                          </label>
                          <label>
                            <span>آیدی عددی:</span>
                            <input
                              type="text"
                              dir="ltr"
                              value={tplFields.numeric_id || ""}
                              placeholder="شناسه عددی اکانت"
                              onChange={(e) =>
                                updateTemplateField(item, "numeric_id", e.target.value)
                              }
                            />
                          </label>
                          <label>
                            <span>آیدی صفحه (@):</span>
                            <input
                              type="text"
                              dir="ltr"
                              value={tplFields.account_handle || ""}
                              placeholder="@mira_rjbpr"
                              onChange={(e) =>
                                updateTemplateField(item, "account_handle", e.target.value)
                              }
                            />
                          </label>
                          <label>
                            <span>آدرس اینترنتی / لینک اینستاگرام (URL):</span>
                            <input
                              type="url"
                              dir="ltr"
                              value={tplFields.profile_url}
                              placeholder="https://www.instagram.com/..."
                              onChange={(e) =>
                                updateTemplateField(item, "profile_url", e.target.value)
                              }
                            />
                          </label>
                          <label>
                            <span>شغل:</span>
                            <input
                              type="text"
                              value={tplFields.occupation}
                              placeholder="شغل / فعالیت صفحه"
                              onChange={(e) =>
                                updateTemplateField(item, "occupation", e.target.value)
                              }
                            />
                          </label>
                          <label>
                            <span>تخلف:</span>
                            <input
                              type="text"
                              value={tplFields.violation}
                              onChange={(e) =>
                                updateTemplateField(item, "violation", e.target.value)
                              }
                            />
                          </label>
                          <label>
                            <span>توضیحات (قوارهٔ اجتماعی):</span>
                            <input
                              type="text"
                              value={tplFields.description || ""}
                              placeholder="توضیحات تکمیلی"
                              onChange={(e) =>
                                updateTemplateField(item, "description", e.target.value)
                              }
                            />
                          </label>
                          <label>
                            <span>هشتگ شهر (قوارهٔ اجتماعی):</span>
                            <input
                              type="text"
                              value={tplFields.city_hashtag || "#کاشمر"}
                              onChange={(e) =>
                                updateTemplateField(item, "city_hashtag", e.target.value)
                              }
                            />
                          </label>
                          <label>
                            <span>هشتگ‌های قوارهٔ فرهنگی (با فاصله):</span>
                            <input
                              type="text"
                              value={(tplFields.hashtags || []).join(" ")}
                              onChange={(e) =>
                                updateTemplateField(
                                  item,
                                  "hashtags",
                                  e.target.value
                                    .split(/\s+/)
                                    .map((s) => s.trim())
                                    .filter(Boolean),
                                )
                              }
                            />
                          </label>
                        </div>

                        <div
                          className="dual-templates-preview-grid"
                          data-testid={`template-preview-text-${idx + 1}`}
                        >
                          <div className="single-template-column">
                            <span className="single-template-badge">
                              قوارهٔ دسته‌بندی اجتماعی (#مسدودسازی #اینستاگرام)
                            </span>
                            <pre
                              className="cultural-social-template-preview"
                              data-testid={`social-template-preview-${idx + 1}`}
                            >
                              {socialTemplateText}
                            </pre>
                          </div>
                          <div className="single-template-column">
                            <span className="single-template-badge">
                              قوارهٔ دسته‌بندی فرهنگی (ترویج ابتذال / مسدودی سیم کارت)
                            </span>
                            <pre
                              className="cultural-social-template-preview"
                              data-testid={`cultural-template-preview-${idx + 1}`}
                            >
                              {culturalTemplateText}
                            </pre>
                          </div>
                        </div>
                      </div>
                    )}

                    {item.extracted_text && (
                      <div className="batch-item-ocr-box">
                        <strong>متن خوانده‌شده از داخل این تصویر (OCR):</strong>
                        <p>{item.extracted_text}</p>
                      </div>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
        </div>
      )}
    </section>
  );
}
