import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  UserReportCreatePayload,
  UserReportDetail,
  UserReportSummary,
} from "../types/archive";
import { ArchiveApiClient } from "../services/apiClient";

interface UserReportViewProps {
  digits: (val: string | number) => string;
}

type ReportTabId =
  | "virtual"
  | "real"
  | "analysis"
  | "charges"
  | "groups"
  | "messages";

const EVIDENCE_PER_PAGE = 5;

export function UserReportView({ digits }: UserReportViewProps) {
  const [summaries, setSummaries] = useState<UserReportSummary[]>([]);
  const [selectedReportId, setSelectedReportId] = useState<string>("");
  const [report, setReport] = useState<UserReportDetail | null>(null);
  const [activeTab, setActiveTab] = useState<ReportTabId>("virtual");
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [isExportingHtml, setIsExportingHtml] = useState<boolean>(false);
  const [isExportingWord, setIsExportingWord] = useState<boolean>(false);
  const [statusBanner, setStatusBanner] = useState<string>("");

  // Per-charge evidence pagination state (5 items per page, matching reference HTML)
  const [evidencePageByCharge, setEvidencePageByCharge] = useState<
    Record<number, number>
  >({});

  // Messages pagination & filtering state (20 items per page default, options: 10, 20, 50, 100, 200)
  const [messagesPerPage, setMessagesPerPage] = useState<number>(20);
  const [currentMessagePage, setCurrentMessagePage] = useState<number>(1);
  const [messageSearch, setMessageSearch] = useState<string>("");
  const [messageGroupFilter, setMessageGroupFilter] = useState<string>("همه");

  // Create / Analyze New User Report Modal State
  const [showCreateModal, setShowCreateModal] = useState<boolean>(false);
  const [formState, setFormState] = useState<UserReportCreatePayload>({
    full_name: "",
    username: "",
    telegram_id: "",
    national_id: "",
    phone_number: "",
    birth_date: "",
    gender: "مرد",
    postal_code: "",
    city: "کاشمر",
    province: "خراسان رضوی",
    final_status: "سیاه",
    activity_type: "",
    behavior_desc: "",
    network_desc: "",
    interests_desc: "",
    key_points: "",
    final_reason: "",
    default_group: "وفاداران به ملی گرایان مردم گرا",
    raw_messages_text: "",
  });

  const htmlFileInputRef = useRef<HTMLInputElement | null>(null);

  const loadReportsList = async (preferredId?: string) => {
    setIsLoading(true);
    try {
      const listRes = await ArchiveApiClient.listUserReports();
      const items = listRes.items || [];
      setSummaries(items);
      const targetId =
        preferredId ||
        (items.find((i) => i.national_id === "890046190")?.id ??
          items[0]?.id ??
          "");
      if (targetId) {
        setSelectedReportId(targetId);
        const detail = await ArchiveApiClient.getUserReportDetail(targetId);
        setReport(detail);
        setEvidencePageByCharge({});
        setCurrentMessagePage(1);
      } else {
        setReport(null);
      }
    } catch {
      setStatusBanner("خطا در بارگذاری گزارش جامع کاربر از سرویس محلی.");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void loadReportsList();
  }, []);

  const handleSelectReport = async (id: string) => {
    if (!id) return;
    setSelectedReportId(id);
    setIsLoading(true);
    try {
      const detail = await ArchiveApiClient.getUserReportDetail(id);
      setReport(detail);
      setEvidencePageByCharge({});
      setCurrentMessagePage(1);
      setMessageSearch("");
      setMessageGroupFilter("همه");
    } catch {
      setStatusBanner("خطا در دریافت جزئیات گزارش کاربر.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleImportHtmlFile = async (
    e: React.ChangeEvent<HTMLInputElement>,
  ) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setIsLoading(true);
    try {
      const saved = await ArchiveApiClient.importUserReportHtml(file);
      setStatusBanner(
        `فایل گزارش کاربر «${saved.full_name}» با ${digits(saved.total_messages)} پیام و ${digits(saved.total_charges)} عنوان اتهامی وارد شد.`,
      );
      await loadReportsList(saved.id);
    } catch {
      setStatusBanner("خطا در واردسازی فایل HTML گزارش کاربر.");
    } finally {
      setIsLoading(false);
      if (htmlFileInputRef.current) {
        htmlFileInputRef.current.value = "";
      }
    }
  };

  const handleCreateReport = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formState.full_name?.trim() && !formState.username?.trim()) {
      setStatusBanner("لطفاً نام کامل یا نام کاربری را وارد نمایید.");
      return;
    }
    setIsLoading(true);
    try {
      const created = await ArchiveApiClient.createUserReport(formState);
      setShowCreateModal(false);
      setStatusBanner(
        `گزارش جامع کاربر «${created.full_name}» با موفقیت ایجاد و تحلیل شد.`,
      );
      await loadReportsList(created.id);
    } catch {
      setStatusBanner("خطا در ثبت گزارش کاربر جدید.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleExportHtml = async () => {
    if (!report) return;
    setIsExportingHtml(true);
    try {
      const blob = await ArchiveApiClient.downloadUserReportHtml(report.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `user-report-${report.national_id || report.username || report.id}.html`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      setStatusBanner("فایل HTML مستقل گزارش کاربر با موفقیت دانلود شد.");
    } catch {
      setStatusBanner("خطا در دریافت خروجی HTML گزارش کاربر.");
    } finally {
      setIsExportingHtml(false);
    }
  };

  const handleExportWord = async () => {
    if (!report) return;
    setIsExportingWord(true);
    try {
      const blob = await ArchiveApiClient.downloadUserReportWord(report.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `user-report-${report.national_id || report.username || report.id}.docx`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      setStatusBanner("سند Word فارسی (.docx) گزارش کاربر با موفقیت دانلود شد.");
    } catch {
      setStatusBanner("خطا در دریافت سند Word گزارش کاربر.");
    } finally {
      setIsExportingWord(false);
    }
  };

  const changeEvidencePage = (
    chargeIdx: number,
    direction: number,
    totalItems: number,
  ) => {
    const totalPages = Math.max(1, Math.ceil(totalItems / EVIDENCE_PER_PAGE));
    const current = evidencePageByCharge[chargeIdx] || 1;
    const next = Math.min(totalPages, Math.max(1, current + direction));
    setEvidencePageByCharge((prev) => ({ ...prev, [chargeIdx]: next }));
  };

  const filteredMessages = useMemo(() => {
    const all = report?.messages || [];
    return all.filter((m) => {
      if (
        messageGroupFilter !== "همه" &&
        m.source.trim() !== messageGroupFilter.trim()
      ) {
        return false;
      }
      if (!messageSearch.trim()) return true;
      const q = messageSearch.trim().toLowerCase();
      return (
        m.content.toLowerCase().includes(q) ||
        m.source.toLowerCase().includes(q) ||
        m.doc_id.toLowerCase().includes(q) ||
        m.date.toLowerCase().includes(q)
      );
    });
  }, [report?.messages, messageGroupFilter, messageSearch]);

  const totalMessagePages = useMemo(
    () => Math.max(1, Math.ceil(filteredMessages.length / messagesPerPage)),
    [filteredMessages.length, messagesPerPage],
  );

  const paginatedMessages = useMemo(() => {
    const safePage = Math.min(currentMessagePage, totalMessagePages);
    const start = (safePage - 1) * messagesPerPage;
    return filteredMessages.slice(start, start + messagesPerPage);
  }, [filteredMessages, currentMessagePage, totalMessagePages, messagesPerPage]);

  return (
    <section
      className="batch-analysis-page"
      data-testid="user-report-view"
      style={{ paddingBottom: "40px" }}
    >
      {/* Top Action & Dossier Switcher Bar */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          justifyContent: "space-between",
          alignItems: "center",
          gap: "12px",
          padding: "16px 20px",
          marginBottom: "18px",
          background: "#ffffff",
          borderRadius: "16px",
          border: "1px solid #e2e8f0",
          boxShadow: "0 4px 14px rgba(15, 23, 42, 0.05)",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "10px",
            flexWrap: "wrap",
          }}
        >
          <label
            htmlFor="user-report-select"
            style={{ fontWeight: 700, color: "#1e293b", fontSize: "14px" }}
          >
            انتخاب پروندهٔ گزارش کاربر:
          </label>
          <select
            id="user-report-select"
            aria-label="انتخاب پرونده گزارش کاربر"
            value={selectedReportId}
            onChange={(e) => void handleSelectReport(e.target.value)}
            style={{
              padding: "9px 14px",
              borderRadius: "10px",
              border: "1px solid #cbd5e1",
              background: "#f8fafc",
              fontWeight: 700,
              fontSize: "14px",
              color: "#0f172a",
              minWidth: "290px",
            }}
          >
            {summaries.map((s) => (
              <option key={s.id} value={s.id}>
                {s.full_name} ({s.username || s.telegram_id || s.national_id}) —{" "}
                {digits(s.total_charges)} اتهام · {digits(s.total_messages)}{" "}
                پیام
              </option>
            ))}
          </select>
        </div>

        <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
          <input
            ref={htmlFileInputRef}
            type="file"
            accept=".html,.htm"
            onChange={(e) => void handleImportHtmlFile(e)}
            style={{ display: "none" }}
          />
          <button
            type="button"
            data-testid="import-user-report-html-btn"
            onClick={() => htmlFileInputRef.current?.click()}
            style={{
              padding: "9px 14px",
              borderRadius: "10px",
              border: "1px solid #cbd5e1",
              background: "#f8fafc",
              color: "#1e293b",
              fontWeight: 700,
              fontSize: "13px",
              cursor: "pointer",
            }}
          >
            📥 بارگذاری فایل گزارش (.html)
          </button>

          <button
            type="button"
            data-testid="open-create-user-report-btn"
            onClick={() => setShowCreateModal((prev) => !prev)}
            style={{
              padding: "9px 14px",
              borderRadius: "10px",
              border: "1px solid #667eea",
              background: "rgba(102, 126, 234, 0.1)",
              color: "#4338ca",
              fontWeight: 700,
              fontSize: "13px",
              cursor: "pointer",
            }}
          >
            ➕ ثبت / تحلیل گزارش کاربر جدید
          </button>

          {report && (
            <>
              <button
                type="button"
                data-testid="export-user-report-html-btn"
                disabled={isExportingHtml}
                onClick={() => void handleExportHtml()}
                style={{
                  padding: "9px 14px",
                  borderRadius: "10px",
                  border: "1px solid #dc2626",
                  background: "#fff5f5",
                  color: "#dc2626",
                  fontWeight: 700,
                  fontSize: "13px",
                  cursor: "pointer",
                }}
              >
                {isExportingHtml
                  ? "در حال آماده‌سازی..."
                  : "🌐 دانلود فایل HTML مستقل"}
              </button>

              <button
                type="button"
                data-testid="export-user-report-word-btn"
                disabled={isExportingWord}
                onClick={() => void handleExportWord()}
                style={{
                  padding: "9px 16px",
                  borderRadius: "10px",
                  border: "none",
                  background: "linear-gradient(135deg, #1e3a5f 0%, #0f172a 100%)",
                  color: "#ffffff",
                  fontWeight: 700,
                  fontSize: "13px",
                  cursor: "pointer",
                }}
              >
                {isExportingWord
                  ? "در حال تولید Word..."
                  : "📄 خروجی سند Word فارسی (.docx)"}
              </button>
            </>
          )}
        </div>
      </div>

      {statusBanner && (
        <div
          data-testid="user-report-status-banner"
          style={{
            marginBottom: "16px",
            padding: "12px 16px",
            borderRadius: "12px",
            background: "#eff6ff",
            border: "1px solid #bfdbfe",
            color: "#1e3a8a",
            fontWeight: 600,
            fontSize: "14px",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <span>{statusBanner}</span>
          <button
            type="button"
            onClick={() => setStatusBanner("")}
            style={{
              border: "none",
              background: "transparent",
              cursor: "pointer",
              fontWeight: 700,
              color: "#1e3a8a",
            }}
          >
            ✕
          </button>
        </div>
      )}

      {/* Create / Auto-Analyze New User Report Form */}
      {showCreateModal && (
        <form
          onSubmit={(e) => void handleCreateReport(e)}
          data-testid="create-user-report-form"
          style={{
            background: "#ffffff",
            borderRadius: "16px",
            border: "2px solid #667eea",
            padding: "24px",
            marginBottom: "22px",
            boxShadow: "0 12px 32px rgba(102, 126, 234, 0.14)",
          }}
        >
          <h3
            style={{
              fontSize: "18px",
              fontWeight: 700,
              color: "#1e293b",
              marginBottom: "16px",
              paddingBottom: "10px",
              borderBottom: "2px solid #e2e8f0",
            }}
          >
            ایجاد و تحلیل هوشمند گزارش جامع کاربر (۶ زبانه)
          </h3>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))",
              gap: "12px",
              marginBottom: "14px",
            }}
          >
            <div>
              <label style={{ display: "block", fontSize: "13px", fontWeight: 700, marginBottom: "4px" }}>
                نام و نام خانوادگی *
              </label>
              <input
                type="text"
                placeholder="مثلاً: علی اکبر آشوری"
                value={formState.full_name || ""}
                onChange={(e) =>
                  setFormState((p) => ({ ...p, full_name: e.target.value }))
                }
                style={{ width: "100%", padding: "8px 10px", borderRadius: "8px", border: "1px solid #cbd5e1" }}
              />
            </div>
            <div>
              <label style={{ display: "block", fontSize: "13px", fontWeight: 700, marginBottom: "4px" }}>
                نام کاربری (آیدی)
              </label>
              <input
                type="text"
                placeholder="mostafa_1368a"
                value={formState.username || ""}
                onChange={(e) =>
                  setFormState((p) => ({ ...p, username: e.target.value }))
                }
                style={{ width: "100%", padding: "8px 10px", borderRadius: "8px", border: "1px solid #cbd5e1" }}
              />
            </div>
            <div>
              <label style={{ display: "block", fontSize: "13px", fontWeight: 700, marginBottom: "4px" }}>
                آیدی عددی تلگرام
              </label>
              <input
                type="text"
                placeholder="250556017"
                value={formState.telegram_id || ""}
                onChange={(e) =>
                  setFormState((p) => ({ ...p, telegram_id: e.target.value }))
                }
                style={{ width: "100%", padding: "8px 10px", borderRadius: "8px", border: "1px solid #cbd5e1" }}
              />
            </div>
            <div>
              <label style={{ display: "block", fontSize: "13px", fontWeight: 700, marginBottom: "4px" }}>
                کد ملی
              </label>
              <input
                type="text"
                placeholder="890046190"
                value={formState.national_id || ""}
                onChange={(e) =>
                  setFormState((p) => ({ ...p, national_id: e.target.value }))
                }
                style={{ width: "100%", padding: "8px 10px", borderRadius: "8px", border: "1px solid #cbd5e1" }}
              />
            </div>
            <div>
              <label style={{ display: "block", fontSize: "13px", fontWeight: 700, marginBottom: "4px" }}>
                شماره تلفن همراه
              </label>
              <input
                type="text"
                placeholder="989159667187"
                value={formState.phone_number || ""}
                onChange={(e) =>
                  setFormState((p) => ({ ...p, phone_number: e.target.value }))
                }
                style={{ width: "100%", padding: "8px 10px", borderRadius: "8px", border: "1px solid #cbd5e1" }}
              />
            </div>
            <div>
              <label style={{ display: "block", fontSize: "13px", fontWeight: 700, marginBottom: "4px" }}>
                تاریخ تولد
              </label>
              <input
                type="text"
                placeholder="13680622"
                value={formState.birth_date || ""}
                onChange={(e) =>
                  setFormState((p) => ({ ...p, birth_date: e.target.value }))
                }
                style={{ width: "100%", padding: "8px 10px", borderRadius: "8px", border: "1px solid #cbd5e1" }}
              />
            </div>
            <div>
              <label style={{ display: "block", fontSize: "13px", fontWeight: 700, marginBottom: "4px" }}>
                کد پستی
              </label>
              <input
                type="text"
                placeholder="9671998959"
                value={formState.postal_code || ""}
                onChange={(e) =>
                  setFormState((p) => ({ ...p, postal_code: e.target.value }))
                }
                style={{ width: "100%", padding: "8px 10px", borderRadius: "8px", border: "1px solid #cbd5e1" }}
              />
            </div>
            <div>
              <label style={{ display: "block", fontSize: "13px", fontWeight: 700, marginBottom: "4px" }}>
                استان
              </label>
              <input
                type="text"
                value={formState.province || ""}
                onChange={(e) =>
                  setFormState((p) => ({ ...p, province: e.target.value }))
                }
                style={{ width: "100%", padding: "8px 10px", borderRadius: "8px", border: "1px solid #cbd5e1" }}
              />
            </div>
            <div>
              <label style={{ display: "block", fontSize: "13px", fontWeight: 700, marginBottom: "4px" }}>
                شهر
              </label>
              <input
                type="text"
                value={formState.city || ""}
                onChange={(e) =>
                  setFormState((p) => ({ ...p, city: e.target.value }))
                }
                style={{ width: "100%", padding: "8px 10px", borderRadius: "8px", border: "1px solid #cbd5e1" }}
              />
            </div>
            <div>
              <label style={{ display: "block", fontSize: "13px", fontWeight: 700, marginBottom: "4px" }}>
                وضعیت نهایی
              </label>
              <select
                value={formState.final_status || "سیاه"}
                onChange={(e) =>
                  setFormState((p) => ({ ...p, final_status: e.target.value }))
                }
                style={{ width: "100%", padding: "8px 10px", borderRadius: "8px", border: "1px solid #cbd5e1" }}
              >
                <option value="سیاه">سیاه</option>
                <option value="خاکستری">خاکستری</option>
                <option value="سفید">سفید</option>
              </select>
            </div>
          </div>

          <div style={{ marginBottom: "14px" }}>
            <label style={{ display: "block", fontSize: "13px", fontWeight: 700, marginBottom: "4px" }}>
              پیام‌های کاربر (هر خط یک پیام؛ امکان درج به فرمت «تاریخ | نام گروه | متن پیام» جهت استخراج خودکار عناوین اتهامی و شواهد):
            </label>
            <textarea
              rows={5}
              placeholder="2026-06-02 15:23 | وفاداران به ملی گرایان مردم گرا | جاوید شاه"
              value={formState.raw_messages_text || ""}
              onChange={(e) =>
                setFormState((p) => ({
                  ...p,
                  raw_messages_text: e.target.value,
                }))
              }
              style={{
                width: "100%",
                padding: "10px",
                borderRadius: "8px",
                border: "1px solid #cbd5e1",
                fontFamily: "inherit",
              }}
            />
          </div>

          <div style={{ display: "flex", gap: "10px", justifyContent: "flex-end" }}>
            <button
              type="button"
              onClick={() => setShowCreateModal(false)}
              style={{
                padding: "8px 16px",
                borderRadius: "8px",
                border: "1px solid #cbd5e1",
                background: "#f8fafc",
                cursor: "pointer",
                fontWeight: 600,
              }}
            >
              انصراف
            </button>
            <button
              type="submit"
              data-testid="submit-create-user-report-btn"
              style={{
                padding: "8px 20px",
                borderRadius: "8px",
                border: "none",
                background: "#dc2626",
                color: "#ffffff",
                cursor: "pointer",
                fontWeight: 700,
              }}
            >
              ثبت و تولید گزارش ۶ زبانه
            </button>
          </div>
        </form>
      )}

      {/* Main Container matching 890046190_8b7aba55.html */}
      {isLoading && !report ? (
        <div
          style={{
            padding: "48px",
            textAlign: "center",
            background: "#ffffff",
            borderRadius: "20px",
            fontWeight: 700,
            color: "#475569",
          }}
        >
          در حال بارگذاری گزارش جامع کاربر...
        </div>
      ) : report ? (
        <div
          data-testid="user-report-card"
          style={{
            maxWidth: "1400px",
            margin: "0 auto",
            background: "#ffffff",
            borderRadius: "20px",
            boxShadow: "0 20px 60px rgba(0, 0, 0, 0.16)",
            overflow: "hidden",
            border: "1px solid #e2e8f0",
          }}
        >
          {/* Red Gradient Header */}
          <div
            style={{
              background: "linear-gradient(135deg, #dc2626 0%, #b91c1c 100%)",
              color: "#ffffff",
              padding: "36px 40px",
              position: "relative",
              overflow: "hidden",
            }}
          >
            <div style={{ position: "relative", zIndex: 1 }}>
              <h1
                data-testid="user-report-header-title"
                style={{
                  fontSize: "30px",
                  marginBottom: "10px",
                  fontWeight: 700,
                  color: "#ffffff",
                }}
              >
                گزارش کاربر: {report.full_name}
              </h1>
              <p
                data-testid="user-report-header-subtitle"
                style={{
                  fontSize: "16px",
                  opacity: 0.95,
                  color: "#ffffff",
                  margin: 0,
                }}
              >
                آیدی: {report.username || "—"} | آیدی تلگرام:{" "}
                {report.telegram_id || "—"} | استان: {report.province || "—"} |
                وضعیت: {report.final_status || "سیاه"}
              </p>
            </div>
          </div>

          {/* 6 Interactive Tabs */}
          <div
            role="tablist"
            aria-label="بخش‌های گزارش کاربر"
            style={{
              display: "flex",
              background: "linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%)",
              borderBottom: "3px solid #dee2e6",
              overflowX: "auto",
              padding: "0 10px",
            }}
          >
            {(
              [
                { id: "virtual", label: "🌐 دیتای فضای مجازی" },
                { id: "real", label: "👤 دیتای حقیقی" },
                { id: "analysis", label: "🧠 تحلیل شخصیت" },
                {
                  id: "charges",
                  label: `⚖️ عناوین اتهامی (${report.charges.length})`,
                },
                {
                  id: "groups",
                  label: `👥 گروه‌های کاربر (${report.groups.length})`,
                },
                {
                  id: "messages",
                  label: `💬 پیام‌های کاربر (${report.messages.length})`,
                },
              ] as { id: ReportTabId; label: string }[]
            ).map((t) => {
              const isActive = activeTab === t.id;
              return (
                <button
                  key={t.id}
                  type="button"
                  role="tab"
                  aria-selected={isActive}
                  data-testid={`user-report-tab-${t.id}`}
                  onClick={() => setActiveTab(t.id)}
                  style={{
                    flex: "1 1 auto",
                    justifyContent: "center",
                    padding: "16px 14px",
                    cursor: "pointer",
                    border: "none",
                    background: isActive ? "#ffffff" : "transparent",
                    fontSize: "14px",
                    fontWeight: 700,
                    color: isActive ? "#667eea" : "#6c757d",
                    whiteSpace: "nowrap",
                    position: "relative",
                    display: "flex",
                    alignItems: "center",
                    gap: "7px",
                    boxShadow: isActive
                      ? "0 4px 12px rgba(102, 126, 234, 0.2)"
                      : "none",
                    borderBottom: isActive
                      ? "4px solid #667eea"
                      : "4px solid transparent",
                    transition: "all 0.2s ease",
                  }}
                >
                  <span
                    style={{
                      width: "12px",
                      height: "12px",
                      borderRadius: "50%",
                      background:
                        "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
                      opacity: isActive ? 1 : 0.2,
                      display: "inline-block",
                    }}
                  />
                  {t.label}
                </button>
              );
            })}
          </div>

          {/* Tab 1: 🌐 دیتای فضای مجازی */}
          {activeTab === "virtual" && (
            <div
              data-testid="tab-panel-virtual"
              style={{ padding: "30px" }}
            >
              <div style={{ marginBottom: "25px" }}>
                <div
                  style={{
                    fontSize: "20px",
                    fontWeight: 700,
                    color: "#2c3e50",
                    marginBottom: "20px",
                    paddingBottom: "10px",
                    borderBottom: "3px solid #667eea",
                    display: "flex",
                    alignItems: "center",
                    gap: "10px",
                  }}
                >
                  <span
                    style={{
                      width: "5px",
                      height: "25px",
                      background: "#667eea",
                      borderRadius: "3px",
                      display: "inline-block",
                    }}
                  />
                  دیتای فضای مجازی
                </div>

                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))",
                    gap: "20px",
                  }}
                >
                  {report.virtual_data.map((item, idx) => (
                    <div
                      key={idx}
                      style={{
                        background:
                          "linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%)",
                        padding: "20px",
                        borderRadius: "12px",
                        border: "1px solid #dee2e6",
                      }}
                    >
                      <div
                        style={{
                          fontWeight: 700,
                          color: "#495057",
                          marginBottom: "8px",
                          fontSize: "14px",
                        }}
                      >
                        {item.label}
                      </div>
                      <div
                        style={{
                          color: "#212529",
                          fontSize: "15px",
                          fontWeight: 600,
                        }}
                      >
                        {item.value}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Tab 2: 👤 دیتای حقیقی */}
          {activeTab === "real" && (
            <div data-testid="tab-panel-real" style={{ padding: "30px" }}>
              <div style={{ marginBottom: "25px" }}>
                <div
                  style={{
                    fontSize: "20px",
                    fontWeight: 700,
                    color: "#2c3e50",
                    marginBottom: "20px",
                    paddingBottom: "10px",
                    borderBottom: "3px solid #667eea",
                    display: "flex",
                    alignItems: "center",
                    gap: "10px",
                  }}
                >
                  <span
                    style={{
                      width: "5px",
                      height: "25px",
                      background: "#667eea",
                      borderRadius: "3px",
                      display: "inline-block",
                    }}
                  />
                  دیتای حقیقی
                </div>

                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))",
                    gap: "20px",
                  }}
                >
                  {report.real_data.map((item, idx) => (
                    <div
                      key={idx}
                      style={{
                        background:
                          "linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%)",
                        padding: "20px",
                        borderRadius: "12px",
                        border: "1px solid #dee2e6",
                      }}
                    >
                      <div
                        style={{
                          fontWeight: 700,
                          color: "#495057",
                          marginBottom: "8px",
                          fontSize: "14px",
                        }}
                      >
                        {item.label}
                      </div>
                      <div
                        style={{
                          color: "#212529",
                          fontSize: "15px",
                          fontWeight: 600,
                        }}
                      >
                        {item.value}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Tab 3: 🧠 تحلیل شخصیت */}
          {activeTab === "analysis" && (
            <div
              data-testid="tab-panel-analysis"
              style={{ padding: "30px" }}
            >
              <div style={{ marginBottom: "25px" }}>
                <div
                  style={{
                    fontSize: "20px",
                    fontWeight: 700,
                    color: "#2c3e50",
                    marginBottom: "20px",
                    paddingBottom: "10px",
                    borderBottom: "3px solid #667eea",
                    display: "flex",
                    alignItems: "center",
                    gap: "10px",
                  }}
                >
                  <span
                    style={{
                      width: "5px",
                      height: "25px",
                      background: "#667eea",
                      borderRadius: "3px",
                      display: "inline-block",
                    }}
                  />
                  تحلیل شخصیت
                </div>

                {report.personality_analysis.map((sec, idx) => (
                  <div
                    key={idx}
                    style={{
                      background:
                        "linear-gradient(135deg, #e8f4f8 0%, #d1e8f0 100%)",
                      padding: "25px",
                      borderRadius: "15px",
                      marginBottom: "20px",
                      border: "2px solid #b8d4e3",
                    }}
                  >
                    <div
                      style={{
                        color: "#2c5f7c",
                        fontSize: "17px",
                        fontWeight: 700,
                        marginBottom: "12px",
                      }}
                    >
                      {sec.title}
                    </div>
                    <div
                      style={{
                        whiteSpace: "pre-wrap",
                        lineHeight: 1.9,
                        color: "#1a3a4a",
                        fontSize: "15px",
                      }}
                    >
                      {sec.content}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Tab 4: ⚖️ عناوین اتهامی */}
          {activeTab === "charges" && (
            <div
              data-testid="tab-panel-charges"
              style={{ padding: "30px" }}
            >
              <div style={{ marginBottom: "25px" }}>
                <div
                  style={{
                    fontSize: "20px",
                    fontWeight: 700,
                    color: "#2c3e50",
                    marginBottom: "20px",
                    paddingBottom: "10px",
                    borderBottom: "3px solid #667eea",
                    display: "flex",
                    alignItems: "center",
                    gap: "10px",
                  }}
                >
                  <span
                    style={{
                      width: "5px",
                      height: "25px",
                      background: "#667eea",
                      borderRadius: "3px",
                      display: "inline-block",
                    }}
                  />
                  عناوین اتهامی
                </div>

                {report.charges.map((charge, cIdx) => {
                  const evidences = charge.evidences || [];
                  const totalEvPages = Math.max(
                    1,
                    Math.ceil(evidences.length / EVIDENCE_PER_PAGE),
                  );
                  const curEvPage = Math.min(
                    evidencePageByCharge[cIdx] || 1,
                    totalEvPages,
                  );
                  const startIdx = (curEvPage - 1) * EVIDENCE_PER_PAGE;
                  const visibleEvidences = evidences.slice(
                    startIdx,
                    startIdx + EVIDENCE_PER_PAGE,
                  );

                  return (
                    <div
                      key={cIdx}
                      id={`charge-${cIdx}`}
                      data-testid={`charge-section-${cIdx}`}
                      style={{
                        background:
                          "linear-gradient(135deg, #fff5f5 0%, #ffe0e0 100%)",
                        padding: "25px",
                        borderRadius: "15px",
                        marginBottom: "20px",
                        border: "2px solid #ffcccc",
                      }}
                    >
                      <div
                        style={{
                          color: "#dc2626",
                          fontSize: "18px",
                          fontWeight: 700,
                          marginBottom: "8px",
                        }}
                      >
                        {charge.title}
                      </div>
                      <div
                        style={{
                          fontSize: "14px",
                          fontWeight: 600,
                          color: "#7f1d1d",
                          marginBottom: "15px",
                        }}
                      >
                        تعداد شواهد: {charge.count || evidences.length}
                      </div>

                      <div>
                        {visibleEvidences.map((ev, eIdx) => (
                          <div
                            key={eIdx}
                            style={{
                              background: "#ffffff",
                              padding: "15px",
                              borderRadius: "10px",
                              marginBottom: "10px",
                              border: "1px solid #ffcccc",
                            }}
                          >
                            <div
                              style={{
                                fontSize: "12px",
                                color: "#6c757d",
                                marginBottom: "8px",
                                paddingBottom: "8px",
                                borderBottom: "1px solid #fecaca",
                              }}
                            >
                              {ev.meta ||
                                `سند #${ev.doc_id} (offset ${ev.offset}) | تاریخ: ${ev.date} | منبع: ${ev.source}`}
                            </div>
                            <div
                              style={{
                                whiteSpace: "pre-wrap",
                                lineHeight: 1.6,
                                color: "#495057",
                                fontSize: "14px",
                              }}
                            >
                              {ev.content}
                            </div>
                          </div>
                        ))}
                      </div>

                      {evidences.length > EVIDENCE_PER_PAGE && (
                        <div
                          style={{
                            display: "flex",
                            justifyContent: "center",
                            alignItems: "center",
                            gap: "10px",
                            marginTop: "15px",
                            padding: "12px",
                            background: "rgba(255, 204, 204, 0.3)",
                            borderRadius: "10px",
                          }}
                        >
                          <button
                            type="button"
                            disabled={curEvPage === 1}
                            onClick={() =>
                              changeEvidencePage(cIdx, -1, evidences.length)
                            }
                            style={{
                              padding: "6px 14px",
                              border: "2px solid #ffcccc",
                              background: "#ffffff",
                              borderRadius: "8px",
                              cursor:
                                curEvPage === 1 ? "not-allowed" : "pointer",
                              fontWeight: 600,
                              fontSize: "13px",
                              color: "#dc2626",
                              opacity: curEvPage === 1 ? 0.4 : 1,
                            }}
                          >
                            قبلی
                          </button>
                          <span
                            style={{
                              fontWeight: 600,
                              color: "#dc2626",
                              fontSize: "13px",
                            }}
                          >
                            صفحه {curEvPage} از {totalEvPages}
                          </span>
                          <button
                            type="button"
                            disabled={curEvPage === totalEvPages}
                            onClick={() =>
                              changeEvidencePage(cIdx, 1, evidences.length)
                            }
                            style={{
                              padding: "6px 14px",
                              border: "2px solid #ffcccc",
                              background: "#ffffff",
                              borderRadius: "8px",
                              cursor:
                                curEvPage === totalEvPages
                                  ? "not-allowed"
                                  : "pointer",
                              fontWeight: 600,
                              fontSize: "13px",
                              color: "#dc2626",
                              opacity: curEvPage === totalEvPages ? 0.4 : 1,
                            }}
                          >
                            بعدی
                          </button>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Tab 5: 👥 گروه‌های کاربر */}
          {activeTab === "groups" && (
            <div data-testid="tab-panel-groups" style={{ padding: "30px" }}>
              <div style={{ marginBottom: "25px" }}>
                <div
                  style={{
                    fontSize: "20px",
                    fontWeight: 700,
                    color: "#2c3e50",
                    marginBottom: "20px",
                    paddingBottom: "10px",
                    borderBottom: "3px solid #667eea",
                    display: "flex",
                    alignItems: "center",
                    gap: "10px",
                  }}
                >
                  <span
                    style={{
                      width: "5px",
                      height: "25px",
                      background: "#667eea",
                      borderRadius: "3px",
                      display: "inline-block",
                    }}
                  />
                  گروه‌های کاربر
                </div>

                {report.groups.map((grp, gIdx) => (
                  <div
                    key={gIdx}
                    style={{
                      background:
                        "linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%)",
                      padding: "15px 20px",
                      borderRadius: "10px",
                      marginBottom: "10px",
                      border: "1px solid #bae6fd",
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                    }}
                  >
                    <div
                      style={{
                        fontWeight: 600,
                        color: "#0369a1",
                        fontSize: "15px",
                      }}
                    >
                      {grp.name}
                    </div>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "10px",
                      }}
                    >
                      <span
                        style={{
                          background: "#0ea5e9",
                          color: "#ffffff",
                          padding: "5px 12px",
                          borderRadius: "20px",
                          fontSize: "13px",
                          fontWeight: 600,
                        }}
                      >
                        {grp.count_label || `${grp.message_count} پیام`}
                      </span>
                      <button
                        type="button"
                        onClick={() => {
                          setMessageGroupFilter(grp.name);
                          setCurrentMessagePage(1);
                          setActiveTab("messages");
                        }}
                        style={{
                          padding: "5px 10px",
                          borderRadius: "8px",
                          border: "1px solid #0284c7",
                          background: "#ffffff",
                          color: "#0369a1",
                          fontSize: "12px",
                          fontWeight: 600,
                          cursor: "pointer",
                        }}
                      >
                        مشاهدهٔ پیام‌ها
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Tab 6: 💬 پیام‌های کاربر */}
          {activeTab === "messages" && (
            <div
              data-testid="tab-panel-messages"
              style={{ padding: "30px" }}
            >
              <div style={{ marginBottom: "25px" }}>
                <div
                  style={{
                    fontSize: "20px",
                    fontWeight: 700,
                    color: "#2c3e50",
                    marginBottom: "20px",
                    paddingBottom: "10px",
                    borderBottom: "3px solid #667eea",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    flexWrap: "wrap",
                    gap: "12px",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "10px",
                    }}
                  >
                    <span
                      style={{
                        width: "5px",
                        height: "25px",
                        background: "#667eea",
                        borderRadius: "3px",
                        display: "inline-block",
                      }}
                    />
                    پیام‌های کاربر ({filteredMessages.length} پیام)
                  </div>

                  {/* Search & Group Filter inside Messages Tab */}
                  <div
                    style={{
                      display: "flex",
                      gap: "10px",
                      flexWrap: "wrap",
                      alignItems: "center",
                    }}
                  >
                    <input
                      type="text"
                      aria-label="جست‌وجو در متن پیام‌های کاربر"
                      placeholder="جست‌وجو در متن پیام‌ها یا شماره سند..."
                      value={messageSearch}
                      onChange={(e) => {
                        setMessageSearch(e.target.value);
                        setCurrentMessagePage(1);
                      }}
                      style={{
                        padding: "8px 14px",
                        borderRadius: "10px",
                        border: "1px solid #cbd5e1",
                        fontSize: "13px",
                        minWidth: "240px",
                      }}
                    />
                    <select
                      aria-label="فیلتر بر اساس گروه"
                      value={messageGroupFilter}
                      onChange={(e) => {
                        setMessageGroupFilter(e.target.value);
                        setCurrentMessagePage(1);
                      }}
                      style={{
                        padding: "8px 12px",
                        borderRadius: "10px",
                        border: "1px solid #cbd5e1",
                        fontSize: "13px",
                        fontWeight: 600,
                      }}
                    >
                      <option value="همه">همهٔ گروه‌ها</option>
                      {report.groups.map((g, idx) => (
                        <option key={idx} value={g.name}>
                          {g.name} ({g.message_count})
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <div id="messages-container">
                  {paginatedMessages.map((msg, mIdx) => (
                    <div
                      key={mIdx}
                      style={{
                        background: "#f8f9fa",
                        padding: "20px",
                        borderRadius: "12px",
                        marginBottom: "15px",
                        borderRight: "4px solid #667eea",
                      }}
                    >
                      <div
                        style={{
                          fontSize: "13px",
                          color: "#6c757d",
                          marginBottom: "10px",
                          paddingBottom: "10px",
                          borderBottom: "1px solid #dee2e6",
                        }}
                      >
                        {msg.meta ||
                          `تاریخ: ${msg.date} | منبع: ${msg.source} | سند: ${msg.doc_id}`}
                      </div>
                      <div
                        style={{
                          whiteSpace: "pre-wrap",
                          lineHeight: 1.8,
                          color: "#212529",
                          fontSize: "15px",
                        }}
                      >
                        {msg.content}
                      </div>
                    </div>
                  ))}
                </div>

                {/* Messages Pagination matching 890046190_8b7aba55.html */}
                <div
                  style={{
                    display: "flex",
                    justifyContent: "center",
                    alignItems: "center",
                    gap: "15px",
                    marginTop: "25px",
                    padding: "20px",
                    background:
                      "linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%)",
                    borderRadius: "15px",
                    flexWrap: "wrap",
                  }}
                >
                  <button
                    type="button"
                    id="prev-btn"
                    disabled={currentMessagePage <= 1}
                    onClick={() =>
                      setCurrentMessagePage((p) => Math.max(1, p - 1))
                    }
                    style={{
                      padding: "10px 20px",
                      border: "2px solid #dee2e6",
                      background:
                        currentMessagePage <= 1 ? "#e9ecef" : "#ffffff",
                      borderRadius: "10px",
                      cursor:
                        currentMessagePage <= 1 ? "not-allowed" : "pointer",
                      fontWeight: 700,
                      fontSize: "14px",
                      color: "#495057",
                      opacity: currentMessagePage <= 1 ? 0.4 : 1,
                    }}
                  >
                    قبلی
                  </button>

                  <span
                    id="page-info"
                    style={{
                      fontWeight: 700,
                      color: "#495057",
                      fontSize: "15px",
                    }}
                  >
                    صفحه {currentMessagePage} از {totalMessagePages}
                  </span>

                  <button
                    type="button"
                    id="next-btn"
                    disabled={currentMessagePage >= totalMessagePages}
                    onClick={() =>
                      setCurrentMessagePage((p) =>
                        Math.min(totalMessagePages, p + 1),
                      )
                    }
                    style={{
                      padding: "10px 20px",
                      border: "2px solid #dee2e6",
                      background:
                        currentMessagePage >= totalMessagePages
                          ? "#e9ecef"
                          : "#ffffff",
                      borderRadius: "10px",
                      cursor:
                        currentMessagePage >= totalMessagePages
                          ? "not-allowed"
                          : "pointer",
                      fontWeight: 700,
                      fontSize: "14px",
                      color: "#495057",
                      opacity:
                        currentMessagePage >= totalMessagePages ? 0.4 : 1,
                    }}
                  >
                    بعدی
                  </button>

                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "10px",
                    }}
                  >
                    <label
                      htmlFor="items-per-page"
                      style={{
                        fontWeight: 600,
                        color: "#495057",
                        fontSize: "14px",
                      }}
                    >
                      تعداد در صفحه:
                    </label>
                    <select
                      id="items-per-page"
                      value={messagesPerPage}
                      onChange={(e) => {
                        setMessagesPerPage(Number(e.target.value));
                        setCurrentMessagePage(1);
                      }}
                      style={{
                        padding: "8px 15px",
                        border: "2px solid #dee2e6",
                        borderRadius: "8px",
                        background: "#ffffff",
                        fontWeight: 600,
                        fontSize: "14px",
                        cursor: "pointer",
                      }}
                    >
                      <option value={10}>10</option>
                      <option value={20}>20</option>
                      <option value={50}>50</option>
                      <option value={100}>100</option>
                      <option value={200}>200</option>
                    </select>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      ) : (
        <div
          style={{
            padding: "40px",
            textAlign: "center",
            background: "#ffffff",
            borderRadius: "16px",
            border: "1px solid #e2e8f0",
          }}
        >
          هنوز گزارش کاربری ثبت نشده است. از دکمهٔ «بارگذاری فایل گزارش (.html)»
          یا «ثبت / تحلیل گزارش کاربر جدید» استفاده کنید.
        </div>
      )}
    </section>
  );
}
