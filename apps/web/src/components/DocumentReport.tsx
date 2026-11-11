import React, { useEffect, useId, useRef, useState } from "react";
import { ArchiveApiClient, ArchiveCollections, DocumentCardData, DocumentEvidence } from "../services/apiClient";
import { FileItem, PageItem } from "../types/archive";

const tabs = ["مشخصات سند", "فراداده", "متن و یادداشت بازبین", "شواهد مستند", "مجموعه‌ها و منابع"];
const fields = { folder_path: "پوشهٔ شخصی", subject: "شرح سوژهٔ سند", location_label: "برچسب مکان سند", source_reference: "مرجع یا نشانی منبع" };
const kinds = ["نامشخص", "اسکرین‌شات", "عکس دوربین", "سند اسکن‌شده", "تصویر گرافیکی", "سند متنی"];
const reviewLabels = { pending: "نیازمند بازبینی", confirmed: "تأییدشده توسط بازبین", rejected: "ردشده توسط بازبین" };
const digits = (n: number) => n.toLocaleString("fa-IR");

export function DocumentReport({ file, pages }: { file: FileItem; pages: PageItem[] }) {
  const [card, setCard] = useState<DocumentCardData | null>(null);
  const [tab, setTab] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [textPage, setTextPage] = useState(1);
  const [quote, setQuote] = useState("");
  const [quotePage, setQuotePage] = useState(1);
  const [collections, setCollections] = useState<ArchiveCollections | null>(null);
  const [offset, setOffset] = useState(0);
  const [collectionError, setCollectionError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const id = useId();
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  useEffect(() => {
    let active = true;
    ArchiveApiClient.getDocumentCard(file.id).then(value => { if (active) setCard(value); })
      .catch(err => { if (active) setError(err.message); });
    return () => { active = false; };
  }, [file.id]);
  useEffect(() => {
    if (tab !== 4) return;
    let active = true;
    setCollections(null); setCollectionError("");
    ArchiveApiClient.getCollections(offset).then(value => { if (active) setCollections(value); })
      .catch(err => { if (active) setCollectionError(err.message); });
    return () => { active = false; };
  }, [tab, offset, refresh]);
  function change(patch: Partial<DocumentCardData>) {
    setCard(current => current ? { ...current, ...patch } : current);
    setDirty(true); setMessage("");
  }
  const evidence = card?.evidence || [];
  function updateEvidence(index: number, patch: Partial<DocumentEvidence>) {
    change({ evidence: evidence.map((entry, i) => i === index ? { ...entry, ...patch } : entry) });
  }
  const activePage = pages.find(p => p.page_number === textPage) || pages[0];
  const activeQuotePage = pages.find(p => p.page_number === quotePage) || pages[0];
  const sources = new Map<string, number>();
  if (card?.source_reference.trim()) sources.set(card.source_reference.trim(), 0);
  evidence.forEach(entry => {
    const source = entry.source_reference.trim() || card?.source_reference.trim() || "منبع ثبت نشده";
    sources.set(source, (sources.get(source) || 0) + 1);
  });
  const metadata = [["نام فایل", file.title], ["قالب", file.mime_type], ["حجم", `${digits(file.file_size)} بایت`],
    ["صفحات", digits(file.page_count)], ["موضوع", file.topic], ["وضعیت", file.status], ["شناسهٔ سند", file.id], ["SHA-256", file.sha256]];
  const pageOptions = pages.map(p => <option key={p.page_number} value={p.page_number}>صفحهٔ {digits(p.page_number)}</option>);

  return <section className="document-report" aria-label="گزارش سند" dir="rtl">
    <header className="report-banner"><small>ساهر · آرشیو اسناد</small><h3>گزارش سند</h3><p>{file.title}</p>
      <button type="button" disabled={busy || dirty || !card} onClick={async () => {
        setBusy(true); setError("");
        try {
          const blob = await ArchiveApiClient.downloadDocumentWord(file.id);
          const url = URL.createObjectURL(blob);
          const link = document.createElement("a"); link.href = url; link.download = "گزارش-سند.docx";
          document.body.appendChild(link); link.click(); link.remove();
          setTimeout(() => URL.revokeObjectURL(url), 1000);
          setMessage("گزارش Word دریافت شد.");
        } catch (err: any) { setError(err.message); }
        finally { setBusy(false); }
      }}>دریافت گزارش Word فارسی</button>
    </header>
    <div role="tablist" aria-label="بخش‌های گزارش سند" className="report-tabs">
      {tabs.map((label, index) => <button key={label} type="button" role="tab" id={`${id}-tab-${index}`}
        aria-controls={`${id}-panel-${index}`} aria-selected={tab === index} tabIndex={tab === index ? 0 : -1}
        ref={node => { tabRefs.current[index] = node; }} onClick={() => setTab(index)} onKeyDown={event => {
          const next = event.key === "ArrowLeft" ? (index + 1) % tabs.length : event.key === "ArrowRight" ? (index + tabs.length - 1) % tabs.length : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : null;
          if (next !== null) { event.preventDefault(); setTab(next); tabRefs.current[next]?.focus(); }
        }}>{label}{index === 3 && <span className="report-count">{digits(evidence.length)}</span>}</button>)}
    </div>
    {!card && !error && <p role="status">در حال دریافت گزارش…</p>}
    {card && <form onSubmit={async event => {
      event.preventDefault(); setBusy(true); setMessage(""); setError("");
      try {
        setCard(await ArchiveApiClient.saveDocumentCard(file.id, card));
        setDirty(false); setMessage("گزارش و شواهد ذخیره شد."); setRefresh(n => n + 1);
      } catch (err: any) { setError(err.message); }
      finally { setBusy(false); }
    }}><fieldset disabled={busy} className="report-fieldset">
      {tabs.map((_, index) => index !== tab && <div key={index} role="tabpanel" id={`${id}-panel-${index}`} aria-labelledby={`${id}-tab-${index}`} hidden />)}
      <div role="tabpanel" id={`${id}-panel-${tab}`} aria-labelledby={`${id}-tab-${tab}`} tabIndex={0} className="report-panel">
        <h4>{tabs[tab]}</h4>
        {tab === 0 && <div className="document-card-grid">
          {Object.entries(fields).map(([key, label]) => <label key={key}>{label}<input dir="auto"
            value={String(card[key as keyof DocumentCardData] || "")} maxLength={key === "source_reference" ? 2000 : key === "location_label" ? 300 : 500}
            onChange={e => change({ [key]: e.target.value })} /></label>)}
          <label>نوع سند یا تصویر<select aria-label="نوع سند یا تصویر" value={card.media_kind} onChange={e => change({ media_kind: e.target.value })}>{kinds.map(kind => <option key={kind}>{kind}</option>)}</select></label>
        </div>}
        {tab === 1 && <><dl className="report-metadata">{metadata.map(([label, value]) => <div key={label}><dt>{label}</dt><dd dir="auto">{value}</dd></div>)}</dl>
          <p>پیشنهاد نوع: <strong>{card.detected_media_kind}</strong> · {card.detection_evidence}</p>
          {card.width && card.height && <p>ابعاد: {digits(card.width)} × {digits(card.height)} پیکسل</p>}</>}
        {tab === 2 && <><label>صفحهٔ سند<select aria-label="صفحهٔ سند" value={activePage?.page_number || ""} disabled={!pages.length} onChange={e => setTextPage(Number(e.target.value))}>
          {!pages.length && <option value="">متن هنوز آماده نیست</option>}{pageOptions}</select></label>
          <pre className="report-source-text" dir="auto">{activePage?.raw_text || "متنی برای نمایش موجود نیست."}</pre>
          <p>متن عین خروجی ذخیره‌شده است؛ اصلاح آن از بخش ویرایش صفحات پایین گزارش انجام می‌شود.</p>
          <label>یادداشت بازبین<textarea aria-label="یادداشت بازبین" rows={5} maxLength={20000} value={card.notes} onChange={e => change({ notes: e.target.value })} /></label></>}
        {tab === 3 && <><p>تطابق نقل‌قول با متن ذخیره‌شده، مستقل از تأیید انسانی نمایش داده می‌شود.</p>
          {!evidence.length && <p className="report-empty">هنوز شاهدی ثبت نشده است.</p>}
          {evidence.map((entry, index) => {
            const matches = pages.find(p => p.page_number === entry.page_number)?.raw_text.includes(entry.quote);
            return <article className={`report-evidence ${entry.review_status}`} key={entry.id}>
              <header><strong>شاهد {digits(index + 1)}</strong><span>{matches ? "تطابق دقیق با متن صفحه" : "نیازمند تطبیق با اصل صفحه"}</span></header>
              <blockquote dir="auto">{entry.quote}</blockquote><div className="document-card-grid">
                <label>مرجع منبع<input dir="auto" maxLength={2000} value={entry.source_reference} placeholder={card.source_reference || "منبع شاهد"} onChange={e => updateEvidence(index, { source_reference: e.target.value })} /></label>
                <label>وضعیت بازبینی<select aria-label={`وضعیت بازبینی شاهد ${digits(index + 1)}`} value={entry.review_status} onChange={e => updateEvidence(index, { review_status: e.target.value as DocumentEvidence["review_status"] })}>
                  {Object.entries(reviewLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
                <label>یادداشت شاهد<textarea aria-label={`یادداشت شاهد ${digits(index + 1)}`} rows={2} maxLength={2000} value={entry.reviewer_note} onChange={e => updateEvidence(index, { reviewer_note: e.target.value })} /></label>
              </div><div className="actions"><button type="button" onClick={() => { setTextPage(entry.page_number); setTab(2); }}>مشاهدهٔ صفحهٔ {digits(entry.page_number)}</button>
                <button type="button" onClick={() => change({ evidence: evidence.filter((_, i) => i !== index) })}>حذف شاهد {digits(index + 1)}</button></div>
            </article>;
          })}
          <div className="report-evidence-editor"><h5>افزودن شاهد مستند</h5>
            <label>صفحهٔ مرجع<select aria-label="صفحهٔ مرجع شاهد جدید" disabled={!pages.length} value={activeQuotePage?.page_number || ""} onChange={e => setQuotePage(Number(e.target.value))}>
              {!pages.length && <option value="">ابتدا استخراج صفحات را تکمیل کنید</option>}{pageOptions}</select></label>
            <label>نقل‌قول دقیق<textarea aria-label="نقل‌قول دقیق" rows={4} maxLength={5000} dir="auto" value={quote} onChange={e => setQuote(e.target.value)} /></label>
            <button type="button" disabled={!quote.trim() || !activeQuotePage || evidence.length >= 100} onClick={() => {
              if (!activeQuotePage) return;
              change({ evidence: [...evidence, { id: crypto.randomUUID(), quote, page_number: activeQuotePage.page_number, source_reference: card.source_reference, review_status: "pending", reviewer_note: "" }] }); setQuote("");
            }}>افزودن به شواهد</button><p>حداکثر ۱۰۰ شاهد؛ افزودن و حذف پس از ذخیرهٔ گزارش ثبت می‌شود.</p>
          </div></>}
        {tab === 4 && <><h5>منابع سند جاری</h5>
          {!sources.size && <p>هنوز منبعی ثبت نشده است.</p>}
          {[...sources].map(([source, count]) => <div className="report-source-row" key={source}><span dir="auto">{source}</span><span className="report-count">{digits(count)} شاهد</span></div>)}
          <h5>مجموعه‌های آرشیو</h5>
          {!collections && !collectionError && <p role="status">در حال دریافت مجموعه‌ها…</p>}{collectionError && <p role="alert">{collectionError}</p>}
          {collections && <><p>{digits(collections.total_documents)} سند در {digits(collections.total_collections)} مجموعه؛ شمار منابع مربوط به مرجع اصلی ثبت‌شدهٔ اسناد است.</p>
            {collections.items.map(item => <div className="report-source-row" key={item.folder_path}><span>{item.folder_path || "بدون پوشه"}</span><span>{digits(item.document_count)} سند · {digits(item.source_count)} منبع</span></div>)}
            <nav className="pagination" aria-label="صفحه‌بندی مجموعه‌ها"><button type="button" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 100))}>قبلی</button>
              <span>صفحهٔ {digits(Math.floor(offset / 100) + 1)}</span><button type="button" disabled={offset + collections.items.length >= collections.total_collections} onClick={() => setOffset(offset + 100)}>بعدی</button></nav></>}
        </>}
      </div><footer className="report-save"><button className="primary" disabled={busy || !dirty}>{busy ? "در حال ذخیره…" : "ذخیرهٔ گزارش"}</button>
        <span>{dirty ? "تغییرات ذخیره‌نشده دارید؛ پیش از خروجی Word ذخیره کنید." : "خروجی Word از آخرین نسخهٔ ذخیره‌شده تهیه می‌شود."}</span></footer>
    </fieldset></form>}
    {message && <p role="status">{message}</p>}{error && <p role="alert" className="modal-error">{error}</p>}
  </section>;
}
