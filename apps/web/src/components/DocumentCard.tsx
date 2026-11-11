import React, { useEffect, useState } from "react";
import { ArchiveApiClient, DocumentCardData } from "../services/apiClient";

const labels = {
  folder_path: "پوشهٔ شخصی", subject: "شرح سوژهٔ سند", location_label: "برچسب مکان سند",
  source_reference: "مرجع یا نشانی منبع", notes: "یادداشت سند",
};
const kinds = ["نامشخص", "اسکرین‌شات", "عکس دوربین", "سند اسکن‌شده", "تصویر گرافیکی", "سند متنی"];

export function DocumentCard({ fileId }: { fileId: string }) {
  const [card, setCard] = useState<DocumentCardData | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    setCard(null); setError(""); setMessage("");
    ArchiveApiClient.getDocumentCard(fileId).then(value => {
      if (active) setCard(value);
    }).catch(err => { if (active) setError(err.message); });
    return () => { active = false; };
  }, [fileId]);
  return <section className="document-card" aria-label="شناسنامهٔ سند">
    <h3>شناسنامهٔ سند</h3>
    <p>مشخصات فایل و منبع آن را ثبت کنید. متن اصلی در بخش صفحات قابل اصلاح است.</p>
    {card && <form onSubmit={async event => {
      event.preventDefault(); setBusy(true); setMessage(""); setError("");
      try {
        setCard(await ArchiveApiClient.saveDocumentCard(fileId, card));
        setMessage("شناسنامهٔ سند ذخیره شد.");
      } catch (err: any) { setError(err.message); }
      finally { setBusy(false); }
    }}>
      <div className="document-card-grid">
        {Object.entries(labels).map(([key, label]) => <label key={key}>
          {label}
          {key === "notes" ? <textarea value={card.notes} maxLength={20000} rows={4}
            onChange={e => setCard({ ...card, notes: e.target.value })} /> :
            <input value={String(card[key as keyof DocumentCardData] || "")} dir="auto"
              maxLength={key === "source_reference" ? 2000 : key === "location_label" ? 300 : 500}
              onChange={e => setCard({ ...card, [key]: e.target.value })} />}
        </label>)}
        <label>نوع سند یا تصویر
          <select value={card.media_kind} onChange={e => setCard({ ...card, media_kind: e.target.value })}>
            {kinds.map(kind => <option key={kind}>{kind}</option>)}
          </select>
        </label>
      </div>
      <p>پیشنهاد نوع فایل: <strong>{card.detected_media_kind}</strong> · {card.detection_evidence}</p>
      {card.width && card.height && <p>ابعاد تصویر: {card.width.toLocaleString("fa-IR")} × {card.height.toLocaleString("fa-IR")} پیکسل</p>}
      <button className="primary" disabled={busy}>{busy ? "در حال ذخیره…" : "ذخیرهٔ شناسنامه"}</button>
      <p>خروجی Word شامل آخرین اطلاعات ذخیره‌شده است.</p>
    </form>}
    {!card && !error && <p role="status">در حال دریافت مشخصات…</p>}
    {message && <p role="status">{message}</p>}
    {error && <p role="alert" className="modal-error">{error}</p>}
  </section>;
}
