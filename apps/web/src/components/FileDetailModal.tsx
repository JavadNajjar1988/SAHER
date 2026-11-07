import React, { useState } from "react";
import { FileItem } from "../types/archive";
import { Preview } from "./Preview";

interface FileDetailModalProps {
  selected: FileItem;
  onClose: () => void;
  onUpdate: (item: FileItem) => void;
  onAddTag: (fileId: string, tag: string) => Promise<void>;
  onRemoveTag: (fileId: string, tag: string) => Promise<void>;
}

export function FileDetailModal({
  selected,
  onClose,
  onUpdate,
  onAddTag,
  onRemoveTag,
}: FileDetailModalProps) {
  const [tagInput, setTagInput] = useState("");
  const [notice, setNotice] = useState("");

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
        <div className="filemeta-row">
          <span className={`status ${selected.status === "آماده" ? "ready" : "attention"}`}>
            {selected.status === "آماده" ? "●" : "◌"} {selected.status}
          </span>
          <span className="filesize-tag">
            حجم: {Math.round(selected.file_size / 1024).toLocaleString("fa-IR")} کیلوبایت · {selected.page_count} صفحه
          </span>
          <span className="sha-tag" title={selected.sha256}>
            هش: {selected.sha256.substring(0, 10)}...
          </span>
        </div>
        <h3>متن استخراج‌شده · صفحهٔ ۱</h3>
        <p className="extracted">{selected.text || "متنی در این فایل یافت نشد یا هنوز پردازش نشده است."}</p>
        <h3>موضوع پیشنهادی</h3>
        <select
          aria-label="موضوع فایل"
          value={selected.topic}
          onChange={(e) => onUpdate({ ...selected, topic: e.target.value })}
        >
          {["طراحی", "معماری", "آموزش", "فناوری", "زندگی", "کار", "پژوهش"].map(
            (t) => (
              <option key={t}>{t}</option>
            ),
          )}
        </select>
        <h3>برچسب‌ها</h3>
        <div className="tags">
          {selected.tags.map((t) => (
            <button
              key={t}
              title="حذف برچسب"
              onClick={async () => {
                await onRemoveTag(selected.id, t);
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
            if (val && !selected.tags.includes(val)) {
              await onAddTag(selected.id, val);
              setTagInput("");
            }
          }}
        >
          <input
            aria-label="برچسب جدید"
            placeholder="برچسب جدید…"
            value={tagInput}
            onChange={(e) => setTagInput(e.target.value)}
          />
          <button type="submit">افزودن</button>
        </form>
        <div className="evidence">
          {selected.error_message
            ? `گزارش خطا: ${selected.error_message}`
            : "محتوای استخراج‌شده و متادیتا به‌صورت پایدار در پایگاه‌داده و فضای فایل محلی نگهداری می‌شوند."}
        </div>
        <div className="actions">
          <button
            className="primary"
            onClick={() => {
              onUpdate({ ...selected, status: "آماده" });
              setNotice("تغییرات شما در پایگاه‌داده محلی با موفقیت ثبت شد.");
            }}
          >
            تأیید و ثبت اصلاح
          </button>
          <button
            onClick={() => {
              onUpdate({ ...selected, status: "در صف" });
              setNotice("فایل برای پردازش مجدد صف‌بندی شد.");
            }}
          >
            پردازش دوباره
          </button>
        </div>
        {notice && <p role="status">{notice}</p>}
      </section>
    </div>
  );
}
