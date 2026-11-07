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
          <h2>واردسازی و بایگانی پایدار فایل در ساهر</h2>
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
          فایل انتخابی پس از بررسی امضای باینری و محاسبهٔ هش SHA-256، در مخزن محلی ذخیره و در پایگاه‌داده SQLite نمایه می‌شود.
        </p>

        <div style={{ marginBottom: "0.75rem" }}>
          <label htmlFor="import-topic-select" style={{ display: "block", marginBottom: "0.35rem", fontSize: "0.9rem" }}>
            موضوع پیش‌فرض فایل ورودی:
          </label>
          <select
            id="import-topic-select"
            aria-label="موضوع فایل ورودی"
            value={selectedTopic}
            disabled={isUploading}
            onChange={(e) => setSelectedTopic(e.target.value)}
            style={{ width: "100%" }}
          >
            {["کار", "طراحی", "معماری", "آموزش", "فناوری", "زندگی", "پژوهش"].map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>

        <label
          className="dropzone"
          style={{
            cursor: isUploading ? "wait" : "pointer",
            opacity: isUploading ? 0.7 : 1,
          }}
        >
          <span>{isUploading ? "◌" : "＋"}</span>
          <strong>
            {isUploading
              ? "در حال ارسال، اعتبارسنجی باینری و استخراج متن در بک‌اند…"
              : "انتخاب فایل از دستگاه"}
          </strong>
          <small>
            فرمت‌های مجاز: TXT, MD, CSV, JSON, PDF, DOCX, PNG, JPG, WEBP, BMP (حداکثر {maxMb} مگابایت)
          </small>
          <input
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
            style={{
              color: "#a82010",
              background: "#fdecea",
              border: "1px solid #f5c2c0",
              borderRadius: "8px",
              padding: "0.75rem",
              marginTop: "0.75rem",
              fontSize: "0.9rem",
            }}
          >
            <strong>خطا در واردسازی:</strong> {errorMessage}
          </div>
        )}

        <div className="evidence" style={{ marginTop: "0.75rem" }}>
          توجه: فایل‌های تکراری (دارای هش SHA-256 یکسان)، فایل‌های آسیب‌دیده یا دارای پسوند جعلی به‌طور خودکار توسط سرویس بک‌اند رد می‌شوند.
        </div>
      </section>
    </div>
  );
}
