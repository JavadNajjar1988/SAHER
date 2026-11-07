import React, { useEffect, useState, useCallback } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";
import { FileItem, StatsResponse } from "./types/archive";
import { ArchiveApiClient } from "./services/apiClient";
import { Sidebar } from "./components/Sidebar";
import { Preview } from "./components/Preview";
import { FileDetailModal } from "./components/FileDetailModal";
import { ImportDialog } from "./components/ImportDialog";

const digits = (value: number) => value.toLocaleString("fa-IR");

function App() {
  const [items, setItems] = useState<FileItem[]>([]);
  const [stats, setStats] = useState<StatsResponse>({ total_files: 0, ready_files: 0, attention_files: 0 });
  const [page, setPage] = useState("کتابخانه");
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("همهٔ فایل‌ها");
  const [view, setView] = useState("grid");
  const [selected, setSelected] = useState<FileItem | null>(null);
  const [adding, setAdding] = useState(false);
  const [loading, setLoading] = useState(false);

  // Load files and stats from API / Local Persistence
  const refreshData = useCallback(async () => {
    setLoading(true);
    try {
      const [fetchedFiles, fetchedStats] = await Promise.all([
        ArchiveApiClient.listFiles(kind, query, page === "بازبینی" ? "نیازمند بازبینی" : undefined),
        ArchiveApiClient.getStats()
      ]);
      setItems(fetchedFiles);
      setStats(fetchedStats);
    } catch (e) {
      console.error("Failed to load archive data", e);
    } finally {
      setLoading(false);
    }
  }, [kind, query, page]);

  useEffect(() => {
    refreshData();
  }, [refreshData]);

  // Modal accessibility & focus management
  const modalOpen = selected !== null || adding;
  useEffect(() => {
    if (!modalOpen) return;
    const previousFocus = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]');
    const focusable = () =>
      Array.from(
        dialog?.querySelectorAll<HTMLElement>(
          "button, input, select, [href]",
        ) ?? [],
      );
    focusable()[0]?.focus();
    function handleKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setSelected(null);
        setAdding(false);
      }
      if (event.key === "Tab") {
        const controls = focusable();
        const first = controls[0];
        const last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    }
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("keydown", handleKey);
      document.body.style.overflow = previousOverflow;
      previousFocus?.focus();
    };
  }, [modalOpen]);

  // Update file handler
  const handleUpdate = async (updated: FileItem) => {
    try {
      await ArchiveApiClient.updateFile(updated.id, {
        topic: updated.topic,
        status: updated.status,
        tags: updated.tags
      });
      setSelected(updated);
      await refreshData();
    } catch (err) {
      console.error("Failed to update file", err);
    }
  };

  const handleAddTag = async (fileId: string, tag: string) => {
    const updated = await ArchiveApiClient.addTag(fileId, tag);
    if (updated) {
      setSelected(updated);
      await refreshData();
    }
  };

  const handleRemoveTag = async (fileId: string, tag: string) => {
    const updated = await ArchiveApiClient.removeTag(fileId, tag);
    if (updated) {
      setSelected(updated);
      await refreshData();
    }
  };

  // Import handler
  const handleImportFiles = async (files: FileList) => {
    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      await ArchiveApiClient.importFile(file);
    }
    await refreshData();
  };

  return (
    <div className="shell">
      <Sidebar
        page={page}
        setPage={setPage}
        setQuery={setQuery}
        attentionCount={stats.attention_files}
        digits={digits}
      />
      <main>
        <header>
          <span>
            فضای شخصی <span className="crumb">/</span> {page}
          </span>
          <div className="headerleft">
            <span className="privacy">◈ حریم خصوصی، پیش‌فرض ماست</span>
            <span className="avatar small">م</span>
          </div>
        </header>
        <div className="content">
          <section className="heading">
            <div>
              <div className="eyebrow">هر چیزی، در جای خودش</div>
              <h1>{page === "کتابخانه" ? "کتابخانهٔ من" : page}</h1>
              <p>اینجا جایی برای نگه‌داشتن، پیدا کردن و دوباره کشف کردن است.</p>
            </div>
            <button className="primary" onClick={() => setAdding(true)}>
              <span>＋</span> افزودن فایل
            </button>
          </section>
          <section className="stats">
            <div>
              <span className="statIcon">▤</span>
              <div>
                <small>تمام فایل‌ها</small>
                <strong>
                  {digits(stats.total_files)}
                  <em>فایل در کتابخانه</em>
                </strong>
              </div>
            </div>
            <div>
              <span className="statIcon green">✓</span>
              <div>
                <small>آمادهٔ جست‌وجو</small>
                <strong>
                  {digits(stats.ready_files)}
                  <em>پردازش کامل شده</em>
                </strong>
              </div>
            </div>
            <div>
              <span className="statIcon amber">◌</span>
              <div>
                <small>نیازمند توجه شما</small>
                <strong>
                  {digits(stats.attention_files)}
                  <em>بازبینی و تحلیل ناقص</em>
                </strong>
              </div>
            </div>
          </section>
          {["کتابخانه", "جست‌وجو", "بازبینی"].includes(page) ? (
            <>
              <section className="toolbar">
                <div className="search">
                  <span>⌕</span>
                  <input
                    aria-label="جست‌وجو در کتابخانه"
                    placeholder="در میان فایل‌ها، متن‌ها و برچسب‌ها بگردید…"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                  {query && (
                    <button
                      aria-label="پاک کردن جست‌وجو"
                      onClick={() => setQuery("")}
                    >
                      ×
                    </button>
                  )}
                </div>
                <select
                  aria-label="نوع فایل"
                  value={kind}
                  onChange={(e) => setKind(e.target.value)}
                >
                  {["همهٔ فایل‌ها", "سند", "تصویر", "اسکرین‌شات"].map((k) => (
                    <option key={k}>{k}</option>
                  ))}
                </select>
                <div className="viewtoggle">
                  <button
                    aria-label="نمای کارتی"
                    className={view === "grid" ? "chosen" : ""}
                    onClick={() => setView("grid")}
                  >
                    ▦
                  </button>
                  <button
                    aria-label="نمای فهرستی"
                    className={view === "list" ? "chosen" : ""}
                    onClick={() => setView("list")}
                  >
                    ☰
                  </button>
                </div>
              </section>
              <div className="sectionline">
                <h2>
                  {query ? "نتیجهٔ جست‌وجو" : "آخرین فایل‌های شما"}{" "}
                  <span>{digits(items.length)} فایل</span>
                </h2>
                <span>{loading ? "در حال دریافت اطلاعات..." : "پایگاه‌داده محلی ساهر"}</span>
              </div>
              <section className={`files ${view}`}>
                {items.map((item) => (
                  <button
                    className="filecard"
                    key={item.id}
                    onClick={() => setSelected(item)}
                  >
                    <div className={`preview ${item.color}`}>
                      <Preview item={item} />
                      <span className="filekind">{item.kind}</span>
                    </div>
                    <div className="cardbody">
                      <span
                        className={`status ${item.status === "آماده" ? "ready" : "attention"}`}
                      >
                        {item.status === "آماده" ? "●" : "◌"} {item.status}
                      </span>
                      <h3>{item.title}</h3>
                      <div className="cardmeta">
                        <span>{item.topic}</span>
                        <span>
                          {item.created_at ? new Date(item.created_at).toLocaleDateString("fa-IR") : "امروز"}
                        </span>
                      </div>
                    </div>
                  </button>
                ))}
              </section>
              {!items.length && !loading && (
                <div className="empty">
                  فایلی با این مشخصات پیدا نشد.
                  <button
                    onClick={() => {
                      setQuery("");
                      setKind("همهٔ فایل‌ها");
                    }}
                  >
                    پاک کردن فیلترها
                  </button>
                </div>
              )}
            </>
          ) : (
            <section className="placeholder">
              <span>◇</span>
              <h2>{page}</h2>
              <p>
                {page === "صف پردازش"
                  ? "صف پردازش پس‌زمینه برای استخراج فشرده، اجرای مدل دیداری Qwen2.5-VL و ساخت بردارهای معنایی در حال اتصال است."
                  : page === "تنظیمات"
                  ? "تنظیمات آرشیو آفلاین، مسیر ذخیره‌سازی پایگاه‌داده و مدیریت مدل‌های هوش مصنوعی محلی."
                  : `این بخش در مرحلهٔ بعد پیاده‌سازی می‌شود. هم‌اکنون می‌توانید ذخیره‌سازی، جست‌وجوی متنی و استخراج اسناد را در بخش کتابخانه آزمایش کنید.`}
              </p>
              {page === "تنظیمات" && (
                <button
                  style={{ marginTop: "1rem" }}
                  onClick={() => {
                    ArchiveApiClient.resetFallbackStorage();
                    refreshData();
                    alert("داده‌های محلی به حالت اولیه بازنشانی شدند.");
                  }}
                >
                  بازنشانی داده‌های نمونه
                </button>
              )}
              <button onClick={() => setPage("کتابخانه")}>
                رفتن به کتابخانه
              </button>
            </section>
          )}
          <footer>
            <span>◈ محتوای شما، روی دستگاه شما</span>
            <span>بایگانی محلی آفلاین ساهر · پایگاه‌داده پایدار SQLite FTS5</span>
          </footer>
        </div>
      </main>
      {selected && (
        <FileDetailModal
          selected={selected}
          onClose={() => setSelected(null)}
          onUpdate={handleUpdate}
          onAddTag={handleAddTag}
          onRemoveTag={handleRemoveTag}
        />
      )}
      {adding && (
        <ImportDialog
          onClose={() => setAdding(false)}
          onImport={handleImportFiles}
        />
      )}
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
