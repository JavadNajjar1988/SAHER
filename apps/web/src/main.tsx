import React, { useEffect, useState, useCallback } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";
import {
  FileItem,
  StatsResponse,
  ConnectionMode,
  FileUpdatePayload,
} from "./types/archive";
import {
  ArchiveApiClient,
  EXPLICIT_DEMO_SAMPLES,
  LegacyBrowserDataHelper,
} from "./services/apiClient";
import { Sidebar } from "./components/Sidebar";
import { Preview } from "./components/Preview";
import { FileDetailModal } from "./components/FileDetailModal";
import { ImportDialog } from "./components/ImportDialog";

const digits = (value: number) => value.toLocaleString("fa-IR");

function App() {
  const [items, setItems] = useState<FileItem[]>([]);
  const [stats, setStats] = useState<StatsResponse>({
    total_files: 0,
    ready_files: 0,
    attention_files: 0,
  });
  const [connectionMode, setConnectionMode] = useState<ConnectionMode>("checking");
  const [backendVersion, setBackendVersion] = useState<string | undefined>(undefined);
  const [maxUploadBytes, setMaxUploadBytes] = useState<number>(25 * 1024 * 1024);
  const [apiErrorBanner, setApiErrorBanner] = useState<string>("");

  const [demoItems, setDemoItems] = useState<FileItem[]>(EXPLICIT_DEMO_SAMPLES);
  const [page, setPage] = useState("کتابخانه");
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("همهٔ فایل‌ها");
  const [view, setView] = useState("grid");
  const [selected, setSelected] = useState<FileItem | null>(null);
  const [adding, setAdding] = useState(false);
  const [loading, setLoading] = useState(false);

  const loadFromBackend = useCallback(async () => {
    setLoading(true);
    setApiErrorBanner("");
    try {
      const health = await ArchiveApiClient.checkHealth();
      setBackendVersion(health.version);
      if (health.max_upload_size_bytes) {
        setMaxUploadBytes(health.max_upload_size_bytes);
      }

      const statusFilter = page === "بازبینی" ? "نیازمند بازبینی" : undefined;
      const [fetchedFiles, fetchedStats] = await Promise.all([
        ArchiveApiClient.listFiles(kind, query, statusFilter),
        ArchiveApiClient.getStats(),
      ]);
      setItems(fetchedFiles);
      setStats(fetchedStats);
      setConnectionMode("connected");
    } catch (err: any) {
      setConnectionMode("disconnected");
      setApiErrorBanner(
        err?.message ||
          "ارتباط با سرویس محلی ساهر (FastAPI) برقرار نشد. عملیات آرشیو تا زمان اتصال مجدد غیرفعال است.",
      );
    } finally {
      setLoading(false);
    }
  }, [kind, query, page]);

  const loadDemoData = useCallback(() => {
    let filtered = [...demoItems];
    if (kind && kind !== "همهٔ فایل‌ها") {
      filtered = filtered.filter((f) => f.kind === kind);
    }
    if (page === "بازبینی") {
      filtered = filtered.filter((f) => f.status === "نیازمند بازبینی");
    }
    if (query.trim()) {
      const q = query.trim().toLowerCase();
      filtered = filtered.filter(
        (f) =>
          f.title.toLowerCase().includes(q) ||
          f.text.toLowerCase().includes(q) ||
          f.tags.some((t) => t.toLowerCase().includes(q)),
      );
    }
    setItems(filtered);
    setStats({
      total_files: demoItems.length,
      ready_files: demoItems.filter((i) => i.status === "آماده").length,
      attention_files: demoItems.filter((i) => i.status !== "آماده").length,
      demo_mode: true,
    });
  }, [demoItems, kind, query, page]);

  useEffect(() => {
    if (connectionMode === "demo") {
      loadDemoData();
    } else {
      loadFromBackend();
    }
  }, [connectionMode, loadFromBackend, loadDemoData]);

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
          "button:not([disabled]), input:not([disabled]), select:not([disabled]), [href]",
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

  const handleUpdateFile = async (fileId: string, payload: FileUpdatePayload) => {
    if (connectionMode === "demo") {
      setDemoItems((prev) =>
        prev.map((item) => {
          if (item.id !== fileId) return item;
          const updated: FileItem = {
            ...item,
            topic: payload.topic ?? item.topic,
            status: payload.status ?? item.status,
            tags: payload.tags ?? item.tags,
            is_user_modified: true,
          };
          setSelected(updated);
          return updated;
        }),
      );
      return;
    }

    const updated = await ArchiveApiClient.updateFile(fileId, payload);
    setSelected(updated);
    await loadFromBackend();
  };

  const handleAddTag = async (fileId: string, tag: string) => {
    if (connectionMode === "demo") {
      const target = demoItems.find((i) => i.id === fileId);
      if (!target) return;
      await handleUpdateFile(fileId, {
        tags: Array.from(new Set([...target.tags, tag])),
      });
      return;
    }

    const updated = await ArchiveApiClient.addTag(fileId, tag);
    setSelected(updated);
    await loadFromBackend();
  };

  const handleRemoveTag = async (fileId: string, tag: string) => {
    if (connectionMode === "demo") {
      const target = demoItems.find((i) => i.id === fileId);
      if (!target) return;
      await handleUpdateFile(fileId, {
        tags: target.tags.filter((t) => t !== tag),
      });
      return;
    }

    const updated = await ArchiveApiClient.removeTag(fileId, tag);
    setSelected(updated);
    await loadFromBackend();
  };

  const handleImportFiles = async (files: FileList, topic?: string) => {
    if (connectionMode === "demo") {
      throw new Error(
        "در حالت نمایشی امکان ذخیره‌سازی واقعی فایل وجود ندارد. لطفاً ابتدا به حالت آرشیو اصلی (متصل به بک‌اند) بازگردید.",
      );
    }
    for (let i = 0; i < files.length; i++) {
      await ArchiveApiClient.importFile(files[i], topic);
    }
    await loadFromBackend();
  };

  const legacyBrowserEntries = LegacyBrowserDataHelper.getLegacyUserEntries();

  return (
    <div className="shell">
      <Sidebar
        page={page}
        setPage={setPage}
        setQuery={setQuery}
        attentionCount={stats.attention_files}
        digits={digits}
        connectionMode={connectionMode}
        backendVersion={backendVersion}
      />
      <main>
        <header>
          <span>
            {connectionMode === "demo" ? "فضای نمایشی آزمایشی" : "فضای شخصی"}{" "}
            <span className="crumb">/</span> {page}
          </span>
          <div className="headerleft">
            {connectionMode === "demo" && (
              <button
                onClick={() => setConnectionMode("checking")}
                style={{
                  background: "#132d31",
                  color: "#fff",
                  border: "none",
                  borderRadius: "6px",
                  padding: "0.35rem 0.75rem",
                  cursor: "pointer",
                  fontSize: "0.82rem",
                }}
              >
                بازگشت به آرشیو اصلی (SQLite)
              </button>
            )}
            <span className="privacy">◈ حریم خصوصی، پیش‌فرض ماست</span>
            <span className="avatar small">م</span>
          </div>
        </header>
        <div className="content">
          {connectionMode === "disconnected" && (
            <div
              role="alert"
              data-testid="backend-disconnected-banner"
              style={{
                background: "#fdecea",
                border: "1px solid #f5c2c0",
                color: "#8a1c14",
                borderRadius: "12px",
                padding: "1rem 1.25rem",
                marginBottom: "1.25rem",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: "1rem",
                flexWrap: "wrap",
              }}
            >
              <div>
                <strong>خطا در ارتباط با سرویس محلی ساهر (FastAPI):</strong>{" "}
                {apiErrorBanner}
              </div>
              <div style={{ display: "flex", gap: "0.5rem" }}>
                <button
                  onClick={() => loadFromBackend()}
                  style={{
                    background: "#8a1c14",
                    color: "#fff",
                    border: "none",
                    borderRadius: "8px",
                    padding: "0.45rem 0.9rem",
                    cursor: "pointer",
                  }}
                >
                  تلاش مجدد برای اتصال
                </button>
                <button
                  onClick={() => setConnectionMode("demo")}
                  style={{
                    background: "transparent",
                    color: "#8a1c14",
                    border: "1px solid #8a1c14",
                    borderRadius: "8px",
                    padding: "0.45rem 0.9rem",
                    cursor: "pointer",
                  }}
                >
                  ورود به حالت نمایشی مجزا
                </button>
              </div>
            </div>
          )}

          {connectionMode === "demo" && (
            <div
              role="status"
              data-testid="demo-mode-banner"
              style={{
                background: "#fff8e6",
                border: "1px solid #f0d890",
                color: "#6e4e00",
                borderRadius: "12px",
                padding: "0.85rem 1.25rem",
                marginBottom: "1.25rem",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: "1rem",
              }}
            >
              <span>
                <strong>حالت نمایشی فعال است:</strong> رکوردهای این نما صرفاً نمونهٔ رابط کاربری هستند و در پایگاه‌داده SQLite ذخیره نمی‌شوند.
              </span>
              <button
                onClick={() => setConnectionMode("checking")}
                style={{
                  background: "#6e4e00",
                  color: "#fff",
                  border: "none",
                  borderRadius: "8px",
                  padding: "0.4rem 0.85rem",
                  cursor: "pointer",
                }}
              >
                اتصال به آرشیو واقعی
              </button>
            </div>
          )}

          <section className="heading">
            <div>
              <div className="eyebrow">هر چیزی، در جای خودش</div>
              <h1>{page === "کتابخانه" ? "کتابخانهٔ من" : page}</h1>
              <p>اینجا جایی برای نگه‌داشتن، پیدا کردن و دوباره کشف کردن است.</p>
            </div>
            <button
              className="primary"
              disabled={connectionMode !== "connected"}
              title={
                connectionMode !== "connected"
                  ? "واردسازی فایل فقط در حالت متصل به سرویس محلی FastAPI امکان‌پذیر است"
                  : "افزودن فایل جدید به آرشیو محلی"
              }
              onClick={() => setAdding(true)}
            >
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
                  <em>بازبینی و در صف</em>
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
                    <option key={k} value={k}>
                      {k}
                    </option>
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
                  {query ? "نتیجهٔ جست‌وجو" : "فایل‌های آرشیو"}{" "}
                  <span>{digits(items.length)} فایل</span>
                </h2>
                <span>
                  {loading
                    ? "در حال دریافت از سرویس محلی…"
                    : connectionMode === "demo"
                      ? "نمایش داده‌های نمونه (مجزا از آرشیو اصلی)"
                      : "پایگاه‌داده پایدار SQLite + FTS5"}
                </span>
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
                      {item.matched_snippet && (
                        <p
                          style={{
                            fontSize: "0.82rem",
                            color: "#4a6266",
                            margin: "0.25rem 0",
                            lineHeight: 1.5,
                          }}
                        >
                          {item.matched_snippet}
                        </p>
                      )}
                      <div className="cardmeta">
                        <span>{item.topic}</span>
                        <span>
                          {item.created_at
                            ? new Date(item.created_at).toLocaleDateString("fa-IR")
                            : "امروز"}
                        </span>
                      </div>
                    </div>
                  </button>
                ))}
              </section>
              {!items.length && !loading && (
                <div className="empty" data-testid="empty-archive-state">
                  {query || kind !== "همهٔ فایل‌ها" || page === "بازبینی" ? (
                    <>
                      فایلی با این مشخصات در آرشیو پیدا نشد.
                      <button
                        onClick={() => {
                          setQuery("");
                          setKind("همهٔ فایل‌ها");
                          if (page === "بازبینی") setPage("کتابخانه");
                        }}
                      >
                        پاک کردن فیلترها
                      </button>
                    </>
                  ) : connectionMode === "connected" ? (
                    <>
                      آرشیو شخصی شما در حال حاضر خالی است. نخستین سند یا تصویر خود را وارد کنید یا برای مشاهدهٔ نمونه‌ها وارد حالت نمایشی شوید.
                      <div style={{ display: "flex", gap: "0.75rem", justifyContent: "center", marginTop: "0.75rem" }}>
                        <button onClick={() => setAdding(true)}>
                          ＋ افزودن نخستین فایل
                        </button>
                        <button onClick={() => setConnectionMode("demo")}>
                          مشاهدهٔ حالت نمایشی آزمایشی
                        </button>
                      </div>
                    </>
                  ) : (
                    <>ارتباط با سرویس بک‌اند برقرار نیست.</>
                  )}
                </div>
              )}
            </>
          ) : (
            <section className="placeholder">
              <span>◇</span>
              <h2>{page}</h2>
              <p>
                {page === "صف پردازش"
                  ? "موتور صف پردازش پایدار (SQLite Jobs + Background Workers) در مایلستون ۲ پیاده‌سازی می‌شود."
                  : page === "تنظیمات"
                    ? "مدیریت حالت عملیاتی آرشیو محلی (متصل به پایگاه‌داده SQLite یا حالت نمایشی مجزا)."
                    : `این بخش در مایلستون‌های بعدی فعال می‌شود. هم‌اکنون می‌توانید واردسازی فایل، استخراج متن و جست‌وجوی FTS5 را در کتابخانه بررسی کنید.`}
              </p>
              {page === "تنظیمات" && (
                <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", justifyContent: "center", marginTop: "1rem" }}>
                  <button
                    onClick={() =>
                      setConnectionMode(connectionMode === "demo" ? "checking" : "demo")
                    }
                  >
                    {connectionMode === "demo"
                      ? "بازگشت به حالت آرشیو اصلی (SQLite)"
                      : "تغییر به حالت نمایشی آزمایشی"}
                  </button>
                  {legacyBrowserEntries.length > 0 && (
                    <button
                      onClick={() => {
                        const blob = new Blob(
                          [JSON.stringify(legacyBrowserEntries, null, 2)],
                          { type: "application/json" },
                        );
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement("a");
                        a.href = url;
                        a.download = "saher-legacy-localstorage-export.json";
                        a.click();
                        URL.revokeObjectURL(url);
                      }}
                    >
                      برون‌ریزی داده‌های قدیمی مرورگر ({digits(legacyBrowserEntries.length)} مورد)
                    </button>
                  )}
                </div>
              )}
              <button onClick={() => setPage("کتابخانه")} style={{ marginTop: "0.75rem" }}>
                رفتن به کتابخانه
              </button>
            </section>
          )}
          <footer>
            <span>◈ محتوای شما، روی دستگاه شما</span>
            <span>
              {connectionMode === "demo"
                ? "حالت نمایشی مجزا · بدون ذخیره‌سازی دیسک"
                : "بایگانی محلی آفلاین ساهر · پایگاه‌داده پایدار SQLite FTS5"}
            </span>
          </footer>
        </div>
      </main>
      {selected && (
        <FileDetailModal
          selected={selected}
          onClose={() => setSelected(null)}
          onUpdate={handleUpdateFile}
          onAddTag={handleAddTag}
          onRemoveTag={handleRemoveTag}
          isDemoMode={connectionMode === "demo"}
        />
      )}
      {adding && (
        <ImportDialog
          onClose={() => setAdding(false)}
          onImport={handleImportFiles}
          maxUploadBytes={maxUploadBytes}
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
