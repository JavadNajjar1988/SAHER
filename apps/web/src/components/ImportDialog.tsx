import React, { useState } from "react";

interface ImportDialogProps {
  onClose: () => void;
  onImport: (files: FileList) => Promise<void>;
}

export function ImportDialog({ onClose, onImport }: ImportDialogProps) {
  const [isUploading, setIsUploading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || e.target.files.length === 0) return;
    try {
      setIsUploading(true);
      setErrorMessage("");
      await onImport(e.target.files);
      onClose();
    } catch (err: any) {
      setErrorMessage(err?.message || "خطا در واردسازی فایل");
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="overlay" onClick={onClose}>
      <section
        className="importdialog"
        role="dialog"
        aria-modal="true"
        aria-label="افزودن فایل"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="dialoghead">
          <h2>بایگانی پایدار فایل‌ها در ساهر</h2>
          <button
            className="close"
            aria-label="بستن"
            onClick={onClose}
          >
            ×
          </button>
        </div>
        <p>فایل‌های مورد نظر (متنی، PDF، Word یا تصویر) را انتخاب کنید تا با استخراج خودکار به آرشیو محلی اضافه شوند.</p>
        <label className="dropzone" style={{ cursor: isUploading ? "wait" : "pointer", opacity: isUploading ? 0.7 : 1 }}>
          <span>{isUploading ? "◌" : "＋"}</span>
          <strong>{isUploading ? "در حال ذخیره‌سازی و استخراج محتوا..." : "انتخاب فایل از دستگاه"}</strong>
          <small>سند متنی، PDF، DOCX، تصویر یا اسکرین‌شات</small>
          <input
            type="file"
            multiple
            disabled={isUploading}
            onChange={handleFileChange}
          />
        </label>
        {errorMessage && (
          <p style={{ color: "var(--crimson, #b00020)", marginTop: "0.5rem" }}>
            {errorMessage}
          </p>
        )}
        <div className="evidence">
          فایل‌های انتخابی شما در فضای ذخیره‌سازی محلی کپی می‌شوند، شناسهٔ یکتا و هش SHA-256 آن‌ها ثبت شده و متن آن‌ها به نمایهٔ جست‌وجوی FTS افزوده می‌شود.
        </div>
      </section>
    </div>
  );
}
