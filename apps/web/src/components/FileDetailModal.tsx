import React, { useEffect, useState } from "react";
import { FileItem, FileUpdatePayload, PageItem } from "../types/archive";
import { ArchiveApiClient } from "../services/apiClient";
import { Preview } from "./Preview";

interface FileDetailModalProps {
  selected: FileItem;
  initialPage?: number | null;
  onClose: () => void;
  onUpdate: (fileId: string, payload: FileUpdatePayload) => Promise<void>;
  onAddTag: (fileId: string, tag: string) => Promise<void>;
  onRemoveTag: (fileId: string, tag: string) => Promise<void>;
  onReanalyze?: (fileId: string, stage?: string) => Promise<string>;
  onPageUpdated?: (fileId: string) => Promise<void>;
  isDemoMode?: boolean;
}

const extractionMethodLabels: Record<string, string> = {
  direct_text: "استخراج مستقیم متن",
  pdf_text: "لایهٔ متنی دیجیتال PDF",
  docx_text: "استخراج مستقیم سند Word",
  ocr_image: "موتور تشخیص متن آفلاین (OCR تصویر)",
  ocr_pdf: "موتور تشخیص متن آفلاین (OCR سند اسکن‌شده)",
  ocr_pdf_page: "موتور تشخیص متن آفلاین (OCR صفحهٔ اسکن‌شده)",
  hybrid_pdf_ocr: "ترکیبی (لایهٔ متنی مستقیم + OCR صفحات اسکن‌شده)",
  user_modified: "اصلاح‌شده توسط کاربر",
  none: "بدون استخراج",
};

