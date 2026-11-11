import React, { useState } from "react";

interface ImportDialogProps {
  onClose: () => void;
  onImport: (files: FileList, topic?: string) => Promise<void>;
  maxUploadBytes?: number;
}

export function ImportDialog({
  onClose,
  onImport,
  maxUploadBytes = 25 * 1024 * 1024,
}: ImportDialogProps) {
  const [isUploading, setIsUploading] = useState(false);
  const [selectedTopic, setSelectedTopic] = useState("کار");
  const [errorMessage, setErrorMessage] = useState("");
  const [folderMode, setFolderMode] = useState(false);

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const fileList = e.target.files;
    if (!fileList || fileList.length === 0) return;
    try {
      setIsUploading(true);
      setErrorMessage("");
      await onImport(fileList, selectedTopic);
      onClose();
    } catch (err: any) {
      setErrorMessage(err?.message || "خطا در واردسازی و اعتبارسنجی فایل در سرویس بک‌اند.");
      e.target.value = "";
    } finally {
      setIsUploading(false);
    }
  };

  const maxMb = Math.round(maxUploadBytes / (1024 * 1024)).toLocaleString("fa-IR");

  return (
    <div className="overlay" onClick={() => !isUploading && onClose()}>
      <section
        className="importdialog"
        role="dialog"
        aria-modal="true"
        aria-label="افزودن فایل"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="dialoghead">
          <h2>واردسازی و ثبت کار پردازشی پایدار در ساهر</h2>
          <button
            className="close"
            aria-label="بستن"
            disabled={isUploading}
            onClick={onClose}
          >
            ×
          </button>
        </div>
        <p>
          فایل‌ها در آرشیو محلی ذخیره می‌شوند و استخراج متن در پس‌زمینه انجام می‌شود. هنگام انتخاب پوشه، نام پوشه‌ها و زیرپوشه‌ها نیز در شناسنامهٔ اسناد حفظ می‌شود.
        </p>

        <div className="import-topic-group">
          <label htmlFor="import-topic-select" className="import-topic-label">
            موضوع پیش‌فرض فایل ورودی:
          </label>
          <select
            id="import-topic-select"
            aria-label="موضوع فایل ورودی"
            className="full-width-select"
            value={selectedTopic}
            disabled={isUploading}
            onChange={(e) => setSelectedTopic(e.target.value)}
          >
            {["کار", "طراحی", "معماری", "آموزش", "فناوری", "زندگی", "پژوهش"].map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>

        <label><input type="checkbox" checked={folderMode} disabled={isUploading}
          onChange={event => setFolderMode(event.target.checked)} /> انتخاب یک پوشه با زیرپوشه‌ها</label>
        <label className={isUploading ? "dropzone uploading" : "dropzone"}>
          <span>{isUploading ? "◌" : "＋"}</span>
          <strong>
            {isUploading
              ? "در حال ارسال، اعتبارسنجی باینری و ثبت در صف پردازش…"
              : folderMode ? "انتخاب پوشه از دستگاه" : "انتخاب فایل از دستگاه"}
          </strong>
          <small>
            فرمت‌های مجاز: TXT, MD, CSV, JSON, PDF, DOCX, PNG, JPG, WEBP, BMP (حداکثر {maxMb} مگابایت)
          </small>
          <input
            key={String(folderMode)}
            {...(folderMode ? { webkitdirectory: "", directory: "" } : {})}
            type="file"
            multiple
            accept=".txt,.md,.csv,.json,.log,.pdf,.docx,.png,.jpg,.jpeg,.webp,.bmp"
            disabled={isUploading}
            onChange={handleFileChange}
          />
        </label>

        {errorMessage && (
          <div
            role="alert"
            data-testid="import-error-alert"
            className="import-error-alert"
          >
            <strong>خطا در واردسازی:</strong> {errorMessage}
          </div>
        )}

        <div className="evidence">
          توجه: فایل‌های تکراری (دارای هش SHA-256 یکسان)، فایل‌های آسیب‌دیده یا دارای پسوند جعلی به‌طور خودکار توسط سرویس بک‌اند رد می‌شوند.
        </div>
      </section>
    </div>
  );
}
