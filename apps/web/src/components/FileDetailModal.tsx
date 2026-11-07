import React, { useState } from "react";
import { FileItem, FileUpdatePayload } from "../types/archive";
import { Preview } from "./Preview";

interface FileDetailModalProps {
  selected: FileItem;
  onClose: () => void;
  onUpdate: (fileId: string, payload: FileUpdatePayload) => Promise<void>;
  onAddTag: (fileId: string, tag: string) => Promise<void>;
  onRemoveTag: (fileId: string, tag: string) => Promise<void>;
  isDemoMode?: boolean;
}

export function FileDetailModal({
  selected,
  onClose,
  onUpdate,
  onAddTag,
  onRemoveTag,
  isDemoMode = false,
}: FileDetailModalProps) {
  const [topicDraft, setTopicDraft] = useState(selected.topic);
  const [tagInput, setTagInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const [errorMsg, setErrorMsg] = useState("");

  const handleTopicChange = async (newTopic: string) => {
    setTopicDraft(newTopic);
    setNotice("");
    setErrorMsg("");
    setSaving(true);
    try {
      await onUpdate(selected.id, { topic: newTopic });
      setNotice(
        isDemoMode
          ? "موضوع در حافظهٔ نمایشی تغییر کرد."
          : "موضوع فایل در پایگاه‌داده SQLite ثبت شد.",
      );
    } catch (err: any) {
      setTopicDraft(selected.topic);
      setErrorMsg(err?.message || "خطا در ثبت موضوع فایل.");
    } finally {
      setSaving(false);
    }
  };

  const handleConfirmReview = async () => {
    setNotice("");
    setErrorMsg("");
    setSaving(true);
    try {
      await onUpdate(selected.id, { topic: topicDraft, status: "آماده" });
      setNotice(
        isDemoMode
          ? "تأیید بازبینی در حالت نمایشی ثبت شد."
          : "تأیید و اصلاحات شما در پایگاه‌داده SQLite با موفقیت ثبت شد.",
      );
    } catch (err: any) {
      setErrorMsg(err?.message || "خطا در ثبت تأیید بازبینی.");
    } finally {
      setSaving(false);
    }
  };

  const extractionStatusLabel: Record<string, string> = {
    extracted: "استخراج مستقیم متن انجام شده",
    pending_ocr: "در انتظار OCR / تحلیل دیداری (بدون لایه متنی)",
    empty: "فاقد متن قابل استخراج",
    unsupported: "فرمت فاقد استخراج متنی",
    failed: "خطا در استخراج متن",
  };

  return (
    <div className="overlay" onClick={onClose}>
      <section
        className="detail"
        role="dialog"
        aria-modal="true"
        aria-label="جزئیات فایل"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="dialoghead">
          <div>
            <small>جزئیات فایل و بایگانی</small>
            <h2>{selected.title}</h2>
          </div>
          <button
            className="close"
            aria-label="بستن جزئیات"
            onClick={onClose}
          >
            ×
          </button>
        </div>
        <div className={`preview large ${selected.color}`}>
          <Preview item={selected} />
        </div>
        <div className="filemeta-row" style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
          <span className={`status ${selected.status === "آماده" ? "ready" : "attention"}`}>
            {selected.status === "آماده" ? "●" : "◌"} {selected.status}
          </span>
          {selected.is_user_modified && (
            <span className="status ready" title="این رکورد توسط کاربر بازبینی و ویرایش شده است">
              ✓ اصلاح‌شده توسط کاربر
            </span>
          )}
          <span className="filesize-tag">
            حجم: {Math.max(1, Math.round(selected.file_size / 1024)).toLocaleString("fa-IR")} کیلوبایت ·{" "}
            {selected.page_count.toLocaleString("fa-IR")} صفحه
          </span>
          <span className="sha-tag" dir="ltr" title={selected.sha256}>
            SHA-256: {selected.sha256.substring(0, 12)}…
          </span>
        </div>

        <h3>
          متن استخراج‌شده ·{" "}
          <small style={{ fontWeight: "normal" }}>
            {extractionStatusLabel[selected.extraction_status] || selected.extraction_status}
          </small>
        </h3>
        {selected.text ? (
          <p className="extracted" data-testid="extracted-text-content">
            {selected.text}
          </p>
        ) : (
          <div className="evidence" data-testid="no-extracted-text-notice">
            {selected.extraction_status === "pending_ocr"
              ? "متنی از این فایل استخراج نشده است. این فایل نیازمند اجرای موتور OCR یا تحلیلگر دیداری آفلاین در مایلستون بعدی است."
              : "محتوای متنی در این فایل وجود ندارد."}
          </div>
        )}

        {selected.system_note && (
          <div className="evidence" style={{ marginTop: "0.5rem" }}>
            <strong>یادداشت سیستم:</strong> {selected.system_note}
          </div>
        )}

        <h3>موضوع پیشنهادی</h3>
        <select
          aria-label="موضوع فایل"
          value={topicDraft}
          disabled={saving}
          onChange={(e) => handleTopicChange(e.target.value)}
        >
          {["طراحی", "معماری", "آموزش", "فناوری", "زندگی", "کار", "پژوهش"].map(
            (t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ),
          )}
        </select>

        <h3>برچسب‌ها</h3>
        <div className="tags">
          {selected.tags.map((t) => (
            <button
              key={t}
              title="حذف برچسب"
              disabled={saving}
              onClick={async () => {
                setNotice("");
                setErrorMsg("");
                setSaving(true);
                try {
                  await onRemoveTag(selected.id, t);
                  setNotice("برچسب حذف شد.");
                } catch (err: any) {
                  setErrorMsg(err?.message || "خطا در حذف برچسب.");
                } finally {
                  setSaving(false);
                }
              }}
            >
              {t} ×
            </button>
          ))}
        </div>
        <form
          className="tagform"
          onSubmit={async (e) => {
            e.preventDefault();
            const val = tagInput.trim();
            if (!val || selected.tags.includes(val)) return;
            setNotice("");
            setErrorMsg("");
            setSaving(true);
            try {
              await onAddTag(selected.id, val);
              setTagInput("");
              setNotice("برچسب جدید در پایگاه‌داده ثبت شد.");
            } catch (err: any) {
              setErrorMsg(err?.message || "خطا در افزودن برچسب.");
            } finally {
              setSaving(false);
            }
          }}
        >
          <input
            aria-label="برچسب جدید"
            placeholder="برچسب جدید…"
            value={tagInput}
            disabled={saving}
            onChange={(e) => setTagInput(e.target.value)}
          />
          <button type="submit" disabled={saving || !tagInput.trim()}>
            افزودن
          </button>
        </form>

        {selected.error_message && (
          <div className="evidence" role="alert" style={{ borderColor: "#e05a47", color: "#a82010" }}>
            گزارش خطای استخراج: {selected.error_message}
          </div>
        )}

        <div className="actions">
          <button
            className="primary"
            disabled={saving}
            onClick={handleConfirmReview}
          >
            {saving ? "در حال ثبت…" : "تأیید و ثبت اصلاح"}
          </button>
          <button
            disabled={true}
            title="صف پردازش پس‌زمینه (Worker) در مایلستون ۲ فعال می‌شود"
            style={{ opacity: 0.55, cursor: "not-allowed" }}
          >
            پردازش دوباره (در مایلستون ۲)
          </button>
        </div>
        {notice && (
          <p role="status" style={{ color: "#1d6b48", fontWeight: 500 }}>
            {notice}
          </p>
        )}
        {errorMsg && (
          <p role="alert" style={{ color: "#b00020", fontWeight: 500 }}>
            {errorMsg}
          </p>
        )}
      </section>
    </div>
  );
}