export function FileDetailModal({
  selected,
  initialPage,
  onClose,
  onUpdate,
  onAddTag,
  onRemoveTag,
  onReanalyze,
  onPageUpdated,
  isDemoMode = false,
}: FileDetailModalProps) {
  const [topicDraft, setTopicDraft] = useState(selected.topic);
  const [tagInput, setTagInput] = useState("");
  const [targetStage, setTargetStage] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [reanalyzing, setReanalyzing] = useState(false);
  const [notice, setNotice] = useState("");
  const [errorMsg, setErrorMsg] = useState("");

  // Milestone 3: Per-page inspection, page preview, bounding boxes, and manual page text override
  const [pages, setPages] = useState<PageItem[]>([]);
  const [loadingPages, setLoadingPages] = useState(false);
  const [activePageNum, setActivePageNum] = useState<number>(
    initialPage || selected.matched_page || 1,
  );
  const [showPagePreviewImg, setShowPagePreviewImg] = useState<boolean>(true);
  const [showBBoxes, setShowBBoxes] = useState<boolean>(false);
  const [editingPageText, setEditingPageText] = useState<boolean>(false);
  const [pageTextDraft, setPageTextDraft] = useState<string>("");

  useEffect(() => {
    setTopicDraft(selected.topic);
    const startPage = initialPage || selected.matched_page || 1;
    setActivePageNum(startPage);
    setEditingPageText(false);
  }, [selected.id, initialPage, selected.matched_page, selected.topic]);

  useEffect(() => {
    if (isDemoMode) {
      setPages([
        {
          id: `demo-page-${selected.id}-1`,
          file_id: selected.id,
          page_number: 1,
          raw_text: selected.text || "",
          normalized_text: selected.text || "",
          bboxes: [],
          extraction_method: selected.extraction_method || "direct_text",
          page_status: selected.text ? "extracted" : "pending_ocr",
          is_user_modified: Boolean(selected.is_user_modified),
        },
      ]);
      return;
    }

    let cancelled = false;
    setLoadingPages(true);
    ArchiveApiClient.getFilePages(selected.id)
      .then((fetched) => {
        if (cancelled) return;
        setPages(fetched);
      })
      .catch(() => {
        if (cancelled) return;
        setPages([]);
      })
      .finally(() => {
        if (!cancelled) setLoadingPages(false);
      });

    return () => {
      cancelled = true;
    };
  }, [selected.id, selected.extraction_version, selected.processing_version, isDemoMode, selected.text, selected.extraction_method, selected.is_user_modified]);

  const activePageObj: PageItem | undefined =
    pages.find((p) => p.page_number === activePageNum) || pages[0];

  useEffect(() => {
    if (activePageObj) {
      setPageTextDraft(activePageObj.raw_text || activePageObj.normalized_text || "");
    } else {
      setPageTextDraft(selected.text || "");
    }
  }, [activePageObj, selected.text]);

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

  const handleSavePageText = async () => {
    if (isDemoMode || !activePageObj) return;
    setNotice("");
    setErrorMsg("");
    setSaving(true);
    try {
      const updated = await ArchiveApiClient.updatePageText(
        selected.id,
        activePageObj.page_number,
        pageTextDraft,
      );
      setPages((prev) =>
        prev.map((p) => (p.page_number === updated.page_number ? updated : p)),
      );
      setEditingPageText(false);
      setNotice(
        `اصلاح دستی متن صفحهٔ ${updated.page_number.toLocaleString("fa-IR")} ذخیره و در موتور جست‌وجوی FTS5 نمایه‌سازی شد.`,
      );
      if (onPageUpdated) {
        await onPageUpdated(selected.id);
      }
    } catch (err: any) {
      setErrorMsg(err?.message || "خطا در ذخیرهٔ متن اصلاح‌شدهٔ صفحه.");
    } finally {
      setSaving(false);
    }
  };

  const handleTriggerReanalyze = async () => {
    if (!onReanalyze || isDemoMode) return;
    setNotice("");
    setErrorMsg("");
    setReanalyzing(true);
    try {
      const msg = await onReanalyze(selected.id, targetStage || undefined);
      setNotice(msg || "کار بازپردازش فایل در صف پردازش پایدار ثبت شد.");
      const refreshedPages = await ArchiveApiClient.getFilePages(selected.id);
      setPages(refreshedPages);
    } catch (err: any) {
      setErrorMsg(err?.message || "خطا در ثبت درخواست بازپردازش فایل.");
    } finally {
      setReanalyzing(false);
    }
  };

  const extractionStatusLabel: Record<string, string> = {
    extracted: "خواندن و نمایه‌سازی متن کامل شده",
    partial_ocr: "خواندن متن با خطای جزئی در برخی صفحات (سایر صفحات سالم)",
    pending_ocr: "در انتظار OCR / تحلیل دیداری (بدون لایه متنی)",
    queued: "در صف استخراج کارگر پس‌زمینه",
    empty: "فاقد متن قابل استخراج",
    unsupported: "فرمت فاقد استخراج متنی",
    failed: "خطا در استخراج متن",
  };

  const totalPagesCount = Math.max(selected.page_count || 1, pages.length || 1);
  const pageNumbers = Array.from({ length: totalPagesCount }, (_, idx) => idx + 1);
  const matchedPagesSet = new Set<number>(selected.matched_pages || []);
  if (selected.matched_page) matchedPagesSet.add(selected.matched_page);

  const displayedPageText = activePageObj
    ? activePageObj.normalized_text || activePageObj.raw_text
    : selected.text;

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
            <small>جزئیات فایل، پیش‌نمایش صفحه و متن استخراج‌شده</small>
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
          {selected.is_user_modified && (
            <span className="status ready" title="این رکورد توسط کاربر بازبینی و ویرایش شده است">
              ✓ اصلاح‌شده توسط کاربر
            </span>
          )}
          <span className="filesize-tag tabular-nums">
            حجم: {Math.max(1, Math.round(selected.file_size / 1024)).toLocaleString("fa-IR")} کیلوبایت ·{" "}
            {totalPagesCount.toLocaleString("fa-IR")} صفحه · روش:{" "}
            {extractionMethodLabels[selected.extraction_method] || selected.extraction_method} · نسخه پردازش:{" "}
            {(selected.processing_version ?? 1).toLocaleString("fa-IR")}
          </span>
          <span className="sha-tag" dir="ltr" title={selected.sha256}>
            SHA-256: {selected.sha256.substring(0, 12)}…
          </span>
        </div>

        {/* Page Navigation & Matched Source Page Indicator */}
        <div className="page-inspector-bar" data-testid="page-inspector-bar">
          <div className="page-tabs" role="tablist" aria-label="انتخاب صفحهٔ سند">
            {pageNumbers.map((pNum) => {
              const pItem = pages.find((p) => p.page_number === pNum);
              const isMatched = matchedPagesSet.has(pNum);
              const isFailed = pItem?.page_status === "failed" || (selected.failed_pages || []).includes(pNum);
              const isUserMod = pItem?.is_user_modified;
              const isActive = activePageNum === pNum;
              return (
                <button
                  key={pNum}
                  type="button"
                  role="tab"
                  aria-selected={isActive}
                  data-testid={`page-tab-${pNum}`}
                  className={`page-tab-btn ${isActive ? "active" : ""} ${isMatched ? "matched" : ""} ${isFailed ? "failed" : ""}`}
                  onClick={() => {
                    setActivePageNum(pNum);
                    setEditingPageText(false);
                  }}
                >
                  <span>صفحهٔ {pNum.toLocaleString("fa-IR")}</span>
                  {isMatched && <em className="page-badge match-badge">⌕ منطبق</em>}
                  {isFailed && <em className="page-badge error-badge">⚠ خطا</em>}
                  {isUserMod && <em className="page-badge mod-badge">✎</em>}
                </button>
              );
            })}
          </div>
          {!isDemoMode && (
            <div className="page-view-toggles">
              <button
                type="button"
                className={`small-toggle-btn ${showPagePreviewImg ? "chosen" : ""}`}
                onClick={() => setShowPagePreviewImg((v) => !v)}
              >
                {showPagePreviewImg ? "پنهان کردن تصویر صفحه" : "نمایش تصویر صفحه"}
              </button>
              {activePageObj && activePageObj.bboxes && activePageObj.bboxes.length > 0 && (
                <button
                  type="button"
                  data-testid="toggle-bboxes-btn"
                  className={`small-toggle-btn ${showBBoxes ? "chosen" : ""}`}
                  onClick={() => setShowBBoxes((v) => !v)}
                >
                  {showBBoxes
                    ? `بستن مختصات قطعات (${activePageObj.bboxes.length.toLocaleString("fa-IR")})`
                    : `مختصات قطعات متن (${activePageObj.bboxes.length.toLocaleString("fa-IR")})`}
                </button>
              )}
            </div>
          )}
        </div>

        {/* Visual Preview of the Active Page */}
        {!isDemoMode && showPagePreviewImg && (
          <div className="page-visual-preview-box" data-testid="page-visual-preview-box">
            <div className="page-visual-header">
              <strong>
                پیش‌نمایش صفحهٔ {activePageNum.toLocaleString("fa-IR")} از {totalPagesCount.toLocaleString("fa-IR")}
              </strong>
              {activePageObj && (
                <span>
                  روش خواندن صفحه:{" "}
                  {extractionMethodLabels[activePageObj.extraction_method] || activePageObj.extraction_method}
                  {activePageObj.ocr_confidence != null &&
                    ` · اطمینان تشخیص: ${Math.round(activePageObj.ocr_confidence).toLocaleString("fa-IR")}٪`}
                  {activePageObj.width && activePageObj.height
                    ? ` · ابعاد: ${activePageObj.width.toLocaleString("fa-IR")}×${activePageObj.height.toLocaleString("fa-IR")}`
                    : ""}
                </span>
              )}
            </div>
            <div className="page-preview-frame">
              <img
                src={`${ArchiveApiClient.getPagePreviewUrl(selected.id, activePageNum)}?v=${selected.extraction_version ?? 1}`}
                alt={`پیش‌نمایش صفحهٔ ${activePageNum} فایل ${selected.title}`}
                className="page-preview-image"
                loading="lazy"
              />
            </div>
          </div>
        )}

        {/* Bounding Boxes Coordinate List when toggled */}
        {showBBoxes && activePageObj && activePageObj.bboxes.length > 0 && (
          <div className="bboxes-inspector" data-testid="bboxes-inspector">
            <h4>
              قطعات متن و مختصات مکانی صفحهٔ {activePageNum.toLocaleString("fa-IR")} (ترتیب خواندن راست‌به‌چپ)
            </h4>
            <div className="bboxes-chips">
              {activePageObj.bboxes.slice(0, 60).map((b, i) => (
                <span
                  key={i}
                  className="bbox-chip"
                  title={`خط ${b.line_num} | مختصات: [x=${b.x}, y=${b.y}, w=${b.width}, h=${b.height}] | اطمینان: ${b.confidence}%`}
                >
                  <strong>{b.text}</strong>
                  <small dir="ltr">
                    [{b.x},{b.y} {b.width}×{b.height}]
                  </small>
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Page-specific read/OCR error banner if this page failed */}
        {activePageObj?.error_message && (
          <div
            className="evidence error-evidence"
            role="alert"
            data-testid={`page-error-banner-${activePageNum}`}
          >
            <strong>گزارش خطای صفحهٔ {activePageNum.toLocaleString("fa-IR")}:</strong>{" "}
            {activePageObj.error_message}
          </div>
        )}

        <div className="section-header-inline">
          <h3>
            متن صفحهٔ {activePageNum.toLocaleString("fa-IR")} ·{" "}
            <small>
              {extractionStatusLabel[selected.extraction_status] || selected.extraction_status}
            </small>
          </h3>
          {!isDemoMode && activePageObj && (
            <button
              type="button"
              data-testid="edit-page-text-btn"
              className="small-toggle-btn"
              onClick={() => setEditingPageText((v) => !v)}
            >
              {editingPageText ? "انصراف از ویرایش" : "✎ اصلاح دستی متن این صفحه"}
            </button>
          )}
        </div>

        {editingPageText ? (
          <div className="page-edit-box" data-testid="page-edit-box">
            <textarea
              aria-label={`متن صفحهٔ ${activePageNum}`}
              rows={5}
              value={pageTextDraft}
              onChange={(e) => setPageTextDraft(e.target.value)}
            />
            <div className="page-edit-actions">
              <button
                type="button"
                className="primary"
                disabled={saving}
                data-testid="save-page-text-btn"
                onClick={handleSavePageText}
              >
                {saving ? "در حال ذخیره…" : "ذخیرهٔ اصلاح متن صفحه و بروزرسانی نمایه"}
              </button>
            </div>
          </div>
        ) : displayedPageText ? (
          <p className="extracted" data-testid="extracted-text-content">
            {displayedPageText}
          </p>
        ) : (
          <div className="evidence" data-testid="no-extracted-text-notice">
            {loadingPages
              ? "در حال دریافت اطلاعات صفحه…"
              : activePageObj?.page_status === "failed"
                ? `خواندن متن صفحهٔ ${activePageNum.toLocaleString("fa-IR")} با خطا مواجه شد. سایر صفحات سالم فایل در تب‌های بالا قابل مشاهده و جست‌وجو هستند.`
                : selected.extraction_status === "pending_ocr"
                  ? "متنی از این فایل استخراج نشده است. این فایل فاقد لایهٔ متنی یا متن قابل تشخیص در OCR است."
                  : selected.extraction_status === "queued"
                    ? "فایل در صف پردازش پس‌زمینه قرار دارد و به‌زودی استخراج می‌شود."
                    : "محتوای متنی در این صفحه وجود ندارد."}
          </div>
        )}

        {selected.system_note && (
          <div className="evidence">
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
          {[
            "مالی و حسابداری",
            "حقوقی و قراردادها",
            "فناوری و نرم‌افزار",
            "معماری و مهندسی",
            "آموزش و پژوهش",
            "اداری و مکاتبات",
            "طراحی و گرافیک",
            "عکاسی و تصاویر عمومی",
            "طراحی",
            "معماری",
            "آموزش",
            "فناوری",
            "زندگی",
            "کار",
            "پژوهش",
          ].map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
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
          <div className="evidence error-evidence" role="alert">
            گزارش خطای استخراج: {selected.error_message}
          </div>
        )}

        <h3>بازپردازش کنترل‌شده (حفظ متن معتبر و اصلاحات کاربر)</h3>
        <div className="reanalyze-row">
          <select
            aria-label="مرحله بازپردازش"
            value={targetStage}
            disabled={reanalyzing || isDemoMode}
            onChange={(e) => setTargetStage(e.target.value)}
          >
            <option value="">همهٔ مراحل (تحلیل، OCR و استخراج کامل)</option>
            <option value="VALIDATION">از مرحلهٔ اعتبارسنجی باینری (VALIDATION)</option>
            <option value="EXTRACTION">از مرحلهٔ استخراج متن (EXTRACTION)</option>
            <option value="OCR_PENDING">اجرای مجدد تشخیص متن آفلاین (OCR_PENDING)</option>
            <option value="INDEXING">بازسازی نمایهٔ جست‌وجو (INDEXING)</option>
          </select>
        </div>

        <div className="actions">
          <button
            className="primary"
            disabled={saving}
            onClick={handleConfirmReview}
          >
            {saving ? "در حال ثبت…" : "تأیید و ثبت اصلاح"}
          </button>
          <button
            type="button"
            data-testid="reanalyze-file-button"
            disabled={reanalyzing || isDemoMode || !onReanalyze}
            title={
              isDemoMode
                ? "بازپردازش فقط در حالت متصل به بک‌اند فعال است"
                : "ارسال فایل به صف پردازش پایدار بدون حذف ویرایش‌های دستی شما"
            }
            onClick={handleTriggerReanalyze}
          >
            {reanalyzing ? "در حال ثبت در صف…" : "↻ پردازش دوباره"}
          </button>
          {!isDemoMode && (
            <button
              type="button"
              data-testid="export-single-word-btn"
              title="دریافت گزارش تحلیل ماهیت و موضوع این فایل در قالب Word (.docx)"
              onClick={async () => {
                setErrorMsg("");
                try {
                  const blob = await ArchiveApiClient.downloadImagesWordReport(
                    [selected.id],
                    selected.title,
                  );
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = `تحلیل-${selected.title.replace(/\.[^.]+$/, "")}.docx`;
                  document.body.appendChild(a);
                  a.click();
                  a.remove();
                  URL.revokeObjectURL(url);
                  setNotice("گزارش تحلیل Word (.docx) با موفقیت آماده و دانلود شد.");
                } catch (err: any) {
                  setErrorMsg(err?.message || "خطا در تولید فایل Word (.docx).");
                }
              }}
            >
              ⬇ خروجی Word (.docx)
            </button>
          )}
        </div>
        {notice && (
          <p role="status" className="modal-notice">
            {notice}
          </p>
        )}
        {errorMsg && (
          <p role="alert" className="modal-error">
            {errorMsg}
          </p>
        )}
      </section>
    </div>
  );
}
